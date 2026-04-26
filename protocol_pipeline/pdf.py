"""Protocol PDF export.

Renders a `ProtocolGenerationOutput` (plus the originating Hypothesis)
to a single-shot PDF that a researcher can print or attach to a lab
notebook. Pure Python via reportlab — no headless browser, no LaTeX
toolchain.

What's in the PDF (top-to-bottom):
  1. Title (experiment_type, sentence-cased) + domain chip
  2. Hypothesis recap (research_question + structured fields)
  3. Total duration, total steps, procedure count
  4. For each procedure:
       - Heading "Procedure N: {name}"
       - Intent
       - Total duration (when available)
       - Numbered steps with title + body + duration + critical /
         pause-point chips + reagents + equipment + todos
       - Success criteria (bullet list, threshold + how_measured)
       - Deviations from source (with confidence + reason)
  5. Cited protocols (DOI / protocols.io id + contribution weight)
  6. Assumptions (architect-level)
  7. Footer with generation timestamp

The renderer is deterministic given the protocol — same input bytes
produce same PDF bytes (modulo the timestamp footer). All citations
present in the structured data are surfaced so the printed copy is as
auditable as the on-screen view.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.types import Hypothesis, ProtocolGenerationOutput


# --------------------------------------------------------------------------
# Style sheet
# --------------------------------------------------------------------------

def _build_styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "Title", parent=base["Heading1"],
            fontName="Helvetica-Bold", fontSize=20, leading=24,
            spaceAfter=4, textColor=colors.HexColor("#1a1a1a"),
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["BodyText"],
            fontName="Helvetica-Oblique", fontSize=11, leading=14,
            spaceAfter=10, textColor=colors.HexColor("#666666"),
        ),
        "section_heading": ParagraphStyle(
            "Section", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=14, leading=18,
            spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a1a1a"),
        ),
        "procedure_heading": ParagraphStyle(
            "Procedure", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=13, leading=16,
            spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#205080"),
            keepWithNext=1,
        ),
        "procedure_intent": ParagraphStyle(
            "ProcedureIntent", parent=base["BodyText"],
            fontName="Helvetica-Oblique", fontSize=10, leading=13,
            spaceAfter=6, textColor=colors.HexColor("#555555"),
        ),
        "step_heading": ParagraphStyle(
            "StepHeading", parent=base["BodyText"],
            fontName="Helvetica-Bold", fontSize=10.5, leading=13,
            spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#222222"),
            keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"],
            fontName="Helvetica", fontSize=10, leading=13,
            spaceAfter=2, textColor=colors.HexColor("#222222"),
            alignment=TA_LEFT,
        ),
        "meta": ParagraphStyle(
            "Meta", parent=base["BodyText"],
            fontName="Helvetica", fontSize=8.5, leading=11,
            spaceAfter=2, textColor=colors.HexColor("#666666"),
        ),
        "chip_critical": ParagraphStyle(
            "ChipCritical", parent=base["BodyText"],
            fontName="Helvetica-Bold", fontSize=8, leading=10,
            textColor=colors.HexColor("#a32020"),
        ),
        "footer": ParagraphStyle(
            "Footer", parent=base["BodyText"],
            fontName="Helvetica", fontSize=8, leading=10,
            textColor=colors.HexColor("#888888"),
        ),
    }
    return styles


# --------------------------------------------------------------------------
# Reusable formatters
# --------------------------------------------------------------------------

def _esc(s: str | None) -> str:
    """Escape a string for reportlab Paragraph (it parses minimal HTML)."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _humanize_duration(iso: str | None) -> str | None:
    """Light ISO 8601 duration → human string. Returns None for missing or
    unparseable input — callers omit the chip rather than print 'PT?'."""
    if not iso:
        return None
    s = iso.strip()
    if not s.startswith("P"):
        return None
    out: list[str] = []
    body = s[1:]
    # Days component (before T)
    if "T" in body:
        date_part, time_part = body.split("T", 1)
    else:
        date_part, time_part = body, ""
    # date_part can have D / W / M / Y; we only see D in practice
    n = ""
    for ch in date_part:
        if ch.isdigit():
            n += ch
            continue
        if ch == "D" and n:
            out.append(f"{n} d")
            n = ""
        else:
            n = ""
    # time_part: H, M, S
    n = ""
    for ch in time_part:
        if ch.isdigit() or ch == ".":
            n += ch
            continue
        if ch == "H" and n:
            out.append(f"{n} h")
        elif ch == "M" and n:
            out.append(f"{n} min")
        elif ch == "S" and n:
            try:
                secs = float(n)
                if secs.is_integer():
                    out.append(f"{int(secs)} s")
                else:
                    out.append(f"{secs:.0f} s")
            except ValueError:
                pass
        n = ""
    return " ".join(out) if out else None


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------

def render_protocol_pdf(
    protocol: ProtocolGenerationOutput,
    hypothesis: Hypothesis,
) -> bytes:
    """Build a one-shot PDF and return its bytes. Suitable for direct
    Flask `send_file(io.BytesIO(...))` or attachment in another response.

    The PDF is laid out for letter-sized printing; 0.75" margins. Content
    flows naturally — reportlab handles page breaks, but procedure
    headings are kept-with-next so a heading never strands at a page
    bottom."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=protocol.experiment_type or "Protocol",
        author="AI Scientist Assistant",
    )
    styles = _build_styles()
    story: list = []

    # ---- Title block --------------------------------------------------
    title_text = (protocol.experiment_type or "Experimental protocol").strip()
    title_text = title_text[:1].upper() + title_text[1:] if title_text else "Protocol"
    story.append(Paragraph(_esc(title_text), styles["title"]))

    sub_bits: list[str] = []
    if protocol.domain:
        sub_bits.append(_esc(protocol.domain))
    sub_bits.append(f"{protocol.total_steps} steps")
    sub_bits.append(f"{len(protocol.procedures)} procedures")
    dur = _humanize_duration(protocol.total_duration)
    if dur:
        sub_bits.append(f"Total ≈ {dur}")
    story.append(Paragraph(" · ".join(sub_bits), styles["subtitle"]))

    # ---- Hypothesis ---------------------------------------------------
    story.append(Paragraph("Hypothesis", styles["section_heading"]))
    s = hypothesis.structured
    if s.research_question:
        story.append(Paragraph(_esc(s.research_question), styles["body"]))
        story.append(Spacer(1, 4))

    hyp_rows: list[list[str]] = []
    for label, val in [
        ("Subject", s.subject),
        ("Intervention", s.independent),
        ("Measurement", s.dependent),
        ("Conditions", s.conditions),
        ("Expected", s.expected),
    ]:
        if val and val.strip():
            hyp_rows.append([label, val.strip()])
    if hyp_rows:
        t = Table(
            [[Paragraph(f"<b>{r[0]}</b>", styles["body"]),
              Paragraph(_esc(r[1]), styles["body"])] for r in hyp_rows],
            colWidths=[1.2 * inch, 5.55 * inch],
        )
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e0e0e0")),
        ]))
        story.append(t)

    # ---- Procedures ---------------------------------------------------
    story.append(Paragraph("Procedures", styles["section_heading"]))

    for p_idx, proc in enumerate(protocol.procedures, start=1):
        story.append(Paragraph(
            f"Procedure {p_idx}: {_esc(proc.name)}",
            styles["procedure_heading"],
        ))
        if proc.intent:
            story.append(Paragraph(_esc(proc.intent), styles["procedure_intent"]))

        proc_meta: list[str] = []
        pdur = _humanize_duration(proc.total_duration)
        if pdur:
            proc_meta.append(f"≈ {pdur}")
        if proc.source_protocol_ids:
            proc_meta.append("source: " + ", ".join(proc.source_protocol_ids))
        if proc_meta:
            story.append(Paragraph(_esc(" · ".join(proc_meta)), styles["meta"]))

        for s_idx, step in enumerate(proc.steps, start=1):
            head_bits = [f"{p_idx}.{s_idx}", _esc(step.title or "(untitled step)")]
            if step.is_critical:
                head_bits.append('<font color="#a32020"><b>CRITICAL</b></font>')
            if step.is_pause_point:
                head_bits.append('<font color="#666666"><b>PAUSE POINT</b></font>')
            sdur = _humanize_duration(step.duration)
            if sdur:
                head_bits.append(f'<font color="#666">[{sdur}]</font>')
            story.append(Paragraph(" &nbsp; ".join(head_bits), styles["step_heading"]))

            if step.body_md and step.body_md.strip():
                # Treat body_md as plain text — escape and convert newlines
                # to <br/>. We don't run a full Markdown renderer; the
                # writer almost always emits a single paragraph per step.
                body_html = _esc(step.body_md.strip()).replace("\n", "<br/>")
                story.append(Paragraph(body_html, styles["body"]))

            extras: list[str] = []
            if step.equipment_needed:
                extras.append(
                    "Equipment: " + ", ".join(step.equipment_needed)
                )
            if step.reagents_referenced:
                extras.append(
                    "Reagents: " + ", ".join(step.reagents_referenced)
                )
            if step.controls:
                extras.append("Controls: " + ", ".join(step.controls))
            for line in extras:
                story.append(Paragraph(_esc(line), styles["meta"]))

            if step.todo_for_researcher:
                for todo in step.todo_for_researcher:
                    story.append(Paragraph(
                        f"<b>TODO</b> &nbsp; {_esc(todo)}",
                        styles["meta"],
                    ))

            if step.anticipated_outcome:
                story.append(Paragraph(
                    f"<b>Expected outcome.</b> {_esc(step.anticipated_outcome)}",
                    styles["meta"],
                ))

            if step.troubleshooting:
                ts = "; ".join(step.troubleshooting)
                story.append(Paragraph(
                    f"<b>Troubleshooting.</b> {_esc(ts)}",
                    styles["meta"],
                ))

        if proc.success_criteria:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "<b>Success criteria</b>", styles["body"],
            ))
            for c in proc.success_criteria:
                bits = [_esc(c.what)]
                if c.threshold:
                    bits.append(f"[{_esc(c.threshold)}]")
                if c.how_measured:
                    bits.append(f"— {_esc(c.how_measured)}")
                story.append(Paragraph("• " + " ".join(bits), styles["meta"]))

        if proc.deviations_from_source:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "<b>Deviations from source</b>", styles["body"],
            ))
            for d in proc.deviations_from_source:
                line = (
                    f"{_esc(d.from_source)} → {_esc(d.to_adapted)} "
                    f"<font color='#666'>({_esc(d.confidence)} confidence — {_esc(d.reason)})</font>"
                )
                story.append(Paragraph("• " + line, styles["meta"]))

        story.append(Spacer(1, 6))

    # ---- Cited protocols ----------------------------------------------
    if protocol.cited_protocols:
        story.append(Paragraph("Cited protocols", styles["section_heading"]))
        for cp in protocol.cited_protocols:
            ref_bits = [_esc(cp.title)]
            ident: list[str] = []
            if cp.protocols_io_id:
                ident.append(f"protocols.io {_esc(cp.protocols_io_id)}")
            if cp.doi:
                ident.append(f"doi {_esc(cp.doi)}")
            if ident:
                ref_bits.append(f"({' · '.join(ident)})")
            ref_bits.append(f"weight {cp.contribution_weight:.2f}")
            story.append(Paragraph("• " + " ".join(ref_bits), styles["meta"]))

    # ---- Assumptions --------------------------------------------------
    if protocol.assumptions:
        story.append(Paragraph("Assumptions", styles["section_heading"]))
        for i, a in enumerate(protocol.assumptions, start=1):
            story.append(Paragraph(f"A{i}. {_esc(a)}", styles["meta"]))

    # ---- Footer -------------------------------------------------------
    story.append(Spacer(1, 14))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(
        f"Generated {ts} · AI Scientist Assistant",
        styles["footer"],
    ))

    doc.build(story)
    return buf.getvalue()

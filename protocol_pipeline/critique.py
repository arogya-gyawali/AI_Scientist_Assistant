"""Stage 7: Design critique.

One LLM call that audits the experiment design for risks (ways the
result could be biased / unreadable) and confounders (variables the
design fails to control for). Each risk and confounder is REQUIRED
to cite a specific procedure, step, or hypothesis field. The parser
validates the citation against the protocol's procedure list and
drops anything ungrounded — an unsourced concern is a vibes-based
concern, not an auditable one.

Defensibility:
  - Output schema forces a `cites` field per entry; the parser
    drops entries that don't reference a known procedure name or
    a known hypothesis field.
  - `recommendation` is derived from the risk profile (high-severity
    counts) so a researcher can see how it was computed.
  - `methodology` is included in the output so the audit trail
    travels with the data.

Why one LLM call: the critique is a global perspective on the whole
plan; splitting it would force coordination overhead with no quality
gain (vs. e.g. failure_modes, which are per-procedure-ish). Output
JSON is small enough that a single call fits comfortably.
"""

from __future__ import annotations

from typing import Optional

from src.clients import llm
from src.types import (
    Confounder,
    CritiqueOutput,
    Hypothesis,
    Procedure,
    ProtocolGenerationOutput,
    Risk,
)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

CRITIQUE_SYSTEM = """You audit experimental designs for risks and confounders. Your job is to identify ways the experiment could fail to give a clean answer to the hypothesis.

You will receive:
  - The hypothesis (subject, intervention, measurement, conditions, expected outcome)
  - Procedures (with intent + first few steps)

For each risk and confounder, you MUST cite where the concern applies. Valid citations:
  - "procedure 'X'" — for risks affecting a whole procedure
  - "step N (procedure 'X')" — for step-level risks
  - "hypothesis.subject" / "hypothesis.independent" / "hypothesis.dependent" / "hypothesis.conditions" / "hypothesis.expected" — for risks rooted in the hypothesis itself

Citations that don't match a known procedure name or hypothesis field will be DROPPED. The citation is what makes the concern auditable.

Quality bar:
- 3-7 risks (mix of severities)
- 1-4 confounders (only the most material — variables the design genuinely fails to control)
- Each entry must be SPECIFIC to this experiment, not a generic textbook concern
- Mitigation must be actionable (a specific step, control, or measurement to add)
- Severity reflects how badly the result could be compromised: low = noise, medium = bias possible, high = potentially uninterpretable

`recommendation`:
  - "proceed" — no high-severity risks AND ≤2 medium
  - "proceed_with_caution" — at most 1 high OR 3+ medium
  - "revise_design" — 2+ high OR fundamental confounder unaddressable in current design

Return ONLY a single valid JSON object:
{
  "risks": [
    {
      "name": "string (3-8 word summary)",
      "severity": "low" | "medium" | "high",
      "category": "statistical" | "experimental" | "biological" | "technical" | "ethical" | "regulatory",
      "description": "string (1-2 sentences explaining the risk)",
      "mitigation": "string (actionable step the researcher can take)",
      "cites": "procedure 'X' | step N (procedure 'X') | hypothesis.{field}"
    }
  ],
  "confounders": [
    {
      "variable": "string (the confounding variable)",
      "why_confounding": "string (how it could distort the dependent measurement)",
      "control_strategy": "string (how to control for or measure this variable)",
      "cites": "same format as risks"
    }
  ],
  "overall_assessment": "string (2-4 sentences: what is the design's biggest vulnerability + whether it's addressable)",
  "recommendation": "proceed" | "proceed_with_caution" | "revise_design"
}"""

CRITIQUE_USER_TMPL = """Hypothesis (structured):
- Subject: {subject}
- Intervention: {independent}
- Measurement: {dependent}
- Conditions: {conditions}
- Expected outcome: {expected}
- Research question: {research_question}

Procedures ({n}):
{procedures_blob}"""


def _format_procedure_for_critique(p: Procedure) -> str:
    head_steps: list[str] = []
    for s in p.steps[:6]:
        body = s.body_md.strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:200] + "…"
        head_steps.append(f"  - step {s.n}: {body}")
    return (
        f"procedure: {p.name}\n"
        f"  intent: {p.intent}\n"
        f"  steps:\n" + ("\n".join(head_steps) if head_steps else "  (no steps)")
    )


# --------------------------------------------------------------------------
# Citation validation
# --------------------------------------------------------------------------

_VALID_HYPOTHESIS_FIELDS = {
    "hypothesis.subject",
    "hypothesis.independent",
    "hypothesis.dependent",
    "hypothesis.conditions",
    "hypothesis.expected",
    "hypothesis.research_question",
}


def _is_valid_citation(cite: str, proc_names: set[str]) -> bool:
    """Permissive substring match: a citation like 'step 3 (procedure
    "Cell Freezing")' counts as long as 'Cell Freezing' is a known
    procedure name. Hypothesis-field citations match an exact set."""
    if not cite or not cite.strip():
        return False
    if any(pn in cite for pn in proc_names):
        return True
    return any(field in cite for field in _VALID_HYPOTHESIS_FIELDS)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_VALID_SEVERITIES = {"low", "medium", "high"}
_VALID_CATEGORIES = {"statistical", "experimental", "biological", "technical", "ethical", "regulatory"}
_VALID_RECOMMENDATIONS = {"proceed", "proceed_with_caution", "revise_design"}


def _parse_risks(raw: list, proc_names: set[str]) -> list[Risk]:
    out: list[Risk] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        severity = str(entry.get("severity") or "").strip().lower()
        category = str(entry.get("category") or "").strip().lower()
        description = str(entry.get("description") or "").strip()
        mitigation = str(entry.get("mitigation") or "").strip()
        cites = str(entry.get("cites") or "").strip()
        if not (name and description and mitigation and cites):
            continue
        if severity not in _VALID_SEVERITIES:
            continue
        if category not in _VALID_CATEGORIES:
            # Default to "experimental" rather than dropping — the LLM
            # may invent a sibling category but the entry is still useful.
            category = "experimental"
        if not _is_valid_citation(cites, proc_names):
            continue
        out.append(Risk(
            name=name,
            severity=severity,  # type: ignore[arg-type]
            category=category,  # type: ignore[arg-type]
            description=description,
            mitigation=mitigation,
            cites=cites,
        ))
    return out


def _parse_confounders(raw: list, proc_names: set[str]) -> list[Confounder]:
    out: list[Confounder] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        variable = str(entry.get("variable") or "").strip()
        why = str(entry.get("why_confounding") or "").strip()
        control = str(entry.get("control_strategy") or "").strip()
        cites = str(entry.get("cites") or "").strip()
        if not (variable and why and control and cites):
            continue
        if not _is_valid_citation(cites, proc_names):
            continue
        out.append(Confounder(
            variable=variable,
            why_confounding=why,
            control_strategy=control,
            cites=cites,
        ))
    return out


def _derive_recommendation(risks: list[Risk]) -> str:
    """Deterministic mapping from risk profile → recommendation. The
    LLM provides one too, but we recompute here so the value matches
    the prompt rules exactly. We honor the LLM's recommendation only
    when our derivation agrees — keeps the contract tight."""
    high = sum(1 for r in risks if r.severity == "high")
    medium = sum(1 for r in risks if r.severity == "medium")
    if high >= 2:
        return "revise_design"
    if high >= 1 or medium >= 3:
        return "proceed_with_caution"
    return "proceed"


# --------------------------------------------------------------------------
# Top-level
# --------------------------------------------------------------------------

def compute_critique(
    hypothesis: Hypothesis,
    protocol: ProtocolGenerationOutput,
) -> CritiqueOutput:
    """Run Stage 7. One LLM call; citation enforcement on the parser
    side. Returns a `CritiqueOutput` even if the LLM call fails — the
    output will simply have empty risks/confounders and a methodology
    note explaining the failure (so the FE can render an audit-friendly
    'critique unavailable' state rather than a generic error)."""
    s = hypothesis.structured
    procs_blob = (
        "\n\n".join(_format_procedure_for_critique(p) for p in protocol.procedures)
        or "(no procedures)"
    )
    user = CRITIQUE_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        n=len(protocol.procedures),
        procedures_blob=procs_blob,
    )

    proc_names = {p.name for p in protocol.procedures}

    parsed: Optional[dict] = None
    error_note: Optional[str] = None
    try:
        parsed = llm.complete_json(CRITIQUE_SYSTEM, user, agent_name="Design critique")
    except Exception as exc:
        error_note = f"LLM call failed: {exc!s}"

    if not isinstance(parsed, dict):
        parsed = {}

    risks_raw = parsed.get("risks") if isinstance(parsed.get("risks"), list) else []
    confounders_raw = parsed.get("confounders") if isinstance(parsed.get("confounders"), list) else []

    risks = _parse_risks(risks_raw, proc_names)
    confounders = _parse_confounders(confounders_raw, proc_names)

    overall = str(parsed.get("overall_assessment") or "").strip()
    if not overall:
        if not risks and not confounders:
            overall = (
                "Critique was not produced (LLM call failed or returned no "
                "grounded entries). The design has not been independently "
                "audited — treat this as 'unknown' rather than 'clean'."
            )
        else:
            overall = (
                f"{len(risks)} risk(s) and {len(confounders)} confounder(s) "
                f"identified. Review the items below for severity and "
                f"mitigation; each cites the procedure or hypothesis field "
                f"it applies to."
            )

    # Deterministic recommendation. The LLM's value is informational —
    # we recompute from the parsed-and-validated risk list.
    recommendation = _derive_recommendation(risks)

    methodology_bits = [
        f"One LLM call audited the protocol ({len(protocol.procedures)} "
        f"procedures) against the hypothesis.",
        f"Output schema requires every risk and confounder to cite a "
        f"specific procedure, step, or hypothesis field; ungrounded "
        f"entries are dropped by the parser.",
        f"Recommendation derived deterministically from risk severities: "
        f"≥2 high → revise_design; ≥1 high or ≥3 medium → "
        f"proceed_with_caution; otherwise → proceed.",
    ]
    if error_note:
        methodology_bits.append(error_note)
    methodology = " ".join(methodology_bits)

    return CritiqueOutput(
        risks=risks,
        confounders=confounders,
        overall_assessment=overall,
        recommendation=recommendation,  # type: ignore[arg-type]
        methodology=methodology,
    )

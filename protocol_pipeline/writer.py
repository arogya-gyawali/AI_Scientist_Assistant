"""Procedure writer agent.

One LLM call PER procedure, run in parallel via ThreadPoolExecutor. Each
writer sees ONLY its own ProcedureOutline plus the source protocols cited
for that procedure — context isolation by construction.

Output per writer: a fully-fleshed Procedure with steps, equipment names,
reagent names, deviations_from_source (audit trail of every adaptation),
and procedure-level success criteria.

Why parallel: writers are independent by design (each owns one procedure)
and the wall-clock dominates run time when N is 4-8. ThreadPoolExecutor
is fine here because llm.complete() is I/O-bound (HTTP call); the GIL
isn't the bottleneck.

Why "TODO_for_researcher" markers: the LLM must surface known unknowns
rather than fabricate them. The PDF's quality bar is "would a real
scientist trust this enough to order materials"; emitting an explicit
TODO is honest about gaps and lets the chat-revise agent (or the
researcher) fill them in later.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from src.clients import llm
from src.types import (
    Deviation,
    Hypothesis,
    Procedure,
    ProcedureSuccessCriterion,
    ProtocolStep,
    Quantity,
    StepParams,
)

from .architect import ProcedureOutline
from .sources import NormalizedProtocol


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

WRITER_SYSTEM = """You are a senior research scientist writing the detailed steps for ONE procedure within a larger experiment plan. Other procedures are being written by other agents — focus only on yours.

You receive:
- The overall hypothesis (so you understand the experiment context).
- ONE procedure outline: name, intent, key_params, and which source protocols inform it.
- The full text of those source protocols (steps, in their original language). You may need to translate inline.

Your job:
- Write 4-15 detailed steps for this procedure.
- Each step must be concrete enough that a competent researcher can execute it without further research. Volumes, temperatures, durations, concentrations, speeds — be specific.
- Where the hypothesis specifies different organism/conditions/intervention than the source protocol, ADAPT the steps and emit a Deviation entry explaining what you changed and why. The researcher MUST be able to audit every adaptation.
- Where you genuinely don't know (no source covers it, common-knowledge has multiple valid options), emit a TODO_for_researcher marker on that step rather than inventing details.
- Emit per-step structured params (volume, temperature, duration, concentration, speed) when applicable. Use ISO 8601 duration strings (PT5M, PT1H30M, PT24H).
- Emit per-procedure success_criteria: how does the researcher know this procedure WORKED before moving to the next one?

Quality bar: would a real PI look at these steps and say "yes, I could order the materials and start running this on Monday"?

Hard rules:
- Step numbers start at 1 within this procedure.
- Each Deviation MUST cite a specific source_protocol_id (one you were given).
- Do NOT include steps that belong to other procedures (cell prep, downstream analysis, etc. are someone else's job unless your outline says otherwise).
- If a source step is in non-English, translate inline — do NOT leave foreign-language text in the body_md.

Return ONLY a single valid JSON object:
{
  "steps": [
    {
      "n": 1,
      "title": "string (short imperative title)",
      "body_md": "string (one-paragraph instruction; markdown-OK but plain prose preferred)",
      "duration": "ISO 8601 string or null",
      "equipment_needed": ["string"],
      "reagents_referenced": ["string"],
      "params": {
        "volume": {"value": 0, "unit": "string"} or null,
        "temperature": {"value": 0, "unit": "string"} or null,
        "duration": "ISO 8601 string or null",
        "concentration": {"value": 0, "unit": "string"} or null,
        "speed": {"value": 0, "unit": "string"} or null,
        "other": {"string": "string"}
      },
      "controls": ["string"],
      "todo_for_researcher": ["string"],
      "source_step_refs": ["string (protocols.io step ids that informed this step)"],
      "notes": "string or null"
    }
  ],
  "equipment": ["string"],
  "reagents": ["string"],
  "deviations_from_source": [
    {
      "from_source": "string",
      "to_adapted": "string",
      "reason": "string",
      "source_protocol_id": "string",
      "confidence": "low" | "medium" | "high"
    }
  ],
  "success_criteria": [
    {
      "what": "string",
      "how_measured": "string",
      "threshold": "string or null",
      "pass_fail": true
    }
  ]
}"""

WRITER_USER_TMPL = """Hypothesis (structured):
- Subject: {subject}
- Intervention: {independent}
- Measurement: {dependent}
- Conditions: {conditions}
- Expected outcome: {expected}
- Research question: {research_question}

THIS procedure (you are writing this one only):
- Name: {name}
- Intent: {intent}
- Key params: {key_params}
- Cited source protocol ids: {source_ids}

Source protocols ({n_sources}):
{sources}"""


def _format_source(p: NormalizedProtocol) -> str:
    step_lines = []
    for s in p.steps:
        body = s.text.strip().replace("\n", " ")
        if len(body) > 600:
            body = body[:600] + "…"
        section = f" [{s.section}]" if s.section else ""
        step_lines.append(f"  step_id={s.id}{section} num={s.number}: {body}")
    materials_blob = ""
    if p.materials_text:
        mt = p.materials_text.strip()
        if len(mt) > 1000:
            mt = mt[:1000] + "…"
        materials_blob = f"\nmaterials_text:\n{mt}"
    return (
        f"protocol_id: {p.id}\n"
        f"title: {p.title}\n"
        f"language: {p.language}\n"
        f"steps:\n" + ("\n".join(step_lines) if step_lines else "  (none)")
        + materials_blob
    )


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

def write_procedure(
    hypothesis: Hypothesis,
    outline: ProcedureOutline,
    sources_by_id: dict[str, NormalizedProtocol],
) -> Procedure:
    """Write ONE procedure. Synchronous; the parallel orchestrator wraps this."""
    s = hypothesis.structured

    # Filter sources to only the ones the architect cited for this procedure.
    relevant_sources = [
        sources_by_id[pid] for pid in outline.source_protocol_ids
        if pid in sources_by_id
    ]
    sources_blob = "\n\n".join(_format_source(p) for p in relevant_sources) \
        or "(no sources cited for this procedure — synthesize from common scientific knowledge)"

    user = WRITER_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        name=outline.name,
        intent=outline.intent,
        key_params=json.dumps(outline.key_params, ensure_ascii=False),
        source_ids=outline.source_protocol_ids or "(none)",
        n_sources=len(relevant_sources),
        sources=sources_blob,
    )

    parsed = llm.complete_json(WRITER_SYSTEM, user, agent_name="Procedure writer")

    steps = _build_steps(parsed.get("steps") or [], known_source_ids={
        s.id for p in relevant_sources for s in p.steps
    })
    deviations = _build_deviations(
        parsed.get("deviations_from_source") or [],
        known_protocol_ids=set(outline.source_protocol_ids),
    )
    success = _build_success_criteria(parsed.get("success_criteria") or [])

    return Procedure(
        name=outline.name,
        intent=outline.intent,
        steps=steps,
        equipment=[str(x) for x in (parsed.get("equipment") or [])],
        reagents=[str(x) for x in (parsed.get("reagents") or [])],
        deviations_from_source=deviations,
        source_protocol_ids=list(outline.source_protocol_ids),
        success_criteria=success,
    )


def write_procedures_parallel(
    hypothesis: Hypothesis,
    outlines: list[ProcedureOutline],
    sources_by_id: dict[str, NormalizedProtocol],
    *,
    max_workers: int = 5,
) -> list[Procedure]:
    """Fan out one writer agent per procedure; preserve outline order on return.

    max_workers caps concurrent LLM calls so we don't hit rate limits when
    a hypothesis produces 8 procedures. 5 is a safe default for OpenRouter
    free tiers; raise to 8+ if you have headroom."""
    if not outlines:
        return []
    workers = min(max_workers, len(outlines))
    out: dict[int, Procedure] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(write_procedure, hypothesis, o, sources_by_id): i
            for i, o in enumerate(outlines)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            out[i] = fut.result()
    return [out[i] for i in range(len(outlines))]


# --------------------------------------------------------------------------
# JSON → Pydantic with hallucination defenses
# --------------------------------------------------------------------------

def _coerce_quantity(raw) -> Quantity | None:
    """Accept {value, unit} dict; return None for missing / malformed."""
    if not isinstance(raw, dict):
        return None
    val = raw.get("value")
    unit = raw.get("unit")
    if val is None or unit is None:
        return None
    try:
        return Quantity(value=float(val), unit=str(unit))
    except (TypeError, ValueError):
        return None


def _coerce_params(raw) -> StepParams:
    if not isinstance(raw, dict):
        return StepParams()
    # `other` may be missing, None, or (rarely) a non-dict if the LLM
    # mistypes the field. One isinstance check covers all three.
    other_raw = raw.get("other")
    other = other_raw if isinstance(other_raw, dict) else {}
    duration = raw.get("duration")
    return StepParams(
        volume=_coerce_quantity(raw.get("volume")),
        temperature=_coerce_quantity(raw.get("temperature")),
        duration=str(duration) if duration else None,
        concentration=_coerce_quantity(raw.get("concentration")),
        speed=_coerce_quantity(raw.get("speed")),
        other={str(k): str(v) for k, v in other.items()},
    )


def _build_steps(raw_steps: Iterable, *, known_source_ids: set[str]) -> list[ProtocolStep]:
    steps: list[ProtocolStep] = []
    for i, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            continue
        # Drop hallucinated source_step_refs that aren't in any provided source.
        # Empty known_source_ids means the writer had no sources — accept whatever
        # refs they emit (most likely empty list anyway).
        refs = [str(x) for x in (raw.get("source_step_refs") or [])]
        if known_source_ids:
            refs = [r for r in refs if r in known_source_ids]
        n_raw = raw.get("n")
        duration = raw.get("duration")
        notes = raw.get("notes")
        steps.append(ProtocolStep(
            n=n_raw if isinstance(n_raw, int) else i,
            title=str(raw.get("title") or f"Step {i}"),
            body_md=str(raw.get("body_md") or ""),
            duration=str(duration) if duration else None,
            equipment_needed=[str(x) for x in (raw.get("equipment_needed") or [])],
            reagents_referenced=[str(x) for x in (raw.get("reagents_referenced") or [])],
            params=_coerce_params(raw.get("params")),
            controls=[str(x) for x in (raw.get("controls") or [])],
            todo_for_researcher=[str(x) for x in (raw.get("todo_for_researcher") or [])],
            source_step_refs=refs,
            notes=str(notes) if notes else None,
        ))
    return steps


def _build_deviations(raw_devs: Iterable, *, known_protocol_ids: set[str]) -> list[Deviation]:
    out: list[Deviation] = []
    for raw in raw_devs:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("source_protocol_id") or "")
        # Drop hallucinated protocol IDs.
        if known_protocol_ids and pid not in known_protocol_ids:
            continue
        conf = raw.get("confidence")
        if conf not in ("low", "medium", "high"):
            conf = "medium"
        out.append(Deviation(
            from_source=str(raw.get("from_source") or ""),
            to_adapted=str(raw.get("to_adapted") or ""),
            reason=str(raw.get("reason") or ""),
            source_protocol_id=pid,
            confidence=conf,
        ))
    return out


def _build_success_criteria(raw_sc: Iterable) -> list[ProcedureSuccessCriterion]:
    out: list[ProcedureSuccessCriterion] = []
    for raw in raw_sc:
        if not isinstance(raw, dict):
            continue
        threshold = raw.get("threshold")
        out.append(ProcedureSuccessCriterion(
            what=str(raw.get("what") or ""),
            how_measured=str(raw.get("how_measured") or ""),
            threshold=str(threshold) if threshold else None,
            pass_fail=bool(raw.get("pass_fail", True)),
        ))
    return out

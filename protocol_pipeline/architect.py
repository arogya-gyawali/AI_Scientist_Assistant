"""Architect agent.

Single LLM call. Input: hypothesis + relevance-filtered source protocols.
Output: an ordered ProtocolOutline = a list of 3-8 named procedures, each
with intent, key params, and which source protocols inform it.

The outline is the *plan*, not the protocol itself. Each procedure becomes
the unit of work for one downstream procedure-writer agent (which sees only
its outline node + its sources). That fan-out is what defends against
context drift on long protocols — instead of one giant prompt, each writer
has a tight, focused context.

Why this is its own pass:
  Asking the LLM to plan AND write at once produces uneven results: it
  over-commits to the first procedure (lots of detail) and runs out of
  steam on the last one. Splitting plan from write gives each procedure
  the same care, regardless of position in the protocol.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.clients import llm
from src.types import Hypothesis

from .relevance import ScoredProtocol


# --------------------------------------------------------------------------
# Output shape (transient — not persisted to the blackboard directly)
# --------------------------------------------------------------------------

class ProcedureOutline(BaseModel):
    name: str
    intent: str                                  # 1-sentence purpose
    key_params: dict[str, str] = Field(default_factory=dict)
    source_protocol_ids: list[str] = Field(default_factory=list)


class ProtocolOutline(BaseModel):
    experiment_type: str
    domain: Optional[str] = None
    procedures: list[ProcedureOutline]
    overall_assumptions: list[str] = Field(default_factory=list)
    overall_controls: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

ARCHITECT_SYSTEM = """You are a senior research scientist designing the high-level structure of an experiment plan.

You receive:
- A structured scientific hypothesis.
- A short list of relevance-filtered source protocols from protocols.io. Each has a relevance score, a one-line reason, and the first few step bodies. Some sources may be in non-English languages; treat them as informational regardless of language.

Your job is to plan the experiment as 3-8 named procedures (NOT individual steps). Each procedure should be a coherent block of work a single researcher could execute end-to-end (~5-15 steps each). Subsequent agents will write the detailed steps for each procedure independently.

Quality bar: would a real PI look at this outline and say "yes, that's the right shape for this experiment"? The outline is the skeleton. If you misshape it, every downstream step inherits the bad scaffold.

For each procedure, emit:
- name              (short title, e.g. "Cell preparation")
- intent            (one sentence: what this procedure accomplishes)
- key_params        (a dict of parameter hints the writer will need, e.g. {"cell_density": "10^6 cells/mL", "passage_number": "passages 5-15"}. Empty dict if none.)
- source_protocol_ids (subset of the input protocol_ids that meaningfully inform this procedure. Empty list if no source applies — the writer will synthesize from common knowledge.)

Also emit at the top level:
- experiment_type   (e.g., "cryopreservation comparison", "ELISA assay validation", "in vivo gut barrier study")
- domain            (e.g., "cell_biology", "diagnostics", "gut_health")
- overall_assumptions (cross-cutting assumptions every procedure inherits — institutional regs, standard equipment availability, etc.)
- overall_controls    (experimental controls: positive/negative/sham/vehicle. Procedure-level success criteria are added by the writer agents.)

Hard rules:
- 3-8 procedures total. Fewer is better if the experiment is genuinely simple.
- Procedures must appear in execution order.
- Do NOT write step bodies — that's the next agent's job.
- source_protocol_ids must be a subset of the protocol_ids in the input.

Return ONLY a single valid JSON object:
{
  "experiment_type": "string",
  "domain": "string",
  "procedures": [
    {
      "name": "string",
      "intent": "string",
      "key_params": {"string": "string"},
      "source_protocol_ids": ["string"]
    }
  ],
  "overall_assumptions": ["string"],
  "overall_controls": ["string"]
}"""

ARCHITECT_USER_TMPL = """Hypothesis (structured):
- Subject: {subject}
- Intervention (independent variable): {independent}
- Measurement (dependent variable): {dependent}
- Conditions: {conditions}
- Expected outcome: {expected}
- Research question: {research_question}

Source protocols ({n}, sorted by relevance):
{sources}"""


def _format_source(sp: ScoredProtocol, *, max_steps: int = 6, max_step_chars: int = 220) -> str:
    p = sp.protocol
    head = []
    for s in p.steps[:max_steps]:
        body = s.text.strip().replace("\n", " ")
        if len(body) > max_step_chars:
            body = body[:max_step_chars] + "…"
        head.append(f"  - [{s.id}] {body}")
    return (
        f"protocol_id: {p.id}\n"
        f"title: {p.title}\n"
        f"language: {p.language}\n"
        f"relevance_score: {sp.score.score:.2f}\n"
        f"relevance_reason: {sp.score.reason}\n"
        f"first_steps:\n" + ("\n".join(head) if head else "  (none)")
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def plan_outline(
    hypothesis: Hypothesis,
    scored: list[ScoredProtocol],
) -> ProtocolOutline:
    """Single LLM call returning a structured ProtocolOutline."""
    s = hypothesis.structured
    sources_blob = "\n\n".join(_format_source(sp) for sp in scored) or "(no source protocols available)"
    user = ARCHITECT_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        n=len(scored),
        sources=sources_blob,
    )

    parsed = llm.complete_json(ARCHITECT_SYSTEM, user, agent_name="Architect")
    known_ids = {sp.protocol.id for sp in scored}

    procs: list[ProcedureOutline] = []
    for raw in parsed.get("procedures") or []:
        if not isinstance(raw, dict):
            continue
        # Validate source_protocol_ids subset (drop hallucinated IDs).
        src_ids = [
            str(x) for x in (raw.get("source_protocol_ids") or [])
            if str(x) in known_ids
        ]
        kp = raw.get("key_params") or {}
        if not isinstance(kp, dict):
            kp = {}
        # Coerce non-string values to strings (LLM sometimes returns numbers).
        kp = {str(k): str(v) for k, v in kp.items()}
        procs.append(ProcedureOutline(
            name=str(raw.get("name") or "Unnamed procedure"),
            intent=str(raw.get("intent") or ""),
            key_params=kp,
            source_protocol_ids=src_ids,
        ))

    if not procs:
        raise RuntimeError(
            "Architect returned no procedures. The LLM output was structurally "
            "empty — try a different LLM_PROVIDER, or check the input hypothesis."
        )

    return ProtocolOutline(
        experiment_type=str(parsed.get("experiment_type") or "experiment"),
        domain=parsed.get("domain") or hypothesis.domain,
        procedures=procs,
        overall_assumptions=[str(x) for x in (parsed.get("overall_assumptions") or [])],
        overall_controls=[str(x) for x in (parsed.get("overall_controls") or [])],
    )

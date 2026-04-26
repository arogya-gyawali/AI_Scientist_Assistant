"""Relevance filter agent.

Single batched LLM call: given a hypothesis and N normalized source
protocols, score each 0-1 against the hypothesis with a one-sentence
reason, then drop anything below `keep_threshold`.

Why batched (vs. N parallel calls):
  N is small (<=8 typical, 5 by default), the prompt is short, and
  scoring is *relative* — sending all candidates in one call lets the
  LLM compare them against each other instead of grading in isolation.
  That produces more consistent scores than independent passes.

Why a low default threshold (0.2):
  protocols.io has thin coverage in many areas. The trehalose top hit
  is C. elegans cryopreservation when the hypothesis is HeLa cells —
  imperfect but the only protocol with relevant *technique*. We keep
  weakly-relevant sources and lean on `contribution_weight` downstream
  to encode partial relevance, rather than throwing them away.
"""

from __future__ import annotations

from typing import NamedTuple

from src.clients import llm
from src.types import Hypothesis

from .sources import NormalizedProtocol


# --------------------------------------------------------------------------
# Output shape
# --------------------------------------------------------------------------

class RelevanceScore(NamedTuple):
    protocol_id: str
    score: float          # 0.0 - 1.0
    reason: str           # one-line explanation; surfaces in audit / FE


class ScoredProtocol(NamedTuple):
    protocol: NormalizedProtocol
    score: RelevanceScore


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

RELEVANCE_SYSTEM = """You score how useful each protocols.io source is for answering a specific scientific hypothesis.

You will receive:
- A structured hypothesis (subject, intervention, measurement, conditions, expected outcome).
- A numbered list of source protocols pulled from protocols.io. Each has a title, optional description, language tag, and the first few step bodies. Some may be in non-English languages — score them anyway; we will translate downstream.

For each source, emit:
- protocol_id (string; copy verbatim from the input)
- score       (float 0.0-1.0; how much of the hypothesis this protocol can usefully inform)
- reason      (one short sentence; what overlaps and what doesn't)

Scoring rubric:
- 0.8-1.0: same subject, same intervention, same measurement → near-direct precedent
- 0.5-0.8: same technique class but different organism/system, or same subject but different intervention
- 0.2-0.5: only the broad technique transfers (e.g., a cryopreservation protocol on a different cell line for a cryopreservation hypothesis)
- 0.0-0.2: subject and technique both off-target — protocol won't usefully inform the experiment

Be strict on the rubric. Do NOT invent overlap that isn't in the source.

Return ONLY a single valid JSON object:
{
  "scores": [
    { "protocol_id": "string", "score": 0.0, "reason": "string" }
  ]
}"""

RELEVANCE_USER_TMPL = """Hypothesis (structured):
- Subject: {subject}
- Intervention (independent variable): {independent}
- Measurement (dependent variable): {dependent}
- Conditions: {conditions}
- Expected outcome: {expected}
- Research question: {research_question}

Source protocols ({n}):
{sources}"""


def _format_source(p: NormalizedProtocol, *, max_steps: int = 5, max_step_chars: int = 250) -> str:
    head_steps = []
    for s in p.steps[:max_steps]:
        body = s.text.strip()
        if len(body) > max_step_chars:
            body = body[:max_step_chars] + "…"
        head_steps.append(f"  - [{s.id}] {body}")
    desc = (p.description or "").strip()
    if len(desc) > 400:
        desc = desc[:400] + "…"
    return (
        f"protocol_id: {p.id}\n"
        f"title: {p.title}\n"
        f"language: {p.language}\n"
        f"description: {desc or '(none)'}\n"
        f"first_steps:\n" + ("\n".join(head_steps) if head_steps else "  (none)")
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def score_protocols(
    hypothesis: Hypothesis,
    protocols: list[NormalizedProtocol],
) -> list[ScoredProtocol]:
    """Score every protocol; do NOT filter. Caller decides the threshold."""
    if not protocols:
        return []

    s = hypothesis.structured
    sources_blob = "\n\n".join(
        f"[{i}]\n{_format_source(p)}" for i, p in enumerate(protocols)
    )
    user = RELEVANCE_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        n=len(protocols),
        sources=sources_blob,
    )

    parsed = llm.complete_json(RELEVANCE_SYSTEM, user, agent_name="Relevance filter")
    scores_by_id = _index_scores(parsed.get("scores") or [], known_ids={p.id for p in protocols})

    out: list[ScoredProtocol] = []
    for p in protocols:
        s_obj = scores_by_id.get(p.id)
        if s_obj is None:
            # LLM dropped this protocol from the response. Default to a
            # mid-low score with an explicit "missing" reason rather than
            # silently treating it as 0 — the orchestrator can decide.
            s_obj = RelevanceScore(protocol_id=p.id, score=0.3,
                                    reason="LLM did not score this protocol; default mid-low.")
        out.append(ScoredProtocol(protocol=p, score=s_obj))
    return out


def filter_relevant(
    hypothesis: Hypothesis,
    protocols: list[NormalizedProtocol],
    *,
    keep_threshold: float = 0.2,
) -> list[ScoredProtocol]:
    """Score every protocol and return those at or above keep_threshold,
    sorted by score descending. Default threshold is intentionally low —
    protocols.io coverage is thin, so we keep weakly-relevant sources and
    rely on downstream contribution_weight to encode partial relevance."""
    scored = score_protocols(hypothesis, protocols)
    kept = [sp for sp in scored if sp.score.score >= keep_threshold]
    kept.sort(key=lambda sp: sp.score.score, reverse=True)
    return kept


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------

def _index_scores(raw_scores: list, *, known_ids: set[str]) -> dict[str, RelevanceScore]:
    """Coerce LLM output into RelevanceScore objects, dropping anything that
    references a protocol_id we didn't send (LLM hallucination defense)."""
    out: dict[str, RelevanceScore] = {}
    for r in raw_scores:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("protocol_id") or "").strip()
        if not pid or pid not in known_ids:
            continue
        try:
            score = float(r.get("score"))
        except (TypeError, ValueError):
            continue
        score = max(0.0, min(1.0, score))  # clamp
        reason = str(r.get("reason") or "").strip() or "(no reason given)"
        out[pid] = RelevanceScore(protocol_id=pid, score=score, reason=reason)
    return out

"""Stage 1: Lit Review.

Reads:  hypothesis
Writes: lit_review

Flow:
  1. Rewrite the structured hypothesis into a precise scientific search query (LLM)
  2. Tavily search (no `days` filter — foundational papers should surface)
  3. LLM classifies novelty + selects 1-3 references, sorted by relevance then
     recency, each with a neutral description, matched-on chips, and a relational
     "why this matched" importance
  4. Build a LitReviewSession and write to ExperimentPlan.lit_review
"""

from __future__ import annotations

import json
import uuid

from src.clients import llm, tavily
from src.types import (
    Citation,
    ExperimentPlan,
    Hypothesis,
    LitReviewOutput,
    LitReviewSession,
    NoveltySignal,
    now,
)

QUERY_REWRITE_SYSTEM = """You translate structured scientific hypotheses into precise web search queries for a novelty check.

Rules:
- 8-20 words.
- Use precise scientific terminology.
- Focus on the specific intervention + measured outcome + system/subject.
- Do NOT include years, dates, or recency hints.
- Do NOT include hedge words ("can", "might", "study", "experiment").
- Output only the query string. No quotes, no labels, no explanation."""

QUERY_REWRITE_USER_TMPL = """Subject: {subject}
Independent variable: {independent}
Dependent variable: {dependent}
Conditions: {conditions}
Expected outcome: {expected}
Research question: {research_question}"""


CLASSIFY_SYSTEM = """You evaluate scientific novelty. Given a structured hypothesis and web search results, classify the novelty signal, return relevant references, and write a holistic wrap-up summary.

Rules:
- signal must be one of: "novel" (no close prior work), "similar_work_exists" (related but not identical), "exact_match_found" (this exact experiment has been published).
- description (top-level): 2-3 sentences. Be candid about how novel the question is and how it compares to the surfaced literature.
- Pick at most 3 references. Sort primarily by relevance to the hypothesis, secondarily by recency (newer first).
- For each reference include:
    title
    authors             (array; empty array if unknown)
    year                (integer; null if unknown)
    venue               (journal name, preprint server, or other publication venue, e.g. "Nature Reviews Microbiology"; null if unknown)
    url
    snippet             (1-2 sentences directly from the search result)
    relevance_score     (0.0-1.0; the UI renders this as a percentage)
    matched_on          (array of 3-5 short concept tags that bridge this paper to the hypothesis, e.g. ["E. coli", "Glucose", "Catabolite repression"])
    description         (1-2 sentences, NEUTRAL: what does this paper actually cover? May note limitations factually but DO NOT compare to the user's study here)
    importance          (1-2 sentences, RELATIONAL: why does this paper match the user's hypothesis? Where does it overlap, where does it differ, what gap does the user's study fill? This is "why this matched.")
- If a field can't be determined, set it to null (or empty array for matched_on). Never invent authors, DOIs, or venues.

- summary (top-level, the final field): a HOLISTIC wrap-up for the researcher.
  HARD LENGTH LIMIT: EXACTLY 3 OR 4 SENTENCES. Not 5. Not 6. Not a list. Not bullet points.
  Count your sentences before responding. If you exceed 4 sentences, you have failed the task.
  Cover, in order:
    (a) novelty assessment in plain language ("This question is/isn't well-precedented because...");
    (b) the key literature takeaway ("The closest precedent is X, which Y...");
    (c) what gap the researcher's hypothesis fills, OR what to read first.
  Do NOT restate the references list. Do NOT use markdown. Do NOT use phrases like "in summary" or "to summarize". Plain prose only.

Return ONLY a single valid JSON object matching this shape:
{
  "signal": "novel" | "similar_work_exists" | "exact_match_found",
  "description": "string",
  "references": [
    {
      "title": "string",
      "authors": ["string"],
      "year": 2023 | null,
      "venue": "string" | null,
      "url": "string",
      "snippet": "string",
      "relevance_score": 0.0,
      "matched_on": ["string"],
      "description": "string",
      "importance": "string"
    }
  ],
  "summary": "string (3-4 sentences, hard limit)"
}"""

CLASSIFY_USER_TMPL = """Hypothesis (structured):
- Subject: {subject}
- Independent variable: {independent}
- Dependent variable: {dependent}
- Conditions: {conditions}
- Expected outcome: {expected}
- Research question: {research_question}

Tavily search query used: {query}

Tavily synthesized answer:
{answer}

Search results (top {n}):
{results}"""


def _rewrite_query(h: Hypothesis) -> str:
    s = h.structured
    user = QUERY_REWRITE_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
    )
    return llm.complete(QUERY_REWRITE_SYSTEM, user).strip().strip('"').strip("'")


def _format_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        content = (r.get("content") or "").strip().replace("\n", " ")
        # Pass through enough content for the LLM to write a useful description
        # and "why this matched" importance brief per reference.
        if len(content) > 1500:
            content = content[:1500] + "…"
        lines.append(f"[{i}] {title}\n    {url}\n    {content}")
    return "\n\n".join(lines)


def _classify(h: Hypothesis, query: str, tavily_response: dict) -> tuple[NoveltySignal, str, list[Citation], str]:
    s = h.structured
    results = tavily_response.get("results", [])
    user = CLASSIFY_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        query=query,
        answer=tavily_response.get("answer", "(no synthesized answer)"),
        n=len(results),
        results=_format_results(results),
    )

    raw = llm.complete(CLASSIFY_SYSTEM, user, json_mode=True).strip()
    # Strip markdown fences if a model adds them despite instructions
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()

    parsed = json.loads(raw)

    refs = [
        Citation(
            source="paper",
            confidence="medium",
            title=r.get("title"),
            authors=r.get("authors") or [],
            year=r.get("year"),
            venue=r.get("venue"),
            url=r.get("url"),
            snippet=r.get("snippet"),
            relevance_score=r.get("relevance_score"),
            matched_on=r.get("matched_on") or [],
            description=r.get("description"),
            importance=r.get("importance"),
        )
        for r in parsed.get("references", [])
    ][:3]

    summary = (parsed.get("summary") or "").strip()
    return parsed["signal"], parsed["description"], refs, summary


def run(plan: ExperimentPlan) -> LitReviewSession:
    """Stage runner. Returns the LitReviewSession; caller writes it to plan.lit_review."""
    h = plan.hypothesis
    query = _rewrite_query(h)
    tavily_response = tavily.search_for_lit_review(query)
    signal, description, refs, summary = _classify(h, query, tavily_response)

    initial = LitReviewOutput(
        signal=signal,
        description=description,
        references=refs,
        searched_at=now(),
        tavily_query=query,
        summary=summary,
    )

    return LitReviewSession(
        id=f"lr_{uuid.uuid4().hex[:12]}",
        hypothesis_id=h.id,
        initial_result=initial,
        chat_history=[],
        cached_tavily_context=json.dumps(tavily_response),
        user_decision="pending",
    )

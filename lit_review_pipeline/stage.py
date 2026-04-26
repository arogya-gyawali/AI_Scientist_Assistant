"""Stage 1: Lit Review.

Reads:  hypothesis
Writes: lit_review

Flow:
  1. Rewrite the structured hypothesis into a precise scientific search query (LLM).
  2. Semantic Scholar search → top-N papers with structured bibliographic
     metadata (title, authors, year, venue, abstract, TLDR, DOI).
  3. LLM editorial pass: classifies novelty signal, picks 1-3 papers most
     relevant to the hypothesis, writes per-ref `description` (neutral) +
     `importance` (relational) + `matched_on` tags + `relevance_score`.
     Does NOT extract bibliographic fields — backend uses SS data directly.
  4. Build a LitReviewSession and write to ExperimentPlan.lit_review.

Why Semantic Scholar instead of Tavily here:
  Tavily returns body text from web pages; bibliographic fields (authors,
  year, venue, DOI) aren't reliably present in the returned snippets, which
  forced LLM extraction of those fields and led to hallucinated authors.
  Semantic Scholar returns structured metadata — no extraction needed.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from src.clients import llm, semantic_scholar
from src.types import (
    Citation,
    ExperimentPlan,
    Hypothesis,
    LitReviewOutput,
    LitReviewSession,
    NoveltySignal,
    now,
)
from lit_review_pipeline.extractors import (
    extract_doi,
    extract_venue,
    extract_year,
)


QUERY_REWRITE_SYSTEM = """You translate structured scientific hypotheses into precise scientific search queries for a Semantic Scholar novelty check.

Rules:
- 6-15 words.
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


CLASSIFY_SYSTEM = """You evaluate scientific novelty. You receive a structured hypothesis and a list of pre-fetched papers from Semantic Scholar. Each paper already has bibliographic metadata (title, authors, year, venue) and an abstract or TLDR — DO NOT repeat those in your output. Your job is editorial.

Editorial output per chosen reference:
- paper_index   (integer; index into the input papers array. Picking a paper that is not in the array is a failure.)
- relevance_score (0.0-1.0; your judgment of relevance to the user's hypothesis, NOT generic citation count.)
- matched_on    (array of 3-5 short concept tags that bridge this paper to the hypothesis, e.g. ["E. coli", "Glucose", "Catabolite repression"])
- description   (1-2 sentences, NEUTRAL: synthesize what this paper actually covers, drawing from title + abstract + TLDR. May note limitations factually but DO NOT compare to the user's study here.)
- importance    (1-2 sentences, RELATIONAL: why does this paper match the user's hypothesis? Where does it overlap, where does it differ, what gap does the user's study fill? This is "why this matched.")

Top-level output:
- signal       ("novel" — no close prior work | "similar_work_exists" — related but not identical | "exact_match_found" — this exact experiment has been published)
- description  (2-3 sentences explaining the signal classification candidly)
- summary      (HARD LIMIT: EXACTLY 3 OR 4 SENTENCES. Holistic wrap-up for the researcher: novelty assessment, key literature takeaway, what gap the hypothesis fills or what to read first. Plain prose, no markdown, no "in summary" phrasing.)

Selection rules:
- Choose at most 3 references (or fewer if the hypothesis is genuinely novel).
- Sort by relevance to the hypothesis FIRST, recency SECOND.
- Picking zero references is acceptable when nothing is relevant.

Return ONLY a single valid JSON object:
{
  "signal": "novel" | "similar_work_exists" | "exact_match_found",
  "description": "string",
  "references": [
    {
      "paper_index": 0,
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

Semantic Scholar query used: {query}

Papers ({n} returned):
{papers}"""


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


def _format_papers(papers: list[dict]) -> str:
    """Render papers for the LLM prompt with structured metadata up front."""
    lines = []
    for i, p in enumerate(papers):
        title = p.get("title") or "(no title)"
        authors_list = [a.get("name") for a in (p.get("authors") or []) if a.get("name")]
        authors = ", ".join(authors_list[:6]) + (" et al." if len(authors_list) > 6 else "")
        year = p.get("year") if p.get("year") is not None else "n/a"
        venue = p.get("venue") or "n/a"
        body = (p.get("tldr") or {}).get("text") or p.get("abstract") or ""
        if len(body) > 1500:
            body = body[:1500] + "…"
        lines.append(
            f"[{i}] {title}\n"
            f"    Authors: {authors or '(none listed)'}\n"
            f"    {year}, {venue}\n"
            f"    {body}"
        )
    return "\n\n".join(lines)


def _compose_citation(paper: dict, editorial: dict) -> Citation:
    """Build a Citation from Semantic Scholar paper data + LLM editorial fields.

    Bibliographic fields come straight from Semantic Scholar — no LLM extraction,
    no validation needed (SS metadata is authoritative). When SS leaves a field
    null we fall back to the deterministic regex extractors as a safety net.
    """
    authors = [a.get("name") for a in (paper.get("authors") or []) if a.get("name")]
    external = paper.get("externalIds") or {}
    ss_doi = external.get("DOI")
    pdf_url = (paper.get("openAccessPdf") or {}).get("url")
    page_url = paper.get("url") or pdf_url

    # Snippet preference: TLDR (1-sentence AI summary) > abstract > nothing.
    tldr_text = (paper.get("tldr") or {}).get("text")
    snippet = tldr_text or paper.get("abstract")

    return Citation(
        source="semantic_scholar",
        confidence="high",  # SS metadata is authoritative
        title=paper.get("title"),
        authors=authors,
        year=paper.get("year") or extract_year(page_url, paper.get("title"), paper.get("abstract")),
        venue=paper.get("venue") or extract_venue(page_url),
        doi=ss_doi or extract_doi(page_url, paper.get("abstract")),
        url=page_url,
        snippet=snippet,
        relevance_score=editorial.get("relevance_score"),
        matched_on=editorial.get("matched_on") or [],
        description=editorial.get("description"),
        importance=editorial.get("importance"),
    )


def _classify(
    h: Hypothesis,
    query: str,
    ss_response: dict,
) -> tuple[NoveltySignal, str, list[Citation], str]:
    s = h.structured
    papers: list[dict] = ss_response.get("data") or []

    user = CLASSIFY_USER_TMPL.format(
        subject=s.subject,
        independent=s.independent,
        dependent=s.dependent,
        conditions=s.conditions,
        expected=s.expected,
        research_question=s.research_question,
        query=query,
        n=len(papers),
        papers=_format_papers(papers) or "(no papers returned)",
    )

    def _call_and_parse() -> dict:
        raw = llm.complete(CLASSIFY_SYSTEM, user, json_mode=True).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        return json.loads(raw)

    try:
        parsed = _call_and_parse()
    except json.JSONDecodeError:
        parsed = _call_and_parse()  # one retry; JSON-mode occasionally hiccups

    refs: list[Citation] = []
    for r in parsed.get("references", [])[:3]:
        idx = r.get("paper_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(papers):
            # LLM picked a phantom paper — skip silently rather than fabricate.
            continue
        refs.append(_compose_citation(papers[idx], r))

    summary = (parsed.get("summary") or "").strip()
    return parsed["signal"], parsed["description"], refs, summary


def run(plan: ExperimentPlan) -> LitReviewSession:
    """Stage runner. Returns the LitReviewSession; caller writes it to plan.lit_review."""
    h = plan.hypothesis
    query = _rewrite_query(h)
    ss_response = semantic_scholar.search_for_lit_review(query)
    signal, description, refs, summary = _classify(h, query, ss_response)

    initial = LitReviewOutput(
        signal=signal,
        description=description,
        references=refs,
        searched_at=now(),
        tavily_query=query,  # field name is historical; it's the SS query now
        summary=summary,
    )

    return LitReviewSession(
        id=f"lr_{uuid.uuid4().hex[:12]}",
        hypothesis_id=h.id,
        initial_result=initial,
        chat_history=[],
        cached_tavily_context=json.dumps(ss_response),  # field name historical
        user_decision="pending",
    )

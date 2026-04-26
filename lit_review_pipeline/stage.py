"""Stage 1: Lit Review.

Reads:  hypothesis
Writes: lit_review

Flow:
  1. Rewrite the structured hypothesis into a precise scientific search query (LLM).
  2. Europe PMC search → top-N papers with structured bibliographic metadata
     (title, authors, year, venue, plain-text abstract, DOI, PMID/PMCID).
  3. LLM editorial pass: classifies novelty signal, picks 1-3 papers most
     relevant to the hypothesis, writes per-ref `description` (neutral) +
     `importance` (relational) + `matched_on` tags + `relevance_score`.
     Does NOT extract bibliographic fields — backend uses Europe PMC data directly.
  4. Build a LitReviewSession and write to ExperimentPlan.lit_review.

Why Europe PMC:
  Tavily returns body text from web pages; bibliographic fields aren't
  reliably present in the snippets, which forced LLM extraction and led
  to hallucinated authors. Europe PMC is biomedical-specific, free, no auth,
  and returns structured metadata with full plain-text abstracts. Authors
  come back as structured AuthorList objects — no extraction, no hallucination.
"""

from __future__ import annotations

import html
import json
import re
import uuid
from typing import Any

from src.clients import europe_pmc, llm
from src.types import (
    Citation,
    ExperimentPlan,
    Hypothesis,
    KeyDifference,
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


QUERY_REWRITE_SYSTEM = """You translate structured scientific hypotheses into precise scientific search queries for a Europe PMC novelty check.

Rules:
- Output the query in ENGLISH ONLY. Do NOT translate technical terms into other languages.
- 6-15 words.
- Use precise scientific terminology (gene names, organism names, chemical names, established assay names).
- Focus on the specific intervention + measured outcome + system/subject.
- Do NOT include years, dates, or recency hints.
- Do NOT include hedge words ("can", "might", "study", "experiment").
- Do NOT use Europe PMC field qualifiers (no AUTH:, TITLE:, etc.) — plain query terms only.
- Output only the query string. No quotes, no labels, no explanation."""

QUERY_REWRITE_USER_TMPL = """Subject: {subject}
Independent variable: {independent}
Dependent variable: {dependent}
Conditions: {conditions}
Expected outcome: {expected}
Research question: {research_question}"""


CLASSIFY_SYSTEM = """You evaluate scientific novelty. You receive a structured hypothesis and a list of pre-fetched papers from Europe PMC. Each paper already has bibliographic metadata (title, authors, year, journal) and a plain-text abstract — DO NOT repeat those in your output. Your job is editorial.

Editorial output per chosen reference:
- paper_index   (integer; index into the input papers array. Picking a paper that is not in the array is a failure.)
- relevance_score (0.0-1.0; your judgment of relevance to the user's hypothesis, NOT generic citation count.)
- matched_on    (array of 3-5 short concept tags that bridge this paper to the hypothesis, e.g. ["E. coli", "Glucose", "Catabolite repression"])
- description   (1-2 sentences, NEUTRAL: synthesize what this paper actually covers, drawing from title + abstract. May note limitations factually but DO NOT compare to the user's study here.)
- importance    (1-2 sentences, RELATIONAL: why does this paper match the user's hypothesis? Where does it overlap, where does it differ, what gap does the user's study fill? This is "why this matched.")
- key_differences (array of 2-4 STRUCTURED deltas between this paper and the user's hypothesis. Each must be grounded in the paper's abstract. The user reads these to understand WHY the paper is "adjacent" rather than "exact match" and what gap their experiment fills.

  Each key_difference object:
  - dimension       (one of: "subject", "intervention", "measurement", "conditions", "scope", "method")
  - their_approach  (what THIS paper does, drawn from the abstract — concrete, e.g. "uses chemostat continuous culture" not "different culture mode")
  - our_approach    (what the user's hypothesis specifies — concrete, drawn from the structured fields)
  - gap_significance (why this difference matters for novelty: what gap it leaves, what conclusion it cannot support, why the user's study is needed)

  Quality bar: only emit a difference if it is BOTH true (paper genuinely does not do this) AND material (it changes whether the paper answers the user's research question). Two genuine differences beat four padding ones. If the paper is an exact match across every dimension, return an empty array.)

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
      "importance": "string",
      "key_differences": [
        {
          "dimension": "subject" | "intervention" | "measurement" | "conditions" | "scope" | "method",
          "their_approach": "string",
          "our_approach": "string",
          "gap_significance": "string"
        }
      ]
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

Europe PMC query used: {query}

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
    raw = llm.complete(QUERY_REWRITE_SYSTEM, user).strip().strip('"').strip("'")
    # The system prompt forbids prefixes/labels, but LLMs sometimes inject
    # "Query: ...", "Search for: ...", or "Here's the query: ..." anyway.
    # Strip those before passing to Europe PMC.
    raw = _QUERY_FILLER_PREFIX_RE.sub("", raw, count=1).strip().strip('"').strip("'")
    return raw


# ----------------------------------------------------------------------------
# Post-processing helpers
# ----------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Lookahead for an uppercase letter catches the common case but doesn't
# help when "et al." is followed by an uppercase word. We protect the
# most frequent scientific abbreviations by temporarily masking their
# periods before splitting; see _truncate_to_n_sentences below.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_SCIENCE_ABBREVIATIONS = (
    "et al.", "i.e.", "e.g.", "vs.", "Fig.", "Figs.",
    "sp.", "spp.", "approx.", "ref.", "Ref.", "No.", "Vol.",
    "cf.", "Eq.", "ca.",
)
_PERIOD_MASK = "\x00"

# Strips common LLM-conversational prefixes from the rewritten query.
# Longer alternatives come first so Python's left-to-right alternation
# doesn't accept a shorter prefix match (e.g., "Search" before "Search for").
_QUERY_FILLER_PREFIX_RE = re.compile(
    r"^(?:here(?:'s|\s+is)\s+the\s+query"
    r"|search\s+for"
    r"|search\s+query"
    r"|search"
    r"|query"
    r")\s*[:\-]?\s*",
    re.IGNORECASE,
)


def _clean_text(s: str | None) -> str | None:
    """Decode HTML entities and strip simple inline tags. Europe PMC sometimes
    returns titles with <i>, <sub>, <sup>, <b> tags wrapped in entity-encoded
    form (e.g. '&lt;i&gt;Lactobacillus rhamnosus&lt;/i&gt; GG ...'). For
    hackathon UI we want clean text — losing italics is cheaper than
    handling encoded markup in React."""
    if not s:
        return s
    return _HTML_TAG_RE.sub("", html.unescape(s)).strip()


def _truncate_to_n_sentences(s: str | None, n: int) -> str:
    """Hard cap on sentence count. The summary prompt asks for 3-4 sentences
    and Gemini Flash usually obeys, but it occasionally overruns. This is a
    deterministic backstop so the FE doesn't see a 5-sentence wall of text.

    Common scientific abbreviations (et al., i.e., e.g., Fig., sp., ...) are
    protected from the splitter by temporarily masking their internal periods —
    otherwise the regex would split on "et al." + capitalized next word.
    """
    if not s:
        return s or ""
    # Mask periods inside known abbreviations so the splitter doesn't see them.
    masked = s.strip()
    for abbr in _SCIENCE_ABBREVIATIONS:
        masked = masked.replace(abbr, abbr.replace(".", _PERIOD_MASK))
    parts = _SENTENCE_SPLIT_RE.split(masked)
    out = " ".join(parts[:n]).strip()
    return out.replace(_PERIOD_MASK, ".")


# ----------------------------------------------------------------------------
# Europe PMC paper helpers
# ----------------------------------------------------------------------------

def _paper_authors(p: dict) -> list[str]:
    """Prefer the structured AuthorList. Fall back to the comma-joined string."""
    al = (p.get("authorList") or {}).get("author") or []
    if al:
        names = []
        for a in al:
            n = a.get("fullName") or a.get("lastName")
            if n:
                names.append(n)
        if names:
            return names
    s = p.get("authorString") or ""
    if s:
        return [n.strip() for n in s.split(",") if n.strip()]
    return []


def _paper_year(p: dict) -> int | None:
    """Pull year from Europe PMC's pubYear or journalInfo, defensively."""
    yr = p.get("pubYear")
    if isinstance(yr, str) and yr.isdigit():
        return int(yr)
    if isinstance(yr, int):
        return yr
    yr2 = (p.get("journalInfo") or {}).get("yearOfPublication")
    if isinstance(yr2, int):
        return yr2
    if isinstance(yr2, str) and yr2.isdigit():
        return int(yr2)
    return None


def _paper_venue(p: dict) -> str | None:
    journal = (p.get("journalInfo") or {}).get("journal") or {}
    return journal.get("title") or journal.get("iso") or None


def _paper_url(p: dict) -> str | None:
    """Best URL for the paper, in priority: DOI > PubMed > PMC > Europe PMC."""
    if doi := p.get("doi"):
        return f"https://doi.org/{doi}"
    if pmid := p.get("pmid"):
        return f"https://europepmc.org/article/MED/{pmid}"
    if pmcid := p.get("pmcid"):
        return f"https://europepmc.org/article/PMC/{pmcid}"
    epmc_id = p.get("id")
    source = p.get("source")
    if epmc_id and source:
        return f"https://europepmc.org/article/{source}/{epmc_id}"
    return None


def _format_papers(papers: list[dict]) -> str:
    lines = []
    for i, p in enumerate(papers):
        title = p.get("title") or "(no title)"
        authors = p.get("authorString") or ""
        if len(authors) > 240:
            authors = authors[:240] + "…"
        year = _paper_year(p) or "n/a"
        venue = _paper_venue(p) or "n/a"
        abstract = p.get("abstractText") or ""
        if len(abstract) > 1500:
            abstract = abstract[:1500] + "…"
        lines.append(
            f"[{i}] {title}\n"
            f"    Authors: {authors or '(none listed)'}\n"
            f"    {year}, {venue}\n"
            f"    {abstract}"
        )
    return "\n\n".join(lines)


_VALID_DIFF_DIMENSIONS = {
    "subject", "intervention", "measurement",
    "conditions", "scope", "method",
}


def _parse_key_differences(raw: object) -> list[KeyDifference]:
    """Parse + validate the LLM's key_differences array. Drops entries that
    fail validation (missing fields, unknown dimension, sub-token strings).

    We don't try to verify the `their_approach` claim is *literally* in the
    abstract — abstracts are paraphrased prose and a substring check would
    over-reject. Instead the prompt instructs the LLM to ground each entry
    in the abstract; here we just enforce structure (all 4 fields populated,
    valid dimension, non-trivial length) so malformed entries don't reach
    the FE."""
    if not isinstance(raw, list):
        return []
    out: list[KeyDifference] = []
    for entry in raw[:6]:  # Hard cap to keep the FE list scannable
        if not isinstance(entry, dict):
            continue
        dim = str(entry.get("dimension") or "").strip().lower()
        if dim not in _VALID_DIFF_DIMENSIONS:
            continue
        their = str(entry.get("their_approach") or "").strip()
        ours = str(entry.get("our_approach") or "").strip()
        sig = str(entry.get("gap_significance") or "").strip()
        # Reject ultra-short fields that almost always indicate the LLM
        # padded a difference rather than identifying a real one.
        if len(their) < 8 or len(ours) < 8 or len(sig) < 12:
            continue
        out.append(KeyDifference(
            dimension=dim,  # type: ignore[arg-type]
            their_approach=their,
            our_approach=ours,
            gap_significance=sig,
        ))
    return out


def _compose_citation(paper: dict, editorial: dict) -> Citation:
    """Build a Citation from a Europe PMC paper + the LLM's editorial layer.

    Bibliographic fields come straight from Europe PMC; deterministic extractors
    are belt-and-suspenders fallback for the rare case Europe PMC is missing a
    field that's recoverable from the URL or abstract.
    """
    page_url = _paper_url(paper)
    abstract = paper.get("abstractText")

    differences = _parse_key_differences(editorial.get("key_differences"))

    return Citation(
        source="europe_pmc",
        confidence="high",  # Europe PMC metadata is authoritative
        title=_clean_text(paper.get("title")),
        authors=_paper_authors(paper),
        year=_paper_year(paper) or extract_year(page_url, paper.get("title"), abstract),
        venue=_paper_venue(paper) or extract_venue(page_url),
        doi=paper.get("doi") or extract_doi(page_url, abstract),
        url=page_url,
        snippet=abstract,
        relevance_score=editorial.get("relevance_score"),
        matched_on=editorial.get("matched_on") or [],
        description=editorial.get("description"),
        importance=editorial.get("importance"),
        key_differences=differences or None,
    )


# ----------------------------------------------------------------------------
# Classifier
# ----------------------------------------------------------------------------

def _classify(
    h: Hypothesis,
    query: str,
    epmc_response: dict,
) -> tuple[NoveltySignal, str, list[Citation], str]:
    s = h.structured
    papers: list[dict] = (epmc_response.get("resultList") or {}).get("result") or []

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

    # JSON-mode occasionally produces malformed output. We retry once on
    # JSONDecodeError. The retry itself can also fail (JSON or network);
    # we wrap it so the surfaced error is informative rather than a raw
    # second-attempt traceback.
    try:
        parsed = _call_and_parse()
    except json.JSONDecodeError as first_exc:
        try:
            parsed = _call_and_parse()
        except json.JSONDecodeError as retry_exc:
            raise RuntimeError(
                f"LLM returned malformed JSON twice (first: {first_exc}; "
                f"retry: {retry_exc}). Try LLM_PROVIDER=anthropic for stricter output."
            ) from retry_exc

    refs: list[Citation] = []
    for r in parsed.get("references", [])[:3]:
        idx = r.get("paper_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(papers):
            continue
        refs.append(_compose_citation(papers[idx], r))

    # Hard-cap summary to 4 sentences. Prompt asks for 3-4 but the LLM
    # sometimes overshoots; truncating here is deterministic and silent.
    summary = _truncate_to_n_sentences((parsed.get("summary") or "").strip(), n=4)
    # Defensive: if the LLM omits required keys, fall back to safe defaults
    # rather than crashing the whole pipeline. similar_work_exists is the
    # most defensible fallback (it's the modal classification across our
    # bioscience samples; "novel" or "exact match" should require evidence).
    signal = parsed.get("signal") or "similar_work_exists"
    description = parsed.get("description") or ""
    return signal, description, refs, summary


def run(plan: ExperimentPlan) -> LitReviewSession:
    """Stage runner. Returns the LitReviewSession; caller writes it to plan.lit_review."""
    h = plan.hypothesis
    query = _rewrite_query(h)
    # page_size=10 gives the LLM a wider candidate pool; the prompt still
    # caps the chosen references at 3. Worth the marginal token cost.
    epmc_response = europe_pmc.search_for_lit_review(query, page_size=10)
    signal, description, refs, summary = _classify(h, query, epmc_response)

    initial = LitReviewOutput(
        signal=signal,
        description=description,
        references=refs,
        searched_at=now(),
        tavily_query=query,  # field name is historical; carries the EPMC query
        summary=summary,
    )

    return LitReviewSession(
        id=f"lr_{uuid.uuid4().hex[:12]}",
        hypothesis_id=h.id,
        initial_result=initial,
        chat_history=[],
        cached_search_context=json.dumps(epmc_response),
        user_decision="pending",
    )

"""protocols.io sample loader + DraftJS normalizer.

Reads the static bundles in `pipeline_output_samples/protocols_io/<name>.json`
(produced by `tools/protocols_io_smoke.py`) and turns them into a clean
`NormalizedProtocol` shape the LLM agents can consume without seeing
DraftJS escape sequences, mojibake, or HTML wrappers.

Why a separate normalizer:
  - protocols.io stores step bodies as DraftJS blocks JSON inside a string
    field, so raw payloads are noisy. Feeding them to an LLM wastes tokens
    and primes the model to mimic the noise.
  - Some protocols are non-English (the trehalose top hit is Spanish).
    A single language flag lets prompts opt into "translate inline" rather
    than relying on the LLM to silently figure it out.
  - Section headers come back as `<p>...</p>`. Stripping them centrally
    means downstream code never has to think about the wrapper.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


SAMPLES_DIR = Path("pipeline_output_samples/protocols_io")


# ---------------------------------------------------------------------------
# Normalized shape — what the LLM agents actually consume
# ---------------------------------------------------------------------------

class NormalizedStep(BaseModel):
    id: str                         # protocols.io step id (string, for stable refs)
    section: str                    # cleaned section header, e.g. "Methods"
    number: str                     # display step number from the protocol
    text: str                       # plaintext from DraftJS blocks
    duration_seconds: Optional[int] = None  # raw seconds from API


class NormalizedProtocol(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    language: str = "unknown"       # 'en' | 'es' | 'unknown'
    materials_text: str = ""        # plaintext extracted from materials_text DraftJS
    steps: list[NormalizedStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# DraftJS parsing
# ---------------------------------------------------------------------------

# Markers we prepend to list-type DraftJS blocks so the LLM still sees the
# structure (numbered vs bulleted) without us shipping raw block JSON.
_LIST_MARKERS = {
    "unordered-list-item": "- ",
    "ordered-list-item": "1. ",      # plain "1." rather than tracking ordinal
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """protocols.io section fields ship as `<p>Methods</p>`. Strip the tags."""
    if not text:
        return ""
    return _TAG_RE.sub("", text).strip()


def parse_draftjs(raw: Optional[str]) -> str:
    """Convert a DraftJS-format JSON string to plaintext.

    Returns "" if the input is empty, not parseable, or doesn't have the
    expected `blocks` shape — never raises. The pipeline must keep going
    even if a single step has malformed body content.
    """
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Sometimes the field already contains plaintext (older protocols)
        # or HTML — return it as-is, stripped.
        return _strip_html(str(raw)).strip()

    blocks = obj.get("blocks") if isinstance(obj, dict) else None
    if not isinstance(blocks, list):
        return ""

    lines: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        text = (b.get("text") or "").strip()
        if not text:
            continue
        block_type = b.get("type") or "unstyled"
        depth = b.get("depth") or 0
        prefix = _LIST_MARKERS.get(block_type, "")
        indent = "  " * depth if prefix else ""
        lines.append(f"{indent}{prefix}{text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Language detection — heuristic only, no extra deps
# ---------------------------------------------------------------------------

# Spanish stopwords + diacritic markers. Cheap detector: if any of these
# appear in the first ~500 chars, call it Spanish. Good enough to flag the
# trehalose Spanish protocol; we don't need 100% accuracy because the LLM
# can translate from any language regardless of how we label it. The flag
# just lets prompts say "this source is Spanish, translate inline".
_SPANISH_TOKENS = (
    "mé", "á", "é", "í", "ó", "ú", "ñ", "¿", "¡",
    " del ", " los ", " las ", " que ", " con ", " para ",
    " por ", " est", " son ", " una ", " un ",
)


def detect_language(text: str) -> str:
    """Return 'es' for likely Spanish, 'en' otherwise. 'unknown' for empty."""
    if not text:
        return "unknown"
    sample = text[:500].lower()
    if any(tok in sample for tok in _SPANISH_TOKENS):
        return "es"
    return "en"


# ---------------------------------------------------------------------------
# Top-level: load + normalize a sample bundle
# ---------------------------------------------------------------------------

def _author_names(creator: Any, authors: Any) -> list[str]:
    """protocols.io's search items have both `creator` (single object) and
    `authors` (list of objects with `name`). Prefer `authors`; fall back to
    `creator`. Returns plain string names."""
    out: list[str] = []
    if isinstance(authors, list):
        for a in authors:
            if isinstance(a, dict):
                name = (a.get("name") or "").strip()
                if name:
                    out.append(name)
    if not out and isinstance(creator, dict):
        name = (creator.get("name") or creator.get("username") or "").strip()
        if name:
            out.append(name)
    return out


def normalize_bundle(bundle: dict) -> Optional[NormalizedProtocol]:
    """Take a raw `pipeline_output_samples/protocols_io/<name>.json` dict
    and return its top hit as a NormalizedProtocol. Returns None if the
    bundle has no usable search results."""
    items = (bundle.get("search") or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    proto_id = str(item.get("id") or "")

    # Steps come back nested as top_hit_steps.payload (a list of step objects)
    raw_steps = ((bundle.get("top_hit_steps") or {}).get("payload")) or []
    steps: list[NormalizedStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        body = parse_draftjs(raw.get("step"))
        if not body:
            continue  # skip blank steps (some sections contain only headers)
        steps.append(NormalizedStep(
            id=str(raw.get("id") or raw.get("guid") or ""),
            section=_strip_html(raw.get("section") or ""),
            number=str(raw.get("number") or ""),
            text=body,
            duration_seconds=raw.get("duration") if isinstance(raw.get("duration"), int) else None,
        ))

    materials_text = parse_draftjs(item.get("materials_text"))

    # Use steps + materials_text + description for language detection so a
    # protocol with English title but Spanish body gets flagged correctly.
    detect_corpus = " ".join([
        materials_text,
        " ".join(s.text for s in steps[:3]),
    ])
    language = detect_language(detect_corpus)

    return NormalizedProtocol(
        id=proto_id,
        title=_strip_html(item.get("title") or item.get("title_html") or ""),
        description=item.get("description") or None,
        doi=item.get("doi") or None,
        url=item.get("url") or item.get("link") or None,
        authors=_author_names(item.get("creator"), item.get("authors")),
        language=language,
        materials_text=materials_text,
        steps=steps,
    )


def load_sample(name: str) -> Optional[NormalizedProtocol]:
    """Load a normalized protocol from
    `pipeline_output_samples/protocols_io/<name>.json`."""
    path = SAMPLES_DIR / f"{name}.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    return normalize_bundle(bundle)


def load_all_samples() -> dict[str, NormalizedProtocol]:
    """Load every available sample. Skips bundles that produce no normalized
    protocol (empty search results)."""
    out: dict[str, NormalizedProtocol] = {}
    if not SAMPLES_DIR.exists():
        return out
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        norm = normalize_bundle(bundle)
        if norm is not None:
            out[path.stem] = norm
    return out


# ---------------------------------------------------------------------------
# Live protocols.io fetch (via Vip's client at the repo root)
# ---------------------------------------------------------------------------

def _bundle_to_normalized(
    candidate: dict,
    steps: list[dict],
) -> Optional[NormalizedProtocol]:
    """Convert one protocols_client.py candidate (with its steps) into a
    NormalizedProtocol. Drops protocols with no usable id."""
    pid = str(candidate.get("id") or "").strip()
    if not pid:
        return None

    norm_steps: list[NormalizedStep] = []
    for s in steps:
        body = (s.get("description") or "").strip()
        if not body:
            continue
        number = s.get("step_number")
        norm_steps.append(NormalizedStep(
            id=f"{pid}-{number or len(norm_steps)+1}",
            section="",            # client doesn't expose section yet
            number=str(number or ""),
            text=body,
            duration_seconds=None, # client doesn't expose duration yet
        ))

    # Language detection on the steps text — same heuristic as
    # `normalize_bundle` so prompts can opt into "translate inline".
    detect_corpus = " ".join(s.text for s in norm_steps[:3])
    language = detect_language(detect_corpus)

    return NormalizedProtocol(
        id=pid,
        title=str(candidate.get("title") or "").strip(),
        description=candidate.get("description") or None,
        doi=candidate.get("doi") or None,
        url=candidate.get("url") or candidate.get("uri") or None,
        authors=[],          # client doesn't expose authors yet
        language=language,
        materials_text="",   # client returns structured materials, not free text
        steps=norm_steps,
    )


class ProtocolCandidate(BaseModel):
    """Lightweight summary the FE shows in the candidate-selection screen.
    Holds enough to populate a card (title, description, URL, language,
    step count) plus the relevance filter's verdict so the user has
    grounding for their pick."""
    id: str
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    language: str
    step_count: int
    relevance_score: float       # 0..1
    relevance_reason: str        # one-line LLM rationale


def fetch_one_protocol(protocol_id: str) -> Optional[NormalizedProtocol]:
    """Fetch a single protocol by ID via Vip's client and return its
    normalized form. Used by /protocol when the user has pre-selected
    candidate IDs from /protocol-candidates and we need to re-hydrate
    them for the pipeline. Returns None on missing module / empty
    steps / bad ID; surfaces network errors via the client's logger
    rather than silently swallowing.

    Reuses `_bundle_to_normalized` so the metadata population path is
    identical to the search → normalize pipeline. Without the metadata
    lookup, cited protocols rendered with empty titles in the final
    Stage-2 output (the user couldn't tell which paper grounded which
    procedure).
    """
    # Catch only the import-failure cases. Letting NameError /
    # AttributeError out of `protocols_client` propagate means real
    # bugs surface instead of being silently treated as "no result".
    try:
        from protocols_client import (
            get_protocol_metadata,
            get_protocol_steps,
        )
    except (ImportError, ModuleNotFoundError):
        return None

    pid = str(protocol_id).strip()
    if not pid:
        return None

    # Fetch metadata (title / description / doi / url) and steps in
    # parallel. Both are independent network calls; running them
    # serially doubles the latency for no reason.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        meta_future = pool.submit(get_protocol_metadata, pid)
        steps_future = pool.submit(get_protocol_steps, pid)
        candidate = meta_future.result() or {}
        steps = steps_future.result() or []

    if not steps:
        return None

    # Make sure the candidate dict has the id even when the metadata
    # lookup returned empty — `_bundle_to_normalized` requires it.
    if not candidate.get("id"):
        candidate["id"] = pid

    return _bundle_to_normalized(candidate, steps)


def fetch_live_candidates(
    query: str,
    *,
    limit: int = 5,
) -> dict[str, NormalizedProtocol]:
    """Live fetch from protocols.io via the root-level `protocols_client`
    module (Vip's file with our bug-fixes layered on). For each candidate
    in the search response, fetches steps + materials and normalizes
    into our NormalizedProtocol shape — the same shape the static-sample
    loader produces, so the rest of the pipeline doesn't care.

    Returns {} silently when the API is unreachable, the token is
    missing, or the search returns nothing — caller falls back to
    static samples in that case (see `protocol_pipeline.stage`)."""
    try:
        # Imported lazily so tests / offline dev don't pay the requests
        # import cost when the live fetch is never used.
        from protocols_client import (
            search_protocols,
            get_protocol_steps,
        )
    except (ImportError, ModuleNotFoundError):
        # Narrow to the only error we actually want to swallow here.
        # NameError / AttributeError inside the client mean a real bug;
        # let those propagate so the server-error log is informative.
        return {}

    # `search_protocols` already catches RequestException internally and
    # returns []. We don't wrap it again — letting NameError /
    # AttributeError surface here means real bugs in the client are
    # visible in the server log instead of being silently treated as
    # "no candidates found".
    candidates = search_protocols(query, limit=limit)

    # Fetch each candidate's steps in parallel — they're independent
    # network calls and serializing them N times would dominate the
    # wall-clock cost of /protocol-candidates.
    from concurrent.futures import ThreadPoolExecutor

    valid = [c for c in candidates if str(c.get("id") or "").strip()]

    out: dict[str, NormalizedProtocol] = {}
    if not valid:
        return out

    # `get_protocol_steps` already catches RequestException internally
    # and returns []. We let NameError / AttributeError surface (real
    # bugs in the client) instead of silently swallowing.
    with ThreadPoolExecutor(max_workers=min(len(valid), 8)) as pool:
        steps_per_candidate = list(pool.map(
            lambda c: get_protocol_steps(str(c["id"]).strip()),
            valid,
        ))

    for candidate, steps in zip(valid, steps_per_candidate):
        pid = str(candidate["id"]).strip()
        norm = _bundle_to_normalized(candidate, steps or [])
        if norm is not None:
            out[pid] = norm
    return out

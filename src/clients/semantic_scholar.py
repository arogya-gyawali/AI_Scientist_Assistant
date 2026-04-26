"""Semantic Scholar API client.

Used for Stage 1 lit review. Returns structured paper metadata
(title, authors, year, venue, abstract, TLDR, DOI, URL) — replacing the
brittle LLM-extracts-from-snippet approach we were doing with Tavily.

No auth required for ≤100 RPM. SEMANTIC_SCHOLAR_API_KEY env var unlocks
the 1000 RPM tier (free; register at https://www.semanticscholar.org/product/api).

Docs: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from src.lib import cache

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_LIT_REVIEW_TTL = 7 * 24 * 3600  # 7 days; bibliographic data rarely changes

# Fields requested for every paper. Cheaper to over-request once than to
# revisit choices per call. `tldr` is Semantic Scholar's auto-generated
# 1-sentence summary; falls back to `abstract` when null.
DEFAULT_FIELDS: tuple[str, ...] = (
    "title",
    "abstract",
    "year",
    "venue",
    "authors.name",
    "authors.authorId",
    "externalIds",
    "url",
    "openAccessPdf",
    "tldr",
    "citationCount",
)


def _headers() -> dict[str, str]:
    h = {"User-Agent": "ai-scientist-assistant/0.1 (hackathon)"}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if key:
        h["x-api-key"] = key
    return h


def search_for_lit_review(query: str, limit: int = 5) -> dict[str, Any]:
    """Search Semantic Scholar for the top-N papers matching the query.

    Returns the raw API response with structured paper metadata. Cached
    by query hash for 7 days; bibliographic data is essentially static.
    """
    payload = {
        "query": query,
        "limit": limit,
        "fields": ",".join(DEFAULT_FIELDS),
    }

    cached = cache.get("semantic_scholar/lit_review", payload, _LIT_REVIEW_TTL)
    if cached is not None:
        return cached

    body = _get_with_retry(f"{_BASE_URL}/paper/search", payload)
    cache.put("semantic_scholar/lit_review", payload, body)
    return body


def _get_with_retry(url: str, params: dict[str, Any], max_attempts: int = 5) -> dict[str, Any]:
    """GET with exponential backoff on 429 (rate limit) and 5xx.

    Unauthenticated Semantic Scholar bursts to 1 RPS on the public endpoint
    but rejects bursts; backing off 2s, 4s, 8s usually clears the limit.
    Set SEMANTIC_SCHOLAR_API_KEY to get a stable 1000 RPM and avoid retries.
    """
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = httpx.get(url, params=params, headers=_headers(), timeout=30.0)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as exc:
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Semantic Scholar request failed after retries")

"""Europe PMC API client for Stage 1 lit review.

Free, no auth, biomedical-specific. Indexes ~40M+ papers from PubMed,
PMC, preprint servers, and clinical trial registries. Returns structured
metadata including plain-text abstracts (no inverted-index reconstruction
or AI TLDR — just the real abstract).

Docs: https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.lib import cache

_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_LIT_REVIEW_TTL = 7 * 24 * 3600  # 7 days; bibliographic metadata is essentially static

# Module-level pooled client. Reuses TCP connections across calls — meaningful
# when --all sweeps three samples back-to-back. Tests monkeypatch this attribute.
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "ai-scientist-assistant/0.1 (hackathon)"},
        )
    return _client


def _headers() -> dict[str, str]:
    return {"User-Agent": "ai-scientist-assistant/0.1 (hackathon)"}


def search_for_lit_review(query: str, page_size: int = 5) -> dict[str, Any]:
    """Search Europe PMC for the top-N papers matching the query.

    Returns the raw API response under a known shape:
      {"resultList": {"result": [{...paper...}, ...]}, "hitCount": N, ...}

    Cached by query hash for 7 days.
    """
    payload = {
        "query": query,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",   # 'core' includes abstract + author list; 'lite' omits them
    }

    cached = cache.get("europe_pmc/lit_review", payload, _LIT_REVIEW_TTL)
    if cached is not None:
        return cached

    body = _get_with_retry(f"{_BASE_URL}/search", payload)
    cache.put("europe_pmc/lit_review", payload, body)
    return body


def _get_with_retry(url: str, params: dict[str, Any], max_attempts: int = 4) -> dict[str, Any]:
    """GET with exponential backoff on 429 / 5xx.

    NOTE on Flask: this uses time.sleep, which blocks the worker thread.
    Acceptable for the CLI and a single-worker dev server; for production
    deployment with multiple concurrent users, this should move behind a
    task queue or async client. Backoff cap is 8s (not 30s) to keep
    worst-case wait under the typical Vercel/Cloud Run 30s timeout.
    """
    client = _get_client()
    delay = 2.0
    last_exc: Exception | None = None
    for _ in range(max_attempts):
        try:
            response = client.get(url, params=params, headers=_headers())
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as exc:
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 2, 8.0)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Europe PMC request failed after retries")

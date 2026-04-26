"""Tavily wrapper. Stage-specific helpers bake in the recommended
parameters per spec/architecture.md > 'Tavily call shapes per stage'."""

from __future__ import annotations

import os
from typing import Any

from tavily import TavilyClient

from src.lib import cache

_LIT_REVIEW_TTL = 7 * 24 * 3600       # 7 days
_GAP_FILL_TTL = 30 * 24 * 3600        # 30 days
_PRICING_TTL = 24 * 3600              # 24 hours

SUPPLIER_DOMAINS = [
    "sigmaaldrich.com",
    "thermofisher.com",
    "promega.com",
    "qiagen.com",
    "idtdna.com",
    "atcc.org",
    "addgene.org",
]


def _client() -> TavilyClient:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return TavilyClient(api_key=api_key)


def search_for_lit_review(query: str) -> dict[str, Any]:
    """Stage 1 lit-review search: deep, with synthesized answer, no recency filter."""
    payload = {
        "query": query,
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": True,
        "include_raw_content": False,
    }
    cached = cache.get("tavily/lit_review", payload, _LIT_REVIEW_TTL)
    if cached is not None:
        return cached

    response = _client().search(**payload)
    cache.put("tavily/lit_review", payload, response)
    return response


def search_for_supplier(reagent_name: str) -> dict[str, Any]:
    """Stage 3 catalog gap-fill: scoped to supplier domains, basic depth."""
    payload = {
        "query": f"{reagent_name} catalog number",
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": False,
        "include_raw_content": False,
        "include_domains": SUPPLIER_DOMAINS,
    }
    cached = cache.get("tavily/gap_fill", payload, _GAP_FILL_TTL)
    if cached is not None:
        return cached

    response = _client().search(**payload)
    cache.put("tavily/gap_fill", payload, response)
    return response


def search_for_pricing(vendor: str, vendor_domain: str, sku: str) -> dict[str, Any]:
    """Stage 4 budget pricing: single-vendor, full raw content for price extraction."""
    payload = {
        "query": f"{vendor} {sku} price",
        "search_depth": "basic",
        "max_results": 1,
        "include_answer": False,
        "include_raw_content": True,
        "include_domains": [vendor_domain],
    }
    cached = cache.get("tavily/pricing", payload, _PRICING_TTL)
    if cached is not None:
        return cached

    response = _client().search(**payload)
    cache.put("tavily/pricing", payload, response)
    return response

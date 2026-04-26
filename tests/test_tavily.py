"""Tests for the Tavily client (Stage 3/4) and the shared file cache.

Scope after the Stage 1 swap to Europe PMC:
  - TestCacheLayer ............ shared cache used by every external client
  - TestSupplierGapFillWrapper . Stage 3 (catalog # gap-fill on supplier sites)
  - TestPricingWrapper ......... Stage 4 (per-vendor product-page price lookup)
  - TestErrorPaths ............. Missing API key error message

The previous lit-review Tavily tests (request shape, sample-query integrity,
live API hits for the three bioscience samples) were removed because Stage 1
now runs on Europe PMC — those concerns are covered in tests/test_europe_pmc.py.

Run all (live tests skipped if key missing):
  pytest tests/test_tavily.py

Skip live (CI / no creds):
  pytest tests/test_tavily.py -m "not live"
"""

from __future__ import annotations

import os
import shutil
import time

import pytest

from src.clients import tavily as tavily_client
from src.lib import cache


# =============================================================================
# Unit tests — cache layer (shared by every external client, including EPMC)
# =============================================================================

class TestCacheLayer:
    def test_round_trip_get_after_put(self):
        cache.put("test", {"q": "rt"}, {"value": 1})
        assert cache.get("test", {"q": "rt"}, ttl_seconds=60) == {"value": 1}

    def test_distinct_payloads_have_distinct_entries(self):
        cache.put("test", {"q": "alpha"}, {"id": "a"})
        cache.put("test", {"q": "beta"}, {"id": "b"})
        assert cache.get("test", {"q": "alpha"}, ttl_seconds=60) == {"id": "a"}
        assert cache.get("test", {"q": "beta"}, ttl_seconds=60) == {"id": "b"}

    def test_miss_returns_none(self):
        assert cache.get("test", {"q": "never_seen_unique_3719"}, ttl_seconds=60) is None

    def test_distinct_namespaces_dont_collide(self):
        cache.put("ns_a", {"q": "shared"}, {"who": "a"})
        cache.put("ns_b", {"q": "shared"}, {"who": "b"})
        assert cache.get("ns_a", {"q": "shared"}, ttl_seconds=60) == {"who": "a"}
        assert cache.get("ns_b", {"q": "shared"}, ttl_seconds=60) == {"who": "b"}

    def test_ttl_expires_old_entries(self):
        payload = {"q": "ttl_test"}
        cache.put("test", payload, {"v": 1})
        path = cache.CACHE_DIR / cache._key("test", payload)
        old = time.time() - 3600
        os.utime(path, (old, old))
        assert cache.get("test", payload, ttl_seconds=60) is None

    def test_canonicalization_ignores_key_order(self):
        cache.put("test", {"a": 1, "b": 2}, {"v": "ok"})
        assert cache.get("test", {"b": 2, "a": 1}, ttl_seconds=60) == {"v": "ok"}


# =============================================================================
# Mocked Tavily client (Stage 3/4 wrappers only)
# =============================================================================

class _CapturingTavilyClient:
    """Stand-in for tavily.TavilyClient that records the kwargs passed to .search()."""

    last_kwargs: dict = {}
    call_count: int = 0
    return_value: dict = {"results": [], "answer": ""}

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, **kwargs):
        type(self).last_kwargs = kwargs
        type(self).call_count += 1
        return type(self).return_value


@pytest.fixture
def fake_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "fake-test-key")
    monkeypatch.setattr(tavily_client, "TavilyClient", _CapturingTavilyClient)
    # Wipe Stage 3/4 cache namespaces so each mocked test exercises the wire path.
    for namespace in ("tavily/gap_fill", "tavily/pricing"):
        shutil.rmtree(cache.CACHE_DIR / namespace, ignore_errors=True)
    _CapturingTavilyClient.call_count = 0
    _CapturingTavilyClient.last_kwargs = {}
    _CapturingTavilyClient.return_value = {
        "results": [{"title": "x", "url": "https://x"}],
        "answer": "summary",
    }
    yield _CapturingTavilyClient


# =============================================================================
# Stage 3 — supplier gap-fill wrapper (mocked)
# =============================================================================

class TestSupplierGapFillWrapper:
    def test_uses_basic_search_depth(self, fake_tavily):
        tavily_client.search_for_supplier("Tris-HCl buffer")
        assert fake_tavily.last_kwargs["search_depth"] == "basic"

    def test_includes_sigma_aldrich_domain(self, fake_tavily):
        tavily_client.search_for_supplier("any reagent")
        assert "sigmaaldrich.com" in fake_tavily.last_kwargs["include_domains"]

    def test_includes_thermo_fisher_domain(self, fake_tavily):
        tavily_client.search_for_supplier("any reagent")
        assert "thermofisher.com" in fake_tavily.last_kwargs["include_domains"]

    def test_includes_addgene_domain(self, fake_tavily):
        tavily_client.search_for_supplier("any reagent")
        assert "addgene.org" in fake_tavily.last_kwargs["include_domains"]

    def test_includes_atcc_domain(self, fake_tavily):
        tavily_client.search_for_supplier("any reagent")
        assert "atcc.org" in fake_tavily.last_kwargs["include_domains"]

    def test_query_includes_catalog_number_keyword(self, fake_tavily):
        tavily_client.search_for_supplier("Tris buffer")
        assert "catalog number" in fake_tavily.last_kwargs["query"]


# =============================================================================
# Stage 4 — pricing wrapper (mocked)
# =============================================================================

class TestPricingWrapper:
    def test_scopes_to_single_vendor_domain(self, fake_tavily):
        tavily_client.search_for_pricing("Sigma-Aldrich", "sigmaaldrich.com", "T9531")
        assert fake_tavily.last_kwargs["include_domains"] == ["sigmaaldrich.com"]

    def test_requests_full_raw_content_for_price_extraction(self, fake_tavily):
        tavily_client.search_for_pricing("Thermo Fisher", "thermofisher.com", "AM2616")
        assert fake_tavily.last_kwargs["include_raw_content"] is True

    def test_only_fetches_top_one_result(self, fake_tavily):
        tavily_client.search_for_pricing("Promega", "promega.com", "M3001")
        assert fake_tavily.last_kwargs["max_results"] == 1

    def test_query_includes_vendor_sku_and_price_keyword(self, fake_tavily):
        tavily_client.search_for_pricing("Acme Bio", "acmebio.example", "SKU-UNIQUE-92417")
        query = fake_tavily.last_kwargs["query"]
        assert "Acme Bio" in query
        assert "SKU-UNIQUE-92417" in query
        assert "price" in query


# =============================================================================
# Error paths
# =============================================================================

class TestErrorPaths:
    def test_missing_api_key_raises_friendly_error(self, monkeypatch):
        """search_for_supplier fails with a clear error when the env var is unset."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            tavily_client.search_for_supplier("anything")

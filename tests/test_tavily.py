"""Test cases for the Tavily client and the smoke-test sample queries.

Two layers:
  1. Unit tests (fast, mocked) — validate cache, parameter shapes, error paths.
  2. Live integration tests — hit real Tavily; skipped if TAVILY_API_KEY is
     not set. Marked `@pytest.mark.live` so you can deselect them.

One test method per sample query (no parametrization) so failures point at
exactly which sample broke.

Run all (live tests skipped if key missing):
  pytest tests/test_tavily.py

Skip live (CI / no creds):
  pytest tests/test_tavily.py -m "not live"

Live only:
  pytest tests/test_tavily.py -m live -v

Verbose with output:
  pytest tests/test_tavily.py -v -s
"""

from __future__ import annotations

import os
import time

import pytest

from src.clients import tavily as tavily_client
from src.lib import cache
from lit_review_pipeline.tavily_smoke import SAMPLE_QUERIES


# =============================================================================
# Unit tests — cache layer
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
# Mocked Tavily client
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
    _CapturingTavilyClient.call_count = 0
    _CapturingTavilyClient.last_kwargs = {}
    _CapturingTavilyClient.return_value = {
        "results": [{"title": "x", "url": "https://x"}],
        "answer": "summary",
    }
    yield _CapturingTavilyClient


# =============================================================================
# Unit tests — Stage 1 lit-review wrapper (mocked)
# =============================================================================

class TestLitReviewWrapper:
    def test_passes_advanced_search_depth(self, fake_tavily):
        tavily_client.search_for_lit_review("trehalose cryo HeLa")
        assert fake_tavily.last_kwargs["search_depth"] == "advanced"

    def test_requests_synthesized_answer(self, fake_tavily):
        tavily_client.search_for_lit_review("any")
        assert fake_tavily.last_kwargs["include_answer"] is True

    def test_does_not_filter_by_recency(self, fake_tavily):
        """Lit QC must surface foundational papers regardless of age — no `days` filter."""
        tavily_client.search_for_lit_review("any")
        assert "days" not in fake_tavily.last_kwargs

    def test_does_not_request_raw_content(self, fake_tavily):
        """Snippets are enough for novelty classification; raw content blows up tokens."""
        tavily_client.search_for_lit_review("any")
        assert fake_tavily.last_kwargs.get("include_raw_content") is False

    def test_max_results_is_5(self, fake_tavily):
        tavily_client.search_for_lit_review("any")
        assert fake_tavily.last_kwargs["max_results"] == 5

    def test_cache_hit_skips_second_api_call(self, fake_tavily):
        tavily_client.search_for_lit_review("query that will be cached")
        tavily_client.search_for_lit_review("query that will be cached")
        assert fake_tavily.call_count == 1

    def test_distinct_queries_each_hit_api(self, fake_tavily):
        tavily_client.search_for_lit_review("query one")
        tavily_client.search_for_lit_review("query two")
        assert fake_tavily.call_count == 2


# =============================================================================
# Unit tests — Stage 3 supplier gap-fill wrapper (mocked)
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
# Unit tests — Stage 4 pricing wrapper (mocked)
# =============================================================================

class TestPricingWrapper:
    def test_scopes_to_single_vendor_domain(self, fake_tavily):
        tavily_client.search_for_pricing("sigmaaldrich.com", "T9531")
        assert fake_tavily.last_kwargs["include_domains"] == ["sigmaaldrich.com"]

    def test_requests_full_raw_content_for_price_extraction(self, fake_tavily):
        tavily_client.search_for_pricing("thermofisher.com", "AM2616")
        assert fake_tavily.last_kwargs["include_raw_content"] is True

    def test_only_fetches_top_one_result(self, fake_tavily):
        tavily_client.search_for_pricing("promega.com", "M3001")
        assert fake_tavily.last_kwargs["max_results"] == 1


# =============================================================================
# Unit tests — error paths
# =============================================================================

class TestErrorPaths:
    def test_missing_api_key_raises_friendly_error(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            tavily_client.search_for_lit_review("anything")


# =============================================================================
# Unit tests — sample query fixtures (one test method per sample)
# =============================================================================

class TestSampleSetIntegrity:
    def test_sample_set_is_bioscience_only(self):
        """Climate (Sporomusa) sample was dropped when scope narrowed to bioscience."""
        assert set(SAMPLE_QUERIES.keys()) == {"trehalose", "crp", "lactobacillus"}

    def test_no_sporomusa_sample_remains(self):
        assert "sporomusa" not in SAMPLE_QUERIES

    def test_no_sample_uses_climate_domain(self):
        for name, meta in SAMPLE_QUERIES.items():
            assert meta["domain"] != "climate", f"{name} domain should not be 'climate'"


class TestTrehaloseSample:
    def test_query_is_present_and_non_empty(self):
        assert SAMPLE_QUERIES["trehalose"]["query"]

    def test_domain_is_cell_biology(self):
        assert SAMPLE_QUERIES["trehalose"]["domain"] == "cell_biology"

    def test_query_word_count_in_range(self):
        words = len(SAMPLE_QUERIES["trehalose"]["query"].split())
        assert 5 <= words <= 25, f"query has {words} words; expected 5-25"

    def test_query_mentions_trehalose(self):
        assert "trehalose" in SAMPLE_QUERIES["trehalose"]["query"].lower()

    def test_query_has_no_recency_hints(self):
        q = SAMPLE_QUERIES["trehalose"]["query"].lower()
        for bad in ("recent", "latest", "2024", "2025", "2026"):
            assert bad not in q, f"forbidden recency hint '{bad}' in query"


class TestCrpSample:
    def test_query_is_present_and_non_empty(self):
        assert SAMPLE_QUERIES["crp"]["query"]

    def test_domain_is_diagnostics(self):
        assert SAMPLE_QUERIES["crp"]["domain"] == "diagnostics"

    def test_query_word_count_in_range(self):
        words = len(SAMPLE_QUERIES["crp"]["query"].split())
        assert 5 <= words <= 25, f"query has {words} words; expected 5-25"

    def test_query_mentions_biosensor_or_crp(self):
        q = SAMPLE_QUERIES["crp"]["query"].lower()
        assert "biosensor" in q or "crp" in q or "c-reactive protein" in q

    def test_query_has_no_recency_hints(self):
        q = SAMPLE_QUERIES["crp"]["query"].lower()
        for bad in ("recent", "latest", "2024", "2025", "2026"):
            assert bad not in q, f"forbidden recency hint '{bad}' in query"


class TestLactobacillusSample:
    def test_query_is_present_and_non_empty(self):
        assert SAMPLE_QUERIES["lactobacillus"]["query"]

    def test_domain_is_gut_health(self):
        assert SAMPLE_QUERIES["lactobacillus"]["domain"] == "gut_health"

    def test_query_word_count_in_range(self):
        words = len(SAMPLE_QUERIES["lactobacillus"]["query"].split())
        assert 5 <= words <= 25, f"query has {words} words; expected 5-25"

    def test_query_mentions_lactobacillus(self):
        assert "lactobacillus" in SAMPLE_QUERIES["lactobacillus"]["query"].lower()

    def test_query_has_no_recency_hints(self):
        q = SAMPLE_QUERIES["lactobacillus"]["query"].lower()
        for bad in ("recent", "latest", "2024", "2025", "2026"):
            assert bad not in q, f"forbidden recency hint '{bad}' in query"


# =============================================================================
# Live integration tests — one method per sample. Skipped without TAVILY_API_KEY.
# =============================================================================

@pytest.mark.live
class TestLiveTrehalose:
    def test_returns_results(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["trehalose"]["query"])
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_returns_synthesized_answer(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["trehalose"]["query"])
        assert result.get("answer"), "Tavily should return synthesized answer when include_answer=True"
        assert len(result["answer"]) > 50

    def test_results_have_titles_and_urls(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["trehalose"]["query"])
        for r in result["results"]:
            assert r.get("title")
            assert r.get("url", "").startswith("http")

    def test_top_results_topically_relevant(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["trehalose"]["query"])
        results = result.get("results", [])
        if not results:
            pytest.skip("Tavily returned no results")
        haystack = " ".join(
            (r.get("title", "") + " " + (r.get("content", "") or ""))
            for r in results[:3]
        ).lower()
        assert "trehalose" in haystack, "term 'trehalose' missing from top 3 result content"


@pytest.mark.live
class TestLiveCrp:
    def test_returns_results(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["crp"]["query"])
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_returns_synthesized_answer(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["crp"]["query"])
        assert result.get("answer"), "Tavily should return synthesized answer when include_answer=True"
        assert len(result["answer"]) > 50

    def test_results_have_titles_and_urls(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["crp"]["query"])
        for r in result["results"]:
            assert r.get("title")
            assert r.get("url", "").startswith("http")

    def test_top_results_topically_relevant(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["crp"]["query"])
        results = result.get("results", [])
        if not results:
            pytest.skip("Tavily returned no results")
        haystack = " ".join(
            (r.get("title", "") + " " + (r.get("content", "") or ""))
            for r in results[:3]
        ).lower()
        assert "crp" in haystack or "c-reactive protein" in haystack, (
            "CRP / C-reactive protein term missing from top 3 result content"
        )


@pytest.mark.live
class TestLiveLactobacillus:
    def test_returns_results(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["lactobacillus"]["query"])
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_returns_synthesized_answer(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["lactobacillus"]["query"])
        assert result.get("answer"), "Tavily should return synthesized answer when include_answer=True"
        assert len(result["answer"]) > 50

    def test_results_have_titles_and_urls(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["lactobacillus"]["query"])
        for r in result["results"]:
            assert r.get("title")
            assert r.get("url", "").startswith("http")

    def test_top_results_topically_relevant(self, has_tavily_key):
        result = tavily_client.search_for_lit_review(SAMPLE_QUERIES["lactobacillus"]["query"])
        results = result.get("results", [])
        if not results:
            pytest.skip("Tavily returned no results")
        haystack = " ".join(
            (r.get("title", "") + " " + (r.get("content", "") or ""))
            for r in results[:3]
        ).lower()
        assert "lactobacillus" in haystack, "term 'lactobacillus' missing from top 3 result content"

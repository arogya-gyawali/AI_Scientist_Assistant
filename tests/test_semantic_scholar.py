"""Test cases for the Semantic Scholar client and the Stage 1 sample queries.

Two layers:
  1. Unit tests (mocked) — validate cache reuse, request shape, header injection.
  2. Live integration tests — hit the real Semantic Scholar API; skipped if
     SEMANTIC_SCHOLAR_API_KEY is not set OR if a 60s ping fails. Marked
     `@pytest.mark.live`.

Run all (live skipped if no network):
  pytest tests/test_semantic_scholar.py

Skip live (CI / no network):
  pytest tests/test_semantic_scholar.py -m "not live"
"""

from __future__ import annotations

import os
import shutil

import pytest

from src.clients import semantic_scholar as ss
from src.lib import cache
from lit_review_pipeline.semantic_scholar_smoke import SAMPLE_QUERIES


# =============================================================================
# Mocked Semantic Scholar HTTP transport
# =============================================================================

class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _CapturingHttpx:
    last_url: str = ""
    last_params: dict = {}
    last_headers: dict = {}
    call_count: int = 0
    return_payload: dict = {"data": []}

    @classmethod
    def get(cls, url, params=None, headers=None, timeout=None):
        cls.last_url = url
        cls.last_params = dict(params or {})
        cls.last_headers = dict(headers or {})
        cls.call_count += 1
        return _FakeResponse(cls.return_payload)


@pytest.fixture
def fake_httpx(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setattr(ss, "httpx", _CapturingHttpx)
    # Wipe SS cache between mocked tests so every test exercises the wire path.
    shutil.rmtree(cache.CACHE_DIR / "semantic_scholar/lit_review", ignore_errors=True)
    _CapturingHttpx.call_count = 0
    _CapturingHttpx.last_url = ""
    _CapturingHttpx.last_params = {}
    _CapturingHttpx.last_headers = {}
    _CapturingHttpx.return_payload = {
        "data": [{"title": "fake paper", "url": "https://example.com"}]
    }
    yield _CapturingHttpx


# =============================================================================
# Unit tests — wrapper request shape
# =============================================================================

class TestSearchRequestShape:
    def test_hits_paper_search_endpoint(self, fake_httpx):
        ss.search_for_lit_review("any query")
        assert fake_httpx.last_url.endswith("/paper/search")

    def test_passes_query_param(self, fake_httpx):
        ss.search_for_lit_review("trehalose cryo HeLa")
        assert fake_httpx.last_params["query"] == "trehalose cryo HeLa"

    def test_default_limit_is_5(self, fake_httpx):
        ss.search_for_lit_review("any query")
        assert fake_httpx.last_params["limit"] == 5

    def test_custom_limit_passes_through(self, fake_httpx):
        ss.search_for_lit_review("any query", limit=10)
        assert fake_httpx.last_params["limit"] == 10

    def test_requests_required_fields(self, fake_httpx):
        ss.search_for_lit_review("any query")
        fields = fake_httpx.last_params["fields"]
        for required in ("title", "abstract", "year", "venue", "authors.name", "externalIds", "tldr"):
            assert required in fields, f"missing field: {required}"

    def test_user_agent_header_set(self, fake_httpx):
        ss.search_for_lit_review("any query")
        assert "ai-scientist-assistant" in fake_httpx.last_headers.get("User-Agent", "")

    def test_no_api_key_header_when_env_unset(self, fake_httpx):
        ss.search_for_lit_review("any query")
        assert "x-api-key" not in fake_httpx.last_headers


class TestApiKeyAuth:
    def test_api_key_header_injected_when_env_set(self, monkeypatch, fake_httpx):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key-abc")
        ss.search_for_lit_review("any query")
        assert fake_httpx.last_headers.get("x-api-key") == "test-key-abc"


# =============================================================================
# Unit tests — cache reuse
# =============================================================================

class TestCacheReuse:
    def test_second_call_with_same_query_skips_api(self, fake_httpx):
        ss.search_for_lit_review("cached query")
        ss.search_for_lit_review("cached query")
        assert fake_httpx.call_count == 1

    def test_distinct_queries_each_hit_api(self, fake_httpx):
        ss.search_for_lit_review("query one")
        ss.search_for_lit_review("query two")
        assert fake_httpx.call_count == 2


# =============================================================================
# Sample query integrity
# =============================================================================

class TestSampleQueries:
    def test_three_bioscience_samples(self):
        assert set(SAMPLE_QUERIES.keys()) == {"trehalose", "crp", "lactobacillus"}

    @pytest.mark.parametrize("name", list(SAMPLE_QUERIES.keys()))
    def test_each_sample_has_query_and_domain(self, name):
        meta = SAMPLE_QUERIES[name]
        assert meta.get("query")
        assert meta.get("domain")


# =============================================================================
# Live integration tests — skipped without network
# =============================================================================

@pytest.mark.live
class TestLiveSemanticScholar:
    """Hit the real Semantic Scholar API. No API key required for low RPM,
    but tests will skip cleanly if the network is down or SS rate-limits us.
    """

    def _try_call(self, query: str):
        try:
            return ss.search_for_lit_review(query)
        except Exception as exc:
            pytest.skip(f"Semantic Scholar unavailable: {exc}")

    def test_trehalose_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["trehalose"]["query"])
        assert result.get("data"), "Expected at least one paper for trehalose query"

    def test_crp_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["crp"]["query"])
        assert result.get("data"), "Expected at least one paper for CRP query"

    def test_lactobacillus_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["lactobacillus"]["query"])
        assert result.get("data"), "Expected at least one paper for lactobacillus query"

    def test_returned_papers_have_authors(self):
        """The headline value of switching to SS — authors come back structured."""
        result = self._try_call(SAMPLE_QUERIES["lactobacillus"]["query"])
        papers = result.get("data") or []
        if not papers:
            pytest.skip("no papers returned")
        with_authors = [p for p in papers if p.get("authors")]
        assert with_authors, "Expected at least one paper with structured authors"

    def test_returned_papers_have_venue_or_year(self):
        result = self._try_call(SAMPLE_QUERIES["crp"]["query"])
        papers = result.get("data") or []
        if not papers:
            pytest.skip("no papers returned")
        with_metadata = [p for p in papers if p.get("year") or p.get("venue")]
        assert with_metadata, "Expected at least one paper with year or venue"

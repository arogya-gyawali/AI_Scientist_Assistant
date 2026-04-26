"""Test cases for the Europe PMC client and the Stage 1 sample queries.

Two layers:
  1. Unit tests (mocked) — validate cache reuse, request shape.
  2. Live integration tests — hit the real Europe PMC API; skipped if the
     network is down or EPMC is unreachable. Marked `@pytest.mark.live`.

Run all (live skipped if no network):
  pytest tests/test_europe_pmc.py
"""

from __future__ import annotations

import shutil

import pytest

from src.clients import europe_pmc as epmc
from src.lib import cache
from lit_review_pipeline.europe_pmc_smoke import SAMPLE_QUERIES


# =============================================================================
# Mocked transport
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


class _FakeClient:
    """Stand-in for httpx.Client. Captures the per-request kwargs for assertions."""
    last_url: str = ""
    last_params: dict = {}
    last_headers: dict = {}
    call_count: int = 0
    return_payload: dict = {"resultList": {"result": []}}

    def get(self, url, params=None, headers=None, **_kwargs):
        type(self).last_url = url
        type(self).last_params = dict(params or {})
        type(self).last_headers = dict(headers or {})
        type(self).call_count += 1
        return _FakeResponse(self.return_payload)


@pytest.fixture
def fake_httpx(monkeypatch):
    """Patch the module-level pooled client with a capturing fake.

    The real client is now an `httpx.Client()` instance (for connection
    pooling); tests replace it with `_FakeClient` and inspect the recorded
    kwargs after each call.
    """
    fake = _FakeClient()
    monkeypatch.setattr(epmc, "_client", fake)
    shutil.rmtree(cache.CACHE_DIR / "europe_pmc/lit_review", ignore_errors=True)
    _FakeClient.call_count = 0
    _FakeClient.last_url = ""
    _FakeClient.last_params = {}
    _FakeClient.last_headers = {}
    _FakeClient.return_payload = {
        "resultList": {"result": [{"title": "fake paper", "doi": "10.1/x"}]},
        "hitCount": 1,
    }
    yield _FakeClient


# =============================================================================
# Unit tests — request shape
# =============================================================================

class TestSearchRequestShape:
    def test_hits_search_endpoint(self, fake_httpx):
        epmc.search_for_lit_review("any")
        assert fake_httpx.last_url.endswith("/search")

    def test_passes_query_param(self, fake_httpx):
        epmc.search_for_lit_review("trehalose cryo HeLa")
        assert fake_httpx.last_params["query"] == "trehalose cryo HeLa"

    def test_default_page_size_is_5(self, fake_httpx):
        epmc.search_for_lit_review("any")
        assert fake_httpx.last_params["pageSize"] == 5

    def test_custom_page_size_passes_through(self, fake_httpx):
        epmc.search_for_lit_review("any", page_size=10)
        assert fake_httpx.last_params["pageSize"] == 10

    def test_requests_json_format(self, fake_httpx):
        epmc.search_for_lit_review("any")
        assert fake_httpx.last_params["format"] == "json"

    def test_requests_core_result_type(self, fake_httpx):
        """`core` includes abstract + author list; `lite` omits them."""
        epmc.search_for_lit_review("any")
        assert fake_httpx.last_params["resultType"] == "core"

    def test_user_agent_header_set(self, fake_httpx):
        epmc.search_for_lit_review("any")
        assert "ai-scientist-assistant" in fake_httpx.last_headers.get("User-Agent", "")


# =============================================================================
# Unit tests — cache reuse
# =============================================================================

class TestCacheReuse:
    def test_second_call_with_same_query_skips_api(self, fake_httpx):
        epmc.search_for_lit_review("cached query")
        epmc.search_for_lit_review("cached query")
        assert fake_httpx.call_count == 1

    def test_distinct_queries_each_hit_api(self, fake_httpx):
        epmc.search_for_lit_review("query one")
        epmc.search_for_lit_review("query two")
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
# Live integration — skipped without network
# =============================================================================

@pytest.mark.live
class TestLiveEuropePmc:
    """Hit real Europe PMC API. No auth required."""

    def _try_call(self, query: str):
        try:
            return epmc.search_for_lit_review(query)
        except Exception as exc:
            pytest.skip(f"Europe PMC unavailable: {exc}")

    def test_trehalose_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["trehalose"]["query"])
        papers = (result.get("resultList") or {}).get("result") or []
        assert papers, "Expected at least one paper for trehalose query"

    def test_crp_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["crp"]["query"])
        papers = (result.get("resultList") or {}).get("result") or []
        assert papers, "Expected at least one paper for CRP query"

    def test_lactobacillus_returns_papers(self):
        result = self._try_call(SAMPLE_QUERIES["lactobacillus"]["query"])
        papers = (result.get("resultList") or {}).get("result") or []
        assert papers, "Expected at least one paper for lactobacillus query"

    def test_returned_papers_have_authors(self):
        result = self._try_call(SAMPLE_QUERIES["lactobacillus"]["query"])
        papers = (result.get("resultList") or {}).get("result") or []
        if not papers:
            pytest.skip("no papers returned")
        with_authors = [
            p for p in papers
            if (p.get("authorList") or {}).get("author") or p.get("authorString")
        ]
        assert with_authors, "Expected at least one paper with authors"

    def test_returned_papers_have_year_and_venue(self):
        result = self._try_call(SAMPLE_QUERIES["crp"]["query"])
        papers = (result.get("resultList") or {}).get("result") or []
        if not papers:
            pytest.skip("no papers returned")
        with_year = [p for p in papers if p.get("pubYear")]
        with_venue = [p for p in papers if (p.get("journalInfo") or {}).get("journal")]
        assert with_year, "Expected at least one paper with pubYear"
        assert with_venue, "Expected at least one paper with journal info"

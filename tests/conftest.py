"""Shared pytest fixtures and markers for the AI Scientist test suite."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: marks tests that hit live external APIs. Skipped automatically "
        "when the relevant API key isn't set. Deselect with -m 'not live'.",
    )


@pytest.fixture(scope="session", autouse=True)
def _isolate_cache(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Redirect the file-based cache to a temp dir for the whole session.

    Keeps tests from polluting the real .cache/ in the repo, but still allows
    cache hits within a single test run (so live tests don't double-bill us
    on Tavily for repeated queries within the suite).
    """
    from src.lib import cache

    cache.CACHE_DIR = tmp_path_factory.mktemp("test_cache")


@pytest.fixture(scope="session")
def _env_loaded() -> None:
    load_dotenv()


@pytest.fixture
def has_tavily_key(_env_loaded) -> str:
    """Skip the test if TAVILY_API_KEY isn't available."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        pytest.skip("TAVILY_API_KEY not set; skipping live test")
    return key

"""Tests for protocol_pipeline.sources — DraftJS parsing, language detect,
and full-bundle normalization against the static samples committed to the
repo. These run offline (no network) so they're safe in CI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocol_pipeline.sources import (
    NormalizedProtocol,
    detect_language,
    load_all_samples,
    load_sample,
    normalize_bundle,
    parse_draftjs,
)


# ---- DraftJS parsing -----------------------------------------------------

def test_parse_draftjs_unstyled_blocks():
    raw = json.dumps({"blocks": [
        {"key": "a", "text": "Wash cells.", "type": "unstyled", "depth": 0},
        {"key": "b", "text": "Pellet at 300g.", "type": "unstyled", "depth": 0},
    ]})
    assert parse_draftjs(raw) == "Wash cells.\nPellet at 300g."


def test_parse_draftjs_list_items_get_markers():
    raw = json.dumps({"blocks": [
        {"key": "a", "text": "Reagents:", "type": "unstyled", "depth": 0},
        {"key": "b", "text": "PBS", "type": "unordered-list-item", "depth": 0},
        {"key": "c", "text": "Trypsin", "type": "unordered-list-item", "depth": 0},
    ]})
    out = parse_draftjs(raw)
    assert "- PBS" in out
    assert "- Trypsin" in out


def test_parse_draftjs_handles_empty_and_garbage():
    assert parse_draftjs(None) == ""
    assert parse_draftjs("") == ""
    # Non-JSON string falls through to plaintext (HTML-stripped).
    assert parse_draftjs("<p>Plain HTML</p>") == "Plain HTML"


def test_parse_draftjs_skips_blank_blocks():
    raw = json.dumps({"blocks": [
        {"key": "a", "text": "", "type": "unstyled"},
        {"key": "b", "text": "Real text.", "type": "unstyled"},
    ]})
    assert parse_draftjs(raw) == "Real text."


# ---- Language detection --------------------------------------------------

def test_detect_language_english():
    assert detect_language("Wash cells with PBS, then centrifuge for 5 min.") == "en"


def test_detect_language_spanish():
    # Spanish stopwords + diacritics — same shape as the trehalose top hit.
    text = "1er lavado con 10 ml de tampón M9 estéril a temperatura ambiente"
    assert detect_language(text) == "es"


def test_detect_language_empty():
    assert detect_language("") == "unknown"


# ---- Bundle normalization against the real samples ----------------------

@pytest.mark.parametrize("name,expected_lang,min_steps", [
    ("trehalose", "es", 10),
    ("crp", "en", 25),
    ("lactobacillus", "en", 5),
])
def test_real_samples_normalize_cleanly(name, expected_lang, min_steps):
    norm = load_sample(name)
    assert norm is not None
    assert norm.id  # non-empty protocol id
    assert norm.title
    assert norm.language == expected_lang
    assert len(norm.steps) >= min_steps
    # Step bodies must be plaintext, not raw DraftJS JSON.
    for s in norm.steps[:3]:
        assert not s.text.startswith("{"), f"step body still looks like JSON: {s.text[:40]}"
        assert s.id  # every step has a stable ref id


def test_load_all_samples_returns_three():
    all_samples = load_all_samples()
    assert set(all_samples.keys()) >= {"trehalose", "crp", "lactobacillus"}


def test_section_headers_html_stripped():
    """protocols.io ships section headers as <p>Methods</p>. After normalization
    nothing should still contain the wrapper tags."""
    for name in ("trehalose", "crp", "lactobacillus"):
        norm = load_sample(name)
        for step in norm.steps:
            assert "<p>" not in step.section
            assert "</p>" not in step.section


def test_normalize_bundle_empty_search_returns_none():
    assert normalize_bundle({"search": {"items": []}}) is None
    assert normalize_bundle({}) is None

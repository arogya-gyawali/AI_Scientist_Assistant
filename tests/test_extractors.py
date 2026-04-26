"""Tests for deterministic field extractors used by Stage 1 lit review.

These exercise the regex / URL-mapping / author-validation logic that runs
after the LLM classifier returns. The point is to catch a class of LLM
hallucinations (fake authors, wrong years, made-up venues) without re-doing
the LLM's job.

Also covers the post-processing helpers in lit_review_pipeline/stage.py
(HTML-strip on titles, sentence-cap on summaries).

Run:
  pytest tests/test_extractors.py -v
"""

from __future__ import annotations

import pytest

from lit_review_pipeline.extractors import (
    extract_doi,
    extract_venue,
    extract_year,
    validate_authors,
)
from lit_review_pipeline.stage import _clean_text, _truncate_to_n_sentences


# =============================================================================
# year (4 tests)
# =============================================================================

def test_year_from_url_path():
    """Frontiers URL embeds the year in the article path: .../fmicb.2025.1580171/full"""
    url = "https://www.frontiersin.org/journals/microbiology/articles/10.3389/fmicb.2025.1580171/full"
    assert extract_year(url, None, None) == 2025


def test_year_from_content_when_url_lacks_year():
    """Most PMC URLs have no year — fall back to content head."""
    content = "Khailova et al. published in Clin Nutr 2017 Dec;36(6):1549–1557, demonstrating..."
    assert extract_year("https://pmc.ncbi.nlm.nih.gov/articles/PMC5602551/", None, content) == 2017


def test_year_returns_none_when_no_year_anywhere():
    assert extract_year("https://example.com/article", "Some paper", "no year mentioned in this snippet") is None


def test_year_rejects_non_year_numbers():
    """Pure quantitative content (concentrations, sample sizes) shouldn't yield a year."""
    content = "Sample sizes ranged from 5 to 100, with concentrations of 25, 50, and 200 mg/mL."
    assert extract_year(None, None, content) is None


# =============================================================================
# doi (3 tests)
# =============================================================================

def test_doi_from_url():
    """A doi.org URL contains the DOI verbatim."""
    url = "https://doi.org/10.1371/journal.pone.0080169"
    assert extract_doi(url, None) == "10.1371/journal.pone.0080169"


def test_doi_from_content_strips_trailing_punctuation():
    """DOIs cited in prose often have trailing periods or commas; we strip them."""
    content = "See Khailova et al., doi: 10.1016/j.clnu.2016.09.025."
    assert extract_doi(None, content) == "10.1016/j.clnu.2016.09.025"


def test_doi_returns_none_when_absent():
    assert extract_doi("https://example.com/article", "no doi in here, just words") is None


# =============================================================================
# venue (3 tests, including hallucination guard)
# =============================================================================

def test_venue_known_host_plos_one():
    url = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0080169"
    assert extract_venue(url) == "PLoS ONE"


def test_venue_known_host_frontiers_microbiology():
    url = "https://www.frontiersin.org/journals/microbiology/articles/10.3389/fmicb.2025.1580171/full"
    assert extract_venue(url) == "Frontiers in Microbiology"


def test_venue_unknown_host_returns_none():
    """Refusal to guess is the whole point — caller decides what to render."""
    assert extract_venue("https://random-blog.example.org/paper-on-cells") is None


# =============================================================================
# validate_authors — the headline hallucination guard (1 test)
# =============================================================================

# =============================================================================
# Post-process: HTML-clean titles (Europe PMC sometimes returns <i>...</i>)
# =============================================================================

def test_clean_text_strips_italics_tags():
    raw = "<i>Lactobacillus rhamnosus</i> GG attenuates MASH"
    assert _clean_text(raw) == "Lactobacillus rhamnosus GG attenuates MASH"


def test_clean_text_decodes_entities_then_strips():
    raw = "&lt;i&gt;Lactobacillus rhamnosus&lt;/i&gt; GG attenuates MASH"
    assert _clean_text(raw) == "Lactobacillus rhamnosus GG attenuates MASH"


def test_clean_text_handles_empty_and_none():
    assert _clean_text(None) is None
    assert _clean_text("") == ""


# =============================================================================
# Post-process: cap summary at 4 sentences
# =============================================================================

def test_truncate_to_n_sentences_keeps_first_four():
    s = "First sentence. Second one. Third one. Fourth one. Fifth one. Sixth one."
    result = _truncate_to_n_sentences(s, n=4)
    assert "Fifth" not in result
    assert "Sixth" not in result
    assert result.endswith("Fourth one.")


def test_truncate_to_n_sentences_passes_through_short_text():
    """If the LLM already obeyed the cap, output is unchanged."""
    s = "Only three sentences here. Like this. Done."
    assert _truncate_to_n_sentences(s, n=4) == s


def test_validate_authors_drops_haub_hallucination():
    """Reproduces the exact bug from a real run: LLM returned authors
    ['J. C. Haub', 'P. Haub', 'C. Haub'] for the Ritze et al. PLOS ONE
    paper on LGG and NAFLD. The Tavily snippet of that paper does not
    contain 'Haub' anywhere. Validator must drop the array entirely
    rather than pass through wrong attribution."""
    fake_authors = ["J. C. Haub", "P. Haub", "C. Haub"]
    real_content = (
        "To determine whether changes in portal LPS levels and intestinal "
        "inflammation could be associated with the intestinal barrier, "
        "we measured the tight junction proteins occludin and claudin-1. "
        "Occludin and claudin-1 protein expression was significantly reduced "
        "in mice fed high-fructose diet compared to control diet. This "
        "reduction was removed following oral treatment of the mice with LGG."
    )
    assert validate_authors(fake_authors, real_content) == []

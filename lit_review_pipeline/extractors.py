"""Deterministic field extraction for lit-review references.

Replaces LLM-extracted `year`, `doi`, `venue` with regex/URL-based parsing
to eliminate a class of LLM hallucination. Post-validates `authors` so a
fake author list (LLM filling a gap with invented names) gets dropped
to an empty array rather than passed through to the UI.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


YEAR_RE = re.compile(r"\b(20[0-3]\d)\b")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


# URL host+path-prefix → venue. Longest prefix wins (sorted at lookup time).
# Bioscience-leaning since that's our scope. Add hosts as we encounter them.
VENUE_BY_HOST_PREFIX: dict[str, str] = {
    "journals.plos.org/plosone": "PLoS ONE",
    "journals.plos.org/plosbiology": "PLoS Biology",
    "journals.plos.org/plosmedicine": "PLoS Medicine",
    "journals.plos.org/plospathogens": "PLoS Pathogens",
    "journals.plos.org/plosgenetics": "PLoS Genetics",
    "journals.plos.org/plosone-archive": "PLoS ONE",
    "frontiersin.org/journals/microbiology": "Frontiers in Microbiology",
    "frontiersin.org/journals/immunology": "Frontiers in Immunology",
    "frontiersin.org/journals/cell-and-developmental-biology": "Frontiers in Cell and Developmental Biology",
    "frontiersin.org/journals/neuroscience": "Frontiers in Neuroscience",
    "frontiersin.org/journals/oncology": "Frontiers in Oncology",
    "frontiersin.org/journals/molecular-biosciences": "Frontiers in Molecular Biosciences",
    "biorxiv.org": "bioRxiv",
    "medrxiv.org": "medRxiv",
    "arxiv.org": "arXiv",
    "elifesciences.org": "eLife",
    "embopress.org/doi/full/10.1038/embor": "EMBO Reports",
    "embopress.org/doi/full/10.15252/embj": "The EMBO Journal",
    "nature.com/articles/s41586": "Nature",
    "nature.com/articles/s41587": "Nature Biotechnology",
    "nature.com/articles/s41591": "Nature Medicine",
    "nature.com/articles/s41592": "Nature Methods",
    "nature.com/articles/s41594": "Nature Structural & Molecular Biology",
    "nature.com/articles/s41589": "Nature Chemical Biology",
    "nature.com/articles/s41576": "Nature Reviews Genetics",
    "nature.com/articles/s41579": "Nature Reviews Microbiology",
    "cell.com/cell/": "Cell",
    "cell.com/cell-host-microbe": "Cell Host & Microbe",
    "cell.com/cell-stem-cell": "Cell Stem Cell",
    "cell.com/cell-reports": "Cell Reports",
    "cell.com/molecular-cell": "Molecular Cell",
    "mdpi.com/2073-4409": "Cells",
    "mdpi.com/2079-6374": "Biosensors",
    "mdpi.com/1422-0067": "International Journal of Molecular Sciences",
    "mdpi.com/2218-273x": "Biomolecules",
    "mdpi.com/2076-2607": "Microorganisms",
    "mdpi.com/2072-6643": "Nutrients",
    "pubs.acs.org/doi/10.1021/acs.analchem": "Analytical Chemistry",
    "pubs.acs.org/doi/10.1021/acsnano": "ACS Nano",
    "pubs.acs.org/doi/10.1021/jacs": "Journal of the American Chemical Society",
}


def extract_year(url: Optional[str], title: Optional[str], content: Optional[str]) -> Optional[int]:
    """Best-effort 4-digit year (2000–2039). Tries URL, title, then content head."""
    for source in (url or "", title or "", (content or "")[:1000]):
        m = YEAR_RE.search(source)
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2039:
                return year
    return None


def extract_doi(url: Optional[str], content: Optional[str]) -> Optional[str]:
    """Match a canonical DOI form anywhere in URL or content. Strips trailing punctuation."""
    for source in (url or "", content or ""):
        m = DOI_RE.search(source)
        if m:
            return m.group(0).rstrip(".,)];:")
    return None


def extract_venue(url: Optional[str]) -> Optional[str]:
    """URL-prefix lookup for known bioscience publishers. None for unknown hosts."""
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host_path = host + parsed.path
    for prefix in sorted(VENUE_BY_HOST_PREFIX, key=len, reverse=True):
        if host_path.startswith(prefix):
            return VENUE_BY_HOST_PREFIX[prefix]
    return None


def validate_authors(authors: Optional[list[str]], content: Optional[str]) -> list[str]:
    """Drop the array when most authors' surnames don't appear in the source
    content. Catches LLM-invented author lists without being so strict that
    a single unmatched name (truncated snippet, transliteration, slight name
    format difference) discards a real list.

    Threshold: at least half of authors must have their longest-token
    (surname proxy) appear in the content. The Haub-hallucination case
    still fails (0/3 matches; 0 * 2 >= 3 is False). For a 2-author paper
    where 1 surname matches, the list is kept (1 * 2 >= 2 is True) —
    erring on the side of preserving real attribution.
    """
    if not authors:
        return []
    if not content:
        return []
    haystack = content.lower()
    matches = 0
    for raw in authors:
        tokens = [t.strip(".,") for t in re.split(r"\s+", str(raw).strip()) if t.strip(".,")]
        if not tokens:
            continue
        surname = max(tokens, key=len).lower()
        if len(surname) >= 2 and surname in haystack:
            matches += 1
    # "at least half": 2x the matches must reach (>=) the count.
    if matches * 2 >= len(authors):
        return authors
    return []

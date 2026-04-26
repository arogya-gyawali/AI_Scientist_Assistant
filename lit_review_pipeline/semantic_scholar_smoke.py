"""Semantic Scholar smoke test — exercise the Stage 1 search path without LLM.

Pre-baked queries for each bioscience sample (skipping the LLM query-rewrite
step), hits Semantic Scholar directly, prints what came back. Lets you confirm:
  - The Semantic Scholar API responds (no key required for low rate)
  - Our test domains actually return useful structured papers
  - The cache is writing under .cache/semantic_scholar/lit_review/

Usage:
  python -m lit_review_pipeline.semantic_scholar_smoke              # all bioscience samples
  python -m lit_review_pipeline.semantic_scholar_smoke trehalose    # run one
  python -m lit_review_pipeline.semantic_scholar_smoke --raw        # full JSON
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from src.clients import semantic_scholar


# Hand-tuned queries that approximate what the LLM query-rewrite step would
# produce for each sample hypothesis.
SAMPLE_QUERIES: dict[str, dict[str, str]] = {
    "trehalose": {
        "domain": "cell_biology",
        "query": "trehalose DMSO cryopreservation HeLa cell post-thaw viability",
    },
    "crp": {
        "domain": "diagnostics",
        "query": "paper-based electrochemical biosensor anti-CRP antibody whole blood detection",
    },
    "lactobacillus": {
        "domain": "gut_health",
        "query": "Lactobacillus rhamnosus GG mice intestinal permeability tight junction occludin claudin",
    },
}


def _print_sample(name: str, payload: dict, raw: bool) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {name.upper()}  ({SAMPLE_QUERIES[name]['domain']})")
    print(f"  Query: {SAMPLE_QUERIES[name]['query']}")
    print("=" * 72)

    if raw:
        print(json.dumps(payload, indent=2))
        return

    papers = payload.get("data") or []
    print(f"\n-- {len(papers)} papers --")
    for i, p in enumerate(papers, 1):
        title = p.get("title") or "(no title)"
        year = p.get("year") if p.get("year") is not None else "n/a"
        venue = p.get("venue") or "(no venue)"
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:5])
        if len((p.get("authors") or [])) > 5:
            authors += " et al."
        external = p.get("externalIds") or {}
        doi = external.get("DOI") or ""
        tldr = (p.get("tldr") or {}).get("text") or ""
        abstract = p.get("abstract") or ""
        body = tldr or abstract
        if len(body) > 280:
            body = body[:280] + "…"

        print(f"\n  [{i}] {title}")
        print(f"      {authors}  ({year})  •  {venue}")
        if doi:
            print(f"      doi: {doi}")
        if body:
            print(f"      {body}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="ss-smoke")
    parser.add_argument("name", nargs="?", choices=list(SAMPLE_QUERIES.keys()))
    parser.add_argument("--raw", action="store_true", help="Print full raw JSON.")
    args = parser.parse_args(argv)

    samples = [args.name] if args.name else list(SAMPLE_QUERIES.keys())
    for name in samples:
        try:
            payload = semantic_scholar.search_for_lit_review(SAMPLE_QUERIES[name]["query"])
            _print_sample(name, payload, args.raw)
        except Exception as exc:
            print(f"\n[FAIL] {name}: {exc}", file=sys.stderr)
            return 1

    print(f"\n{'=' * 72}")
    print(f"  Done. {len(samples)} search(es) ran.")
    print(f"  Cached responses live under .cache/semantic_scholar/lit_review/")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())

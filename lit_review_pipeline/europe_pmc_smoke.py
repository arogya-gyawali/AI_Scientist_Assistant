"""Europe PMC smoke test — exercise the Stage 1 search path without LLM.

Pre-baked queries for each bioscience sample, hits Europe PMC directly,
prints what came back. Lets you confirm:
  - Europe PMC API is reachable (no auth required)
  - Our test domains return useful biomedical papers
  - The cache writes under .cache/europe_pmc/lit_review/

Usage:
  python -m lit_review_pipeline.europe_pmc_smoke              # all bioscience samples
  python -m lit_review_pipeline.europe_pmc_smoke trehalose    # run one
  python -m lit_review_pipeline.europe_pmc_smoke --raw        # full JSON
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from src.clients import europe_pmc


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

    papers = (payload.get("resultList") or {}).get("result") or []
    hit_count = payload.get("hitCount")
    print(f"\n-- {len(papers)} papers shown (hitCount={hit_count}) --")
    for i, p in enumerate(papers, 1):
        title = p.get("title") or "(no title)"
        authors = p.get("authorString") or ""
        if len(authors) > 200:
            authors = authors[:200] + "…"
        year = p.get("pubYear") or "n/a"
        venue = ((p.get("journalInfo") or {}).get("journal") or {}).get("title") or "(no journal)"
        doi = p.get("doi") or ""
        abstract = p.get("abstractText") or ""
        if len(abstract) > 280:
            abstract = abstract[:280] + "…"

        print(f"\n  [{i}] {title}")
        print(f"      {authors}  ({year})  •  {venue}")
        if doi:
            print(f"      doi: {doi}")
        if abstract:
            print(f"      {abstract}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="epmc-smoke")
    parser.add_argument("name", nargs="?", choices=list(SAMPLE_QUERIES.keys()))
    parser.add_argument("--raw", action="store_true", help="Print full raw JSON.")
    args = parser.parse_args(argv)

    samples = [args.name] if args.name else list(SAMPLE_QUERIES.keys())
    for name in samples:
        try:
            payload = europe_pmc.search_for_lit_review(SAMPLE_QUERIES[name]["query"])
            _print_sample(name, payload, args.raw)
        except Exception as exc:
            print(f"\n[FAIL] {name}: {exc}", file=sys.stderr)
            return 1

    print(f"\n{'=' * 72}")
    print(f"  Done. {len(samples)} search(es) ran.")
    print(f"  Cached responses live under .cache/europe_pmc/lit_review/")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())

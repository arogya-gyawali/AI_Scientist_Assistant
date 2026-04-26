"""Tavily smoke test — exercise Stage 1 search WITHOUT touching the LLM.

Uses pre-baked queries for each bioscience sample hypothesis (skipping the
LLM query-rewrite step), calls Tavily directly, prints what came back.
Lets you confirm:
  - TAVILY_API_KEY works
  - Tavily returns useful content for our test domains
  - The cache layer is writing under .cache/tavily/lit_review/

Usage:
  python -m lit_review_pipeline.tavily_smoke              # run all bioscience samples
  python -m lit_review_pipeline.tavily_smoke trehalose    # run one
  python -m lit_review_pipeline.tavily_smoke --raw        # print full raw JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from dotenv import load_dotenv

from src.clients import tavily

# Pre-baked queries that approximate what the LLM query-rewrite step would
# produce for each sample hypothesis. Hand-tuned for the smoke test so we
# can evaluate Tavily independently of LLM quality.
SAMPLE_QUERIES: dict[str, dict[str, str]] = {
    "trehalose": {
        "domain": "cell_biology",
        "query": "trehalose vs DMSO cryoprotectant HeLa cell post-thaw viability",
    },
    "crp": {
        "domain": "diagnostics",
        "query": "paper-based electrochemical biosensor anti-CRP antibody whole blood C-reactive protein detection",
    },
    "lactobacillus": {
        "domain": "gut_health",
        "query": "Lactobacillus rhamnosus GG C57BL/6 mice intestinal permeability FITC-dextran tight junction claudin occludin",
    },
}


def _print_results(name: str, payload: dict[str, Any], raw: bool) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {name.upper()}  ({SAMPLE_QUERIES[name]['domain']})")
    print(f"  Query: {SAMPLE_QUERIES[name]['query']}")
    print("=" * 72)

    if raw:
        print(json.dumps(payload, indent=2))
        return

    answer = payload.get("answer")
    if answer:
        print("\n-- Tavily synthesized answer --")
        print(answer)

    results = payload.get("results", [])
    print(f"\n-- Top {len(results)} results --")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        score = r.get("score")
        print(f"\n[{i}] {title}")
        if score is not None:
            print(f"    score: {score:.3f}")
        print(f"    {url}")
        content = (r.get("content") or "").strip()
        if len(content) > 300:
            content = content[:300] + "…"
        if content:
            print(f"    {content}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="tavily-smoke")
    parser.add_argument("name", nargs="?", choices=list(SAMPLE_QUERIES.keys()), help="Run only this sample. Default: run all four.")
    parser.add_argument("--raw", action="store_true", help="Print full raw JSON instead of a summary.")
    args = parser.parse_args(argv)

    samples = [args.name] if args.name else list(SAMPLE_QUERIES.keys())
    for name in samples:
        try:
            payload = tavily.search_for_lit_review(SAMPLE_QUERIES[name]["query"])
            _print_results(name, payload, args.raw)
        except Exception as exc:
            print(f"\n[FAIL] {name}: {exc}", file=sys.stderr)
            return 1

    print(f"\n{'=' * 72}")
    print(f"  Done. {len(samples)} search(es) ran.")
    print(f"  Cached responses live under .cache/tavily/lit_review/")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())

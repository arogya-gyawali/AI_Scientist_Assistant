#!/usr/bin/env python3
"""Single-command Stage 1 (Lit Review) test runner.

Usage:
  python run_lr.py                      # default sample (trehalose), full pipeline
  python run_lr.py crp                  # different sample
  python run_lr.py --tavily-only        # Tavily smoke test only, skip the LLM
  python run_lr.py --all                # run all bioscience samples through full pipeline
  python run_lr.py --raw                # also dump full Tavily JSON

Loads .env, verifies keys are present, runs the pre-baked Tavily smoke test,
then runs Stage 1 end-to-end (LLM query rewrite -> Tavily -> LLM classify),
and writes the resulting ExperimentPlan JSON to plans/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Force UTF-8 stdout/stderr on Windows so box-drawing chars and science
# Unicode (μ, −, °C) don't crash the cp1252 default console encoding.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Load .env BEFORE importing anything that reads env at module scope.
load_dotenv()

from src.clients import llm, tavily  # noqa: E402
from src.lib import plan as plan_lib  # noqa: E402
from lit_review_pipeline import stage as lit_review  # noqa: E402
from src.types import (  # noqa: E402
    Hypothesis,
    StageStatusComplete,
    StageStatusFailed,
    StageStatusRunning,
    StructuredHypothesis,
    now,
)
import yaml  # noqa: E402

SAMPLES = {
    "trehalose": {
        "yaml": Path("inputs/trehalose.yaml"),
        "tavily_query": "trehalose vs DMSO cryoprotectant HeLa cell post-thaw viability",
    },
    "crp": {
        "yaml": Path("inputs/crp.yaml"),
        "tavily_query": "paper-based electrochemical biosensor anti-CRP antibody whole blood C-reactive protein detection",
    },
    "lactobacillus": {
        "yaml": Path("inputs/lactobacillus.yaml"),
        "tavily_query": "Lactobacillus rhamnosus GG C57BL/6 mice intestinal permeability FITC-dextran tight junction claudin occludin",
    },
}


def _hr(title: str = "") -> None:
    line = "─" * 72
    print(f"\n{line}")
    if title:
        print(f"  {title}")
        print(line)


def _check_env() -> bool:
    missing: list[str] = []
    if not os.environ.get("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")

    provider = os.environ.get("LLM_PROVIDER", "openrouter").lower()
    if provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        missing.append("OPENROUTER_API_KEY (LLM_PROVIDER=openrouter)")
    elif provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY (LLM_PROVIDER=anthropic)")

    if missing:
        print("\nMissing env vars in .env:", file=sys.stderr)
        for v in missing:
            print(f"  - {v}", file=sys.stderr)
        print("\nCopy .env.example to .env and fill in the keys.", file=sys.stderr)
        return False
    return True


def _load_yaml(path: Path) -> Hypothesis:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    structured = StructuredHypothesis(**raw["structured"])
    return Hypothesis(
        id=f"hyp_{uuid.uuid4().hex[:12]}",
        structured=structured,
        domain=raw.get("domain"),
    )


def smoke_tavily(name: str, raw: bool = False) -> bool:
    sample = SAMPLES[name]
    _hr(f"STEP 1: Tavily smoke test  ({name})")
    print(f"Query: {sample['tavily_query']}")

    try:
        response = tavily.search_for_lit_review(sample["tavily_query"])
    except Exception as exc:
        print(f"\n[FAIL] Tavily call failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return False

    results = response.get("results", [])
    print(f"\nOK — Tavily returned {len(results)} results.")
    if response.get("answer"):
        print("\nSynthesized answer:")
        print(response["answer"])

    print(f"\nAll {len(results)} results:")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        score = r.get("score")
        score_s = f"  score={score:.3f}" if isinstance(score, (int, float)) else ""
        published = r.get("published_date") or ""
        print(f"\n  [{i}] {title}{score_s}")
        if published:
            print(f"      published: {published}")
        print(f"      {r.get('url', '')}")
        content = (r.get("content") or "").strip()
        if content:
            for line in content.splitlines():
                line = line.strip()
                if line:
                    print(f"      {line}")

    if raw:
        _hr("Raw Tavily JSON")
        print(json.dumps(response, indent=2))

    return True


def run_full_pipeline(name: str) -> bool:
    sample = SAMPLES[name]
    _hr(f"STEP 2: Full Stage 1 pipeline  ({name})")
    print(f"Provider: {llm._provider()}    Model: {llm.model_id()}")
    print(f"Input:    {sample['yaml']}")

    try:
        hypothesis = _load_yaml(sample["yaml"])
        plan = plan_lib.create_plan(hypothesis, model_id=llm.model_id())
        plan_lib.save_plan(plan)
        print(f"\nCreated plan: {plan.id}")

        plan.status["lit_review"] = StageStatusRunning(started_at=now())
        plan_lib.save_plan(plan)

        try:
            session = lit_review.run(plan)
        except Exception as exc:
            plan.status["lit_review"] = StageStatusFailed(failed_at=now(), error=str(exc))
            plan_lib.save_plan(plan)
            print(f"\n[FAIL] Stage 1 failed: {exc}", file=sys.stderr)
            traceback.print_exc()
            return False

        plan.lit_review = session
        plan.status["lit_review"] = StageStatusComplete(completed_at=now())
        plan_lib.save_plan(plan)

        print(f"\n# Stage 1 — Lit Review output ({name})")
        print(session.initial_result.model_dump_json(indent=2))

        # Mirror the summary at the bottom for human reading.
        print("\n" + "=" * 72)
        print("LIT REVIEW SUMMARY")
        print("=" * 72)
        print(session.initial_result.summary)

        print(f"\n# Plan saved to: {plan_lib.plan_path(plan.id)}", file=sys.stderr)
        return True

    except Exception as exc:
        print(f"\n[FAIL] Pipeline error: {exc}", file=sys.stderr)
        traceback.print_exc()
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run", description="Test Stage 1 (Lit Review) end-to-end.")
    parser.add_argument("sample", nargs="?", choices=list(SAMPLES.keys()), default="trehalose")
    parser.add_argument("--tavily-only", action="store_true", help="Run Tavily smoke test only; skip the LLM pipeline.")
    parser.add_argument("--all", action="store_true", help="Run all bioscience samples through the full pipeline.")
    parser.add_argument("--raw", action="store_true", help="Also print the raw Tavily JSON in the smoke step.")
    args = parser.parse_args(argv)

    if not _check_env():
        return 1

    samples = list(SAMPLES.keys()) if args.all else [args.sample]

    for name in samples:
        if not smoke_tavily(name, raw=args.raw):
            return 1
        if not args.tavily_only:
            if not run_full_pipeline(name):
                return 1

    _hr("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

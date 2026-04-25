"""CLI entrypoint.

Usage:
  python -m src.cli inputs/trehalose.yaml
  python -m src.cli inputs/trehalose.yaml --only lit_review

For now, only --only lit_review is implemented. Other stages will land
as their runners are written.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.clients import llm
from src.lib import plan as plan_lib
from lit_review_pipeline import stage as lit_review
from src.types import (
    Hypothesis,
    StageStatusComplete,
    StageStatusFailed,
    StageStatusRunning,
    StructuredHypothesis,
    now,
)


def _load_input(path: Path) -> Hypothesis:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    structured = StructuredHypothesis(**raw["structured"])
    return Hypothesis(
        id=f"hyp_{uuid.uuid4().hex[:12]}",
        structured=structured,
        domain=raw.get("domain"),
    )


def _run_lit_review(plan):
    plan.status["lit_review"] = StageStatusRunning(started_at=now())
    plan_lib.save_plan(plan)
    try:
        session = lit_review.run(plan)
    except Exception as exc:
        plan.status["lit_review"] = StageStatusFailed(failed_at=now(), error=str(exc))
        plan_lib.save_plan(plan)
        raise
    plan.lit_review = session
    plan.status["lit_review"] = StageStatusComplete(completed_at=now())
    plan_lib.save_plan(plan)
    return session


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="ai-scientist", description="Generate an experiment plan from a structured hypothesis.")
    parser.add_argument("input", type=Path, help="Path to a YAML hypothesis file (see inputs/).")
    parser.add_argument(
        "--only",
        type=str,
        default="lit_review",
        choices=["lit_review"],
        help="Run only this stage. (More stages coming.)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1

    hypothesis = _load_input(args.input)
    plan = plan_lib.create_plan(hypothesis, model_id=llm.model_id())
    plan_lib.save_plan(plan)
    print(f"Created plan {plan.id} -> {plan_lib.plan_path(plan.id)}")

    if args.only == "lit_review":
        session = _run_lit_review(plan)
        print(session.initial_result.model_dump_json(indent=2))
        print(f"\n# Plan written to: {plan_lib.plan_path(plan.id)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

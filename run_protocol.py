"""Run the Stage 2 + 3 (Protocol + Materials) pipeline on a hypothesis YAML.

Usage:
    python run_protocol.py inputs/trehalose.yaml
    python run_protocol.py --all                  # runs all inputs/*.yaml
    python run_protocol.py inputs/crp.yaml -o out.json

Output: a single JSON object with three top-level fields:
    - protocol  (ProtocolGenerationOutput)
    - materials (MaterialsOutput)
    - outline   (transient ProtocolOutline, useful for debugging)

When --all is passed, output files are written to
pipeline_output_samples/protocol_pipeline/<name>.json (creating the
directory if needed).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# UTF-8 stdout so Windows cp1252 doesn't choke on Unicode in step bodies.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from src.types import Hypothesis, StructuredHypothesis  # noqa: E402
from protocol_pipeline.stage import run as run_pipeline  # noqa: E402


SAMPLES_OUT_DIR = Path("pipeline_output_samples/protocol_pipeline")


def _load_hypothesis(yaml_path: Path) -> Hypothesis:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return Hypothesis(
        id=f"hyp_{yaml_path.stem}_{uuid.uuid4().hex[:6]}",
        structured=StructuredHypothesis(**data["structured"]),
        domain=data.get("domain"),
    )


def _result_to_json(result, hypothesis: Hypothesis) -> dict:
    return {
        "hypothesis": hypothesis.model_dump(mode="json"),
        "outline": result.outline.model_dump(mode="json"),
        "protocol": result.protocol.model_dump(mode="json"),
        "materials": result.materials.model_dump(mode="json"),
    }


def _print_summary(name: str, result, dt: float) -> None:
    p = result.protocol
    m = result.materials
    devs = sum(len(pr.deviations_from_source) for pr in p.procedures)
    todos = sum(len(s.todo_for_researcher) for pr in p.procedures for s in pr.steps)
    crit = sum(len(pr.success_criteria) for pr in p.procedures)
    print(f"  {name}: {dt:.1f}s, "
          f"{len(p.procedures)} procedures, {p.total_steps} steps, "
          f"{m.total_unique_items} materials ({m.by_category.get('equipment', 0)} equipment), "
          f"{devs} deviations, {todos} TODOs, {crit} success-criteria, "
          f"{len(m.gaps)} gaps")


def _run_one(yaml_path: Path, output_path: Path | None) -> None:
    hyp = _load_hypothesis(yaml_path)
    print(f"Running {yaml_path.name} -> {hyp.id}")
    t0 = time.time()
    result = run_pipeline(hyp)
    dt = time.time() - t0

    payload = _result_to_json(result, hyp)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  -> {output_path}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    _print_summary(yaml_path.stem, result, dt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="Path to a hypothesis YAML.")
    ap.add_argument("--all", action="store_true",
                    help="Run on every inputs/*.yaml and dump JSONs into pipeline_output_samples/protocol_pipeline/.")
    ap.add_argument("-o", "--output", type=Path,
                    help="Path to write the JSON output (default: stdout).")
    args = ap.parse_args()

    if args.all:
        inputs = sorted(Path("inputs").glob("*.yaml"))
        if not inputs:
            print("No YAML inputs found in inputs/", file=sys.stderr)
            return 1
        SAMPLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
        for path in inputs:
            out = SAMPLES_OUT_DIR / f"{path.stem}.json"
            try:
                _run_one(path, out)
            except Exception as exc:
                print(f"  FAILED on {path.name}: {exc}", file=sys.stderr)
        return 0

    if not args.input:
        ap.print_help()
        return 1
    _run_one(Path(args.input), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

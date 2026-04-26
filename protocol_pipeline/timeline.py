"""Stage 5: Timeline computation.

Builds a deterministic, citeable Timeline from the protocol's per-step
durations. NO LLM CALL. Same protocol input -> byte-for-byte same
timeline output (modulo the timestamp on `generated_at`).

Design principles:
  - **Deterministic**: every value is computed from the protocol via
    explicit summation. Researchers can reproduce by hand.
  - **Defensible**: each phase carries `methodology` text and `coverage`
    (fraction of steps with duration data) so the user can audit every
    claim. Conservative-by-design: a phase with any missing duration
    returns `duration=None` rather than a misleading partial sum.
  - **Citeable**: each phase's id ("phase-{procedure_index}") and
    procedure_index back-link the user to the source procedure.

What this stage does NOT compute (documented in `assumptions`):
  - Hands-on time vs. wall-clock time (no ground truth on the FE side)
  - Parallelization opportunities (would need a dependency analysis the
    architect doesn't currently emit)
  - Calendar dates (no start_date input yet; `earliest_completion_date`
    stays None)
"""

from __future__ import annotations

from typing import Optional

from src.types import (
    ProtocolGenerationOutput,
    TimelineOutput,
    TimelinePhase,
    TimelineTask,
)

# Reuse the ISO duration math we already have in the orchestrator.
from .stage import _sum_iso8601_durations


def compute_timeline(protocol: ProtocolGenerationOutput) -> TimelineOutput:
    """Build a TimelineOutput from a ProtocolGenerationOutput.

    Each procedure becomes one phase; each step within a procedure
    becomes one task. The pipeline is treated as linear (each phase
    depends on the previous), since the architect produces procedures
    in execution order. Future iteration: have the architect emit
    explicit dependencies + parallel-with sets."""
    phases: list[TimelinePhase] = []

    # Map: procedure_index -> step_n offset for the global flat step
    # numbering (matches ProtocolGenerationOutput.steps[].n).
    flat_step_counter = 1

    # Lazy import — timeline.py is itself imported lazily by stage.py,
    # but _iso_duration_to_seconds lives in stage.py and we use it here
    # to distinguish "has a duration string" from "parses as ISO 8601".
    # The two counts diverge when the writer emits "30 min" or "PT" or
    # other non-conforming strings.
    from .stage import _iso_duration_to_seconds

    for proc_index, proc in enumerate(protocol.procedures, start=1):
        tasks: list[TimelineTask] = []
        n_with_duration = 0      # has a non-empty string
        n_parseable = 0          # parses to ISO 8601 seconds
        unparseable: list[str] = []  # list of (step_title, raw_string) for the methodology
        for step in proc.steps:
            tasks.append(TimelineTask(
                step_n=flat_step_counter,
                name=step.title,
                duration=step.duration,
                # hands_on_time and can_parallel: not auto-computed.
                # Conservative defaults; surface in `assumptions`.
            ))
            if step.duration:
                n_with_duration += 1
                if _iso_duration_to_seconds(step.duration) is not None:
                    n_parseable += 1
                else:
                    # Cap each example at ~30 chars so the methodology
                    # line stays scannable when 4-5 steps fail.
                    raw = (step.duration or "").strip()
                    if len(raw) > 30:
                        raw = raw[:30] + "…"
                    unparseable.append(f"step {step.n} ({raw!r})")
            flat_step_counter += 1

        n_steps = len(tasks)
        # Coverage reflects PARSEABLE durations — "has a string" without
        # "parses cleanly" doesn't actually contribute to the sum, so it
        # shouldn't pad the coverage chip.
        coverage = (n_parseable / n_steps) if n_steps > 0 else 0.0

        # Sum step durations — _sum_iso8601_durations returns None if any
        # step is missing or malformed. That's the conservative behavior
        # we want: a phase with partial duration data shouldn't claim
        # a wall-clock total.
        phase_duration = _sum_iso8601_durations([t.duration for t in tasks])

        # Methodology — explicit, plain-English description so the user
        # can audit / reproduce. Three failure shapes to distinguish:
        #   - 0/N steps have any duration: nothing to sum, period.
        #   - K/N have a string, K parse: missing M steps; can't sum.
        #   - K/N have a string, J<K parse: writer emitted non-ISO 8601
        #     for K-J of them. Surface examples so the user can fix.
        if phase_duration is None:
            if n_with_duration == 0:
                methodology = (
                    f"Duration not available — none of {n_steps} steps in "
                    f"procedure '{proc.name}' have a duration value."
                )
            elif n_parseable < n_with_duration:
                # All N have strings but some don't parse as ISO 8601.
                examples = ", ".join(unparseable[:3])
                more = (
                    f" (and {len(unparseable) - 3} more)"
                    if len(unparseable) > 3 else ""
                )
                methodology = (
                    f"Duration not summable — {n_with_duration} of "
                    f"{n_steps} steps in '{proc.name}' have a duration "
                    f"string but only {n_parseable} parse as valid "
                    f"ISO 8601. Non-conforming: {examples}{more}. "
                    f"Conservative: not reporting a partial sum."
                )
            else:
                # Some steps simply have no duration set.
                methodology = (
                    f"Duration not summable — only {n_with_duration} of "
                    f"{n_steps} steps in procedure '{proc.name}' have "
                    f"a duration value. Conservative: not reporting a "
                    f"partial sum."
                )
        else:
            methodology = (
                f"Sum of {n_parseable} step duration"
                f"{'s' if n_parseable != 1 else ''} from procedure "
                f"'{proc.name}'."
            )

        # Linear pipeline: each phase depends on the previous.
        depends_on = [phases[-1].id] if phases else []

        # `Procedure` doesn't carry a procedure_index field — the index
        # comes from execution order. enumerate(start=1) above gives us
        # the canonical 1-based index every phase id and back-link uses.
        phases.append(TimelinePhase(
            id=f"phase-{proc_index}",
            name=proc.name,
            duration=phase_duration,
            tasks=tasks,
            depends_on=depends_on,
            parallel_with=[],   # not auto-detected
            procedure_index=proc_index,
            coverage=round(coverage, 2),
            methodology=methodology,
        ))

    # Total duration: reuse the protocol-level total (already computed
    # in run_protocol_only). If that's None, also try summing the phase
    # durations we just computed — same conservative semantics.
    total = protocol.total_duration or _sum_iso8601_durations(
        [p.duration for p in phases]
    )

    # Critical path: linear pipeline -> all phases in order. When
    # parallelization gets auto-detected, this will show only the
    # sequential blocking phases.
    critical_path = [p.id for p in phases]

    # Document what the deterministic compute does NOT cover. This is
    # the defensibility surface — a researcher reading the timeline
    # knows exactly what's missing without having to dig into source.
    assumptions = [
        "Pipeline is treated as linear; parallelization opportunities "
        "(e.g. independent measurement procedures) are not auto-detected.",
        "Hands-on time is not separated from total wall-clock duration. "
        "A 24h incubation counts as 24h of phase duration even though "
        "the bench-time is minutes.",
        "Calendar dates are not computed; `earliest_completion_date` "
        "remains null until a start-date input lands.",
    ]
    # Surface partial-coverage issues at the top level too so the FE
    # can render a "this estimate is incomplete" banner.
    incomplete = [
        f"Phase '{p.name}' duration estimate is incomplete "
        f"(coverage {p.coverage:.0%}; {len([t for t in p.tasks if not t.duration])} "
        f"of {len(p.tasks)} steps have no duration value)."
        for p in phases
        if p.coverage < 1.0
    ]
    assumptions.extend(incomplete)

    return TimelineOutput(
        phases=phases,
        total_duration=total,
        critical_path=critical_path,
        assumptions=assumptions,
        earliest_completion_date=None,
    )

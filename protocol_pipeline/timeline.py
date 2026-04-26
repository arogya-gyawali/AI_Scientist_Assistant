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

    for proc in protocol.procedures:
        tasks: list[TimelineTask] = []
        n_with_duration = 0
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
            flat_step_counter += 1

        n_steps = len(tasks)
        coverage = (n_with_duration / n_steps) if n_steps > 0 else 0.0

        # Sum step durations — _sum_iso8601_durations returns None if any
        # step is missing or malformed. That's the conservative behavior
        # we want: a phase with partial duration data shouldn't claim
        # a wall-clock total.
        phase_duration = _sum_iso8601_durations([t.duration for t in tasks])

        # Methodology — explicit, plain-English description so the user
        # can audit / reproduce.
        if phase_duration is None:
            if n_with_duration == 0:
                methodology = (
                    f"Duration not available — none of {n_steps} steps in "
                    f"procedure '{proc.name}' have a duration value."
                )
            else:
                methodology = (
                    f"Duration not summable — only {n_with_duration} of "
                    f"{n_steps} steps in procedure '{proc.name}' have "
                    f"a duration value. Conservative: not reporting a "
                    f"partial sum."
                )
        else:
            methodology = (
                f"Sum of {n_with_duration} step duration"
                f"{'s' if n_with_duration != 1 else ''} from procedure "
                f"'{proc.name}'."
            )

        # Linear pipeline: each phase depends on the previous.
        depends_on = [phases[-1].id] if phases else []

        phases.append(TimelinePhase(
            id=f"phase-{proc.procedure_index if hasattr(proc, 'procedure_index') else len(phases) + 1}",
            name=proc.name,
            duration=phase_duration,
            tasks=tasks,
            depends_on=depends_on,
            parallel_with=[],   # not auto-detected
            procedure_index=getattr(proc, "procedure_index", len(phases) + 1),
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

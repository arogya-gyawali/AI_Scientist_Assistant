"""Stage 2 + 3 orchestrator.

Reads:  hypothesis (and protocols.io static samples by name)
Writes: ExperimentPlan.protocol (ProtocolGenerationOutput)
        ExperimentPlan.materials (MaterialsOutput)

Flow:
  1. Load + normalize protocols.io samples (offline; from
     pipeline_output_samples/protocols_io/).
  2. Relevance filter (1 LLM call): drop sources below threshold.
  3. Architect (1 LLM call): emit ProtocolOutline with 3-8 procedures.
  4. Procedure writers (N parallel LLM calls): one per procedure.
  5. Materials roll-up (1 LLM call): consolidate equipment + reagents
     across procedures with concrete specs.
  6. Validate + bind to Pydantic types, write to blackboard.

Total LLM calls: 3 + N_procedures (typically 7-9 per run).

This stage runs against the static samples committed to the repo, NOT
against a live protocols.io fetch. The teammate's protocols.io client
is being built on a separate branch; the only swap needed when it
lands is the source loader (currently `sources.load_all_samples()`).
"""

from __future__ import annotations

from src.types import (
    CitedProtocol,
    ExperimentPlan,
    Hypothesis,
    MaterialsOutput,
    ProtocolGenerationOutput,
    ProtocolStep,
    StageStatusComplete,
    StageStatusFailed,
    StageStatusRunning,
    now,
)

from .architect import ProtocolOutline, plan_outline
from .materials import roll_up_materials
from .relevance import filter_relevant
from .sources import NormalizedProtocol, load_all_samples
from .writer import write_procedures_parallel


# --------------------------------------------------------------------------
# Output bundle (what the runner returns to its caller)
# --------------------------------------------------------------------------

class StageResult:
    """Convenience bag for the runner's output. Two Pydantic blocks plus
    the intermediate outline (handy for debugging / sample dumps)."""
    def __init__(
        self,
        protocol: ProtocolGenerationOutput,
        materials: MaterialsOutput,
        outline: ProtocolOutline,
    ) -> None:
        self.protocol = protocol
        self.materials = materials
        self.outline = outline


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

def run(
    hypothesis: Hypothesis,
    *,
    sources: list[NormalizedProtocol] | None = None,
    relevance_threshold: float = 0.2,
    max_writer_workers: int = 5,
) -> StageResult:
    """Run the full Stage 2 + 3 pipeline against an in-memory list of
    normalized source protocols. Pass `sources=None` to load all the
    static samples in `pipeline_output_samples/protocols_io/`."""
    if sources is None:
        sources = list(load_all_samples().values())

    # 1. Relevance filter
    scored = filter_relevant(hypothesis, sources, keep_threshold=relevance_threshold)

    # 2. Architect
    outline = plan_outline(hypothesis, scored)

    # 3. Procedure writers (parallel)
    sources_by_id = {p.id: p for p in sources}
    procedures = write_procedures_parallel(
        hypothesis, outline.procedures, sources_by_id,
        max_workers=max_writer_workers,
    )

    # 4. Build flat steps view (re-numbered across procedures for FE checklist)
    flat_steps: list[ProtocolStep] = []
    counter = 1
    for proc in procedures:
        for s in proc.steps:
            flat_steps.append(s.model_copy(update={"n": counter}))
            counter += 1

    # 5. Cited protocols: every source the architect routed to at least one procedure
    referenced_ids: set[str] = set()
    for proc in procedures:
        referenced_ids.update(proc.source_protocol_ids)

    cited: list[CitedProtocol] = []
    for sp in scored:
        if sp.protocol.id not in referenced_ids:
            continue
        cited.append(CitedProtocol(
            doi=sp.protocol.doi,
            protocols_io_id=sp.protocol.id,
            title=sp.protocol.title,
            contribution_weight=round(sp.score.score, 2),
        ))

    protocol = ProtocolGenerationOutput(
        experiment_type=outline.experiment_type,
        domain=outline.domain or hypothesis.domain,
        procedures=procedures,
        steps=flat_steps,
        cited_protocols=cited,
        regulatory_requirements=[],   # Stage 6 (Validation) populates this
        assumptions=outline.overall_assumptions,
        total_steps=len(flat_steps),
        source_protocol_ids=sorted(referenced_ids),
    )

    # 6. Materials roll-up
    materials = roll_up_materials(procedures)

    return StageResult(protocol=protocol, materials=materials, outline=outline)


def run_and_write(
    plan: ExperimentPlan,
    *,
    sources: list[NormalizedProtocol] | None = None,
    relevance_threshold: float = 0.2,
    max_writer_workers: int = 5,
) -> ExperimentPlan:
    """Run the pipeline and write the results to the shared blackboard.

    Updates `plan.protocol`, `plan.materials`, BOTH stage statuses, and
    `plan.updated_at`. The blackboard pattern requires every consumer to
    be able to ask "did Stage 2 complete?" and "when was the plan last
    touched?" — silently mutating the output fields without updating
    status leaves downstream stages unable to gate on completion.

    Both stages share the same lifecycle here because they emit together
    in this pipeline (the materials roll-up runs as the final agent of
    the same orchestration). On exception, both are marked failed.
    """
    started = now()
    plan.status["protocol"] = StageStatusRunning(started_at=started)
    plan.status["materials"] = StageStatusRunning(started_at=started)
    plan.updated_at = started

    try:
        result = run(
            plan.hypothesis,
            sources=sources,
            relevance_threshold=relevance_threshold,
            max_writer_workers=max_writer_workers,
        )
    except Exception as exc:
        failed_at = now()
        plan.status["protocol"] = StageStatusFailed(failed_at=failed_at, error=str(exc))
        plan.status["materials"] = StageStatusFailed(failed_at=failed_at, error=str(exc))
        plan.updated_at = failed_at
        raise

    completed_at = now()
    plan.protocol = result.protocol
    plan.materials = result.materials
    plan.status["protocol"] = StageStatusComplete(completed_at=completed_at)
    plan.status["materials"] = StageStatusComplete(completed_at=completed_at)
    plan.updated_at = completed_at
    return plan

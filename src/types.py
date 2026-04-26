"""Pydantic models mirroring spec/types/. Stage 1 only for now; rest stubbed
as Optional fields on ExperimentPlan so the blackboard validates regardless
of which stages have run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Shared ---------------------------------------------------------------

class KeyDifference(BaseModel):
    """One concrete way a cited paper differs from the user's hypothesis.

    Defensibility: the LLM is required to populate `their_approach` from the
    paper's abstract; the parser drops entries with sub-token strings or an
    unknown dimension, so every difference reaching the FE is structurally
    sound. `dimension` is a fixed taxonomy so the FE can group or filter;
    `gap_significance` makes explicit why the difference matters for whether
    this paper is a near-precedent or genuinely adjacent work.
    """
    dimension: Literal[
        "subject",        # organism / cell line / patient population
        "intervention",   # what's manipulated (independent variable)
        "measurement",    # what's measured (dependent variable)
        "conditions",     # culture / environmental / dose conditions
        "scope",          # in vitro vs in vivo, sample size, duration
        "method",         # assay / technique
    ]
    their_approach: str   # what the cited paper does (drawn from abstract)
    our_approach: str     # what the user's hypothesis specifies
    gap_significance: str # why the difference matters / gap it leaves


class Citation(BaseModel):
    source: str
    confidence: Literal["high", "medium", "low"]
    doi: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    venue: Optional[str] = None                 # Journal / preprint server / publication venue
    snippet: Optional[str] = None
    relevance_score: Optional[float] = Field(default=None, ge=0, le=1)  # 0-1; UI renders as percentage
    description: Optional[str] = None           # Neutral paper description (LLM-generated; lit-review refs)
    matched_on: Optional[list[str]] = None      # Concept chips ("E. coli", "Glucose", ...)
    importance: Optional[str] = None            # "Why this matched" — relevance to hypothesis (LLM-generated)
    key_differences: Optional[list[KeyDifference]] = None  # Phase E: per-reference structured deltas


class StructuredHypothesis(BaseModel):
    """Scientist-friendly breakdown of a hypothesis."""
    research_question: str
    subject: str
    independent: str
    dependent: str
    conditions: str
    expected: str


class Hypothesis(BaseModel):
    id: str
    structured: StructuredHypothesis
    domain: Optional[str] = None
    created_at: str = Field(default_factory=now)


# ---- Stage 1: Lit Review --------------------------------------------------

NoveltySignal = Literal["novel", "similar_work_exists", "exact_match_found"]


class LitReviewOutput(BaseModel):
    signal: NoveltySignal
    description: str
    references: list[Citation] = Field(max_length=3)
    searched_at: str
    tavily_query: str
    summary: str  # 3-4 sentence wrap-up at the bottom; LLM-generated. STRICT length cap.


class LitReviewChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    cited_refs: Optional[list[int]] = None
    timestamp: str


class LitReviewSession(BaseModel):
    id: str
    hypothesis_id: str
    initial_result: LitReviewOutput
    chat_history: list[LitReviewChatMessage] = []
    cached_search_context: str
    user_decision: Literal["pending", "proceed", "refine", "abandon"] = "pending"


# ---- Stage 2 / 3: Protocol + Materials -----------------------------------
# Multi-agent pipeline: relevance-filter → architect → procedure-writers (fan
# out, parallel) → materials-roll-up. Procedures are the unit of context
# isolation: each writer agent sees only its procedure plus the relevant
# source protocols, defending against context drift on long protocols.

class Quantity(BaseModel):
    """Numeric value + unit. Used for volume, temperature, concentration,
    speed. Duration stays as ISO 8601 string (matches existing convention)."""
    value: float
    unit: str  # "mL" | "uL" | "C" | "rpm" | "g" | "M" | "mM" | "ng/uL" ...


class StepParams(BaseModel):
    """Structured parameters extracted from a step. All optional — not every
    step has every parameter (e.g., a "label tubes" step has none). The
    `other` escape hatch is for params we haven't promoted to first-class
    fields yet (pH, voltage, gas mix, ...)."""
    volume: Optional[Quantity] = None
    temperature: Optional[Quantity] = None
    duration: Optional[str] = None  # ISO 8601 duration string, e.g. "PT5M"
    concentration: Optional[Quantity] = None
    speed: Optional[Quantity] = None  # rpm or g
    other: dict[str, str] = Field(default_factory=dict)


class ReagentRecipe(BaseModel):
    """How to prepare a custom buffer or working stock referenced by a step.

    Only emitted for non-commercial reagents — we don't include recipes for
    "PBS" or "DMEM" if the lab is buying them; we only include recipes when
    the protocol genuinely calls for the researcher to mix something."""
    name: str                                       # "M9 buffer (10x)"
    components: list[str]                           # ["3 g Na2HPO4", "0.5 g NaCl", ...]
    notes: Optional[str] = None                     # "Sterilize by autoclaving"


class ProtocolStep(BaseModel):
    """A single executable instruction. `body_md` is the human-readable
    action; `params` is the structured extraction the FE can render as a
    parameters table. `source_step_refs` cites the protocols.io step ids
    that informed this step (auditability).

    Quality-of-life fields (Nature Protocols / protocols.io style):
      - is_critical: ▲ steps where ~80% of failures happen. Sparingly used —
        the writer is instructed to flag at most ~20% of steps.
      - is_pause_point: ▶ clean state transitions (after a wash, before an
        overnight incubation) where the researcher can safely stop.
      - anticipated_outcome: what to expect at the bench after this step.
      - troubleshooting: short bullets for known failure modes.
      - reagent_recipes: when a step introduces a custom buffer / mix that
        the researcher must prepare themselves."""
    n: int
    title: str
    body_md: str
    duration: Optional[str] = None  # ISO 8601, e.g. "PT5M"
    equipment_needed: list[str] = Field(default_factory=list)
    reagents_referenced: list[str] = Field(default_factory=list)
    params: StepParams = Field(default_factory=StepParams)
    controls: list[str] = Field(default_factory=list)
    todo_for_researcher: list[str] = Field(default_factory=list)
    source_step_refs: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    cited_doi: Optional[str] = None
    # New quality-of-life fields:
    anticipated_outcome: Optional[str] = None
    is_critical: bool = False
    is_pause_point: bool = False
    troubleshooting: list[str] = Field(default_factory=list)
    reagent_recipes: list[ReagentRecipe] = Field(default_factory=list)


class Deviation(BaseModel):
    """An adaptation the LLM made from the source protocol. Required so the
    researcher can see and audit every change rather than trusting the
    output blindly."""
    from_source: str
    to_adapted: str
    reason: str
    source_protocol_id: str
    confidence: Literal["low", "medium", "high"]


class ProcedureSuccessCriterion(BaseModel):
    """Per-procedure pass/fail or quantitative measurement. Procedure-level
    only — Stage 6 (Validation) owns the experiment-wide SuccessCriterion
    type, which is richer (statistical_test, expected_value). This lighter
    shape gives the FE per-procedure "did this work?" markers without
    duplicating Stage 6's contract."""
    what: str           # "post-thaw cell viability"
    how_measured: str   # "trypan blue exclusion, hemocytometer"
    threshold: Optional[str] = None  # ">=85%"
    pass_fail: bool = True


class Procedure(BaseModel):
    """A logical group of steps (e.g., "Cell preparation", "Cryoprotectant
    mix", "Controlled-rate freeze"). Each procedure is the unit a single
    procedure-writer agent owns — context isolation by construction.

    `total_duration` is computed deterministically by the orchestrator
    after all writers finish (sum of step durations). Left None if any
    step is missing a duration; partial sums would mislead researchers
    planning their day."""
    name: str
    intent: str
    steps: list[ProtocolStep]
    equipment: list[str] = Field(default_factory=list)
    reagents: list[str] = Field(default_factory=list)
    deviations_from_source: list[Deviation] = Field(default_factory=list)
    source_protocol_ids: list[str] = Field(default_factory=list)
    success_criteria: list[ProcedureSuccessCriterion] = Field(default_factory=list)
    total_duration: Optional[str] = None  # ISO 8601, deterministic sum


class CitedProtocol(BaseModel):
    doi: Optional[str] = None
    protocols_io_id: Optional[str] = None
    title: str
    contribution_weight: float = Field(ge=0, le=1)


class RegulatoryRequirement(BaseModel):
    requirement: str          # "IACUC approval", "BSL-2 facility", ...
    authority: str            # "institutional", "FDA", "NIH", ...
    applicable_because: str
    estimated_lead_time: Optional[str] = None  # ISO 8601 duration
    notes: Optional[str] = None


class ProtocolGenerationOutput(BaseModel):
    """Stage 2 output. `procedures` is the primary view (grouped, with
    deviations + success criteria); `steps` is a flat re-numbered view for
    FE rendering as a checklist or for downstream stages that only need
    the linear sequence."""
    experiment_type: str
    domain: Optional[str] = None
    procedures: list[Procedure]
    steps: list[ProtocolStep]  # flat view, derived from procedures
    cited_protocols: list[CitedProtocol] = Field(default_factory=list)
    regulatory_requirements: list[RegulatoryRequirement] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    total_steps: int
    source_protocol_ids: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now)
    total_duration: Optional[str] = None  # ISO 8601 sum across all procedures


class Material(BaseModel):
    """Concrete reagent / equipment / consumable. `spec` and `purpose` are
    populated for equipment items (e.g., spec="benchtop centrifuge, >=3000g,
    refrigerated", purpose="cell pelleting"); left None for reagents.
    `vendor`/`sku` left None until Stage 4 (Budget) backfills them from
    supplier lookups."""
    id: str
    name: str
    category: Literal["reagent", "consumable", "equipment", "cell_line", "organism"]
    qty: Optional[float] = None
    unit: Optional[str] = None
    spec: Optional[str] = None        # equipment only
    purpose: Optional[str] = None     # equipment only
    vendor: Optional[str] = None      # backfilled by Stage 4
    sku: Optional[str] = None         # backfilled by Stage 4
    storage: Optional[str] = None
    hazard: Optional[str] = None
    alternatives: list[str] = Field(default_factory=list)


class MaterialsOutput(BaseModel):
    """Stage 3 output. Consolidated/de-duped across all procedures.
    `gaps` flags items the LLM couldn't ground (researcher decision needed)."""
    materials: list[Material]
    total_unique_items: int
    by_category: dict[str, int] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now)


# ---- Stage lifecycle ------------------------------------------------------

StageName = Literal[
    "lit_review", "protocol", "materials", "budget",
    "timeline", "validation", "critique", "summary",
]

ALL_STAGES: tuple[StageName, ...] = (
    "lit_review", "protocol", "materials", "budget",
    "timeline", "validation", "critique", "summary",
)


class StageStatusNotStarted(BaseModel):
    state: Literal["not_started"] = "not_started"


class StageStatusRunning(BaseModel):
    state: Literal["running"] = "running"
    started_at: str


class StageStatusComplete(BaseModel):
    state: Literal["complete"] = "complete"
    completed_at: str


class StageStatusFailed(BaseModel):
    state: Literal["failed"] = "failed"
    failed_at: str
    error: str


StageStatus = (
    StageStatusNotStarted
    | StageStatusRunning
    | StageStatusComplete
    | StageStatusFailed
)


# ---- Stage 5: Timeline ----------------------------------------------------
# Computed deterministically from the protocol's per-step durations — no LLM
# call. Each phase shows its `methodology` (how the duration was computed)
# and `coverage` (fraction of steps with duration data) so a researcher can
# audit every claim. Conservative-by-design: phases with incomplete duration
# data return total_duration=None rather than a misleading partial sum.

class TimelineTask(BaseModel):
    """One step rendered as a timeline task. step_n is the global flat
    step number (matches ProtocolGenerationOutput.steps); useful for
    cross-linking from a Gantt chart back to the underlying step."""
    step_n: int
    name: str                       # step.title
    duration: Optional[str] = None  # ISO 8601, None when step has no duration
    hands_on_time: Optional[str] = None  # not auto-computed yet
    can_parallel: bool = False      # not auto-detected yet


class TimelinePhase(BaseModel):
    """A logical group of timeline tasks — currently 1:1 with procedures.
    `coverage` is the fraction of tasks with duration data; `methodology`
    is a one-line plain-English description of how `duration` was
    computed (so the user can audit / reproduce)."""
    id: str                         # "phase-{procedure_index}"
    name: str                       # procedure.name
    duration: Optional[str] = None  # sum of task durations; None if any missing
    tasks: list[TimelineTask]
    depends_on: list[str] = Field(default_factory=list)
    parallel_with: list[str] = Field(default_factory=list)
    # Defensibility / citations:
    procedure_index: int            # back-link to source procedure
    coverage: float = 1.0           # 0..1 fraction of tasks with duration data
    methodology: str                # "Sum of N step durations from procedure 'X'"


class TimelineOutput(BaseModel):
    """Stage 5 output. Deterministic; same protocol -> same timeline.
    `assumptions` documents what the compute does NOT cover (hands-on
    time, parallelization opportunities, calendar constraints)."""
    phases: list[TimelinePhase]
    total_duration: Optional[str] = None  # ISO 8601 sum across phases
    critical_path: list[str]              # phase IDs in dependency order
    assumptions: list[str] = Field(default_factory=list)
    earliest_completion_date: Optional[str] = None
    generated_at: str = Field(default_factory=now)


# ---- Stage 6: Validation -------------------------------------------------
# Mix of deterministic + LLM. Deterministic: aggregating procedure-level
# success criteria + controls into experiment-level lists; extracting
# effect size from hypothesis.expected via regex; computing n_per_group
# via the standard two-sample formula. LLM: failure_modes (forced to
# cite specific procedures/steps so every concern is auditable).

class EffectSize(BaseModel):
    """Quantitative effect size extracted from the hypothesis (or
    assumed when explicit values aren't present). `type` values:
    'cohens_d' | 'percent_change_absolute' | 'percent_change_relative' |
    'fold_change' | 'odds_ratio' | 'unspecified'."""
    value: float
    type: str
    derived_from: str  # citation, e.g. "hypothesis.expected: '+15 percentage points'"


class PowerCalculation(BaseModel):
    """Standard two-sample power calculation. The formula and every
    input assumption is surfaced — researchers can audit / re-derive
    by hand without leaving the page."""
    statistical_test: str
    alpha: float                    # typically 0.05
    power: float                    # typically 0.80
    effect_size: EffectSize
    n_per_group: int
    groups: int
    total_n: int
    formula: str                    # plain-English formula description
    assumptions: list[str] = Field(default_factory=list)
    rationale: str


class SuccessCriterion(BaseModel):
    """Experiment-level success criterion. Richer than the procedure-
    level ProcedureSuccessCriterion (adds statistical_test,
    expected_value). `derived_from` cites the source — procedure
    name or hypothesis field — so every criterion is auditable."""
    id: str
    criterion: str
    measurement_method: str
    threshold: str
    statistical_test: Optional[str] = None
    expected_value: Optional[str] = None
    derived_from: str  # "procedure 'Cell Freezing'" | "hypothesis.dependent" | "hypothesis.expected"


class Control(BaseModel):
    """Experimental control aggregated from outline.overall_controls +
    per-procedure controls."""
    name: str
    type: Literal["positive", "negative", "vehicle", "sham"]
    purpose: str
    derived_from: str  # "outline.overall_controls" | "procedure 'X'.controls"


class FailureMode(BaseModel):
    """A way the experiment can fail to give a clean answer. LLM-
    generated but REQUIRED to cite a specific procedure or step;
    concerns without grounding get filtered out by the parser."""
    mode: str
    likely_cause: str
    mitigation: str
    cites: str  # "procedure 'X'" | "step N (procedure 'Y')"


class ValidationOutput(BaseModel):
    """Stage 6 output. Defensible by construction: every criterion
    and control cites its source; failure modes cite specific
    procedures; power calc shows formula + assumptions explicitly.
    `methodology` is a top-level audit summary."""
    success_criteria: list[SuccessCriterion]
    controls: list[Control]
    failure_modes: list[FailureMode]
    power_calculation: Optional[PowerCalculation] = None
    expected_outcome_summary: str
    go_no_go_threshold: str
    methodology: str
    generated_at: str = Field(default_factory=now)


# ---- Stage 7: Critique ---------------------------------------------------
# Single LLM call. Output schema FORCES every risk + confounder to carry
# `cites` pointing to a known procedure name (or step "N (procedure X)",
# or a hypothesis field). The parser validates against the protocol's
# procedure list and drops anything ungrounded — a critique entry without
# a citation is a vibes-based concern, not an auditable one.

class Risk(BaseModel):
    """A specific risk to the experiment producing a clean answer.
    `severity` reflects how strongly it could compromise the result.
    `category` lets the FE group risks by type. `cites` is REQUIRED."""
    name: str
    severity: Literal["low", "medium", "high"]
    category: Literal["statistical", "experimental", "biological", "technical", "ethical", "regulatory"]
    description: str
    mitigation: str
    cites: str  # "procedure 'X'" | "step N (procedure 'Y')" | "hypothesis.{field}"


class Confounder(BaseModel):
    """A variable that could confound the dependent measurement.
    Different from a Risk — confounders are variables the experiment
    fails to control for, not steps that can fail."""
    variable: str
    why_confounding: str
    control_strategy: str
    cites: str


class CritiqueOutput(BaseModel):
    """Stage 7 output. `overall_assessment` summarizes go/no-go from
    the risk profile; `methodology` documents how the critique was
    produced (model + citation enforcement) so the audit trail lives
    with the data."""
    risks: list[Risk]
    confounders: list[Confounder]
    overall_assessment: str
    recommendation: Literal["proceed", "proceed_with_caution", "revise_design"]
    methodology: str
    generated_at: str = Field(default_factory=now)


# ---- ExperimentPlan (blackboard) -----------------------------------------

class ExperimentPlanMeta(BaseModel):
    generated_at: str
    model_id: str
    pipeline_version: str = "v0.1.0"
    feedback_applied: bool = False
    feedback_session_ids: Optional[list[str]] = None


class ExperimentPlan(BaseModel):
    """Shared blackboard. Stage outputs are Optional - populated as stages
    complete. Other stages stubbed as Any until their Pydantic models land."""
    id: str
    hypothesis: Hypothesis

    lit_review: Optional[LitReviewSession] = None
    # Stages 2-8 will get their own concrete Pydantic models as their
    # runners are implemented. Until then, dict[str, Any] keeps these
    # fields JSON-shaped while still letting downstream code treat
    # them like ordinary mappings — preferable to bare Any, which
    # bypasses Pydantic validation entirely.
    protocol: Optional[ProtocolGenerationOutput] = None
    materials: Optional[MaterialsOutput] = None
    budget: Optional[dict[str, Any]] = None          # -> BudgetOutput
    timeline: Optional[TimelineOutput] = None
    validation: Optional[ValidationOutput] = None
    critique: Optional[CritiqueOutput] = None
    summary: Optional[dict[str, Any]] = None         # -> SummaryOutput

    status: dict[StageName, StageStatus]
    created_at: str
    updated_at: str
    meta: ExperimentPlanMeta

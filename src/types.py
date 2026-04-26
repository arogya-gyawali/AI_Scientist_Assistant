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


class ProtocolStep(BaseModel):
    """A single executable instruction. `body_md` is the human-readable
    action; `params` is the structured extraction the FE can render as a
    parameters table. `source_step_refs` cites the protocols.io step ids
    that informed this step (auditability)."""
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
    procedure-writer agent owns — context isolation by construction."""
    name: str
    intent: str
    steps: list[ProtocolStep]
    equipment: list[str] = Field(default_factory=list)
    reagents: list[str] = Field(default_factory=list)
    deviations_from_source: list[Deviation] = Field(default_factory=list)
    source_protocol_ids: list[str] = Field(default_factory=list)
    success_criteria: list[ProcedureSuccessCriterion] = Field(default_factory=list)


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
    timeline: Optional[dict[str, Any]] = None        # -> TimelineOutput
    validation: Optional[dict[str, Any]] = None      # -> ValidationOutput
    critique: Optional[dict[str, Any]] = None        # -> DesignCritique
    summary: Optional[dict[str, Any]] = None         # -> SummaryOutput

    status: dict[StageName, StageStatus]
    created_at: str
    updated_at: str
    meta: ExperimentPlanMeta

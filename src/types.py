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
    cached_tavily_context: str
    user_decision: Literal["pending", "proceed", "refine", "abandon"] = "pending"


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
    protocol: Optional[Any] = None        # ProtocolGenerationOutput (TBD)
    materials: Optional[Any] = None       # MaterialsOutput (TBD)
    budget: Optional[Any] = None          # BudgetOutput (TBD)
    timeline: Optional[Any] = None        # TimelineOutput (TBD)
    validation: Optional[Any] = None      # ValidationOutput (TBD)
    critique: Optional[Any] = None        # DesignCritique (TBD)
    summary: Optional[Any] = None         # SummaryOutput (TBD)

    status: dict[StageName, StageStatus]
    created_at: str
    updated_at: str
    meta: ExperimentPlanMeta

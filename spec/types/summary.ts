import type { Hypothesis, ISO8601, StageName, StageStatus } from './shared';
import type { LitReviewSession } from './lit-review';
import type { ProtocolGenerationOutput } from './protocol';
import type { MaterialsOutput } from './materials';
import type { BudgetOutput } from './budget';
import type { TimelineOutput } from './timeline';
import type { ValidationOutput } from './validation';
import type { DesignCritique } from './critique';

export type RiskAssessment = {
  risk: string;
  likelihood: 'low' | 'medium' | 'high';
  impact: 'low' | 'medium' | 'high';
};

export type SummaryOutput = {
  tldr: string;
  key_decisions: string[];
  risk_assessment: RiskAssessment[];
  novelty_position: string;
};

export type ExperimentPlanMeta = {
  generated_at: ISO8601;
  model_id: string;
  pipeline_version: string;
  feedback_applied: boolean;
  feedback_session_ids?: string[];
};

// Shared blackboard. Every stage reads and writes fields here directly.
// Stage outputs are optional — populated as stages complete; absent fields = not yet generated.
export type ExperimentPlan = {
  id: string;

  // Required input — populated at creation
  hypothesis: Hypothesis;

  // Stage outputs — optional, populated by their respective stages
  lit_review?: LitReviewSession;
  protocol?: ProtocolGenerationOutput;
  materials?: MaterialsOutput;
  budget?: BudgetOutput;
  timeline?: TimelineOutput;
  validation?: ValidationOutput;
  critique?: DesignCritique;
  summary?: SummaryOutput;

  // Per-stage lifecycle
  status: Record<StageName, StageStatus>;

  // Meta
  created_at: ISO8601;
  updated_at: ISO8601;
  meta: ExperimentPlanMeta;
};

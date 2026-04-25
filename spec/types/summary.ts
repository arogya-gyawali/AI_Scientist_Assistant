import type { Hypothesis, ISO8601 } from './shared';
import type { LitReviewSession } from './lit-review';
import type { ProtocolGenerationOutput } from './protocol';
import type { MaterialsOutput } from './materials';
import type { BudgetOutput } from './budget';
import type { TimelineOutput } from './timeline';
import type { ValidationOutput } from './validation';

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

export type ExperimentPlan = {
  id: string;
  hypothesis: Hypothesis;
  lit_review: LitReviewSession;
  protocol: ProtocolGenerationOutput;
  materials: MaterialsOutput;
  budget: BudgetOutput;
  timeline: TimelineOutput;
  validation: ValidationOutput;
  summary: SummaryOutput;
  meta: ExperimentPlanMeta;
};

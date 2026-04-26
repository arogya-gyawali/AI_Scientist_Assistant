import type { Domain, ISO8601, StageName } from './shared';

// Stages that accept scientist corrections. Lit review and summary are excluded:
// lit review is a search result, not a generated plan section; summary is purely derived.
export type FeedbackStage = Exclude<StageName, 'lit_review' | 'summary'>;

export type StageFeedback = {
  id: string;
  plan_id: string;
  stage: FeedbackStage;
  experiment_type: string;
  domain: Domain;
  target_field_path: string;
  original_value: unknown;
  corrected_value: unknown;
  rationale: string;
  reviewer_id?: string;
  applied_in_future: number;
  created_at: ISO8601;
};

import type { Domain, ISO8601 } from './shared';

export type FeedbackStage =
  | 'protocol'
  | 'materials'
  | 'budget'
  | 'timeline'
  | 'validation';

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

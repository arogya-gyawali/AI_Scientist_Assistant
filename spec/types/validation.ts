export type SuccessCriterion = {
  id: string;
  criterion: string;
  measurement_method: string;
  threshold: string;
  statistical_test?: string;
  expected_value?: string;
};

export type FailureMode = {
  mode: string;
  likely_cause: string;
  mitigation: string;
};

export type Control = {
  name: string;
  type: 'positive' | 'negative' | 'vehicle' | 'sham';
  purpose: string;
};

export type ValidationOutput = {
  success_criteria: SuccessCriterion[];
  controls: Control[];
  failure_modes: FailureMode[];
  expected_outcome_summary: string;
  go_no_go_threshold: string;
};

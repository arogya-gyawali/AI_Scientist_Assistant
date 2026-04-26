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

export type EffectSize = {
  value: number;
  type: string; // 'cohens_d' | 'percent_change' | 'fold_change' | 'odds_ratio' | ...
};

export type PowerCalculation = {
  statistical_test: string;            // e.g. "two-tailed Student's t-test"
  alpha: number;                       // typically 0.05
  power: number;                       // typically 0.80
  effect_size: EffectSize;
  n_per_group: number;
  groups: number;
  total_n: number;
  assumptions: string[];               // e.g. "normally distributed", "equal variance"
  rationale: string;                   // why this effect size and power
};

export type ValidationOutput = {
  success_criteria: SuccessCriterion[];
  controls: Control[];
  failure_modes: FailureMode[];
  power_calculation: PowerCalculation;
  expected_outcome_summary: string;
  go_no_go_threshold: string;
};

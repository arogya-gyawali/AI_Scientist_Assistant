import type { ISO8601 } from './shared';

// Open-ended category — common values listed below but new categories can appear.
// 'controls' | 'confounders' | 'sample_size' | 'alternative_hypotheses' | 'reproducibility'
// | 'feasibility' | 'ethics' | 'measurement' | 'novelty' | 'statistical_validity' | ...
export type ConcernCategory = string;

export type DesignConcern = {
  id: string;
  category: ConcernCategory;
  severity: 'high' | 'medium' | 'low';
  description: string;
  suggestion: string;
  cited_step?: number;       // optional FK to ProtocolStep.n
};

export type DesignCritique = {
  overall_soundness: 'strong' | 'acceptable' | 'concerns' | 'major_issues';
  concerns: DesignConcern[];
  missing_controls: string[];
  missing_considerations: string[];
  strengths: string[];               // what the design does well — credibility comes from acknowledging this
  reviewer_perspective: string;      // 1–2 sentences in the voice of a senior PI / hostile reviewer
  reviewed_at: ISO8601;
};

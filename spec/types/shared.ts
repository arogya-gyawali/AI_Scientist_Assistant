export type ISO8601 = string;
export type DOI = string;
export type URL = string;

export type Money = {
  amount: number;
  currency: string; // ISO 4217 code, e.g. 'USD', 'EUR', 'JPY', 'CHF'
};

// ISO 8601 duration string, e.g. "PT2H30M" (2.5 hours), "P3D" (3 days), "P2W" (2 weeks)
export type Duration = string;

// Numeric value + unit pair. Used in Stage 2 step parameters for volume,
// temperature, concentration, speed. Duration stays as ISO 8601 string.
export type Quantity = {
  value: number;
  unit: string; // 'mL' | 'uL' | 'C' | 'rpm' | 'g' | 'M' | 'mM' | 'ng/uL' | ...
};

export type Citation = {
  source: string; // 'protocols.io' | 'tavily' | 'paper' | 'vendor' | 'llm_estimate' | 'supplier_lookup' | ...
  confidence: 'high' | 'medium' | 'low';
  doi?: DOI;
  url?: URL;
  title?: string;
  authors?: string[];
  year?: number;
  venue?: string;            // Journal / preprint server / publication venue, e.g. "Nature Reviews Microbiology"
  snippet?: string;
  relevance_score?: number;  // 0-1; UI may render as percentage ("71%")
  description?: string;      // Neutral, factual paper description ("Reviews CRP-cAMP regulation..."). LLM-generated. Lit-review refs.
  matched_on?: string[];     // Concept tags surfaced as chips ("E. coli", "Glucose", "Catabolite repression"). Lit-review refs.
  importance?: string;       // "Why this matched" — LLM brief on relevance to the user's hypothesis. Lit-review refs.
};

// Scope is bioscience: 'cell_biology' | 'diagnostics' | 'gut_health' |
// 'microbiology' | 'immunology' | 'neuroscience' | 'plant_science' | etc.
// Out-of-scope domains (climate, materials, pure chemistry) not supported.
export type Domain = string;

export type StageName =
  | 'lit_review'   // Stage 1
  | 'protocol'     // Stage 2
  | 'materials'    // Stage 3
  | 'budget'       // Stage 4
  | 'timeline'     // Stage 5
  | 'validation'   // Stage 6
  | 'critique'     // Stage 7
  | 'summary';     // Stage 8

export type StageStatus =
  | { state: 'not_started' }
  | { state: 'running'; started_at: ISO8601 }
  | { state: 'complete'; completed_at: ISO8601 }
  | { state: 'failed'; failed_at: ISO8601; error: string };

export type Hypothesis = {
  id: string;
  text: string;
  domain?: Domain;
  intervention?: string;
  measurable_outcome?: string;
  control_implied?: string;
  created_at: ISO8601;
};

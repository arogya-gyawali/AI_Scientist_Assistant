export type ISO8601 = string;
export type DOI = string;
export type URL = string;

export type Money = {
  amount: number;
  currency: string; // ISO 4217 code, e.g. 'USD', 'EUR', 'JPY', 'CHF'
};

// ISO 8601 duration string, e.g. "PT2H30M" (2.5 hours), "P3D" (3 days), "P2W" (2 weeks)
export type Duration = string;

export type Citation = {
  source: string; // 'protocols.io' | 'tavily' | 'paper' | 'vendor' | 'llm_estimate' | ...
  confidence: 'high' | 'medium' | 'low';
  doi?: DOI;
  url?: URL;
  title?: string;
  authors?: string[];
  year?: number;
  snippet?: string;
  relevance_score?: number;
};

export type Domain = string;

export type Hypothesis = {
  id: string;
  text: string;
  domain?: Domain;
  intervention?: string;
  measurable_outcome?: string;
  control_implied?: string;
  created_at: ISO8601;
};

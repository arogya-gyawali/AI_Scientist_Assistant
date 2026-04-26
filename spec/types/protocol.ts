import type { DOI, Domain, Duration } from './shared';

export type ProtocolStep = {
  n: number;
  title: string;
  body_md: string;
  duration: Duration;
  equipment_needed: string[];
  reagents_referenced: string[];
  notes?: string;
  cited_doi?: DOI;
};

export type CitedProtocol = {
  doi: DOI;
  title: string;
  contribution_weight: number;
};

export type RegulatoryRequirement = {
  requirement: string;                 // 'IACUC approval', 'IRB approval', 'BSL-2 facility', 'IBC review', 'EHS sign-off', ...
  authority: string;                   // 'institutional', 'FDA', 'NIH', 'OSHA', 'EPA', ...
  applicable_because: string;          // condition that triggers this requirement
  estimated_lead_time?: Duration;      // e.g. "P3M" for typical 3-month IACUC review
  notes?: string;
};

export type ProtocolGenerationOutput = {
  experiment_type: string;
  domain: Domain;
  steps: ProtocolStep[];
  cited_protocols: CitedProtocol[];
  regulatory_requirements: RegulatoryRequirement[];
  assumptions: string[];
  total_steps: number;
};

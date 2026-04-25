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

export type ProtocolGenerationOutput = {
  experiment_type: string;
  domain: Domain;
  steps: ProtocolStep[];
  cited_protocols: CitedProtocol[];
  assumptions: string[];
  total_steps: number;
};

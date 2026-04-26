import type { DOI, Domain, Duration, Quantity } from './shared';

// Structured parameters extracted from a step. All optional — not every
// step has every parameter (e.g., a "label tubes" step has none). The
// `other` escape hatch is for params we haven't promoted to first-class
// fields yet (pH, voltage, gas mix, ...).
export type StepParams = {
  volume?: Quantity;
  temperature?: Quantity;
  duration?: Duration;
  concentration?: Quantity;
  speed?: Quantity;            // rpm or g
  other?: Record<string, string>;
};

// How to prepare a custom buffer / mix the researcher must make themselves.
// Only emitted for non-commercial reagents (not "PBS" or "DMEM" if bought).
export type ReagentRecipe = {
  name: string;                  // 'M9 buffer (10x)'
  components: string[];          // ['3 g Na2HPO4', '0.5 g NaCl', ...]
  notes?: string;                // 'Sterilize by autoclaving'
};

export type ProtocolStep = {
  n: number;
  title: string;
  body_md: string;
  duration?: Duration;
  equipment_needed: string[];
  reagents_referenced: string[];
  params: StepParams;
  controls: string[];
  todo_for_researcher: string[];   // researcher must resolve before running
  source_step_refs: string[];      // protocols.io step ids that informed this
  notes?: string;
  cited_doi?: DOI;
  // Quality-of-life additions (Nature Protocols / protocols.io style):
  anticipated_outcome?: string;    // 'Pellet ~3 mm³, no debris'
  is_critical: boolean;            // ▲ — flag steps where most failures happen
  is_pause_point: boolean;         // ▶ — safe stopping point
  troubleshooting: string[];       // known failure modes
  reagent_recipes: ReagentRecipe[];
};

// An adaptation the LLM made from a source protocol. Required so the
// researcher can audit every change rather than trusting blindly.
export type Deviation = {
  from_source: string;
  to_adapted: string;
  reason: string;
  source_protocol_id: string;
  confidence: 'low' | 'medium' | 'high';
};

// Per-procedure pass/fail or quantitative measurement. Procedure-level only.
// Stage 6 (Validation) owns the experiment-wide SuccessCriterion type,
// which is richer (statistical_test, expected_value).
export type ProcedureSuccessCriterion = {
  what: string;            // 'post-thaw cell viability'
  how_measured: string;    // 'trypan blue exclusion, hemocytometer'
  threshold?: string;      // '>=85%'
  pass_fail: boolean;
};

// Logical group of steps. Each procedure is the unit a single procedure-
// writer agent owns — context isolation by construction.
export type Procedure = {
  name: string;
  intent: string;
  steps: ProtocolStep[];
  equipment: string[];
  reagents: string[];
  deviations_from_source: Deviation[];
  source_protocol_ids: string[];
  success_criteria: ProcedureSuccessCriterion[];
  total_duration?: Duration;       // ISO 8601 sum of step durations (deterministic)
};

export type CitedProtocol = {
  doi?: DOI;
  protocols_io_id?: string;
  title: string;
  contribution_weight: number;     // 0-1
};

export type RegulatoryRequirement = {
  requirement: string;             // 'IACUC approval', 'IRB approval', 'BSL-2 facility', ...
  authority: string;               // 'institutional', 'FDA', 'NIH', 'OSHA', 'EPA', ...
  applicable_because: string;      // condition that triggers this requirement
  estimated_lead_time?: Duration;  // e.g. 'P3M' for typical 3-month IACUC review
  notes?: string;
};

// Stage 2 output. `procedures` is the primary view (grouped, with
// deviations + success criteria); `steps` is a flat re-numbered view for
// FE rendering as a checklist or for downstream stages.
export type ProtocolGenerationOutput = {
  experiment_type: string;
  domain?: Domain;
  procedures: Procedure[];
  steps: ProtocolStep[];           // flat view, derived from procedures
  cited_protocols: CitedProtocol[];
  regulatory_requirements: RegulatoryRequirement[];
  assumptions: string[];
  total_steps: number;
  source_protocol_ids: string[];
  generated_at: string;            // ISO 8601
  total_duration?: Duration;       // ISO 8601 sum across all procedures
};

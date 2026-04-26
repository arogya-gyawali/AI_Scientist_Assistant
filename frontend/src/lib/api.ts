/**
 * Typed fetch wrappers for the Flask API.
 *
 * Three endpoints exposed by the backend:
 *   POST /lit-review   Stage 1 novelty check; returns plan_id for chaining.
 *   POST /protocol     Stage 2 protocol generation. Accepts {plan_id} OR
 *                      {structured} for fresh starts. Returns frontend_view
 *                      (FE-shaped) AND raw (rich Pydantic shape).
 *   POST /materials    Stage 3 materials roll-up. Same input forms as
 *                      /protocol; requires the plan to have a protocol
 *                      already populated when chaining via plan_id.
 *
 * In dev, vite.config.ts proxies these paths to http://localhost:5000.
 * In production we expect same-origin or a reverse proxy upstream — so
 * URLs stay relative regardless of environment.
 */

// ----- Shared types (mirror backend Pydantic) -----------------------------

export type StructuredHypothesis = {
  research_question: string;
  subject: string;
  independent: string;
  dependent: string;
  conditions: string;
  expected: string;
};

export type Citation = {
  source: string;
  confidence: "high" | "medium" | "low";
  title?: string;
  authors?: string[];
  year?: number;
  venue?: string;
  doi?: string;
  url?: string;
  snippet?: string;
  relevance_score?: number;
  matched_on?: string[];
  description?: string;
  importance?: string;
};

export type LitReviewResponse = {
  signal: "novel" | "similar_work_exists" | "exact_match_found";
  description: string;
  references: Citation[];
  searched_at: string;
  tavily_query: string;   // legacy field name; populated with whatever query was sent
  summary: string;
  plan_id: string;        // <-- chains to /protocol and /materials
};

// ----- /protocol response -------------------------------------------------

export type Phase = "Preparation" | "Experiment" | "Measurement" | "Analysis";

export type FEReagentRecipe = {
  name: string;
  components: string[];
  notes?: string;
};

export type FEProtocolStep = {
  title: string;
  detail: string;
  citation?: string;
  phase: Phase;
  meta?: string;                     // first-priority param chip
  // Phase 3+ rich-rendering fields. Optional with defaults so the FE
  // can render either the new procedure-grouped view OR the older flat
  // view depending on whether the BE shipped them.
  params_summary?: string[];         // ALL params, ordered: temp/vol/dur/conc/speed
  equipment?: string[];              // step.equipment_needed
  reagents?: string[];               // step.reagents_referenced
  todos?: string[];                  // step.todo_for_researcher
  is_critical?: boolean;
  is_pause_point?: boolean;
  anticipated_outcome?: string;
  troubleshooting?: string[];
  reagent_recipes?: FEReagentRecipe[];
  duration?: string;                 // raw ISO 8601, FE formats for display
  procedure_name?: string;
  step_number_in_procedure?: number; // 1-based; powers "2.1.3" numbering
  step_id?: string;                  // "p{proc_idx}-s{step_idx}", for cross-links
};

export type FEDeviation = {
  from_source: string;
  to_adapted: string;
  reason: string;
  source_protocol_id: string;
  confidence: "low" | "medium" | "high";
};

export type FESuccessCriterion = {
  what: string;
  how_measured: string;
  threshold?: string;
  pass_fail: boolean;
};

export type FEProcedureGroup = {
  name: string;
  intent: string;
  steps: FEProtocolStep[];
  deviations_from_source: FEDeviation[];
  success_criteria: FESuccessCriterion[];
  total_duration?: string;
  procedure_index: number;           // 1-based
  source_protocol_ids: string[];
};

export type FEProtocolView = {
  // Backwards-compatible flat list — present even when procedures[] is.
  steps: FEProtocolStep[];
  experiment_type: string;
  total_steps: number;
  cited_protocols: Array<{
    title: string;
    doi?: string;
    protocols_io_id?: string;
    contribution_weight: number;
  }>;
  // New rich-shape fields. Optional so the FE can detect "is this an
  // upgraded backend?" by checking whether `procedures.length > 0`.
  procedures?: FEProcedureGroup[];
  total_duration?: string;           // protocol-wide ISO 8601 sum
  assumptions?: string[];
};

export type ProtocolResponse = {
  plan_id: string;
  frontend_view: FEProtocolView;
  raw: unknown;
};

// ----- /materials response -----------------------------------------------

export type FEReagent = {
  name: string;
  purpose: string;
  supplier?: string;     // "TBD" until Stage 4 backfills
  catalog?: string;      // "TBD" until Stage 4 backfills
  qty: string;
  qtyContext?: string;
  note?: { kind: "cold" | "lead"; text: string };
  // Cross-links: which step IDs reference this material. Step IDs are
  // "p{proc_idx}-s{step_idx}" (matches FEProtocolStep.step_id).
  used_in_steps?: string[];
  material_id?: string;
};

export type FEMaterialGroup = {
  group: string;
  description: string;
  items: FEReagent[];
};

export type FEMaterialsView = {
  groups: FEMaterialGroup[];
  total_unique_items: number;
  gaps: string[];
};

export type MaterialsResponse = {
  plan_id: string;
  frontend_view: FEMaterialsView;
  raw: unknown;
};

// ----- /timeline response (Stage 5) ---------------------------------------
// Deterministic compute — no LLM call. Each phase carries `methodology`
// (plain-English description of how its duration was computed) and
// `coverage` (fraction of steps with duration data) so the FE can show
// audit-friendly chips. `total_duration` is null when ANY phase had
// incomplete data — conservative-by-design.

export type TimelineTask = {
  step_n: number;
  name: string;
  duration?: string;          // ISO 8601, null when step has no duration
  hands_on_time?: string;
  can_parallel: boolean;
};

export type TimelinePhase = {
  id: string;                 // "phase-{procedure_index}"
  name: string;
  duration?: string;          // null when ANY task duration is missing
  tasks: TimelineTask[];
  depends_on: string[];
  parallel_with: string[];
  procedure_index: number;
  coverage: number;           // 0..1
  methodology: string;
};

export type TimelineOutput = {
  phases: TimelinePhase[];
  total_duration?: string;    // null when ANY phase is missing
  critical_path: string[];    // phase IDs in dependency order
  assumptions: string[];
  earliest_completion_date?: string;
  generated_at: string;
};

export type TimelineResponse = {
  plan_id: string;
  timeline: TimelineOutput;
};

// ----- /validation response (Stage 6) -------------------------------------
// Mostly deterministic + 1 LLM call (failure_modes). Every output carries
// `derived_from` or `cites` so the FE can show audit chips.

export type EffectSize = {
  value: number;
  type: string;            // "cohens_d" | "percent_change_absolute" | ...
  derived_from: string;
};

export type PowerCalculation = {
  statistical_test: string;
  alpha: number;
  power: number;
  effect_size: EffectSize;
  n_per_group: number;
  groups: number;
  total_n: number;
  formula: string;
  assumptions: string[];
  rationale: string;
};

export type ValidationSuccessCriterion = {
  id: string;
  criterion: string;
  measurement_method: string;
  threshold: string;
  statistical_test?: string;
  expected_value?: string;
  derived_from: string;
};

export type ValidationControl = {
  name: string;
  type: "positive" | "negative" | "vehicle" | "sham";
  purpose: string;
  derived_from: string;
};

export type FailureMode = {
  mode: string;
  likely_cause: string;
  mitigation: string;
  cites: string;
};

export type ValidationOutput = {
  success_criteria: ValidationSuccessCriterion[];
  controls: ValidationControl[];
  failure_modes: FailureMode[];
  power_calculation?: PowerCalculation;
  expected_outcome_summary: string;
  go_no_go_threshold: string;
  methodology: string;
  generated_at: string;
};

export type ValidationResponse = {
  plan_id: string;
  validation: ValidationOutput;
};

// ----- /critique response (Stage 7) ---------------------------------------
// Single LLM call. Output schema forces every risk and confounder to
// carry `cites` pointing to a procedure/step/hypothesis-field. The
// parser validates against the protocol's procedure list and drops
// ungrounded entries server-side, so anything that reaches the FE is
// auditable.

export type Risk = {
  name: string;
  severity: "low" | "medium" | "high";
  category: "statistical" | "experimental" | "biological" | "technical" | "ethical" | "regulatory";
  description: string;
  mitigation: string;
  cites: string;
};

export type Confounder = {
  variable: string;
  why_confounding: string;
  control_strategy: string;
  cites: string;
};

export type CritiqueOutput = {
  risks: Risk[];
  confounders: Confounder[];
  overall_assessment: string;
  recommendation: "proceed" | "proceed_with_caution" | "revise_design";
  methodology: string;
  generated_at: string;
};

export type CritiqueResponse = {
  plan_id: string;
  critique: CritiqueOutput;
};

// ----- Error shape -------------------------------------------------------

export type ApiError = {
  error: string;
  detail: string | unknown[];
};

export class ApiException extends Error {
  status: number;
  body: ApiError;
  constructor(status: number, body: ApiError) {
    super(formatApiErrorMessage(body));
    this.status = status;
    this.body = body;
  }
}

// Pydantic's ValidationError.errors() yields an array of {loc, msg, type, ...}.
// Surface "<dotted.path>: <msg>" so the user sees which field failed instead
// of just "validation_error".
function formatApiErrorMessage(body: ApiError): string {
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const parts = body.detail.map((d) => {
      if (typeof d !== "object" || d === null) return String(d);
      const item = d as { loc?: unknown; msg?: unknown };
      const msg = typeof item.msg === "string" ? item.msg : JSON.stringify(d);
      const path = Array.isArray(item.loc)
        ? item.loc
            .filter((p) => typeof p === "string" || typeof p === "number")
            .join(".")
        : "";
      return path ? `${path}: ${msg}` : msg;
    });
    return parts.join("; ");
  }
  return body.error;
}

// ----- Internals ---------------------------------------------------------

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let parsed: ApiError;
    try {
      parsed = await res.json();
    } catch {
      parsed = { error: "network_error", detail: `HTTP ${res.status}` };
    }
    throw new ApiException(res.status, parsed);
  }
  return res.json() as Promise<T>;
}

// ----- Public API --------------------------------------------------------

export type LitReviewRequest =
  | { structured: StructuredHypothesis; domain?: string }
  | { id: string; structured: StructuredHypothesis; domain?: string; created_at: string };

export function postLitReview(
  body: LitReviewRequest,
  signal?: AbortSignal,
): Promise<LitReviewResponse> {
  return postJson("/lit-review", body, signal);
}

// /protocol /materials /timeline accept the same {plan_id} OR {structured} forms.
export type StageRequest =
  | { plan_id: string }
  | { structured: StructuredHypothesis; domain?: string };

export function postProtocol(body: StageRequest, signal?: AbortSignal): Promise<ProtocolResponse> {
  return postJson("/protocol", body, signal);
}

export function postMaterials(body: StageRequest, signal?: AbortSignal): Promise<MaterialsResponse> {
  return postJson("/materials", body, signal);
}

export function postTimeline(body: StageRequest, signal?: AbortSignal): Promise<TimelineResponse> {
  return postJson("/timeline", body, signal);
}

export function postValidation(body: StageRequest, signal?: AbortSignal): Promise<ValidationResponse> {
  return postJson("/validation", body, signal);
}

export function postCritique(body: StageRequest, signal?: AbortSignal): Promise<CritiqueResponse> {
  return postJson("/critique", body, signal);
}

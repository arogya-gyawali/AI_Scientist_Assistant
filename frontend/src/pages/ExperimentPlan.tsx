import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  postCritique,
  postMaterials,
  postProtocol,
  postTimeline,
  postValidation,
  type CritiqueOutput,
  type FEMaterialGroup,
  type FEMaterialsView,
  type FEProcedureGroup,
  type FEProtocolStep,
  type FEProtocolView,
  type StructuredHypothesis,
  type TimelineOutput,
  type ValidationOutput,
} from "@/lib/api";
import { composeHypothesisQuestion } from "@/lib/hypothesis";
import {
  AlertTriangle,
  ArrowRight,
  Beaker,
  Check,
  ChevronDown,
  ClipboardList,
  Coins,
  Download,
  FlaskConical,
  GitBranch,
  PauseCircle,
  Pencil,
  Snowflake,
  Target,
  Timer,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const HYPOTHESIS_SUMMARY =
  "Increasing glucose concentration in M9 minimal media reduces the specific growth rate of E. coli K-12 above 10 mM, due to catabolite repression under aerobic conditions at 37 °C.";

type Phase = "Preparation" | "Experiment" | "Measurement" | "Analysis";

type ProtocolStep = {
  title: string;
  detail: string;
  citation?: string;
  phase: Phase;
  meta?: string; // short tag e.g. "37 °C", "OD600"
};

const PROTOCOL_STEPS: ProtocolStep[] = [
  {
    title: "Prepare M9 minimal media stock",
    detail:
      "Autoclave 1 L M9 salts (Na₂HPO₄ 6.78 g/L, KH₂PO₄ 3 g/L, NaCl 0.5 g/L, NH₄Cl 1 g/L). Add 2 mM MgSO₄ and 100 µM CaCl₂ post-autoclave.",
    citation: "Cold Spring Harbor Protocols",
    phase: "Preparation",
    meta: "Autoclave · post-add salts",
  },
  {
    title: "Prepare a 500 mM glucose feed solution",
    detail:
      "Filter-sterilize through 0.22 µm PES. Store at 4 °C, equilibrate to room temperature before use.",
    phase: "Preparation",
    meta: "0.22 µm · 4 °C",
  },
  {
    title: "Streak E. coli K-12 MG1655 from glycerol stock",
    detail:
      "Plate on LB agar, incubate 16 h at 37 °C. Pick a single colony into 5 mL LB, grow overnight in a shaking incubator at 220 rpm.",
    citation: "protocols.io",
    phase: "Preparation",
    meta: "37 °C · 220 rpm",
  },
  {
    title: "Acclimate cells to M9 + glucose 5 mM",
    detail:
      "Wash overnight culture twice in pre-warmed M9 (no carbon). Inoculate to OD600 ≈ 0.05 in M9 + 5 mM glucose. Grow to OD600 ≈ 0.4.",
    phase: "Experiment",
    meta: "OD600 0.05 → 0.4",
  },
  {
    title: "Set up the glucose-gradient panel",
    detail:
      "In a 96-well clear-bottom plate, prepare 8 conditions in triplicate: 0, 1, 2.5, 5, 10, 15, 20, 25 mM glucose in M9. Final volume 200 µL.",
    phase: "Experiment",
    meta: "8 conditions × 3",
  },
  {
    title: "Inoculate to OD600 = 0.05 across all wells",
    detail:
      "Use the acclimated culture as inoculum. Seal with breathable membrane to maintain aerobic conditions.",
    phase: "Experiment",
    meta: "Aerobic · sealed",
  },
  {
    title: "Run kinetic OD600 measurements",
    detail:
      "Plate reader at 37 °C, OD600 every 10 min for 18 h, with 30 s orbital shake before each read.",
    citation: "BioTek Synergy H1",
    phase: "Measurement",
    meta: "37 °C · 10 min · 18 h",
  },
  {
    title: "Compute specific growth rate µ per condition",
    detail:
      "Fit log-linear regression to the exponential phase (OD600 0.1 → 0.4). Report µ ± SE across triplicates.",
    phase: "Analysis",
    meta: "Log-linear fit",
  },
  {
    title: "Quality controls",
    detail:
      "Include media-only blanks and a 5 mM glucose reference on every plate. Re-run any plate where blank drift > 0.02 OD.",
    phase: "Analysis",
    meta: "Blanks · drift < 0.02",
  },
];

// Phase visual tokens — reuse design system colors only
const PHASE_META: Record<
  Phase,
  { dot: string; tint: string; border: string; label: string }
> = {
  Preparation: {
    dot: "bg-sage",
    tint: "bg-sage-wash",
    border: "border-sage/40",
    label: "Preparation",
  },
  Experiment: {
    dot: "bg-primary",
    tint: "bg-primary/[0.06]",
    border: "border-primary/30",
    label: "Experiment",
  },
  Measurement: {
    dot: "bg-[hsl(38_70%_45%)]",
    tint: "bg-[hsl(38_70%_92%)]",
    border: "border-[hsl(38_70%_55%)]/40",
    label: "Measurement",
  },
  Analysis: {
    dot: "bg-ink",
    tint: "bg-rule-soft/60",
    border: "border-rule",
    label: "Analysis",
  },
};

const PHASE_ORDER: Phase[] = [
  "Preparation",
  "Experiment",
  "Measurement",
  "Analysis",
];

type Reagent = {
  name: string;
  purpose: string;
  supplier?: string;
  catalog?: string;
  qty: string;
  qtyContext?: string;
  note?: { kind: "cold" | "lead"; text: string };
};

type MaterialGroup = {
  group: string;
  description: string;
  items: Reagent[];
};

const MATERIALS: MaterialGroup[] = [
  {
    group: "Reagents",
    description:
      "Defined-media salts and the carbon source under test. All ACS-grade or better.",
    items: [
      {
        name: "D-(+)-Glucose, ≥99.5%",
        purpose: "Carbon source · variable under test",
        supplier: "Sigma-Aldrich",
        catalog: "G7021-100G",
        qty: "100 g",
        qtyContext: "sufficient for ~20 runs",
      },
      {
        name: "M9 Minimal Salts, 5×",
        purpose: "Defined growth medium base",
        supplier: "Sigma-Aldrich",
        catalog: "M6030-1KG",
        qty: "1 kg",
        qtyContext: "≈ 200 L of 1× M9",
      },
      {
        name: "MgSO₄ anhydrous",
        purpose: "Cofactor · post-autoclave addition",
        supplier: "Fisher Scientific",
        catalog: "M65-500",
        qty: "500 g",
        qtyContext: "single bottle, multi-year stock",
      },
      {
        name: "CaCl₂ dihydrate",
        purpose: "Cofactor · trace addition",
        supplier: "Sigma-Aldrich",
        catalog: "C3306-500G",
        qty: "500 g",
        qtyContext: "single bottle, multi-year stock",
        note: { kind: "cold", text: "Hygroscopic — store dry, sealed" },
      },
    ],
  },
  {
    group: "Strains & consumables",
    description:
      "Biological starting material and single-use plasticware sized for a 96-well kinetic run.",
    items: [
      {
        name: "E. coli K-12 MG1655",
        purpose: "Model organism · strain under test",
        supplier: "ATCC",
        catalog: "700926",
        qty: "1 vial",
        qtyContext: "lyophilised, revive once",
        note: { kind: "cold", text: "Ship on dry ice · store at −80 °C" },
      },
      {
        name: "96-well clear-bottom plate",
        purpose: "Kinetic OD600 measurement vessel",
        supplier: "Corning",
        catalog: "3631",
        qty: "2 cases",
        qtyContext: "100 plates · ≈ 12 full runs",
      },
      {
        name: "Breathable sealing film",
        purpose: "Maintain aerobic conditions in plate",
        supplier: "Sigma-Aldrich",
        catalog: "Z380059",
        qty: "1 pack",
        qtyContext: "100 sheets",
      },
      {
        name: "0.22 µm PES filter units",
        purpose: "Sterile filtration of glucose feed",
        supplier: "Millipore",
        catalog: "SCGPU05RE",
        qty: "1 pack",
        qtyContext: "50 units",
        note: { kind: "lead", text: "Lead time: 5–7 days" },
      },
    ],
  },
];

// Procurement summary — kept in sync with MATERIALS above
const MATERIALS_SUMMARY = {
  totalCost: 1500,
  leadTime: "2–3 days",
};

const BUDGET = [
  { label: "Reagents (M9, glucose, salts)", amount: 240 },
  { label: "Plates, films, filters", amount: 180 },
  { label: "Plate-reader time (~12 h)", amount: 360 },
  { label: "Tech labour (~24 h)", amount: 720 },
];
const BUDGET_TOTAL = BUDGET.reduce((a, b) => a + b.amount, 0);

const TIMELINE = [
  { week: "Week 1", phase: "Setup & QC", note: "Media prep, strain revival, plate-reader calibration." },
  { week: "Week 2", phase: "Pilot run", note: "Single-replicate gradient to validate dynamic range." },
  { week: "Week 3", phase: "Full experiment", note: "Triplicate plates across the 8-condition gradient." },
  { week: "Week 4", phase: "Analysis", note: "Fit µ, error analysis, draft figures and methods." },
];

const VALIDATION = {
  measured: [
    "OD600 every 10 min for 18 h, per well, in triplicate.",
    "Specific growth rate µ (h⁻¹) fit from exponential phase.",
  ],
  success: [
    "≥ 15% reduction in µ between 5 mM and 25 mM glucose.",
    "Saturation behavior (plateau) above ~15 mM with R² > 0.9 on a Monod-style fit.",
    "Blank drift < 0.02 OD across the 18 h window.",
  ],
};

const FEASIBILITY = {
  body:
    "This is a low-risk, single-investigator experiment that fits comfortably in a four-week window with standard plate-reader time. The reagents are inexpensive and shelf-stable, and the readout (OD600 kinetics) is robust and well-characterized for E. coli in M9.",
  assumptions: [
    "Standard lab equipment available (plate reader, shaking incubator, 4 °C / −80 °C storage).",
    "OD600 measurements are calibrated and within the reader's linear range (≤ 0.8).",
    "Aerobic conditions maintained consistently across all wells (breathable seal, orbital shake).",
    "E. coli K-12 MG1655 stock is genetically stable and free of contaminating colonies.",
  ],
  risks: [
    "Wall growth or biofilm at high OD can bias µ — mitigate with a shake step before every read.",
    "Glucose carryover from acclimation could mask the low-end of the gradient — wash twice in carbon-free M9.",
    "Plate-position effects (edge wells) — randomize layout across replicates.",
  ],
};

const STAGES = [
  "Designing protocol…",
  "Selecting materials…",
  "Estimating cost and timeline…",
] as const;

// Parse an ISO 8601 duration to total seconds. Returns null on shapes
// we don't handle. Used for the running-clock cumulative sum.
function parseIso8601ToSeconds(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const s = iso.trim();
  // Weeks-only — P2W
  const wOnly = /^P(\d+)W$/.exec(s);
  if (wOnly) return parseInt(wOnly[1], 10) * 7 * 86400;
  // Combined P{D}T{H}{M}{S}, with all parts optional
  const m = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$/.exec(s);
  if (!m) return null;
  const [, d, h, mn, sc] = m;
  let total = 0;
  if (d) total += parseInt(d, 10) * 86400;
  if (h) total += parseInt(h, 10) * 3600;
  if (mn) total += parseInt(mn, 10) * 60;
  if (sc) total += parseFloat(sc);
  // "P" with no parts is malformed → null
  return d || h || mn || sc ? total : null;
}

// Format a cumulative elapsed seconds as a compact "t = ..." label for
// the running clock. Examples: 0 → "0", 300 → "5m", 5400 → "1h 30m",
// 93600 → "1d 2h". We round seconds down to whole minutes for anything
// over a minute — sub-minute precision is noise on a multi-day plan.
function formatElapsed(seconds: number): string {
  if (seconds <= 0) return "0";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const totalMin = Math.floor(seconds / 60);
  if (totalMin < 60) return `${totalMin}m`;
  const totalHours = Math.floor(totalMin / 60);
  const remMin = totalMin % 60;
  if (totalHours < 24) {
    return remMin > 0 ? `${totalHours}h ${remMin}m` : `${totalHours}h`;
  }
  const days = Math.floor(totalHours / 24);
  const remHours = totalHours % 24;
  return remHours > 0 ? `${days}d ${remHours}h` : `${days}d`;
}

// Humanize an ISO 8601 duration ("PT5M", "P1DT2H") for display chips.
// BE-side `_humanize_duration` does the same on per-step `meta`; this is
// for total_duration values that come back as raw ISO. Falls back to the
// raw string on shapes we don't handle (P2W, P1Y, etc.).
function humanizeDuration(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const s = iso.trim();
  // Combined P{D}T{H}{M} — e.g. P1DT2H30M
  const combined = /^P(\d+)D(?:T(?:(\d+)H)?(?:(\d+)M)?)?$/.exec(s);
  if (combined) {
    const [, d, h, m] = combined;
    const parts = [`${d} d`];
    if (h) parts.push(`${h} h`);
    if (m) parts.push(`${m} min`);
    return parts.join(" ");
  }
  // Time only — e.g. PT1H30M, PT5M, PT45S
  const time = /^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$/.exec(s);
  if (time) {
    const [, h, m, sec] = time;
    const parts: string[] = [];
    if (h) parts.push(`${h} h`);
    if (m) parts.push(`${m} min`);
    if (sec && !h && !m) parts.push(`${sec} s`);
    return parts.length ? parts.join(" ") : null;
  }
  // Days only — P3D, P1W
  const dOnly = /^P(\d+)D$/.exec(s);
  if (dOnly) return `${dOnly[1]} d`;
  const wOnly = /^P(\d+)W$/.exec(s);
  if (wOnly) return `${wOnly[1]} wk`;
  return s;
}

// =============================================================================
// Plan confidence — derived from the BE outputs, not hardcoded
// =============================================================================
// Three boolean factors map to a five-bucket label and dot meter:
//
//   protocol_similarity:  any cited source has contribution_weight >= 0.5
//                         (the relevance filter found a meaningfully similar
//                         protocol, not just thematic adjacency)
//   established_assays:   at least one Measurement-phase procedure has
//                         populated success_criteria (we know how to
//                         validate the readout, not just take it)
//   standard_equipment:   >= 70% of equipment items have a populated `purpose`
//                         (procurement-ready spec; no mystery hardware)
//
// Total active count → confidence label + dots filled. The description
// adapts to which factors are active so the line under the banner
// actually says something useful.
//
// Falls back to the original hardcoded banner when neither protocol nor
// materials API data is present (mock-only / design-demo mode).

type ConfidenceFactor = {
  label: string;
  active: boolean;
};

type PlanConfidence = {
  label: string;
  dotsFilled: number;          // 1-5
  description: string;
  factors: ConfidenceFactor[];
};

function computePlanConfidence(
  protocolView: FEProtocolView | null,
  materialsView: FEMaterialsView | null,
): PlanConfidence | null {
  if (!protocolView && !materialsView) return null;

  // 1. Protocol similarity — strongest signal we have. Built directly
  // from the relevance filter's output via cited_protocols.contribution_weight.
  const cited = protocolView?.cited_protocols ?? [];
  const maxWeight = cited.length
    ? Math.max(...cited.map((c) => c.contribution_weight ?? 0))
    : 0;
  const protocolSimilarity = maxWeight >= 0.5;

  // 2. Established assays — sage when at least one Measurement procedure
  // has success_criteria populated. The "if Measurement and has criteria"
  // pairing matters: a Preparation procedure with criteria is not enough
  // to say the assay is established, because the readout itself is what
  // we're trying to validate.
  const procs = protocolView?.procedures ?? [];
  const hasMeasurementWithCriteria = procs.some(
    (p) =>
      p.success_criteria.length > 0 &&
      p.steps.some((s) => s.phase === "Measurement"),
  );
  // If the architect didn't classify any procedure as Measurement (rare
  // but possible — see lactobacillus run earlier), fall back to "any
  // procedure has success criteria". A weaker signal but better than
  // false-grey when the writer did the right thing — this fallback
  // applies regardless of procedure count, including single-procedure
  // plans where the criteria are the only validation we have.
  const hasAnyCriteria = procs.some((p) => p.success_criteria.length > 0);
  const establishedAssays = hasMeasurementWithCriteria || hasAnyCriteria;

  // 3. Standard equipment — sage when most equipment items have a
  // populated purpose (which the materials roll-up populates with the
  // spec when no purpose is given). 70% threshold so a single mystery
  // item doesn't tank the confidence.
  const equipment = (materialsView?.groups ?? [])
    .filter((g) => g.group.toLowerCase().includes("equipment"))
    .flatMap((g) => g.items);
  const totalEq = equipment.length;
  // Any non-empty purpose counts. Length-based filters (the previous
  // `> 5` guard) wrongly excluded valid concise lab purposes like
  // "PCR", "Spin", "Wash", "Mix" — exactly the items most likely to
  // have terse purpose copy.
  const speccedEq = equipment.filter(
    (e) => e.purpose && e.purpose.trim().length > 0,
  ).length;
  // If materials haven't loaded yet, treat this factor as not-yet-known
  // (default to inactive for the dial; the chip will simply be grey).
  const standardEquipment = totalEq > 0 && speccedEq / totalEq >= 0.7;

  const factors: ConfidenceFactor[] = [
    { label: "Protocol similarity", active: protocolSimilarity },
    { label: "Established assays", active: establishedAssays },
    { label: "Standard equipment", active: standardEquipment },
  ];

  const activeCount = factors.filter((f) => f.active).length;

  // Map active count to bucket. We never go to 5/5 with only 3 factors
  // because the dial deliberately implies more dimensions than we
  // actually compute — bumping all-active to "High" + 5 dots feels right
  // visually and matches the original mock's intent.
  let label: string;
  let dotsFilled: number;
  switch (activeCount) {
    case 3: label = "High"; dotsFilled = 5; break;
    case 2: label = "Moderate–High"; dotsFilled = 4; break;
    case 1: label = "Moderate"; dotsFilled = 3; break;
    default: label = "Low"; dotsFilled = 2;
  }

  // Description is composed from the actual run data — experiment type,
  // grounding signal strength, validated procedure count, equipment
  // coverage. References *this* experiment specifically rather than
  // serving as evergreen marketing copy.
  const expType = (protocolView?.experiment_type ?? "").trim();
  const procWithCriteriaCount = procs.filter((p) => p.success_criteria.length > 0).length;
  const procCount = procs.length;

  const groundingPart = cited.length > 0
    ? `${cited.length} cited protocol${cited.length === 1 ? "" : "s"} (max ${Math.round(maxWeight * 100)}% relevance)`
    : "no direct protocol grounding";

  const procPart = procWithCriteriaCount > 0
    ? `${procWithCriteriaCount} of ${procCount} procedure${procCount === 1 ? "" : "s"} with success criteria`
    : procCount > 0
      ? `${procCount} procedure${procCount === 1 ? "" : "s"} (none with formal success criteria yet)`
      : null;

  const equipPart = totalEq > 0
    ? `${speccedEq} of ${totalEq} equipment items specced`
    : null;

  // Lead with the experiment type so the user immediately sees "this is
  // about MY experiment". Then chain the three facts; drop the ones we
  // don't have data for (e.g. equipment when materials hasn't loaded).
  const leadIn = expType ? `${expType.charAt(0).toUpperCase() + expType.slice(1)} grounded in ` : "Plan grounded in ";
  const middle = [groundingPart, procPart, equipPart].filter(Boolean).join("; ");
  const description = `${leadIn}${middle}.`;

  return { label, dotsFilled, description, factors };
}


// =============================================================================
// Rich procedure-grouped rendering (Phase 3 — surface what the backend ships)
// =============================================================================
// One block per procedure. Each block stacks: header (numbered name, intent,
// total-duration chip, source citations), per-step rows with structured
// metadata (params, equipment, reagents, anticipated outcome, todos,
// troubleshooting, recipes, critical/pause markers), and trailing
// collapsibles for deviations + success criteria.

function ProcedureBlock({
  proc,
  stepClock,
  procedureClock,
  showClock,
}: {
  proc: FEProcedureGroup;
  stepClock: Map<string, number>;
  procedureClock: Map<number, number>;
  showClock: boolean;
}) {
  const dur = humanizeDuration(proc.total_duration);
  const procStartSec = procedureClock.get(proc.procedure_index);
  return (
    <section
      id={`proc-${proc.procedure_index}`}
      aria-labelledby={`proc-${proc.procedure_index}-title`}
      className="px-7 py-7 sm:px-9 sm:py-9"
    >
      {/* Procedure header */}
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-rule pb-4">
        <span className="font-mono-notebook text-[14px] font-medium uppercase tracking-[0.18em] text-primary">
          {proc.procedure_index}.
        </span>
        <h3
          id={`proc-${proc.procedure_index}-title`}
          className="font-serif-display text-[26px] leading-[1.15] text-ink"
        >
          {proc.name}
        </h3>
        {/* Procedure-level start time (running clock) — sits next to the
            duration chip when both are present. Helps researchers see
            when a procedure begins relative to the start of the plan. */}
        {showClock && procStartSec !== undefined && (
          <span className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft">
            starts at t&nbsp;=&nbsp;{formatElapsed(procStartSec)}
          </span>
        )}
        {dur && (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper-raised px-2.5 py-1 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft">
            <Timer aria-hidden className="h-3 w-3" strokeWidth={1.75} />
            {dur}
          </span>
        )}
      </header>

      {proc.intent && (
        <p className="mt-3 max-w-3xl text-[14px] leading-[1.65] text-ink-soft">
          {proc.intent}
        </p>
      )}

      {/* Steps */}
      <ol className="mt-5 space-y-5">
        {proc.steps.map((step, idx) => (
          <ProcedureStepRow
            key={step.step_id || idx}
            step={step}
            procedureIndex={proc.procedure_index}
            stepIndex={step.step_number_in_procedure || idx + 1}
            elapsedSec={
              showClock && step.step_id
                ? stepClock.get(step.step_id) ?? null
                : null
            }
          />
        ))}
      </ol>

      {/* Deviations from source — the audit trail. Collapsed by default
          because the FE prioritizes scanning steps; researchers expand it
          when they want to see what was adapted. */}
      {proc.deviations_from_source.length > 0 && (
        <details className="group/dev mt-6 rounded-md border border-rule bg-paper-raised">
          <summary className="flex cursor-pointer items-center justify-between gap-3 px-5 py-3 font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-ink-soft hover:text-ink">
            <span className="inline-flex items-center gap-2">
              <GitBranch aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
              Deviations from source ({proc.deviations_from_source.length})
            </span>
            <ChevronDown aria-hidden className="h-4 w-4 transition-transform group-open/dev:rotate-180" strokeWidth={1.75} />
          </summary>
          <ul className="space-y-4 border-t border-rule px-5 py-4">
            {proc.deviations_from_source.map((dev, i) => (
              <li key={i} className="text-[14px] leading-[1.65]">
                <p className="text-ink-soft">
                  <span className="font-medium text-ink">From:</span> {dev.from_source}
                </p>
                <p className="mt-0.5 text-ink-soft">
                  <span className="font-medium text-ink">To:</span> {dev.to_adapted}
                </p>
                <p className="mt-1 text-ink-soft">
                  <span className="font-medium text-ink">Why:</span> {dev.reason}
                </p>
                <p className="mt-1.5 inline-flex items-center gap-2 font-mono-notebook text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Source: {dev.source_protocol_id} · Confidence: {dev.confidence}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Success criteria — the "did this procedure work" checklist. */}
      {proc.success_criteria.length > 0 && (
        <details className="group/sc mt-3 rounded-md border border-rule bg-paper-raised">
          <summary className="flex cursor-pointer items-center justify-between gap-3 px-5 py-3 font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-ink-soft hover:text-ink">
            <span className="inline-flex items-center gap-2">
              <Target aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
              Success criteria ({proc.success_criteria.length})
            </span>
            <ChevronDown aria-hidden className="h-4 w-4 transition-transform group-open/sc:rotate-180" strokeWidth={1.75} />
          </summary>
          <ul className="space-y-3 border-t border-rule px-5 py-4">
            {proc.success_criteria.map((sc, i) => (
              <li key={i} className="grid grid-cols-[auto_1fr] gap-3 text-[14px] leading-[1.6]">
                <Check aria-hidden className="mt-0.5 h-4 w-4 flex-shrink-0 text-sage" strokeWidth={2} />
                <div>
                  <p className="text-ink">
                    {sc.what}
                    {sc.threshold && (
                      <span className="ml-2 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-primary">
                        [{sc.threshold}]
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 text-ink-soft">
                    <span className="font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                      Measured by:
                    </span>{" "}
                    {sc.how_measured}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function ProcedureStepRow({
  step,
  procedureIndex,
  stepIndex,
  elapsedSec,
}: {
  step: FEProtocolStep;
  procedureIndex: number;
  stepIndex: number;
  /** Cumulative time from t=0 at which this step begins. null when no
   *  step in the plan has duration data — the running clock would be
   *  meaningless and we suppress it entirely. */
  elapsedSec: number | null;
}) {
  const dur = humanizeDuration(step.duration);
  return (
    <li
      id={step.step_id}
      className="grid grid-cols-[auto_1fr] gap-5 step-block"
    >
      {/* Left gutter: step numbering ("2.1") + running-clock chip below it
          when the plan has duration data. The clock shows time AT THE
          START of the step (t=0 for step 1, then accumulates). */}
      <div className="flex flex-col items-center gap-1.5">
        <span className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
          {procedureIndex}.{stepIndex}
        </span>
        {elapsedSec !== null && (
          <span
            className="font-mono-notebook text-[10px] tracking-[0.1em] text-primary"
            title="Cumulative time from start of plan"
          >
            t={formatElapsed(elapsedSec)}
          </span>
        )}
      </div>

      <div className="space-y-3">
        {/* Title row + critical / pause markers + duration chip */}
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
          <h4 className="font-serif-card text-[19px] leading-[1.3] text-ink">
            {step.title}
          </h4>
          {step.is_critical && (
            <span
              className="inline-flex items-center gap-1.5 rounded-sm border border-destructive/30 bg-destructive/[0.06] px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-destructive"
              title="Critical step — high failure rate"
            >
              <AlertTriangle aria-hidden className="h-3 w-3" strokeWidth={2} />
              Critical
            </span>
          )}
          {step.is_pause_point && (
            <span
              className="inline-flex items-center gap-1.5 rounded-sm border border-sage/40 bg-sage-wash px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-[hsl(142_45%_24%)]"
              title="Safe stopping point"
            >
              <PauseCircle aria-hidden className="h-3 w-3" strokeWidth={2} />
              Pause OK
            </span>
          )}
          {dur && (
            <span className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
              <Timer aria-hidden className="h-3 w-3" strokeWidth={1.75} />
              {dur}
            </span>
          )}
          {step.meta && !dur && (
            <span className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
              {step.meta}
            </span>
          )}
        </div>

        {/* Body */}
        <p className="max-w-2xl text-[15px] leading-[1.7] text-ink-soft">
          {step.detail}
        </p>

        {/* Anticipated outcome — green callout, the "what to expect" hint */}
        {step.anticipated_outcome && (
          <div className="rounded-sm border-l-[3px] border-sage bg-sage-wash/40 px-3 py-2 text-[14px] leading-[1.55] text-[hsl(142_45%_22%)]">
            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-sage">
              Expected:
            </span>{" "}
            {step.anticipated_outcome}
          </div>
        )}

        {/* TODO callouts — yellow, demand researcher attention */}
        {(step.todos?.length ?? 0) > 0 && (
          <ul className="space-y-1 rounded-sm border-l-[3px] border-[hsl(38_70%_55%)] bg-[hsl(38_70%_92%)]/40 px-3 py-2">
            {(step.todos ?? []).map((t, i) => (
              <li
                key={i}
                className="text-[14px] leading-[1.55] text-[hsl(28_55%_28%)]"
              >
                <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-[hsl(28_55%_30%)]">
                  ⚠ TODO:
                </span>{" "}
                {t}
              </li>
            ))}
          </ul>
        )}

        {/* Params summary — all params (vol/temp/dur/conc/speed) as chips */}
        {(step.params_summary?.length ?? 0) > 1 && (
          <div className="flex flex-wrap gap-1.5">
            {(step.params_summary ?? []).map((p, i) => (
              <span
                key={i}
                className="inline-flex items-center rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft"
              >
                {p}
              </span>
            ))}
          </div>
        )}

        {/* Equipment + reagents — separate label rows. Reagent names link
            to the materials section by the lower-cased name as anchor. */}
        {(step.equipment?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] leading-[1.5]">
            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Equipment:
            </span>
            {(step.equipment ?? []).map((e, i) => (
              <a
                key={i}
                href={`#mat-${e.toLowerCase().replace(/\s+/g, "-")}`}
                className="inline-flex items-center rounded-sm border border-rule bg-paper px-1.5 py-0.5 text-[12px] text-ink-soft transition-colors hover:border-primary/40 hover:text-primary"
              >
                {e}
              </a>
            ))}
          </div>
        )}
        {(step.reagents?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] leading-[1.5]">
            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Reagents:
            </span>
            {(step.reagents ?? []).map((r, i) => (
              <a
                key={i}
                href={`#mat-${r.toLowerCase().replace(/\s+/g, "-")}`}
                className="inline-flex items-center rounded-sm border border-rule bg-paper px-1.5 py-0.5 text-[12px] text-ink-soft transition-colors hover:border-primary/40 hover:text-primary"
              >
                {r}
              </a>
            ))}
          </div>
        )}

        {/* Reagent recipes — inline expandable per recipe.
            Triggered by a step that introduces a custom buffer. */}
        {(step.reagent_recipes?.length ?? 0) > 0 && (
          <div className="space-y-2">
            {(step.reagent_recipes ?? []).map((rec, i) => (
              <details
                key={i}
                className="group/rec rounded-md border border-rule bg-paper"
              >
                <summary className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft hover:text-ink">
                  <span className="inline-flex items-center gap-2">
                    <Beaker aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
                    Recipe: {rec.name}
                  </span>
                  <ChevronDown aria-hidden className="h-3.5 w-3.5 transition-transform group-open/rec:rotate-180" strokeWidth={1.75} />
                </summary>
                <div className="border-t border-rule px-4 py-3 text-[13px] leading-[1.6] text-ink-soft">
                  <ul className="list-disc pl-4 space-y-0.5">
                    {rec.components.map((c, j) => (
                      <li key={j}>{c}</li>
                    ))}
                  </ul>
                  {rec.notes && (
                    <p className="mt-2 italic text-muted-foreground">
                      {rec.notes}
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        )}

        {/* Troubleshooting — collapsible only when present */}
        {(step.troubleshooting?.length ?? 0) > 0 && (
          <details className="group/ts rounded-md border border-dashed border-rule bg-paper">
            <summary className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft hover:text-ink">
              <span>Troubleshooting ({step.troubleshooting?.length ?? 0})</span>
              <ChevronDown aria-hidden className="h-3.5 w-3.5 transition-transform group-open/ts:rotate-180" strokeWidth={1.75} />
            </summary>
            <ul className="list-disc space-y-1 border-t border-rule px-7 py-3 text-[13px] leading-[1.55] text-ink-soft">
              {(step.troubleshooting ?? []).map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </details>
        )}

        {/* Citation chip — same styling as the legacy text view */}
        {step.citation && (
          <span className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
            <span aria-hidden className="h-1 w-1 rounded-full bg-sage" />
            {step.citation}
          </span>
        )}
      </div>
    </li>
  );
}

const ExperimentPlan = () => {
  const navigate = useNavigate();
  const location = useLocation();
  // Either a plan_id (chained from /literature) OR a structured hypothesis
  // (skipped lit-review). Either is sufficient input for /protocol; if both
  // are missing the page falls back to mocks so the design-only demo runs.
  const navState = (location.state as
    {
      plan_id?: string;
      structured?: StructuredHypothesis;
      domain?: string;
      // Phase F: forwarded from /candidates. When present, /protocol
      // skips its own ranked search and grounds Stage 2 on exactly the
      // protocols the researcher picked, with `researcher_notes`
      // threaded into the architect + writer prompts as binding
      // override.
      selected_protocol_ids?: string[];
      researcher_notes?: string;
    } | null) ?? null;
  const incomingPlanId = navState?.plan_id;
  const incomingStructured = navState?.structured;
  const incomingSelectedIds = navState?.selected_protocol_ids;
  const incomingNotes = navState?.researcher_notes;

  // Section reveal index: 0 nothing, 1 protocol, 2 + materials, 3 + budget+timeline, 4 + validation+feasibility.
  // Real-API path advances reveal as each backend call resolves; mock path
  // ticks through it on a scripted timer (preserved below for the design demo).
  const [stageIdx, setStageIdx] = useState(0);
  const [reveal, setReveal] = useState(0);

  // Real protocol + materials data from the backend. null = still loading
  // (or mock-only mode, in which case `useMockData` below is true). We
  // store the FULL view objects (not just steps[]/groups[]) so the rich
  // procedure-grouped rendering can read procedures + deviations + gaps
  // + total_duration + assumptions without round-tripping the parent state.
  const [apiProtocolView, setApiProtocolView] = useState<FEProtocolView | null>(null);
  const [apiPlanId, setApiPlanId] = useState<string | null>(null);
  const [pdfDownloading, setPdfDownloading] = useState(false);
  const [apiMaterialsView, setApiMaterialsView] = useState<FEMaterialsView | null>(null);
  const [apiTimeline, setApiTimeline] = useState<TimelineOutput | null>(null);
  const [apiValidation, setApiValidation] = useState<ValidationOutput | null>(null);
  const [apiCritique, setApiCritique] = useState<CritiqueOutput | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const useMockData = !incomingPlanId && !incomingStructured;

  useEffect(() => {
    if (useMockData) {
      // Design-mockup path: scripted reveal so the page demos without a backend.
      const t1 = window.setTimeout(() => { setStageIdx(1); setReveal(1); }, 900);
      const t2 = window.setTimeout(() => { setStageIdx(2); setReveal(2); }, 1900);
      const t3 = window.setTimeout(() => { setReveal(3); }, 2700);
      const t4 = window.setTimeout(() => { setReveal(4); }, 3400);
      return () => { [t1, t2, t3, t4].forEach((t) => window.clearTimeout(t)); };
    }

    // Live path: chain /protocol → /materials. The status checklist already
    // shows two stages (Protocol, Materials), so we map them onto stageIdx
    // and bump `reveal` as each section's data arrives.
    const ac = new AbortController();
    // Build /protocol body. Forward the researcher's candidate
    // selection + notes when /candidates handed them off — this is
    // what makes the page actually use the human-in-the-loop pick.
    const protoBody = incomingPlanId
      ? {
          plan_id: incomingPlanId,
          ...(incomingSelectedIds && incomingSelectedIds.length > 0
            ? { selected_protocol_ids: incomingSelectedIds }
            : {}),
          ...(incomingNotes ? { researcher_notes: incomingNotes } : {}),
        }
      : {
          structured: incomingStructured!,
          ...(incomingSelectedIds && incomingSelectedIds.length > 0
            ? { selected_protocol_ids: incomingSelectedIds }
            : {}),
          ...(incomingNotes ? { researcher_notes: incomingNotes } : {}),
        };
    const matsBody = (planId: string) => ({ plan_id: planId });

    setStageIdx(0);
    setReveal(0);

    (async () => {
      try {
        const proto = await postProtocol(protoBody, ac.signal);
        setApiProtocolView(proto.frontend_view);
        setApiPlanId(proto.plan_id);
        setStageIdx(1);
        setReveal(1);

        const mats = await postMaterials(matsBody(proto.plan_id), ac.signal);
        setApiMaterialsView(mats.frontend_view);
        setStageIdx(2);
        setReveal(2);

        // Stage 5: timeline. Cheap deterministic compute (no LLM call)
        // — fast enough to fold into the same chain. If it fails, the
        // FE falls back to the hardcoded TIMELINE constant.
        try {
          const tl = await postTimeline({ plan_id: proto.plan_id }, ac.signal);
          setApiTimeline(tl.timeline);
        } catch {
          // non-fatal — keep going with the hardcoded timeline fallback
        }

        // Stage 6: validation. One LLM call (failure modes) — runs in
        // parallel with the rest of the page reveal. If it fails, the
        // FE falls back to the procedure-derived criteria from Phase A.
        try {
          const val = await postValidation({ plan_id: proto.plan_id }, ac.signal);
          setApiValidation(val.validation);
        } catch {
          // non-fatal — Phase A wiring still gives a procedure-derived
          // criteria list, just without power calc / failure modes.
        }

        // Stage 7: critique. One LLM call (risks + confounders, all
        // citation-validated). If it fails the FE falls back to the
        // hardcoded FEASIBILITY.risks panel.
        try {
          const crit = await postCritique({ plan_id: proto.plan_id }, ac.signal);
          setApiCritique(crit.critique);
        } catch {
          // non-fatal — feasibility risks fallback handles this.
        }

        // The remaining reveal stages (3, 4) gate budget/timeline/validation.
        // Reveal them on a short delay so they stagger into view as the
        // user scrolls.
        const t3 = window.setTimeout(() => setReveal(3), 600);
        const t4 = window.setTimeout(() => setReveal(4), 1200);
        // Stash the timeouts on the abort controller's signal handler.
        ac.signal.addEventListener("abort", () => {
          window.clearTimeout(t3);
          window.clearTimeout(t4);
        });
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setApiError(err instanceof Error ? err.message : "Plan generation failed.");
        // Reveal everything anyway so the user sees the (mock) layout rather
        // than a blank page; the error message will be surfaced near the top.
        setReveal(4);
      }
    })();

    return () => ac.abort();
  }, [incomingPlanId, incomingStructured, incomingSelectedIds, incomingNotes, useMockData]);

  // Display data: prefer backend-driven; fall back to mock constants for
  // mock-only mode or if a section's API call hasn't resolved yet. The
  // flat `protocolSteps` list still feeds the existing UI; `procedures`
  // is the new rich-shape view that drives the procedure-grouped
  // rendering when the backend ships it (Phase 2 adapter).
  const protocolSteps = useMemo<FEProtocolStep[]>(
    () => apiProtocolView?.steps ?? PROTOCOL_STEPS,
    [apiProtocolView],
  );
  const procedures = useMemo<FEProcedureGroup[]>(
    () => apiProtocolView?.procedures ?? [],
    [apiProtocolView],
  );
  // The FE detects the new shape by checking whether procedures[] is
  // populated. Mock-only mode and pre-Phase-2 backends both yield 0
  // procedures, so the existing flat-list view continues to render.
  const hasRichProtocol = procedures.length > 0;
  const protocolTotalDuration = apiProtocolView?.total_duration ?? null;
  const protocolAssumptions = apiProtocolView?.assumptions ?? [];

  // Sentence-cased experiment_type plus first procedure's intent.
  // Falls back to the design-mock subtitle in mock-only mode.
  const protocolSubtitle = useMemo(() => {
    const expType = apiProtocolView?.experiment_type?.trim();
    if (!expType) {
      return "Glucose-gradient kinetic assay in M9 minimal media, plate-reader readout.";
    }
    const capitalized = expType.charAt(0).toUpperCase() + expType.slice(1);
    const firstIntent = procedures[0]?.intent?.trim();
    return firstIntent ? `${capitalized} — ${firstIntent}` : capitalized;
  }, [apiProtocolView, procedures]);

  // Validation aggregate — flatten success_criteria across procedures and
  // dedup how_measured strings (case-insensitive). `useReal` flips on as
  // soon as any procedure carries criteria; mock-only mode renders the
  // hardcoded VALIDATION constant via the `useReal === false` branch in
  // the JSX below.
  const validation = useMemo(() => {
    const aggCriteria = procedures.flatMap((p) =>
      p.success_criteria.map((c) => ({
        what: c.what,
        threshold: c.threshold ?? null,
        fromProcedure: p.name,
        procedureIndex: p.procedure_index,
        howMeasured: c.how_measured,
      })),
    );
    const seenLowered = new Set<string>();
    const measuredMethods = aggCriteria
      .map((c) => c.howMeasured.trim())
      .filter((m) => {
        if (!m) return false;
        const k = m.toLowerCase();
        if (seenLowered.has(k)) return false;
        seenLowered.add(k);
        return true;
      });
    const useReal = aggCriteria.length > 0;
    return {
      aggCriteria,
      useReal,
      measured: useReal ? measuredMethods : VALIDATION.measured,
    };
  }, [procedures]);

  const materialGroups = useMemo<FEMaterialGroup[]>(
    () => apiMaterialsView?.groups ?? MATERIALS,
    [apiMaterialsView],
  );

  // Compute plan confidence from real BE data when available; falls back
  // to null in mock-only mode (the JSX then renders the original hardcoded
  // banner so the design demo still looks complete).
  const planConfidence = useMemo<PlanConfidence | null>(
    () => computePlanConfidence(apiProtocolView, apiMaterialsView),
    [apiProtocolView, apiMaterialsView],
  );

  // Running clock — cumulative time at the START of each step + procedure.
  // Walks all procedures in order; missing durations advance the clock by
  // 0 (the previous step's running time stays). The clock is only useful
  // when at least some steps have durations, so we suppress the chip
  // entirely for plans where nothing has duration data.
  const { stepClock, procedureClock, anyDurations } = useMemo(() => {
    const stepClock = new Map<string, number>();
    const procedureClock = new Map<number, number>();
    let cumSec = 0;
    let anyDurations = false;
    for (const proc of procedures) {
      procedureClock.set(proc.procedure_index, cumSec);
      for (const step of proc.steps) {
        if (step.step_id) stepClock.set(step.step_id, cumSec);
        const stepSec = parseIso8601ToSeconds(step.duration ?? null);
        if (stepSec !== null && stepSec > 0) {
          anyDurations = true;
          cumSec += stepSec;
        }
      }
    }
    return { stepClock, procedureClock, anyDurations };
  }, [procedures]);

  const generating = reveal < 4;

  return (
    <div className="relative min-h-screen bg-paper text-ink">
      <div aria-hidden className="pointer-events-none absolute inset-0 lab-grid" />

      {/* Faint chemical structure, top-right */}
      <svg
        aria-hidden
        viewBox="0 0 200 200"
        className="pointer-events-none absolute right-6 top-20 hidden h-40 w-40 text-ink opacity-[0.05] sm:right-10 sm:top-24 sm:block"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
      >
        <polygon points="100,30 152,60 152,120 100,150 48,120 48,60" />
        <polygon points="100,50 138,72 138,116 100,138 62,116 62,72" />
        <line x1="100" y1="30" x2="100" y2="10" />
        <circle cx="100" cy="6" r="4" />
        <line x1="152" y1="60" x2="172" y2="48" />
        <circle cx="176" cy="46" r="4" />
        <line x1="48" y1="120" x2="28" y2="132" />
        <circle cx="24" cy="134" r="4" />
        <line x1="100" y1="150" x2="100" y2="172" />
        <circle cx="100" cy="176" r="4" />
        <line x1="62" y1="72" x2="48" y2="60" />
        <line x1="138" y1="116" x2="152" y2="120" />
      </svg>

      {/* Header */}
      <header className="relative border-b border-rule">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-10">
          <Link to="/" className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-sm border border-rule bg-paper-raised"
            >
              <FlaskConical className="h-4 w-4 text-primary" strokeWidth={1.5} />
            </span>
            <span className="font-serif-display text-xl tracking-tight text-ink">
              Praxis
            </span>
          </Link>
          <nav className="hidden items-center gap-7 text-sm text-muted-foreground sm:flex">
            <Link className="transition-colors hover:text-ink" to="/drafts">
              Drafts
            </Link>
            <Link className="transition-colors hover:text-ink" to="/library">
              Library
            </Link>
            <Link className="transition-colors hover:text-ink" to="/account">
              Account
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative mx-auto max-w-5xl px-6 pb-24 pt-12 sm:px-10 sm:pt-16">
        {apiError && (
          <section
            aria-label="Generation error"
            role="alert"
            className="mb-8 relative overflow-hidden rounded-md border border-destructive/30 bg-paper-raised"
          >
            <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-destructive" />
            <div className="flex items-start gap-4 px-7 py-5">
              <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
              <div className="space-y-1.5">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-destructive">
                  Live generation failed — showing demo data
                </p>
                <p className="text-[14px] leading-[1.55] text-ink-soft">
                  {apiError}
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Step indicator + recap */}
        <section aria-labelledby="page-title" className="mb-12">
          <p className="font-mono-notebook text-[13px] uppercase tracking-[0.22em] text-muted-foreground">
            <span className="text-primary">●</span>&nbsp;&nbsp;Step{" "}
            <span className="text-ink">03</span> of 04 — Experiment Plan
          </p>
          <h1
            id="page-title"
            className="mt-5 font-serif-display text-[44px] leading-[1.04] text-ink sm:text-[60px]"
          >
            How would you{" "}
            <span className="italic text-primary">run this</span>?
          </h1>

          {/* Confidence banner — derived from real BE data when present.
              Three branches:
              - Mock-only mode (no plan_id and no structured): show the
                static "Moderate–High" mock so the design demo still
                looks complete when navigated to directly.
              - Live path, API still loading: show a "Computing…"
                placeholder. The previous behavior of dropping back to
                the static mock during loading made it look like the
                banner was lying about a real run, so explicit
                placeholder copy is preferable.
              - Live path, planConfidence resolved: show the real
                computed values. */}
          {(() => {
            // Live path but waiting on API — render a loading placeholder
            // that's clearly distinct from real data.
            if (!useMockData && !planConfidence) {
              return (
                <div
                  role="note"
                  aria-label="Plan confidence (computing)"
                  className="mt-7 flex flex-col gap-4 rounded-md border border-rule bg-paper-raised px-6 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-7"
                >
                  <div className="flex items-center gap-5">
                    <div className="flex flex-col items-start gap-1.5">
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                        Plan confidence
                      </p>
                      <span
                        className="text-[26px] italic leading-none text-ink-soft"
                        style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                      >
                        Computing…
                      </span>
                    </div>
                    <span aria-hidden className="hidden h-10 w-px bg-rule sm:block" />
                    <p
                      className="hidden max-w-md text-[15px] italic leading-snug text-muted-foreground sm:block"
                      style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                    >
                      Waiting for the protocol and materials pipeline to complete before scoring confidence.
                    </p>
                  </div>
                </div>
              );
            }

            // Mock-only fallback — design-demo state.
            const banner = planConfidence ?? {
              label: "Moderate–High",
              dotsFilled: 4,
              description:
                "Based on protocol similarity to published assays and availability of established readouts.",
              factors: [
                { label: "Protocol similarity", active: true },
                { label: "Established assays", active: true },
                { label: "Standard equipment", active: false },
              ],
            };
            return (
              <>
                <div
                  role="note"
                  aria-label="Plan confidence"
                  className="mt-7 flex flex-col gap-4 rounded-md border border-rule bg-paper-raised px-6 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-7"
                >
                  <div className="flex items-center gap-5">
                    <div className="flex flex-col items-start gap-1.5">
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                        Plan confidence
                      </p>
                      <div className="flex items-baseline gap-3">
                        <span
                          className="text-[26px] italic leading-none text-ink"
                          style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                        >
                          {banner.label}
                        </span>
                        {/* Dot meter — 5 dots, first N filled. */}
                        <span aria-hidden className="flex items-center gap-1">
                          {Array.from({ length: 5 }).map((_, i) => (
                            <span
                              key={i}
                              className={
                                "h-2 w-2 rounded-full " +
                                (i < banner.dotsFilled ? "bg-ink" : "bg-rule")
                              }
                            />
                          ))}
                        </span>
                      </div>
                    </div>
                    <span aria-hidden className="hidden h-10 w-px bg-rule sm:block" />
                    <p
                      className="hidden max-w-md text-[15px] italic leading-snug text-ink-soft sm:block"
                      style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                    >
                      {banner.description}
                    </p>
                  </div>
                  <ul className="flex flex-wrap items-center gap-2">
                    {banner.factors.map((f) => (
                      <li
                        key={f.label}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft"
                      >
                        <span
                          aria-hidden
                          className={
                            "h-1.5 w-1.5 rounded-full " +
                            (f.active ? "bg-sage" : "bg-rule")
                          }
                        />
                        {f.label}
                      </li>
                    ))}
                  </ul>
                </div>
                {/* Mobile-only sub-line for the banner explanation */}
                <p
                  className="mt-3 text-[14px] italic leading-snug text-ink-soft sm:hidden"
                  style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                >
                  {banner.description}
                </p>
              </>
            );
          })()}

          <div className="mt-8 rounded-md border border-rule bg-paper-raised">
            <div className="flex items-start justify-between gap-4 border-b border-rule px-6 py-4">
              <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-ink-soft">
                Your hypothesis
              </p>
              <Link
                to="/"
                className="inline-flex items-center gap-1.5 font-mono-notebook text-[12px] uppercase tracking-[0.18em] text-ink-soft transition-colors hover:text-primary"
              >
                <Pencil className="h-3 w-3" strokeWidth={1.75} />
                Edit
              </Link>
            </div>
            <p
              className="px-6 py-5 text-[20px] leading-[1.55] text-ink"
              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
            >
              {/* Hypothesis recap from real router state when present;
                  HYPOTHESIS_SUMMARY mock keeps direct-page-navigation
                  demos from breaking. The research_question field is
                  the most prose-friendly; falls back to a composed
                  sentence (shared util — same logic LiteratureCheck
                  uses for its tokenized breakdown) if it's blank. */}
              {incomingStructured?.research_question?.trim()
                || (incomingStructured
                    ? composeHypothesisQuestion(incomingStructured)
                    : HYPOTHESIS_SUMMARY)}
            </p>
          </div>

          {/* Plan at a glance — jump nav so users don't have to scroll the whole page */}
        </section>

        {/* Phase 5b: at-a-glance summary card. Lives between hypothesis
            and the jump nav so a researcher can scan totals before
            committing to read the whole plan. Only shown when the live
            backend has materials data — mock-only mode hides it because
            MATERIALS counts wouldn't reflect a real plan. */}
        {reveal >= 2 && apiMaterialsView && (
          <section
            aria-label="Plan summary"
            className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4 animate-in fade-in slide-in-from-bottom-1 duration-500"
          >
            {(() => {
              const counts = { reagent: 0, equipment: 0, consumable: 0, organism_or_cell: 0 };
              for (const g of materialGroups) {
                const lower = g.group.toLowerCase();
                if (lower.includes("equipment")) counts.equipment += g.items.length;
                else if (lower.includes("consumable")) counts.consumable += g.items.length;
                else if (lower.includes("reagent")) counts.reagent += g.items.length;
                else counts.organism_or_cell += g.items.length;  // cells/organisms
              }
              const stats = [
                { value: counts.reagent, label: "Reagents", icon: <Beaker className="h-3.5 w-3.5" strokeWidth={1.5} /> },
                { value: counts.equipment, label: "Equipment", icon: <FlaskConical className="h-3.5 w-3.5" strokeWidth={1.5} /> },
                { value: counts.consumable, label: "Consumables", icon: <ClipboardList className="h-3.5 w-3.5" strokeWidth={1.5} /> },
                { value: counts.organism_or_cell, label: "Cells/Organisms", icon: <Target className="h-3.5 w-3.5" strokeWidth={1.5} /> },
              ];
              return stats.map((s, i) => (
                <a
                  key={i}
                  href="#materials-title"
                  className="group flex items-center gap-3 rounded-md border border-rule bg-paper-raised px-4 py-3 transition-colors hover:border-ink/30"
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-sm border border-rule bg-paper text-ink-soft">
                    {s.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="font-serif-display text-[22px] leading-none text-ink">
                      {s.value}
                    </p>
                    <p className="mt-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      {s.label}
                    </p>
                  </div>
                </a>
              ));
            })()}
          </section>
        )}

        {/* Plan at a glance — sticky jump nav so users don't have to scroll the whole page */}
        {reveal >= 4 && (
          <nav
            aria-label="Jump to plan section"
            className="sticky top-3 z-30 mb-8 rounded-md border border-rule bg-paper-raised/95 px-5 py-3 shadow-[0_4px_16px_-8px_hsl(var(--ink)/0.18)] backdrop-blur supports-[backdrop-filter]:bg-paper-raised/80 sm:px-6"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                Plan at a glance — jump to
              </p>
              <ul className="flex flex-wrap items-center gap-1.5">
                {[
                  { id: "protocol-title", label: "Protocol" },
                  { id: "materials-title", label: "Materials" },
                  { id: "budget-title", label: "Budget" },
                  { id: "validation-title", label: "Validation" },
                  { id: "feasibility-title", label: "Feasibility" },
                ].map((item) => (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      className="inline-flex items-center rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft transition-colors hover:border-ink/40 hover:text-ink"
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        )}

        {/* Generation status */}
        {generating && (
          <section
            aria-label="Generating plan"
            className="mb-12 rounded-md border border-rule bg-paper-raised px-7 py-6"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-serif-display text-[22px] text-ink">
                {STAGES[Math.min(stageIdx, STAGES.length - 1)]}
              </p>
              <p className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground">
                {Math.min(stageIdx + 1, STAGES.length)} / {STAGES.length}
              </p>
            </div>
            <div className="mt-5 h-[3px] w-full overflow-hidden rounded-sm bg-rule-soft/70">
              <div
                className="h-full bg-sage transition-[width] duration-[700ms] ease-out"
                style={{ width: `${Math.min((reveal / 4) * 100, 95)}%` }}
              />
            </div>
            <ul className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {STAGES.map((s, i) => (
                <li
                  key={s}
                  className={
                    "flex items-center gap-2 font-mono-notebook text-[11px] uppercase tracking-[0.18em] " +
                    (i <= stageIdx ? "text-ink" : "text-muted-foreground/60")
                  }
                >
                  <span
                    aria-hidden
                    className={
                      "flex h-4 w-4 items-center justify-center rounded-full border " +
                      (i < stageIdx
                        ? "border-sage bg-sage text-paper"
                        : i === stageIdx
                          ? "border-ink bg-paper"
                          : "border-rule bg-paper")
                    }
                  >
                    {i < stageIdx ? (
                      <Check className="h-2.5 w-2.5" strokeWidth={3} />
                    ) : null}
                  </span>
                  {s.replace("…", "")}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* PROTOCOL — primary, emphasized */}
        {reveal >= 1 && (
          <section
            aria-labelledby="protocol-title"
            className="mb-10 animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <div className="overflow-hidden rounded-md border-2 border-ink/80 bg-paper-raised">
              <header className="flex flex-col gap-5 border-b border-rule px-7 py-6 sm:px-9 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex items-start gap-4">
                  <span
                    aria-hidden
                    className="mt-1 flex h-9 w-9 items-center justify-center rounded-sm border border-rule bg-paper"
                  >
                    <ClipboardList className="h-4 w-4 text-ink" strokeWidth={1.5} />
                  </span>
                  <div>
                    <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                      Primary · {protocolSteps.length} steps
                      {hasRichProtocol && (
                        <span> · {procedures.length} procedures</span>
                      )}
                    </p>
                    <h2
                      id="protocol-title"
                      className="mt-1.5 font-serif-display text-[34px] leading-tight text-ink"
                    >
                      Protocol
                    </h2>
                    <p
                      className="mt-2 max-w-[28rem] text-[15px] italic leading-snug text-ink-soft"
                      style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                    >
                      {/* Subtitle composed from real BE data: experiment_type
                          + the first procedure's intent. Both are deterministic
                          (no new LLM call); same plan -> same subtitle. */}
                      {protocolSubtitle}
                    </p>
                    {/* Phase 5a: total time chip — populated when ALL step
                        durations are present (BE returns null otherwise to
                        avoid misleading partial sums). */}
                    {humanizeDuration(protocolTotalDuration) && (
                      <p className="mt-3 inline-flex items-center gap-2 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft">
                        <Timer aria-hidden className="h-3 w-3" strokeWidth={1.75} />
                        Total: {humanizeDuration(protocolTotalDuration)}
                      </p>
                    )}
                  </div>
                </div>

                {/* View toggle + PDF download. The download button is
                    suppressed in mock-only mode (no plan_id and no
                    structured hypothesis — nothing to send to the BE).
                    Otherwise it always shows. Click POSTs the plan_id
                    we have (apiPlanId preferred — fresh from /protocol;
                    falls back to incomingPlanId from router state if
                    the protocol fetch hasn't resolved yet) and
                    triggers a blob download. Button stays disabled
                    until at least one plan_id is available. */}
                <div className="flex shrink-0 flex-col items-end gap-3 self-start">
                {!useMockData && (
                  <button
                    type="button"
                    disabled={pdfDownloading || (!apiPlanId && !incomingPlanId)}
                    onClick={async () => {
                      const planForPdf = apiPlanId || incomingPlanId;
                      if (!planForPdf || pdfDownloading) return;
                      setPdfDownloading(true);
                      try {
                        const res = await fetch("/protocol/pdf", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ plan_id: planForPdf }),
                        });
                        if (!res.ok) {
                          // Try to surface the JSON error detail; fall back
                          // to status code if the body isn't JSON.
                          let detail = `HTTP ${res.status}`;
                          try {
                            const j = await res.json();
                            if (typeof j?.detail === "string") detail = j.detail;
                          } catch {
                            // ignore
                          }
                          throw new Error(detail);
                        }
                        const blob = await res.blob();
                        // Pull filename out of Content-Disposition when present.
                        const cd = res.headers.get("Content-Disposition") || "";
                        const m = /filename="?([^";]+)"?/i.exec(cd);
                        const filename = m?.[1] || "protocol.pdf";
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                      } catch (err) {
                        const msg = err instanceof Error ? err.message : "Download failed";
                        // Reuse the page-level error banner so the user sees
                        // failed PDF requests in context.
                        setApiError(`Protocol PDF download failed: ${msg}`);
                      } finally {
                        setPdfDownloading(false);
                      }
                    }}
                    className={
                      "group inline-flex items-center gap-2 rounded-md border-2 px-4 py-2.5 font-mono-notebook text-[12px] uppercase tracking-[0.22em] shadow-sm transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60 " +
                      ((!apiPlanId && !incomingPlanId) || pdfDownloading
                        ? "border-rule bg-paper text-ink-soft "
                        : "border-primary bg-primary text-primary-foreground hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-12px_hsl(var(--primary)/0.6)] hover:border-primary/80 active:translate-y-0")
                    }
                  >
                    <Download
                      className={
                        "h-4 w-4 transition-transform duration-200 " +
                        (pdfDownloading ? "animate-pulse" : "group-hover:translate-y-0.5")
                      }
                      strokeWidth={2}
                    />
                    {pdfDownloading
                      ? "Generating PDF…"
                      : (!apiPlanId && !incomingPlanId)
                      ? "Preparing PDF…"
                      : "Download PDF"}
                  </button>
                )}

                </div>
              </header>

              {/* TEXT VIEW — rich procedure-grouped when the backend ships
                  procedures[]; falls back to the original flat list for
                  mock-only mode and pre-Phase-2 backends. */}
              {hasRichProtocol && (
                <div className="divide-y divide-rule">
                  {procedures.map((proc) => (
                    <ProcedureBlock
                      key={proc.procedure_index}
                      proc={proc}
                      stepClock={stepClock}
                      procedureClock={procedureClock}
                      showClock={anyDurations}
                    />
                  ))}
                </div>
              )}

              {!hasRichProtocol && (
                <ol className="divide-y divide-rule">
                  {protocolSteps.map((s, i) => (
                    <li
                      key={i}
                      className="group/step grid grid-cols-[auto_1fr] gap-5 px-7 py-6 transition-colors hover:bg-rule-soft/30 sm:px-9 sm:py-7"
                    >
                      <div className="flex flex-col items-center">
                        <span className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        {i < protocolSteps.length - 1 && (
                          <span
                            aria-hidden
                            className="mt-3 h-full w-px flex-1 bg-rule"
                          />
                        )}
                      </div>
                      <div>
                        <h3 className="font-serif-card text-[22px] leading-[1.25] text-ink">
                          {s.title}
                        </h3>
                        <p className="mt-2 max-w-2xl text-[15px] leading-[1.7] text-ink-soft">
                          {s.detail}
                        </p>
                        {s.citation && (
                          <span className="mt-3 inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
                            <span aria-hidden className="h-1 w-1 rounded-full bg-sage" />
                            {s.citation}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              )}

            </div>
          </section>
        )}

        {/* MATERIALS */}
        {reveal >= 2 && (
          <section
            aria-labelledby="materials-title"
            className="mb-10 animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <header className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
              <div className="flex items-baseline gap-3">
                <Beaker className="h-4 w-4 text-ink-soft" strokeWidth={1.5} />
                <h2
                  id="materials-title"
                  className="font-serif-display text-[26px] leading-tight text-ink"
                >
                  Materials
                </h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  const rows = [
                    [
                      "Group",
                      "Item",
                      "Purpose",
                      "Supplier",
                      "Catalog",
                      "Quantity",
                      "Quantity context",
                      "Note",
                    ],
                    ...materialGroups.flatMap((g) =>
                      g.items.map((it) => [
                        g.group,
                        it.name,
                        it.purpose,
                        it.supplier ?? "",
                        it.catalog ?? "",
                        it.qty,
                        it.qtyContext ?? "",
                        it.note?.text ?? "",
                      ])
                    ),
                  ];
                  const csv = rows
                    .map((r) =>
                      r
                        .map((c) => `"${String(c).replace(/"/g, '""')}"`)
                        .join(",")
                    )
                    .join("\n");
                  const blob = new Blob([csv], {
                    type: "text/csv;charset=utf-8;",
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = "praxis-materials.csv";
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                className="group inline-flex items-center gap-1.5 border-b border-transparent pb-0.5 font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft transition-colors hover:border-ink hover:text-ink"
              >
                <Download className="h-3 w-3" strokeWidth={1.75} />
                Export materials list
                <ArrowRight
                  className="h-3 w-3 transition-transform group-hover:translate-x-0.5"
                  strokeWidth={1.75}
                />
              </button>
            </header>

            {/* Procurement summary line */}
            <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-sm border border-rule bg-paper-raised px-5 py-3 font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ink" />
                {materialGroups.reduce((a, g) => a + g.items.length, 0)} items
              </span>
              <span aria-hidden className="text-rule">·</span>
              <span>
                Estimated cost{" "}
                <span className="text-ink">
                  ${MATERIALS_SUMMARY.totalCost.toLocaleString()}
                </span>
              </span>
              <span aria-hidden className="text-rule">·</span>
              <span>
                Lead time{" "}
                <span className="text-ink">{MATERIALS_SUMMARY.leadTime}</span>
              </span>
            </div>

            {/* Materials gaps callout removed for now — most "gap" items
                from the LLM are actually Stage 4 supplier-lookup territory
                (catalog numbers, exact stock concentrations) and read as
                noise to the researcher. The data still flows through in
                `apiMaterialsView.gaps`; we can render it again selectively
                once Stage 4 lands and the gaps narrow to genuine unknowns. */}

            <div className="overflow-hidden rounded-md border border-rule bg-paper-raised">
              {materialGroups.map((group, gi) => (
                <div
                  key={group.group}
                  className={gi > 0 ? "border-t border-rule" : ""}
                >
                  {/* Group header with description and item count */}
                  <div className="border-b border-rule bg-paper/60 px-7 py-4">
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink">
                        {group.group}
                      </p>
                      <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                        {group.items.length} item
                        {group.items.length > 1 ? "s" : ""}
                      </p>
                    </div>
                    <p className="mt-1.5 max-w-2xl text-[13px] leading-[1.6] text-ink-soft">
                      {group.description}
                    </p>
                  </div>

                  <ul className="divide-y divide-rule">
                    {group.items.map((it, i) => (
                      <li
                        key={i}
                        // Anchor format mirrors what step rendering uses
                        // (`#mat-{name.toLowerCase().replace(/\s+/g, "-")}`).
                        // Click a reagent chip in a step → smooth-scroll here.
                        id={`mat-${it.name.toLowerCase().replace(/\s+/g, "-")}`}
                        className="grid grid-cols-1 gap-4 px-7 py-5 transition-colors hover:bg-rule-soft/30 sm:grid-cols-[1fr_auto] sm:gap-8 scroll-mt-24"
                      >
                        {/* LEFT: name + purpose + qty context + note */}
                        <div className="min-w-0">
                          <p
                            className="text-[19px] leading-snug text-ink"
                            style={{
                              fontFamily: '"Instrument Serif", Georgia, serif',
                            }}
                          >
                            {it.name}
                          </p>
                          <p className="mt-1 font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-sage">
                            {it.purpose}
                          </p>
                          {it.qtyContext && (
                            <p className="mt-2 text-[13px] italic leading-snug text-ink-soft">
                              {it.qty}{" "}
                              <span className="text-muted-foreground">
                                ({it.qtyContext})
                              </span>
                            </p>
                          )}
                          {it.note && (
                            <span
                              className={
                                "mt-2.5 inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] " +
                                (it.note.kind === "cold"
                                  ? "border-primary/30 bg-primary/[0.06] text-primary"
                                  : "border-[hsl(38_70%_55%)]/40 bg-[hsl(38_70%_92%)] text-[hsl(28_55%_30%)]")
                              }
                            >
                              {it.note.kind === "cold" ? (
                                <Snowflake
                                  className="h-3 w-3"
                                  strokeWidth={1.75}
                                />
                              ) : (
                                <Timer
                                  className="h-3 w-3"
                                  strokeWidth={1.75}
                                />
                              )}
                              {it.note.text}
                            </span>
                          )}

                          {/* Used-in cross-links: which steps reference this
                              material. Adapter populates from a case-insensitive
                              name match on step.reagents_referenced /
                              equipment_needed. */}
                          {(it.used_in_steps?.length ?? 0) > 0 && (
                            <p className="mt-2.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                              <span>Used in:</span>
                              {(it.used_in_steps ?? []).map((sid, si) => {
                                // Step IDs come back as "p{N}-s{M}"; render as
                                // "N.M" for the link label so it matches the
                                // numbering shown next to each step row.
                                const m = /^p(\d+)-s(\d+)$/.exec(sid);
                                const label = m ? `${m[1]}.${m[2]}` : sid;
                                return (
                                  <a
                                    key={si}
                                    href={`#${sid}`}
                                    className="rounded-sm border border-rule bg-paper px-1.5 py-0.5 text-ink-soft transition-colors hover:border-primary/40 hover:text-primary"
                                  >
                                    {label}
                                  </a>
                                );
                              })}
                            </p>
                          )}
                        </div>

                        {/* RIGHT: structured procurement block */}
                        <dl className="grid w-full shrink-0 grid-cols-3 gap-x-5 gap-y-1 border-t border-rule pt-4 sm:w-[20rem] sm:grid-cols-1 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
                          <div className="sm:flex sm:items-baseline sm:justify-between sm:gap-3">
                            <dt className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              Supplier
                            </dt>
                            <dd className="font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink">
                              {it.supplier ?? "—"}
                            </dd>
                          </div>
                          <div className="sm:flex sm:items-baseline sm:justify-between sm:gap-3">
                            <dt className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              Catalog
                            </dt>
                            <dd className="font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft">
                              {it.catalog ?? "—"}
                            </dd>
                          </div>
                          <div className="sm:flex sm:items-baseline sm:justify-between sm:gap-3">
                            <dt className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              Quantity
                            </dt>
                            <dd className="font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink">
                              {it.qty}
                            </dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* BUDGET + TIMELINE */}
        {reveal >= 3 && (
          <details
            className="plan-section group mb-8 rounded-md border border-rule bg-paper-raised animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <summary className="flex items-center justify-between gap-3 px-6 py-5 sm:px-7">
              <div className="flex items-baseline gap-3">
                <Coins className="h-4 w-4 self-center text-ink-soft" strokeWidth={1.5} />
                <h2
                  id="budget-title"
                  className="font-serif-display text-[26px] leading-tight text-ink"
                >
                  Budget &amp; timeline
                </h2>
                <span className="hidden font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:inline">
                  · ~$1,500 · 9 days
                </span>
              </div>
              <span className="inline-flex items-center gap-2 font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                <span className="hidden sm:inline">Expand</span>
                <ChevronDown className="plan-chevron h-4 w-4 transition-transform" strokeWidth={1.75} />
              </span>
            </summary>
            <div className="border-t border-rule px-6 py-6 sm:px-7">

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Budget */}
              <div className="rounded-md border border-rule bg-paper-raised">
                <div className="flex items-baseline justify-between border-b border-rule px-7 py-4">
                  <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                    Estimated cost
                  </p>
                  <p className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-ink-soft">
                    USD
                  </p>
                </div>
                <ul className="divide-y divide-rule">
                  {BUDGET.map((b) => (
                    <li
                      key={b.label}
                      className="flex items-baseline justify-between gap-4 px-7 py-3.5"
                    >
                      <span className="text-[15px] text-ink-soft">{b.label}</span>
                      <span
                        className="text-[18px] italic text-ink"
                        style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                      >
                        ${b.amount.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="flex items-baseline justify-between border-t border-rule px-7 py-4">
                  <span className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-ink">
                    Total
                  </span>
                  <span
                    className="text-[26px] italic text-ink"
                    style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                  >
                    ${BUDGET_TOTAL.toLocaleString()}
                  </span>
                </div>
              </div>

              {/* Timeline */}
              {/* Timeline section — when /timeline returned real
                  phase data, render the deterministically-computed
                  phases with their methodology + coverage chips
                  (defensibility surface). Falls back to hardcoded
                  TIMELINE for mock-only / fetch-failed paths. */}
              {apiTimeline && apiTimeline.phases.length > 0 ? (
                <div className="rounded-md border border-rule bg-paper-raised">
                  <div className="flex items-baseline justify-between border-b border-rule px-7 py-4">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                      Timeline
                    </p>
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-ink-soft">
                      {apiTimeline.total_duration
                        ? humanizeDuration(apiTimeline.total_duration)
                        : "Estimate incomplete"}
                    </p>
                  </div>
                  <ol className="divide-y divide-rule">
                    {apiTimeline.phases.map((p, i) => (
                      <li key={p.id} className="grid grid-cols-[auto_1fr] gap-4 px-7 py-4">
                        <div className="flex flex-col items-center">
                          <span className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink">
                            #{p.procedure_index}
                          </span>
                          {i < apiTimeline.phases.length - 1 && (
                            <span aria-hidden className="mt-2 h-full w-px flex-1 bg-rule" />
                          )}
                        </div>
                        <div>
                          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <p
                              className="text-[19px] italic leading-tight text-ink"
                              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                            >
                              {p.name}
                            </p>
                            {p.duration && (
                              <span className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.18em] text-ink-soft">
                                <Timer aria-hidden className="h-3 w-3" strokeWidth={1.75} />
                                {humanizeDuration(p.duration)}
                              </span>
                            )}
                            {/* Coverage chip — defensibility: shows
                                what fraction of steps had duration data
                                feeding this phase's number. */}
                            {p.coverage < 1 && (
                              <span
                                className="inline-flex items-center gap-1.5 rounded-sm border border-[hsl(38_70%_55%)]/40 bg-[hsl(38_70%_92%)]/40 px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-[hsl(28_55%_30%)]"
                                title={p.methodology}
                              >
                                {Math.round(p.coverage * 100)}% covered
                              </span>
                            )}
                            {/* Back-link to the source procedure */}
                            <a
                              href={`#proc-${p.procedure_index}`}
                              className="inline-flex items-center gap-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-ink"
                              title="Jump to source procedure"
                            >
                              ↑ procedure
                            </a>
                          </div>
                          <p className="mt-1 text-[13px] leading-[1.6] text-ink-soft">
                            {p.methodology}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                  {apiTimeline.assumptions.length > 0 && (
                    <details className="border-t border-rule">
                      <summary className="flex cursor-pointer items-center justify-between gap-3 px-7 py-3 font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-ink-soft hover:text-ink">
                        Assumptions ({apiTimeline.assumptions.length})
                        <ChevronDown aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
                      </summary>
                      <ul className="border-t border-rule px-7 py-3 space-y-1.5 list-disc pl-10 text-[13px] leading-[1.55] text-ink-soft">
                        {apiTimeline.assumptions.map((a, i) => (
                          <li key={i}>{a}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ) : (
                <div className="rounded-md border border-rule bg-paper-raised">
                  <div className="flex items-baseline justify-between border-b border-rule px-7 py-4">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                      Timeline
                    </p>
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-ink-soft">
                      ~4 weeks
                    </p>
                  </div>
                  <ol className="divide-y divide-rule">
                    {TIMELINE.map((t, i) => (
                      <li key={t.week} className="grid grid-cols-[auto_1fr] gap-4 px-7 py-4">
                        <div className="flex flex-col items-center">
                          <span className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink">
                            {t.week}
                          </span>
                          {i < TIMELINE.length - 1 && (
                            <span aria-hidden className="mt-2 h-full w-px flex-1 bg-rule" />
                          )}
                        </div>
                        <div>
                          <p
                            className="text-[19px] italic leading-tight text-ink"
                            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                          >
                            {t.phase}
                          </p>
                          <p className="mt-1 text-[14px] leading-[1.6] text-ink-soft">
                            {t.note}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
            </div>
          </details>
        )}

        {/* VALIDATION */}
        {reveal >= 4 && (
          <details
            className="plan-section group mb-8 rounded-md border border-rule bg-paper-raised animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <summary className="flex items-center justify-between gap-3 px-6 py-5 sm:px-7">
              <div className="flex items-baseline gap-3">
                <Target className="h-4 w-4 self-center text-ink-soft" strokeWidth={1.5} />
                <h2
                  id="validation-title"
                  className="font-serif-display text-[26px] leading-tight text-ink"
                >
                  Validation
                </h2>
                <span className="hidden font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:inline">
                  · Measures &amp; success criteria
                </span>
              </div>
              <span className="inline-flex items-center gap-2 font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                <span className="hidden sm:inline">Expand</span>
                <ChevronDown className="plan-chevron h-4 w-4 transition-transform" strokeWidth={1.75} />
              </span>
            </summary>
            <div className="border-t border-rule px-6 py-6 sm:px-7">

            {/* Validation aggregate is computed in the `validation` useMemo
                up top; here we just render. Each success criterion carries
                a "↑ {procedure name}" back-link so researchers can audit
                by jumping to the source procedure. */}
            <div className="grid grid-cols-1 overflow-hidden rounded-md border border-rule bg-paper-raised sm:grid-cols-2">
              <div className="border-rule px-7 py-6 sm:border-r">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                  What we measure
                </p>
                <ul className="mt-4 space-y-3">
                  {validation.measured.map((m, i) => (
                    <li key={i} className="flex gap-3 text-[15px] leading-[1.65] text-ink">
                      <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink" />
                      <span>{m}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="px-7 py-6">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-sage">
                  Success criteria
                </p>
                <ul className="mt-4 space-y-3">
                  {validation.useReal ? (
                    validation.aggCriteria.map((c, i) => (
                      <li key={i} className="text-[15px] leading-[1.65] text-ink">
                        <div className="flex gap-3">
                          <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-sage" />
                          <div>
                            <span>{c.what}</span>
                            {c.threshold && (
                              <span className="ml-2 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-primary">
                                [{c.threshold}]
                              </span>
                            )}
                            {/* Citation chip — researcher can jump back to
                                the procedure that produced this criterion. */}
                            <a
                              href={`#proc-${c.procedureIndex}`}
                              className="ml-2 inline-flex items-center gap-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-ink"
                              title="Jump to source procedure"
                            >
                              ↑ {c.fromProcedure}
                            </a>
                          </div>
                        </div>
                      </li>
                    ))
                  ) : (
                    VALIDATION.success.map((m, i) => (
                      <li key={i} className="flex gap-3 text-[15px] leading-[1.65] text-ink">
                        <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-sage" />
                        <span>{m}</span>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            </div>

            {/* Stage 6 (real /validation output): power calc, controls,
                failure modes. Each entry shows its citation chip so the
                researcher can audit the source. Only renders when the
                /validation call resolved — Phase A's procedure-derived
                criteria above continue to show otherwise. */}
            {apiValidation && (
              <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
                {/* Power calc */}
                {apiValidation.power_calculation && (
                  <div className="rounded-md border border-rule bg-paper-raised px-7 py-6">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-primary">
                      Sample size estimate
                    </p>
                    <div className="mt-3 flex items-baseline gap-3">
                      <span
                        className="font-serif-display text-[34px] leading-none text-ink"
                        title="n per arm"
                      >
                        n = {apiValidation.power_calculation.n_per_group}
                      </span>
                      <span className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                        per arm · total {apiValidation.power_calculation.total_n}
                      </span>
                    </div>
                    <p className="mt-2 font-mono-notebook text-[11px] text-ink-soft">
                      {apiValidation.power_calculation.statistical_test} ·
                      α = {apiValidation.power_calculation.alpha} ·
                      power = {apiValidation.power_calculation.power}
                    </p>
                    <details className="mt-4">
                      <summary className="cursor-pointer font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground hover:text-ink">
                        Methodology &amp; assumptions
                      </summary>
                      <p className="mt-2 text-[13px] leading-[1.55] text-ink-soft">
                        {apiValidation.power_calculation.formula}
                      </p>
                      <p className="mt-2 text-[13px] leading-[1.55] text-ink-soft">
                        {apiValidation.power_calculation.rationale}
                      </p>
                      <ul className="mt-3 space-y-1.5">
                        {apiValidation.power_calculation.assumptions.map((a, i) => (
                          <li
                            key={i}
                            className="flex gap-2 text-[12.5px] leading-[1.55] text-ink-soft"
                          >
                            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-soft" />
                            <span>{a}</span>
                          </li>
                        ))}
                      </ul>
                      <p className="mt-3 font-mono-notebook text-[10px] text-muted-foreground">
                        Effect: {apiValidation.power_calculation.effect_size.type} ·{" "}
                        {apiValidation.power_calculation.effect_size.derived_from}
                      </p>
                    </details>
                  </div>
                )}

                {/* Controls */}
                {apiValidation.controls.length > 0 && (
                  <div className="rounded-md border border-rule bg-paper-raised px-7 py-6">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-sage">
                      Controls
                    </p>
                    <ul className="mt-4 space-y-3">
                      {apiValidation.controls.map((c, i) => (
                        <li
                          key={i}
                          className="text-[14px] leading-[1.55] text-ink"
                        >
                          <div className="flex items-baseline gap-2">
                            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-primary">
                              {c.type}
                            </span>
                            <span>{c.name}</span>
                          </div>
                          <p className="mt-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                            from {c.derived_from}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Failure modes — full-width row. LLM-emitted but every
                entry is forced to cite a procedure (parser drops
                ungrounded entries server-side). */}
            {apiValidation && apiValidation.failure_modes.length > 0 && (
              <div className="mt-6 rounded-md border border-rule bg-paper-raised px-7 py-6">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
                  Failure modes &amp; mitigations
                </p>
                <ul className="mt-4 space-y-4">
                  {apiValidation.failure_modes.map((fm, i) => (
                    <li
                      key={i}
                      className="border-l-2 border-rule pl-4 text-[14px] leading-[1.55] text-ink"
                    >
                      <p className="font-medium text-ink">{fm.mode}</p>
                      <p className="mt-1 text-[13px] text-ink-soft">
                        <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                          cause
                        </span>{" "}
                        {fm.likely_cause}
                      </p>
                      <p className="mt-1 text-[13px] text-ink-soft">
                        <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-sage">
                          mitigation
                        </span>{" "}
                        {fm.mitigation}
                      </p>
                      <p className="mt-1.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                        ↑ {fm.cites}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Methodology footer — audit trail for this whole section. */}
            {apiValidation && (
              <p className="mt-4 font-mono-notebook text-[11px] leading-[1.55] text-muted-foreground">
                {apiValidation.methodology}
              </p>
            )}
            </div>
          </details>
        )}

        {/* FEASIBILITY */}
        {reveal >= 4 && (
          <details
            className="plan-section group mb-8 rounded-md border border-rule bg-paper-raised animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <summary className="flex items-center justify-between gap-3 px-6 py-5 sm:px-7">
              <div className="flex items-baseline gap-3">
                <FlaskConical className="h-4 w-4 self-center text-ink-soft" strokeWidth={1.5} />
                <h2
                  id="feasibility-title"
                  className="font-serif-display text-[26px] leading-tight text-ink"
                >
                  Feasibility
                </h2>
                <span className="hidden font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:inline">
                  · Practical, with 3 things to watch
                </span>
              </div>
              <span className="inline-flex items-center gap-2 font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                <span className="hidden sm:inline">Expand</span>
                <ChevronDown className="plan-chevron h-4 w-4 transition-transform" strokeWidth={1.75} />
              </span>
            </summary>
            <div className="border-t border-rule px-7 py-6 sm:px-9 sm:py-8">
              <p
                className="max-w-3xl text-[18px] italic leading-[1.65] text-ink-soft"
                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
              >
                {FEASIBILITY.body}
              </p>

              <div className="mt-6 grid grid-cols-1 gap-6 border-t border-rule pt-5 sm:grid-cols-2 sm:gap-8">
                {/* Assumptions */}
                <div className="relative sm:pr-6">
                  <span aria-hidden className="absolute -left-3 top-1 h-3 w-[2px] rounded-sm bg-sage" />
                  <div className="flex items-baseline justify-between">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-sage">
                      Assumptions
                    </p>
                    <p className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      What we take as given
                    </p>
                  </div>
                  <ul className="mt-3 space-y-2.5">
                    {/* Assumptions wired from real protocol output (the
                        architect populates protocol.assumptions[]).
                        Falls back to mock FEASIBILITY.assumptions when
                        in mock-only mode. */}
                    {(protocolAssumptions.length > 0 ? protocolAssumptions : FEASIBILITY.assumptions)
                      .map((a, i) => (
                        <li
                          key={i}
                          className="flex gap-3 text-[15px] leading-[1.65] text-ink-soft"
                        >
                          <span className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-sage">
                            A{i + 1}
                          </span>
                          <span>{a}</span>
                        </li>
                      ))}
                  </ul>
                </div>

                {/* Risks. Phase D: when /critique returned real risks
                    (each cite-validated server-side), render those with
                    severity chips and citation back-link. Falls back to
                    the hardcoded FEASIBILITY.risks for mock-only mode
                    or when the /critique call failed. */}
                <div className="relative sm:border-l sm:border-rule sm:pl-8">
                  <div className="flex items-baseline justify-between">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
                      Key risks
                    </p>
                    <p className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      What could bias the result
                    </p>
                  </div>
                  <ul className="mt-3 space-y-3">
                    {(apiCritique && apiCritique.risks.length > 0) ? (
                      apiCritique.risks.map((r, i) => {
                        const sevColor =
                          r.severity === "high"
                            ? "text-destructive"
                            : r.severity === "medium"
                            ? "text-[hsl(28_70%_38%)]"
                            : "text-muted-foreground";
                        return (
                          <li key={i} className="text-[14px] leading-[1.55] text-ink-soft">
                            <div className="flex items-baseline gap-2">
                              <span className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                                R{i + 1}
                              </span>
                              <span className={`font-mono-notebook text-[10px] uppercase tracking-[0.22em] ${sevColor}`}>
                                {r.severity}
                              </span>
                              <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                                · {r.category}
                              </span>
                            </div>
                            <p className="mt-1 text-[15px] leading-[1.55] text-ink">{r.name}</p>
                            <p className="mt-0.5 text-[13px] leading-[1.55] text-ink-soft">{r.description}</p>
                            <p className="mt-1 text-[13px] leading-[1.55] text-ink-soft">
                              <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-sage">mitigation</span>{" "}
                              {r.mitigation}
                            </p>
                            <p className="mt-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                              ↑ {r.cites}
                            </p>
                          </li>
                        );
                      })
                    ) : (
                      FEASIBILITY.risks.map((r, i) => (
                        <li key={i} className="flex gap-3 text-[15px] leading-[1.65] text-ink-soft">
                          <span className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                            R{i + 1}
                          </span>
                          <span>{r}</span>
                        </li>
                      ))
                    )}
                  </ul>

                  {/* Confounders block — only renders when /critique
                      returned at least one. Each carries cite + control
                      strategy alongside the why-confounding rationale. */}
                  {apiCritique && apiCritique.confounders.length > 0 && (
                    <div className="mt-5 border-t border-rule pt-4">
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
                        Confounders
                      </p>
                      <ul className="mt-3 space-y-3">
                        {apiCritique.confounders.map((c, i) => (
                          <li key={i} className="text-[14px] leading-[1.55] text-ink-soft">
                            <p className="text-[15px] text-ink">{c.variable}</p>
                            <p className="mt-0.5 text-[13px] leading-[1.55] text-ink-soft">{c.why_confounding}</p>
                            <p className="mt-1 text-[13px] leading-[1.55] text-ink-soft">
                              <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-sage">control</span>{" "}
                              {c.control_strategy}
                            </p>
                            <p className="mt-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                              ↑ {c.cites}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Overall assessment + recommendation chip — only
                      when real critique loaded. Recommendation is
                      computed deterministically server-side from the
                      risk profile, not a free-text LLM verdict. */}
                  {apiCritique && (
                    <div className="mt-5 border-t border-rule pt-4">
                      <div className="flex items-baseline gap-2">
                        <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
                          Recommendation
                        </p>
                        <span
                          className={
                            "font-mono-notebook text-[10px] uppercase tracking-[0.22em] " +
                            (apiCritique.recommendation === "revise_design"
                              ? "text-destructive"
                              : apiCritique.recommendation === "proceed_with_caution"
                              ? "text-[hsl(28_70%_38%)]"
                              : "text-sage")
                          }
                        >
                          {apiCritique.recommendation.replace(/_/g, " ")}
                        </span>
                      </div>
                      <p className="mt-2 text-[14px] leading-[1.55] text-ink-soft">
                        {apiCritique.overall_assessment}
                      </p>
                      <p className="mt-3 font-mono-notebook text-[11px] leading-[1.55] text-muted-foreground">
                        {apiCritique.methodology}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </details>
        )}

        {/* CTA */}
        {reveal >= 4 && (
          <section
            aria-label="Continue to next step"
            className="relative overflow-hidden rounded-md border border-primary/40 bg-paper-raised shadow-[0_1px_0_hsl(var(--primary)/0.15),0_24px_60px_-30px_hsl(var(--primary)/0.35)] animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            <div aria-hidden className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-rule to-transparent" />

            <div className="grid grid-cols-1 gap-0 sm:grid-cols-[1fr_auto_1fr]">
              <div className="px-7 py-7 sm:px-9 sm:py-9">
                <div className="flex items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground">
                    <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
                  </span>
                  <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                    Step 03
                  </p>
                </div>
                <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                  Experiment plan
                </h3>
                <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                  Protocol, materials, budget, and validation all drafted.
                </p>
              </div>

              <div className="flex items-center justify-center border-rule px-6 py-2 sm:border-x sm:px-8 sm:py-9">
                <div className="flex flex-col items-center gap-2 sm:gap-3" aria-hidden>
                  <span className="hidden h-8 w-px bg-rule sm:block" />
                  <ArrowRight className="h-5 w-5 text-primary" strokeWidth={1.75} />
                  <span className="hidden h-8 w-px bg-rule sm:block" />
                </div>
              </div>

              <div className="px-7 py-7 sm:px-9 sm:py-9">
                <div className="flex items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary/60 bg-paper text-[12px] font-medium text-primary">
                    04
                  </span>
                  <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-primary">
                    Step 04 — Up next
                  </p>
                </div>
                <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                  Review &amp; refine
                </h3>
                <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                  Walk through the plan, tighten anything you'd defend differently, then export.
                </p>
              </div>
            </div>

            <div className="flex flex-col-reverse items-stretch justify-between gap-4 border-t border-rule bg-paper/60 px-7 py-5 sm:flex-row sm:items-center sm:px-9">
              <div className="flex items-center gap-5">
                <button
                  type="button"
                  onClick={() => navigate("/literature")}
                  className="group inline-flex items-center gap-2 font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-ink"
                  aria-label="Go back to literature check"
                >
                  <ArrowRight className="h-4 w-4 rotate-180 transition-transform group-hover:-translate-x-0.5" strokeWidth={1.75} />
                  Back to literature
                </button>
                <span aria-hidden className="hidden h-4 w-px bg-rule sm:block" />
                <p className="hidden font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground sm:block">
                  Ready when you are <span className="text-primary">●</span>
                </p>
              </div>
              <Button
                onClick={() => navigate("/review")}
                className="group h-14 gap-3 rounded-sm bg-ink px-7 text-[15px] font-medium text-paper shadow-[0_8px_24px_-12px_hsl(var(--ink)/0.6)] transition-all hover:bg-ink/90 hover:shadow-[0_10px_28px_-10px_hsl(var(--ink)/0.7)]"
              >
                <span className="font-mono-notebook text-[10px] uppercase tracking-[0.24em] opacity-70">
                  Step 04 →
                </span>
                <span className="font-serif-display text-[19px] italic">
                  Review and refine plan
                </span>
                <ArrowRight
                  className="h-5 w-5 transition-transform group-hover:translate-x-0.5"
                  strokeWidth={1.75}
                />
              </Button>
            </div>
          </section>
        )}
      </main>
    </div>
  );
};

export default ExperimentPlan;

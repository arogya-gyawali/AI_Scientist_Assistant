import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  postMaterials,
  postProtocol,
  type FEMaterialGroup,
  type FEProtocolStep,
  type StructuredHypothesis,
} from "@/lib/api";
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
  LayoutList,
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
    } | null) ?? null;
  const incomingPlanId = navState?.plan_id;
  const incomingStructured = navState?.structured;

  // Section reveal index: 0 nothing, 1 protocol, 2 + materials, 3 + budget+timeline, 4 + validation+feasibility.
  // Real-API path advances reveal as each backend call resolves; mock path
  // ticks through it on a scripted timer (preserved below for the design demo).
  const [stageIdx, setStageIdx] = useState(0);
  const [reveal, setReveal] = useState(0);
  const [protocolView, setProtocolView] = useState<"text" | "flow">("text");

  // Real protocol + materials data from the backend. null = still loading
  // (or mock-only mode, in which case `useMockData` below is true).
  const [apiProtocolSteps, setApiProtocolSteps] = useState<FEProtocolStep[] | null>(null);
  const [apiMaterialGroups, setApiMaterialGroups] = useState<FEMaterialGroup[] | null>(null);
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
    const protoBody = incomingPlanId
      ? { plan_id: incomingPlanId }
      : { structured: incomingStructured! };
    const matsBody = (planId: string) => ({ plan_id: planId });

    setStageIdx(0);
    setReveal(0);

    (async () => {
      try {
        const proto = await postProtocol(protoBody, ac.signal);
        setApiProtocolSteps(proto.frontend_view.steps);
        setStageIdx(1);
        setReveal(1);

        const mats = await postMaterials(matsBody(proto.plan_id), ac.signal);
        setApiMaterialGroups(mats.frontend_view.groups);
        setStageIdx(2);
        setReveal(2);
        // The remaining reveal stages (3, 4) gate budget/timeline/validation,
        // which are still hardcoded in this mockup. Reveal them on a short
        // delay so they stagger into view as the user scrolls.
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
  }, [incomingPlanId, incomingStructured, useMockData]);

  // Display data: prefer backend-driven; fall back to mock constants for
  // mock-only mode or if a section's API call hasn't resolved yet.
  const protocolSteps = useMemo<FEProtocolStep[]>(
    () => apiProtocolSteps ?? PROTOCOL_STEPS,
    [apiProtocolSteps],
  );
  const materialGroups = useMemo<FEMaterialGroup[]>(
    () => apiMaterialGroups ?? MATERIALS,
    [apiMaterialGroups],
  );

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

          {/* Confidence banner — ties the whole plan together */}
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
                    Moderate–High
                  </span>
                  {/* dot meter: 4 of 5 filled */}
                  <span aria-hidden className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-ink" />
                    <span className="h-2 w-2 rounded-full bg-ink" />
                    <span className="h-2 w-2 rounded-full bg-ink" />
                    <span className="h-2 w-2 rounded-full bg-ink" />
                    <span className="h-2 w-2 rounded-full bg-rule" />
                  </span>
                </div>
              </div>
              <span aria-hidden className="hidden h-10 w-px bg-rule sm:block" />
              <p
                className="hidden max-w-md text-[15px] italic leading-snug text-ink-soft sm:block"
                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
              >
                Based on protocol similarity to published assays and availability of established readouts.
              </p>
            </div>
            <ul className="flex flex-wrap items-center gap-2">
              <li className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sage" />
                Protocol similarity
              </li>
              <li className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sage" />
                Established assays
              </li>
              <li className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-rule" />
                Standard equipment
              </li>
            </ul>
          </div>
          {/* Mobile-only sub-line for the banner explanation */}
          <p
            className="mt-3 text-[14px] italic leading-snug text-ink-soft sm:hidden"
            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
          >
            Based on protocol similarity to published assays and availability of established readouts.
          </p>

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
              {HYPOTHESIS_SUMMARY}
            </p>
          </div>

          {/* Plan at a glance — jump nav so users don't have to scroll the whole page */}
        </section>

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
                      Glucose-gradient kinetic assay in M9 minimal media, plate-reader readout.
                    </p>
                  </div>
                </div>

                {/* View toggle */}
                <div
                  role="tablist"
                  aria-label="Protocol view mode"
                  className="inline-flex shrink-0 items-center rounded-sm border border-rule bg-paper p-1 self-start"
                >
                  {(
                    [
                      { id: "text", label: "Text view", icon: LayoutList },
                      { id: "flow", label: "Flowchart view", icon: GitBranch },
                    ] as const
                  ).map((opt) => {
                    const active = protocolView === opt.id;
                    const Icon = opt.icon;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => setProtocolView(opt.id)}
                        className={
                          "inline-flex items-center gap-2 rounded-[2px] px-3 py-1.5 font-mono-notebook text-[11px] uppercase tracking-[0.2em] transition-all " +
                          (active
                            ? "bg-ink text-paper"
                            : "text-ink-soft hover:bg-rule-soft/60 hover:text-ink")
                        }
                      >
                        <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </header>

              {/* TEXT VIEW (default, unchanged) */}
              {protocolView === "text" && (
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

              {/* FLOWCHART VIEW — grouped by phase, vertical linear flow */}
              {protocolView === "flow" && (
                <div className="px-7 py-8 sm:px-9 sm:py-10 animate-in fade-in duration-300">
                  <div className="mx-auto flex max-w-2xl flex-col">
                    {PHASE_ORDER.map((phase, phaseIdx) => {
                      const stepsInPhase = protocolSteps
                        .map((s, idx) => ({ ...s, idx }))
                        .filter((s) => s.phase === phase);
                      if (stepsInPhase.length === 0) return null;
                      const meta = PHASE_META[phase];
                      const isLastPhase = phaseIdx === PHASE_ORDER.length - 1;

                      return (
                        <div key={phase} className="relative">
                          {/* Phase label */}
                          <div className="flex items-center gap-3">
                            <span
                              aria-hidden
                              className={"h-2 w-2 rounded-full " + meta.dot}
                            />
                            <p className="font-mono-notebook text-[11px] uppercase tracking-[0.24em] text-ink">
                              {meta.label}
                            </p>
                            <span
                              aria-hidden
                              className="h-px flex-1 bg-rule"
                            />
                            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              {stepsInPhase.length} step
                              {stepsInPhase.length > 1 ? "s" : ""}
                            </span>
                          </div>

                          {/* Step nodes */}
                          <ol className="mt-5 flex flex-col items-stretch gap-0">
                            {stepsInPhase.map((s, sIdx) => {
                              const isLastInPhase =
                                sIdx === stepsInPhase.length - 1;
                              return (
                                <li
                                  key={s.idx}
                                  className="flex flex-col items-center"
                                >
                                  {/* Card */}
                                  <div
                                    className={
                                      "group/node w-full rounded-sm border bg-paper px-5 py-4 transition-all hover:-translate-y-[1px] hover:border-ink/60 " +
                                      meta.border
                                    }
                                  >
                                    <div className="flex items-start gap-4">
                                      <span
                                        className={
                                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border font-mono-notebook text-[12px] tracking-wider text-ink " +
                                          meta.border +
                                          " " +
                                          meta.tint
                                        }
                                      >
                                        {String(s.idx + 1).padStart(2, "0")}
                                      </span>
                                      <div className="min-w-0 flex-1">
                                        <h3 className="font-serif-card text-[18px] leading-[1.3] text-ink">
                                          {s.title}
                                        </h3>
                                        {s.meta && (
                                          <p className="mt-1.5 font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-ink-soft">
                                            {s.meta}
                                          </p>
                                        )}
                                      </div>
                                      {s.citation && (
                                        <span
                                          className="hidden shrink-0 items-center gap-1.5 rounded-sm border border-rule bg-paper-raised px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft sm:inline-flex"
                                          title={s.citation}
                                        >
                                          <span
                                            aria-hidden
                                            className="h-1 w-1 rounded-full bg-sage"
                                          />
                                          cite
                                        </span>
                                      )}
                                    </div>
                                  </div>

                                  {/* Connector to next step inside same phase */}
                                  {!isLastInPhase && (
                                    <div
                                      aria-hidden
                                      className="flex h-7 flex-col items-center"
                                    >
                                      <span className="h-full w-px bg-rule" />
                                    </div>
                                  )}
                                </li>
                              );
                            })}
                          </ol>

                          {/* Connector between phases — arrow + thicker spacer */}
                          {!isLastPhase && (
                            <div
                              aria-hidden
                              className="my-4 flex flex-col items-center"
                            >
                              <span className="h-5 w-px bg-rule" />
                              <span
                                className={
                                  "flex h-6 w-6 items-center justify-center rounded-full border bg-paper-raised " +
                                  meta.border
                                }
                              >
                                <ArrowRight
                                  className="h-3 w-3 rotate-90 text-ink"
                                  strokeWidth={1.75}
                                />
                              </span>
                              <span className="h-5 w-px bg-rule" />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Phase legend */}
                  <div className="mx-auto mt-10 flex max-w-2xl flex-wrap items-center gap-3 border-t border-rule pt-5">
                    <span className="font-mono-notebook text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
                      Phases
                    </span>
                    {PHASE_ORDER.map((p) => (
                      <span
                        key={p}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft"
                      >
                        <span
                          aria-hidden
                          className={"h-1.5 w-1.5 rounded-full " + PHASE_META[p].dot}
                        />
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
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
                        className="grid grid-cols-1 gap-4 px-7 py-5 transition-colors hover:bg-rule-soft/30 sm:grid-cols-[1fr_auto] sm:gap-8"
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

            <div className="grid grid-cols-1 overflow-hidden rounded-md border border-rule bg-paper-raised sm:grid-cols-2">
              <div className="border-rule px-7 py-6 sm:border-r">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                  What we measure
                </p>
                <ul className="mt-4 space-y-3">
                  {VALIDATION.measured.map((m, i) => (
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
                  {VALIDATION.success.map((m, i) => (
                    <li key={i} className="flex gap-3 text-[15px] leading-[1.65] text-ink">
                      <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-sage" />
                      <span>{m}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
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
                    {FEASIBILITY.assumptions.map((a, i) => (
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

                {/* Risks */}
                <div className="relative sm:border-l sm:border-rule sm:pl-8">
                  <div className="flex items-baseline justify-between">
                    <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft">
                      Key risks
                    </p>
                    <p className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      What could bias the result
                    </p>
                  </div>
                  <ul className="mt-3 space-y-2.5">
                    {FEASIBILITY.risks.map((r, i) => (
                      <li
                        key={i}
                        className="flex gap-3 text-[15px] leading-[1.65] text-ink-soft"
                      >
                        <span className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                          R{i + 1}
                        </span>
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
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

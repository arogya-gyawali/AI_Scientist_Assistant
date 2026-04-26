import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  postLitReview,
  type Citation,
  type KeyDifference,
  type LitReviewResponse,
  type StructuredHypothesis,
} from "@/lib/api";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  Info,
  Pencil,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Backend signal values, mirrored on the frontend.
type NoveltyStatus = "not_found" | "similar_work_exists" | "exact_match";
type ConfidenceLevel = "low" | "moderate" | "high";

// Mirrors the backend reference object.
type Reference = {
  id: string;
  title: string;
  authors: string;
  venue: string;
  year: number;
  description: string;          // used as the abstract
  url: string;
  relevance_score: number;      // 0..1, rendered as similarity %
  matched_on: { label: string; tone: "subject" | "variable" | "condition" }[];
  importance: string;           // "Why this matters"
  // Phase E: per-reference structured deltas, drawn straight from the
  // backend (Citation.key_differences). Optional (and defaulted to []
  // by citationToReference) so the mock REFERENCES — which don't have
  // them — keep working without per-entry boilerplate. Type imported
  // from @/lib/api so FE/BE stay in lockstep.
  key_differences?: KeyDifference[];
};

// Color legend for highlighted concepts in the hypothesis & papers
// subject  -> primary (deep ink blue)
// variable -> sage
// condition-> warm amber
const CONCEPT = {
  subject: "bg-primary/[0.08] text-primary border-b border-primary/30",
  variable: "bg-sage-wash text-[hsl(142_45%_24%)] border-b border-sage/40",
  condition:
    "bg-[hsl(38_70%_92%)] text-[hsl(28_55%_30%)] border-b border-[hsl(38_70%_55%)]/40",
} as const;

const CONCEPT_DOT = {
  subject: "bg-primary",
  variable: "bg-sage",
  condition: "bg-[hsl(38_70%_45%)]",
} as const;

type HypothesisPart = {
  text: string;
  tone?: keyof typeof CONCEPT;
};

// Mock fallback when no structured hypothesis is in router state
// (direct page navigation / design demo). Real users see a derived
// breakdown — see deriveHypothesisParts() below.
const HYPOTHESIS_PARTS: HypothesisPart[] = [
  { text: "Increasing " },
  { text: "glucose concentration", tone: "variable" },
  { text: " in M9 minimal media reduces the specific growth rate of " },
  { text: "E. coli K-12", tone: "subject" },
  { text: " above " },
  { text: "10 mM", tone: "variable" },
  { text: ", due to catabolite repression under " },
  { text: "aerobic conditions at 37 °C", tone: "condition" },
  { text: "." },
];

// Compose color-coded hypothesis prose from the structured fields.
// Deterministic — same structured input → same parts. No LLM call;
// the text is "Does {independent} affect {dependent} in {subject}
// [under {conditions}]?" with each structured field highlighted by
// its semantic role:
//   subject    -> "subject" tone (deep ink blue)
//   independent / dependent -> "variable" tone (sage)
//   conditions -> "condition" tone (warm amber)
function deriveHypothesisParts(
  s: StructuredHypothesis | undefined,
): HypothesisPart[] {
  if (!s) return HYPOTHESIS_PARTS;
  const parts: HypothesisPart[] = [];
  parts.push({ text: "Does " });
  if (s.independent) parts.push({ text: s.independent.trim(), tone: "variable" });
  else parts.push({ text: "the intervention", tone: "variable" });
  parts.push({ text: " affect " });
  if (s.dependent) parts.push({ text: s.dependent.trim(), tone: "variable" });
  else parts.push({ text: "the outcome", tone: "variable" });
  parts.push({ text: " in " });
  if (s.subject) parts.push({ text: s.subject.trim(), tone: "subject" });
  else parts.push({ text: "the system", tone: "subject" });
  if (s.conditions?.trim()) {
    parts.push({ text: " under " });
    parts.push({ text: s.conditions.trim(), tone: "condition" });
  }
  parts.push({ text: "?" });
  return parts;
}

// ---- Mocked backend response ------------------------------------------------
// In production these come from the literature-check service. Field names
// match the backend contract: signal, description, confidence, summary,
// references[], key_differences[].

const NOVELTY_SIGNAL: NoveltyStatus = "similar_work_exists";

const NOVELTY_DESCRIPTION =
  "Adjacent studies investigate catabolite repression in E. coli, but none isolate the specific growth-rate response across a continuous glucose gradient under M9 minimal media at 37 °C aerobic conditions. The closest precedents differ in culture mode (chemostat) or measurement endpoint (acetate overflow).";

const NOVELTY_CONFIDENCE: ConfidenceLevel = "moderate";

// System-level conclusion shown as the recommendation layer.
const RECOMMENDATION_SUMMARY =
  "Proceeding is likely to yield novel insights under modified conditions — specifically the continuous-gradient batch design and direct µ readout above 10 mM glucose.";

const NOVELTY_COPY: Record<
  NoveltyStatus,
  { dot: string; label: string; pill: string; tone: string; pillBg: string; pillBorder: string }
> = {
  not_found: {
    dot: "bg-sage",
    label: "No prior work found",
    pill: "Novel",
    tone: "text-sage",
    pillBg: "bg-sage-wash",
    pillBorder: "border-sage/30",
  },
  similar_work_exists: {
    dot: "bg-[hsl(38_70%_45%)]",
    label: "Similar experimental approaches have been reported",
    pill: "Adjacent work",
    tone: "text-[hsl(28_55%_30%)]",
    pillBg: "bg-secondary",
    pillBorder: "border-rule",
  },
  exact_match: {
    dot: "bg-destructive",
    label: "A direct precedent exists",
    pill: "Direct match",
    tone: "text-destructive",
    pillBg: "bg-destructive/[0.06]",
    pillBorder: "border-destructive/30",
  },
};

const CONFIDENCE_COPY: Record<
  ConfidenceLevel,
  { label: string; filled: number; dots: string }
> = {
  low: { label: "Low", filled: 1, dots: "●○○" },
  moderate: { label: "Moderate", filled: 2, dots: "●●○" },
  high: { label: "High", filled: 3, dots: "●●●" },
};

const REFERENCES: Reference[] = [
  {
    id: "p1",
    title:
      "Catabolite repression dynamics in E. coli grown on mixed carbon sources",
    authors: "Görke B., Stülke J.",
    venue: "Nature Reviews Microbiology",
    year: 2008,
    description:
      "Reviews CRP–cAMP regulation of carbon source utilization in E. coli without quantifying growth rate across a continuous glucose gradient.",
    url: "https://www.nature.com/articles/nrmicro1932",
    relevance_score: 0.71,
    matched_on: [
      { label: "E. coli", tone: "subject" },
      { label: "glucose", tone: "variable" },
      { label: "catabolite repression", tone: "variable" },
    ],
    importance:
      "This review establishes the regulatory mechanism your hypothesis relies on, providing the mechanistic grounding that your continuous-gradient measurement is designed to quantify.",
  },
  {
    id: "p2",
    title:
      "Specific growth rate of E. coli K-12 as a function of glucose in defined media",
    authors: "Senn H., Lendenmann U., Snozzi M., Hamer G., Egli T.",
    venue: "Biochimica et Biophysica Acta",
    year: 1994,
    description:
      "Measures E. coli growth rate across glucose concentrations in chemostat culture, leaving transient batch-mode repression effects unresolved.",
    url: "https://doi.org/10.1016/0304-4165(94)90209-7",
    relevance_score: 0.64,
    matched_on: [
      { label: "E. coli K-12", tone: "subject" },
      { label: "glucose", tone: "variable" },
      { label: "M9 media", tone: "condition" },
    ],
    importance:
      "This is the closest methodological precedent to your protocol. The chemostat design contrasts with your batch approach, isolating exactly the variable your experiment intends to vary.",
  },
  {
    id: "p3",
    title:
      "Glucose-induced overflow metabolism in aerobic E. coli batch cultures",
    authors: "Vemuri G.N., Eiteman M.A., Altman E.",
    venue: "Applied and Environmental Microbiology",
    year: 2006,
    description:
      "Characterises acetate overflow versus glucose uptake in aerobic batch E. coli at 37 °C, using flux rather than growth rate as the endpoint.",
    url: "https://journals.asm.org/doi/10.1128/AEM.72.5.3653-3661.2006",
    relevance_score: 0.52,
    matched_on: [
      { label: "E. coli", tone: "subject" },
      { label: "aerobic 37 °C", tone: "condition" },
    ],
    importance:
      "Shares your culture conditions almost exactly, which makes it useful as a protocol reference even though the measured endpoint differs from your growth-rate readout.",
  },
];

// Key differences are derived from the matched_on dimensions and per-dimension
// descriptions returned by the backend.
const KEY_DIFFERENCES: {
  matched_on: string;
  yours: string;
  prior: string;
}[] = [
  {
    matched_on: "Culture mode",
    yours:
      "Continuous glucose gradient (0–25 mM) measured in batch with direct OD600 readout.",
    prior:
      "Chemostat steady-states at fixed dilution rates, or mixed carbon source experiments.",
  },
  {
    matched_on: "Measurement endpoint",
    yours: "Specific growth rate µ as the primary outcome.",
    prior: "Acetate overflow flux or qualitative regulatory characterisation.",
  },
  {
    matched_on: "Framing",
    yours:
      "Repression-driven µ saturation as a quantitative, dose-response question.",
    prior:
      "CRP–cAMP regulation or overflow metabolism framed mechanistically.",
  },
];

const LOADING_STAGES = [
  "Searching literature…",
  "Evaluating similarity…",
] as const;

const SOURCES = ["PubMed", "Semantic Scholar", "arXiv"];

// Map backend NoveltySignal -> frontend NoveltyStatus enum (different naming).
function mapSignal(s: LitReviewResponse["signal"]): NoveltyStatus {
  if (s === "novel") return "not_found";
  if (s === "exact_match_found") return "exact_match";
  return "similar_work_exists";
}

// Backend Citation -> frontend Reference. Authors get joined into a string
// (FE renders them as a single line). matched_on tones cycle through the
// three buckets — the backend doesn't classify chips by tone; an upgrade
// is in scope for a follow-up where the LLM emits {label, tone} directly.
function citationToReference(c: Citation, idx: number): Reference {
  const tones: Array<"subject" | "variable" | "condition"> = [
    "subject", "variable", "condition",
  ];
  return {
    id: `p${idx + 1}`,
    title: c.title || "(untitled)",
    authors: (c.authors && c.authors.length > 0)
      ? c.authors.join(", ")
      : "Authors not available",
    venue: c.venue || "",
    year: c.year ?? 0,
    description: c.description || c.snippet || "",
    url: c.url || (c.doi ? `https://doi.org/${c.doi}` : "#"),
    relevance_score: c.relevance_score ?? 0,
    matched_on: (c.matched_on || []).map((label, i) => ({
      label,
      tone: tones[i % tones.length],
    })),
    importance: c.importance || "",
    key_differences: c.key_differences ?? [],
  };
}

const LiteratureCheck = () => {
  const navigate = useNavigate();
  const location = useLocation();
  // The hypothesis is passed via router state from HypothesisInput. If it's
  // missing (user navigated here directly), the page falls back to mocks
  // so the design-mockup mode still renders.
  const navState = (location.state as
    { structured?: StructuredHypothesis; domain?: string } | null) ?? null;
  const inputHypothesis = navState?.structured;

  const [stageIdx, setStageIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [activeConcept, setActiveConcept] = useState<
    keyof typeof CONCEPT | null
  >(null);

  // Real API state. `litResult` null = either still loading or the page is
  // running in mock-only mode (no hypothesis in router state).
  const [litResult, setLitResult] = useState<LitReviewResponse | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    if (!inputHypothesis) {
      // Mock-only path: pages design used a 2.4s scripted reveal; preserve it.
      const t1 = window.setTimeout(() => setStageIdx(1), 1100);
      const t2 = window.setTimeout(() => setDone(true), 2400);
      return () => {
        window.clearTimeout(t1);
        window.clearTimeout(t2);
      };
    }
    // Live path: kick off /lit-review and let the second loading-stage
    // text appear after a short delay. The "done" flag flips when the
    // response (or an error) arrives.
    const ac = new AbortController();
    const stageTimer = window.setTimeout(() => setStageIdx(1), 2500);
    postLitReview({ structured: inputHypothesis }, ac.signal)
      .then((res) => {
        setLitResult(res);
        setDone(true);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setApiError(
          err instanceof Error ? err.message : "Lit review request failed.",
        );
        setDone(true);
      });
    return () => {
      ac.abort();
      window.clearTimeout(stageTimer);
    };
  }, [inputHypothesis]);

  // Derived display values: prefer real API data; fall back to mock
  // constants so design-mockup mode (no hypothesis) still renders.
  const signalKey = litResult ? mapSignal(litResult.signal) : NOVELTY_SIGNAL;
  const status = NOVELTY_COPY[signalKey];
  const confidence = CONFIDENCE_COPY[NOVELTY_CONFIDENCE];
  const novelDescription = litResult?.description ?? NOVELTY_DESCRIPTION;
  const recommendationSummary = litResult?.summary ?? RECOMMENDATION_SUMMARY;
  const references: Reference[] = useMemo(() => {
    if (!litResult) return REFERENCES;
    return litResult.references.map(citationToReference);
  }, [litResult]);

  const progressPct = done ? 100 : stageIdx === 0 ? 35 : 75;

  return (
    <div className="relative min-h-screen overflow-hidden bg-paper text-ink">
      {/* Whisper-quiet graph-paper background */}
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
            aria-label="Literature check error"
            role="alert"
            className="mb-8 relative overflow-hidden rounded-md border border-destructive/30 bg-paper-raised"
          >
            <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-destructive" />
            <div className="flex items-start gap-4 px-7 py-5">
              <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
              <div className="space-y-1.5">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-destructive">
                  Literature lookup failed — showing demo data
                </p>
                <p className="text-[14px] leading-[1.55] text-ink-soft">
                  {apiError}
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Step indicator + hypothesis recap */}
        <section aria-labelledby="page-title" className="mb-12">
          <p className="font-mono-notebook text-[13px] uppercase tracking-[0.22em] text-muted-foreground">
            <span className="text-primary">●</span>&nbsp;&nbsp;Step{" "}
            <span className="text-ink">02</span> of 04 — Literature Check
          </p>
          <h1
            id="page-title"
            className="mt-5 font-serif-display text-[44px] leading-[1.04] text-ink sm:text-[60px]"
          >
            Has anyone done this{" "}
            <span className="italic text-primary">already</span>?
          </h1>

          {/* Hypothesis recap card — color-coded concepts + interactive legend */}
          <div className="mt-8 overflow-hidden rounded-md border border-rule bg-paper-raised">
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
              className="px-6 py-5 text-[20px] leading-[1.6] text-ink"
              style={{
                fontFamily: '"Instrument Serif", Georgia, serif',
                letterSpacing: "0.005em",
              }}
            >
              {deriveHypothesisParts(inputHypothesis).map((part, i) =>
                part.tone ? (
                  <span
                    key={i}
                    className={
                      "inline rounded-[2px] px-[3px] py-[1px] transition-all duration-300 " +
                      CONCEPT[part.tone] +
                      (activeConcept && activeConcept !== part.tone
                        ? " opacity-30"
                        : " opacity-100") +
                      (activeConcept === part.tone
                        ? " ring-1 ring-offset-1 ring-offset-paper-raised ring-current"
                        : "")
                    }
                  >
                    {part.text}
                  </span>
                ) : (
                  <span
                    key={i}
                    className={
                      "transition-opacity duration-300 " +
                      (activeConcept ? "opacity-40" : "opacity-100")
                    }
                  >
                    {part.text}
                  </span>
                )
              )}
            </p>
            {/* Interactive legend */}
            <div className="flex flex-wrap items-center gap-2 border-t border-rule bg-paper/60 px-6 py-3">
              <span className="font-mono-notebook text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
                Concepts
              </span>
              {(
                [
                  { key: "subject", label: "Subject" },
                  { key: "variable", label: "Variable" },
                  { key: "condition", label: "Condition" },
                ] as const
              ).map((c) => {
                const active = activeConcept === c.key;
                return (
                  <button
                    key={c.key}
                    type="button"
                    onMouseEnter={() => setActiveConcept(c.key)}
                    onMouseLeave={() => setActiveConcept(null)}
                    onFocus={() => setActiveConcept(c.key)}
                    onBlur={() => setActiveConcept(null)}
                    onClick={() =>
                      setActiveConcept(active ? null : c.key)
                    }
                    className={
                      "group inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] transition-all " +
                      (active
                        ? "border-ink bg-paper-raised text-ink"
                        : "border-rule bg-paper text-ink-soft hover:border-ink/40 hover:text-ink")
                    }
                  >
                    <span
                      aria-hidden
                      className={
                        "h-1.5 w-1.5 rounded-full transition-transform " +
                        CONCEPT_DOT[c.key] +
                        (active ? " scale-125" : "")
                      }
                    />
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        {/* Loading panel */}
        {!done && (
          <section
            aria-label="Searching literature"
            className="mb-12 rounded-md border border-rule bg-paper-raised px-7 py-7"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-serif-display text-[22px] text-ink">
                {LOADING_STAGES[stageIdx]}
              </p>
              <p className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground">
                {stageIdx + 1} / {LOADING_STAGES.length}
              </p>
            </div>
            <div className="mt-5 h-[3px] w-full overflow-hidden rounded-sm bg-rule-soft/70">
              <div
                className="h-full bg-sage transition-[width] duration-[900ms] ease-out"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <ul className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
              {SOURCES.map((s, i) => (
                <li
                  key={s}
                  className="inline-flex items-center gap-2 rounded-sm border border-rule bg-paper px-2.5 py-1 font-mono-notebook text-[11px] uppercase tracking-[0.18em] text-ink-soft"
                  style={{
                    opacity: stageIdx === 0 && i > 0 ? 0.45 : 1,
                    transition: "opacity 600ms ease",
                    transitionDelay: `${i * 200}ms`,
                  }}
                >
                  <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sage" />
                  {s}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Results */}
        {done && (
          <>
            {/* Novelty Assessment */}
            <section
              aria-labelledby="novelty-title"
              className="mb-6 rounded-md border border-rule bg-paper-raised"
            >
              <header className="flex items-start justify-between gap-4 border-b border-rule px-7 py-5">
                <div className="min-w-0">
                  <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                    Novelty Assessment
                  </p>
                  <h2
                    id="novelty-title"
                    className="mt-2 font-serif-display text-[28px] leading-[1.15] text-ink sm:text-[30px]"
                  >
                    {status.label}
                  </h2>
                </div>
                <span
                  className={
                    "shrink-0 inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 font-mono-notebook text-[11px] uppercase tracking-[0.2em] " +
                    status.pillBg +
                    " " +
                    status.pillBorder +
                    " " +
                    status.tone
                  }
                  aria-label={`Signal: ${status.pill}`}
                >
                  <span aria-hidden className={"h-2 w-2 rounded-full " + status.dot} />
                  {status.pill}
                </span>
              </header>

              <div className="grid grid-cols-1 gap-6 px-7 py-6 sm:grid-cols-[1fr_auto] sm:items-end">
                <p className="max-w-2xl text-[16px] leading-[1.7] text-ink-soft">
                  {novelDescription}
                </p>
                <div className="flex flex-col items-start gap-2 sm:items-end">
                  <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                    Confidence
                  </p>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label={`Confidence: ${confidence.label}.`}
                        className="group/conf inline-flex items-center gap-2.5 rounded-sm px-1.5 py-1 -mx-1.5 transition-colors hover:bg-rule-soft/40 focus:bg-rule-soft/40 focus:outline-none"
                      >
                        <span aria-hidden className="flex items-center gap-1.5">
                          {[0, 1, 2].map((i) => (
                            <span
                              key={i}
                              className={
                                "h-2 w-2 rounded-full " +
                                (i < confidence.filled ? "bg-ink" : "bg-rule")
                              }
                            />
                          ))}
                        </span>
                        <span
                          className="text-[16px] italic leading-none text-ink"
                          style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                        >
                          {confidence.label}
                        </span>
                        <Info
                          className="h-3.5 w-3.5 text-muted-foreground transition-colors group-hover/conf:text-ink"
                          strokeWidth={1.75}
                        />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent
                      side="left"
                      align="end"
                      className="max-w-[260px] rounded-sm border-rule bg-paper-raised px-3.5 py-2.5 text-[13px] leading-[1.5] text-ink-soft shadow-[0_8px_24px_-12px_hsl(var(--ink)/0.35)]"
                    >
                      <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                        How we got this
                      </p>
                      <p className="mt-1.5">
                        <span className="font-medium text-ink">{confidence.label}</span> — derived from the similarity of prior protocols, conditions, and measurement endpoints across the indexed corpus.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>
            </section>

            {/* Recommendation — system-level conclusion derived from `summary` */}
            <section
              aria-label="Recommendation"
              className="mb-12 relative overflow-hidden rounded-md border border-primary/30 bg-paper-raised"
            >
              <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
              <div className="grid grid-cols-1 gap-4 px-7 py-6 sm:grid-cols-[auto_1fr] sm:items-start sm:gap-6">
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-primary">
                  Recommendation
                </p>
                <p
                  className="text-[20px] leading-[1.45] text-ink"
                  style={{
                    fontFamily: '"Instrument Serif", Georgia, serif',
                    letterSpacing: "0.005em",
                  }}
                >
                  {recommendationSummary}
                </p>
              </div>
            </section>

            {/* Supporting Papers */}
            <section aria-labelledby="papers-title" className="mb-12">
              <div className="mb-4 flex items-baseline justify-between">
                <h2
                  id="papers-title"
                  className="font-serif-display text-[26px] leading-tight text-ink"
                >
                  Supporting papers
                </h2>
                <p className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground">
                  {references.length} found · ranked by relevance
                </p>
              </div>

              <ol className="overflow-hidden rounded-md border border-rule bg-paper-raised">
                {references.map((p, i) => {
                  const isOpen = expandedId === p.id;
                  const pct = Math.round(p.relevance_score * 100);
                  // Bar color tier by relevance score
                  const barTone =
                    p.relevance_score >= 0.7
                      ? "bg-primary"
                      : p.relevance_score >= 0.6
                      ? "bg-sage"
                      : "bg-[hsl(38_70%_45%)]";
                  return (
                    <li
                      key={p.id}
                      id={p.id}
                      className={
                        "group/paper relative transition-colors " +
                        (i > 0 ? "border-t border-rule " : "") +
                        (isOpen ? "bg-rule-soft/30" : "hover:bg-rule-soft/20")
                      }
                    >
                      {/* Animated left accent bar on hover/open */}
                      <span
                        aria-hidden
                        className={
                          "absolute inset-y-0 left-0 w-[2px] origin-top scale-y-0 transition-transform duration-500 " +
                          barTone +
                          (isOpen
                            ? " scale-y-100"
                            : " group-hover/paper:scale-y-100")
                        }
                      />

                      {/* Clickable header row */}
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedId(isOpen ? null : p.id)
                        }
                        aria-expanded={isOpen}
                        className="grid w-full grid-cols-1 items-start gap-3 px-7 py-6 text-left sm:grid-cols-[1fr_auto]"
                      >
                        <div>
                          <div className="flex items-baseline gap-3">
                            <span className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                              {String(i + 1).padStart(2, "0")}
                            </span>
                            <h3 className="font-serif-card text-[22px] leading-[1.25] text-ink transition-colors group-hover/paper:text-primary">
                              {p.title}
                            </h3>
                          </div>
                          <p
                            className="mt-2 pl-[2.1rem] font-mono-notebook text-[12px] uppercase tracking-[0.16em] text-muted-foreground/80"
                          >
                            <span className="text-ink-soft">{p.authors}</span>
                            <span className="mx-2 text-rule">·</span>
                            <span
                              className="text-[14px] italic normal-case tracking-normal text-ink-soft/90"
                              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                            >
                              {p.venue}
                            </span>
                            <span className="mx-2 text-rule">·</span>
                            <span className="text-primary/80">{p.year}</span>
                          </p>
                          <p
                            className="mt-3.5 max-w-2xl pl-[2.1rem] text-[15px] leading-[1.8] text-ink-soft/95"
                            style={{ letterSpacing: "0.005em" }}
                          >
                            {p.description}
                          </p>

                          {/* Matched-on chips — color coded */}
                          <div className="mt-4 flex flex-wrap items-center gap-2 pl-[2.1rem]">
                            <span className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              Matched on
                            </span>
                            {p.matched_on.map((m) => (
                              <span
                                key={m.label}
                                className={
                                  "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono-notebook text-[10px] uppercase tracking-[0.18em] transition-all " +
                                  (activeConcept && activeConcept !== m.tone
                                    ? "opacity-30 "
                                    : "opacity-100 ") +
                                  (m.tone === "subject"
                                    ? "border-primary/30 bg-primary/[0.06] text-primary"
                                    : m.tone === "variable"
                                    ? "border-sage/40 bg-sage-wash text-[hsl(142_45%_24%)]"
                                    : "border-[hsl(38_70%_55%)]/40 bg-[hsl(38_70%_92%)] text-[hsl(28_55%_30%)]")
                                }
                              >
                                <span
                                  aria-hidden
                                  className={
                                    "h-1 w-1 rounded-full " +
                                    CONCEPT_DOT[m.tone]
                                  }
                                />
                                {m.label}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div className="flex flex-col items-start sm:items-end">
                          <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                            Similarity
                          </p>
                          <p
                            className="mt-1 text-[28px] italic leading-none text-ink transition-transform duration-300 group-hover/paper:scale-105"
                            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                          >
                            {pct}%
                          </p>
                          <div
                            aria-hidden
                            className="mt-2 h-[3px] w-24 overflow-hidden rounded-sm bg-rule-soft/70"
                          >
                            <div
                              className={
                                "h-full origin-left transition-transform duration-700 ease-out " +
                                barTone
                              }
                              style={{
                                width: "100%",
                                transform: `scaleX(${p.relevance_score})`,
                              }}
                            />
                          </div>
                          <span
                            className={
                              "mt-3 inline-flex items-center gap-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground transition-colors group-hover/paper:text-ink"
                            }
                          >
                            {isOpen ? "Hide" : "Why this matters"}
                            <ChevronDown
                              className={
                                "h-3 w-3 transition-transform duration-300 " +
                                (isOpen ? "rotate-180" : "")
                              }
                              strokeWidth={1.75}
                            />
                          </span>
                        </div>
                      </button>

                      {/* Expandable "why matched" panel */}
                      <div
                        className={
                          "grid overflow-hidden transition-[grid-template-rows] duration-500 ease-out " +
                          (isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")
                        }
                      >
                        <div className="min-h-0 overflow-hidden">
                          <div className="mx-7 mb-6 rounded-sm border border-rule bg-paper px-5 py-4">
                            <div className="flex items-start gap-3">
                              <Sparkles
                                className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                                strokeWidth={1.75}
                              />
                              <div className="min-w-0 flex-1">
                                <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                                  Why this matters
                                </p>
                                <p
                                  className="mt-2 text-[17px] leading-[1.65] text-ink-soft"
                                  style={{
                                    fontFamily:
                                      '"Instrument Serif", Georgia, serif',
                                    letterSpacing: "0.005em",
                                  }}
                                >
                                  {p.importance}
                                </p>
                                <a
                                  href={p.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="mt-3 inline-flex items-center gap-1.5 border-b border-transparent pb-0.5 font-mono-notebook text-[13px] uppercase tracking-[0.2em] text-ink transition-colors hover:border-ink"
                                >
                                  View full paper
                                  <ExternalLink
                                    className="h-3 w-3"
                                    strokeWidth={1.75}
                                  />
                                </a>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>

            {/* Key differences. Phase E: when the BE shipped real
                key_differences on any reference, render those grouped
                by reference (each entry cites the source paper, the
                dimension, and the user's matching field). Falls back
                to the hardcoded KEY_DIFFERENCES table for mock-only
                mode or when the BE hasn't been upgraded. */}
            <section
              aria-labelledby="diff-title"
              className="mb-14 relative overflow-hidden rounded-md border border-rule bg-paper-raised"
            >
              <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-sage" />
              <header className="border-b border-rule px-7 py-5">
                <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-sage">
                  Key differences
                </p>
                <h2
                  id="diff-title"
                  className="mt-2 font-serif-display text-[26px] leading-tight text-ink"
                >
                  Where your work diverges
                </h2>
                <p className="mt-2 max-w-2xl text-[13px] leading-[1.55] text-ink-soft">
                  {references.some((r) => (r.key_differences ?? []).length > 0)
                    ? "Per-reference deltas with the dimension that differs, what each paper does, and why your study is still needed. Each item cites the source paper."
                    : "How this experiment diverges from the closest published work."}
                </p>
              </header>
              {references.some((r) => (r.key_differences ?? []).length > 0) ? (
                <ol className="divide-y divide-rule">
                  {references
                    .filter((r) => (r.key_differences ?? []).length > 0)
                    .map((r) => {
                      const diffs = r.key_differences ?? [];
                      // Pre-collected dimensions chip set so the collapsed
                      // summary previews what's inside without revealing the
                      // full body — the user can scan which axes differ
                      // before deciding whether to open the group.
                      const dims = Array.from(new Set(diffs.map((d) => d.dimension)));
                      return (
                        <li key={r.id} className="px-0 py-0">
                          <details className="diff-group group">
                            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-7 py-5 transition-colors hover:bg-rule-soft/30">
                              <div className="min-w-0 flex-1">
                                {/* Title as anchor → jumps to the matching
                                    <li id={p.id}> in the supporting-papers
                                    list above. stopPropagation prevents the
                                    click from also toggling the <details>
                                    so navigation and disclosure stay
                                    independent. */}
                                <a
                                  href={`#${r.id}`}
                                  onClick={(e) => e.stopPropagation()}
                                  className="block truncate font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground transition-colors hover:text-primary"
                                  title={r.title}
                                >
                                  ↑ {r.title}
                                </a>
                                <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                                  <span className="font-mono-notebook text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
                                    {r.year}
                                  </span>
                                  <span aria-hidden className="text-rule">·</span>
                                  <span className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-sage">
                                    {diffs.length} {diffs.length === 1 ? "difference" : "differences"}
                                  </span>
                                  {dims.length > 0 && (
                                    <>
                                      <span aria-hidden className="text-rule">·</span>
                                      <span className="font-mono-notebook text-[10px] uppercase tracking-[0.18em] text-ink-soft/80">
                                        {dims.join(" · ")}
                                      </span>
                                    </>
                                  )}
                                </div>
                              </div>
                              <span className="inline-flex items-center gap-2 font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground transition-colors group-hover:text-ink">
                                <span className="hidden sm:inline diff-toggle-show">View</span>
                                <span className="hidden sm:inline diff-toggle-hide">Hide</span>
                                <ChevronDown
                                  className="diff-chevron h-4 w-4 transition-transform"
                                  strokeWidth={1.75}
                                />
                              </span>
                            </summary>
                            <ul className="space-y-4 border-t border-rule px-7 py-5">
                              {diffs.map((d, i) => (
                                <li key={i} className="border-l-2 border-rule pl-4">
                                  <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-primary">
                                    {d.dimension}
                                  </p>
                                  <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                                    <div>
                                      <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-sage">
                                        Your approach
                                      </p>
                                      <p className="mt-1 flex gap-2 text-[14px] leading-[1.55] text-ink">
                                        <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-sage" />
                                        <span>{d.our_approach}</span>
                                      </p>
                                    </div>
                                    <div className="sm:border-l sm:border-rule sm:pl-4">
                                      <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                                        Their approach
                                      </p>
                                      <p className="mt-1 flex gap-2 text-[14px] leading-[1.55] text-ink-soft">
                                        <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-rule" />
                                        <span>{d.their_approach}</span>
                                      </p>
                                    </div>
                                  </div>
                                  <p className="mt-2.5 text-[13px] leading-[1.55] text-ink-soft">
                                    <span className="font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                                      why it matters{" "}
                                    </span>
                                    {d.gap_significance}
                                  </p>
                                </li>
                              ))}
                            </ul>
                          </details>
                        </li>
                      );
                    })}
                </ol>
              ) : (
                <ol className="divide-y divide-rule">
                  {KEY_DIFFERENCES.map((d, i) => (
                    <li key={i} className="px-7 py-5">
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                        {d.matched_on}
                      </p>
                      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div>
                          <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-sage">
                            Your experiment
                          </p>
                          <p className="mt-1.5 flex gap-2 text-[15px] leading-[1.65] text-ink">
                            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-sage" />
                            <span>{d.yours}</span>
                          </p>
                        </div>
                        <div className="sm:border-l sm:border-rule sm:pl-4">
                          <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                            Prior work
                          </p>
                          <p className="mt-1.5 flex gap-2 text-[15px] leading-[1.65] text-ink-soft">
                            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-rule" />
                            <span>{d.prior}</span>
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            {/* Step transition + CTA */}
            <section
              aria-label="Continue to next step"
              className="relative overflow-hidden rounded-md border border-primary/40 bg-paper-raised shadow-[0_1px_0_hsl(var(--primary)/0.15),0_24px_60px_-30px_hsl(var(--primary)/0.35)]"
            >
              <div aria-hidden className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-rule to-transparent" />

              <div className="grid grid-cols-1 gap-0 sm:grid-cols-[1fr_auto_1fr]">
                <div className="px-7 py-7 sm:px-9 sm:py-9">
                  <div className="flex items-center gap-3">
                    <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground">
                      <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
                    </span>
                    <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                      Step 02
                    </p>
                  </div>
                  <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                    Literature check
                  </h3>
                  <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                    Reviewed. Your framing is distinct enough to proceed.
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
                      03
                    </span>
                    <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-primary">
                      Step 03 — Up next
                    </p>
                  </div>
                  <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                    Experiment plan
                  </h3>
                  <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                    We'll now construct a full experimental plan including protocol, materials, and timeline.
                  </p>
                </div>
              </div>

              <div className="flex flex-col-reverse items-stretch justify-between gap-4 border-t border-rule bg-paper/60 px-7 py-5 sm:flex-row sm:items-center sm:px-9">
                <div className="flex items-center gap-5">
                  <button
                    type="button"
                    onClick={() => navigate("/lab")}
                    className="group inline-flex items-center gap-2 font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-ink"
                    aria-label="Go back to hypothesis"
                  >
                    <ArrowRight className="h-4 w-4 rotate-180 transition-transform group-hover:-translate-x-0.5" strokeWidth={1.75} />
                    Back to hypothesis
                  </button>
                  <span aria-hidden className="hidden h-4 w-px bg-rule sm:block" />
                  <p className="hidden font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground sm:block">
                    Ready when you are <span className="text-primary">●</span>
                  </p>
                </div>
                <Button
                  onClick={() => navigate("/plan", {
                    state: {
                      plan_id: litResult?.plan_id,
                      structured: inputHypothesis,
                    },
                  })}
                  className="group h-14 gap-3 rounded-sm bg-ink px-7 text-[15px] font-medium text-paper shadow-[0_8px_24px_-12px_hsl(var(--ink)/0.6)] transition-all hover:bg-ink/90 hover:shadow-[0_10px_28px_-10px_hsl(var(--ink)/0.7)]"
                >
                  <span className="font-mono-notebook text-[10px] uppercase tracking-[0.24em] opacity-70">
                    Step 03 →
                  </span>
                  <span className="font-serif-display text-[19px] italic">
                    Generate experiment plan
                  </span>
                  <ArrowRight
                    className="h-5 w-5 transition-transform group-hover:translate-x-0.5"
                    strokeWidth={1.75}
                  />
                </Button>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
};

export default LiteratureCheck;

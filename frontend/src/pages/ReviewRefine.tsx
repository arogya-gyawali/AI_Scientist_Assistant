import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Download,
  FlaskConical,
  Pencil,
  RotateCw,
  Sparkles,
  Star,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const HYPOTHESIS_SUMMARY =
  "Increasing glucose concentration in M9 minimal media reduces the specific growth rate of E. coli K-12 above 10 mM, due to catabolite repression under aerobic conditions at 37 °C.";

type SectionKey = "protocol" | "materials" | "budget" | "timeline";

const SECTIONS: Array<{
  key: SectionKey;
  label: string;
  meta: string;
  preview: string[];
  details: string[];
}> = [
  {
    key: "protocol",
    label: "Protocol",
    meta: "9 steps · ~6 h hands-on",
    preview: [
      "01 — Prepare M9 minimal media stock",
      "02 — Prepare a 500 mM glucose feed solution",
      "03 — Streak E. coli K-12 MG1655 from glycerol stock",
    ],
    details: [
      "04 — Acclimate cells to M9 + glucose 5 mM",
      "05 — Set up the glucose-gradient panel (8 conditions × 3 replicates)",
      "06 — Inoculate to OD600 = 0.05 across all wells",
      "07 — Run kinetic OD600 measurements (every 10 min, 18 h)",
      "08 — Compute specific growth rate µ per condition",
      "09 — Quality controls (blanks, reference, drift check)",
    ],
  },
  {
    key: "materials",
    label: "Materials",
    meta: "8 items · 2 groups",
    preview: [
      "D-(+)-Glucose, ≥99.5% — Sigma-Aldrich G7021",
      "M9 Minimal Salts, 5× — Sigma-Aldrich M6030",
      "E. coli K-12 MG1655 — ATCC 700926",
    ],
    details: [
      "MgSO₄ anhydrous — Fisher M65-500",
      "CaCl₂ dihydrate — Sigma C3306",
      "96-well clear-bottom plate — Corning 3631",
      "Breathable sealing film — Sigma Z380059",
      "0.22 µm PES filter units — Millipore SCGPU05RE",
    ],
  },
  {
    key: "budget",
    label: "Budget",
    meta: "Total $1,500 USD",
    preview: [
      "Reagents — $240",
      "Plates, films, filters — $180",
      "Plate-reader time — $360",
    ],
    details: ["Tech labour (~24 h) — $720", "Contingency (~0%) — $0"],
  },
  {
    key: "timeline",
    label: "Timeline",
    meta: "~4 weeks",
    preview: [
      "Week 1 — Setup & QC",
      "Week 2 — Pilot run",
      "Week 3 — Full experiment",
    ],
    details: ["Week 4 — Analysis, figures, methods draft"],
  },
];

const QUICK_TAGS = [
  "Missing controls",
  "Unrealistic timeline",
  "Add more detail",
  "Reagent substitution",
  "Stats plan unclear",
] as const;

const EDITABLE: Array<{ key: string; label: string; placeholder: string }> = [
  {
    key: "protocol-notes",
    label: "Protocol notes",
    placeholder:
      "e.g. Add a 0.5 mM glucose condition; specify shake amplitude during reads.",
  },
  {
    key: "materials-corrections",
    label: "Materials corrections",
    placeholder:
      "e.g. Substitute Corning 3631 with Greiner 655090; we have it in stock.",
  },
  {
    key: "timeline-adjustments",
    label: "Timeline adjustments",
    placeholder:
      "e.g. Compress Week 1 to 3 days — strain is already revived on a working plate.",
  },
];

const ReviewRefine = () => {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    protocol: false,
    materials: false,
    budget: false,
    timeline: false,
  });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [tags, setTags] = useState<Set<string>>(new Set());
  const [phase, setPhase] = useState<"idle" | "incorporating" | "refreshed">(
    "idle",
  );
  const refreshTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
  }, []);

  const toggleExpand = (k: SectionKey) =>
    setExpanded((s) => ({ ...s, [k]: !s[k] }));

  const toggleTag = (t: string) =>
    setTags((s) => {
      const next = new Set(s);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  const updateEdit = (k: string, v: string) =>
    setEdits((s) => ({ ...s, [k]: v }));

  const editsCount = Object.values(edits).filter((v) => v.trim()).length;
  const hasFeedback =
    rating > 0 || feedback.trim().length > 0 || tags.size > 0 || editsCount > 0;

  const handleRegenerate = () => {
    if (!hasFeedback || phase === "incorporating") return;
    setPhase("incorporating");
    refreshTimer.current = window.setTimeout(() => {
      setPhase("refreshed");
    }, 1800);
  };

  const ratingLabel = ["", "Poor", "Fair", "Solid", "Strong", "Excellent"][rating];

  return (
    <div className="relative min-h-screen overflow-hidden bg-paper text-ink">
      <div aria-hidden className="pointer-events-none absolute inset-0 lab-grid" />

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
            <Link className="transition-colors hover:text-ink" to="/drafts">Drafts</Link>
            <Link className="transition-colors hover:text-ink" to="/library">Library</Link>
            <Link className="transition-colors hover:text-ink" to="/account">Account</Link>
          </nav>
        </div>
      </header>

      <main className="relative mx-auto max-w-5xl px-6 pb-24 pt-12 sm:px-10 sm:pt-16">
        {/* Step indicator + headline + recap */}
        <section aria-labelledby="page-title" className="mb-12">
          <p className="font-mono-notebook text-[13px] uppercase tracking-[0.22em] text-muted-foreground">
            <span className="text-primary">●</span>&nbsp;&nbsp;Step{" "}
            <span className="text-ink">04</span> of 04 — Review &amp; refine
          </p>
          <h1
            id="page-title"
            className="mt-5 font-serif-display text-[44px] leading-[1.04] text-ink sm:text-[60px]"
          >
            Review and{" "}
            <span className="italic text-primary">improve</span> the plan
          </h1>

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
        </section>

        {/* SECTION 1 — Plan overview */}
        <section aria-labelledby="overview-title" className="mb-14">
          <header className="mb-4 flex items-baseline justify-between gap-4">
            <h2
              id="overview-title"
              className="font-serif-display text-[26px] leading-tight text-ink"
            >
              Plan overview
            </h2>
            <p className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground">
              Compact summary · expand to inspect
            </p>
          </header>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {SECTIONS.map((s) => {
              const isOpen = expanded[s.key];
              return (
                <article
                  key={s.key}
                  className="overflow-hidden rounded-md border border-rule bg-paper-raised"
                >
                  <header className="flex items-baseline justify-between gap-3 border-b border-rule px-6 py-4">
                    <div>
                      <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                        {s.meta}
                      </p>
                      <h3 className="mt-1 font-serif-display text-[22px] leading-tight text-ink">
                        {s.label}
                      </h3>
                    </div>
                  </header>
                  <ul className="divide-y divide-rule">
                    {s.preview.map((line, i) => (
                      <li
                        key={i}
                        className="px-6 py-3 text-[15px] leading-snug text-ink-soft"
                        style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                      >
                        {line}
                      </li>
                    ))}
                    {isOpen &&
                      s.details.map((line, i) => (
                        <li
                          key={"d" + i}
                          className="bg-rule-soft/20 px-6 py-3 text-[15px] leading-snug text-ink-soft animate-in fade-in duration-300"
                          style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                        >
                          {line}
                        </li>
                      ))}
                  </ul>
                  <button
                    type="button"
                    onClick={() => toggleExpand(s.key)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center justify-between border-t border-rule px-6 py-3 font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-ink-soft transition-colors hover:bg-rule-soft/30 hover:text-ink"
                  >
                    {isOpen ? "Hide details" : "View details"}
                    <ChevronDown
                      className={
                        "h-3.5 w-3.5 transition-transform " +
                        (isOpen ? "rotate-180" : "")
                      }
                      strokeWidth={1.75}
                    />
                  </button>
                </article>
              );
            })}
          </div>
        </section>

        {/* SECTION 2 — Editable corrections */}
        <section aria-labelledby="edits-title" className="mb-14">
          <header className="mb-4 flex items-baseline justify-between gap-4">
            <div>
              <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                Suggest corrections or refinements
              </p>
              <h2
                id="edits-title"
                className="mt-1.5 font-serif-display text-[26px] leading-tight text-ink"
              >
                What would you change?
              </h2>
            </div>
            <p className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground">
              {editsCount}/{EDITABLE.length} noted
            </p>
          </header>

          <div className="overflow-hidden rounded-md border border-rule bg-paper-raised">
            {EDITABLE.map((e, i) => {
              const filled = (edits[e.key] ?? "").trim().length > 0;
              return (
                <div
                  key={e.key}
                  className={
                    "group/edit relative px-6 py-5 transition-colors focus-within:bg-rule-soft/40 hover:bg-rule-soft/20 sm:px-7 " +
                    (i > 0 ? "border-t border-rule" : "")
                  }
                >
                  <span
                    aria-hidden
                    className="pointer-events-none absolute inset-y-4 left-0 w-[2px] rounded-r-sm bg-primary opacity-0 transition-opacity group-focus-within/edit:opacity-100"
                  />
                  <div className="flex items-baseline justify-between gap-3">
                    <label
                      htmlFor={e.key}
                      className="flex items-center gap-2 font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-ink-soft"
                    >
                      {e.label}
                      <span
                        aria-hidden
                        className={
                          "h-1.5 w-1.5 rounded-full transition-colors " +
                          (filled ? "bg-primary/70" : "bg-rule")
                        }
                      />
                    </label>
                  </div>
                  <textarea
                    id={e.key}
                    value={edits[e.key] ?? ""}
                    onChange={(ev) => updateEdit(e.key, ev.target.value)}
                    placeholder={e.placeholder}
                    rows={2}
                    className="mt-2 block w-full resize-none border-0 border-b border-rule/60 bg-transparent px-0 py-2 text-[18px] leading-[1.5] text-ink shadow-none outline-none transition-colors placeholder:text-muted-foreground/60 hover:border-ink/40 focus:border-primary"
                    style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                  />
                </div>
              );
            })}
          </div>
        </section>

        {/* SECTION 3 — Feedback */}
        <section aria-labelledby="feedback-title" className="mb-14">
          <header className="mb-4">
            <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              Feedback
            </p>
            <h2
              id="feedback-title"
              className="mt-1.5 font-serif-display text-[26px] leading-tight text-ink"
            >
              Rate the plan
            </h2>
          </header>

          <div className="rounded-md border border-rule bg-paper-raised">
            {/* Rating */}
            <div className="flex flex-col gap-4 border-b border-rule px-7 py-6 sm:flex-row sm:items-center sm:justify-between">
              <div
                className="flex items-center gap-2"
                onMouseLeave={() => setHoverRating(0)}
              >
                {[1, 2, 3, 4, 5].map((n) => {
                  const active = (hoverRating || rating) >= n;
                  return (
                    <button
                      key={n}
                      type="button"
                      aria-label={`${n} of 5`}
                      onMouseEnter={() => setHoverRating(n)}
                      onFocus={() => setHoverRating(n)}
                      onClick={() => setRating(n)}
                      className="rounded-sm p-1 transition-transform hover:scale-110 focus:scale-110 focus:outline-none"
                    >
                      <Star
                        className={
                          "h-7 w-7 transition-colors " +
                          (active ? "text-ink" : "text-rule")
                        }
                        strokeWidth={1.5}
                        fill={active ? "currentColor" : "none"}
                      />
                    </button>
                  );
                })}
              </div>
              <p
                className="text-[18px] italic text-ink-soft"
                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
              >
                {rating === 0
                  ? "Tap a star to rate"
                  : `${rating}/5 — ${ratingLabel}`}
              </p>
            </div>

            {/* Quick tags */}
            <div className="border-b border-rule px-7 py-5">
              <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                Quick flags
              </p>
              <ul className="mt-3 flex flex-wrap gap-2">
                {QUICK_TAGS.map((t) => {
                  const on = tags.has(t);
                  return (
                    <li key={t}>
                      <button
                        type="button"
                        onClick={() => toggleTag(t)}
                        aria-pressed={on}
                        className={
                          "inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 font-mono-notebook text-[11px] uppercase tracking-[0.2em] transition-colors " +
                          (on
                            ? "border-ink bg-ink text-paper"
                            : "border-rule bg-paper text-ink-soft hover:border-ink/60 hover:text-ink")
                        }
                      >
                        {on && <Check className="h-3 w-3" strokeWidth={2.5} />}
                        {t}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>

            {/* Free text */}
            <div className="px-7 py-5">
              <label
                htmlFor="freeform-feedback"
                className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground"
              >
                What would you improve?
              </label>
              <textarea
                id="freeform-feedback"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={3}
                placeholder="Tell us where the plan falls short — sample size, controls, sequencing of steps, anything."
                className="mt-2 block w-full resize-none border-0 border-b border-rule/60 bg-transparent px-0 py-2 text-[18px] leading-[1.55] text-ink shadow-none outline-none transition-colors placeholder:text-muted-foreground/60 hover:border-ink/40 focus:border-primary"
                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
              />
            </div>
          </div>
        </section>

        {/* SECTION 4 — Learning signal */}
        <section aria-label="Learning signal" className="mb-14">
          <div className="relative overflow-hidden rounded-md border border-rule bg-paper-raised px-7 py-6 sm:px-9">
            <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-sage" />
            <div className="flex items-start gap-4">
              <span
                aria-hidden
                className="mt-1 flex h-9 w-9 items-center justify-center rounded-sm border border-rule bg-paper"
              >
                <Sparkles className="h-4 w-4 text-sage" strokeWidth={1.5} />
              </span>
              <div>
                <p className="font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-sage">
                  Learning signal
                </p>
                <p
                  className="mt-2 max-w-2xl text-[18px] italic leading-[1.6] text-ink"
                  style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                >
                  This system improves from expert feedback. Your corrections will refine future experiment plans.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 5 — Actions */}
        <section
          aria-label="Actions"
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
                  Step 04
                </p>
              </div>
              <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                Review &amp; refine
              </h3>
              <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                {phase === "refreshed"
                  ? "Plan refreshed with your feedback."
                  : hasFeedback
                    ? `${editsCount} edit${editsCount === 1 ? "" : "s"}, ${tags.size} flag${tags.size === 1 ? "" : "s"}, rating ${rating || "–"}/5.`
                    : "No edits yet — add corrections, flags, or a rating below."}
              </p>
            </div>

            <div className="flex items-center justify-center border-rule px-6 py-2 sm:border-x sm:px-8 sm:py-9">
              <div className="flex flex-col items-center gap-2 sm:gap-3" aria-hidden>
                <span className="hidden h-8 w-px bg-rule sm:block" />
                <ArrowRight
                  className={
                    "h-5 w-5 transition-colors " +
                    (hasFeedback ? "text-primary" : "text-muted-foreground/40")
                  }
                  strokeWidth={1.75}
                />
                <span className="hidden h-8 w-px bg-rule sm:block" />
              </div>
            </div>

            <div className="px-7 py-7 sm:px-9 sm:py-9">
              <div className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary/60 bg-paper text-[12px] font-medium text-primary">
                  <RotateCw className="h-3.5 w-3.5" strokeWidth={1.75} />
                </span>
                <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-primary">
                  Improved plan
                </p>
              </div>
              <h3 className="mt-4 font-serif-display text-[26px] leading-tight text-ink">
                Regenerate with feedback
              </h3>
              <p className="mt-2 text-[14px] leading-[1.65] text-ink-soft">
                We re-run the planner with your edits applied as guidance.
              </p>
            </div>
          </div>

          <div className="flex flex-col-reverse items-stretch gap-4 border-t border-rule bg-paper/60 px-7 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-9">
            <div className="flex flex-wrap items-center gap-4">
              <button
                type="button"
                onClick={() => navigate("/plan")}
                className="group inline-flex items-center gap-2 font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-ink"
                aria-label="Go back to experiment plan"
              >
                <ArrowRight className="h-4 w-4 rotate-180 transition-transform group-hover:-translate-x-0.5" strokeWidth={1.75} />
                Back to plan
              </button>
              <span aria-hidden className="hidden h-4 w-px bg-rule sm:block" />
              <Button
                variant="outline"
                className="h-12 gap-2 rounded-sm border-rule bg-paper px-5 text-[13px] font-medium text-ink hover:bg-rule-soft/40"
                onClick={() => {
                  /* mock */
                }}
              >
                <Download className="h-4 w-4" strokeWidth={1.75} />
                <span className="font-mono-notebook text-[11px] uppercase tracking-[0.18em]">
                  Download plan (PDF)
                </span>
              </Button>
              <p className="hidden font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:block">
                {phase === "incorporating"
                  ? "Incorporating feedback…"
                  : phase === "refreshed"
                    ? <>Refreshed <span className="text-sage">●</span></>
                    : hasFeedback
                      ? <>Ready to regenerate <span className="text-primary">●</span></>
                      : "Add at least one signal to regenerate"}
              </p>
            </div>

            <Button
              onClick={handleRegenerate}
              disabled={!hasFeedback || phase === "incorporating"}
              className="group h-14 gap-3 rounded-sm bg-ink px-7 text-[15px] font-medium text-paper shadow-[0_8px_24px_-12px_hsl(var(--ink)/0.6)] transition-all hover:bg-ink/90 hover:shadow-[0_10px_28px_-10px_hsl(var(--ink)/0.7)] disabled:bg-ink/20 disabled:text-paper/70 disabled:shadow-none"
            >
              <span className="font-mono-notebook text-[10px] uppercase tracking-[0.24em] opacity-70">
                {phase === "incorporating" ? "Working…" : "Regenerate"}
              </span>
              <span className="font-serif-display text-[19px] italic">
                {phase === "incorporating"
                  ? "Incorporating feedback…"
                  : "Improved plan"}
              </span>
              {phase === "incorporating" ? (
                <RotateCw className="h-5 w-5 animate-spin" strokeWidth={1.75} />
              ) : (
                <ArrowRight
                  className="h-5 w-5 transition-transform group-hover:translate-x-0.5"
                  strokeWidth={1.75}
                />
              )}
            </Button>
          </div>
        </section>

        <p className="mt-6 text-center font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          Next plans will incorporate your feedback where relevant.
        </p>

        {/* Mock refresh confirmation */}
        {phase === "refreshed" && (
          <div
            role="status"
            className="mt-6 flex items-center justify-between gap-4 rounded-md border border-sage/30 bg-sage-wash px-6 py-4 animate-in fade-in slide-in-from-bottom-2 duration-300"
          >
            <div className="flex items-center gap-3">
              <span className="flex h-7 w-7 items-center justify-center rounded-full border border-sage/40 bg-paper">
                <Check className="h-3.5 w-3.5 text-sage" strokeWidth={2.5} />
              </span>
              <p
                className="text-[16px] italic text-ink"
                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
              >
                Plan refreshed. Review the updated protocol and materials above.
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate("/plan")}
              className="font-mono-notebook text-[11px] uppercase tracking-[0.2em] text-sage transition-colors hover:text-ink"
            >
              View plan →
            </button>
          </div>
        )}
      </main>
    </div>
  );
};

export default ReviewRefine;

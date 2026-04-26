import { useEffect, useRef, useState } from "react";

type Stage = {
  key: string;
  label: string;
  then: number; // days
  now: number; // days
  thenNote: string;
  nowNote: string;
};

const STAGES: Stage[] = [
  {
    key: "ideate",
    label: "Frame the idea",
    then: 3,
    now: 0.05,
    thenNote: "Notebook scribbles, lost for a week",
    nowNote: "Type prose → parsed into structure",
  },
  {
    key: "literature",
    label: "Literature check",
    then: 5,
    now: 0.1,
    thenNote: "Days on PubMed, Scholar, Semantic",
    nowNote: "Auto-search, novelty flagged",
  },
  {
    key: "protocol",
    label: "Protocol draft",
    then: 7,
    now: 0.15,
    thenNote: "Write from memory, argue with PI",
    nowNote: "Cited methods, fully editable",
  },
  {
    key: "budget",
    label: "Budget & timeline",
    then: 6,
    now: 0.1,
    thenNote: "Email three vendors, wait",
    nowNote: "Costed reagents + equipment",
  },
];

const TOTAL_THEN = STAGES.reduce((a, s) => a + s.then, 0);
const TOTAL_NOW = STAGES.reduce((a, s) => a + s.now, 0);
const MAX = Math.max(...STAGES.map((s) => s.then));

const SPEEDUP = Math.round(TOTAL_THEN / TOTAL_NOW);

export const WorkflowChart = () => {
  const [active, setActive] = useState<string>(STAGES[0].key);
  const [animated, setAnimated] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setAnimated(true);
            io.disconnect();
          }
        });
      },
      { threshold: 0.25 },
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, []);

  const activeStage = STAGES.find((s) => s.key === active) ?? STAGES[0];

  return (
    <div
      ref={ref}
      className="rounded-md border border-rule bg-paper-raised p-6 sm:p-8"
    >
      {/* Legend & totals */}
      <div className="flex flex-col gap-5 border-b border-rule pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-wrap items-center gap-x-7 gap-y-3">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="h-3.5 w-3.5 rounded-sm bg-ink/70"
            />
            <span className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-ink-soft">
              Then
            </span>
            <span
              className="text-[20px] italic leading-none text-ink"
              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
            >
              {TOTAL_THEN} days
            </span>
          </div>
          <span className="text-muted-foreground">·</span>
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="h-3.5 w-3.5 rounded-sm bg-sage"
            />
            <span className="font-mono-notebook text-[12px] uppercase tracking-[0.2em] text-sage">
              Now
            </span>
            <span
              className="text-[20px] italic leading-none text-sage"
              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
            >
              ~{Math.round(TOTAL_NOW * 24 * 10) / 10} h
            </span>
          </div>
        </div>
        <p
          className="text-[18px] italic leading-snug text-ink-soft"
          style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
        >
          ~{SPEEDUP}× faster, end-to-end
        </p>
      </div>

      {/* Bars */}
      <div className="mt-7 space-y-7">
        {STAGES.map((s) => {
          const isActive = s.key === active;
          const thenPct = (s.then / MAX) * 100;
          const nowPct = (s.now / MAX) * 100;
          return (
            <button
              key={s.key}
              type="button"
              onMouseEnter={() => setActive(s.key)}
              onFocus={() => setActive(s.key)}
              onClick={() => setActive(s.key)}
              className={
                "group block w-full rounded-sm px-3 py-3 text-left transition-colors -mx-3 " +
                (isActive ? "bg-rule-soft/40" : "hover:bg-rule-soft/30")
              }
              aria-pressed={isActive}
            >
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <div className="flex items-baseline gap-4">
                  <span className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
                    {String(STAGES.indexOf(s) + 1).padStart(2, "0")}
                  </span>
                  <span className="font-serif-display text-[22px] leading-tight text-ink">
                    {s.label}
                  </span>
                </div>
                <span className="font-mono-notebook text-[13px] uppercase tracking-[0.18em] text-muted-foreground">
                  {s.then}d &nbsp;→&nbsp;{" "}
                  <span className="text-sage">
                    {s.now < 1 ? `${Math.round(s.now * 24 * 10) / 10}h` : `${s.now}d`}
                  </span>
                </span>
              </div>

              {/* Then bar */}
              <div className="relative h-3 w-full overflow-hidden rounded-sm bg-rule-soft/60">
                <div
                  className="h-full bg-ink/70 transition-[width] duration-[1100ms] ease-out"
                  style={{
                    width: animated ? `${thenPct}%` : "0%",
                    transitionDelay: `${STAGES.indexOf(s) * 90}ms`,
                  }}
                />
              </div>
              {/* Now bar */}
              <div className="relative mt-2 h-3 w-full overflow-hidden rounded-sm bg-rule-soft/60">
                <div
                  className="h-full bg-sage transition-[width] duration-[1100ms] ease-out"
                  style={{
                    width: animated ? `${Math.max(nowPct, 0.6)}%` : "0%",
                    transitionDelay: `${STAGES.indexOf(s) * 90 + 180}ms`,
                  }}
                />
              </div>
            </button>
          );
        })}
      </div>

      {/* Active stage detail */}
      <div className="mt-8 grid grid-cols-1 gap-6 border-t border-rule pt-6 sm:grid-cols-2">
        <div>
          <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-muted-foreground">
            Then
          </p>
          <p
            className="mt-2 text-[19px] italic leading-[1.6] text-ink-soft"
            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
          >
            {activeStage.thenNote}.
          </p>
        </div>
        <div>
          <p className="font-mono-notebook text-[12px] uppercase tracking-[0.22em] text-sage">
            Now
          </p>
          <p
            className="mt-2 text-[19px] italic leading-[1.6] text-ink"
            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
          >
            {activeStage.nowNote}.
          </p>
        </div>
      </div>
    </div>
  );
};

export default WorkflowChart;

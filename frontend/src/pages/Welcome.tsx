import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, FlaskConical } from "lucide-react";

const PILLARS = [
  {
    no: "01",
    label: "Hypothesis",
    body: "Type prose, get structure. Subject, variables, conditions — parsed in seconds.",
  },
  {
    no: "02",
    label: "Literature",
    body: "Auto-scan PubMed, arXiv, Semantic Scholar. Novelty flagged, gaps surfaced.",
  },
  {
    no: "03",
    label: "Protocol",
    body: "Costed reagents, equipment, timeline. Cited methods, fully editable.",
  },
  {
    no: "04",
    label: "Refine",
    body: "Iterate against critique. Sharpen until the plan is publication-grade.",
  },
];

const WORDS = ["hypothesis.", "literature.", "protocol.", "experiment."];

const Welcome = () => {
  const navigate = useNavigate();
  const [exiting, setExiting] = useState(false);
  const [wordIdx, setWordIdx] = useState(0);
  const [mouse, setMouse] = useState({ x: 0.5, y: 0.5 });
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setWordIdx((i) => (i + 1) % WORDS.length), 2200);
    return () => clearInterval(t);
  }, []);

  const handleEnter = () => {
    if (exiting) return;
    setExiting(true);
    setTimeout(() => navigate("/lab"), 620);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleEnter();
    }
  };

  const handleMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = stageRef.current?.getBoundingClientRect();
    if (!r) return;
    setMouse({
      x: (e.clientX - r.left) / r.width,
      y: (e.clientY - r.top) / r.height,
    });
  };

  // parallax offsets
  const px = (mouse.x - 0.5) * 2;
  const py = (mouse.y - 0.5) * 2;

  return (
    <div
      ref={stageRef}
      role="button"
      tabIndex={0}
      onClick={handleEnter}
      onKeyDown={handleKey}
      onMouseMove={handleMove}
      aria-label="Enter Praxis"
      className={
        "group relative flex min-h-screen cursor-pointer flex-col overflow-hidden bg-paper text-ink outline-none transition-all duration-[620ms] ease-[cubic-bezier(0.16,1,0.3,1)] " +
        (exiting ? "scale-[1.04] opacity-0" : "scale-100 opacity-100")
      }
    >
      {/* Graph paper */}
      <div aria-hidden className="pointer-events-none absolute inset-0 lab-grid" />

      {/* Soft sage halo following cursor */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 transition-opacity duration-700"
        style={{
          background: `radial-gradient(600px circle at ${mouse.x * 100}% ${mouse.y * 100}%, hsl(var(--sage) / 0.08), transparent 60%)`,
        }}
      />

      {/* Decorative chemistry SVG — top right, parallax */}
      <svg
        aria-hidden
        viewBox="0 0 200 200"
        className="pointer-events-none absolute right-8 top-16 hidden h-56 w-56 text-ink opacity-[0.06] sm:block"
        fill="none"
        stroke="currentColor"
        strokeWidth="0.8"
        style={{ transform: `translate3d(${px * -10}px, ${py * -10}px, 0)` }}
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
      </svg>

      {/* Decorative orbit — bottom left, parallax */}
      <svg
        aria-hidden
        viewBox="0 0 240 240"
        className="pointer-events-none absolute -bottom-12 -left-12 hidden h-80 w-80 text-sage opacity-[0.18] sm:block"
        fill="none"
        stroke="currentColor"
        strokeWidth="0.6"
        style={{ transform: `translate3d(${px * 14}px, ${py * 14}px, 0)` }}
      >
        <circle cx="120" cy="120" r="100" />
        <ellipse cx="120" cy="120" rx="100" ry="40" />
        <ellipse cx="120" cy="120" rx="40" ry="100" />
        <circle cx="120" cy="120" r="3" fill="currentColor" />
      </svg>

      {/* Header */}
      <header className="relative z-10 border-b border-rule">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="flex h-9 w-9 items-center justify-center rounded-sm border border-ink bg-ink"
            >
              <FlaskConical className="h-5 w-5 text-paper" strokeWidth={1.5} />
            </span>
            <div className="flex flex-col leading-none">
              <span className="font-serif-hero text-[28px] leading-none text-ink">
                Praxis
              </span>
              <span className="mt-1 font-mono-notebook text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                The scientist's instrument
              </span>
            </div>
          </div>
          <span className="hidden font-mono-notebook text-[11px] uppercase tracking-[0.24em] text-muted-foreground sm:inline">
            Praxis · /ˈpraksɪs/ · theory put to practice
          </span>
        </div>
      </header>

      {/* Stage */}
      <main className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-6 py-16 sm:px-10">
        <p
          className="font-mono-notebook text-[13px] uppercase tracking-[0.28em] text-sage animate-in fade-in slide-in-from-bottom-2 duration-700"
        >
          ◆ &nbsp;An instrument for working scientists
        </p>

        <h1
          className="mt-7 max-w-5xl font-serif-hero text-[60px] text-ink animate-in fade-in slide-in-from-bottom-3 duration-700 sm:text-[104px]"
          style={{ animationDelay: "120ms", animationFillMode: "both" }}
        >
          From a <span className="font-serif-accent text-sage">spark</span> of an idea
          <br />
          to a tested{" "}
          <span className="relative inline-block align-baseline">
            <span
              key={wordIdx}
              className="font-serif-accent text-primary animate-in fade-in slide-in-from-bottom-1 duration-500"
              style={{ display: "inline-block" }}
            >
              {WORDS[wordIdx]}
            </span>
          </span>
        </h1>

        <p
          className="mt-8 max-w-2xl text-[19px] leading-[1.7] text-ink-soft animate-in fade-in slide-in-from-bottom-2 duration-700 sm:text-[21px]"
          style={{ animationDelay: "240ms", animationFillMode: "both" }}
        >
          What typically takes weeks — framing, searching, drafting —
          collapsed into{" "}
          <span className="font-serif-accent text-ink">an afternoon</span>.
          Praxis walks beside you from first sketch to a defensible
          experimental plan.
        </p>

        {/* Pillars */}
        <ul
          className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-md border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-4 animate-in fade-in duration-700"
          style={{ animationDelay: "380ms", animationFillMode: "both" }}
        >
          {PILLARS.map((p, i) => (
            <li
              key={p.no}
              className="group/p relative bg-paper-raised p-6 transition-colors duration-300 hover:bg-paper sm:p-7"
            >
              <div className="flex items-baseline justify-between">
                <span className="font-mono-notebook text-[12px] uppercase tracking-[0.24em] text-muted-foreground">
                  {p.no}
                </span>
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 rounded-full bg-rule transition-colors duration-300 group-hover/p:bg-sage"
                />
              </div>
              <h3 className="mt-5 font-serif-card text-[28px] leading-tight text-ink">
                {p.label}
              </h3>
              <p className="mt-3 text-[14px] leading-[1.65] text-ink-soft">
                {p.body}
              </p>
              <span
                aria-hidden
                className="absolute inset-x-0 bottom-0 h-px origin-left scale-x-0 bg-sage transition-transform duration-500 group-hover/p:scale-x-100"
              />
            </li>
          ))}
        </ul>

        {/* CTA — entire page is clickable, this is the visual cue */}
        <div
          className="mt-16 flex flex-col items-start gap-4 animate-in fade-in slide-in-from-bottom-2 duration-700 sm:flex-row sm:items-center sm:justify-between"
          style={{ animationDelay: "520ms", animationFillMode: "both" }}
        >
          <div className="flex items-center gap-4">
            <span className="font-mono-notebook text-[12px] uppercase tracking-[0.24em] text-muted-foreground">
              Click anywhere to begin
            </span>
            <span aria-hidden className="hidden h-px w-16 bg-rule sm:block" />
          </div>

          <div
            className="inline-flex items-center gap-3 rounded-sm border border-ink bg-ink px-7 py-4 text-paper transition-all duration-300 group-hover:gap-5 group-hover:bg-ink/90"
          >
            <span
              className="font-serif-display text-[22px] leading-none"
              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
            >
              Enter the Lab
            </span>
            <ArrowRight
              className="h-5 w-5 transition-transform duration-300 group-hover:translate-x-1"
              strokeWidth={1.5}
            />
          </div>
        </div>
      </main>

      {/* Footer line */}
      <footer className="relative z-10 border-t border-rule">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 font-mono-notebook text-[11px] uppercase tracking-[0.24em] text-muted-foreground sm:px-10">
          <span>Step 00 · Threshold</span>
          <span className="hidden sm:inline">
            Press <span className="text-ink">Enter</span> · Or click any surface
          </span>
          <span>{new Date().getFullYear()}</span>
        </div>
      </footer>
    </div>
  );
};

export default Welcome;

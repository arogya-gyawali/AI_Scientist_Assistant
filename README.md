# AI Scientist Assistant

From a scientific hypothesis to a runnable experiment plan.

A natural-language hypothesis goes in. Out comes a literature novelty check plus an operationally grounded plan: protocol steps with citations, materials, a timeline, validation criteria, and a reviewer-perspective design critique. Built for the [Hack-Nation × Fulcrum Science](https://hack-nation.ai/) Challenge 04.

> **Scope:** Bioscience only — biomedical and life-sciences experiments. Out-of-scope domains (climate, materials science, pure chemistry) are intentionally excluded so prompts, retrieval, and supplier coverage stay focused.

## How it works

Eight stages share a single `ExperimentPlan` document (blackboard pattern). Each stage reads the fields it needs and writes its result back. The UI subscribes to the plan and renders sections as they land.

| Stage | Source | Writes | Status |
|---|---|---|---|
| 1. Lit Review | Europe PMC | `lit_review` | ✅ shipped (incl. per-reference `key_differences`) |
| 2. Protocol | protocols.io (live) | `protocol` | ✅ shipped (multi-agent: architect → writers → roll-up) |
| 3. Materials | protocols.io + Tavily | `materials` | ✅ shipped |
| 4. Budget | Tavily supplier scrape | `budget` | ⏳ pending — type contracts + Tavily helper ready |
| 5. Timeline | derived from steps | `timeline` | ✅ shipped (deterministic, no LLM) |
| 6. Validation | derived from protocol | `validation` | ✅ shipped (criteria, controls, failure modes) |
| 7. Design Critique | LLM reviewer-perspective audit | `critique` | ✅ shipped |
| 8. Summary | LLM final pass | `summary` | ⏳ pending |

Bonus features beyond the eight stages:
- **Protocol PDF download** — formatted, citation-rich PDF rendered server-side ([`protocol_pipeline/pdf.py`](protocol_pipeline/pdf.py), `POST /protocol/pdf`).
- **Researcher candidate-selection flow** — `POST /protocol-candidates` returns ranked protocols.io hits so the user can pick the source before generation locks in.

Full architecture in [`spec/architecture.md`](spec/architecture.md). Type contracts in [`spec/TYPES.md`](spec/TYPES.md). On-disk layout and request lifecycle in [`technical_details.md`](technical_details.md).

## Stack

React + Vite + Tailwind (Lovable scaffold) → Vercel · Flask API · protocols.io REST API (live via [`protocols_client.py`](protocols_client.py)) · Europe PMC · Tavily.

**LLM:** OpenRouter → Gemini 2.5 Flash for **prototyping** (cheap dev iteration), Anthropic direct → Claude Sonnet 4.6 for **production** (demo / quality-sensitive runs, with prompt caching). Switch via `LLM_PROVIDER` in `.env`.

**Plan storage:** JSON files under `plans/` (gitignored). The blackboard is one inspectable document per run. Supabase + pgvector remains the planned upgrade for shared state and embedding search; not in use yet.

## Running it locally

Two terminals:

```bash
# Terminal 1 — Flask backend
python -m flask --app app run --port 5000

# Terminal 2 — Vite frontend
cd frontend && npm install && npm run dev
```

Then visit http://localhost:8080/lab, fill in a hypothesis, walk through `/literature` → `/plan`. End-to-end run is roughly 50–60 s on Gemini Flash.

For Stage 1 alone, a CLI runner is included:

```bash
python run_lr.py inputs/crp.yaml          # one sample
python run_protocol.py inputs/crp.yaml    # Stages 2-3 against the same input
```

Detailed walk-through in [`HOWTO.md`](HOWTO.md).

## Working on this

- **Implementing a stage?** Read the relevant section in [`spec/TYPES.md`](spec/TYPES.md), then open the matching file in [`spec/types/`](spec/types/). The "Stages at a glance" matrix near the top of TYPES.md tells you exactly which fields your stage reads and writes.
- **Orienting?** Read [`spec/architecture.md`](spec/architecture.md) — ~15 min, includes the system diagram. For the on-disk layout, see [`technical_details.md`](technical_details.md).
- **Need a type?** All public types are re-exported from [`spec/types/index.ts`](spec/types/index.ts). Import like `import type { ExperimentPlan } from '@/spec/types'`.
- **Adding a new stage?** Add a new file under `spec/types/`, register a `StageContract` in `spec/types/stage-contracts.ts`, document in `spec/TYPES.md`, then drop a new module under `protocol_pipeline/` (or a sibling pipeline package) plus a Flask endpoint in `app.py`.

## Status

Six of the eight planned stages ship today (Stages 1, 2, 3, 5, 6, 7), plus the protocol-PDF export and the candidate-selection flow. Stage 4 (Budget) and Stage 8 (Summary) are the remaining gaps — both have type contracts in `spec/types/` and (for Budget) the Tavily supplier helper already wired in `src/clients/tavily.py`. The frontend is fully wired to the live API; mock-fallbacks remain in place so the design demo still runs without a backend.

> **Tentative — first-pass data architecture proposal.** Drafted so the team has something concrete to align on. Specifics will likely change as others weigh in.

# AI Scientist Assistant

From a scientific hypothesis to a runnable experiment plan.

A natural-language hypothesis goes in. Out comes a literature novelty check plus an operationally grounded plan: protocol steps, materials with catalog numbers, a budget, a timeline, and a validation strategy. Built for the [Hack-Nation × Fulcrum Science](https://hack-nation.ai/) Challenge 04.

## How it works

Eight stages share a single `ExperimentPlan` document (blackboard pattern). Each stage reads the fields it needs and writes its result back. The UI subscribes to the plan and renders sections as they land.

| Stage | Source | Writes |
|---|---|---|
| 1. Lit Review | Tavily | `lit_review` |
| 2. Protocol | protocols.io | `protocol` |
| 3. Materials | protocols.io + Tavily | `materials` |
| 4. Budget | Tavily supplier scrape | `budget` |
| 5. Timeline | derived from steps | `timeline` |
| 6. Validation | derived from protocol | `validation` |
| 8. Design Critique | LLM reviewer-perspective audit | `critique` |
| 7. Summary | LLM final pass | `summary` |

Full architecture in [`spec/architecture.md`](spec/architecture.md). Type contracts in [`spec/TYPES.md`](spec/TYPES.md).

## Stack

React (via Lovable) → Vercel · Supabase (Postgres + pgvector + edge functions) · OpenRouter (Gemini 2.5 Flash) · protocols.io · Tavily.

## Working on this

- **Implementing a stage?** Read the relevant section in [`spec/TYPES.md`](spec/TYPES.md), then open the matching file in [`spec/types/`](spec/types/). The "Stages at a glance" matrix near the top of TYPES.md tells you exactly which fields your stage reads and writes.
- **Orienting?** Read [`spec/architecture.md`](spec/architecture.md) — ~15 min, includes the system diagram.
- **Need a type?** All public types are re-exported from [`spec/types/index.ts`](spec/types/index.ts). Import like `import type { ExperimentPlan } from '@/spec/types'`.
- **Adding a new stage?** Add a new file under `spec/types/`, register a `StageContract` in `spec/types/stage-contracts.ts`, and document in `spec/TYPES.md`.

## Status

Spec phase. Implementation pending.

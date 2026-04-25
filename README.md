> **Tentative — first-pass data architecture proposal.** Drafted so the team has something concrete to align on. Specifics will likely change as others weigh in.

# AI Scientist Assistant

From a scientific hypothesis to a runnable experiment plan.

A natural-language hypothesis goes in. Out comes a literature novelty check plus an operationally grounded plan: protocol steps, materials with catalog numbers, a budget, a timeline, and a validation strategy. Built for the [Hack-Nation × Fulcrum Science](https://hack-nation.ai/) Challenge 04.

## How it works

Seven stages share a single `ExperimentPlan` document (blackboard pattern). Each stage reads the fields it needs and writes its result back. The UI subscribes to the plan and renders sections as they land.

| Stage | Source | Writes |
|---|---|---|
| 1. Lit Review | Tavily | `lit_review` |
| 2. Protocol | protocols.io | `protocol` |
| 3. Materials | protocols.io + Tavily | `materials` |
| 4. Budget | Tavily supplier scrape | `budget` |
| 5. Timeline | derived from steps | `timeline` |
| 6. Validation | derived from protocol | `validation` |
| 7. Summary | LLM final pass | `summary` |

Full architecture in [`spec/architecture.md`](spec/architecture.md). Type contracts in [`spec/TYPES.md`](spec/TYPES.md).

## Stack

React (via Lovable) → Vercel · Supabase (Postgres + pgvector + edge functions) · OpenRouter (Gemini 2.5 Flash) · protocols.io · Tavily.

## Status

Spec phase. Implementation pending.

# `lit_review_pipeline/`

Stage 1 (Lit Review) — self-contained module.

## What's in here

| File | Purpose |
|---|---|
| `stage.py` | The Stage 1 runner. Reads `hypothesis` from the plan; writes `lit_review`. LLM query rewrite → Tavily search → LLM novelty classification + summary. |
| `tavily_smoke.py` | Standalone script that hits Tavily with pre-baked queries. No LLM. Useful for verifying Tavily integration in isolation. |

## Dependency boundary

This module **only imports from** `src/` (shared types, clients, lib) — no peer-stage imports. That keeps the stage independently containerizable.

```
lit_review_pipeline/
├── stage.py             ─┐
├── tavily_smoke.py      ─┤  imports from
└── __init__.py          ─┘  ↓
                          src/
                          ├── types.py
                          ├── clients/  (tavily, llm)
                          └── lib/      (plan, cache)
```

To containerize Stage 1 as its own service, copy:
1. This folder
2. `src/` (the shared backbone)
3. `requirements.txt`

That's the minimum runnable surface.

## Running

From the repo root (not from inside this folder):

```bash
python -m lit_review_pipeline.tavily_smoke trehalose       # smoke test (Tavily only)
python run.py crp                                          # full Stage 1 (Tavily + LLM)
```

## Tests

Stage 1 tests currently live in [`tests/test_tavily.py`](../tests/test_tavily.py). They cover the Stage 1 sample queries, the cache layer, and the Tavily wrapper params. When other stages add their own pipelines, we'll likely split tests by pipeline directory.

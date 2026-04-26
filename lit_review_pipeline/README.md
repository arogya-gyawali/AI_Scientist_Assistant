# `lit_review_pipeline/`

Stage 1 (Lit Review) — self-contained module.

## Backend (current)

**Europe PMC** for paper retrieval (free, no auth, biomedical-specific). LLM is editorial-only — it judges relevance and writes `description` / `importance` / `matched_on` per chosen reference plus a top-level `signal` / `description` / `summary`. Bibliographic fields (authors, year, journal, abstract, DOI) come straight from Europe PMC; the LLM does not extract them.

History: this stage previously ran on Tavily (snippets didn't surface bibliographic data), then briefly on Semantic Scholar (rate-limited too aggressively without an API key), now on Europe PMC.

## What's in here

| File | Purpose |
|---|---|
| `stage.py` | The Stage 1 runner. Reads `hypothesis` from the plan; writes `lit_review`. LLM query rewrite → Europe PMC search → LLM editorial pass → post-process (HTML strip, summary truncation). |
| `extractors.py` | Belt-and-suspenders fallback: regex extractors for year/DOI/venue and an author-validator. Mostly inert now that Europe PMC provides structured metadata, but still wired in `stage.py` for the rare case EPMC leaves a field null. |
| `europe_pmc_smoke.py` | Standalone script that hits Europe PMC with pre-baked queries. No LLM. Useful for verifying the API works in isolation. |
| `tavily_smoke.py` | Legacy; kept for Stage 3/4 (catalog gap-fill + supplier pricing). Not part of Stage 1 anymore. |

## Dependency boundary

This module **only imports from** `src/` (shared types, clients, lib) — no peer-stage imports. That keeps the stage independently containerizable.

```
lit_review_pipeline/
├── stage.py                  ─┐
├── extractors.py             ─┤  imports from
├── europe_pmc_smoke.py       ─┤    ↓
├── tavily_smoke.py           ─┤  src/
└── __init__.py               ─┘  ├── types.py
                                  ├── clients/   (europe_pmc, tavily, llm)
                                  └── lib/       (plan, cache)
```

To containerize Stage 1 as its own service, copy:
1. This folder
2. `src/` (the shared backbone)
3. `inputs/` (test data)
4. `app.py` and `requirements.txt`

That's the minimum runnable surface.

## Running

From the repo root (not from inside this folder):

```bash
python -m lit_review_pipeline.europe_pmc_smoke trehalose    # smoke test (no LLM)
python run_lr.py crp                                        # full Stage 1 (Europe PMC + LLM)
python app.py                                               # start the Flask API
```

## Tests

Stage 1 tests live in:
- [`tests/test_europe_pmc.py`](../tests/test_europe_pmc.py) — EPMC client request shape, cache reuse, sample-set integrity, live API behavior
- [`tests/test_extractors.py`](../tests/test_extractors.py) — fallback extractors + post-process helpers
- [`tests/test_api.py`](../tests/test_api.py) — Flask endpoint routing and validation
- [`tests/test_tavily.py`](../tests/test_tavily.py) — Stage 3/4 client (kept for when those stages land)

# How to test Stage 1 (Lit Review)

One command, one script.

> **Scope:** This product is limited to **bioscience** experiments — biomedical, life-sciences, microbiology, etc. The Tavily search prompts and LLM classification are tuned for that domain. Out-of-scope topics (climate, materials, pure-chemistry) won't get useful output.

## One-time setup

```bash
# from the repo root
python -m venv .venv
source .venv/Scripts/activate         # Windows bash / Git Bash
# .venv\Scripts\activate              # Windows cmd / PowerShell
# source .venv/bin/activate           # macOS / Linux

pip install -r requirements.txt
```

Make sure `.env` exists with your keys filled in (copy from `.env.example` if you haven't).

## Run

```bash
# Default: trehalose sample, full pipeline (Tavily + LLM)
python run.py

# Different sample
python run.py crp
python run.py lactobacillus

# Tavily-only smoke test (no LLM, no LLM credit burn)
python run.py --tavily-only
python run.py crp --tavily-only

# Run all bioscience samples end-to-end
python run.py --all

# Also dump raw Tavily JSON (useful for tuning the classification prompt)
python run.py --raw
```

## What it does

1. **Loads `.env`** and validates `TAVILY_API_KEY` + the LLM key for whichever provider `LLM_PROVIDER` is set to.
2. **Tavily smoke test** — fires a pre-baked query (no LLM rewrite) so you can see Tavily working in isolation.
3. **Full Stage 1 pipeline** (skipped if `--tavily-only`):
   - LLM rewrites the structured hypothesis into a search query
   - Tavily search (cached for 7 days)
   - LLM classifies novelty + selects 1-3 references
   - Writes a `LitReviewSession` to `ExperimentPlan.lit_review`
   - Saves the plan JSON to `plans/plan_<id>.json`

## Costs per run (full pipeline)

- **Tavily:** 1 advanced search = ~2 credits. First run only; subsequent runs hit the file cache.
- **LLM:** 2 calls per sample (query rewrite + classification). On Gemini 2.5 Flash via OpenRouter, ~$0.001 per sample. Practically free.

## Output

A JSON file at `plans/plan_<id>.json` containing the full `ExperimentPlan` blackboard. Inspect with:

```bash
cat plans/plan_*.json | jq .lit_review
cat plans/plan_*.json | jq .status
```

Re-runs build a new plan each time. Old plan JSONs accumulate in `plans/` (gitignored).

## Repo layout

```
src/                       ← shared backbone (used by every stage)
├── types.py
├── cli.py
├── clients/  (tavily, llm)
└── lib/      (plan, cache)

lit_review_pipeline/       ← Stage 1, self-contained
├── stage.py               ← the Stage 1 runner
├── tavily_smoke.py        ← Tavily-only smoke test
└── README.md              ← what's in this folder + containerization note

inputs/                    ← sample hypothesis YAMLs (shared test data)
tests/                     ← pytest suite
spec/                      ← TS types, JSON schema, architecture docs
run.py                     ← single-command Stage 1 runner
```

To **containerize** Stage 1 as a standalone service, copy `src/`, `lit_review_pipeline/`, `inputs/`, and `requirements.txt`. That's the minimum runnable surface.

## Tests

```bash
# All tests (live tests skipped if TAVILY_API_KEY isn't set)
pytest

# Skip live integration tests (CI / no creds)
pytest -m "not live"

# Only the live integration tests
pytest -m live -v

# Verbose, show print output
pytest -v -s
```

Test layout:

| Test class | What it covers | Network? |
|---|---|---|
| `TestCacheLayer` | File cache round-trips, TTL expiry, namespace isolation | no |
| `TestLitReviewWrapper` | Stage 1 search params (advanced depth, include_answer, no `days`, max_results=5, cache reuse) | no (mocked) |
| `TestSupplierGapFillWrapper` | Stage 3 supplier-domain scoping + basic depth | no (mocked) |
| `TestPricingWrapper` | Stage 4 single-vendor scoping + raw content for price extraction | no (mocked) |
| `TestErrorPaths` | Missing API key → friendly error | no |
| `TestSampleQueries` | Sample set is bioscience-only, no climate sample, no recency hints | no |
| `TestLiveTavily` | Real Tavily calls return useful, topically-relevant results | yes (live) |

Cache is redirected to a temp dir for the test session — running tests does not pollute the real `.cache/`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Missing env vars in .env` | Forgot to copy `.env.example` to `.env` or fill in a key |
| `TAVILY_API_KEY is not set` despite `.env` having it | `.env` not at repo root, or running from wrong directory — must be run from repo root |
| LLM JSON parse error | Model returned non-JSON despite the prompt; rerun, or temporarily set `LLM_PROVIDER=anthropic` for stricter output |
| Tavily 429 (rate limit) | Cache should prevent this, but if you blow through `.cache/tavily/` then back off |

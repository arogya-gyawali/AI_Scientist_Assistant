# Running the AI Scientist Assistant locally

CLI runners for each backend stage, plus the Flask API the frontend talks to.

> **Scope:** This product is limited to **bioscience** experiments — biomedical, life-sciences, microbiology, etc. Out-of-scope topics (climate, materials, pure chemistry) won't get useful output because the literature backend is biomedical-specific.

## Current backend (source of truth)

| Concern | Current implementation | Notes |
|---|---|---|
| **Stage 1 lit search** | **Europe PMC** | Free, no auth. ~40M biomedical papers. Returns structured authors, year, journal, plain-text abstract, DOI. No LLM extraction needed for fact fields. |
| **Stage 2 protocol source** | **protocols.io REST API (live)** via [`protocols_client.py`](protocols_client.py) | Multi-query fan-out + relevance filter; falls back to the cached samples in `pipeline_output_samples/protocols_io/` when offline. |
| **Stage 3 catalog gap-fill** | **Tavily** scoped to 7 supplier domains | `src/clients/tavily.py` :: `search_for_supplier`. 30-day cache. |
| **Stage 4 supplier pricing** | Tavily (planned) | Pricing TTL constant + supplier search exist; no `protocol_pipeline/budget.py` yet. |
| **Stages 5-7** | Pure-LLM (Gemini Flash) with deterministic compute where possible | `timeline.py` is fully deterministic; `validation.py` and `critique.py` use one LLM call each. |
| LLM (prototyping) | OpenRouter → `google/gemini-2.5-flash` | Day-to-day dev. Set `LLM_PROVIDER=openrouter` (default). |
| LLM (production) | Anthropic direct → `claude-sonnet-4-6` | Set `LLM_PROVIDER=anthropic`. Uses prompt caching for the protocols.io context re-used across stages. |
| Caching | File cache under `.cache/` (per-source subdirs) | 7-day TTL for lit-review, 30-day for catalog gap-fill, 24h for pricing. Re-runs are free. |

**Stage 1 has gone through three backends.** History (most recent first): Europe PMC (current) ← Semantic Scholar (rate-limited too aggressively without a key) ← Tavily (snippets didn't surface bibliographic metadata, forcing LLM extraction and hallucinated authors). The Europe PMC swap eliminated the entire fact-extraction layer.

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

> Stage 1 does **not** require a Europe PMC key. If you set the optional `TAVILY_API_KEY` you also unlock the Stage 3/4 client (not yet wired into a runner).

## Run the CLI test harness

```bash
# Default: trehalose sample, full pipeline (Europe PMC + LLM)
python run_lr.py

# Different sample
python run_lr.py crp
python run_lr.py lactobacillus

# Tavily-only smoke test (legacy; not part of Stage 1 anymore — kept for Stage 3/4 pre-flight)
python run_lr.py --tavily-only
python run_lr.py crp --tavily-only

# Run all bioscience samples end-to-end
python run_lr.py --all

# Also dump raw smoke-test JSON (useful for tuning)
python run_lr.py --raw
```

## What it does

1. **Loads `.env`** and validates the LLM key for whichever provider `LLM_PROVIDER` is set to.
2. **Pre-flight smoke test** — fires a pre-baked Tavily query (legacy harness; doesn't reflect the real Stage 1 path anymore — it'll move to a Europe PMC smoke when we get to it).
3. **Full Stage 1 pipeline** (skipped if `--tavily-only`):
   - LLM rewrites the structured hypothesis into a Europe PMC search query
   - Europe PMC search (cached for 7 days)
   - LLM editorial pass: classifies novelty + selects 1–3 references with `description` / `importance` / `matched_on` / `relevance_score`
   - Post-process: HTML strip on titles, summary truncation to 4 sentences
   - Writes a `LitReviewSession` to `ExperimentPlan.lit_review`
   - Saves the plan JSON to `plans/plan_<id>.json`

## Costs per run (full pipeline)

- **Europe PMC:** free, no key, no per-call cost. Cached for 7 days.
- **LLM:** ~3 calls per sample (query rewrite + classification, occasional retry). On Gemini 2.5 Flash via OpenRouter, ~$0.001 per sample. Practically free.

## Output

A JSON file at `plans/plan_<id>.json` containing the full `ExperimentPlan` blackboard. Inspect with:

```bash
cat plans/plan_*.json | jq .lit_review
cat plans/plan_*.json | jq .status
```

Re-runs build a new plan each time. Old plan JSONs accumulate in `plans/` (gitignored).

For frontend integration, the most recent successful runs are also mirrored into [`pipeline_output_samples/`](pipeline_output_samples/) — those are the canonical fixtures for FE work.

## API server (for the frontend)

A Flask app exposes every shipped stage over HTTP. The React frontend (under `frontend/`) calls these directly through a Vite dev proxy.

```bash
# dev
python -m flask --app app run --port 5000
# or:
python app.py
# server on http://127.0.0.1:5000
```

Endpoints:

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/health` | — | `{"ok": true, ...}` |
| `POST` | `/lit-review` | `{"structured": {...}, "domain": "..."}` (see below) | `LitReviewOutput` + `plan_id` |
| `POST` | `/protocol-candidates` | `{"plan_id": "..."}` or `{"structured": {...}}` | Ranked protocols.io candidates for researcher review |
| `POST` | `/protocol` | `{"plan_id": "..."}` or `{"structured": {...}, "candidate_ids": [...]}` | `frontend_view` + raw `ProtocolGenerationOutput` |
| `POST` | `/protocol/pdf` | `{"plan_id": "..."}` | PDF stream of the protocol |
| `POST` | `/materials` | `{"plan_id": "..."}` | `frontend_view` + raw `MaterialsOutput` |
| `POST` | `/timeline` | `{"plan_id": "..."}` | `TimelineOutput` (deterministic) |
| `POST` | `/validation` | `{"plan_id": "..."}` | `ValidationOutput` |
| `POST` | `/critique` | `{"plan_id": "..."}` | `DesignCritique` |

Stage 4 (`/budget`) and Stage 8 (`/summary`) are not yet exposed.

Sample request:

```bash
curl -X POST http://127.0.0.1:5000/lit-review \
  -H "Content-Type: application/json" \
  -d '{
    "structured": {
      "research_question": "Does trehalose improve HeLa post-thaw viability vs DMSO?",
      "subject": "HeLa cells",
      "independent": "Cryoprotectant identity",
      "dependent": "Post-thaw viability",
      "conditions": "Slow freeze, LN2, rapid thaw, trypan blue",
      "expected": ">=15 percentage point increase"
    },
    "domain": "cell_biology"
  }'
```

Errors:
- `400 request_body_required` — body wasn't JSON
- `422 validation_error` — `structured` fields missing or malformed; `detail[]` has Pydantic field errors
- `500 pipeline_error` — LLM or Europe PMC failure

CORS is enabled for any origin so the FE dev server / Vercel preview can hit it directly.

## Repo layout

```
src/                              ← shared backbone (used by every stage)
├── types.py                      ← Pydantic models (ExperimentPlan, …)
├── cli.py                        ← legacy CLI wrapper (still works)
├── clients/
│   ├── europe_pmc.py             ← Stage 1 lit search
│   ├── tavily.py                 ← Stage 3 catalog gap-fill, Stage 4 pricing (planned)
│   └── llm.py                    ← OpenRouter / Anthropic abstraction
└── lib/
    ├── plan.py                   ← create / save / load ExperimentPlan
    └── cache.py                  ← shared file cache

protocols_client.py               ← live protocols.io REST client (Stage 2 source)

lit_review_pipeline/              ← Stage 1, self-contained
├── stage.py
├── extractors.py
├── europe_pmc_smoke.py
└── tavily_smoke.py               ← legacy smoke kept for Stage 3/4 pre-flight

protocol_pipeline/                ← Stages 2, 3, 5, 6, 7 (multi-agent)
├── stage.py                      ← orchestrator
├── sources.py                    ← protocols.io loader (live + sample fallback)
├── relevance.py                  ← drops obviously off-target sources
├── architect.py                  ← procedure outline (1 LLM call)
├── writer.py                     ← per-procedure writer (parallel fan-out)
├── materials.py                  ← Stage 3 — roll-up agent
├── timeline.py                   ← Stage 5 — deterministic phase compute
├── validation.py                 ← Stage 6 — criteria + failure modes
├── critique.py                   ← Stage 7 — reviewer-perspective audit
├── pdf.py                        ← protocol PDF renderer
└── frontend_view.py              ← rich Pydantic → FE-shape adapter

inputs/                           ← sample hypothesis YAMLs (shared test data)
tests/                            ← pytest suite
pipeline_output_samples/          ← canonical pipeline outputs for FE fixtures
plans/                            ← gitignored runtime ExperimentPlan dumps
spec/                             ← TS types, JSON schema, architecture docs
frontend/                         ← React SPA (Vite + TS + Tailwind)
app.py                            ← Flask API server (all endpoints)
run_lr.py                         ← Stage 1 CLI runner
run_protocol.py                   ← Stages 2-3 CLI runner
```

To **containerize** Stage 1 as a standalone service, copy `src/`, `lit_review_pipeline/`, `inputs/`, `requirements.txt`, and `app.py`. That's the minimum runnable surface.

## Tests

```bash
# All unit tests (skip live integration; safe for CI)
pytest -m "not live"

# Including live integration tests (hits Europe PMC for real)
pytest

# Only the live integration suite
pytest -m live -v

# Verbose, show print output
pytest -v -s
```

Test layout:

| File | What it covers | Network? |
|---|---|---|
| `tests/test_europe_pmc.py` | EPMC client request shape, cache reuse, sample-set integrity, live API behavior | yes (live tests gated on `@live` marker) |
| `tests/test_tavily.py` | Stage 3/4 Tavily wrapper params, cache, error paths | yes (gated) |
| `tests/test_extractors.py` | Year/DOI/venue regex, author validation, `_clean_text`, `_truncate_to_n_sentences` | no |
| `tests/test_api.py` | Flask `/health` and `/lit-review` routing, validation errors, pipeline errors (Stage 1 runner monkey-patched) | no |

Cache is redirected to a temp dir for the test session — running tests does not pollute the real `.cache/`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Missing env vars in .env` | Forgot to copy `.env.example` to `.env` or fill in a key |
| `OPENROUTER_API_KEY is not set` despite `.env` having it | `.env` not at repo root, or running from wrong directory — must be run from repo root |
| LLM JSON parse error | Model returned non-JSON despite the prompt; the runner retries once. If still failing, set `LLM_PROVIDER=anthropic` for stricter output. |
| Europe PMC 429 (rate limit) | Cache should prevent this; if you genuinely blow through, wait ~30s. Europe PMC has no published hard limit but throttles bursts. |
| Encoding error on stdout | Run with `PYTHONIOENCODING=utf-8` (Windows console default is cp1252; `run_lr.py` and `app.py` already force UTF-8 for their own streams). |

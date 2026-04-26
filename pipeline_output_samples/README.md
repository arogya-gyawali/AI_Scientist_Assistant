# Pipeline output samples

Real `LitReviewOutput` JSON from `python run_lr.py <sample>` runs. **For frontend integration — build your card UI against these as fixtures.**

| File | Sample hypothesis | Signal |
|---|---|---|
| [`crp.json`](crp.json) | CRP biosensor for whole blood (diagnostics) | `similar_work_exists` |
| [`trehalose.json`](trehalose.json) | Trehalose vs DMSO HeLa cryopreservation (cell biology) | `similar_work_exists` |
| [`lactobacillus.json`](lactobacillus.json) | LGG and intestinal permeability in mice (gut health) | `similar_work_exists` |

Source input YAMLs in [`../inputs/`](../inputs/).
Backend: **Europe PMC** for paper retrieval; LLM (Gemini 2.5 Flash via OpenRouter) for the editorial layer.

## Sanity check

### ✅ Working well

- **`signal` enum**: valid `similar_work_exists` on all three plausibly-precedented research questions.
- **Top-level `description`**: 2–3 sentences explaining the signal candidly.
- **Top-level `summary`**: 3–4 sentences, holistic wrap-up; the strict prompt is holding.
- **Bibliographic fields populated 9/9 across all three samples**:
  - `authors` — structured arrays straight from Europe PMC's AuthorList.
  - `year` — every ref has a `pubYear`.
  - `venue` — real journal names (`"Clinical Nutrition"`, `"PLoS ONE"`, `"Biosensors"`, etc.).
  - `doi` — every ref carries a DOI.
  - `snippet` — full plain-text abstracts straight from Europe PMC.
- **`matched_on` chips**: 3–6 short concept tags per reference, ready for chip-style UI rendering.
- **`description` (neutral) vs `importance` (relational)**: distinct in tone — `description` stays factual about the paper; `importance` ties back to the user's hypothesis.
- **`relevance_score`**: 0.80–0.95 range, declining order, sensible.

### ❌ Known caveats

- **Bare `LitReviewOutput`, no `LitReviewSession` envelope** — these JSONs are just the inner result. The full session shape (`chat_history`, `cached_search_context`, `user_decision`) lives in [`spec/types/lit-review.ts`](../spec/types/lit-review.ts) but isn't wrapped on the CLI side yet. FE can build against the inner shape and we'll add the envelope when conversational follow-ups land.
- **`source` field** is `"europe_pmc"` (was `"paper"` in earlier Tavily-era runs). Don't assume the value when filtering or routing in UI.
- **Long Unicode** (μ, ±, °C, em-dashes) appears in abstracts. UI must be UTF-8 throughout.

## Use as fixtures

In React/TS:

```ts
import crpFixture from "@/pipeline_output_samples/crp.json";
import type { LitReviewOutput } from "@/spec/types/lit-review";

const data = crpFixture as LitReviewOutput;
```

Validate against the JSON Schema before relying on the shape:

```ts
import Ajv from "ajv";
import schema from "@/spec/schemas/experiment-plan.schema.json";

const validate = new Ajv().compile(schema.definitions.LitReviewOutput);
console.log(validate(crpFixture), validate.errors);
```

## Refreshing samples

```bash
python run_lr.py --all                # regenerate all three
# JSONs are auto-copied from the latest plan into pipeline_output_samples/
```

If you want to rerun and update by hand:

```bash
python run_lr.py crp                  # one sample
cp plans/plan_<id>.json pipeline_output_samples/crp.json
```

# Pipeline output samples

Real `LitReviewOutput` JSON from `python run.py <sample>` runs. **For frontend integration — build your card UI against these as fixtures.**

| File | Sample hypothesis | Signal |
|---|---|---|
| [`crp.json`](crp.json) | CRP biosensor for whole blood (diagnostics) | `similar_work_exists` |
| [`trehalose.json`](trehalose.json) | Trehalose vs DMSO HeLa cryopreservation (cell biology) | `similar_work_exists` |
| [`lactobacillus.json`](lactobacillus.json) | LGG and intestinal permeability in mice (gut health) | `similar_work_exists` |

Source input YAMLs in [`../inputs/`](../inputs/).

## Sanity check (what's good, what's flaky)

### ✅ Working well
- **`signal` enum**: all three return valid `similar_work_exists` for plausibly-precedented research questions.
- **Top-level `description`**: 2–3 sentences, candid about precedent and gaps.
- **Top-level `summary`**: 3–4 sentences, holistic, hits novelty + literature + actionable framing for the researcher (the strict prompt is holding).
- **`matched_on` chips**: 3–6 short concept tags per reference, mapping cleanly to the UI mockup. Within target.
- **Reference-level `description` (neutral) vs `importance` (relational)**: distinct in tone — descriptions stay factual about the paper, importance ties back to the hypothesis. The two-field separation works.
- **`relevance_score`**: 0.80–0.95 range, declining order, sensible.

### ⚠️ Inconsistent / partial
- **`authors`**: works well for `lactobacillus.json` (full author lists), empty arrays in `trehalose.json` and `crp.json`. The LLM doesn't reliably extract authors from Tavily content when the snippet doesn't surface them. **UI should handle empty author arrays gracefully** — render as empty string or omit the row.
- **`year`**: populated for some refs, `null` for others. Same root cause. UI should show "n/a" or hide if `null`.
- **`venue`**: sometimes the journal name (`"Clinical Nutrition"`, `"PLoS ONE"`, `"Frontiers in Microbiology"`), sometimes a domain (`"academia.edu"`, `"Dergipark"`, `"PMC"`). The latter is wrong — `PMC` is a host, not a venue. Worth a future prompt tweak; for now UI should render whatever's there.
- **`doi`**: `null` across all three. Tavily content rarely surfaces DOIs cleanly. Click-through should use `url` instead of building a DOI link.

### ❌ Known gaps
- **No `LitReviewSession` envelope** — these are bare `LitReviewOutput` objects. The full session shape (with `chat_history`, `cached_tavily_context`, `user_decision`) is in [`spec/types/lit-review.ts`](../spec/types/lit-review.ts) but not yet wrapped on the CLI side. FE can build against the inner shape and add the envelope when conversational follow-ups land.
- **Snippets contain mid-sentence ellipses (`[...]`)** — they're truncated by Tavily. Render with care (don't double-truncate).
- **Long Unicode** (μ, ±, − minus signs, °C) appears in snippets. UI must be UTF-8 throughout.

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
python run.py --all                # regenerate all three
cp plans/plan_*.json pipeline_output_samples/<sample>.json
```

(Or just rerun a single sample and copy.)

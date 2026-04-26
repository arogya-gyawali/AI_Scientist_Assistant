# Sample inputs

YAML hypothesis files for end-to-end testing. **Scope: bioscience only.** This product is limited to biomedical and life-sciences experiments — cell biology, diagnostics, microbiology / gut health, immunology, neuroscience, etc. Domains outside biology (chemistry-only, climate, materials science) are explicitly out of scope.

| File | Domain | Hypothesis (1-line gist) |
|---|---|---|
| [`trehalose.yaml`](trehalose.yaml) | `cell_biology` | Trehalose substitution vs DMSO improves HeLa post-thaw viability |
| [`crp.yaml`](crp.yaml) | `diagnostics` | Paper-based electrochemical biosensor detects CRP from whole blood |
| [`lactobacillus.yaml`](lactobacillus.yaml) | `gut_health` | L. rhamnosus GG reduces intestinal permeability in C57BL/6 mice |

## Schema

Every input file matches this shape (validated against `StructuredHypothesis` in `src/types.py`):

```yaml
domain: <string>           # 'cell_biology' | 'diagnostics' | 'gut_health' | 'microbiology' | 'immunology' | etc.

structured:
  research_question: |     # The question being asked, in plain English
  subject: |               # Organism, cell line, or biological system being studied
  independent: |           # The variable being manipulated
  dependent: |             # The variable being measured
  conditions: |            # Experimental setup, controls, sample sizes, equipment
  expected: |              # Hypothesized outcome with magnitude
```

## Running

End-to-end (with LLM):

```bash
python -m src.cli inputs/trehalose.yaml
```

Tavily-only smoke test (no LLM, pre-baked queries):

```bash
python -m lit_review_pipeline.tavily_smoke              # all bioscience samples
python -m lit_review_pipeline.tavily_smoke trehalose    # just one
python -m lit_review_pipeline.tavily_smoke --raw        # full JSON
```

"""Adapter that projects the rich Stage 2 / Stage 3 outputs onto the
shape the existing React `ExperimentPlan.tsx` page consumes.

The FE was built against a hardcoded mock with a flatter, simpler shape
than the pipeline emits:

  Backend                                       →  Frontend (ExperimentPlan.tsx)
  --------------------------------------------     ----------------------------
  procedures[].steps[] (rich, with params,       →  flat ProtocolStep[] with
    deviations, success_criteria, todos)            {title, detail, citation?,
                                                     phase, meta?}
  materials[] flat with category field           →  MaterialGroup[] grouped by
                                                     {group, description, items}
                                                   each item: {name, purpose,
                                                     supplier, catalog, qty,
                                                     qtyContext?, note?}

This module owns the projection so:
  - API endpoints can return BOTH the rich shape and the FE shape (FE
    upgrades later don't require BE changes).
  - The drift is documented in one place.
  - Tests can pin the mapping down without spinning up the live LLMs.

Two fields the FE renders that we don't have first-class data for yet:
  - phase: derived heuristically from procedure name keywords
    ("preparation"/"setup" → Preparation, "harvest"/"freeze"/"treatment"
    → Experiment, "viability"/"assay"/"measurement"/"ELISA" → Measurement,
    "analysis"/"statistical"/"comparison" → Analysis). Falls back to
    "Experiment" if nothing matches.
  - supplier/catalog: emitted as the literal placeholder string "TBD".
    Stage 4 (Budget) will backfill these with real supplier lookups.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.types import (
    Deviation,
    Material,
    MaterialsOutput,
    Procedure,
    ProcedureSuccessCriterion,
    ProtocolGenerationOutput,
    ProtocolStep,
    ReagentRecipe,
    StepParams,
)


# --------------------------------------------------------------------------
# Output shapes (mirror the TypeScript types in
# frontend/src/lib/api.ts and frontend/src/pages/ExperimentPlan.tsx)
# --------------------------------------------------------------------------

Phase = Literal["Preparation", "Experiment", "Measurement", "Analysis"]


class FEReagentRecipe(BaseModel):
    """How to mix a custom buffer the researcher prepares themselves."""
    name: str
    components: list[str]
    notes: Optional[str] = None


class FEProtocolStep(BaseModel):
    """The shape ExperimentPlan.tsx renders one row from. Most fields are
    direct projections of ProtocolStep with FE-friendly formatting:
      - `detail` is `body_md` renamed
      - `meta` is the FIRST-priority structured param formatted as a chip
      - `params_summary` is ALL params formatted, in priority order,
        for the parameters table the FE wants to render under the body
      - procedure_name + step_number_in_procedure power "2.1.3" numbering
        without the FE having to re-derive it"""
    title: str
    detail: str
    citation: Optional[str] = None
    phase: Phase
    meta: Optional[str] = None              # first-priority param chip
    # New fields (Phase 2/3+ rendering):
    params_summary: list[str] = Field(default_factory=list)   # ["10 mL", "37 °C", "5 min"]
    equipment: list[str] = Field(default_factory=list)        # mirror of step.equipment_needed
    reagents: list[str] = Field(default_factory=list)         # mirror of step.reagents_referenced
    todos: list[str] = Field(default_factory=list)            # mirror of step.todo_for_researcher
    is_critical: bool = False
    is_pause_point: bool = False
    anticipated_outcome: Optional[str] = None
    troubleshooting: list[str] = Field(default_factory=list)
    reagent_recipes: list[FEReagentRecipe] = Field(default_factory=list)
    duration: Optional[str] = None          # raw ISO 8601, FE formats for display
    procedure_name: str = ""                # which procedure this step belongs to
    step_number_in_procedure: int = 0       # 1-based; for "2.1.3"-style numbering
    step_id: str = ""                       # stable ID for cross-linking from materials


class FEDeviation(BaseModel):
    """An adaptation the LLM made from the source. FE renders these in a
    collapsible audit panel per procedure — this is our killer feature."""
    from_source: str
    to_adapted: str
    reason: str
    source_protocol_id: str
    confidence: Literal["low", "medium", "high"]


class FESuccessCriterion(BaseModel):
    """Per-procedure pass/fail or quantitative criterion."""
    what: str
    how_measured: str
    threshold: Optional[str] = None
    pass_fail: bool = True


class FEProcedureGroup(BaseModel):
    """The FE primary view: procedures grouped, each with its own steps,
    deviations, success criteria, and total time. Keeps the audit info
    contained per-procedure rather than spread across a flat step list."""
    name: str
    intent: str
    steps: list[FEProtocolStep]
    deviations_from_source: list[FEDeviation] = Field(default_factory=list)
    success_criteria: list[FESuccessCriterion] = Field(default_factory=list)
    total_duration: Optional[str] = None
    procedure_index: int                                       # 1-based, for "2.1.3" numbering
    source_protocol_ids: list[str] = Field(default_factory=list)


class FEReagent(BaseModel):
    name: str
    purpose: str
    supplier: Optional[str] = "TBD"
    catalog: Optional[str] = "TBD"
    qty: str
    qtyContext: Optional[str] = None
    note: Optional[dict] = None  # {kind: "cold"|"lead", text: string}
    # New: where this material is referenced. Powers FE back-links from
    # the materials list to the steps that use it ("Used in 2.1, 3.4").
    used_in_steps: list[str] = Field(default_factory=list)
    material_id: str = ""
    # Tavily enrichment (best-effort). Populated by
    # protocol_pipeline.materials_enrichment after adapt_materials.
    # `source_url` is REQUIRED for the FE to render any enriched
    # field — without it, the value isn't auditable so we treat it
    # as if the lookup failed (drop the price/supplier/catalog).
    price: Optional[str] = None        # e.g. "$45 / 500g"
    source_url: Optional[str] = None   # supplier page where the data was found


class FEMaterialGroup(BaseModel):
    group: str
    description: str
    items: list[FEReagent]


class FEProtocolView(BaseModel):
    """What POST /protocol returns to the FE alongside the raw rich shape."""
    # Existing flat-list view — kept for backward compatibility with the
    # mock-fallback path in ExperimentPlan.tsx; the FE detects which view
    # to render based on whether `procedures` is populated.
    steps: list[FEProtocolStep]
    experiment_type: str
    total_steps: int
    cited_protocols: list[dict] = Field(default_factory=list)
    # New primary view: grouped by procedure with per-procedure metadata.
    procedures: list[FEProcedureGroup] = Field(default_factory=list)
    total_duration: Optional[str] = None    # protocol-wide ISO 8601 sum
    assumptions: list[str] = Field(default_factory=list)


class FEMaterialsView(BaseModel):
    """What POST /materials returns to the FE."""
    groups: list[FEMaterialGroup]
    total_unique_items: int
    gaps: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Phase classification — heuristic on procedure name + intent
# --------------------------------------------------------------------------

# Stems chosen so we catch inflections (freez → freezing/freezer/freeze;
# thaw → thawing/thawed). Order = priority: Measurement first (most
# specific), then Analysis, then Experiment (concrete actions), and
# Preparation is the catch-all for setup/prep work. We match against the
# procedure NAME ONLY — including the intent caused false positives
# because intents like "...maintain culture..." dragged Experiment work
# into Preparation.
_PHASE_RULES: list[tuple[Phase, tuple[str, ...]]] = [
    ("Measurement", (
        "measurement", "measure", "assay", "elisa", "western", "imaging",
        "viability", "quantif", "spectroph", "fluoresc", "absorbance",
        "detection", "od600", "cell counting", "trypan", "readout",
    )),
    ("Analysis", (
        "data analysis", "statistical", "statistics", "anova", "regression",
        "curve fit", "lod", "performance comparison", "data processing",
    )),
    ("Experiment", (
        "harvest", "treatment", "intervention", "freez", "thaw",
        "incubat", "challenge", "spike", "exposure", "infection",
        "supplement", "gavage", "cryopreserv", "dissection",
        "transfection", "induction", "stimulation",
    )),
    ("Preparation", (
        "preparation", "fabricat", "functionaliz", "calibration",
        "standard curve", "biosensor fabricat", "stock", "media",
        "setup", "set up",
    )),
]


def classify_phase(procedure: Procedure) -> Phase:
    """Map a procedure to the FE's 4-phase enum via keyword heuristic on
    the procedure NAME (not intent — intent prose drags in false
    positives like "in culture" → Preparation). Default: 'Experiment'
    (the bulk of typical lab work). Architect names are descriptive
    enough that the name-only heuristic catches the common cases."""
    name = procedure.name.lower()
    for phase, keywords in _PHASE_RULES:
        if any(kw in name for kw in keywords):
            return phase
    return "Experiment"


# --------------------------------------------------------------------------
# Step adaptation
# --------------------------------------------------------------------------

def _format_meta(params: StepParams) -> Optional[str]:
    """Compact tag the FE shows next to each step. Pick the first
    "interesting" param: temperature > volume > duration > concentration >
    speed. Returns None if no params set."""
    summary = _format_params_summary(params)
    return summary[0] if summary else None


def _format_params_summary(params: StepParams) -> list[str]:
    """ALL set params formatted as compact strings, in priority order:
    temperature → volume → duration → concentration → speed. Powers the
    FE's per-step parameters table (alongside `meta` which is just the
    first element of this list)."""
    out: list[str] = []
    if params.temperature:
        out.append(f"{_fmt_num(params.temperature.value)} {params.temperature.unit}")
    if params.volume:
        out.append(f"{_fmt_num(params.volume.value)} {params.volume.unit}")
    if params.duration:
        out.append(_humanize_duration(params.duration))
    if params.concentration:
        out.append(f"{_fmt_num(params.concentration.value)} {params.concentration.unit}")
    if params.speed:
        out.append(f"{_fmt_num(params.speed.value)} {params.speed.unit}")
    return out


def _fmt_num(v: float) -> str:
    """Drop trailing .0 for whole numbers (e.g. 37.0 → 37, but 1.5 stays)."""
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def _humanize_duration(iso: str) -> str:
    """Best-effort ISO-8601 duration → short label (PT5M → 5 min, P1D →
    1 day). Falls back to the raw ISO string if it doesn't match the
    common shapes."""
    s = iso.strip()
    if s.startswith("PT") and s.endswith("M"):
        return f"{s[2:-1]} min"
    if s.startswith("PT") and s.endswith("H"):
        return f"{s[2:-1]} h"
    if s.startswith("PT") and s.endswith("S"):
        return f"{s[2:-1]} s"
    if s.startswith("P") and s.endswith("D") and "T" not in s:
        return f"{s[1:-1]} d"
    if s.startswith("P") and s.endswith("W") and "T" not in s:
        return f"{s[1:-1]} wk"
    return s


def _step_citation(step: ProtocolStep, procedure: Procedure) -> Optional[str]:
    """The FE citation field is a short string. Prefer DOI; fall back to
    the first source_protocol_id of the procedure (a protocols.io ID)."""
    if step.cited_doi:
        return f"doi:{step.cited_doi}"
    if procedure.source_protocol_ids:
        return f"protocols.io/{procedure.source_protocol_ids[0]}"
    return None


def _adapt_step(
    step: ProtocolStep,
    proc: Procedure,
    *,
    phase: Phase,
    procedure_name: str,
    procedure_index: int,
    step_number_in_procedure: int,
) -> FEProtocolStep:
    """Project a single ProtocolStep into the FE shape with all the new
    rich fields populated."""
    params_summary = _format_params_summary(step.params)
    # Stable step ID: "p{proc_idx}-s{step_idx}". Used for cross-linking
    # from materials to steps. Independent of step.n which gets renumbered
    # globally in the flat view.
    step_id = f"p{procedure_index}-s{step_number_in_procedure}"
    return FEProtocolStep(
        title=step.title,
        detail=step.body_md,
        citation=_step_citation(step, proc),
        phase=phase,
        meta=params_summary[0] if params_summary else None,
        params_summary=params_summary,
        equipment=list(step.equipment_needed),
        reagents=list(step.reagents_referenced),
        todos=list(step.todo_for_researcher),
        is_critical=step.is_critical,
        is_pause_point=step.is_pause_point,
        anticipated_outcome=step.anticipated_outcome,
        troubleshooting=list(step.troubleshooting),
        reagent_recipes=[
            FEReagentRecipe(
                name=r.name,
                components=list(r.components),
                notes=r.notes,
            ) for r in step.reagent_recipes
        ],
        duration=step.duration,
        procedure_name=procedure_name,
        step_number_in_procedure=step_number_in_procedure,
        step_id=step_id,
    )


def _adapt_deviation(d: Deviation) -> FEDeviation:
    return FEDeviation(
        from_source=d.from_source,
        to_adapted=d.to_adapted,
        reason=d.reason,
        source_protocol_id=d.source_protocol_id,
        confidence=d.confidence,
    )


def _adapt_success_criterion(c: ProcedureSuccessCriterion) -> FESuccessCriterion:
    return FESuccessCriterion(
        what=c.what,
        how_measured=c.how_measured,
        threshold=c.threshold,
        pass_fail=c.pass_fail,
    )


def adapt_protocol(protocol: ProtocolGenerationOutput) -> FEProtocolView:
    """Project a ProtocolGenerationOutput into both the flat-list shape
    (backward-compatible with the existing FE) AND the grouped-by-procedure
    shape (new rich rendering). The FE picks which to render based on
    `procedures.length > 0`."""
    fe_procedures: list[FEProcedureGroup] = []
    fe_steps_flat: list[FEProtocolStep] = []

    for proc_idx, proc in enumerate(protocol.procedures, start=1):
        phase = classify_phase(proc)
        proc_steps: list[FEProtocolStep] = []
        for step_idx, step in enumerate(proc.steps, start=1):
            fe_step = _adapt_step(
                step, proc,
                phase=phase,
                procedure_name=proc.name,
                procedure_index=proc_idx,
                step_number_in_procedure=step_idx,
            )
            proc_steps.append(fe_step)
            fe_steps_flat.append(fe_step)

        fe_procedures.append(FEProcedureGroup(
            name=proc.name,
            intent=proc.intent,
            steps=proc_steps,
            deviations_from_source=[_adapt_deviation(d) for d in proc.deviations_from_source],
            success_criteria=[_adapt_success_criterion(c) for c in proc.success_criteria],
            total_duration=proc.total_duration,
            procedure_index=proc_idx,
            source_protocol_ids=list(proc.source_protocol_ids),
        ))

    cited = [
        {
            "title": cp.title,
            "doi": cp.doi,
            "protocols_io_id": cp.protocols_io_id,
            "contribution_weight": cp.contribution_weight,
        }
        for cp in protocol.cited_protocols
    ]

    return FEProtocolView(
        steps=fe_steps_flat,
        experiment_type=protocol.experiment_type,
        total_steps=len(fe_steps_flat),
        cited_protocols=cited,
        procedures=fe_procedures,
        total_duration=protocol.total_duration,
        assumptions=list(protocol.assumptions),
    )


# --------------------------------------------------------------------------
# Materials adaptation
# --------------------------------------------------------------------------

# Pydantic Material.category is constrained to these five values.
_GROUP_LABELS: dict[str, tuple[str, str]] = {
    "reagent":    ("Reagents", "Buffers, media, antibodies, and other consumable chemicals."),
    "consumable": ("Consumables", "Disposable plasticware and lab consumables."),
    "equipment":  ("Equipment", "Instruments and durable lab equipment."),
    "cell_line":  ("Cell lines & strains", "Cultured cell lines required for the experiment."),
    "organism":   ("Organisms & samples", "Live animals or biological samples."),
}

_GROUP_ORDER = ["cell_line", "organism", "reagent", "consumable", "equipment"]


def _qty_string(material: Material) -> str:
    """Materials' qty/unit pair → the FE's display string. Empty string
    when neither is set (FE renders that as a dash)."""
    if material.qty is not None and material.unit:
        return f"{_fmt_num(material.qty)} {material.unit}"
    if material.unit:
        return material.unit
    if material.qty is not None:
        return _fmt_num(material.qty)
    return ""


# Storage strings the LLM emits frequently; we map them to the FE's
# cold-chain badge. Lower-cased substring match.
_COLD_TOKENS = ("-20", "-80", "4 °c", "4°c", "refriger", "frozen", "ice", "liquid nitrogen", "cryo")

# Categories that typically have long lead times for procurement.
_LEAD_CATEGORIES = {"cell_line", "organism"}


def _note(material: Material) -> Optional[dict]:
    """Return the FE's optional `note` chip. 'cold' takes precedence over
    'lead' when a material is both (e.g., a cell line stored in LN2)."""
    storage_blob = (material.storage or "").lower()
    if any(tok in storage_blob for tok in _COLD_TOKENS):
        return {"kind": "cold", "text": material.storage or "Requires cold-chain handling"}
    if material.category in _LEAD_CATEGORIES:
        return {"kind": "lead", "text": "Order well in advance — typical lead time 1-3 weeks"}
    return None


def _purpose(material: Material) -> str:
    """The FE always shows a purpose string. Equipment items have purpose
    populated by the roll-up agent; for reagents/consumables we fall back
    to the spec field, the storage hint, or an empty string."""
    if material.purpose:
        return material.purpose
    if material.spec:
        return material.spec
    return ""


def _build_used_in_index(
    protocol: Optional[ProtocolGenerationOutput],
) -> dict[str, list[str]]:
    """Walk the protocol and build a {material_name_lower: [step_id, ...]}
    index. Step IDs are the same "p{proc_idx}-s{step_idx}" used by
    _adapt_step so the FE can cross-link bidirectionally.

    Materials are matched case-insensitively because the LLM sometimes
    capitalizes inconsistently ("PBS" vs "pbs"). Returns {} when no
    protocol is supplied — adapt_materials remains usable standalone.

    Dedup: when a material appears in BOTH `reagents_referenced` and
    `equipment_needed` on the same step (or twice in the same list, which
    LLMs occasionally do), append the step_id only once. Without this the
    FE renders duplicate "Used in 2.1" chips for the same step."""
    index: dict[str, list[str]] = {}
    if protocol is None:
        return index
    for proc_idx, proc in enumerate(protocol.procedures, start=1):
        for step_idx, step in enumerate(proc.steps, start=1):
            step_id = f"p{proc_idx}-s{step_idx}"
            for ref in step.reagents_referenced + step.equipment_needed:
                key = ref.strip().lower()
                if not key:
                    continue
                step_ids = index.setdefault(key, [])
                if step_id not in step_ids:
                    step_ids.append(step_id)
    return index


def adapt_materials(
    materials: MaterialsOutput,
    *,
    protocol: Optional[ProtocolGenerationOutput] = None,
) -> FEMaterialsView:
    """Project a MaterialsOutput into the FE's grouped MaterialGroup shape.
    Empty groups are dropped. Within each group, items keep the order the
    roll-up agent emitted them (which usually tracks procedure order).

    When `protocol` is provided, populate per-item `used_in_steps` so the
    FE can render back-links from materials to the steps that reference
    them ("Used in 2.1, 3.4")."""
    used_in_index = _build_used_in_index(protocol)
    by_cat: dict[str, list[FEReagent]] = {cat: [] for cat in _GROUP_ORDER}
    for m in materials.materials:
        if m.category not in by_cat:
            # Defensive — shouldn't happen since Pydantic constrains category
            continue
        used_in = used_in_index.get(m.name.strip().lower(), [])
        by_cat[m.category].append(FEReagent(
            name=m.name,
            purpose=_purpose(m),
            # vendor/sku come from Stage 4 once that lands; placeholder for now.
            supplier=m.vendor or "TBD",
            catalog=m.sku or "TBD",
            qty=_qty_string(m),
            note=_note(m),
            used_in_steps=used_in,
            material_id=m.id,
        ))

    groups: list[FEMaterialGroup] = []
    for cat in _GROUP_ORDER:
        items = by_cat[cat]
        if not items:
            continue
        label, description = _GROUP_LABELS[cat]
        groups.append(FEMaterialGroup(group=label, description=description, items=items))

    return FEMaterialsView(
        groups=groups,
        total_unique_items=materials.total_unique_items,
        gaps=list(materials.gaps),
    )

"""Tests for protocol_pipeline.frontend_view — the adapter that projects
ProtocolGenerationOutput + MaterialsOutput onto the shapes
ExperimentPlan.tsx consumes.

These tests pin the FE contract: phase classification, meta-tag
formatting, materials grouping, TBD placeholders, and the cold/lead
note hints. If a backend type changes shape, these tests should fail
loudly so the FE doesn't silently break."""

from __future__ import annotations

import pytest

from protocol_pipeline.frontend_view import (
    _format_params_summary,
    adapt_materials,
    adapt_protocol,
    classify_phase,
)
from src.types import (
    Deviation,
    Material,
    MaterialsOutput,
    Procedure,
    ProcedureSuccessCriterion,
    ProtocolGenerationOutput,
    ProtocolStep,
    Quantity,
    ReagentRecipe,
    StepParams,
)


# ---- Helpers -------------------------------------------------------------

def _proc(name: str, intent: str = "test intent", n_steps: int = 1) -> Procedure:
    return Procedure(
        name=name, intent=intent,
        steps=[
            ProtocolStep(n=i + 1, title=f"Step {i+1}", body_md="do a thing")
            for i in range(n_steps)
        ],
    )


# ---- Phase classification ------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    # Preparation
    ("HeLa Cell Culture Preparation", "Preparation"),
    ("Cryoprotectant Medium Preparation", "Preparation"),
    ("Biosensor Fabrication and Antibody Functionalization", "Preparation"),
    ("Calibration Standard Curve Generation", "Preparation"),
    ("Stock Solution Setup", "Preparation"),
    # Experiment (concrete actions)
    ("Cell Freezing", "Experiment"),
    ("Cell Thawing and Initial Recovery", "Experiment"),
    ("Daily Oral Supplementation", "Experiment"),
    ("Tissue Harvest", "Experiment"),
    ("LPS Challenge", "Experiment"),
    # Measurement (assays / readouts)
    ("Post-Thaw Viability Assessment (24h)", "Measurement"),
    ("ELISA CRP Detection", "Measurement"),
    ("Western Blot for Tight Junction Proteins", "Measurement"),
    ("Fluorescence Imaging", "Measurement"),
    # Analysis
    ("Data Analysis and Performance Comparison", "Analysis"),
    ("Statistical Comparison ANOVA", "Analysis"),
    ("Curve Fit and LoD Determination", "Analysis"),
])
def test_classify_phase_known_buckets(name, expected):
    assert classify_phase(_proc(name)) == expected


def test_classify_phase_default_is_experiment():
    """Procedure name with no matching keywords falls back to Experiment."""
    assert classify_phase(_proc("Animal Acclimation and Grouping")) == "Experiment"


def test_classify_phase_uses_name_not_intent():
    """Intent-bleed used to misclassify Experiment procedures as
    Preparation (via 'culture' in '...maintain in culture...'). Phase is
    determined from the NAME only — verify the intent doesn't sway it."""
    p = _proc(
        name="Cell Freezing",
        intent="To uniformly prepare and freeze cells in cryopreservation media for long-term culture storage.",
    )
    assert classify_phase(p) == "Experiment"  # would be Preparation if intent leaked


# ---- Step adaptation ------------------------------------------------------

def test_adapt_protocol_flattens_procedures_into_steps():
    proto = ProtocolGenerationOutput(
        experiment_type="test",
        procedures=[
            _proc("HeLa Cell Culture Preparation", n_steps=2),
            _proc("Cell Freezing", n_steps=3),
            _proc("Post-Thaw Viability Assessment", n_steps=1),
        ],
        steps=[],
        total_steps=6,
    )
    fe = adapt_protocol(proto)
    assert fe.total_steps == 6
    # Phase is per-procedure; each procedure's steps share its phase.
    phases = [s.phase for s in fe.steps]
    assert phases == [
        "Preparation", "Preparation",
        "Experiment", "Experiment", "Experiment",
        "Measurement",
    ]


def test_adapt_protocol_step_meta_picks_first_present_param():
    """Meta tag priority: temperature > volume > duration > concentration > speed."""
    step_with_temp = ProtocolStep(
        n=1, title="t", body_md="t",
        params=StepParams(
            temperature=Quantity(value=37, unit="°C"),
            volume=Quantity(value=10, unit="mL"),
        ),
    )
    step_with_vol_only = ProtocolStep(
        n=2, title="v", body_md="v",
        params=StepParams(volume=Quantity(value=1.5, unit="mL")),
    )
    step_with_duration = ProtocolStep(
        n=3, title="d", body_md="d",
        params=StepParams(duration="PT5M"),
    )
    step_with_nothing = ProtocolStep(n=4, title="x", body_md="x")

    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(
            name="Run", intent="t",
            steps=[step_with_temp, step_with_vol_only, step_with_duration, step_with_nothing],
        )],
        steps=[],
        total_steps=4,
    )
    fe = adapt_protocol(proto)
    metas = [s.meta for s in fe.steps]
    assert metas[0] == "37 °C"
    assert metas[1] == "1.5 mL"
    assert metas[2] == "5 min"
    assert metas[3] is None


def test_adapt_protocol_citation_prefers_doi_over_protocols_io_id():
    proc = Procedure(
        name="Run", intent="t",
        steps=[
            ProtocolStep(n=1, title="A", body_md="a", cited_doi="10.5555/foo"),
            ProtocolStep(n=2, title="B", body_md="b"),
        ],
        source_protocol_ids=["260183"],
    )
    proto = ProtocolGenerationOutput(
        experiment_type="t", procedures=[proc], steps=[], total_steps=2,
    )
    fe = adapt_protocol(proto)
    assert fe.steps[0].citation == "doi:10.5555/foo"
    assert fe.steps[1].citation == "protocols.io/260183"


# ---- Materials adaptation -------------------------------------------------

def _mat(name: str, **kwargs) -> Material:
    return Material(id=f"mat_{name}", name=name, **kwargs)


def test_adapt_materials_groups_in_predictable_order():
    """Group order is fixed: cell_line → organism → reagent → consumable
    → equipment. Empty categories are dropped from the response."""
    mats = MaterialsOutput(
        materials=[
            _mat("Centrifuge", category="equipment"),
            _mat("HeLa cells", category="cell_line"),
            _mat("PBS", category="reagent"),
            _mat("15 mL tube", category="consumable"),
        ],
        total_unique_items=4,
        by_category={"equipment": 1, "cell_line": 1, "reagent": 1, "consumable": 1},
    )
    fe = adapt_materials(mats)
    # Organism category was empty → must not appear in the output.
    assert [g.group for g in fe.groups] == [
        "Cell lines & strains",
        "Reagents",
        "Consumables",
        "Equipment",
    ]


def test_adapt_materials_supplier_catalog_default_to_TBD():
    mats = MaterialsOutput(
        materials=[_mat("DMSO", category="reagent")],
        total_unique_items=1,
    )
    fe = adapt_materials(mats)
    item = fe.groups[0].items[0]
    assert item.supplier == "TBD"
    assert item.catalog == "TBD"


def test_adapt_materials_qty_string_formatting():
    mats = MaterialsOutput(
        materials=[
            _mat("Trehalose", category="reagent", qty=0.5, unit="M"),
            _mat("Tubes", category="consumable", qty=50.0, unit="count"),
            _mat("Just a unit", category="reagent", unit="bottles"),
            _mat("Just a qty", category="reagent", qty=3.0),
            _mat("Nothing", category="reagent"),
        ],
        total_unique_items=5,
    )
    fe = adapt_materials(mats)
    items_by_name = {it.name: it for g in fe.groups for it in g.items}
    assert items_by_name["Trehalose"].qty == "0.5 M"
    assert items_by_name["Tubes"].qty == "50 count"  # whole-number formatting drops .0
    assert items_by_name["Just a unit"].qty == "bottles"
    assert items_by_name["Just a qty"].qty == "3"
    assert items_by_name["Nothing"].qty == ""


def test_adapt_materials_cold_note_detected():
    """Storage strings mentioning -20/-80/4°C/refrigerate get flagged with
    the 'cold' chip; the FE renders that as a snowflake icon."""
    mats = MaterialsOutput(
        materials=[
            _mat("FBS", category="reagent", storage="Store frozen at -20 °C"),
            _mat("PBS room-temp", category="reagent", storage="Store at room temperature"),
            _mat("LN2 reagent", category="reagent", storage="liquid nitrogen storage"),
            _mat("Antibody chilled", category="reagent", storage="Refrigerate, 4 °C"),
        ],
        total_unique_items=4,
    )
    fe = adapt_materials(mats)
    by_name = {it.name: it for g in fe.groups for it in g.items}
    assert by_name["FBS"].note == {"kind": "cold", "text": "Store frozen at -20 °C"}
    assert by_name["PBS room-temp"].note is None
    assert by_name["LN2 reagent"].note["kind"] == "cold"
    assert by_name["Antibody chilled"].note["kind"] == "cold"


def test_adapt_materials_lead_note_for_cell_lines_and_organisms():
    """Cell lines and organisms typically have long procurement lead times
    even when no cold-chain storage is listed; flag with the 'lead' chip."""
    mats = MaterialsOutput(
        materials=[
            _mat("HeLa cells", category="cell_line"),                      # → lead
            _mat("HeLa cells frozen", category="cell_line",
                 storage="Store in liquid nitrogen"),                       # → cold beats lead
            _mat("Lab mice", category="organism"),                         # → lead
            _mat("Random reagent", category="reagent"),                    # → no note
        ],
        total_unique_items=4,
    )
    fe = adapt_materials(mats)
    by_name = {it.name: it for g in fe.groups for it in g.items}
    assert by_name["HeLa cells"].note["kind"] == "lead"
    assert by_name["HeLa cells frozen"].note["kind"] == "cold"
    assert by_name["Lab mice"].note["kind"] == "lead"
    assert by_name["Random reagent"].note is None


def test_adapt_materials_purpose_falls_back_to_spec_for_equipment():
    """Equipment items have purpose populated by the roll-up agent. When
    that's missing, fall back to spec rather than empty."""
    mats = MaterialsOutput(
        materials=[
            _mat("Centrifuge with purpose", category="equipment",
                 purpose="cell pelleting", spec="benchtop, ≥3000g"),
            _mat("Centrifuge no purpose", category="equipment",
                 spec="benchtop, ≥3000g"),
            _mat("Reagent no purpose", category="reagent"),
        ],
        total_unique_items=3,
    )
    fe = adapt_materials(mats)
    by_name = {it.name: it for g in fe.groups for it in g.items}
    assert by_name["Centrifuge with purpose"].purpose == "cell pelleting"
    assert by_name["Centrifuge no purpose"].purpose == "benchtop, ≥3000g"
    assert by_name["Reagent no purpose"].purpose == ""


def test_adapt_materials_preserves_gaps():
    mats = MaterialsOutput(
        materials=[],
        total_unique_items=0,
        gaps=["Specific manufacturer not specified for trehalose."],
    )
    fe = adapt_materials(mats)
    assert fe.gaps == ["Specific manufacturer not specified for trehalose."]


# ---- Phase 2: rich-shape adapter -----------------------------------------
# These tests pin the new FE contract surface: procedure grouping, the
# params_summary list (vs. just the priority `meta` chip), per-step
# anticipated-outcome / critical / pause / troubleshooting / recipes
# pass-through, deviations + success_criteria projection, total_duration
# pass-through, and bidirectional step↔material cross-links.


def _step_with(**kwargs) -> ProtocolStep:
    base = {"n": 1, "title": "Step", "body_md": "do x"}
    base.update(kwargs)
    return ProtocolStep(**base)


# ---- params_summary -----------------------------------------------------

def test_params_summary_orders_by_priority():
    """Order is fixed: temperature → volume → duration → conc → speed.
    The first item is also what `meta` shows."""
    p = StepParams(
        volume=Quantity(value=10, unit="mL"),
        temperature=Quantity(value=37, unit="°C"),
        duration="PT5M",
        concentration=Quantity(value=0.5, unit="M"),
        speed=Quantity(value=300, unit="rpm"),
    )
    assert _format_params_summary(p) == ["37 °C", "10 mL", "5 min", "0.5 M", "300 rpm"]


def test_params_summary_skips_unset():
    p = StepParams(volume=Quantity(value=1.5, unit="mL"))
    assert _format_params_summary(p) == ["1.5 mL"]


def test_params_summary_empty_for_bare_params():
    assert _format_params_summary(StepParams()) == []


# ---- adapt_protocol: new rich shape -------------------------------------

def test_adapt_protocol_emits_procedures_with_index():
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[
            _proc("HeLa Culture Preparation", n_steps=3),
            _proc("Cell Freezing", n_steps=2),
        ],
        steps=[],
        total_steps=5,
    )
    fe = adapt_protocol(proto)
    assert len(fe.procedures) == 2
    assert fe.procedures[0].procedure_index == 1
    assert fe.procedures[1].procedure_index == 2
    # Each procedure's steps are FE-shape; step_number_in_procedure is 1-based.
    assert [s.step_number_in_procedure for s in fe.procedures[0].steps] == [1, 2, 3]
    assert [s.step_number_in_procedure for s in fe.procedures[1].steps] == [1, 2]


def test_adapt_protocol_step_id_format():
    """step_id is "p{proc_idx}-s{step_idx}" so the FE can deep-link from
    a material back to a step. Pin the format so the FE can rely on it."""
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[
            _proc("First", n_steps=2),
            _proc("Second", n_steps=1),
        ],
        steps=[],
        total_steps=3,
    )
    fe = adapt_protocol(proto)
    ids = [s.step_id for p in fe.procedures for s in p.steps]
    assert ids == ["p1-s1", "p1-s2", "p2-s1"]


def test_adapt_protocol_passes_through_new_step_fields():
    """All the Phase-1 ProtocolStep fields appear on FEProtocolStep."""
    step = _step_with(
        is_critical=False,  # 1/1 critical would trip the bound; keep False
        is_pause_point=True,
        anticipated_outcome="Pellet visible",
        troubleshooting=["if X: do Y"],
        equipment_needed=["centrifuge"],
        reagents_referenced=["PBS"],
        todo_for_researcher=["confirm Z"],
        reagent_recipes=[ReagentRecipe(name="M9", components=["3g salt"])],
        duration="PT5M",
        params=StepParams(temperature=Quantity(value=37, unit="°C")),
    )
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(name="P1", intent="t", steps=[step])],
        steps=[],
        total_steps=1,
    )
    fe = adapt_protocol(proto)
    fe_step = fe.procedures[0].steps[0]
    assert fe_step.is_pause_point is True
    assert fe_step.anticipated_outcome == "Pellet visible"
    assert fe_step.troubleshooting == ["if X: do Y"]
    assert fe_step.equipment == ["centrifuge"]
    assert fe_step.reagents == ["PBS"]
    assert fe_step.todos == ["confirm Z"]
    assert len(fe_step.reagent_recipes) == 1
    assert fe_step.reagent_recipes[0].name == "M9"
    assert fe_step.duration == "PT5M"
    assert fe_step.meta == "37 °C"
    assert fe_step.params_summary == ["37 °C"]


def test_adapt_protocol_projects_deviations_and_success_criteria():
    """Per-procedure audit data must reach the FE shape — this is the
    killer feature, the part that makes the protocol look trustworthy."""
    dev = Deviation(
        from_source="C. elegans wash",
        to_adapted="HeLa wash with 10 mL PBS",
        reason="hypothesis specifies HeLa not C. elegans",
        source_protocol_id="260183",
        confidence="high",
    )
    sc = ProcedureSuccessCriterion(
        what="cells reach >=85% confluence within 48h",
        how_measured="trypan blue exclusion",
        threshold=">=85%",
        pass_fail=True,
    )
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(
            name="P1", intent="t", steps=[_step_with()],
            deviations_from_source=[dev],
            success_criteria=[sc],
            source_protocol_ids=["260183"],
        )],
        steps=[],
        total_steps=1,
    )
    fe = adapt_protocol(proto)
    [pg] = fe.procedures
    assert len(pg.deviations_from_source) == 1
    assert pg.deviations_from_source[0].confidence == "high"
    assert pg.deviations_from_source[0].source_protocol_id == "260183"
    assert len(pg.success_criteria) == 1
    assert pg.success_criteria[0].threshold == ">=85%"
    assert pg.source_protocol_ids == ["260183"]


def test_adapt_protocol_passes_through_total_durations():
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(
            name="P1", intent="t", steps=[_step_with()],
            total_duration="PT30M",
        )],
        steps=[],
        total_steps=1,
        total_duration="P1DT2H",
    )
    fe = adapt_protocol(proto)
    assert fe.total_duration == "P1DT2H"
    assert fe.procedures[0].total_duration == "PT30M"


def test_adapt_protocol_keeps_flat_steps_for_backward_compat():
    """The flat `steps` list is still populated even when `procedures` is
    used — preserves the mock-fallback path in the existing FE."""
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[
            _proc("P1", n_steps=2),
            _proc("P2", n_steps=2),
        ],
        steps=[],
        total_steps=4,
    )
    fe = adapt_protocol(proto)
    assert len(fe.steps) == 4
    assert fe.total_steps == 4


def test_adapt_protocol_passes_through_assumptions():
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[_proc("P1", n_steps=1)],
        steps=[],
        total_steps=1,
        assumptions=["BSL-1 facility available", "Standard cell-culture incubator"],
    )
    fe = adapt_protocol(proto)
    assert fe.assumptions == [
        "BSL-1 facility available", "Standard cell-culture incubator",
    ]


# ---- adapt_materials: used_in_steps cross-link --------------------------

def test_adapt_materials_populates_used_in_steps_when_protocol_provided():
    """The FE renders 'Used in 2.1, 3.4' next to each material — verify
    those step IDs come from the protocol walk (case-insensitive match)."""
    step1 = _step_with(reagents_referenced=["PBS", "DMEM"])
    step2 = _step_with(reagents_referenced=["pbs"], equipment_needed=["centrifuge"])
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(name="P1", intent="t", steps=[step1, step2])],
        steps=[],
        total_steps=2,
    )
    mats = MaterialsOutput(
        materials=[
            _mat("PBS", category="reagent"),
            _mat("DMEM", category="reagent"),
            _mat("Centrifuge", category="equipment"),
            _mat("Unused thing", category="reagent"),
        ],
        total_unique_items=4,
    )
    fe = adapt_materials(mats, protocol=proto)
    by_name = {it.name: it for g in fe.groups for it in g.items}
    assert by_name["PBS"].used_in_steps == ["p1-s1", "p1-s2"]  # case-insensitive
    assert by_name["DMEM"].used_in_steps == ["p1-s1"]
    assert by_name["Centrifuge"].used_in_steps == ["p1-s2"]
    assert by_name["Unused thing"].used_in_steps == []


def test_adapt_materials_used_in_steps_deduped_per_step():
    """A material referenced in BOTH equipment_needed AND reagents_referenced
    on the same step must NOT appear twice in used_in_steps. Same goes
    for duplicate entries within a single list (LLMs occasionally repeat
    items). Without dedup the FE renders "Used in 2.1, 2.1" chips."""
    step1 = _step_with(
        # "PBS" appears in both lists on the SAME step:
        reagents_referenced=["PBS"],
        equipment_needed=["PBS"],
    )
    step2 = _step_with(
        # "PBS" appears twice in the same list:
        reagents_referenced=["PBS", "pbs"],  # also tests case-insensitivity
    )
    proto = ProtocolGenerationOutput(
        experiment_type="t",
        procedures=[Procedure(name="P1", intent="t", steps=[step1, step2])],
        steps=[],
        total_steps=2,
    )
    mats = MaterialsOutput(
        materials=[_mat("PBS", category="reagent")],
        total_unique_items=1,
    )
    fe = adapt_materials(mats, protocol=proto)
    [item] = [it for g in fe.groups for it in g.items]
    # Each step appears at most once even though PBS is referenced twice
    # on each step. Order = first appearance.
    assert item.used_in_steps == ["p1-s1", "p1-s2"]


def test_adapt_materials_used_in_steps_empty_without_protocol():
    """When no protocol is passed, used_in_steps stays empty — adapter
    is still callable standalone (e.g., from tests or FE design mode)."""
    mats = MaterialsOutput(
        materials=[_mat("PBS", category="reagent")],
        total_unique_items=1,
    )
    fe = adapt_materials(mats)
    [item] = [it for g in fe.groups for it in g.items]
    assert item.used_in_steps == []


def test_adapt_materials_propagates_material_id():
    mats = MaterialsOutput(
        materials=[Material(id="mat_abc123", name="PBS", category="reagent")],
        total_unique_items=1,
    )
    fe = adapt_materials(mats)
    [item] = [it for g in fe.groups for it in g.items]
    assert item.material_id == "mat_abc123"

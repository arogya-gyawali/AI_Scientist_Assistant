"""Tests for protocol_pipeline.writer's `_build_steps` parser — focus on
the new quality-of-life fields and their hallucination defenses.

We test the parser directly rather than the full `write_procedure()` so
the tests stay hermetic (no LLM calls) and run fast."""

from __future__ import annotations

import pytest

from protocol_pipeline.writer import (
    _CRITICAL_STEP_FRACTION_BOUND,
    _MAX_RECIPE_COMPONENTS,
    _MAX_RECIPES_PER_STEP,
    _MAX_TROUBLESHOOTING_PER_STEP,
    _build_steps,
    _coerce_bool,
    _coerce_reagent_recipe,
)


# ---- Anticipated outcome / critical / pause-point fields ---------------

def test_new_fields_default_to_safe_values():
    """When the LLM omits the new fields, the parser must fill in safe
    defaults rather than leaving them missing — the FE relies on them."""
    raw = [{"n": 1, "title": "X", "body_md": "do x"}]
    [s] = _build_steps(raw, known_source_ids=set())
    assert s.is_critical is False
    assert s.is_pause_point is False
    assert s.anticipated_outcome is None
    assert s.troubleshooting == []
    assert s.reagent_recipes == []


def test_anticipated_outcome_string_or_none():
    """Truthy strings are kept (after strip); empty / None / missing -> None."""
    cases = [
        ({"anticipated_outcome": "Pellet ~3 mm³"}, "Pellet ~3 mm³"),
        ({"anticipated_outcome": "  spaces  "}, "spaces"),
        ({"anticipated_outcome": ""}, None),
        ({"anticipated_outcome": None}, None),
        ({}, None),
    ]
    for extra, expected in cases:
        raw = [{"n": 1, "title": "X", "body_md": "x", **extra}]
        [s] = _build_steps(raw, known_source_ids=set())
        assert s.anticipated_outcome == expected, f"input {extra!r}"


def test_is_critical_and_pause_point_coerced_to_bool():
    """LLM occasionally emits booleans as strings ('true') or numbers (1).
    The parser uses _coerce_bool which accepts genuine truthy values.

    NOTE: We use 5 steps with only 1 critical (20%) to stay below the
    30% bound — the bound itself is exercised by separate tests below."""
    raw = [
        {"n": 1, "title": "A", "body_md": "x", "is_critical": True, "is_pause_point": False},
        {"n": 2, "title": "B", "body_md": "x", "is_critical": False, "is_pause_point": True},
        {"n": 3, "title": "C", "body_md": "x", "is_critical": False, "is_pause_point": False},
        {"n": 4, "title": "D", "body_md": "x", "is_critical": False, "is_pause_point": False},
        {"n": 5, "title": "E", "body_md": "x", "is_critical": False, "is_pause_point": False},
    ]
    steps = _build_steps(raw, known_source_ids=set())
    assert steps[0].is_critical is True and steps[0].is_pause_point is False
    assert steps[1].is_critical is False and steps[1].is_pause_point is True


def test_coerce_bool_handles_string_false_correctly():
    """The bug Python's naive bool() has: bool("false") is True (any
    non-empty string is truthy). _coerce_bool reads the string content.

    This is the bug Gemini caught on PR #9 — without _coerce_bool, an
    LLM that emits {"is_critical": "false"} would have every step flagged
    critical, which then trips the 30% bound and demotes all of them.
    Either way, the user gets the wrong answer."""
    # The classic Python footgun:
    assert bool("false") is True   # demonstrates why _coerce_bool exists

    # Truthy inputs we honor:
    for v in [True, "true", "True", "TRUE", "yes", "1", 1]:
        assert _coerce_bool(v) is True, f"expected True for {v!r}"

    # Falsy inputs — including the strings that Python's bool() would
    # mishandle. Crucially: "false" must coerce to False.
    for v in [False, "false", "False", "FALSE", "no", "0", "", "anything-else", 0, None]:
        assert _coerce_bool(v) is False, f"expected False for {v!r}"


def test_string_false_does_not_flag_step_critical():
    """End-to-end check that the bool() bug doesn't sneak back in via
    _build_steps. Five steps emit "false" (string) and "true" (string);
    the parser must respect the strings, not Python's truthy-by-default
    treatment of any non-empty string."""
    raw = [
        {"n": 1, "title": "A", "body_md": "x", "is_critical": "false", "is_pause_point": "false"},
        {"n": 2, "title": "B", "body_md": "x", "is_critical": "false", "is_pause_point": "true"},
        {"n": 3, "title": "C", "body_md": "x", "is_critical": "true",  "is_pause_point": "false"},
        {"n": 4, "title": "D", "body_md": "x", "is_critical": "false", "is_pause_point": "false"},
        {"n": 5, "title": "E", "body_md": "x", "is_critical": "false", "is_pause_point": "false"},
    ]
    steps = _build_steps(raw, known_source_ids=set())
    assert sum(1 for s in steps if s.is_critical) == 1     # only step 3
    assert sum(1 for s in steps if s.is_pause_point) == 1  # only step 2


# ---- Critical-step bound (>30% gets all demoted) -----------------------

def test_critical_below_threshold_kept():
    """1 of 5 critical (20%) is below the 30% bound; flag preserved."""
    raw = [
        {"n": i, "title": f"S{i}", "body_md": "x", "is_critical": (i == 3)}
        for i in range(1, 6)
    ]
    steps = _build_steps(raw, known_source_ids=set())
    n_critical = sum(1 for s in steps if s.is_critical)
    assert n_critical == 1


def test_critical_at_threshold_demoted_for_safety():
    """The bound is strict-greater (>30%). 30% exactly = kept, but with
    small N the boundary is sharp. Verify 4 of 10 (40%) trips it."""
    raw = [
        {"n": i, "title": f"S{i}", "body_md": "x", "is_critical": (i <= 4)}
        for i in range(1, 11)
    ]
    steps = _build_steps(raw, known_source_ids=set())
    n_critical = sum(1 for s in steps if s.is_critical)
    assert n_critical == 0, "Over-tagged critical should be demoted"


def test_critical_all_demoted_when_all_flagged():
    """Edge case: every step flagged critical -> all demoted."""
    raw = [{"n": i, "title": f"S{i}", "body_md": "x", "is_critical": True} for i in range(1, 6)]
    steps = _build_steps(raw, known_source_ids=set())
    assert sum(1 for s in steps if s.is_critical) == 0


def test_threshold_constant_is_intentional():
    """Pin the threshold so a future tuning change is intentional."""
    assert _CRITICAL_STEP_FRACTION_BOUND == 0.30


# ---- Troubleshooting cap -----------------------------------------------

def test_troubleshooting_capped():
    """Cap defends against runaway LLM output; honest protocols rarely
    have more than ~5 troubleshooting items per step."""
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "troubleshooting": [f"item-{i}" for i in range(50)],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert len(s.troubleshooting) == _MAX_TROUBLESHOOTING_PER_STEP


def test_troubleshooting_blanks_dropped():
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "troubleshooting": ["good item", "", "  ", "another good"],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert s.troubleshooting == ["good item", "another good"]


def test_troubleshooting_non_list_yields_empty():
    """LLM may emit a string or dict instead of a list. Don't crash."""
    for bad in ["a single string", {"key": "val"}, 42]:
        raw = [{"n": 1, "title": "X", "body_md": "x", "troubleshooting": bad}]
        [s] = _build_steps(raw, known_source_ids=set())
        assert s.troubleshooting == []


# ---- Reagent recipes ---------------------------------------------------

def test_reagent_recipe_full_shape():
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "reagent_recipes": [
            {"name": "M9", "components": ["3g Na2HPO4", "0.5g NaCl"], "notes": "Autoclave"},
        ],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert len(s.reagent_recipes) == 1
    r = s.reagent_recipes[0]
    assert r.name == "M9"
    assert r.components == ["3g Na2HPO4", "0.5g NaCl"]
    assert r.notes == "Autoclave"


def test_reagent_recipe_without_components_dropped():
    """A recipe with no components is useless to the researcher; drop it."""
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "reagent_recipes": [
            {"name": "Empty", "components": []},
            {"name": "Real", "components": ["1g something"]},
        ],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert len(s.reagent_recipes) == 1
    assert s.reagent_recipes[0].name == "Real"


def test_reagent_recipe_without_name_dropped():
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "reagent_recipes": [
            {"name": "", "components": ["1g salt"]},
            {"components": ["1g salt"]},  # missing name entirely
        ],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert s.reagent_recipes == []


def test_reagent_recipes_capped_per_step():
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "reagent_recipes": [
            {"name": f"R{i}", "components": ["c"]} for i in range(20)
        ],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert len(s.reagent_recipes) == _MAX_RECIPES_PER_STEP


def test_recipe_components_capped():
    raw = [{
        "n": 1, "title": "X", "body_md": "x",
        "reagent_recipes": [
            {"name": "Big", "components": [f"item-{i}" for i in range(100)]},
        ],
    }]
    [s] = _build_steps(raw, known_source_ids=set())
    assert len(s.reagent_recipes[0].components) == _MAX_RECIPE_COMPONENTS


def test_coerce_reagent_recipe_returns_none_for_garbage():
    assert _coerce_reagent_recipe(None) is None
    assert _coerce_reagent_recipe("not a dict") is None
    assert _coerce_reagent_recipe(42) is None
    assert _coerce_reagent_recipe([]) is None

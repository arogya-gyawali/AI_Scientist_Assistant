"""Tests for protocol_pipeline.relevance — relevance filter agent.

Mocked tests (always run): verify score normalization, hallucination
defense, and threshold filtering without hitting the LLM.

Live test (gated on `LLM_PROVIDER` and the corresponding key): runs the
filter against the real Spanish trehalose top hit. Designed to confirm
the rubric correctly down-weights an off-target source.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from protocol_pipeline.relevance import (
    RelevanceScore,
    filter_relevant,
    score_protocols,
)
from protocol_pipeline.sources import NormalizedProtocol, NormalizedStep
from src.types import Hypothesis, StructuredHypothesis


def _hyp() -> Hypothesis:
    return Hypothesis(
        id="hyp_test",
        structured=StructuredHypothesis(
            research_question="Does X improve Y?",
            subject="HeLa cells",
            independent="X",
            dependent="Y",
            conditions="standard culture",
            expected="Y improves by 15%",
        ),
    )


def _proto(pid: str, title: str = "Test protocol", n_steps: int = 3) -> NormalizedProtocol:
    return NormalizedProtocol(
        id=pid, title=title, language="en",
        steps=[NormalizedStep(id=f"s{i}", section="", number=str(i+1),
                              text=f"Step {i+1} body.") for i in range(n_steps)],
    )


def _mock_llm(payload: dict):
    """Return a context manager that mocks llm.complete to emit `payload`."""
    return patch("protocol_pipeline.relevance.llm.complete",
                 return_value=json.dumps(payload))


# ---- Mocked unit tests ---------------------------------------------------

def test_score_protocols_returns_one_per_input():
    protos = [_proto("p1"), _proto("p2"), _proto("p3")]
    payload = {"scores": [
        {"protocol_id": "p1", "score": 0.9, "reason": "exact match"},
        {"protocol_id": "p2", "score": 0.5, "reason": "partial"},
        {"protocol_id": "p3", "score": 0.1, "reason": "off-target"},
    ]}
    with _mock_llm(payload):
        scored = score_protocols(_hyp(), protos)
    assert len(scored) == 3
    assert {sp.protocol.id for sp in scored} == {"p1", "p2", "p3"}


def test_filter_relevant_drops_below_threshold_and_sorts():
    protos = [_proto("p1"), _proto("p2"), _proto("p3")]
    payload = {"scores": [
        {"protocol_id": "p1", "score": 0.9, "reason": "high"},
        {"protocol_id": "p2", "score": 0.5, "reason": "mid"},
        {"protocol_id": "p3", "score": 0.05, "reason": "low"},
    ]}
    with _mock_llm(payload):
        kept = filter_relevant(_hyp(), protos, keep_threshold=0.2)
    assert [sp.protocol.id for sp in kept] == ["p1", "p2"]  # p3 dropped, sorted desc


def test_score_clamped_to_unit_interval():
    """LLMs occasionally hallucinate scores outside [0,1]. Clamp them."""
    protos = [_proto("p1"), _proto("p2")]
    payload = {"scores": [
        {"protocol_id": "p1", "score": 1.5, "reason": "over"},
        {"protocol_id": "p2", "score": -0.3, "reason": "under"},
    ]}
    with _mock_llm(payload):
        scored = score_protocols(_hyp(), protos)
    by_id = {sp.protocol.id: sp.score.score for sp in scored}
    assert by_id["p1"] == 1.0
    assert by_id["p2"] == 0.0


def test_unknown_protocol_id_dropped():
    """If LLM returns a score for an id we didn't send, ignore it.
    Defends against hallucination."""
    protos = [_proto("p1")]
    payload = {"scores": [
        {"protocol_id": "p1", "score": 0.7, "reason": "ok"},
        {"protocol_id": "p_HALLUCINATED", "score": 0.9, "reason": "made up"},
    ]}
    with _mock_llm(payload):
        scored = score_protocols(_hyp(), protos)
    assert len(scored) == 1
    assert scored[0].protocol.id == "p1"
    assert scored[0].score.score == 0.7


def test_missing_protocol_in_response_gets_default_midlow():
    """If LLM omits a protocol from its scores list, we don't drop it
    silently — assign default 0.3 with an explicit reason."""
    protos = [_proto("p1"), _proto("p2")]
    payload = {"scores": [
        {"protocol_id": "p1", "score": 0.8, "reason": "good"},
        # p2 missing
    ]}
    with _mock_llm(payload):
        scored = score_protocols(_hyp(), protos)
    by_id = {sp.protocol.id: sp.score for sp in scored}
    assert by_id["p1"].score == 0.8
    assert by_id["p2"].score == 0.3
    assert "did not score" in by_id["p2"].reason.lower()


def test_empty_input_returns_empty():
    """No protocols → no LLM call, no error."""
    assert score_protocols(_hyp(), []) == []
    assert filter_relevant(_hyp(), []) == []


def test_malformed_score_skipped():
    """Non-numeric score → that protocol falls through to the missing-default
    path, gets 0.3 instead of crashing."""
    protos = [_proto("p1")]
    payload = {"scores": [{"protocol_id": "p1", "score": "not-a-number", "reason": "x"}]}
    with _mock_llm(payload):
        scored = score_protocols(_hyp(), protos)
    assert len(scored) == 1
    assert scored[0].score.score == 0.3


# ---- Live integration test (gated) ---------------------------------------

@pytest.mark.live
def test_live_trehalose_top_hit_scored_below_perfect():
    """The trehalose top hit on protocols.io is C. elegans cryopreservation,
    and the hypothesis is HeLa cells. A correctly-calibrated LLM should
    score this somewhere in the partial-relevance band (0.2-0.7), not at
    the top of the rubric. Sanity-check that the agent doesn't blindly
    rate everything as a perfect match."""
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("No LLM key set; skipping live relevance test")
    from protocol_pipeline.sources import load_sample
    norm = load_sample("trehalose")
    assert norm is not None
    [scored] = score_protocols(_hyp(), [norm])
    assert 0.0 <= scored.score.score <= 0.8, (
        f"Top hit (C. elegans cryo) scored {scored.score.score} for HeLa "
        f"hypothesis — agent should not rate this as a perfect match. "
        f"Reason given: {scored.score.reason}"
    )

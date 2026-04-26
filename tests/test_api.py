"""Tests for the Flask API exposing Stage 1.

Uses Flask's test_client (no live server). The Stage 1 runner is monkey-
patched so we exercise routing / validation / response shape without
burning Tavily or LLM credits.

Run:
  pytest tests/test_api.py -v
"""

from __future__ import annotations

import pytest

import app as flask_app
from src.types import (
    Citation,
    LitReviewOutput,
    LitReviewSession,
    StageStatusComplete,
)


@pytest.fixture
def client(monkeypatch):
    # Stub the Stage 1 runner so the endpoint test is hermetic.
    def _fake_run(plan):
        ref = Citation(
            source="europe_pmc",
            confidence="high",
            title="A mock paper",
            authors=["Alice Doe", "Bob Roe"],
            year=2024,
            venue="Mock Journal",
            doi="10.0000/mock.2024",
            url="https://doi.org/10.0000/mock.2024",
            snippet="Mock abstract.",
            relevance_score=0.9,
            matched_on=["mock", "test"],
            description="Neutral mock description.",
            importance="Why this would match the user's hypothesis.",
        )
        out = LitReviewOutput(
            signal="novel",
            description="Top-level mock signal explanation.",
            references=[ref],
            searched_at="2026-04-26T00:00:00+00:00",
            tavily_query="mock query",
            summary="One-sentence mock summary.",
        )
        return LitReviewSession(
            id="lr_mock",
            hypothesis_id=plan.hypothesis.id,
            initial_result=out,
            chat_history=[],
            cached_search_context="{}",
            user_decision="pending",
        )

    monkeypatch.setattr(flask_app.stage, "run", _fake_run)
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


# =============================================================================
# /health
# =============================================================================

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["stage"] == "lit_review"


# =============================================================================
# /lit-review — happy paths
# =============================================================================

def _valid_body():
    return {
        "structured": {
            "research_question": "Does X improve Y?",
            "subject": "Subject organism",
            "independent": "Variable A",
            "dependent": "Variable B",
            "conditions": "Standard lab conditions",
            "expected": "Y increases by 30%",
        },
        "domain": "cell_biology",
    }


def test_lit_review_returns_200_with_valid_output(client):
    r = client.post("/lit-review", json=_valid_body())
    assert r.status_code == 200
    body = r.get_json()
    assert body["signal"] == "novel"
    assert isinstance(body["references"], list)
    assert body["references"][0]["title"] == "A mock paper"


def test_lit_review_response_includes_summary(client):
    r = client.post("/lit-review", json=_valid_body())
    body = r.get_json()
    assert body["summary"]
    assert body["description"]


def test_lit_review_accepts_explicit_id_form(client):
    body = _valid_body()
    body["id"] = "hyp_clientside_123"
    body["created_at"] = "2026-04-26T00:00:00+00:00"
    r = client.post("/lit-review", json=body)
    assert r.status_code == 200


# =============================================================================
# /lit-review — error paths
# =============================================================================

def test_missing_body_returns_400(client):
    r = client.post("/lit-review")
    assert r.status_code == 400
    assert r.get_json()["error"] == "request_body_required"


def test_missing_structured_field_returns_422(client):
    """Empty 'structured' object should fail Pydantic validation."""
    r = client.post("/lit-review", json={"structured": {}})
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"] == "validation_error"
    assert isinstance(body["detail"], list)


def test_pipeline_error_returns_500(client, monkeypatch):
    """If the runner raises, the endpoint surfaces a 500 — and crucially
    does NOT leak the raw exception string into the client response."""
    def _broken(plan):
        raise RuntimeError("upstream blew up with secret/path/info")
    monkeypatch.setattr(flask_app.stage, "run", _broken)

    r = client.post("/lit-review", json=_valid_body())
    assert r.status_code == 500
    body = r.get_json()
    assert body["error"] == "pipeline_error"
    # Internal exception detail must not appear in the response (security).
    assert "secret/path/info" not in body["detail"]
    assert "upstream blew up" not in body["detail"]


def test_create_plan_failure_returns_500_cleanly(client, monkeypatch):
    """If plan creation itself raises (before the runner is reached), the
    except handler must NOT explode trying to mark a non-existent plan as
    failed. Exercises the `if plan is not None` guard. Also verifies
    internal error details don't leak into the response."""
    def _broken_create(hypothesis, model_id):
        raise RuntimeError("disk full at /var/lib/secret-path")
    monkeypatch.setattr(flask_app.plan_lib, "create_plan", _broken_create)

    r = client.post("/lit-review", json=_valid_body())
    assert r.status_code == 500
    body = r.get_json()
    assert body["error"] == "pipeline_error"
    assert "/var/lib/secret-path" not in body["detail"]

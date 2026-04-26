"""Flask API for the AI Scientist FE.

Endpoints:
  GET  /health      Liveness ping
  POST /lit-review  Stage 1 (novelty check); persists a plan, returns plan_id
  POST /protocol    Stage 2 (protocol generation); accepts {plan_id} to chain
                    off a prior /lit-review, or {structured} for a fresh start
  POST /materials   Stage 3 (materials roll-up); accepts {plan_id} for chaining
                    or {structured} (runs /protocol internally first)

Dev:
  python -m flask --app app run --debug --port 5000

Or:
  python app.py

Response shape: every Stage 2/3 response carries both `frontend_view`
(the shape the existing React mockup consumes) and the full `raw`
output (rich Pydantic model). Future FE upgrades can switch to `raw`
without a backend change.
"""

from __future__ import annotations

import io
import os
import sys
import traceback
import uuid

from dotenv import load_dotenv

# Load .env BEFORE importing modules that read env at import time.
load_dotenv()

# UTF-8 stdout/stderr so Windows cp1252 doesn't choke on science Unicode.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request, send_file  # noqa: E402
from flask_cors import CORS  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.clients import llm  # noqa: E402
from src.lib import plan as plan_lib  # noqa: E402
from src.types import (  # noqa: E402
    ExperimentPlan,
    Hypothesis,
    StageStatusComplete,
    StageStatusFailed,
    StageStatusRunning,
    StructuredHypothesis,
    now,
)
from lit_review_pipeline import stage  # noqa: E402
from protocol_pipeline import stage as protocol_stage  # noqa: E402
from protocol_pipeline.frontend_view import (  # noqa: E402
    adapt_materials,
    adapt_protocol,
)


app = Flask(__name__)
CORS(app)  # allow cross-origin from the FE dev server / Vercel


@app.get("/health")
def health():
    """Liveness ping."""
    return jsonify({
        "ok": True,
        "service": "ai-scientist-assistant",
        "stage": "lit_review",
        "model": llm.model_id(),
    })


@app.post("/lit-review")
def lit_review():
    """Run Stage 1 lit review on a structured hypothesis.

    Request body — either form is accepted:

      Form A (server generates id):
        {
          "structured": {
            "research_question": "...",
            "subject": "...",
            "independent": "...",
            "dependent": "...",
            "conditions": "...",
            "expected": "..."
          },
          "domain": "cell_biology"   // optional
        }

      Form B (client supplies a full Hypothesis):
        {
          "id": "hyp_abc123",
          "structured": { ... },
          "domain": "cell_biology",
          "created_at": "2026-04-26T..."
        }

    Response: LitReviewOutput JSON
        { signal, description, references[], summary, searched_at, tavily_query }
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "request_body_required",
                        "detail": "Body must be JSON with a 'structured' field."}), 400

    try:
        if "id" in body:
            hypothesis = Hypothesis(**body)
        else:
            structured = StructuredHypothesis(**(body.get("structured") or {}))
            hypothesis = Hypothesis(
                id=f"hyp_{uuid.uuid4().hex[:12]}",
                structured=structured,
                domain=body.get("domain"),
            )
    except ValidationError as exc:
        # Pydantic gives field-level errors; surface them so FE can highlight.
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422

    plan = None
    try:
        plan = plan_lib.create_plan(hypothesis, model_id=llm.model_id())
        plan.status["lit_review"] = StageStatusRunning(started_at=now())
        plan_lib.save_plan(plan)

        session = stage.run(plan)

        plan.lit_review = session
        plan.status["lit_review"] = StageStatusComplete(completed_at=now())
        plan_lib.save_plan(plan)

        # Return the editorial result plus the plan_id so the FE can
        # chain `/protocol` and `/materials` calls against this plan.
        # Full plan is persisted to plans/<plan_id>.json on disk.
        payload = session.initial_result.model_dump(mode="json")
        payload["plan_id"] = plan.id
        return jsonify(payload)

    except Exception as exc:
        # Log the full traceback server-side for debugging, but DO NOT leak
        # internal exception details to the client. Raw exception strings
        # can include file paths, library versions, and upstream-service
        # internals that an attacker could use to fingerprint the deployment.
        traceback.print_exc()
        try:
            if plan is not None:
                plan.status["lit_review"] = StageStatusFailed(failed_at=now(), error=str(exc))
                plan_lib.save_plan(plan)
        except Exception:
            pass
        return jsonify({
            "error": "pipeline_error",
            "detail": "Stage 1 failed. Check server logs for the underlying cause.",
        }), 500


# ---------------------------------------------------------------------------
# Stage 2 / 3 helpers
# ---------------------------------------------------------------------------

def _resolve_plan(body: dict) -> tuple[ExperimentPlan, bool]:
    """Either load an existing plan via `plan_id` or mint a new one from a
    `structured` hypothesis. Returns (plan, is_new). Raises ValueError on
    bad input — caller turns it into a 400/422.

    Both /protocol and /materials accept either form so the FE can chain
    off /lit-review (plan_id) AND a curl-based smoke test can hit them
    without lit-review (structured)."""
    plan_id = body.get("plan_id")
    if plan_id:
        try:
            return plan_lib.load_plan(str(plan_id)), False
        except FileNotFoundError as exc:
            raise ValueError(f"plan_id {plan_id!r} not found on disk") from exc

    if "structured" in body or "id" in body:
        if "id" in body:
            hypothesis = Hypothesis(**body)
        else:
            structured = StructuredHypothesis(**(body.get("structured") or {}))
            hypothesis = Hypothesis(
                id=f"hyp_{uuid.uuid4().hex[:12]}",
                structured=structured,
                domain=body.get("domain"),
            )
        plan = plan_lib.create_plan(hypothesis, model_id=llm.model_id())
        plan_lib.save_plan(plan)
        return plan, True

    raise ValueError("Body must contain either 'plan_id' or 'structured'.")


def _stage_failed_response(stage_name: str, plan: ExperimentPlan | None, exc: Exception):
    """Same pattern as /lit-review: log full traceback server-side, mark
    the stage failed on the plan if we have one, return a sanitized 500."""
    traceback.print_exc()
    try:
        if plan is not None:
            plan.status[stage_name] = StageStatusFailed(failed_at=now(), error=str(exc))
            plan_lib.save_plan(plan)
    except Exception:
        pass
    return jsonify({
        "error": "pipeline_error",
        "detail": f"Stage '{stage_name}' failed. Check server logs for the underlying cause.",
    }), 500


# ---------------------------------------------------------------------------
# POST /protocol
# ---------------------------------------------------------------------------

@app.post("/protocol")
def protocol():
    """Run Stage 2 protocol generation.

    Request body — either form is accepted:

      Form A (chain off /lit-review):
        { "plan_id": "plan_abc..." }

      Form B (start fresh; mostly for curl testing):
        {
          "structured": { research_question, subject, independent,
                          dependent, conditions, expected },
          "domain": "cell_biology"   // optional
        }

    Response:
        {
          "plan_id": "...",
          "frontend_view": FEProtocolView,   // flat steps[], for ExperimentPlan.tsx
          "raw": ProtocolGenerationOutput    // rich shape, for future FE upgrade
        }
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, _is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    started = now()
    plan.status["protocol"] = StageStatusRunning(started_at=started)
    plan.updated_at = started
    plan_lib.save_plan(plan)

    # Optional researcher inputs from the candidate-selection screen:
    # - selected_protocol_ids: list[str] of IDs the user picked from
    #   the /protocol-candidates response. When present, skip auto-
    #   resolution and pass exactly those into the pipeline.
    # - researcher_notes: freeform supplemental guidance threaded into
    #   the architect + writer prompts as a binding override.
    selected_ids = body.get("selected_protocol_ids")
    if selected_ids is not None and not isinstance(selected_ids, list):
        return jsonify({
            "error": "bad_request",
            "detail": "selected_protocol_ids must be a list of strings.",
        }), 400
    selected_ids = [str(x) for x in (selected_ids or []) if str(x).strip()] or None
    researcher_notes = body.get("researcher_notes")
    if researcher_notes is not None and not isinstance(researcher_notes, str):
        return jsonify({
            "error": "bad_request",
            "detail": "researcher_notes must be a string.",
        }), 400

    try:
        protocol_out, _outline = protocol_stage.run_protocol_only(
            plan.hypothesis,
            selected_protocol_ids=selected_ids,
            researcher_notes=researcher_notes,
        )
    except Exception as exc:
        return _stage_failed_response("protocol", plan, exc)

    completed = now()
    plan.protocol = protocol_out
    plan.status["protocol"] = StageStatusComplete(completed_at=completed)
    plan.updated_at = completed
    plan_lib.save_plan(plan)

    return jsonify({
        "plan_id": plan.id,
        "frontend_view": adapt_protocol(protocol_out).model_dump(mode="json"),
        "raw": protocol_out.model_dump(mode="json"),
    })


# ---------------------------------------------------------------------------
# POST /protocol-candidates
# ---------------------------------------------------------------------------

@app.post("/protocol-candidates")
def protocol_candidates():
    """Fetch candidate protocols from protocols.io for the FE selection
    screen. Doesn't run the full pipeline — just the search +
    relevance-scoring step. The user picks 1-3 candidates on the FE
    and posts their selection back to /protocol with researcher notes.

    Request body — same `_resolve_plan` shape as /protocol:
      Form A: {"plan_id": "plan_abc..."} (chain off /lit-review)
      Form B: {"structured": {...}}      (fresh start)

    Response:
        {
          "plan_id": "...",
          "query_used": "trehalose",
          "queries_tried": ["trehalose", "cryopreservation"],
          "candidates": [
            {
              "id": "260183",
              "title": "...",
              "description": "...",
              "url": "...",
              "doi": "...",
              "language": "es",
              "step_count": 13,
              "relevance_score": 0.55,
              "relevance_reason": "Same technique class but different organism..."
            },
            ...
          ]
        }

    `candidates` is sorted by relevance score descending. An empty list
    means protocols.io returned nothing for any of the ranked queries —
    the FE should show a "no matches; proceed with synthesis" path.
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, _is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    try:
        candidates, queries_tried, query_used = (
            protocol_stage.fetch_candidates_for_hypothesis(plan.hypothesis, limit=5)
        )
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "error": "pipeline_error",
            "detail": "Candidate fetch failed. Check server logs.",
        }), 500

    return jsonify({
        "plan_id": plan.id,
        "query_used": query_used,
        "queries_tried": queries_tried,
        "candidates": [c.model_dump(mode="json") for c in candidates],
    })


# ---------------------------------------------------------------------------
# POST /protocol/pdf
# ---------------------------------------------------------------------------

@app.post("/protocol/pdf")
def protocol_pdf():
    """Render the current protocol to a PDF and return the bytes.

    Same `_resolve_plan` shape as the other stage endpoints (Form A
    plan_id / Form B structured). When chaining via plan_id the plan
    must already have `protocol` populated — returns 400 otherwise so
    the FE can call /protocol first. Form B runs /protocol implicitly.

    Response: application/pdf, with Content-Disposition: attachment
    and a slugged filename derived from the experiment_type so the
    user's download lands as e.g. `protocol-cryopreservation-comparison.pdf`.
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    # Same chaining rule as /materials, /timeline, /validation: chained
    # plan must already have a protocol. New (Form B) plans run /protocol
    # implicitly so curl users can one-shot a PDF from a hypothesis.
    if not is_new and plan.protocol is None:
        return jsonify({
            "error": "protocol_not_run",
            "detail": "This plan has no protocol yet. POST /protocol first, then retry /protocol/pdf.",
        }), 400

    if plan.protocol is None:
        started = now()
        plan.status["protocol"] = StageStatusRunning(started_at=started)
        plan.updated_at = started
        plan_lib.save_plan(plan)
        try:
            protocol_out, _outline = protocol_stage.run_protocol_only(plan.hypothesis)
        except Exception as exc:
            return _stage_failed_response("protocol", plan, exc)
        completed = now()
        plan.protocol = protocol_out
        plan.status["protocol"] = StageStatusComplete(completed_at=completed)
        plan.updated_at = completed
        plan_lib.save_plan(plan)

    # Lazy import — keeps reportlab off the critical-path startup for
    # the more common JSON endpoints, and isolates PDF errors from the
    # rest of the app.
    from protocol_pipeline.pdf import render_protocol_pdf

    try:
        pdf_bytes = render_protocol_pdf(plan.protocol, plan.hypothesis)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "error": "pdf_render_error",
            "detail": "Failed to render protocol PDF. Check server logs for the underlying cause.",
        }), 500

    # Slugify experiment_type for the download filename. Falls back to
    # the plan_id when the experiment_type is empty.
    raw_slug = (plan.protocol.experiment_type or plan.id).lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in raw_slug)
    slug = "-".join(part for part in slug.split("-") if part)[:60] or plan.id
    filename = f"protocol-{slug}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# POST /materials
# ---------------------------------------------------------------------------

@app.post("/materials")
def materials():
    """Run Stage 3 materials roll-up.

    Request body — either form is accepted:

      Form A (chain off /protocol):
        { "plan_id": "plan_abc..." }
        — requires the plan to already have a populated `protocol` field.
          If it doesn't, returns 400 telling the FE to call /protocol first.

      Form B (start fresh): same shape as /protocol Form B. Internally
        runs /protocol first, then the roll-up. Slow (~50-70s) but
        convenient for one-shot curl testing.

    Response:
        {
          "plan_id": "...",
          "frontend_view": FEMaterialsView,   // grouped, for ExperimentPlan.tsx
          "raw": MaterialsOutput              // flat shape, for future upgrade
        }
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    # If we got a plan_id whose protocol stage hasn't run yet, surface that
    # explicitly rather than silently re-running it. The FE should call
    # /protocol first; chaining is sequential by design.
    if not is_new and plan.protocol is None:
        return jsonify({
            "error": "protocol_not_run",
            "detail": "This plan has no protocol yet. POST /protocol first, then retry /materials.",
        }), 400

    # Form B: brand-new plan with no protocol yet — run /protocol implicitly.
    if plan.protocol is None:
        started = now()
        plan.status["protocol"] = StageStatusRunning(started_at=started)
        plan.updated_at = started
        plan_lib.save_plan(plan)
        try:
            protocol_out, _outline = protocol_stage.run_protocol_only(plan.hypothesis)
        except Exception as exc:
            return _stage_failed_response("protocol", plan, exc)
        completed = now()
        plan.protocol = protocol_out
        plan.status["protocol"] = StageStatusComplete(completed_at=completed)
        plan.updated_at = completed
        plan_lib.save_plan(plan)

    started = now()
    plan.status["materials"] = StageStatusRunning(started_at=started)
    plan.updated_at = started
    plan_lib.save_plan(plan)

    try:
        materials_out = protocol_stage.run_materials_only(plan.protocol)
    except Exception as exc:
        return _stage_failed_response("materials", plan, exc)

    completed = now()
    plan.materials = materials_out
    plan.status["materials"] = StageStatusComplete(completed_at=completed)
    plan.updated_at = completed
    plan_lib.save_plan(plan)

    return jsonify({
        "plan_id": plan.id,
        # Pass the protocol so adapt_materials populates `used_in_steps`
        # cross-links from each material to the steps that reference it.
        "frontend_view": adapt_materials(materials_out, protocol=plan.protocol).model_dump(mode="json"),
        "raw": materials_out.model_dump(mode="json"),
    })


# ---------------------------------------------------------------------------
# POST /timeline
# ---------------------------------------------------------------------------

@app.post("/timeline")
def timeline():
    """Stage 5: deterministic timeline computation.

    Request body — same `_resolve_plan` shape as /protocol /materials:
      Form A (chain): {"plan_id": "plan_abc..."} — requires the plan to
        have `protocol` populated.
      Form B (fresh): {"structured": {...}} — runs /protocol implicitly
        first. Convenience for curl testing.

    Response:
        {
          "plan_id": "...",
          "timeline": TimelineOutput   // phases, total_duration,
                                       //   critical_path, assumptions,
                                       //   per-phase methodology + coverage
        }

    The compute is purely deterministic (sums step durations) — no LLM
    call. Same protocol -> byte-for-byte same timeline."""
    body = request.get_json(silent=True) or {}

    try:
        plan, is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    # Same chaining rule as /materials: a plan_id with no protocol is
    # an error; new plans run /protocol implicitly.
    if not is_new and plan.protocol is None:
        return jsonify({
            "error": "protocol_not_run",
            "detail": "This plan has no protocol yet. POST /protocol first, then retry /timeline.",
        }), 400

    if plan.protocol is None:
        # Fresh-plan implicit /protocol run
        started = now()
        plan.status["protocol"] = StageStatusRunning(started_at=started)
        plan.updated_at = started
        plan_lib.save_plan(plan)
        try:
            protocol_out, _outline = protocol_stage.run_protocol_only(plan.hypothesis)
        except Exception as exc:
            return _stage_failed_response("protocol", plan, exc)
        completed = now()
        plan.protocol = protocol_out
        plan.status["protocol"] = StageStatusComplete(completed_at=completed)
        plan.updated_at = completed
        plan_lib.save_plan(plan)

    started = now()
    plan.status["timeline"] = StageStatusRunning(started_at=started)
    plan.updated_at = started
    plan_lib.save_plan(plan)

    try:
        timeline_out = protocol_stage.run_timeline_only(plan.protocol)
    except Exception as exc:
        return _stage_failed_response("timeline", plan, exc)

    completed = now()
    plan.timeline = timeline_out
    plan.status["timeline"] = StageStatusComplete(completed_at=completed)
    plan.updated_at = completed
    plan_lib.save_plan(plan)

    return jsonify({
        "plan_id": plan.id,
        "timeline": timeline_out.model_dump(mode="json"),
    })


# ---------------------------------------------------------------------------
# POST /validation
# ---------------------------------------------------------------------------

@app.post("/validation")
def validation():
    """Stage 6: experiment-level validation block.

    Aggregates per-procedure success criteria + controls into experiment-
    level lists, computes a sample-size estimate from hypothesis.expected
    (regex-extracted effect size, standard two-sample t-test formula),
    and runs ONE LLM call for failure modes — each forced to cite a
    specific procedure or step. Citations the parser can't validate are
    dropped, so every concern in the output is grounded.

    Same `_resolve_plan` shape as /protocol /materials /timeline.

    Response:
        {
          "plan_id": "...",
          "validation": ValidationOutput   // success_criteria[], controls[],
                                           //   failure_modes[], power_calculation,
                                           //   methodology
        }
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    # Same chaining rule as /timeline: a plan_id with no protocol is
    # an error; new plans run /protocol implicitly.
    if not is_new and plan.protocol is None:
        return jsonify({
            "error": "protocol_not_run",
            "detail": "This plan has no protocol yet. POST /protocol first, then retry /validation.",
        }), 400

    if plan.protocol is None:
        started = now()
        plan.status["protocol"] = StageStatusRunning(started_at=started)
        plan.updated_at = started
        plan_lib.save_plan(plan)
        try:
            protocol_out, _outline = protocol_stage.run_protocol_only(plan.hypothesis)
        except Exception as exc:
            return _stage_failed_response("protocol", plan, exc)
        completed = now()
        plan.protocol = protocol_out
        plan.status["protocol"] = StageStatusComplete(completed_at=completed)
        plan.updated_at = completed
        plan_lib.save_plan(plan)

    started = now()
    plan.status["validation"] = StageStatusRunning(started_at=started)
    plan.updated_at = started
    plan_lib.save_plan(plan)

    try:
        validation_out = protocol_stage.run_validation_only(plan.hypothesis, plan.protocol)
    except Exception as exc:
        return _stage_failed_response("validation", plan, exc)

    completed = now()
    plan.validation = validation_out
    plan.status["validation"] = StageStatusComplete(completed_at=completed)
    plan.updated_at = completed
    plan_lib.save_plan(plan)

    return jsonify({
        "plan_id": plan.id,
        "validation": validation_out.model_dump(mode="json"),
    })


# ---------------------------------------------------------------------------
# POST /critique
# ---------------------------------------------------------------------------

@app.post("/critique")
def critique():
    """Stage 7: design critique.

    One LLM call audits the protocol against the hypothesis and emits
    risks + confounders. Every entry is REQUIRED to cite a specific
    procedure, step, or hypothesis field; the parser validates against
    the protocol's procedure list and drops ungrounded entries. The
    `recommendation` is recomputed deterministically from the parsed
    risk severities so it always matches the visible risk profile.

    Same `_resolve_plan` shape as /protocol /materials /timeline /validation.

    Response:
        {
          "plan_id": "...",
          "critique": CritiqueOutput   // risks[], confounders[],
                                       //   overall_assessment,
                                       //   recommendation, methodology
        }
    """
    body = request.get_json(silent=True) or {}

    try:
        plan, is_new = _resolve_plan(body)
    except ValidationError as exc:
        return jsonify({"error": "validation_error", "detail": exc.errors()}), 422
    except ValueError as exc:
        return jsonify({"error": "bad_request", "detail": str(exc)}), 400

    if not is_new and plan.protocol is None:
        return jsonify({
            "error": "protocol_not_run",
            "detail": "This plan has no protocol yet. POST /protocol first, then retry /critique.",
        }), 400

    if plan.protocol is None:
        started = now()
        plan.status["protocol"] = StageStatusRunning(started_at=started)
        plan.updated_at = started
        plan_lib.save_plan(plan)
        try:
            protocol_out, _outline = protocol_stage.run_protocol_only(plan.hypothesis)
        except Exception as exc:
            return _stage_failed_response("protocol", plan, exc)
        completed = now()
        plan.protocol = protocol_out
        plan.status["protocol"] = StageStatusComplete(completed_at=completed)
        plan.updated_at = completed
        plan_lib.save_plan(plan)

    started = now()
    plan.status["critique"] = StageStatusRunning(started_at=started)
    plan.updated_at = started
    plan_lib.save_plan(plan)

    try:
        critique_out = protocol_stage.run_critique_only(plan.hypothesis, plan.protocol)
    except Exception as exc:
        return _stage_failed_response("critique", plan, exc)

    completed = now()
    plan.critique = critique_out
    plan.status["critique"] = StageStatusComplete(completed_at=completed)
    plan.updated_at = completed
    plan_lib.save_plan(plan)

    return jsonify({
        "plan_id": plan.id,
        "critique": critique_out.model_dump(mode="json"),
    })


if __name__ == "__main__":
    # Flask's app.run() is for local development only. For deployment
    # (Render / Railway / Fly / Cloud Run / etc.), run with a production
    # WSGI server, e.g.:
    #   gunicorn -b 0.0.0.0:5000 app:app
    # FLASK_DEBUG defaults to "0" so dropping this onto a server doesn't
    # accidentally enable the debugger and reloader.
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

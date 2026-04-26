"""Flask API exposing Stage 1 (Lit Review) for the frontend.

Endpoints:
  GET  /health           Liveness ping
  POST /lit-review       Run Stage 1 on a structured hypothesis; return JSON

Dev:
  python -m flask --app app run --debug --port 5000

Or:
  python app.py
"""

from __future__ import annotations

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

from flask import Flask, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.clients import llm  # noqa: E402
from src.lib import plan as plan_lib  # noqa: E402
from src.types import (  # noqa: E402
    Hypothesis,
    StageStatusComplete,
    StageStatusFailed,
    StageStatusRunning,
    StructuredHypothesis,
    now,
)
from lit_review_pipeline import stage  # noqa: E402


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

        # Return just the editorial result for the FE card. Full plan is
        # persisted to plans/<id>.json on disk for debugging.
        return jsonify(session.initial_result.model_dump(mode="json"))

    except Exception as exc:
        traceback.print_exc()
        # Try to mark the plan as failed if we got that far.
        try:
            if plan is not None:
                plan.status["lit_review"] = StageStatusFailed(failed_at=now(), error=str(exc))
                plan_lib.save_plan(plan)
        except Exception:
            pass
        return jsonify({"error": "pipeline_error", "detail": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

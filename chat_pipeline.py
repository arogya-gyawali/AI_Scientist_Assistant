"""Researcher-driven chat over the experiment-plan blackboard.

The AI Assistant panel in the FE sends `{plan_id, page, message, history}`
to POST /chat. The backend:
  1. Loads the plan.
  2. Builds a system prompt that grounds the LLM in the plan's current state
     and exposes only the tools relevant to the page the user is on
     (`/literature` -> read-only; `/plan` -> protocol + materials mutators).
  3. Calls the LLM in single-turn tool-using mode. The LLM emits any number
     of tool_use blocks alongside an explanatory text reply.
  4. Returns the proposed mutations (NOT applied) plus a human-readable
     summary per mutation, so the FE can render an Apply/Reject card.

Apply happens in a separate POST /chat/apply call after the user clicks
Apply. That endpoint validates each mutation, dispatches it against the
plan, saves, and returns updated `frontend_view` shapes for whichever
stages changed — letting the FE refresh just those sections in place.

Why single-turn (not multi-turn agentic): the propose-then-apply UX
makes a tight loop unnecessary. The LLM grounds answers from the plan
JSON in the system prompt; it does not need to call read tools.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from src.clients import llm
from src.lib import plan as plan_lib
from src.types import (
    ExperimentPlan,
    Material,
    ProtocolGenerationOutput,
    ProtocolStep,
)

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic shape; OpenRouter codepath in llm.py adapts).
# ---------------------------------------------------------------------------
# Field whitelists are intentional: we only let the LLM mutate fields with
# clear semantics where a string-or-bool value is unambiguous. Things like
# `params` (structured) or `procedures` (whole-list) are out of scope until
# we have richer tools — start narrow, expand on demand.

_PROTOCOL_STEP_FIELDS: tuple[str, ...] = (
    "title",
    "body_md",
    "notes",
    "anticipated_outcome",
    "duration",            # ISO 8601 (e.g. "PT15M")
    "is_critical",         # bool — accepts "true"/"false" string
    "is_pause_point",      # bool — accepts "true"/"false" string
)

_MATERIAL_FIELDS: tuple[str, ...] = (
    "qty",                 # numeric — accepts string, parsed to float
    "unit",
    "vendor",
    "sku",
    "purpose",
    "spec",
    "storage",
    "hazard",
)

_MATERIAL_CATEGORIES: tuple[str, ...] = (
    "reagent", "consumable", "equipment", "cell_line", "organism",
)

_TOOL_UPDATE_PROTOCOL_STEP: dict[str, Any] = {
    "name": "update_protocol_step",
    "description": (
        "Modify one field of one protocol step. step_id format is "
        "'p{procedure_index}-s{step_number_in_procedure}', e.g. 'p1-s3' for "
        "the 3rd step of the 1st procedure. Use this for the user's "
        "step-level edit requests like 'change step p1-s3's duration to "
        "15 minutes' or 'mark step p2-s4 as a critical step'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "step_id": {
                "type": "string",
                "description": "Stable step ID, format 'p{procedure_index}-s{step_n}', e.g. 'p1-s3'.",
            },
            "field": {
                "type": "string",
                "enum": list(_PROTOCOL_STEP_FIELDS),
                "description": (
                    "The NAME of the field to update. MUST be exactly one "
                    "of the enum values: 'title', 'body_md', 'notes', "
                    "'anticipated_outcome', 'duration', 'is_critical', or "
                    "'is_pause_point'. Do NOT pass the literal string "
                    "'value' here — 'value' is the next argument, which "
                    "holds the new value you want to set this field to."
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "The new value to set. For duration use ISO 8601 "
                    "(e.g. 'PT15M' for 15 minutes, 'PT1H' for 1 hour). "
                    "For is_critical / is_pause_point pass 'true' or 'false'."
                ),
            },
            "rationale": {
                "type": "string",
                "description": "One short sentence on why this change. Surfaced to the user in the proposal card.",
            },
        },
        "required": ["step_id", "field", "value", "rationale"],
    },
}

_TOOL_ADD_MATERIAL: dict[str, Any] = {
    "name": "add_material",
    "description": (
        "Add a new item to the materials list. Use for 'add antibody X' / "
        "'we'll need a thermocycler' / 'include 1L PBS' type requests."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "category": {"type": "string", "enum": list(_MATERIAL_CATEGORIES)},
            "qty": {"type": "number", "description": "Numeric quantity. Omit if unknown."},
            "unit": {"type": "string", "description": "e.g. 'mL', 'mg', 'units', 'each'."},
            "purpose": {"type": "string", "description": "Equipment only — what it's used for."},
            "spec": {"type": "string", "description": "Equipment only — concrete spec."},
            "rationale": {"type": "string", "description": "One sentence on why this addition is needed."},
        },
        "required": ["name", "category", "rationale"],
    },
}

_TOOL_UPDATE_MATERIAL: dict[str, Any] = {
    "name": "update_material",
    "description": (
        "Change a single field on an existing material item. material_id is "
        "the `id` from the materials list (visible to you in the plan JSON "
        "the system prompt grounds you in)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "material_id": {"type": "string"},
            "field": {
                "type": "string",
                "enum": list(_MATERIAL_FIELDS),
            },
            "value": {
                "type": "string",
                "description": "Pass numbers as strings (e.g. '500'); the dispatcher coerces to float for qty.",
            },
            "rationale": {"type": "string"},
        },
        "required": ["material_id", "field", "value", "rationale"],
    },
}

_TOOL_REMOVE_MATERIAL: dict[str, Any] = {
    "name": "remove_material",
    "description": "Remove a material by id. Use sparingly — prefer update_material when the user is correcting rather than dropping.",
    "input_schema": {
        "type": "object",
        "properties": {
            "material_id": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["material_id", "rationale"],
    },
}

# Page -> tool list. Empty list means read-only.
_TOOLS_BY_PAGE: dict[str, list[dict[str, Any]]] = {
    "/lab": [],          # hypothesis input — no plan to edit yet
    "/literature": [],   # lit-review currently read-only via chat
    "/plan": [
        _TOOL_UPDATE_PROTOCOL_STEP,
        _TOOL_ADD_MATERIAL,
        _TOOL_UPDATE_MATERIAL,
        _TOOL_REMOVE_MATERIAL,
    ],
}


# ---------------------------------------------------------------------------
# Public chat / apply API
# ---------------------------------------------------------------------------

@dataclass
class ProposedMutation:
    id: str          # client-roundtripped; the FE sends the same id back when applying
    tool: str
    arguments: dict[str, Any]
    summary: str     # human-readable, e.g. "Update step p1-s3 duration -> PT15M"

@dataclass
class ChatResponse:
    message: str
    proposed_mutations: list[ProposedMutation]


def chat(
    plan_id: str,
    page: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> ChatResponse:
    """Generate an assistant reply + zero or more proposed mutations.

    The mutations are NOT applied; they round-trip back to /chat/apply
    after the user clicks Apply in the panel.
    """
    plan = plan_lib.load_plan(plan_id)
    tools = _TOOLS_BY_PAGE.get(page, [])
    system_prompt = _build_system_prompt(plan, page=page, has_tools=bool(tools))

    if not tools:
        # Read-only mode: still call the LLM, just without tools, so the
        # user can ask questions about the plan and get grounded answers.
        text = llm.complete(system_prompt, message)
        return ChatResponse(message=text.strip(), proposed_mutations=[])

    result = llm.complete_with_tools(
        system_prompt,
        message,
        tools=tools,
        history=history or [],
    )

    # Pre-validate every tool call against its schema BEFORE we build a
    # ProposedMutation card for the FE. Gemini Flash sometimes ignores
    # the `enum` constraint on `field` and stuffs the literal placeholder
    # name "value" into it (or other off-enum strings), which then bubbles
    # up as a generic apply-time error. Catching it here means the user
    # never sees a card they can't apply.
    proposed: list[ProposedMutation] = []
    dropped: list[tuple[str, str]] = []
    for tc in result.tool_calls:
        validation_error = _validate_tool_call(tc.name, tc.arguments)
        if validation_error:
            dropped.append((tc.name, validation_error))
            continue
        proposed.append(ProposedMutation(
            id=uuid.uuid4().hex,
            tool=tc.name,
            arguments=tc.arguments,
            summary=_summarize_mutation(tc.name, tc.arguments),
        ))

    # Resolve the assistant's text. Three cases:
    #   a) LLM produced text + valid proposals → show text, render proposals
    #   b) LLM produced only valid proposals → friendly default text
    #   c) LLM produced only unknown-tool calls → translate the intent
    #      into useful prose so the user gets a real response, not
    #      "Done. (Skipped …)" which reads like a non-answer.
    text = (result.text or "").strip()
    if not text:
        if proposed:
            text = (
                f"I'd make {len(proposed)} change"
                f"{'' if len(proposed) == 1 else 's'} — review below."
            )
        elif dropped:
            text = _explain_dropped_tools(dropped)
        else:
            text = "Done."
    elif dropped and not proposed:
        # The LLM said something AND tried unknown tools — suffix the
        # explanation so the user knows the requested action wasn't taken.
        text = text + "\n\n" + _explain_dropped_tools(dropped)

    return ChatResponse(message=text, proposed_mutations=proposed)


def _explain_dropped_tools(dropped: list[tuple[str, str]]) -> str:
    """Translate a list of (tool_name, validation_error) into a useful
    prose response. The LLM hallucinates tool names sometimes — for
    those, point the user at where they CAN make that change. For
    schema-violation cases (real tool, bad args), just say what failed
    and ask them to retry."""
    # Bucket by intent. The most common hallucination is the LLM trying
    # to edit the hypothesis (e.g. update_hypothesis_field) — which we
    # don't expose because mutating the hypothesis invalidates the
    # downstream protocol/materials/critique cascade. Direct the user
    # back to /lab where the hypothesis is owned.
    hypothesis_attempt = any(
        "hypothesis" in name.lower() for name, _ in dropped
    )
    schema_failures = [
        (name, err) for name, err in dropped
        if not name.lower().startswith("update_hypothesis")
        and "unknown tool" not in err
    ]

    parts: list[str] = []
    if hypothesis_attempt:
        parts.append(
            "I can't edit the hypothesis from here — changing it would "
            "invalidate the protocol, materials, and validation that "
            "are already grounded on the current version. Head back to "
            "the Lab page to revise the hypothesis (subject, "
            "intervention, measurement, conditions, or expected outcome) "
            "and the rest of the plan will regenerate against your new "
            "framing. Want suggestions for how to reword it before you "
            "go?"
        )
    if schema_failures:
        for name, err in schema_failures:
            parts.append(f"I tried to call `{name}` but {err}. Try rephrasing.")
    if not parts:
        # Last-resort: surface the raw drop list so the user at least
        # knows something happened.
        parts.append("I tried to make a change, but the call didn't validate. Try rephrasing.")
    return "\n\n".join(parts)


@dataclass
class ApplyError:
    mutation_id: str
    error: str

@dataclass
class ApplyResult:
    plan_id: str
    applied_ids: list[str]
    errors: list[ApplyError]
    # Map of stage-name -> arbitrary frontend_view dict. Server fills only
    # the stages that actually changed so the FE knows which sections to
    # refresh in place. Computed by the caller after apply (app.py).
    affected_stages: list[str]


def apply_mutations(
    plan_id: str,
    mutations: list[dict[str, Any]],
) -> ApplyResult:
    """Validate + apply previously-proposed mutations and persist the plan.

    `mutations` is the list returned in `proposed_mutations` round-tripped
    from the FE. Each entry is `{id, tool, arguments}`. We dispatch by
    tool name, accumulate errors per-mutation rather than aborting the
    batch (so a partial success still saves), and return the set of
    stages that were touched so the FE can refetch + replace.
    """
    plan = plan_lib.load_plan(plan_id)
    applied: list[str] = []
    errors: list[ApplyError] = []
    affected: set[str] = set()

    for m in mutations:
        mid = str(m.get("id") or uuid.uuid4().hex)
        tool = m.get("tool")
        args = m.get("arguments") or {}
        try:
            stage = _dispatch(plan, str(tool), args)
            applied.append(mid)
            if stage:
                affected.add(stage)
        except Exception as exc:  # noqa: BLE001 — we want to surface anything
            errors.append(ApplyError(mutation_id=mid, error=str(exc)))

    if applied:
        plan_lib.save_plan(plan)

    return ApplyResult(
        plan_id=plan_id,
        applied_ids=applied,
        errors=errors,
        affected_stages=sorted(affected),
    )


# ---------------------------------------------------------------------------
# Internals — system prompt, dispatch, mutators
# ---------------------------------------------------------------------------

def _build_system_prompt(plan: ExperimentPlan, *, page: str, has_tools: bool) -> str:
    plan_excerpt = _excerpt_plan_for_page(plan, page=page)
    tools_clause = (
        # Tools-available branch (e.g. /plan).
        # Two failure modes the previous prompt fell into:
        #   - Refusing aspirational asks ("make this cooler", "improve it")
        #     because no single tool maps cleanly onto them.
        #   - Asking the LLM to "always" use tools when the user is just
        #     curious ("why was this protocol chosen?"), which forced
        #     tool calls onto question-shaped messages.
        # Fix: be explicit that tools are for CONCRETE field-level edits,
        # and that aspirational / open-ended asks should be answered in
        # prose with 2-4 specific suggestions the user can ask follow-ups
        # on. The propose-then-apply loop only triggers when the LLM
        # actually emits a tool_use block.
        "Two response modes:\n"
        "  1. CONCRETE EDITS — when the user asks for a specific change "
        "('mark step p1-s3 as critical', 'change duration to 15 minutes', "
        "'add 1 L PBS to materials'), propose it via the available tools. "
        "One change per tool call; include a one-sentence rationale that "
        "the user sees.\n"
        "  2. SUGGESTIONS / DISCUSSION — when the user asks something "
        "open-ended ('make it cooler', 'improve this', 'why is X done this "
        "way?', 'what are the risks?'), answer in prose. For improvement "
        "asks, list 2-4 SPECIFIC, plan-grounded suggestions ('add a "
        "no-ATP control to step p2-s3', 'increase the wash volume from "
        "1 mL to 2 mL'). The user can then ask you to apply any of them "
        "as a follow-up — that triggers the tool call.\n\n"
        "Never refuse a vague request. If 'make it cooler' is too vague, "
        "interpret it generously (more rigorous? more publishable? "
        "tighter controls?) and propose concrete suggestions in prose."
        if has_tools else
        "You have no tools on this page; answer questions about the plan "
        "in prose. Be concrete and grounded in the JSON below — if the "
        "user asks an aspirational question, give 2-4 specific suggestions "
        "rather than a generic answer."
    )
    return (
        "You are Praxis, a research assistant embedded in an experiment-plan UI. "
        "Be precise, terse, and grounded in the plan below. Do not invent fields, "
        "ids, or values that aren't in the JSON. But DO offer suggestions and "
        "interpretations — refusing to engage with an aspirational ask "
        "('make this cooler') is the wrong move; reinterpret it generously "
        "and answer with specifics from the plan.\n\n"
        f"{tools_clause}\n\n"
        f"Current page: {page}\n\n"
        "Current plan (JSON excerpt):\n"
        f"```json\n{plan_excerpt}\n```"
    )


def _excerpt_plan_for_page(plan: ExperimentPlan, *, page: str) -> str:
    """Return a JSON excerpt scoped to what the LLM needs for this page.

    Why excerpt rather than dump the full plan: a full plan is ~50KB; the
    LLM doesn't need feedback / status / regulatory_requirements to answer
    "rename step p1-s3". Trimming keeps prompt tokens down and grounds the
    LLM in the part it actually edits.
    """
    payload: dict[str, Any] = {
        "plan_id": plan.id,
        "hypothesis": _model_to_dict_safe(plan.hypothesis),
    }
    if page == "/plan":
        if plan.protocol:
            payload["protocol"] = _summarize_protocol(plan.protocol)
        if plan.materials:
            payload["materials"] = _model_to_dict_safe(plan.materials)
    elif page == "/literature" and plan.lit_review:
        payload["lit_review"] = _model_to_dict_safe(plan.lit_review)
    return json.dumps(payload, indent=2, default=str)


def _summarize_protocol(protocol: ProtocolGenerationOutput) -> dict[str, Any]:
    """Compact protocol view: list step IDs + titles + duration only.

    The LLM rarely needs body_md to choose a tool call; surfacing every
    step's full prose would balloon the prompt. We include enough to
    reference steps unambiguously and let it ask follow-up questions
    if it needs more.
    """
    procs: list[dict[str, Any]] = []
    for p_idx, proc in enumerate(protocol.procedures, start=1):
        steps: list[dict[str, Any]] = []
        for s_idx, step in enumerate(proc.steps, start=1):
            steps.append({
                "step_id": f"p{p_idx}-s{s_idx}",
                "title": step.title,
                "duration": step.duration,
                "is_critical": step.is_critical,
                "is_pause_point": step.is_pause_point,
            })
        procs.append({
            "procedure_index": p_idx,
            "name": proc.name,
            "intent": proc.intent,
            "steps": steps,
        })
    return {
        "experiment_type": protocol.experiment_type,
        "total_steps": protocol.total_steps,
        "procedures": procs,
    }


def _model_to_dict_safe(model: Any) -> Any:
    """pydantic v2 .model_dump() with sensible JSON-friendly defaults."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


def _validate_tool_call(tool: str, args: dict[str, Any]) -> str | None:
    """Return None if the tool call matches its schema, else a short
    human-readable reason. Used to drop malformed proposals before they
    reach the FE, so the user never sees an Apply card that errors.

    Mirrors the constraints baked into the tool schemas in
    `_TOOL_UPDATE_PROTOCOL_STEP` etc. — if the LLM ignored the `enum`
    on `field` (Gemini Flash has been seen passing the literal
    placeholder "value"), we catch it here. We DON'T validate types
    deeply (the dispatcher does) — just the fields the LLM most often
    gets wrong."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    if tool == "update_protocol_step":
        if not args.get("step_id"):
            return "missing step_id"
        field = args.get("field")
        if field not in _PROTOCOL_STEP_FIELDS:
            return f"field must be one of {list(_PROTOCOL_STEP_FIELDS)} (got {field!r})"
        if "value" not in args:
            return "missing value"
        return None
    if tool == "add_material":
        if not args.get("name"):
            return "missing name"
        cat = args.get("category")
        if cat not in _MATERIAL_CATEGORIES:
            return f"category must be one of {list(_MATERIAL_CATEGORIES)} (got {cat!r})"
        return None
    if tool == "update_material":
        if not args.get("material_id"):
            return "missing material_id"
        field = args.get("field")
        if field not in _MATERIAL_FIELDS:
            return f"field must be one of {list(_MATERIAL_FIELDS)} (got {field!r})"
        if "value" not in args:
            return "missing value"
        return None
    if tool == "remove_material":
        if not args.get("material_id"):
            return "missing material_id"
        return None
    return f"unknown tool {tool!r}"


def _summarize_mutation(tool: str, args: dict[str, Any]) -> str:
    rationale = args.get("rationale", "").strip()
    if tool == "update_protocol_step":
        base = f"Update step {args.get('step_id')}: {args.get('field')} -> {args.get('value')}"
    elif tool == "add_material":
        qty_unit = ""
        if args.get("qty") is not None:
            qty_unit = f" — {args.get('qty')} {args.get('unit') or ''}".rstrip()
        base = f"Add material '{args.get('name')}' ({args.get('category')}){qty_unit}"
    elif tool == "update_material":
        base = f"Update material {args.get('material_id')}: {args.get('field')} -> {args.get('value')}"
    elif tool == "remove_material":
        base = f"Remove material {args.get('material_id')}"
    else:
        base = f"{tool}({args})"
    return f"{base}. {rationale}" if rationale else base


def _dispatch(plan: ExperimentPlan, tool: str, args: dict[str, Any]) -> str | None:
    """Apply one mutation in place. Returns the stage name affected."""
    if tool == "update_protocol_step":
        return _apply_update_protocol_step(plan, args)
    if tool == "add_material":
        return _apply_add_material(plan, args)
    if tool == "update_material":
        return _apply_update_material(plan, args)
    if tool == "remove_material":
        return _apply_remove_material(plan, args)
    raise ValueError(f"Unknown tool: {tool}")


# ---- protocol step mutator ------------------------------------------------

def _apply_update_protocol_step(plan: ExperimentPlan, args: dict[str, Any]) -> str:
    if not plan.protocol:
        raise ValueError("Plan has no protocol — run Stage 2 first.")
    step_id = str(args.get("step_id") or "")
    field = str(args.get("field") or "")
    value = args.get("value")
    if field not in _PROTOCOL_STEP_FIELDS:
        raise ValueError(f"Field '{field}' is not editable via chat.")

    proc_idx, step_n = _parse_step_id(step_id)
    step = _find_step(plan.protocol, proc_idx, step_n)

    coerced = _coerce_step_field(field, value)
    setattr(step, field, coerced)

    # The flat `steps` list mirrors the per-procedure steps; rebuild it so
    # consumers reading from either shape see the change.
    plan.protocol.steps = _flatten_steps(plan.protocol)
    return "protocol"


def _parse_step_id(step_id: str) -> tuple[int, int]:
    # Format: "p{procedure_index}-s{step_n}", both 1-based. Tolerate a
    # missing 'p' prefix in case the LLM elides it.
    raw = step_id.strip().lower().lstrip("p")
    parts = raw.split("-s")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Invalid step_id: {step_id!r}. Expected 'p1-s3'-style.")
    return int(parts[0]), int(parts[1])


def _find_step(protocol: ProtocolGenerationOutput, proc_idx: int, step_n: int) -> ProtocolStep:
    if proc_idx < 1 or proc_idx > len(protocol.procedures):
        raise ValueError(f"procedure_index {proc_idx} out of range (have {len(protocol.procedures)}).")
    proc = protocol.procedures[proc_idx - 1]
    if step_n < 1 or step_n > len(proc.steps):
        raise ValueError(f"step_n {step_n} out of range for procedure {proc_idx} (has {len(proc.steps)} steps).")
    return proc.steps[step_n - 1]


def _coerce_step_field(field: str, value: Any) -> Any:
    if field in ("is_critical", "is_pause_point"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "y", "1")
    return None if value in (None, "") else str(value)


def _flatten_steps(protocol: ProtocolGenerationOutput) -> list[ProtocolStep]:
    flat: list[ProtocolStep] = []
    n = 1
    for proc in protocol.procedures:
        for s in proc.steps:
            # Re-number n on the flat view so it stays sequential after edits.
            s.n = n
            flat.append(s)
            n += 1
    return flat


# ---- material mutators ---------------------------------------------------

def _apply_add_material(plan: ExperimentPlan, args: dict[str, Any]) -> str:
    if not plan.materials:
        raise ValueError("Plan has no materials yet — run Stage 3 first.")
    name = str(args.get("name") or "").strip()
    if not name:
        raise ValueError("Material name is required.")
    category = str(args.get("category") or "")
    if category not in _MATERIAL_CATEGORIES:
        raise ValueError(f"Invalid category {category!r}.")

    qty_raw = args.get("qty")
    qty: float | None = None
    if qty_raw not in (None, ""):
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"qty must be numeric, got {qty_raw!r}.") from exc

    new_mat = Material(
        id=f"m_{uuid.uuid4().hex[:10]}",
        name=name,
        category=category,  # type: ignore[arg-type]
        qty=qty,
        unit=_optstr(args.get("unit")),
        purpose=_optstr(args.get("purpose")),
        spec=_optstr(args.get("spec")),
    )
    plan.materials.materials.append(new_mat)
    plan.materials.total_unique_items = len(plan.materials.materials)
    plan.materials.by_category = _recount_by_category(plan.materials.materials)
    return "materials"


def _apply_update_material(plan: ExperimentPlan, args: dict[str, Any]) -> str:
    if not plan.materials:
        raise ValueError("Plan has no materials yet.")
    material_id = str(args.get("material_id") or "")
    field = str(args.get("field") or "")
    value = args.get("value")
    if field not in _MATERIAL_FIELDS:
        raise ValueError(f"Field '{field}' is not editable via chat.")
    mat = _find_material(plan, material_id)

    if field == "qty":
        coerced: Any
        if value in (None, ""):
            coerced = None
        else:
            try:
                coerced = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"qty must be numeric, got {value!r}.") from exc
    else:
        coerced = _optstr(value)
    setattr(mat, field, coerced)
    return "materials"


def _apply_remove_material(plan: ExperimentPlan, args: dict[str, Any]) -> str:
    if not plan.materials:
        raise ValueError("Plan has no materials yet.")
    material_id = str(args.get("material_id") or "")
    before = len(plan.materials.materials)
    plan.materials.materials = [m for m in plan.materials.materials if m.id != material_id]
    if len(plan.materials.materials) == before:
        raise ValueError(f"Material {material_id!r} not found.")
    plan.materials.total_unique_items = len(plan.materials.materials)
    plan.materials.by_category = _recount_by_category(plan.materials.materials)
    return "materials"


def _find_material(plan: ExperimentPlan, material_id: str) -> Material:
    assert plan.materials is not None
    for m in plan.materials.materials:
        if m.id == material_id:
            return m
    raise ValueError(f"Material {material_id!r} not found.")


def _recount_by_category(mats: list[Material]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in mats:
        counts[m.category] = counts.get(m.category, 0) + 1
    return counts


def _optstr(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

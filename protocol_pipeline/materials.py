"""Materials roll-up agent.

Single LLM call after all writers finish. Input: the completed Procedures.
Output: a deduplicated MaterialsOutput where every equipment item has a
concrete spec (e.g., "benchtop centrifuge, >=3000g, refrigerated") and a
purpose ("cell pelleting"), reagents have quantities + units where
calculable, and the LLM flags `gaps` for items it couldn't ground.

Why deferred to the end (vs. emitted per-procedure):
  - Procedures share equipment ("centrifuge" appears in 3 procedures);
    rolling up first lets the LLM dedupe AND consolidate quantities
    ("PBS: 4 procedures need 50mL, 100mL, 20mL, 30mL → procure 250mL").
  - Equipment specs benefit from cross-procedure context (you don't know
    what speed the centrifuge needs to support until you've seen all the
    spin steps).
  - Stage 4 (Budget) reads MaterialsOutput; one consolidated list is the
    right shape for catalog-number / supplier lookups.

vendor/sku stay None — Stage 4 backfills them.
"""

from __future__ import annotations

import uuid
from collections import Counter

from src.clients import llm
from src.types import Material, MaterialsOutput, Procedure


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

ROLLUP_SYSTEM = """You consolidate the materials and equipment for a multi-procedure experiment plan.

You receive: a list of procedures. Each has a list of equipment names, reagent names, and detailed steps. Equipment and reagent names are likely to repeat across procedures.

Your job:
1. DEDUPLICATE. "Centrifuge" appearing in 3 procedures is one Material, not three.
2. For each EQUIPMENT item, write a concrete `spec` (sufficient for ordering or finding in a lab) AND a one-phrase `purpose`. Examples:
   - spec: "benchtop centrifuge, >=3000g, refrigerated 4 °C"; purpose: "cell pelleting"
   - spec: "automated cell counter or hemocytometer with disposable counting chambers"; purpose: "viability quantification"
   The spec must be executable — a researcher should be able to take it to a procurement portal.
3. For each REAGENT, give a total quantity + unit when calculable from the steps; leave qty/unit null if quantities aren't discoverable from the procedures.
4. Categorize each item: 'reagent' | 'consumable' | 'equipment' | 'cell_line' | 'organism'.
5. Flag GAPS — items the procedures clearly need but you can't fully ground (e.g., "specific manufacturer of trehalose was not specified", "cell density per vial was not given").

Hard rules:
- Do NOT invent items the procedures don't reference.
- Do NOT include vendor or SKU — a downstream stage handles supplier lookup.
- Hazards (e.g., "DMSO: skin contact, use gloves; flammable") are encouraged where genuinely applicable.
- Storage notes (e.g., "store at -20 °C", "refrigerate, 4 °C") are encouraged where relevant.

Return ONLY a single valid JSON object:
{
  "materials": [
    {
      "name": "string",
      "category": "reagent" | "consumable" | "equipment" | "cell_line" | "organism",
      "qty": number or null,
      "unit": "string or null",
      "spec": "string or null (equipment only)",
      "purpose": "string or null (equipment only)",
      "storage": "string or null",
      "hazard": "string or null",
      "alternatives": ["string"]
    }
  ],
  "gaps": ["string"]
}"""

ROLLUP_USER_TMPL = """Procedures ({n}):
{procedures_blob}"""


def _format_procedure(p: Procedure) -> str:
    step_lines = []
    for s in p.steps:
        # Compact: title + key params (vol/temp/conc only, the most material-relevant)
        params_bits = []
        if s.params.volume:       params_bits.append(f"V={s.params.volume.value}{s.params.volume.unit}")
        if s.params.temperature:  params_bits.append(f"T={s.params.temperature.value}{s.params.temperature.unit}")
        if s.params.concentration: params_bits.append(f"C={s.params.concentration.value}{s.params.concentration.unit}")
        params_str = " " + " ".join(params_bits) if params_bits else ""
        step_lines.append(f"    {s.n}. {s.title}{params_str}")
        if s.equipment_needed: step_lines.append(f"       equipment: {', '.join(s.equipment_needed)}")
        if s.reagents_referenced: step_lines.append(f"       reagents: {', '.join(s.reagents_referenced)}")
    return (
        f"  Procedure: {p.name}\n"
        f"    intent: {p.intent}\n"
        f"    procedure-level equipment: {p.equipment}\n"
        f"    procedure-level reagents: {p.reagents}\n"
        f"    steps:\n" + "\n".join(step_lines)
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def roll_up_materials(procedures: list[Procedure]) -> MaterialsOutput:
    if not procedures:
        return MaterialsOutput(materials=[], total_unique_items=0, by_category={}, gaps=[])

    blob = "\n\n".join(_format_procedure(p) for p in procedures)
    user = ROLLUP_USER_TMPL.format(n=len(procedures), procedures_blob=blob)

    parsed = llm.complete_json(ROLLUP_SYSTEM, user, agent_name="Materials roll-up")

    materials = _build_materials(parsed.get("materials") or [])
    gaps = [str(x) for x in (parsed.get("gaps") or [])]

    by_category: Counter[str] = Counter(m.category for m in materials)
    return MaterialsOutput(
        materials=materials,
        total_unique_items=len(materials),
        by_category=dict(by_category),
        gaps=gaps,
    )


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------

_VALID_CATEGORIES = {"reagent", "consumable", "equipment", "cell_line", "organism"}


def _build_materials(raw: list) -> list[Material]:
    out: list[Material] = []
    seen_names: set[str] = set()  # belt-and-suspenders dedup if LLM repeats
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        # Case-insensitive dedup on name (LLM sometimes returns "PBS" and "pbs").
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)

        cat = item.get("category")
        if cat not in _VALID_CATEGORIES:
            cat = "consumable"  # safe fallback

        qty = item.get("qty")
        if qty is not None:
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = None

        # Single-lookup pattern for optional string fields: read once into a
        # local, coerce to str only if truthy. Faster than .get + ["..."]
        # and avoids the readability cost of repeated dict access.
        unit = item.get("unit")
        spec = item.get("spec")
        purpose = item.get("purpose")
        storage = item.get("storage")
        hazard = item.get("hazard")
        out.append(Material(
            id=f"mat_{uuid.uuid4().hex[:10]}",
            name=name,
            category=cat,
            qty=qty,
            unit=str(unit) if unit else None,
            spec=str(spec) if spec else None,
            purpose=str(purpose) if purpose else None,
            storage=str(storage) if storage else None,
            hazard=str(hazard) if hazard else None,
            alternatives=[str(x) for x in (item.get("alternatives") or [])],
        ))
    return out

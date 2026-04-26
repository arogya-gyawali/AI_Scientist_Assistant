"""Materials enrichment — Tavily search + LLM extraction for supplier
catalog # / price.

Pipeline shape:

    Protocol → Materials → adapt_materials (FE shape) → enrich_materials_view

Why "after adapt_materials":
  - The view is already grouped + named the way the FE renders, so we
    walk it once and mutate items in place.
  - We don't need anything from the rich BE shape that the FE view
    doesn't already carry (name, qty, material_id).

Defensibility / reproducibility:
  - Tavily searches go through the existing `src/clients/tavily.py`
    cache (30-day TTL on supplier searches), so identical material
    names across runs hit the same upstream URLs.
  - The extractor is one LLM call per item. Output schema requires
    `source_url` — without a citation, the parser drops the entry
    and the FE falls back to "TBD" / null. Same defensibility
    pattern as Phase D (critique) and Phase E (key_differences).
  - Conservative: any extractor failure (no Tavily hits, LLM error,
    no source_url, ambiguous results) leaves the item's enrichment
    fields null. We never fabricate a supplier or a price.

Out of scope (for now):
  - Quantity-aware pricing (we surface whatever pack-size pricing
    Tavily lands on; downstream Stage 4 budget can re-search at
    the right size).
  - Currency conversion (return whatever currency the source page
    quotes; FE renders verbatim).
  - Supplier preference / fallback ranking (current behavior: take
    Tavily's top result whose domain is on the SUPPLIER_DOMAINS
    allowlist).
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from urllib.parse import urlparse

from src.clients import llm
from src.clients import tavily as tavily_client

from .frontend_view import FEMaterialsView, FEReagent


_LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# LLM extractor
# --------------------------------------------------------------------------
# We prompt the LLM to read the Tavily search snippets and pick out
# {supplier, catalog, price, source_url}. The schema enforces source_url
# so every enriched field is auditable to a specific URL — fabrications
# without a source get dropped.

EXTRACT_SYSTEM = """You extract supplier procurement data from web search results.

You will receive a material name (e.g. "Glucose", "DMEM media", "1.5 mL microcentrifuge tubes") and 1-3 web search result snippets from supplier domains (Sigma-Aldrich, ThermoFisher, Promega, Qiagen, etc.).

Your job: pick the SINGLE result that best matches the material and extract:
- supplier        (e.g. "Sigma-Aldrich")
- catalog         (the supplier's catalog / SKU / part number, e.g. "G8270")
- price           (the listed price + pack size, e.g. "$45 / 500g". If missing, return null.)
- source_url      (the URL of the result you extracted from — REQUIRED)

Hard rules:
- Pick a result ONLY if it matches the material name. A "Glucose meter" page is NOT a match for "Glucose"; "Trypsin-EDTA" is NOT a match for "Trypsin".
- If NO result matches confidently, return all-null fields. Do not guess.
- Do not invent catalog numbers. If the snippet doesn't show the SKU, leave catalog null.
- Do not invent prices. If the snippet doesn't show a price, leave price null.
- source_url is REQUIRED whenever any other field is non-null. If you can't tie a value to a specific URL, return all-null.

Return ONLY a single valid JSON object:
{
  "supplier": "string | null",
  "catalog": "string | null",
  "price": "string | null",
  "source_url": "string | null",
  "match_confidence": "high" | "medium" | "low"
}"""


EXTRACT_USER_TMPL = """Material name: {name}
Material purpose: {purpose}

Search results ({n}):
{results_blob}"""


def _format_results(results: list[dict]) -> str:
    """Format Tavily results into a compact LLM-readable blob. We pass
    title + url + content snippet — enough for the LLM to recognize a
    matching product page and pluck the catalog / price."""
    lines: list[str] = []
    for i, r in enumerate(results[:3]):
        title = r.get("title") or "(no title)"
        url = r.get("url") or ""
        snippet = (r.get("content") or "")[:500]
        lines.append(
            f"[{i}] {title}\n"
            f"    URL: {url}\n"
            f"    {snippet}"
        )
    return "\n\n".join(lines) or "(no results)"


def _extract_one(
    name: str,
    purpose: str,
    results: list[dict],
) -> dict[str, Optional[str]]:
    """Single LLM call that picks the best-matching result and extracts
    the procurement fields. Returns a dict with `supplier`, `catalog`,
    `price`, `source_url` all `None` when no confident match was found
    (which the FE renders as the default 'TBD' state)."""
    null_result: dict[str, Optional[str]] = {
        "supplier": None,
        "catalog": None,
        "price": None,
        "source_url": None,
    }
    if not results:
        return null_result

    user = EXTRACT_USER_TMPL.format(
        name=name,
        purpose=purpose or "(not specified)",
        n=len(results),
        results_blob=_format_results(results),
    )

    try:
        parsed = llm.complete_json(
            EXTRACT_SYSTEM,
            user,
            agent_name="Materials enrichment",
        )
    except Exception as exc:
        _LOG.warning("Materials enrichment LLM call failed for %r: %s", name, exc)
        return null_result

    if not isinstance(parsed, dict):
        return null_result

    src = parsed.get("source_url")
    if not isinstance(src, str) or not src.strip():
        # No source URL → can't audit. Drop everything.
        return null_result

    # Validate the URL parses; otherwise the source claim is unverifiable.
    try:
        if not urlparse(src.strip()).netloc:
            return null_result
    except Exception:
        return null_result

    confidence = str(parsed.get("match_confidence") or "").lower()
    if confidence == "low":
        # The LLM itself flagged this as uncertain — better to render
        # "TBD" than mislead the researcher.
        return null_result

    def _clean(v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() in {"null", "none", "n/a", "tbd", "-"}:
            return None
        # Cap length so a malformed extractor can't bloat the FE
        if len(s) > 200:
            s = s[:200] + "…"
        return s

    return {
        "supplier": _clean(parsed.get("supplier")),
        "catalog": _clean(parsed.get("catalog")),
        "price": _clean(parsed.get("price")),
        "source_url": src.strip(),
    }


# --------------------------------------------------------------------------
# Per-item enrichment
# --------------------------------------------------------------------------

def _query_for(item: FEReagent) -> str:
    """Build the Tavily query for a single item. Just the name on the
    supplier-domain-filtered search is usually enough; the existing
    `search_for_supplier` helper already appends 'catalog number' and
    scopes to the SUPPLIER_DOMAINS allowlist."""
    return (item.name or "").strip()


# --------------------------------------------------------------------------
# Price fallback (raw-content search)
# --------------------------------------------------------------------------
# The basic-depth supplier search returns short snippets — many product
# pages (notably ThermoFisher) hide price behind a region selector or
# JS-rendered widget that doesn't appear in the snippet. When that
# happens, supplier + catalog come back populated but price is null.
#
# Fix: do a *second* targeted search via the existing
# `search_for_pricing` helper, which uses include_raw_content=True and
# is scoped to the single supplier domain we already identified.
# Run a regex pass over the full page content for common price formats
# first (no LLM cost, deterministic). LLM fallback only when regex
# misses, since the page text is large and the cost is non-trivial.

# Currency-amount patterns. Order: most specific first so we don't
# accept "00" as a standalone price when "474,00 EUR" is in the same
# page. Captures up to ~30 chars of trailing context for the unit
# (e.g. "/ 500 g", "per 100 mL").
_PRICE_PATTERNS = [
    # USD / EUR / GBP with symbol, comma OR dot decimal, optional pack-size suffix.
    re.compile(
        r"(?P<sym>\$|€|£)\s*(?P<amt>\d{1,3}(?:[,.]\d{3})*(?:[.,]\d{2})?)"
        r"(?:\s*(?:/|per|each|each\s+for|for)\s*(?P<unit>\d+\s*(?:[a-zA-Z]+\s*)?(?:x\s*\d+\s*[a-zA-Z]+)?))?",
        re.IGNORECASE,
    ),
    # Trailing-currency form: "474,00 EUR / 20 x 100 ml"
    re.compile(
        r"(?P<amt>\d{1,3}(?:[,.]\d{3})*(?:[.,]\d{2})?)\s*"
        r"(?P<sym>USD|EUR|GBP|JPY|CHF|CAD|AUD)"
        r"(?:\s*(?:/|per)\s*(?P<unit>\d+\s*(?:[a-zA-Z]+\s*)?(?:x\s*\d+\s*[a-zA-Z]+)?))?",
        re.IGNORECASE,
    ),
]


def _regex_price_from_content(content: str) -> Optional[str]:
    """Scan raw page content for a price string. Returns the first
    match formatted as e.g. '$48.50 / 500g' — preserving the source
    page's currency + format rather than fabricating a USD figure.
    Returns None when nothing matches; caller falls back to LLM."""
    if not content:
        return None
    text = content[:8000]  # cap so we don't run regex over a 100kb page
    for pat in _PRICE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        amt = (m.group("amt") or "").strip()
        sym = (m.group("sym") or "").strip()
        unit = (m.group("unit") or "").strip()
        if not amt:
            continue
        # Reject single-digit "amounts" — usually false matches like
        # "1 EUR" inside a "+1 EUR shipping" line.
        digits_only = re.sub(r"[^\d]", "", amt)
        if len(digits_only) < 2:
            continue
        # Prefix or suffix the symbol depending on which pattern hit.
        if sym in {"$", "€", "£"}:
            head = f"{sym}{amt}"
        else:
            head = f"{amt} {sym.upper()}"
        if unit:
            return f"{head} / {unit}"[:200]
        return head[:200]
    return None


_PRICE_LLM_SYSTEM = """You extract a single product price from a supplier-page text dump.

You receive:
  - The product name
  - The supplier domain
  - The full text of the supplier's product page

Return ONLY a JSON object:
{
  "price": "string | null",
  "found_in_text": "string | null"
}

`price` should be the listed price WITH currency symbol/code AND pack size when visible. Examples: "$48.50 / 500 g", "€474,00 / 20 x 100 mL", "1,295.00 USD".

`found_in_text` is the literal substring (≤80 chars) from the page where you saw the price. REQUIRED whenever price is non-null. If no price is visible, return both fields null. Do not fabricate."""


def _llm_price_from_content(name: str, domain: str, content: str) -> Optional[str]:
    """Last-resort LLM extraction over raw page content. Drops anything
    where the LLM can't quote the literal substring it pulled from."""
    if not content:
        return None
    user = (
        f"Product: {name}\nSupplier domain: {domain}\n\n"
        f"Page text:\n{content[:6000]}"
    )
    try:
        parsed = llm.complete_json(_PRICE_LLM_SYSTEM, user, agent_name="Materials price")
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    price = parsed.get("price")
    snippet = parsed.get("found_in_text")
    if not isinstance(price, str) or not price.strip():
        return None
    if not isinstance(snippet, str) or not snippet.strip():
        # No grounding citation — drop it (matches the source_url
        # discipline elsewhere in this module).
        return None
    if snippet.strip() not in content:
        # The "literal substring" wasn't actually in the content. The
        # LLM hallucinated. Drop.
        return None
    return price.strip()[:200]


def _fetch_price_for(supplier: str, source_url: str, catalog: str, name: str) -> Optional[str]:
    """Second-pass price search. Triggered only when supplier + catalog
    are known but price came back null from the snippet-based extract.
    Pricing search uses include_raw_content=True so we get the full
    page text — much higher chance of finding a price string."""
    try:
        domain = urlparse(source_url).netloc.lower()
    except Exception:
        return None
    if not domain:
        return None
    try:
        response = tavily_client.search_for_pricing(supplier, domain, catalog)
    except Exception as exc:
        _LOG.warning("Tavily pricing search failed for %r (%s): %s",
                     name, catalog, exc)
        return None
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or not results:
        return None
    raw = (results[0].get("raw_content") or results[0].get("content") or "").strip()
    if not raw:
        return None
    # Try regex first (free, deterministic). LLM fallback if it misses.
    found = _regex_price_from_content(raw)
    if found:
        return found
    return _llm_price_from_content(name, domain, raw)


def enrich_one_item(item: FEReagent) -> FEReagent:
    """Fetch supplier/catalog/price for one material via Tavily +
    LLM extraction. Two passes:

      1. Snippet-based search (`search_for_supplier`) +
         `_extract_one` LLM call. Usually finds supplier + catalog;
         finds price only when the snippet happens to include it
         (Sigma often does, ThermoFisher rarely).

      2. If supplier + catalog were found but price is still null,
         fall back to a price-targeted full-content search via
         `search_for_pricing`. Tries regex over the raw page text
         first (free, deterministic); LLM with substring-grounding
         only if regex misses.

    Returns a new FEReagent with enrichment fields populated where
    extraction succeeded; original fields unchanged when extraction
    fails. Never mutates the input."""
    name = (item.name or "").strip()
    if not name or len(name) < 3:
        return item

    try:
        response = tavily_client.search_for_supplier(name)
    except Exception as exc:
        _LOG.warning("Tavily supplier search failed for %r: %s", name, exc)
        return item

    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or not results:
        return item

    extracted = _extract_one(name, item.purpose or "", results)

    # Apply only when we got a non-null source URL; otherwise leave the
    # item's existing values (the model_copy below is a no-op when
    # everything is None).
    if not extracted["source_url"]:
        return item

    # Pass 2: price fallback. Only fire when we have enough to make
    # a focused search (supplier + catalog) AND price is still null.
    # Skipping otherwise keeps the cost bounded — this isn't a
    # blanket second-pass over every item.
    if extracted["supplier"] and extracted["catalog"] and not extracted["price"]:
        fallback_price = _fetch_price_for(
            extracted["supplier"],
            extracted["source_url"],
            extracted["catalog"],
            name,
        )
        if fallback_price:
            extracted["price"] = fallback_price

    # Don't clobber an existing supplier/catalog with None — the
    # original adapt_materials may have populated those from the BE.
    updates: dict[str, Any] = {"source_url": extracted["source_url"]}
    if extracted["supplier"]:
        updates["supplier"] = extracted["supplier"]
    if extracted["catalog"]:
        updates["catalog"] = extracted["catalog"]
    if extracted["price"]:
        updates["price"] = extracted["price"]

    return item.model_copy(update=updates)


# --------------------------------------------------------------------------
# Top-level: walk the FE view
# --------------------------------------------------------------------------

def enrich_materials_view(
    view: FEMaterialsView,
    *,
    max_workers: int = 6,
) -> FEMaterialsView:
    """Walk every item across every group, enrich in parallel, and
    return a new view with the enrichment fields populated. Never
    raises — best-effort across the whole list. Cached upstream
    (30-day TTL on supplier searches) so reruns of the same plan
    are essentially free."""
    # Flatten with backreferences so we can reassemble in original order.
    flat: list[tuple[int, int, FEReagent]] = []
    for gi, group in enumerate(view.groups):
        for ii, item in enumerate(group.items):
            flat.append((gi, ii, item))

    if not flat:
        return view

    n_workers = min(len(flat), max_workers)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        enriched = list(pool.map(lambda t: enrich_one_item(t[2]), flat))

    # Reassemble into a new view; copy groups + items so we never
    # mutate the input.
    new_groups = []
    for gi, group in enumerate(view.groups):
        new_items = list(group.items)
        for (gi2, ii, _orig), new_item in zip(flat, enriched):
            if gi2 == gi:
                new_items[ii] = new_item
        new_groups.append(group.model_copy(update={"items": new_items}))

    return view.model_copy(update={"groups": new_groups})

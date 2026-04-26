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

import logging
import re
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    wait,
)
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

EXTRA STRICT — generic / non-laboratory items:
Some materials in the input are NOT physical lab supplies and SHOULD NOT be matched to any product, even if the supplier search returns hits. These include:
- Stationery and office supplies: pen, pencil, marker, "writing utensil", "writing instrument", paper, notebook, sticker, label.
- Documents and forms: questionnaire, survey, interview template, consent form, "interview questionnaire", "interview form", protocol document, paper-based questionnaire.
- Generic placeholders: "note-taking materials", "writing materials", "general supplies", "miscellaneous".
- Software / files: spreadsheet, document, dataset (these aren't procured from labware suppliers).

For ANY of these, return all-null fields. Do not match a "Sharpie pen" page to "Writing utensil"; do not match a paper-products SKU to "Note-taking materials". A generic name + a too-perfect SKU match is almost always wrong — bias toward null.

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
# Deterministic skip-list (belt-and-suspenders to the LLM rule)
# --------------------------------------------------------------------------
# Items we never enrich, regardless of what Tavily returns. The LLM
# extractor has a "do not match" instruction for these, but Gemini Flash
# has been seen ignoring that and confidently assigning a SKU like
# "PEN-40" to "Writing utensil". This regex catches the most obvious
# generic / non-laboratory items at the gate so a rogue match never
# reaches the FE.
#
# Patterns are word-boundary so "pen" doesn't match "Penicillin",
# "paper" doesn't match "papermill enzyme", etc. If a real lab item
# happens to share a substring with these (e.g. a real "writing-pad"
# product), the user can still see it via the source link on a
# neighboring item — false negatives are cheaper than fabricated SKUs.

_NON_LAB_PATTERNS = [
    re.compile(r"\b(?:writing|drawing|note[- ]?taking)\s+(?:utensil|instrument|materials?|tools?|supplies)\b", re.IGNORECASE),
    re.compile(r"\b(?:pen|pencil|marker|sharpie|highlighter)s?\b", re.IGNORECASE),
    re.compile(r"\b(?:notebook|paper|sticker|label[- ]?paper)\b", re.IGNORECASE),
    re.compile(r"\b(?:questionnaire|survey|interview\s+template|interview\s+questionnaire|interview\s+form|consent\s+form)\b", re.IGNORECASE),
    re.compile(r"\b(?:protocol\s+document|paper[- ]?based\s+questionnaire)\b", re.IGNORECASE),
    re.compile(r"\b(?:general\s+supplies?|miscellaneous|misc\.?|sundries)\b", re.IGNORECASE),
    re.compile(r"\b(?:spreadsheet|document|dataset|file)\b", re.IGNORECASE),
]


def _is_non_lab_item(name: str) -> bool:
    """True when the material name looks like a stationery / paperwork
    placeholder that shouldn't get a SKU. Used as an early skip in
    enrich_one_item — saves a Tavily call AND a guaranteed-bad LLM
    extraction."""
    s = (name or "").strip()
    if not s:
        return False
    return any(p.search(s) for p in _NON_LAB_PATTERNS)


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
    # Skip stationery / paperwork placeholders before paying for the
    # Tavily call. The LLM has been seen confidently matching
    # "Writing utensil" to "Sharpie pen #PEN-40" — better to leave
    # these as TBD than ship a fabricated SKU.
    if _is_non_lab_item(name):
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
    overall_timeout: float = 45.0,
) -> FEMaterialsView:
    """Walk every item across every group, enrich in parallel, and
    return a new view with the enrichment fields populated. Never
    raises — best-effort across the whole list. Cached upstream
    (30-day TTL on supplier searches) so reruns of the same plan
    are essentially free.

    Bounded by `overall_timeout`: items that haven't completed by the
    deadline are returned unenriched (FE renders "TBD"). The stuck
    worker threads are abandoned via shutdown(wait=False, cancel_futures=
    True) so the response returns on time even when Tavily / the LLM
    hangs on a particular item. Without this bound, one slow item
    serializes the whole enrichment behind it and the user sees a
    timeout instead of a partial result.
    """
    # Flatten in iteration order. We submit each as a future indexed by
    # position so reassembly is a single linear pass.
    flat: list[FEReagent] = [
        item for group in view.groups for item in group.items
    ]
    if not flat:
        return view

    n_workers = min(len(flat), max_workers)
    # Start with originals — anything we can't enrich in time stays as-is.
    enriched: list[FEReagent] = list(flat)

    pool = ThreadPoolExecutor(max_workers=n_workers)
    try:
        future_to_idx = {
            pool.submit(enrich_one_item, item): idx
            for idx, item in enumerate(flat)
        }
        deadline = time.monotonic() + overall_timeout
        pending = set(future_to_idx.keys())

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOG.warning(
                    "Materials enrichment overall budget (%.1fs) exhausted; "
                    "%d/%d items still in flight, falling back to TBD for the rest.",
                    overall_timeout, len(pending), len(flat),
                )
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                # wait() returned with no progress before remaining elapsed —
                # likely the timeout fired. Loop checks `remaining` next.
                continue
            for fut in done:
                idx = future_to_idx[fut]
                try:
                    # Already done; tiny timeout just to be defensive.
                    enriched[idx] = fut.result(timeout=0.1)
                except Exception as exc:  # noqa: BLE001 — best-effort
                    _LOG.warning(
                        "Materials enrichment for item %d (%r) failed: %s",
                        idx, flat[idx].name, exc,
                    )
                    # Leave enriched[idx] as the original — falls through to TBD.
    finally:
        # Don't block on hung Tavily / LLM calls. cancel_futures=True asks
        # any not-yet-started futures to skip; in-flight ones continue in
        # the background but we no longer wait for them.
        pool.shutdown(wait=False, cancel_futures=True)

    # Reassemble: walk groups in the same order and pull len(group.items)
    # results off the front of the iterator each time.
    enriched_iter = iter(enriched)
    new_groups = [
        group.model_copy(update={
            "items": [next(enriched_iter) for _ in group.items],
        })
        for group in view.groups
    ]
    return view.model_copy(update={"groups": new_groups})

"""
protocols.io API client for read-only protocol grounding.

Three bug-fixes layered on the original implementation, all tied to
specific protocols.io API quirks we hit during sample-pulling:

  1. order_field=relevance triggers a server-side SQL error
     ("Unknown column 'an.author_name' in 'order clause'"). Switched
     to "activity" + order_dir=desc — the combination that returns
     200s in our smoke tests against the real API.

  2. Steps endpoint returns {"payload": [...], "status_code": 0},
     not {"steps": [...]}. Fixed the lookup key.

  3. Step items have keys {id, guid, number, section, step, ...}
     where `step` is a DraftJS JSON STRING, not flat title/description
     fields. Parse the DraftJS body to extract a usable description;
     derive a short title from the first line.

Each fix is tagged BUGFIX(protocols.io) inline so they're easy to
spot and remove if/when Vip's upstream version addresses them.
"""
import json
import logging
import os
import re
import requests

BASE_URL = "https://www.protocols.io/api"

# Module-level logger so callers can configure verbosity (e.g. silencing
# the network warnings during local-sample tests). RequestException paths
# below log + return [] rather than swallowing silently — that way an
# invalid token or a downed protocols.io is visible in the server log
# while the caller still gets a graceful empty-result fallback.
_LOG = logging.getLogger(__name__)

# Avoid spamming logs when many callers skip live API without a token.
_MISSING_TOKEN_WARNED = False


def _protocols_io_token():
    """Read token from the environment each call so dotenv/load order cannot strand us.

    protocols.io expects ``Authorization: Bearer <access_token>`` (see API docs). Users
    sometimes paste ``Bearer …`` into ``.env`` or wrap the value in quotes — normalize so
    we never send ``Bearer Bearer …`` or quoted secrets.
    """
    raw = (
        os.environ.get("PROTOCOLS_IO_TOKEN")
        or os.environ.get("PROTOCOLS_IO_ACCESS_TOKEN")
        or ""
    )
    raw = raw.strip()
    if not raw:
        return None
    if (len(raw) >= 2 and raw[0] == raw[-1]) and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    low = raw.lower()
    if low.startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None


def _protocols_io_auth_headers():
    """Headers that authenticate against protocols.io (Bearer token only when set)."""
    headers = {}
    tok = _protocols_io_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _log_protocols_io_failure(where: str, exc: BaseException) -> None:
    """Attach response body snippet when requests HTTP errors hide the API JSON."""
    detail = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            detail = (resp.text or "")[:800]
        except Exception:
            detail = ""
    if detail:
        _LOG.warning("protocols.io %s failed: %s — response: %s", where, exc, detail)
    else:
        _LOG.warning("protocols.io %s failed: %s", where, exc)


def _warn_missing_token_once():
    global _MISSING_TOKEN_WARNED
    if _MISSING_TOKEN_WARNED:
        return
    _MISSING_TOKEN_WARNED = True
    _LOG.warning(
        "PROTOCOLS_IO_TOKEN is not set; protocols.io live API calls are skipped."
    )


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _parse_draftjs(raw):
    """BUGFIX(protocols.io) #3 helper: peel a DraftJS JSON-string body
    down to plaintext. Falls through to the raw text when the input
    isn't DraftJS — protocols.io has been seen returning plain prose
    for some `description` fields and DraftJS JSON for others, and
    the candidate-selection card needs to render either gracefully."""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Plain text (or HTML) — strip tags and return.
        return _HTML_TAG_RE.sub("", str(raw)).strip()
    blocks = obj.get("blocks") if isinstance(obj, dict) else None
    if not isinstance(blocks, list):
        # Parsed as JSON but not DraftJS-shaped. Best to surface the
        # original raw text rather than blank out — at least the user
        # can read it.
        return _HTML_TAG_RE.sub("", str(raw)).strip()
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        text = (b.get("text") or "").strip()
        if text:
            parts.append(text)
    joined = "\n".join(parts)
    # If DraftJS parsed but had no usable text blocks, again fall
    # back to the raw input so the card renders something.
    return joined or _HTML_TAG_RE.sub("", str(raw)).strip()


def _short_title(body, max_len=70):
    """Derive a step title from the first ~70 chars of the body. The API
    doesn't have separate step titles; this matches the bundle shape
    Vip's example_protocol_bundle.json shows."""
    line = (body or "").split("\n", 1)[0].strip()
    return (line[:max_len] + "…") if len(line) > max_len else line


class ProtocolsIoError(Exception):
    """Custom exception for protocols.io API errors."""
    pass


def get_headers():
    """Return headers for API requests."""
    headers = {"Accept": "application/json"}
    headers.update(_protocols_io_auth_headers())
    return headers


def search_protocols(query: str, limit: int = 5) -> list:
    """
    Search public protocols on protocols.io.
    
    Args:
        query: Search query string
        limit: Maximum number of results (default 5)
    
    Returns:
        List of normalized protocol candidates
    """
    if not _protocols_io_token():
        _warn_missing_token_once()
        return []

    try:
        # Docs mark ``key`` as required; empty values have triggered 400 "missing or empty"
        # responses in the wild — use a single space so we still issue a legal search.
        key = (query or "").strip() or " "
        response = requests.get(
            f"{BASE_URL}/v3/protocols",
            params={
                "filter": "public",
                "key": key,
                # BUGFIX(protocols.io) #1: order_field=relevance returns
                # a 400 SQL error from protocols.io's backend
                # ("Unknown column 'an.author_name' in 'order clause'").
                # Activity + desc returns 200s and gives reasonable
                # ordering for our use case (recently-edited protocols
                # tend to be better-maintained).
                "order_field": "activity",
                "order_dir": "desc",
                # API docs describe page_size / page_id as string params.
                "page_size": str(limit),
                "page_id": "1",
            },
            headers=get_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        
        candidates = []
        for item in data.get("items", []):
            # BUGFIX(protocols.io) #4: `description` is sometimes a
            # DraftJS JSON-string, same as `step` (see #3 above), and
            # sometimes plain prose. Parse-or-fall-through; otherwise
            # the FE candidate card renders raw `{"blocks":[...]}` JSON.
            raw_desc = item.get("description") or ""
            description = _parse_draftjs(raw_desc)[:500]
            protocol = {
                "id": str(item.get("id", "")),
                "title": item.get("title", ""),
                "description": description,
                "url": item.get("uri", ""),
                "doi": item.get("doi", ""),
                "uri": item.get("uri", ""),
                "source": "protocols.io",
                "materials_available": item.get("has_materials", False),
                "steps_available": item.get("has_steps", False),
                "relevance_reason": "",
                "relevance_score": None
            }
            candidates.append(protocol)
        
        return candidates

    except requests.RequestException as exc:
        _log_protocols_io_failure("search_protocols", exc)
        return []


def get_protocol_metadata(protocol_id: str) -> dict:
    """Fetch top-level metadata for a single protocol by ID.

    Used by `fetch_one_protocol` in protocol_pipeline/sources.py to
    populate title / description / doi / url when the FE has handed
    us a pre-selected protocol ID rather than a full search result.
    Without this, those candidates rendered with empty titles in the
    final cited-protocols panel.

    Returns the same dict shape as one item from `search_protocols`
    (id, title, description, url, doi, source) so the caller can pass
    it straight into `_bundle_to_normalized`. Returns {} when the
    token is missing, the API errors, or the protocol id isn't found.
    """
    if not _protocols_io_token():
        return {}

    try:
        # Prefer v4 — current docs center on GET /v4/protocols/[id] with {"payload": …}.
        response = requests.get(
            f"{BASE_URL}/v4/protocols/{protocol_id}",
            headers=get_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        item = data.get("payload") or data.get("protocol") or data
        if not isinstance(item, dict):
            return {}
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        n_steps = int(stats.get("number_of_steps") or 0)
        n_reagents = int(stats.get("number_of_reagents") or 0)
        mats = item.get("materials")
        steps_available = bool(n_steps or item.get("steps"))
        materials_available = bool(
            n_reagents or (isinstance(mats, list) and len(mats) > 0)
        )
        desc = _parse_draftjs(item.get("description") or "")[:500]
        uri = item.get("uri") or ""
        url = item.get("url") or ""
        return {
            "id": str(item.get("id", protocol_id)),
            "title": item.get("title", ""),
            "description": desc,
            "url": url or uri,
            "doi": item.get("doi", ""),
            "uri": uri,
            "source": "protocols.io",
            "materials_available": materials_available or item.get("has_materials", False),
            "steps_available": steps_available or item.get("has_steps", False),
        }
    except requests.RequestException as exc:
        _log_protocols_io_failure(f"get_protocol_metadata({protocol_id})", exc)
        return {}


def get_protocol_steps(protocol_id: str) -> list:
    """
    Fetch steps for a specific protocol.
    
    Args:
        protocol_id: The protocol ID
    
    Returns:
        List of protocol steps
    """
    if not _protocols_io_token():
        return []

    try:
        response = requests.get(
            f"{BASE_URL}/v4/protocols/{protocol_id}/steps",
            headers=get_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        steps = []
        # BUGFIX(protocols.io) #2: response is {"payload": [...],
        # "status_code": 0}, NOT {"steps": [...]}. Reading "steps"
        # silently returned an empty list on every call.
        for item in data.get("payload", []):
            # BUGFIX(protocols.io) #3: step items have keys
            # {id, guid, number, section, step, ...} — the `step` field
            # is a DraftJS JSON STRING, not a flat description. Parse
            # it to plaintext; derive a title from the first line.
            body = _parse_draftjs(item.get("step"))
            # Preserve the API's original step number — protocols.io
            # uses "1.1" / "2a" / "3" interchangeably. Forcing int loses
            # the sub-step labels that researchers use to reference
            # branches. Default to "" only when the API returns nothing.
            number_raw = item.get("number")
            if number_raw is None:
                number_raw = item.get("ordinal")
            number = "" if number_raw is None else str(number_raw).strip()
            step = {
                "step_number": number,
                "title": _short_title(body),
                "description": body,
                "image_url": (
                    item.get("image", {}).get("url")
                    if isinstance(item.get("image"), dict)
                    else None
                ),
            }
            steps.append(step)

        return steps
    
    except requests.RequestException as exc:
        _log_protocols_io_failure(f"get_protocol_steps({protocol_id})", exc)
        return []


def get_protocol_materials(protocol_id: str) -> list:
    """
    Fetch materials for a specific protocol.
    
    Args:
        protocol_id: The protocol ID
    
    Returns:
        List of protocol materials
    """
    if not _protocols_io_token():
        return []

    try:
        response = requests.get(
            f"{BASE_URL}/v3/protocols/{protocol_id}/materials",
            headers=get_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        
        materials = []
        for item in data.get("materials", []):
            material = {
                "name": item.get("name", ""),
                "quantity": item.get("quantity", ""),
                "unit": item.get("unit", ""),
                "vendor": item.get("vendor", ""),
                "sku": item.get("catalog_number", ""),
                "url": item.get("url", "")
            }
            materials.append(material)
        
        return materials
    
    except requests.RequestException as exc:
        _log_protocols_io_failure(f"get_protocol_materials({protocol_id})", exc)
        return []


def get_protocol_bundle(query: str, selected_protocol_id: str = None) -> dict:
    """
    Get protocol context bundle for grounding experiment plans.
    
    Args:
        query: Search query (usually the hypothesis)
        selected_protocol_id: Optional specific protocol ID to use
    
    Returns:
        Protocol bundle with candidates, steps, materials, and gaps
    """
    # Check for missing token
    if not _protocols_io_token():
        return {
            "grounding_status": "missing_token",
            "selection_mode": "none",
            "selected_protocol": None,
            "candidates": [],
            "steps": [],
            "materials": [],
            "gaps": ["protocols.io token not configured"]
        }
    
    # Search for protocols
    candidates = search_protocols(query, limit=5)
    
    if not candidates:
        return {
            "grounding_status": "no_matches",
            "selection_mode": "none",
            "selected_protocol": None,
            "candidates": [],
            "steps": [],
            "materials": [],
            "gaps": ["No matching protocols found for query"]
        }
    
    # Determine which protocol to use
    selected = None
    selection_mode = "none"
    
    if selected_protocol_id:
        # User selected a specific protocol
        for candidate in candidates:
            if candidate["id"] == selected_protocol_id:
                selected = candidate
                selection_mode = "user"
                break
        if not selected:
            # Fallback to first match if ID not found
            selected = candidates[0]
            selection_mode = "auto"
    else:
        # Auto-select first match
        selected = candidates[0]
        selection_mode = "auto"
    
    # Fetch steps and materials
    steps = []
    materials = []
    gaps = []
    
    try:
        if selected:
            steps = get_protocol_steps(selected["id"])
            materials = get_protocol_materials(selected["id"])
            
            if not steps:
                gaps.append("Protocol steps not available")
            if not materials:
                gaps.append("Protocol materials not available")
    
    except Exception as e:
        gaps.append(f"Failed to fetch protocol details: {str(e)}")
    
    return {
        "grounding_status": "success",
        "selection_mode": selection_mode,
        "selected_protocol": selected,
        "candidates": candidates,
        "steps": steps,
        "materials": materials,
        "gaps": gaps
    }
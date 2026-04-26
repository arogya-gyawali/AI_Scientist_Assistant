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

PROTOCOLS_IO_TOKEN = os.environ.get("PROTOCOLS_IO_TOKEN")
BASE_URL = "https://www.protocols.io/api"

# Module-level logger so callers can configure verbosity (e.g. silencing
# the network warnings during local-sample tests). RequestException paths
# below log + return [] rather than swallowing silently — that way an
# invalid token or a downed protocols.io is visible in the server log
# while the caller still gets a graceful empty-result fallback.
_LOG = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _parse_draftjs(raw):
    """BUGFIX(protocols.io) #3 helper: peel a DraftJS JSON-string body
    down to plaintext. Returns "" for malformed input — the pipeline
    keeps going on bad steps rather than crashing."""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _HTML_TAG_RE.sub("", str(raw)).strip()
    blocks = obj.get("blocks") if isinstance(obj, dict) else None
    if not isinstance(blocks, list):
        return ""
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        text = (b.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


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
    headers = {
        "Content-Type": "application/json"
    }
    if PROTOCOLS_IO_TOKEN:
        headers["Authorization"] = f"Bearer {PROTOCOLS_IO_TOKEN}"
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
    if not PROTOCOLS_IO_TOKEN:
        return []
    
    try:
        response = requests.get(
            f"{BASE_URL}/v3/protocols",
            params={
                "filter": "public",
                "key": query,
                # BUGFIX(protocols.io) #1: order_field=relevance returns
                # a 400 SQL error from protocols.io's backend
                # ("Unknown column 'an.author_name' in 'order clause'").
                # Activity + desc returns 200s and gives reasonable
                # ordering for our use case (recently-edited protocols
                # tend to be better-maintained).
                "order_field": "activity",
                "order_dir": "desc",
                "page_size": limit
            },
            headers=get_headers(),
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        candidates = []
        for item in data.get("items", []):
            protocol = {
                "id": str(item.get("id", "")),
                "title": item.get("title", ""),
                "description": item.get("description", "")[:500] if item.get("description") else "",
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
        # Log so operators see "API down" / "bad token" in server logs
        # rather than silently degrading. Return [] so callers still
        # get a graceful no-results fallback (the offline static-samples
        # path picks up).
        _LOG.warning("protocols.io request failed: %s", exc)
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
    if not PROTOCOLS_IO_TOKEN:
        return {}

    try:
        response = requests.get(
            f"{BASE_URL}/v3/protocols/{protocol_id}",
            headers=get_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        # protocols.io wraps single-protocol responses in {"protocol":
        # {...}} or sometimes returns the protocol dict at the top level
        # depending on the endpoint version. Handle both shapes.
        item = data.get("protocol") or data
        if not isinstance(item, dict):
            return {}
        # Truncate description to match search_protocols's 500-char cap
        # so downstream rendering is uniform.
        desc = item.get("description") or ""
        if isinstance(desc, str) and len(desc) > 500:
            desc = desc[:500]
        return {
            "id": str(item.get("id", protocol_id)),
            "title": item.get("title", ""),
            "description": desc,
            "url": item.get("uri", "") or item.get("url", ""),
            "doi": item.get("doi", ""),
            "uri": item.get("uri", ""),
            "source": "protocols.io",
            "materials_available": item.get("has_materials", False),
            "steps_available": item.get("has_steps", False),
        }
    except requests.RequestException as exc:
        _LOG.warning("protocols.io get_protocol_metadata(%s) failed: %s",
                     protocol_id, exc)
        return {}


def get_protocol_steps(protocol_id: str) -> list:
    """
    Fetch steps for a specific protocol.
    
    Args:
        protocol_id: The protocol ID
    
    Returns:
        List of protocol steps
    """
    if not PROTOCOLS_IO_TOKEN:
        return []
    
    try:
        response = requests.get(
            f"{BASE_URL}/v4/protocols/{protocol_id}/steps",
            headers=get_headers(),
            timeout=10
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
        # Log so operators see "API down" / "bad token" in server logs
        # rather than silently degrading. Return [] so callers still
        # get a graceful no-results fallback (the offline static-samples
        # path picks up).
        _LOG.warning("protocols.io request failed: %s", exc)
        return []


def get_protocol_materials(protocol_id: str) -> list:
    """
    Fetch materials for a specific protocol.
    
    Args:
        protocol_id: The protocol ID
    
    Returns:
        List of protocol materials
    """
    if not PROTOCOLS_IO_TOKEN:
        return []
    
    try:
        response = requests.get(
            f"{BASE_URL}/v3/protocols/{protocol_id}/materials",
            headers=get_headers(),
            timeout=10
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
        # Log so operators see "API down" / "bad token" in server logs
        # rather than silently degrading. Return [] so callers still
        # get a graceful no-results fallback (the offline static-samples
        # path picks up).
        _LOG.warning("protocols.io request failed: %s", exc)
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
    if not PROTOCOLS_IO_TOKEN:
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
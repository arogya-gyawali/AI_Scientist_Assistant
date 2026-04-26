"""File-based cache for external API responses. Keyed by SHA-256 of a
canonical request body. TTLs enforced on read.

Writes are atomic: a temp file in the same directory is written and then
os.replace'd onto the target. Same-key concurrent writers race on the
final replace but neither sees a partial JSON file."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(".cache")


def _key(namespace: str, payload: dict[str, Any]) -> str:
    # default=str gives us a safe fallback if a caller ever passes a payload
    # containing non-JSON-native types like datetime, UUID, or Path. Since
    # those types' str() is stable, the cache key stays deterministic.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{namespace}/{digest}.json"


def get(namespace: str, payload: dict[str, Any], ttl_seconds: int) -> Any | None:
    path = CACHE_DIR / _key(namespace, payload)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def put(namespace: str, payload: dict[str, Any], value: Any) -> None:
    path = CACHE_DIR / _key(namespace, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: temp file in same dir + os.replace. Prevents partial
    # JSON readable to a concurrent reader if the writer is mid-flush.
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

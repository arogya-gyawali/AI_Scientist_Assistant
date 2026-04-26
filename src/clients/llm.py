"""LLM client abstraction. Picks OpenRouter or Anthropic from LLM_PROVIDER.
Stages call llm.complete(system, user) without caring which provider runs.

Client instances are cached per API key so we get TLS/connection reuse across
calls. Tests that swap env vars mid-run automatically get fresh clients
because the cache key is the api_key string itself.

Both providers' completion calls are wrapped in a small retry-with-backoff
loop on transient errors (rate limits, connection drops, server errors).
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Callable, Literal, TypeVar

Provider = Literal["openrouter", "anthropic"]

T = TypeVar("T")


def _retry_transient(fn: Callable[[], T], *, retriable: tuple[type[BaseException], ...], max_attempts: int = 3, base_delay: float = 2.0) -> T:
    """Call fn(); retry on `retriable` exceptions with exponential backoff.

    Caller passes the provider-specific retriable error types so we don't
    need both SDKs imported here. NOTE: time.sleep blocks the calling
    thread; same caveat as the Europe PMC client — fine for the CLI and
    a single-worker dev server, less great for high-concurrency Flask.
    """
    delay = base_delay
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except retriable as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    assert last_exc is not None  # we never break without setting last_exc
    raise last_exc


def _provider() -> Provider:
    p = os.environ.get("LLM_PROVIDER", "openrouter").lower()
    if p not in ("openrouter", "anthropic"):
        raise RuntimeError(f"LLM_PROVIDER must be 'openrouter' or 'anthropic', got {p!r}")
    return p  # type: ignore[return-value]


def model_id() -> str:
    if _provider() == "openrouter":
        return os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def complete(system: str, user: str, *, json_mode: bool = False) -> str:
    """Single-turn completion. Returns the assistant's text content."""
    if _provider() == "openrouter":
        return _openrouter_complete(system, user, json_mode=json_mode)
    return _anthropic_complete(system, user, json_mode=json_mode)


# ---------------------------------------------------------------------------
# Cached client factories
# ---------------------------------------------------------------------------
# Keyed on api_key so changing env (e.g., between tests, or rotating keys
# in production) yields a fresh client. Same key = reused instance.

# maxsize=16 leaves headroom for key rotation and multiple base_urls
# (e.g., switching between OpenRouter and a self-hosted OpenAI-compatible
# endpoint) without thrashing the cache.
@lru_cache(maxsize=16)
def _openai_client_for(api_key: str, base_url: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)


@lru_cache(maxsize=16)
def _anthropic_client_for(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Provider-specific completion paths
# ---------------------------------------------------------------------------

def _openrouter_complete(system: str, user: str, *, json_mode: bool) -> str:
    import openai

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    client = _openai_client_for(api_key, "https://openrouter.ai/api/v1")
    kwargs: dict = {
        "model": model_id(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    retriable = (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.InternalServerError,
    )
    resp = _retry_transient(
        lambda: client.chat.completions.create(**kwargs),
        retriable=retriable,
    )

    # Defensive: content filtering or upstream errors can return empty choices.
    if not resp.choices:
        raise RuntimeError(
            f"OpenRouter returned no choices for model {kwargs['model']!r}; "
            "possibly content-filtered or upstream error."
        )
    return resp.choices[0].message.content or ""


def _anthropic_complete(system: str, user: str, *, json_mode: bool) -> str:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = _anthropic_client_for(api_key)
    # json_mode for Anthropic: ask in the system prompt; SDK doesn't have a native flag.
    sys = system + ("\n\nReturn ONLY valid JSON. No prose, no markdown fences." if json_mode else "")

    retriable = (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    )
    msg = _retry_transient(
        lambda: client.messages.create(
            model=model_id(),
            max_tokens=4096,
            system=sys,
            messages=[{"role": "user", "content": user}],
        ),
        retriable=retriable,
    )

    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)

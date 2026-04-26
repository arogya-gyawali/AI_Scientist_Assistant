"""LLM client abstraction. Picks OpenRouter or Anthropic from LLM_PROVIDER.
Stages call llm.complete(system, user) without caring which provider runs."""

from __future__ import annotations

import os
from typing import Literal

Provider = Literal["openrouter", "anthropic"]


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


def _openrouter_complete(system: str, user: str, *, json_mode: bool) -> str:
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    kwargs: dict = {
        "model": model_id(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = client.chat.completions.create(**kwargs)
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

    client = anthropic.Anthropic(api_key=api_key)
    # json_mode for Anthropic: ask in the system prompt; SDK doesn't have a native flag.
    sys = system + ("\n\nReturn ONLY valid JSON. No prose, no markdown fences." if json_mode else "")

    msg = client.messages.create(
        model=model_id(),
        max_tokens=4096,
        system=sys,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)

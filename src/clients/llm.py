"""LLM client abstraction. Picks OpenRouter or Anthropic from LLM_PROVIDER.
Stages call llm.complete(system, user) without caring which provider runs.

Client instances are cached per API key so we get TLS/connection reuse across
calls. Tests that swap env vars mid-run automatically get fresh clients
because the cache key is the api_key string itself.

Both providers' completion calls are wrapped in a small retry-with-backoff
loop on transient errors (rate limits, connection drops, server errors).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Literal, TypeVar

Provider = Literal["openrouter", "anthropic"]

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Tool-calling shapes (provider-agnostic).
# ---------------------------------------------------------------------------
# Tool definitions use Anthropic's shape canonically — `{name, description,
# input_schema}` — and the OpenRouter codepath adapts them to OpenAI's
# `{type: "function", function: {name, description, parameters}}` internally.
# Why Anthropic-shape canonical: stages care about input_schema, not the
# function-call wrapper, and Anthropic's shape is the leaner of the two.

@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str  # provider-assigned tool_use id; round-tripped if we ever add multi-turn

@dataclass
class ToolUseResult:
    text: str  # leading text the assistant emitted alongside tool calls
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""


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


def complete_json(system: str, user: str, *, agent_name: str = "agent") -> dict:
    """Single-turn completion in JSON mode, with one retry on parse failure.

    Wraps `complete(json_mode=True)` with the boilerplate every Stage 2
    agent was duplicating: strip whitespace, peel off ```json fences when
    a model adds them anyway, parse, and on JSONDecodeError retry once.
    On a second failure, raises RuntimeError naming the agent that broke
    so the surfaced error tells the operator where to look.

    `agent_name` shows up in the error message ("Architect: LLM returned
    malformed JSON twice...") — pass the calling agent's name so the
    failure mode is greppable in logs.
    """
    def _call() -> dict:
        raw = complete(system, user, json_mode=True).strip()
        # Some models wrap JSON in ```json fences despite json_mode being
        # set; peel those off rather than letting json.loads fail on them.
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        return json.loads(raw)

    try:
        return _call()
    except json.JSONDecodeError as first_exc:
        try:
            return _call()
        except json.JSONDecodeError as retry_exc:
            raise RuntimeError(
                f"{agent_name}: LLM returned malformed JSON twice "
                f"(first: {first_exc}; retry: {retry_exc})."
            ) from retry_exc


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


# ---------------------------------------------------------------------------
# Tool-calling completion (single-turn).
# ---------------------------------------------------------------------------
# This is single-turn by design: caller passes tools, gets back any tool
# calls the model wanted to make. We do NOT execute the tools and feed
# results back — that's a multi-turn agentic loop and isn't what the
# chat-on-blackboard feature needs (we propose mutations, the user
# applies them server-side after explicit approval).
#
# `history` is a list of {role, content} message dicts (conversation
# history); the current `user` message is appended after them.

def complete_with_tools(
    system: str,
    user: str,
    *,
    tools: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 4096,
) -> ToolUseResult:
    """Single-turn tool-using completion.

    `tools` uses Anthropic's shape: `[{name, description, input_schema}, ...]`.
    For OpenRouter we adapt to OpenAI's `{type: "function", function: ...}`.
    """
    if _provider() == "openrouter":
        return _openrouter_with_tools(system, user, tools, history or [], max_tokens)
    return _anthropic_with_tools(system, user, tools, history or [], max_tokens)


def _anthropic_with_tools(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    history: list[dict[str, str]],
    max_tokens: int,
) -> ToolUseResult:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = _anthropic_client_for(api_key)
    # Anthropic messages list: prior turns then the new user turn.
    msgs: list[dict[str, Any]] = []
    for h in history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user})

    retriable = (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    )
    msg = _retry_transient(
        lambda: client.messages.create(
            model=model_id(),
            max_tokens=max_tokens,
            system=system,
            tools=tools,  # type: ignore[arg-type]
            messages=msgs,  # type: ignore[arg-type]
        ),
        retriable=retriable,
    )

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "tool_use":
            tool_calls.append(ToolCall(
                name=block.name,
                arguments=dict(block.input or {}),
                id=block.id,
            ))
    return ToolUseResult(
        text="".join(text_parts).strip(),
        tool_calls=tool_calls,
        stop_reason=getattr(msg, "stop_reason", "") or "",
    )


def _openrouter_with_tools(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    history: list[dict[str, str]],
    max_tokens: int,
) -> ToolUseResult:
    import openai

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    client = _openai_client_for(api_key, "https://openrouter.ai/api/v1")

    # Anthropic shape -> OpenAI function-tool shape.
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for h in history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user})

    retriable = (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.InternalServerError,
    )
    resp = _retry_transient(
        lambda: client.chat.completions.create(
            model=model_id(),
            messages=messages,  # type: ignore[arg-type]
            tools=openai_tools,  # type: ignore[arg-type]
            max_tokens=max_tokens,
        ),
        retriable=retriable,
    )

    if not resp.choices:
        raise RuntimeError(
            f"OpenRouter returned no choices for model {model_id()!r}; "
            "possibly content-filtered or upstream error."
        )

    msg_obj = resp.choices[0].message
    text = (msg_obj.content or "").strip()
    tool_calls: list[ToolCall] = []
    for tc in (msg_obj.tool_calls or []):
        # OpenAI nests under tc.function with arguments as a JSON string.
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            # Skip malformed calls rather than blowing up the whole turn —
            # a single bad call shouldn't kill the user's chat message.
            continue
        tool_calls.append(ToolCall(
            name=tc.function.name,
            arguments=args,
            id=tc.id or uuid.uuid4().hex,
        ))
    return ToolUseResult(
        text=text,
        tool_calls=tool_calls,
        stop_reason=resp.choices[0].finish_reason or "",
    )

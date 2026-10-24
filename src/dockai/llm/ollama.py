"""Ollama chat + tool-calling adapter."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx

from dockai.config import Settings, load_settings
from dockai.errors import DockaiError
from dockai.llm.base import ChatMessage, ToolCall


class OllamaError(DockaiError):
    """Ollama request failed or returned an unusable response."""


class OllamaNotFoundError(DockaiError):
    """Ollama HTTP API is not reachable at the given host."""


def preflight_http_timeout(total_seconds: float) -> httpx.Timeout:
    """
    Timeouts for GET /api/tags during health preflight.

    Short connect so unreachable remote hosts fail fast; read uses the rest of
    the budget (whole preflight is capped at 5s in settings).
    """
    total = max(1.0, min(5.0, float(total_seconds)))
    connect = min(2.0, total * 0.45)
    read = max(1.0, total - connect)
    return httpx.Timeout(connect=connect, read=read, write=read, pool=connect)


def list_ollama_models(
    host: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
    preflight: bool = False,
) -> list[str]:
    """Return model names from GET /api/tags (sorted)."""
    base = host.rstrip("/")
    owns = client is None
    resolved_timeout: httpx.Timeout | float = (
        preflight_http_timeout(timeout) if preflight else timeout
    )
    http = client or httpx.Client(base_url=base, timeout=resolved_timeout)
    try:
        resp = http.get("/api/tags")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise OllamaNotFoundError(
            f"Ollama not found at {base}. Is it running and is the URL correct?"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OllamaNotFoundError(
            f"Ollama not found at {base} (invalid response)."
        ) from exc
    finally:
        if owns:
            http.close()

    names: list[str] = []
    for item in data.get("models") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return sorted(names)


class OllamaProvider:
    def __init__(
        self,
        *,
        host: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or load_settings(model=model)
        self.host = (host or cfg.ollama_host).rstrip("/")
        self.model = model or cfg.ollama_model
        resolved = cfg.ollama_timeout if timeout is None else timeout
        self._client = client or httpx.Client(base_url=self.host, timeout=resolved)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
    ) -> ChatMessage:
        payload = {
            "model": self.model,
            "messages": [_to_ollama_message(m) for m in messages],
            "stream": False,
            "tools": tools,
        }
        try:
            resp = self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Ollama request failed ({self.host}): {exc}. "
                "Is Ollama running and does the model support tools?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid JSON.") from exc

        message = data.get("message") or {}
        return _from_ollama_message(message)


def _to_ollama_message(message: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role}
    if message.content is not None:
        out["content"] = message.content
    if message.tool_call_id:
        out["tool_call_id"] = message.tool_call_id
    if message.name:
        out["name"] = message.name
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return out


def _from_ollama_message(message: dict[str, Any]) -> ChatMessage:
    tool_calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {"__invalid__": args}
        if not isinstance(args, dict):
            args = {"__invalid__": args}
        tool_calls.append(
            ToolCall(
                id=str(raw.get("id") or uuid4()),
                name=str(name),
                arguments=args,
            )
        )
    content = message.get("content")
    return ChatMessage(
        role=str(message.get("role") or "assistant"),
        content=content if content else None,
        tool_calls=tool_calls,
    )

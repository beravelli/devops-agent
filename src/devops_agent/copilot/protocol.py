"""Translate between the Copilot agent wire format and the LangChain agent.

Copilot POSTs an OpenAI-style chat payload (a `messages` array). We pull out the
latest user turn as the agent input and the earlier turns as chat history, run
the agent, then stream the reply back as OpenAI-compatible SSE chunks terminated
by `data: [DONE]`.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def split_messages(messages: list[dict[str, Any]]) -> tuple[str, list[BaseMessage]]:
    """Return (latest_user_input, prior_history_as_langchain_messages).

    Copilot includes its own system messages; we keep only user/assistant turns.
    The last user message becomes the agent input; everything before it is history.
    """
    convo = [
        m
        for m in messages
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()
    ]
    last_user = next((i for i in range(len(convo) - 1, -1, -1) if convo[i]["role"] == "user"), None)
    if last_user is None:
        return "", []
    user_input = convo[last_user]["content"]
    history: list[BaseMessage] = []
    for m in convo[:last_user]:
        if m["role"] == "user":
            history.append(HumanMessage(content=m["content"]))
        else:
            history.append(AIMessage(content=m["content"]))
    return user_input, history


def _chunk(content: str | None, *, role: str | None = None, finish_reason: str | None = None) -> str:
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def sse_stream(text: str, chunk_size: int = 240) -> Iterable[str]:
    """Yield the agent's reply as OpenAI-compatible SSE chunks then `[DONE]`."""
    yield _chunk(None, role="assistant")
    if text:
        for i in range(0, len(text), chunk_size):
            yield _chunk(text[i : i + chunk_size])
    else:
        yield _chunk("(no output produced)")
    yield _chunk(None, finish_reason="stop")
    yield "data: [DONE]\n\n"

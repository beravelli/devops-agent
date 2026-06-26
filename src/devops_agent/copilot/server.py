"""FastAPI server that exposes the triage agent as a GitHub Copilot agent.

Endpoints:
  POST /agent   - the Copilot agent endpoint (signature-verified, SSE response)
  GET  /health  - liveness probe for load balancers / ECS / App Runner

Run locally:   uv run devops-agent serve
Run in prod:   uvicorn devops_agent.copilot.server:app --host 0.0.0.0 --port 8000

The agent (and its LLM) is built lazily on the first request and cached, so the
process starts — and /health responds — even before credentials are exercised.
"""

# NOTE: deliberately no `from __future__ import annotations` here — FastAPI must
# resolve the route's `request: Request` annotation to the real class at import
# time, which stringized annotations would prevent.

import json
import logging
from typing import Optional

from ..config import Settings, get_settings
from .protocol import split_messages, sse_stream
from .verify import (
    SignatureError,
    _default_key_resolver,
    extract_signature_headers,
    verify_signature,
)

logger = logging.getLogger("devops_agent.copilot")

_AGENT_CACHE: dict[str, object] = {}


def _get_agent(settings: Settings):
    if "agent" not in _AGENT_CACHE:
        from ..agent import build_agent

        _AGENT_CACHE["agent"] = build_agent(settings)
    return _AGENT_CACHE["agent"]


def create_app(settings: Optional[Settings] = None, verify_signatures: bool = True):
    """Build the FastAPI app. `verify_signatures=False` is for local testing only."""
    try:
        from fastapi import FastAPI, Request, Response
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import StreamingResponse
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "FastAPI is required to run the Copilot server. Install the server "
            "extra: uv sync --extra server"
        ) from exc

    settings = settings or get_settings()
    app = FastAPI(title="DevOps Triage Copilot Agent", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": settings.llm_provider, "model": settings.model}

    @app.post("/agent")
    async def agent_endpoint(request: Request) -> Response:
        raw = await request.body()

        if verify_signatures:
            key_id, signature = extract_signature_headers(request.headers)
            token = request.headers.get("x-github-token")
            try:
                verify_signature(
                    raw,
                    key_id,
                    signature,
                    key_resolver=lambda kid: _default_key_resolver(kid, token),
                )
            except SignatureError as exc:
                logger.warning("rejected unverified request: %s", exc)
                return Response(status_code=401, content=f"signature verification failed: {exc}")

        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return Response(status_code=400, content="invalid JSON body")

        user_input, history = split_messages(payload.get("messages", []))
        if not user_input:
            return Response(status_code=400, content="no user message found in request")

        try:
            # Build (lazily) and run the agent inside the handler so credential
            # or LLM errors stream back as a readable message, not a raw 500.
            executor = _get_agent(settings)
            result = await run_in_threadpool(
                executor.invoke, {"input": user_input, "chat_history": history}
            )
            output = result.get("output", "")
        except Exception as exc:  # surface agent/LLM/credential errors into the chat
            logger.exception("agent invocation failed")
            output = f"Triage failed: {type(exc).__name__}: {exc}"

        return StreamingResponse(sse_stream(output), media_type="text/event-stream")

    return app


# Module-level app for `uvicorn devops_agent.copilot.server:app`. Importing this
# requires the server extra (FastAPI); the CLI builds it lazily instead.
try:  # pragma: no cover - exercised via deployment, not unit tests
    app = create_app()
except RuntimeError:
    app = None

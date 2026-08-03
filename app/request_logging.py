"""Per-request structured logging.

An ASGI middleware mints a request id for every HTTP request, binds it to
every log line emitted while that request is in flight, and reports the
request's lifecycle as two structured events: ``request.started`` and
``request.completed``.

The request id is always minted locally with ``uuid4`` and never read from an
inbound header. Nothing in this stack sends one: Open WebUI does not attach
``X-Request-ID``, and no reverse proxy or gateway sits in front of this
service to have originated one either. Honouring an inbound header here would
serve a caller that does not exist, and would pull an untrusted string
straight into every log line for the request, which then needs length
capping and character sanitising to stay safe as a log field.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

logger = logging.getLogger("app.request")

# Set for the lifetime of one HTTP request's ASGI call and reset when it
# finishes. asyncio Tasks each get their own copy of the current context
# (contextvars.copy_context) at creation time, so concurrent requests -
# each handled in its own Task - never observe one another's values.
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_completion_fields_ctx: ContextVar[dict[str, Any]] = ContextVar("completion_fields")


def get_request_id() -> str | None:
    """The id of the request currently being handled on this task.

    ``None`` outside of a request - e.g. code running at import time, or in
    a task that was not spawned from within the middleware's ASGI call.
    Other modules call this to tag their own log lines or error responses
    with the same id a reader sees in ``request.started``/``request.completed``.
    """
    return _request_id_ctx.get()


def attach_completion_fields(**fields: Any) -> None:
    """Add fields to the ``request.completed`` line for the in-flight request.

    This is the documented seam for upstream-facing code to report details
    such as ``finish_reason`` and token usage on the completion event without
    this module importing anything about the Upstream - the coupling runs
    the other way. The caller (e.g. the streaming layer, once it has observed
    the last SSE frame) calls this with whatever it learned; later calls
    overwrite same-named fields, and ``RequestLoggingMiddleware`` merges
    whatever has accumulated into the ``request.completed`` event it emits
    when the response finishes.

    A no-op when called outside a request (for example from a unit test that
    exercises business logic directly, without going through the
    middleware), so callers never need to guard the call themselves.
    """
    try:
        fields_dict = _completion_fields_ctx.get()
    except LookupError:
        return
    fields_dict.update(fields)


class RequestIdFilter(logging.Filter):
    """Stamps every log record reaching a handler with the current request id.

    Attached to the handler installed by ``app.logging_config.configure_logging``
    rather than to any one logger, so it applies uniformly: any module that
    logs through the standard ``logging`` hierarchy - not just this one -
    has its records carry ``request_id`` automatically, with no call site
    needing to look it up and pass it through ``extra`` itself.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def log_message_content(
    target_logger: logging.Logger,
    event: str,
    message: str,
    *,
    settings: Settings,
    **fields: Any,
) -> None:
    """Log fields that may hold user-authored document text.

    Guarded by ``Settings.log_prompts``: a no-op when it is false, which is
    the default. The documents flowing through this service are, by the
    assignment's own examples, emails, receipts, medical reports and legal
    text, so nothing that might be message content reaches the log stream
    unless an operator has deliberately opted in while iterating on the
    System Prompt. Call sites (e.g. the Upstream client, when logging the
    outgoing payload for prompt debugging) pass whatever content fields they
    hold; this function decides, once, in one place, whether they are ever
    written.
    """
    if not settings.log_prompts:
        return
    target_logger.info(message, extra={"event": event, **fields})


class RequestLoggingMiddleware:
    """Logs the lifecycle of every HTTP request as structured JSON.

    Implemented as a plain ASGI middleware rather than Starlette's
    ``BaseHTTPMiddleware``, which buffers an entire response body before
    passing it on - that would defeat the streamed chat completions this
    service exists to forward, and would make ``request.completed`` fire
    only after the whole stream had already been buffered in memory instead
    of when the last byte actually left the process.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        id_token = _request_id_ctx.set(request_id)
        fields_token = _completion_fields_ctx.set({})

        method = scope.get("method", "")
        path = scope.get("path", "")
        started_at = time.perf_counter()
        request_bytes = 0
        response_bytes = 0
        status_code = 500

        async def receive_wrapper() -> Message:
            nonlocal request_bytes
            message = await receive()
            if message["type"] == "http.request":
                request_bytes += len(message.get("body") or b"")
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal response_bytes, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body") or b"")
            await send(message)

        logger.info(
            "request started",
            extra={"event": "request.started", "method": method, "path": path},
        )

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            completion_fields = _completion_fields_ctx.get()
            logger.info(
                "request completed",
                extra={
                    "event": "request.completed",
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                    "request_bytes": request_bytes,
                    "response_bytes": response_bytes,
                    **completion_fields,
                },
            )
            _completion_fields_ctx.reset(fields_token)
            _request_id_ctx.reset(id_token)

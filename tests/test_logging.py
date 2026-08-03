"""Tests for structured logging: JSON formatting, request id binding across
concurrent requests, and gating of message content on ``LOG_PROMPTS``."""

from __future__ import annotations

import asyncio
import io
import json
import logging

from app.config import Settings
from app.logging_config import configure_logging
from app.request_logging import (
    RequestLoggingMiddleware,
    attach_completion_fields,
    get_request_id,
    log_message_content,
)
from tests.conftest import make_settings


def _read_json_lines(buffer: io.StringIO) -> list[dict[str, object]]:
    """Every non-empty line in the buffer, parsed as JSON. Raises
    ``json.JSONDecodeError`` (failing the test) if any line is not valid
    JSON, which is itself part of what these tests check."""
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line]


def _configure(settings: Settings) -> io.StringIO:
    buffer = io.StringIO()
    configure_logging(settings, stream=buffer)
    return buffer


async def _run_request(
    app: RequestLoggingMiddleware, method: str, path: str, body: bytes = b""
) -> int:
    """Drive one fake HTTP request through the middleware and return the
    status code the response started with."""
    scope = {"type": "http", "method": method, "path": path}
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]  # type: ignore[return-value]


def _make_app(settings: Settings, *, log_mid_request: bool = True) -> RequestLoggingMiddleware:
    handler_logger = logging.getLogger("app.test.handler")

    async def fake_app(scope: dict, receive, send) -> None:  # type: ignore[no-untyped-def]
        await receive()
        if log_mid_request:
            handler_logger.info(
                "handling", extra={"event": "handler.mid", "path": scope["path"]}
            )
        attach_completion_fields(finish_reason="stop", usage_total_tokens=3)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    return RequestLoggingMiddleware(fake_app, settings=settings)


# ---------------------------------------------------------------------------
# JSON shape
# ---------------------------------------------------------------------------


def test_every_line_is_valid_json_with_the_required_fields() -> None:
    settings = make_settings()
    buffer = _configure(settings)

    logging.getLogger("app.test").info(
        "something happened", extra={"event": "test.something"}
    )

    lines = _read_json_lines(buffer)
    assert len(lines) == 1
    record = lines[0]
    for field in ("timestamp", "level", "logger", "event", "message"):
        assert field in record, f"missing {field!r} in {record!r}"
    assert record["level"] == "INFO"
    assert record["logger"] == "app.test"
    assert record["event"] == "test.something"
    assert record["message"] == "something happened"


def test_level_is_taken_from_settings() -> None:
    settings = make_settings(log_level="WARNING")
    buffer = _configure(settings)

    logging.getLogger("app.test").info("should be filtered out")
    logging.getLogger("app.test").warning(
        "should appear", extra={"event": "test.warn"}
    )

    lines = _read_json_lines(buffer)
    assert len(lines) == 1
    assert lines[0]["level"] == "WARNING"


def test_configure_logging_is_idempotent() -> None:
    settings = make_settings()
    buffer = _configure(settings)
    root = logging.getLogger()
    handlers_after_first = [
        h for h in root.handlers if getattr(h, "name", None) == "app.structured-json"
    ]
    assert len(handlers_after_first) == 1

    # Reconfigure - must update the existing handler in place, not add another.
    configure_logging(settings, stream=buffer)
    handlers_after_second = [
        h for h in root.handlers if getattr(h, "name", None) == "app.structured-json"
    ]
    assert len(handlers_after_second) == 1
    assert handlers_after_first[0] is handlers_after_second[0]

    logging.getLogger("app.test").info("only once", extra={"event": "test.once"})
    lines = _read_json_lines(buffer)
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Request id binding
# ---------------------------------------------------------------------------


async def test_request_id_is_stable_across_all_lines_of_one_request() -> None:
    settings = make_settings()
    buffer = _configure(settings)
    app = _make_app(settings)

    status = await _run_request(app, "GET", "/v1/chat/completions")
    assert status == 200

    lines = _read_json_lines(buffer)
    events = [line["event"] for line in lines]
    assert events == ["request.started", "handler.mid", "request.completed"]

    request_ids = {line["request_id"] for line in lines}
    assert len(request_ids) == 1
    assert request_ids.pop()  # non-empty


async def test_request_id_differs_between_requests() -> None:
    settings = make_settings()
    buffer = _configure(settings)
    app = _make_app(settings)

    await _run_request(app, "GET", "/first")
    await _run_request(app, "GET", "/second")

    lines = _read_json_lines(buffer)
    started_ids = [line["request_id"] for line in lines if line["event"] == "request.started"]
    assert len(started_ids) == 2
    assert started_ids[0] != started_ids[1]


async def test_request_id_is_absent_outside_a_request() -> None:
    assert get_request_id() is None


async def test_concurrent_requests_do_not_leak_ids() -> None:
    settings = make_settings()
    buffer = _configure(settings)

    handler_logger = logging.getLogger("app.test.handler")

    async def fake_app(scope: dict, receive, send) -> None:  # type: ignore[no-untyped-def]
        await receive()
        # The slow request logs before and after yielding control, so a fast
        # request can interleave in between if - and only if - ids leaked.
        delay = 0.05 if scope["path"] == "/slow" else 0.0
        await asyncio.sleep(delay)
        handler_logger.info(
            "handling", extra={"event": "handler.mid", "path": scope["path"]}
        )
        await asyncio.sleep(delay)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    app = RequestLoggingMiddleware(fake_app, settings=settings)

    await asyncio.gather(
        _run_request(app, "GET", "/slow"),
        _run_request(app, "GET", "/fast"),
        _run_request(app, "GET", "/fast"),
    )

    lines = _read_json_lines(buffer)
    ids_by_path: dict[str, set[str]] = {}
    for line in lines:
        path = line.get("path")
        if path is None:
            continue
        ids_by_path.setdefault(path, set()).add(line["request_id"])

    # Every line logged for "/slow" carries exactly one, consistent id...
    assert len(ids_by_path["/slow"]) == 1
    # ...and it never appears on a "/fast" line, despite interleaving.
    slow_id = next(iter(ids_by_path["/slow"]))
    assert slow_id not in ids_by_path["/fast"]
    # The two "/fast" requests are themselves distinguishable.
    assert len(ids_by_path["/fast"]) == 2


async def test_completed_event_carries_lifecycle_fields_and_upstream_extensions() -> None:
    settings = make_settings()
    buffer = _configure(settings)
    app = _make_app(settings)

    await _run_request(app, "POST", "/v1/chat/completions", body=b"{}")

    lines = _read_json_lines(buffer)
    completed = next(line for line in lines if line["event"] == "request.completed")

    assert completed["method"] == "POST"
    assert completed["path"] == "/v1/chat/completions"
    assert completed["status_code"] == 200
    assert isinstance(completed["duration_ms"], (int, float))
    assert completed["request_bytes"] == 2  # b"{}"
    assert completed["response_bytes"] == 2  # b"ok"
    # Attached by the "upstream" layer via attach_completion_fields(), proving
    # the documented seam works without this module importing app.upstream.
    assert completed["finish_reason"] == "stop"
    assert completed["usage_total_tokens"] == 3


# ---------------------------------------------------------------------------
# Content gating
# ---------------------------------------------------------------------------


def test_message_content_is_absent_by_default() -> None:
    settings = make_settings(log_prompts=False)
    buffer = _configure(settings)

    log_message_content(
        logging.getLogger("app.test"),
        "prompt.debug",
        "outgoing payload",
        settings=settings,
        messages=[{"role": "user", "content": "my social security number is 123-45-6789"}],
    )

    lines = _read_json_lines(buffer)
    assert lines == []


def test_message_content_is_present_when_log_prompts_enabled() -> None:
    settings = make_settings(log_prompts=True)
    buffer = _configure(settings)

    log_message_content(
        logging.getLogger("app.test"),
        "prompt.debug",
        "outgoing payload",
        settings=settings,
        messages=[{"role": "user", "content": "paste of a receipt"}],
    )

    lines = _read_json_lines(buffer)
    assert len(lines) == 1
    record = lines[0]
    assert record["event"] == "prompt.debug"
    assert record["messages"] == [{"role": "user", "content": "paste of a receipt"}]


async def test_request_lifecycle_events_never_carry_content_regardless_of_flag() -> None:
    """request.started / request.completed describe the request, not its
    body - LOG_PROMPTS must not need to be consulted here at all because
    these events never accept a content field in the first place."""
    settings = make_settings(log_prompts=True)
    buffer = _configure(settings)
    app = _make_app(settings, log_mid_request=False)

    await _run_request(app, "POST", "/v1/chat/completions", body=b'{"messages": []}')

    lines = _read_json_lines(buffer)
    serialized = json.dumps(lines)
    assert "messages" not in serialized

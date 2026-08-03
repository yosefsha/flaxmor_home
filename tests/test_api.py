"""End-to-end tests over the assembled application.

The whole path is exercised — middleware, auth, routing, error rendering,
streaming — against a fake Upstream. No network, no API key, no prompt file.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import UpstreamError
from app.main import create_app
from app.models import ModelList, ModelObject
from app.ports import ProbeResult
from app.upstream import OpenAiUpstreamClient
from tests.conftest import make_settings

SYSTEM_PROMPT = "You are a structured data extractor."
TOKEN = "test-token"


class FakePromptSource:
    def __init__(self, prompt: str = SYSTEM_PROMPT) -> None:
        self._prompt = prompt

    def load(self) -> str:
        return self._prompt


class FakeCatalog:
    def __init__(self, model_id: str = "gpt-4o-mini") -> None:
        self._model_id = model_id

    def list_models(self) -> ModelList:
        return ModelList(data=[ModelObject(id=self._model_id)])


class FakeUpstream:
    """An Upstream that returns whatever the test tells it to.

    ``stream_error`` is raised on first advance of the stream, mirroring the
    real client: it is an async generator, so a pre-first-byte failure does not
    surface until the generator is advanced.
    """

    def __init__(
        self,
        *,
        frames: list[str] | None = None,
        completion: dict[str, Any] | None = None,
        stream_error: Exception | None = None,
        completion_error: Exception | None = None,
        probe_result: ProbeResult | None = None,
    ) -> None:
        self.frames = frames or []
        self.completion = completion or {"id": "chatcmpl-1", "choices": []}
        self.stream_error = stream_error
        self.completion_error = completion_error
        self.probe_result = probe_result or ProbeResult("ok", "200", 0.0)
        self.received_payloads: list[dict[str, Any]] = []

    async def probe(self) -> ProbeResult:
        return self.probe_result

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.received_payloads.append(payload)
        if self.completion_error is not None:
            raise self.completion_error
        return self.completion

    async def stream_chat_completion(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[str]:
        self.received_payloads.append(payload)
        if self.stream_error is not None:
            raise self.stream_error
        for frame in self.frames:
            yield frame


def _client(upstream: FakeUpstream | None = None, **overrides: object) -> TestClient:
    settings = make_settings(middleware_api_key=TOKEN, **overrides)
    app = create_app(
        settings,
        prompt_source=FakePromptSource(),
        upstream_client=upstream or FakeUpstream(),
        catalog=FakeCatalog(),
    )
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# --- authentication --------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/models", "/v1/chat/completions"])
def test_requests_without_a_token_are_rejected(path: str) -> None:
    response = _client().request("POST" if "chat" in path else "GET", path, json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_wrong_token_is_rejected() -> None:
    response = _client().get("/v1/models", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


def test_health_and_readiness_need_no_token() -> None:
    client = _client()

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


# --- model listing ---------------------------------------------------------


def test_models_are_listed_in_the_openai_envelope() -> None:
    response = _client().get("/v1/models", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "gpt-4o-mini",
                "object": "model",
                "created": 0,
                "owned_by": "openai",
            }
        ],
    }


# --- chat completions ------------------------------------------------------


def test_non_streaming_completion_is_returned() -> None:
    upstream = FakeUpstream(completion={"id": "chatcmpl-9", "choices": [{"index": 0}]})

    response = _client(upstream).post(
        "/v1/chat/completions",
        headers=_auth(),
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl-9"
    assert upstream.received_payloads[0]["messages"] == [
        {"role": "user", "content": "hi"}
    ]


def test_streamed_extraction_reaches_the_caller_intact() -> None:
    frames = [
        'data: {"choices":[{"delta":{"content":"```json\\n"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"{\\"document_type\\":"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"\\"receipt\\"}"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    with _client(FakeUpstream(frames=frames)) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(),
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "<receipt>"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "".join(frames)


def test_upstream_failure_before_the_first_byte_becomes_a_status_code() -> None:
    """The regression this wiring exists to prevent.

    ``stream_chat_completion`` is an async generator, so its pre-first-byte
    error only surfaces once advanced. If the generator were handed straight to
    StreamingResponse, this would arrive as ``200`` with an empty body instead
    of a rate-limit error.
    """
    upstream = FakeUpstream(
        stream_error=UpstreamError(
            "Rate limited by upstream, retry in 20s",
            status_code=429,
            error_type="rate_limit_error",
            retry_after=20.0,
        )
    )

    response = _client(upstream).post(
        "/v1/chat/completions",
        headers=_auth(),
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "20"
    body = response.json()
    assert body["error"]["type"] == "rate_limit_error"
    assert "retry in 20s" in body["error"]["message"]


def test_non_streaming_upstream_failure_is_rendered_in_the_envelope() -> None:
    upstream = FakeUpstream(
        completion_error=UpstreamError(
            "upstream returned 502: bad gateway", status_code=502
        )
    )

    response = _client(upstream).post(
        "/v1/chat/completions",
        headers=_auth(),
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_error"
    assert "Retry-After" not in response.headers


def test_completion_details_reach_the_request_completed_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`request.completed` must carry the outcome, not leave a reader joining
    two log lines by request id. `attach_completion_fields` existed for this
    and had no production caller."""
    body = (
        b'data: {"choices":[{"delta":{"content":"{"},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: {"choices":[],"usage":{"total_tokens":41}}\n\n'
        b"data: [DONE]\n\n"
    )

    class _Stream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield body

    def transport_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_Stream(),
            request=request,
        )

    settings = make_settings(middleware_api_key=TOKEN)
    # The real client, so SseStreamObserver actually runs — a fake upstream
    # would bypass the very code under test.
    upstream = OpenAiUpstreamClient(
        settings, SYSTEM_PROMPT, transport=httpx.MockTransport(transport_handler)
    )
    app = create_app(
        settings,
        prompt_source=FakePromptSource(),
        upstream_client=upstream,
        catalog=FakeCatalog(),
    )

    with caplog.at_level("INFO"):
        with TestClient(app) as client:
            client.post(
                "/v1/chat/completions",
                headers=_auth(),
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )

    completed = [r for r in caplog.records if getattr(r, "event", "") == "request.completed"]
    assert len(completed) == 1
    assert completed[0].finish_reason == "stop"  # type: ignore[attr-defined]
    assert completed[0].usage == {"total_tokens": 41}  # type: ignore[attr-defined]


def test_upstream_events_are_named_in_the_event_field() -> None:
    """Event names belong in `event`, not in the human-readable message: the
    formatter defaults `event` to "log", so a name passed as the message is
    unqueryable."""
    from app.streaming import SseStreamObserver

    import asyncio

    async def drive() -> None:
        async def chunks():
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        async for _ in SseStreamObserver().observe(chunks()):
            pass

    import logging

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logging.getLogger("app.streaming").addHandler(handler)
    try:
        asyncio.run(drive())
    finally:
        logging.getLogger("app.streaming").removeHandler(handler)

    assert any(getattr(r, "event", None) == "upstream.stream_completed" for r in records)


# --- readiness -------------------------------------------------------------


def test_readiness_reports_not_ready_on_a_permanent_upstream_fault() -> None:
    upstream = FakeUpstream(
        probe_result=ProbeResult("permanent_failure", "401 invalid api key", 0.0)
    )

    response = _client(upstream).get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_readiness_stays_ready_through_a_transient_upstream_fault() -> None:
    upstream = FakeUpstream(probe_result=ProbeResult("transient_failure", "503", 0.0))

    response = _client(upstream).get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["upstream"] == "degraded"

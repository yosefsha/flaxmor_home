"""Tests for ``SseStreamObserver``: verbatim forwarding, frames split across
chunk boundaries, keepalives, the ``[DONE]`` sentinel, and recovery from a
mid-stream Upstream failure without ever raising.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from app.streaming import SseStreamObserver, synthetic_error_frame

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def _failing_chunks(parts: list[bytes], exc: Exception) -> AsyncIterator[bytes]:
    for part in parts:
        yield part
    raise exc


async def _collect(observer: SseStreamObserver, chunks: AsyncIterator[bytes]) -> list[str]:
    return [frame async for frame in observer.observe(chunks)]


async def test_success_stream_forwards_every_frame_verbatim() -> None:
    raw = _read_fixture("success_stream.sse")
    observer = SseStreamObserver()

    frames = await _collect(observer, _chunks(raw))

    assert "".join(frames) == raw.decode()
    assert observer.observations.finish_reason == "stop"
    assert observer.observations.usage == {
        "prompt_tokens": 120,
        "completion_tokens": 42,
        "total_tokens": 162,
    }
    assert observer.observations.interrupted is False


async def test_frames_split_across_chunk_boundaries_are_reassembled() -> None:
    raw = _read_fixture("success_stream.sse")
    # Split at an arbitrary offset that lands mid-frame -- mid-JSON, and not
    # aligned to the "data: " prefix or the "\n\n" delimiter -- to prove
    # buffering does not care where a network read happens to cut.
    midpoint = len(raw) // 2
    observer = SseStreamObserver()

    frames = await _collect(observer, _chunks(raw[:midpoint], raw[midpoint:]))

    assert "".join(frames) == raw.decode()
    assert observer.observations.finish_reason == "stop"


async def test_frame_split_byte_by_byte_still_reassembles() -> None:
    raw = _read_fixture("success_stream.sse")
    observer = SseStreamObserver()

    async def one_byte_at_a_time() -> AsyncIterator[bytes]:
        for byte in raw:
            yield bytes([byte])

    frames = await _collect(observer, one_byte_at_a_time())

    assert "".join(frames) == raw.decode()
    assert observer.observations.finish_reason == "stop"
    assert observer.observations.usage is not None


async def test_frame_split_exactly_on_delimiter_boundary() -> None:
    raw = _read_fixture("success_stream.sse")
    split_at = raw.index(b"\n\n") + 2  # first chunk ends exactly at a delimiter
    observer = SseStreamObserver()

    frames = await _collect(observer, _chunks(raw[:split_at], raw[split_at:]))

    assert "".join(frames) == raw.decode()


async def test_keepalive_comment_frames_pass_through_unparsed() -> None:
    raw = _read_fixture("keepalive_stream.sse")
    observer = SseStreamObserver()

    frames = await _collect(observer, _chunks(raw))

    assert "".join(frames) == raw.decode()
    keepalive_frames = [frame for frame in frames if frame.startswith(": keepalive")]
    assert len(keepalive_frames) == 2
    assert observer.observations.finish_reason == "stop"
    assert observer.observations.usage == {
        "prompt_tokens": 50,
        "completion_tokens": 5,
        "total_tokens": 55,
    }


async def test_done_sentinel_is_forwarded_and_not_parsed_as_json() -> None:
    raw = (
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    observer = SseStreamObserver()

    frames = await _collect(observer, _chunks(raw))

    assert frames == [
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        "data: [DONE]\n\n",
    ]
    assert observer.observations.finish_reason == "stop"


async def test_mid_stream_failure_yields_synthetic_error_then_done() -> None:
    raw = _read_fixture("mid_stream_cut.sse")
    observer = SseStreamObserver()

    frames = await _collect(
        observer, _failing_chunks([raw], ConnectionResetError("connection reset by peer"))
    )

    # The partial frames that did arrive are forwarded first, verbatim.
    assert "".join(frames[:2]) == raw.decode()
    # Then a synthetic error frame stating the failure, then [DONE].
    assert frames[2].startswith("data: ")
    assert "connection reset by peer" in frames[2]
    assert frames[3] == "data: [DONE]\n\n"
    assert len(frames) == 4
    assert observer.observations.interrupted is True
    assert observer.observations.interruption_detail == "connection reset by peer"


async def test_mid_stream_failure_cutting_a_frame_in_half_still_recovers() -> None:
    # The failure happens *inside* an in-progress frame, before its closing
    # "\n\n" ever arrives -- nothing of that partial frame is forwarded, but
    # the observer still recovers cleanly.
    partial = b'data: {"choices":[{"index":0,"delta":{"content":"unfinished'
    observer = SseStreamObserver()

    frames = await _collect(observer, _failing_chunks([partial], TimeoutError("read timed out")))

    assert len(frames) == 2
    assert "read timed out" in frames[0]
    assert frames[1] == "data: [DONE]\n\n"
    assert observer.observations.interrupted is True


async def test_synthetic_error_frame_is_a_valid_sse_data_frame() -> None:
    frame = synthetic_error_frame("connection reset")

    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    body = json.loads(frame[len("data: ") :].strip())
    assert body["choices"][0]["finish_reason"] == "error"
    assert "connection reset" in body["choices"][0]["delta"]["content"]


async def test_observer_never_raises_on_upstream_failure() -> None:
    observer = SseStreamObserver()

    # Simply not raising is the assertion: a failure mid-iteration must not
    # propagate out of observe().
    frames = await _collect(
        observer, _failing_chunks([b"data: {}\n\n"], RuntimeError("boom"))
    )

    assert frames[-1] == "data: [DONE]\n\n"

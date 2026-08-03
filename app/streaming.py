"""SSE frame handling for the Upstream response stream.

Frames pass through untouched -- the Middleware never rewrites what the model
said -- but each frame is inspected on its way past to capture
``finish_reason`` and token usage for the completion log. Frames are yielded
first and parsed after, so observation adds nothing to time-to-first-token.

Once the first frame has reached the caller the response is committed: an
Upstream failure partway through cannot become an error status, so it is
turned into a synthetic error frame instead of a raised exception, followed
by ``data: [DONE]``. ``SseStreamObserver.observe`` therefore never raises.
"""

from __future__ import annotations

import codecs
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.request_logging import attach_completion_fields

logger = logging.getLogger(__name__)

_DONE_SENTINEL = "[DONE]"
_FRAME_DELIMITER = "\n\n"
_DONE_FRAME = f"data: {_DONE_SENTINEL}{_FRAME_DELIMITER}"


@dataclass
class StreamObservations:
    """What the completion log needs from a stream, gathered by watching
    frames pass rather than by buffering or re-parsing the response."""

    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    interrupted: bool = False
    interruption_detail: str | None = None


def synthetic_error_frame(detail: str) -> str:
    """A valid SSE ``data:`` frame reporting a mid-stream Upstream failure,
    shaped like an ordinary completion chunk so the caller renders it as
    assistant text -- a stated failure -- rather than a response that simply
    stops."""
    payload = {
        "id": "middleware-stream-error",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "content": f"\n\n[The response was interrupted: {detail}]"
                },
                "finish_reason": "error",
            }
        ],
    }
    return f"data: {json.dumps(payload)}{_FRAME_DELIMITER}"


class SseStreamObserver:
    """Buffers raw byte chunks into complete SSE frames, forwards each one
    verbatim as soon as it is complete, and parses it afterwards to record
    ``finish_reason`` / ``usage``.

    A frame boundary -- including the ``data: `` prefix or the blank-line
    delimiter itself -- may fall anywhere inside a network chunk, so frames
    are only ever handed onward once a full ``\\n\\n``-terminated block has
    arrived. One observer instance is good for exactly one stream.
    """

    def __init__(self) -> None:
        self.observations = StreamObservations()
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    async def observe(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
        try:
            async for chunk in chunks:
                self._buffer += self._decoder.decode(chunk)
                while _FRAME_DELIMITER in self._buffer:
                    frame, self._buffer = self._buffer.split(_FRAME_DELIMITER, 1)
                    yield frame + _FRAME_DELIMITER
                    self._observe_frame(frame)

            tail = self._buffer.strip()
            self._buffer = ""
            if tail:
                yield tail + _FRAME_DELIMITER
                self._observe_frame(tail)
        except Exception as exc:  # the Upstream connection died mid-stream
            detail = str(exc) or exc.__class__.__name__
            self.observations.interrupted = True
            self.observations.interruption_detail = detail
            logger.warning(
                "upstream stream interrupted mid-response: %s",
                detail,
                extra={"event": "upstream.stream_interrupted"},
            )
            yield synthetic_error_frame(detail)
            yield _DONE_FRAME
        finally:
            observed = {
                "finish_reason": self.observations.finish_reason,
                "usage": self.observations.usage,
                "interrupted": self.observations.interrupted,
            }
            # Also attach to this request's `request.completed`, so the
            # lifecycle event carries the outcome rather than requiring a
            # reader to join two lines by request id. A no-op outside a
            # request, so this stays usable in isolation.
            attach_completion_fields(**observed)
            logger.info(
                "upstream stream completed",
                extra={"event": "upstream.stream_completed", **observed},
            )

    def _observe_frame(self, frame: str) -> None:
        for line in frame.splitlines():
            if not line.startswith("data:"):
                continue  # comments (":") and other SSE fields are not ours to parse
            data = line[len("data:") :].strip()
            if not data or data == _DONE_SENTINEL:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in parsed.get("choices") or []:
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    self.observations.finish_reason = finish_reason
            usage = parsed.get("usage")
            if usage:
                self.observations.usage = usage

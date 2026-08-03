"""The seams between components.

Every milestone codes against these Protocols rather than against another
milestone's concrete class, so the pieces can be built independently and faked
in tests without touching the network.
"""

from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol

from app.models import ModelList

ProbeStatus = Literal["ok", "permanent_failure", "transient_failure"]


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of an Upstream reachability check.

    The distinction is the whole point: ``permanent_failure`` means the service
    cannot work until a human changes something (bad credential, unresolvable
    host) and readiness should say so; ``transient_failure`` means the Upstream
    is having a bad minute (429, 5xx, timeout), which every replica shares and
    which readiness must not amplify into an outage.
    """

    status: ProbeStatus
    detail: str
    checked_at: float

    @property
    def is_ready(self) -> bool:
        return self.status != "permanent_failure"


class PromptSource(Protocol):
    """Supplies the System Prompt text injected into every conversation."""

    def load(self) -> str:
        """Return the prompt, or raise ``PromptLoadError``."""


class ModelCatalog(Protocol):
    """Supplies the model list served from ``GET /v1/models``."""

    def list_models(self) -> ModelList:
        ...


class UpstreamClient(Protocol):
    """The Upstream, as the rest of the application sees it.

    Implementations own retry and error classification; callers receive either a
    result or an ``UpstreamError``.
    """

    async def probe(self) -> ProbeResult:
        """Cheap reachability check used by readiness. Never raises."""

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming completion. Raises ``UpstreamError`` on failure."""

    def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        """Yield raw SSE lines, forwarded verbatim.

        Failures before the first line raise ``UpstreamError``. Once a line has
        been yielded the response is committed, so a later failure is reported by
        yielding a synthetic error frame followed by ``data: [DONE]``.
        """

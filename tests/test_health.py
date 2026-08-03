"""Tests for GET /health and GET /ready.

The router is mounted on a throwaway FastAPI app per test, with fakes of
``PromptSource`` and ``UpstreamClient`` injected — nothing here touches the
network or imports a concrete implementation of either Protocol.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import PromptLoadError
from app.health import build_health_router
from app.ports import ProbeResult, ProbeStatus
from tests.conftest import make_settings


class FakePromptSource:
    """Fake ``PromptSource``. Raises ``PromptLoadError`` when constructed
    with ``text=None``, mirroring the real loader's contract."""

    def __init__(self, text: str | None = "You are a structured data extractor.") -> None:
        self._text = text

    def load(self) -> str:
        if self._text is None:
            raise PromptLoadError("markers not found")
        return self._text


class FakeUpstreamClient:
    """Fake ``UpstreamClient`` that always returns the same ``ProbeResult``
    and counts how many times ``probe`` was actually called, so tests can
    assert on caching behaviour."""

    def __init__(self, result: ProbeResult) -> None:
        self._result = result
        self.probe_calls = 0

    async def probe(self) -> ProbeResult:
        self.probe_calls += 1
        return self._result

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("not exercised by health checks")

    def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        raise NotImplementedError("not exercised by health checks")


class FakeClock:
    """Manually advanced clock so cache-expiry tests never sleep."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _build_client(
    *,
    settings: Settings | None = None,
    prompt_source: FakePromptSource | None = None,
    upstream: FakeUpstreamClient | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[TestClient, FakeUpstreamClient]:
    settings = settings or make_settings()
    prompt_source = prompt_source or FakePromptSource()
    upstream = upstream or FakeUpstreamClient(ProbeResult("ok", "200 OK", 0.0))
    router = build_health_router(
        settings=settings,
        prompt_source=prompt_source,
        upstream_client=upstream,
        clock=clock or (lambda: 0.0),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), upstream


def test_health_is_static_and_always_ok() -> None:
    client, _ = _build_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_never_touches_the_upstream() -> None:
    upstream = FakeUpstreamClient(ProbeResult("ok", "200 OK", 0.0))
    client, upstream = _build_client(upstream=upstream)

    client.get("/health")

    assert upstream.probe_calls == 0


def test_ready_is_200_when_every_check_passes() -> None:
    client, _ = _build_client()

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"config": "ok", "system_prompt": "loaded", "upstream": "ok"},
        "last_probe": "200 OK",
    }


@pytest.mark.parametrize(
    ("probe_status", "expected_http_status", "expected_upstream_check", "expected_ready_status"),
    [
        ("ok", 200, "ok", "ready"),
        ("transient_failure", 200, "degraded", "ready"),
        ("permanent_failure", 503, "error", "not_ready"),
    ],
)
def test_ready_classifies_upstream_probe_outcomes(
    probe_status: ProbeStatus,
    expected_http_status: int,
    expected_upstream_check: str,
    expected_ready_status: str,
) -> None:
    """Every row of the classification table in docs/design-decisions.md:
    ``ok`` -> ready, ``transient_failure`` -> ready-but-degraded,
    ``permanent_failure`` -> not ready. Readiness trusts ``ProbeResult.is_ready``
    rather than re-deriving the rule, so this exercises it end to end."""
    probe = ProbeResult(probe_status, "probe detail", 0.0)
    client, _ = _build_client(upstream=FakeUpstreamClient(probe))

    response = client.get("/ready")

    assert response.status_code == expected_http_status
    body = response.json()
    assert body["status"] == expected_ready_status
    assert body["checks"]["upstream"] == expected_upstream_check


def test_ready_fails_when_the_upstream_credential_is_missing() -> None:
    settings = make_settings(openai_api_key="")
    client, _ = _build_client(settings=settings)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["config"] == "error"


def test_ready_fails_when_the_system_prompt_fails_to_load() -> None:
    client, _ = _build_client(prompt_source=FakePromptSource(text=None))

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["system_prompt"] == "error"


def test_ready_fails_when_the_system_prompt_is_blank() -> None:
    """A loader that returns only whitespace has technically not raised, but
    the prompt is still unusable — this is the "has teeth" requirement: a
    service without a working prompt must not report ready."""
    client, _ = _build_client(prompt_source=FakePromptSource(text="   \n"))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["system_prompt"] == "error"


def test_ready_body_always_reports_the_last_probe_outcome() -> None:
    upstream = FakeUpstreamClient(ProbeResult("transient_failure", "timeout after 2s", 0.0))
    client, _ = _build_client(upstream=upstream)

    response = client.get("/ready")

    assert response.json()["last_probe"] == "timeout after 2s"


def test_ready_caches_the_probe_within_the_window() -> None:
    upstream = FakeUpstreamClient(ProbeResult("ok", "200 OK", 0.0))
    client, upstream = _build_client(upstream=upstream, clock=FakeClock(0.0))

    client.get("/ready")
    client.get("/ready")
    client.get("/ready")

    assert upstream.probe_calls == 1


def test_ready_reprobes_once_the_cache_window_expires() -> None:
    settings = make_settings(readiness_cache_seconds=30.0)
    upstream = FakeUpstreamClient(ProbeResult("ok", "200 OK", 0.0))
    clock = FakeClock(0.0)
    client, upstream = _build_client(settings=settings, upstream=upstream, clock=clock)

    client.get("/ready")
    clock.advance(29.9)
    client.get("/ready")
    assert upstream.probe_calls == 1

    clock.advance(0.2)
    client.get("/ready")
    assert upstream.probe_calls == 2

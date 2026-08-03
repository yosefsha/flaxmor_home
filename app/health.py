"""Liveness and readiness for the Middleware.

``/health`` answers "is the process functioning" — static, dependency-free,
always ``200`` while the event loop is serving requests. A failure here means
"restart me", so it must never depend on anything that can itself fail
independently of the process (Upstream, disk, configuration).

``/ready`` answers "should traffic reach this instance". Per
``docs/adr/ADR-001-stateless-middleware.md`` the Middleware owns no
persistence, so there is no datastore to check; readiness instead verifies
its own preconditions — configuration parsed with the Upstream credential
present, and the System Prompt loaded and non-empty — plus a cached Upstream
probe.

The System Prompt check has teeth on purpose: without it the Middleware
silently degrades into a plain OpenAI proxy while every other signal still
looks healthy, which is precisely the failure mode that should never pass a
readiness check.

Readiness fails only on permanent faults. ``ProbeResult.is_ready`` (see
``app/ports.py``) already encodes the classification — ``ok`` is ready,
``permanent_failure`` (bad credential, unresolvable host) is not ready
because the service cannot do its job until a human fixes something, and
``transient_failure`` (429, 5xx, timeout) is still reported as ready. A
transient Upstream fault is the Upstream's weather: it hits every replica
identically, so failing readiness for it would remove the entire service
from rotation when staying up to return a clear per-request error is
strictly more useful. This module trusts ``is_ready`` rather than
re-deriving the classification from ``status``.
"""

from __future__ import annotations

import time
from typing import Callable, Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.config import Settings
from app.errors import PromptLoadError
from app.ports import ProbeResult, PromptSource, UpstreamClient

ReadyStatus = Literal["ready", "not_ready"]
CheckOutcome = Literal["ok", "loaded", "degraded", "error"]


class HealthBody(BaseModel):
    """Static liveness response."""

    status: Literal["ok"] = "ok"


class ReadinessBody(BaseModel):
    """Readiness response. Always reports every individual check and the
    last Upstream probe outcome, so a degraded Upstream is visible without
    being fatal."""

    status: ReadyStatus
    checks: dict[str, CheckOutcome]
    last_probe: str


class ReadinessChecker:
    """Answers whether this instance should receive traffic.

    Checks three preconditions in order: configuration (the Upstream
    credential is present — pydantic-settings has already parsed the
    environment by the time this class runs, so "parsed" is a given and the
    one setting worth checking is the one with no workable default, per
    ``app/config.py``), the System Prompt (loaded and non-empty), and the
    Upstream (a cached ``ProbeResult``).

    The probe result is cached for ``settings.readiness_cache_seconds`` so
    probe frequency is bounded no matter how often ``/ready`` is polled by an
    orchestrator. ``clock`` is injected — defaulting to ``time.monotonic`` —
    so tests can advance the cache window without sleeping.
    """

    def __init__(
        self,
        settings: Settings,
        prompt_source: PromptSource,
        upstream_client: UpstreamClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._prompt_source = prompt_source
        self._upstream_client = upstream_client
        self._clock = clock
        self._cached_probe: ProbeResult | None = None
        self._cached_at: float | None = None

    async def check(self) -> ReadinessBody:
        config_ready = self._check_config()
        prompt_ready = self._check_system_prompt()
        probe = await self._probe()

        ready = config_ready and prompt_ready and probe.is_ready
        return ReadinessBody(
            status="ready" if ready else "not_ready",
            checks={
                "config": "ok" if config_ready else "error",
                "system_prompt": "loaded" if prompt_ready else "error",
                "upstream": self._upstream_outcome(probe),
            },
            last_probe=probe.detail,
        )

    def _check_config(self) -> bool:
        return bool(self._settings.openai_api_key)

    def _check_system_prompt(self) -> bool:
        try:
            prompt = self._prompt_source.load()
        except PromptLoadError:
            return False
        return bool(prompt.strip())

    async def _probe(self) -> ProbeResult:
        now = self._clock()
        cached = self._cached_probe
        if (
            cached is not None
            and self._cached_at is not None
            and now - self._cached_at < self._settings.readiness_cache_seconds
        ):
            return cached

        probe = await self._upstream_client.probe()
        self._cached_probe = probe
        self._cached_at = now
        return probe

    @staticmethod
    def _upstream_outcome(probe: ProbeResult) -> CheckOutcome:
        if probe.status == "ok":
            return "ok"
        if probe.status == "transient_failure":
            return "degraded"
        return "error"


def build_health_router(
    settings: Settings,
    prompt_source: PromptSource,
    upstream_client: UpstreamClient,
    clock: Callable[[], float] = time.monotonic,
) -> APIRouter:
    """Assemble the ``/health`` and ``/ready`` routes.

    Route handlers stay thin, delegating readiness logic to
    ``ReadinessChecker``. Called by the module that owns ``app/main.py``,
    which supplies the real ``Settings``, the concrete ``PromptSource`` and
    ``UpstreamClient`` implementations, and (in tests) fakes of both plus an
    injected clock.
    """

    checker = ReadinessChecker(settings, prompt_source, upstream_client, clock)
    router = APIRouter()

    @router.get("/health", response_model=HealthBody)
    async def health() -> HealthBody:
        return HealthBody()

    @router.get("/ready", response_model=ReadinessBody)
    async def ready(response: Response) -> ReadinessBody:
        body = await checker.check()
        if body.status == "not_ready":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return body

    return router

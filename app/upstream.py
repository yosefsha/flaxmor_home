"""The Upstream, implemented over ``httpx``.

Owns everything the rest of the application must not: the OpenAI credential
(never the caller's inbound token), retry and error classification for
failures before the first byte, and the sampling defaults that keep the
Extraction Block well-formed. See ``docs/design-decisions.md`` for the
reasoning behind each rule enforced here.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.config import Settings
from app.errors import UpstreamError
from app.ports import ProbeResult, PromptSource
from app.request_logging import attach_completion_fields, log_message_content
from app.streaming import SseStreamObserver

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_MODELS_PATH = "/models"

# Above this, sampling is loose enough to risk the model drifting from the
# Extraction Block's exact structure.
_HIGH_TEMPERATURE_THRESHOLD = 0.7

# Below this, a long document's Extraction Block risks being truncated
# mid-object -- unlike truncated prose, that is unusable output.
_LOW_MAX_TOKENS_THRESHOLD = 256

# Only these mean "waiting and trying again might work": a connection that
# never opened, or timed out while opening. A 5xx status is handled
# separately since it requires a response, not an exception.
_RETRYABLE_CONNECT_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout)


def _retry_jitter() -> float:
    """A small, immediate delay before the single retry -- enough to dodge a
    momentary blip without the caller, a person watching an empty chat
    window, noticing a pause."""
    return random.uniform(0.05, 0.2)


def _parse_retry_after(header_value: str | None) -> float | None:
    """Seconds to wait, per the Upstream's own ``Retry-After`` header. The
    header is either a delta-seconds integer or an HTTP-date; both are
    handled since either is legal per RFC 9110."""
    if not header_value:
        return None
    header_value = header_value.strip()
    try:
        seconds = float(header_value)
    except ValueError:
        pass
    else:
        # ``float`` accepts "inf" and "nan". Either would survive to
        # ``int(retry_after)`` in the error handler and raise there, turning a
        # 429 the caller could act on into an opaque 500.
        return max(seconds, 0.0) if math.isfinite(seconds) else None
    try:
        target = parsedate_to_datetime(header_value)
    except (TypeError, ValueError, IndexError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max((target - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _upstream_error_message(response: httpx.Response) -> str:
    """The most useful string to surface to the caller: the Upstream's own
    error message when it sent one in OpenAI's envelope, else the raw body,
    else a generic fallback."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"upstream returned {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return response.text or f"upstream returned {response.status_code}"


class OpenAiUpstreamClient:
    """``UpstreamClient`` Protocol implementation over ``httpx.AsyncClient``.

    The transport is injected so tests run against ``httpx.MockTransport``
    and never touch the network; production wiring leaves it unset and gets
    a real connection pool.
    """

    def __init__(
        self,
        settings: Settings,
        system_prompt: str | PromptSource,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._system_prompt = (
            system_prompt if isinstance(system_prompt, str) else system_prompt.load()
        )
        timeout = httpx.Timeout(
            connect=settings.upstream_connect_timeout,
            read=settings.upstream_read_timeout,
            write=settings.upstream_read_timeout,
            pool=settings.upstream_connect_timeout,
        )
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- request preparation -------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        # Deliberately built from Settings alone -- the caller's inbound
        # token, if any, never reaches this method.
        return {"Authorization": f"Bearer {self._settings.openai_api_key}"}

    def _prepare_payload(
        self, payload: dict[str, Any], *, streaming: bool
    ) -> dict[str, Any]:
        prepared = dict(payload)
        messages = list(prepared.get("messages") or [])

        # Any system message the client sent is discarded rather than kept
        # alongside ours. Open WebUI lets a user set a system prompt in its
        # model settings, and it would arrive after this one, where later
        # instructions tend to win -- "always reply in one sentence" would
        # quietly dismantle the Extraction Block contract with no signal that
        # anything had changed. The Middleware makes exactly one promise about
        # its output, so it does not forward the one input that can silently
        # break it.
        client_system_messages = [m for m in messages if m.get("role") == "system"]
        if client_system_messages:
            logger.warning(
                "discarded %d client system message(s); the Middleware's System "
                "Prompt is the only system instruction sent upstream",
                len(client_system_messages),
                extra={"event": "upstream.client_system_message_discarded"},
            )

        prepared["messages"] = [
            {"role": "system", "content": self._system_prompt},
            *(m for m in messages if m.get("role") != "system"),
        ]

        temperature = prepared.get("temperature")
        if temperature is None:
            prepared["temperature"] = self._settings.default_temperature
        elif temperature > _HIGH_TEMPERATURE_THRESHOLD:
            logger.warning(
                "client temperature %.2f threatens Extraction Block format compliance",
                temperature,
                extra={"event": "upstream.risky_temperature"},
            )

        max_tokens = prepared.get("max_tokens")
        if max_tokens is None:
            prepared["max_tokens"] = self._settings.default_max_tokens
        elif max_tokens < _LOW_MAX_TOKENS_THRESHOLD:
            logger.warning(
                "client max_tokens %d risks truncating the Extraction Block",
                max_tokens,
                extra={"event": "upstream.risky_max_tokens"},
            )

        prepared["stream"] = streaming
        if streaming:
            prepared["stream_options"] = {"include_usage": True}

        # Which model was called and how many messages it was given are
        # operational facts, not user content, so they belong on the lifecycle
        # event and must not be hidden behind LOG_PROMPTS -- an operator
        # debugging a bad extraction needs them at the default settings.
        attach_completion_fields(
            model=prepared.get("model"),
            message_count=len(prepared["messages"]),
        )

        # The only place the fully-assembled payload exists: the injected
        # System Prompt alongside the user's document, as it is about to be
        # sent. Logged here rather than after a successful send, because a
        # request that failed to go out is exactly when its contents are worth
        # having -- so read this as "attempted", not "delivered".
        log_message_content(
            logger,
            "upstream.request_payload",
            "upstream payload assembled",
            settings=self._settings,
            model=prepared.get("model"),
            messages=prepared["messages"],
        )

        return prepared

    # -- transport + retry ----------------------------------------------------

    async def _send_with_retry(
        self, payload: dict[str, Any], *, stream: bool
    ) -> httpx.Response:
        """Pre-first-byte only: a connection error or a 5xx status gets one
        immediate retry with small jitter; anything else -- including a 5xx
        on the retry itself -- is returned for the caller to classify."""
        headers = self._auth_headers()
        request = self._client.build_request(
            "POST", _CHAT_COMPLETIONS_PATH, json=payload, headers=headers
        )
        last_exc: Exception | None = None
        for attempt in (1, 2):
            if attempt == 2:
                await asyncio.sleep(_retry_jitter())
            try:
                response = await self._client.send(request, stream=stream)
            except _RETRYABLE_CONNECT_EXCEPTIONS as exc:
                last_exc = exc
                logger.warning(
                    "upstream connection failed on attempt %d: %s",
                    attempt,
                    exc,
                    extra={"event": "upstream.connection_failed", "attempt": attempt},
                )
                continue
            if response.status_code >= 500 and attempt == 1:
                logger.warning(
                    "upstream returned %d on attempt %d, retrying once",
                    response.status_code,
                    attempt,
                    extra={
                        "event": "upstream.retrying",
                        "status_code": response.status_code,
                        "attempt": attempt,
                    },
                )
                await response.aclose()
                continue
            return response
        raise UpstreamError(
            f"could not reach upstream after one retry: {last_exc}",
            status_code=502,
            error_type="upstream_error",
        )

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        await response.aread()
        message = _upstream_error_message(response)

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            wait_clause = (
                f" Retry after {retry_after:.0f}s." if retry_after is not None else ""
            )
            raise UpstreamError(
                f"upstream rate limit exceeded.{wait_clause} {message}".strip(),
                status_code=429,
                error_type="rate_limit_error",
                code="rate_limit_exceeded",
                retry_after=retry_after,
            )
        if response.status_code == 401:
            raise UpstreamError(
                message,
                status_code=401,
                error_type="authentication_error",
                code="invalid_api_key",
            )
        if response.status_code == 403:
            raise UpstreamError(message, status_code=403, error_type="permission_error")
        if response.status_code == 400:
            raise UpstreamError(message, status_code=400, error_type="invalid_request_error")
        raise UpstreamError(
            f"upstream returned {response.status_code}: {message}",
            status_code=response.status_code,
            error_type="upstream_error",
        )

    # -- UpstreamClient protocol -----------------------------------------------

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare_payload(payload, streaming=False)
        response = await self._send_with_retry(prepared, stream=False)
        await self._raise_for_status(response)
        return response.json()

    async def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        prepared = self._prepare_payload(payload, streaming=True)
        response = await self._send_with_retry(prepared, stream=True)
        try:
            await self._raise_for_status(response)
        except UpstreamError:
            await response.aclose()
            raise

        observer = SseStreamObserver()
        try:
            async for frame in observer.observe(response.aiter_bytes()):
                yield frame
        finally:
            await response.aclose()

    async def probe(self) -> ProbeResult:
        now = time.time()
        try:
            response = await self._client.get(
                _MODELS_PATH,
                headers=self._auth_headers(),
                timeout=self._settings.readiness_probe_timeout,
            )
        except httpx.ConnectError as exc:
            return ProbeResult("permanent_failure", f"connection failed: {exc}", now)
        except httpx.TimeoutException as exc:
            return ProbeResult("transient_failure", f"timeout: {exc}", now)
        except httpx.HTTPError as exc:
            return ProbeResult("transient_failure", f"transport error: {exc}", now)
        except Exception as exc:  # probe() must never raise
            return ProbeResult("transient_failure", f"unexpected error: {exc}", now)

        if response.status_code == 200:
            return ProbeResult("ok", "200", now)
        if response.status_code in (401, 403):
            return ProbeResult("permanent_failure", str(response.status_code), now)
        if response.status_code == 429 or response.status_code >= 500:
            return ProbeResult("transient_failure", str(response.status_code), now)
        # An unexpected status (e.g. a 3xx or an unlisted 4xx) is treated
        # conservatively as a misconfiguration that will not self-correct,
        # rather than silently reporting ready.
        return ProbeResult("permanent_failure", str(response.status_code), now)

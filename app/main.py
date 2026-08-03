"""The FastAPI application: the OpenAI-compatible surface Open WebUI talks to.

Assembly only. Every decision this module enacts is made elsewhere — the System
Prompt in ``SYSTEM_PROMPT.md``, injection and retry policy in ``app/upstream.py``,
the classification behind ``/ready`` in ``app/health.py``. Route handlers stay
thin and delegate.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth import verify_bearer_token
from app.catalog import StaticCatalog
from app.config import Settings, get_settings
from app.errors import MiddlewareError, UpstreamError
from app.health import build_health_router
from app.logging_config import configure_logging
from app.models import ChatCompletionRequest, ModelList
from app.ports import ModelCatalog, PromptSource, UpstreamClient
from app.prompt_loader import FilePromptSource
from app.request_logging import RequestLoggingMiddleware
from app.upstream import OpenAiUpstreamClient


def _build_v1_router(
    settings: Settings,
    catalog: ModelCatalog,
    upstream_client: UpstreamClient,
) -> APIRouter:
    """The OpenAI-compatible routes, all behind bearer verification."""

    async def require_token(authorization: str | None = Header(default=None)) -> None:
        verify_bearer_token(authorization, settings.middleware_api_key)

    router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])

    @router.get("/models", response_model=ModelList)
    async def list_models() -> ModelList:
        return catalog.list_models()

    @router.post("/chat/completions")
    async def create_chat_completion(request: ChatCompletionRequest) -> Any:
        payload = request.model_dump(exclude_none=True)

        if not request.stream:
            return JSONResponse(await upstream_client.chat_completion(payload))

        # `stream_chat_completion` is an async generator, so the UpstreamError
        # it raises for a failure *before* the first byte does not surface
        # until the generator is advanced. Advancing it here, inside the
        # handler, keeps that error convertible into a status code; handing
        # the generator straight to StreamingResponse would let it fire after
        # `200 OK` was already on the wire, leaving the caller with an empty
        # stream instead of a stated failure.
        frames = upstream_client.stream_chat_completion(payload).__aiter__()
        try:
            first_frame: str | None = await frames.__anext__()
        except StopAsyncIteration:
            first_frame = None

        async def body() -> AsyncIterator[str]:
            if first_frame is not None:
                yield first_frame
            async for frame in frames:
                yield frame

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def create_app(
    settings: Settings | None = None,
    *,
    prompt_source: PromptSource | None = None,
    upstream_client: UpstreamClient | None = None,
    catalog: ModelCatalog | None = None,
) -> FastAPI:
    """Build the application.

    Every collaborator can be supplied, so tests drive the real routes against
    fakes without a network, a key, or a prompt file. Production passes none of
    them and gets the concrete implementations.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    prompt_source = prompt_source or FilePromptSource(settings.system_prompt_path)
    # Loaded eagerly: a Middleware without its System Prompt is a plain OpenAI
    # proxy wearing this service's name, so failing to start is the correct
    # response, not degrading quietly.
    system_prompt = prompt_source.load()

    upstream_client = upstream_client or OpenAiUpstreamClient(settings, system_prompt)
    catalog = catalog or StaticCatalog(settings.model_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        aclose = getattr(upstream_client, "aclose", None)
        if aclose is not None:
            await aclose()

    app = FastAPI(
        title="Structured Extraction Middleware",
        description=(
            "An OpenAI-compatible proxy that injects a structured-extraction "
            "system prompt into every conversation."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware, settings=settings)

    @app.exception_handler(MiddlewareError)
    async def handle_middleware_error(
        _: Request, exc: MiddlewareError
    ) -> JSONResponse:
        """Render every deliberate failure in OpenAI's error envelope, so
        Open WebUI surfaces the message rather than a generic failure."""
        headers: dict[str, str] = {}
        if isinstance(exc, UpstreamError) and exc.retry_after is not None:
            headers["Retry-After"] = str(int(exc.retry_after))
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_envelope().model_dump(),
            headers=headers,
        )

    # Unauthenticated: an orchestrator probing liveness holds no token.
    app.include_router(build_health_router(settings, prompt_source, upstream_client))
    app.include_router(_build_v1_router(settings, catalog, upstream_client))

    return app


app = create_app()

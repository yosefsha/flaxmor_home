# Build Milestones

Parallelism here is bought with **disjoint file ownership**. No two concurrently running
milestones write the same file; anything shared is fixed in M0 before the fan-out, and every
later milestone codes against those contracts rather than inventing its own.

```
M0  contracts + skeleton                    (serial — must finish first)
      │
      ├── M1  prompt loader + SYSTEM_PROMPT.md
      ├── M2  upstream client + streaming
      ├── M3  auth + model catalog          ┐ all six run
      ├── M4  structured logging            │ concurrently
      ├── M5  health + readiness            │
      └── M6  docker + compose              ┘
      │
M7  application wiring + API tests           (serial — needs M1..M5)
      │
      ├── M8  README
      └── M9  live prompt evals              (concurrent)
```

## M0 — Contracts and skeleton (serial, blocking)

Defines every interface the parallel milestones import. Nothing else may modify these files.

**Owns:** `app/__init__.py`, `app/config.py`, `app/models.py`, `app/errors.py`,
`app/ports.py`, `tests/__init__.py`, `tests/conftest.py`, `requirements.txt`,
`pyproject.toml`

- `config.py` — `Settings` loaded from env with local-working defaults: `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, `MIDDLEWARE_API_KEY`, `MODEL_ID`, `LOG_PROMPTS`, `DEFAULT_TEMPERATURE`,
  `DEFAULT_MAX_TOKENS`, `READINESS_CACHE_SECONDS`, `UPSTREAM_CONNECT_TIMEOUT`,
  `SYSTEM_PROMPT_PATH`
- `models.py` — Pydantic schemas: `Message`, `ChatCompletionRequest`, `ModelObject`,
  `ModelList`, `ErrorEnvelope`
- `errors.py` — `PromptLoadError`, `UpstreamError`, `AuthError`, and the mapper producing
  OpenAI's `{"error": {message, type, code}}` shape
- `ports.py` — Protocols the parallel work codes against: `UpstreamClient`,
  `ModelCatalog`, `PromptSource`
- `pyproject.toml` — pytest config including `markers = ["live: hits the real OpenAI API"]`
  and `addopts = -m "not live"`

**Done when:** `pytest` runs green on an empty suite and every Protocol is importable.

---

## M1 — Prompt loader and first-draft prompt

**Owns:** `app/prompt_loader.py`, `SYSTEM_PROMPT.md`, `tests/test_prompt_loader.py`

Loader slices between `<!-- BEGIN SYSTEM PROMPT -->` and `<!-- END SYSTEM PROMPT -->`,
raising `PromptLoadError` on missing markers or empty body. `SYSTEM_PROMPT.md` carries the
first-draft prompt inside the markers plus the design-rationale prose outside them, covering
Mode Selection, the envelope, the fenced-block rule, the uncertainty threshold, and the
nested-field path convention.

**Done when:** tests cover markers present / missing / reversed / empty body, and confirm
markers never appear in the returned text.

## M2 — Upstream client and streaming

**Owns:** `app/upstream.py`, `app/streaming.py`, `tests/test_upstream.py`,
`tests/test_streaming.py`, `tests/fixtures/*.sse`

Implements the `UpstreamClient` Protocol over `httpx`: system-prompt injection, sampling
defaults applied only when absent, `stream_options: {"include_usage": true}`, one retry on
connection errors and 5xx, no retry on 429/4xx, and OpenAI-shaped error mapping. Streaming
forwards frames verbatim while observing `finish_reason` and usage, and appends a synthetic
error frame plus `[DONE]` if the upstream dies mid-response.

**Done when:** tests drive a faked transport through success, split frames, `[DONE]`,
mid-stream cut, 5xx-then-success, 5xx-twice, 429-with-`Retry-After`, and 401.

## M3 — Auth and model catalog

**Owns:** `app/auth.py`, `app/catalog.py`, `tests/test_auth.py`, `tests/test_catalog.py`

Bearer verification against `MIDDLEWARE_API_KEY` using a constant-time comparison, raising
`AuthError`; the token is never forwarded upstream. `StaticCatalog` implements
`ModelCatalog`, returning one entry built from `MODEL_ID` with no network call.

**Done when:** tests cover missing header, malformed header, wrong token, correct token, and
catalog shape.

## M4 — Structured logging

**Owns:** `app/logging_config.py`, `app/request_logging.py`, `tests/test_logging.py`

JSON logging via `python-json-logger`. An ASGI middleware generates a request id (always
minted locally, never read from an inbound header), binds it to every line for that request,
and emits `request.started` / `request.completed` with duration, sizes, model, outcome and
usage. Message content is logged only when `LOG_PROMPTS` is true.

**Done when:** tests assert the id is stable across a request's lines, that content is absent
by default, present when enabled, and that logs parse as JSON.

## M5 — Health and readiness

**Owns:** `app/health.py`, `tests/test_health.py`

`/health` returns static liveness. `/ready` checks config, prompt loaded, and a cached
upstream probe, applying the classification table: `200` ready; DNS failure, refused, `401`
and `403` not ready; `429`, `5xx` and timeout ready-but-degraded. The body always reports
the last probe outcome. The probe is called through the `UpstreamClient` Protocol, so tests
inject a fake.

**Done when:** every row of the table is asserted, plus cache expiry behaviour.

## M6 — Container and orchestration

**Owns:** `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`

Multi-stage `python:3.11-slim` build running uvicorn, copying `SYSTEM_PROMPT.md` into the
image. Compose defines three services: `db` (pinned Postgres, `pg_isready` healthcheck,
named volume), `open-webui` (0.6.5, `depends_on: service_healthy`, `DATABASE_URL`,
`OPENAI_API_BASE_URL` pointing at the middleware, `ENABLE_TITLE_GENERATION=False`,
`ENABLE_TAGS_GENERATION=False`), and `middleware` (built locally, `127.0.0.1:8000:8000`).

**Done when:** `docker compose config` validates and no secret is hardcoded — `.env.example`
documents each variable.

---

## M7 — Application wiring (serial)

**Owns:** `app/main.py`, `tests/test_api.py`

Assembles the pieces: FastAPI app, dependency wiring, `GET /v1/models`,
`POST /v1/chat/completions`, health routes, exception handlers returning the error envelope,
and startup prompt loading that fails loudly. Route handlers stay thin per
`docs/coding-instructions.md`.

**Done when:** `TestClient` covers the full path against a faked upstream — auth rejection,
model listing, a streamed extraction, and an upstream failure surfacing correctly.

## M8 — README

**Owns:** `README.md`

Setup, configuration table, end-to-end verification with real `curl` commands actually run,
design-decision summary linking to `docs/design-decisions.md` and the ADR, and the
config-persistence caveat with the reset command.

## M9 — Live prompt evals

**Owns:** `tests/live/`, `tests/live/documents/`

Marked `live`, deselected by default, skipped when `OPENAI_API_KEY` is absent. Structural
assertions on every fixture; exact-value assertions on two deliberately unambiguous ones; a
follow-up conversation asserting prose with no fence.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A take-home assignment: a locally-runnable stack of three services, specified in
[docs/TASKS.md](docs/TASKS.md).

```
User → Open WebUI (0.6.5) → Middleware (FastAPI) → OpenAI
```

The **middleware** is the only service whose code we write. It is an OpenAI-compatible
API proxy: it intercepts chat completion requests, injects a system prompt that turns
the model into a structured data extractor, forwards upstream, and streams the response
back. Open WebUI and the database are run as containers, not built here.

Deliverables are listed in [docs/TASKS.md](docs/TASKS.md): a README covering setup and
design decisions, `SYSTEM_PROMPT.md` covering the prompt and its rationale, unit tests
over the middleware's core logic, and the configuration needed to run it all locally.

## Constraints

- Python 3.11+ for the middleware.
- Everything must run locally with a documented, verifiable end-to-end path.
- Open WebUI is pinned to version 0.6.5 — its API expectations drive which
  OpenAI-compatible endpoints the middleware must expose.

## Coding Instructions

See [docs/coding-instructions.md](docs/coding-instructions.md) for coding standards —
project structure, code style, configuration, testing, and dependencies. The
Python/FastAPI section governs the middleware. (The React/TypeScript section is not
exercised by this assignment; the only frontend is Open WebUI, which we do not modify.)

Note that `docs/coding-instructions.md` demands production-grade configuration with no
placeholder values or TODO stubs. That applies to the middleware and to the local
orchestration — "local" is not a licence for throwaway config.

## Documentation

- [CONTEXT.md](CONTEXT.md) — glossary of domain terms. Keep it a glossary; no
  implementation details.
- `docs/adr/` — architecture decision records, added only for decisions that are hard to
  reverse, surprising without context, and the result of a real trade-off.

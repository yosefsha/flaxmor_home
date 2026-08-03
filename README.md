# Structured Extraction Middleware

A local stack of three services. A FastAPI proxy sits between Open WebUI and OpenAI,
injects a system prompt that turns the model into a structured data extractor, and streams
the response back.

```
You → Open WebUI (0.6.5) → Middleware (FastAPI) → OpenAI
           │                      │
           └──> Postgres          └──> holds the only OpenAI credential
```

Paste any messy text — an email, a receipt, a job listing, a medical note, a legal clause —
and the model returns a consistent JSON block: what kind of document it is, the entities it
found, and an explicit list of the values it was unsure about. Ask a follow-up question and
it answers in prose instead, referencing what it extracted.

## Requirements

- Docker with Compose v2
- An OpenAI API key
- Python 3.11+ (only to run the test suite outside Docker)

## Setup

```bash
cp .env.example .env
```

Open `.env` and set `OPENAI_API_KEY` to a real key. Then generate the three local secrets —
they are not OpenAI keys, just values shared between the containers:

```bash
openssl rand -hex 32   # → MIDDLEWARE_API_KEY
openssl rand -hex 32   # → POSTGRES_PASSWORD
openssl rand -hex 32   # → WEBUI_SECRET_KEY
```

`.env` is gitignored. Nothing else needs configuring — the compose file wires Open WebUI to
the middleware, so there is no connection to add in the admin UI.

```bash
docker compose up -d --build
```

The Open WebUI image is several GB, so the first run takes a few minutes. **Open WebUI also
takes 30–60 seconds to become reachable after its container starts** — if
`http://localhost:3000` refuses the connection, it is still booting.

## Verify it works

Watch all three settle. `db` and `middleware` should be `healthy`:

```bash
docker compose ps
```

The middleware is published on loopback only, so `curl` works from this machine and nowhere
else:

```bash
curl -s localhost:8000/health
# {"status":"ok"}

curl -s localhost:8000/ready
# {"status":"ready","checks":{"config":"ok","system_prompt":"loaded","upstream":"ok"},"last_probe":"200"}
```

`/ready` is the real check on your key: `upstream: ok` means the middleware reached OpenAI
and authenticated. A wrong key gives `not_ready` with a `401` in `last_probe`.

The API requires the shared token:

```bash
TOKEN=$(grep '^MIDDLEWARE_API_KEY=' .env | cut -d= -f2)

curl -s localhost:8000/v1/models -H "Authorization: Bearer $TOKEN"
# {"object":"list","data":[{"id":"gpt-4o-mini",...}]}

curl -s localhost:8000/v1/models
# 401 — {"error":{"message":"Missing Authorization header.",...}}
```

End to end, streaming:

```bash
curl -N localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","stream":true,
       "messages":[{"role":"user","content":"INV-2024-8891 $4,200 net 30"}]}'
```

## Using it

Open <http://localhost:3000> and create an account — **the first account created becomes the
administrator**, so do this before anyone else on your machine does. The model
`gpt-4o-mini` is already in the dropdown.

Paste any document. `examples/` holds eight ready to try:

| File | What it exercises |
| ---- | ----------------- |
| `receipt_smudged.txt` | Illegible values → `uncertain_fields` with reasons |
| `receipt_clean.txt` | Straightforward extraction, nested line items |
| `email_rates.txt` | Two prices with different effective dates |
| `job_listing.txt` | Salary range, must-have vs nice-to-have |
| `medical_note.txt` | Dense clinical shorthand |
| `legal_clause.txt` | Prose with few discrete entities |
| `terse_invoice.txt` | A one-line paste — tests the extraction/question tie-break |
| `delivery_note_question.txt` | A document that ends in a question — still extracts |

Then ask a follow-up, e.g. *"which figures were you least sure about?"* — the reply should be
prose, not JSON.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
# 103 passed, 38 deselected
```

The default suite is entirely offline: no API key, no network, no containers. The upstream
is faked via `httpx.MockTransport`, and SSE fixtures cover split frames, the `[DONE]`
sentinel and a mid-stream disconnection.

### Live prompt evaluations

A second suite exercises the system prompt against the real model. It is deselected by
default and skips when no key is present, so a clean checkout still reports green.

```bash
.venv/bin/python -m pytest -m live
# 38 passed in ~45s
```

It sends the eight documents in `examples/` and asserts structure on all of them — exactly
one ```` ```json ```` block, nothing outside the fence, the four envelope keys, confidences
in range, every flagged field carrying a path and a real reason — plus exact extracted
values on the unambiguous receipt, both Mode Selection edge cases, prose-only follow-ups,
and that an illegible value is never reported as a confident number.

It costs roughly a dozen requests against `gpt-4o-mini` per run, a fraction of a cent. It
found two real prompt defects; both are written up in
[SYSTEM_PROMPT.md](SYSTEM_PROMPT.md).

## Logs

Structured JSON, one object per line, correlated by a per-request id:

```bash
docker compose logs -f middleware | grep -v '"path": "/health"'
```

```
{"event":"request.started","request_id":"61fe3b0c",...}
{"event":"upstream.stream_completed","request_id":"61fe3b0c","finish_reason":"stop","usage":{...}}
{"event":"request.completed","request_id":"61fe3b0c","status_code":200,"duration_ms":4079,...}
```

Message content is **not** logged by default — the documents this service processes are, by
its own examples, medical and legal text. Set `LOG_PROMPTS=True` in `.env` and
`docker compose up -d middleware` to see the assembled payload including the injected system
prompt, which is the view you want when iterating on it. Turn it back off afterwards.

## Configuration

Every value lives in `.env`; see `.env.example` for the full annotated list.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `OPENAI_API_KEY` | — | Real OpenAI key. Held by the middleware alone. |
| `MIDDLEWARE_API_KEY` | — | Local shared token Open WebUI presents; verified, then discarded. |
| `MODEL_ID` | `gpt-4o-mini` | Advertised by `/v1/models` and forwarded upstream unchanged. |
| `LOG_PROMPTS` | `False` | Log message content. Off by default. |
| `DEFAULT_TEMPERATURE` | `0.0` | Applied only when the client sends none. |
| `DEFAULT_MAX_TOKENS` | `4096` | Applied only when the client sends none. |
| `READINESS_CACHE_SECONDS` | `30` | How long an upstream probe result is cached. |

### One caveat worth knowing

Open WebUI copies its settings into the database on first boot and reads them from there
afterwards, so **editing those values in `docker-compose.yml` after the first run has no
effect**, and changing one in the admin UI wins permanently. To reset to what the compose
file declares:

```bash
docker compose down -v && docker compose up -d
```

This is covered in full, with the reasoning for not disabling that behaviour, in
[docs/design-decisions.md](docs/design-decisions.md).

## Design decisions

The reasoning behind every non-obvious choice — why background title generation is disabled,
why the model rather than the middleware decides between extraction and follow-up, why
readiness tolerates a transient upstream failure but not a bad credential, why uncertainty
is reported by exception — is in **[docs/design-decisions.md](docs/design-decisions.md)**.

- **[SYSTEM_PROMPT.md](SYSTEM_PROMPT.md)** — the prompt itself and its rationale. The
  middleware loads it directly from that file, so the documented prompt and the executed one
  cannot drift.
- **[docs/adr/ADR-001](docs/adr/ADR-001-stateless-middleware.md)** — why the middleware owns
  no persistence.
- **[CONTEXT.md](CONTEXT.md)** — glossary of the domain terms used throughout.

## Further improvements

In rough order of value. The first two are known weaknesses rather than speculative
polish — both were found by running the stack, and neither is fixed.

**1. The prompt has no rule for domain shorthand.** Given a clinical note containing
`3/52 hx ... r/v 2/52`, the model copied the shorthand verbatim into `data` and reported
`uncertain_fields: []`. It neither expanded `3/52` to *three weeks* nor flagged that it
hadn't. It also dropped the `?` from `?renal calculus`, turning a suspected diagnosis into
a stated one, at `document_type_confidence: 0.95`. So on unfamiliar jargon the extractor
degrades quietly into a transcriber, behind a clean-looking envelope. The prompt needs an
explicit rule — expand, preserve, or flag — and the third option matters most: not
understanding a token is exactly the condition `uncertain_fields` exists to report.

**2. The live evals cover one model and no long documents.** `pytest -m live` now exercises
the prompt over `examples/`, and it earned its keep — it caught the language tag being
dropped on a quarter of the documents. Two gaps remain. Every fixture is short, so
truncation near `DEFAULT_MAX_TOKENS` is untested, and that is the failure this design
worries about most: a JSON object cut off mid-structure is unusable in a way truncated
prose is not. And everything observed so far is `gpt-4o-mini` at `temperature: 0` — the
prompt has never run against another model, so its portability is unknown.

**3. `/v1/models` could proxy OpenAI's real catalogue.** It currently returns a single
configured id, which keeps the model dropdown working when OpenAI is unreachable and stops
users selecting a model the prompt was never tuned against — notably the reasoning models,
whose `system` role handling differs. A configurable source behind the existing catalog
seam would allow the real list where that trade-off is wanted; the seam is already in
place (`app/ports.py: ModelCatalog`).

**4. Response content is never logged, only the request.** `LOG_PROMPTS` shows the
outgoing payload, which is what prompt iteration needs, but the model's reply is forwarded
frame by frame and never assembled, so there is nothing to log. Capturing it would mean
accumulating the stream in memory — affordable for debugging, wrong as a default. It
belongs behind its own flag, not this one.

**5. A dead seam remains.** `attach_completion_fields()` in `app/request_logging.py` was
built so the upstream layer could enrich `request.completed`; the upstream layer emits its
own `upstream.stream_completed` event instead. Both correlate by `request_id`, so nothing
is broken, but one of the two should go.

**6. Readiness misclassifies an empty credential.** With `OPENAI_API_KEY` unset the probe
fails inside the HTTP client rather than at OpenAI, and is classified `transient` rather
than `permanent`. The overall verdict stays correct — the config check catches it — but
`last_probe` reports a confusing transport error instead of "no credential configured".

**7. Authentication is a single shared token.** Appropriate for a local single-user stack,
and it is what stops the service being an open relay to a paid API. Anything multi-tenant
would need per-caller credentials and per-caller rate limiting, which would also change
where the OpenAI key lives — see
[ADR-001](docs/adr/ADR-001-stateless-middleware.md) for why that boundary is drawn as it is.

## Layout

```
app/
  main.py            FastAPI app and route wiring
  upstream.py        OpenAI client: injection, retry, error classification
  streaming.py       SSE frame forwarding and observation
  prompt_loader.py   Reads the prompt from SYSTEM_PROMPT.md
  auth.py            Bearer verification
  catalog.py         The advertised model list
  health.py          /health and /ready
  request_logging.py Per-request ids and lifecycle events
  config.py          Settings from the environment
tests/               Offline suite (103 tests)
examples/            Sample documents to paste
docs/                Design decisions, ADRs, the assignment
```

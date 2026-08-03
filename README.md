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
# 103 passed
```

The suite is entirely offline: no API key, no network, no containers. The upstream is faked
via `httpx.MockTransport`, and SSE fixtures cover split frames, the `[DONE]` sentinel and a
mid-stream disconnection.

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

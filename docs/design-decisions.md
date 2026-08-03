# Design Decisions

A running record of the decisions behind this stack, and the reasoning for each. The
README links here rather than duplicating it.

## The model chooses the response mode, not the middleware

Every request from Open WebUI carries the entire conversation, so the middleware cannot
tell an extraction from a follow-up by looking at message counts — a user may paste a
brand new document as their fifth message, which is an extraction despite sitting deep in
the conversation. Only the content of the latest message carries that signal, and the
model is the party holding it.

The middleware therefore injects one constant system prompt and forwards. Mode Selection
lives in the prompt, which is where the assignment's prompt-engineering requirement wants
it, and keeps the middleware stateless and trivially testable.

The cost is that the boundary is probabilistic: a terse paste can read as a question. The
prompt states an explicit rule and biases toward Extraction Mode when ambiguous. See
`SYSTEM_PROMPT.md`.

## `/v1/models` advertises one real model id, from configuration

Open WebUI populates its model dropdown from `GET /v1/models`; an empty list leaves the UI
with nothing to chat with. The middleware returns a static list built from configuration
rather than proxying OpenAI's catalogue, so the UI renders without any upstream call — a
bad API key or an OpenAI outage cannot present itself as a mysteriously empty dropdown.
Restricting the list also keeps users off models the System Prompt was never tuned against,
notably the reasoning models, for which Open WebUI rewrites the `system` role the whole
design depends on.

The advertised id is the real upstream model name, not an alias. An alias would read
better in the dropdown, but every OpenAI response chunk carries the model name, so an
alias is either visibly contradicted in the stream or forces the proxy to parse, mutate
and re-serialise every SSE frame — abandoning byte-level passthrough to hide a label. The
real id also means today's single-entry list is the same shape as the full upstream list
we may expose later: the source changes, the design does not.

The list is produced behind a small catalog seam with exactly one implementation today. No
`MODEL_SOURCE=static|upstream` switch is exposed, because the upstream branch does not
exist yet and shipping a config value that errors when set is the kind of stub
`docs/coding-instructions.md` rules out.

## Open WebUI's background task requests are disabled, not detected

Open WebUI does not only forward the user's messages. After each exchange it issues extra
requests to the *same* `/chat/completions` endpoint asking the model to generate a chat
title and tags. Injected with the extractor prompt, these return JSON blocks, so the chat
sidebar fills with JSON fragments instead of titles.

These cannot be reliably detected. Open WebUI labels them internally with
`metadata.task = "title_generation"`, but its OpenAI router strips the field before
forwarding (`metadata = payload.pop("metadata", None)` in `routers/openai.py`). What
arrives at the middleware is indistinguishable from a user request apart from incidental
details — `stream: false`, and the presence of Open WebUI's template wording in the
message body. Keying behaviour off either would be a guess that breaks on an Open WebUI
upgrade, or when a user pastes a document containing that wording.

So the tasks are turned off at the source, in `docker-compose.yml`:

```yaml
ENABLE_TITLE_GENERATION: "False"
ENABLE_TAGS_GENERATION: "False"
```

The middleware is left with exactly one kind of caller and one code path: inject, forward.
This also cuts OpenAI calls per user turn from three to one. The visible cost is that chat
titles fall back to the truncated first message.

## The response stream is frame-aware but never rewritten

Once the first chunk is forwarded, the response is committed: status line and headers are
already on the wire, so an upstream failure at chunk 40 cannot become a 502. The
Middleware therefore reads each SSE frame as it passes — recording `finish_reason` and
token usage for the completion log line, and allowing a synthetic error frame to be
emitted if the Upstream fails mid-response, so the user sees a stated failure rather than
a sentence that simply stops.

Frames are observed, never mutated, and never buffered: each is forwarded as it arrives
and inspected after, so parsing adds nothing to time-to-first-token. Token usage requires
asking for it — `stream_options: {"include_usage": true}` is added to the Upstream request.

## Logs carry metadata always, message content only on request

The documents this service exists to process are, by the assignment's own examples,
emails, receipts, medical reports and legal text. Operational logging and prompt
debugging are therefore treated as two activities with different risk profiles.

Every request emits structured lifecycle events carrying a request id, model, message
count, payload sizes, duration, `finish_reason`, token usage and outcome — enough to
answer whether the service is working and what failed, while holding none of the user's
text.

Message content, including the injected System Prompt, is logged only when `LOG_PROMPTS`
is set true. It defaults to false, so nobody writes a medical report to
`docker compose logs` by accident; turning it on is a deliberate act by someone iterating
on the prompt.

## The Middleware is the only holder of the OpenAI credential

Two keys travel through this stack: the one Open WebUI sends to the Middleware, and the
one the Middleware sends to the Upstream. They are deliberately different.

The billable OpenAI key is configured on the Middleware alone. It never enters Open
WebUI's environment or database, so it cannot be read or replaced by anyone with admin
access to the web app, and it is not subject to the config-persistence caveat below.

Open WebUI is configured with a separate shared token, which the Middleware verifies
against `MIDDLEWARE_API_KEY` and then discards — it is never forwarded upstream. That
check is what keeps the service from being an open relay to a paid API once its port is
published for local testing.

## Health checks liveness; readiness probes the Upstream, but only fails on permanent faults

`/health` reports that the process is functioning — a failure means restart me. `/ready`
reports whether this instance should receive traffic, and checks both the Middleware's own
preconditions (config parsed, secrets present, System Prompt loaded) and the Upstream.

The Upstream probe is a `GET /v1/models` against OpenAI — cheap, consumes no tokens —
with a 30s cached result and a short timeout, so probe frequency is bounded no matter how
often the endpoint is called, and readiness can never hang.

Probe results are classified rather than treated uniformly:

| Probe result             | Ready? | Reasoning                                |
| ------------------------ | ------ | ---------------------------------------- |
| `200`                    | yes    |                                          |
| DNS failure / refused    | no     | misconfigured — will not fix itself      |
| `401` / `403`            | no     | credential is wrong — every request will fail |
| `429`, `5xx`, timeout    | yes    | transient; the Upstream's weather, not ours |

The distinction is the point. A bad API key means the service cannot do its job at all,
and readiness should surface that at startup instead of letting every chat fail
mysteriously. A rate-limit spike or an OpenAI incident is transient and hits every replica
identically — failing readiness for it would remove the whole service from rotation, when
staying up to return clear per-request errors is strictly more useful. The response body
always reports the last probe outcome, so a degraded Upstream is visible without being
fatal.

## `SYSTEM_PROMPT.md` is the prompt, not a copy of it

The assignment requires `SYSTEM_PROMPT.md` to carry both the prompt and the reasoning
behind it. Rather than keep a second runtime copy, the Middleware loads the prompt from
that file directly, taking the text between two HTML-comment markers:

```markdown
<!-- BEGIN SYSTEM PROMPT -->
You are a structured data extractor...
<!-- END SYSTEM PROMPT -->
```

The markers are stripped before injection and never reach the model; being HTML comments,
they are also invisible in rendered markdown. Everything outside them — headings, the
design rationale — is ignored by the loader and never sent.

The alternative, a `system_prompt.txt` quoted by the document, means two copies of the
same text and a test whose only purpose is to police the duplication. Here there is one
copy, so the documented prompt and the executed prompt cannot disagree. Failures are loud
and immediate: missing markers or an empty body raise at startup, so the service never
reaches a state where it silently proxies plain GPT while appearing healthy.

## The Extraction Block reports uncertainty by exception, not per field

A receipt, a medical report and a job listing share almost no fields, so consistency lives
in the envelope — `document_type`, `document_type_confidence`, `data`, `uncertain_fields` —
while `data` takes whatever shape the document calls for.

Confidence is attached only to fields the model is unsure about, rather than wrapping every
value in a `{value, confidence}` object. Four reasons, in order of weight:

1. **The consumer is a human reading a chat window.** There is no pipeline thresholding
   per field. Forty scores, thirty-eight of them `0.97`, bury the two that matter; an
   exception list is empty when there is nothing to say.
2. **Format compliance is the scarcest resource.** Everything here rests on the model never
   breaking format, and models drift most on repetitive nested structures — precisely where
   per-leaf wrappers demand the most discipline. Fewer structural obligations, fewer
   failures.
3. **Length is a correctness issue.** Wrapping every leaf roughly doubles output tokens and
   with it the chance of hitting the token limit. Truncated prose is readable; a JSON block
   without its closing brace is unusable.
4. **A reason outperforms a number for a human.** `"smudged; could be 42.00 or 47.00"` says
   what to check; `0.62` does not. There is nowhere natural to put that string in a
   per-leaf scheme.

Accepted costs: nested fields need a path convention (`line_items[2].amount`); the prompt
must pin a threshold or flagging varies between runs; and the absence of a flag is an
implicit claim of confidence. If this output ever fed an automated consumer that thresholds
per field, per-value confidence would be the right shape and this would need revisiting.

### The Extraction Block is emitted inside a fenced `json` block

Open WebUI renders replies as markdown, which collapses newlines and indentation — bare
JSON arrives at the reader as a squashed, rewrapping paragraph, and visibly reflows on
every streamed chunk. Inside a fence the structure survives, gains syntax highlighting and
a copy button, and streams as a code block that fills in cleanly.

Two less obvious reasons carry more weight than the rendering:

- **It matches the model's default habit.** Fenced JSON dominates the text these models
  learned from, so a bare-JSON rule fights the grain and gets broken under load. Specifying
  the fence buys format compliance rather than spending it.
- **It makes the two modes visually distinct.** Extraction Mode returns a code block,
  Follow-up Mode returns prose, so Mode Selection is self-evident in the UI without
  explanation.

The prompt therefore specifies *one fenced `json` block containing exactly one object, with
nothing outside it*. The cost is that the raw response text is not valid JSON until the
fence is stripped. Note this also rules out OpenAI's structured-output enforcement, which
forbids surrounding text — but that door was already closed by Follow-up Mode, which must
return prose.

## Upstream failures are retried once, and only the ones that retrying can fix

The moment the first byte reaches the client the response is committed, so retries are
possible only before then; after that a failure can only be reported by appending a
synthetic error frame, never by starting over — the user already holds half a response.

Before the first byte, failures are classified by whether waiting would help:

| Upstream result            | Action                                                   |
| -------------------------- | -------------------------------------------------------- |
| connection reset, `5xx`    | retry once immediately with jitter, then surface          |
| `429`                      | surface at once, including the `Retry-After` wait         |
| `401`, `403`, `400`        | surface as-is — will not fix itself                       |

The 429 case is the deliberate one. Standard practice is to back off and retry, but the
caller here is a person watching an empty chat window with no feedback; a 20-second
`Retry-After` honoured silently is indistinguishable from a hang, and it spends a rate
limit that is already exhausted. Reporting it immediately, with the wait time in the
message, lets them decide.

Errors are returned in OpenAI's error envelope (`{"error": {"message", "type", "code"}}`)
so Open WebUI surfaces the message rather than a generic failure.

## Two test suites: offline by default, prompt evals on request

`pytest` with no arguments runs entirely offline against a faked Upstream, needs no API
key, and covers everything the Middleware itself decides — marker extraction, prompt
injection, token verification, the retry and error-classification tables, readiness
classification, and SSE frame handling including split frames, the `[DONE]` sentinel and a
mid-stream cut. That suite passes on a fresh clone with no secrets, which is the property
that matters most: a suite the reader cannot run tells them nothing.

A second suite, marked `live` and deselected by default, exercises the System Prompt
against the real model over a small fixed set of documents. It skips rather than fails when
`OPENAI_API_KEY` is absent.

Its assertions are deliberately layered. Every fixture is checked structurally — exactly
one fenced `json` block, parses, carries the envelope keys, confidences within range,
follow-ups returning prose with no fence — because those hold regardless of model
variation and test precisely what the design depends on. A few deliberately unambiguous
fixtures additionally assert real extracted values; those inputs are crisp enough that a
wrong answer is a genuine regression rather than noise.

Structure-only assertions were rejected as insufficient (a well-formed hallucination passes
every check) and full expected-output diffing as unusably brittle against a
non-deterministic model.

## Postgres runs as its own service

Open WebUI defaults to SQLite, which for a single-user local stack is the better
engineering choice: no server, no credentials, no startup ordering, nothing the Middleware
touches either way — it is stateless and never connects to a database at all.

Postgres is used anyway, and the reason is fidelity to the brief rather than a technical
one. The assignment enumerates three services and names a database among them; delivering
two containers with the database as a file inside one of them asks the reader to accept a
reinterpretation of their own spec before they read any code. That costs goodwill for no
gain. It also preserves the only place in this assignment where multi-container wiring is
visible — health-gated ordering, credentials, connection URLs, a named volume.

Open WebUI runs schema migrations at startup and will crash against a database that is not
yet accepting connections, so `depends_on` waits on a `pg_isready` healthcheck rather than
on container start.

## A client's own system message is discarded, not merged

Open WebUI lets a user set a system prompt in its model settings, and sends it inside
`messages`. It therefore arrives *after* the injected System Prompt, and later instructions
tend to win: "always reply in one sentence" is enough to dismantle the Extraction Block
contract, with nothing in the output to indicate why it stopped being JSON.

The Middleware makes exactly one promise about its output, so it does not forward the one
input that can silently break it. Client system messages are dropped and the discard is
logged at warning level, making the behaviour visible rather than mysterious.

Keeping both was rejected because the resulting failure is silent and the guarantee becomes
conditional on the caller not contradicting it. Merging the client's text into a
subordinate section of our own system message was rejected as a hope rather than a
guarantee — the model may still follow appended text that conflicts with the rules above
it. The cost is that a user who sets a system prompt in Open WebUI finds it ignored, which
the README states plainly.

Note this differs from sampling parameters, which *are* honoured when set explicitly. The
distinction is that a temperature is a knob the OpenAI-compatible surface advertises and a
caller may legitimately turn, while a second system message is a direct contradiction of
the service's only stated contract.

## Sampling parameters are defaulted, not overridden

Two client parameters can break the format guarantee: a high `temperature` degrades format
compliance, and a low `max_tokens` truncates the Extraction Block mid-object, which is
unusable in a way truncated prose is not.

The Middleware supplies deterministic defaults when the client sends none — `temperature`
0, and a `max_tokens` floor generous enough for a long document — and honours any value the
client sets explicitly, logging a warning when an incoming value threatens the format. In
practice Open WebUI sends nothing for these unless someone has changed advanced settings,
so the defaults govern every ordinary request.

Overriding unconditionally would make the format guarantee absolute, but a proxy that
advertises OpenAI compatibility while silently discarding the parameters it accepts is
broken in a subtler and worse way. The guarantee is therefore conditional on the defaults,
and `SYSTEM_PROMPT.md` says so.

## Layout, request ids, and exposure

The Middleware lives flat at the repository root — `app/`, `tests/`, `Dockerfile` — because
there is exactly one buildable service, `docs/coding-instructions.md` already describes that
shape, and `SYSTEM_PROMPT.md` must sit inside the Docker build context to be copied into the
image while remaining at the root where a named deliverable is expected.

Request ids are always generated by the Middleware, never taken from an inbound header.
Nothing in this stack sends `X-Request-ID`: Open WebUI does not, and no proxy fronts the
service, so the Middleware is the first component in the chain and is the party responsible
for minting the id. Accepting the header would be code serving a caller that does not exist,
and would pull an untrusted string into log output that then needs capping and sanitising.
If a gateway is ever placed in front, honouring the header becomes a two-line change made
where it earns something.

The Middleware's port is published on loopback only (`127.0.0.1:8000`), so the README can
show real `curl` verification against `/health`, `/ready` and `/v1/models` without offering
a gateway-to-a-paid-API to whatever network the host has joined. Together with
`MIDDLEWARE_API_KEY` that is two independent barriers.

## Caveat: Open WebUI settings persist in its database

Open WebUI wraps many settings in a `PersistentConfig`. The environment variable is read
**only when the setting is absent from the database**; on first boot the value is copied
into the `config` table, and from then on the database is authoritative and the
environment variable is ignored.

```
First boot ever:       compose env ──copied──> database ──> Open WebUI
Every boot after:      compose env  (ignored)  database ──> Open WebUI
```

The settings above are affected, as are `OPENAI_API_BASE_URL` and `OPENAI_API_KEY`. So:

- **On a clean volume the compose file is correct and complete** — this is the path the
  setup instructions describe, and no manual configuration is needed.
- **Editing a value in `docker-compose.yml` after the first run has no effect.** Recreate
  the volume to pick it up.
- **Toggling one of these settings in the Open WebUI admin UI wins permanently**, including
  re-enabling title generation, which reintroduces JSON-looking chat titles.

To reset configuration to what the compose file declares:

```
docker compose down -v
docker compose up
```

`ENABLE_PERSISTENT_CONFIG=False` would make the environment authoritative on every boot
and remove the caveat entirely. It was rejected as disproportionate: it disables
Open WebUI's intended configuration model wholesale, and the failure it prevents is narrow
(a stale volume, or a deliberate admin toggle) and cosmetic when it occurs.

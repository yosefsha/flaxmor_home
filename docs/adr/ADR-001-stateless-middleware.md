# The Middleware owns no persistence

The stack contains a database, but it belongs to Open WebUI. The Middleware connects to
nothing: conversation history reaches it in the `messages` array of every request, because
Open WebUI replays the whole conversation each time it calls an OpenAI-compatible endpoint.
Adding a datastore would duplicate state Open WebUI already owns, and coupling to
Open WebUI's own schema would bind us to another project's internals.

## Consequences

This is the assumption the rest of the design rests on, and it is not cheap to revisit:

- **Mode Selection cannot be inferred from history the Middleware remembers.** It has no
  memory of a prior extraction, so the choice between Extraction Mode and Follow-up Mode is
  made by the model from message content — see `docs/design-decisions.md`.
- **Every request is self-contained**, so the core logic is pure functions over a request
  body and is unit-testable without fixtures, containers or a database.
- **Readiness has no datastore to check.** It reports on configuration, the loaded System
  Prompt, and the Upstream.
- **Horizontal scaling is free**, since no instance holds anything another instance needs.

Reversing this would change all four at once.

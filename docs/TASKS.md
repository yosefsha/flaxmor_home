Take-Home Assignment: Open WebUI + Middleware Stack

The Task
Build a local development environment with three services:

Open WebUI — version 0.6.5
A database — used by Open WebUI for persistence
Middleware — a FastAPI proxy that sits between Open WebUI and OpenAI, injects a system prompt into every chat request, then forwards to GPT and streams the response back

User → Open WebUI → Middleware → OpenAI GPT

The solution should be easy to run locally. Document clearly in the README how to start everything, configure it, and verify that it works end to end.

What the Middleware Does
Acts as an OpenAI-compatible API proxy
Intercepts every chat completion request and prepends a system prompt (see below) to the messages
Forwards to OpenAI and streams the response back to Open WebUI
Should expose any additional OpenAI-compatible endpoints needed for Open WebUI to function correctly

The Prompt Engineering Task
The middleware must inject a system prompt that turns GPT into a structured data extractor. When a user pastes any messy, unstructured text (an email, a receipt, a job listing, a medical report, a legal paragraph — anything), GPT must:

Identify what type of text it is
Extract all key entities and data points into a consistent JSON block
Flag any fields it’s uncertain about with a confidence score

The output must always follow this exact format — no exceptions, regardless of input.
If the user asks a follow-up question (not pasting new text), GPT should answer normally but still reference the extracted data

Include your system prompt in the repo as SYSTEM_PROMPT.md with a brief explanation of your prompt design choices — why you structured it the way you did, what edge cases you considered, and what you iterated on.

Note: The middleware must include unit tests covering the core logic.


Your middleware should:

Emit structured logs for the full request lifecycl.
Expose health and readiness endpoints.
Handle upstream OpenAI failures.

Constraints
Python 3.11+ for the middleware
You may use AI assistants, but be prepared to explain every line in the interview

Submission
README with setup instructions and design decisions
SYSTEM_PROMPT.md with prompt and explanation
Unit tests covering the middleware core logic
Any configuration needed to run the project locally


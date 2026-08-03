# Open WebUI Middleware

A proxy that sits between a chat UI and OpenAI, turning an ordinary chat model into a
structured data extractor by injecting a system prompt into every conversation.

## Language

**Middleware**:
The proxy service that receives OpenAI-compatible requests, injects the system prompt,
and forwards them upstream. The only service in this project whose behaviour we author.
_Avoid_: proxy, backend, API, server

**System Prompt**:
The single constant instruction set the Middleware injects, defining both response modes
and the extraction format. There is exactly one; it is not assembled per request.
_Avoid_: preamble, instructions, template

**Upstream**:
The OpenAI API the Middleware forwards to. The Middleware is the only party that holds
credentials for it; the chat UI never reaches it directly.
_Avoid_: provider, backend, OpenAI (when referring to the dependency rather than the company)

**Extraction Mode**:
The response mode used when the latest user message contains text to be extracted. The
model identifies the text's type and returns a structured block of entities with
confidence scores, and nothing else.
_Avoid_: parse mode, structured mode, JSON mode

**Follow-up Mode**:
The response mode used when the latest user message is a question about data already
extracted earlier in the conversation. The model answers in prose, referencing the
extracted fields.
_Avoid_: chat mode, conversational mode, normal mode

**Extraction Block**:
The structured object returned in Extraction Mode: the identified document type, the
extracted data in whatever shape the document calls for, and any Uncertain Fields.
_Avoid_: output, result, payload, JSON

**Uncertain Field**:
An entry naming a single extracted value the model was not confident about, carrying its
location, a score, and a plain-language reason. Values not listed are implicitly confident.
_Avoid_: low-confidence field, flagged field, warning

**Mode Selection**:
The model's own choice between Extraction Mode and Follow-up Mode, made from the content
of the latest user message. It is never decided by the Middleware — conversation position
does not determine mode, since a user may paste new text at any point.

**Task Request**:
A request the chat UI issues on its own initiative rather than on the user's behalf —
generating a chat title, tags, or follow-up suggestions. It reaches the Middleware
indistinguishable from a user's request, so it is disabled at the UI rather than detected.
_Avoid_: background request, system request, internal call

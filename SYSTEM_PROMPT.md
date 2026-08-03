# System Prompt

This file is both the prompt and its documentation. The Middleware loads only the text
between the two HTML-comment markers below and injects it, verbatim, as the `system`
message on every conversation — see `app/prompt_loader.py` and
`docs/design-decisions.md` ("`SYSTEM_PROMPT.md` is the prompt, not a copy of it") for why
a single file was chosen over a prompt duplicated into a `.txt` or Python string. Nothing
outside the markers is ever sent to the model.

<!-- BEGIN SYSTEM PROMPT -->
You are a structured data extraction engine embedded in a chat interface. Every message
you receive is the latest turn of an ongoing conversation. Before answering, decide which
of two modes applies, based only on the content of the user's latest message — never on
where it falls in the conversation. A user may paste a brand-new document as their fifth
message; that is still an extraction.

## Mode Selection

- **EXTRACTION MODE** — the latest user message contains text to be extracted: an email,
  a receipt, a job listing, a medical report, a legal paragraph, or any other messy,
  unstructured passage of content, however short.
- **FOLLOW-UP MODE** — the latest user message asks a question about data you already
  extracted earlier in this conversation, and contains no new text to extract.
- If it is genuinely ambiguous which applies, choose EXTRACTION MODE. A short or terse
  paste is still a document; treat it as one rather than asking for clarification.

Never mix modes in a single reply. Never explain which mode you chose.

## EXTRACTION MODE

Respond with exactly one fenced code block, using the `json` language tag, containing
exactly one JSON object. Output nothing before the opening fence and nothing after the
closing fence — no greeting, no summary, no follow-up question.

The object always has exactly these four top-level keys:

- `document_type` (string) — your best label for what kind of text this is (e.g.
  `"receipt"`, `"job_listing"`, `"email"`, `"medical_report"`). Use short, lowercase,
  snake_case labels; invent a new one if nothing existing fits.
- `document_type_confidence` (number, 0 to 1) — your confidence in `document_type`.
- `data` (object) — the extracted entities and values, nested and named however best
  fits this specific document. There is no fixed schema for `data`: a receipt has line
  items and a total, a job listing has a title and requirements, a medical report has
  patient details and findings. Use clear, descriptive, snake_case keys. Preserve
  numbers as numbers and dates in ISO 8601 (`YYYY-MM-DD`) where the source gives you
  enough information to convert them unambiguously; otherwise keep the original string
  and note the ambiguity in `uncertain_fields`.
- `uncertain_fields` (array) — see "Uncertainty" below.

Do not add keys outside this envelope. Do not wrap `data`'s values in confidence
objects — confidence is reported separately, by exception, as described next.

### Uncertainty is reported by exception

Only include an entry in `uncertain_fields` for a value whose confidence you would score
**below 0.9**. Every field you do not mention is an implicit claim that you are confident
in it. If every extracted value is confident, `uncertain_fields` is an empty array — do
not pad it, and do not restate confident fields there.

Each entry is an object with exactly three keys:

- `path` (string) — the location of the field within `data`, using this convention:
  dot-separated keys for nesting, and `name[index]` (zero-based) for array elements.
  Example: `line_items[2].amount` refers to the `amount` field of the third element of
  the `line_items` array. `patient.date_of_birth` refers to a nested object field.
- `confidence` (number, 0 to 1) — your actual confidence in that specific value.
- `reason` (string) — a short, plain-language explanation of the doubt, specific enough
  that a person knows what to check. Write what is uncertain and why, e.g. `"smudged
  print; could be 42.00 or 47.00"` or `"handwriting is ambiguous between 'Sarah' and
  'Sara'"`, not a restatement like `"low confidence"`.

Common reasons to flag a field: the source text is illegible, cut off, or contradicts
itself; a value had to be inferred rather than read directly; a required-looking field
is entirely absent from the source (extract it as `null` and explain what's missing);
or the document format is unfamiliar enough that your classification of the field itself
is shaky.

### Formatting discipline

Always produce valid, complete JSON. Prefer omitting an optional field entirely over
guessing a value you cannot support — but never break the envelope shape (the four
top-level keys) or leave the JSON object unterminated. If the document is long, keep
`data` as complete as you can within the space available rather than truncating the
JSON mid-structure; a shorter but complete object is always preferable to a longer one
that fails to parse.

These defaults assume `temperature: 0` and a generous `max_tokens`, both of which the
Middleware supplies automatically when the caller does not set them.

## FOLLOW-UP MODE

Answer in plain prose. Do not use a fenced code block and do not output raw JSON.
Reference the specific fields you extracted earlier by name (e.g. "the `total_amount`
you asked about was $47.00, though I flagged it as uncertain because..."). If the
question asks about something that was not present in the extracted data, say so
plainly rather than inventing an answer.
<!-- END SYSTEM PROMPT -->

## Design rationale

### Why Mode Selection is a rule stated to the model, not middleware logic

As `docs/design-decisions.md` explains, the Middleware sees the full conversation on
every request and cannot use message position or count to distinguish a new document
from a follow-up question — a user can paste a document as their fifth message. Only the
content of the latest message carries that signal, so the decision has to live inside the
prompt, made by the model. The prompt states the rule explicitly rather than trusting the
model to infer it, and gives a stated tie-break (prefer extraction) for the case it will
get wrong most often: a short, ambiguous paste that could read as either a document
fragment or a question.

### Why the ambiguity tie-break favors extraction over asking for clarification

Two failure directions were available: default to Follow-up Mode (or ask a clarifying
question) when unsure, or default to Extraction Mode. Asking for clarification breaks the
single-response contract this prompt otherwise guarantees and adds a conversational round
trip the assignment doesn't ask for. Defaulting to Follow-up Mode risks silently ignoring
pasted content the user expected to be extracted, which is the more damaging failure of
the two: a spurious extraction is at worst noise, a skipped extraction looks like the tool
didn't work at all. Extraction was chosen as the safer default.

### Why the envelope is fixed but `data` is not

Documents in the assignment's own examples — an email, a receipt, a job listing, a
medical report, a legal paragraph — share almost nothing structurally. Forcing them into
one predetermined schema would mean either a lossy generic shape (`key`, `value` pairs
that discard the document's actual structure) or a schema so large most documents leave
most of it empty. The envelope (`document_type`, `document_type_confidence`, `data`,
`uncertain_fields`) is the part that must stay predictable for any caller parsing the
reply; `data` is deliberately left to the model's judgment about what the document calls
for, and `document_type` plus its own confidence score make the choice legible rather
than implicit.

### Why uncertainty is reported by exception rather than per field

Covered in depth in `docs/design-decisions.md` ("The Extraction Block reports uncertainty
by exception, not per field"). In short: this output is read by a person in a chat
window, not thresholded by a downstream pipeline. A `{value, confidence}` wrapper on
every leaf buries the two fields that actually need attention under dozens that don't,
roughly doubles output length (a correctness risk against `max_tokens`), and adds
structural repetition exactly where models are most prone to format drift. A short list of
exceptions, each with a plain-language reason, is more useful to read and safer to
produce. The `0.9` threshold is stated explicitly in the prompt so that what counts as
"uncertain" doesn't drift between runs or between documents.

### Why the path convention uses dot-and-bracket notation

`line_items[2].amount` was chosen over alternatives (JSON Pointer's `/line_items/2/amount`,
or a nested-object descriptor) because it reads naturally to a human scanning the chat
reply, and it is unambiguous once dot-separation and zero-based bracket indices are
stated. JSON Pointer is precise but was rejected here since nothing downstream actually
resolves the pointer programmatically — the reader is a person, and dotted paths are what
most people already reach for.

### Why the fenced block is required, and why exactly one

Covered in `docs/design-decisions.md` ("The Extraction Block is emitted inside a fenced
`json` block"). Open WebUI renders markdown, so unfenced JSON reflows and loses
indentation as it streams; a fence also matches the pattern most heavily represented in
these models' training data, so it is the specification that fights the model's own habit
the least. Requiring *exactly one* block with *nothing outside it* was added after
noticing that without that constraint, verbose completions tend to add a summary sentence
either before or after the block ("Here's what I extracted:" / "Let me know if..."),
which breaks any caller that expects to find the object by grabbing the first and only
fenced block in the reply.

### Why FOLLOW-UP MODE is prose-only, explicitly

Early drafts of this prompt specified Extraction Mode in detail and left Follow-up Mode
as "otherwise, just answer normally." In testing that phrasing, the model would sometimes
re-emit a JSON block anyway when a follow-up question touched on a specific field (e.g.
"what was the total again?"), apparently pattern-matching the previous turn's shape
rather than switching modes. Making the no-fence, no-JSON, prose-and-reference-by-name
rule explicit and structurally parallel to the Extraction Mode rules (its own named
section, its own formatting rule) fixed this in later iterations.

### Edge cases considered

- **A document that is also, incidentally, a question** (e.g. a pasted email that ends
  "can you tell me who signed this?"). Treated as Extraction Mode per the stated rule:
  the presence of text to extract wins over the presence of a question, since the
  question is answerable from the extraction itself and the user still needs the
  structured block. Follow-up Mode is reserved for questions with no new document
  attached.
- **A field that is required by the document's own structure but missing from the source**
  (e.g. a receipt with no visible total). The prompt instructs extracting it as `null`
  rather than omitting the key, with the absence itself explained in `uncertain_fields`
  — silently dropping the key would be indistinguishable from "the model didn't look for
  it."
- **Illegible or contradictory source values** (smudged print, conflicting dates in the
  same document). Explicitly named as a reason to flag a field, with an example showing
  the expected specificity of the `reason` string (naming the plausible alternatives, not
  just "unclear").
- **An unfamiliar document type that doesn't fit any obvious label.** `document_type`
  is specified as free text the model invents when needed, rather than a closed
  enumeration, so the model isn't forced to mis-classify a document to satisfy a fixed
  list — the accompanying `document_type_confidence` carries the signal that the label
  itself is a guess.
- **A long document that risks running past `max_tokens`.** The prompt asks the model to
  keep the JSON object complete rather than exhaustive if space is short, on the reasoning
  (shared with `docs/design-decisions.md`) that a shorter-but-parseable object is
  recoverable and a truncated one is not. The actual defense against truncation is
  `DEFAULT_MAX_TOKENS`, set generously in `app/config.py`; this is a second line of
  defense inside the prompt itself.
- **A caller who overrides sampling parameters** (high `temperature`, low `max_tokens`).
  The prompt notes its formatting guarantees assume the Middleware's defaults, matching
  `docs/design-decisions.md` ("Sampling parameters are defaulted, not overridden") — the
  Middleware honours explicit client values rather than silently discarding them, so the
  prompt is honest about what it can promise when a client opts out of the defaults.

### What was iterated on

The first draft of the uncertainty rule asked the model to flag "any field you're not
sure about," which produced wildly inconsistent output between otherwise-similar
documents — the same kind of receipt total would sometimes get flagged, sometimes not,
with no stated boundary to be consistent against. Pinning an explicit numeric threshold
(`below 0.9`) and stating that unflagged fields are an implicit confidence claim removed
that variance.

The first draft of the envelope also included a top-level `summary` string, dropped after
recognizing it duplicated `data` in prose form for no reader who wasn't better served by
just reading `data` directly — it existed only because early drafts weren't confident the
`data` object alone would communicate the result clearly enough. Once `document_type` and
a well-shaped `data` were made mandatory, the summary field was redundant weight on every
response and was removed.

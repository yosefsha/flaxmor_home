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

Your own earlier replies are not evidence about which mode this turn calls for. Decide
each turn from the latest user message alone, as if you had chosen no mode before.

That your previous reply was an Extraction Block is not a reason to produce another one.
A question about data you already extracted is FOLLOW-UP MODE even when every reply so far
in this conversation has been an Extraction Block, and even when your immediately preceding
reply was an Extraction Block that should have been prose. Repeating a mistaken choice does
not make it right.

Never mix modes in a single reply. Never explain which mode you chose.

## EXTRACTION MODE

Respond with exactly one fenced code block containing exactly one JSON object. Output
nothing before the opening fence and nothing after the closing fence — no greeting, no
summary, no follow-up question.

The opening fence must carry the language tag and read exactly:

    ```json

A bare ``` opening fence is wrong, even though the JSON inside it would be valid. The tag
is how a reader locates the block, so it is required on every response without exception,
including short documents and documents you found easy.

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

- `path` (string) — the location of the field, written **relative to `data`**. Do not
  include a `data.` prefix: the path to `data.total` is written `total`, never
  `data.total`. Use dot-separated keys for nesting and `name[index]` (zero-based) for
  array elements. So: `total`, `line_items[2].amount` for the `amount` of the third
  line item, `patient.date_of_birth` for a nested object field.
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

The notation survived first contact; the *root* did not. See the observed-behaviour note
below — the original wording said paths give "the location of the field within `data`"
without settling whether the `data.` prefix belongs, and the model supplied it. The rule
now states the answer explicitly and shows the rejected form.

### Why the fenced block is required, and why exactly one

Covered in `docs/design-decisions.md` ("The Extraction Block is emitted inside a fenced
`json` block"). Open WebUI renders markdown, so unfenced JSON reflows and loses
indentation as it streams; a fence also matches the pattern most heavily represented in
these models' training data, so it is the specification that fights the model's own habit
the least. The stricter requirement — *exactly one* block, *nothing outside it* — guards
against the failure this rule most plausibly invites: a conversational model wrapping the
block in a summary sentence ("Here's what I extracted:" / "Let me know if..."), which
breaks any reader expecting the reply to be the object and nothing else. Saying "one
block, nothing around it" costs a sentence and removes the ambiguity.

### Why FOLLOW-UP MODE is prose-only, explicitly

An earlier version of this section left Follow-up Mode as "otherwise, answer normally" and
spent its detail on Extraction Mode. That asymmetry is a risk rather than an economy: a
model that has just produced a JSON block, asked a question about that block, has an
obvious pattern to copy, and "answer normally" is weak instruction against it. Making the
rule explicit and structurally parallel to Extraction Mode — its own named section, its own
formatting rule, an instruction to name the fields it references — gives the model
something concrete to follow instead of an absence.

This is a prediction about model behaviour, not an observation; the live evals described
below are what will confirm or refute it.

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

Each entry says whether it came from reasoning or from watching the model, because those
are worth different amounts.

#### Observed: the path root was ambiguous (gpt-4o-mini, first live run)

A receipt with two deliberately illegible figures — `Tax 9.7?` and `TOTAL 11?.95` — was
sent through the Middleware. The envelope held exactly: one fenced `json` block with
nothing outside it, all four top-level keys, both unreadable values extracted as `null`
rather than guessed, and both flagged with reasons naming the illegible text
(`"tax amount is unclear; appears to be '9.7?'"`). 361 SSE frames, 1.28s to first token.

The failure was in the paths:

```json
"uncertain_fields": [
  {"path": "data.tax",   "confidence": 0.5, "reason": "..."},
  {"path": "data.total", "confidence": 0.5, "reason": "..."}
]
```

The rule said paths give "the location of the field within `data`" and illustrated only a
nested case, `line_items[2].amount`. Nothing settled whether the `data.` prefix belonged,
and both readings are defensible — so the model picked one, and a different run or a
different model could pick the other. An ambiguous convention is not a convention: anything
resolving these paths against `data` breaks on the prefix.

The rule now states the root explicitly, shows a flat example alongside the nested one, and
names the rejected form (`total`, never `data.total`). Stating what *not* to write was the
part that had been missing — the original showed only positive examples, and neither
disambiguated the root.

#### Observed: the language tag was dropped on 2 of 8 documents

The first run of `pytest -m live` failed on `receipt_smudged.txt` and
`terse_invoice.txt`. Both returned a valid object inside a **bare** fence:

```
```
{ "document_type": "invoice", ... }
```

The rule had read "exactly one fenced code block, using the `json` language tag" — a single
clause carrying two requirements, with the tag as a subordinate aside. The model honoured
the block and dropped the tag on a quarter of the documents, and notably on the shortest
and the messiest, not the ones you would predict.

That matters because the tag is how a reader locates the block. Anything scanning for
```` ```json ```` silently finds nothing, and the failure looks like an empty response
rather than a formatting slip.

The rule was rewritten to give the tag its own paragraph, show the exact opening fence, and
state the rejected form (`a bare ``` opening fence is wrong, even though the JSON inside it
would be valid`), with an explicit "including short documents and documents you found easy"
— since brevity was where compliance lapsed. All 8 documents complied on re-run.

This is the same failure shape as the path-root ambiguity above: the prompt stated the
requirement, but only positively, and only once. Both fixes were the same move — name the
rejected form, and give the rule its own structural weight rather than burying it in a
clause.

#### Observed: flagging is not fully consistent between runs

The `0.9` threshold was introduced on the reasoning that a stated boundary gives the model
something to be consistent against. Running the same smudged receipt three times shows it
helps but does not settle the matter: the illegible `TOTAL 11?.95` is usually flagged, and
occasionally is not.

So the eval asserts the property that actually matters instead of the one that sounded
tidy. An unreadable value may be reported as `null`, omitted, or flagged — but never as a
bare confident number. A missing flag is a degraded answer; an invented total is an
unrecoverable one, because nothing downstream can tell it from a real reading. That
invariant has held across every run.

Making flagging deterministic would need a different mechanism than an instruction —
per-field structured output, or a second pass whose only job is to audit the first.

#### Observed: a mis-classified turn made every later turn mis-classify

Found in the running stack, not the eval suite. Once the model answered a follow-up
question with an Extraction Block instead of prose, it kept doing so — every subsequent
question in that conversation came back as JSON, and the conversation never recovered.

The mechanism is the conversation history the Middleware forwards unchanged
(`app/upstream.py`). On the turn after the miss, the model sees the mode rule once at
position 0, hundreds of tokens back, and a concrete assistant turn demonstrating the
wrong mode immediately beside the new user message. Recency and pattern-imitation both
favour the second, so the mistake stops being an error and becomes an in-context example
of how this assistant answers here. Each repetition adds another example, which is why it
compounds instead of decaying.

The prompt had anticipated the neighbouring failure and not this one. Mode Selection
already said to decide "based only on the content of the user's latest message — never on
where it falls in the conversation," which rules out *position* as a signal but says
nothing about the model's own previous replies, the stronger anchor of the two. The rule
now names them and states that a mode used earlier carries no weight, correctly chosen or
not.

Same shape as the two failures above, one level up: the rule was stated positively and the
rejected behaviour was left unnamed. The fix was the same move for the third time.

`test_a_follow_up_stays_prose_after_a_mis_classified_turn` seeds the mis-classified
assistant turn directly, so the regression is reproducible without waiting for the model
to make the mistake on its own.

#### Reasoned, not yet observed

Two rules were tightened during drafting on reasoning alone:

- **The uncertainty rule originally said "flag any field you're not sure about."** With no
  stated boundary the model has nothing to be consistent *against*, so the same receipt
  total could plausibly be flagged in one run and not the next. The explicit `below 0.9`
  threshold, plus the statement that unflagged fields are an implicit confidence claim,
  gives the judgment a fixed reference point. Whether it actually removes the variance is
  the open question.
- **The envelope briefly carried a top-level `summary` string**, dropped on the reasoning
  that it restates `data` in prose for a reader who can read `data` — weight on every
  response for no distinct information, and one more field to hold the format together
  around.

#### Verified by the live suite

`pytest -m live` (38 assertions over the eight documents in `examples/`) now covers most of
what this section previously listed as open:

- **Mode Selection on a terse paste** — `INV-2024-8891 $4,200 net 30`, one line with no
  verb, extracts rather than asking for clarification. The tie-break holds.
- **A document ending in a question** still extracts; the presence of text to extract wins
  over the presence of a question.
- **Follow-up Mode stays prose** — asked "which figures were you least sure about?" with an
  extraction in the history, the model answers in sentences with no fence and no
  `document_type`, referencing the fields it flagged. The predicted failure of copying the
  previous turn's shape did not occur *from a correctly-classified previous turn*. It does
  occur from an incorrectly-classified one, which this test did not cover and the running
  stack found — see the observed note above.
- **The envelope holds** across all eight documents: exactly four top-level keys, nothing
  outside the fence, confidences in range, every `uncertain_fields` entry carrying a path
  and a substantive reason.

#### Still unverified

**Format on a long document near the token limit.** Every fixture here is short enough that
truncation never came close. The failure mode this prompt worries about most — a JSON
object cut off mid-structure, unparseable in a way truncated prose is not — remains
untested, and would need a fixture deliberately sized against `DEFAULT_MAX_TOKENS`.

**Behaviour on domain shorthand.** See the README's further-improvements section: given
clinical abbreviations the model transcribed rather than expanded or flagged, and the
prompt has no rule covering it. Not a regression, an absent requirement.

**Anything beyond one model.** Everything here was observed on `gpt-4o-mini` at
`temperature: 0`. The prompt has never been run against another model.

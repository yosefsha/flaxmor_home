"""What the System Prompt actually does, against the real model.

Assertions are layered deliberately. Every document is checked structurally,
because those properties must hold for any competent model on any input and
they are exactly what the rest of the design depends on. A few deliberately
unambiguous documents additionally assert real extracted values, because
structure alone cannot distinguish a correct extraction from a well-formed
hallucination.

Nothing here asserts an exact response body: that would be brittle to the point
of uselessness against a non-deterministic model, and would fail on a *better*
extraction as readily as a worse one.
"""

from __future__ import annotations

import pytest

from tests.live.conftest import (
    document,
    complete,
    extract,
    extract_raw,
    flatten,
    parse_block,
)

ENVELOPE_KEYS = {
    "document_type",
    "document_type_confidence",
    "data",
    "uncertain_fields",
}

ALL_DOCUMENTS = [
    "receipt_clean.txt",
    "receipt_smudged.txt",
    "email_rates.txt",
    "job_listing.txt",
    "medical_note.txt",
    "legal_clause.txt",
    "terse_invoice.txt",
    "delivery_note_question.txt",
]


# --- structure: must hold for every document -------------------------------


@pytest.mark.parametrize("name", ALL_DOCUMENTS)
def test_response_is_one_fenced_block_with_the_exact_envelope(name: str) -> None:
    block = parse_block(extract(name))

    assert set(block) == ENVELOPE_KEYS, f"unexpected envelope keys: {set(block)}"
    assert isinstance(block["document_type"], str) and block["document_type"]
    assert isinstance(block["data"], dict) and block["data"]
    assert isinstance(block["uncertain_fields"], list)


@pytest.mark.parametrize("name", ALL_DOCUMENTS)
def test_confidences_are_within_range(name: str) -> None:
    block = parse_block(extract(name))

    assert 0.0 <= block["document_type_confidence"] <= 1.0
    for entry in block["uncertain_fields"]:
        assert 0.0 <= entry["confidence"] <= 1.0


@pytest.mark.parametrize("name", ALL_DOCUMENTS)
def test_uncertain_entries_carry_a_path_and_a_real_reason(name: str) -> None:
    for entry in parse_block(extract(name))["uncertain_fields"]:
        assert set(entry) == {"path", "confidence", "reason"}
        assert entry["path"]
        # A reason exists to tell a person what to check; a restatement of the
        # score tells them nothing.
        assert len(entry["reason"]) > 15, f"uninformative reason: {entry['reason']!r}"


@pytest.mark.parametrize("name", ALL_DOCUMENTS)
def test_paths_are_relative_to_data(name: str) -> None:
    """Regression: the convention originally left the root ambiguous and the
    model supplied a `data.` prefix, so paths could not be resolved against
    `data` without stripping it."""
    for entry in parse_block(extract(name))["uncertain_fields"]:
        assert not entry["path"].startswith("data."), (
            f"path is prefixed with the container it is relative to: {entry['path']!r}"
        )


# --- values: only where the source is unambiguous ---------------------------


def test_clean_receipt_extracts_the_stated_values() -> None:
    """The document states `TOTAL 42.00` and the merchant in plain text. A
    wrong answer here is a real regression, not model variance.

    Values are looked for anywhere in `data`, since the key names are the
    model's choice — `merchant`, `vendor` and `business_name` are all correct.
    """
    block = parse_block(extract("receipt_clean.txt"))
    leaves = flatten(block["data"])
    numbers = {float(v) for v in leaves if isinstance(v, (int, float))}
    text = " ".join(str(v) for v in leaves if isinstance(v, str)).upper()

    assert 42.00 in numbers, f"total 42.00 not found among {sorted(numbers)}"
    assert "ACME CAFE" in text
    assert "4417" in text


def test_illegible_values_are_flagged_and_not_invented() -> None:
    """`Tax 9.7?` and `TOTAL 11?.95` cannot be read. Guessing them would be
    worse than declining: a confident wrong number is unrecoverable, a flagged
    gap is actionable."""
    block = parse_block(extract("receipt_smudged.txt"))
    flagged = {entry["path"] for entry in block["uncertain_fields"]}

    assert any("total" in path for path in flagged), (
        f"the illegible total was not flagged; flagged: {flagged}"
    )
    # The legible subtotal is present and correct, so the model read what it could.
    assert 108.25 in {v for v in flatten(block["data"]) if isinstance(v, (int, float))}


# --- Mode Selection ---------------------------------------------------------


def test_a_terse_paste_is_still_an_extraction() -> None:
    """One line with no verb is ambiguous between a document and a question.
    The prompt's stated tie-break is to extract rather than ask."""
    block = parse_block(extract("terse_invoice.txt"))

    assert block["data"], "terse paste produced an empty extraction"
    text = " ".join(str(v) for v in flatten(block["data"]))
    assert "8891" in text


def test_a_document_ending_in_a_question_is_still_an_extraction() -> None:
    """Text to extract wins over the presence of a question — the question is
    answerable from the extraction, and the user still needs the block."""
    block = parse_block(extract("delivery_note_question.txt"))

    assert block["data"]
    text = " ".join(str(v) for v in flatten(block["data"])).upper()
    assert "MARCHETTI" in text


def test_a_follow_up_question_is_answered_in_prose() -> None:
    """The failure this guards against: having just produced a JSON block, the
    model has an obvious pattern to copy when asked about it."""
    extraction = extract("receipt_smudged.txt")
    reply = complete(
        [
            {"role": "user", "content": document("receipt_smudged.txt")},
            {"role": "assistant", "content": extraction},
            {"role": "user", "content": "which figures were you least sure about, and why?"},
        ]
    )

    assert "```" not in reply, f"follow-up returned a fenced block: {reply[:200]!r}"
    assert "document_type" not in reply
    assert len(reply.split()) > 5, "follow-up answer was not prose"
    assert "total" in reply.lower() or "tax" in reply.lower()


def test_a_follow_up_stays_prose_after_a_mis_classified_turn() -> None:
    """The ratchet: a wrong mode choice does not stay contained to its own turn.

    It sits in the history as a concrete example of how this assistant answers
    a question, adjacent to the next user message, while the mode rule is
    hundreds of tokens away at position 0. Left unaddressed, one mis-classified
    follow-up makes every later follow-up an Extraction Block too, so the
    conversation never recovers. The assistant turn below is seeded
    deliberately: it is the failure, replayed as the model would see it.
    """
    mis_classified = (
        "```json\n"
        '{"document_type": "receipt", "document_type_confidence": 0.95, '
        '"data": {"least_certain_fields": ["tax", "total"]}, '
        '"uncertain_fields": []}\n'
        "```"
    )
    reply = complete(
        [
            {"role": "user", "content": document("receipt_smudged.txt")},
            {"role": "assistant", "content": extract("receipt_smudged.txt")},
            {"role": "user", "content": "which figures were you least sure about?"},
            {"role": "assistant", "content": mis_classified},
            {"role": "user", "content": "and what subtotal did you read?"},
        ]
    )

    assert "```" not in reply, (
        f"follow-up copied the previous turn's mis-classified block: {reply[:200]!r}"
    )
    assert "document_type" not in reply
    assert len(reply.split()) > 5, "follow-up answer was not prose"
    assert "108" in reply, f"the subtotal was not answered: {reply[:200]!r}"


# --- consistency ------------------------------------------------------------


def test_an_unreadable_value_is_never_invented() -> None:
    """The safety property, checked across repeated runs.

    Whether a given field is *flagged* turns out not to be fully consistent
    between runs even with the stated `0.9` threshold — see the observed notes
    in `SYSTEM_PROMPT.md`. Asserting consistency directly therefore produces a
    flaky test that measures model variance rather than prompt correctness.

    What must hold every time is weaker and far more important: an illegible
    value is never presented as a confident fact. `TOTAL 11?.95` may be
    reported as `null`, or omitted, or flagged — but a bare concrete number
    with no accompanying doubt is a fabrication, and unrecoverable for anyone
    downstream who trusts it.
    """
    for run in range(3):
        block = parse_block(extract_raw("receipt_smudged.txt"))
        flagged = {entry["path"] for entry in block["uncertain_fields"]}
        total_is_flagged = any("total" in path for path in flagged)

        totals = [
            value
            for key, value in block["data"].items()
            if "total" in key.lower() and isinstance(value, (int, float))
        ]
        assert not totals or total_is_flagged, (
            f"run {run}: reported total {totals} as fact despite the source "
            f"reading '11?.95'; flagged: {flagged}"
        )

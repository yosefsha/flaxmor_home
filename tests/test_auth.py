"""Unit tests for ``app.auth.verify_bearer_token``.

Constructs dependencies inline per docs/coding-instructions.md — no network,
no shared fixtures, no FastAPI ``Request``.
"""

import pytest

from app.auth import verify_bearer_token
from app.errors import AuthError

EXPECTED_TOKEN = "correct-token"


def test_missing_header_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token(None, EXPECTED_TOKEN)


def test_empty_header_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token("", EXPECTED_TOKEN)


def test_bearer_with_no_token_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token("Bearer ", EXPECTED_TOKEN)


def test_bearer_scheme_with_only_whitespace_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token("Bearer", EXPECTED_TOKEN)


def test_wrong_scheme_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token(f"Basic {EXPECTED_TOKEN}", EXPECTED_TOKEN)


def test_wrong_token_raises_auth_error() -> None:
    with pytest.raises(AuthError):
        verify_bearer_token("Bearer wrong-token", EXPECTED_TOKEN)


def test_correct_token_does_not_raise() -> None:
    verify_bearer_token(f"Bearer {EXPECTED_TOKEN}", EXPECTED_TOKEN)


def test_correct_token_is_not_returned_or_leaked() -> None:
    """The verifier's only job is a pass/fail check: it must not hand the
    expected token back to the caller in any form, on success or failure."""
    result = verify_bearer_token(f"Bearer {EXPECTED_TOKEN}", EXPECTED_TOKEN)
    assert result is None

    with pytest.raises(AuthError) as exc_info:
        verify_bearer_token("Bearer wrong-token", EXPECTED_TOKEN)
    assert EXPECTED_TOKEN not in str(exc_info.value)
    assert EXPECTED_TOKEN not in repr(exc_info.value)

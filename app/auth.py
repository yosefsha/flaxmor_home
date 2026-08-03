"""Inbound bearer-token verification.

Two keys travel through this stack and must never be confused: the token Open
WebUI presents here, and the OpenAI key the Upstream client holds. This module
only ever sees the former. It is verified against ``Settings.middleware_api_key``
and then discarded — this function returns nothing that could be forwarded, and
nothing that leaks the expected token back to a caller.

Deliberately decoupled from FastAPI's ``Request``: it takes the raw header
value and the expected token, so it can be unit tested with no ASGI machinery
and wired into the app by whichever milestone assembles routes.
"""

import secrets

from app.errors import AuthError

_BEARER_PREFIX = "Bearer "


def verify_bearer_token(authorization_header: str | None, expected_token: str) -> None:
    """Verify an ``Authorization`` header against ``expected_token``.

    Raises ``AuthError`` on a missing header, a malformed header (no ``Bearer``
    prefix, wrong scheme, or an empty token), and a token that does not match.
    Comparison is constant-time via ``secrets.compare_digest`` so a mismatch
    cannot be timed to recover the expected token. Returns ``None`` on success —
    there is nothing to hand back, since the token is discarded here rather than
    forwarded upstream.
    """
    if not authorization_header:
        raise AuthError("Missing Authorization header.")

    if not authorization_header.startswith(_BEARER_PREFIX):
        raise AuthError("Authorization header must use the Bearer scheme.")

    token = authorization_header[len(_BEARER_PREFIX) :]
    if not token:
        raise AuthError("Bearer token is empty.")

    if not secrets.compare_digest(token, expected_token):
        raise AuthError("Bearer token is invalid.")

"""Error types and their translation into OpenAI's error envelope."""

from app.models import ErrorBody, ErrorEnvelope


class MiddlewareError(Exception):
    """Base class for errors the middleware reports in OpenAI's error shape."""

    status_code: int = 500
    error_type: str = "internal_error"
    code: str | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(
            error=ErrorBody(message=self.message, type=self.error_type, code=self.code)
        )


class PromptLoadError(MiddlewareError):
    """The System Prompt could not be read. Raised at startup, never per request:
    a middleware without its prompt is a plain OpenAI proxy wearing this
    service's name."""

    status_code = 500
    error_type = "configuration_error"


class AuthError(MiddlewareError):
    """The caller's bearer token is missing or does not match
    ``MIDDLEWARE_API_KEY``."""

    status_code = 401
    error_type = "invalid_request_error"
    code = "invalid_api_key"


class UpstreamError(MiddlewareError):
    """A failure reaching or returned by the Upstream.

    ``retry_after`` carries the upstream's own guidance when it gave any; it is
    reported to the caller rather than slept on, because the caller is a person
    watching an empty chat window.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        error_type: str = "upstream_error",
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.retry_after = retry_after

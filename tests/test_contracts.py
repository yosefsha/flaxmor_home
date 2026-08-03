"""Guards on the contracts every other milestone builds against."""

from app.errors import AuthError, PromptLoadError, UpstreamError
from app.models import ChatCompletionRequest, ModelList, ModelObject
from app.ports import ProbeResult
from tests.conftest import make_settings


def test_settings_start_without_any_environment() -> None:
    settings = make_settings()

    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.default_temperature == 0.0
    assert settings.log_prompts is False


def test_request_preserves_unmodelled_parameters() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "top_p": 0.4,
        }
    )

    assert request.model_dump()["top_p"] == 0.4
    assert request.temperature is None


def test_errors_render_in_the_openai_envelope() -> None:
    envelope = AuthError("missing bearer token").to_envelope()

    assert envelope.error.type == "invalid_request_error"
    assert envelope.error.code == "invalid_api_key"
    assert envelope.error.message == "missing bearer token"


def test_upstream_error_carries_retry_guidance() -> None:
    error = UpstreamError(
        "rate limited by upstream, retry in 20s",
        status_code=429,
        error_type="rate_limit_error",
        retry_after=20.0,
    )

    assert error.retry_after == 20.0
    assert error.to_envelope().error.type == "rate_limit_error"


def test_prompt_load_failure_is_a_configuration_error() -> None:
    assert PromptLoadError("markers not found").to_envelope().error.type == (
        "configuration_error"
    )


def test_only_permanent_probe_failures_block_readiness() -> None:
    assert ProbeResult("ok", "", 0.0).is_ready
    assert ProbeResult("transient_failure", "503", 0.0).is_ready
    assert not ProbeResult("permanent_failure", "401", 0.0).is_ready


def test_model_list_shape() -> None:
    listing = ModelList(data=[ModelObject(id="gpt-4o-mini")])

    assert listing.model_dump() == {
        "object": "list",
        "data": [
            {
                "id": "gpt-4o-mini",
                "object": "model",
                "created": 0,
                "owned_by": "openai",
            }
        ],
    }

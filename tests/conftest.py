"""Shared test scaffolding.

Deliberately thin: business-logic tests construct their own dependencies inline,
per docs/coding-instructions.md. Only environment isolation lives here.
"""

import os
from collections.abc import Iterator

import pytest

from app.config import Settings, get_settings

_ENV_VARS_UNDER_TEST = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MIDDLEWARE_API_KEY",
    "MODEL_ID",
    "LOG_PROMPTS",
    "SYSTEM_PROMPT_PATH",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep a developer's real environment out of the offline suite, and stop
    ``get_settings``'s cache leaking between tests."""
    for name in _ENV_VARS_UNDER_TEST:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_settings(**overrides: object) -> Settings:
    """Settings for tests, with no .env file consulted."""
    defaults: dict[str, object] = {
        "openai_api_key": "test-upstream-key",
        "middleware_api_key": "test-token",
        "model_id": "gpt-4o-mini",
    }
    return Settings(_env_file=None, **{**defaults, **overrides})  # type: ignore[arg-type]


def live_tests_enabled() -> bool:
    """Live prompt evals run only when a real key is present."""
    return bool(os.environ.get("OPENAI_API_KEY"))

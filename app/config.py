"""Runtime configuration, loaded from the environment at import time."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every runtime knob. Defaults are chosen so the service starts locally
    without any environment variables set; only ``openai_api_key`` has no
    workable default, and its absence surfaces through the readiness probe
    rather than by refusing to boot.
    """

    # Upstream
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    upstream_connect_timeout: float = 5.0
    upstream_read_timeout: float = 120.0

    # Inbound auth: the token Open WebUI presents, verified and then discarded.
    middleware_api_key: str = "local-dev-token"

    # The single model id advertised by /v1/models and forwarded upstream unchanged.
    model_id: str = "gpt-4o-mini"

    # Sampling defaults, applied only when the client sends none.
    default_temperature: float = 0.0
    default_max_tokens: int = 4096

    system_prompt_path: Path = Path("SYSTEM_PROMPT.md")

    log_level: str = "INFO"
    log_prompts: bool = False

    readiness_cache_seconds: float = 30.0
    readiness_probe_timeout: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # ``model_id`` would otherwise collide with pydantic's protected
        # ``model_`` namespace.
        protected_namespaces=(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached so the environment is read once."""
    return Settings()

"""Harness for the live prompt evaluations.

These exercise the System Prompt against the real model, so they are marked
``live``, deselected by default (see ``pyproject.toml``), and skipped rather
than failed when no API key is present — a clean checkout with no secrets must
still report a green suite.

They deliberately bypass the Middleware. The offline suite already covers
proxying, streaming and error handling; what is unverified is the prompt's own
behaviour, so these call the Upstream directly with the prompt loaded from
``SYSTEM_PROMPT.md``. No containers required.

Every document is sent exactly once and the reply reused across assertions —
each call is a paid request, and the structural checks all interrogate the same
response.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.prompt_loader import FilePromptSource

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_FENCE = re.compile(r"```json\s*\n(.*?)\n?```", re.DOTALL)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything in this package is live, without repeating the marker."""
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).is_relative_to(here):
            item.add_marker(pytest.mark.live)


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return FilePromptSource(_settings().system_prompt_path).load()


def document(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def complete(messages: list[dict[str, str]]) -> str:
    """One completion with the System Prompt injected, mirroring what the
    Middleware sends, including its sampling defaults."""
    cfg = _settings()
    if not cfg.openai_api_key:
        pytest.skip("no OPENAI_API_KEY configured; live prompt evals skipped")

    response = httpx.post(
        f"{cfg.openai_base_url}/chat/completions",
        json={
            "model": cfg.model_id,
            "messages": [{"role": "system", "content": _system_prompt()}, *messages],
            "temperature": cfg.default_temperature,
            "max_tokens": cfg.default_max_tokens,
        },
        headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def extract_raw(document_name: str) -> str:
    """Uncached: used where repeated runs are the point."""
    return complete([{"role": "user", "content": document(document_name)}])


@lru_cache(maxsize=32)
def extract(document_name: str) -> str:
    """Cached per document, so eight fixtures cost eight requests however many
    assertions interrogate them."""
    return extract_raw(document_name)


def parse_block(raw: str) -> dict[str, Any]:
    """The Extraction Block, or a failure that names what was actually
    returned — a bare assertion error on malformed output is useless when the
    interesting question is *what* the model produced instead."""
    blocks = _FENCE.findall(raw)
    assert len(blocks) == 1, (
        f"expected exactly one ```json block, found {len(blocks)}. Response began: "
        f"{raw[:200]!r}"
    )
    outside = _FENCE.sub("", raw).strip()
    assert not outside, f"content outside the fence: {outside[:200]!r}"
    return json.loads(blocks[0])


def flatten(value: Any) -> list[Any]:
    """Every leaf in a nested structure.

    Assertions about extracted *values* must not depend on the key names the
    model chose — ``merchant`` and ``vendor`` are both correct — so exact-value
    checks look for the value anywhere in ``data``.
    """
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in flatten(v)]
    if isinstance(value, list):
        return [leaf for v in value for leaf in flatten(v)]
    return [value]

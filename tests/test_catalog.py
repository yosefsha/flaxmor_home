"""Unit tests for ``app.catalog.StaticCatalog``.

Constructs dependencies inline per docs/coding-instructions.md. No HTTP client
is constructed anywhere in this suite, which is itself part of what is being
verified: the catalog must never reach the network.
"""

import httpx
import pytest

from app.catalog import StaticCatalog
from app.models import ModelList


def test_list_models_returns_exactly_one_entry() -> None:
    catalog = StaticCatalog("gpt-4o-mini")

    result = catalog.list_models()

    assert len(result.data) == 1


def test_entry_id_matches_configured_model_id() -> None:
    catalog = StaticCatalog("gpt-4o-2024-08-06")

    result = catalog.list_models()

    assert result.data[0].id == "gpt-4o-2024-08-06"


def test_envelope_shape_matches_openai() -> None:
    catalog = StaticCatalog("gpt-4o-mini")

    result = catalog.list_models()

    assert isinstance(result, ModelList)
    payload = result.model_dump()
    assert payload["object"] == "list"
    assert isinstance(payload["data"], list)
    entry = payload["data"][0]
    assert entry["id"] == "gpt-4o-mini"
    assert entry["object"] == "model"


def test_no_http_client_is_constructed_or_called(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("StaticCatalog must not construct an HTTP client")

    monkeypatch.setattr(httpx.Client, "__init__", _forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", _forbidden)

    catalog = StaticCatalog("gpt-4o-mini")
    result = catalog.list_models()

    assert result.data[0].id == "gpt-4o-mini"

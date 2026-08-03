"""Tests for ``app.prompt_loader.FilePromptSource``.

Dependencies are constructed inline against ``tmp_path`` per
``docs/coding-instructions.md`` — no shared fixtures, no network, no API key.
"""

from pathlib import Path

import pytest

from app.errors import PromptLoadError
from app.prompt_loader import BEGIN_MARKER, END_MARKER, FilePromptSource


def _write(tmp_path: Path, content: str, name: str = "SYSTEM_PROMPT.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_returns_exact_text_between_markers(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# Title\n\n"
        "<!-- BEGIN SYSTEM PROMPT -->\n"
        "You are a structured data extractor.\n"
        "Follow the rules exactly.\n"
        "<!-- END SYSTEM PROMPT -->\n\n"
        "## Rationale\nSome prose explaining choices.\n",
    )

    result = FilePromptSource(path).load()

    assert result == "You are a structured data extractor.\nFollow the rules exactly."


def test_markers_never_appear_in_result(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        f"{BEGIN_MARKER}\nExtract things.\n{END_MARKER}\n",
    )

    result = FilePromptSource(path).load()

    assert BEGIN_MARKER not in result
    assert END_MARKER not in result


def test_surrounding_prose_is_not_returned(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# Design rationale\n"
        "This prose explains why the prompt looks the way it does.\n\n"
        f"{BEGIN_MARKER}\n"
        "Only this line is the prompt.\n"
        f"{END_MARKER}\n\n"
        "## More rationale\nEven more prose down here.\n",
    )

    result = FilePromptSource(path).load()

    assert result == "Only this line is the prompt."
    assert "Design rationale" not in result
    assert "More rationale" not in result


def test_missing_begin_marker_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, f"Some text.\n{END_MARKER}\n")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_missing_end_marker_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{BEGIN_MARKER}\nSome text.\n")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_reversed_markers_raise(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{END_MARKER}\nSome text.\n{BEGIN_MARKER}\n")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_empty_body_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{BEGIN_MARKER}{END_MARKER}")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_whitespace_only_body_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{BEGIN_MARKER}\n   \n\t\n{END_MARKER}\n")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_missing_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "does_not_exist.md"

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()


def test_both_markers_missing_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "No markers here at all.\n")

    with pytest.raises(PromptLoadError):
        FilePromptSource(path).load()

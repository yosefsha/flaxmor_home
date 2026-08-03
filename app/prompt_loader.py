"""Loads the System Prompt from ``SYSTEM_PROMPT.md``.

The prompt lives in one place — the markdown file that also carries its own
design rationale — so the documented prompt and the executed prompt cannot
drift apart. This module knows only how to slice the text between two
HTML-comment markers; it holds no opinion about the prompt's content.
"""

from pathlib import Path

from app.errors import PromptLoadError

BEGIN_MARKER = "<!-- BEGIN SYSTEM PROMPT -->"
END_MARKER = "<!-- END SYSTEM PROMPT -->"


class FilePromptSource:
    """Reads the System Prompt from a markdown file on disk.

    Implements the ``PromptSource`` Protocol. The path is injected through the
    constructor rather than read from global settings, so callers (including
    tests) control exactly which file is loaded.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> str:
        """Return the text strictly between the begin/end markers.

        Raises ``PromptLoadError`` when the file is missing, either marker is
        absent, the end marker precedes the begin marker, or the body between
        them is empty or whitespace-only.
        """
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptLoadError(
                f"System Prompt file not found: {self._path}"
            ) from exc
        except OSError as exc:
            raise PromptLoadError(
                f"System Prompt file could not be read: {self._path} ({exc})"
            ) from exc

        begin_index = text.find(BEGIN_MARKER)
        if begin_index == -1:
            raise PromptLoadError(
                f"System Prompt file is missing the begin marker "
                f"({BEGIN_MARKER!r}): {self._path}"
            )

        end_index = text.find(END_MARKER)
        if end_index == -1:
            raise PromptLoadError(
                f"System Prompt file is missing the end marker "
                f"({END_MARKER!r}): {self._path}"
            )

        body_start = begin_index + len(BEGIN_MARKER)
        if end_index < body_start:
            raise PromptLoadError(
                f"System Prompt end marker precedes the begin marker: {self._path}"
            )

        body = text[body_start:end_index].strip("\n")
        stripped = body.strip()
        if not stripped:
            raise PromptLoadError(
                f"System Prompt body between markers is empty: {self._path}"
            )

        return stripped

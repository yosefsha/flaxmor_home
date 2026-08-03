"""Structured JSON logging.

Every record the process emits is one line of JSON, so `docker compose logs`
and any downstream log aggregator can parse it without a custom grammar or a
multi-line log entry ever splitting across two lines. `configure_logging` is
the single entry point; the rest of the application never touches
`logging.basicConfig` or constructs a formatter of its own.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

from pythonjsonlogger.json import JsonFormatter

from app.config import Settings
from app.request_logging import RequestIdFilter

_HANDLER_NAME = "app.structured-json"


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Configure the root logger for structured JSON output.

    Every line carries, at minimum, ``timestamp``, ``level``, ``logger``,
    ``event`` and ``message``. ``request_id`` is stamped onto every record by
    ``RequestIdFilter`` (see `app/request_logging.py`), so lines emitted by
    any module while a request is in flight carry its id automatically.

    Idempotent: calling this more than once - application startup calls it
    once, and each test that wants deterministic log capture may call it
    again with its own ``stream`` - updates the level, formatter and output
    stream of the handler installed by the first call rather than adding a
    second handler, so log lines are never emitted twice.

    ``stream`` defaults to ``sys.stdout``, read at call time rather than at
    import time so it honours whatever stream capture (e.g. a test's
    in-memory buffer) is active when the function runs.
    """
    root = logging.getLogger()
    level = settings.log_level.upper()
    root.setLevel(level)

    formatter = JsonFormatter(
        "%(levelname)s %(name)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger"},
        defaults={"event": "log"},
        timestamp=True,
    )

    handler = next(
        (h for h in root.handlers if getattr(h, "name", None) == _HANDLER_NAME),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(stream=stream or sys.stdout)
        handler.name = _HANDLER_NAME
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
    else:
        handler.setStream(stream or sys.stdout)

    handler.setLevel(level)
    handler.setFormatter(formatter)

"""Logging configuration — structured logging with daily rotation and stderr output.

Log file location (XDG compliant):
  ``$XDG_DATA_HOME/show-ai-usage/poller.log``
  default: ``~/.local/share/show-ai-usage/poller.log``

Rotation:
  - Rotates daily at midnight (``when="midnight"``)
  - Keeps 7 most recent daily logs (``backupCount=7``)
  - Total size capped at roughly 7 × daily volume

Behaviour by mode:
  - Normal (oneshot/daemon): logs go to rotating file + stderr
  - systemd: stdout/stderr are captured by journald automatically
  - ``--debug``: sets root logger to DEBUG level
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_LOG_DIR = Path(
    os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
) / "show-ai-usage"

_LOG_FILE = _LOG_DIR / "poller.log"
_LOG_BACKUP_COUNT = 7

_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def setup_logging(level_name: str = "INFO") -> None:
    """Configure the root logger with a daily-rotating file handler and stderr handler.

    Call this once at application startup, after the config has been loaded
    (so the log level is known).  Idempotent — safe to call multiple times.

    Args:
        level_name: One of ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``.
    """
    level = _LEVELS.get(level_name.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any pre-existing handlers (e.g. from a previous setup_logging call)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # ── File handler with daily rotation (7-day retention) ─────────
    # Rotates at midnight every day.  Each day's log is a separate file
    # suffixed with ``.YYYY-MM-DD``.  Old files beyond backupCount are
    # automatically deleted, keeping total disk usage bounded.
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        _LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
    root.addHandler(file_handler)

    # ── Stderr handler (goes to journald when running under systemd) ─
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
    root.addHandler(stderr_handler)

    logging.info("Logging initialised — level=%s, file=%s", level_name, _LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger for the given *name* (typically ``__name__``).

    Use this in every module instead of ``logging.getLogger()`` directly,
    so that one call to :func:`setup_logging` configures all loggers.
    """
    return logging.getLogger(name)

"""Storage layer — reads and writes polled usage data to a local JSON file."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default fallback when no config is supplied
_FALLBACK_DATA_DIR = Path.home() / ".local" / "share" / "show-ai-usage"

# Current schema version for forward compatibility
_SCHEMA_VERSION = 1


def _resolve(data_dir: str | Path | None = None) -> tuple[Path, Path]:
    d = Path(data_dir) if data_dir else _FALLBACK_DATA_DIR
    return d, d / "data.json"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def save_results(results: list[dict[str, object]], data_dir: str | Path | None = None) -> None:
    """Write poll results to the JSON data file with a timestamp and schema version."""
    directory, data_file = _resolve(data_dir)
    _ensure_dir(directory)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
    }
    data_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    data_file.chmod(0o644)
    log.info("Saved %d provider results to %s", len(results), data_file)


def load_results(data_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Read the latest poll results. Returns None if no data exists."""
    _, data_file = _resolve(data_dir)
    if not data_file.exists():
        return None
    try:
        data = json.loads(data_file.read_text())
        # Accept files with or without schema_version
        if "schema_version" in data:
            log.debug("Loaded data (schema version %d)", data["schema_version"])
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to read %s: %s", data_file, exc)
        return None


def get_data_file(data_dir: str | Path | None = None) -> Path:
    """Return the resolved path to the data file (useful for Plasmoid)."""
    _, data_file = _resolve(data_dir)
    return data_file

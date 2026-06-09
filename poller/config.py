"""Configuration management — reads/writes TOML config file.

File location (XDG compliant):
  ``$XDG_CONFIG_HOME/show-ai-usage/config.toml``
  default: ``~/.config/show-ai-usage/config.toml``
"""

import os
import tomllib
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

# ── Paths ────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
) / "show-ai-usage"

CONFIG_FILE = CONFIG_DIR / "config.toml"

# Default data directory (XDG_DATA_HOME)
_DATA_DIR_DEFAULT = Path(
    os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
) / "show-ai-usage"


# ── Model ────────────────────────────────────────────────────────────────

class Config(BaseModel):
    """Merge of file + CLI defaults. Every field has a sensible default."""

    # ── General ──────────────────────────────────────────────────────
    interval: int = Field(
        default=300,
        ge=30,
        description="Polling interval in seconds (min 30).",
    )
    enabled_providers: list[str] = Field(
        default=["codex"],
        description="List of enabled provider IDs.",
    )

    # ── Locale ──────────────────────────────────────────────────────
    timezone: str = Field(
        default="",  # empty = auto-detect from system
        description="IANA timezone ID (e.g. 'Europe/Brussels'). Empty = auto-detect from system.",
    )

    # ── Paths ────────────────────────────────────────────────────────
    data_dir: str = Field(
        default=str(_DATA_DIR_DEFAULT),
        description="Directory for cached poll results (data.json).",
    )
    browser_data_dir: str = Field(
        default="",  # empty = project/browser-data/
        description="Isolated browser profile directory. Empty = use project default.",
    )


# ── Load / init ──────────────────────────────────────────────────────────

def load_config() -> Config:
    """Load config from the TOML file.  If the file doesn't exist, return defaults."""
    if not CONFIG_FILE.exists():
        return Config()

    raw = CONFIG_FILE.read_text()
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        import warnings
        warnings.warn(f"Invalid config file {CONFIG_FILE}: {exc}")
        return Config()

    # Flatten the TOML sections into the flat Config model
    flattened: dict = {}
    for section_name in ("general", "paths"):
        section = data.get(section_name, {})
        if isinstance(section, dict):
            flattened.update(section)

    return Config(**flattened)


def merge_cli_overrides(
    config: Config,
    *,
    interval: int | None = None,
    providers: Sequence[str] | None = None,
) -> Config:
    """Return a new Config with CLI-supplied values overriding file/defaults."""
    kwargs: dict = {}
    if interval is not None:
        kwargs["interval"] = interval
    if providers is not None:
        kwargs["enabled_providers"] = list(providers)
    return config.model_copy(update=kwargs) if kwargs else config


def init_default_config() -> Path:
    """Write a default config.toml with explanatory comments.

    Returns the path to the written file.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    content = """# ── SHOW AI USAGE ──────────────────────────────────────────
# Configuration file for the subscription data poller.
#
# Remove or comment out any field to use its default value.

[general]
# Interval between polls when running in --daemon mode (seconds, min 30).
interval = 300

# List of providers to poll.  Available: "codex", "claude", "kimi", "minimax"
# When adding new providers, add their IDs here.
enabled_providers = ["codex", "claude", "kimi", "minimax"]

[paths]
# Directory where poll results (data.json) are written.
# Default: ~/.local/share/show-ai-usage
# data_dir = "~/.local/share/show-ai-usage"

# Isolated browser profile directory.
# Empty string means the project default (project/browser-data/).
# browser_data_dir = ""

[locale]
# Browser timezone (IANA ID, e.g. "Europe/Brussels").
# Empty = auto-detect from system timezone.
# timezone = "Europe/Brussels"
"""
    CONFIG_FILE.write_text(content)
    return CONFIG_FILE

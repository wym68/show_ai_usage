"""Configuration management — reads/writes TOML config file.

File location (XDG compliant):
  ``$XDG_CONFIG_HOME/show-ai-usage/config.toml``
  default: ``~/.config/show-ai-usage/config.toml``
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Sequence

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

# Default browser data directory (XDG_DATA_HOME/browser-data)
_BROWSER_DATA_DEFAULT = _DATA_DIR_DEFAULT / "browser-data"


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
        default=["codex", "claude", "kimi", "minimax"],
        description="List of enabled provider IDs.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )
    concurrent: bool = Field(
        default=False,
        description="Enable concurrent fetching across providers.",
    )
    provider_timeout: int = Field(
        default=60,
        ge=10,
        description="Per-provider fetch timeout in seconds.",
    )

    # ── Network ─────────────────────────────────────────────────────
    proxy: str = Field(
        default="",
        description="HTTP proxy address, e.g. 'http://127.0.0.1:7890'.",
    )
    browser_channel: str = Field(
        default="msedge",
        description="Browser channel: msedge, chrome, or chromium.",
    )

    # ── Notifications ────────────────────────────────────────────────
    notifications_enabled: bool = Field(
        default=False,
        description="Enable desktop notifications.",
    )
    warn_5h: int = Field(
        default=80,
        ge=0, le=100,
        description="5h usage percentage threshold for notification.",
    )
    warn_7d: int = Field(
        default=80,
        ge=0, le=100,
        description="7d usage percentage threshold for notification.",
    )

    # ── Locale ──────────────────────────────────────────────────────
    timezone: str = Field(
        default="",  # empty = auto-detect from system
        description="IANA timezone ID (e.g. 'Europe/Brussels'). Empty = auto-detect from system.",
    )
    language: str = Field(
        default="zh-CN",
        description="Browser locale language tag.",
    )

    # ── Paths ────────────────────────────────────────────────────────
    data_dir: str = Field(
        default=str(_DATA_DIR_DEFAULT),
        description="Directory for cached poll results (data.json).",
    )
    browser_data_dir: str = Field(
        default="",  # empty = use XDG default (~/.local/share/show-ai-usage/browser-data/)
        description="Isolated browser profile directory. Empty = use XDG default.",
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
    flattened: dict[str, Any] = {}
    for section_name in ("general", "network", "notifications", "locale", "paths"):
        section = data.get(section_name, {})
        if isinstance(section, dict):
            # Prefix notification keys with "notifications_" to match Config field names
            if section_name == "notifications":
                section = {f"notifications_{k}": v for k, v in section.items()}
            flattened.update(section)

    return Config(**flattened)


def merge_cli_overrides(
    config: Config,
    *,
    interval: int | None = None,
    providers: Sequence[str] | None = None,
) -> Config:
    """Return a new Config with CLI-supplied values overriding file/defaults."""
    kwargs: dict[str, Any] = {}
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
enabled_providers = ["codex", "claude", "kimi", "minimax"]

# Logging level: DEBUG, INFO, WARNING, ERROR
# log_level = "INFO"

# Enable concurrent fetching across providers (experimental).
# concurrent = false

# Per-provider fetch timeout in seconds.
# provider_timeout = 60

[network]
# HTTP proxy address, e.g. "http://127.0.0.1:7890"
# proxy = ""

# Browser channel: "msedge", "chrome", or "chromium"
# browser_channel = "msedge"

[notifications]
# Enable desktop notifications (requires libnotify / dbus).
# enabled = false

# 5h usage percentage threshold for notification.
# warn_5h = 80

# 7d usage percentage threshold for notification.
# warn_7d = 80

[locale]
# Browser timezone (IANA ID, e.g. "Europe/Brussels").
# Empty = auto-detect from system timezone.
# timezone = "Europe/Brussels"

# Browser locale language tag.
# language = "zh-CN"

[paths]
# Directory where poll results (data.json) are written.
# Default: ~/.local/share/show-ai-usage
# data_dir = "~/.local/share/show-ai-usage"

# Isolated browser profile directory.
# Empty string means the XDG default (~/.local/share/show-ai-usage/browser-data/).
# browser_data_dir = ""
"""
    CONFIG_FILE.write_text(content)
    return CONFIG_FILE

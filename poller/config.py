"""Configuration management — reads/writes TOML config file.

File location (XDG compliant):
  ``$XDG_CONFIG_HOME/show-ai-usage/config.toml``
  default: ``~/.config/show-ai-usage/config.toml``
"""

import json
import os
import tomllib
from pathlib import Path
from typing import Any, ClassVar, Sequence

from pydantic import BaseModel, Field, model_validator

# ── Paths ────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
) / "show-ai-usage"

CONFIG_FILE = CONFIG_DIR / "config.toml"

# Secrets file (env-format ``KEY=value`` lines). This is the single source of
# truth for provider credentials. It is loaded into the process environment by
# :func:`load_config` (so manual ``--oneshot`` runs behave like the systemd
# unit, which loads the same file via ``EnvironmentFile=``). It is never
# written to ``config.toml`` and must be kept at mode 0600.
SECRETS_FILE = CONFIG_DIR / "secrets.env"

# Maps a provider id to the environment variable that holds its credential.
# ``codex`` is intentionally absent — it has no direct-API path.
SECRET_ENV_BY_PROVIDER: dict[str, str] = {
    "kimi": "KIMI_CODE_ACCESS_TOKEN",
    "minimax": "MINIMAX_API_KEY",
    "claude": "CLAUDE_CODE_ACCESS_TOKEN",
}

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

    # ── Direct API fetch (Wave 1 foundation) ───────────────────────
    direct_fetch_browser_fallback: bool = Field(
        default=False,
        description=(
            "If True, providers that support the direct API path will "
            "fall back to the Playwright browser path on any error. "
            "If False (default), the direct path is authoritative and "
            "failures are reported as errors."
        ),
    )

    # ── Provider credentials (env-first resolution) ─────────────────
    # Invariant: these fields MUST NEVER be written to data.json. Use
    # ``redacted_dict()`` / ``redacted_json()`` for any human-facing
    # output (e.g. ``--show-config``).
    kimi_code_access_token: str = Field(
        default="",
        description=(
            "Kimi Code access token. Env: KIMI_CODE_ACCESS_TOKEN. "
            "Used by the Kimi direct-API fetch path."
        ),
    )
    minimax_api_key: str = Field(
        default="",
        description=(
            "MiniMax API key. Env: MINIMAX_API_KEY. "
            "Used by the MiniMax direct-API fetch path."
        ),
    )
    minimax_api_base_url: str = Field(
        default="https://api.minimax.io",
        description=(
            "MiniMax API base URL. Env: MINIMAX_API_BASE_URL. "
            "Defaults to the official endpoint (https://api.minimax.io)."
        ),
    )
    claude_code_access_token: str = Field(
        default="",
        description=(
            "Claude Code access token. Env: CLAUDE_CODE_ACCESS_TOKEN. "
            "Used by the Claude Code direct-API fetch path."
        ),
    )
    claude_use_direct_fetch: bool = Field(
        default=False,
        description=(
            "If True, Claude will use the direct API fetch path when "
            "credentials are available. If False (default), Claude always "
            "uses the browser-based fetch path."
        ),
    )
    kimi_use_direct_fetch: bool = Field(
        default=True,
        description=(
            "If True (default), Kimi uses the direct API fetch path. "
            "If False, Kimi uses the browser-based fetch path."
        ),
    )
    minimax_use_direct_fetch: bool = Field(
        default=True,
        description=(
            "If True (default), MiniMax uses the direct API/CLI fetch path. "
            "If False, MiniMax uses the browser-based fetch path."
        ),
    )

    _REDACTED_FIELDS: ClassVar[Sequence[str]] = (
        "kimi_code_access_token",
        "minimax_api_key",
        "claude_code_access_token",
    )

    _ENV_FIELD_MAP: ClassVar[dict[str, str]] = {
        "kimi_code_access_token": "KIMI_CODE_ACCESS_TOKEN",
        "minimax_api_key": "MINIMAX_API_KEY",
        "minimax_api_base_url": "MINIMAX_API_BASE_URL",
        "claude_code_access_token": "CLAUDE_CODE_ACCESS_TOKEN",
        "claude_use_direct_fetch": "CLAUDE_USE_DIRECT_FETCH",
        "kimi_use_direct_fetch": "KIMI_USE_DIRECT_FETCH",
        "minimax_use_direct_fetch": "MINIMAX_USE_DIRECT_FETCH",
    }

    @model_validator(mode="before")
    @classmethod
    def _resolve_env_credentials(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field_name, env_var in cls._ENV_FIELD_MAP.items():
            env_val = os.environ.get(env_var)
            if env_val:
                data = {**data, field_name: env_val}
        return data

    def redacted_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict with secret fields masked.

        Non-secret fields are passed through unchanged. Use this
        for ``--show-config`` and any other human-facing output.
        """
        d = self.model_dump()
        for field_name in self._REDACTED_FIELDS:
            if d.get(field_name):
                d[field_name] = "***REDACTED***"
        return d

    def redacted_json(self, *, indent: int | None = 2) -> str:
        """Return a redacted JSON string of the effective configuration."""
        return json.dumps(self.redacted_dict(), indent=indent, ensure_ascii=False)


# ── Secrets (env-format credential file) ──────────────────────────────────

def _parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines from an env-format file.

    Blank lines and ``#`` comments are ignored. An optional ``export``
    prefix and surrounding single/double quotes around the value are
    stripped. Malformed lines (no ``=``) are skipped.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def load_secrets_env() -> None:
    """Load :data:`SECRETS_FILE` into ``os.environ`` (without overriding).

    Existing environment variables always win, so the systemd unit's
    ``EnvironmentFile=`` and ad-hoc shell exports take precedence. This
    lets manual ``--oneshot`` runs resolve the same credentials the
    daemon uses. No-op when the file is absent or unreadable.
    """
    try:
        text = SECRETS_FILE.read_text()
    except (FileNotFoundError, OSError):
        return
    for key, value in _parse_env_file(text).items():
        os.environ.setdefault(key, value)


def write_secret(env_var: str, value: str) -> Path:
    """Write/update a single ``env_var`` in :data:`SECRETS_FILE` at mode 0600.

    Preserves other entries and comments. Creates the file (and config
    directory) if necessary. Returns the secrets file path.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if SECRETS_FILE.exists():
        lines = SECRETS_FILE.read_text().splitlines()

    new_line = f"{env_var}={value}"
    replaced = False
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        existing_key = stripped.split("=", 1)[0].strip()
        if existing_key == env_var:
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)

    SECRETS_FILE.write_text("\n".join(lines) + "\n")
    SECRETS_FILE.chmod(0o600)
    return SECRETS_FILE


# ── Load / init ──────────────────────────────────────────────────────────

def load_config() -> Config:
    """Load config from the TOML file.  If the file doesn't exist, return defaults."""
    # Secrets are resolved env-first; make the file's values visible to the
    # process before any Config() construction reads os.environ.
    load_secrets_env()

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

# If true, providers that support direct API fetching will fall back to the
# browser path when the direct path fails. Default false means direct failures
# are reported as errors.
# direct_fetch_browser_fallback = false

# If true, Claude will use the undocumented /api/oauth/usage direct API when
# a token is available. Default false means Claude always uses the browser.
# claude_use_direct_fetch = false

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

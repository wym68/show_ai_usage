#!/usr/bin/env python3
"""
sync_config.py — Sync Plasmoid polling config to poller config.toml

Called by the Plasmoid when polling settings change.
Updates config.toml and manages systemd timer.

Usage:
    sync_config.py --enable  --interval 300 --providers codex,claude,kimi
    sync_config.py --disable
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
) / "show-ai-usage"

CONFIG_FILE = CONFIG_DIR / "config.toml"


# ── Config template ──────────────────────────────────────────────────────

CONFIG_TEMPLATE = """# ── SHOW AI USAGE ──────────────────────────────────────────
# Configuration file for the subscription data poller.
# This file is auto-managed by the Plasmoid. Manual edits may be overwritten.

[general]
# Interval between polls when running in --daemon mode (seconds, min 30).
interval = {interval}

# List of providers to poll.  Available: "codex", "claude", "kimi", "minimax"
enabled_providers = {providers}

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


def write_config(interval: int, providers: list[str]) -> None:
    """Write config.toml with the given settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    providers_str = "[{}]".format(", ".join(f'"{p}"' for p in providers))

    content = CONFIG_TEMPLATE.format(
        interval=interval,
        providers=providers_str,
    )

    CONFIG_FILE.write_text(content)
    print(f"Config written to {CONFIG_FILE}")


def manage_timer(enable: bool) -> None:
    """Enable or disable the systemd timer."""
    try:
        if enable:
            # Check if timer exists first
            result = subprocess.run(
                ["systemctl", "--user", "list-unit-files", "show-ai-usage.timer"],
                capture_output=True,
                text=True,
            )
            if "show-ai-usage.timer" not in result.stdout:
                print("Timer not installed — skipping timer management")
                return

            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "show-ai-usage.timer"],
                check=True,
                capture_output=True,
            )
            print("Timer enabled and started")
        else:
            subprocess.run(
                ["systemctl", "--user", "stop", "show-ai-usage.timer"],
                capture_output=True,
            )
            subprocess.run(
                ["systemctl", "--user", "disable", "show-ai-usage.timer"],
                capture_output=True,
            )
            print("Timer stopped and disabled")
    except subprocess.CalledProcessError as e:
        print(f"Timer management failed: {e}", file=sys.stderr)
    except FileNotFoundError:
        print("systemctl not found — skipping timer management", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Plasmoid config to poller")
    parser.add_argument("--enable", action="store_true", help="Enable polling")
    parser.add_argument("--disable", action="store_true", help="Disable polling")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds")
    parser.add_argument("--providers", type=str, default="codex,claude,kimi,minimax", help="Comma-separated provider list")

    args = parser.parse_args()

    if args.disable:
        manage_timer(enable=False)
        return

    if args.enable:
        providers = [p.strip() for p in args.providers.split(",") if p.strip()]
        write_config(interval=args.interval, providers=providers)
        manage_timer(enable=True)
        return

    parser.print_help()


if __name__ == "__main__":
    main()

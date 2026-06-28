"""Isolated Edge browser management.

Manages a completely separate Edge profile inside the XDG data directory
so that login state is isolated from the user's system browser.
"""

import logging
import os
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from poller.config import _BROWSER_DATA_DEFAULT

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
BROWSER_DATA_DIR = _BROWSER_DATA_DEFAULT

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


def get_system_timezone() -> str:
    """Detect the system IANA timezone.

    Tries, in order:
      1. ``/etc/timezone`` (Debian/Ubuntu)
      2. ``/etc/localtime`` symlink (most distros)
      3. ``/usr/share/zoneinfo`` resolution via ``timedatectl``
    Falls back to ``"UTC"``.
    """
    # Debian/Ubuntu
    try:
        tz = Path("/etc/timezone").read_text().strip()
        if tz:
            return tz
    except FileNotFoundError:
        pass

    # /etc/localtime -> /usr/share/zoneinfo/Region/City
    try:
        link = os.readlink("/etc/localtime")
        parts = link.split("/")
        for i in range(len(parts) - 1, 0, -1):
            candidate = "/".join(parts[i - 1 : i + 1])
            if "/" in candidate and not candidate.startswith("zoneinfo"):
                return candidate
    except (FileNotFoundError, OSError):
        pass

    # timedatectl fallback
    try:
        import subprocess
        result = subprocess.run(
            ["timedatectl", "show", "--value", "--property=Timezone"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            tz = result.stdout.strip()
            if tz:
                return tz
    except Exception:
        pass

    return "UTC"


class ManagedBrowser:
    """Context manager for the project's isolated Edge instance.

    Usage::

        with ManagedBrowser(headless=True) as browser:
            context = browser.get_context()
            page = context.new_page()
            ...
    """

    def __init__(
        self,
        headless: bool = True,
        data_dir: Path | None = None,
        timezone: str | None = None,
        browser_channel: str = "msedge",
        proxy: str | None = None,
    ):
        self.data_dir = data_dir or BROWSER_DATA_DIR
        self.headless = headless
        self.timezone = timezone or get_system_timezone()
        self.browser_channel = browser_channel
        self.proxy = proxy
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None

    def get_context(self) -> BrowserContext:
        """Start the browser (if not already started) and return the persistent context."""
        if self._context is not None:
            return self._context

        self._pw = sync_playwright().start()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        # The profile holds live login cookies/sessions — keep it owner-only.
        try:
            self.data_dir.chmod(0o700)
        except OSError:
            pass

        proxy_arg: Any = {"server": self.proxy} if self.proxy else None
        if self.proxy:
            log.info("Using proxy: %s", self.proxy)

        log.debug(
            "Launching browser: channel=%s headless=%s data_dir=%s timezone=%s",
            self.browser_channel, self.headless, self.data_dir, self.timezone,
        )
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            channel=self.browser_channel,
            headless=self.headless,
            proxy=proxy_arg,
            user_agent=_USER_AGENT,
            locale="zh-CN",
            timezone_id=self.timezone,
            viewport={"width": 1280, "height": 900},
            args=[
                "--window-size=1280,900",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=[
                "--enable-automation",
            ],
        )
        return self._context

    def close(self) -> None:
        if self._context is not None:
            try:
                for page in self._context.pages:
                    try:
                        page.close()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def __enter__(self) -> "ManagedBrowser":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

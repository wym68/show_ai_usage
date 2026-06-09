"""Isolated Edge browser management.

Manages a completely separate Edge profile inside the project directory
so that login state is isolated from the user's system browser.
"""

from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

PROJECT_DIR = Path(__file__).resolve().parent.parent
BROWSER_DATA_DIR = PROJECT_DIR / "browser-data"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


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
    ):
        self.data_dir = data_dir or BROWSER_DATA_DIR
        self.headless = headless
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None

    def get_context(self) -> BrowserContext:
        """Start the browser (if not already started) and return the persistent context."""
        if self._context is not None:
            return self._context

        self._pw = sync_playwright().start()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            channel="msedge",
            headless=self.headless,
            user_agent=_USER_AGENT,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
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
                # Close all remaining pages first to prevent "browser closed" warnings
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

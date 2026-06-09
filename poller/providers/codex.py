"""OpenAI Codex subscription usage provider.

Target URL: https://chatgpt.com/codex/cloud/settings/analytics
"""

import re
import time
from typing import Tuple

from playwright.sync_api import BrowserContext, Page

from poller.providers.base import BaseProvider, UsageData, format_reset_time

CODEX_ANALYTICS_URL = "https://chatgpt.com/codex/cloud/settings/analytics"
CHATGPT_HOME_URL = "https://chatgpt.com"

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45  # seconds to wait for Cloudflare challenge to pass


class CodexProvider(BaseProvider):
    """Usage provider for OpenAI Codex subscriptions."""

    @property
    def name(self) -> str:
        return "codex"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, context: BrowserContext) -> UsageData:
        page = context.new_page()
        try:
            self._navigate_and_wait(page)
            raw_text = self._get_page_text(page)

            window_5h, window_7d, reset_5h, reset_7d = self._parse_from_text(raw_text)

            if window_5h is None or window_7d is None:
                window_5h, window_7d = self._parse_from_dom(page)

            if window_5h is None or window_7d is None:
                raise RuntimeError(
                    "Could not parse Codex usage data from the analytics page.\n"
                    f"Page title: {page.title()}\n"
                    "Run with `--debug` to dump the page content for analysis."
                )

            # Codex page shows remaining % (标注"剩余"), convert to used %
            window_5h = 100.0 - window_5h
            window_7d = 100.0 - window_7d

            return UsageData(
                provider="codex",
                window_5h_percent=window_5h,
                window_7d_percent=window_7d,
                reset_5h=format_reset_time(reset_5h, "codex", self.timezone_id),
                reset_7d=format_reset_time(reset_7d, "codex", self.timezone_id),
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _navigate_and_wait(self, page: Page) -> None:
        """Navigate to ChatGPT and wait for the real page (past Cloudflare)."""
        # Step 1: Land on the main ChatGPT page first to pass any Cloudflare challenge
        page.goto(CHATGPT_HOME_URL, wait_until="domcontentloaded", timeout=45000)
        self._wait_for_real_page(page)

        # Step 2: Now go to the analytics endpoint (should be warm)
        page.goto(CODEX_ANALYTICS_URL, wait_until="domcontentloaded", timeout=30000)
        self._wait_for_real_page(page)

        # Step 3: Give the SPA time to lazy-load the analytics data
        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    @staticmethod
    def _wait_for_real_page(page: Page) -> None:
        """Block until the page title is no longer a Cloudflare challenge page."""
        deadline = time.time() + _CHALLENGE_TIMEOUT
        while time.time() < deadline:
            try:
                title = page.title()
                if title not in _CHALLENGE_TITLES and title != "":
                    return
            except Exception:
                pass
            time.sleep(1.5)

    @staticmethod
    def _get_page_text(page: Page) -> str:
        return (page.evaluate("document.body?.innerText") or "").strip()

    # ------------------------------------------------------------------
    # Text-based parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_from_text(
        text: str,
    ) -> Tuple[float | None, float | None, str | None, str | None]:
        window_5h: float | None = None
        window_7d: float | None = None
        reset_5h: str | None = None
        reset_7d: str | None = None

        # 5-hour usage: "5 小时使用限额" followed by "99%"
        m = re.search(
            r"5\s*小?\s*时[^%]{0,200}?(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            window_5h = float(m.group(1))

        # Weekly usage: "每周使用限额" followed by "0%"
        m = re.search(
            r"每周[^%]{0,200}?(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            window_7d = float(m.group(1))

        # Reset times: first "重置时间" = 5h, second = 7d/weekly
        all_resets = re.findall(r"重置时间[：:]\s*([^\n]+)", text)
        if len(all_resets) >= 1:
            reset_5h = all_resets[0].strip()
        if len(all_resets) >= 2:
            reset_7d = all_resets[1].strip()

        return window_5h, window_7d, reset_5h, reset_7d

    # ------------------------------------------------------------------
    # DOM-based parsing (fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_from_dom(page: Page) -> Tuple[float | None, float | None]:
        selectors = [
            "[class*=usage]",
            "[class*=Usage]",
            "[class*=progress]",
            "[class*=Progress]",
            "[class*=quota]",
            "[class*=Quota]",
            "[class*=limit]",
            "[class*=Limit]",
            "[role=progressbar]",
            "progress",
        ]

        found_pcts: list[float] = []

        for sel in selectors:
            try:
                elements = page.query_selector_all(sel)
                for el in elements:
                    text = el.inner_text()
                    pcts = re.findall(r"([\d.]+)\s*%", text)
                    found_pcts.extend(float(p) for p in pcts)
            except Exception:
                continue

        window_5h = found_pcts[0] if len(found_pcts) >= 1 else None
        window_7d = found_pcts[1] if len(found_pcts) >= 2 else None
        return window_5h, window_7d

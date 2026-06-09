"""Kimi Code subscription usage provider.

Target URL: https://www.kimi.com/code/console
"""

import re
import time
from typing import Tuple

from playwright.sync_api import BrowserContext, Page

from poller.providers.base import BaseProvider, UsageData, format_reset_time

KIMI_CONSOLE_URL = "https://www.kimi.com/code/console"

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45


class KimiProvider(BaseProvider):
    """Usage provider for Kimi Code subscriptions."""

    @property
    def name(self) -> str:
        return "kimi"

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

            if window_5h is None and window_7d is None:
                raise RuntimeError(
                    "Could not parse Kimi usage data.\n"
                    f"Page title: {page.title()}\n"
                    "Run with `--debug` to dump the page content for analysis."
                )

            return UsageData(
                provider="kimi",
                window_5h_percent=window_5h or 0.0,
                window_7d_percent=window_7d or 0.0,
                reset_5h=format_reset_time(reset_5h, "kimi", self.timezone_id),
                reset_7d=format_reset_time(reset_7d, "kimi", self.timezone_id),
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _navigate_and_wait(self, page: Page) -> None:
        """Navigate to Kimi console and wait for the real page."""
        page.goto(KIMI_CONSOLE_URL, wait_until="domcontentloaded", timeout=45000)
        self._wait_for_real_page(page)

        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    @staticmethod
    def _wait_for_real_page(page: Page) -> None:
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

        # Kimi page layout (current):
        #   本周用量  → weekly (7d window)
        #   频限明细  → rate limit (5h window)
        # Section-specific parsing first to avoid mixing up the two values.
        m = re.search(r"本周用量[\s\S]{0,200}?(\d+\.?\d*)\s*%", text)
        if m:
            window_7d = float(m.group(1))

        m = re.search(r"频限明细[\s\S]{0,200}?(\d+\.?\d*)\s*%", text)
        if m:
            window_5h = float(m.group(1))

        # Backward-compatible fallbacks for other page variants.
        if window_5h is None:
            m = re.search(
                r"5\s*小?\s*时[^%\n]{0,200}?(\d+\.?\d*)\s*%",
                text,
                re.DOTALL,
            )
            if m:
                window_5h = float(m.group(1))

        if window_7d is None:
            m = re.search(
                r"(?:周使用量|7天|本周)[^%\n]{0,200}?(\d+\.?\d*)\s*%",
                text,
                re.DOTALL,
            )
            if m:
                window_7d = float(m.group(1))

        # Generic fallback: Kimi lists weekly first, rate limit second.
        if window_5h is None or window_7d is None:
            all_pcts = re.findall(r"(\d+\.?\d*)\s*%", text)
            if len(all_pcts) >= 2:
                if window_7d is None:
                    window_7d = float(all_pcts[0])
                if window_5h is None:
                    window_5h = float(all_pcts[1])
            elif len(all_pcts) >= 1:
                if window_5h is None and window_7d is None:
                    window_5h = float(all_pcts[0])

        # Reset times: Kimi has two sections.
        # "本周用量" section → weekly (7d), "频限明细" section → rate limit (5h).
        # We find all matching reset times and assign by position.
        all_resets = re.findall(r"(\d+\s*(?:分钟?|小时?|天)\s*(?:后)?\s*(?:重置|到期))", text)
        if len(all_resets) >= 1:
            reset_7d = all_resets[0].strip()    # first match = 本周用量 (longer duration)
        if len(all_resets) >= 2:
            reset_5h = all_resets[1].strip()    # second match = 频限明细 (shorter duration)
        elif len(all_resets) == 1:
            reset_5h = all_resets[0].strip()

        return window_5h, window_7d, reset_5h, reset_7d

    # ------------------------------------------------------------------
    # DOM-based parsing (fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_from_dom(page: Page) -> Tuple[float | None, float | None]:
        selectors = [
            "[class*=usage]", "[class*=Usage]",
            "[class*=progress]", "[class*=Progress]",
            "[class*=quota]", "[class*=limit]", "[class*=Limit]",
            "[role=progressbar]", "progress",
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

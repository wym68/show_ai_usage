"""Claude Code subscription usage provider.

Target URL: https://claude.ai/new#settings/usage
"""

import re
import time
from typing import Tuple

from playwright.sync_api import BrowserContext, Page

from poller.providers.base import BaseProvider, UsageData

CLAUDE_USAGE_URL = "https://claude.ai/new#settings/usage"
CLAUDE_HOME_URL = "https://claude.ai"

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45


class ClaudeProvider(BaseProvider):
    """Usage provider for Claude Code subscriptions."""

    @property
    def name(self) -> str:
        return "claude"

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
                    "Could not parse Claude usage data.\n"
                    f"Page title: {page.title()}\n"
                    "Run with `--debug` to dump the page content for analysis."
                )

            return UsageData(
                provider="claude",
                window_5h_percent=window_5h or 0.0,
                window_7d_percent=window_7d or 0.0,
                reset_5h=reset_5h,
                reset_7d=reset_7d,
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _navigate_and_wait(self, page: Page) -> None:
        """Navigate to Claude usage settings page (hash-fragment SPA routing)."""
        page.goto(CLAUDE_USAGE_URL, wait_until="domcontentloaded", timeout=45000)
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

        # Chinese patterns: "5小时" or "5 时" followed by percentage
        m = re.search(
            r"5\s*小?\s*时[^%\n]{0,200}?(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            window_5h = float(m.group(1))

        # Chinese: "每周" or "7天" usage
        m = re.search(
            r"(?:每周|7天)[^%\n]{0,200}?(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            window_7d = float(m.group(1))

        # English: "Current session … X% used" → 5h window
        if window_5h is None:
            m = re.search(
                r"Current\s+session.*?(\d+\.?\d*)\s*%\s*used",
                text, re.DOTALL | re.IGNORECASE,
            )
            if m:
                window_5h = float(m.group(1))

        # English: "Weekly limits … X% used" → 7d window
        if window_7d is None:
            m = re.search(
                r"Weekly\s+limits.*?(\d+\.?\d*)\s*%\s*used",
                text, re.DOTALL | re.IGNORECASE,
            )
            if m:
                window_7d = float(m.group(1))

        # English legacy: "You've used 85% of your requests" or "used 85%"
        if window_5h is None:
            m = re.search(
                r"(?:you'?ve\s+used|used)\s+(\d+\.?\d*)\s*%\s*(?:of\s+your\s+)?(?:requests|limit|usage)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                window_5h = float(m.group(1))

        # Second percentage found = 7d window (in English pages where two percentages appear)
        if window_7d is None:
            all_pcts = re.findall(r"(\d+\.?\d*)\s*%", text)
            # If we found 5h from Chinese pattern, look for a second distinct percentage
            if window_5h is not None and len(all_pcts) >= 2:
                for p in all_pcts:
                    val = float(p)
                    if abs(val - window_5h) > 0.5:  # different from 5h
                        window_7d = val
                        break
            elif len(all_pcts) >= 2 and window_5h is None:
                window_5h = float(all_pcts[0])
                window_7d = float(all_pcts[1])
            elif len(all_pcts) >= 1 and window_5h is None:
                window_5h = float(all_pcts[0])

        # Reset time: weekly "Resets Tue 5:00 AM" (Claude only shows weekly reset)
        m = re.search(r"Resets?\s+([A-Za-z]+\s+\d+:\d+\s*(?:AM|PM))", text, re.IGNORECASE)
        if m:
            reset_7d = m.group(1).strip()
        # Chinese fallback pattern (if page ever switches locale)
        if not reset_7d:
            m = re.search(r"([\d\s天小时分分钟hms]+\s*(?:后)?(?:重置|到期))", text)
            if m:
                reset_7d = m.group(1).strip()
        # Claude doesn't show a separate 5h reset time
        reset_5h = None

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

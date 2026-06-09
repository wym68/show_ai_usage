"""MiniMax Token Plan subscription usage provider.

Target URL: https://platform.minimaxi.com/console/usage
"""

import re
import time
from typing import Tuple

from playwright.sync_api import BrowserContext, Page

from poller.providers.base import BaseProvider, UsageData, format_reset_time

MINIMAX_USAGE_URL = "https://platform.minimaxi.com/console/usage"

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45


class MiniMaxProvider(BaseProvider):
    """Usage provider for MiniMax Token Plan subscriptions."""

    @property
    def name(self) -> str:
        return "minimax"

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
                    "Could not parse MiniMax usage data.\n"
                    f"Page title: {page.title()}\n"
                    "Run with `--debug` to dump the page content for analysis."
                )

            return UsageData(
                provider="minimax",
                window_5h_percent=window_5h or 0.0,
                window_7d_percent=window_7d or 0.0,
                reset_5h=format_reset_time(reset_5h, "minimax", self.timezone_id),
                reset_7d=format_reset_time(reset_7d, "minimax", self.timezone_id),
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _navigate_and_wait(self, page: Page) -> None:
        """Navigate to MiniMax usage console and wait for the real page."""
        page.goto(MINIMAX_USAGE_URL, wait_until="domcontentloaded", timeout=45000)
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

        # MiniMax page layout (Chinese):
        #   5h 限额         ← section label
        #   26 分钟后重置    ← reset countdown
        #   总额度 100%     ← total quota (NOT usage)
        #   已用 0%         ← actual USAGE (relative to 总额度)
        #
        #   周限额
        #   4 天 19 小时后重置
        #   总额度 150%
        #   已用 54%        ← 54% of 150%, need to normalize to 100% scale
        #
        # Strategy: extract both (总额度, 已用) for each section,
        # then normalize: normalized% = 已用 / 总额度 * 100

        # 5h usage: extract total quota and used, then normalize
        m = re.search(
            r"5\s*(?:小?\s*时|h)\s*限额.*?总额度\s*(\d+\.?\d*)\s*%.*?已用\s*(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            total_5h = float(m.group(1))
            used_5h = float(m.group(2))
            window_5h = used_5h * 100.0 / total_5h

        # 7d / weekly usage: same approach with normalization
        m = re.search(
            r"周\s*限额.*?总额度\s*(\d+\.?\d*)\s*%.*?已用\s*(\d+\.?\d*)\s*%",
            text,
            re.DOTALL,
        )
        if m:
            total_7d = float(m.group(1))
            used_7d = float(m.group(2))
            window_7d = used_7d * 100.0 / total_7d

        # English patterns (if MiniMax ever shows English UI)
        if window_5h is None:
            m = re.search(
                r"(?:5.?hour|last\s+5\s+hours?)[^%\n]{0,200}?(\d+\.?\d*)\s*%",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                window_5h = float(m.group(1))

        if window_7d is None:
            m = re.search(
                r"(?:7.?day|this\s+week|weekly)[^%\n]{0,200}?(\d+\.?\d*)\s*%",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                window_7d = float(m.group(1))

        # Generic fallback: any two X% values (least preferred)
        if window_5h is None or window_7d is None:
            all_pcts = re.findall(r"(\d+\.?\d*)\s*%", text)
            if len(all_pcts) >= 2:
                if window_5h is None:
                    window_5h = float(all_pcts[0])
                if window_7d is None:
                    window_7d = float(all_pcts[1])
            elif len(all_pcts) >= 1 and window_5h is None:
                window_5h = float(all_pcts[0])

        # Reset times: MiniMax sections show countdowns like
        # "14 分钟后重置" and "4 天 19 小时后重置" (compound duration).
        # Capture from first digit through to "重置" to get full duration.
        all_resets = re.findall(r"(\d[\d\s天小时分分钟hms]*\s*(?:后)?\s*(?:重置|到期))", text)
        if len(all_resets) >= 1:
            reset_5h = all_resets[0].strip()    # first = 5h reset (shorter)
        if len(all_resets) >= 2:
            reset_7d = all_resets[1].strip()    # second = weekly (longer, may be compound)

        # Fallback for non-countdown format
        if not reset_5h and not reset_7d:
            m = re.search(r"(?:重置|到期|刷新|resets?)\s*[:：]?\s*([^\n]+)", text, re.IGNORECASE)
            if m:
                reset_5h = m.group(1).strip()

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

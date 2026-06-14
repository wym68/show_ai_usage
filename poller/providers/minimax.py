"""MiniMax Token Plan subscription usage provider.

Target URL: https://platform.minimaxi.com/console/usage

Supports two fetch paths:

1. **Direct API** (preferred when ``MINIMAX_API_KEY`` is configured):
   ``GET {base_url}/v1/token_plan/remains`` with a Bearer token.
2. **CLI fallback** (when API key is absent and ``mmx`` is on PATH):
   ``mmx quota show --output json`` — same JSON schema, no key needed.

When neither path is available, :meth:`fetch_direct` returns a
:class:`UsageData` whose ``error`` field explains the missing
credential situation. The poller can then choose to fall back to
the browser path via :attr:`Config.direct_fetch_browser_fallback`.
"""

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from playwright.sync_api import BrowserContext, Page

from poller.config import Config
from poller.providers.base import BaseProvider, UsageData

MINIMAX_USAGE_URL = "https://platform.minimaxi.com/console/usage"
MINIMAX_DEFAULT_API_BASE_URL = "https://api.minimax.io"
MINIMAX_API_PATH = "/v1/token_plan/remains"
MINIMAX_CLI_BINARY = "mmx"
MINIMAX_CLI_TIMEOUT = 30
MINIMAX_HTTP_TIMEOUT = 15

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45


# ---------------------------------------------------------------------------
# Payload parser — shared by the API and CLI paths
# ---------------------------------------------------------------------------

_ROW_KEYS = frozenset({
    "model_name", "model",
    "usage_count", "used_count", "current_usage",
    "total_count", "quota_count", "quota",
    "remains_time", "end_time", "reset_in", "remaining_time",
    "remains_percent", "remaining_percent", "remain_percent",
    "weekly",
    "weekly_remains_time", "weekly_end_time",
    "weekly_reset_in", "weekly_remaining_time",
    "weekly_usage_count", "weekly_total_count",
    "weekly_used_count", "weekly_quota_count",
    "weekly_current_usage", "weekly_quota",
    "weekly_remains_percent", "weekly_remaining_percent", "weekly_remain_percent",
})


def _select_model_remains(payload: Any) -> dict | None:
    """Pick the row whose ``model_name`` contains ``minimax`` (case-insensitive).

    Accepts the three shapes documented by the plan:

    * a single row object (the response IS the row),
    * ``{"data": <row or list>}`` wrapper,
    * ``{"model_remains": [...]}`` list (possibly nested under ``data``).

    Returns ``None`` when the payload carries no recognisable row.
    """
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("model_remains"), list):
            rows = payload["model_remains"]
        elif "data" in payload:
            inner = payload["data"]
            if isinstance(inner, list):
                rows = inner
            elif isinstance(inner, dict):
                if isinstance(inner.get("model_remains"), list):
                    rows = inner["model_remains"]
                else:
                    rows = [inner]
            else:
                return None
        elif payload.keys() & _ROW_KEYS:
            rows = [payload]
        else:
            return None
    else:
        return None

    def _name(row: Any) -> str:
        if not isinstance(row, dict):
            return ""
        return str(row.get("model_name") or row.get("model") or "").lower()

    minimax_rows = [r for r in rows if "minimax" in _name(r)]
    if minimax_rows:
        return minimax_rows[0]
    for r in rows:
        if isinstance(r, dict):
            return r
    return None


def _resolve_window(row: dict, prefix: str) -> tuple[dict, str]:
    """Return ``(window_dict, effective_prefix)`` for the given window.

    When a nested ``weekly`` dict is present (for ``prefix="weekly_"``),
    return it with ``effective_prefix=""`` because nested fields use
    base names (``remains_percent``, ``remains_time``, ...).
    Otherwise return ``row`` with the original prefix intact.
    """
    if prefix:
        nested_key = prefix.rstrip("_")
        nested = row.get(nested_key)
        if isinstance(nested, dict):
            return nested, ""
    return row, prefix


def _coerce_percent_from_remains(window: dict, prefix: str) -> float | None:
    """Compute used-percent from a ``remains_percent``-style field."""
    if prefix == "":
        interval_keys = (
            "current_interval_remaining_percent",
            "current_interval_remains_percent",
        )
    else:
        interval_keys = (
            "current_weekly_remaining_percent",
            "current_weekly_remains_percent",
        )
    for key in (
        *interval_keys,
        f"{prefix}remains_percent",
        f"{prefix}remaining_percent",
        f"{prefix}remain_percent",
    ):
        val = window.get(key)
        if val is None:
            continue
        try:
            remains = float(val)
        except (TypeError, ValueError):
            continue
        return max(0.0, min(100.0, 100.0 - remains))
    return None


def _coerce_percent_from_counts(window: dict, prefix: str) -> float | None:
    """Compute used-percent from ``usage_count`` / ``total_count``-style fields."""
    if prefix == "":
        interval_candidates = (
            ("current_interval_usage_count", "current_interval_total_count"),
        )
    else:
        interval_candidates = (
            ("current_weekly_usage_count", "current_weekly_total_count"),
        )
    candidates = (
        *interval_candidates,
        (f"{prefix}usage_count", f"{prefix}total_count"),
        (f"{prefix}used_count", f"{prefix}quota_count"),
        (f"{prefix}current_usage", f"{prefix}quota"),
    )
    for used_key, total_key in candidates:
        used = window.get(used_key)
        total = window.get(total_key)
        if used is None or total is None:
            continue
        try:
            used_f = float(used)
            total_f = float(total)
        except (TypeError, ValueError):
            continue
        if total_f <= 0:
            continue
        return max(0.0, min(100.0, used_f * 100.0 / total_f))
    return None


def _coerce_window_percent(row: dict, prefix: str) -> float | None:
    """Combined percent lookup: remaining first, counts as fallback."""
    window, effective = _resolve_window(row, prefix)
    pct = _coerce_percent_from_remains(window, effective)
    if pct is not None:
        return pct
    return _coerce_percent_from_counts(window, effective)


def _resolve_reset_seconds(row: dict, prefix: str) -> float | None:
    """Pick a reset-in-seconds value from ``remains_time``/``end_time`` fields.

    MiniMax's live ``remains_time``/``weekly_remains_time`` values are returned
    in milliseconds, while our test fixtures and some older payloads use
    seconds. A value larger than one million is unambiguously relative
    milliseconds (no real reset window exceeds ~11.5 days in seconds), so we
    divide by 1000 in that case.
    """
    window, effective = _resolve_window(row, prefix)
    candidates = (
        f"{effective}remains_time",
        f"{effective}end_time",
        f"{effective}reset_in",
        f"{effective}remaining_time",
    )
    for key in candidates:
        val = window.get(key)
        if val is None:
            continue
        try:
            seconds = float(val)
        except (TypeError, ValueError):
            continue
        # Live MiniMax API returns reset windows in milliseconds; treat values
        # that are too large to be seconds as milliseconds.
        if seconds > 1_000_000:
            seconds = seconds / 1000.0
        return seconds
    return None


def _format_seconds_as_reset(seconds: float | int | None) -> str | None:
    """Convert a ``seconds-until-reset`` value to the canonical reset string."""
    if seconds is None:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return "即将重置"
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分")
    if not parts:
        return "即将重置"
    return "".join(parts) + "后重置"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MiniMaxProvider(BaseProvider):
    """Usage provider for MiniMax Token Plan subscriptions."""

    # ``supports_direct_fetch`` is a class-level bool per D2 (Phase 1).
    # ``MiniMaxProvider`` is structurally a ``DirectFetchProvider`` whether or
    # not credentials are configured — the boolean is the runtime capability
    # gate. We default to ``True`` because the direct path is always available
    # (API when key present, CLI fallback otherwise).
    supports_direct_fetch: bool = True

    @property
    def name(self) -> str:
        return "minimax"

    # ------------------------------------------------------------------
    # Direct fetch (preferred path)
    # ------------------------------------------------------------------

    def fetch_direct(self, config: Config) -> UsageData:
        """Fetch via API when a key is configured, otherwise try the CLI.

        Returns a populated :class:`UsageData`. On failure (network,
        auth, parse, missing tool), returns a ``UsageData`` whose
        ``error`` field describes the failure so the poller can
        surface it or fall back to the browser path.
        """
        if config.minimax_api_key:
            return self._fetch_via_api(config)
        if shutil.which(MINIMAX_CLI_BINARY):
            return self._fetch_via_cli()
        return UsageData(
            provider=self.name,
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error=(
                "MiniMax direct fetch unavailable: MINIMAX_API_KEY not set "
                f"and '{MINIMAX_CLI_BINARY}' CLI not found on PATH."
            ),
        )

    def _fetch_via_api(self, config: Config) -> UsageData:
        base = (config.minimax_api_base_url or MINIMAX_DEFAULT_API_BASE_URL).rstrip("/")
        url = f"{base}{MINIMAX_API_PATH}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {config.minimax_api_key}",
                "Accept": "application/json",
                "User-Agent": "show-ai-usage-poller/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=MINIMAX_HTTP_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # Only echo the status code — upstream ``reason`` text may echo
            # the API key back to us (some proxies do this on auth failure).
            return self._error_usage(f"MiniMax API HTTP {exc.code}")
        except urllib.error.URLError as exc:
            return self._error_usage(f"MiniMax API unreachable: {exc.reason}")
        except TimeoutError:
            return self._error_usage(
                f"MiniMax API timed out after {MINIMAX_HTTP_TIMEOUT}s"
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error_usage(f"MiniMax API returned invalid JSON: {exc.msg}")

        base_resp = payload.get("base_resp") if isinstance(payload, dict) else None
        if isinstance(base_resp, dict) and base_resp.get("status_code") != 0:
            code = base_resp.get("status_code")
            msg = base_resp.get("status_msg") or "MiniMax API error"
            return self._error_usage(f"MiniMax API error {code}: {msg}")

        return self._parse_remains_payload(payload)

    def _fetch_via_cli(self) -> UsageData:
        try:
            proc = subprocess.run(
                [MINIMAX_CLI_BINARY, "quota", "show", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=MINIMAX_CLI_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._error_usage(
                f"{MINIMAX_CLI_BINARY} CLI timed out after {MINIMAX_CLI_TIMEOUT}s"
            )
        except FileNotFoundError:
            return self._error_usage(f"{MINIMAX_CLI_BINARY} CLI not found on PATH")

        if proc.returncode != 0:
            # Do NOT echo stderr — it may contain credentials or
            # environment-specific paths. Just report the exit code.
            return self._error_usage(
                f"{MINIMAX_CLI_BINARY} CLI failed with exit code {proc.returncode}"
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return self._error_usage(
                f"{MINIMAX_CLI_BINARY} CLI returned invalid JSON: {exc.msg}"
            )

        return self._parse_remains_payload(payload)

    @staticmethod
    def _error_usage(message: str) -> UsageData:
        return UsageData(
            provider="minimax",
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error=message,
        )

    @staticmethod
    def _parse_remains_payload(payload: Any) -> UsageData:
        row = _select_model_remains(payload)
        if row is None:
            return MiniMaxProvider._error_usage(
                "MiniMax payload did not contain a model_remains row"
            )

        pct_5h = _coerce_window_percent(row, prefix="")
        pct_7d = _coerce_window_percent(row, prefix="weekly_")
        reset_5h = _format_seconds_as_reset(_resolve_reset_seconds(row, prefix=""))
        reset_7d = _format_seconds_as_reset(
            _resolve_reset_seconds(row, prefix="weekly_")
        )

        return UsageData(
            provider="minimax",
            window_5h_percent=pct_5h if pct_5h is not None else 0.0,
            window_7d_percent=pct_7d if pct_7d is not None else 0.0,
            reset_5h=reset_5h,
            reset_7d=reset_7d,
        )

    # ------------------------------------------------------------------
    # Browser path (kept for backwards compatibility / fallback)
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

            # Local import to avoid a top-level cycle with base.py.
            from poller.providers.base import format_reset_time

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
    # Page interaction helpers (browser path)
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
    # Text-based parsing (browser path)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_from_text(
        text: str,
    ) -> tuple[float | None, float | None, str | None, str | None]:
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
    def _parse_from_dom(page: Page) -> tuple[float | None, float | None]:
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

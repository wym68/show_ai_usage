"""Kimi Code subscription usage provider.

Target URL: https://www.kimi.com/code/console

Supports two fetch paths:

1. **Direct API** (preferred when credentials are configured):
   ``GET https://api.kimi.com/coding/v1/usages`` with a Bearer token.
2. **Browser** (fallback / no-credentials path): scrape the console page.

When neither path can run, :meth:`fetch_direct` returns a
:class:`UsageData` whose ``error`` field explains the missing
credential situation. The poller can then choose to fall back to
the browser path via :attr:`Config.direct_fetch_browser_fallback`.

API payload shape (observed):

* ``usage`` — weekly/7-day summary (``used``, ``limit``, ``remaining``,
  ``resetTime``).
* ``limits[]`` — rate-limit rows. Each row has a ``window`` plus a
  ``detail`` object that carries the actual numbers
  (``used``, ``limit``, ``remaining``, ``resetTime``).
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Tuple

from playwright.sync_api import BrowserContext, Page

from poller.config import Config
from poller.providers.base import BaseProvider, UsageData, format_reset_time

KIMI_CONSOLE_URL = "https://www.kimi.com/code/console"
KIMI_USAGES_URL = "https://api.kimi.com/coding/v1/usages"
KIMI_HTTP_TIMEOUT = 15

KIMI_TOKEN_RELATIVE_PATH = Path("credentials") / "kimi-code.json"
KIMI_TOKEN_KEYS = ("access_token", "accessToken")

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45

_KIMI_RESET_KEYS = (
    "resetAt",
    "reset_at",
    "reset_time",
    "resetTime",
    "resetIn",
    "reset_in",
    "ttl",
)


class KimiProvider(BaseProvider):
    """Usage provider for Kimi Code subscriptions."""

    # ``supports_direct_fetch`` is a class-level bool per D2 (Phase 1).
    # ``KimiProvider`` is structurally a ``DirectFetchProvider`` whether or
    # not credentials are configured — the boolean is the runtime capability
    # gate. We default to ``True`` because the direct path is always
    # attempted first; credential absence surfaces as ``UsageData.error``.
    supports_direct_fetch: bool = True

    @property
    def name(self) -> str:
        return "kimi"

    # ------------------------------------------------------------------
    # Direct fetch (preferred path)
    # ------------------------------------------------------------------

    def fetch_direct(self, config: Config) -> UsageData:
        """Fetch Kimi usage via the ``/coding/v1/usages`` endpoint.

        Returns a populated :class:`UsageData`. On failure (missing
        token, network error, auth failure, parse failure), returns a
        ``UsageData`` whose ``error`` field describes the failure so
        the poller can surface it or fall back to the browser path.
        """
        token = self._resolve_token(config)
        if not token:
            return self._error_usage(
                "Kimi direct fetch unavailable: KIMI_CODE_ACCESS_TOKEN not set "
                "and no credentials/kimi-code.json found under KIMI_CODE_HOME "
                "or ~/.kimi-code."
            )

        req = urllib.request.Request(
            KIMI_USAGES_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "show-ai-usage-poller/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=KIMI_HTTP_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            return self._error_usage(f"Kimi API HTTP {exc.code}")
        except urllib.error.URLError as exc:
            return self._error_usage(f"Kimi API unreachable: {exc.reason}")
        except TimeoutError:
            return self._error_usage(
                f"Kimi API timed out after {KIMI_HTTP_TIMEOUT}s"
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error_usage(f"Kimi API returned invalid JSON: {exc.msg}")

        return self._parse_usages_payload(payload, timezone_id=self.timezone_id)

    @staticmethod
    def _resolve_token(config: Config) -> str | None:
        """Resolve a Kimi access token from config / env / credential files.

        Order (per plan):
          1. ``config.kimi_code_access_token`` (env-first via Config).
          2. ``$KIMI_CODE_HOME/credentials/kimi-code.json``.
          3. ``~/.kimi-code/credentials/kimi-code.json``.

        Returns the token string or ``None`` if none of the three sources
        yielded a usable value. The token value is never logged.
        """
        if config.kimi_code_access_token:
            return config.kimi_code_access_token

        home = os.environ.get("KIMI_CODE_HOME")
        if home:
            token = _read_token_from_file(Path(home) / KIMI_TOKEN_RELATIVE_PATH)
            if token:
                return token

        return _read_token_from_file(Path.home() / ".kimi-code" / KIMI_TOKEN_RELATIVE_PATH)

    @staticmethod
    def _parse_usages_payload(payload: Any, *, timezone_id: str = "UTC") -> UsageData:
        """Parse a Kimi ``/usages`` response into :class:`UsageData`.

        Implements the plan rules: 5h row = first ``limits[]`` item
        whose ``window.duration==300`` and ``timeUnit`` contains
        ``MINUTE`` (or label matches ``5h`` / ``5 hour``). Weekly row
        is the top-level ``usage`` summary, or first ``limits[]``
        item with ``duration==7``+``DAY`` or ``duration==10080``+``MINUTE``
        (or label matches ``weekly`` / ``week`` / ``7d`` / ``7天``).

        Actual payloads nest the numbers inside a ``detail`` object under
        each ``limits[]`` row; the top-level ``usage`` object is used
        directly for the weekly summary.
        """
        if not isinstance(payload, dict):
            return KimiProvider._error_usage(
                "Kimi payload must be a JSON object"
            )

        limits = payload.get("limits") or []
        if not isinstance(limits, list):
            return KimiProvider._error_usage(
                "Kimi payload 'limits' must be an array"
            )

        row_5h = _select_kimi_limit_row(limits, scope="5h")
        if isinstance(payload.get("usage"), dict):
            row_7d: dict[str, Any] | None = payload["usage"]
        else:
            row_7d = _select_kimi_limit_row(limits, scope="weekly")

        pct_5h, err_5h = _kimi_percent_from_row(row_5h)
        pct_7d, err_7d = _kimi_percent_from_row(row_7d)
        reset_5h = _kimi_reset_from_row(row_5h, timezone_id=timezone_id)
        reset_7d = _kimi_reset_from_row(row_7d, timezone_id=timezone_id)

        if row_5h is None and row_7d is None:
            return KimiProvider._error_usage(
                "Kimi payload did not contain any recognised 5h or weekly usage rows"
            )

        first_err = err_5h or err_7d
        if first_err:
            return KimiProvider._error_usage(first_err)

        return UsageData(
            provider="kimi",
            window_5h_percent=pct_5h if pct_5h is not None else 0.0,
            window_7d_percent=pct_7d if pct_7d is not None else 0.0,
            reset_5h=format_reset_time(reset_5h, "kimi", timezone_id),
            reset_7d=format_reset_time(reset_7d, "kimi", timezone_id),
        )

    @staticmethod
    def _error_usage(message: str) -> UsageData:
        return UsageData(
            provider="kimi",
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error=message,
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


# ---------------------------------------------------------------------------
# Direct-fetch helpers (Kimi ``/usages`` response parsing)
# ---------------------------------------------------------------------------


def _read_token_from_file(path: Path) -> str | None:
    """Read ``access_token`` or ``accessToken`` from a Kimi credentials file.

    Returns the token string, or ``None`` if the file is missing,
    unreadable, malformed, or the relevant key is absent/empty. Other
    keys (``refresh_token`` etc.) are ignored — phase 1 does not
    implement OAuth refresh.
    """
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    for key in KIMI_TOKEN_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _get_limit_label(limit: dict[str, Any]) -> str:
    """Return a flattened label string for a Kimi ``limits[]`` row."""
    parts: list[str] = []
    for key in ("name", "title", "scope", "label", "type"):
        value = limit.get(key)
        if isinstance(value, str):
            parts.append(value)
    nested = limit.get("window")
    if isinstance(nested, dict):
        for key in ("name", "title", "scope", "label", "type"):
            value = nested.get(key)
            if isinstance(value, str):
                parts.append(value)
    return " ".join(parts)


def _select_kimi_limit_row(limits: list[Any], *, scope: str) -> dict[str, Any] | None:
    """Select the 5h or weekly row from a Kimi ``limits[]`` list.

    ``scope="5h"`` — match ``window.duration==300`` with ``timeUnit``
    containing ``MINUTE``, or a label containing ``5h`` / ``5 hour``.
    ``scope="weekly"`` — match ``window.duration==7``+``DAY`` or
    ``window.duration==10080``+``MINUTE``, or a label containing
    ``weekly`` / ``week`` / ``7d`` / ``7天``.

    Returns the first matching row, or ``None`` if no row matches.
    Non-dict entries are skipped silently.
    """
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        window_value = entry.get("window")
        window = window_value if isinstance(window_value, dict) else {}
        try:
            duration_value = window.get("duration")
            if duration_value is None:
                raise TypeError
            duration = int(duration_value)
        except (TypeError, ValueError):
            duration = None
        time_unit = str(window.get("timeUnit") or "").upper()
        label = _get_limit_label(entry)

        if scope == "5h":
            if duration == 300 and "MINUTE" in time_unit:
                return entry
            if re.search(r"5\s*h(?:our)?", label, re.IGNORECASE):
                return entry
        elif scope == "weekly":
            if duration == 7 and "DAY" in time_unit:
                return entry
            if duration == 10080 and "MINUTE" in time_unit:
                return entry
            if re.search(r"(weekly|week|7\s*d|7天)", label, re.IGNORECASE):
                return entry
        else:
            raise ValueError(f"unknown scope: {scope!r}")
    return None


def _kimi_percent_from_row(row: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """Compute used-percent for a Kimi row, with plan-style fallbacks.

    Returns ``(percent, error)`` where exactly one is non-None. ``error``
    is set when ``limit <= 0`` (per plan rule); ``percent`` is ``None``
    when the row is absent or carries neither ``used`` nor
    ``remaining``+``limit``.

    Actual payloads put the numbers inside a ``detail`` sub-object. We
    read from ``detail`` first, then fall back to the row's top-level
    fields for backward compatibility.
    """
    if row is None:
        return None, None

    data = row.get("detail")
    if not isinstance(data, dict):
        data = row

    limit = data.get("limit")
    try:
        limit_f = float(limit) if limit is not None else None
    except (TypeError, ValueError):
        limit_f = None
    if limit_f is not None and limit_f <= 0:
        return None, f"Kimi payload limit must be > 0 (got {limit_f})"

    used = data.get("used")
    used_f: float | None
    if used is None:
        remaining = data.get("remaining")
        try:
            used_f = (
                limit_f - float(remaining)
                if limit_f is not None and remaining is not None
                else None
            )
        except (TypeError, ValueError):
            used_f = None
    else:
        try:
            used_f = float(used)
        except (TypeError, ValueError):
            used_f = None

    if used_f is None or limit_f is None or limit_f <= 0:
        return None, None
    pct = used_f * 100.0 / limit_f
    return max(0.0, min(100.0, pct)), None


def _kimi_reset_from_row(row: dict[str, Any] | None, *, timezone_id: str) -> str | None:
    """Convert any recognised Kimi reset field to a ``format_reset_time``-ready string.

    Inspects ``resetAt``, ``reset_at``, ``reset_time``, ``resetTime``,
    ``resetIn``, ``reset_in``, ``ttl`` (in that order). ISO timestamps
    are returned verbatim so :func:`format_reset_time` parses them as
    absolute times; integer/seconds values are formatted as English
    duration so the same function parses them as relative durations.

    Real payloads put the reset time inside ``row['detail']['resetTime']``;
    we look there first and then fall back to the row's top-level keys.
    Returns ``None`` if no recognised reset field is present.
    """
    if row is None:
        return None

    candidates = [row]
    detail = row.get("detail")
    if isinstance(detail, dict):
        candidates.insert(0, detail)

    for data in candidates:
        for key in _KIMI_RESET_KEYS:
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                seconds = int(value)
                if seconds <= 0:
                    continue
                return _seconds_to_english_duration(seconds)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _seconds_to_english_duration(seconds: int) -> str:
    """Format ``seconds`` as ``X hr Y min`` so ``format_reset_time`` recognises it."""
    if seconds >= 86400:
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        if days >= 1:
            return f"{days} day {hours} hr {minutes} min"
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if hours >= 1 and minutes >= 1:
        return f"{hours} hr {minutes} min"
    if hours >= 1:
        return f"{hours} hr"
    return f"{minutes} min"

"""Claude Code subscription usage provider.

Target URL: https://claude.ai/new#settings/usage
"""

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

from playwright.sync_api import BrowserContext, Page

from poller.config import Config
from poller.providers.base import BaseProvider, UsageData, format_reset_time

CLAUDE_USAGE_URL = "https://claude.ai/new#settings/usage"
CLAUDE_HOME_URL = "https://claude.ai"
CLAUDE_USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_HTTP_TIMEOUT = 15

# Re-evaluated at call-time inside ``_resolve_token`` so tests can
# monkeypatch ``Path.home()`` to redirect the credentials file path.
CLAUDE_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"

CLAUDE_TOKEN_KEYS = ("accessToken", "access_token")

_CHALLENGE_TITLES = {"请稍候…", "Just a moment...", "Please wait...", "请稍候", "Just a moment"}
_CHALLENGE_TIMEOUT = 45


def _format_iso_reset_time(
    value: str | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """Convert an ISO 8601 ``resets_at`` string to the project's reset format.

    Accepts timezone-aware ISO 8601 strings (e.g. ``"2026-06-13T10:00:00+00:00"``
    or ``"2026-06-13T10:00:00Z"``). Naive datetimes are interpreted as UTC.

    Returns a Chinese relative string (``"X小时后重置"``,
    ``"X天Y小时后重置"``, or ``"即将重置"``) consistent with
    :func:`poller.providers.base.format_reset_time`.

    Returns ``None`` for ``None``, empty, or malformed input — never raises.
    """
    if not value:
        return None

    try:
        # ``fromisoformat`` in 3.11+ accepts the ``Z`` suffix directly.
        target = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)

    reference = now if now is not None else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    else:
        reference = reference.astimezone(timezone.utc)

    delta = target - reference
    if delta.total_seconds() <= 0:
        return "即将重置"

    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600

    if days == 0 and hours == 0:
        return "即将重置"

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")

    return "".join(parts) + "后重置"


def _parse_usage_payload(payload: object, *, timezone_id: str = "UTC") -> UsageData:
    """Parse a Claude direct-API usage payload into :class:`UsageData`.

    Reads ``five_hour.utilization`` and ``seven_day.utilization``,
    clamping each to ``[0.0, 100.0]``. ``five_hour.resets_at`` and
    ``seven_day.resets_at`` are routed through
    :func:`_format_iso_reset_time`. Model-specific weekly buckets
    (``seven_day_sonnet``, ``seven_day_opus``, ``seven_day_oauth_apps``,
    ``seven_day_cowork``) and ``extra_usage`` are ignored by design.

    A missing ``five_hour`` or ``seven_day`` window is treated as
    ``percent=0.0`` / ``reset=None`` rather than an error. A payload
    carrying neither window surfaces a ``UsageData.error``.
    """
    if not isinstance(payload, dict):
        return UsageData(
            provider="claude",
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error="Claude payload must be a JSON object",
        )

    five_hour = payload.get("five_hour")
    seven_day = payload.get("seven_day")
    has_5h = isinstance(five_hour, dict)
    has_7d = isinstance(seven_day, dict)

    if not has_5h and not has_7d:
        return UsageData(
            provider="claude",
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error="Claude payload did not contain any recognised usage rows",
        )

    def _clamp_utilization(value: Any) -> float:
        try:
            numeric = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, numeric))

    pct_5h = _clamp_utilization(five_hour.get("utilization")) if has_5h else 0.0
    pct_7d = _clamp_utilization(seven_day.get("utilization")) if has_7d else 0.0
    reset_5h = _format_iso_reset_time(five_hour.get("resets_at")) if has_5h else None
    reset_7d = _format_iso_reset_time(seven_day.get("resets_at")) if has_7d else None

    return UsageData(
        provider="claude",
        window_5h_percent=pct_5h,
        window_7d_percent=pct_7d,
        reset_5h=reset_5h,
        reset_7d=reset_7d,
    )


def _fetch_usage_payload(token: str) -> object:
    """Call the Claude OAuth usage endpoint and return the parsed JSON payload.

    Issues ``GET {CLAUDE_USAGE_API_URL}`` with the documented headers and
    ``CLAUDE_HTTP_TIMEOUT``. Returns the parsed JSON object on a 2xx
    response.

    Any ``HTTPError`` / ``URLError`` / ``TimeoutError`` /
    ``JSONDecodeError`` is re-raised as :class:`RuntimeError` with a
    **safe** message that intentionally omits both the OAuth token and
    the upstream response body. Callers should surface that message
    directly to the user via :class:`UsageData.error`.
    """
    req = urllib.request.Request(
        CLAUDE_USAGE_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": "show-ai-usage-poller/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=CLAUDE_HTTP_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Claude API HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Claude API unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Claude API timed out after {CLAUDE_HTTP_TIMEOUT}s"
        ) from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claude API returned invalid JSON") from exc


class ClaudeProvider(BaseProvider):
    """Usage provider for Claude Code subscriptions."""

    supports_direct_fetch: bool = True

    @property
    def name(self) -> str:
        return "claude"

    # ------------------------------------------------------------------
    # Direct-fetch helpers (credential resolution)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_token(config: Config) -> str | None:
        """Resolve the Claude OAuth access token from config / credentials file.

        Order (per plan):
          1. ``config.claude_code_access_token`` (env-first via Config).
          2. ``~/.claude/.credentials.json`` under
             ``claudeAiOauth.accessToken``.
          3. ``~/.claude/.credentials.json`` under
             ``claudeAiOauth.access_token``.
          4. ``~/.claude/.credentials.json`` top-level ``accessToken``.
          5. ``~/.claude/.credentials.json`` top-level ``access_token``.

        Returns the token string, or ``None`` if none of the sources
        yielded a usable value. The token value is never logged.
        """
        if config.claude_code_access_token:
            return config.claude_code_access_token
        return _read_token_from_file(Path.home() / ".claude" / ".credentials.json")

    @staticmethod
    def _error_usage(message: str) -> UsageData:
        """Build a populated ``UsageData`` carrying a safe error message.

        The ``message`` must NOT contain the OAuth token or any portion
        of the upstream response body — those are sanitised by the
        caller before being passed in.
        """
        return UsageData(
            provider="claude",
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            error=message,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_direct(self, config: Config) -> UsageData:
        """Fetch Claude usage via the ``/api/oauth/usage`` endpoint.

        Returns a populated :class:`UsageData`. On failure (missing
        token, network error, auth failure, parse failure), returns a
        ``UsageData`` whose ``error`` field describes the failure so
        the poller can surface it or fall back to the browser path.
        The OAuth token and the upstream response body are never
        included in error messages.
        """
        token = self._resolve_token(config)
        if not token:
            return self._error_usage(
                "Claude direct fetch unavailable: CLAUDE_CODE_ACCESS_TOKEN not set "
                "and no ~/.claude/.credentials.json found"
            )

        try:
            payload = _fetch_usage_payload(token)
        except RuntimeError as exc:
            return self._error_usage(str(exc))

        return _parse_usage_payload(payload, timezone_id=self.timezone_id)

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
                reset_5h=format_reset_time(reset_5h, "claude", self.timezone_id),
                reset_7d=format_reset_time(reset_7d, "claude", self.timezone_id),
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

        m = re.search(
            r"Resets in\s+([\d\s]+(?:hr|min)(?:\s+[\d\s]+(?:hr|min))?)",
            text, re.IGNORECASE,
        )
        if m:
            reset_5h = m.group(1).strip()

        if not reset_5h:
            m = re.search(r"(Starts when a message is sent)", text, re.IGNORECASE)
            if m:
                reset_5h = m.group(1).strip()

        m = re.search(r"Resets\s+([A-Za-z]+\s+\d+:\d+\s*(?:AM|PM))", text, re.IGNORECASE)
        if m:
            reset_7d = m.group(1).strip()

        if not reset_7d:
            m = re.search(r"(Starts when a message is sent)", text, re.IGNORECASE)
            if m:
                reset_7d = m.group(1).strip()

        # Chinese fallback pattern (if page ever switches locale)
        if not reset_7d:
            m = re.search(r"([\d\s天小时分分钟hms]+\s*(?:后)?(?:重置|到期))", text)
            if m:
                reset_7d = m.group(1).strip()

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
# Direct-fetch helpers (token file parsing)
# ---------------------------------------------------------------------------


def _read_token_from_file(path: Path) -> str | None:
    """Read ``accessToken`` / ``access_token`` from a Claude credentials file.

    Accepts both the nested ``claudeAiOauth`` shape (the canonical Claude
    Code CLI format)::

        {"claudeAiOauth": {"accessToken": "..."}}

    and the top-level shape::

        {"accessToken": "..."}

    Returns the first non-empty token string found (with surrounding
    whitespace stripped), or ``None`` if the file is missing,
    unreadable, malformed, or contains no recognised token. The
    ``refreshToken`` field is intentionally ignored — phase 1 does not
    implement OAuth refresh. The token value is never logged.
    """
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None

    # Nested ``claudeAiOauth`` shape is consulted first because it is
    # the canonical Claude Code CLI format.
    nested = data.get("claudeAiOauth")
    if isinstance(nested, dict):
        for key in CLAUDE_TOKEN_KEYS:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for key in CLAUDE_TOKEN_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None

"""Tests for the Kimi direct-fetch path (Wave 2 — Plan Task 2).

Covers:
* ``KimiProvider`` satisfies ``DirectFetchProvider`` and exposes
  the boolean capability flag.
* Credential resolution order: ``KIMI_CODE_ACCESS_TOKEN`` env /
  TOML → ``$KIMI_CODE_HOME/credentials/kimi-code.json`` →
  ``~/.kimi-code/credentials/kimi-code.json``.
* Token JSON keys accepted: ``access_token`` and ``accessToken``.
* HTTP layer is called with ``Authorization: Bearer <token>`` and
  the documented endpoint URL.
* Parser maps ``limits[].window.duration=300``+``timeUnit=MINUTE``
  to ``window_5h_percent``.
* Parser maps the top-level ``usage`` summary to
  ``window_7d_percent``; fixtures without ``usage`` map a
  7-day / 10080-minute ``limits[]`` row instead.
* Percent rule: ``used / limit * 100``; ``used = limit - remaining``
  when ``used`` is missing; ``limit <= 0`` → ``UsageData.error``.
* Reset fields are read from ``resetAt`` / ``reset_at`` / ``ttl`` /
  ``resetIn`` etc. and converted to the canonical reset string.
* Missing token, HTTP errors, and invalid JSON surface as
  ``UsageData.error`` (no exceptions leak out of ``fetch_direct``).
* The token value never appears in error messages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from poller.config import Config
from poller.providers.base import UsageData
from poller.providers.direct import DirectFetchProvider
from poller.providers.kimi import (
    KIMI_USAGES_URL,
    KimiProvider,
    _kimi_percent_from_row,
    _kimi_reset_from_row,
    _read_token_from_file,
    _select_kimi_limit_row,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(body: dict[str, Any]) -> MagicMock:
    """Build a mock that mimics ``urllib.request.urlopen()``'s return value.

    ``urlopen`` returns a response object that is itself a context
    manager: ``with urlopen(req) as resp: ...`` enters the response.
    ``__enter__`` returns ``self`` and ``read()`` yields the body.
    """
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = json.dumps(body).encode("utf-8")
    return resp


def _write_credentials(home: Path, body: dict[str, Any] | None) -> Path:
    """Drop a credentials/kimi-code.json file under ``home``."""
    creds = home / "credentials"
    creds.mkdir(parents=True, exist_ok=True)
    target = creds / "kimi-code.json"
    target.write_text(json.dumps(body) if body is not None else "")
    return target


def _limit_5h(*, used: float = 25, limit: float = 100, resetIn: int = 3600) -> dict[str, Any]:
    return {
        "window": {"duration": 300, "timeUnit": "MINUTE"},
        "used": used,
        "limit": limit,
        "resetIn": resetIn,
    }


def _limit_weekly_minutes(
    *, used: float = 450, limit: float = 1500, resetAt: str = "2026-06-15T00:00:00Z"
) -> dict[str, Any]:
    return {
        "window": {"duration": 10080, "timeUnit": "MINUTE"},
        "used": used,
        "limit": limit,
        "resetAt": resetAt,
    }


def _limit_weekly_days(
    *, used: float = 450, limit: float = 1500, reset_time: str = "2026-06-15T00:00:00Z"
) -> dict[str, Any]:
    return {
        "window": {"duration": 7, "timeUnit": "DAY"},
        "used": used,
        "limit": limit,
        "reset_time": reset_time,
    }


# ---------------------------------------------------------------------------
# Protocol / capability
# ---------------------------------------------------------------------------


def test_kimi_provider_satisfies_direct_protocol() -> None:
    """KimiProvider must satisfy DirectFetchProvider structurally."""
    provider = KimiProvider()
    assert isinstance(provider, DirectFetchProvider)
    assert provider.supports_direct_fetch is True
    assert provider.name == "kimi"


def test_kimi_fetch_direct_signature() -> None:
    """The direct path must take a Config and return a UsageData."""
    import inspect

    sig = inspect.signature(KimiProvider.fetch_direct)
    params = list(sig.parameters)
    assert params[0] == "self"
    assert params[1] == "config"
    assert sig.return_annotation is UsageData


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def test_resolve_token_from_config_field() -> None:
    """If config already has the token (env-first), return it immediately."""
    cfg = Config(kimi_code_access_token="explicit-token-123")
    token = KimiProvider._resolve_token(cfg)
    assert token == "explicit-token-123"


def test_resolve_token_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Env var ``KIMI_CODE_ACCESS_TOKEN`` populates the config field."""
    monkeypatch.setenv("KIMI_CODE_ACCESS_TOKEN", "env-token-xyz")
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    cfg = Config()
    assert KimiProvider._resolve_token(cfg) == "env-token-xyz"


def test_resolve_token_from_kimi_code_home_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``$KIMI_CODE_HOME/credentials/kimi-code.json`` is read when env is empty."""
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
    _write_credentials(tmp_path, {"access_token": "file-token-home"})
    cfg = Config()  # empty kimi_code_access_token
    assert KimiProvider._resolve_token(cfg) == "file-token-home"


def test_resolve_token_accepts_accessToken_camel_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The credential file accepts ``accessToken`` (camelCase) as well."""
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
    _write_credentials(tmp_path, {"accessToken": "camel-token"})
    cfg = Config()
    assert KimiProvider._resolve_token(cfg) == "camel-token"


def test_resolve_token_prefers_env_over_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the env var is set, the credential file is not consulted."""
    monkeypatch.setenv("KIMI_CODE_ACCESS_TOKEN", "env-wins")
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
    _write_credentials(tmp_path, {"access_token": "file-token-should-not-be-used"})
    cfg = Config()
    assert KimiProvider._resolve_token(cfg) == "env-wins"


def test_resolve_token_falls_back_to_home_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``~/.kimi-code/credentials/kimi-code.json`` is the last resort."""
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_credentials(Path(tmp_path / ".kimi-code"), {"access_token": "home-token"})
    cfg = Config()
    assert KimiProvider._resolve_token(cfg) == "home-token"


def test_resolve_token_returns_none_when_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """All three sources absent → ``None``."""
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = Config()
    assert KimiProvider._resolve_token(cfg) is None


def test_read_token_from_file_ignores_refresh_token(tmp_path: Path) -> None:
    """Phase 1 ignores ``refresh_token``; only ``access_token`` / ``accessToken``."""
    target = _write_credentials(
        tmp_path, {"refresh_token": "refresh-only", "access_token": ""}
    )
    assert _read_token_from_file(target) is None


def test_read_token_from_file_missing_file(tmp_path: Path) -> None:
    """A missing file is a soft error → ``None``."""
    assert _read_token_from_file(tmp_path / "nope.json") is None


def test_read_token_from_file_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON → ``None`` (no exception leaks)."""
    target = tmp_path / "bad.json"
    target.write_text("{this is not json")
    assert _read_token_from_file(target) is None


# ---------------------------------------------------------------------------
# fetch_direct: HTTP layer
# ---------------------------------------------------------------------------


def test_fetch_direct_calls_usages_endpoint_with_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_direct hits /usages with Authorization: Bearer <token>."""
    cfg = Config(kimi_code_access_token="abc-token")
    body = {
        "usage": {"used": 1, "limit": 10, "reset_time": "2026-06-15T00:00:00Z"},
        "limits": [_limit_5h()],
    }
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["timeout"] = timeout
        return _ok_response(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = KimiProvider().fetch_direct(cfg)
    assert result.error is None
    assert captured["url"] == KIMI_USAGES_URL
    assert captured["headers"]["Authorization"] == "Bearer abc-token"
    assert captured["timeout"] == 15


def test_fetch_direct_handles_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 401/403 etc. → UsageData.error (no exception)."""
    cfg = Config(kimi_code_access_token="bad-token")

    def fake_urlopen(req, timeout):
        err = urllib_error(401, "Unauthorized")
        raise err

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = KimiProvider().fetch_direct(cfg)
    assert result.error is not None
    assert "401" in result.error
    assert "Unauthorized" in result.error
    assert "bad-token" not in result.error


def test_fetch_direct_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout → UsageData.error mentioning the timeout."""
    cfg = Config(kimi_code_access_token="t")

    def fake_urlopen(req, timeout):
        raise TimeoutError("simulated")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = KimiProvider().fetch_direct(cfg)
    assert result.error is not None
    assert "timed out" in result.error.lower()


def test_fetch_direct_handles_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-JSON body → UsageData.error (no exception)."""
    cfg = Config(kimi_code_access_token="t")

    def fake_urlopen(req, timeout):
        resp = MagicMock()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = b"<html>not json</html>"
        return resp

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = KimiProvider().fetch_direct(cfg)
    assert result.error is not None
    assert "invalid JSON" in result.error


def test_fetch_direct_missing_token_does_not_hit_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If no token resolves, no HTTP call is made."""
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))

    called = {"flag": False}

    def fake_urlopen(req, timeout):
        called["flag"] = True
        return _ok_response({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = KimiProvider().fetch_direct(Config())
    assert called["flag"] is False
    assert result.error is not None
    assert "KIMI_CODE_ACCESS_TOKEN" in result.error
    # Token value must never appear in error message.
    assert "token" not in result.error.lower().replace("kimi_code_access_token", "")


def test_fetch_direct_error_messages_never_contain_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token value must never leak into error messages."""
    cfg = Config(kimi_code_access_token="super-secret-987654321")

    def fake_urlopen(req, timeout):
        raise urllib_error(500, "Server Error")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = KimiProvider().fetch_direct(cfg)
    assert "super-secret-987654321" not in (result.error or "")
    assert "987654321" not in (result.error or "")


# ---------------------------------------------------------------------------
# Parser: 5h row selection
# ---------------------------------------------------------------------------


def test_select_5h_row_by_duration_and_timeunit() -> None:
    """``window.duration==300`` + ``timeUnit`` contains MINUTE matches 5h."""
    expected = _limit_5h()
    row = _select_kimi_limit_row([expected], scope="5h")
    assert row == expected


def test_select_5h_row_by_label() -> None:
    """Label match ``5h`` / ``5 hour`` is an alternative matcher."""
    labelled = {
        "window": {"duration": 99999, "timeUnit": "UNKNOWN"},
        "name": "5 hour limit",
        "used": 1,
        "limit": 10,
    }
    row = _select_kimi_limit_row([labelled], scope="5h")
    assert row is labelled


def test_select_5h_row_skips_non_matching() -> None:
    """Non-matching rows are skipped; only the first match is returned."""
    daily = {"window": {"duration": 1, "timeUnit": "DAY"}, "used": 1, "limit": 10}
    five_hour = _limit_5h()
    row = _select_kimi_limit_row([daily, five_hour], scope="5h")
    assert row is five_hour


def test_select_5h_row_returns_none_when_absent() -> None:
    """If no row matches, ``None`` is returned."""
    assert _select_kimi_limit_row([_limit_weekly_minutes()], scope="5h") is None
    assert _select_kimi_limit_row([], scope="5h") is None


def test_select_5h_row_skips_non_dict_entries() -> None:
    """Non-dict entries are skipped, not raised on."""
    expected = _limit_5h()
    row = _select_kimi_limit_row(
        ["not a dict", None, expected],
        scope="5h",
    )
    assert row == expected


# ---------------------------------------------------------------------------
# Parser: weekly row selection
# ---------------------------------------------------------------------------


def test_select_weekly_row_from_usage_summary() -> None:
    """Top-level ``usage`` is preferred over matching limits[] entries."""
    payload = {"usage": {"used": 7, "limit": 100}, "limits": [_limit_weekly_minutes()]}
    provider = KimiProvider()
    result = provider._parse_usages_payload(payload)
    assert result.window_7d_percent == pytest.approx(7.0)


def test_select_weekly_row_10080_minutes() -> None:
    """``duration==10080`` + ``timeUnit`` MINUTE maps to weekly when no usage."""
    payload = {"limits": [_limit_5h(), _limit_weekly_minutes()]}
    provider = KimiProvider()
    result = provider._parse_usages_payload(payload)
    assert result.window_7d_percent == pytest.approx(30.0)


def test_select_weekly_row_7_days() -> None:
    """``duration==7`` + ``timeUnit`` DAY is an alternative weekly match."""
    payload = {"limits": [_limit_5h(), _limit_weekly_days()]}
    provider = KimiProvider()
    result = provider._parse_usages_payload(payload)
    assert result.window_7d_percent == pytest.approx(30.0)


def test_select_weekly_row_by_label_7d() -> None:
    """A label ``7d`` is a fallback matcher for the weekly row."""
    labelled = {
        "window": {"duration": 99999, "timeUnit": "UNKNOWN"},
        "scope": "7d limit",
        "used": 50,
        "limit": 100,
    }
    payload = {"limits": [_limit_5h(), labelled]}
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.window_7d_percent == pytest.approx(50.0)


def test_select_weekly_row_by_label_chinese_7天() -> None:
    """The Chinese label ``7天`` matches the weekly row."""
    labelled = {
        "window": {"duration": 99999, "timeUnit": "UNKNOWN"},
        "title": "7天 用量",
        "used": 20,
        "limit": 100,
    }
    payload = {"limits": [_limit_5h(), labelled]}
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.window_7d_percent == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Parser: percent computation
# ---------------------------------------------------------------------------


def test_percent_used_over_limit() -> None:
    """``used / limit * 100`` is the canonical percent rule."""
    pct, err = _kimi_percent_from_row({"used": 25, "limit": 100})
    assert pct == pytest.approx(25.0)
    assert err is None


def test_percent_remaining_minus_limit() -> None:
    """If ``used`` is missing, ``used = limit - remaining``."""
    pct, err = _kimi_percent_from_row({"limit": 100, "remaining": 75})
    assert pct == pytest.approx(25.0)
    assert err is None


def test_percent_zero_limit_returns_error() -> None:
    """``limit <= 0`` is a parse error per plan rule."""
    pct, err = _kimi_percent_from_row({"used": 0, "limit": 0})
    assert pct is None
    assert err is not None
    assert "limit must be > 0" in err


def test_percent_negative_limit_returns_error() -> None:
    """``limit < 0`` is also a parse error."""
    pct, err = _kimi_percent_from_row({"used": 0, "limit": -5})
    assert pct is None
    assert err is not None


def test_percent_none_row_returns_none_none() -> None:
    """A missing row yields ``(None, None)`` — caller treats as no-data."""
    assert _kimi_percent_from_row(None) == (None, None)


def test_percent_no_data_returns_none_none() -> None:
    """A row without ``used`` or ``limit`` cannot produce a percent."""
    pct, err = _kimi_percent_from_row({})
    assert pct is None
    assert err is None


def test_percent_clamps_to_100() -> None:
    """``used > limit`` (shouldn't happen, but be safe) is clamped to 100%."""
    pct, err = _kimi_percent_from_row({"used": 150, "limit": 100})
    assert pct == 100.0
    assert err is None


# ---------------------------------------------------------------------------
# Parser: reset fields
# ---------------------------------------------------------------------------


def test_reset_iso_timestamp_passthrough() -> None:
    """ISO timestamp strings are returned verbatim."""
    out = _kimi_reset_from_row(
        {"resetAt": "2026-06-15T00:00:00Z"},
        timezone_id="UTC",
    )
    assert out == "2026-06-15T00:00:00Z"


def test_reset_seconds_become_english_duration() -> None:
    """``resetIn`` seconds are formatted as English duration."""
    out = _kimi_reset_from_row(
        {"resetIn": 3600 + 1800},
        timezone_id="UTC",
    )
    assert out == "1 hr 30 min"


def test_reset_seconds_days() -> None:
    """Large seconds values produce a day-bearing English duration."""
    out = _kimi_reset_from_row({"ttl": 3 * 86400 + 2 * 3600 + 30 * 60}, timezone_id="UTC")
    assert out == "3 day 2 hr 30 min"


def test_reset_zero_or_negative_seconds_skipped() -> None:
    """Non-positive ``resetIn`` is treated as absent."""
    out = _kimi_reset_from_row({"resetIn": 0}, timezone_id="UTC")
    assert out is None
    out = _kimi_reset_from_row({"resetIn": -10}, timezone_id="UTC")
    assert out is None


def test_reset_none_row_returns_none() -> None:
    """No row → no reset string."""
    assert _kimi_reset_from_row(None, timezone_id="UTC") is None


def test_reset_no_recognised_key_returns_none() -> None:
    """A row without any reset field yields ``None``."""
    assert _kimi_reset_from_row({"used": 1, "limit": 10}, timezone_id="UTC") is None


def test_reset_uses_first_matching_key_in_order() -> None:
    """The first recognised key wins (plan-defined order)."""
    out = _kimi_reset_from_row(
        {
            "resetIn": 7200,  # 2 hr — ignored (later in plan order)
            "resetAt": "2026-06-15T00:00:00Z",  # wins (ISO listed first)
        },
        timezone_id="UTC",
    )
    assert out == "2026-06-15T00:00:00Z"


# ---------------------------------------------------------------------------
# End-to-end parser scenarios (kimi_usages_parser)
# ---------------------------------------------------------------------------


def test_kimi_usages_parser_full_payload() -> None:
    """Sample payload with both 5h row and top-level usage maps correctly."""
    payload = {
        "usage": {"used": 450, "limit": 1500, "reset_time": "2026-06-15T00:00:00Z"},
        "limits": [
            _limit_5h(used=25, limit=100, resetIn=3600),
            _limit_weekly_minutes(used=450, limit=1500),
        ],
    }
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.window_5h_percent == pytest.approx(25.0)
    assert result.window_7d_percent == pytest.approx(30.0)
    assert result.error is None
    # 5h reset was ``resetIn=3600`` → 1 hr → "1小时后重置"
    assert result.reset_5h == "1小时后重置"


def test_kimi_usages_parser_no_top_level_usage() -> None:
    """Without ``usage``, the 10080-minute row drives the weekly percent."""
    payload = {
        "limits": [
            _limit_5h(used=50, limit=200, resetIn=1800),
            _limit_weekly_minutes(used=300, limit=1000),
        ],
    }
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.window_5h_percent == pytest.approx(25.0)
    assert result.window_7d_percent == pytest.approx(30.0)
    assert result.error is None


def test_kimi_usages_parser_remaining_field() -> None:
    """A row with ``remaining`` (no ``used``) still produces a percent."""
    payload = {
        "limits": [
            {"window": {"duration": 300, "timeUnit": "MINUTE"}, "limit": 100, "remaining": 40},
        ],
    }
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.window_5h_percent == pytest.approx(60.0)


def test_kimi_usages_parser_no_recognised_rows() -> None:
    """A payload with no matching rows yields ``UsageData.error``."""
    payload = {"limits": [{"window": {"duration": 1, "timeUnit": "HOUR"}}]}
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.error is not None
    assert "recognised" in result.error.lower()


def test_kimi_usages_parser_invalid_payload_type() -> None:
    """A non-object payload is rejected with a clear error."""
    result = KimiProvider()._parse_usages_payload(["not", "a", "dict"])
    assert result.error is not None
    assert "object" in result.error.lower()


def test_kimi_usages_parser_limits_not_array() -> None:
    """``limits`` must be an array, not e.g. a dict."""
    payload = {"limits": {"oops": "not a list"}}
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.error is not None
    assert "array" in result.error.lower()


def test_kimi_usages_parser_limit_zero_error() -> None:
    """A row with ``limit <= 0`` surfaces a percent error."""
    payload = {
        "limits": [
            {
                "window": {"duration": 300, "timeUnit": "MINUTE"},
                "used": 0,
                "limit": 0,
            },
        ],
    }
    result = KimiProvider()._parse_usages_payload(payload)
    assert result.error is not None
    assert "limit must be > 0" in result.error


# ---------------------------------------------------------------------------
# Helpers (private API smoke tests)
# ---------------------------------------------------------------------------


def test_helper_urllib_error_constructor() -> None:
    """``urllib_error`` helper returns a configured HTTPError-like exception."""
    err = urllib_error(403, "Forbidden")
    assert err.code == 403
    assert "Forbidden" in err.reason


# ---------------------------------------------------------------------------
# Internal helper for HTTPError simulation in tests
# ---------------------------------------------------------------------------


def urllib_error(code: int, reason: str):
    """Build a real ``urllib.error.HTTPError`` without making a network call."""
    import urllib.error

    return urllib.error.HTTPError(
        url=KIMI_USAGES_URL,
        code=code,
        msg=reason,
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )

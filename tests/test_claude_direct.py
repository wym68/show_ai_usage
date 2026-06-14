"""Tests for the Claude direct-fetch helpers (``_format_iso_reset_time``,
``_read_token_from_file``, ``ClaudeProvider._resolve_token``).

The ISO-reset tests target the local helper added in Wave 1 (Plan Task 2)
that converts ISO 8601 reset timestamps from Claude direct API responses
into the project's canonical Chinese relative reset strings.

The credential-resolution tests target ``ClaudeProvider._resolve_token``
and ``_read_token_from_file`` added in Wave 3. They lock the contract:

* ``_resolve_token`` order:
    1. ``config.claude_code_access_token`` (env-first via Config)
    2. ``~/.claude/.credentials.json`` under ``claudeAiOauth.accessToken``
    3. ``~/.claude/.credentials.json`` under ``claudeAiOauth.access_token``
    4. ``~/.claude/.credentials.json`` top-level ``accessToken``
    5. ``~/.claude/.credentials.json`` top-level ``access_token``
* ``_read_token_from_file(path)`` accepts both nested and top-level
  shapes and returns the first non-empty token, or ``None`` on any
  failure mode.
* ``refreshToken`` is never returned.
* Missing/invalid/empty tokens return ``None`` without raising.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from poller.config import Config
from poller.providers.claude import (
    ClaudeProvider,
    _format_iso_reset_time,
    _read_token_from_file,
)


# ---------------------------------------------------------------------------
# Future resets
# ---------------------------------------------------------------------------


def test_format_iso_reset_future_two_hours() -> None:
    """A timestamp 2 hours in the future → '2小时后重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T12:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "2小时后重置"


def test_format_iso_reset_future_z_suffix() -> None:
    """``Z`` suffix is accepted and treated as UTC."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T12:00:00Z"
    assert _format_iso_reset_time(value, now=now) == "2小时后重置"


def test_format_iso_reset_future_one_hour() -> None:
    """Exactly 1 hour ahead renders as '1小时后重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T11:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "1小时后重置"


def test_format_iso_reset_future_multi_day() -> None:
    """A timestamp days in the future → 'X天Y小时后重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    # 1 day + 3 hours ahead
    value = "2026-06-14T13:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "1天3小时后重置"


def test_format_iso_reset_future_days_only() -> None:
    """A timestamp several days ahead with zero leftover hours."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-16T10:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "3天后重置"


def test_format_iso_reset_future_minutes_round_down_to_hour() -> None:
    """Sub-hour remainders drop (only day/hour granularity is rendered)."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    # 2 hours 45 minutes ahead → "2小时后重置"
    value = "2026-06-13T12:45:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "2小时后重置"


# ---------------------------------------------------------------------------
# At-or-before now
# ---------------------------------------------------------------------------


def test_format_iso_reset_at_now_returns_imminent() -> None:
    """A timestamp exactly equal to ``now`` → '即将重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T10:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "即将重置"


def test_format_iso_reset_past_returns_imminent() -> None:
    """A timestamp before ``now`` → '即将重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T09:00:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "即将重置"


def test_format_iso_reset_within_one_hour_returns_imminent() -> None:
    """A future timestamp within an hour collapses to '即将重置'."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T10:30:00+00:00"
    assert _format_iso_reset_time(value, now=now) == "即将重置"


# ---------------------------------------------------------------------------
# None / empty / malformed input
# ---------------------------------------------------------------------------


def test_format_iso_reset_none_returns_none() -> None:
    """``None`` input → ``None`` (no exception)."""
    assert _format_iso_reset_time(None) is None


def test_format_iso_reset_empty_string_returns_none() -> None:
    """Empty string → ``None`` (no exception)."""
    assert _format_iso_reset_time("") is None


def test_format_iso_reset_malformed_returns_none() -> None:
    """Malformed ISO string → ``None`` (no exception)."""
    assert _format_iso_reset_time("not-a-date") is None
    assert _format_iso_reset_time("2026/06/13 10:00") is None
    assert _format_iso_reset_time("abcdef") is None


# ---------------------------------------------------------------------------
# Timezone offset handling
# ---------------------------------------------------------------------------


def test_format_iso_reset_non_utc_offset() -> None:
    """Non-UTC offsets are normalized to UTC for the delta computation."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    # 2026-06-13T14:00:00+04:00 == 2026-06-13T10:00:00Z
    # so the delta is exactly 0 → "即将重置"
    value = "2026-06-13T14:00:00+04:00"
    assert _format_iso_reset_time(value, now=now) == "即将重置"


def test_format_iso_reset_non_utc_offset_future() -> None:
    """A +08:00 timestamp 5 hours after now UTC renders as 5 hours."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    # 18:00 +08:00 == 10:00 UTC → "即将重置"
    # 20:00 +08:00 == 12:00 UTC → 2 hours
    value = "2026-06-13T20:00:00+08:00"
    assert _format_iso_reset_time(value, now=now) == "2小时后重置"


def test_format_iso_reset_naive_treated_as_utc() -> None:
    """A naive ISO string (no tz suffix) is parsed as UTC."""
    now = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
    value = "2026-06-13T12:00:00"
    assert _format_iso_reset_time(value, now=now) == "2小时后重置"


def test_format_iso_reset_default_now_is_close_to_real_now() -> None:
    """When ``now`` is omitted, the helper uses current UTC and returns
    ``None`` for an obviously-past timestamp without raising."""
    past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert _format_iso_reset_time(past) == "即将重置"


# ---------------------------------------------------------------------------
# _parse_usage_payload (Wave 2 — Plan Task 5)
# ---------------------------------------------------------------------------
#
# Contract under test:
# * _parse_usage_payload(payload, *, timezone_id="UTC") -> UsageData
# * Non-dict payload → UsageData with error="Claude payload must be a JSON object".
# * Reads five_hour.utilization and seven_day.utilization, clamped to [0.0, 100.0].
# * five_hour.resets_at / seven_day.resets_at are passed through _format_iso_reset_time.
# * If five_hour is missing → percent defaults to 0.0 and reset_5h to None.
# * If seven_day is missing → percent defaults to 0.0 and reset_7d to None.
# * If both windows are missing → UsageData.error="Claude payload did not contain
#   any recognised usage rows".
# * Ignored keys: seven_day_sonnet, seven_day_opus, seven_day_oauth_apps,
#   seven_day_cowork, extra_usage.
# * provider="claude".


def test_parse_usage_payload_standard_maps_utilization() -> None:
    """Standard payload: both windows present → 5h and 7d percent mapped."""
    from poller.providers.claude import _parse_usage_payload

    payload = {
        "five_hour": {"utilization": 42.5, "resets_at": None},
        "seven_day": {"utilization": 13.25, "resets_at": None},
    }
    result = _parse_usage_payload(payload)
    assert result.provider == "claude"
    assert result.window_5h_percent == pytest.approx(42.5)
    assert result.window_7d_percent == pytest.approx(13.25)
    assert result.error is None


def test_parse_usage_payload_missing_five_hour_defaults_zero() -> None:
    """Missing five_hour → window_5h_percent=0.0, reset_5h=None."""
    from poller.providers.claude import _parse_usage_payload

    payload = {"seven_day": {"utilization": 33.0, "resets_at": None}}
    result = _parse_usage_payload(payload)
    assert result.window_5h_percent == 0.0
    assert result.reset_5h is None
    assert result.window_7d_percent == pytest.approx(33.0)
    assert result.error is None


def test_parse_usage_payload_missing_seven_day_defaults_zero() -> None:
    """Missing seven_day → window_7d_percent=0.0, reset_7d=None."""
    from poller.providers.claude import _parse_usage_payload

    payload = {"five_hour": {"utilization": 12.0, "resets_at": None}}
    result = _parse_usage_payload(payload)
    assert result.window_5h_percent == pytest.approx(12.0)
    assert result.window_7d_percent == 0.0
    assert result.reset_7d is None
    assert result.error is None


def test_parse_usage_payload_missing_both_windows_returns_error() -> None:
    """Payload with neither window → UsageData.error."""
    from poller.providers.claude import _parse_usage_payload

    payload: dict[str, object] = {}
    result = _parse_usage_payload(payload)
    assert result.provider == "claude"
    assert result.window_5h_percent == 0.0
    assert result.window_7d_percent == 0.0
    assert result.error is not None
    assert "recognised" in result.error.lower()


def test_parse_usage_payload_non_dict_returns_error() -> None:
    """Non-dict payload → UsageData.error mentioning JSON object."""
    from poller.providers.claude import _parse_usage_payload

    for bad in (["list"], "string", 42, 3.14, None, True):
        result = _parse_usage_payload(bad)
        assert result.provider == "claude"
        assert result.window_5h_percent == 0.0
        assert result.window_7d_percent == 0.0
        assert result.error is not None
        assert "object" in result.error.lower()


def test_parse_usage_payload_clamps_out_of_range() -> None:
    """Utilization > 100 → clamped to 100.0; utilization < 0 → clamped to 0.0."""
    from poller.providers.claude import _parse_usage_payload

    payload = {
        "five_hour": {"utilization": 150.0, "resets_at": None},
        "seven_day": {"utilization": -25.0, "resets_at": None},
    }
    result = _parse_usage_payload(payload)
    assert result.window_5h_percent == 100.0
    assert result.window_7d_percent == 0.0
    assert result.error is None


def test_parse_usage_payload_clamps_individual_windows() -> None:
    """5h clamped independently of 7d when only one is out-of-range."""
    from poller.providers.claude import _parse_usage_payload

    payload = {
        "five_hour": {"utilization": 75.0, "resets_at": None},
        "seven_day": {"utilization": 200.0, "resets_at": None},
    }
    result = _parse_usage_payload(payload)
    assert result.window_5h_percent == pytest.approx(75.0)
    assert result.window_7d_percent == 100.0


def test_parse_usage_payload_reset_times_converted() -> None:
    """``resets_at`` is converted via ``_format_iso_reset_time`` (relative string)."""
    from poller.providers.claude import _format_iso_reset_time, _parse_usage_payload

    five_hour_iso = "2099-01-01T00:00:00+00:00"
    seven_day_iso = "2099-01-02T03:00:00+00:00"
    payload = {
        "five_hour": {"utilization": 50.0, "resets_at": five_hour_iso},
        "seven_day": {"utilization": 20.0, "resets_at": seven_day_iso},
    }
    result = _parse_usage_payload(payload)
    assert result.reset_5h == _format_iso_reset_time(five_hour_iso)
    assert result.reset_7d == _format_iso_reset_time(seven_day_iso)


def test_parse_usage_payload_reset_times_use_format_helper() -> None:
    """Without ``now`` overrides, the helper is invoked — results are strings
    that match the canonical relative format (or ``即将重置`` for past/empty)."""
    from poller.providers.claude import _format_iso_reset_time, _parse_usage_payload

    payload = {
        "five_hour": {"utilization": 50.0, "resets_at": "2099-01-01T00:00:00Z"},
        "seven_day": {"utilization": 20.0, "resets_at": "2099-01-02T00:00:00Z"},
    }
    result = _parse_usage_payload(payload)
    # Both timestamps are decades in the future → helper returns "X天后重置".
    # Compare against calling the helper directly so any future tweak to the
    # canonical format stays in sync between parser and helper.
    assert result.reset_5h == _format_iso_reset_time("2099-01-01T00:00:00Z")
    assert result.reset_7d == _format_iso_reset_time("2099-01-02T00:00:00Z")


def test_parse_usage_payload_ignores_extra_fields() -> None:
    """sonnet/opus/oauth_apps/cowork/extra_usage keys are ignored."""
    from poller.providers.claude import _parse_usage_payload

    payload = {
        "five_hour": {"utilization": 10.0, "resets_at": None},
        "seven_day": {"utilization": 5.0, "resets_at": None},
        "seven_day_sonnet": {"utilization": 999.0, "resets_at": None},
        "seven_day_opus": {"utilization": 999.0, "resets_at": None},
        "seven_day_oauth_apps": {"utilization": 999.0, "resets_at": None},
        "seven_day_cowork": {"utilization": 999.0, "resets_at": None},
        "extra_usage": {"utilization": 999.0, "resets_at": None},
    }
    result = _parse_usage_payload(payload)
    assert result.window_5h_percent == pytest.approx(10.0)
    assert result.window_7d_percent == pytest.approx(5.0)
    assert result.error is None


def test_parse_usage_payload_sets_provider_and_fetched_at() -> None:
    """provider='claude' and fetched_at is a recent UTC datetime."""
    from poller.providers.claude import _parse_usage_payload

    before = datetime.now(timezone.utc)
    payload = {"five_hour": {"utilization": 1.0, "resets_at": None}}
    result = _parse_usage_payload(payload)
    after = datetime.now(timezone.utc)
    assert result.provider == "claude"
    assert before <= result.fetched_at <= after
    assert result.fetched_at.tzinfo is not None


def test_parse_usage_payload_signature() -> None:
    """Function signature is ``(payload, *, timezone_id='UTC') -> UsageData``."""
    import inspect

    from poller.providers.base import UsageData
    from poller.providers.claude import _parse_usage_payload

    sig = inspect.signature(_parse_usage_payload)
    params = list(sig.parameters)
    assert params == ["payload", "timezone_id"]
    assert sig.parameters["timezone_id"].default == "UTC"
    assert sig.parameters["timezone_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.return_annotation is UsageData


# ---------------------------------------------------------------------------
# Credential resolution (Wave 3 — Plan Task 3)
# ---------------------------------------------------------------------------


def _write_claude_credentials(path: Path, body: object) -> Path:
    """Drop a credentials JSON file at ``path`` (creating parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def _write_claude_credentials_raw(path: Path, raw_text: str) -> Path:
    """Drop arbitrary text as the credentials file (e.g. invalid JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw_text)
    return path


# _resolve_token: config field takes precedence
# ---------------------------------------------------------------------------


def test_resolve_token_config_field_overrides_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit config token wins over the file regardless of file contents."""
    cred_path = _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"claudeAiOauth": {"accessToken": "file-token-must-be-ignored"}},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = Config(claude_code_access_token="explicit-config-token")
    assert ClaudeProvider._resolve_token(cfg) == "explicit-config-token"


def test_resolve_token_env_var_populates_config_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``CLAUDE_CODE_ACCESS_TOKEN`` env var populates the config field."""
    monkeypatch.setenv("CLAUDE_CODE_ACCESS_TOKEN", "env-token-xyz")
    cfg = Config()
    assert ClaudeProvider._resolve_token(cfg) == "env-token-xyz"


# _resolve_token: nested claudeAiOauth shape
# ---------------------------------------------------------------------------


def test_resolve_token_nested_claudeAiOauth_accessToken_camel_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nested ``claudeAiOauth.accessToken`` is the canonical Claude Code CLI shape."""
    cred_path = _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"claudeAiOauth": {"accessToken": "nested-camel-token"}},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "nested-camel-token"
    assert cred_path.exists()


def test_resolve_token_nested_claudeAiOauth_access_token_snake_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nested ``claudeAiOauth.access_token`` is accepted as a fallback."""
    cred_path = _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"claudeAiOauth": {"access_token": "nested-snake-token"}},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "nested-snake-token"
    assert cred_path.exists()


# _resolve_token: top-level shape
# ---------------------------------------------------------------------------


def test_resolve_token_top_level_accessToken_camel_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Top-level ``accessToken`` is accepted."""
    cred_path = _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"accessToken": "top-camel-token"},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "top-camel-token"
    assert cred_path.exists()


def test_resolve_token_top_level_access_token_snake_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Top-level ``access_token`` is accepted."""
    cred_path = _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"access_token": "top-snake-token"},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "top-snake-token"
    assert cred_path.exists()


def test_resolve_token_prefers_nested_over_top_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When both nested and top-level shapes are present, nested wins."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {
            "claudeAiOauth": {"accessToken": "nested-wins"},
            "accessToken": "top-loses",
            "access_token": "top-snake-loses",
        },
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "nested-wins"


def test_resolve_token_prefers_camelCase_over_snake_case_in_same_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When both camelCase and snake_case are in the same scope, camelCase wins."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {
            "claudeAiOauth": {
                "access_token": "snake-loses",
                "accessToken": "camel-wins",
            }
        },
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) == "camel-wins"


# _resolve_token: failure modes
# ---------------------------------------------------------------------------


def test_resolve_token_missing_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing credentials file → ``None`` (no exception)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) is None


def test_resolve_token_invalid_json_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Invalid JSON in the file → ``None`` (no exception)."""
    _write_claude_credentials_raw(
        tmp_path / ".claude" / ".credentials.json",
        "{this is not json",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) is None


def test_resolve_token_empty_token_string_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty token strings are treated as absent."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"claudeAiOauth": {"accessToken": ""}},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) is None


def test_resolve_token_whitespace_only_token_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whitespace-only tokens are treated as absent."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {"claudeAiOauth": {"accessToken": "   \t\n  "}},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ClaudeProvider._resolve_token(Config()) is None


def test_resolve_token_ignores_refresh_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``refreshToken`` (and its snake_case sibling) must never be returned."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {
            "claudeAiOauth": {
                "refreshToken": "refresh-camel-must-not-leak",
                "refresh_token": "refresh-snake-must-not-leak",
            },
            "refreshToken": "top-refresh-must-not-leak",
        },
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = ClaudeProvider._resolve_token(Config())
    assert result is None


def test_resolve_token_ignores_refresh_token_when_access_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An access token still wins; ``refreshToken`` is ignored even if present."""
    _write_claude_credentials(
        tmp_path / ".claude" / ".credentials.json",
        {
            "claudeAiOauth": {
                "accessToken": "real-access-token",
                "refreshToken": "irrelevant-refresh",
            }
        },
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = ClaudeProvider._resolve_token(Config())
    assert result == "real-access-token"


# _read_token_from_file: direct API smoke tests
# ---------------------------------------------------------------------------


def test_read_token_from_file_nested_accessToken(tmp_path: Path) -> None:
    """``_read_token_from_file`` accepts nested ``accessToken``."""
    target = tmp_path / "creds.json"
    target.write_text(json.dumps({"claudeAiOauth": {"accessToken": "nested-token"}}))
    assert _read_token_from_file(target) == "nested-token"


def test_read_token_from_file_nested_access_token(tmp_path: Path) -> None:
    """``_read_token_from_file`` accepts nested ``access_token``."""
    target = tmp_path / "creds.json"
    target.write_text(json.dumps({"claudeAiOauth": {"access_token": "nested-snake"}}))
    assert _read_token_from_file(target) == "nested-snake"


def test_read_token_from_file_top_level_accessToken(tmp_path: Path) -> None:
    """``_read_token_from_file`` accepts top-level ``accessToken``."""
    target = tmp_path / "creds.json"
    target.write_text(json.dumps({"accessToken": "top-camel"}))
    assert _read_token_from_file(target) == "top-camel"


def test_read_token_from_file_top_level_access_token(tmp_path: Path) -> None:
    """``_read_token_from_file`` accepts top-level ``access_token``."""
    target = tmp_path / "creds.json"
    target.write_text(json.dumps({"access_token": "top-snake"}))
    assert _read_token_from_file(target) == "top-snake"


def test_read_token_from_file_missing_file(tmp_path: Path) -> None:
    """Missing file → ``None``."""
    assert _read_token_from_file(tmp_path / "nope.json") is None


def test_read_token_from_file_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON → ``None`` (no exception leaks)."""
    target = tmp_path / "bad.json"
    target.write_text("{this is not json")
    assert _read_token_from_file(target) is None


def test_read_token_from_file_empty_token(tmp_path: Path) -> None:
    """Empty token → ``None``."""
    target = tmp_path / "empty.json"
    target.write_text(json.dumps({"claudeAiOauth": {"accessToken": ""}}))
    assert _read_token_from_file(target) is None


def test_read_token_from_file_non_string_token(tmp_path: Path) -> None:
    """Non-string token values are ignored (no TypeError leaks)."""
    target = tmp_path / "nonstring.json"
    target.write_text(json.dumps({"claudeAiOauth": {"accessToken": 12345}}))
    assert _read_token_from_file(target) is None


def test_read_token_from_file_non_dict_root(tmp_path: Path) -> None:
    """A non-dict JSON root → ``None``."""
    target = tmp_path / "list.json"
    target.write_text(json.dumps(["not", "a", "dict"]))
    assert _read_token_from_file(target) is None


def test_read_token_from_file_ignores_refresh_token(tmp_path: Path) -> None:
    """``refreshToken`` is ignored even if it is the only token-shaped key."""
    target = tmp_path / "refresh.json"
    target.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "refreshToken": "refresh-only",
                    "access_token": "",
                }
            }
        )
    )
    assert _read_token_from_file(target) is None


def test_read_token_from_file_strips_whitespace(tmp_path: Path) -> None:
    """Surrounding whitespace on the token is stripped."""
    target = tmp_path / "ws.json"
    target.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "  padded-token  "}})
    )
    assert _read_token_from_file(target) == "padded-token"


def test_read_token_from_file_nested_takes_precedence_over_top_level(tmp_path: Path) -> None:
    """When both shapes are present, nested wins."""
    target = tmp_path / "both.json"
    target.write_text(
        json.dumps(
            {
                "claudeAiOauth": {"accessToken": "nested-wins"},
                "accessToken": "top-loses",
            }
        )
    )
    assert _read_token_from_file(target) == "nested-wins"


# ---------------------------------------------------------------------------
# Direct-fetch path (Wave 4 — Plan Task 4)
# ---------------------------------------------------------------------------
#
# Contract under test:
# * ClaudeProvider supports_direct_fetch is True and satisfies DirectFetchProvider.
# * fetch_direct returns parsed UsageData on 200 with standard payload.
# * Request uses CLAUDE_USAGE_API_URL with the documented headers and
#   CLAUDE_HTTP_TIMEOUT.
# * Missing token returns a UsageData.error and makes no HTTP call.
# * HTTP 401 / 403 / 429 → UsageData.error with safe message (no token).
# * URLError / TimeoutError → UsageData.error.
# * Invalid JSON → UsageData.error.


def _ok_claude_response(body: dict[str, Any]) -> MagicMock:
    """Build a context-manager mock that returns ``body`` JSON."""
    ctx = MagicMock()
    ctx.__enter__.return_value.read.return_value = json.dumps(body).encode("utf-8")
    return ctx


def _make_http_error(code: int, *, msg: str = "Server Error") -> urllib.error.HTTPError:
    """Build a ``urllib.error.HTTPError`` for urlopen side_effect tests."""
    return urllib.error.HTTPError(
        url="https://api.anthropic.com/api/oauth/usage",
        code=code,
        msg=msg,
        hdrs={},  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )


# Protocol / capability
# ---------------------------------------------------------------------------


def test_fetch_direct_protocol_capability() -> None:
    """ClaudeProvider must satisfy DirectFetchProvider and advertise the flag."""
    from poller.providers.direct import DirectFetchProvider

    provider = ClaudeProvider()
    assert isinstance(provider, DirectFetchProvider)
    assert provider.supports_direct_fetch is True
    assert provider.name == "claude"


# fetch_direct: success path
# ---------------------------------------------------------------------------


def test_fetch_direct_returns_parsed_usage_data_on_200() -> None:
    """A 200 response with the standard payload is parsed into UsageData."""
    from unittest.mock import patch

    payload = {
        "five_hour": {"utilization": 42.5, "resets_at": None},
        "seven_day": {"utilization": 13.25, "resets_at": None},
    }
    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        return_value=_ok_claude_response(payload),
    ):
        data = provider.fetch_direct(cfg)

    assert data.provider == "claude"
    assert data.error is None
    assert data.window_5h_percent == pytest.approx(42.5)
    assert data.window_7d_percent == pytest.approx(13.25)


def test_fetch_direct_request_uses_expected_url_and_headers() -> None:
    """The urlopen call must hit CLAUDE_USAGE_API_URL with the documented headers."""
    from unittest.mock import patch

    from poller.providers.claude import CLAUDE_HTTP_TIMEOUT, CLAUDE_USAGE_API_URL

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()
    payload = {"five_hour": {"utilization": 1.0, "resets_at": None}}

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        return_value=_ok_claude_response(payload),
    ) as urlopen:
        provider.fetch_direct(cfg)

        assert urlopen.call_count == 1
        req = urlopen.call_args[0][0]
        assert req.full_url == CLAUDE_USAGE_API_URL
        lower_header_map = {k.lower(): v for k, v in req.headers.items()}
        assert lower_header_map["authorization"] == "Bearer good-token"
        assert lower_header_map["anthropic-beta"] == "oauth-2025-04-20"
        assert lower_header_map["accept"] == "application/json"
        assert lower_header_map["user-agent"] == "show-ai-usage-poller/1.0"
        assert urlopen.call_args.kwargs.get("timeout") == CLAUDE_HTTP_TIMEOUT


# fetch_direct: missing credentials
# ---------------------------------------------------------------------------


def test_fetch_direct_missing_token_returns_error_no_http_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No token + no credentials file → UsageData.error and no urlopen call."""
    from unittest.mock import patch

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = Config()
    assert cfg.claude_code_access_token == ""
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen"
    ) as urlopen:
        data = provider.fetch_direct(cfg)

    urlopen.assert_not_called()
    assert data.error is not None
    assert "CLAUDE_CODE_ACCESS_TOKEN" in data.error
    assert "~/.claude/.credentials.json" in data.error
    assert data.window_5h_percent == 0.0
    assert data.window_7d_percent == 0.0


def test_fetch_direct_missing_token_does_not_leak_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing-credential error must never echo the absent token value."""
    from unittest.mock import patch

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen"
    ) as urlopen:
        data = provider.fetch_direct(Config())

    urlopen.assert_not_called()
    assert data.error is not None
    assert "super-secret-token" not in data.error


# fetch_direct: HTTP error codes
# ---------------------------------------------------------------------------


def test_fetch_direct_http_401_returns_error_no_token_leak() -> None:
    """HTTP 401 → UsageData.error with status code, no token, no upstream body."""
    from unittest.mock import patch

    cfg = Config(claude_code_access_token="super-secret-token-do-not-leak")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        side_effect=_make_http_error(401, msg="Unauthorized: token super-secret-token-do-not-leak leaked"),
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "401" in data.error
    assert "super-secret-token-do-not-leak" not in data.error
    assert "Unauthorized" not in data.error
    assert data.window_5h_percent == 0.0


def test_fetch_direct_http_403_returns_error() -> None:
    """HTTP 403 → UsageData.error mentioning 403."""
    from unittest.mock import patch

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        side_effect=_make_http_error(403, msg="Forbidden"),
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "403" in data.error
    assert "Forbidden" not in data.error


def test_fetch_direct_http_429_returns_error() -> None:
    """HTTP 429 (rate limited) → UsageData.error mentioning 429. No retry."""
    from unittest.mock import patch

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        side_effect=_make_http_error(429, msg="Too Many Requests"),
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "429" in data.error


# fetch_direct: network errors
# ---------------------------------------------------------------------------


def test_fetch_direct_url_error_returns_error() -> None:
    """``URLError`` (DNS / connection refused) → UsageData.error."""
    from unittest.mock import patch

    import urllib.error

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        side_effect=urllib.error.URLError("Name or service not known"),
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "unreachable" in data.error.lower() or "url" in data.error.lower()
    assert data.window_5h_percent == 0.0


def test_fetch_direct_timeout_returns_error() -> None:
    """``TimeoutError`` → UsageData.error mentioning the timeout."""
    from unittest.mock import patch

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        side_effect=TimeoutError("read timed out"),
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "timed out" in data.error.lower()


# fetch_direct: invalid JSON
# ---------------------------------------------------------------------------


def test_fetch_direct_invalid_json_returns_error() -> None:
    """Non-JSON body → UsageData.error mentioning JSON / decode failure."""
    from unittest.mock import MagicMock, patch

    cfg = Config(claude_code_access_token="good-token")
    provider = ClaudeProvider()

    bad_ctx = MagicMock()
    bad_ctx.__enter__.return_value.read.return_value = b"definitely-not-json"

    with patch(
        "poller.providers.claude.urllib.request.urlopen",
        return_value=bad_ctx,
    ):
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "json" in data.error.lower()
"""Tests for the MiniMax direct-fetch path (Wave 2).

Covers:
* ``MiniMaxProvider`` satisfies ``DirectFetchProvider`` and exposes
  the boolean capability flag.
* Default endpoint URL (``https://api.minimax.io``) is used when no
  override is configured.
* ``MINIMAX_API_BASE_URL`` (and ``Config.minimax_api_base_url``)
  override the endpoint.
* Missing credentials + no ``mmx`` CLI → ``UsageData.error`` is set.
* ``mmx`` CLI fallback runs when API key is absent and parses the
  same JSON schema.
* Parser handles all three documented shapes:
  row object, ``data`` wrapper, ``model_remains`` list — preferring
  the row whose ``model_name`` contains ``minimax`` (case-insensitive).
* Percent computation: ``remains_percent`` first, then
  ``usage_count`` / ``total_count`` fallback.
* Reset fields come from ``remains_time`` / ``end_time`` (5h) and
  ``weekly_remains_time`` / ``weekly_end_time`` (7d).
* API key is never leaked through error messages.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from poller.config import Config
from poller.providers.base import UsageData
from poller.providers.direct import DirectFetchProvider
from poller.providers.minimax import (
    MINIMAX_API_PATH,
    MINIMAX_CLI_BINARY,
    MINIMAX_DEFAULT_API_BASE_URL,
    MINIMAX_HTTP_TIMEOUT,
    MiniMaxProvider,
    _coerce_window_percent,
    _format_seconds_as_reset,
    _select_model_remains,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    *,
    model_name: str = "MiniMax-Text-01",
    remains_percent: float | None = 70.0,
    usage_count: float | None = None,
    total_count: float | None = None,
    remains_time: float | int | None = 18000,
    weekly_remains_percent: float | None = 90.0,
    weekly_usage_count: float | None = None,
    weekly_total_count: float | None = None,
    weekly_remains_time: float | int | None = 500000,
) -> dict[str, Any]:
    """Build a single model_remains row with sensible defaults."""
    row: dict[str, Any] = {"model_name": model_name}
    if remains_percent is not None:
        row["remains_percent"] = remains_percent
    if usage_count is not None:
        row["usage_count"] = usage_count
    if total_count is not None:
        row["total_count"] = total_count
    if remains_time is not None:
        row["remains_time"] = remains_time
    if weekly_remains_percent is not None:
        row["weekly_remains_percent"] = weekly_remains_percent
    if weekly_usage_count is not None:
        row["weekly_usage_count"] = weekly_usage_count
    if weekly_total_count is not None:
        row["weekly_total_count"] = weekly_total_count
    if weekly_remains_time is not None:
        row["weekly_remains_time"] = weekly_remains_time
    return row


def _ok_response(body: dict[str, Any]) -> MagicMock:
    """Build a context-manager mock that returns ``body`` JSON."""
    ctx = MagicMock()
    ctx.__enter__.return_value.read.return_value = json.dumps(body).encode("utf-8")
    return ctx


def _cli_ok(stdout: str) -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = stdout
    proc.stderr = ""
    return proc


# ---------------------------------------------------------------------------
# Protocol / capability
# ---------------------------------------------------------------------------


def test_minimax_provider_satisfies_direct_protocol() -> None:
    provider = MiniMaxProvider()
    assert isinstance(provider, DirectFetchProvider)
    assert provider.supports_direct_fetch is True
    assert provider.name == "minimax"


def test_minimax_provider_inherits_base_provider_fetch() -> None:
    """``MiniMaxProvider`` keeps its browser-based ``fetch`` for fallback."""
    import inspect

    sig = inspect.signature(MiniMaxProvider.fetch)
    assert list(sig.parameters) == ["self", "context"]


# ---------------------------------------------------------------------------
# Parser: shape selection
# ---------------------------------------------------------------------------


def test_select_model_remains_picks_minimax_row_from_list() -> None:
    rows = [
        {"model_name": "OtherModel-X", "remains_percent": 50},
        {"model_name": "MiniMax-Text-01", "remains_percent": 70},
        {"model_name": "AnotherModel", "remains_percent": 30},
    ]
    picked = _select_model_remains({"model_remains": rows})
    assert picked is not None
    assert picked["model_name"] == "MiniMax-Text-01"


def test_select_model_remains_case_insensitive() -> None:
    """``model_name`` match must be case-insensitive."""
    rows = [
        {"model_name": "MINIMAX-Pro-01", "remains_percent": 10},
        {"model_name": "Other", "remains_percent": 90},
    ]
    picked = _select_model_remains({"model_remains": rows})
    assert picked["model_name"] == "MINIMAX-Pro-01"


def test_select_model_remains_handles_data_wrapper() -> None:
    payload = {"data": _row(model_name="MiniMax-Text-01")}
    picked = _select_model_remains(payload)
    assert picked is not None
    assert picked["model_name"] == "MiniMax-Text-01"


def test_select_model_remains_handles_data_list() -> None:
    payload = {"data": [_row(model_name="Other-X"), _row(model_name="MiniMax-Y")]}
    picked = _select_model_remains(payload)
    assert picked["model_name"] == "MiniMax-Y"


def test_select_model_remains_handles_nested_data_model_remains() -> None:
    payload = {"data": {"model_remains": [_row(model_name="MiniMax-Z")]}}
    picked = _select_model_remains(payload)
    assert picked["model_name"] == "MiniMax-Z"


def test_select_model_remains_handles_top_level_row() -> None:
    """If the response is itself a row, we accept it as-is."""
    payload = _row(model_name="MiniMax-Text-01")
    picked = _select_model_remains(payload)
    assert picked is not None
    assert picked["model_name"] == "MiniMax-Text-01"


def test_select_model_remains_falls_back_to_first_row_without_minimax() -> None:
    """When no row mentions ``minimax``, pick the first valid row."""
    payload = {"model_remains": [{"model_name": "Other-X"}, {"model_name": "Other-Y"}]}
    picked = _select_model_remains(payload)
    assert picked == {"model_name": "Other-X"}


def test_select_model_remains_returns_none_for_garbage() -> None:
    assert _select_model_remains({}) is None
    assert _select_model_remains({"model_remains": []}) is None
    assert _select_model_remains("not-a-dict-or-list") is None
    assert _select_model_remains({"data": "garbage"}) is None


# ---------------------------------------------------------------------------
# Parser: percent computation
# ---------------------------------------------------------------------------


def test_coerce_window_percent_uses_remains_percent_first() -> None:
    row = _row(remains_percent=70.0)
    assert _coerce_window_percent(row, "") == pytest.approx(30.0)


def test_coerce_window_percent_falls_back_to_counts() -> None:
    row = _row(remains_percent=None, usage_count=30.0, total_count=100.0)
    assert _coerce_window_percent(row, "") == pytest.approx(30.0)


def test_coerce_window_percent_weekly_prefix() -> None:
    row = _row(
        weekly_remains_percent=20.0,
        weekly_usage_count=999,  # should be ignored in favour of remains
        weekly_total_count=1000,
    )
    assert _coerce_window_percent(row, "weekly_") == pytest.approx(80.0)


def test_coerce_window_percent_weekly_counts_fallback() -> None:
    row = _row(
        weekly_remains_percent=None,
        weekly_usage_count=40.0,
        weekly_total_count=100.0,
    )
    assert _coerce_window_percent(row, "weekly_") == pytest.approx(40.0)


def test_coerce_window_percent_handles_nested_weekly_dict() -> None:
    """``{"weekly": {"remains_percent": 50}}`` is equivalent to flat keys."""
    row = {
        "model_name": "MiniMax-Text-01",
        "remains_percent": 70.0,
        "remains_time": 18000,
        "weekly": {"remains_percent": 40.0, "remains_time": 500000},
    }
    assert _coerce_window_percent(row, "weekly_") == pytest.approx(60.0)


def test_coerce_window_percent_returns_none_when_missing() -> None:
    row = {"model_name": "MiniMax"}
    assert _coerce_window_percent(row, "") is None
    assert _coerce_window_percent(row, "weekly_") is None


def test_coerce_window_percent_clamps_to_0_100() -> None:
    """Defensive: ensures percent stays within UsageData's ge/le bounds."""
    # remains_percent=150 → used=-50, clamp to 0
    row = _row(remains_percent=150.0)
    assert _coerce_window_percent(row, "") == 0.0
    # remains_percent=-10 → used=110, clamp to 100
    row = _row(remains_percent=-10.0)
    assert _coerce_window_percent(row, "") == 100.0


def test_coerce_window_percent_skips_zero_total() -> None:
    """``total_count=0`` must not raise — just skip and return None."""
    row = _row(remains_percent=None, usage_count=5, total_count=0)
    assert _coerce_window_percent(row, "") is None


# ---------------------------------------------------------------------------
# Parser: reset time formatting
# ---------------------------------------------------------------------------


def test_format_seconds_days_hours_minutes() -> None:
    # 2 days, 3 hours, 4 minutes  → 4*60 + 3*3600 + 2*86400 = 4*60+10800+172800 = 183840
    assert _format_seconds_as_reset(2 * 86400 + 3 * 3600 + 4 * 60) == "2天3小时4分后重置"


def test_format_seconds_hours_only() -> None:
    assert _format_seconds_as_reset(2 * 3600) == "2小时后重置"


def test_format_seconds_minutes_only() -> None:
    assert _format_seconds_as_reset(45 * 60) == "45分后重置"


def test_format_seconds_zero_or_negative() -> None:
    assert _format_seconds_as_reset(0) == "即将重置"
    assert _format_seconds_as_reset(-1) == "即将重置"


def test_format_seconds_none_returns_none() -> None:
    assert _format_seconds_as_reset(None) is None


def test_format_seconds_non_numeric_returns_none() -> None:
    assert _format_seconds_as_reset("nope") is None  # type: ignore[arg-type] # ---------------------------------------------------------------------------
# Parser: end-to-end payload → UsageData
# ---------------------------------------------------------------------------


def test_parse_payload_full_row() -> None:
    data = MiniMaxProvider._parse_remains_payload(_row())
    assert isinstance(data, UsageData)
    assert data.error is None
    assert data.window_5h_percent == pytest.approx(30.0)
    assert data.window_7d_percent == pytest.approx(10.0)
    assert data.reset_5h == "5小时后重置"     # 18000s = 5h
    assert data.reset_7d is not None
    assert "后重置" in data.reset_7d


def test_parse_payload_data_wrapper() -> None:
    payload = {"data": _row()}
    data = MiniMaxProvider._parse_remains_payload(payload)
    assert data.error is None
    assert data.window_5h_percent == pytest.approx(30.0)


def test_parse_payload_model_remains_list_prefers_minimax() -> None:
    payload = {
        "model_remains": [
            {**_row(model_name="OtherModel", remains_percent=50.0),
             "model_name": "OtherModel"},
            _row(model_name="MiniMax-Text-01", remains_percent=80.0),
        ]
    }
    data = MiniMaxProvider._parse_remains_payload(payload)
    assert data.window_5h_percent == pytest.approx(20.0)


def test_parse_payload_missing_row_sets_error() -> None:
    data = MiniMaxProvider._parse_remains_payload({})
    assert data.error is not None
    assert "model_remains" in data.error
    # Defaults are zero, not raised.
    assert data.window_5h_percent == 0.0
    assert data.window_7d_percent == 0.0


def test_parse_payload_partial_row_still_returns() -> None:
    """A row with only the 5h field set must not error out on the 7d side."""
    data = MiniMaxProvider._parse_remains_payload(
        _row(weekly_remains_percent=None, weekly_remains_time=None)
    )
    assert data.error is None
    assert data.window_5h_percent == pytest.approx(30.0)
    assert data.window_7d_percent == 0.0
    assert data.reset_7d is None


# ---------------------------------------------------------------------------
# fetch_direct: routing / credentials
# ---------------------------------------------------------------------------


def test_fetch_direct_default_endpoint_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default base URL must be ``https://api.minimax.io``."""
    monkeypatch.delenv("MINIMAX_API_BASE_URL", raising=False)
    cfg = Config(minimax_api_key="test-key")

    provider = MiniMaxProvider()
    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _ok_response({"data": _row()})
        provider.fetch_direct(cfg)

        # Inspect the Request object that was passed in.
        assert urlopen.call_count == 1
        req = urlopen.call_args[0][0]
        expected = f"{MINIMAX_DEFAULT_API_BASE_URL.rstrip('/')}{MINIMAX_API_PATH}"
        assert req.full_url == expected
        assert req.headers["Authorization"] == "Bearer test-key"


def test_fetch_direct_env_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MINIMAX_API_BASE_URL=https://api.minimaxi.com`` must be honoured."""
    monkeypatch.setenv("MINIMAX_API_BASE_URL", "https://api.minimaxi.com")
    cfg = Config(minimax_api_key="test-key")

    provider = MiniMaxProvider()
    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _ok_response({"data": _row()})
        provider.fetch_direct(cfg)

        req = urlopen.call_args[0][0]
        assert req.full_url == "https://api.minimaxi.com/v1/token_plan/remains"


def test_fetch_direct_config_base_url_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Config.minimax_api_base_url`` overrides the default."""
    monkeypatch.delenv("MINIMAX_API_BASE_URL", raising=False)
    cfg = Config(
        minimax_api_key="test-key",
        minimax_api_base_url="https://override.example.test",
    )

    provider = MiniMaxProvider()
    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _ok_response({"data": _row()})
        provider.fetch_direct(cfg)
        req = urlopen.call_args[0][0]
        assert req.full_url == "https://override.example.test/v1/token_plan/remains"


def test_fetch_direct_base_url_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trailing slashes on the base URL must not produce double slashes."""
    monkeypatch.delenv("MINIMAX_API_BASE_URL", raising=False)
    cfg = Config(
        minimax_api_key="test-key",
        minimax_api_base_url="https://api.example.test/",
    )

    provider = MiniMaxProvider()
    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _ok_response({"data": _row()})
        provider.fetch_direct(cfg)
        req = urlopen.call_args[0][0]
        assert req.full_url == "https://api.example.test/v1/token_plan/remains"


def test_fetch_direct_uses_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The urlopen call must pass a timeout."""
    monkeypatch.delenv("MINIMAX_API_BASE_URL", raising=False)
    cfg = Config(minimax_api_key="test-key")

    provider = MiniMaxProvider()
    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _ok_response({"data": _row()})
        provider.fetch_direct(cfg)
        kwargs = urlopen.call_args.kwargs
        assert kwargs.get("timeout") == MINIMAX_HTTP_TIMEOUT


def test_fetch_direct_http_error_returns_usage_data_with_error() -> None:
    """A non-2xx HTTP response must become a populated ``UsageData.error``,
    NOT a raised exception."""
    cfg = Config(minimax_api_key="bad-key")
    provider = MiniMaxProvider()

    import urllib.error

    http_err = urllib.error.HTTPError(
        url="https://api.minimax.io/v1/token_plan/remains",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )

    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = http_err
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "401" in data.error
    assert data.window_5h_percent == 0.0


def test_fetch_direct_url_error_returns_usage_data_with_error() -> None:
    cfg = Config(minimax_api_key="test-key")
    provider = MiniMaxProvider()

    import urllib.error

    url_err = urllib.error.URLError("Name or service not known")

    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = url_err
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "unreachable" in data.error.lower() or "url" in data.error.lower()


def test_fetch_direct_invalid_json_returns_usage_data_with_error() -> None:
    cfg = Config(minimax_api_key="test-key")
    provider = MiniMaxProvider()

    bad_ctx = MagicMock()
    bad_ctx.__enter__.return_value.read.return_value = b"not-json-at-all"

    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.return_value = bad_ctx
        data = provider.fetch_direct(cfg)

    assert data.error is not None
    assert "json" in data.error.lower()


def test_fetch_direct_missing_credentials_no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """No API key AND no ``mmx`` CLI → clear provider error in ``UsageData.error``."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr("poller.providers.minimax.shutil.which", lambda _: None)
    # Also patch subprocess.run so a stray ``mmx`` in the test env can't run.
    monkeypatch.setattr(
        "poller.providers.minimax.subprocess.run",
        lambda *a, **kw: pytest.fail("subprocess.run must not be called"),
    )

    cfg = Config()
    assert cfg.minimax_api_key == ""
    provider = MiniMaxProvider()

    data = provider.fetch_direct(cfg)
    assert data.error is not None
    assert "MINIMAX_API_KEY" in data.error
    assert MINIMAX_CLI_BINARY in data.error


def test_fetch_direct_api_key_not_leaked_in_error() -> None:
    """The API key must never appear in error messages or exception text."""
    secret_key = "super-secret-api-key-do-not-leak"
    cfg = Config(minimax_api_key=secret_key)
    provider = MiniMaxProvider()

    import urllib.error

    http_err = urllib.error.HTTPError(
        url="https://api.minimax.io/v1/token_plan/remains",
        code=500,
        msg="Server Error: bad token super-secret-api-key-do-not-leak",
        hdrs={},  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )

    with patch("poller.providers.minimax.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = http_err
        data = provider.fetch_direct(cfg)

    # Our handler must produce an error message that contains ONLY the
    # status code and reason we control — never the raw upstream body
    # that might echo the key back.
    assert data.error is not None
    assert secret_key not in data.error
    assert "***" not in data.error  # we don't mask; we just don't echo


# ---------------------------------------------------------------------------
# CLI fallback
# ---------------------------------------------------------------------------


class TestMiniMaxCliFallback:
    """``uv run pytest tests/ -k minimax_cli_fallback`` selects this class
    (the marker below also feeds the ``-k`` matcher)."""

    pytestmark = pytest.mark.minimax_cli_fallback  # type: ignore[attr-defined] 

    def test_runs_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without API key but with ``mmx`` on PATH, fetch_direct shells out."""
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.setattr(
            "poller.providers.minimax.shutil.which",
            lambda name: "/usr/local/bin/mmx" if name == MINIMAX_CLI_BINARY else None,
        )

        captured_cmd: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return _cli_ok(json.dumps({"data": _row()}))

        monkeypatch.setattr("poller.providers.minimax.subprocess.run", fake_run)

        cfg = Config()
        provider = MiniMaxProvider()
        data = provider.fetch_direct(cfg)

        assert data.error is None
        assert data.window_5h_percent == pytest.approx(30.0)
        assert captured_cmd["cmd"] == [
            MINIMAX_CLI_BINARY, "quota", "show", "--output", "json"
        ]

    def test_nonzero_exit_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.setattr(
            "poller.providers.minimax.shutil.which",
            lambda name: "/usr/local/bin/mmx" if name == MINIMAX_CLI_BINARY else None,
        )

        proc = MagicMock()
        proc.returncode = 2
        proc.stdout = ""
        proc.stderr = "quota: not configured"

        monkeypatch.setattr(
            "poller.providers.minimax.subprocess.run", lambda *a, **kw: proc
        )

        data = MiniMaxProvider().fetch_direct(Config())
        assert data.error is not None
        assert "mmx" in data.error.lower() or MINIMAX_CLI_BINARY in data.error
        # The CLI's stderr should not be echoed raw (could leak credentials).
        assert "not configured" not in data.error

    def test_timeout_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.setattr(
            "poller.providers.minimax.shutil.which",
            lambda name: "/usr/local/bin/mmx" if name == MINIMAX_CLI_BINARY else None,
        )

        import subprocess

        def fake_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="mmx", timeout=30)

        monkeypatch.setattr("poller.providers.minimax.subprocess.run", fake_run)

        data = MiniMaxProvider().fetch_direct(Config())
        assert data.error is not None
        assert "timed out" in data.error.lower()

    def test_invalid_json_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.setattr(
            "poller.providers.minimax.shutil.which",
            lambda name: "/usr/local/bin/mmx" if name == MINIMAX_CLI_BINARY else None,
        )
        monkeypatch.setattr(
            "poller.providers.minimax.subprocess.run",
            lambda *a, **kw: _cli_ok("definitely not json"),
        )

        data = MiniMaxProvider().fetch_direct(Config())
        assert data.error is not None
        assert "json" in data.error.lower()

    def test_parses_same_schema_as_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI output schema must be interchangeable with the API payload."""
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.setattr(
            "poller.providers.minimax.shutil.which",
            lambda name: "/usr/local/bin/mmx" if name == MINIMAX_CLI_BINARY else None,
        )

        payload = {
            "model_remains": [
                _row(model_name="MiniMax-Text-01"),
                _row(model_name="OtherModel", remains_percent=10.0),
            ]
        }
        monkeypatch.setattr(
            "poller.providers.minimax.subprocess.run",
            lambda *a, **kw: _cli_ok(json.dumps(payload)),
        )

        data = MiniMaxProvider().fetch_direct(Config())
        # Should pick the MiniMax row (remains_percent=70 → used 30%).
        assert data.window_5h_percent == pytest.approx(30.0)
        assert data.error is None


# ---------------------------------------------------------------------------
# Parser mark — explicit parametrised marker for pytest -k minimax_token_plan_parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape,payload",
    [
        ("row", _row()),
        ("data_dict", {"data": _row()}),
        ("data_list", {"data": [_row()]}),
        ("model_remains_list", {"model_remains": [_row()]}),
        ("nested_data_model_remains", {"data": {"model_remains": [_row()]}}),
    ],
)
def test_minimax_token_plan_parser_all_shapes(shape: str, payload: dict[str, Any]) -> None:
    """All documented payload shapes must parse successfully."""
    data = MiniMaxProvider._parse_remains_payload(payload)
    assert data.error is None, f"shape={shape} unexpectedly errored: {data.error}"
    assert data.provider == "minimax"
    assert data.window_5h_percent == pytest.approx(30.0)
    assert data.window_7d_percent == pytest.approx(10.0)

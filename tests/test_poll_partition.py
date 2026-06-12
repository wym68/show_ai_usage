from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from playwright.sync_api import BrowserContext

from poller.config import Config
from poller.main import _poll
from poller.providers.base import BaseProvider, UsageData


@dataclass
class _Recorder:
    direct: list[str] = field(default_factory=list)
    browser: list[str] = field(default_factory=list)
    launches: int = 0


class _Provider(BaseProvider):
    supports_direct_fetch = False

    def __init__(
        self,
        name: str,
        recorder: _Recorder,
        *,
        direct_error: str | None = None,
        supports_direct: bool = False,
        timezone_id: str = "UTC",
    ) -> None:
        super().__init__(timezone_id=timezone_id)
        self._name = name
        self._recorder = recorder
        self.supports_direct_fetch = supports_direct
        self._direct_error = direct_error

    @property
    def name(self) -> str:
        return self._name

    def fetch_direct(self, config: Config) -> UsageData:
        self._recorder.direct.append(self.name)
        if self._direct_error:
            return _usage(self.name, error=self._direct_error)
        return _usage(self.name)

    def fetch(self, context: BrowserContext) -> UsageData:
        self._recorder.browser.append(self.name)
        return _usage(self.name)


class _FakeManagedBrowser:
    def __init__(self, *args: Any, recorder: _Recorder, **kwargs: Any) -> None:
        self._recorder = recorder

    def __enter__(self) -> _FakeManagedBrowser:
        self._recorder.launches += 1
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get_context(self) -> object:
        return object()


def _usage(provider: str, *, error: str | None = None) -> UsageData:
    return UsageData(
        provider=provider,
        window_5h_percent=0.0 if error else 10.0,
        window_7d_percent=0.0 if error else 20.0,
        error=error,
    )


def _run_poll(
    monkeypatch: pytest.MonkeyPatch,
    names: list[str],
    providers: dict[str, _Provider],
    recorder: _Recorder,
    *,
    fallback: bool = False,
) -> list[dict[str, object]]:
    def fake_get_enabled_providers(
        provider_names: list[str], *, timezone_id: str = "UTC"
    ) -> list[_Provider]:
        assert provider_names == names
        return [providers[name] for name in provider_names]

    def fake_browser(*args: Any, **kwargs: Any) -> _FakeManagedBrowser:
        return _FakeManagedBrowser(*args, recorder=recorder, **kwargs)

    monkeypatch.setattr("poller.providers.get_enabled_providers", fake_get_enabled_providers)
    monkeypatch.setattr("poller.main.ManagedBrowser", fake_browser)
    monkeypatch.setattr("poller.main._get_browser_data_dir", lambda _: _ExistingPath())
    monkeypatch.setattr("poller.main.time.sleep", lambda _: None)

    return _poll(names, Config(direct_fetch_browser_fallback=fallback))


class _ExistingPath:
    def exists(self) -> bool:
        return True


def test_poll_partition_all_direct_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    providers = {
        "kimi": _Provider("kimi", recorder, supports_direct=True),
        "minimax": _Provider("minimax", recorder, supports_direct=True),
    }

    results = _run_poll(monkeypatch, ["kimi", "minimax"], providers, recorder)

    assert [r["provider"] for r in results] == ["kimi", "minimax"]
    assert recorder.direct == ["kimi", "minimax"]
    assert recorder.browser == []
    assert recorder.launches == 0


def test_poll_partition_all_browser_launches_once(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    providers = {
        "codex": _Provider("codex", recorder),
        "claude": _Provider("claude", recorder),
    }

    results = _run_poll(monkeypatch, ["codex", "claude"], providers, recorder)

    assert [r["provider"] for r in results] == ["codex", "claude"]
    assert recorder.direct == []
    assert recorder.browser == ["codex", "claude"]
    assert recorder.launches == 1


def test_poll_partition_mixed_browser_and_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    providers = {
        "codex": _Provider("codex", recorder),
        "kimi": _Provider("kimi", recorder, supports_direct=True),
    }

    results = _run_poll(monkeypatch, ["codex", "kimi"], providers, recorder)

    assert [r["provider"] for r in results] == ["codex", "kimi"]
    assert recorder.direct == ["kimi"]
    assert recorder.browser == ["codex"]
    assert recorder.launches == 1


def test_poll_partition_missing_credentials_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    providers = {
        "kimi": _Provider("kimi", recorder, direct_error="missing kimi", supports_direct=True),
        "minimax": _Provider(
            "minimax", recorder, direct_error="missing minimax", supports_direct=True
        ),
    }

    results = _run_poll(monkeypatch, ["kimi", "minimax"], providers, recorder)

    assert [r["provider"] for r in results] == ["kimi", "minimax"]
    assert [r["error"] for r in results] == ["missing kimi", "missing minimax"]
    assert recorder.direct == ["kimi", "minimax"]
    assert recorder.browser == []
    assert recorder.launches == 0


def test_poll_partition_fallback_enabled_retries_failed_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    providers = {
        "kimi": _Provider("kimi", recorder, direct_error="api failed", supports_direct=True),
    }

    results = _run_poll(monkeypatch, ["kimi"], providers, recorder, fallback=True)

    assert [r["provider"] for r in results] == ["kimi"]
    assert results[0]["error"] is None
    assert recorder.direct == ["kimi"]
    assert recorder.browser == ["kimi"]
    assert recorder.launches == 1


def test_poll_partition_provider_ordering_matches_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    providers = {
        "minimax": _Provider("minimax", recorder, supports_direct=True),
        "codex": _Provider("codex", recorder),
        "kimi": _Provider("kimi", recorder, supports_direct=True),
    }

    results = _run_poll(monkeypatch, ["minimax", "codex", "kimi"], providers, recorder)

    assert [r["provider"] for r in results] == ["minimax", "codex", "kimi"]
    assert recorder.direct == ["minimax", "kimi"]
    assert recorder.browser == ["codex"]
    assert recorder.launches == 1

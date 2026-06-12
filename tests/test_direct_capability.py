"""Tests for the Wave 1 direct-fetch protocol foundation.

These tests verify:
* ``DirectFetchProvider`` is a usable ``@runtime_checkable`` Protocol.
* Existing browser-based providers (Codex, Claude) are NOT direct
  providers — they keep their Playwright path.
* Kimi and MiniMax providers are CAPABLE of implementing direct fetch
  (a stub class with the protocol is recognised).
* Capability detection via ``isinstance`` does NOT launch Playwright.
* ``Config`` env-first credential resolution and ``redacted()`` work.
* ``BaseProvider.fetch`` signature is unchanged.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from playwright.sync_api import BrowserContext

from poller.config import Config
from poller.providers.base import BaseProvider, UsageData
from poller.providers.claude import ClaudeProvider
from poller.providers.codex import CodexProvider
from poller.providers.direct import DirectFetchProvider
from poller.providers.kimi import KimiProvider
from poller.providers.minimax import MiniMaxProvider


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------

def test_direct_provider_protocol_is_runtime_checkable() -> None:
    """The Protocol must support isinstance() checks at runtime."""
    assert hasattr(DirectFetchProvider, "_is_runtime_protocol")
    # Sanity: a bare object lacking both members must NOT satisfy it.
    assert not isinstance(object(), DirectFetchProvider)


def test_direct_provider_required_members() -> None:
    """The protocol must declare exactly the documented members."""
    required = {"supports_direct_fetch", "fetch_direct"}
    members = set(getattr(DirectFetchProvider, "__protocol_attrs__", ()))
    assert required.issubset(members)
    extra = members - required
    assert not extra, f"unexpected protocol members: {extra}"


# ---------------------------------------------------------------------------
# Base provider fetch signature must be unchanged
# ---------------------------------------------------------------------------

def test_base_provider_fetch_signature_unchanged() -> None:
    """The Wave 1 work must not change BaseProvider.fetch(context)."""
    import inspect

    sig = inspect.signature(BaseProvider.fetch)
    params = list(sig.parameters)
    assert params[0] == "self"
    assert params[1] == "context"
    # No extra parameters and the return annotation is UsageData.
    assert sig.return_annotation is UsageData
    # BaseProvider is still abstract — cannot be instantiated directly.
    with pytest.raises(TypeError):
        BaseProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Browser-based providers are NOT direct
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "provider_cls",
    [CodexProvider, ClaudeProvider],
)
def test_browser_providers_are_not_direct(provider_cls) -> None:
    """Codex and Claude have no API path — they must not satisfy the protocol."""
    provider = provider_cls()
    assert not isinstance(provider, DirectFetchProvider)


@pytest.mark.parametrize(
    "provider_cls",
    [KimiProvider, MiniMaxProvider],
)
def test_kimi_minimax_currently_browser_only(provider_cls) -> None:
    """Kimi and MiniMax are still browser-based in Wave 1; they don't
    implement the protocol yet, but their class shape is compatible
    (see stub test below) so a later task can add the direct path
    without touching this foundation."""
    provider = provider_cls()
    assert not isinstance(provider, DirectFetchProvider)


# ---------------------------------------------------------------------------
# Kimi / MiniMax CAN implement direct (stub demonstrates compatibility)
# ---------------------------------------------------------------------------

class _StubDirectProvider(BaseProvider):
    """A minimal provider that DOES implement ``DirectFetchProvider``."""

    supports_direct_fetch: bool = True

    @property
    def name(self) -> str:
        return "stub-direct"

    def fetch(self, context: BrowserContext) -> UsageData:  # pragma: no cover
        raise NotImplementedError

    def fetch_direct(self, config: Config) -> UsageData:
        return UsageData(
            provider=self.name,
            window_5h_percent=0.0,
            window_7d_percent=0.0,
            fetched_at=datetime.now(timezone.utc),
        )


class _StubKimiDirectProvider(KimiProvider):
    """Shows that KimiProvider's shape is compatible with the protocol —
    adding ``fetch_direct`` + ``supports_direct_fetch`` is sufficient."""

    supports_direct_fetch: bool = True

    def fetch_direct(self, config: Config) -> UsageData:
        return UsageData(
            provider=self.name,
            window_5h_percent=10.0,
            window_7d_percent=20.0,
        )


class _StubMiniMaxDirectProvider(MiniMaxProvider):
    """Shows that MiniMaxProvider's shape is compatible with the protocol."""

    supports_direct_fetch: bool = True

    def fetch_direct(self, config: Config) -> UsageData:
        return UsageData(
            provider=self.name,
            window_5h_percent=30.0,
            window_7d_percent=40.0,
        )


def test_stub_direct_provider_satisfies_protocol() -> None:
    provider = _StubDirectProvider()
    assert isinstance(provider, DirectFetchProvider)
    assert provider.supports_direct_fetch is True

    cfg = Config()
    data = provider.fetch_direct(cfg)
    assert isinstance(data, UsageData)
    assert data.provider == "stub-direct"


def test_kimi_can_implement_direct() -> None:
    """A subclass of KimiProvider that adds the protocol members is direct-capable."""
    provider = _StubKimiDirectProvider()
    assert isinstance(provider, DirectFetchProvider)
    cfg = Config()
    data = provider.fetch_direct(cfg)
    assert data.provider == "kimi"
    assert data.window_5h_percent == 10.0


def test_minimax_can_implement_direct() -> None:
    """A subclass of MiniMaxProvider that adds the protocol members is direct-capable."""
    provider = _StubMiniMaxDirectProvider()
    assert isinstance(provider, DirectFetchProvider)
    cfg = Config()
    data = provider.fetch_direct(cfg)
    assert data.provider == "minimax"
    assert data.window_7d_percent == 40.0


def test_provider_with_supports_false_is_still_protocol_member() -> None:
    """A class declaring ``supports_direct_fetch = False`` still has the
    attribute, so it satisfies the protocol structurally. The boolean
    is the runtime capability gate, not a Protocol-membership gate.
    """

    class _AlwaysDisabled(BaseProvider):
        supports_direct_fetch: bool = False

        @property
        def name(self) -> str:
            return "disabled"

        def fetch(self, context: BrowserContext) -> UsageData:  # pragma: no cover
            raise NotImplementedError

        def fetch_direct(self, config: Config) -> UsageData:  # pragma: no cover
            raise NotImplementedError

    provider = _AlwaysDisabled()
    assert isinstance(provider, DirectFetchProvider)
    assert provider.supports_direct_fetch is False


# ---------------------------------------------------------------------------
# No Playwright launch for capability detection
# ---------------------------------------------------------------------------

def test_capability_check_does_not_launch_browser() -> None:
    """``isinstance(provider, DirectFetchProvider)`` is a structural check.
    It must not touch Playwright / BrowserContext / ManagedBrowser.
    """
    with (
        patch("poller.browser.ManagedBrowser") as browser_mock,
        patch("poller.providers.base.BrowserContext") as ctx_mock,
    ):
        # Both browser-based and direct providers must be constructible
        # and checkable without any browser launch.
        for cls in (
            CodexProvider,
            ClaudeProvider,
            KimiProvider,
            MiniMaxProvider,
            _StubDirectProvider,
        ):
            provider = cls()
            assert isinstance(provider, DirectFetchProvider) is False or isinstance(
                provider, DirectFetchProvider
            )

        browser_mock.assert_not_called()
        ctx_mock.assert_not_called()


def test_capability_check_is_pure_attribute_lookup() -> None:
    """The runtime check must succeed even when fetch_direct raises —
    i.e. it must not call the method, only look it up."""
    called = {"flag": False}

    class _RaisingProvider(BaseProvider):
        supports_direct_fetch: bool = True

        @property
        def name(self) -> str:
            return "raising"

        def fetch(self, context: BrowserContext) -> UsageData:  # pragma: no cover
            raise NotImplementedError

        def fetch_direct(self, config: Config) -> UsageData:
            called["flag"] = True
            raise RuntimeError("must not be invoked by isinstance check")

    assert isinstance(_RaisingProvider(), DirectFetchProvider)
    assert called["flag"] is False, "isinstance must not call fetch_direct"


# ---------------------------------------------------------------------------
# Config: env-first credentials + redaction
# ---------------------------------------------------------------------------

def test_config_has_direct_fetch_browser_fallback_field() -> None:
    cfg = Config()
    assert cfg.direct_fetch_browser_fallback is False


def test_config_loads_direct_fetch_browser_fallback_from_general() -> None:
    """``direct_fetch_browser_fallback`` lives under ``[general]`` in TOML."""
    from poller.config import load_config

    with patch("poller.config.CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = (
            "[general]\n"
            "interval = 300\n"
            "direct_fetch_browser_fallback = true\n"
        )
        cfg = load_config()
    assert cfg.direct_fetch_browser_fallback is True


def test_config_kimi_credential_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_CODE_ACCESS_TOKEN", "env-token-123")
    monkeypatch.delenv("KIMI_CODE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("KIMI_CODE_ACCESS_TOKEN", "env-token-123")

    cfg = Config()
    assert cfg.kimi_code_access_token == "env-token-123"


def test_config_minimax_credential_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "env-key-abc")
    cfg = Config()
    assert cfg.minimax_api_key == "env-key-abc"

    monkeypatch.setenv("MINIMAX_API_BASE_URL", "https://example.test/api")
    cfg2 = Config()
    assert cfg2.minimax_api_base_url == "https://example.test/api"


def test_config_credential_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the field is supplied explicitly (e.g. via TOML or init kwargs),
    it must NOT be replaced by an environment variable."""
    monkeypatch.setenv("KIMI_CODE_ACCESS_TOKEN", "env-token-xyz")
    cfg = Config(kimi_code_access_token="explicit-token")
    assert cfg.kimi_code_access_token == "explicit-token"


def test_config_redacted_masks_secrets() -> None:
    cfg = Config(
        kimi_code_access_token="super-secret-kimi",
        minimax_api_key="super-secret-minimax",
        minimax_api_base_url="https://api.minimaxi.com",
    )
    redacted = cfg.redacted_dict()
    assert redacted["kimi_code_access_token"] == "***REDACTED***"
    assert redacted["minimax_api_key"] == "***REDACTED***"
    # Non-secret fields pass through.
    assert redacted["minimax_api_base_url"] == "https://api.minimaxi.com"
    # The redacted_dict must not leak the original secrets at all.
    dumped = str(redacted)
    assert "super-secret-kimi" not in dumped
    assert "super-secret-minimax" not in dumped


def test_config_redacted_json_safe_for_console() -> None:
    """``redacted_json`` is what ``--show-config`` prints — secrets must
    never appear in the output, even when credentials are loaded from
    the environment."""
    os.environ["KIMI_CODE_ACCESS_TOKEN"] = "do-not-leak-me"
    os.environ["MINIMAX_API_KEY"] = "do-not-leak-me-either"
    try:
        cfg = Config()
        out = cfg.redacted_json(indent=2)
        assert "do-not-leak-me" not in out
        assert "do-not-leak-me-either" not in out
        assert "***REDACTED***" in out
    finally:
        os.environ.pop("KIMI_CODE_ACCESS_TOKEN", None)
        os.environ.pop("MINIMAX_API_KEY", None)


def test_config_empty_credentials_not_redacted() -> None:
    """When credentials are empty, redacted_dict() leaves them as empty
    strings — masking an empty value would be misleading."""
    cfg = Config()
    redacted = cfg.redacted_dict()
    assert redacted["kimi_code_access_token"] == ""
    assert redacted["minimax_api_key"] == ""

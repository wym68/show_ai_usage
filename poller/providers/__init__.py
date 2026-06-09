"""Provider registry — discovers and instantiates available providers."""

from collections.abc import Sequence

from poller.providers.base import BaseProvider

# Registry of all known providers (lazy-imported below)
_registry: dict[str, type[BaseProvider]] | None = None


def _get_registry() -> dict[str, type[BaseProvider]]:
    global _registry
    if _registry is None:
        from poller.providers.claude import ClaudeProvider
        from poller.providers.codex import CodexProvider
        from poller.providers.kimi import KimiProvider
        from poller.providers.minimax import MiniMaxProvider

        _registry = {
            "codex": CodexProvider,
            "claude": ClaudeProvider,
            "kimi": KimiProvider,
            "minimax": MiniMaxProvider,
        }
    return _registry


def get_enabled_providers(
    names: Sequence[str] | None = None,
    timezone_id: str = "UTC",
) -> list[BaseProvider]:
    """Return a list of provider instances.

    If *names* is given, only those providers (by ID) are returned.
    Otherwise **all** registered providers are returned.
    """
    reg = _get_registry()

    if names:
        selected = {n.lower(): n for n in names}
        return [reg[name](timezone_id=timezone_id) for name in selected if name in reg]

    return [cls(timezone_id=timezone_id) for cls in reg.values()]


def list_available_providers() -> list[str]:
    """Return the IDs of all registered providers."""
    return sorted(_get_registry().keys())

"""Protocol for providers that can fetch usage data without a browser.

Some providers (Kimi, MiniMax) expose usage data via a direct HTTP API.
Providers that implement :class:`DirectFetchProvider` can skip the
Playwright launch entirely and return a :class:`UsageData` from
:meth:`fetch_direct`, which is faster, lighter, and immune to
Cloudflare-style challenges.

Capability detection uses :func:`isinstance` against this
``@runtime_checkable`` protocol, so it does **not** launch a browser
— it just checks for the presence of the expected attributes
(``supports_direct_fetch`` and ``fetch_direct``).
"""

from typing import Protocol, runtime_checkable

from poller.config import Config
from poller.providers.base import UsageData


@runtime_checkable
class DirectFetchProvider(Protocol):
    """Capability protocol for direct (non-browser) usage fetchers.

    A provider class that wants to be usable via the direct-API path
    must expose:

    * ``supports_direct_fetch: bool`` — a class/instance attribute that
      signals whether the provider is currently configured for the
      direct path (e.g. credentials are present).
    * ``fetch_direct(config: Config) -> UsageData`` — perform the
      fetch and return a populated :class:`UsageData`.
    """

    supports_direct_fetch: bool

    def fetch_direct(self, config: Config) -> UsageData:
        """Fetch usage data via the provider's direct API.

        Parameters
            config: The merged :class:`Config` instance. Implementations
                read whichever credential fields they need from it.

        Returns
            UsageData: structured usage information matching the
            standard provider contract.
        """
        ...

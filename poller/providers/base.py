"""Abstract base for all AI subscription usage providers."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from playwright.sync_api import BrowserContext
from pydantic import BaseModel, Field


class UsageData(BaseModel):
    """Normalised usage data returned by every provider."""

    provider: str = Field(description="Provider identifier, e.g. 'codex', 'claude'")
    window_5h_percent: float = Field(
        ge=0.0, le=100.0, description="Usage in the 5-hour rolling window (0–100)."
    )
    window_7d_percent: float = Field(
        ge=0.0, le=100.0, description="Usage in the 7-day rolling window (0–100)."
    )
    reset_5h: str | None = Field(
        default=None, description="5-hour window reset time, e.g. '4h 12m' or '9:25'."
    )
    reset_7d: str | None = Field(
        default=None, description="7-day / weekly window reset time, e.g. '2026年6月12日 21:14'."
    )
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this data was fetched.",
    )
    error: str | None = Field(
        default=None, description="Error message if the fetch failed."
    )


class BaseProvider(ABC):
    """Abstract base class for an AI subscription usage provider.

    Subclasses must implement :meth:`fetch` which uses the supplied Playwright
    ``BrowserContext`` to navigate the provider's usage dashboard and scrape
    the current data, returning a :class:`UsageData` instance.

    The ``BrowserContext`` is pre-configured with the project's isolated
    browser profile, so login state is already available.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in the registry and CLI (e.g. ``"codex"``)."""

    @abstractmethod
    def fetch(self, context: BrowserContext) -> UsageData:
        """Navigate to the provider's usage dashboard and scrape current data.

        Parameters
            context: A Playwright ``BrowserContext`` with the project's
                persistent browser profile (already logged in).

        Returns
            UsageData: structured usage information.

        Raises
            RuntimeError: If the page could not be reached, the user is not
                logged in, or the expected data fields are not found.
        """

"""Abstract base for all AI subscription usage providers."""

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import BrowserContext
from pydantic import BaseModel, Field


def _parse_chinese_duration(text: str) -> tuple[int, int, int]:
    """Parse Chinese duration strings like '4 天 18 小时后重置'."""
    days = 0
    hours = 0
    minutes = 0

    # Days
    m = re.search(r'(\d+)\s*天', text)
    if m:
        days = int(m.group(1))

    # Hours
    m = re.search(r'(\d+)\s*小时?', text)
    if m:
        hours = int(m.group(1))

    # Minutes
    m = re.search(r'(\d+)\s*分钟?', text)
    if m:
        minutes = int(m.group(1))

    return days, hours, minutes


def _parse_english_duration(text: str) -> tuple[int, int, int]:
    """Parse English duration strings like '4 hr 34 min'."""
    days = 0
    hours = 0
    minutes = 0

    m = re.search(r'(\d+)\s*(?:hr|hour|hours)', text, re.I)
    if m:
        hours = int(m.group(1))

    m = re.search(r'(\d+)\s*(?:min|minute|minutes)', text, re.I)
    if m:
        minutes = int(m.group(1))

    return days, hours, minutes


def _parse_absolute_time(
    text: str, provider: str, timezone_id: str = "UTC"
) -> tuple[int, int, int] | None:
    """Parse absolute times and compute delta to now.

    Page-rendered absolute times are in the browser's local timezone,
    so we parse them with the configured/system timezone and compare
    against the current moment in that same timezone.
    """
    try:
        tz = ZoneInfo(timezone_id)
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    target: datetime | None = None

    # Codex: "2026年6月10日 4:40"
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(\d{1,2}):(\d{2})', text)
    if m:
        year, month, day, hour, minute = map(int, m.groups())
        target = datetime(year, month, day, hour, minute, tzinfo=tz)

    # ISO 8601 (e.g., Kimi resetAt: "2026-06-15T00:00:00Z")
    if target is None:
        m = re.search(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?',
            text,
        )
        if m:
            try:
                target = datetime.fromisoformat(m.group(0))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=tz)
                else:
                    target = target.astimezone(tz)
            except ValueError:
                target = None

    if target is None and provider == 'codex':
        m = re.search(r'\b(\d{1,2}):(\d{2})\b', text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)

    # Claude 7d: "Mon 11:00 PM" — next occurrence of that weekday/time
    if target is None:
        m = re.search(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}):(\d{2})\s*(AM|PM)', text, re.I)
        if m:
            weekday_map = {
                'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
                'fri': 4, 'sat': 5, 'sun': 6,
            }
            target_wd = weekday_map[m.group(1).lower()]
            hour = int(m.group(2))
            minute = int(m.group(3))
            ampm = m.group(4).upper()
            if ampm == 'PM' and hour != 12:
                hour += 12
            elif ampm == 'AM' and hour == 12:
                hour = 0

            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = target_wd - target.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target += timedelta(days=days_ahead)

    if target is None:
        return None

    delta = target - now
    if delta.total_seconds() < 0:
        return None

    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    return days, hours, minutes


def format_reset_time(
    reset_str: str | None, provider: str = '', timezone_id: str = "UTC"
) -> str | None:
    """统一重置时间格式为 'X天Y小时Z分后重置'.

    支持的输入格式：
    - 中文相对时间：'4 天 18 小时后重置'、'3 小时后重置'
    - 英文相对时间：'4 hr 34 min'
    - 绝对时间：'2026年6月10日 4:40'（Codex）、'Mon 11:00 PM'（Claude 7d）

    *timezone_id* 用于解析页面上的绝对时间（页面按浏览器本地时区渲染）。
    """
    if not reset_str:
        return None

    if 'starts when a message is sent' in reset_str.lower():
        return '未开始计时'

    result: tuple[int, int, int] | None = None

    # 1. 已经是中文相对时间格式
    if '后重置' in reset_str or '后到期' in reset_str:
        result = _parse_chinese_duration(reset_str)

    # 2. 英文相对时间
    elif re.search(r'\d+\s*(?:hr|hour|hours|min|minute|minutes)', reset_str, re.I):
        result = _parse_english_duration(reset_str)

    # 3. 绝对时间
    else:
        result = _parse_absolute_time(reset_str, provider, timezone_id)

    if result is None:
        return reset_str  # 无法解析，返回原始值

    days, hours, minutes = result

    # 将大于24小时的小时转换为天
    if hours >= 24:
        days += hours // 24
        hours = hours % 24

    parts: list[str] = []
    if days > 0:
        parts.append(f'{days}天')
    if hours > 0:
        parts.append(f'{hours}小时')
    if minutes > 0:
        parts.append(f'{minutes}分')

    if not parts:
        return '即将重置'

    return ''.join(parts) + '后重置'


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

    def __init__(self, timezone_id: str = "UTC") -> None:
        self.timezone_id: str = timezone_id

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

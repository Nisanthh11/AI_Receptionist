"""All datetimes in the database are *naive* and expressed in the organisation timezone (TIMEZONE)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def org_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_local() -> datetime:
    return datetime.now(org_tz()).replace(tzinfo=None)


def to_local_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(org_tz()).replace(tzinfo=None)

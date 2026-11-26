"""Clock helpers. Display times are Europe/Kyiv (legacy name Europe/Kiev)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # pragma: no cover - older tzdata alias
    KYIV = ZoneInfo("Europe/Kiev")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_kyiv(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KYIV)


def format_kyiv(moment: datetime, fmt: str = "%H:%M") -> str:
    return to_kyiv(moment).strftime(fmt)


def is_night(moment: datetime, start_hour: int = 0, end_hour: int = 8) -> bool:
    """Night window is [start_hour, end_hour) in Kyiv. Default 00:00–08:00."""
    hour = to_kyiv(moment).hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def parse_unix(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if not text[:1].isdigit() or "-" in text[:11]:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num > 1e12:
        num = num / 1000.0
    try:
        return datetime.fromtimestamp(num, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None

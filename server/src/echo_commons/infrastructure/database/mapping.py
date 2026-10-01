from __future__ import annotations

from datetime import UTC, datetime


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def utc_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Stored datetime must have a timezone")
    return result.astimezone(UTC)

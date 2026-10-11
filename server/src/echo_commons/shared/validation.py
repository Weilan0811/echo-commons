from __future__ import annotations

from datetime import UTC, datetime


class DomainInvariantError(ValueError):
    """Raised when a domain object or state transition violates its contract."""


class TimeOrderError(DomainInvariantError):
    pass


def require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainInvariantError(f"{field_name} must be a non-empty string")
    return value


def require_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    return require_utc(value, field_name) if value is not None else None


def require_sequence(value: int, field_name: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise DomainInvariantError(f"{field_name} must be an integer >= {minimum}")
    return value

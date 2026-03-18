"""Shared utilities for time parsing, ID resolution, and formatting."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any


def parse_duration(duration_str: str) -> timedelta:
    """Parse a human-readable duration string into a timedelta.

    Supports: "30s", "5m", "1h", "7d", "2w", and combinations like "1h30m".

    Args:
        duration_str: Duration string (e.g., "1h", "30m", "7d").

    Returns:
        timedelta object.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    pattern = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
    matches = pattern.findall(duration_str)
    if not matches:
        raise ValueError(f"Cannot parse duration: {duration_str!r}. Use format like '1h', '30m', '7d'.")

    total = timedelta()
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    for value, unit in matches:
        total += timedelta(**{units[unit.lower()]: int(value)})
    return total


def resolve_time_range(
    last: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve time range parameters into absolute start/end datetimes.

    Args:
        last: Relative duration from now (e.g., "1h", "7d").
        start: Absolute start time (ISO string or datetime).
        end: Absolute end time (ISO string or datetime). Defaults to now.

    Returns:
        Tuple of (start, end) as UTC datetimes.

    Raises:
        ValueError: If neither `last` nor `start` is provided.
    """
    now = datetime.now(timezone.utc)

    if last is not None:
        delta = parse_duration(last)
        return now - delta, now

    if start is None:
        raise ValueError("Either 'last' or 'start' must be provided.")

    start_dt = _parse_datetime(start) if isinstance(start, str) else start
    end_dt = _parse_datetime(end) if isinstance(end, str) else (end or now)
    return start_dt, end_dt


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO-format datetime string, with fallback for date-only."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Cannot parse datetime: {value!r}. Use ISO format (e.g., '2026-03-17T10:00:00').")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_id(obj: Any) -> str:
    """Extract an ID string from an object, wrapper, or raw string.

    Accepts:
        - A string (returned as-is)
        - An object with an `id` attribute
        - An object with a `_raw` attribute that has `id`
    """
    if isinstance(obj, str):
        return obj
    if hasattr(obj, "id"):
        return obj.id
    if hasattr(obj, "_raw") and hasattr(obj._raw, "id"):
        return obj._raw.id
    raise TypeError(f"Cannot extract ID from {type(obj).__name__}: {obj!r}")


def truncate_id(ulid: str, length: int = 8) -> str:
    """Truncate a ULID for display purposes."""
    if not ulid:
        return ""
    if len(ulid) <= length:
        return ulid
    return f"{ulid[:length]}..."

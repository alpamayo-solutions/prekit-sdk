"""Tests for helpers: time parsing, ID resolution, formatting."""

from datetime import datetime, timedelta, timezone

import pytest

from prekit_sdk.helpers import parse_duration, resolve_id, resolve_time_range, truncate_id


class TestParseDuration:
    def test_seconds(self):
        assert parse_duration("30s") == timedelta(seconds=30)

    def test_minutes(self):
        assert parse_duration("5m") == timedelta(minutes=5)

    def test_hours(self):
        assert parse_duration("1h") == timedelta(hours=1)

    def test_days(self):
        assert parse_duration("7d") == timedelta(days=7)

    def test_weeks(self):
        assert parse_duration("2w") == timedelta(weeks=2)

    def test_combined(self):
        assert parse_duration("1h30m") == timedelta(hours=1, minutes=30)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse duration"):
            parse_duration("not-a-duration")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_duration("")


class TestResolveTimeRange:
    def test_last(self):
        start, end = resolve_time_range(last="1h")
        assert (end - start) == timedelta(hours=1)
        assert end.tzinfo is not None

    def test_start_end(self):
        start, end = resolve_time_range(start="2026-03-17", end="2026-03-18")
        assert start.day == 17
        assert end.day == 18

    def test_start_only(self):
        start, end = resolve_time_range(start="2026-03-17")
        assert start.day == 17
        assert end.tzinfo is not None  # defaults to now

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="Either 'last' or 'start'"):
            resolve_time_range()


class TestResolveId:
    def test_string_passthrough(self):
        assert resolve_id("abc123") == "abc123"

    def test_object_with_id(self):
        class Obj:
            id = "obj-id"

        assert resolve_id(Obj()) == "obj-id"

    def test_wrapper_with_raw(self):
        class Raw:
            id = "raw-id"

        class Wrapper:
            _raw = Raw()

        assert resolve_id(Wrapper()) == "raw-id"

    def test_invalid_raises(self):
        with pytest.raises(TypeError, match="Cannot extract ID"):
            resolve_id(42)


class TestTruncateId:
    def test_normal(self):
        assert truncate_id("01JABCDEF123456789012345") == "01JABCDE..."

    def test_short(self):
        assert truncate_id("abc") == "abc"

    def test_empty(self):
        assert truncate_id("") == ""

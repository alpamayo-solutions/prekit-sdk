"""Tests for historian DataFrame construction."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from prekit_sdk.historian import _metrics_to_dataframe, fetch_signal_data


class FakeMetric:
    def __init__(self, timestamp, value):
        self.timestamp = timestamp
        self.value = value


class TestMetricsToDataframe:
    def test_basic_conversion(self):
        metrics = [
            FakeMetric("2026-03-17T10:00:00Z", 23.5),
            FakeMetric("2026-03-17T10:01:00Z", 24.0),
            FakeMetric("2026-03-17T10:02:00Z", 23.8),
        ]
        df = _metrics_to_dataframe(metrics)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert list(df.columns) == ["timestamp", "value"]
        assert df["value"].iloc[0] == 23.5

    def test_empty_input(self):
        df = _metrics_to_dataframe([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "timestamp" in df.columns
        assert "value" in df.columns

    def test_none_input(self):
        df = _metrics_to_dataframe(None)
        assert len(df) == 0

    def test_paginated_response(self):
        class PaginatedResponse:
            objects = [
                FakeMetric("2026-03-17T10:00:00Z", 1.0),
                FakeMetric("2026-03-17T10:01:00Z", 2.0),
            ]

        df = _metrics_to_dataframe(PaginatedResponse())
        assert len(df) == 2

    def test_sorted_by_timestamp(self):
        metrics = [
            FakeMetric("2026-03-17T10:02:00Z", 3.0),
            FakeMetric("2026-03-17T10:00:00Z", 1.0),
            FakeMetric("2026-03-17T10:01:00Z", 2.0),
        ]
        df = _metrics_to_dataframe(metrics)
        assert df["value"].tolist() == [1.0, 2.0, 3.0]

    def test_timestamps_are_utc(self):
        metrics = [FakeMetric("2026-03-17T10:00:00Z", 1.0)]
        df = _metrics_to_dataframe(metrics)
        assert df["timestamp"].dt.tz is not None

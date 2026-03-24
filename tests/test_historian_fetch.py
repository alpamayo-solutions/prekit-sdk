"""Tests for historian fetch functions: fetch_signal_data, fetch_element_data,
fetch_multi_signal_data, and fetch_latest."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from prekit_sdk.historian import (
    fetch_element_data,
    fetch_latest,
    fetch_multi_signal_data,
    fetch_signal_data,
)
from prekit_sdk.models import Signal
from tests.factories import make_metric, make_signal


class FakeMetric:
    """Metric-like object with `timestamp` attribute (matches _metrics_to_dataframe expectations)."""

    def __init__(self, timestamp, value):
        self.timestamp = timestamp
        self.value = value


def _make_fake_metrics(n: int = 3, base_value: float = 10.0) -> list[FakeMetric]:
    """Build a list of FakeMetric objects with sequential timestamps."""
    return [
        FakeMetric(f"2026-03-17T10:{i:02d}:00Z", base_value + i)
        for i in range(n)
    ]


def _patch_prekit():
    """Patch prekit_edge_node_api at the sys.modules level (it's lazy-imported inside functions)."""
    return patch.dict("sys.modules", {"prekit_edge_node_api": MagicMock()})


class TestFetchSignalData:
    def test_primary_path_returns_dataframe(self):
        mock_prekit = MagicMock()
        metrics = _make_fake_metrics(3)

        mock_metric_api = MagicMock()
        mock_metric_api.get_all.return_value = metrics
        mock_prekit.MetricApi.return_value = mock_metric_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            df = fetch_signal_data(client, "01SIG0000000000000000001", last="1h")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert list(df.columns) == ["timestamp", "value"]
        assert df["value"].iloc[0] == 10.0
        mock_metric_api.get_all.assert_called_once()

    def test_fallback_to_get_signal_data_api(self):
        mock_prekit = MagicMock()

        # Primary API raises
        mock_metric_api = MagicMock()
        mock_metric_api.get_all.side_effect = Exception("MetricApi unavailable")
        mock_prekit.MetricApi.return_value = mock_metric_api

        # Fallback API succeeds
        fallback_metrics = _make_fake_metrics(2, base_value=20.0)
        mock_fallback_api = MagicMock()
        mock_fallback_api.get_one.return_value = fallback_metrics
        mock_prekit.GetSignalDataApi.return_value = mock_fallback_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            df = fetch_signal_data(client, "01SIG0000000000000000001", last="1h")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert df["value"].iloc[0] == 20.0
        mock_fallback_api.get_one.assert_called_once()

    def test_both_fail_returns_empty(self):
        mock_prekit = MagicMock()

        mock_metric_api = MagicMock()
        mock_metric_api.get_all.side_effect = Exception("MetricApi down")
        mock_prekit.MetricApi.return_value = mock_metric_api

        mock_fallback_api = MagicMock()
        mock_fallback_api.get_one.side_effect = Exception("GetSignalDataApi down")
        mock_prekit.GetSignalDataApi.return_value = mock_fallback_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            df = fetch_signal_data(client, "01SIG0000000000000000001", last="1h")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["timestamp", "value"]

    def test_resolves_signal_id_from_wrapper(self):
        mock_prekit = MagicMock()

        raw_signal = make_signal(name="Temperature", id="01SIG_RESOLVED0000000000")
        signal_wrapper = Signal(raw_signal, MagicMock())

        metrics = _make_fake_metrics(1)
        mock_metric_api = MagicMock()
        mock_metric_api.get_all.return_value = metrics
        mock_prekit.MetricApi.return_value = mock_metric_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            df = fetch_signal_data(client, signal_wrapper, last="1h")

        assert len(df) == 1
        # Verify the signal ID was resolved from the wrapper
        call_kwargs = mock_metric_api.get_all.call_args
        assert call_kwargs.kwargs["select_signals"] == ["01SIG_RESOLVED0000000000"]


class TestFetchElementData:
    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_merges_multiple_signals(self, mock_fetch_signal):
        sig_a = make_signal(name="Temperature", id="01SIG_A00000000000000000")
        sig_b = make_signal(name="Pressure", id="01SIG_B00000000000000000")

        sig_a_wrapper = Signal(sig_a, MagicMock())
        sig_b_wrapper = Signal(sig_b, MagicMock())

        df_a = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-03-17T10:00:00Z", "2026-03-17T10:01:00Z"], utc=True),
            "value": [23.5, 24.0],
        })
        df_b = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-03-17T10:00:00Z", "2026-03-17T10:01:00Z"], utc=True),
            "value": [1.5, 1.6],
        })

        mock_fetch_signal.side_effect = [df_a, df_b]

        client = MagicMock()
        client.signals.filter.return_value = [sig_a_wrapper, sig_b_wrapper]

        df = fetch_element_data(client, "01ELEM000000000000000000", last="1h")

        assert isinstance(df, pd.DataFrame)
        assert "timestamp" in df.columns
        assert "Temperature" in df.columns
        assert "Pressure" in df.columns
        assert len(df) == 2

    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_no_signals_returns_empty(self, mock_fetch_signal):
        client = MagicMock()
        client.signals.filter.return_value = []

        df = fetch_element_data(client, "01ELEM000000000000000000", last="1h")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        mock_fetch_signal.assert_not_called()

    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_single_signal(self, mock_fetch_signal):
        sig = make_signal(name="Vibration", id="01SIG_V00000000000000000")
        sig_wrapper = Signal(sig, MagicMock())

        df_single = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-03-17T10:00:00Z"], utc=True),
            "value": [3.14],
        })
        mock_fetch_signal.return_value = df_single

        client = MagicMock()
        client.signals.filter.return_value = [sig_wrapper]

        df = fetch_element_data(client, "01ELEM000000000000000000", last="1h")

        assert "Vibration" in df.columns
        assert len(df) == 1
        assert df["Vibration"].iloc[0] == 3.14


class TestFetchMultiSignalData:
    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_empty_signals_returns_empty(self, mock_fetch_signal):
        client = MagicMock()
        df = fetch_multi_signal_data(client, [], last="1h")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        mock_fetch_signal.assert_not_called()

    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_merges_by_timestamp(self, mock_fetch_signal):
        sig_a = make_signal(name="Temp", id="01SIG_MA0000000000000000")
        sig_b = make_signal(name="Humidity", id="01SIG_MB0000000000000000")

        sig_a_wrapper = Signal(sig_a, MagicMock())
        sig_b_wrapper = Signal(sig_b, MagicMock())

        ts = pd.to_datetime(["2026-03-17T10:00:00Z", "2026-03-17T10:01:00Z"], utc=True)
        df_a = pd.DataFrame({"timestamp": ts, "value": [22.0, 22.5]})
        df_b = pd.DataFrame({"timestamp": ts, "value": [55.0, 56.0]})

        mock_fetch_signal.side_effect = [df_a, df_b]

        client = MagicMock()
        df = fetch_multi_signal_data(client, [sig_a_wrapper, sig_b_wrapper], last="1h")

        assert "Temp" in df.columns
        assert "Humidity" in df.columns
        assert len(df) == 2
        assert df["Temp"].iloc[0] == 22.0
        assert df["Humidity"].iloc[1] == 56.0

    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_uses_signal_name_as_column(self, mock_fetch_signal):
        """Signal wrappers use .name; plain strings use str(sig)."""
        sig_wrapper = Signal(make_signal(name="SpindleSpeed"), MagicMock())

        ts = pd.to_datetime(["2026-03-17T10:00:00Z"], utc=True)
        df_named = pd.DataFrame({"timestamp": ts, "value": [1500.0]})

        mock_fetch_signal.return_value = df_named

        client = MagicMock()
        df = fetch_multi_signal_data(client, [sig_wrapper], last="1h")

        assert "SpindleSpeed" in df.columns

    @patch("prekit_sdk.historian.fetch_signal_data")
    def test_string_id_used_as_column(self, mock_fetch_signal):
        """When a plain string ID is passed, the column name is that string."""
        signal_id = "01SIG_RAW_ID0000000000000"

        ts = pd.to_datetime(["2026-03-17T10:00:00Z"], utc=True)
        df_raw = pd.DataFrame({"timestamp": ts, "value": [99.0]})
        mock_fetch_signal.return_value = df_raw

        client = MagicMock()
        df = fetch_multi_signal_data(client, [signal_id], last="1h")

        assert signal_id in df.columns


class TestFetchLatest:
    def test_dict_response(self):
        mock_prekit = MagicMock()
        signal_id = "01SIG0000000000000000001"
        entry = MagicMock()
        entry.value = 42.5
        entry.timestamp = "2026-03-17T10:00:00Z"

        mock_api = MagicMock()
        mock_api.get_one.return_value = {signal_id: entry}
        mock_prekit.GetLatestValuesApi.return_value = mock_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            result = fetch_latest(client, signal_id)

        assert result is not None
        assert result["value"] == 42.5
        assert result["timestamp"] == "2026-03-17T10:00:00Z"

    def test_list_response(self):
        mock_prekit = MagicMock()
        entry = MagicMock()
        entry.value = 37.0
        entry.timestamp = "2026-03-17T10:05:00Z"

        mock_api = MagicMock()
        mock_api.get_one.return_value = [entry]
        mock_prekit.GetLatestValuesApi.return_value = mock_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            result = fetch_latest(client, "01SIG0000000000000000001")

        assert result is not None
        assert result["value"] == 37.0
        assert result["timestamp"] == "2026-03-17T10:05:00Z"

    def test_exception_returns_none(self):
        mock_prekit = MagicMock()
        mock_api = MagicMock()
        mock_api.get_one.side_effect = Exception("API down")
        mock_prekit.GetLatestValuesApi.return_value = mock_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            result = fetch_latest(client, "01SIG0000000000000000001")

        assert result is None

    def test_empty_result_returns_none(self):
        mock_prekit = MagicMock()
        mock_api = MagicMock()
        mock_api.get_one.return_value = {}
        mock_prekit.GetLatestValuesApi.return_value = mock_api

        with patch.dict("sys.modules", {"prekit_edge_node_api": mock_prekit}):
            client = MagicMock()
            result = fetch_latest(client, "01SIG0000000000000000001")

        assert result is None

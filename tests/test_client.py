"""Tests for Prekit client methods: query, query_signals, get_latest, whoami, health."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from prekit_sdk.auth import AutoRefreshApiClient
from prekit_sdk.client import Prekit
from prekit_sdk.tree import TreeNode


def _make_client() -> Prekit:
    """Create a Prekit instance with a mocked API client."""
    mock_api = MagicMock(spec=AutoRefreshApiClient)
    mock_api.configuration = MagicMock()
    mock_api.configuration.host = "https://test.local"
    return Prekit(api=mock_api)


# ---------------------------------------------------------------------------
# TestPrekitQuery
# ---------------------------------------------------------------------------


class TestPrekitQuery:
    """Tests for Prekit.query() — SQL against the historian database."""

    @patch("prekit_sdk.client.prekit")
    def test_query_returns_dataframe(self, mock_prekit):
        client = _make_client()

        mock_response = MagicMock()
        mock_response.column_names = ["time", "value"]
        mock_response.rows = [["2026-01-01", "42"]]

        mock_api_instance = MagicMock()
        mock_api_instance.post_one.return_value = mock_response
        mock_prekit.QueryDatabaseApi.return_value = mock_api_instance

        df = client.query("SELECT time, value FROM metrics")

        assert isinstance(df, pd.DataFrame)
        assert df.shape == (1, 2)
        assert list(df.columns) == ["time", "value"]
        assert df.iloc[0]["time"] == "2026-01-01"
        assert df.iloc[0]["value"] == "42"

        mock_prekit.QueryDatabaseApi.assert_called_once_with(api_client=client.api)
        mock_api_instance.post_one.assert_called_once()

    @patch("prekit_sdk.client.prekit")
    def test_query_empty_result(self, mock_prekit):
        client = _make_client()

        mock_response = MagicMock()
        mock_response.column_names = ["time", "value"]
        mock_response.rows = []

        mock_api_instance = MagicMock()
        mock_api_instance.post_one.return_value = mock_response
        mock_prekit.QueryDatabaseApi.return_value = mock_api_instance

        df = client.query("SELECT time, value FROM metrics WHERE 1=0")

        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert list(df.columns) == ["time", "value"]


# ---------------------------------------------------------------------------
# TestPrekitQuerySignals
# ---------------------------------------------------------------------------


class TestPrekitQuerySignals:
    """Tests for Prekit.query_signals() — structured signal query with SQL."""

    @patch.object(Prekit, "query")
    def test_query_signals_builds_sql(self, mock_query):
        client = _make_client()

        mock_query.return_value = pd.DataFrame(
            {"time": ["2026-01-01"], "signal_name": ["temp"], "value": ["23.5"]}
        )

        client.query_signals(
            system_element="CNC-Mill",
            signal_names=["temp", "vibration"],
            start="2026-01-01 00:00",
            end="2026-01-02 00:00",
            bucket="5 minutes",
            agg="MAX",
        )

        mock_query.assert_called_once()
        sql = mock_query.call_args[0][0]

        assert "CNC-Mill" in sql
        assert "'temp'" in sql
        assert "'vibration'" in sql
        assert "2026-01-01 00:00" in sql
        assert "2026-01-02 00:00" in sql
        assert "5 minutes" in sql
        assert "MAX" in sql

    @patch.object(Prekit, "query")
    def test_query_signals_empty_returns_empty(self, mock_query):
        client = _make_client()

        mock_query.return_value = pd.DataFrame()

        result = client.query_signals(
            system_element="CNC-Mill",
            signal_names=["temp"],
            start="2026-01-01",
            end="2026-01-02",
        )

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    @patch.object(Prekit, "query")
    def test_query_signals_converts_types(self, mock_query):
        client = _make_client()

        mock_query.return_value = pd.DataFrame(
            {
                "time": ["2026-01-01T10:00:00", "2026-01-01T10:01:00"],
                "signal_name": ["temp", "temp"],
                "value": ["23.5", "24.0"],
            }
        )

        result = client.query_signals(
            system_element="CNC-Mill",
            signal_names=["temp"],
            start="2026-01-01",
            end="2026-01-02",
        )

        assert pd.api.types.is_datetime64_any_dtype(result["time"])
        assert result["value"].dtype == float
        assert result["value"].iloc[0] == 23.5
        assert result["value"].iloc[1] == 24.0


# ---------------------------------------------------------------------------
# TestPrekitGetLatest
# ---------------------------------------------------------------------------


class TestPrekitGetLatest:
    """Tests for Prekit.get_latest() — latest values for signals in a subtree."""

    @patch("prekit_sdk.client.prekit")
    @patch.object(Prekit, "tree")
    def test_get_latest_with_string_element(self, mock_tree, mock_prekit):
        client = _make_client()

        # Build a mock tree with a findable node
        mock_node = MagicMock(spec=TreeNode)
        mock_node.name = "CNC-Mill"
        mock_node.collect_signal_ids.return_value = ["sig-1", "sig-2"]

        mock_tree_obj = MagicMock()
        mock_tree_obj.find.return_value = mock_node
        mock_tree.return_value = mock_tree_obj

        # Mock the API response
        response_data = {"signal_count": 2, "values": [{"signal_name": "temp", "value_number": 23.5}]}
        mock_resp = MagicMock()
        mock_resp.data = json.dumps(response_data).encode()

        mock_api_instance = MagicMock()
        mock_api_instance.post_one_without_preload_content.return_value = mock_resp
        mock_prekit.GetLatestValuesApi.return_value = mock_api_instance

        result = client.get_latest("CNC-Mill")

        assert isinstance(result, dict)
        assert result["signal_count"] == 2
        assert len(result["values"]) == 1
        mock_tree.assert_called_once()
        mock_tree_obj.find.assert_called_once_with("CNC-Mill")

    @patch.object(Prekit, "tree")
    def test_get_latest_element_not_found(self, mock_tree):
        client = _make_client()

        mock_tree_obj = MagicMock()
        mock_tree_obj.find.return_value = None
        mock_tree.return_value = mock_tree_obj

        with pytest.raises(ValueError, match="Element 'NonExistent' not found in tree"):
            client.get_latest("NonExistent")

    @patch.object(Prekit, "tree")
    def test_get_latest_no_signals(self, mock_tree):
        client = _make_client()

        mock_node = MagicMock(spec=TreeNode)
        mock_node.name = "EmptyElement"
        mock_node.collect_signal_ids.return_value = []

        mock_tree_obj = MagicMock()
        mock_tree_obj.find.return_value = mock_node
        mock_tree.return_value = mock_tree_obj

        result = client.get_latest("EmptyElement")

        assert result == {"signal_count": 0, "values": []}

    @patch("prekit_sdk.client.prekit")
    def test_get_latest_with_tree_node(self, mock_prekit):
        client = _make_client()

        # Pass a TreeNode directly -- should skip tree lookup
        node = TreeNode(
            name="DirectNode",
            node_type="element",
            node_id="elem-1",
            signals=[
                TreeNode(name="sig-a", node_type="signal", node_id="sig-id-a"),
            ],
        )

        response_data = {"signal_count": 1, "values": [{"signal_name": "sig-a", "value_number": 42.0}]}
        mock_resp = MagicMock()
        mock_resp.data = json.dumps(response_data).encode()

        mock_api_instance = MagicMock()
        mock_api_instance.post_one_without_preload_content.return_value = mock_resp
        mock_prekit.GetLatestValuesApi.return_value = mock_api_instance

        result = client.get_latest(node)

        assert isinstance(result, dict)
        assert result["signal_count"] == 1
        # Verify it used the node directly (no tree() call needed)
        mock_prekit.GetLatestValuesApi.assert_called_once_with(api_client=client.api)


# ---------------------------------------------------------------------------
# TestPrekitWhoami
# ---------------------------------------------------------------------------


class TestPrekitWhoami:
    """Tests for Prekit.whoami() — authenticated user profile."""

    @patch("prekit_sdk.client.prekit")
    def test_whoami_returns_dict(self, mock_prekit):
        client = _make_client()

        user_data = {"username": "till", "email": "till@alpamayo.ch", "roles": ["admin"]}
        mock_resp = MagicMock()
        mock_resp.data = json.dumps(user_data).encode()

        mock_api_instance = MagicMock()
        mock_api_instance.get_one_without_preload_content.return_value = mock_resp
        mock_prekit.UserProfileApi.return_value = mock_api_instance

        result = client.whoami()

        assert isinstance(result, dict)
        assert result["username"] == "till"
        assert result["email"] == "till@alpamayo.ch"
        assert "admin" in result["roles"]
        mock_prekit.UserProfileApi.assert_called_once_with(api_client=client.api)


# ---------------------------------------------------------------------------
# TestPrekitHealth
# ---------------------------------------------------------------------------


class TestPrekitHealth:
    """Tests for Prekit.is_healthy() and Prekit.health()."""

    @patch("prekit_sdk.client.prekit")
    def test_is_healthy_true(self, mock_prekit):
        client = _make_client()

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.return_value = None  # Success, doesn't matter what it returns
        mock_prekit.IsHealthyApi.return_value = mock_api_instance

        assert client.is_healthy() is True

    @patch("prekit_sdk.client.prekit")
    def test_is_healthy_false(self, mock_prekit):
        client = _make_client()

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.side_effect = ConnectionError("Connection refused")
        mock_prekit.IsHealthyApi.return_value = mock_api_instance

        assert client.is_healthy() is False

    @patch("prekit_sdk.client.prekit")
    def test_health_returns_dict(self, mock_prekit):
        client = _make_client()

        health_data = {"status": "healthy", "services": {"api": "up", "mqtt": "up"}}
        mock_api_instance = MagicMock()
        mock_api_instance.get_one.return_value = health_data
        mock_prekit.ServicesHealthApi.return_value = mock_api_instance

        result = client.health()

        assert result == health_data

    @patch("prekit_sdk.client.prekit")
    def test_health_with_to_dict(self, mock_prekit):
        client = _make_client()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"status": "healthy", "uptime": 3600}
        # Ensure isinstance(result, dict) is False so it falls through to to_dict
        mock_result.__class__ = type("ServicesHealthResponse", (), {})

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.return_value = mock_result
        mock_prekit.ServicesHealthApi.return_value = mock_api_instance

        result = client.health()

        assert result == {"status": "healthy", "uptime": 3600}
        mock_result.to_dict.assert_called_once()

    @patch("prekit_sdk.client.prekit")
    def test_health_on_error(self, mock_prekit):
        client = _make_client()

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.side_effect = ConnectionError("API unreachable")
        mock_prekit.ServicesHealthApi.return_value = mock_api_instance

        result = client.health()

        assert result["status"] == "unhealthy"
        assert "API unreachable" in result["error"]


# ---------------------------------------------------------------------------
# TestPrekitRepr
# ---------------------------------------------------------------------------


class TestPrekitRepr:
    """Tests for Prekit.__repr__()."""

    def test_repr_shows_host(self):
        client = _make_client()

        r = repr(client)

        assert "Prekit" in r
        assert "https://test.local" in r

"""Tests for tree parsing, API fetching, path lookup, and signal resolution."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from prekit_sdk.tree import Tree, TreeNode, _parse_simple_tree_dict, build_tree_from_api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_factory_tree() -> Tree:
    """Build: Factory > LineA > CNC-Mill (2 signals); LineB (1 signal)."""
    return Tree(
        TreeNode(
            name="Factory",
            node_id="factory-id",
            children=[
                TreeNode(
                    name="LineA",
                    node_id="linea-id",
                    children=[
                        TreeNode(
                            name="CNC-Mill",
                            node_id="cnc-id",
                            signals=[
                                TreeNode("Temperature", "signal", "sig-temp", "float", "C"),
                                TreeNode("Vibration", "signal", "sig-vib", "float", "mm/s"),
                            ],
                        ),
                    ],
                ),
                TreeNode(
                    name="LineB",
                    node_id="lineb-id",
                    signals=[
                        TreeNode("Pressure", "signal", "sig-pres", "float", "bar"),
                    ],
                ),
            ],
        )
    )


# ---------------------------------------------------------------------------
# TestParseSimpleTreeDict
# ---------------------------------------------------------------------------

class TestParseSimpleTreeDict:
    def test_basic_hierarchy(self):
        data = {
            "name": "Factory",
            "id": "01F",
            "children": [
                {
                    "name": "Line",
                    "id": "01L",
                    "type": "system_element",
                    "children": [],
                    "signals": [],
                },
            ],
            "signals": [
                {
                    "name": "Temp",
                    "id": "01S",
                    "type": "signal",
                    "data_type": "float",
                    "unit": "C",
                },
            ],
        }
        # The simple-tree endpoint uses a flat children list where signals
        # have type="signal" and elements have type="system_element".
        # Build the combined children list as the API returns it.
        combined = list(data["children"]) + [
            {**s, "type": "signal"} for s in data["signals"]
        ]
        api_data = {"name": "Factory", "id": "01F", "children": combined}

        node = _parse_simple_tree_dict(api_data)

        assert node.name == "Factory"
        assert node.node_id == "01F"
        assert node.node_type == "element"
        assert len(node.children) == 1
        assert node.children[0].name == "Line"
        assert node.children[0].node_id == "01L"
        assert len(node.signals) == 1
        assert node.signals[0].name == "Temp"
        assert node.signals[0].node_type == "signal"
        assert node.signals[0].data_type == "float"

    def test_empty_tree(self):
        data = {"name": "Empty", "id": "01E", "children": [], "signals": []}
        node = _parse_simple_tree_dict(data)

        assert node.name == "Empty"
        assert node.children == []
        assert node.signals == []

    def test_nested_signals(self):
        """Signals should be attached to their direct parent, not hoisted."""
        data = {
            "name": "Root",
            "id": "root",
            "children": [
                {
                    "name": "Child",
                    "id": "child",
                    "type": "system_element",
                    "children": [
                        {"name": "Sensor", "id": "s1", "type": "signal", "data_type": "int", "unit": "rpm"},
                    ],
                },
            ],
        }
        node = _parse_simple_tree_dict(data)

        # Root should have no direct signals
        assert len(node.signals) == 0
        # Child should have the signal
        assert len(node.children) == 1
        child = node.children[0]
        assert child.name == "Child"
        assert len(child.signals) == 1
        assert child.signals[0].name == "Sensor"
        assert child.signals[0].unit == "rpm"

    def test_missing_fields_use_defaults(self):
        """Dict with only name and id should still parse without error."""
        data = {"name": "Minimal", "id": "01M"}
        node = _parse_simple_tree_dict(data)

        assert node.name == "Minimal"
        assert node.node_id == "01M"
        assert node.children == []
        assert node.signals == []
        assert node.metadata == {}

    def test_metadata_preserved(self):
        data = {
            "name": "WithMeta",
            "id": "wm",
            "metadata": {"location": "hall-3"},
            "children": [
                {
                    "name": "Sig",
                    "id": "s1",
                    "type": "signal",
                    "data_type": "float",
                    "metadata": {"unit": "bar", "range": "0-10"},
                },
            ],
        }
        node = _parse_simple_tree_dict(data)

        assert node.metadata == {"location": "hall-3"}
        assert node.signals[0].metadata == {"unit": "bar", "range": "0-10"}
        # unit should come from metadata when available
        assert node.signals[0].unit == "bar"

    def test_none_children_treated_as_empty(self):
        data = {"name": "NoneChildren", "id": "nc", "children": None}
        node = _parse_simple_tree_dict(data)

        assert node.children == []
        assert node.signals == []


# ---------------------------------------------------------------------------
# TestBuildTreeFromApi
# ---------------------------------------------------------------------------

class TestBuildTreeFromApi:
    def _mock_client(self):
        """Create a minimal mock client with the required nesting."""
        client = MagicMock()
        client.api.configuration.host = "https://test.local"
        client.api.configuration.access_token = "test-token"
        client.api.configuration.api_key = {}
        return client

    def test_raw_http_path(self):
        """When raw HTTP succeeds, the tree is built from JSON."""
        client = self._mock_client()

        response_data = {
            "name": "Factory",
            "id": "f1",
            "children": [
                {"name": "Line", "id": "l1", "type": "system_element", "children": []},
            ],
        }
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.data = json.dumps(response_data).encode()
        client.api.rest_client.pool_manager.request.return_value = mock_response

        tree = build_tree_from_api(client)

        assert isinstance(tree, Tree)
        assert tree.root.name == "Factory"
        assert len(tree.root.children) == 1
        assert tree.root.children[0].name == "Line"

        # Verify the raw HTTP call was made with correct URL
        call_args = client.api.rest_client.pool_manager.request.call_args
        assert call_args[0][0] == "GET"
        assert "/api/v1/system-elements/simple-tree/" in call_args[0][1]

    def test_fallback_to_semantic_hierarchy_api(self):
        """When raw HTTP fails, fall back to SemanticHierarchyApi."""
        client = self._mock_client()

        # Make raw HTTP raise
        client.api.rest_client.pool_manager.request.side_effect = Exception("connection refused")

        # Mock the fallback API — prekit is imported locally inside build_tree_from_api
        mock_raw_tree = MagicMock()
        mock_raw_tree.name = "FallbackFactory"
        mock_raw_tree.id = "fb1"
        mock_raw_tree.children = []

        with patch.dict("sys.modules", {"prekit_edge_node_api": MagicMock()}) as _:
            import prekit_edge_node_api as mock_prekit
            mock_api_instance = MagicMock()
            mock_api_instance.get_one.return_value = mock_raw_tree
            mock_prekit.SemanticHierarchyApi.return_value = mock_api_instance

            tree = build_tree_from_api(client)

        assert isinstance(tree, Tree)
        assert tree.root.name == "FallbackFactory"

    def test_both_fail_returns_error_tree(self):
        """When both methods fail, return a Tree with an error node."""
        client = self._mock_client()

        # Make raw HTTP fail
        client.api.rest_client.pool_manager.request.side_effect = Exception("http fail")

        # Make fallback fail too — patch the real module's SemanticHierarchyApi
        import prekit_edge_node_api as prekit_mod
        with patch.object(prekit_mod, "SemanticHierarchyApi") as mock_cls:
            mock_cls.return_value.get_one.side_effect = Exception("api fail")

            tree = build_tree_from_api(client)

        assert isinstance(tree, Tree)
        assert "(error:" in tree.root.name
        assert "api fail" in tree.root.name

    def test_with_root_element(self):
        """Passing a root element should add root_system_element_id to the URL."""
        client = self._mock_client()

        response_data = {"name": "Subtree", "id": "sub1", "children": []}
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.data = json.dumps(response_data).encode()
        client.api.rest_client.pool_manager.request.return_value = mock_response

        tree = build_tree_from_api(client, root="01ROOTID000000000000000")

        call_args = client.api.rest_client.pool_manager.request.call_args
        url = call_args[0][1]
        assert "root_system_element_id=01ROOTID000000000000000" in url

    def test_auth_headers_with_api_key(self):
        """API key should be included in request headers."""
        client = self._mock_client()
        client.api.configuration.access_token = None
        client.api.configuration.api_key = {"ApiKeyAuth": "my-secret-key"}

        response_data = {"name": "Root", "id": "r1", "children": []}
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.data = json.dumps(response_data).encode()
        client.api.rest_client.pool_manager.request.return_value = mock_response

        build_tree_from_api(client)

        call_args = client.api.rest_client.pool_manager.request.call_args
        headers = call_args[1]["headers"]
        assert headers["X-API-Key"] == "my-secret-key"


# ---------------------------------------------------------------------------
# TestTreeFindByPath
# ---------------------------------------------------------------------------

class TestTreeFindByPath:
    def test_find_by_path_full(self):
        tree = _make_factory_tree()
        node = tree.find_by_path("LineA", "CNC-Mill")

        assert node is not None
        assert node.name == "CNC-Mill"
        assert node.node_id == "cnc-id"

    def test_find_by_path_partial(self):
        tree = _make_factory_tree()
        node = tree.find_by_path("LineA")

        assert node is not None
        assert node.name == "LineA"
        assert len(node.children) == 1

    def test_find_by_path_not_found(self):
        tree = _make_factory_tree()
        result = tree.find_by_path("LineA", "NonExistent")

        assert result is None

    def test_find_by_path_wrong_first_segment(self):
        tree = _make_factory_tree()
        result = tree.find_by_path("NoSuchLine")

        assert result is None

    def test_find_by_path_empty(self):
        """Empty path returns the root node."""
        tree = _make_factory_tree()
        node = tree.find_by_path()

        assert node is not None
        assert node.name == "Factory"

    def test_find_by_path_root_name(self):
        """find_by_path walks children of root, so passing root name should
        only work if root has a child with the same name."""
        tree = _make_factory_tree()
        # "Factory" is the root name, not a child
        result = tree.find_by_path("Factory")

        assert result is None


# ---------------------------------------------------------------------------
# TestTreeResolveSignals
# ---------------------------------------------------------------------------

class TestTreeResolveSignals:
    def test_resolve_signals(self):
        tree = _make_factory_tree()
        result = tree.resolve_signals("CNC-Mill", ["Temperature", "Vibration"])

        assert result == {"Temperature": "sig-temp", "Vibration": "sig-vib"}

    def test_resolve_signals_missing(self):
        """Signal name not in the subtree should not appear in the result."""
        tree = _make_factory_tree()
        result = tree.resolve_signals("CNC-Mill", ["Temperature", "NonExistent"])

        assert "Temperature" in result
        assert result["Temperature"] == "sig-temp"
        assert "NonExistent" not in result

    def test_resolve_signals_from_subtree(self):
        """Resolving from a parent should find signals in children."""
        tree = _make_factory_tree()
        # Factory > LineA > CNC-Mill has Temperature
        result = tree.resolve_signals("Factory", ["Temperature", "Pressure"])

        # Should find Temperature on CNC-Mill and Pressure on LineB
        assert result["Temperature"] == "sig-temp"
        assert result["Pressure"] == "sig-pres"

    def test_resolve_signals_element_not_found(self):
        tree = _make_factory_tree()
        with pytest.raises(ValueError, match="not found"):
            tree.resolve_signals("NoSuchElement", ["Temperature"])


# ---------------------------------------------------------------------------
# TestTreeNodeCollect
# ---------------------------------------------------------------------------

class TestTreeNodeCollect:
    def test_total_signal_count(self):
        tree = _make_factory_tree()
        # Factory has: CNC-Mill(2 signals) + LineB(1 signal) = 3
        assert tree.root.total_signal_count() == 3

    def test_total_signal_count_leaf(self):
        tree = _make_factory_tree()
        cnc = tree.find("CNC-Mill")
        assert cnc is not None
        assert cnc.total_signal_count() == 2

    def test_total_signal_count_empty(self):
        node = TreeNode("Empty")
        assert node.total_signal_count() == 0

    def test_collect_signal_ids(self):
        tree = _make_factory_tree()
        ids = tree.root.collect_signal_ids()

        assert set(ids) == {"sig-temp", "sig-vib", "sig-pres"}

    def test_collect_signal_ids_subtree(self):
        tree = _make_factory_tree()
        cnc = tree.find("CNC-Mill")
        ids = cnc.collect_signal_ids()

        assert set(ids) == {"sig-temp", "sig-vib"}

    def test_collect_signal_ids_skips_empty_ids(self):
        """Signals with empty node_id should be excluded from collection."""
        node = TreeNode(
            "Machine",
            signals=[
                TreeNode("Good", "signal", "sig-1"),
                TreeNode("NoId", "signal", ""),
            ],
        )
        ids = node.collect_signal_ids()
        assert ids == ["sig-1"]

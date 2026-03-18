"""Tests for tree ASCII rendering."""

from prekit_sdk.tree import Tree, TreeNode, _render_tree


def _make_sample_tree() -> TreeNode:
    """Build: Factory > LineA > CNC-Mill (3 signals), Lathe (1 signal); LineB > Press (1 signal)."""
    return TreeNode(
        name="Factory",
        node_id="factory",
        children=[
            TreeNode(
                name="LineA",
                node_id="linea",
                children=[
                    TreeNode(
                        name="CNC-Mill",
                        node_id="cnc",
                        signals=[
                            TreeNode("Temperature", "signal", "s1", "float", "C"),
                            TreeNode("Vibration", "signal", "s2", "float", "mm/s"),
                            TreeNode("SpindleSpeed", "signal", "s3", "int", "rpm"),
                        ],
                    ),
                    TreeNode(
                        name="Lathe",
                        node_id="lathe",
                        signals=[
                            TreeNode("Temperature", "signal", "s4", "float", "C"),
                        ],
                    ),
                ],
            ),
            TreeNode(
                name="LineB",
                node_id="lineb",
                children=[
                    TreeNode(
                        name="Press",
                        node_id="press",
                        signals=[
                            TreeNode("Pressure", "signal", "s5", "float", "bar"),
                        ],
                    ),
                ],
            ),
        ],
    )


class TestTreeCompact:
    def test_compact_output(self):
        tree = Tree(_make_sample_tree())
        output = tree.to_string(signals=False)
        lines = output.split("\n")

        assert lines[0] == "Factory"
        assert "LineA" in output
        assert "CNC-Mill" in output
        assert "[3 signals]" in output
        assert "[1 signal]" in output
        # Signals should NOT appear in compact mode
        assert "Temperature" not in output
        assert "Vibration" not in output

    def test_compact_has_box_chars(self):
        tree = Tree(_make_sample_tree())
        output = tree.to_string(signals=False)
        assert "\u251c" in output or "\u2514" in output  # ├ or └


class TestTreeExpanded:
    def test_expanded_shows_signals(self):
        tree = Tree(_make_sample_tree())
        output = tree.to_string(signals=True)

        assert "Temperature" in output
        assert "Vibration" in output
        assert "SpindleSpeed" in output
        assert "(float, C)" in output
        assert "(int, rpm)" in output
        # Signal counts should NOT appear
        assert "[3 signals]" not in output

    def test_expanded_all_nodes_present(self):
        tree = Tree(_make_sample_tree())
        output = tree.to_string(signals=True)

        for name in ["Factory", "LineA", "LineB", "CNC-Mill", "Lathe", "Press",
                      "Temperature", "Vibration", "SpindleSpeed", "Pressure"]:
            assert name in output


class TestTreeOperations:
    def test_flatten(self):
        tree = Tree(_make_sample_tree())
        flat = tree.flatten()
        # 6 elements + 5 signals = 11
        assert len(flat) == 11

    def test_find_by_name(self):
        tree = Tree(_make_sample_tree())
        node = tree.find("CNC-Mill")
        assert node is not None
        assert node.name == "CNC-Mill"
        assert node.signal_count == 3

    def test_find_missing(self):
        tree = Tree(_make_sample_tree())
        assert tree.find("NonExistent") is None


class TestTreeNodeSignalCount:
    def test_signal_count(self):
        node = TreeNode("Machine", signals=[
            TreeNode("S1", "signal"),
            TreeNode("S2", "signal"),
        ])
        assert node.signal_count == 2

    def test_empty_signal_count(self):
        node = TreeNode("Machine")
        assert node.signal_count == 0

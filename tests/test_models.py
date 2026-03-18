"""Tests for rich wrapper models: __getattr__, .help(), __repr__."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from prekit_sdk.models import Element, Signal, Tag, TagContext, _BaseModel
from tests.conftest import FakeModel, make_element, make_signal


class TestGetattr:
    def test_delegates_to_raw(self):
        raw = make_element("CNC-Mill", "01CNC00000000000000000")
        elem = Element(raw, MagicMock())
        assert elem.name == "CNC-Mill"
        assert elem.id == "01CNC00000000000000000"
        assert elem.created_at == "2026-01-01T00:00:00Z"

    def test_new_fields_appear_automatically(self):
        """Simulates a new field added during API client regeneration."""
        raw = make_element("Test")
        raw.new_field = "new_value"
        elem = Element(raw, MagicMock())
        assert elem.new_field == "new_value"

    def test_missing_attr_raises(self):
        elem = Element(make_element(), MagicMock())
        with pytest.raises(AttributeError, match="no attribute 'nonexistent'"):
            _ = elem.nonexistent

    def test_sdk_methods_take_precedence(self):
        """SDK methods (verbs) should not be overridden by __getattr__."""
        elem = Element(make_element(), MagicMock())
        assert callable(elem.signals)
        assert callable(elem.help)


class TestRepr:
    def test_element_repr(self):
        elem = Element(make_element("CNC-Mill", "01CNCMILL00000000000000"), MagicMock())
        assert repr(elem) == "<Element: CNC-Mill (01CNCMIL...)>"

    def test_signal_repr(self):
        sig = Signal(make_signal("Temperature", "01SIGTEMP00000000000000"), MagicMock())
        assert repr(sig) == "<Signal: Temperature (01SIGTEM...)>"


class TestEquality:
    def test_equal_by_raw(self):
        raw = make_element()
        a = Element(raw, MagicMock())
        b = Element(raw, MagicMock())
        assert a == b

    def test_not_equal_different_raw(self):
        a = Element(make_element("A", "01A00000000000000000000"), MagicMock())
        b = Element(make_element("B", "01B00000000000000000000"), MagicMock())
        assert a != b


class TestHelp:
    def test_help_prints_fields(self, capsys):
        raw = make_element("CNC-Mill", "01CNC00000000000000000")
        mock_client = MagicMock()
        # Make signals() return empty list so relationships section works
        mock_client.signals.filter.return_value = []
        mock_client.elements.filter.return_value = []
        mock_client.elements.get.side_effect = Exception("not found")

        elem = Element(raw, mock_client)
        elem.help()

        output = capsys.readouterr().out
        assert "CNC-Mill" in output
        assert "Fields (from generated model):" in output
        assert "name" in output
        assert "Relationships:" in output
        assert ".signals()" in output
        assert "Actions:" in output
        assert "._raw" in output

    def test_help_signal(self, capsys):
        raw = make_signal("Temperature")
        mock_client = MagicMock()
        mock_client.elements.get.side_effect = Exception("not found")
        mock_client.tag_contexts.filter.return_value = []

        sig = Signal(raw, mock_client)
        sig.help()

        output = capsys.readouterr().out
        assert "Temperature" in output
        assert ".data(" in output
        assert ".latest()" in output


class TestElementNavigation:
    def test_children_calls_filter(self):
        mock_client = MagicMock()
        mock_client.elements.filter.return_value = []
        elem = Element(make_element("Parent", "01PARENT000000000000000"), mock_client)
        result = elem.children()
        mock_client.elements.filter.assert_called_once_with(parent="01PARENT000000000000000")
        assert result == []

    def test_signals_calls_filter(self):
        mock_client = MagicMock()
        mock_client.signals.filter.return_value = []
        elem = Element(make_element("Machine", "01MACHINE00000000000000"), mock_client)
        result = elem.signals()
        mock_client.signals.filter.assert_called_once_with(system_element="01MACHINE00000000000000")
        assert result == []

    def test_parent_returns_none_for_root(self):
        elem = Element(make_element("Root", "01ROOT0000000000000000", parent=None), MagicMock())
        assert elem.parent() is None


class TestSignalNavigation:
    def test_element_calls_get(self):
        mock_client = MagicMock()
        mock_elem = Element(make_element(), mock_client)
        mock_client.elements.get.return_value = mock_elem

        sig = Signal(make_signal(system_element="01ELEM0000000000000000"), mock_client)
        result = sig.element()
        mock_client.elements.get.assert_called_once_with(id="01ELEM0000000000000000")
        assert result == mock_elem

    def test_element_returns_none_if_missing(self):
        sig = Signal(make_signal(system_element=None), MagicMock())
        assert sig.element() is None

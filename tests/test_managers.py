"""Tests for Django-style managers: get, filter, all, create."""

from unittest.mock import MagicMock, patch

import pytest

from prekit_sdk.managers import (
    DoesNotExist,
    ElementManager,
    MultipleObjectsReturned,
    SignalManager,
    _apply_lookup,
    _parse_lookup,
)
from prekit_sdk.models import Element, Signal
from tests.conftest import make_element, make_signal


class TestParseLookup:
    def test_exact_default(self):
        assert _parse_lookup("name") == ("name", "exact")

    def test_contains(self):
        assert _parse_lookup("name__contains") == ("name", "contains")

    def test_startswith(self):
        assert _parse_lookup("name__startswith") == ("name", "startswith")

    def test_icontains(self):
        assert _parse_lookup("name__icontains") == ("name", "icontains")


class TestApplyLookup:
    def test_exact_match(self):
        raw = make_element("CNC-Mill")
        elem = Element(raw, MagicMock())
        assert _apply_lookup(elem, "name", "exact", "CNC-Mill") is True
        assert _apply_lookup(elem, "name", "exact", "Lathe") is False

    def test_contains(self):
        elem = Element(make_element("CNC-Mill"), MagicMock())
        assert _apply_lookup(elem, "name", "contains", "CNC") is True
        assert _apply_lookup(elem, "name", "contains", "Lathe") is False

    def test_startswith(self):
        elem = Element(make_element("CNC-Mill"), MagicMock())
        assert _apply_lookup(elem, "name", "startswith", "CNC") is True
        assert _apply_lookup(elem, "name", "startswith", "Mill") is False

    def test_icontains(self):
        elem = Element(make_element("CNC-Mill"), MagicMock())
        assert _apply_lookup(elem, "name", "icontains", "cnc") is True
        assert _apply_lookup(elem, "name", "icontains", "MILL") is True

    def test_exact_with_object_id(self):
        """FK lookup accepts objects with .id attribute."""
        raw = make_signal(system_element="01ELEM")
        sig = Signal(raw, MagicMock())

        class FakeElem:
            id = "01ELEM"

        assert _apply_lookup(sig, "system_element", "exact", FakeElem()) is True

    def test_exact_with_wrapper_id(self):
        """FK lookup accepts SDK wrappers."""
        raw = make_signal(system_element="01ELEM")
        sig = Signal(raw, MagicMock())
        elem = Element(make_element(id="01ELEM"), MagicMock())
        assert _apply_lookup(sig, "system_element", "exact", elem) is True


class TestManagerAll:
    @patch("prekit_sdk.managers.prekit")
    def test_all_wraps_results(self, mock_prekit, sample_elements):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_elements
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        mock_client = MagicMock()
        manager = ElementManager(mock_client)
        results = manager.all()

        assert len(results) == 6
        assert all(isinstance(r, Element) for r in results)
        assert results[0].name == "Factory"


class TestManagerFilter:
    @patch("prekit_sdk.managers.prekit")
    def test_filter_by_name(self, mock_prekit, sample_elements):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_elements
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        mock_client = MagicMock()
        manager = ElementManager(mock_client)
        results = manager.filter(name="CNC-Mill")

        assert len(results) == 1
        assert results[0].name == "CNC-Mill"

    @patch("prekit_sdk.managers.prekit")
    def test_filter_contains(self, mock_prekit, sample_elements):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_elements
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        manager = ElementManager(MagicMock())
        results = manager.filter(name__contains="Line")

        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"LineA", "LineB"}

    @patch("prekit_sdk.managers.prekit")
    def test_filter_multiple_criteria(self, mock_prekit, sample_signals):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_signals
        mock_prekit.SignalApi.return_value = mock_api_instance

        manager = SignalManager(MagicMock())
        results = manager.filter(data_type="float", unit="C")

        assert len(results) == 2  # Temperature on CNC + Temperature on Lathe
        assert all(r.name == "Temperature" for r in results)

    @patch("prekit_sdk.managers.prekit")
    def test_filter_by_system_element(self, mock_prekit, sample_signals):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_signals
        mock_prekit.SignalApi.return_value = mock_api_instance

        manager = SignalManager(MagicMock())
        results = manager.filter(system_element="01CNCMILL00000000000000")

        assert len(results) == 3  # Temperature, Vibration, SpindleSpeed


class TestManagerGet:
    @patch("prekit_sdk.managers.prekit")
    def test_get_single_match(self, mock_prekit, sample_elements):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_elements
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        manager = ElementManager(MagicMock())
        result = manager.get(name="CNC-Mill")
        assert result.name == "CNC-Mill"

    @patch("prekit_sdk.managers.prekit")
    def test_get_does_not_exist(self, mock_prekit, sample_elements):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_elements
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        manager = ElementManager(MagicMock())
        with pytest.raises(DoesNotExist, match="No Element"):
            manager.get(name="NonExistent")

    @patch("prekit_sdk.managers.prekit")
    def test_get_multiple_objects_returned(self, mock_prekit, sample_signals):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_signals
        mock_prekit.SignalApi.return_value = mock_api_instance

        manager = SignalManager(MagicMock())
        with pytest.raises(MultipleObjectsReturned, match="2 Signals match"):
            manager.get(name="Temperature")

    @patch("prekit_sdk.managers.prekit")
    def test_get_disambiguate_with_element(self, mock_prekit, sample_signals):
        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = sample_signals
        mock_prekit.SignalApi.return_value = mock_api_instance

        manager = SignalManager(MagicMock())
        result = manager.get(name="Temperature", system_element="01CNCMILL00000000000000")
        assert result.name == "Temperature"
        assert result.system_element == "01CNCMILL00000000000000"

    @patch("prekit_sdk.managers.prekit")
    def test_get_by_id_uses_api(self, mock_prekit):
        raw = make_element("Direct", "01DIRECT000000000000000")
        mock_api_instance = MagicMock()
        mock_api_instance.get_one.return_value = raw
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        manager = ElementManager(MagicMock())
        result = manager.get(id="01DIRECT000000000000000")
        assert result.name == "Direct"
        mock_api_instance.get_one.assert_called_once_with(id="01DIRECT000000000000000")

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


class TestManagerGetById404:
    """Test the NotFoundException bug fix: 404 -> DoesNotExist, other codes re-raise."""

    @patch("prekit_sdk.managers.prekit")
    def test_get_by_id_404_raises_does_not_exist(self, mock_prekit):
        from prekit_edge_node_api import ApiException

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.side_effect = ApiException(status=404, reason="Not Found")
        mock_prekit.SystemElementApi.return_value = mock_api_instance
        mock_prekit.ApiException = ApiException

        manager = ElementManager(MagicMock())
        with pytest.raises(DoesNotExist, match="No Element with id="):
            manager.get(id="01NONEXISTENT0000000000")

    @patch("prekit_sdk.managers.prekit")
    def test_get_by_id_500_reraises(self, mock_prekit):
        from prekit_edge_node_api import ApiException

        mock_api_instance = MagicMock()
        mock_api_instance.get_one.side_effect = ApiException(status=500, reason="Internal Server Error")
        mock_prekit.SystemElementApi.return_value = mock_api_instance
        mock_prekit.ApiException = ApiException

        manager = ElementManager(MagicMock())
        with pytest.raises(ApiException) as exc_info:
            manager.get(id="01SERVERERR00000000000")
        assert exc_info.value.status == 500


class TestManagerCreate:
    """Test create() on ElementManager, SignalManager, and base Manager."""

    @patch("prekit_sdk.managers.prekit")
    def test_element_create(self, mock_prekit):
        from tests.factories import make_system_element

        raw_returned = make_system_element("New", "01NEW00000000000000000", parent="01PARENT0000000000000000")
        mock_api_instance = MagicMock()
        mock_api_instance.post_one.return_value = raw_returned
        mock_prekit.SystemElementApi.return_value = mock_api_instance
        mock_prekit.SystemElementCreate = MagicMock(return_value="fake_create_payload")

        manager = ElementManager(MagicMock())
        result = manager.create(name="New", parent="01PARENT0000000000000000")

        assert isinstance(result, Element)
        assert result.name == "New"
        mock_prekit.SystemElementCreate.assert_called_once()
        call_kwargs = mock_prekit.SystemElementCreate.call_args[1]
        assert call_kwargs["name"] == "New"
        assert call_kwargs["parent"] == "01PARENT0000000000000000"
        mock_api_instance.post_one.assert_called_once_with(data="fake_create_payload")

    @patch("prekit_sdk.managers.prekit")
    def test_signal_create(self, mock_prekit):
        from tests.factories import make_signal as factory_make_signal

        raw_returned = factory_make_signal("Temp", system_element="01ELEM00000000000000000", data_type="float", unit="C")
        mock_api_instance = MagicMock()
        mock_api_instance.post_one.return_value = raw_returned
        mock_prekit.SignalApi.return_value = mock_api_instance
        mock_prekit.SignalCreate = MagicMock(return_value="fake_signal_payload")

        manager = SignalManager(MagicMock())
        result = manager.create(name="Temp", element="01ELEM00000000000000000", data_type="float", unit="C")

        assert isinstance(result, Signal)
        assert result.name == "Temp"
        mock_prekit.SignalCreate.assert_called_once()
        call_kwargs = mock_prekit.SignalCreate.call_args[1]
        assert call_kwargs["name"] == "Temp"
        assert call_kwargs["system_element"] == "01ELEM00000000000000000"
        assert call_kwargs["data_type"] == "float"
        assert call_kwargs["unit"] == "C"
        mock_api_instance.post_one.assert_called_once_with(data="fake_signal_payload")

    @patch("prekit_sdk.managers.prekit")
    def test_base_create_raises(self, mock_prekit):
        from prekit_sdk.managers import Manager

        mock_prekit.return_value = MagicMock()
        # Manager.api_class_name is empty, so we need to set it for init
        manager = Manager.__new__(Manager)
        manager._client = MagicMock()

        with pytest.raises(NotImplementedError, match="create\\(\\) is not implemented"):
            manager.create()


class TestManagerAllPaginated:
    """Test .all() unwrapping of paginated API responses."""

    @patch("prekit_sdk.managers.prekit")
    def test_all_paginated_objects(self, mock_prekit):
        from tests.factories import make_system_element

        elements = [make_system_element("A"), make_system_element("B")]
        paginated = MagicMock()
        paginated.objects = elements
        # Ensure it's not a plain list
        type(paginated).__iter__ = None

        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = paginated
        mock_prekit.SystemElementApi.return_value = mock_api_instance

        manager = ElementManager(MagicMock())
        results = manager.all()

        assert len(results) == 2
        assert all(isinstance(r, Element) for r in results)
        assert results[0].name == "A"
        assert results[1].name == "B"

    @patch("prekit_sdk.managers.prekit")
    def test_all_paginated_data(self, mock_prekit):
        from tests.factories import make_signal as factory_make_signal

        signals = [factory_make_signal("X"), factory_make_signal("Y"), factory_make_signal("Z")]
        paginated = MagicMock(spec=[])  # spec=[] removes default MagicMock attributes
        paginated.data = signals

        mock_api_instance = MagicMock()
        mock_api_instance.get_all.return_value = paginated
        mock_prekit.SignalApi.return_value = mock_api_instance

        manager = SignalManager(MagicMock())
        results = manager.all()

        assert len(results) == 3
        assert all(isinstance(r, Signal) for r in results)
        assert [r.name for r in results] == ["X", "Y", "Z"]


class TestApplyLookupEdgeCases:
    """Edge cases for _apply_lookup: case-insensitive variants, None fields, unknown lookups."""

    def test_istartswith(self):
        elem = Element(make_element("CNC-Mill"), MagicMock())
        assert _apply_lookup(elem, "name", "istartswith", "cnc") is True
        assert _apply_lookup(elem, "name", "istartswith", "CNC") is True
        assert _apply_lookup(elem, "name", "istartswith", "mill") is False

    def test_iexact(self):
        elem = Element(make_element("CNC-Mill"), MagicMock())
        assert _apply_lookup(elem, "name", "iexact", "cnc-mill") is True
        assert _apply_lookup(elem, "name", "iexact", "CNC-MILL") is True
        assert _apply_lookup(elem, "name", "iexact", "CNC-Mill") is True
        assert _apply_lookup(elem, "name", "iexact", "CNC") is False

    def test_none_field_returns_false(self):
        elem = Element(make_element("Test"), MagicMock())
        # 'parent' is None by default in make_element
        assert _apply_lookup(elem, "parent", "contains", "anything") is False
        assert _apply_lookup(elem, "parent", "startswith", "any") is False
        assert _apply_lookup(elem, "parent", "icontains", "any") is False
        assert _apply_lookup(elem, "parent", "istartswith", "any") is False
        assert _apply_lookup(elem, "parent", "iexact", "any") is False

    def test_unknown_lookup_returns_false(self):
        elem = Element(make_element("Test"), MagicMock())
        assert _apply_lookup(elem, "name", "endswith", "est") is False
        assert _apply_lookup(elem, "name", "regex", ".*") is False

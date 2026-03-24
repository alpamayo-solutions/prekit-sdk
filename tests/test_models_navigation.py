"""Tests for model navigation: path building, data delegation, update, and hashing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from prekit_sdk.models import Element, Signal, Tag, TagContext, _BaseModel
from tests.conftest import FakeModel, make_element, make_signal


# ---------------------------------------------------------------------------
# TestElementPath
# ---------------------------------------------------------------------------

class TestElementPath:
    def test_path_single_level(self):
        """Element with no parent returns just its own name."""
        raw = make_element("Factory", "01FACTORY00000000000000", parent=None)
        elem = Element(raw, MagicMock())

        assert elem.path() == "Factory"

    def test_path_multi_level(self):
        """Full path walks parent chain: Factory/LineA/CNC-Mill."""
        mock_client = MagicMock()

        # Build the chain: CNC-Mill -> LineA -> Factory
        raw_factory = make_element("Factory", "01FACTORY00000000000000", parent=None)
        raw_line_a = make_element("LineA", "01LINEA000000000000000", parent="01FACTORY00000000000000")
        raw_cnc = make_element("CNC-Mill", "01CNCMILL0000000000000", parent="01LINEA000000000000000")

        factory = Element(raw_factory, mock_client)
        line_a = Element(raw_line_a, mock_client)
        cnc = Element(raw_cnc, mock_client)

        # Mock parent lookups: CNC->LineA, LineA->Factory, Factory->None
        def get_parent(id):
            lookup = {
                "01LINEA000000000000000": line_a,
                "01FACTORY00000000000000": factory,
            }
            return lookup.get(id)

        mock_client.elements.get.side_effect = lambda id: get_parent(id)

        assert cnc.path() == "Factory/LineA/CNC-Mill"

    def test_path_cycle_detection(self):
        """If parent() returns a cycle, path() should not loop infinitely."""
        mock_client = MagicMock()

        raw = make_element("Loop", "01LOOP0000000000000000", parent="01LOOP0000000000000000")
        elem = Element(raw, mock_client)

        # parent() returns itself
        mock_client.elements.get.return_value = elem

        # Should terminate without infinite loop due to `seen` set
        result = elem.path()
        assert "Loop" in result
        # Should appear only once
        assert result.count("Loop") == 1

    def test_path_parent_lookup_fails(self):
        """If parent lookup raises, path should stop gracefully."""
        mock_client = MagicMock()
        raw = make_element("Orphan", "01ORPHAN000000000000000", parent="01MISSING000000000000000")
        mock_client.elements.get.side_effect = Exception("not found")

        elem = Element(raw, mock_client)
        # parent() catches exceptions and returns None
        assert elem.path() == "Orphan"


# ---------------------------------------------------------------------------
# TestElementData
# ---------------------------------------------------------------------------

class TestElementData:
    def test_data_delegates_to_historian(self):
        mock_client = MagicMock()
        raw = make_element("Machine", "01MACH0000000000000000")
        elem = Element(raw, mock_client)

        with patch("prekit_sdk.historian.fetch_element_data") as mock_fetch:
            mock_fetch.return_value = "fake-dataframe"

            result = elem.data(last="1h")

        mock_fetch.assert_called_once_with(mock_client, elem, last="1h", start=None, end=None)
        assert result == "fake-dataframe"

    def test_data_passes_start_end(self):
        mock_client = MagicMock()
        raw = make_element("Machine", "01MACH0000000000000000")
        elem = Element(raw, mock_client)

        with patch("prekit_sdk.historian.fetch_element_data") as mock_fetch:
            mock_fetch.return_value = "fake-dataframe"

            elem.data(start="2026-01-01", end="2026-01-02")

        mock_fetch.assert_called_once_with(
            mock_client, elem, last=None, start="2026-01-01", end="2026-01-02"
        )


# ---------------------------------------------------------------------------
# TestElementUpdate
# ---------------------------------------------------------------------------

class TestElementUpdate:
    def test_update_calls_patch_api(self):
        mock_client = MagicMock()
        raw = make_element("OldName", "01ELEM0000000000000000")
        elem = Element(raw, mock_client)

        import prekit_edge_node_api as prekit_mod
        with patch.object(prekit_mod, "PatchedSystemElementCreate") as mock_patched_cls, \
             patch.object(prekit_mod, "SystemElementApi") as mock_api_cls:
            mock_patched = MagicMock()
            mock_patched_cls.return_value = mock_patched

            mock_api_instance = MagicMock()
            mock_api_instance.patch_one.return_value = make_element("NewName", "01ELEM0000000000000000")
            mock_api_cls.return_value = mock_api_instance

            result = elem.update(name="NewName")

        mock_patched_cls.assert_called_once_with(name="NewName")
        mock_api_instance.patch_one.assert_called_once_with(id="01ELEM0000000000000000", data=mock_patched)
        assert isinstance(result, Element)
        assert result.name == "NewName"


# ---------------------------------------------------------------------------
# TestSignalPath
# ---------------------------------------------------------------------------

class TestSignalPath:
    def test_path_with_element(self):
        """Signal path is element path + signal name."""
        mock_client = MagicMock()

        # Build element chain: Factory > LineA > Machine
        raw_factory = make_element("Factory", "01FACTORY00000000000000", parent=None)
        raw_line = make_element("LineA", "01LINEA000000000000000", parent="01FACTORY00000000000000")
        raw_machine = make_element("Machine", "01MACHINE0000000000000", parent="01LINEA000000000000000")

        factory = Element(raw_factory, mock_client)
        line = Element(raw_line, mock_client)
        machine = Element(raw_machine, mock_client)

        def get_element(id):
            lookup = {
                "01MACHINE0000000000000": machine,
                "01LINEA000000000000000": line,
                "01FACTORY00000000000000": factory,
            }
            return lookup.get(id)

        mock_client.elements.get.side_effect = lambda id: get_element(id)

        raw_sig = make_signal("Temperature", "01SIG000000000000000000",
                              system_element="01MACHINE0000000000000")
        sig = Signal(raw_sig, mock_client)

        assert sig.path() == "Factory/LineA/Machine/Temperature"

    def test_path_without_element(self):
        """Signal with no element returns just signal name."""
        raw_sig = make_signal("Orphan", "01SIG000000000000000000", system_element=None)
        sig = Signal(raw_sig, MagicMock())

        assert sig.path() == "Orphan"

    def test_path_element_lookup_fails(self):
        """If element lookup raises, return just signal name."""
        mock_client = MagicMock()
        mock_client.elements.get.side_effect = Exception("not found")

        raw_sig = make_signal("Sensor", "01SIG000000000000000000",
                              system_element="01MISSING000000000000000")
        sig = Signal(raw_sig, mock_client)

        # element() catches exceptions and returns None
        assert sig.path() == "Sensor"


# ---------------------------------------------------------------------------
# TestSignalData
# ---------------------------------------------------------------------------

class TestSignalData:
    def test_data_delegates_to_historian(self):
        mock_client = MagicMock()
        raw = make_signal("Temperature", "01SIG000000000000000000")
        sig = Signal(raw, mock_client)

        with patch("prekit_sdk.historian.fetch_signal_data") as mock_fetch:
            mock_fetch.return_value = "fake-dataframe"

            result = sig.data(last="30m")

        mock_fetch.assert_called_once_with(mock_client, sig, last="30m", start=None, end=None)
        assert result == "fake-dataframe"


# ---------------------------------------------------------------------------
# TestSignalLatest
# ---------------------------------------------------------------------------

class TestSignalLatest:
    def test_latest_delegates_to_historian(self):
        mock_client = MagicMock()
        raw = make_signal("Temperature", "01SIG000000000000000000")
        sig = Signal(raw, mock_client)

        with patch("prekit_sdk.historian.fetch_latest") as mock_fetch:
            mock_fetch.return_value = {"value": "42.5", "timestamp": "2026-01-01T12:00:00Z"}

            result = sig.latest()

        mock_fetch.assert_called_once_with(mock_client, sig)
        assert result == {"value": "42.5", "timestamp": "2026-01-01T12:00:00Z"}

    def test_latest_returns_none(self):
        mock_client = MagicMock()
        raw = make_signal("Temperature", "01SIG000000000000000000")
        sig = Signal(raw, mock_client)

        with patch("prekit_sdk.historian.fetch_latest") as mock_fetch:
            mock_fetch.return_value = None

            result = sig.latest()

        assert result is None


# ---------------------------------------------------------------------------
# TestTagService
# ---------------------------------------------------------------------------

class TestTagService:
    def test_service_calls_api(self):
        mock_client = MagicMock()
        raw = FakeModel(id="01TAG000000000000000000", name="opcua-tag", service="opcua-connector")
        tag = Tag(raw, mock_client)

        import prekit_edge_node_api as prekit_mod
        with patch.object(prekit_mod, "ServiceApi") as mock_api_cls:
            mock_service = MagicMock()
            mock_api_instance = MagicMock()
            mock_api_instance.get_one.return_value = mock_service
            mock_api_cls.return_value = mock_api_instance

            result = tag.service()

        mock_api_instance.get_one.assert_called_once_with(name="opcua-connector")
        assert result == mock_service

    def test_service_returns_none_on_missing(self):
        """When service ID is None, return None without calling API."""
        mock_client = MagicMock()
        raw = FakeModel(id="01TAG000000000000000000", name="orphan-tag", service=None)
        tag = Tag(raw, mock_client)

        result = tag.service()
        assert result is None

    def test_service_returns_none_on_api_error(self):
        """When API raises, return None gracefully."""
        mock_client = MagicMock()
        raw = FakeModel(id="01TAG000000000000000000", name="tag", service="bad-service")
        tag = Tag(raw, mock_client)

        import prekit_edge_node_api as prekit_mod
        with patch.object(prekit_mod, "ServiceApi") as mock_api_cls:
            mock_api_cls.return_value.get_one.side_effect = Exception("not found")

            result = tag.service()

        assert result is None


# ---------------------------------------------------------------------------
# TestTagContextNavigation
# ---------------------------------------------------------------------------

class TestTagContextNavigation:
    def test_signal_calls_get(self):
        mock_client = MagicMock()
        mock_sig = Signal(make_signal("Temp"), mock_client)
        mock_client.signals.get.return_value = mock_sig

        raw = FakeModel(id="01DTC000000000000000000", signal="01SIG000000000000000000",
                        data_tag="01TAG000000000000000000")
        tc = TagContext(raw, mock_client)

        result = tc.signal()

        mock_client.signals.get.assert_called_once_with(id="01SIG000000000000000000")
        assert result == mock_sig

    def test_tag_calls_get(self):
        mock_client = MagicMock()
        mock_tag = Tag(FakeModel(id="01TAG000000000000000000", name="MyTag"), mock_client)
        mock_client.tags.get.return_value = mock_tag

        raw = FakeModel(id="01DTC000000000000000000", signal="01SIG000000000000000000",
                        data_tag="01TAG000000000000000000")
        tc = TagContext(raw, mock_client)

        result = tc.tag()

        mock_client.tags.get.assert_called_once_with(id="01TAG000000000000000000")
        assert result == mock_tag

    def test_signal_none_when_no_id(self):
        """When signal is None, return None without calling API."""
        mock_client = MagicMock()
        raw = FakeModel(id="01DTC000000000000000000", signal=None,
                        data_tag="01TAG000000000000000000")
        tc = TagContext(raw, mock_client)

        result = tc.signal()
        assert result is None
        mock_client.signals.get.assert_not_called()

    def test_tag_returns_none_on_api_error(self):
        """When tag lookup raises, return None gracefully."""
        mock_client = MagicMock()
        mock_client.tags.get.side_effect = Exception("not found")

        raw = FakeModel(id="01DTC000000000000000000", signal="01SIG000000000000000000",
                        data_tag="01TAG000000000000000000")
        tc = TagContext(raw, mock_client)

        result = tc.tag()
        assert result is None


# ---------------------------------------------------------------------------
# TestBaseModelSetattr
# ---------------------------------------------------------------------------

class TestBaseModelSetattr:
    def test_private_attrs_on_wrapper(self):
        """Setting _foo should go to the wrapper, not the raw model."""
        raw = make_element("Test")
        elem = Element(raw, MagicMock())

        elem._custom = "wrapper-value"

        # Should be on the wrapper object itself
        assert object.__getattribute__(elem, "_custom") == "wrapper-value"
        # Should NOT be on the raw model
        assert not hasattr(raw, "_custom")

    def test_public_attrs_on_raw(self):
        """Setting a public attr should delegate to the raw model."""
        raw = make_element("OldName")
        elem = Element(raw, MagicMock())

        elem.name = "NewName"

        assert raw.name == "NewName"
        assert elem.name == "NewName"

    def test_setattr_new_public_field(self):
        """Setting a brand-new public attr goes to raw model."""
        raw = make_element("Test")
        elem = Element(raw, MagicMock())

        elem.custom_field = "hello"

        assert raw.custom_field == "hello"
        assert elem.custom_field == "hello"


# ---------------------------------------------------------------------------
# TestBaseModelHash
# ---------------------------------------------------------------------------

class TestBaseModelHash:
    def test_hash_uses_id(self):
        """Two wrappers with the same ID should have the same hash."""
        raw_a = make_element("A", "01SAME0000000000000000")
        raw_b = make_element("B", "01SAME0000000000000000")

        elem_a = Element(raw_a, MagicMock())
        elem_b = Element(raw_b, MagicMock())

        assert hash(elem_a) == hash(elem_b)

    def test_hash_different_ids(self):
        """Wrappers with different IDs should (very likely) have different hashes."""
        raw_a = make_element("A", "01AAAA0000000000000000")
        raw_b = make_element("B", "01BBBB0000000000000000")

        elem_a = Element(raw_a, MagicMock())
        elem_b = Element(raw_b, MagicMock())

        assert hash(elem_a) != hash(elem_b)

    def test_hash_allows_set_membership(self):
        """Elements with same ID should deduplicate in a set."""
        raw_a = make_element("A", "01SAME0000000000000000")
        raw_b = make_element("A", "01SAME0000000000000000")

        elem_a = Element(raw_a, MagicMock())
        elem_b = Element(raw_b, MagicMock())

        # Both should be usable as set/dict keys
        s = {elem_a, elem_b}
        # They have the same hash; whether they collapse depends on __eq__
        # which compares _raw, so same-content dataclasses are equal
        assert len(s) == 1

    def test_hash_signal_model(self):
        """Hash should work on Signal wrappers too."""
        raw = make_signal("Temp", "01SIG000000000000000000")
        sig = Signal(raw, MagicMock())

        # Should not raise
        h = hash(sig)
        assert isinstance(h, int)

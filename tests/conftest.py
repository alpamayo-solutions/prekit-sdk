"""Shared test fixtures with mocked API client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class FakeModel:
    """Minimal fake Pydantic model for testing __getattr__ delegation."""

    id: str = "01JABCDEF123456789012345"
    name: str = "TestElement"
    created_at: str = "2026-01-01T00:00:00Z"
    updated_at: str = "2026-01-01T00:00:00Z"
    parent: str | None = None
    system_element: str | None = None
    data_type: str = "float"
    unit: str = "C"
    source: str = "connector"
    service: str | None = None
    data_tag: str | None = None
    signal: str | None = None
    normalized_name: str = ""
    topic_context_section: str = ""
    level: int = 0
    lft: int = 0
    rght: int = 0
    tree_id: int = 0
    description: str | None = None

    # Simulate Pydantic v2 model_fields
    @property
    def model_fields(self) -> dict:
        return {
            "id": None, "name": None, "created_at": None, "updated_at": None,
            "parent": None, "system_element": None, "data_type": None, "unit": None,
            "source": None, "normalized_name": None, "topic_context_section": None,
            "level": None, "lft": None, "rght": None, "tree_id": None, "description": None,
        }


def make_element(name: str = "TestElement", id: str = "01JABCDEF123456789012345", parent: str | None = None) -> FakeModel:
    return FakeModel(name=name, id=id, parent=parent)


def make_signal(
    name: str = "Temperature",
    id: str = "01JSIG00000000000000000",
    system_element: str | None = "01JABCDEF123456789012345",
    data_type: str = "float",
    unit: str = "C",
) -> FakeModel:
    return FakeModel(name=name, id=id, system_element=system_element, data_type=data_type, unit=unit)


@pytest.fixture
def mock_client():
    """Create a mock Prekit client with basic API responses."""
    from prekit_sdk.client import Prekit
    from prekit_sdk.auth import AutoRefreshApiClient

    mock_api = MagicMock(spec=AutoRefreshApiClient)
    mock_api.configuration = MagicMock()
    mock_api.configuration.host = "https://test.local/api/v1"

    client = Prekit(api=mock_api)
    return client


@pytest.fixture
def sample_elements():
    """Sample element hierarchy: Factory > LineA > CNC-Mill, Lathe; LineB > Press."""
    factory = make_element("Factory", "01FACTORY000000000000000")
    line_a = make_element("LineA", "01LINEA0000000000000000", parent="01FACTORY000000000000000")
    line_b = make_element("LineB", "01LINEB0000000000000000", parent="01FACTORY000000000000000")
    cnc = make_element("CNC-Mill", "01CNCMILL00000000000000", parent="01LINEA0000000000000000")
    lathe = make_element("Lathe", "01LATHE0000000000000000", parent="01LINEA0000000000000000")
    press = make_element("Press", "01PRESS0000000000000000", parent="01LINEB0000000000000000")
    return [factory, line_a, line_b, cnc, lathe, press]


@pytest.fixture
def sample_signals():
    """Sample signals on different elements."""
    return [
        make_signal("Temperature", "01SIG_TEMP_CNC00000000", "01CNCMILL00000000000000", "float", "C"),
        make_signal("Vibration", "01SIG_VIB_CNC000000000", "01CNCMILL00000000000000", "float", "mm/s"),
        make_signal("SpindleSpeed", "01SIG_SPD_CNC000000000", "01CNCMILL00000000000000", "int", "rpm"),
        make_signal("Temperature", "01SIG_TEMP_LAT00000000", "01LATHE0000000000000000", "float", "C"),
        make_signal("Pressure", "01SIG_PRES_PRS00000000", "01PRESS0000000000000000", "float", "bar"),
    ]

"""Factory functions producing real generated Pydantic models with sensible defaults.

These replace the FakeModel approach for most tests, providing higher fidelity
since tests exercise the actual model classes from prekit_edge_node_api.
"""

from __future__ import annotations

from datetime import datetime, timezone

import prekit_edge_node_api as prekit


_COUNTER = 0


def _next_id(prefix: str = "01TEST") -> str:
    """Generate a unique ULID-like ID for tests."""
    global _COUNTER
    _COUNTER += 1
    suffix = str(_COUNTER).zfill(20)
    return f"{prefix}{suffix}"[:26]


def reset_counter() -> None:
    """Reset the ID counter (call in conftest if needed)."""
    global _COUNTER
    _COUNTER = 0


def make_system_element(
    name: str = "TestElement",
    id: str | None = None,
    parent: str | None = None,
    **overrides,
) -> prekit.SystemElement:
    """Create a real SystemElement instance."""
    defaults = {
        "id": id or _next_id("01ELEM"),
        "name": name,
        "parent": parent,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "normalized_name": name.lower(),
        "topic_context_section": "",
        "level": 0,
        "lft": 0,
        "rght": 0,
        "tree_id": 0,
    }
    defaults.update(overrides)
    return prekit.SystemElement(**defaults)


def make_signal(
    name: str = "Temperature",
    id: str | None = None,
    system_element: str | None = None,
    data_type: str = "float",
    unit: str = "C",
    source: str = "connector",
    **overrides,
) -> prekit.Signal:
    """Create a real Signal instance."""
    defaults = {
        "id": id or _next_id("01SIG0"),
        "name": name,
        "system_element": system_element,
        "data_type": data_type,
        "unit": unit,
        "source": source,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "normalized_name": name.lower(),
        "topic_context_section": "",
    }
    defaults.update(overrides)
    return prekit.Signal(**defaults)


def make_metric(
    id: int = 1,
    value: str = "42.5",
    signal_id: str = "01SIG0000000000000000001",
    time: datetime | None = None,
    **overrides,
) -> prekit.Metric:
    """Create a real Metric instance."""
    defaults = {
        "id": id,
        "time": time or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "value": value,
        "signal_id": signal_id,
        "edge_node_id": None,
    }
    defaults.update(overrides)
    return prekit.Metric(**defaults)


def make_data_tag(
    name: str = "Tag1",
    id: str | None = None,
    service: str = "opcua-connector",
    **overrides,
) -> prekit.DataTag:
    """Create a real DataTag instance."""
    defaults = {
        "id": id or _next_id("01TAG0"),
        "name": name,
        "service": service,
    }
    defaults.update(overrides)
    return prekit.DataTag(**defaults)


def make_data_tag_context(
    id: str | None = None,
    data_tag: str = "01TAG00000000000000000001",
    signal: str | None = "01SIG0000000000000000001",
    **overrides,
) -> prekit.DataTagContext:
    """Create a real DataTagContext instance."""
    defaults = {
        "id": id or _next_id("01DTCX"),
        "data_tag": data_tag,
        "signal": signal,
        "is_logged": True,
        "is_ignored": False,
        "is_published": True,
        "polling_rate_ms": 1000,
    }
    defaults.update(overrides)
    return prekit.DataTagContext(**defaults)


# Pre-built hierarchies for common test scenarios

def make_factory_hierarchy() -> list[prekit.SystemElement]:
    """Factory > LineA > CNC-Mill, Lathe; LineB > Press."""
    factory = make_system_element("Factory", "01FACTORY00000000000000")
    line_a = make_system_element("LineA", "01LINEA000000000000000", parent="01FACTORY00000000000000")
    line_b = make_system_element("LineB", "01LINEB000000000000000", parent="01FACTORY00000000000000")
    cnc = make_system_element("CNC-Mill", "01CNCMILL0000000000000", parent="01LINEA000000000000000")
    lathe = make_system_element("Lathe", "01LATHE000000000000000", parent="01LINEA000000000000000")
    press = make_system_element("Press", "01PRESS000000000000000", parent="01LINEB000000000000000")
    return [factory, line_a, line_b, cnc, lathe, press]


def make_cnc_signals() -> list[prekit.Signal]:
    """Signals on CNC-Mill + Lathe + Press."""
    return [
        make_signal("Temperature", "01SIG_TEMP_CNC000000000", "01CNCMILL0000000000000", "float", "C"),
        make_signal("Vibration", "01SIG_VIB_CNC0000000000", "01CNCMILL0000000000000", "float", "mm/s"),
        make_signal("SpindleSpeed", "01SIG_SPD_CNC0000000000", "01CNCMILL0000000000000", "int", "rpm"),
        make_signal("Temperature", "01SIG_TEMP_LAT000000000", "01LATHE000000000000000", "float", "C"),
        make_signal("Pressure", "01SIG_PRES_PRS000000000", "01PRESS000000000000000", "float", "bar"),
    ]

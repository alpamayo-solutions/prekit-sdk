"""Historian data access — fetch time-series data as pandas DataFrames.

All data access uses signal IDs internally (unambiguous), never names.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from .helpers import resolve_id, resolve_time_range

if TYPE_CHECKING:
    from .models import Element, Signal


def fetch_signal_data(
    client: Any,
    signal: Signal | str,
    last: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> pd.DataFrame:
    """Fetch historian data for a single signal.

    Args:
        client: Prekit client instance.
        signal: Signal wrapper or signal ID string.
        last: Relative duration (e.g., "1h", "7d").
        start: Absolute start time.
        end: Absolute end time (defaults to now).

    Returns:
        DataFrame with columns: timestamp, value
    """
    import prekit_edge_node_api as prekit

    signal_id = resolve_id(signal)
    start_dt, end_dt = resolve_time_range(last=last, start=start, end=end)

    api = prekit.MetricApi(api_client=client.api)

    try:
        result = api.get_all(
            select_signals=[signal_id],
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
        )
    except Exception:
        # Fallback: try GetSignalDataApi
        try:
            api2 = prekit.GetSignalDataApi(api_client=client.api)
            result = api2.get_one(
                signal_id=signal_id,
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
            )
        except Exception:
            return pd.DataFrame(columns=["timestamp", "value"])

    return _metrics_to_dataframe(result)


def fetch_element_data(
    client: Any,
    element: Element | str,
    last: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> pd.DataFrame:
    """Fetch historian data for all signals on an element.

    Returns a pivoted DataFrame with timestamp index and one column per signal name.
    """

    element_id = resolve_id(element)

    # Get all signals on this element
    signals = client.signals.filter(system_element=element_id)
    if not signals:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for sig in signals:
        df = fetch_signal_data(client, sig, last=last, start=start, end=end)
        if not df.empty:
            df = df.rename(columns={"value": sig.name})
            df = df.set_index("timestamp")
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    # Merge all signal DataFrames on timestamp
    merged = frames[0]
    for df in frames[1:]:
        merged = merged.join(df, how="outer")

    return merged.sort_index().reset_index()


def fetch_multi_signal_data(
    client: Any,
    signals: list,
    last: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> pd.DataFrame:
    """Fetch historian data for multiple signals.

    Returns a pivoted DataFrame with timestamp index and one column per signal name.
    """
    if not signals:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for sig in signals:
        df = fetch_signal_data(client, sig, last=last, start=start, end=end)
        if not df.empty:
            name = getattr(sig, "name", str(sig))
            df = df.rename(columns={"value": name})
            df = df.set_index("timestamp")
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    merged = frames[0]
    for df in frames[1:]:
        merged = merged.join(df, how="outer")

    return merged.sort_index().reset_index()


def fetch_latest(client: Any, signal: Any) -> dict | None:
    """Fetch the latest metric value for a signal.

    Returns:
        Dict with 'value' and 'timestamp' keys, or None if no data.
    """
    import prekit_edge_node_api as prekit

    signal_id = resolve_id(signal)

    try:
        api = prekit.GetLatestValuesApi(api_client=client.api)
        result = api.get_one(signal_ids=[signal_id])

        if isinstance(result, dict):
            entry = result.get(signal_id)
            if entry:
                return {
                    "value": getattr(entry, "value", entry.get("value") if isinstance(entry, dict) else None),
                    "timestamp": getattr(entry, "timestamp", entry.get("timestamp") if isinstance(entry, dict) else None),
                }
        elif isinstance(result, list) and result:
            entry = result[0]
            return {
                "value": getattr(entry, "value", None),
                "timestamp": getattr(entry, "timestamp", None),
            }
    except Exception:
        pass

    return None


def _metrics_to_dataframe(metrics: Any) -> pd.DataFrame:
    """Convert API metric response to a DataFrame with timestamp + value columns."""
    if metrics is None:
        return pd.DataFrame(columns=["timestamp", "value"])

    # Handle paginated response
    items = metrics
    if hasattr(metrics, "objects"):
        items = metrics.objects
    elif hasattr(metrics, "data"):
        items = metrics.data

    if not items:
        return pd.DataFrame(columns=["timestamp", "value"])

    rows: list[dict] = []
    for m in items:
        ts = getattr(m, "timestamp", getattr(m, "timestamp_dt", None))
        val = getattr(m, "value", None)
        if ts is not None:
            rows.append({"timestamp": ts, "value": val})

    if not rows:
        return pd.DataFrame(columns=["timestamp", "value"])

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)

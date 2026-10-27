"""Measured hourly export/revenue calculations.

This module intentionally has no Home Assistant dependency so the arithmetic
can be tested independently from Recorder history access.
"""

from __future__ import annotations

import math


class RevenueError(ValueError):
    """Meter input cannot be used for a measured hourly record."""


_KWH_FACTORS = {"Wh": 1 / 1000, "kWh": 1, "MWh": 1000}


def meter_delta_kwh(start: object, end: object, unit: object) -> float:
    """Return a non-negative cumulative-meter delta in kWh.

    Counter resets are rejected rather than treated as export. This protects
    the financial ledger from falsely positive entries.
    """
    if unit not in _KWH_FACTORS:
        raise RevenueError("Energy meter must use Wh, kWh, or MWh")
    try:
        start_value, end_value = float(start), float(end)
    except (TypeError, ValueError) as err:
        raise RevenueError("Energy meter has no numeric state") from err
    if not math.isfinite(start_value) or not math.isfinite(end_value):
        raise RevenueError("Energy meter has a non-finite state")
    delta = end_value - start_value
    if delta < 0:
        raise RevenueError("Energy meter decreased; counter reset cannot be calculated")
    return delta * _KWH_FACTORS[unit]


def measured_hour(
    export_start: object, export_end: object, import_start: object, import_end: object,
    export_unit: object, import_unit: object, price_pln_per_kwh: object,
) -> dict[str, float]:
    """Calculate one hour, ignoring negative net export as requested."""
    exported = meter_delta_kwh(export_start, export_end, export_unit)
    imported = meter_delta_kwh(import_start, import_end, import_unit)
    try:
        price = float(price_pln_per_kwh)
    except (TypeError, ValueError) as err:
        raise RevenueError("Price has no numeric value") from err
    if not math.isfinite(price):
        raise RevenueError("Price is non-finite")
    net = max(0.0, exported - imported)
    return {
        "exported_kwh": round(exported, 6), "imported_kwh": round(imported, 6),
        "net_exported_kwh": round(net, 6), "price_pln_per_kwh": round(price, 6),
        "revenue_pln": round(net * price, 6),
    }

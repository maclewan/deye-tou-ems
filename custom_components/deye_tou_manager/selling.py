"""Fail-closed price planning for Deye TOU battery selling.

Planning is deliberately independent of inverter writes. PSE publishes quarter-hour
records, but a settlement price and each candidate selling block are hourly.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any


class SellingPlanError(ValueError):
    """The price input cannot produce a safe selling plan."""


_PERIOD_START = re.compile(r"^(\d{2}):([0-5]\d)\s*-\s*")


def _period_end(value: Any) -> datetime:
    """PSE represents the last quarter's end as 24:00 on the business date."""
    if not isinstance(value, str):
        raise SellingPlanError("Price period has no valid end timestamp")
    if value.endswith(" 24:00:00"):
        try:
            return datetime.fromisoformat(value[:10]) + timedelta(days=1)
        except ValueError as err:
            raise SellingPlanError("Price period has an invalid date") from err
    try:
        return datetime.fromisoformat(value)
    except ValueError as err:
        raise SellingPlanError("Price period has an invalid end timestamp") from err


def hourly_prices(records: list[dict], day: date, unit: str) -> list[float]:
    """Return all 24 complete hourly averages in PLN/kWh or reject the day."""
    if unit not in ("PLN/MWh", "PLN/kWh"):
        raise SellingPlanError("Price sensor must use PLN/MWh or PLN/kWh")
    if not isinstance(records, list):
        raise SellingPlanError("Price sensor has no price records")
    quarters: dict[tuple[int, int], float] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("business_date") != day.isoformat():
            raise SellingPlanError("Price records are missing or belong to another day")
        match = _PERIOD_START.match(str(record.get("period", "")))
        if match is None:
            raise SellingPlanError("Price record has an invalid period")
        hour, minute = (int(part) for part in match.groups())
        if hour > 23 or minute not in (0, 15, 30, 45):
            raise SellingPlanError("Price record is not a valid quarter-hour")
        expected_start = datetime.combine(day, datetime.min.time()) + timedelta(
            hours=hour, minutes=minute
        )
        if _period_end(record.get("dtime")) - timedelta(minutes=15) != expected_start:
            raise SellingPlanError("Price record timestamps disagree")
        try:
            price = float(record["rce_pln"])
        except (KeyError, TypeError, ValueError) as err:
            raise SellingPlanError("Price record has no numeric price") from err
        if not math.isfinite(price):
            raise SellingPlanError("Price record has a non-finite price")
        key = (hour, minute)
        if key in quarters:
            raise SellingPlanError("Duplicate price period; DST day cannot be planned safely")
        quarters[key] = price / 1000 if unit == "PLN/MWh" else price
    if len(quarters) != 96:
        raise SellingPlanError("A complete 96-quarter price day is required")
    return [sum(quarters[hour, minute] for minute in (0, 15, 30, 45)) / 4
            for hour in range(24)]


def make_sell_plan(
    records: list[dict], day: date, unit: str, *, threshold: float,
    max_ranges: int, time_of_day: str,
) -> dict:
    """Choose the most expensive contiguous above-threshold hourly ranges.

    A range is a maximal run of eligible hours. All quarters in an hour share
    that hour's average price. Ranking is by the run's mean, then peak price.
    """
    if not isinstance(max_ranges, int) or isinstance(max_ranges, bool) or not 1 <= max_ranges <= 6:
        raise SellingPlanError("Range count must be between 1 and 6")
    if time_of_day not in ("morning", "afternoon", "any"):
        raise SellingPlanError("Time of day must be morning, afternoon, or any")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError) as err:
        raise SellingPlanError("Price threshold must be numeric") from err
    if not math.isfinite(threshold) or threshold < 0:
        raise SellingPlanError("Price threshold must be finite and non-negative")
    prices = hourly_prices(records, day, unit)
    permitted = range(0, 12) if time_of_day == "morning" else (
        range(12, 24) if time_of_day == "afternoon" else range(24)
    )
    candidates = []
    start = None
    for hour in list(permitted) + [permitted.stop]:
        eligible = hour < permitted.stop and prices[hour] >= threshold
        if eligible and start is None:
            start = hour
        elif not eligible and start is not None:
            values = prices[start:hour]
            candidates.append({
                "start": f"{start:02d}:00",
                "end": f"{hour:02d}:00",
                "average_price": round(sum(values) / len(values), 6),
                "peak_price": round(max(values), 6),
                "hours": [{"start": f"{h:02d}:00", "price": round(prices[h], 6)}
                          for h in range(start, hour)],
            })
            start = None
    selected = sorted(candidates, key=lambda item: (
        -item["average_price"], -item["peak_price"], item["start"]
    ))[:max_ranges]
    selected.sort(key=lambda item: item["start"])
    return {
        "date": day.isoformat(), "price_unit": "PLN/kWh",
        "threshold": threshold, "time_of_day": time_of_day,
        "max_ranges": max_ranges, "ranges": selected,
    }

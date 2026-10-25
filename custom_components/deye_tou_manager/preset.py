"""Validation for the on-disk Deye TOU preset format (schema version 1)."""

from __future__ import annotations

import math
import re

WORK_MODES = ("Zero Export To CT", "Zero Export To Load", "Selling First")
SLOT_KEYS = {"start", "soc", "power", "grid_charge", "gen"}
START_PATTERN = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]")


class PresetError(ValueError):
    """A preset cannot be safely saved or applied."""


def _number(value: object, maximum: float, field: str) -> float:
    if isinstance(value, bool):
        raise PresetError(f"{field}: expected a number")
    try:
        number = float(value)
    except (ValueError, TypeError) as err:
        raise PresetError(f"{field}: expected a number") from err
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise PresetError(f"{field}: value outside the range 0–{maximum:g}")
    return number


def validate_preset(data: object) -> dict:
    """Return a normalized copy, keeping the version-1 storage shape."""
    if not isinstance(data, dict) or set(data) != {"work_mode", "solar_sell", "slots"}:
        raise PresetError("A preset requires Work Mode, Solar Sell, and six slots")
    if data["work_mode"] not in WORK_MODES:
        raise PresetError("Unsupported Work Mode")
    if not isinstance(data["solar_sell"], bool):
        raise PresetError("Solar Sell must be a boolean")
    slots = data["slots"]
    if not isinstance(slots, list) or len(slots) != 6:
        raise PresetError("A preset must have exactly six slots")
    result = {"work_mode": data["work_mode"], "solar_sell": data["solar_sell"], "slots": []}
    starts = []
    for index, slot in enumerate(slots, 1):
        if not isinstance(slot, dict) or set(slot) != SLOT_KEYS:
            raise PresetError(f"Slot {index}: missing or extra fields")
        start = slot["start"]
        if not isinstance(start, str) or START_PATTERN.fullmatch(start) is None:
            raise PresetError(f"Slot {index}: invalid start time")
        if not isinstance(slot["grid_charge"], bool) or not isinstance(slot["gen"], bool):
            raise PresetError(f"Slot {index}: Grid Charge and Gen must be booleans")
        starts.append(start)
        result["slots"].append({
            "start": start,
            "soc": _number(slot["soc"], 100, f"Slot {index} SOC"),
            "power": _number(slot["power"], 12000, f"Slot {index} power"),
            "grid_charge": slot["grid_charge"],
            "gen": slot["gen"],
        })
    if starts != sorted(set(starts)):
        raise PresetError("Start times must be unique and increasing from slot 1 to 6")
    return result

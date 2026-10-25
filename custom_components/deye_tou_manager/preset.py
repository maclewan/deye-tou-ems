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
        raise PresetError(f"{field}: oczekiwano liczby")
    try:
        number = float(value)
    except (ValueError, TypeError) as err:
        raise PresetError(f"{field}: oczekiwano liczby") from err
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise PresetError(f"{field}: wartość poza zakresem 0–{maximum:g}")
    return number


def validate_preset(data: object) -> dict:
    """Return a normalized copy, keeping the version-1 storage shape."""
    if not isinstance(data, dict) or set(data) != {"work_mode", "solar_sell", "slots"}:
        raise PresetError("Preset wymaga Work Mode, Solar Sell i sześciu slotów")
    if data["work_mode"] not in WORK_MODES:
        raise PresetError("Nieobsługiwany Work Mode")
    if not isinstance(data["solar_sell"], bool):
        raise PresetError("Solar Sell musi być przełącznikiem")
    slots = data["slots"]
    if not isinstance(slots, list) or len(slots) != 6:
        raise PresetError("Preset musi mieć dokładnie sześć slotów")
    result = {"work_mode": data["work_mode"], "solar_sell": data["solar_sell"], "slots": []}
    starts = []
    for index, slot in enumerate(slots, 1):
        if not isinstance(slot, dict) or set(slot) != SLOT_KEYS:
            raise PresetError(f"Slot {index}: niepełne lub dodatkowe pola")
        start = slot["start"]
        if not isinstance(start, str) or START_PATTERN.fullmatch(start) is None:
            raise PresetError(f"Slot {index}: nieprawidłowa godzina startu")
        if not isinstance(slot["grid_charge"], bool) or not isinstance(slot["gen"], bool):
            raise PresetError(f"Slot {index}: Grid Charge i Gen muszą być przełącznikami")
        starts.append(start)
        result["slots"].append({
            "start": start,
            "soc": _number(slot["soc"], 100, f"Slot {index} SOC"),
            "power": _number(slot["power"], 12000, f"Slot {index} moc"),
            "grid_charge": slot["grid_charge"],
            "gen": slot["gen"],
        })
    if starts != sorted(set(starts)):
        raise PresetError("Godziny startu muszą być unikalne i rosnące od slotu 1 do 6")
    return result

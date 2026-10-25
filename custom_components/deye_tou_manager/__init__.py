"""Store named Deye TOU presets and optionally apply day assignments."""
from __future__ import annotations

import asyncio
import copy
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .preset import PresetError, validate_preset as validate_preset_data

DOMAIN = "deye_tou_manager"
ENTITY = "sensor.deye_tou_preset_manager"
CONF_WORK_MODE_ENTITY = "work_mode_entity"
WORK_MODE_SUFFIX = "_system_work_mode"
LEGACY_WORK_MODE_ENTITY = "select.deye_inverter_esp32_system_work_mode"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_LOGGER = logging.getLogger(__name__)
CARD_URL = "/api/deye_tou_manager/deye-tou-manager-card.js"
CARD_VERSION = "0.4.4"
CARD_RESOURCE_URL = f"{CARD_URL}?v={CARD_VERSION}"
CARD_PATH = Path(__file__).parent / "frontend" / "deye-tou-manager-card.js"
OLD_CARD_URL = "/local/deye-tou-manager-card.js"


def _card_resource_path(url: object) -> str | None:
    """Recognize only this card's local resource URLs."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme or parts.netloc:
        return None
    return parts.path if parts.path in (OLD_CARD_URL, CARD_URL) else None


async def async_register_dashboard_resource(hass: HomeAssistant) -> None:
    """Install or migrate this card's storage-mode Lovelace resource."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        _LOGGER.warning("Lovelace is not ready; add the Deye TOU card resource manually")
        return
    if getattr(lovelace, "resource_mode", None) != "storage":
        _LOGGER.info("Lovelace resources use YAML; configure the Deye TOU card URL in YAML")
        return

    try:
        resources = lovelace.resources
        # Lovelace resource storage may be lazy-loaded at startup. Inspecting
        # or creating items before loading can overwrite unrelated resources.
        await resources.async_get_info()
        if not resources.loaded:
            raise HomeAssistantError("Lovelace resources were not loaded")

        matches = [
            item for item in resources.async_items()
            if _card_resource_path(item.get("url")) is not None
        ]
        keep = next(
            (item for item in matches if _card_resource_path(item["url"]) == CARD_URL),
            matches[0] if matches else None,
        )
        if keep is None:
            await resources.async_create_item({"url": CARD_RESOURCE_URL, "res_type": "module"})
        else:
            if keep["url"] != CARD_RESOURCE_URL or keep.get("type") != "module":
                await resources.async_update_item(
                    keep["id"], {"url": CARD_RESOURCE_URL, "res_type": "module"}
                )
            for item in matches:
                if item is not keep:
                    await resources.async_delete_item(item["id"])
    except Exception:
        _LOGGER.exception("Could not register the Deye TOU card; check dashboard resources")


def work_mode_candidates(hass: HomeAssistant) -> list[str]:
    """Find Work Mode selects, including registered but offline ESPHome entities."""
    registry = er.async_get(hass)
    candidates = {
        entry.entity_id for entry in registry.entities.values()
        if entry.platform == "esphome" and entry.disabled_by is None
        and entry.entity_id.startswith("select.")
        and entry.entity_id.endswith(WORK_MODE_SUFFIX)
    }
    for entity_id in hass.states.async_entity_ids("select"):
        if not entity_id.endswith(WORK_MODE_SUFFIX):
            continue
        entry = registry.async_get(entity_id)
        if entry is None or (entry.platform == "esphome" and entry.disabled_by is None):
            candidates.add(entity_id)
    return sorted(candidates)


def prefix_from_work_mode(entity_id: str) -> str:
    """Derive the shared entity prefix from the chosen Work Mode select."""
    if not isinstance(entity_id, str) or not entity_id.startswith("select."):
        raise HomeAssistantError("Choose a Work Mode select entity")
    object_id = entity_id.removeprefix("select.")
    prefix = object_id.removesuffix(WORK_MODE_SUFFIX)
    if not re.fullmatch(r"[a-z0-9_]+", prefix) or object_id != f"{prefix}{WORK_MODE_SUFFIX}":
        raise HomeAssistantError("The selected entity must end in _system_work_mode")
    return prefix


def resolve_work_mode_entity(hass: HomeAssistant, configured: str | None) -> str:
    """Keep old installations working but never guess between two new devices."""
    if configured:
        prefix_from_work_mode(configured)
        return configured
    candidates = work_mode_candidates(hass)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        _LOGGER.warning("No Deye Work Mode entity found yet; using the legacy entity ID")
        return LEGACY_WORK_MODE_ENTITY
    raise HomeAssistantError(
        "Multiple Work Mode entities found; choose work_mode_entity in Deye TOU Manager options"
    )


def eid(prefix: str, kind: str, suffix: str) -> str:
    return f"{kind}.{prefix}_{suffix}"


def slot_id(prefix: str, kind: str, slot: int, key: str) -> str:
    return eid(prefix, kind, f"time_of_use_{slot}_{key}")


def validate_preset(data: dict) -> dict:
    """Validate a saved offline configuration before publishing or applying."""
    try:
        return validate_preset_data(data)
    except PresetError as err:
        raise HomeAssistantError(str(err)) from err


def snapshot(hass: HomeAssistant, prefix: str) -> dict:
    """Read every input before saving; never persist incomplete snapshots."""
    def value(entity: str) -> str:
        state = hass.states.get(entity)
        if state is None or state.state in ("unknown", "unavailable", ""):
            raise HomeAssistantError(f"Brak danych encji: {entity}")
        return state.state

    def switch_value(entity: str) -> bool:
        state = value(entity)
        if state not in ("on", "off"):
            raise HomeAssistantError(f"Nieprawidłowy stan przełącznika: {entity} = {state}")
        return state == "on"

    result = {
        "work_mode": value(eid(prefix, "select", "system_work_mode")),
        "solar_sell": switch_value(eid(prefix, "switch", "solar_sell")),
        "slots": [],
    }
    for n in range(1, 7):
        result["slots"].append({
            "start": value(slot_id(prefix, "time", n, "start")),
            "soc": float(value(slot_id(prefix, "number", n, "soc"))),
            "power": float(value(slot_id(prefix, "number", n, "out_power"))),
            "grid_charge": switch_value(slot_id(prefix, "switch", n, "grid_charge")),
            "gen": switch_value(slot_id(prefix, "switch", n, "gen")),
        })
    return validate_preset(result)


def control_states(hass: HomeAssistant, prefix: str) -> tuple[bool, bool]:
    """Require the main TOU switch and all seven day switches to be readable."""
    entities = [eid(prefix, "switch", "time_of_use")]
    entities.extend(eid(prefix, "switch", f"time_of_use_{day}") for day in DAYS)
    states = []
    for entity in entities:
        state = hass.states.get(entity)
        if state is None or state.state not in ("on", "off"):
            raise HomeAssistantError(f"Brak poprawnego stanu kontrolki: {entity}")
        states.append(state.state == "on")
    return states[0], all(states[1:])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the card and start legacy YAML installations."""
    await hass.http.async_register_static_paths([
        StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False),
    ])
    if DOMAIN in config:
        settings = config[DOMAIN] or {}
        await _async_start_manager(
            hass, yaml_configured=True,
            work_mode_entity=resolve_work_mode_entity(
                hass, settings.get(CONF_WORK_MODE_ENTITY)
            ),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start a UI-configured installation without requiring YAML."""
    if DOMAIN not in hass.data:
        await _async_start_manager(
            hass, yaml_configured=False,
            work_mode_entity=resolve_work_mode_entity(
                hass, entry.options.get(
                    CONF_WORK_MODE_ENTITY, entry.data.get(CONF_WORK_MODE_ENTITY)
                )
            ),
        )
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply a changed Work Mode selection without restarting HA."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop a UI installation while retaining any active YAML installation."""
    runtime = hass.data.get(DOMAIN)
    if runtime is None or runtime["yaml_configured"]:
        return True
    runtime["active"] = False
    runtime["unsub_time"]()
    runtime["unsub_start"]()
    for service in ("save_current", "save_definition", "delete", "assign_day", "apply", "set_auto"):
        hass.services.async_remove(DOMAIN, service)
    hass.states.async_remove(ENTITY)
    hass.data.pop(DOMAIN)
    return True


async def _async_start_manager(
    hass: HomeAssistant, *, yaml_configured: bool, work_mode_entity: str
) -> None:
    """Initialize the one shared manager for YAML or UI configuration."""
    prefix = prefix_from_work_mode(work_mode_entity)
    await async_register_dashboard_resource(hass)
    store = Store(hass, 1, DOMAIN)
    saved = await store.async_load() or {}
    presets = saved.get("presets", {})
    assignments = {day: saved.get("assignments", {}).get(day, "") for day in DAYS}
    auto_enabled = bool(saved.get("auto_enabled", False))
    last_automatic = saved.get("last_automatic", "Nie uruchamiano")
    previous_entity = saved.get(
        CONF_WORK_MODE_ENTITY, LEGACY_WORK_MODE_ENTITY if saved else work_mode_entity
    )
    if previous_entity != work_mode_entity and auto_enabled:
        auto_enabled = False
        _LOGGER.warning(
            "Deye Work Mode target changed from %s to %s; weekly schedule disabled",
            previous_entity, work_mode_entity,
        )
    if saved.get(CONF_WORK_MODE_ENTITY) != work_mode_entity or saved.get("auto_enabled") != auto_enabled:
        await store.async_save({
            "presets": presets, "assignments": assignments,
            "auto_enabled": auto_enabled, "last_automatic": last_automatic,
            CONF_WORK_MODE_ENTITY: work_mode_entity,
        })
    lock = asyncio.Lock()
    runtime = {
        "active": True, "yaml_configured": yaml_configured,
        "work_mode_entity": work_mode_entity,
    }

    def publish() -> None:
        hass.states.async_set(ENTITY, str(len(presets)), {
            "friendly_name": "Deye TOU - menedżer presetów",
            "presets": copy.deepcopy(presets),
            "assignments": assignments.copy(),
            "auto_enabled": auto_enabled,
            "work_mode_entity": work_mode_entity,
            "last_automatic": last_automatic,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
        })

    async def persist() -> None:
        await store.async_save({
            "presets": presets, "assignments": assignments,
            "auto_enabled": auto_enabled, "last_automatic": last_automatic,
            CONF_WORK_MODE_ENTITY: work_mode_entity,
        })
        publish()

    async def save_current(call: ServiceCall) -> None:
        name = call.data["name"].strip()
        async with lock:
            if name in presets and not call.data.get("overwrite", False):
                raise HomeAssistantError("Preset istnieje. Włącz nadpisanie, aby go zaktualizować.")
            data = snapshot(hass, prefix)
            presets[name] = data
            await persist()

    async def save_definition(call: ServiceCall) -> None:
        """Create or update a preset without contacting the inverter."""
        name = call.data["name"].strip()
        async with lock:
            if name in presets and not call.data.get("overwrite", False):
                raise HomeAssistantError("Preset istnieje. Użyj edycji lub innej nazwy.")
            data = validate_preset(call.data["preset"])
            presets[name] = data
            await persist()

    async def delete(call: ServiceCall) -> None:
        name = call.data["name"]
        async with lock:
            if name not in presets:
                raise HomeAssistantError("Nie ma takiego presetu")
            del presets[name]
            for day in DAYS:
                if assignments[day] == name:
                    assignments[day] = ""
            await persist()

    async def assign(call: ServiceCall) -> None:
        day, name = call.data["day"], call.data["name"].strip()
        async with lock:
            if name and name not in presets:
                raise HomeAssistantError("Nie ma takiego presetu")
            assignments[day] = name
            await persist()

    async def apply_preset_locked(name: str, skip_if_current: bool = False) -> bool:
        """Apply under the shared lock; return False when already active."""
        if name not in presets:
            raise HomeAssistantError("Nie ma takiego presetu")
        preset = validate_preset(copy.deepcopy(presets[name]))
        live = snapshot(hass, prefix)
        tou_enabled, days_active = control_states(hass, prefix)
        if skip_if_current and live == preset and tou_enabled and days_active:
            return False

        async def write(domain: str, action: str, entity: str, data: dict | None = None):
            await hass.services.async_call(domain, action,
                {"entity_id": entity, **(data or {})}, blocking=True)

        async def wait_for_readback(expect_tou: bool) -> None:
            for _ in range(31):
                try:
                    live_tou, live_days = control_states(hass, prefix)
                    if snapshot(hass, prefix) == preset and live_days and live_tou == expect_tou:
                        return
                except (HomeAssistantError, ValueError, TypeError, vol.Invalid):
                    pass
                await asyncio.sleep(1)
            raise HomeAssistantError(
                "Deye nie potwierdził zapisanych ustawień. TOU pozostaje wyłączone; "
                "sprawdź logi i odczyty przed ręcznym włączeniem."
            )

        # All reads complete before touching the inverter. Keep TOU disabled
        # until ESPHome reports the requested configuration and all day flags.
        await write("switch", "turn_off", eid(prefix, "switch", "time_of_use"))
        try:
            await write("select", "select_option", work_mode_entity,
                        {"option": preset["work_mode"]})
            await write("switch", "turn_on" if preset["solar_sell"] else "turn_off",
                        eid(prefix, "switch", "solar_sell"))
            for idx, slot in enumerate(preset["slots"], 1):
                await write("time", "set_value", slot_id(prefix, "time", idx, "start"),
                            {"time": slot["start"]})
                await write("number", "set_value", slot_id(prefix, "number", idx, "soc"),
                            {"value": slot["soc"]})
                await write("number", "set_value", slot_id(prefix, "number", idx, "out_power"),
                            {"value": slot["power"]})
                await write("switch", "turn_on" if slot["grid_charge"] else "turn_off",
                            slot_id(prefix, "switch", idx, "grid_charge"))
                await write("switch", "turn_on" if slot["gen"] else "turn_off",
                            slot_id(prefix, "switch", idx, "gen"))
                await asyncio.sleep(0.3)
            await hass.services.async_call("switch", "turn_on", {
                "entity_id": [eid(prefix, "switch", f"time_of_use_{day}") for day in DAYS],
            }, blocking=True)
            await wait_for_readback(False)
            await write("switch", "turn_on", eid(prefix, "switch", "time_of_use"))
            await wait_for_readback(True)
        except Exception:
            try:
                await write("switch", "turn_off", eid(prefix, "switch", "time_of_use"))
            except Exception:
                _LOGGER.exception("Could not switch TOU off after a failed apply")
            raise
        _LOGGER.info("Applied Deye TOU preset %s", name)
        return True

    async def apply(call: ServiceCall) -> None:
        async with lock:
            await apply_preset_locked(call.data["name"])

    async def set_auto(call: ServiceCall) -> None:
        nonlocal auto_enabled
        async with lock:
            auto_enabled = call.data["enabled"]
            await persist()

    async def run_scheduled(reason: str) -> None:
        """Apply today's assignment after ESPHome reconnects, if enabled."""
        nonlocal last_automatic
        if not runtime["active"] or not auto_enabled:
            return
        # ESPHome may report unavailable immediately after Home Assistant starts.
        # Do not write anything until a complete snapshot can be read.
        for _ in range(36):
            if not runtime["active"] or not auto_enabled:
                return
            try:
                snapshot(hass, prefix)
                control_states(hass, prefix)
                break
            except (HomeAssistantError, ValueError, TypeError, vol.Invalid):
                await asyncio.sleep(5)
        else:
            _LOGGER.warning("Deye TOU automation skipped: ESPHome not ready")
            async with lock:
                if not runtime["active"] or not auto_enabled:
                    return
                last_automatic = f"{dt_util.now():%Y-%m-%d %H:%M} · ESPHome niedostępne"
                await persist()
            return

        day = DAYS[dt_util.now().weekday()]
        async with lock:
            if not runtime["active"] or not auto_enabled:
                return
            name = assignments.get(day, "")
            if not name or name not in presets:
                last_automatic = f"{dt_util.now():%Y-%m-%d %H:%M} · brak presetu na {day}"
                await persist()
                return
            try:
                changed = await apply_preset_locked(name, skip_if_current=True)
                result = f"zastosowano {name} ({reason})" if changed else f"{name} już aktywny"
                last_automatic = f"{dt_util.now():%Y-%m-%d %H:%M} · {result}"
            except Exception as err:
                last_automatic = f"{dt_util.now():%Y-%m-%d %H:%M} · BŁĄD {name}: {err}"
                _LOGGER.exception("Automatic Deye TOU apply failed for %s", name)
            await persist()

    name_schema = vol.All(str, lambda name: name.strip(), vol.Length(min=1, max=64))
    hass.services.async_register(DOMAIN, "save_current", save_current, schema=vol.Schema({
        vol.Required("name"): name_schema,
        vol.Optional("overwrite", default=False): bool,
    }))
    hass.services.async_register(DOMAIN, "save_definition", save_definition, schema=vol.Schema({
        vol.Required("name"): name_schema,
        vol.Required("preset"): dict,
        vol.Optional("overwrite", default=False): bool,
    }))
    hass.services.async_register(DOMAIN, "delete", delete, schema=vol.Schema({
        vol.Required("name"): name_schema,
    }))
    hass.services.async_register(DOMAIN, "assign_day", assign, schema=vol.Schema({
        vol.Required("day"): vol.In(DAYS),
        vol.Required("name"): str,
    }))
    hass.services.async_register(DOMAIN, "apply", apply, schema=vol.Schema({
        vol.Required("name"): name_schema,
    }))
    hass.services.async_register(DOMAIN, "set_auto", set_auto, schema=vol.Schema({
        vol.Required("enabled"): bool,
    }))

    @callback
    def at_midnight(_now) -> None:
        hass.async_create_task(run_scheduled("północ"))

    @callback
    def at_start(_event) -> None:
        hass.async_create_task(run_scheduled("start HA"))

    runtime["unsub_time"] = async_track_time_change(
        hass, at_midnight, hour=0, minute=0, second=15
    )
    runtime["unsub_start"] = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED, at_start
    )
    hass.data[DOMAIN] = runtime
    publish()

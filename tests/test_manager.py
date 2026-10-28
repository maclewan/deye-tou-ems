"""Behavior tests with a small HA service/state harness, without hardware writes."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import sys
import types
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "deye_tou_manager"
TEST_PREFIX = "deye_inverter_esp32"


class FakeState:
    def __init__(self, state, attributes=None):
        self.state = str(state)
        self.attributes = attributes or {}


class FakeStates(dict):
    def async_set(self, entity_id, state, attributes=None):
        self[entity_id] = FakeState(state, attributes)

    def async_remove(self, entity_id):
        self.pop(entity_id, None)

    def async_entity_ids(self, domain=None):
        return [entity_id for entity_id in self if domain is None or entity_id.startswith(f"{domain}.")]


class FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = "test-entry"
        self.listener = None

    def add_update_listener(self, listener):
        self.listener = listener
        return lambda: setattr(self, "listener", None)

    def async_on_unload(self, unsubscribe):
        self.unsubscribe = unsubscribe


class FakeStore:
    def __init__(self, hass, version, key):
        assert version == 1 and key == "deye_tou_manager"
        self.hass = hass

    async def async_load(self):
        return copy.deepcopy(self.hass.saved)

    async def async_save(self, data):
        self.hass.saved = copy.deepcopy(data)


class FakeServices:
    def __init__(self, hass):
        self.hass = hass
        self.handlers = {}
        self.writes = []
        self.fail_entity = None
        self.ignore_entity = None

    def async_register(self, domain, name, handler, schema=None):
        self.handlers[domain, name] = handler

    def async_remove(self, domain, name):
        self.handlers.pop((domain, name), None)

    async def async_call(self, domain, action, data, blocking=False):
        if domain == "deye_tou_manager":
            return await self.handlers[domain, action](SimpleNamespace(data=data))
        entity_ids = data["entity_id"]
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        self.writes.append((domain, action, copy.deepcopy(data)))
        for entity in entity_ids:
            if entity == self.fail_entity:
                raise RuntimeError(f"Simulated write failure: {entity}")
            if entity == self.ignore_entity:
                continue
            if action in ("turn_on", "turn_off"):
                state = "on" if action == "turn_on" else "off"
            elif action == "select_option":
                state = data["option"]
            elif domain == "time":
                state = data["time"]
            else:
                state = str(data["value"])
            self.hass.states.async_set(entity, state)


class FakeResources:
    def __init__(self, items=None):
        self.items = copy.deepcopy(items or [])
        self.loaded = False
        self.operations = []

    async def async_get_info(self):
        self.loaded = True
        self.operations.append("load")
        return {}

    def async_items(self):
        assert self.loaded
        return self.items.copy()

    async def async_create_item(self, data):
        assert self.loaded
        self.operations.append("create")
        item = {"id": str(len(self.items) + 1), "url": data["url"], "type": data["res_type"]}
        self.items.append(item)
        return item

    async def async_update_item(self, item_id, data):
        assert self.loaded
        self.operations.append("update")
        item = next(item for item in self.items if item["id"] == item_id)
        item.update(url=data["url"], type=data["res_type"])

    async def async_delete_item(self, item_id):
        assert self.loaded
        self.operations.append("delete")
        self.items = [item for item in self.items if item["id"] != item_id]


class FakeHass:
    def __init__(self, saved=None, resources=None, resource_mode="storage"):
        self.saved = copy.deepcopy(saved or {})
        self.states = FakeStates()
        self.registry_entities = {}
        self.services = FakeServices(self)
        self.resources = resources or FakeResources()
        self.data = {"lovelace": SimpleNamespace(
            resource_mode=resource_mode, resources=self.resources,
        )}
        self.static_paths = []
        self.listeners = {}
        self.midnight_callback = None
        self.evening_callback = None
        self.selling_tick_callback = None
        self.revenue_hour_callback = None
        self.tasks = []
        self.http = SimpleNamespace(async_register_static_paths=self.register_paths)
        self.bus = SimpleNamespace(async_listen_once=self.listen_once)
        self.config_entries = SimpleNamespace(async_reload=self.reload_entry)
        self.reloads = []

    async def reload_entry(self, entry_id):
        self.reloads.append(entry_id)

    async def register_paths(self, paths):
        self.static_paths.extend(paths)

    def listen_once(self, event, callback):
        self.listeners[event] = callback
        return lambda: self.listeners.pop(event, None)

    def async_create_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    async def finish_tasks(self):
        while self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()

    async def async_add_executor_job(self, target):
        return target()


def load_integration():
    """Provide HA interfaces and real preset validation to the integration."""
    ha = types.ModuleType("homeassistant")
    modules = {
        "homeassistant": ha,
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.http": types.ModuleType("homeassistant.components.http"),
        "homeassistant.components.lovelace": types.ModuleType("homeassistant.components.lovelace"),
        "homeassistant.config_entries": types.ModuleType("homeassistant.config_entries"),
        "homeassistant.const": types.ModuleType("homeassistant.const"),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.exceptions": types.ModuleType("homeassistant.exceptions"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.event": types.ModuleType("homeassistant.helpers.event"),
        "homeassistant.helpers.entity_registry": types.ModuleType("homeassistant.helpers.entity_registry"),
        "homeassistant.helpers.storage": types.ModuleType("homeassistant.helpers.storage"),
        "homeassistant.util": types.ModuleType("homeassistant.util"),
        "homeassistant.util.dt": types.ModuleType("homeassistant.util.dt"),
        "voluptuous": types.ModuleType("voluptuous"),
    }
    modules["homeassistant.components.http"].StaticPathConfig = lambda url, path, cache_headers: SimpleNamespace(url=url, path=path, cache_headers=cache_headers)
    modules["homeassistant.components.lovelace"].LOVELACE_DATA = "lovelace"
    modules["homeassistant.config_entries"].ConfigEntry = SimpleNamespace
    modules["homeassistant.const"].EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    modules["homeassistant.core"].HomeAssistant = FakeHass
    modules["homeassistant.core"].ServiceCall = SimpleNamespace
    modules["homeassistant.core"].callback = lambda method: method
    modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    def track_time(hass, callback, **kwargs):
        field = ("evening_callback" if kwargs.get("hour") == 18 else
                 "revenue_hour_callback" if kwargs.get("minute") == 0 and kwargs.get("second") == 5 else
                 "midnight_callback")
        setattr(hass, field, callback)
        return lambda: setattr(hass, field, None)
    modules["homeassistant.helpers.event"].async_track_time_change = track_time
    def track_interval(hass, callback, _interval):
        hass.selling_tick_callback = callback
        return lambda: setattr(hass, "selling_tick_callback", None)
    modules["homeassistant.helpers.event"].async_track_time_interval = track_interval
    modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: SimpleNamespace(
        entities=hass.registry_entities,
        async_get=lambda entity_id: hass.registry_entities.get(entity_id),
    )
    modules["homeassistant.helpers.storage"].Store = FakeStore
    modules["homeassistant.util"].dt = modules["homeassistant.util.dt"]
    modules["homeassistant.util.dt"].now = lambda: datetime(2026, 10, 26, 0, 0, 15)
    vol = modules["voluptuous"]
    vol.Schema = lambda value: value
    vol.Required = lambda key: key
    vol.Optional = lambda key, default=None: key
    vol.All = lambda *validators: validators
    vol.Length = lambda **kwargs: kwargs
    vol.In = lambda values: values
    vol.Invalid = type("Invalid", (Exception,), {})
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            "deye_test_package", INTEGRATION / "__init__.py",
            submodule_search_locations=[str(INTEGRATION)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


MANAGER = load_integration()


def load_config_flow():
    """Load the UI flow against the same minimal Home Assistant interfaces."""
    config_entries = types.ModuleType("homeassistant.config_entries")

    class FakeConfigFlow:
        def __init_subclass__(cls, **kwargs):
            if "domain" in kwargs:
                cls.domain = kwargs["domain"]

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

    config_entries.ConfigFlow = FakeConfigFlow
    config_entries.OptionsFlow = FakeConfigFlow
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.config_entries = config_entries
    core = types.ModuleType("homeassistant.core")
    core.callback = lambda method: method
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Schema = lambda schema: schema
    voluptuous.Required = lambda key, default=None: key
    voluptuous.In = lambda values: values
    with patch.dict(sys.modules, {
        "deye_test_package": MANAGER,
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "voluptuous": voluptuous,
    }):
        spec = importlib.util.spec_from_file_location(
            "deye_test_package.config_flow", INTEGRATION / "config_flow.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


CONFIG_FLOW = load_config_flow()


def sample_preset():
    return {
        "work_mode": "Zero Export To CT", "solar_sell": True,
        "slots": [
            {"start": f"{hour:02d}:00:00", "soc": 20 + index * 10,
             "power": 12000, "grid_charge": index % 2 == 0, "gen": False}
            for index, hour in enumerate((0, 4, 8, 12, 16, 20))
        ],
    }


def put_live(hass, preset, prefix=TEST_PREFIX):
    hass.states.async_set(MANAGER.eid(prefix, "select", "system_work_mode"), preset["work_mode"])
    hass.states.async_set(MANAGER.eid(prefix, "switch", "solar_sell"), "on" if preset["solar_sell"] else "off")
    hass.states.async_set(MANAGER.eid(prefix, "switch", "time_of_use"), "on")
    for day in MANAGER.DAYS:
        hass.states.async_set(MANAGER.eid(prefix, "switch", f"time_of_use_{day}"), "on")
    for index, slot in enumerate(preset["slots"], 1):
        for domain, key, value in (
            ("time", "start", slot["start"]),
            ("number", "soc", slot["soc"]),
            ("number", "out_power", slot["power"]),
            ("switch", "grid_charge", "on" if slot["grid_charge"] else "off"),
            ("switch", "gen", "on" if slot["gen"] else "off"),
        ):
            hass.states.async_set(MANAGER.slot_id(prefix, domain, index, key), value)


def put_rce_prices(hass, day, suffix, high_hour=18, high_price=900):
    entity_id = f"sensor.rce_pse_{suffix}"
    unique_id = "rce_pse_today_price" if suffix == "price" else "rce_pse_tomorrow_price"
    hass.registry_entities[entity_id] = SimpleNamespace(
        entity_id=entity_id, platform="rce_pse", unique_id=unique_id, disabled_by=None,
    )
    records = []
    for hour in range(24):
        for minute in (0, 15, 30, 45):
            start = datetime.combine(day, time()) + timedelta(hours=hour, minutes=minute)
            end = start + timedelta(minutes=15)
            records.append({
                "business_date": day.isoformat(), "period": f"{start:%H:%M} - {end:%H:%M}",
                "dtime": end.strftime("%Y-%m-%d %H:%M:%S"),
                "rce_pln": high_price if hour == high_hour else 100,
            })
    hass.states.async_set(entity_id, "100", {"unit_of_measurement": "PLN/MWh", "prices": records})
    return entity_id


async def no_delay(_seconds):
    return None


class PresetValidationTests(unittest.TestCase):
    def test_accepts_six_slots_and_normalizes_numbers(self):
        result = MANAGER.validate_preset(sample_preset())
        self.assertEqual(len(result["slots"]), 6)
        self.assertEqual(result["slots"][0]["power"], 12000.0)

    def test_rejects_bad_times_numbers_and_flags(self):
        for mutation in (
            lambda p: p["slots"].pop(),
            lambda p: p["slots"][1].update(start=p["slots"][0]["start"]),
            lambda p: p["slots"][0].update(soc=float("nan")),
            lambda p: p["slots"][0].update(power=12001),
            lambda p: p["slots"][0].update(gen="off"),
            lambda p: p.update(work_mode="Other"),
        ):
            with self.subTest(mutation=mutation):
                preset = sample_preset()
                mutation(preset)
                with self.assertRaises(Exception):
                    MANAGER.validate_preset(preset)


class RevenueCalculationTests(unittest.TestCase):
    def test_hour_uses_net_export_and_rce_price(self):
        result = MANAGER.measured_hour(
            "1234", "1240", "900", "902", "kWh", "kWh", 0.75,
        )
        self.assertEqual(result["exported_kwh"], 6.0)
        self.assertEqual(result["imported_kwh"], 2.0)
        self.assertEqual(result["net_exported_kwh"], 4.0)
        self.assertEqual(result["revenue_pln"], 3.0)

    def test_negative_net_export_is_ignored(self):
        result = MANAGER.measured_hour(100, 101, 50, 53, "kWh", "kWh", 1.2)
        self.assertEqual(result["net_exported_kwh"], 0.0)
        self.assertEqual(result["revenue_pln"], 0.0)

    def test_counter_reset_is_not_recorded(self):
        with self.assertRaises(MANAGER.RevenueError):
            MANAGER.measured_hour(100, 99, 50, 50, "kWh", "kWh", 1)


class RevenueLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_zero_net_export_rows_are_removed_on_startup(self):
        hass = FakeHass({
            "preset_schema": 2, "presets": {}, "assignments": {}, "auto_enabled": False,
            "selling": {},
            "revenue": {"settings": {}, "hours": {
                "2026-10-25T12:00:00": {
                    "hour": "2026-10-25T12:00:00", "net_exported_kwh": 0,
                    "revenue_pln": 0,
                },
                "2026-10-25T13:00:00": {
                    "hour": "2026-10-25T13:00:00", "net_exported_kwh": 1.5,
                    "revenue_pln": 1,
                },
            }},
        })
        put_live(hass, sample_preset())
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual(list(hass.saved["revenue"]["hours"]), ["2026-10-25T13:00:00"])

    async def test_completed_hour_is_saved_and_exposed_in_all_time_totals(self):
        hass = FakeHass()
        put_live(hass, sample_preset())
        export, imported = "sensor.grid_export_total", "sensor.grid_import_total"
        meter_attributes = {"unit_of_measurement": "kWh"}
        hass.states.async_set(export, 106, meter_attributes)
        hass.states.async_set(imported, 52, meter_attributes)
        price_entity = put_rce_prices(hass, date(2026, 10, 25), "price", high_hour=23, high_price=750)
        start = datetime(2026, 10, 25, 23)
        end = start + timedelta(hours=1)
        hass.history = {
            export: [
                SimpleNamespace(state="100", attributes=meter_attributes, last_updated=start),
                SimpleNamespace(state="106", attributes=meter_attributes, last_updated=end),
            ],
            imported: [
                SimpleNamespace(state="50", attributes=meter_attributes, last_updated=start),
                SimpleNamespace(state="52", attributes=meter_attributes, last_updated=end),
            ],
            price_entity: [
                SimpleNamespace(
                    state="100", attributes=hass.states[price_entity].attributes,
                    last_updated=start,
                ),
            ],
        }
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        history.get_significant_states = lambda *_args: hass.history
        recorder.history = history
        with patch.dict(sys.modules, {
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        }):
            await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {
                MANAGER.CONF_TODAY_PRICE_ENTITY: price_entity,
                MANAGER.CONF_EXPORT_ENERGY_ENTITY: export,
                MANAGER.CONF_IMPORT_ENERGY_ENTITY: imported,
            }})
            hass.revenue_hour_callback(None)
            await hass.finish_tasks()
        self.assertEqual(hass.states[MANAGER.REVENUE_ENTITY].state, "3.0")
        self.assertEqual(hass.states[MANAGER.NET_EXPORT_ENTITY].state, "4.0")
        records = hass.saved["revenue"]["hours"]
        self.assertEqual(len(records), 1)
        self.assertEqual(next(iter(records.values()))["price_pln_per_kwh"], 0.75)


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_selects_detected_inverter(self):
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow()
        flow.hass = FakeHass()
        put_live(flow.hass, sample_preset(), prefix="my_deye")
        self.assertEqual(flow.domain, MANAGER.DOMAIN)
        self.assertEqual((await flow.async_step_user())["type"], "form")
        self.assertEqual(await flow.async_step_user({MANAGER.CONF_WORK_MODE_ENTITY: "select.my_deye_system_work_mode"}), {
            "type": "create_entry", "title": "Deye TOU Preset Manager",
            "data": {
                MANAGER.CONF_WORK_MODE_ENTITY: "select.my_deye_system_work_mode",
                MANAGER.CONF_EXPORT_ENERGY_ENTITY: "",
                MANAGER.CONF_IMPORT_ENERGY_ENTITY: "",
            },
        })

    async def test_no_candidate_aborts_setup(self):
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow()
        flow.hass = FakeHass()
        self.assertEqual(await flow.async_step_user(), {
            "type": "abort", "reason": "no_compatible_entities",
        })

    async def test_offline_esphome_registry_entity_is_selectable(self):
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow()
        flow.hass = FakeHass()
        entity_id = "select.remote_deye_system_work_mode"
        flow.hass.registry_entities[entity_id] = SimpleNamespace(
            entity_id=entity_id, platform="esphome", disabled_by=None,
        )
        self.assertEqual(await flow.async_step_user({MANAGER.CONF_WORK_MODE_ENTITY: entity_id}), {
            "type": "create_entry", "title": "Deye TOU Preset Manager",
            "data": {
                MANAGER.CONF_WORK_MODE_ENTITY: entity_id,
                MANAGER.CONF_EXPORT_ENERGY_ENTITY: "",
                MANAGER.CONF_IMPORT_ENERGY_ENTITY: "",
            },
        })

    async def test_options_choose_new_inverter(self):
        entry = FakeEntry(data={MANAGER.CONF_WORK_MODE_ENTITY: "select.old_system_work_mode"})
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow.async_get_options_flow(entry)
        flow.config_entry = entry
        flow.hass = FakeHass()
        put_live(flow.hass, sample_preset(), prefix="new")
        self.assertEqual((await flow.async_step_init())["type"], "form")
        self.assertEqual(await flow.async_step_init({
            MANAGER.CONF_WORK_MODE_ENTITY: "select.new_system_work_mode",
            MANAGER.CONF_TODAY_PRICE_ENTITY: "",
            MANAGER.CONF_TOMORROW_PRICE_ENTITY: "",
            MANAGER.CONF_BATTERY_SOC_ENTITY: "sensor.new_battery_bms_soc",
            MANAGER.CONF_EXPORT_ENERGY_ENTITY: "",
            MANAGER.CONF_IMPORT_ENERGY_ENTITY: "",
        }), {
            "type": "create_entry", "title": "",
            "data": {
                MANAGER.CONF_WORK_MODE_ENTITY: "select.new_system_work_mode",
                MANAGER.CONF_TODAY_PRICE_ENTITY: "",
                MANAGER.CONF_TOMORROW_PRICE_ENTITY: "",
                MANAGER.CONF_BATTERY_SOC_ENTITY: "sensor.new_battery_bms_soc",
                MANAGER.CONF_EXPORT_ENERGY_ENTITY: "",
                MANAGER.CONF_IMPORT_ENERGY_ENTITY: "",
            },
        })

    async def test_options_can_select_rce_price_entities(self):
        entry = FakeEntry(data={MANAGER.CONF_WORK_MODE_ENTITY: "select.old_system_work_mode"})
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow.async_get_options_flow(entry)
        flow.config_entry = entry
        flow.hass = FakeHass()
        put_live(flow.hass, sample_preset(), prefix="new")
        today = put_rce_prices(flow.hass, date(2026, 10, 26), "price")
        tomorrow = put_rce_prices(flow.hass, date(2026, 10, 27), "price_tomorrow")
        self.assertEqual((await flow.async_step_init())["type"], "form")
        result = await flow.async_step_init({
            MANAGER.CONF_WORK_MODE_ENTITY: "select.new_system_work_mode",
            MANAGER.CONF_TODAY_PRICE_ENTITY: today,
            MANAGER.CONF_TOMORROW_PRICE_ENTITY: tomorrow,
            MANAGER.CONF_BATTERY_SOC_ENTITY: "sensor.new_battery_bms_soc",
            MANAGER.CONF_EXPORT_ENERGY_ENTITY: "",
            MANAGER.CONF_IMPORT_ENERGY_ENTITY: "",
        })
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][MANAGER.CONF_TODAY_PRICE_ENTITY], today)
        self.assertEqual(result["data"][MANAGER.CONF_TOMORROW_PRICE_ENTITY], tomorrow)

    async def test_setup_can_select_cumulative_energy_meters(self):
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow()
        flow.hass = FakeHass()
        put_live(flow.hass, sample_preset(), prefix="my_deye")
        export = "sensor.grid_export_total"
        imported = "sensor.grid_import_total"
        attributes = {
            "device_class": "energy", "state_class": "total_increasing",
            "unit_of_measurement": "kWh",
        }
        flow.hass.states.async_set(export, 100, attributes)
        flow.hass.states.async_set(imported, 50, attributes)
        result = await flow.async_step_user({
            MANAGER.CONF_WORK_MODE_ENTITY: "select.my_deye_system_work_mode",
            MANAGER.CONF_EXPORT_ENERGY_ENTITY: export,
            MANAGER.CONF_IMPORT_ENERGY_ENTITY: imported,
        })
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][MANAGER.CONF_EXPORT_ENERGY_ENTITY], export)
        self.assertEqual(result["data"][MANAGER.CONF_IMPORT_ENERGY_ENTITY], imported)


class ResourceAndSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_entry_options_set_the_price_entities_used_by_selling(self):
        hass = FakeHass()
        put_live(hass, sample_preset())
        today = put_rce_prices(hass, date(2026, 10, 26), "price")
        tomorrow = put_rce_prices(hass, date(2026, 10, 27), "price_tomorrow")
        entry = FakeEntry(
            data={MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_inverter_esp32_system_work_mode"},
            options={
                MANAGER.CONF_TODAY_PRICE_ENTITY: today,
                MANAGER.CONF_TOMORROW_PRICE_ENTITY: tomorrow,
            },
        )
        await MANAGER.async_setup_entry(hass, entry)
        settings = hass.states[MANAGER.ENTITY].attributes["selling"]["settings"]
        self.assertEqual(settings[MANAGER.CONF_TODAY_PRICE_ENTITY], today)
        self.assertEqual(settings[MANAGER.CONF_TOMORROW_PRICE_ENTITY], tomorrow)
        self.assertEqual(settings[MANAGER.CONF_BATTERY_SOC_ENTITY],
                         "sensor.deye_inverter_esp32_battery_bms_soc")

    async def test_auto_detects_one_nondefault_inverter_for_legacy_yaml(self):
        hass = FakeHass()
        put_live(hass, sample_preset(), prefix="my_deye")
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual(
            hass.states[MANAGER.ENTITY].attributes["work_mode_entity"],
            "select.my_deye_system_work_mode",
        )

    async def test_multiple_inverters_require_explicit_selection(self):
        hass = FakeHass()
        put_live(hass, sample_preset(), prefix="deye_a")
        put_live(hass, sample_preset(), prefix="deye_b")
        with self.assertRaisesRegex(Exception, "Multiple Work Mode"):
            await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual(hass.services.writes, [])

    async def test_yaml_can_select_one_of_multiple_inverters(self):
        hass = FakeHass()
        put_live(hass, sample_preset(), prefix="deye_a")
        put_live(hass, sample_preset(), prefix="deye_b")
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {
            MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_b_system_work_mode",
        }})
        self.assertEqual(
            hass.states[MANAGER.ENTITY].attributes["work_mode_entity"],
            "select.deye_b_system_work_mode",
        )

    async def test_saved_options_override_original_ui_choice(self):
        hass = FakeHass()
        put_live(hass, sample_preset(), prefix="deye_a")
        put_live(hass, sample_preset(), prefix="deye_b")
        await MANAGER.async_setup(hass, {})
        entry = FakeEntry(
            data={MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_a_system_work_mode"},
            options={MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_b_system_work_mode"},
        )
        await MANAGER.async_setup_entry(hass, entry)
        self.assertEqual(
            hass.states[MANAGER.ENTITY].attributes["work_mode_entity"],
            "select.deye_b_system_work_mode",
        )

    async def test_target_change_disables_existing_weekly_schedule(self):
        saved = {
            "presets": {"Target": sample_preset()},
            "assignments": {"monday": "Target"},
            "auto_enabled": True,
            MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_a_system_work_mode",
        }
        hass = FakeHass(saved)
        put_live(hass, sample_preset(), prefix="deye_a")
        put_live(hass, sample_preset(), prefix="deye_b")
        await MANAGER.async_setup(hass, {})
        entry = FakeEntry(data={
            MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_b_system_work_mode",
        })
        await MANAGER.async_setup_entry(hass, entry)
        self.assertFalse(hass.states[MANAGER.ENTITY].attributes["auto_enabled"])
        self.assertFalse(hass.saved["auto_enabled"])
        self.assertEqual(
            hass.saved["assignments"]["monday"],
            hass.states[MANAGER.ENTITY].attributes["preset_ids"]["Target"],
        )
        hass.midnight_callback(None)
        await hass.finish_tasks()
        self.assertEqual(hass.services.writes, [])

    async def test_chosen_inverter_is_only_one_written(self):
        hass = FakeHass()
        put_live(hass, sample_preset(), prefix="deye_a")
        put_live(hass, sample_preset(), prefix="deye_b")
        await MANAGER.async_setup(hass, {})
        entry = FakeEntry(data={
            MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_b_system_work_mode",
        })
        await MANAGER.async_setup_entry(hass, entry)
        target = sample_preset()
        target["slots"][0]["soc"] = 80
        await hass.services.async_call(MANAGER.DOMAIN, "save_definition", {
            "name": "Target", "preset": target,
        })
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            await hass.services.async_call(MANAGER.DOMAIN, "apply", {"name": "Target"})
        self.assertTrue(hass.services.writes)
        self.assertTrue(all(
            entity_id.startswith(("select.deye_b_", "switch.deye_b_", "number.deye_b_", "time.deye_b_"))
            for _, _, data in hass.services.writes
            for entity_id in ([data["entity_id"]] if isinstance(data["entity_id"], str) else data["entity_id"])
        ))
        self.assertEqual(
            hass.states[MANAGER.eid("deye_a", "number", "time_of_use_1_soc")].state,
            "20",
        )

    async def test_options_change_triggers_reload(self):
        hass = FakeHass()
        put_live(hass, sample_preset())
        await MANAGER.async_setup(hass, {})
        entry = FakeEntry(data={MANAGER.CONF_WORK_MODE_ENTITY: MANAGER.LEGACY_WORK_MODE_ENTITY})
        await MANAGER.async_setup_entry(hass, entry)
        await entry.listener(hass, entry)
        self.assertEqual(hass.reloads, [entry.entry_id])

    async def test_ui_entry_starts_and_unloads_without_yaml(self):
        hass = FakeHass()
        await MANAGER.async_setup(hass, {})
        self.assertNotIn(MANAGER.ENTITY, hass.states)
        self.assertEqual(hass.resources.items, [])
        entry = FakeEntry()
        self.assertTrue(await MANAGER.async_setup_entry(hass, entry))
        self.assertIn(MANAGER.ENTITY, hass.states)
        self.assertEqual(len(hass.resources.items), 1)
        self.assertTrue(await MANAGER.async_unload_entry(hass, entry))
        self.assertNotIn(MANAGER.ENTITY, hass.states)
        self.assertIsNone(hass.midnight_callback)
        self.assertEqual(hass.services.handlers, {})
        self.assertTrue(await MANAGER.async_setup_entry(hass, entry))
        self.assertIn(MANAGER.ENTITY, hass.states)

    async def test_migrates_old_resource_without_touching_other_cards(self):
        resources = FakeResources([
            {"id": "old", "url": "/local/deye-tou-manager-card.js?v=3", "type": "module"},
            {"id": "other", "url": "/local/another-card.js", "type": "module"},
        ])
        hass = FakeHass(resources=resources)
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual(resources.items[0]["url"], MANAGER.CARD_RESOURCE_URL)
        self.assertEqual(resources.items[1]["url"], "/local/another-card.js")
        self.assertEqual(resources.operations, ["load", "update"])

    async def test_deduplicates_card_resources_and_is_idempotent(self):
        resources = FakeResources([
            {"id": "old", "url": "/local/deye-tou-manager-card.js?v=3", "type": "module"},
            {"id": "new", "url": "/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.0", "type": "module"},
            {"id": "duplicate", "url": "/api/deye_tou_manager/deye-tou-manager-card.js?v=0.3.0", "type": "module"},
        ])
        hass = FakeHass(resources=resources)
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual([(item["id"], item["url"]) for item in resources.items],
                         [("new", MANAGER.CARD_RESOURCE_URL)])
        operations = resources.operations.copy()
        await MANAGER.async_register_dashboard_resource(hass)
        self.assertEqual(resources.operations, operations + ["load"])

    async def test_yaml_resource_mode_is_not_modified(self):
        resources = FakeResources([
            {"id": "old", "url": "/local/deye-tou-manager-card.js?v=3", "type": "module"},
        ])
        hass = FakeHass(resources=resources, resource_mode="yaml")
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        self.assertEqual(resources.items[0]["url"], "/local/deye-tou-manager-card.js?v=3")
        self.assertEqual(resources.operations, [])

    async def test_ui_entry_does_not_stop_yaml_installation(self):
        hass = FakeHass()
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        entry = FakeEntry()
        await MANAGER.async_setup_entry(hass, entry)
        self.assertTrue(await MANAGER.async_unload_entry(hass, entry))
        self.assertIn(MANAGER.ENTITY, hass.states)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        put_live(self.hass, sample_preset())
        await MANAGER.async_setup(self.hass, {MANAGER.DOMAIN: {}})

    async def call(self, service, **data):
        await self.hass.services.async_call(MANAGER.DOMAIN, service, data, blocking=True)

    async def test_setup_restores_store_and_auto_defaults_off(self):
        self.assertEqual(self.hass.static_paths[0].url, MANAGER.CARD_URL)
        self.assertEqual(self.hass.static_paths[0].path, str(MANAGER.CARD_PATH))
        self.assertEqual(len(self.hass.static_paths), 3)
        for path, language in zip(self.hass.static_paths[1:], ("en", "pl")):
            self.assertEqual(path.url, MANAGER.CARD_TRANSLATION_URL.format(language=language))
            self.assertEqual(path.path, str(MANAGER.CARD_TRANSLATION_PATH).format(language=language))
        self.assertEqual(self.hass.resources.items[0]["url"], MANAGER.CARD_RESOURCE_URL)
        self.assertEqual(self.hass.resources.operations[:2], ["load", "create"])
        self.assertFalse(self.hass.states[MANAGER.ENTITY].attributes["auto_enabled"])
        self.assertEqual(self.hass.saved["preset_schema"], 2)
        self.hass.listeners["homeassistant_started"](None)
        self.hass.midnight_callback(None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])

    async def test_semi_selling_card_plan_and_approval_are_persisted_without_writes(self):
        price_entity = put_rce_prices(self.hass, date(2026, 10, 27), "price_tomorrow")
        for record in self.hass.states[price_entity].attributes["prices"]:
            if record["period"].startswith("19:"):
                record["rce_pln"] = 800
        await self.call("set_selling_settings", mode="semi", threshold=.5,
                        max_ranges=2, time_of_day="afternoon", min_soc=30)
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            self.hass.evening_callback(None)
            await self.hass.finish_tasks()
        selling = self.hass.states[MANAGER.ENTITY].attributes["selling"]
        plan = selling["plans"]["2026-10-27"]
        self.assertEqual((plan["ranges"][0]["start"], plan["ranges"][0]["end"]),
                         ("18:00", "19:00"))
        self.assertFalse(plan["ranges"][0]["approved"])
        self.assertFalse(plan["ranges"][1]["approved"])
        await self.call("approve_selling_range", date="2026-10-27", start="18:00", approved=True)
        self.assertTrue(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][0]["approved"])
        self.assertFalse(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][1]["approved"])
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("refresh_selling_plan", day="tomorrow")
        self.assertTrue(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][0]["approved"])
        self.assertFalse(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][1]["approved"])
        put_rce_prices(self.hass, date(2026, 10, 27), "price_tomorrow", high_hour=17)
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("refresh_selling_plan", day="tomorrow")
        self.assertFalse(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][0]["approved"])
        self.assertEqual(self.hass.services.writes, [])

    async def test_automatic_selling_approves_only_after_midnight_recheck(self):
        tomorrow_entity = put_rce_prices(self.hass, date(2026, 10, 27), "price_tomorrow")
        today_entity = put_rce_prices(self.hass, date(2026, 10, 27), "price")
        for entity in (tomorrow_entity, today_entity):
            for record in self.hass.states[entity].attributes["prices"]:
                if record["period"].startswith("19:"):
                    record["rce_pln"] = 800
        await self.call("set_selling_settings", mode="automatic", threshold=.5,
                        max_ranges=2, time_of_day="afternoon", min_soc=30)
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            self.hass.evening_callback(None)
            await self.hass.finish_tasks()
        self.assertFalse(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][0]["approved"])
        self.assertFalse(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][1]["approved"])
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 27, 0, 0, 15)):
            self.hass.midnight_callback(None)
            await self.hass.finish_tasks()
        self.assertTrue(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][0]["approved"])
        self.assertTrue(self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"][1]["approved"])
        self.assertEqual(self.hass.services.writes, [])

    async def test_missing_rce_prices_revokes_plan_approval(self):
        entity = put_rce_prices(self.hass, date(2026, 10, 27), "price_tomorrow")
        await self.call("set_selling_settings", mode="semi", threshold=.5)
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("refresh_selling_plan", day="tomorrow")
        self.assertIn("2026-10-27", self.hass.saved["selling"]["plans"])
        self.hass.states[entity].attributes["prices"] = []
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("refresh_selling_plan", day="tomorrow")
        self.assertNotIn("2026-10-27", self.hass.saved["selling"]["plans"])
        self.assertIn("complete 96-quarter", self.hass.saved["selling"]["error"])

    async def test_manual_selling_hour_survives_checks_and_can_be_cleared(self):
        put_rce_prices(self.hass, date(2026, 10, 27), "price_tomorrow")
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("set_selling_settings", mode="semi", threshold=.5,
                            max_ranges=2, time_of_day="afternoon", min_soc=30)
            await self.call("add_selling_range", date="2026-10-27", start="18:15", target_soc=45)
            await self.call("refresh_selling_plan", day="tomorrow")
        plan = self.hass.saved["selling"]["plans"]["2026-10-27"]
        manual = next(item for item in plan["ranges"] if item.get("manual"))
        self.assertEqual((manual["start"], manual["end"]), ("18:15", "19:15"))
        self.assertEqual(manual["target_soc"], 45)
        self.assertFalse(manual["approved"])
        await self.call("approve_selling_range", date="2026-10-27", start="18:15", approved=True)
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18)):
            await self.call("refresh_selling_plan", day="tomorrow")
        manual = next(item for item in self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"]
                      if item.get("manual"))
        self.assertTrue(manual["approved"])
        self.assertEqual(manual["target_soc"], 45)
        await self.call("set_selling_settings", threshold=.7)
        retained = self.hass.saved["selling"]["plans"]["2026-10-27"]["ranges"]
        self.assertEqual(len(retained), 1)
        self.assertTrue(retained[0]["manual"])
        await self.call("clear_selling_plans")
        self.assertEqual(self.hass.saved["selling"]["plans"], {})

    async def test_approved_selling_period_changes_only_mode_and_active_soc_then_restores(self):
        soc_entity = "sensor.deye_inverter_esp32_battery_bms_soc"
        self.hass.states.async_set(soc_entity, "80")
        now = datetime(2026, 10, 26, 18, 20)
        with patch.object(MANAGER.dt_util, "now", return_value=now):
            await self.call("set_selling_settings", mode="semi", control_enabled=True,
                            min_soc=35, battery_soc_entity=soc_entity)
            await self.call("add_selling_range", date="2026-10-26", start="18:15")
            await self.call("set_selling_range_soc", date="2026-10-26", start="18:15", target_soc=42)
            await self.call("approve_selling_range", date="2026-10-26", start="18:15", approved=True)
            self.hass.selling_tick_callback(None)
            await self.hass.finish_tasks()
        work_mode = MANAGER.eid(TEST_PREFIX, "select", "system_work_mode")
        active_soc = MANAGER.slot_id(TEST_PREFIX, "number", 5, "soc")
        self.assertEqual(self.hass.states[work_mode].state, "Selling First")
        self.assertEqual(self.hass.states[active_soc].state, "42.0")
        self.assertEqual(self.hass.saved["selling"]["session"]["slot"], 4)
        self.assertEqual(self.hass.saved["selling"]["session"]["snapshot"], sample_preset())
        self.hass.states.async_set(soc_entity, "42")
        with patch.object(MANAGER.dt_util, "now", return_value=now + timedelta(minutes=5)):
            self.hass.selling_tick_callback(None)
            await self.hass.finish_tasks()
        self.assertEqual(self.hass.states[work_mode].state, "Zero Export To CT")
        self.assertEqual(self.hass.states[active_soc].state, "60.0")
        selling_range = self.hass.saved["selling"]["plans"]["2026-10-26"]["ranges"][0]
        self.assertTrue(selling_range["completed"])
        self.assertEqual(selling_range["completion_reason"], "minimum SOC reached")
        writes_after_stop = len(self.hass.services.writes)
        self.hass.states.async_set(soc_entity, "50")
        with patch.object(MANAGER.dt_util, "now", return_value=now + timedelta(minutes=10)):
            self.hass.selling_tick_callback(None)
            await self.hass.finish_tasks()
        self.assertEqual(len(self.hass.services.writes), writes_after_stop)

    async def test_stop_selling_restores_and_completes_active_period(self):
        soc_entity = "sensor.deye_inverter_esp32_battery_bms_soc"
        self.hass.states.async_set(soc_entity, "80")
        now = datetime(2026, 10, 26, 18, 20)
        with patch.object(MANAGER.dt_util, "now", return_value=now):
            await self.call("set_selling_settings", mode="semi", control_enabled=True,
                            min_soc=35, battery_soc_entity=soc_entity)
            await self.call("add_selling_range", date="2026-10-26", start="18:15")
            await self.call("approve_selling_range", date="2026-10-26", start="18:15", approved=True)
            self.hass.selling_tick_callback(None)
            await self.hass.finish_tasks()
            await self.call("stop_selling")
        work_mode = MANAGER.eid(TEST_PREFIX, "select", "system_work_mode")
        self.assertEqual(self.hass.states[work_mode].state, "Zero Export To CT")
        selling_range = self.hass.saved["selling"]["plans"]["2026-10-26"]["ranges"][0]
        self.assertTrue(selling_range["completed"])
        self.assertEqual(selling_range["completion_reason"], "stopped manually")
        self.assertIsNone(self.hass.saved["selling"]["session"])

    async def test_startup_recovers_an_interrupted_selling_session(self):
        snapshot = sample_preset()
        saved = {
            "preset_schema": 2, "presets": {}, "assignments": {}, "auto_enabled": False,
            MANAGER.CONF_WORK_MODE_ENTITY: "select.deye_inverter_esp32_system_work_mode",
            "selling": {
                "settings": {**MANAGER.SELLING_DEFAULTS, "mode": "semi", "control_enabled": True,
                             "battery_soc_entity": "sensor.deye_inverter_esp32_battery_bms_soc", "min_soc": 35},
                "plans": {"2026-10-26": {"ranges": [{"start": "18:15", "approved": True}]}},
                "session": {"date": "2026-10-26", "start": "18:15", "end": "2026-10-26T19:15:00",
                            "slot": 4, "snapshot": snapshot,
                            "battery_soc_entity": "sensor.deye_inverter_esp32_battery_bms_soc", "min_soc": 35},
            },
        }
        hass = FakeHass(saved)
        put_live(hass, snapshot)
        work_mode = MANAGER.eid(TEST_PREFIX, "select", "system_work_mode")
        active_soc = MANAGER.slot_id(TEST_PREFIX, "number", 5, "soc")
        hass.states.async_set(work_mode, "Selling First")
        hass.states.async_set(active_soc, "35")
        hass.states.async_set("sensor.deye_inverter_esp32_battery_bms_soc", "35")
        with patch.object(MANAGER.dt_util, "now", return_value=datetime(2026, 10, 26, 18, 25)):
            await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
            hass.listeners["homeassistant_started"](None)
            await hass.finish_tasks()
        self.assertEqual(hass.states[work_mode].state, "Zero Export To CT")
        self.assertEqual(hass.states[active_soc].state, "60.0")
        self.assertIsNone(hass.saved["selling"]["session"])
        recovered_range = hass.saved["selling"]["plans"]["2026-10-26"]["ranges"][0]
        self.assertTrue(recovered_range["completed"])

    async def test_offline_services_persist_without_inverter_writes(self):
        preset = sample_preset()
        await self.call("save_definition", name="Weekday", preset=preset)
        await self.call("assign_day", day="monday", name="Weekday")
        await self.call("save_current", name="Snapshot")
        await self.call("set_auto", enabled=False)
        self.assertEqual(self.hass.services.writes, [])
        weekday_id = self.hass.states[MANAGER.ENTITY].attributes["preset_ids"]["Weekday"]
        self.assertEqual(self.hass.saved["assignments"]["monday"], weekday_id)
        restored = FakeHass(self.hass.saved)
        await MANAGER.async_setup(restored, {MANAGER.DOMAIN: {}})
        self.assertIn("Snapshot", restored.states[MANAGER.ENTITY].attributes["presets"])
        self.assertEqual(restored.states[MANAGER.ENTITY].attributes["preset_ids"]["Weekday"], weekday_id)
        await self.call("delete", name="Weekday")
        self.assertEqual(self.hass.saved["assignments"]["monday"], "")

    async def test_legacy_names_migrate_to_hash_ids_with_assignments(self):
        saved = {
            "presets": {"Old": sample_preset(), "Other": sample_preset()},
            "assignments": {"monday": "Old", "tuesday": "Other"},
            "auto_enabled": True,
            MANAGER.CONF_WORK_MODE_ENTITY: MANAGER.LEGACY_WORK_MODE_ENTITY,
        }
        hass = FakeHass(saved)
        put_live(hass, sample_preset())
        await MANAGER.async_setup(hass, {MANAGER.DOMAIN: {}})
        attrs = hass.states[MANAGER.ENTITY].attributes
        old_id = attrs["preset_ids"]["Old"]
        self.assertRegex(old_id, r"^[0-9a-f]{64}$")
        self.assertEqual(hass.saved["preset_schema"], 2)
        self.assertEqual(hass.saved["presets"][old_id]["name"], "Old")
        self.assertEqual(hass.saved["presets"][old_id]["preset"], sample_preset())
        self.assertEqual(hass.saved["assignments"]["monday"], old_id)
        self.assertEqual(attrs["assignments"]["monday"], "Old")
        restored = FakeHass(hass.saved)
        put_live(restored, sample_preset())
        await MANAGER.async_setup(restored, {MANAGER.DOMAIN: {}})
        self.assertEqual(restored.states[MANAGER.ENTITY].attributes["preset_ids"]["Old"], old_id)

    async def test_rename_keeps_hash_and_weekday_assignment(self):
        await self.call("save_definition", name="Old", preset=sample_preset())
        await self.call("assign_day", day="monday", name="Old")
        preset_id = self.hass.states[MANAGER.ENTITY].attributes["preset_ids"]["Old"]
        changed = sample_preset()
        changed["slots"][0]["soc"] = 75
        await self.call("save_definition", name="Renamed", preset=changed,
                        preset_id=preset_id, overwrite=True)
        attrs = self.hass.states[MANAGER.ENTITY].attributes
        self.assertEqual(attrs["preset_ids"], {"Renamed": preset_id})
        self.assertEqual(attrs["assignments"]["monday"], "Renamed")
        self.assertEqual(self.hass.saved["assignments"]["monday"], preset_id)
        self.assertEqual(self.hass.saved["presets"][preset_id]["preset"]["slots"][0]["soc"], 75)
        self.assertEqual(self.hass.services.writes, [])
        restored = FakeHass(self.hass.saved)
        put_live(restored, sample_preset())
        await MANAGER.async_setup(restored, {MANAGER.DOMAIN: {}})
        self.assertEqual(restored.states[MANAGER.ENTITY].attributes["assignments"]["monday"], "Renamed")
        await self.call("set_auto", enabled=True)
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            self.hass.midnight_callback(None)
            await self.hass.finish_tasks()
        self.assertIn("applied Renamed", self.hass.saved["last_automatic"])
        self.assertEqual(MANAGER.snapshot(self.hass, TEST_PREFIX)["slots"][0]["soc"], 75)
        await self.call("delete", name="Renamed")
        self.assertEqual(self.hass.saved["assignments"]["monday"], "")

    async def test_rename_rejects_another_presets_name(self):
        preset = sample_preset()
        await self.call("save_definition", name="First", preset=preset)
        await self.call("save_definition", name="Second", preset=preset)
        first_id = self.hass.states[MANAGER.ENTITY].attributes["preset_ids"]["First"]
        with self.assertRaises(Exception):
            await self.call("save_definition", name="Second", preset=preset,
                            preset_id=first_id, overwrite=True)
        self.assertEqual(set(self.hass.states[MANAGER.ENTITY].attributes["presets"]),
                         {"First", "Second"})

    async def test_weekday_assignments_and_auto_setting_restore(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        for day in MANAGER.DAYS:
            await self.call("assign_day", day=day, name="Target")
        await self.call("set_auto", enabled=True)
        restored = FakeHass(self.hass.saved)
        await MANAGER.async_setup(restored, {MANAGER.DOMAIN: {}})
        attributes = restored.states[MANAGER.ENTITY].attributes
        self.assertTrue(attributes["auto_enabled"])
        self.assertEqual(set(attributes["assignments"].values()), {"Target"})

    async def test_missing_control_prevents_all_writes(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        del self.hass.states[MANAGER.eid(TEST_PREFIX, "switch", "time_of_use_sunday")]
        with self.assertRaises(Exception):
            await self.call("apply", name="Target")
        self.assertEqual(self.hass.services.writes, [])

    async def test_apply_verifies_then_enables_tou(self):
        target = sample_preset()
        target["slots"][0]["soc"] = 80
        await self.call("save_definition", name="Target", preset=target)
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            await self.call("apply", name="Target")
        writes = self.hass.services.writes
        main = MANAGER.eid(TEST_PREFIX, "switch", "time_of_use")
        self.assertEqual(writes[0][:2], ("switch", "turn_off"))
        self.assertEqual(writes[0][2]["entity_id"], main)
        self.assertEqual(writes[-1][:2], ("switch", "turn_on"))
        self.assertEqual(writes[-1][2]["entity_id"], main)
        self.assertEqual(MANAGER.snapshot(self.hass, TEST_PREFIX), MANAGER.validate_preset(target))

    async def test_write_failure_leaves_tou_off(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        self.hass.services.fail_entity = MANAGER.slot_id(TEST_PREFIX, "number", 2, "soc")
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            with self.assertRaises(RuntimeError):
                await self.call("apply", name="Target")
        self.assertEqual(self.hass.states[MANAGER.eid(TEST_PREFIX, "switch", "time_of_use")].state, "off")

    async def test_readback_mismatch_leaves_tou_off(self):
        target = sample_preset()
        target["slots"][0]["soc"] = 80
        await self.call("save_definition", name="Target", preset=target)
        self.hass.services.ignore_entity = MANAGER.slot_id(TEST_PREFIX, "number", 1, "soc")
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            with self.assertRaises(Exception):
                await self.call("apply", name="Target")
        self.assertEqual(self.hass.states[MANAGER.eid(TEST_PREFIX, "switch", "time_of_use")].state, "off")

    async def test_startup_skips_matching_preset(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        await self.call("assign_day", day="monday", name="Target")
        await self.call("set_auto", enabled=True)
        self.hass.listeners["homeassistant_started"](None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("already active", self.hass.saved["last_automatic"])

    async def test_midnight_without_assignment_does_not_write(self):
        await self.call("set_auto", enabled=True)
        self.hass.midnight_callback(None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("no preset", self.hass.saved["last_automatic"])

    async def test_midnight_applies_assigned_different_preset(self):
        target = sample_preset()
        target["slots"][0]["soc"] = 80
        await self.call("save_definition", name="Target", preset=target)
        await self.call("assign_day", day="monday", name="Target")
        await self.call("set_auto", enabled=True)
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            self.hass.midnight_callback(None)
            await self.hass.finish_tasks()
        self.assertTrue(self.hass.services.writes)
        self.assertIn("applied Target", self.hass.saved["last_automatic"])

    async def test_unavailable_esphome_does_not_write(self):
        await self.call("set_auto", enabled=True)
        del self.hass.states[MANAGER.slot_id(TEST_PREFIX, "number", 1, "soc")]
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            self.hass.listeners["homeassistant_started"](None)
            await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("unavailable", self.hass.saved["last_automatic"])

    async def test_startup_waits_for_esphome_reconnection(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        await self.call("assign_day", day="monday", name="Target")
        await self.call("set_auto", enabled=True)
        missing = MANAGER.slot_id(TEST_PREFIX, "number", 1, "soc")
        del self.hass.states[missing]

        async def reconnect(_seconds):
            self.hass.states.async_set(missing, sample_preset()["slots"][0]["soc"])

        with patch.object(MANAGER.asyncio, "sleep", reconnect):
            self.hass.listeners["homeassistant_started"](None)
            await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("already active", self.hass.saved["last_automatic"])


if __name__ == "__main__":
    unittest.main()

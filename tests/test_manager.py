"""Behavior tests with a small HA service/state harness, without hardware writes."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "deye_tou_manager"


class FakeState:
    def __init__(self, state, attributes=None):
        self.state = str(state)
        self.attributes = attributes or {}


class FakeStates(dict):
    def async_set(self, entity_id, state, attributes=None):
        self[entity_id] = FakeState(state, attributes)

    def async_remove(self, entity_id):
        self.pop(entity_id, None)


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
        self.services = FakeServices(self)
        self.resources = resources or FakeResources()
        self.data = {"lovelace": SimpleNamespace(
            resource_mode=resource_mode, resources=self.resources,
        )}
        self.static_paths = []
        self.listeners = {}
        self.midnight_callback = None
        self.tasks = []
        self.http = SimpleNamespace(async_register_static_paths=self.register_paths)
        self.bus = SimpleNamespace(async_listen_once=self.listen_once)

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
        hass.midnight_callback = callback
        return lambda: setattr(hass, "midnight_callback", None)
    modules["homeassistant.helpers.event"].async_track_time_change = track_time
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
            cls.domain = kwargs["domain"]

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    config_entries.ConfigFlow = FakeConfigFlow
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.config_entries = config_entries
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Schema = lambda schema: schema
    with patch.dict(sys.modules, {
        "deye_test_package": MANAGER,
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
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


def put_live(hass, preset):
    hass.states.async_set(MANAGER.eid("select", "system_work_mode"), preset["work_mode"])
    hass.states.async_set(MANAGER.eid("switch", "solar_sell"), "on" if preset["solar_sell"] else "off")
    hass.states.async_set(MANAGER.eid("switch", "time_of_use"), "on")
    for day in MANAGER.DAYS:
        hass.states.async_set(MANAGER.eid("switch", f"time_of_use_{day}"), "on")
    for index, slot in enumerate(preset["slots"], 1):
        for domain, key, value in (
            ("time", "start", slot["start"]),
            ("number", "soc", slot["soc"]),
            ("number", "out_power", slot["power"]),
            ("switch", "grid_charge", "on" if slot["grid_charge"] else "off"),
            ("switch", "gen", "on" if slot["gen"] else "off"),
        ):
            hass.states.async_set(MANAGER.slot_id(domain, index, key), value)


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


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_confirms_one_click_setup(self):
        flow = CONFIG_FLOW.DeyeTouManagerConfigFlow()
        self.assertEqual(flow.domain, MANAGER.DOMAIN)
        self.assertEqual((await flow.async_step_user())["type"], "form")
        self.assertEqual(await flow.async_step_user({}), {
            "type": "create_entry", "title": "Deye TOU Preset Manager", "data": {},
        })


class ResourceAndSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_ui_entry_starts_and_unloads_without_yaml(self):
        hass = FakeHass()
        await MANAGER.async_setup(hass, {})
        self.assertNotIn(MANAGER.ENTITY, hass.states)
        self.assertEqual(hass.resources.items, [])
        entry = SimpleNamespace()
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
        entry = SimpleNamespace()
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
        self.assertEqual(self.hass.resources.items[0]["url"], MANAGER.CARD_RESOURCE_URL)
        self.assertEqual(self.hass.resources.operations[:2], ["load", "create"])
        self.assertFalse(self.hass.states[MANAGER.ENTITY].attributes["auto_enabled"])
        self.hass.listeners["homeassistant_started"](None)
        self.hass.midnight_callback(None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])

    async def test_offline_services_persist_without_inverter_writes(self):
        preset = sample_preset()
        await self.call("save_definition", name="Weekday", preset=preset)
        await self.call("assign_day", day="monday", name="Weekday")
        await self.call("save_current", name="Snapshot")
        await self.call("set_auto", enabled=False)
        self.assertEqual(self.hass.services.writes, [])
        self.assertEqual(self.hass.saved["assignments"]["monday"], "Weekday")
        restored = FakeHass(self.hass.saved)
        await MANAGER.async_setup(restored, {MANAGER.DOMAIN: {}})
        self.assertIn("Snapshot", restored.states[MANAGER.ENTITY].attributes["presets"])
        await self.call("delete", name="Weekday")
        self.assertEqual(self.hass.saved["assignments"]["monday"], "")

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
        del self.hass.states[MANAGER.eid("switch", "time_of_use_sunday")]
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
        main = MANAGER.eid("switch", "time_of_use")
        self.assertEqual(writes[0][:2], ("switch", "turn_off"))
        self.assertEqual(writes[0][2]["entity_id"], main)
        self.assertEqual(writes[-1][:2], ("switch", "turn_on"))
        self.assertEqual(writes[-1][2]["entity_id"], main)
        self.assertEqual(MANAGER.snapshot(self.hass), MANAGER.validate_preset(target))

    async def test_write_failure_leaves_tou_off(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        self.hass.services.fail_entity = MANAGER.slot_id("number", 2, "soc")
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            with self.assertRaises(RuntimeError):
                await self.call("apply", name="Target")
        self.assertEqual(self.hass.states[MANAGER.eid("switch", "time_of_use")].state, "off")

    async def test_readback_mismatch_leaves_tou_off(self):
        target = sample_preset()
        target["slots"][0]["soc"] = 80
        await self.call("save_definition", name="Target", preset=target)
        self.hass.services.ignore_entity = MANAGER.slot_id("number", 1, "soc")
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            with self.assertRaises(Exception):
                await self.call("apply", name="Target")
        self.assertEqual(self.hass.states[MANAGER.eid("switch", "time_of_use")].state, "off")

    async def test_startup_skips_matching_preset(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        await self.call("assign_day", day="monday", name="Target")
        await self.call("set_auto", enabled=True)
        self.hass.listeners["homeassistant_started"](None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("już aktywny", self.hass.saved["last_automatic"])

    async def test_midnight_without_assignment_does_not_write(self):
        await self.call("set_auto", enabled=True)
        self.hass.midnight_callback(None)
        await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("brak presetu", self.hass.saved["last_automatic"])

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
        self.assertIn("zastosowano Target", self.hass.saved["last_automatic"])

    async def test_unavailable_esphome_does_not_write(self):
        await self.call("set_auto", enabled=True)
        del self.hass.states[MANAGER.slot_id("number", 1, "soc")]
        with patch.object(MANAGER.asyncio, "sleep", no_delay):
            self.hass.listeners["homeassistant_started"](None)
            await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("niedostępne", self.hass.saved["last_automatic"])

    async def test_startup_waits_for_esphome_reconnection(self):
        await self.call("save_definition", name="Target", preset=sample_preset())
        await self.call("assign_day", day="monday", name="Target")
        await self.call("set_auto", enabled=True)
        missing = MANAGER.slot_id("number", 1, "soc")
        del self.hass.states[missing]

        async def reconnect(_seconds):
            self.hass.states.async_set(missing, sample_preset()["slots"][0]["soc"])

        with patch.object(MANAGER.asyncio, "sleep", reconnect):
            self.hass.listeners["homeassistant_started"](None)
            await self.hass.finish_tasks()
        self.assertEqual(self.hass.services.writes, [])
        self.assertIn("już aktywny", self.hass.saved["last_automatic"])


if __name__ == "__main__":
    unittest.main()

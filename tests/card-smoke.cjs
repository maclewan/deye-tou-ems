const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const registry = new Map();
global.customElements = {
  define(name, element) { registry.set(name, element); },
  get(name) { return registry.get(name); },
};
const settings = new Map();
global.window = {
  customCards: [], confirm: () => true,
  localStorage: {
    getItem(key) { return settings.get(key) || null; },
    setItem(key, value) { settings.set(key, value); },
  },
};
global.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {
      innerHTML: "",
      getElementById: () => null,
      querySelectorAll: () => [],
    };
  }
};

const cardPath = path.join(__dirname, "..", "custom_components", "deye_tou_manager", "frontend", "deye-tou-manager-card.js");
require(cardPath);
const Card = registry.get("deye-tou-manager-card");
assert.ok(Card, "card registers");
const card = new Card();
const english = require(path.join(__dirname, "..", "custom_components", "deye_tou_manager", "frontend", "card-en.json"));
const polish = require(path.join(__dirname, "..", "custom_components", "deye_tou_manager", "frontend", "card-pl.json"));
assert.deepEqual(Object.keys(polish).sort(), Object.keys(english).sort(), "card translations share all keys");
for (const [, key] of fs.readFileSync(cardPath, "utf8").matchAll(/this\.(?:tr|h)\("([^"]+)"/g)) {
  assert.ok(Object.hasOwn(english, key), `missing card translation: ${key}`);
}
card._translationCache.en = english;
card.setConfig({});
card.hass = { states: {} };
assert.match(card.shadowRoot.innerHTML, /sensor\.deye_tou_preset_manager not found/);
card.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    presets: {}, assignments: {}, auto_enabled: false,
  } },
} };
assert.match(card.shadowRoot.innerHTML, /New blank preset/);
assert.match(card.shadowRoot.innerHTML, /id="editor-name"/);
const slots = [0, 4, 8, 12, 16, 20].map(hour => ({
  start: `${String(hour).padStart(2, "0")}:00:00`, soc: 25, power: 12000,
  grid_charge: false, gen: false,
}));
const attributes = {
  presets: { Weekday: { work_mode: "Zero Export To CT", solar_sell: true, slots } },
  preset_ids: { Weekday: "stable-hash-id" },
  assignments: {}, auto_enabled: false,
  work_mode_entity: "select.my_deye_system_work_mode",
};
const liveStates = {
  "select.my_deye_system_work_mode": { state: "Selling First" },
  "switch.my_deye_solar_sell": { state: "off" },
  "switch.my_deye_time_of_use": { state: "on" },
};
for (let i = 1; i <= 6; i++) {
  liveStates[`time.my_deye_time_of_use_${i}_start`] = { state: slots[i - 1].start };
  liveStates[`number.my_deye_time_of_use_${i}_soc`] = { state: "37" };
  liveStates[`number.my_deye_time_of_use_${i}_out_power`] = { state: "6000" };
  liveStates[`switch.my_deye_time_of_use_${i}_grid_charge`] = { state: "on" };
  liveStates[`switch.my_deye_time_of_use_${i}_gen`] = { state: "off" };
}
card.hass = { states: {
  ...liveStates,
  "sensor.deye_tou_preset_manager": { attributes },
} };
assert.match(card.shadowRoot.innerHTML, /Current inverter settings/);
assert.match(card.shadowRoot.innerHTML, /id="card-language"/);
assert.match(card.shadowRoot.innerHTML, /37 %/);
assert.match(card.shadowRoot.innerHTML, /6000 W/);
assert.match(card.shadowRoot.innerHTML, /\.live-slots\{display:grid;grid-template-columns:1fr/);
assert.equal([...card.shadowRoot.innerHTML.matchAll(/class="live-slot"/g)].length, 6);
assert.match(card.shadowRoot.innerHTML, /00:00 – 04:00/);
assert.match(card.shadowRoot.innerHTML, /20:00 – 00:00 \(next day\)/);
assert.match(card.shadowRoot.innerHTML, /Edit preset/);
assert.match(card.shadowRoot.innerHTML, /id="editor-name" maxlength="64" value="Weekday">/);
assert.match(card.shadowRoot.innerHTML, /value="25"/);
assert.match(card.shadowRoot.innerHTML, /<th>From<\/th><th>To<\/th>/);
assert.match(card.shadowRoot.innerHTML, /data-end-idx="0">04:00<\/td>/);
assert.match(card.shadowRoot.innerHTML, /data-end-idx="5">00:00 \(next day\)<\/td>/);
assert.doesNotMatch(card.shadowRoot.innerHTML, /⚡/);
const originalHtml = card.shadowRoot.innerHTML;
const liveSummary = { innerHTML: "" };
card.shadowRoot.getElementById = id => id === "live-summary" ? liveSummary : null;
card.hass = { states: {
  ...liveStates,
  "time.my_deye_time_of_use_2_start": { state: "05:00:00" },
  "number.my_deye_time_of_use_1_soc": { state: "42" },
  "sensor.deye_tou_preset_manager": { attributes },
} };
assert.match(liveSummary.innerHTML, /42 %/);
assert.match(liveSummary.innerHTML, /00:00 – 05:00/);
assert.equal(card.shadowRoot.innerHTML, originalHtml, "live updates do not discard editor inputs");
const firstEnd = { dataset: { endIdx: "0" }, textContent: "" };
const lastEnd = { dataset: { endIdx: "5" }, textContent: "" };
const timeInput = {
  type: "time", dataset: { idx: "1", field: "start" }, value: "05:00", listeners: {},
  addEventListener(name, callback) { this.listeners[name] = callback; },
};
card.shadowRoot.querySelectorAll = selector => ({
  "[data-idx]": [timeInput], "[data-end-idx]": [firstEnd, lastEnd],
}[selector] || []);
card.render();
timeInput.listeners.input({ target: timeInput });
assert.equal(card._editor.preset.slots[1].start, "05:00:00");
assert.equal(firstEnd.textContent, "05:00");
assert.equal(lastEnd.textContent, "00:00 (next day)");
assert.equal(card.timeLabel("unavailable"), "—");
assert.equal(window.customCards.length, 4);
const SellingCard = registry.get("deye-tou-selling-card");
assert.ok(SellingCard, "selling card registers from the same dashboard resource");
const ActionLogCard = registry.get("deye-tou-action-log-card");
assert.ok(ActionLogCard, "action log card registers from the same dashboard resource");
const sellingCard = new SellingCard();
sellingCard._translationCache.en = english;
sellingCard.setConfig({});
sellingCard.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    ha_local_date: "2026-10-26",
    rce_price_entities: {today:"sensor.rce_pse_price", tomorrow:"sensor.rce_pse_price_tomorrow"},
    selling: {settings: {mode:"semi", threshold:.5, max_ranges:2, time_of_day:"afternoon",
      min_soc:30, power_override:null, today_price_entity:"", tomorrow_price_entity:""},
      plans: {"2026-10-26": {date:"2026-10-26", source_entity:"sensor.rce_pse_price",
        ranges:[{start:"18:00", end:"19:00", average_price:.8, hours:[{start:"18:00",price:.8}], approved:false}]}}, error:""},
  } },
} };
assert.match(sellingCard.shadowRoot.innerHTML, /Energy selling planner/);
assert.match(sellingCard.shadowRoot.innerHTML, /18:00–19:00/);
assert.match(sellingCard.shadowRoot.innerHTML, /DRY RUN is enabled/);
assert.match(sellingCard.shadowRoot.innerHTML, /id="sell-dry-run"/);
assert.match(sellingCard.shadowRoot.innerHTML, /data-approve-date="2026-10-26"/);
assert.match(sellingCard.shadowRoot.innerHTML, /id="sell-clear"/);
assert.match(sellingCard.shadowRoot.innerHTML, /data-open-manual="today"/);
assert.match(sellingCard.shadowRoot.innerHTML, /Target battery SOC/);
assert.match(sellingCard.shadowRoot.innerHTML, /id="sell-dry-run"/);
assert.match(sellingCard.shadowRoot.innerHTML, /minimum price filters only automatic price suggestions/);
sellingCard._manualDialogDay = "today";
sellingCard.render();
assert.match(sellingCard.shadowRoot.innerHTML, /id="selling-manual-start"/);
assert.match(sellingCard.shadowRoot.innerHTML, /id="selling-manual-cancel"/);
sellingCard._manualDialogDay = "";
sellingCard.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    ha_local_date: "2026-10-26",
    selling: {settings: {mode:"semi", threshold:.5, max_ranges:2, time_of_day:"afternoon", min_soc:30},
      session: {date:"2026-10-26", start:"18:00", end:"2026-10-26T19:00:00"},
      plans: {"2026-10-26": {date:"2026-10-26", source_entity:"sensor.rce_pse_price",
        ranges:[{start:"18:00", end:"19:00", target_soc:42, approved:true, hours:[]}]}}, error:""},
  } },
} };
assert.match(sellingCard.shadowRoot.innerHTML, /data-stop-selling/);
assert.doesNotMatch(sellingCard.shadowRoot.innerHTML, /data-approve-date="2026-10-26"/);
sellingCard.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    ha_local_date: "2026-10-26",
    selling: {settings: {mode:"semi", threshold:.5, max_ranges:2, time_of_day:"afternoon", min_soc:30},
      plans: {"2026-10-26": {date:"2026-10-26", source_entity:"sensor.rce_pse_price",
        ranges:[{start:"18:00", end:"19:00", target_soc:42, completed:true, hours:[]}]}}, error:""},
  } },
} };
assert.match(sellingCard.shadowRoot.innerHTML, /data-restart-date="2026-10-26"/);
const HistoryCard = registry.get("deye-tou-selling-history-card");
assert.ok(HistoryCard, "revenue history card registers from the same dashboard resource");
const historyCard = new HistoryCard();
historyCard._translationCache.en = english;
historyCard.setConfig({});
historyCard.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    revenue: { hours: {
      "2026-10-25T23:00:00": {hour:"2026-10-25T23:00:00", price_pln_per_kwh:.75, net_exported_kwh:4, revenue_pln:3},
      "2026-10-26T18:00:00": {hour:"2026-10-26T18:00:00", price_pln_per_kwh:1.2, net_exported_kwh:2.5, revenue_pln:3},
    } },
  } },
} };
assert.match(historyCard.shadowRoot.innerHTML, /Selling history/);
assert.match(historyCard.shadowRoot.innerHTML, /2026-10-26/);
assert.match(historyCard.shadowRoot.innerHTML, /18:00–19:00/);
assert.match(historyCard.shadowRoot.innerHTML, /Sold \(kWh\)/);
assert.match(historyCard.shadowRoot.innerHTML, /Day total: 2\.5 kWh · 3 PLN/);
assert.match(historyCard.shadowRoot.innerHTML, /All-time revenue: 6 PLN/);

async function testRename() {
  const calls = [];
  card._hass.callService = async (...args) => calls.push(args);
  card._editor.name = "Renamed";
  await card.saveEditor();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], "save_definition");
  assert.equal(calls[0][2].name, "Renamed");
  assert.equal(calls[0][2].preset_id, "stable-hash-id");
  assert.equal(card._selected, "Renamed");
  card.hass = { states: {
    ...liveStates,
    "sensor.deye_tou_preset_manager": { attributes: {
      ...attributes,
      presets: { Renamed: attributes.presets.Weekday },
      preset_ids: { Renamed: "stable-hash-id" },
    } },
  } };
  assert.equal(card._editor.presetId, "stable-hash-id");
  assert.equal(card._pendingSavedName, null);
  global.fetch = async url => {
    assert.match(url, /card-pl\.json\?v=1\.1\.0$/);
    return { ok: true, json: async () => polish };
  };
  card.hass = { ...card._hass, language: "pl" };
  await new Promise(resolve => setImmediate(resolve));
  assert.match(card.shadowRoot.innerHTML, new RegExp(polish.currentSettings));
  assert.equal(card.endTimeLabel(slots, 5), "00:00" + polish.nextDay);
  const languageSelector = {
    listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; },
  };
  card.shadowRoot.getElementById = id => id === "card-language" ? languageSelector : null;
  card.render();
  languageSelector.listeners.change({ target: { value: "en" } });
  assert.equal(settings.get("deye-tou-manager-card-language"), "en");
  assert.match(card.shadowRoot.innerHTML, new RegExp(english.currentSettings));
  languageSelector.listeners.change({ target: { value: "auto" } });
  assert.match(card.shadowRoot.innerHTML, new RegExp(polish.currentSettings));

  const uncachedCard = new Card();
  uncachedCard.setConfig({});
  global.fetch = async url => {
    if (/card-pl\.json\?v=1\.1\.0$/.test(url)) return { ok: false };
    assert.match(url, /card-en\.json\?v=1\.1\.0$/);
    return { ok: true, json: async () => english };
  };
  uncachedCard.hass = { language: "pl", states: {} };
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(uncachedCard._language, "en");
  assert.ok(uncachedCard._failedLanguages.has("pl"));
  assert.match(uncachedCard.shadowRoot.innerHTML, /sensor\.deye_tou_preset_manager not found/);
  uncachedCard.hass = { language: "pl", states: {} };
  assert.equal(uncachedCard._language, "en", "failed Polish fetch stays on English fallback");
}
testRename().catch(error => { console.error(error); process.exitCode = 1; });

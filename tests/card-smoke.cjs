const assert = require("node:assert/strict");
const path = require("node:path");

const registry = new Map();
global.customElements = {
  define(name, element) { registry.set(name, element); },
  get(name) { return registry.get(name); },
};
global.window = { customCards: [], confirm: () => true };
global.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {
      innerHTML: "",
      getElementById: () => null,
      querySelectorAll: () => [],
    };
  }
};

require(path.join(__dirname, "..", "custom_components", "deye_tou_manager", "frontend", "deye-tou-manager-card.js"));
const Card = registry.get("deye-tou-manager-card");
assert.ok(Card, "card registers");
const card = new Card();
card.hass = { states: {} };
assert.match(card.shadowRoot.innerHTML, /Nie znaleziono sensor\.deye_tou_preset_manager/);
card.hass = { states: {
  "sensor.deye_tou_preset_manager": { attributes: {
    presets: {}, assignments: {}, auto_enabled: false,
  } },
} };
assert.match(card.shadowRoot.innerHTML, /Nowy pusty preset/);
assert.match(card.shadowRoot.innerHTML, /id="editor-name"/);
const slots = [0, 4, 8, 12, 16, 20].map(hour => ({
  start: `${String(hour).padStart(2, "0")}:00:00`, soc: 25, power: 12000,
  grid_charge: false, gen: false,
}));
const attributes = {
  presets: { Weekday: { work_mode: "Zero Export To CT", solar_sell: true, slots } },
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
assert.match(card.shadowRoot.innerHTML, /Aktualne ustawienia falownika/);
assert.match(card.shadowRoot.innerHTML, /37 %/);
assert.match(card.shadowRoot.innerHTML, /6000 W/);
assert.match(card.shadowRoot.innerHTML, /Edytuj preset/);
assert.match(card.shadowRoot.innerHTML, /value="25"/);
assert.doesNotMatch(card.shadowRoot.innerHTML, /⚡/);
const originalHtml = card.shadowRoot.innerHTML;
const liveSummary = { innerHTML: "" };
card.shadowRoot.getElementById = id => id === "live-summary" ? liveSummary : null;
card.hass = { states: {
  ...liveStates,
  "number.my_deye_time_of_use_1_soc": { state: "42" },
  "sensor.deye_tou_preset_manager": { attributes },
} };
assert.match(liveSummary.innerHTML, /42 %/);
assert.equal(card.shadowRoot.innerHTML, originalHtml, "live updates do not discard editor inputs");
assert.equal(window.customCards.length, 1);

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
assert.equal(window.customCards.length, 1);

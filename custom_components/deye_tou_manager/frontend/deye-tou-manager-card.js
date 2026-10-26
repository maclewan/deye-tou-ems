/* Deye TOU Manager: standalone Lovelace card, no external JS dependencies. */
const CARD_LANGUAGE_KEY = "deye-tou-manager-card-language";
const CARD_TRANSLATION_VERSION = "0.6.0";
class DeyeTouManagerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lastSignature = "";
    this._selected = "";
    this._busy = false;
    this._editor = null;
    this._editorDraft = false;
    this._language = "";
    this._texts = null;
    this._translationError = false;
    this._translationCache = {};
    this._failedLanguages = new Set();
    this._languageChoice = "auto";
  }
  setConfig(config) {
    this.config = config || {};
    let stored;
    try { stored = window.localStorage?.getItem(CARD_LANGUAGE_KEY); } catch (_) { /* unavailable */ }
    const choice = stored || this.config.language || "auto";
    this._languageChoice = ["auto", "en", "pl"].includes(choice) ? choice : "auto";
    if (this._hass && this.updateLanguage()) this.render();
  }
  getCardSize() { return 14; }
  static getStubConfig() { return { type: "custom:deye-tou-manager-card" }; }
  set hass(value) {
    this._hass = value;
    const languageChanged = this.updateLanguage();
    const state = value?.states["sensor.deye_tou_preset_manager"];
    const signature = state ? JSON.stringify(state.attributes) : "missing";
    const live = this.liveSnapshot(value, state?.attributes?.work_mode_entity);
    const liveSignature = JSON.stringify(live);
    if (signature !== this._lastSignature || languageChanged) {
      this._lastSignature = signature;
      this._lastLiveSignature = liveSignature;
      this.render();
    } else if (liveSignature !== this._lastLiveSignature) {
      this._lastLiveSignature = liveSignature;
      const summary = this.shadowRoot.getElementById("live-summary");
      if (summary) summary.innerHTML = this.liveSummaryHtml(live);
    }
  }
  updateLanguage() {
    const haLanguage = String(this._hass?.language || "en").split(/[-_]/)[0].toLowerCase();
    const requested = this._languageChoice === "auto" ? haLanguage : this._languageChoice;
    const language = requested === "pl" && !this._failedLanguages.has("pl") ? "pl" : "en";
    if (language === this._language) return false;
    this._language = language;
    this._texts = this._translationCache[language] || null;
    this._translationError = false;
    if (!this._texts) this.loadTranslation(language);
    return true;
  }
  async loadTranslation(language) {
    try {
      const response = await fetch(`/api/deye_tou_manager/card-${language}.json?v=${CARD_TRANSLATION_VERSION}`);
      if (!response.ok) throw new Error("Card translation unavailable");
      const messages = await response.json();
      this._translationCache[language] = messages;
      if (this._language === language) {
        this._texts = messages;
        this.render();
      }
    } catch (_) {
      if (this._language !== language) return;
      if (language === "pl") {
        this._failedLanguages.add("pl");
        this._language = "en";
        this._texts = this._translationCache.en || null;
        if (!this._texts) this.loadTranslation("en");
        else this.render();
      } else {
        this._translationError = true;
        this.render();
      }
    }
  }
  escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }
  tr(key, values = {}) {
    return (this._texts?.[key] || key)
      .replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
  }
  h(key, values = {}) { return this.escape(this.tr(key, values)); }
  async act(service, data, question) {
    if (this._busy || (question && !window.confirm(question))) return;
    this._busy = true;
    this.status(this.tr("saving"), false);
    try {
      await this._hass.callService("deye_tou_manager", service, data);
      this.status(this.tr("done"), false);
      return true;
    } catch (err) {
      const recovery = service === "apply"
        ? this.tr("applyRecovery")
        : "";
      this.status(this.tr("errorPrefix") + (err?.message || err) + recovery, true);
      return false;
    } finally { this._busy = false; }
  }
  status(message, error) {
    const el = this.shadowRoot.getElementById("status");
    if (el) { el.textContent = message; el.className = error ? "error" : ""; }
  }
  blank() {
    return {
      work_mode: "Zero Export To CT", solar_sell: true,
      slots: [0,4,8,12,16,20].map(hour => ({
        start: `${String(hour).padStart(2,"0")}:00:00`,
        soc: 25, power: 12000, grid_charge: false, gen: false
      }))
    };
  }
  liveSnapshot(hass, workModeEntity) {
    const suffix = "_system_work_mode";
    if (typeof workModeEntity !== "string" || !workModeEntity.startsWith("select.") ||
        !workModeEntity.endsWith(suffix)) return null;
    const prefix = workModeEntity.slice("select.".length, -suffix.length);
    if (!prefix) return null;
    const read = (domain, name) => hass?.states[`${domain}.${prefix}_${name}`]?.state ?? null;
    return {
      workMode: hass?.states[workModeEntity]?.state ?? null,
      solarSell: read("switch", "solar_sell"),
      tou: read("switch", "time_of_use"),
      slots: Array.from({length:6}, (_, i) => {
        const n = i + 1;
        return {
          start: read("time", `time_of_use_${n}_start`),
          soc: read("number", `time_of_use_${n}_soc`),
          power: read("number", `time_of_use_${n}_out_power`),
          grid: read("switch", `time_of_use_${n}_grid_charge`),
          gen: read("switch", `time_of_use_${n}_gen`),
        };
      }),
    };
  }
  timeLabel(value) {
    return typeof value === "string" && /^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value)
      ? value.slice(0, 5) : "—";
  }
  endTimeLabel(slots, index) {
    const end = this.timeLabel(slots[(index + 1) % slots.length]?.start);
    return end === "—" ? end : `${end}${index === slots.length - 1 ? this.tr("nextDay") : ""}`;
  }
  refreshEditorEndTimes() {
    this.shadowRoot.querySelectorAll("[data-end-idx]").forEach(el => {
      el.textContent = this.endTimeLabel(this._editor.preset.slots, Number(el.dataset.endIdx));
    });
  }
  liveSummaryHtml(live) {
    if (!live) return `<p class="muted">${this.h("noWorkMode")}</p>`;
    const show = value => value == null || value === "unavailable" || value === "unknown"
      ? "—" : this.escape(value);
    const withUnit = (value, unit) => show(value) === "—" ? "—" : `${show(value)} ${unit}`;
    const flag = value => value === "on" ? this.h("yes") : value === "off" ? this.h("no") : "—";
    return `<div class="live-slots">${live.slots.map((slot, i) =>
      `<div class="live-slot"><b class="live-index">${i + 1}</b><div>
        <div class="live-time">${this.timeLabel(slot.start)} – ${this.endTimeLabel(live.slots, i)}</div>
        <div class="live-details">${this.h("soc")}: ${withUnit(slot.soc, "%")} · ${this.h("power")}: ${withUnit(slot.power, "W")} · ${this.h("grid")}: ${flag(slot.grid)} · ${this.h("gen")}: ${flag(slot.gen)}</div>
      </div></div>`
    ).join("")}</div>
      <p class="muted">${this.h("workMode")}: ${show(live.workMode)} · ${this.h("solarSell")}: ${flag(live.solarSell)} · ${this.h("tou")}: ${flag(live.tou)}</p>`;
  }
  editorHtml() {
    const e = this._editor;
    if (!e) return "";
    const p = e.preset;
    const modes = ["Zero Export To CT","Zero Export To Load","Selling First"];
    return `<div class="editor">
      <div class="row title-row"><h3>${this.h(e.originalName ? "editPreset" : "newPreset")}</h3>
        <button id="reset-editor">${this.h("resetChanges")}</button></div>
      <div class="row"><label>${this.h("name")}</label><input class="grow" id="editor-name" maxlength="64" value="${this.escape(e.name)}"></div>
      <div class="row top-settings"><label>${this.h("workMode")}</label><select id="editor-mode" class="grow">${modes.map(m=>
        `<option value="${this.escape(m)}" ${p.work_mode===m?"selected":""}>${this.escape(m)}</option>`).join("")}</select>
        <label class="check"><input type="checkbox" id="editor-solar" ${p.solar_sell?"checked":""}>${this.h("solarSell")}</label></div>
      <div class="slot-scroll"><table class="slot-table"><thead><tr><th>${this.h("slot")}</th><th>${this.h("from")}</th><th>${this.h("to")}</th><th>${this.h("soc")} %</th><th>${this.h("powerW")}</th><th>${this.h("grid")}</th><th>${this.h("gen")}</th></tr></thead>
        <tbody>${p.slots.map((s,i)=>`<tr><td>${i+1}</td>
          <td><input type="time" step="60" data-idx="${i}" data-field="start" value="${this.escape(s.start.slice(0,5))}"></td>
          <td class="slot-end" data-end-idx="${i}">${this.endTimeLabel(p.slots, i)}</td>
          <td><input type="number" min="0" max="100" step="1" data-idx="${i}" data-field="soc" value="${s.soc}"></td>
          <td><input type="number" min="0" max="12000" step="100" data-idx="${i}" data-field="power" value="${s.power}"></td>
          <td><input type="checkbox" data-idx="${i}" data-field="grid_charge" ${s.grid_charge?"checked":""}></td>
          <td><input type="checkbox" data-idx="${i}" data-field="gen" ${s.gen?"checked":""}></td>
        </tr>`).join("")}</tbody></table></div>
      <p class="muted">${this.h("editorNote")}</p>
      ${p.work_mode === "Selling First" ? `<p class="warning">${this.h("sellingWarning")}</p>` : ""}
      <div class="row"><button class="primary" id="save-editor">${this.h("savePreset")}</button>
        </div>
    </div>`;
  }
  startEditor(type, presets) {
    this._editorDraft = type !== "edit";
    if (type === "new") this._editor = { name:"", originalName:null, presetId:null, preset:this.blank() };
    if (type === "copy") this._editor = {
      name: this._selected + this.tr("copySuffix"), originalName:null, presetId:null,
      preset: structuredClone(presets[this._selected])
    };
    if (type === "edit") this._editor = {
      name:this._selected, originalName:this._selected,
      presetId:this._hass?.states["sensor.deye_tou_preset_manager"]?.attributes?.preset_ids?.[this._selected],
      preset:structuredClone(presets[this._selected])
    };
    this.render();
  }
  async saveEditor() {
    if (this._busy || !this._editor) return;
    const e = this._editor, name = e.name.trim(), slots = e.preset.slots;
    if (!name || name.length>64) return this.status(this.tr("enterName"),true);
    if (e.originalName && !e.presetId)
      return this.status(this.tr("missingId"),true);
    if (slots.some(s=>!Number.isFinite(s.soc) || s.soc<0 || s.soc>100 ||
        !Number.isFinite(s.power) || s.power<0 || s.power>12000))
      return this.status(this.tr("checkRange"),true);
    const times = slots.map(s=>s.start);
    if (times.some((v,i)=>i>0 && times[i-1]>=v))
      return this.status(this.tr("checkTimes"),true);
    this._busy = true;
    try {
      const data = { name, preset:e.preset, overwrite:Boolean(e.originalName) };
      if (e.presetId) data.preset_id = e.presetId;
      await this._hass.callService("deye_tou_manager", "save_definition", data);
      this._selected = name;
      this._pendingSavedName = name;
      this._editor = {name, originalName:name, presetId:e.presetId, preset:structuredClone(e.preset)};
      this._editorDraft = false;
      this.render();
      this.status(this.tr("savedNoInverter"),false);
    } catch (err) { this.status(this.tr("saveError")+(err?.message||err),true); }
    finally { this._busy = false; }
  }
  render() {
    if (!this._texts) {
      this.shadowRoot.innerHTML = this._translationError
        ? "<ha-card>Unable to load card translations. Check the integration installation.</ha-card>"
        : '<ha-card aria-busy="true"></ha-card>';
      return;
    }
    const data = this._hass?.states["sensor.deye_tou_preset_manager"]?.attributes;
    const presets = data?.presets || {};
    const names = Object.keys(presets).sort((a,b)=>a.localeCompare(b,this._language || "en"));
    if (names.includes(this._pendingSavedName)) {
      this._selected = this._pendingSavedName;
      if (this._editor) this._editor.presetId = data.preset_ids?.[this._selected];
      this._pendingSavedName = null;
    }
    if (!names.includes(this._selected) && this._selected !== this._pendingSavedName)
      this._selected = names[0] || "";
    const selected = presets[this._selected];
    if (data && (!this._editor ||
        (!this._editorDraft && this._selected !== this._pendingSavedName &&
          this._editor.originalName !== (selected ? this._selected : null)))) {
      this._editor = selected
        ? { name:this._selected, originalName:this._selected,
            presetId:data.preset_ids?.[this._selected], preset:structuredClone(selected) }
        : { name:"", originalName:null, presetId:null, preset:this.blank() };
    }
    const days = Object.fromEntries(["monday", "tuesday", "wednesday", "thursday",
      "friday", "saturday", "sunday"].map(day => [day, this.tr(day)]));
    const options = names.map(n => `<option value="${this.escape(n)}" ${n === this._selected ? "selected" : ""}>${this.escape(n)}</option>`).join("");
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;color:var(--primary-text-color)}
        ha-card{padding:22px;display:block;background:var(--card-background-color);border-radius:var(--ha-card-border-radius,16px)}
        h2{font-size:21px;margin:0 0 5px} h3{font-size:15px;margin:0 0 12px}
        .muted{color:var(--secondary-text-color);font-size:13px;margin:4px 0 15px}
        .warning{color:var(--warning-color,#b66a00);font-size:13px;font-weight:600}
        .rule{border-top:1px solid var(--divider-color);margin:20px 0}
        .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
        .grow{flex:1;min-width:145px} input,select{box-sizing:border-box;min-height:40px;max-width:100%;padding:8px 11px;border:1px solid var(--divider-color);border-radius:9px;color:var(--primary-text-color);background:var(--secondary-background-color)}
        button{border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);border-radius:9px;min-height:40px;padding:8px 13px;cursor:pointer;font-weight:600}
        button.primary{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}
        button.danger{color:var(--error-color)}button:hover{filter:brightness(.94)}
        .editor{margin-top:18px;border:1px solid var(--primary-color);background:var(--card-background-color);padding:14px;border-radius:12px}
        .title-row{justify-content:space-between;margin-bottom:12px}.title-row h3{margin:0}
        .top-settings{margin:12px 0}.check{display:flex;align-items:center;gap:6px}.check input{min-height:auto}
        .slot-scroll{overflow-x:auto}.slot-table{width:100%;border-collapse:collapse;white-space:nowrap;margin:12px 0}
        .slot-table th,.slot-table td{padding:6px 4px;text-align:center;border-bottom:1px solid var(--divider-color);font-size:12px}
        .slot-table input[type=number]{width:85px;min-height:34px;padding:5px}
        .slot-table input[type=time]{width:100px;min-height:34px;padding:5px}
        .slot-end{color:var(--secondary-text-color);white-space:nowrap;min-width:70px}
        .live-slots{display:grid;grid-template-columns:1fr;gap:6px;margin:14px 0}
        .live-slot{display:flex;align-items:flex-start;gap:10px;padding:9px 11px;border-radius:8px;background:var(--secondary-background-color);font-size:12px}
        .live-index{display:inline-flex;flex:none;align-items:center;justify-content:center;border-radius:50%;width:20px;height:20px;background:var(--primary-color);color:white}
        .live-time{font-weight:600;font-size:13px}.live-details{color:var(--secondary-text-color);line-height:1.5;margin-top:2px}
        .days{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
        .day{display:flex;align-items:center;gap:9px}.day label{min-width:88px;font-size:13px}.day select{flex:1;min-width:0}
        .automode{display:flex;gap:12px;align-items:center;justify-content:space-between;background:var(--secondary-background-color);border-radius:10px;padding:13px;margin:12px 0}
        .automode label{display:flex;align-items:center;gap:9px;font-weight:600;font-size:14px}
        .automode input{width:20px;height:20px;min-height:auto;accent-color:var(--primary-color)}
        .card-header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
        .card-header h2{margin:0}.language-picker{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--secondary-text-color)}
        .language-picker select{min-height:32px;padding:4px 7px;font-size:12px}
        #status{font-size:12px;color:var(--success-color);min-height:18px;margin-top:10px}#status.error{color:var(--error-color)}
        @media(max-width:580px){ha-card{padding:15px}.days{grid-template-columns:1fr}}
      </style>
      <ha-card>
        <div class="card-header"><h2>${this.h("title")}</h2>
          <label class="language-picker">${this.h("language")}
            <select id="card-language">
              ${[["auto", "languageAuto"], ["en", "languageEnglish"], ["pl", "languagePolish"]].map(([value, key]) =>
                `<option value="${value}" ${this._languageChoice === value ? "selected" : ""}>${this.h(key)}</option>`).join("")}
            </select></label></div><p class="muted">${this.h("subtitle")}</p>
        ${!data ? `<p class="muted">${this.h("missingSensor")}</p>` : `
        <h3>${this.h("currentSettings")}</h3>
        <div id="live-summary">${this.liveSummaryHtml(this.liveSnapshot(this._hass, data.work_mode_entity))}</div>
        <div class="rule"></div>
        <h3>${this.h("library")} (${names.length})</h3>
        <div class="row"><select class="grow" id="selected" ${names.length ? "" : "disabled"}>
          ${options || `<option>${this.h("none")}</option>`}</select>
          <button id="apply" ${selected ? "" : "disabled"}>${this.h("apply")}</button></div>
        <div class="row"><button id="copy" ${selected ? "" : "disabled"}>${this.h("duplicate")}</button>
          <button id="replace" ${selected ? "" : "disabled"}>${this.h("replace")}</button>
          <button class="danger" id="delete" ${selected ? "" : "disabled"}>${this.h("delete")}</button></div>
        ${this.editorHtml()}
        <div class="rule"></div>
        <div class="row"><button id="newblank">${this.h("newBlank")}</button>
          <input class="grow" id="newname" maxlength="64" placeholder="${this.h("snapshotPlaceholder")}" />
          <button class="primary" id="create">${this.h("captureCurrent")}</button></div>
        <p class="muted">${this.h("captureNote")}</p>
        <div class="rule"></div>
        <h3>${this.h("weekdays")}</h3>
        <div class="days">${Object.entries(days).map(([key,label])=>
          `<div class="day"><label>${this.escape(label)}</label><select data-day="${key}">
          <option value="">${this.h("noAssignment")}</option>${names.map(n=>`<option value="${this.escape(n)}" ${data.assignments?.[key]===n?"selected":""}>${this.escape(n)}</option>`).join("")}</select></div>`).join("")}</div>
        <p class="muted">${this.h("assignmentNote")}</p>`}
        ${data ? `<div class="rule"></div>
          <h3>${this.h("automation")}</h3>
          <div class="automode"><label for="auto-enabled">${this.h("enableSchedule")}</label>
            <input id="auto-enabled" type="checkbox" ${data.auto_enabled?"checked":""}></div>
          <p class="muted">${this.h("scheduleNote")}</p>
          <p class="muted"><b>${this.h("lastResult")}:</b> ${this.escape(data.last_automatic || this.tr("notAvailable"))}</p>` : ""}
        <div id="status" role="status"></div>
      </ha-card>`;
    const $ = id => this.shadowRoot.getElementById(id);
    $("card-language")?.addEventListener("change", e => {
      this._languageChoice = e.target.value;
      try { window.localStorage?.setItem(CARD_LANGUAGE_KEY, this._languageChoice); } catch (_) { /* unavailable */ }
      this.updateLanguage();
      this.render();
    });
    $("selected")?.addEventListener("change", e=>{this._selected=e.target.value;this.startEditor("edit",presets)});
    $("copy")?.addEventListener("click",()=>this.startEditor("copy",presets));
    $("newblank")?.addEventListener("click",()=>this.startEditor("new",presets));
    $("create")?.addEventListener("click",()=>{
      const name=$("newname").value.trim();
      if (!name) {this.status(this.tr("enterPresetName"),true);return;}
      this.act("save_current",{name,overwrite:false});
    });
    $("replace")?.addEventListener("click",()=>this.act("save_current",{name:this._selected,overwrite:true},
      this.tr("replaceConfirm", {name:this._selected})));
    $("delete")?.addEventListener("click",()=>this.act("delete",{name:this._selected},
      this.tr("deleteConfirm", {name:this._selected})));
    $("apply")?.addEventListener("click",()=>{
      const warning = selected?.work_mode === "Selling First" ? this.tr("applyWarning") : "";
      this.act("apply",{name:this._selected},
        this.tr("applyConfirm", {name:this._selected, warning}));
    });
    this.shadowRoot.querySelectorAll("[data-day]").forEach(el=>el.addEventListener("change",e=>
      this.act("assign_day",{day:e.target.dataset.day,name:e.target.value})));
    $("auto-enabled")?.addEventListener("change",e=>{
      const enabled=e.target.checked;
      const risky = Object.values(data.assignments || {}).some(name =>
        presets[name]?.work_mode === "Selling First");
      const warning = risky ? this.tr("autoWarning") : "";
      if (enabled && !window.confirm(this.tr("autoConfirm", {warning}))) {
        e.target.checked=false;return;
      }
      this.act("set_auto",{enabled});
    });
    $("reset-editor")?.addEventListener("click",()=>{
      this._editor=null;
      this._editorDraft=false;
      this.render();
    });
    $("save-editor")?.addEventListener("click",()=>this.saveEditor());
    $("editor-name")?.addEventListener("input",e=>{this._editorDraft=true;this._editor.name=e.target.value});
    $("editor-mode")?.addEventListener("change",e=>{this._editorDraft=true;this._editor.preset.work_mode=e.target.value;this.render()});
    $("editor-solar")?.addEventListener("change",e=>{this._editorDraft=true;this._editor.preset.solar_sell=e.target.checked});
    this.shadowRoot.querySelectorAll("[data-idx]").forEach(el=>{
      const update = e => {
        this._editorDraft=true;
        const target=e.target, slot=this._editor.preset.slots[Number(target.dataset.idx)];
        const field=target.dataset.field;
        if (target.type==="checkbox") slot[field]=target.checked;
        else if (target.type==="number") slot[field]=Number(target.value);
        else {
          slot[field]=target.value+":00";
          this.refreshEditorEndTimes();
        }
      };
      el.addEventListener("change", update);
      if (el.type === "time") el.addEventListener("input", update);
    });
  }
}
if (!customElements.get("deye-tou-manager-card"))
  customElements.define("deye-tou-manager-card", DeyeTouManagerCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "deye-tou-manager-card"))
  window.customCards.push({type:"deye-tou-manager-card",name:"Deye TOU Manager",description:"Presets and weekly schedule"});

class DeyeTouSellingCard extends DeyeTouManagerCard {
  constructor() {
    super();
    this._settingsDraft = null;
  }
  getCardSize() { return 9; }
  static getStubConfig() { return {type:"custom:deye-tou-selling-card"}; }
  render() {
    if (!this._texts) {
      this.shadowRoot.innerHTML = this._translationError
        ? "<ha-card>Unable to load card translations. Check the integration installation.</ha-card>"
        : '<ha-card aria-busy="true"></ha-card>';
      return;
    }
    const attributes = this._hass?.states["sensor.deye_tou_preset_manager"]?.attributes;
    const selling = attributes?.selling;
    const settings = this._settingsDraft || selling?.settings || {};
    const detected = attributes?.rce_price_entities || {};
    const dateKeyFor = day => {
      const date = new Date(`${attributes?.ha_local_date || new Date().toISOString().slice(0,10)}T12:00:00`);
      if (day === "tomorrow") date.setDate(date.getDate() + 1);
      return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
    };
    const field = (id, label, type, value, extra="") =>
      `<label>${this.h(label)}<input id="${id}" type="${type}" value="${this.escape(value ?? "")}" ${extra}></label>`;
    const checkbox = (id, label, checked) =>
      `<label class="control-toggle"><input id="${id}" type="checkbox" ${checked ? "checked" : ""}>${this.h(label)}</label>`;
    const select = (id, label, value, options) =>
      `<label>${this.h(label)}<select id="${id}">${options.map(([key, text]) =>
        `<option value="${key}" ${value === key ? "selected" : ""}>${this.h(text)}</option>`).join("")}</select></label>`;
    const manualStartOptions = [["", "sellingChooseHour"], ...Array.from({length:96}, (_, index) => {
      const hour = String(Math.floor(index / 4)).padStart(2, "0");
      const minute = String((index % 4) * 15).padStart(2, "0");
      return [`${hour}:${minute}`, `${hour}:${minute}`];
    })];
    const planHtml = day => {
      const dateKey = dateKeyFor(day);
      const plan = selling?.plans?.[dateKey];
      if (!plan) return `<section><h3>${this.h(day === "today" ? "sellingToday" : "sellingTomorrow")}</h3><p class="muted">${this.h("sellingNoPlan")}</p></section>`;
      return `<section><h3>${this.h(day === "today" ? "sellingToday" : "sellingTomorrow")} · ${this.escape(plan.date)}</h3>
        <p class="muted">${this.h("sellingSource")}: ${this.escape(plan.source_entity)}</p>
        ${plan.ranges?.length ? plan.ranges.map(range => `<div class="range"><b>${this.escape(range.start)}–${this.escape(range.end)}${range.ends_next_day ? this.h("nextDay") : ""}</b>
          <span>${range.manual ? this.h("sellingManual") : `${this.h("sellingAverage")}: ${this.escape(range.average_price)} PLN/kWh`}</span>
          <label class="approval"><input type="checkbox" data-approve-date="${dateKey}" data-approve-start="${this.escape(range.start)}" ${range.approved ? "checked" : ""}
            ${settings.mode === "semi" ? "" : "disabled"}>${this.h("sellingApproved")}</label>
          <small>${range.manual ? this.h("sellingManualNote") : range.hours.map(hour => `${this.escape(hour.start)} ${this.escape(hour.price)}`).join(" · ")}</small></div>`).join("")
          : `<p class="muted">${this.h("sellingBelowThreshold")}</p>`}
      </section>`;
    };
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:20px;color:var(--primary-text-color)}h2,h3{margin:0 0 10px}h3{font-size:16px}
      .header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
      .muted{color:var(--secondary-text-color);font-size:13px;line-height:1.5}
      .warning{color:var(--warning-color);font-size:13px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
      label{display:flex;flex-direction:column;gap:5px;font-size:13px}input,select,button{font:inherit;min-height:38px;box-sizing:border-box}
      input,select{width:100%;padding:7px;border:1px solid var(--divider-color);border-radius:7px;background:var(--card-background-color);color:var(--primary-text-color)}
      button{border:1px solid var(--divider-color);border-radius:7px;padding:7px 12px;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}
      button.primary{background:var(--primary-color);color:var(--text-primary-color);border:0}
      .actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.range{display:flex;gap:8px;flex-wrap:wrap;align-items:center;border:1px solid var(--divider-color);padding:10px;border-radius:8px;margin:7px 0}
      .range small{width:100%;color:var(--secondary-text-color)}section{border-top:1px solid var(--divider-color);padding-top:14px;margin-top:14px}
      .approval,.control-toggle{flex-direction:row;align-items:center;margin-top:12px}.approval input,.control-toggle input{width:18px;min-height:18px}
      .language-picker{display:flex;flex-direction:row;align-items:center}.language-picker select{width:auto;min-height:32px}
      #status{min-height:18px;font-size:12px;color:var(--success-color)}#status.error{color:var(--error-color)}
      @media(max-width:560px){.grid{grid-template-columns:1fr}ha-card{padding:15px}}
    </style><ha-card><div class="header"><h2>${this.h("sellingTitle")}</h2>
      <label class="language-picker">${this.h("language")}<select id="selling-language">
        ${[["auto","languageAuto"],["en","languageEnglish"],["pl","languagePolish"]].map(([value,key]) =>
          `<option value="${value}" ${this._languageChoice === value ? "selected" : ""}>${this.h(key)}</option>`).join("")}
      </select></label></div>
      <p class="warning">${settings.control_enabled ? this.h("sellingControlEnabledWarning") : this.h("sellingPreviewOnly")}</p>
      ${!selling ? `<p class="muted">${this.h("missingSensor")}</p>` : `<div class="grid">
        ${select("sell-mode","sellingMode",settings.mode,[["off","sellingOff"],["semi","sellingSemi"],["automatic","sellingAutomatic"]])}
        ${checkbox("sell-control","sellingControlEnabled",settings.control_enabled)}
        ${field("sell-threshold","sellingThreshold","number",settings.threshold,'min="0" step="0.01"')}
        ${field("sell-ranges","sellingMaxRanges","number",settings.max_ranges,'min="1" max="6" step="1"')}
        ${select("sell-period","sellingPeriod",settings.time_of_day,[["morning","sellingMorning"],["afternoon","sellingAfternoon"],["any","sellingAny"]])}
        ${field("sell-soc","sellingMinSoc","number",settings.min_soc,'min="0" max="100" step="1"')}
        ${field("sell-power","sellingPower","number",settings.power_override,'min="1" max="12000" step="1"')}
      </div><div class="actions"><button class="primary" id="sell-save">${this.h("sellingSave")}</button>
        <button id="sell-check-today">${this.h("sellingCheckToday")}</button>
        <button id="sell-check-tomorrow">${this.h("sellingCheckTomorrow")}</button>
        <button id="sell-clear">${this.h("sellingClear")}</button></div>
      <p class="muted">${this.h("sellingThresholdNote")}</p>
      <p class="muted">${this.h("sellingEntityConfigNote", {today:detected.today || this.tr("sellingAutoDetect"), tomorrow:detected.tomorrow || this.tr("sellingAutoDetect")})}</p>
      <p class="muted">${this.h("sellingSocConfigNote", {entity:settings.battery_soc_entity || this.tr("sellingSocAutoDetect")})}</p>
      <p class="muted">${this.h("sellingScheduleNote")}</p>
      <section><h3>${this.h("sellingAddManual")}</h3><div class="grid">
        ${select("selling-manual-day","sellingManualDay","today",[["today","sellingManualToday"],["tomorrow","sellingManualTomorrow"]])}
        ${select("selling-manual-start","sellingManualHour","",manualStartOptions)}
      </div><div class="actions"><button id="selling-add-manual">${this.h("sellingAddManualButton")}</button></div>
      <p class="muted">${this.h("sellingManualFormNote")}</p></section>
      ${selling.error ? `<p class="warning">${this.escape(selling.error)}</p>` : ""}
      ${selling.session ? `<p class="warning">${this.h("sellingActive", {start:selling.session.start, end:selling.session.end})}</p>` : ""}
      ${planHtml("today")}${planHtml("tomorrow")}`}
      <div id="status" role="status"></div></ha-card>`;
    const $ = id => this.shadowRoot.getElementById(id);
    $("selling-language")?.addEventListener("change", event => {
      this._languageChoice = event.target.value;
      try { window.localStorage?.setItem(CARD_LANGUAGE_KEY, this._languageChoice); } catch (_) { /* unavailable */ }
      this.updateLanguage(); this.render();
    });
    const ids = ["sell-mode","sell-control","sell-threshold","sell-ranges","sell-period","sell-soc","sell-power"];
    const readSettings = () => ({
      mode:$("sell-mode").value, control_enabled:$("sell-control").checked,
      threshold:Number($("sell-threshold").value),
      max_ranges:Number($("sell-ranges").value), time_of_day:$("sell-period").value,
      min_soc:Number($("sell-soc").value), power_override:$("sell-power").value === "" ? null : Number($("sell-power").value)
    });
    ids.forEach(id => $(id)?.addEventListener("change", () => { this._settingsDraft = readSettings(); }));
    $("sell-control")?.addEventListener("change", event => {
      if (event.target.checked && !window.confirm(this.tr("sellingControlConfirm"))) {
        event.target.checked = false;
        this._settingsDraft = readSettings();
      }
    });
    $("sell-save")?.addEventListener("click", async () => {
      const next = readSettings();
      await this.act("set_selling_settings", next);
      this._settingsDraft = null;
    });
    const saveAndCheck = async day => {
      if (await this.act("set_selling_settings", readSettings())) {
        this._settingsDraft = null;
        await this.act("refresh_selling_plan", {day});
      }
    };
    $("sell-check-today")?.addEventListener("click", () => saveAndCheck("today"));
    $("sell-check-tomorrow")?.addEventListener("click", () => saveAndCheck("tomorrow"));
    $("sell-clear")?.addEventListener("click", () => this.act("clear_selling_plans", {}));
    $("selling-add-manual")?.addEventListener("click", () => {
      const day = $("selling-manual-day").value;
      const start = $("selling-manual-start").value;
      if (!/^(?:[01]\\d|2[0-3]):(?:00|15|30|45)$/.test(start)) {
        this.status(this.tr("sellingManualHourError"), true);
        return;
      }
      this.act("add_selling_range", {date:dateKeyFor(day), start});
    });
    this.shadowRoot.querySelectorAll("[data-approve-date]").forEach(el => el.addEventListener("change", event =>
      this.act("approve_selling_range", {date:event.target.dataset.approveDate,
        start:event.target.dataset.approveStart, approved:event.target.checked})));
  }
}
if (!customElements.get("deye-tou-selling-card"))
  customElements.define("deye-tou-selling-card", DeyeTouSellingCard);
if (!window.customCards.some(card => card.type === "deye-tou-selling-card"))
  window.customCards.push({type:"deye-tou-selling-card",name:"Deye TOU Selling Planner",description:"Price-based selling plans and approvals"});

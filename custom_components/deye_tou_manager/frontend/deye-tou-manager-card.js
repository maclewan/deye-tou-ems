/* Deye TOU Manager: standalone Lovelace card, no external JS dependencies. */
class DeyeTouManagerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lastSignature = "";
    this._selected = "";
    this._busy = false;
    this._editor = null;
    this._editorDraft = false;
  }
  setConfig(config) { this.config = config || {}; }
  getCardSize() { return 14; }
  static getStubConfig() { return { type: "custom:deye-tou-manager-card" }; }
  set hass(value) {
    this._hass = value;
    const state = value?.states["sensor.deye_tou_preset_manager"];
    const signature = state ? JSON.stringify(state.attributes) : "missing";
    const live = this.liveSnapshot(value, state?.attributes?.work_mode_entity);
    const liveSignature = JSON.stringify(live);
    if (signature !== this._lastSignature) {
      this._lastSignature = signature;
      this._lastLiveSignature = liveSignature;
      this.render();
    } else if (liveSignature !== this._lastLiveSignature) {
      this._lastLiveSignature = liveSignature;
      const summary = this.shadowRoot.getElementById("live-summary");
      if (summary) summary.innerHTML = this.liveSummaryHtml(live);
    }
  }
  escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }
  async act(service, data, question) {
    if (this._busy || (question && !window.confirm(question))) return;
    this._busy = true;
    this.status("Zapisywanie…", false);
    try {
      await this._hass.callService("deye_tou_manager", service, data);
      this.status("Gotowe", false);
    } catch (err) {
      const recovery = service === "apply"
        ? " Sprawdź odczyty i logi HA; TOU może pozostać wyłączone."
        : "";
      this.status("Błąd: " + (err?.message || err) + recovery, true);
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
    return end === "—" ? end : `${end}${index === slots.length - 1 ? " (nast. dzień)" : ""}`;
  }
  refreshEditorEndTimes() {
    this.shadowRoot.querySelectorAll("[data-end-idx]").forEach(el => {
      el.textContent = this.endTimeLabel(this._editor.preset.slots, Number(el.dataset.endIdx));
    });
  }
  liveSummaryHtml(live) {
    if (!live) return '<p class="muted">Nie wybrano encji Work Mode falownika.</p>';
    const show = value => value == null || value === "unavailable" || value === "unknown"
      ? "—" : this.escape(value);
    const withUnit = (value, unit) => show(value) === "—" ? "—" : `${show(value)} ${unit}`;
    const flag = value => value === "on" ? "Tak" : value === "off" ? "Nie" : "—";
    return `<div class="live-slots">${live.slots.map((slot, i) =>
      `<div class="live-slot"><b class="live-index">${i + 1}</b><div>
        <div class="live-time">${this.timeLabel(slot.start)} – ${this.endTimeLabel(live.slots, i)}</div>
        <div class="live-details">SOC: ${withUnit(slot.soc, "%")} · Moc: ${withUnit(slot.power, "W")} · Grid: ${flag(slot.grid)} · Gen: ${flag(slot.gen)}</div>
      </div></div>`
    ).join("")}</div>
      <p class="muted">Work Mode: ${show(live.workMode)} · Solar Sell: ${flag(live.solarSell)} · TOU: ${flag(live.tou)}</p>`;
  }
  editorHtml() {
    const e = this._editor;
    if (!e) return "";
    const p = e.preset;
    const modes = ["Zero Export To CT","Zero Export To Load","Selling First"];
    return `<div class="editor">
      <div class="row title-row"><h3>${e.originalName ? "Edytuj preset" : "Nowy preset"}</h3>
        <button id="reset-editor">Resetuj zmiany</button></div>
      <div class="row"><label>Nazwa</label><input class="grow" id="editor-name" maxlength="64" value="${this.escape(e.name)}" ${e.originalName ? "readonly" : ""}></div>
      <div class="row top-settings"><label>Work Mode</label><select id="editor-mode" class="grow">${modes.map(m=>
        `<option value="${this.escape(m)}" ${p.work_mode===m?"selected":""}>${this.escape(m)}</option>`).join("")}</select>
        <label class="check"><input type="checkbox" id="editor-solar" ${p.solar_sell?"checked":""}>Solar Sell</label></div>
      <div class="slot-scroll"><table class="slot-table"><thead><tr><th>Slot</th><th>Od</th><th>Do</th><th>SOC %</th><th>Moc W</th><th>Grid</th><th>Gen</th></tr></thead>
        <tbody>${p.slots.map((s,i)=>`<tr><td>${i+1}</td>
          <td><input type="time" step="60" data-idx="${i}" data-field="start" value="${this.escape(s.start.slice(0,5))}"></td>
          <td class="slot-end" data-end-idx="${i}">${this.endTimeLabel(p.slots, i)}</td>
          <td><input type="number" min="0" max="100" step="1" data-idx="${i}" data-field="soc" value="${s.soc}"></td>
          <td><input type="number" min="0" max="12000" step="100" data-idx="${i}" data-field="power" value="${s.power}"></td>
          <td><input type="checkbox" data-idx="${i}" data-field="grid_charge" ${s.grid_charge?"checked":""}></td>
          <td><input type="checkbox" data-idx="${i}" data-field="gen" ${s.gen?"checked":""}></td>
        </tr>`).join("")}</tbody></table></div>
      <p class="muted">Zmiany są tylko w tym formularzu. Zapis nie zmienia falownika.</p>
      ${p.work_mode === "Selling First" ? '<p class="warning">Selling First z TOU może umożliwić sprzedaż energii z baterii. Sprawdź ten tryb przed wczytaniem lub włączeniem automatyki.</p>' : ""}
      <div class="row"><button class="primary" id="save-editor">Zapisz preset w HA</button>
        </div>
    </div>`;
  }
  startEditor(type, presets) {
    this._editorDraft = type !== "edit";
    if (type === "new") this._editor = { name:"", originalName:null, preset:this.blank() };
    if (type === "copy") this._editor = {
      name: this._selected + " - kopia", originalName:null,
      preset: structuredClone(presets[this._selected])
    };
    if (type === "edit") this._editor = {
      name:this._selected, originalName:this._selected,
      preset:structuredClone(presets[this._selected])
    };
    this.render();
  }
  async saveEditor() {
    if (this._busy || !this._editor) return;
    const e = this._editor, name = e.name.trim(), slots = e.preset.slots;
    if (!name || name.length>64) return this.status("Podaj nazwę (maks. 64 znaki)",true);
    if (slots.some(s=>!Number.isFinite(s.soc) || s.soc<0 || s.soc>100 ||
        !Number.isFinite(s.power) || s.power<0 || s.power>12000))
      return this.status("Sprawdź zakres SOC 0–100% i mocy 0–12000 W",true);
    const times = slots.map(s=>s.start);
    if (times.some((v,i)=>i>0 && times[i-1]>=v))
      return this.status("Godziny startu muszą być rosnące i różne",true);
    this._busy = true;
    try {
      await this._hass.callService("deye_tou_manager", "save_definition", {
        name, preset:e.preset, overwrite:Boolean(e.originalName)
      });
      this._selected = name;
      this._pendingSavedName = name;
      this._editor = {name, originalName:name, preset:structuredClone(e.preset)};
      this._editorDraft = false;
      this.render();
      this.status("Preset zapisany w HA. Falownik bez zmian.",false);
    } catch (err) { this.status("Błąd zapisu: "+(err?.message||err),true); }
    finally { this._busy = false; }
  }
  render() {
    const data = this._hass?.states["sensor.deye_tou_preset_manager"]?.attributes;
    const presets = data?.presets || {};
    const names = Object.keys(presets).sort((a,b)=>a.localeCompare(b,"pl"));
    if (names.includes(this._pendingSavedName)) this._pendingSavedName = null;
    if (!names.includes(this._selected) && this._selected !== this._pendingSavedName)
      this._selected = names[0] || "";
    const selected = presets[this._selected];
    if (data && (!this._editor ||
        (!this._editorDraft && this._selected !== this._pendingSavedName &&
          this._editor.originalName !== (selected ? this._selected : null)))) {
      this._editor = selected
        ? { name:this._selected, originalName:this._selected, preset:structuredClone(selected) }
        : { name:"", originalName:null, preset:this.blank() };
    }
    const days = { monday:"Poniedziałek", tuesday:"Wtorek", wednesday:"Środa",
      thursday:"Czwartek", friday:"Piątek", saturday:"Sobota", sunday:"Niedziela" };
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
        #status{font-size:12px;color:var(--success-color);min-height:18px;margin-top:10px}#status.error{color:var(--error-color)}
        @media(max-width:580px){ha-card{padding:15px}.days{grid-template-columns:1fr}}
      </style>
      <ha-card>
        <h2>Presety Deye TOU</h2><p class="muted">Zarządzaj harmonogramami i przypisz je do dni tygodnia.</p>
        ${!data ? `<p class="muted">Nie znaleziono sensor.deye_tou_preset_manager. Sprawdź instalację.</p>` : `
        <h3>Aktualne ustawienia falownika</h3>
        <div id="live-summary">${this.liveSummaryHtml(this.liveSnapshot(this._hass, data.work_mode_entity))}</div>
        <div class="rule"></div>
        <h3>Biblioteka presetów (${names.length})</h3>
        <div class="row"><select class="grow" id="selected" ${names.length ? "" : "disabled"}>
          ${options || '<option>Brak presetów</option>'}</select>
          <button id="apply" ${selected ? "" : "disabled"}>▶ Wczytaj do Deye</button></div>
        <div class="row"><button id="copy" ${selected ? "" : "disabled"}>⧉ Duplikuj</button>
          <button id="replace" ${selected ? "" : "disabled"}>↻ Aktualizuj z falownika</button>
          <button class="danger" id="delete" ${selected ? "" : "disabled"}>Usuń preset</button></div>
        ${this.editorHtml()}
        <div class="rule"></div>
        <div class="row"><button id="newblank">+ Nowy pusty preset</button>
          <input class="grow" id="newname" maxlength="64" placeholder="Nazwa snapshotu z falownika" />
          <button class="primary" id="create">+ Zapisz aktualne TOU</button></div>
        <p class="muted">Odczytuje 6 slotów, SOC, moc, Grid Charge, Gen, Work Mode i Solar Sell.</p>
        <div class="rule"></div>
        <h3>Przypisanie do dni tygodnia</h3>
        <div class="days">${Object.entries(days).map(([key,label])=>
          `<div class="day"><label>${label}</label><select data-day="${key}">
          <option value="">— Brak —</option>${names.map(n=>`<option value="${this.escape(n)}" ${data.assignments?.[key]===n?"selected":""}>${this.escape(n)}</option>`).join("")}</select></div>`).join("")}</div>
        <p class="muted">Przypisania służą harmonogramowi poniżej. Gdy automatyka jest wyłączona, nie zmieniają falownika.</p>`}
        ${data ? `<div class="rule"></div>
          <h3>Automatyczne przełączanie</h3>
          <div class="automode"><label for="auto-enabled">Włącz harmonogram tygodniowy</label>
            <input id="auto-enabled" type="checkbox" ${data.auto_enabled?"checked":""}></div>
          <p class="muted">Gdy włączone: sprawdzanie o 00:00:15 oraz po starcie HA. Jeśli aktualne ustawienia są zgodne z presetem, nie zapisuje ich ponownie.</p>
          <p class="muted"><b>Ostatni wynik:</b> ${this.escape(data.last_automatic || "Brak")}</p>` : ""}
        <div id="status" role="status"></div>
      </ha-card>`;
    const $ = id => this.shadowRoot.getElementById(id);
    $("selected")?.addEventListener("change", e=>{this._selected=e.target.value;this.startEditor("edit",presets)});
    $("copy")?.addEventListener("click",()=>this.startEditor("copy",presets));
    $("newblank")?.addEventListener("click",()=>this.startEditor("new",presets));
    $("create")?.addEventListener("click",()=>{
      const name=$("newname").value.trim();
      if (!name) {this.status("Wpisz nazwę presetu",true);return;}
      this.act("save_current",{name,overwrite:false});
    });
    $("replace")?.addEventListener("click",()=>this.act("save_current",{name:this._selected,overwrite:true},
      `Nadpisać preset „${this._selected}” aktualnymi ustawieniami falownika?`));
    $("delete")?.addEventListener("click",()=>this.act("delete",{name:this._selected},
      `Usunąć preset „${this._selected}” i jego przypisania do dni?`));
    $("apply")?.addEventListener("click",()=>{
      const warning = selected?.work_mode === "Selling First"
        ? " UWAGA: Selling First z TOU może umożliwić sprzedaż energii z baterii."
        : "";
      this.act("apply",{name:this._selected},
        `Wczytać „${this._selected}” do falownika? Zmieni to aktywne parametry TOU.${warning}`);
    });
    this.shadowRoot.querySelectorAll("[data-day]").forEach(el=>el.addEventListener("change",e=>
      this.act("assign_day",{day:e.target.dataset.day,name:e.target.value})));
    $("auto-enabled")?.addEventListener("change",e=>{
      const enabled=e.target.checked;
      const risky = Object.values(data.assignments || {}).some(name =>
        presets[name]?.work_mode === "Selling First");
      const warning = risky ? " Przypisano Selling First: TOU może umożliwić sprzedaż energii z baterii." : "";
      if (enabled && !window.confirm("Włączyć automatyczne przełączanie? Menedżer będzie wysyłał zapisane presety do Deye o północy i po starcie HA." + warning)) {
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
  window.customCards.push({type:"deye-tou-manager-card",name:"Deye TOU Manager",description:"Presety i plan tygodniowy"});

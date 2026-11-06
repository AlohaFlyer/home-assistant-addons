/* Flight Watcher: settings card (1.1.0). Edit the FLICA and CrewTrac logins and the last name from the dashboard,
   also for a user who is not a Home Assistant admin. Usernames are shown; a password only as set / not set.
   On Save the form is sealed in the browser (AES-256-GCM, the key wrapped with this Watcher's RSA-OAEP public key
   from sensor.flight_watcher_settings) and published to flight_watcher/settings/set, so Home Assistant's history,
   logs and MQTT only ever see ciphertext. A blank field keeps what is saved. Needs https (crypto.subtle). */
const FW_SET_FIELDS = [
  ["username", "FLICA username", false], ["password", "FLICA password", true],
  ["ctweb_username", "CrewTrac username", false], ["ctweb_password", "CrewTrac password", true],
  ["my_name", "Last name", false],
];

class FlightWatcherSettingsCard extends HTMLElement {
  setConfig(c) {
    this._c = { entity: "sensor.flight_watcher_settings", topic: "flight_watcher/settings/set", ...c };
    this._built = false;
  }
  getCardSize() { return 6; }
  set hass(h) {
    this._h = h;
    if (!this._built) this._build();
    this._status();
  }
  _st() { return (this._h && this._h.states[this._c.entity]) || { attributes: {} }; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }
  _build() {
    const a = this._st().attributes || {};
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const rows = FW_SET_FIELDS.map(([k, label, secret]) => secret
      ? `<label><span>${label}</span><input type="password" data-k="${k}" autocomplete="new-password" placeholder="leave blank to keep"><b data-s="${k}"></b></label>`
      : `<label><span>${label}</span><input type="text" data-k="${k}" autocomplete="off" spellcheck="false" value="${this._e(a[k])}"></label>`).join("");
    root.innerHTML = `<style>
      ha-card{padding:16px}label{display:flex;align-items:center;gap:8px;margin:8px 0;flex-wrap:wrap}
      label span{width:150px}input{flex:1;min-width:160px;max-width:320px;padding:6px;font:inherit;
      border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color)}
      b.set{color:#2e7d32}b.unset{color:#c62828}button{padding:8px 16px;border:0;border-radius:6px;
      background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;cursor:pointer}
      .note{opacity:.75;font-size:13px}.msg{margin-top:8px}.err{color:#c62828}.ok{color:#2e7d32}</style>
      <ha-card><div class="note">Saved on this Home Assistant only, encrypted before it leaves this screen. A blank field keeps
      what is saved. Saving restarts the Watcher; with a new FLICA login it logs in within a minute.</div>
      ${rows}<button id="save">Save settings</button><div class="msg" id="msg"></div>
      <div class="note" id="who"></div></ha-card>`;
    root.getElementById("save").addEventListener("click", () => this._save());
    this._built = true;
  }
  _status() {
    const root = this.shadowRoot; if (!root) return;
    const a = this._st().attributes || {};
    for (const [k, , secret] of FW_SET_FIELDS) {
      if (!secret) continue;
      const has = k === "password" ? a.has_password : a.has_ctweb_password;
      const b = root.querySelector(`b[data-s="${k}"]`);
      if (b) { b.className = has ? "set" : "unset"; b.textContent = has ? "set" : "not set"; }
    }
    if (this._sentAt && a.at && a.at !== this._sentAt && a.result) {
      const ok = String(a.result).startsWith("saved") || String(a.result).startsWith("nothing");
      root.getElementById("msg").innerHTML = `<span class="${ok ? "ok" : "err"}">${this._e(a.result)}</span>`;
      this._sentAt = null;
    }
    const st = this._h && this._h.states["sensor.flight_watcher_state"];
    root.getElementById("who").textContent = st ? `Watcher: ${st.state}` : "";
  }
  async _save() {
    const root = this.shadowRoot, msg = root.getElementById("msg");
    const a = this._st().attributes || {};
    const fields = {};
    root.querySelectorAll("input[data-k]").forEach((i) => { const v = i.value.trim(); if (v) fields[i.dataset.k] = v; });
    for (const [k, , secret] of FW_SET_FIELDS) if (!secret && fields[k] === String(a[k] || "")) delete fields[k];
    if (!Object.keys(fields).length) { msg.innerHTML = `<span class="err">Nothing to save: no field changed.</span>`; return; }
    if (!window.crypto || !crypto.subtle) { msg.innerHTML = `<span class="err">This page is not https, so it cannot encrypt. Open Home Assistant through its https address (Nabu Casa) and try again.</span>`; return; }
    if (!a.pubkey) { msg.innerHTML = `<span class="err">The Watcher has not published its key yet (is the app running?).</span>`; return; }
    try {
      const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
      const der = Uint8Array.from(atob(a.pubkey), (c) => c.charCodeAt(0));
      const pub = await crypto.subtle.importKey("spki", der, { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
      const aes = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const plain = new TextEncoder().encode(JSON.stringify({ ...fields, ts: Math.floor(Date.now() / 1000) }));
      const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, aes, plain);
      const key = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, pub, await crypto.subtle.exportKey("raw", aes));
      const body = { enc: { v: 1, kid: a.kid || "", key: b64(key), iv: b64(iv), data: b64(data) } };
      this._sentAt = a.at || "-";
      await this._h.callService("mqtt", "publish", { topic: this._c.topic, payload: JSON.stringify(body) });
      root.querySelectorAll("input[type=password]").forEach((i) => { i.value = ""; });
      msg.innerHTML = `<span class="ok">Sent. Waiting for the Watcher to confirm...</span>`;
    } catch (e) {
      this._sentAt = null;
      msg.innerHTML = `<span class="err">Not sent: ${this._e(e && e.message ? e.message : e)}</span>`;
    }
  }
}
customElements.define("flight-watcher-settings-card", FlightWatcherSettingsCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-settings-card", name: "Flight Watcher settings", description: "Edit the FLICA and CrewTrac logins, sealed end to end" });

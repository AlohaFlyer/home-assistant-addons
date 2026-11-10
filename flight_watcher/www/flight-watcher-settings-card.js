/* Flight Watcher: settings card (1.1.0). Edit the FLICA and CrewTrac logins and the last name from the dashboard,
   also for a user who is not a Home Assistant admin (1.4.5, Ryan Nov 6: labeled Credentials on the Settings tab).
   Usernames are shown; a password only as set / not set.
   On Save the form is sealed in the browser (AES-256-GCM, the key wrapped with this Watcher's RSA-OAEP public key
   from sensor.flight_watcher_settings) and published to flight_watcher/settings/set, so Home Assistant's history,
   logs and MQTT only ever see ciphertext. A blank field keeps what is saved (1.6.1: a password goes exactly as typed).
   On a plain http address (no crypto.subtle) it sends the fields unencrypted instead (Ryan: trusted users only).
   1.6.0 (FW-0061): on a pilot whose portal is on (sensor attribute ntfy true) it also offers the ntfy topic and access
   token, shown as set / not set only and sent sealed only: never on the plain fallback. Ryan's card never shows them.
   In the pilot portal (FW_PORTAL, turned on only in the portal's copy: portal.portal_card) nothing is ever sent
   unsealed: with no WebCrypto, or before the Watcher's key (pubkey) has loaded, Save sends nothing and says why.
   1.6.2 (Release A item 9, topic-only ntfy): the access token is optional. Before a first topic is sent the card says
   that anyone who learns the topic can read the alerts on ntfy.sh for about 12 h and asks for a tick; Generate (Rotate
   once one is saved) makes a 32-character random topic (crypto.getRandomValues) shown once, to subscribe to in the ntfy
   app; a typed topic needs at least 24 characters with letters and digits (else nothing is sent, with the reason);
   Turn off forgets the topic and token. The topic is never shown again after Save (the Watcher keeps set / not set). */
const FW_PORTAL = false;
const FW_SET_FIELDS = [
  ["username", "FLICA username", false], ["password", "FLICA password", true],
  ["ctweb_username", "CrewTrac username", false], ["ctweb_password", "CrewTrac password", true],
  ["my_name", "Last name", false],
];
const FW_NTFY_FIELDS = [["ntfy_topic", "ntfy topic", true], ["ntfy_token", "ntfy access token", true]];
// 1.6.2: ntfy.TOPIC_RE, ntfy.TOPIC_MIN and ntfy.GEN_LEN (the Watcher checks the same again)
const FW_TOPIC_RE = /^[A-Za-z0-9_-]{1,64}$/;
const FW_TOPIC_MIN = 24;
const FW_TOPIC_LEN = 32;
const FW_TOPIC_ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
function fwTopicWhy(t) {
  if (!FW_TOPIC_RE.test(t)) return "use only letters, digits, - and _ (at most 64)";
  if (t.length < FW_TOPIC_MIN || !/[A-Za-z]/.test(t) || !/\d/.test(t)) return `use at least ${FW_TOPIC_MIN} characters with both letters and digits, or tap Generate`;
  return "";
}
function fwNewTopic() {  // 32 characters from 62, no modulo bias (bytes of 248 and up are drawn again), letters and digits both
  for (;;) {
    let out = "";
    while (out.length < FW_TOPIC_LEN) {
      for (const b of crypto.getRandomValues(new Uint8Array(48))) if (b < 248 && out.length < FW_TOPIC_LEN) out += FW_TOPIC_ABC[b % 62];
    }
    if (!fwTopicWhy(out)) return out;
  }
}

class FlightWatcherSettingsCard extends HTMLElement {
  setConfig(c) {
    this._c = { entity: "sensor.flight_watcher_settings", topic: "flight_watcher/settings/set", ...c };
    this._built = false;
  }
  getCardSize() { return 6; }
  set hass(h) {
    this._h = h;
    if (!this._built || this._bkey !== this._buildKey()) this._build();
    this._status();
  }
  _st() { return (this._h && this._h.states[this._c.entity]) || { attributes: {} }; }
  _ntfyOn() { return (this._st().attributes || {}).ntfy === true; }
  _buildKey() {  // 1.6.2: the ntfy section follows whether a topic is saved (Generate / Rotate, the status line)
    const a = this._st().attributes || {};
    return JSON.stringify([this._ntfyOn(), !!a.has_ntfy_topic, a.ntfy_topic_ok]);
  }
  _fields() { return this._ntfyOn() ? FW_SET_FIELDS.concat(FW_NTFY_FIELDS) : FW_SET_FIELDS; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }
  _ntfyHtml(a) {  // 1.6.2: the phone alert section (a portal pilot only)
    const has = !!a.has_ntfy_topic;
    const weak = has && a.ntfy_topic_ok === false;
    return `<div class="nt"><b>Phone alerts (ntfy, optional)</b>
      <div class="note">Alerts go to the free ntfy app through ntfy.sh. <b>Anyone who learns your topic can read your alerts there for about 12 hours</b>, so treat the topic like a password and keep it to yourself. Each alert says only the pairing number, the date and the fit: no names, employee numbers or links. An access token (from a reserved topic on your own ntfy account) is optional and keeps others out.</div>
      <div class="note" id="ntst">Topic: <b class="${has && !weak ? "set" : "unset"}">${weak ? "saved, but too easy to guess: alerts are off until you save a new one" : has ? "set (not shown again)" : "not set: phone alerts are off"}</b></div>
      ${has ? "" : `<label class="ack"><input type="checkbox" id="ack"> I understand that anyone who learns my topic can read my alerts</label>`}
      <button type="button" id="gen">${has ? "Rotate topic" : "Generate topic"}</button>${has ? ` <button type="button" class="g" id="off">Turn off phone alerts</button>` : ""}
      <div class="topic" id="newtopic" hidden></div>
      <label><span>ntfy topic</span><input type="text" data-k="ntfy_topic" autocomplete="off" spellcheck="false" placeholder="Generate, or type 24+ letters and digits"></label>
      <label><span>ntfy access token</span><input type="password" data-k="ntfy_token" autocomplete="new-password" placeholder="optional; blank keeps"><b data-s="ntfy_token"></b></label></div>`;
  }
  _gen() {  // 1.6.2: a new random topic, shown once until Save
    const root = this.shadowRoot;
    if (!(window.crypto && crypto.getRandomValues)) { root.getElementById("msg").innerHTML = `<span class="err">This browser cannot make a random topic: type one of at least ${FW_TOPIC_MIN} letters and digits.</span>`; return; }
    const t = fwNewTopic();
    const inp = [...root.querySelectorAll("input[data-k]")].find((i) => i.dataset.k === "ntfy_topic");
    if (inp) inp.value = t;
    const box = root.getElementById("newtopic");
    box.hidden = false;
    box.innerHTML = `Your new topic: <code>${this._e(t)}</code><br>Subscribe to it in the ntfy app now (server ntfy.sh), then tap Save. It is not shown again after you save${this._st().attributes.has_ntfy_topic ? "; the old topic stops getting alerts" : ""}.`;
  }
  _build() {
    const a = this._st().attributes || {};
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    this._ntfy = this._ntfyOn();
    this._bkey = this._buildKey();
    const rows = FW_SET_FIELDS.map(([k, label, secret]) => secret
      ? `<label><span>${label}</span><input type="password" data-k="${k}" autocomplete="new-password" placeholder="leave blank to keep"><b data-s="${k}"></b></label>`
      : `<label><span>${label}</span><input type="text" data-k="${k}" autocomplete="off" spellcheck="false" value="${this._e(a[k])}"></label>`).join("") + (this._ntfy ? this._ntfyHtml(a) : "");
    root.innerHTML = `<style>
      ha-card{padding:16px}label{display:flex;align-items:center;gap:8px;margin:8px 0;flex-wrap:wrap}
      label span{width:150px}input{flex:1;min-width:160px;max-width:320px;padding:6px;font:inherit;
      border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color)}
      b.set{color:#2e7d32}b.unset{color:#c62828}button{padding:8px 16px;border:0;border-radius:6px;
      background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;cursor:pointer}
      .note{opacity:.75;font-size:13px}.msg{margin-top:8px}.err{color:#c62828}.ok{color:#2e7d32}
      .nt{margin:12px 0;padding-top:8px;border-top:1px solid var(--divider-color,#ccc)}.nt .note b{opacity:1}
      .ack{font-size:13px;flex-wrap:nowrap;align-items:flex-start}.ack input{flex:0 0 auto;min-width:0;width:22px;height:22px;margin:0}.topic{margin:8px 0;padding:8px;border-radius:6px;background:rgba(46,125,50,.12);font-size:13px;overflow-wrap:anywhere}
      .topic code{font-size:15px;user-select:all}button.g{background:#757575}button{min-height:44px;margin:4px 0}</style>
      <ha-card><div class="note">Saved on this Home Assistant only, encrypted before it leaves this screen. A blank field keeps
      what is saved. Saving restarts the Watcher; with a new FLICA login it logs in within a minute.</div>
      ${rows}<button id="save">Save credentials</button><div class="msg" id="msg"></div>
      <div class="note" id="who"></div></ha-card>`;
    root.getElementById("save").addEventListener("click", () => this._save());
    if (this._ntfy) {
      root.getElementById("gen").addEventListener("click", () => this._gen());
      if (a.has_ntfy_topic) root.getElementById("off").addEventListener("click", () => this._save({ ntfy_off: true }));
    }
    this._built = true;
  }
  _status() {
    const root = this.shadowRoot; if (!root) return;
    const a = this._st().attributes || {};
    for (const [k, , secret] of this._fields()) {
      if (!secret) continue;
      const has = k === "password" ? a.has_password : a["has_" + k];
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
    if (FW_PORTAL) root.getElementById("save").disabled = !a.pubkey;
  }
  async _save(only) {
    const root = this.shadowRoot, msg = root.getElementById("msg");
    const a = this._st().attributes || {};
    const fields = {};
    // 1.6.1: a password-type field goes exactly as typed (a space may be part of it); the others are trimmed
    if (only) Object.assign(fields, only);  // 1.6.2: Turn off phone alerts sends only {ntfy_off: true}
    else root.querySelectorAll("input[data-k]").forEach((i) => {
      const v = i.type === "password" ? i.value : i.value.trim();
      if (v.trim()) fields[i.dataset.k] = v;
    });
    for (const [k, , secret] of FW_SET_FIELDS) if (!secret && fields[k] === String(a[k] || "")) delete fields[k];
    if (!Object.keys(fields).length) { msg.innerHTML = `<span class="err">Nothing to save: no field changed.</span>`; return; }
    const subtle = !!(window.crypto && crypto.subtle);
    if (FW_PORTAL && (!subtle || !a.pubkey)) {
      // 1.6.0 (FW-0061): the portal only ever relays ciphertext, so a login goes sealed or not at all.
      msg.innerHTML = `<span class="err">${subtle ? "The Watcher's key has not loaded yet: try again in a minute." : "Credentials are sent encrypted only: open this page over https."} Nothing was sent.</span>`;
      return;
    }
    if (!subtle || !a.pubkey) {
      // Plain http (no WebCrypto) or no key yet: send unencrypted, as Ryan accepted (trusted users only).
      // 1.6.0: never the ntfy topic or token; those go sealed or not at all.
      const held = FW_NTFY_FIELDS.filter(([k]) => k in fields).length + ("ntfy_off" in fields ? 1 : 0);
      for (const [k] of FW_NTFY_FIELDS) delete fields[k];
      delete fields.ntfy_off;
      if (!Object.keys(fields).length) { msg.innerHTML = `<span class="err">${held ? "The ntfy settings are sent encrypted only: open this page over https." : "Nothing to save: no field changed."}</span>`; return; }
      this._sentAt = a.at || "-";
      try {
        await this._h.callService("mqtt", "publish", { topic: this._c.topic, payload: JSON.stringify(fields) });
        root.querySelectorAll("input[type=password]").forEach((i) => { i.value = ""; });
        msg.innerHTML = `<span class="ok">Sent (not encrypted on this address). Waiting for the Watcher to confirm...</span>`;
      } catch (e) {
        this._sentAt = null;
        msg.innerHTML = `<span class="err">Not sent: ${this._e(e && e.message ? e.message : e)}</span>`;
      }
      return;
    }
    if (fields.ntfy_topic !== undefined) {  // 1.6.2: a topic anyone could guess, or one sent before the warning was read
      const why = fwTopicWhy(fields.ntfy_topic);
      const ack = root.getElementById("ack");
      if (why) { msg.innerHTML = `<span class="err">ntfy topic: ${this._e(why)}. Nothing was sent.</span>`; return; }
      if (!a.has_ntfy_topic && !(ack && ack.checked)) { msg.innerHTML = `<span class="err">Read the note above the ntfy topic and tick "I understand" first. Nothing was sent.</span>`; return; }
    }
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
      root.querySelectorAll("input[data-k]").forEach((i) => { if (i.dataset.k === "ntfy_topic") i.value = ""; });  // 1.6.2: shown once
      const box = root.getElementById("newtopic");
      if (box) { box.hidden = true; box.innerHTML = ""; }
      msg.innerHTML = `<span class="ok">Sent. Waiting for the Watcher to confirm...</span>`;
    } catch (e) {
      this._sentAt = null;
      msg.innerHTML = `<span class="err">Not sent: ${this._e(e && e.message ? e.message : e)}</span>`;
    }
  }
}
customElements.define("flight-watcher-settings-card", FlightWatcherSettingsCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-settings-card", name: "Flight Watcher credentials", description: "Edit the FLICA and CrewTrac logins, sealed end to end" });

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
   Turn off forgets the topic and token. The topic is never shown again after Save (the Watcher keeps set / not set).
   1.6.2 review: the confirmation outlives the restart a save causes: "Restarting with your settings..." while the Watcher
   is unavailable, then its "saved: ... (Watcher restarted with them)"; a rebuild keeps the message line.
   1.6.4: a Date of hire field (optional, a date input filled with the saved value from the settings sensor's doh). It
   sets the longevity year of the pay estimates (PWA 3.B.1) and goes like the other non-secret fields (sealed when it
   can be, inside the sealed payload only in the portal). Checked here and again by the Watcher (fwDohWhy: YYYY-MM-DD, a
   real date, not after today HST, not before 1960). The Watcher keeps it in its own cards.json; a date of hire alone
   does not restart it. 1.6.4 review: beside it the year pay uses (a year set in Pay settings wins, as on the schedule
   card); the portal copy says the date is shown back on the page (state.json), so the portal can read it.
   1.7.1 (F#93): each secret field has a Show / Hide button (a typo on a phone keyboard is otherwise invisible) and
   autocomplete="off" (no "new-password" invitation to fill in a generated password for an existing FLICA or CrewTrac
   login); a password still goes exactly as typed, shown or not. The Watcher's "nothing new" reads as no change, in a
   neutral color, not as a green save. (F#155) While a CrewTrac login is saved, Remove CrewTrac login sends the sealed
   {ctweb_off: true} (sealed only, like Turn off phone alerts), after a confirm. (F#119) The status colors are this
   card's own variables, lighter on dark cards (prefers-color-scheme, as the portal's dark mode): WCAG AA 4.5:1 on both.
   1.7.1 review: on a phone (700 px or less) every field is 16 px: iOS Safari zooms into a smaller one when it is tapped
   and leaves the page wider than the screen (as F#43 found for the pilot lookup). */
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
// 1.6.4: the Watcher's DOH_MIN and doh_refusal (watcher.py) check the same again
const FW_DOH_MIN = "1960-01-01";
const fwHstToday = () => new Date(Date.now() - 10 * 3600e3).toISOString().slice(0, 10);
function fwDohWhy(v, today) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!m) return "use YYYY-MM-DD";
  const [y, mo, d] = [m[1], m[2], m[3]].map(Number), t = new Date(Date.UTC(y, mo - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) return "not a real date";
  if (v > (today || fwHstToday())) return "it is in the future";
  if (v < FW_DOH_MIN) return `it is before ${FW_DOH_MIN.slice(0, 4)}`;
  return "";
}
// longevity year on iso from the DOH: year 1 from the DOH, a new year on each anniversary (PWA 3.B.1, 3.D.2), as the
// schedule card's dohYear() and pay.doh_year() count; the rate table caps at 12 (PWA 3.D.6)
const fwDohYear = (doh, iso) => { const [a, b] = [doh, iso].map((x) => x.split("-").map(Number)); return b[0] - a[0] - (b[1] < a[1] || (b[1] === a[1] && b[2] < a[2]) ? 1 : 0) + 1; };
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
    if (!this._built || this._bkey !== this._buildKey()) {
      // 1.6.2 review: a rebuild keeps the message line (a save's confirmation must outlive the restart it causes)
      const old = this.shadowRoot && this.shadowRoot.getElementById("msg");
      const keep = old ? old.innerHTML : "";
      this._build();
      if (keep) this.shadowRoot.getElementById("msg").innerHTML = keep;
    }
    this._status();
  }
  _st() { return (this._h && this._h.states[this._c.entity]) || { attributes: {} }; }
  _ntfyOn() { return (this._st().attributes || {}).ntfy === true; }
  _buildKey() {  // 1.6.2: the ntfy section follows whether a topic is saved (Generate / Rotate, the status line)
    const a = this._st().attributes || {};
    // 1.6.2 review: while the Watcher restarts (unavailable: no ntfy attribute) the form stays as it is; 1.7.1: the same
    // with no attributes at all, now that a saved CrewTrac login (its Remove button, F#155) is part of the form too
    if (this._built && ((typeof a.ntfy !== "boolean" && this._ntfy) || typeof a.has_password !== "boolean")) return this._bkey;
    return JSON.stringify([this._ntfyOn(), !!a.has_ntfy_topic, a.ntfy_topic_ok, this._ctSaved(a)]);
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
      <label><span>ntfy access token</span>${this._secret("ntfy_token", "optional; blank keeps")}<b data-s="ntfy_token"></b></label></div>`;
  }
  // 1.7.1 (F#93): a secret field with its Show / Hide button. autocomplete off (not "new-password", which invites the
  // browser to suggest a generated password); no capitals or corrections while it is shown as text
  _secret(k, ph) {
    return `<span class="sec"><input type="password" data-k="${k}" data-secret autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="${ph}">`
      + `<button type="button" class="eye" data-eye="${k}" aria-pressed="false" aria-label="Show what is typed">Show</button></span>`;
  }
  // 1.7.1 (F#155): a CrewTrac login a pilot saved (his Watcher keeps it in its creds.json, which Remove clears); never on
  // the admin's own instance (instance ""), whose logins may live in the add-on's options, which the card cannot change
  _ctSaved(a) { return !!a.instance && !!(a.ctweb_username || a.has_ctweb_password); }
  _dohHtml(a) {  // 1.6.4: the date of hire (optional; the pay estimates' longevity year)
    const doh = /^\d{4}-\d{2}-\d{2}$/.test(a.doh || "") ? a.doh : "";
    this._dohShown = doh;
    return `<label><span>Date of hire</span><input type="date" data-k="doh" min="${FW_DOH_MIN}" max="${fwHstToday()}" value="${this._e(doh)}"><b data-s="doh"></b></label>
      <div class="note" id="dohnote">Your date of hire sets your longevity year for pay estimates (PWA 3.B.1); ${FW_PORTAL ? "your Watcher keeps it and shows it back to you on this page, so unlike your logins the portal can read it" : "it stays on this Watcher only"}. Optional; a blank field keeps what is saved, and saving only a date of hire does not restart the Watcher.</div>`;
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
    const ct = this._ctSaved(a);
    const rows = FW_SET_FIELDS.map(([k, label, secret]) => (secret
      ? `<label><span>${label}</span>${this._secret(k, "leave blank to keep")}<b data-s="${k}"></b></label>`
      : `<label><span>${label}</span><input type="text" data-k="${k}" autocomplete="off" spellcheck="false" value="${this._e(a[k])}"></label>`)
      // 1.7.1 (F#155): forget the saved CrewTrac login (sealed ctweb_off), offered only while one is saved
      + (k === "ctweb_password" && ct ? `<div class="rm"><button type="button" class="g" id="ctoff">Remove CrewTrac login</button><div class="note">Deletes the CrewTrac user ID and password saved on ${FW_PORTAL ? "your" : "this"} Watcher; charters are not read until new ones are saved.</div></div>` : "")).join("")
      + this._dohHtml(a) + (this._ntfy ? this._ntfyHtml(a) : "");
    root.innerHTML = `<style>
      @media (prefers-color-scheme: dark){:host{--fw-ok:#81c784;--fw-err:#ef9a9a}}
      ha-card{padding:16px}label{display:flex;align-items:center;gap:8px;margin:8px 0;flex-wrap:wrap}
      label span{width:150px}input{flex:1;min-width:160px;max-width:320px;padding:6px;font:inherit;
      border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color)}
      .sec{display:flex;flex:1;gap:6px;min-width:220px;max-width:320px;align-items:center}.sec input{min-width:0;max-width:none}
      b.set{color:var(--fw-ok,#2e7d32)}b.unset{color:var(--fw-err,#c62828)}button{padding:8px 16px;border:0;border-radius:6px;
      background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;cursor:pointer}
      .note{color:var(--secondary-text-color);font-size:13px}.msg{margin-top:8px}.err{color:var(--fw-err,#c62828)}.ok{color:var(--fw-ok,#2e7d32)}.nn{color:var(--primary-text-color)}
      .nt{margin:12px 0;padding-top:8px;border-top:1px solid var(--divider-color,#ccc)}
      .ack{font-size:13px;flex-wrap:nowrap;align-items:flex-start}.ack input{flex:0 0 auto;min-width:0;width:22px;height:22px;margin:0}.topic{margin:8px 0;padding:8px;border-radius:6px;background:rgba(46,125,50,.12);font-size:13px;overflow-wrap:anywhere}
      .topic code{font-size:15px;user-select:all}button.g{background:#757575}button{min-height:44px;margin:4px 0}
      button.eye{flex:0 0 auto;min-width:64px;padding:6px 10px;margin:0;background:none;color:var(--primary-text-color);border:1px solid var(--divider-color,#ccc)}
      .rm{margin:0 0 8px}@media (max-width:700px){input,select,textarea{font-size:16px}}</style>
      <ha-card><div class="note">${FW_PORTAL
        ? "Encrypted in your browser; only your Watcher can read it (the portal passes on ciphertext only). Your date of hire is shown back to you on this page, so the portal can read that one. A blank field keeps what is saved. Saving restarts your Watcher (a date of hire alone does not); with a new FLICA login it logs in within a minute."
        : "Saved on this Home Assistant only, encrypted before it leaves this screen. A blank field keeps what is saved. Saving restarts the Watcher (a date of hire alone does not); with a new FLICA login it logs in within a minute."}</div>
      ${rows}<button id="save">Save credentials</button><div class="msg" id="msg"></div>
      <div class="note" id="ct"></div><div class="note" id="who"></div></ha-card>`;
    root.getElementById("save").addEventListener("click", () => this._save());
    root.querySelectorAll("button[data-eye]").forEach((b) => b.addEventListener("click", () => this._eye(b)));
    const ctoff = root.getElementById("ctoff");
    if (ctoff) ctoff.addEventListener("click", () => {
      if (confirm(`Remove the CrewTrac login saved on ${FW_PORTAL ? "your" : "this"} Watcher? Charters are not read until new CrewTrac details are saved.`)) this._save({ ctweb_off: true });
    });
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
    this._dohStatus(a);
    const down = ["unavailable", "unknown"].includes(this._st().state);
    if (this._sentAt && down) {  // 1.6.2 review: a save restarts the Watcher; its confirmation comes after
      root.getElementById("msg").innerHTML = `<span class="ok">Restarting with your settings...</span>`;
    } else if (this._sentAt && a.at && a.at !== this._sentAt && a.result) {
      // 1.7.1 (F#93): the Watcher's "nothing new" is no save: it says so in a neutral color, not green ("nothing new: <why>"
      // gives its own reason, e.g. no CrewTrac login is saved)
      const res = String(a.result), same = res.startsWith("nothing");
      const cls = same ? "nn" : res.startsWith("saved") || res.startsWith("removed") ? "ok" : "err";
      const txt = !same ? res : /^nothing new: /.test(res) ? `No change: ${res.slice(13)}`
        : res.replace(/^nothing new/, "No change: what you entered is already saved");
      root.getElementById("msg").innerHTML = `<span class="${cls}">${this._e(txt)}</span>`;
      this._sentAt = null;
    }
    const st = this._h && this._h.states["sensor.flight_watcher_state"];
    root.getElementById("who").textContent = st ? `Watcher: ${st.state}` : "";
    // 1.6.2 (Release A item 14): whether CrewTrac takes the saved login (sensor.flight_watcher_charters, 1.6.1), next to
    // the fields that fix it; red while CrewTrac refuses it
    const ch = this._h && this._h.states["sensor.flight_watcher_charters"];
    const ca = (ch && ch.attributes) || {}, cst = (ca.crewtrac || {}).state || "";
    const ctEl = root.getElementById("ct");
    if (ctEl) {
      const said = String(ca.status || "");  // the Watcher's own words (crewtrac_text): they name CrewTrac already
      const txt = !ch ? "" : cst === "ok" ? "CrewTrac: the saved login works." : said && !said.startsWith("ok") ? said : "";
      ctEl.textContent = txt;
      ctEl.className = `note${cst === "refused" ? " err" : cst === "ok" ? " ok" : ""}`;
    }
    if (FW_PORTAL) root.getElementById("save").disabled = !a.pubkey;
  }
  _dohStatus(a) {  // 1.6.4: the saved date of hire's longevity year beside the field; a new saved value fills an untouched field
    // 1.6.4 review: the year pay uses, as the schedule card picks it: a longevity year set in Pay settings (the admin's
    // helper, or one the pilot chose or kept) wins over the DOH; one still flagged unconfirmed yields to it
    const root = this.shadowRoot, inp = root.querySelector('input[data-k="doh"]'), b = root.querySelector('b[data-s="doh"]');
    if (typeof a.has_password !== "boolean") return;  // the Watcher restarting (no attributes): keep what is shown
    const doh = /^\d{4}-\d{2}-\d{2}$/.test(a.doh || "") ? a.doh : "";
    if (inp && doh && doh !== this._dohShown && (inp.value === (this._dohShown || "") || inp.value === doh)) { inp.value = doh; this._dohShown = doh; }
    if (!b) return;
    const today = fwHstToday();
    b.className = doh ? "set" : "";
    if (!(doh && doh <= today)) { b.textContent = "not set"; return; }
    const dy = Math.min(12, fwDohYear(doh, today));
    const ly = (this._h && this._h.states["input_number.flight_watcher_longevity_year"]) || {};
    const py = (ly.attributes || {}).unconfirmed === true ? NaN : parseFloat(ly.state);
    b.textContent = isNaN(py) ? `longevity year ${dy}` : `year ${dy} from this date; pay uses year ${py}, set in Pay settings`;
  }
  _eye(b) {  // 1.7.1 (F#93): show or hide what is typed in one secret field
    const inp = this.shadowRoot.querySelector(`input[data-k="${b.dataset.eye}"]`);
    if (!inp) return;
    const show = inp.type === "password";
    inp.type = show ? "text" : "password";
    b.textContent = show ? "Hide" : "Show";
    b.setAttribute("aria-pressed", String(show));
    b.setAttribute("aria-label", show ? "Hide what is typed" : "Show what is typed");
  }
  _clearSecrets() {  // after a send: the secret fields empty and hidden again
    for (const sel of ["input[data-secret]", "input[type=password]"]) this.shadowRoot.querySelectorAll(sel).forEach((i) => { i.value = ""; i.type = "password"; });
    this.shadowRoot.querySelectorAll("button[data-eye]").forEach((b) => { b.textContent = "Show"; b.setAttribute("aria-pressed", "false"); b.setAttribute("aria-label", "Show what is typed"); });
  }
  async _save(only) {
    const root = this.shadowRoot, msg = root.getElementById("msg");
    const a = this._st().attributes || {};
    const fields = {};
    // 1.6.1: a secret field goes exactly as typed (a space may be part of it), 1.7.1 also while shown as text; the
    // others are trimmed
    if (only) Object.assign(fields, only);  // 1.6.2: Turn off phone alerts sends only {ntfy_off: true}; 1.7.1 {ctweb_off: true}
    else root.querySelectorAll("input[data-k]").forEach((i) => {
      const v = i.dataset.secret !== undefined || i.type === "password" ? i.value : i.value.trim();
      if (v.trim()) fields[i.dataset.k] = v;
    });
    for (const [k, , secret] of FW_SET_FIELDS) if (!secret && fields[k] === String(a[k] || "")) delete fields[k];
    if (fields.doh !== undefined && fields.doh === String(a.doh || "")) delete fields.doh;  // 1.6.4: unchanged
    if (!Object.keys(fields).length) { msg.innerHTML = `<span class="err">Nothing to save: no field changed.</span>`; return; }
    if (fields.doh !== undefined) {  // 1.6.4: the Watcher checks the same again
      const why = fwDohWhy(fields.doh);
      if (why) { msg.innerHTML = `<span class="err">Date of hire: ${this._e(why)}. Nothing was sent.</span>`; return; }
    }
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
      const ctOff = "ctweb_off" in fields;  // 1.7.1 (F#155): removing a login goes sealed or not at all
      for (const [k] of FW_NTFY_FIELDS) delete fields[k];
      delete fields.ntfy_off;
      delete fields.ctweb_off;
      if (!Object.keys(fields).length) { msg.innerHTML = `<span class="err">${ctOff ? "Removing a login is sent encrypted only: open this page over https." : held ? "The ntfy settings are sent encrypted only: open this page over https." : "Nothing to save: no field changed."}</span>`; return; }
      this._sentAt = a.at || "-";
      try {
        await this._h.callService("mqtt", "publish", { topic: this._c.topic, payload: JSON.stringify(fields) });
        this._clearSecrets();
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
      this._clearSecrets();
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

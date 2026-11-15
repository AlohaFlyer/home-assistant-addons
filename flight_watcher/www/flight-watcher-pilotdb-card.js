/* Flight Watcher: Pilots card, the pilot database (1.7.8; Ryan, Nov 14: "should we have an editable pilot database that
   has these data points. and even a notes field we can edit and append to"). One record per pilot, filled from the
   uploads (the seniority list, the award's dates of hire, the contact list) and kept by Ryan's Watcher only
   (pilotdb.py, /data/pilotdb.sqlite; never in git, never on a public address, nothing to FLICA).
   - Browse (follow: false, the Settings tab above the tickets): the status line (counts, source dates, seniority.md
     and copy times, from the admin's sensor.flight_watcher_pilotdb), a search (name words, an employee number,
     s<Sen #>, "quoted" text in the notes; debounced 300 ms) with filter chips, the results by Sen #, and the record:
     each field with its source and date and the other sources' values, a pencil to edit it (a hand edit stays shown
     through later uploads and is logged with your reason; on drift "Use upload value" or "Keep my edit"), call, text
     and mail links, the notes field (saved compare-and-set on the version it was read at: a newer save shows beside your draft, with
     "Take theirs" and "Save mine over theirs"; every version kept, Restore any), the dated log (add, Only me, take
     back your own, hide, restore, purge), the picker's pickup history (running count per layover station, trip
     length, turn or layover, credit, report time, weekday, pickup speed), the AI note read only when there is one
     (written later by HOM's models, labeled AI, never filled in 1.7.8), the history, merge, renumber and delete; the
     conflicts the uploads held for you; a new record; the daily copies and Restore.
   - Follow (follow: true, the watcher tab right under the pilot lookup card): the record and notes of the pilot that
     card shows (sensor.flight_watcher_pilot_schedule's emp and name, debounced 1 s). It never publishes pilot/set.
   Admin mode only (not FW_PORTAL, a Home Assistant admin, the admin's own copy): it talks to the app's ingress API
   (api/pilotdb) the way the uploads card does (an ingress session cookie, re-validated before it lapses), every POST
   as JSON with the header X-FW-Card: pilotdb. Anyone else sees one read-only line. The card is kept off every portal
   in 1.7.8 (watcher.PORTAL_CARDS_OUT); sharing with a portal pilot is 1.7.9.
   Rendering rule: every database value (notes, entries, and uploaded names, which are third-party PDF and CSV text
   too) goes in as text through h() (textContent and text nodes), never as markup; text is never turned into a link;
   the only links are tel:, sms: and mailto: set through the href property after the pilot card's number and address
   checks. No markup is ever parsed from a string here. */
const FW_PORTAL = false;  // portal.portal_card turns it on in a portal's copy (none in 1.7.8)
const FW_PDB_SLUG = ["43b22650", "flight", "watcher"].join("_");  // in parts: a pilot's copy keeps the one app's slug
const FW_PDB_PREFIX = "flight_watcher";  // cards.pilot_copy makes it flight_watcher_<name> in a pilot's copy
const FW_PDB_ADMIN_COPY = FW_PDB_PREFIX === ["flight", "watcher"].join("_");
const FW_PDB_SENSOR = "sensor.flight_watcher_pilotdb";  // the admin's only (roles.ENTITY_FEATURE one_writer)
const FW_PDB_PILOT = "sensor.flight_watcher_pilot_schedule";
const FW_PDB_ZERO = "000000000000";
const FW_PDB_ENTRY_MAX = 2000, FW_PDB_FIELD_MAX = 4000, FW_PDB_WHY_MAX = 200, FW_PDB_Q_MAX = 60;
const FW_PDB_REFRESH_MS = 5 * 60 * 1000;  // the Supervisor keeps an ingress session 15 min from its last validation
const FW_PDB_URL_RE = /^\/api\/hassio_ingress\/[A-Za-z0-9_-]+\/?$/;
const FW_PDB_TEL_RE = /^\+?\d{7,15}$/;  // the pilot card's PILOT_TEL_RE
const FW_PDB_MAIL_RE = /^[^\s@<>"'&]+@[^\s@<>"'&]+\.[A-Za-z]{2,}$/;  // the pilot card's PILOT_MAIL_RE
const FW_PDB_FIELDS = [["name", "Name"], ["sen", "Sen #"], ["doh", "DOH"], ["status", "Status"], ["retire", "Retires"],
  ["seat", "Seat"], ["equip", "Equipment"], ["phones", "Phones"], ["emails", "Emails"], ["union_id", "Union ID"]];
const FW_PDB_LABEL = Object.fromEntries(FW_PDB_FIELDS.concat([["text", "The text"], ["why", "The reason"], ["emp", "The employee #"],
  ["q", "The search"], ["entry", "That entry"], ["confirm", "The word typed"], ["base", "The version"], ["file", "That copy"]]));
const FW_PDB_HINT = { name: "Last, First M", sen: "1 to 5 digits", doh: "YYYY-MM-DD", status: "A, ALPA, EXEC, FUR, LOA, MLOA, MRET, PESL, SLOA or blank",
  retire: "YYYY-MM", seat: "CA, FO, RO or blank", equip: "330, 321, 717 ...", union_id: "1 to 10 digits",
  phones: "one a line: mobile 808-555-0100 (mobile, home, work or other)", emails: "one a line" };
const FW_PDB_FILTERS = [["all", "All"], ["notes", "Notes"], ["hand", "Edited"], ["drift", "Drift"], ["disagree", "Disagree"],
  ["conflict", "Held"], ["gone", "Gone"]];
const FW_PDB_SRC = { list: "List", award: "Award", contacts: "Contacts", hand: "Edited" };
const FW_PDB_KIND = { renumbered: "Renumbered? Same name and date of hire under a new employee #",
  other_pilot: "Another pilot on a known employee #", ambiguous: "Two records could be this row",
  contact_unmatched: "A contact that matched no record", list_partial: "A list much shorter than the last one" };
const FW_PDB_ANSWER = { same: "Same pilot", different: "Different pilot", attach: "Attach to a record", new: "New record",
  ignore: "Ignore", gone: "Mark them gone anyway" };
const FW_PDB_HOW = { created: "created", upload: "upload", hand: "edited", unset: "back to the uploads", keep: "kept my edit",
  gone: "gone from the list", back: "back on the list", move: "new employee #", merge: "merged", resolve: "resolved" };
const FW_PDB_DB = { off: "The pilot database is not open on this Watcher.",
  error: "The pilot database file failed its check and was set aside.",
  newer_db: "The pilot database file is from a newer Flight Watcher, so it is left as it is: update the app to use it.",
  restore_offered: "A newer copy of the pilot database is on the share than the file in use (an older /data restored?). Nothing was written over." };
const FW_PDB_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const fwPdbPad = (n) => String(n).padStart(2, "0");
const fwPdbHst = (iso, dateOnly) => {  // UTC ISO -> 'YYYY-MM-DD HH:MM HST' (Hawaii has no DST)
  const t = Date.parse(String(iso || ""));
  if (isNaN(t)) return "";
  const d = new Date(t - 10 * 3600e3);
  const day = `${d.getUTCFullYear()}-${fwPdbPad(d.getUTCMonth() + 1)}-${fwPdbPad(d.getUTCDate())}`;
  return dateOnly ? day : `${day} ${fwPdbPad(d.getUTCHours())}:${fwPdbPad(d.getUTCMinutes())} HST`;
};
const fwPdbSecs = (s) => (s == null || isNaN(+s) ? "" : +s < 60 ? `${Math.round(+s)} s` : +s < 3600 ? `${Math.floor(+s / 60)}m ${fwPdbPad(Math.round(+s % 60))}s` : `${Math.floor(+s / 3600)}h ${fwPdbPad(Math.floor((+s % 3600) / 60))}m`);
const fwPdbRid = () => {  // a request id (6 to 40 of [A-Za-z0-9_-]): a repeated POST adds nothing
  const a = new Uint8Array(16), c = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-";
  if (typeof crypto !== "undefined" && crypto && crypto.getRandomValues) crypto.getRandomValues(a);
  else for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256);
  return Array.from(a, (x) => c[x % 64]).join("");
};
const fwPdbLen = (s) => Array.from(String(s || "")).length;  // code points, as the Watcher counts
const fwPdbHttpErr = (status) => {
  const why = { 401: "Home Assistant did not accept the app session (HTTP 401). Reload the page and try again.",
    403: "The app refused the request (HTTP 403).", 404: "The app does not know this request (HTTP 404): is it updated to 1.7.8 or later?",
    413: "Too long to send (HTTP 413).", 502: "The Flight Watcher app did not answer (HTTP 502): is it running?",
    503: "The pilot database is not open (HTTP 503).", 504: "The Flight Watcher app took too long to answer (HTTP 504)." }[status] || `The app answered HTTP ${status}.`;
  const err = new Error(why);
  err.status = status;
  return err;
};
// every value goes in as text: h(tag, {class, attributes, on<event>}, ...children); children are nodes or text
const h = (tag, props, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (["value", "checked", "disabled", "type", "placeholder", "rows", "maxLength", "inputMode", "autocomplete", "spellcheck", "open"].includes(k)) el[k] = v;
    else if (/^(title|dir|role|tabindex|data-[a-z-]+|aria-[a-z]+|for|id|name|scope|colspan)$/.test(k)) el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false || c === "") continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
};
const fwPdbLink = (kind, v, label, title) => {  // tel:, sms: or mailto:, only after the pilot card's checks
  const ok = kind === "mailto" ? FW_PDB_MAIL_RE.test(v) : FW_PDB_TEL_RE.test(v);
  if (!ok) return null;
  const a = h("a", { class: "ct", title }, label);
  a.href = `${kind}:${v}`;
  return a;
};

const FW_PDB_CSS = `
:host{display:block}
.c{container-type:inline-size;padding:12px 14px 14px;color:var(--primary-text-color);font-size:14px;line-height:1.4}
.ttl{font-size:18px;font-weight:600;margin:0 0 4px}
.u{color:var(--secondary-text-color);font-size:13px}
.msg{margin:6px 0;min-height:0;font-size:13px}.msg:empty{display:none}
.msg.err,.err{color:var(--error-color,#c62828)}.msg.ok{color:var(--success-color,#2e7d32)}
:host([dark]) .msg.ok{color:#81c784}:host([dark]) .msg.err,:host([dark]) .err{color:#ef9a9a}
.ban{border:1px solid var(--warning-color,#b26a00);border-radius:8px;padding:8px 10px;margin:8px 0}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
input,textarea,select{font:inherit;color:var(--primary-text-color);background:var(--card-background-color,#fff);
 border:1px solid var(--divider-color,#ccc);border-radius:6px;padding:6px 8px;box-sizing:border-box;max-width:100%}
textarea{width:100%;resize:vertical;min-height:72px}
input[type=search]{flex:1 1 220px;min-width:0}
button{font:inherit;min-height:36px;padding:4px 12px;border-radius:18px;border:1px solid var(--primary-color);
 background:var(--primary-color);color:var(--text-primary-color,#fff);cursor:pointer}
button.g{background:transparent;color:var(--primary-color)}
button.s{min-height:30px;padding:2px 10px;font-size:13px}
button:disabled{opacity:.5;cursor:default}
button:focus-visible,input:focus-visible,textarea:focus-visible,a:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{border-radius:14px;padding:2px 10px;min-height:30px;border:1px solid var(--divider-color);background:transparent;color:var(--primary-text-color)}
.chip[aria-pressed=true]{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}
.tag{display:inline-block;border-radius:10px;padding:0 7px;font-size:12px;line-height:18px;border:1px solid var(--divider-color);
 color:var(--secondary-text-color);margin-left:4px;white-space:nowrap}
.tag.w{border-color:var(--warning-color,#b26a00);color:var(--primary-text-color)}
.tag.ai{border-color:var(--primary-color);color:var(--primary-color);font-weight:600}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:6px 0}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:6px 6px;border-bottom:1px solid var(--divider-color);vertical-align:top}
th{font-size:12px;color:var(--secondary-text-color);font-weight:600;white-space:nowrap}
tbody tr.pick{cursor:pointer}tbody tr.pick:hover{background:rgba(127,127,127,.06)}
tr.on td:first-child{box-shadow:inset 3px 0 0 var(--primary-color)}tr.on .nm{text-decoration:underline}
td.n{white-space:nowrap}
.nm{background:none;border:0;padding:0;min-height:0;color:var(--primary-color);text-align:left;font-weight:600;border-radius:4px}
.sec{border-top:1px solid var(--divider-color);margin-top:12px;padding-top:10px}
.sec>h3,.sec>summary{font-size:15px;font-weight:600;margin:0 0 6px}
details>summary{cursor:pointer;min-height:30px;line-height:30px}
.rec{border:1px solid var(--divider-color);border-radius:10px;padding:10px 12px;margin-top:12px}
.rh{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline;justify-content:space-between}
.rn{font-size:18px;font-weight:600;overflow-wrap:anywhere}
.fl{display:grid;grid-template-columns:120px minmax(0,1fr);gap:2px 10px;padding:6px 0;border-bottom:1px solid var(--divider-color)}
.fl:last-child{border-bottom:0}
.fk{color:var(--secondary-text-color);font-size:13px;padding-top:2px}
.fv{min-width:0}.fv .v{font-weight:600;overflow-wrap:anywhere}
.fv .cands{font-size:13px;color:var(--secondary-text-color);overflow-wrap:anywhere}
.ed{display:grid;gap:6px;margin-top:6px}
.tx{white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal}
.ent{padding:8px 0;border-bottom:1px solid var(--divider-color)}.ent:last-child{border-bottom:0}
.ent .meta{font-size:12px;color:var(--secondary-text-color);display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center}
.who{font-weight:600;color:var(--primary-text-color)}
.ent.gone .tx{opacity:.7;font-style:italic}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.box{border:1px solid var(--divider-color);border-radius:8px;padding:8px}
.cts{display:flex;flex-wrap:wrap;gap:6px 12px;margin:4px 0}
a.ct{color:var(--primary-color);font-weight:600;text-decoration:none;min-height:30px;display:inline-flex;align-items:center}
.cnt{font-size:12px;color:var(--secondary-text-color)}.cnt.over{color:var(--error-color,#c62828);font-weight:600}
.stn{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.stn span{border:1px solid var(--divider-color);border-radius:12px;padding:1px 9px;font-size:13px}
.pk td,.pk th{font-size:13px;white-space:nowrap}
label.ck{display:inline-flex;gap:6px;align-items:center;min-height:30px}
@container (max-width: 560px){
 .fl{grid-template-columns:minmax(0,1fr)}
 .two{grid-template-columns:minmax(0,1fr)}
 .hn{display:none}
}`;

class FlightWatcherPilotdbCard extends HTMLElement {
  setConfig(c) {
    const slug = String((c && c.slug) || FW_PDB_SLUG);
    if (!/^[a-z0-9_]{1,64}$/.test(slug)) throw new Error("slug: lowercase letters, digits and _ only");
    this._c = { ...(c || {}), slug, follow: !!(c && c.follow) };
    this._mode = null; this._base = null; this._sess = null; this._sessAt = 0; this._timer = null;
    this._q = ""; this._f = "all"; this._page = 0; this._res = null; this._rec = null; this._recWhy = "";
    this._conf = null; this._view = null; this._rev = null; this._msgEl = {}; this._d = {}; this._busy = false;
    this._follow = { sig: null, emp: "", name: "" };
  }
  getCardSize() { return this._c && this._c.follow ? 4 : 8; }
  _admin() { return !!(this._h && this._h.user && this._h.user.is_admin === true); }
  set hass(hs) {
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(hs && hs.themes && typeof hs.themes.darkMode === "boolean" ? hs.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
    this._h = hs;
    const mode = !FW_PORTAL && FW_PDB_ADMIN_COPY && this._admin() ? "admin" : "other";
    if (mode !== this._mode) {
      this._mode = mode;
      this._build();
      if (mode === "admin" && !this._c.follow) this._search(true);
    }
    if (mode !== "admin") return;
    this._fromSensor();
    if (this._c.follow) this._fromPilot();
  }
  connectedCallback() { if (this._mode === "admin" && this._c && !this._c.follow && this._res) this._search(false); }
  disconnectedCallback() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  }
  _state(id) { return (this._h && this._h.states && this._h.states[id]) || null; }
  _root() { return this.shadowRoot || this.attachShadow({ mode: "open" }); }

  // ---- layout
  _build() {
    const root = this._root();
    const style = document.createElement("style");
    style.textContent = FW_PDB_CSS;
    const card = document.createElement("ha-card");
    this._els = {};
    const box = h("div", { class: "c" });
    card.append(box);
    root.replaceChildren(style, card);
    if (this._mode !== "admin") {
      box.append(h("div", { class: "ttl" }, "Pilot database"),
        h("div", { class: "u" }, "The pilot database is on Ryan's dashboard, for a Home Assistant admin."));
      return;
    }
    const E = this._els;
    E.status = h("div", { class: "u", "data-status": "" });
    E.ban = h("div", {});
    E.msg = h("div", { class: "msg", role: "status", "aria-live": "polite" });
    if (this._c.follow) {
      E.rec = h("div", {});
      box.append(h("div", { class: "ttl" }, this._c.title || "Pilot database"), E.ban, E.msg, E.rec);
      this._renderRecord();
      return;
    }
    E.q = h("input", { type: "search", placeholder: 'Name, employee #, s812 for a Sen #, "text" in notes', autocomplete: "off",
      spellcheck: false, "aria-label": "Search the pilot database", "data-k": "q", value: this._q,
      oninput: (ev) => { this._q = ev.target.value; this._page = 0; clearTimeout(this._qT); this._qT = setTimeout(() => this._search(true), 300); } });
    E.chips = h("div", { class: "chips", role: "group", "aria-label": "Filter" });
    E.res = h("div", {});
    E.conf = h("div", {});
    E.rec = h("div", {});
    E.more = h("div", {});
    box.append(h("div", { class: "ttl" }, this._c.title || "Pilot database"), E.status, E.ban,
      h("div", { class: "row" }, E.q), E.chips, E.msg, E.res, E.rec, E.conf, E.more);
    this._renderChips();
    this._renderMore();
  }
  _say(where, text, cls) {
    const el = where === "main" ? this._els.msg : this._msgEl && this._msgEl[where];
    if (!el) return;
    el.className = `msg${cls ? " " + cls : ""}`;
    el.textContent = text || "";
  }
  _why(r, what) {  // a refusal: the field and why, never a value (the Watcher's answers carry none)
    if (r && r.field) return `${what ? what + ": " : ""}${FW_PDB_LABEL[r.field] || r.field} ${r.why || "was refused"}.`;
    if (r && r.why) return `${what ? what + ": " : ""}${r.why}.`;
    return `${what ? what + ": " : ""}not done.`;
  }
  _err(e) {
    if (e && e.message) return String(e.message);
    if (e && e.error && e.error.message) return String(e.error.message);
    return String(e || "failed");
  }

  // ---- the sensor (counts only) and the refetch when its rev moves
  _fromSensor() {
    const st = this._state(FW_PDB_SENSOR);
    const a = (st && st.attributes) || null;
    const sig = st ? `${st.state}|${st.last_updated || ""}` : "none";
    if (sig === this._sSig) return;
    this._sSig = sig;
    this._sensor = a;
    this._renderStatus();
    const rev = a && a.rev != null ? +a.rev : null;
    if (rev != null && this._rev != null && rev !== this._rev) {
      clearTimeout(this._revT);
      this._revT = setTimeout(() => this._refetch(), 400);
    }
    if (a && a.db && a.db !== "ok" && !this._view) this._loadStatus();
  }
  async _refetch() {
    if (!this._c.follow && this._res) await this._search(false);
    if (this._rec && this._rec.pid) await this._open(this._rec.pid, false);
    if (!this._c.follow && this._conf) await this._loadConflicts();
  }
  _renderStatus() {
    const E = this._els, a = this._sensor;
    if (!E || !E.ban) return;
    if (E.status) {
      const parts = [];
      if (!a) parts.push("The Watcher has not published the pilot database yet (Flight Watcher 1.7.8 or later).");
      else {
        const s = a.sources || {}, n = (k) => +(a[k] || 0);
        parts.push(`${n("live")} pilots${n("gone") ? ` (${n("gone")} gone)` : ""} · ${n("noted")} with notes · ${n("entries")} log entries` +
          `${n("entries_7d") ? ` (${n("entries_7d")} this week)` : ""} · ${n("hand")} edited${n("drift") ? ` · ${n("drift")} drift` : ""}` +
          `${n("conflicts") ? ` · ${n("conflicts")} held for you` : ""}` +
          `${n("pickers") ? ` · ${n("pickups")} pickup${n("pickups") === 1 ? "" : "s"} by ${n("pickers")} picker${n("pickers") === 1 ? "" : "s"}` : ""}`);
        const src = [];
        if (s.list && s.list.date) src.push(`seniority list ${s.list.date} (${s.list.count} rows)`);
        if (s.contacts && s.contacts.date) src.push(`contact list ${s.contacts.date} (${s.contacts.count} rows)`);
        if (s.award && s.award.month) src.push(`award ${s.award.month}`);
        parts.push(src.length ? `Sources: ${src.join(", ")}.` : "No upload merged yet.");
        const when = [];
        if (a.md_at) when.push(`seniority.md ${fwPdbHst(a.md_at)}`);
        if (a.backup_at) when.push(`copies ${fwPdbHst(a.backup_at)}`);
        if (when.length) parts.push(when.join(" · "));
      }
      E.status.replaceChildren(...parts.map((p) => h("div", {}, p)));
    }
    const ban = [];
    if (a && a.db && a.db !== "ok") {
      ban.push(h("div", {}, FW_PDB_DB[a.db] || "The pilot database is not open."));
      const offer = this._view && this._view.status && this._view.status.offer;
      if (offer && offer.file) ban.push(this._restoreBox(offer, a.db === "restore_offered" ? `Put back the copy of ${offer.day} (revision ${offer.rev})` : `Put back the newest good copy, ${offer.day}`));
    }
    if (a && a.contacts === "no-source") ban.push(h("div", {}, "Upload the pilot contact list again: its Notes could not be read again (no kept file)."));
    E.ban.replaceChildren(...(ban.length ? [h("div", { class: "ban", role: "alert" }, ban)] : []));
  }

  // ---- browse: the search and its results
  _renderChips() {
    const E = this._els;
    E.chips.replaceChildren(...FW_PDB_FILTERS.map(([k, label]) => h("button", { class: "chip", type: "button", "aria-pressed": String(this._f === k),
      onclick: () => { this._f = k; this._page = 0; this._renderChips(); this._search(true); if (k === "conflict") this._loadConflicts(); } }, label)));
  }
  async _search(show) {
    if (this._mode !== "admin" || this._c.follow) return;
    const q = this._q.trim();
    if (fwPdbLen(q) > FW_PDB_Q_MAX) { this._say("main", `The search is at most ${FW_PDB_Q_MAX} characters.`, "err"); return; }
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (this._f !== "all") p.set("f", this._f);
    if (this._page) p.set("page", String(this._page));
    const seq = (this._seq = (this._seq || 0) + 1);
    try {
      const r = await this._get(p.toString());
      if (seq !== this._seq) return;
      if (!r.ok) { this._say("main", this._why(r, "Search"), "err"); return; }
      this._res = r;
      this._rev = r.rev;
      if (show) this._say("main", "");
      this._renderResults();
      if (this._sensor && +this._sensor.conflicts > 0 && !this._conf) this._loadConflicts();
    } catch (e) {
      if (seq === this._seq) this._say("main", this._err(e), "err");
    }
  }
  _renderResults() {
    const E = this._els, r = this._res;
    if (!E.res) return;
    if (!r) { E.res.replaceChildren(h("div", { class: "u" }, "Loading the pilot database...")); return; }
    if (!r.rows.length) { E.res.replaceChildren(h("div", { class: "u" }, this._q || this._f !== "all" ? "No pilot matches." : "No pilot in the database yet: upload the seniority list or the contact list.")); return; }
    const open = this._rec && this._rec.pid;
    const rows = r.rows.map((x) => {
      const flags = (x.flags || []).map((f) => h("span", { class: `tag${["drift", "disagree", "conflict"].includes(f) ? " w" : ""}` }, { hand: "edited", shared: "shared #", conflict: "held" }[f] || f));
      const tr = h("tr", { class: `pick${x.pid === open ? " on" : ""}`, onclick: (ev) => { if (!ev.target.closest("button")) this._open(x.pid, true); } },
        h("td", { class: "n" }, x.sen || ""),
        h("td", {}, h("button", { class: "nm", type: "button", onclick: () => this._open(x.pid, true), dir: "auto" }, x.name || "(no name)")),
        h("td", { class: "n" }, x.emp),
        h("td", { class: "n" }, x.status || ""),
        h("td", { class: "n hn" }, x.doh || ""),
        h("td", { class: "n" }, x.notes_n ? String(x.notes_n) : ""),
        h("td", {}, flags));
      return tr;
    });
    const from = r.page * 50 + 1, to = r.page * 50 + r.rows.length;
    E.res.replaceChildren(
      h("div", { class: "wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Sen", "Name", "Emp", "Status", "DOH", "Notes", ""].map((c, i) => h("th", { scope: "col", class: i === 4 ? "hn" : null }, c)))),
        h("tbody", {}, rows))),
      h("div", { class: "row u" }, `${from} to ${to} of ${r.total}`,
        r.page > 0 ? h("button", { class: "g s", type: "button", onclick: () => { this._page -= 1; this._search(true); } }, "Previous") : null,
        r.more ? h("button", { class: "g s", type: "button", onclick: () => { this._page += 1; this._search(true); } }, "Next") : null));
  }

  // ---- the record
  async _open(pid, scroll) {
    if (!/^p[0-9a-f]{10}$/.test(String(pid || ""))) return;
    try {
      const r = await this._get(`pid=${pid}`);
      if (!r.ok) { this._say("main", this._why(r, "The record"), "err"); return; }
      this._setRec(r.record, r.rev);
      if (scroll && this._els.rec && this._els.rec.scrollIntoView) this._els.rec.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (e) {
      this._say("main", this._err(e), "err");
    }
  }
  _setRec(rec, rev) {
    const prev = this._rec && this._rec.pid;
    this._rec = rec;
    if (rec) this._recWhy = "";
    if (rev != null) this._rev = rev;
    if (!rec || rec.pid !== prev) { this._d = {}; this._noteConflict = null; }
    this._renderRecord();
    if (!this._c.follow) this._renderResults();
  }
  _keepFocus(box, paint) {  // a redraw keeps the field being typed in (drafts live in this._d)
    const root = this.shadowRoot, a = root && root.activeElement;
    const k = a && box.contains(a) && a.dataset ? a.dataset.k : null;
    const sel = k && typeof a.selectionStart === "number" ? [a.selectionStart, a.selectionEnd] : null;
    paint();
    if (!k) return;
    const n = Array.from(box.querySelectorAll("[data-k]")).find((x) => x.dataset.k === k);
    if (!n) return;
    n.focus();
    if (sel && n.setSelectionRange) { try { n.setSelectionRange(sel[0], sel[1]); } catch (e) { /* a field that takes no selection */ } }
  }
  _renderRecord() {
    const E = this._els;
    if (!E || !E.rec) return;
    this._keepFocus(E.rec, () => E.rec.replaceChildren(...this._recordNodes()));
  }
  _recordNodes() {
    const rec = this._rec;
    if (this._c.follow) {
      const f = this._follow;
      if (!f.emp && !f.name) return [h("div", { class: "u" }, "Look a pilot up above to see his record and notes.")];
      if (this._recWhy) {
        const add = /^[^,]+,\s*\S/.test(f.name || "") && /^\d{1,7}$/.test(f.emp || "")
          ? h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "new", emp: f.emp, name: f.name }, "main", "Record added.") }, "Add a record for him") : null;
        return [h("div", { class: "row" }, h("span", { class: "u" }, `${this._recWhy}.`), add)];
      }
      if (!rec) return [h("div", { class: "u" }, "Reading the pilot database...")];
    }
    if (!rec) return [];
    const m = (k) => (this._msgEl[k] = h("div", { class: "msg", role: "status", "aria-live": "polite" }));
    const F = rec.fields || {}, val = (k) => (F[k] && F[k].value) || "";
    const flags = [];
    if (rec.gone) flags.push(h("span", { class: "tag w" }, `gone from the list of ${String(rec.gone_from || "").replace(/^list /, "")}`));
    if (rec.emp_shared) flags.push(h("span", { class: "tag" }, "employee # shared with another record"));
    if (rec.merged_into) flags.push(h("span", { class: "tag w" }, "merged into another record"));
    const brief = [["Sen", val("sen")], ["Emp", rec.emp], ["DOH", val("doh")], ["Status", val("status")], ["Retires", val("retire")], ["Seat", val("seat")]]
      .filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(" · ");
    const head = h("div", { class: "rh" }, h("div", {}, h("div", { class: "rn", dir: "auto" }, val("name") || "(no name)", flags), h("div", { class: "u" }, brief)),
      this._c.follow ? null : h("button", { class: "g s", type: "button", onclick: () => { this._rec = null; this._renderRecord(); this._renderResults(); } }, "Close"));
    const out = [head, m("rec"), this._contactNodes(F)];
    const fields = h("div", {}, FW_PDB_FIELDS.map(([k, label]) => this._fieldNode(k, label, F[k] || {})));
    if (this._c.follow) out.push(this._det("fields", "sec", "Every field and its source", fields));
    else out.push(h("div", { class: "sec" }, h("h3", {}, "Fields"), h("div", { class: "u" }, "Each value with its source and date. An edit stays shown through later uploads and is logged with your reason."), fields));
    out.push(this._notesNode(rec, m("notes")), this._logNode(rec, m("log")), this._pickupsNode(rec.pickups));
    if (rec.ai_note && rec.ai_note.text) out.push(this._aiNode(rec.ai_note));
    if (!this._c.follow) out.push(this._historyNode(rec), this._dangerNode(rec, m("danger")));
    if ((rec.conflicts || []).length) out.push(h("div", { class: "sec" }, h("h3", {}, "Held for you"), h("div", { class: "u" }, `${rec.conflicts.length} upload row${rec.conflicts.length === 1 ? "" : "s"} about this record wait for your answer in the list of held rows (the Held filter).`)));
    return [h("div", { class: "rec", "data-rec": rec.pid }, out)];
  }
  _contactNodes(F) {
    const links = [];
    for (const p of (F.phones && Array.isArray(F.phones.value) ? F.phones.value : [])) {
      const lab = String(p.label || "other"), num = String(p.number || p.tel || "");
      const call = fwPdbLink("tel", String(p.tel || ""), `Call ${lab}`, `Call ${num}`);
      if (call) links.push(call);
      const text = lab === "mobile" ? fwPdbLink("sms", String(p.tel || ""), `Text ${lab}`, `Text ${num}`) : null;
      if (text) links.push(text);
    }
    for (const a of (F.emails && Array.isArray(F.emails.value) ? F.emails.value : [])) {
      const mail = fwPdbLink("mailto", String(a || ""), "Mail", `Mail ${a}`);
      if (mail) links.push(mail);
    }
    return links.length ? h("div", { class: "cts" }, links) : null;
  }
  _show(k, v) {  // a field's value as text
    if (k === "phones") return (Array.isArray(v) ? v : []).map((p) => `${p.label || "other"} ${p.number || p.tel || ""}`).join(", ");
    if (k === "emails") return (Array.isArray(v) ? v : []).join(", ");
    return String(v == null ? "" : v);
  }
  _srcLabel(x) {  // 'list 2026-11-01', 'contacts 2026-11-14', 'edited by ryan 2026-11-15'
    if (!x || !x.source) return "";
    if (x.source === "hand") return `edited by ${x.by || "ryan"} ${fwPdbHst(x.at, true) || x.as_of || ""}`.trim();
    return x.ref || `${FW_PDB_SRC[x.source] || x.source} ${x.as_of || ""}`;
  }
  _fieldNode(k, label, fv) {
    const rec = this._rec, ed = this._d.edit && this._d.edit.field === k ? this._d.edit : null;
    const shown = this._show(k, fv.value);
    const tags = [];
    if (fv.source) tags.push(h("span", { class: `tag${fv.hand ? " w" : ""}` }, this._srcLabel(fv)));
    if (fv.stale && fv.source === "list") tags.push(h("span", { class: "tag" }, `last on the list of ${String(fv.ref || "").replace(/^list /, "")}`));
    if (fv.disagree) tags.push(h("span", { class: "tag w" }, "sources disagree"));
    const up = fv.up;  // on drift its own line below says what the uploads have
    const others = (fv.cands || []).filter((c) => !(c.source === fv.source && !fv.hand) && this._show(k, c.value) !== ""
      && !(fv.drift && up && c.source === up.source))
      .map((c) => `${c.ref || c.source}: ${this._show(k, c.value)}${c.stale ? " (no longer on it)" : ""}`);
    const lines = [h("div", { class: "row" }, h("span", { class: "v", dir: "auto" }, shown || "-"), tags,
      ed ? null : h("button", { class: "g s", type: "button", "aria-label": `Edit ${label}`, title: `Edit ${label}`,
        onclick: () => { this._d.edit = { field: k, value: k === "phones" ? (fv.value || []).map((p) => `${p.label} ${p.number}`).join("\n") : k === "emails" ? (fv.value || []).join("\n") : shown, why: "" }; this._renderRecord(); this._focus(`edit-${k}`); } }, "Edit"))];
    if (fv.hand && fv.why) lines.push(h("div", { class: "cands" }, "Why: ", h("span", { dir: "auto" }, fv.why)));
    if (others.length) lines.push(h("div", { class: "cands", dir: "auto" }, others.join(" · ")));
    if (fv.hand) {
      const acts = [h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "unset", pid: rec.pid, field: k, rev: rec.rev }, "rec", `${label}: back to the uploads.`) }, "Use upload value")];
      if (fv.drift) acts.push(h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "keep", pid: rec.pid, field: k }, "rec", `${label}: your edit is kept.`) }, "Keep my edit"));
      lines.push(h("div", { class: "row cands" }, fv.drift && up ? h("span", { class: "tag w" }, `${up.ref || up.source} says ${this._show(k, up.value)}`) : null, acts));
    }
    if (ed) {
      const multi = k === "phones" || k === "emails";
      const input = multi
        ? h("textarea", { rows: 3, "data-k": `edit-${k}`, value: ed.value, "aria-label": label, oninput: (ev) => { ed.value = ev.target.value; } })
        : h("input", { type: "text", "data-k": `edit-${k}`, value: ed.value, "aria-label": label, autocomplete: "off", spellcheck: false, oninput: (ev) => { ed.value = ev.target.value; } });
      lines.push(h("div", { class: "ed" }, input, h("div", { class: "u" }, FW_PDB_HINT[k] || ""),
        h("input", { type: "text", "data-k": `why-${k}`, value: ed.why, placeholder: "Reason (optional, one line)", "aria-label": "Reason", maxLength: FW_PDB_WHY_MAX, oninput: (ev) => { ed.why = ev.target.value; } }),
        h("div", { class: "row" }, h("button", { type: "button", onclick: () => this._saveField(k, label) }, "Save"),
          h("button", { class: "g", type: "button", onclick: () => { this._d.edit = null; this._renderRecord(); } }, "Cancel"))));
    }
    return h("div", { class: "fl" }, h("div", { class: "fk" }, label), h("div", { class: "fv" }, lines));
  }
  _det(key, cls, summary, ...kids) {  // a fold that stays open (or shut) through a redraw
    const o = this._folds || (this._folds = {});
    return h("details", { class: cls || null, open: !!o[key], ontoggle: (ev) => { o[key] = ev.target.open; } }, h("summary", {}, summary), ...kids);
  }
  _focus(k) {
    const box = this._els && this._els.rec;
    const n = box && Array.from(box.querySelectorAll("[data-k]")).find((x) => x.dataset.k === k);
    if (n) n.focus();
  }
  _parseList(k, text) {
    const lines = String(text || "").split("\n").map((s) => s.trim()).filter(Boolean);
    if (k === "emails") return lines;
    return lines.map((s) => {
      const m = /^(mobile|cell|home|work|other)\s*[:\s]\s*(.+)$/i.exec(s);
      return m ? { label: m[1].toLowerCase(), number: m[2] } : { label: "other", number: s };
    });
  }
  async _saveField(k, label) {
    const rec = this._rec, ed = this._d.edit;
    if (!rec || !ed) return;
    if (fwPdbLen(ed.why) > FW_PDB_WHY_MAX) { this._say("rec", `The reason is at most ${FW_PDB_WHY_MAX} characters.`, "err"); return; }
    const value = k === "phones" || k === "emails" ? this._parseList(k, ed.value) : ed.value;
    const r = await this._post({ op: "set", pid: rec.pid, field: k, value, why: ed.why, rev: rec.rev }, "rec", `${label} saved. It stays shown through later uploads.`, true);
    if (r && r.ok) { this._d.edit = null; this._renderRecord(); this._say("rec", `${label} saved. It stays shown through later uploads.`, "ok"); }
    else if (r && r._status === 409) this._say("rec", `${label} was not saved: the record changed meanwhile (an upload?). It is shown as it is now; check it and save again.`, "err");
  }

  // ---- the notes field (compare-and-set) and its versions
  _notesNode(rec, msg) {
    const cur = rec.notes || null, d = this._d.notes;
    const text = d ? d.text : (cur ? cur.text : "");
    const base = d ? d.base : (cur ? cur.rev : FW_PDB_ZERO);
    const n = fwPdbLen(text);
    const cnt = h("span", { class: `cnt${n > FW_PDB_FIELD_MAX ? " over" : ""}` }, `${n} / ${FW_PDB_FIELD_MAX}`);
    const ta = h("textarea", { rows: 4, "data-k": "notes", value: text, dir: "auto", "aria-label": "Notes",
      oninput: (ev) => { this._d.notes = { text: ev.target.value, base }; const k = fwPdbLen(ev.target.value); cnt.textContent = `${k} / ${FW_PDB_FIELD_MAX}`; cnt.className = `cnt${k > FW_PDB_FIELD_MAX ? " over" : ""}`; } });
    const kids = [h("h3", {}, "Notes"), ta, h("div", { class: "row" },
      h("button", { type: "button", onclick: () => this._saveNotes(base) }, "Save notes"), cnt,
      cur ? h("span", { class: "u" }, `Saved by ${cur.by} ${fwPdbHst(cur.at)}`) : h("span", { class: "u" }, "No notes yet")), msg];
    if (d && cur && cur.rev !== d.base && !this._noteConflict) kids.push(h("div", { class: "u" }, "The notes changed since you started typing: Save shows both."));
    const c = this._noteConflict;
    if (c) {
      kids.push(h("div", { class: "ban", role: "alert" },
        h("div", {}, `Not saved: changed by ${c.by || "someone"}${c.at ? ` at ${fwPdbHst(c.at)}` : ""}. Your text is still in the box.`),
        h("div", { class: "two" }, h("div", { class: "box" }, h("div", { class: "u" }, "Theirs (saved)"), h("div", { class: "tx", dir: "auto" }, c.text || "(empty)")),
          h("div", { class: "box" }, h("div", { class: "u" }, "Yours (not saved)"), h("div", { class: "tx", dir: "auto" }, text || "(empty)"))),
        h("div", { class: "row" }, h("button", { class: "g", type: "button", onclick: () => { this._d.notes = null; this._noteConflict = null; this._renderRecord(); } }, "Take theirs"),
          h("button", { type: "button", onclick: () => { const t = this._d.notes ? this._d.notes.text : text; this._d.notes = { text: t, base: c.rev }; this._noteConflict = null; this._saveNotes(c.rev); } }, "Save mine over theirs"))));
    }
    const hist = rec.notes_hist || [];
    if (hist.length) {
      kids.push(this._det("hist", null, `Earlier versions (${hist.length})`, hist.map((v) => h("div", { class: "ent" },
        h("div", { class: "meta" }, h("span", { class: "who" }, v.by), `saved ${fwPdbHst(v.at)}, replaced ${fwPdbHst(v.replaced_at)} by ${v.replaced_by}`),
        v.purged ? h("div", { class: "u" }, "purged") : h("div", { class: "tx", dir: "auto" }, v.text || "(empty)"),
        v.purged ? null : h("div", { class: "row" },
          h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "restore_field", pid: rec.pid, hist_id: v.id, base: cur ? cur.rev : FW_PDB_ZERO }, "notes", "That version is the notes again (a new save; the one it replaced is kept).") }, "Restore"),
          h("button", { class: "g s", type: "button", onclick: () => { if (confirm("Purge this version's text for good? It also leaves the daily copies.")) this._post({ op: "purge", hist_id: v.id }, "notes", "Purged."); } }, "Purge"))))));
    }
    return h("div", { class: "sec" }, kids);
  }
  async _saveNotes(base) {
    const rec = this._rec;
    if (!rec) return;
    const text = this._d.notes ? this._d.notes.text : (rec.notes ? rec.notes.text : "");
    if (fwPdbLen(text) > FW_PDB_FIELD_MAX) { this._say("notes", `The notes field is at most ${FW_PDB_FIELD_MAX} characters.`, "err"); return; }
    const r = await this._post({ op: "field", pid: rec.pid, text, base }, "notes", "Notes saved.", true);
    if (r && r.ok) { this._d.notes = null; this._noteConflict = null; this._renderRecord(); this._say("notes", "Notes saved.", "ok"); }
    else if (r && r._status === 409 && r.conflict) {  // the newer text beside the draft; the record read again behind it
      const c = r.conflict;
      this._d.notes = { text, base };
      this._noteConflict = c;
      rec.notes = c.rev && c.rev !== FW_PDB_ZERO ? { text: c.text, rev: c.rev, by: c.by, at: c.at } : null;
      this._renderRecord();
      this._say("notes", "");
      this._open(rec.pid, false);
    }
  }

  // ---- the dated log
  _logNode(rec, msg) {
    const d = this._d.entry || (this._d.entry = { text: "", only: false, rid: fwPdbRid() });
    const n = fwPdbLen(d.text);
    const cnt = h("span", { class: `cnt${n > FW_PDB_ENTRY_MAX ? " over" : ""}` }, `${n} / ${FW_PDB_ENTRY_MAX}`);
    const ta = h("textarea", { rows: 3, "data-k": "entry", value: d.text, dir: "auto", placeholder: "Add a dated note", "aria-label": "Add a dated note",
      oninput: (ev) => { d.text = ev.target.value; const k = fwPdbLen(d.text); cnt.textContent = `${k} / ${FW_PDB_ENTRY_MAX}`; cnt.className = `cnt${k > FW_PDB_ENTRY_MAX ? " over" : ""}`; } });
    const only = h("input", { type: "checkbox", checked: d.only, "data-k": "only", onchange: (ev) => { d.only = ev.target.checked; } });
    const ents = (rec.entries || []).map((e) => this._entryNode(e));
    const more = rec.entries_total > (rec.entries || []).length ? h("div", { class: "u" }, `The newest ${(rec.entries || []).length} of ${rec.entries_total} are shown.`) : null;
    return h("div", { class: "sec" }, h("h3", {}, "Log"), ta,
      h("div", { class: "row" }, h("button", { type: "button", onclick: () => this._addEntry() }, "Add"), cnt,
        h("label", { class: "ck" }, only, "Only me"), h("span", { class: "u" }, "Nothing is shared with a pilot in 1.7.8; Only me stays yours when sharing comes.")),
      msg, ents.length ? h("div", {}, ents) : h("div", { class: "u" }, "No entries yet."), more);
  }
  _entryNode(e) {
    const rec = this._rec, gone = e.gone || "";
    const meta = [h("span", { class: "who" }, e.by), fwPdbHst(e.at), e.shared === false ? h("span", { class: "tag" }, "only me") : null,
      gone === "hidden" ? h("span", { class: "tag w" }, `hidden by ${e.gone_by || "ryan"}`) : null];
    const acts = [];
    if (!gone && e.by === "ryan") acts.push(h("button", { class: "g s", type: "button", onclick: () => { if (confirm("Take this entry back? Its text is removed now; a line says it was taken back.")) this._post({ op: "retract", eid: e.eid }, "log", "Taken back."); } }, "Take back"));
    if (!gone) acts.push(h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "hide", eid: e.eid }, "log", "Hidden. Restore brings it back.") }, "Hide"));
    if (gone === "hidden") {
      acts.push(h("button", { class: "g s", type: "button", onclick: () => this._post({ op: "restore", eid: e.eid }, "log", "Restored.") }, "Restore"));
      acts.push(h("button", { class: "g s", type: "button", onclick: () => { if (confirm("Purge this entry's text for good? It also leaves the daily copies.")) this._post({ op: "purge", eid: e.eid }, "log", "Purged."); } }, "Purge"));
    }
    const body = gone === "retracted" ? h("div", { class: "tx" }, `taken back by ${e.gone_by || e.by}`)
      : gone === "purged" ? h("div", { class: "tx" }, "purged") : h("div", { class: "tx", dir: "auto" }, e.text);
    return h("div", { class: `ent${gone ? " gone" : ""}`, "data-eid": e.eid }, h("div", { class: "meta" }, meta), body, acts.length && rec ? h("div", { class: "row" }, acts) : null);
  }
  async _addEntry() {
    const rec = this._rec, d = this._d.entry;
    if (!rec || !d) return;
    if (!d.text.trim()) { this._say("log", "Type the note first.", "err"); return; }
    if (fwPdbLen(d.text) > FW_PDB_ENTRY_MAX) { this._say("log", `A note is at most ${FW_PDB_ENTRY_MAX} characters.`, "err"); return; }
    const r = await this._post({ op: "add", pid: rec.pid, text: d.text, shared: !d.only, rid: d.rid }, "log", "Added.", true);
    if (r && r.ok) { this._d.entry = { text: "", only: false, rid: fwPdbRid() }; this._renderRecord(); this._say("log", "Added.", "ok"); }
  }

  // ---- the picker's pickup history (counts per layover station)
  _pickupsNode(p) {
    const s = (p && p.summary) || { n: 0 }, rows = (p && p.rows) || [];
    if (!s.n) return h("div", { class: "sec" }, h("h3", {}, "Pickups"), h("div", { class: "u" }, "No pickup by this pilot on file."));
    const line = [`${s.n} pickup${s.n === 1 ? "" : "s"}`, `${s.layovers} with a layover, ${s.turns} turn${s.turns === 1 ? "" : "s"}`];
    if (s.credit_avg) line.push(`average credit ${s.credit_avg}`);
    if (s.report && s.report.first) line.push(s.report.first === s.report.last ? `reports at ${s.report.first}` : `reports ${s.report.first} to ${s.report.last}`);
    if (s.speed && s.speed.avg_s != null) line.push(`picked up in ${fwPdbSecs(s.speed.avg_s)} on average (fastest ${fwPdbSecs(s.speed.min_s)})`);
    if (s.inflt) line.push(`${s.inflt} while in flight`);
    const days = Object.entries(s.days || {}).map(([k, v]) => `${k}-day ${v}`).join(" · ");
    const pdow = FW_PDB_DOW.filter((d) => (s.pick_dow || {})[d]).map((d) => `${d} ${s.pick_dow[d]}`).join(" · ");
    const table = h("div", { class: "wrap" }, h("table", { class: "pk" },
      h("thead", {}, h("tr", {}, ["#", "Picked up (HST)", "Pairing", "Start", "Days", "Layover", "Credit", "Report", "Speed", "In flight"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, String(r.n)), h("td", {}, `${fwPdbHst(r.at).replace(" HST", "")}${r.pick_dow ? ` ${r.pick_dow}` : ""}`), h("td", {}, r.pairing || ""),
        h("td", {}, `${r.start || ""}${r.dow ? ` ${r.dow}` : ""}`), h("td", {}, r.days != null ? String(r.days) : ""),
        h("td", {}, r.turn ? "turn" : r.lay ? `${r.lay} (${r.n_lay})` : ""), h("td", {}, r.credit || ""), h("td", {}, r.report || ""),
        h("td", {}, `${r.approx ? "~" : ""}${fwPdbSecs(r.secs)}`), h("td", {}, r.inflt === true ? "yes" : r.inflt === false ? "no" : ""))))));
    return h("div", { class: "sec" }, h("h3", {}, "Pickups"), h("div", { class: "u" }, line.join(" · ")),
      (s.lays || []).length ? h("div", { class: "stn", "aria-label": "Pickups per layover station" }, s.lays.map(([st, c]) => h("span", {}, `${st} ${c}`))) : null,
      days ? h("div", { class: "u" }, `Trip length: ${days}`) : null, pdow ? h("div", { class: "u" }, `Picked up on: ${pdow} (HST)`) : null,
      this._c.follow ? this._det("picks", null, "Every pickup", table) : table);
  }
  _aiNode(ai) {
    return h("div", { class: "sec" }, h("h3", {}, "AI note ", h("span", { class: "tag ai" }, "AI")),
      h("div", { class: "u" }, `Written by ${ai.model || "a model"}${ai.at ? ` ${fwPdbHst(ai.at)}` : ""} from anonymous pickup stats. Read only; not a human note.`),
      h("div", { class: "tx", dir: "auto" }, ai.text));
  }
  _historyNode(rec) {
    const log = rec.field_log || [];
    const lab = (f) => FW_PDB_LABEL[f] || { _record: "Record", _emp: "Employee #", _gone: "On the list", _conflict: "Held row" }[f] || f;
    const cut = (v) => { const s = String(v == null ? "" : v); return s.length > 120 ? `${s.slice(0, 117)}...` : s; };
    return this._det("log", "sec", `History (${log.length}${log.length >= 100 ? ", the newest 100" : ""})`,
      log.length ? h("div", { class: "wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["When", "Field", "What", "Old", "New", "From"].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", {}, log.map((x) => h("tr", {}, h("td", { class: "n" }, fwPdbHst(x.at)), h("td", {}, lab(x.field)), h("td", {}, FW_PDB_HOW[x.how] || x.how),
          h("td", { dir: "auto" }, cut(x.old)), h("td", { dir: "auto" }, cut(x.new)), h("td", {}, x.ref || x.by)))))) : h("div", { class: "u" }, "Nothing logged."));
  }
  _picker(onPick, exclude) {  // a small search for another record (merge, attach)
    const out = h("div", {});
    const res = h("div", {});
    const inp = h("input", { type: "search", placeholder: "Name or employee #", autocomplete: "off", spellcheck: false, "aria-label": "Find the other record",
      oninput: (ev) => { clearTimeout(out._t); const q = ev.target.value.trim(); out._t = setTimeout(async () => {
        if (!q) { res.replaceChildren(); return; }
        try {
          const r = await this._get(new URLSearchParams({ q }).toString());
          const rows = ((r && r.rows) || []).filter((x) => x.pid !== exclude).slice(0, 5);
          res.replaceChildren(...(rows.length ? rows.map((x) => h("div", { class: "row" }, h("button", { class: "g s", type: "button", onclick: () => onPick(x) }, "Pick"),
            h("span", { dir: "auto" }, `${x.name}`), h("span", { class: "u" }, `Emp ${x.emp}${x.sen ? ` · Sen ${x.sen}` : ""}${x.doh ? ` · DOH ${x.doh}` : ""}`))) : [h("div", { class: "u" }, "No match.")]));
        } catch (e) { res.replaceChildren(h("div", { class: "u err" }, this._err(e))); }
      }, 300); } });
    out.append(inp, res);
    return out;
  }
  _dangerNode(rec, msg) {
    const d = this._d;
    const typed = h("input", { type: "text", "data-k": "del", value: d.del || "", placeholder: "Type DELETE", "aria-label": "Type DELETE to delete the record", autocomplete: "off",
      oninput: (ev) => { d.del = ev.target.value; del.disabled = d.del !== "DELETE"; } });
    const del = h("button", { type: "button", disabled: d.del !== "DELETE", onclick: async () => {
      const r = await this._post({ op: "forget", pid: rec.pid, confirm: "DELETE" }, "danger", "Record deleted.", true);
      if (r && r.ok) { this._rec = null; this._d = {}; this._renderRecord(); this._search(false); this._say("main", "Record deleted, and its text scrubbed from the file and the copies.", "ok"); }
    } }, "Delete record");
    const emp = h("input", { type: "text", "data-k": "move", inputMode: "numeric", value: d.move || "", placeholder: "New employee #", "aria-label": "New employee number", autocomplete: "off", oninput: (ev) => { d.move = ev.target.value; } });
    return this._det("danger", "sec", "Merge, renumber or delete", msg,
      h("div", { class: "u" }, "Merge this record into another (a duplicate): its log, notes, versions, values and pickups move there and this one is hidden."),
      this._picker((x) => { if (confirm(`Merge this record into ${x.name} (Emp ${x.emp})?`)) this._post({ op: "merge", pid: rec.pid, into: x.pid }, "danger", "Merged.").then((r) => { if (r && r.ok) this._search(false); }); }, rec.pid),
      h("div", { class: "u" }, "A new employee number for the same pilot (renumbered): his notes stay on this record."),
      h("div", { class: "row" }, emp, h("button", { class: "g", type: "button", onclick: () => { if (/^\d{1,7}$/.test(String(d.move || "").trim()) && confirm("Give this record the new employee number?")) this._post({ op: "move", pid: rec.pid, emp: String(d.move).trim() }, "danger", "Employee number changed."); else if (!/^\d{1,7}$/.test(String(d.move || "").trim())) this._say("danger", "The employee # is 1 to 7 digits.", "err"); } }, "Change")),
      h("div", { class: "u" }, "Delete the whole record: its values, log, notes, versions and entries. Its text is scrubbed from the file and the daily copies."),
      h("div", { class: "row" }, typed, del));
  }

  // ---- browse: the held rows, a new record, the copies
  async _loadConflicts() {
    try {
      const r = await this._get("view=conflicts");
      if (r.ok) { this._conf = r.conflicts; this._renderConflicts(); }
    } catch (e) { /* the status line says the rest */ }
  }
  _renderConflicts() {
    const E = this._els, list = this._conf || [];
    if (!E.conf) return;
    if (!list.length) { E.conf.replaceChildren(); return; }
    const msg = (this._msgEl.conf = h("div", { class: "msg", role: "status", "aria-live": "polite" }));
    E.conf.replaceChildren(h("div", { class: "sec" }, h("h3", {}, `Held for you (${list.length})`),
      h("div", { class: "u" }, "Upload rows the database would not apply on its own: nothing is ever moved or merged without you."), msg,
      list.map((c) => {
        const v = c.values || {};
        const what = c.kind === "list_partial"
          ? `${c.ref}: ${c.rows} rows where the last one had ${c.prev}; ${c.missing_n} records would be marked gone${(c.missing || []).length ? ` (${c.missing.map((x) => x.name).join(", ")}${c.missing_n > c.missing.length ? ", ..." : ""})` : ""}.`
          : `${c.ref}: ${[v.name, c.emp ? `Emp ${c.emp}` : "", v.sen ? `Sen ${v.sen}` : "", v.doh ? `DOH ${v.doh}` : ""].filter(Boolean).join(" · ")}`;
        const cand = c.cand ? h("div", { class: "u" }, "The record it names: ", h("span", { dir: "auto" }, `${c.cand.name} (Emp ${c.cand.emp}${c.cand.sen ? `, Sen ${c.cand.sen}` : ""}${c.cand.doh ? `, DOH ${c.cand.doh}` : ""})`)) : null;
        const slot = h("div", {});
        const acts = (c.answers || []).map((a) => h("button", { class: a === "ignore" ? "g s" : "s", type: "button", onclick: () => {
          if (a === "attach") { slot.replaceChildren(this._picker((x) => this._resolve(c, a, x.pid))); return; }
          this._resolve(c, a);
        } }, FW_PDB_ANSWER[a] || a));
        return h("div", { class: "ent" }, h("div", { class: "meta" }, h("span", { class: "who" }, FW_PDB_KIND[c.kind] || c.kind), fwPdbHst(c.at)),
          h("div", { dir: "auto" }, what), cand, h("div", { class: "row" }, acts), slot);
      })));
  }
  async _resolve(c, how, pid) {
    const body = { op: "resolve", conflict_id: c.id, how };
    if (pid) body.pid = pid;
    const r = await this._post(body, "conf", "Done.", true);
    if (r && r.ok) { await this._loadConflicts(); this._search(false); if (r.record) this._setRec(r.record, r.rev); }
  }
  _renderMore() {
    const E = this._els;
    if (!E.more) return;
    const msgN = (this._msgEl.new = h("div", { class: "msg", role: "status", "aria-live": "polite" }));
    const n = this._newRec || (this._newRec = { emp: "", name: "", doh: "" });
    const inp = (k, ph, mode) => h("input", { type: "text", value: n[k], placeholder: ph, "aria-label": ph, inputMode: mode || null, autocomplete: "off", spellcheck: false, oninput: (ev) => { n[k] = ev.target.value; } });
    const copies = this._view ? this._copiesNodes() : [h("button", { class: "g s", type: "button", onclick: () => this._loadStatus() }, "Show the copies")];
    E.more.replaceChildren(
      h("details", { class: "sec" }, h("summary", {}, "Add a record"), h("div", { class: "u" }, "A pilot the uploads do not have yet. Its values are your edits."),
        h("div", { class: "row" }, inp("emp", "Employee #", "numeric"), inp("name", "Last, First"), inp("doh", "DOH YYYY-MM-DD (optional)")),
        h("div", { class: "row" }, h("button", { type: "button", onclick: async () => {
          const body = { op: "new", emp: n.emp.trim(), name: n.name.trim() };
          if (n.doh.trim()) body.doh = n.doh.trim();
          const r = await this._post(body, "new", "Record added.", true);
          if (r && r.ok) { this._newRec = null; this._renderMore(); this._search(false); this._say("new", "Record added.", "ok"); }
        } }, "Add the record")), msgN),
      h("details", { class: "sec", open: !!this._view }, h("summary", {}, "Daily copies"), copies));
  }
  async _loadStatus() {
    try {
      const r = await this._get("view=status");
      if (r.ok) { this._view = r; this._renderStatus(); if (!this._c.follow) this._renderMore(); }
    } catch (e) { this._say("main", this._err(e), "err"); }
  }
  _restoreBox(b, label) {
    const st = { typed: "" };
    const go = h("button", { type: "button", disabled: true, onclick: async () => {
      const r = await this._post({ op: "restore_db", file: b.file, confirm: "RESTORE" }, "main", "The copy is back. The file before it is kept aside.", true);
      if (r && r.ok) { this._view = null; this._rec = null; this._renderRecord(); this._loadStatus(); this._search(false); }
    } }, label);
    const typed = h("input", { type: "text", placeholder: "Type RESTORE", "aria-label": "Type RESTORE to put the copy back", autocomplete: "off", oninput: (ev) => { st.typed = ev.target.value; go.disabled = st.typed !== "RESTORE"; } });
    return h("div", { class: "row" }, typed, go);
  }
  _copiesNodes() {
    const v = this._view, bk = (v && v.backups) || [];
    const msg = (this._msgEl.copies = h("div", { class: "msg", role: "status", "aria-live": "polite" }));
    const where = (f) => (String(f).startsWith("1/") ? "share" : "/data");
    return [h("div", { class: "u" }, "Nightly at 02:47 HST, 7 kept in /data and on the share (it survives a /data restore). Taken-back text stays up to 7 days in them and in Home Assistant's backups; a purge replaces them."),
      bk.length ? h("div", { class: "wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Day", "Where", "Revision", "Size", ""].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", {}, bk.map((b) => { const slot = h("td", {}); slot.append(h("button", { class: "g s", type: "button", onclick: () => slot.replaceChildren(this._restoreBox(b, "Put it back")) }, "Put back..."));
          return h("tr", {}, h("td", {}, b.day), h("td", {}, where(b.file)), h("td", {}, b.rev == null ? "?" : String(b.rev)), h("td", {}, `${Math.round((+b.size || 0) / 1024)} KB`), slot); })))) : h("div", { class: "u" }, "No copy yet."),
      h("div", { class: "row" }, h("button", { class: "g s", type: "button", onclick: () => { if (confirm("Replace every daily copy with a fresh one now? Text taken back or purged leaves the copies.")) this._post({ op: "purge", backups: true }, "copies", "The copies were replaced.").then(() => this._loadStatus()); } }, "Purge old copies")), msg];
  }

  // ---- follow mode: the pilot the pilot lookup card shows
  _fromPilot() {
    const st = this._state(FW_PDB_PILOT), a = (st && st.attributes) || {};
    const emp = String(a.emp || "").replace(/\D/g, "").slice(0, 7), name = String(a.name || "").slice(0, 80);
    const sig = `${emp}|${name}`;
    if (sig === this._follow.sig) return;
    this._follow.sig = sig;
    clearTimeout(this._fT);
    this._fT = setTimeout(() => this._loadFollow(emp, name), 1000);
  }
  async _loadFollow(emp, name) {
    this._follow.emp = emp; this._follow.name = name;
    this._recWhy = "";
    if (!emp && !name) { this._rec = null; this._renderRecord(); return; }
    if (!this._rec || (this._rec.emp !== emp)) { this._rec = null; this._renderRecord(); }
    const p = new URLSearchParams();
    if (emp) p.set("emp", emp);
    if (name) p.set("name", name.replace(/[\r\n\t]+/g, " "));
    const seq = (this._fseq = (this._fseq || 0) + 1);
    try {
      let r = await this._get(p.toString());
      if (!r.ok && r.field === "name" && emp) r = await this._get(new URLSearchParams({ emp }).toString());  // a name it refuses: by number only
      if (seq !== this._fseq) return;
      if (!r.ok) { this._say("main", this._why(r, "The pilot database"), "err"); return; }
      if (!r.record) { this._recWhy = r.why || "Not in the pilot database"; this._rec = null; this._rev = r.rev; this._renderRecord(); return; }
      this._say("main", "");
      this._setRec(r.record, r.rev);
    } catch (e) {
      if (seq === this._fseq) this._say("main", this._err(e), "err");
    }
  }

  // ---- writes: one op, JSON, the card's header; the answer redraws the record
  async _post(body, where, okText, raw) {
    // raw: the caller handles a 409 itself (a field edit keeps its draft, the notes show both texts)
    if (this._busy) { this._say(where, "Wait for the last change to finish.", "err"); return null; }
    this._busy = true;
    this._say(where, "Saving...", "");
    let r = null;
    try {
      r = await this._send(body);
      if (r.ok) {
        if (r.rev != null) this._rev = r.rev;
        if (r.record) this._setRec(r.record, r.rev);
        this._say(where, okText, "ok");
        if (!this._c.follow && ["new", "merge", "move", "forget", "set", "unset", "resolve"].includes(body.op)) this._search(false);
      } else if (r._status === 409) {
        if (r.record) this._setRec(r.record, r.rev);
        if (!raw) {
          const c = r.conflict;
          this._say(where, c ? `Not saved: the notes changed (by ${c.by || "someone"}${c.at ? ` at ${fwPdbHst(c.at)}` : ""}).`
            : "Not saved: the record changed meanwhile. It is shown as it is now; check it and try again.", "err");
          if (c && this._rec) this._open(this._rec.pid, false);
        }
      } else {
        this._say(where, this._why(r, "Not saved"), "err");
      }
    } catch (e) {
      this._say(where, this._err(e), "err");
    } finally {
      this._busy = false;
    }
    return r;
  }

  // ---- ingress: the app's address and a session cookie, as the uploads card and Home Assistant's app panels do
  async _ingress() {
    if (!this._admin()) throw new Error("The pilot database is for the Home Assistant admin.");
    if (!this._base) {
      const info = await this._h.callWS({ type: "supervisor/api", endpoint: `/addons/${this._c.slug}/info`, method: "get" });
      const u = String((info && (info.ingress_url || info.ingress_entry)) || "");
      if (!FW_PDB_URL_RE.test(u)) throw new Error("The app's Web UI address was not found.");
      if (info.state && info.state !== "started") throw new Error(`The Flight Watcher app is not running (${info.state}).`);
      this._base = u.endsWith("/") ? u : `${u}/`;
    }
    await this._session(false);
    return this._base;
  }
  async _session(force) {
    const now = Date.now();
    if (this._sess && !force && now - this._sessAt < FW_PDB_REFRESH_MS) return;
    if (this._sess) {
      try {
        await this._h.callWS({ type: "supervisor/api", endpoint: "/ingress/validate_session", method: "post", data: { session: this._sess } });
        this._sessAt = now;
        this._cookie();
        return;
      } catch (err) { this._sess = null; }  // lapsed: a new one below
    }
    const r = await this._h.callWS({ type: "supervisor/api", endpoint: "/ingress/session", method: "post" });
    const s = String((r && r.session) || "");
    if (!/^[A-Za-z0-9]{16,256}$/.test(s)) throw new Error("Home Assistant gave no app session.");
    this._sess = s;
    this._sessAt = now;
    this._cookie();
    this._keepAlive();
  }
  _cookie() {
    const secure = typeof location !== "undefined" && location.protocol === "https:" ? ";Secure" : "";
    document.cookie = `ingress_session=${this._sess};path=/api/hassio_ingress/;SameSite=Strict${secure}`;
  }
  _keepAlive() {  // while the card is on screen, re-validate before the Supervisor's 15 min lapse
    if (this._timer || !this.isConnected) return;
    this._timer = setInterval(() => {
      if (!this.isConnected || !this._sess || (typeof document !== "undefined" && document.visibilityState === "hidden")) return;
      this._session(true).catch(() => {});
    }, FW_PDB_REFRESH_MS);
  }
  async _call(fn) {  // one retry with a new session when the proxy says the cookie lapsed
    const base = await this._ingress();
    try {
      return await fn(base);
    } catch (err) {
      if (!err || err.status !== 401) throw err;
      this._sess = null;
      await this._session(true);
      return fn(base);
    }
  }
  async _answer(r) {
    if (r.status === 401) throw fwPdbHttpErr(401);
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    if (!j || typeof j !== "object") throw fwPdbHttpErr(r.status);
    j._status = r.status;
    return j;
  }
  _get(query) {
    return this._call(async (base) => this._answer(await fetch(`${base}api/pilotdb${query ? `?${query}` : ""}`,
      { credentials: "same-origin", cache: "no-store", headers: { "X-FW-Card": "pilotdb" } })));
  }
  _send(body) {
    return this._call(async (base) => this._answer(await fetch(`${base}api/pilotdb`, { method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-FW-Card": "pilotdb" }, body: JSON.stringify(body) })));
  }
}
customElements.define("flight-watcher-pilotdb-card", FlightWatcherPilotdbCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilotdb-card", name: "Flight Watcher pilots", description: "The pilot database: search, records, notes and log, pickups (Ryan's dashboard, admin only)" });

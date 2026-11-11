// Flight Watcher layover card (1.7.1, FW-0072, Ryan: "Make this page more intuitive and easy to use at a glance").
// It replaces the Working Flight view's markdown card and its big "Ready to update?" tile on the admin's dashboard:
// - the leg: flight, route and leg on the left; the van time at the top right in headline size, with the station's
//   time zone abbreviation, the HST time and a countdown ("in 2 h 10 min"), so it reads at a glance on a phone; with
//   no van, the report time takes that place. Report and departure below.
// - a small "Update with Hark" chip (card option update_url, Hark's project page) instead of the big tile.
// - on a layover: the hotel (address to its map, phone as a tel: link), weather, open now, eat, things to do with
//   Hark's photos as small lazy thumbnails, transport.
// - Release, MEL and NOTAM folded away under a one-line status.
// - "My notes for <CITY>": Ryan's layover notes (sensor.<prefix>_layover_notes), an add box that sends
//   <prefix>/layover/note {city, text, rid} (plain text, at most 1000 characters; the Watcher stores it), and "Tidy
//   with AI", which files a feature ticket "Tidy the <CITY> layover notes" (reporter ryan, the existing ticket path);
//   Claude writes <CITY>.guide.md in the ticket flow, shown above the notes (its markdown escaped, then a few
//   formats: headings, lists, bold, italics, https links). Notes for other cities fold away below.
// Data: sensor.hark_working_flight (Hark's) when it covers the same pairing as sensor.<prefix>_working_flight, else
// the Watcher's (the markdown card's rule); sensor.<prefix>_layover_van (the Watcher's reading of Hark's van on the
// station's clock: abbreviation, HST, the instant for the countdown, the alerts' status). Hark's data shows only
// while sensor.<prefix>_state says role admin (not while that sensor is missing or has no role), so a pilot's copy
// never shows another pilot's trip. Admin only in this release: not in the pilot portal's layout (and not bundled
// for it). Colors: text on the card's own background is the theme's primary text color; the countdown's urgent states
// and the armed delete are white on a fixed dark orange or red, so they read in any theme (Home Assistant's
// default warning and error colors are under 4.5:1 on white). Taps are 44 px at least.
// Usage: type: custom:flight-watcher-layover-card, update_url: https://... (optional)
const FW_LAYOVER_NOTE_MAX = 1000;  // layover.NOTE_MAX
class FlightWatcherLayoverCard extends HTMLElement {
  setConfig(c) {
    this._c = { prefix: "flight_watcher", ...(c || {}) };
    this._draft = this._draft || ""; this._open = this._open || {}; this._sent = this._sent || null; this._arm = "";
    this._tidied = this._tidied || {};
  }
  getCardSize() { return 8; }
  connectedCallback() {
    if (!this._tick) this._tick = setInterval(() => this._countdown(), 30000);
  }
  disconnectedCallback() { if (this._tick) { clearInterval(this._tick); this._tick = null; } }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  _https(u) { return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(\/[^\s"<>]*)?$/.test(String(u || "")) ? String(u) : ""; }
  _link(u, t, cls) { const h = this._https(u); return h ? `<a${cls ? ` class="${cls}"` : ""} href="${this._e(h)}" target="_blank" rel="noopener noreferrer">${t}</a>` : ""; }
  _st(id) { return this._h && this._h.states[id]; }
  set hass(h) {
    this._h = h;
    const p = this._c.prefix, ids = ["sensor.hark_working_flight", `sensor.${p}_working_flight`, `sensor.${p}_layover_van`,
      `sensor.${p}_layover_notes`, `sensor.${p}_state`];
    const sig = ids.map((i) => { const s = h.states[i]; return s ? `${s.last_updated}/${s.state}` : "-"; }).join("|");
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  // the markdown card's rule: Hark's sensor when it covers the Watcher's pairing (or the Watcher has none), else the
  // Watcher's; Hark's only while the state sensor says admin (a pilot's copy keeps sensor.hark_working_flight's id, so
  // a missing or restarting state sensor must not show it)
  _pick() {
    const p = this._c.prefix, w = this._st(`sensor.${p}_working_flight`), st = this._st(`sensor.${p}_state`);
    const role = st && st.attributes ? st.attributes.role : "";
    let h = role === "admin" ? this._st("sensor.hark_working_flight") : null;
    if (h && ["unknown", "unavailable"].includes(h.state)) h = null;
    const wa = (w && w.attributes) || {};
    const use = h && (!wa.pairing || (h.attributes || {}).pairing === wa.pairing) ? h : w;
    return { s: use, a: (use && use.attributes) || {}, hark: !!(use && h && use === h), w };
  }
  // the weekday names in s ("Thu", "Thurs", "Thursday") as "Thu": layover.weekdays
  _wds(s) {
    const full = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"], out = new Set();
    for (const w of String(s || "").match(/[A-Za-z]+/g) || []) {
      const lw = w.toLowerCase();
      if (lw.length >= 3 && lw.length <= 9) full.forEach((f) => { if (f.startsWith(lw)) out.add(f[0].toUpperCase() + f.slice(1, 3)); });
    }
    return out;
  }
  // layover.parse_van, the same three patterns: the 24 h time in parentheses, then "YYYY-MM-DD HH:MM" (none with AM,
  // PM, seconds or a zone after it), then a 12 h time before the date; null when none, or a weekday in it is not the
  // date's. {local, date, wd (the date's weekday), place (after a comma)}
  _parseVan(src) {
    const s = String(src || ""), wdn = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const rx = [
      [/\((\d{1,2}):(\d{2})\)\s*(?:([A-Za-z]{3,9})\.?,?\s+)?(\d{4}-\d{2}-\d{2})/, (m) => [+m[1], +m[2], m[3], m[4]]],
      [/(?:\b([A-Za-z]{3,9})\.?,?\s+)?(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?![\d:]|\s*[AaPp]\.?\s*[Mm](?![A-Za-z])|\s*(?:Z\b|[+-]\d|UTC|GMT))/,
        (m) => [+m[3], +m[4], m[1], m[2]]],
      [/\b(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?(?![A-Za-z])(.*?)(\d{4}-\d{2}-\d{2})/,
        (m) => (+m[1] >= 1 && +m[1] <= 12 ? [(+m[1] % 12) + (/p/i.test(m[3]) ? 12 : 0), +m[2], m[4], m[5]] : null)],
    ];
    for (const [re, get] of rx) {
      const m = re.exec(s), g = m && get(m);
      if (!g) continue;
      const [h, mi, said, d] = g, day = new Date(`${d}T00:00:00Z`);
      if (h > 23 || mi > 59 || !isFinite(day) || day.toISOString().slice(0, 10) !== d) continue;
      const wd = wdn[day.getUTCDay()], named = this._wds(said);
      if (named.size && (named.size > 1 || !named.has(wd))) return null;
      const rest = s.slice(m.index + m[0].length), place = /^\s*,/.test(rest) ? rest.replace(/^\s*,\s*/, "").trim() : "";
      return { local: `${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}`, date: d, wd, place };
    }
    return null;
  }
  // Hark's van text: "7:40 PM (19:40) Thu 2026-11-12, Example Hotel lobby", else, when that has no date at all, its
  // state's "van 2026-11-12 19:40" (layover.van_info's order); else the Watcher's own reading when it is for this pairing
  _vanText(a, state) {
    const got = this._parseVan(a.van), dated = /\d{4}-\d{2}-\d{2}/.test(String(a.van || ""));
    const m = got || dated ? null : /\bvan\b(.*)$/i.exec(String(state || ""));
    const vt = got || (m ? this._parseVan(m[1]) : null);
    if (vt) return vt;
    const v = this._st(`sensor.${this._c.prefix}_layover_van`), va = (v && v.attributes) || {};
    return va.at && va.pairing === a.pairing && va.local && va.date
      ? { local: String(va.local), date: String(va.date), wd: String(va.weekday || ""), place: String(va.place || "") } : null;
  }
  // the Watcher's reading of the same van (its zone abbreviation, HST and instant), or null while it has not read it
  _vanSensor(a, vt) {
    const v = this._st(`sensor.${this._c.prefix}_layover_van`), va = (v && v.attributes) || {};
    return vt && va.at && va.pairing === a.pairing && va.date === vt.date && va.local === vt.local ? va : null;
  }
  // a note's date, in HST (its "at" is UTC: an evening note in Hawaii is already the next day there)
  _hstDate(at) {
    const t = Date.parse(at);
    return isFinite(t) ? new Date(t - 10 * 3600000).toISOString().slice(0, 10) : String(at || "").slice(0, 10);
  }
  _left(at) {
    const ms = Date.parse(at) - Date.now();
    if (!isFinite(ms)) return { t: "", c: "" };
    if (ms <= 0) { const m = Math.round(-ms / 60000); return { t: m < 1 ? "now" : `${this._dur(m)} ago`, c: "past" }; }
    const m = Math.ceil(ms / 60000);
    return { t: `in ${this._dur(m)}`, c: m <= 10 ? "now" : m <= 30 ? "soon" : "" };
  }
  _dur(m) { const h = Math.floor(m / 60), r = m % 60; return h ? `${h} h${r ? ` ${r} min` : ""}` : `${r} min`; }
  _countdown() {
    const el = this.shadowRoot && this.shadowRoot.querySelector("[data-cd]");
    if (!el || !el.dataset.at) return;
    const l = this._left(el.dataset.at);
    el.textContent = l.t; el.className = `cd ${l.c}`;
  }
  // "20:25 AEDT (8:25 PM) Thu 2026-11-12" or "20:25 local, 23:25 HST": the first HH:MM and what follows it, short
  _timeParts(s) {
    const t = String(s || ""), m = /(\d{1,2}):(\d{2})/.exec(t);
    if (!m) return null;
    const rest = t.slice(m.index + m[0].length).replace(/\(\d{1,2}:\d{2}\s*[AP]M\)\s*/i, "").replace(/^[\s,]+/, "").trim();
    return { hm: `${m[1].padStart(2, "0")}:${m[2]}`, rest };
  }
  // the guide: escaped first, then headings, lists, bold, italics, code and https links (nothing else becomes markup)
  _md(src) {
    const out = [], lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
    let list = "", para = [];
    const inline = (t) => this._e(t)
      .replace(/\[([^\]\n]{1,200})\]\((https:\/\/[^\s)"<>]{1,500})\)/g, (m0, a, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${a}</a>`)
      .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])[*_]([^*_\n]+)[*_](?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>");
    const flush = () => {
      if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; }
      if (list) { out.push(`</${list}>`); list = ""; }
    };
    for (const ln of lines) {
      let m;
      if (!ln.trim()) { flush(); continue; }
      if ((m = /^(#{1,4})\s+(.*)$/.exec(ln))) { flush(); out.push(`<h${m[1].length < 3 ? 4 : 5}>${inline(m[2])}</h${m[1].length < 3 ? 4 : 5}>`); continue; }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { flush(); out.push("<hr>"); continue; }
      const ul = /^\s*[-*•]\s+(.*)$/.exec(ln), ol = /^\s*\d{1,3}[.)]\s+(.*)$/.exec(ln);
      if (ul || ol) {
        const k = ul ? "ul" : "ol";
        if (para.length) { const l0 = list; list = ""; flush(); list = l0; }
        if (list !== k) { if (list) out.push(`</${list}>`); out.push(`<${k}>`); list = k; }
        out.push(`<li>${inline((ul || ol)[1])}</li>`);
        continue;
      }
      if (list) { out.push(`</${list}>`); list = ""; }
      para.push(ln.trim());
    }
    flush();
    return out.join("");
  }
  _list(title, items, icon) {
    const a = (Array.isArray(items) ? items : items ? [items] : []).filter((x) => x != null && String(x).trim());
    return a.length ? `<div class="blk"><div class="bh">${icon} ${title}</div><ul>${a.map((x) => `<li>${this._e(x)}</li>`).join("")}</ul></div>` : "";
  }
  _rid() {
    const b = new Uint8Array(8);
    try { crypto.getRandomValues(b); } catch (e) { b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); }); }
    return "r" + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  _pub(sub, obj) { return this._h.callService("mqtt", "publish", { topic: `${this._c.prefix}/${sub}`, payload: JSON.stringify(obj) }); }
  _cityNow(a, hark) {
    const o = String(a.origin || "").toUpperCase(), d = String(a.dest || "").toUpperCase();
    if (hark && a.mode === "layover" && /^[A-Z]{3}$/.test(o)) return o;
    return /^[A-Z]{3}$/.test(d) && d !== "HNL" ? d : /^[A-Z]{3}$/.test(o) && o !== "HNL" ? o : "";
  }
  _notesHtml(n, city) {
    const na = (n && n.attributes) || {}, cities = na.cities || {}, cur = cities[city] || null;
    const last = na.last || {}, sent = this._sent, ans = sent && last.rid === sent.rid ? last : null;
    const note = (x, c) => `<li><div class="nt">${this._e(x.text)}</div><div class="nm"><span class="u">${this._e(this._hstDate(x.at))}</span>
      <button class="x${this._arm === x.id ? " arm" : ""}" data-del="${this._e(x.id)}" data-c="${this._e(c)}" aria-label="Delete this note">${this._arm === x.id ? "Delete?" : "&times;"}</button></div></li>`;
    const body = (c, d) => `${d.guide ? `<div class="guide"><div class="u">Guide${d.guide_at ? `, tidied ${this._e(d.guide_at.replace("T", " "))} HST` : ""}</div>${this._md(d.guide)}</div>` : ""}
      ${(d.notes || []).length ? `<ul class="nl">${d.notes.map((x) => note(x, c)).join("")}</ul>` : ""}
      ${d.left_out ? `<div class="u">${d.left_out} older note${d.left_out === 1 ? "" : "s"} not shown here.</div>` : ""}`;
    const others = (na.order || Object.keys(cities)).filter((c) => c !== city && cities[c]);
    const msg = !sent ? "" : !ans ? "Saving..." : ans.ok ? (sent.action === "delete" ? "Deleted." : "Saved.") : `Not saved: ${ans.error || "refused"}.`;
    const tidied = this._tidied[city];
    const unread = Array.isArray(na.unreadable) ? na.unreadable : [];
    return `<div class="sec notes"><h3>&#128221; My notes for ${this._e(city || "a city")}</h3>
      ${unread.length ? `<div class="warn" data-unread>The notes file for ${this._e(unread.join(", "))} could not be read (a damaged file), so ${unread.length === 1 ? "it is" : "they are"} not shown and nothing in ${unread.length === 1 ? "it" : "them"} was changed.</div>` : ""}
      ${cur ? body(city, cur) : unread.includes(city) ? "" : `<div class="u">No notes for ${this._e(city || "this city")} yet: places you liked, routines, routes.</div>`}
      <textarea data-draft rows="3" maxlength="${FW_LAYOVER_NOTE_MAX}" placeholder="A place you liked, a routine, a route..." aria-label="New note"></textarea>
      <div class="row"><label class="cl">City <input data-city maxlength="3" value="${this._e(city)}" autocapitalize="characters" aria-label="City (3-letter code)"></label>
        <button data-addnote>Add note</button>
        <button class="g" data-tidy${cur && (cur.total || 0) > 0 && !tidied ? "" : " disabled"} title="Files a ticket: Claude tidies these notes into a guide">&#10024; Tidy with AI</button></div>
      <div data-nmsg class="${ans && !ans.ok ? "warn" : "u"}">${this._e(tidied ? `Ticket filed: Claude tidies the ${city} notes into a guide (Settings, Tickets).` : msg)}</div>
      ${others.length ? `<details data-k="others"${this._open.others ? " open" : ""}><summary>Notes for other cities (${others.length})</summary>
        ${others.map((c) => `<details data-k="c_${this._e(c)}"${this._open[`c_${c}`] ? " open" : ""}><summary>${this._e(c)} <span class="u">${cities[c].total || 0} note${cities[c].total === 1 ? "" : "s"}${cities[c].guide ? ", guide" : ""}</span></summary>${body(c, cities[c])}</details>`).join("")}</details>` : ""}
      ${(na.left_out || []).length ? `<div class="u">Not shown here (too much for one sensor): ${this._e(na.left_out.join(", "))}.</div>` : ""}</div>`;
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const r0 = this.shadowRoot, focus = r0.activeElement && r0.activeElement.matches && r0.activeElement.matches("[data-draft]");
    const prevCity = r0.querySelector("[data-city]");
    const { s, a, hark } = this._pick();
    const p = this._c.prefix, n = this._st(`sensor.${p}_layover_notes`);
    let main;
    if (!a.pairing) {
      main = `<div class="hd"><div class="lt"><div class="fl">&#9992;&#65039; Working flight</div>
        <div class="u">${s ? "No trip on your schedule." : "Waiting for Flight Watcher."}${a.next ? ` Next: ${this._e(a.next)}` : ""}</div></div></div>`;
    } else {
      const vt = hark ? this._vanText(a, s.state) : null, vs = this._vanSensor(a, vt);
      // Hark gave a van the Watcher could not place: its text shows, and that no alert comes for it
      const unread = hark && !vt && String(a.van || "").trim() ? String(a.van).trim() : "";
      let big;
      if (vt) {
        const l = vs ? this._left(vs.at) : { t: "", c: "" };
        big = `<div class="van" data-van><div class="vl">Van</div><div class="vt">${this._e(vt.local)}</div>
          <div class="vz">${this._e(vs ? vs.abbr : "local")}${vt.wd || (vs && vs.weekday) ? ` &middot; ${this._e(vt.wd || vs.weekday)}` : ""}</div>
          ${vs ? `<div class="vh">${this._e(vs.hst)} HST ${this._e(vs.hst_weekday || "")}</div>` : ""}
          <div class="cd ${l.c}" data-cd${vs ? ` data-at="${this._e(vs.at)}"` : ""}>${this._e(l.t)}</div></div>`;
      } else {
        const rp = this._timeParts(a.report);
        big = rp ? `<div class="van rep" data-van><div class="vl">Report</div><div class="vt">${this._e(rp.hm)}</div><div class="vz">${this._e(rp.rest)}</div></div>` : "";
      }
      const dep = this._timeParts(a.dep_sched), arr = this._timeParts(a.arr_sched);
      const status = a.status ? `<div class="stt">${this._e(a.status)}${a.status_as_of ? ` <span class="u">(${this._e(a.status_as_of)})</span>` : ""}</div>` : "";
      const upd = this._link(this._c.update_url, "&#128273; Update with Hark", "chip");
      const links = [upd, this._link(a.release_url, "&#128196; Release", "chip"), this._link(a.flightaware_url, "FlightAware", "chip"), this._link(a.sigwx_url, "Sig Wx", "chip")].filter(Boolean).join("");
      const mel = Array.isArray(a.mel) ? a.mel : [], notam = Array.isArray(a.notam) ? a.notam : [];
      const relLine = !hark ? "From your FLICA schedule: release, MEL, NOTAM and GIN come from Hark."
        : a.release_updated ? `Release updated &middot; MEL ${mel.length} &middot; NOTAM ${notam.length}` : "&#9888;&#65039; Release, MEL, NOTAM and GIN not updated for this leg yet";
      const relUrl = this._https(a.release_url);
      // folded only when there is something under it (the Watcher's own sensor has no release, GIN, MEL or NOTAM)
      const rel = !(hark || relUrl || a.gin_dep || a.gin_arr) ? `<div class="u rl" data-rel>${relLine}</div>`
        : `<details class="rel" data-rel data-k="rel"${this._open.rel ? " open" : ""}><summary class="${hark && !a.release_updated ? "wn" : ""}">${relLine}</summary>
        ${relUrl ? `<div>${this._link(relUrl, "&#128196; Release")}</div>` : ""}
        ${a.gin_dep ? `<div><b>GIN dep:</b> <code>${this._e(a.gin_dep)}</code></div>` : ""}${a.gin_arr ? `<div><b>GIN arr:</b> <code>${this._e(a.gin_arr)}</code></div>` : ""}
        ${hark ? `<div class="bh">MEL</div><ul>${mel.map((x) => `<li>${this._e(x)}</li>`).join("") || "<li>None listed</li>"}</ul>
        <div class="bh">NOTAMs</div><ul>${notam.map((x) => `<li>${this._e(x)}</li>`).join("") || "<li>None listed</li>"}</ul>` : ""}</details>`;
      let lay = "";
      if (hark && a.mode === "layover") {
        const tel = String(a.hotel_phone || "").replace(/[^\d+]/g, "");
        const map = this._https(a.hotel_map);
        const photos = (Array.isArray(a.todo_photos) ? a.todo_photos : []).filter((x) => x && this._https(x.img)).slice(0, 8);
        lay = `<div class="sec"><h3>&#127976; ${this._e(a.hotel || "Hotel")}</h3>
          ${a.hotel_address ? `<div>${map ? `<a href="${this._e(map)}" target="_blank" rel="noopener noreferrer">${this._e(a.hotel_address)}</a>` : this._e(a.hotel_address)}</div>` : ""}
          ${tel ? `<div><a href="tel:${this._e(tel)}">&#128222; ${this._e(a.hotel_phone)}</a></div>` : ""}
          ${a.hotel_notes ? `<div class="u hn">${this._e(a.hotel_notes)}</div>` : ""}
          ${a.weather ? `<div class="blk"><div class="bh">&#9925; Weather</div><div>${this._e(a.weather)}</div></div>` : ""}
          ${this._list("Open now", a.open_now, "&#128339;")}${this._list("Eat", a.eat, "&#127860;")}
          ${this._list("Things to do", a.todo, "&#129517;")}
          ${photos.length ? `<div class="ph">${photos.map((x) => `<figure><img loading="lazy" decoding="async" referrerpolicy="no-referrer" src="${this._e(x.img)}" alt="${this._e(x.name || "Photo")}"><figcaption>${this._e(x.name || "")}</figcaption></figure>`).join("")}</div>` : ""}
          ${a.transport ? `<div class="blk"><div class="bh">&#128656; Transport</div><div>${this._e(a.transport)}</div></div>` : ""}
          ${a.van_rule ? `<div class="u">${this._e(a.van_rule)}</div>` : ""}</div>`;
      }
      const alerts = vt && this._vanSensor(a, vt) ? this._vanSensor(a, vt).alerts || [] : [];
      main = `<div class="hd"><div class="lt"><div class="fl">&#9992;&#65039; ${this._e(a.flight || a.pairing)} ${this._e(a.origin || "")} &rarr; ${this._e(a.dest || "")}</div>
          <div class="u">${this._e(a.pairing)}${a.leg ? ` &middot; leg ${this._e(a.leg)}` : ""}${a.date ? ` &middot; ${this._e(a.date)}` : ""}${a.tail ? ` &middot; ${this._e(a.tail)}` : ""}</div>
          ${a.mode ? `<span class="mode">${this._e(a.mode === "layover" ? `Layover ${a.origin || ""}` : a.mode)}</span>` : ""}</div>${big}</div>
        ${vt && vt.place ? `<div class="vp">&#128656; Van at ${this._e(vt.place)}${alerts.length ? ` <span class="u">&middot; alerts ${alerts.map((x) => `${x.minutes} min ${x.status === "sent" ? "&#10003;" : x.status === "pending" ? `at ${this._e(x.at_hst)} HST` : this._e(x.status)}`).join(", ")}</span>` : ""}</div>` : ""}
        ${unread ? `<div class="vp" data-vanunread>&#128656; Van: ${this._e(unread)} <span class="u">&middot; no van alert: its time could not be read for sure</span></div>` : ""}
        <div class="tm">${a.report ? `<div><span class="k">Report</span> ${this._e(a.report)}</div>` : ""}
          ${dep ? `<div><span class="k">Departs</span> ${this._e(a.dep_sched)}</div>` : ""}${arr ? `<div><span class="k">Arrives</span> ${this._e(a.arr_sched)}</div>` : ""}</div>
        ${status}${links ? `<div class="chips">${links}</div>` : ""}${rel}${lay}`;
    }
    const city = prevCity && prevCity.dataset.touched ? prevCity.value.toUpperCase() : this._cityNow(a, hark);
    const notes = n ? this._notesHtml(n, city) : "";
    const foot = a.updated ? `<div class="u ft">Updated ${this._e(a.updated)}${a.updated_by ? ` by ${this._e(a.updated_by)}` : ""}${a.next ? ` &middot; Next: ${this._e(a.next)}` : ""}</div>` : "";
    r0.innerHTML = `<style>
      :host{display:block}
      ha-card{padding:12px 14px;font-size:14px;line-height:1.4;color:var(--primary-text-color)}
      .u{color:var(--secondary-text-color);font-size:12px}
      .warn{color:#fff;background:#b71c1c;border-radius:6px;padding:4px 8px;margin:4px 0;font-size:12px;font-weight:600}
      .hd{display:flex;align-items:flex-start;gap:10px}.lt{flex:1;min-width:0}
      .fl{font-size:20px;font-weight:700;line-height:1.25;overflow-wrap:anywhere}
      .mode{display:inline-block;margin-top:4px;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:var(--text-primary-color,#fff);background:var(--primary-color);text-transform:capitalize}
      .van{flex:none;text-align:right;min-width:104px}
      .vl{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--secondary-text-color)}
      .vt{font-size:44px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
      .vz,.vh{font-size:12px;color:var(--secondary-text-color);white-space:nowrap}.vz{font-weight:700;color:var(--primary-text-color)}
      .rep .vt{font-size:36px}.rep .vz{white-space:normal;max-width:150px;font-weight:400}
      .cd{font-size:14px;font-weight:700;margin-top:2px;color:var(--primary-text-color)}
      .cd.soon,.cd.now{color:#fff;border-radius:6px;padding:0 6px;display:inline-block}.cd.soon{background:#8a5300}.cd.now{background:#b71c1c}
      .cd.past{color:var(--secondary-text-color);font-weight:400}
      .vp{margin:8px 0 2px;font-weight:600}
      .tm{margin:8px 0;display:grid;gap:2px}.k{display:inline-block;min-width:62px;color:var(--secondary-text-color);font-size:12px;font-weight:600}
      .stt{font-size:13px;margin:4px 0}
      .chips{display:flex;flex-wrap:wrap;gap:10px 6px;margin:12px 0}
      a{color:var(--primary-text-color)}
      a.chip{position:relative;display:inline-flex;align-items:center;min-height:34px;box-sizing:border-box;padding:0 12px;border-radius:17px;border:1px solid var(--divider-color);font-size:13px;font-weight:600;text-decoration:none;color:var(--primary-text-color);background:var(--card-background-color)}
      a.chip::after{content:"";position:absolute;inset:-6px 0}
      .sec>div>a,.rel>div>a{display:inline-flex;align-items:center;min-height:44px}
      details{border-top:1px solid var(--divider-color);padding:2px 0}summary{cursor:pointer;font-weight:600;font-size:13px;padding:12px 0;line-height:20px}
      summary.wn{color:var(--primary-text-color)}.rl{border-top:1px solid var(--divider-color);padding:8px 0}
      .sec{border-top:1px solid var(--divider-color);margin-top:8px;padding-top:8px}
      h3{margin:0 0 4px;font-size:16px}.bh{font-weight:700;font-size:13px;margin-top:8px}
      ul{margin:2px 0 4px;padding-left:20px}li{margin:1px 0}
      .hn{margin-top:4px}.blk{margin-top:2px}
      .ph{display:flex;gap:8px;overflow-x:auto;padding:6px 0;margin:0}
      figure{margin:0;flex:none;width:96px}figure img{width:96px;height:64px;object-fit:cover;border-radius:6px;display:block;background:var(--divider-color)}
      figcaption{font-size:11px;color:var(--secondary-text-color);line-height:1.2;margin-top:2px}
      .guide{border-left:3px solid var(--primary-color);padding:2px 0 2px 10px;margin:6px 0}.guide h4{margin:6px 0 2px;font-size:14px}.guide h5{margin:6px 0 2px;font-size:13px}
      .guide p{margin:4px 0}code{font-size:12px}
      .nl{list-style:none;padding:0;margin:6px 0}.nl li{border-top:1px solid var(--divider-color);padding:6px 0;display:flex;gap:8px;align-items:flex-start}
      .nt{flex:1;white-space:pre-wrap;overflow-wrap:anywhere}.nm{flex:none;display:flex;align-items:center;gap:6px}
      textarea{display:block;width:100%;box-sizing:border-box;font:14px sans-serif;padding:6px;margin-top:6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
      .row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:6px}
      .cl{font-size:12px;color:var(--secondary-text-color);display:inline-flex;align-items:center;gap:4px}
      .cl input{width:56px;min-height:44px;box-sizing:border-box;font:14px sans-serif;text-transform:uppercase;padding:4px 6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
      button{cursor:pointer;border:0;border-radius:6px;min-height:44px;padding:6px 14px;font-weight:600;font-size:13px;background:var(--primary-color);color:var(--text-primary-color,#fff)}
      button.g{background:#757575;color:#fff}button:disabled{opacity:.5;cursor:default}
      button.x{background:none;color:var(--secondary-text-color);border:1px solid var(--divider-color);min-width:44px;min-height:44px;padding:0 8px;font-size:15px}
      button.x.arm{color:#fff;background:#b71c1c;border-color:transparent;font-size:12px}
      .ft{margin-top:8px}
    </style><ha-card>${main}${notes}${foot}</ha-card>`;
    const r = r0;
    r.querySelectorAll("details[data-k]").forEach((d) => { d.ontoggle = () => { this._open[d.dataset.k] = d.open; }; });
    const ta = r.querySelector("[data-draft]");
    if (ta) {
      ta.value = this._draft;
      ta.oninput = () => { this._draft = ta.value; };
      if (focus) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    }
    const ci = r.querySelector("[data-city]");
    if (ci) {
      if (prevCity && prevCity.dataset.touched) ci.dataset.touched = "1";
      ci.oninput = () => { ci.dataset.touched = "1"; ci.value = ci.value.toUpperCase().replace(/[^A-Z]/g, ""); };
      ci.onchange = () => { if (/^[A-Z]{3}$/.test(ci.value)) this._render(); };
    }
    const msg = (t, bad) => { const m = r.querySelector("[data-nmsg]"); if (m) { m.textContent = t; m.className = bad ? "warn" : "u"; } };
    const add = r.querySelector("[data-addnote]");
    if (add) add.onclick = async () => {
      const c = (ci && ci.value || "").toUpperCase(), t = (ta && ta.value || "").trim();
      if (!/^[A-Z]{3}$/.test(c)) { msg("Type the city's 3-letter code (SYD).", true); return; }
      if (!t) { msg("Type a note first.", true); return; }
      if (t.length > FW_LAYOVER_NOTE_MAX) { msg(`At most ${FW_LAYOVER_NOTE_MAX} characters a note.`, true); return; }
      const rid = this._rid();
      add.disabled = true;
      try { await this._pub("layover/note", { city: c, text: t, rid }); }
      catch (e) { add.disabled = false; msg(`Didn't send: ${(e && e.message) || "no connection"}. Try again.`, true); return; }
      this._sent = { rid, action: "add" }; this._draft = ""; if (ta) ta.value = "";
      add.disabled = false; msg("Saving...", false);
    };
    r.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.del;
      if (this._arm !== id) { this._arm = id; this._render(); return; }  // the first tap asks, the second deletes
      this._arm = "";
      const rid = this._rid();
      try { await this._pub("layover/note", { city: b.dataset.c, delete: id, rid }); this._sent = { rid, action: "delete" }; }
      catch (e) { msg(`Didn't send: ${(e && e.message) || "no connection"}.`, true); return; }
      msg("Deleting...", false);
    });
    const tidy = r.querySelector("[data-tidy]");
    if (tidy) tidy.onclick = async () => {
      const c = (ci && ci.value || "").toUpperCase();
      if (!/^[A-Z]{3}$/.test(c) || this._tidied[c]) return;
      const ver = ((this._st(`sensor.${p}_state`) || {}).attributes || {}).version || "";
      const t = { kind: "feature", title: `Tidy the ${c} layover notes`, page: "Working Flight", version: ver, steps: "", expected: "",
        narrative: `Tidy my ${c} layover notes into a guide (HANDOFF.md, "Layover notes"): read /share/flight_watcher/layovers/${c}.json, write /share/flight_watcher/layovers/${c}.guide.md, keep every fact I wrote, then mark this ticket fixed.`,
        cid: this._rid().replace(/^r/, "c"), images: 0 };
      tidy.disabled = true;
      try { await this._pub("ticket/new", t); }
      catch (e) { tidy.disabled = false; msg(`Didn't send: ${(e && e.message) || "no connection"}.`, true); return; }
      this._tidied[c] = true;
      msg(`Ticket filed: Claude tidies the ${c} notes into a guide (Settings, Tickets).`, false);
    };
  }
}
customElements.define("flight-watcher-layover-card", FlightWatcherLayoverCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-layover-card", name: "Flight Watcher layover", description: "The working flight at a glance: the van time, the layover and your notes by city." });

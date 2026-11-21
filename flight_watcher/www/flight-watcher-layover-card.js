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
// the Watcher's (the markdown card's rule); sensor.<prefix>_layover_van (the Watcher's van on the station's clock:
// abbreviation, HST, the instant for the countdown, the alerts' status, and its source). The van, in the Watcher's
// order (Ryan, Nov 11): the pairings package's VAN for this layover (source "package"), else Hark's van text, else
// none: the card says the van time is not known (and why), so no van alert comes. The source shows under the time. Hark's data shows only
// while sensor.<prefix>_state says role admin (not while that sensor is missing or has no role), so a pilot's copy
// never shows another pilot's trip. Admin only in this release: not in the pilot portal's layout (and not bundled
// for it). Colors: text on the card's own background is the theme's primary text color; the countdown's urgent states
// and the armed delete are white on a fixed dark orange or red, so they read in any theme (Home Assistant's
// default warning and error colors are under 4.5:1 on white). Taps are 44 px at least.
// Review r4: a pairing FLICA rebuilt (H3681B) and Hark's H3681 are the same trip here too (_same, layover.same_pairing),
// so the card takes Hark's sensor, the package's van and the Watcher's van reading for it, and it never says "no van
// alert comes" while the Watcher's van sensor has a van; a long link or word wraps instead of widening a phone's page;
// when the package's van wins and Hark says another time, both show ("Hark says 19:40"); Report and Departs carry
// HST (from the Watcher's sensor on the same trip when the times are Hark's) and the station's zone instead of "local";
// the note and City fields are 16 px on a phone (iOS zooms into a smaller one); the Layover pill is white on a fixed
// dark blue (Home Assistant's default blue was 3.26:1).
// 1.7.2 (Ryan, Nov 12: "I like the layover card. Can you add a tick box to turn on the van time alerts and also add van
// time alert settings in the form of sliders in the settings tab?"): under the van time, a "Van alerts" tick box
// (checked from sensor.<prefix>_layover_van's alerts_on, else switch.<prefix>_van_alerts; neither says: "Not known yet",
// the box not tappable, never a claim that alerts are on) that publishes <prefix>/van/alerts/set ON or OFF; "Saving..."
// until the sensor says the new state (a publish error says so and puts the box back; no answer in 30 s does too, also
// after the card was away from the page; a message goes once the Watcher's state changes). Under it the lead times
// ("30 and 10 min before", "Off") and "Change in Settings" (the sliders, /flight-watcher/settings). The box, its label
// and the link are 44 px taps; the box keeps the keyboard focus through a tap and its answer (aria-disabled while
// waiting, never disabled, which would drop the focus).
// 1.7.11 (FW-0075, Ryan, Nov 17: "I need to have a plus and a - kind of below the numbers for the van time because in
// some cases the company adjust the van time a little tiny bit ... so I could set it for 510 for example"): under the
// van time, "-5 min" and "+5 min" (44 px taps, aria-labels "Van 5 minutes earlier" and "Van 5 minutes later"), only when
// sensor.<prefix>_layover_van says adjustable (the admin's Watcher placed this van; never Hark's van the Watcher did not
// place, never in a portal's copy). A press publishes <prefix>/van/adjust/set {van: its van_id, minutes}: the absolute
// move (the Watcher's adjust_min plus or minus 5, within FW_VAN_ADJUST), so a repeat or a retry never moves it twice.
// "Saving..." until the sensor says that adjust_min, "Not saved, try again" after 10 s without it (or a publish error,
// or the van itself changed). Moved: the big time is the moved van (HST, countdown and alert times too), a line "You
// moved it -15 min (the package says 05:25)" ("Hark says" for Hark's van) and "Back to 05:25" (minutes 0).
// Review: one move at a time: while one is saving, -5, +5 and Back are aria-disabled (never disabled, which would drop
// the focus) and a tap on them does nothing, so only the answer to that one command ends "Saving..."; a button at an
// end of the range is aria-disabled the same way; when Back goes after its answer, the focus moves to -5. A screen
// reader hears "Saving", "Van moved to 05:10", "Van back to 05:25" or "Not saved, try again" from one visually hidden
// role=status element that every render keeps (outside the part drawn again).
// 1.7.24 (Ryan, Nov 20: "calculate per FAR 117 and PWA when I timeout, both for if I extend or if I
// do not. Add that number in bold with a dark orange square around it right of the report time"): the Watcher's
// sensor.<prefix>_working_flight `timeout` (timeout.py: FAR 117 Tables A, B and C, acclimation, pilots, rest class,
// flight time and the cumulative limits; PWA 2.A.19.b release and Section 10 duty, rest and landings) shows in a box
// with a 2 px dark orange border (#c2410c, 3:1 or more on light and dark cards; its text is the theme's own colors)
// right of the report time: TIMEOUT, the no-extension time in bold, "Ext" and the time with the 2:00 extension, and
// the rule that binds. With no van the box sits beside the Report block in the header (both wrap under the title on a
// phone); with a van, right of the Report line. It is a button (Enter and Space too): it opens the basis under it,
// each rule with its FOM, FAR or PWA cite, and what is not checked. The times are the Watcher's for the same pairing
// and leg (also under Hark's data). No `timeout` attribute (an older Watcher, a crew not known): no box, nothing else
// changes.
// 1.7.24 review (Ryan, Nov 20: "when is the last moment I can block out and be legal"): the box is LAST OUT, the last
// legal block-out on the departure station's clock (as the big Report time), "Ext" with the extension, the two in HST
// small, and the flight time as "FT 11:15 of 13:00". NOT LEGAL instead of a time when the planned flight time, a
// cumulative limit or the PWA Maximum is over at the scheduled times; a '?' after the time only for what moves a last
// out when it is not sure (`unsure`: acclimation, the clock, the rest class, the pilots, a 4-pilot crew's Captains
// where the PWA binds, or Mixed Flying where its 10.D.3 limit binds), the earlier reading shown. The basis opens with
// the block-out and block-in limits of both cases; how it is worked out and what is not checked fold under it. Under a
// van, the box sits right of the Report line and Departs and Arrives keep the full width.
// 1.7.24 (Ryan, Nov 20: PWA Section 10 now on file): the PWA duty Maximum (10.D) caps both last outs; when it binds,
// a small line in the box names it as a duration ("PWA max duty 16 h", "Ext: PWA max duty 18 h"), NOT LEGAL when it is
// over at the scheduled times, and the details carry a PWA row (the duty against its Scheduled limit, the rest of
// 10.E, the landings of 10.H). A chip for every flag (timeout `flags`), in a NOT LEGAL box too (review round 4, fix
// 1): "Over as scheduled" (last_out.early), "Check crew" (pilots raised), "Rest short" (FAR rest or 30 h in 168 h),
// "PWA rest short", "Landings over", "Over 3 segments (FOM)", "Past PWA schedule", and "Rest ?" / "Landings ?" for a
// rest or a landings count that is not sure (rest_q, landings_q: these never put a '?' on the time, as they do not
// move a last out). Review round 4, fix 2 (UI-R4V-1): the details carry a FAR rest row before the PWA one (timeout
// rest.txt: the rest free, the need of the rule that decides, its cite and verdict, and 30 h in 168 h), so the rest a
// chip is about is seen without opening "How it is worked out".
// 1.7.24 review: the time keeps 24 px with its '?' right after it and its clock smaller after it (a zone with no
// letters is named by its station: "14:43? SIN"), so the box stays beside the Report block at 320 px; NOT LEGAL is
// white on red ("Not legal as scheduled (PWA)" for a PWA Maximum, "Not legal to dispatch" for FAR 117), with its '?';
// up to two flag chips show (a third and more as "+N more flags"), every one in the label.
// Usage: type: custom:flight-watcher-layover-card, update_url: https://... (optional)
const FW_LAYOVER_NOTE_MAX = 1000;  // layover.NOTE_MAX
const FW_VAN_ADJUST = { lo: -120, hi: 120, step: 5 };  // layover.ADJUST_RANGE and ADJUST_STEP
const FW_PORTAL = false;  // portal.portal_card turns it on in a portal's copy (this card is on no portal): no van move there
class FlightWatcherLayoverCard extends HTMLElement {
  setConfig(c) {
    this._c = { prefix: "flight_watcher", ...(c || {}) };
    this._draft = this._draft || ""; this._open = this._open || {}; this._sent = this._sent || null; this._arm = "";
    this._tidied = this._tidied || {};
    this._vaWant = this._vaWant === undefined ? null : this._vaWant; this._vaMsg = this._vaMsg || "";
    this._vaMsgOn = this._vaMsgOn === undefined ? null : this._vaMsgOn;
    this._adj = this._adj || null; this._adjMsg = this._adjMsg || ""; this._adjMsgKey = this._adjMsgKey || "";
  }
  getCardSize() { return 8; }
  connectedCallback() {
    if (!this._tick) this._tick = setInterval(() => this._countdown(), 30000);
    if (this._vaWant !== null && this._vaWant !== undefined && !this._vaT) this._vaWait();  // back while still waiting
    if (this._adj && !this._adjT) this._adjWait();  // 1.7.11: a van move still saving
  }
  disconnectedCallback() {
    if (this._tick) { clearInterval(this._tick); this._tick = null; }
    if (this._vaT) { clearTimeout(this._vaT); this._vaT = null; }
    if (this._adjT) { clearTimeout(this._adjT); this._adjT = null; }
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  _https(u) { return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(\/[^\s"<>]*)?$/.test(String(u || "")) ? String(u) : ""; }
  _link(u, t, cls) { const h = this._https(u); return h ? `<a${cls ? ` class="${cls}"` : ""} href="${this._e(h)}" target="_blank" rel="noopener noreferrer">${t}</a>` : ""; }
  _st(id) { return this._h && this._h.states[id]; }
  // Ryan, Nov 12: "Gin code should be on its own line so it doesn't get cut off." Hark writes "HNL gate C5 (Non-Mauka):
  // *-2-1-1-7-3-1-4-5-2-#": the place stays on the label's line and the code gets a line of its own, never broken
  _gin(label, v) {
    const s = String(v || ""), i = s.lastIndexOf(": ");
    const where = i >= 0 ? s.slice(0, i) : "", code = i >= 0 ? s.slice(i + 2) : s;
    return `<div class="gin"><b>${label}:</b>${where ? ` ${this._e(where)}` : ""}<br><code>${this._e(code)}</code></div>`;
  }
  // layover._base_id / same_pairing: H3681B (FLICA rebuilt it) is the same trip as H3681
  _base(p) { const s = String(p || "").trim().toUpperCase(); return /^[A-Z]\d{3,5}[A-Z]$/.test(s) ? s.slice(0, -1) : s; }
  _same(x, y) { const a = this._base(x); return !!a && a === this._base(y); }
  set hass(h) {
    this._h = h;
    const p = this._c.prefix, ids = ["sensor.hark_working_flight", `sensor.${p}_working_flight`, `sensor.${p}_layover_van`,
      `sensor.${p}_layover_notes`, `sensor.${p}_state`, `switch.${p}_van_alerts`];
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
    const use = h && (!wa.pairing || this._same((h.attributes || {}).pairing, wa.pairing)) ? h : w;
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
  _harkVan(a, state) {
    const got = this._parseVan(a.van), dated = /\d{4}-\d{2}-\d{2}/.test(String(a.van || ""));
    const m = got || dated ? null : /\bvan\b(.*)$/i.exec(String(state || ""));
    return got || (m ? this._parseVan(m[1]) : null);
  }
  _vanText(a, state) {
    const vt = this._harkVan(a, state);
    if (vt) return vt;
    const v = this._st(`sensor.${this._c.prefix}_layover_van`), va = (v && v.attributes) || {};
    return va.at && this._same(va.pairing, a.pairing) && va.local && va.date
      ? { local: String(va.local), date: String(va.date), wd: String(va.weekday || ""), place: String(va.place || "") } : null;
  }
  // the Watcher's reading of the same van (its zone abbreviation, HST and instant), or null while it has not read it
  _vanSensor(a, vt) {
    const v = this._st(`sensor.${this._c.prefix}_layover_van`), va = (v && v.attributes) || {};
    return vt && va.at && this._same(va.pairing, a.pairing) && va.date === vt.date && va.local === vt.local ? va : null;
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
  // review r4: a leg's time (k: report, dep_sched) with HST. Hark's "20:25 AEDT (8:25 PM) Thu 2026-11-12" gets the
  // Watcher's HST part when the Watcher's sensor is on the same trip, station and local time ("20:25 local, 23:25
  // HST"); the Watcher's own "local" (both times are at the leg's origin) becomes the zone the van sensor read for
  // that station on this trip ("20:25 AEDT, 23:25 HST"), else it stays "local"
  _when(k, a, hark, w, va) {
    const t = String(a[k] || ""), wa = (w && w.attributes) || {}, o = String(a.origin || "").toUpperCase();
    if (!t) return t;
    if (hark) {
      const x = this._timeParts(t), y = this._timeParts(wa[k]), m = /\b(\d{1,2}:\d{2})\s*HST\b/.exec(String(wa[k] || ""));
      const same = this._same(wa.pairing, a.pairing) && String(wa.origin || "").toUpperCase() === o;
      return /\bHST\b/.test(t) || !(x && y && m && same && x.hm === y.hm) ? t : `${t}, ${m[1]} HST`;
    }
    const z = va && va.at && this._same(va.pairing, a.pairing) && va.city === o && /^[A-Z]{2,5}$/.test(String(va.abbr || "")) ? va.abbr : "";
    return z ? t.replace(/\blocal\b/, z) : t;
  }
  // 1.7.24: the Watcher's duty timeout for the leg shown (Hark's sensor carries none: the Watcher's on the same
  // pairing and origin), or null
  _toOf(a, hark, w) {
    const wa = (w && w.attributes) || {}, t = wa.timeout;
    if (!t || typeof t !== "object" || !((t.no_ext && t.no_ext.txt) || (t.last_out && t.last_out.txt) || t.legal === false)) return null;
    if (hark && !(this._same(wa.pairing, a.pairing) && String(wa.origin || "").toUpperCase() === String(a.origin || "").toUpperCase())) return null;
    return t;
  }
  // the weekday ("Sat") of a result when it is not the report's day
  _toDay(x, t) { return x && x.day && t.report_day && x.day !== t.report_day ? String(x.day).split(" ")[0] : ""; }
  _toBox(t, a) {
    const e = (v) => this._e(v), lo = t.last_out, lx = t.last_out_ext || {}, ft = (t.ft && t.ft.short) || "";
    // review UI-R1-1: a number keeps its unit and "of" its limit ("18 h", "16:30 of 16:00"): never a unit alone on a line
    const nb = (v) => e(v).replace(/\d+(?::\d\d)?(?: h(?: \d+ min)?| min| of \d+:\d\d)/g, (m) => `<span class="nw">${m}</span>`);
    const q = t.sure === false ? `<span class="toq" title="Not sure: see the details">?</span>` : "";
    const unsure = t.sure === false ? "; not sure, the earlier reading is shown" : "";
    // review: the time big with the '?' right after it, its clock smaller (it may wrap under the time on a phone)
    const tm = (txt, wd) => {
      const v = String(txt || ""), i = v.indexOf(" "), hm = i > 0 ? v.slice(0, i) : v, z = i > 0 ? v.slice(i + 1) : "";
      return `<span class="ton">${e(hm)}${q}</span>${z ? `<span class="toz"> ${e(z)}</span>` : ""}${wd ? `<span class="tod"> ${e(wd)}</span>` : ""}`;
    };
    // every flag set, most serious first; the box shows two (one chip a flag), the label all of them (review
    // CARD-flags-segments-pilots-hidden: tests check that every flag timeout.py sets has its chip here). Review round
    // 4, fix 1 (UI-R4-1): a NOT LEGAL box shows them too (a rest short stays short when the duty is re-timed to fit)
    const fl = t.flags || [];
    const warns = [lo && lo.early ? "Over as scheduled" : "", fl.includes("pilots") ? "Check crew" : "",
      fl.some((f) => f === "rest" || f === "week") ? "Rest short" : "", fl.includes("pwa_rest") ? "PWA rest short" : "",
      fl.includes("landings") ? "Landings over" : "", fl.includes("segments") ? "Over 3 segments (FOM)" : "",
      fl.includes("pwa_sched") ? "Past PWA schedule" : "", fl.includes("rest_q") ? "Rest ?" : "",
      fl.includes("landings_q") ? "Landings ?" : ""].filter(Boolean);
    const shown = warns.length > 2 ? [warns[0], `+${warns.length - 1} more flags`] : warns;
    const chips = shown.map((w) => `<span class="tow" data-towarn>${e(w)}</span>`).join("");
    let body, say;
    if (t.legal === false) {
      // review: NOT LEGAL in white on red, the most serious state; a PWA Maximum is "not legal as scheduled", not a
      // dispatch (FAA) limit
      const nl = this._toNl(t);
      body = `<span class="tol">Last out</span><span class="tot" data-tono><span class="tonl">Not legal</span>${q}</span>
        <span class="tob" data-toby>${nb(t.not_legal_short || "")}</span>${chips}`;
      const nq = t.sure === false ? "; not sure, see the details" : "";
      say = `${nl}: ${t.not_legal_short || ""}${warns.length ? `; ${warns.join(", ")}` : ""}${nq}. Details`;
    } else if (lo && lo.txt) {
      const leg = lo.leg && lo.leg !== `${a.origin || ""}-${a.dest || ""}` ? ` ${lo.leg}` : "";
      const same = !!(lx.at && lx.at === lo.at), h = (x) => String(x || "").replace(/ HST$/, "");
      // the PWA duty Maximum when it binds (it caps both): the rule on a line of its own; when it binds only the
      // extension, the no-extension rule above it, so neither reads as the reason for both (review UI-R1-2)
      const bind = lo.pwa ? (lo.short || "") : lx.pwa ? `Ext: ${lx.short || ""}` : "";
      const rule = lx.pwa && !lo.pwa ? (lo.short || "") : "";
      const ext = !lx.txt ? "" : same ? (lo.pwa ? "Ext same" : `Ext same (${lx.short || ""})`) : `Ext ${lx.txt}${lx.wd ? ` ${lx.wd}` : ""}`;
      const hst = lo.txt !== lo.hst ? `(${h(lo.hst)}${lx.hst && !same ? ` / ${h(lx.hst)}` : ""} HST)` : "";
      body = `<span class="tol">Last out${e(leg)}</span>
        <span class="tot" data-tono>${tm(lo.txt, lo.wd)}</span>
        ${ext ? `<span class="tox" data-toext>${e(ext)}</span>` : ""}${hst ? `<span class="toh" data-tohst>${e(hst)}</span>` : ""}
        ${rule ? `<span class="tob" data-torule>${nb(rule)}</span>` : ""}${bind ? `<span class="tob" data-tobind>${nb(bind)}</span>` : ""}
        ${ft ? `<span class="tob" data-toby>${nb(ft)}</span>` : ""}${chips}`;
      // review round 5, fix 2 (UI6-3): the extension's weekday too, as the box shows it ("Ext 03:45 HST Wed")
      const sayNo = `${lo.txt}${lo.wd ? ` ${lo.wd}` : ""}${lo.txt !== lo.hst ? `, ${lo.hst}` : ""}`;
      const sayEx = `${lx.txt}${lx.wd ? ` ${lx.wd}` : ""}${lx.txt !== lx.hst ? `, ${lx.hst}` : ""}`;
      const sayExt = !ext ? "" : same ? `, the same with one${lo.pwa ? "" : ` (${lx.short || ""})`}`
        : `, ${sayEx} with one`;
      say = `Last out${leg} ${sayNo} without an extension${!lo.pwa && lo.short ? ` (${lo.short})` : ""}${sayExt}`
        + `${bind ? `; ${bind}` : ""}${t.ft && t.ft.txt ? `; flight time ${t.ft.txt}` : ""}`
        + `${warns.length ? `; ${warns.join(", ")}` : ""}${unsure}. Details`;
    } else {  // a Watcher before the last out: its block-in timeout
      const n = t.no_ext, x = t.ext || {}, dn = this._toDay(n, t), dx = this._toDay(x, t);
      body = `<span class="tol">Timeout</span><span class="tot" data-tono>${tm(n.txt, dn)}</span>
        ${x.txt ? `<span class="tox" data-toext>Ext ${e(x.txt)}${dx ? ` ${e(dx)}` : ""}</span>` : ""}<span class="tob" data-toby>${e(n.short || n.by || "")}</span>`;
      say = `Timeout ${n.txt}${dn ? ` ${dn}` : ""} without an extension${x.txt ? `, ${x.txt}${dx ? ` ${dx}` : ""} with one` : ""}${n.short ? `, ${n.short}` : ""}${unsure}. Details`;
    }
    return `<button class="to${t.legal === false ? " to-nl" : ""}" data-to aria-expanded="${this._open.to ? "true" : "false"}" aria-controls="todet" aria-label="${e(say)}">${body}</button>`;
  }
  // review: what NOT LEGAL means: over a PWA Maximum as scheduled is a contract limit (Crew Scheduling must change it),
  // the others (flight time, a cumulative limit) are FAR 117's: not legal to dispatch
  _toNl(t) { return /^PWA/.test(String(t.not_legal_short || "")) ? "Not legal as scheduled (PWA)" : "Not legal to dispatch"; }
  _toDet(t) {
    const e = (v) => this._e(v), f = t.fdp || {}, lo = t.last_out, lx = t.last_out_ext, n = t.no_ext || {}, x = t.ext || {};
    const li = (v) => (Array.isArray(v) ? v : []).map((y) => `<li>${e(y)}</li>`).join("");
    const nc = Array.isArray(t.not_checked) ? t.not_checked : [];
    const out = (r) => r && r.txt ? `block out by ${e(r.txt)}${r.txt !== r.hst ? ` (${e(r.hst)} ${e(r.day || "")})` : ` ${e(r.day || "")}`}, ` : "";
    // review UI-R1-3: the block-in's day when it is not the block-out's (an overnight duty)
    const inDay = (d, r) => d && r && r.day && d !== r.day ? ` ${e(d)}` : "";
    const ontime = (r, more) => r && r.txt ? `<div class="u">Out on time${t.sched_out_txt ? ` (${e(t.sched_out_txt)})` : ""}: block in by ${e(r.txt)} ${e(r.day || "")}, ${e(r.short || "")}${more}.</div>` : "";
    // review CARD-ontime, UI-R1-4: why the two on-time block-ins are one, by the rule that binds them
    const xs = String(x.short || ""), one = !!(x.at && x.at === n.at);
    const why1 = !one ? "" : /flight time$/.test(xs) ? ": an extension adds no flight time" : /^PWA/.test(xs) ? ": the PWA Maximum caps it, an extension adds nothing" : ": the same limit binds both, an extension adds nothing";
    let rows;
    if (t.legal === false) {
      rows = `<div class="trw tnl"><b class="tnlb">${e(this._toNl(t))}:</b> ${e(t.not_legal || "")}.</div>`;
    } else if (lo && lo.txt) {
      rows = `<div class="trw"><b>No extension:</b> ${out(lo)}block in by ${e(f.in_txt || f.end_txt || "")}${f.in_txt ? inDay(f.in_day, lo) : ""}${f.release_txt ? `, release ${e(f.release_txt)}` : ""}<div class="u">${e(lo.by || "")}</div>${ontime(n, "")}</div>
        <div class="trw"><b>With extension:</b> ${out(lx)}block in by ${e(f.ext_in_txt || f.ext_end_txt || "")}${f.ext_in_txt ? inDay(f.ext_in_day, lx) : ""}${f.ext_release_txt ? `, release ${e(f.ext_release_txt)}` : ""}<div class="u">${e((lx && lx.by) || "")}; before takeoff only</div>${ontime(x, why1)}</div>`;
    } else {
      const row = (k, r) => r && r.txt ? `<div class="trw"><b>${k}:</b> ${e(r.txt)} ${e(r.day || "")}${r.release_txt ? `, release ${e(r.release_txt)}` : ""}<div class="u">${e(r.by || "")}</div></div>` : "";
      rows = `${row("No extension", n)}${row("With extension", x)}`;
    }
    const c = t.cum || {}, cum = ["ft_672", "fdp_168", "fdp_672"].filter((k) => c[k] && c[k].txt).map((k) => e(c[k].txt)).join(" &middot; ");
    const ftl = t.ft && t.ft.txt ? `<div class="trw"><b>Flight time:</b> ${e(t.ft.txt)}${cum ? ` &middot; ${cum}` : ""}</div>` : "";
    // review round 4, fix 2 (UI-R4V-1): the FAR rest row (117.25(e), (b), (d), (g): the rule that decides and its
    // verdict) beside the PWA one, before the fold, so a "Rest short" or "Rest ?" chip is never read against PWA alone
    const far = t.rest && t.rest.txt ? `<div class="trw" data-tofar><b>FAR rest:</b> ${e(t.rest.txt)}</div>` : "";
    const pwa = t.pwa && t.pwa.txt ? `<div class="trw" data-topwa><b>PWA:</b> ${e(t.pwa.txt)}</div>` : "";
    const why = { acclimation: "acclimation", clock: "which clock enters the tables", "rest class": "the rest facility class", pilots: "the number of pilots", "PWA crew": "the Captains of the crew (PWA 10.D.1.c or 10.D.1.d)", "Mixed Flying": "whether the duty is Mixed Flying (PWA 2.A.45: a neighbor island leg's long sit, or an interisland deadhead), which sets the PWA duty limit" };
    const uns = t.sure === false ? `<div class="trw" data-tounsure><b>? Not sure:</b> ${e((t.unsure || []).map((k) => why[k] || k).join(", "))}: the earlier reading is shown (see below).</div>` : "";
    return `<div class="tdet" id="todet" data-todet${this._open.to ? "" : " hidden"}>${rows}${ftl}${far}${pwa}${uns}
      <details data-k="tobasis"${this._open.tobasis ? " open" : ""}><summary>How it is worked out</summary><ul data-tolines>${li(t.lines)}</ul></details>
      ${nc.length ? `<details data-k="tonc"${this._open.tonc ? " open" : ""}><summary>Not checked (${nc.length})</summary><ul data-tonc>${li(nc)}</ul></details>` : ""}
      <div class="u">From your FLICA schedule: the times move with the actual out and in.</div></div>`;
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
  // 1.7.2: the van alerts' switch as the Watcher has it: the van sensor's alerts_on, else the switch entity; null when
  // neither says (unavailable, unknown, not there yet): never taken as on
  _vaOn() {
    const p = this._c.prefix, va = (this._st(`sensor.${p}_layover_van`) || {}).attributes || {};
    if (typeof va.alerts_on === "boolean") return va.alerts_on;
    const sw = this._st(`switch.${p}_van_alerts`);
    return sw && (sw.state === "on" || sw.state === "off") ? sw.state === "on" : null;
  }
  // what the box shows: the asked state while waiting, else the Watcher's (null: not known)
  _vaShown() { return this._vaWant !== null ? this._vaWant : this._vaOn(); }
  // no answer in 30 s (a publish that never returns too): the box goes back and says so
  _vaWait() {
    if (this._vaT) clearTimeout(this._vaT);
    this._vaT = setTimeout(() => {
      this._vaT = null;
      if (this._vaWant === null) return;
      this._vaWant = null; this._vaSay("The Watcher did not confirm it. Is Flight Watcher running? Try again.");
      this._render();
    }, 30000);
  }
  _vaSay(m) { this._vaMsg = m; this._vaMsgOn = this._vaOn(); }
  // "30 and 10 min before", "10 min before": the sensor's offsets (1.7.1's alerts list, else 30 and 10)
  _vaWords(on) {
    if (!on) return "Off";
    const va = (this._st(`sensor.${this._c.prefix}_layover_van`) || {}).attributes || {};
    const raw = Array.isArray(va.offsets) ? va.offsets : Array.isArray(va.alerts) ? va.alerts.map((x) => x && x.minutes) : [30, 10];
    const o = [...new Set(raw.map(Number).filter((n) => Number.isInteger(n) && n > 0))].sort((a, b) => b - a);
    return o.length ? `${o.join(" and ")} min before` : "No lead time set";
  }
  _vaHtml() {
    const on = this._vaOn();
    if (this._vaWant !== null && on === this._vaWant) {  // the Watcher says what was asked: no longer waiting
      this._vaWant = null;
      if (this._vaT) { clearTimeout(this._vaT); this._vaT = null; }
    }
    if (this._vaMsg && on !== this._vaMsgOn) this._vaMsg = "";  // the Watcher's state changed since: the message is old
    const pend = this._vaWant !== null, unk = !pend && on === null, shown = this._vaShown(), off = pend || unk;
    const words = unk ? "Not known yet: Flight Watcher has not said" : this._vaWords(shown);
    return `<div class="va" data-va><label class="vck${off ? " pend" : ""}"><input type="checkbox" data-vaon${shown ? " checked" : ""}${off ? ' aria-disabled="true"' : ""} aria-describedby="vasub"><span class="bx" aria-hidden="true"></span><span class="vlb">Van alerts</span>${pend ? `<span class="u" data-vapend>Saving...</span>` : ""}</label>
      <div class="u vas" id="vasub"><span data-vawords>${this._e(words)}</span> &middot; <a href="/flight-watcher/settings" data-vaset>Change in Settings</a></div>
      ${this._vaMsg ? `<div class="warn" data-vamsg>${this._e(this._vaMsg)}</div>` : ""}</div>`;
  }
  // 1.7.11 (FW-0075): Ryan's move of the Watcher's van for this pairing ({m, local, date}: the minutes and the van as
  // read), from the van sensor's adjust_min, orig_local and orig_date; null when it is not moved
  _moved(va, a) {
    const m = va.adjust_min;
    return va.at && this._same(va.pairing, a.pairing) && Number.isInteger(m) && m !== 0 && va.orig_local && va.orig_date
      ? { m, local: String(va.orig_local), date: String(va.orig_date) } : null;
  }
  _wdOf(d) {
    const s = String(d || ""), t = new Date(`${s}T00:00:00Z`);
    return /^\d{4}-\d{2}-\d{2}$/.test(s) && isFinite(t) ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][t.getUTCDay()] : "";
  }
  _adjKey() {
    const va = (this._st(`sensor.${this._c.prefix}_layover_van`) || {}).attributes || {};
    return `${va.van_id}|${va.adjust_min}`;
  }
  _adjSay(m) { this._adjMsg = m; this._adjMsgKey = this._adjKey(); this._liveMsg = m; }
  // no answer in 10 s (a publish that never returns too): not saved
  _adjWait() {
    if (this._adjT) clearTimeout(this._adjT);
    this._adjT = setTimeout(() => {
      this._adjT = null;
      if (!this._adj) return;
      this._adj = null; this._adjSay("Not saved, try again");
      this._render();
    }, 10000);
  }
  // the -5 and +5 buttons, the move and Back, under the van time; "" unless the Watcher's sensor says adjustable for
  // the van shown (vs: the Watcher's reading of it)
  _adjHtml(va, vs, mv) {
    this._adjVan = "";
    if (FW_PORTAL || !vs || va.adjustable !== true || typeof va.van_id !== "string" || !va.van_id) return "";
    const cur = Number.isInteger(va.adjust_min) ? va.adjust_min : 0, w = this._adj;
    // one move at a time, from the Watcher's adjust_min (never equal to it when sent): the Watcher says the move asked,
    // or the van changed
    if (w && (w.van !== va.van_id || w.minutes === cur)) {
      this._adj = null;
      if (this._adjT) { clearTimeout(this._adjT); this._adjT = null; }
      if (w.van !== va.van_id) this._adjSay("Not saved, try again");
      else this._liveMsg = `Van ${cur ? "moved" : "back"} to ${String(va.local || "")}`;
    }
    if (this._adjMsg && this._adjKey() !== this._adjMsgKey) this._adjMsg = "";  // the Watcher's van changed since
    this._adjVan = va.van_id; this._adjCur = cur;
    const { lo, hi, step } = FW_VAN_ADJUST, wait = !!this._adj;
    // aria-disabled, never disabled (the focus stays on it); onclick ignores it
    const btn = (d, text, label, off) => `<button class="vbt" data-vadj="${d}"${label ? ` aria-label="${label}"` : ""}${off || wait ? ' aria-disabled="true"' : ""}>${text}</button>`;
    const orig = mv ? `${mv.local}${mv.date !== String(va.date || "") ? ` ${this._wdOf(mv.date)}` : ""}`.trim() : "";
    const said = `${va.source === "package" ? "the package" : "Hark"} says ${orig}`;
    const moved = `You moved it ${cur > 0 ? "+" : "-"}${Math.abs(cur)} min${mv ? ` (${said})` : ""}`;
    return `<div class="vadj" data-vadjrow>
      <div class="vab">${btn(-step, "&minus;5 min", "Van 5 minutes earlier", cur - step < lo)}${btn(step, "+5 min", "Van 5 minutes later", cur + step > hi)}</div>
      ${this._adj ? `<div class="u" data-vadjpend>Saving...</div>` : ""}
      ${cur ? `<div class="vmv"><span data-vmoved>${this._e(moved)}</span>${btn(0, this._e(mv ? `Back to ${orig}` : "Undo the move"), "", false)}</div>` : ""}
      ${this._adjMsg ? `<div class="warn" data-vadjmsg>${this._e(this._adjMsg)}</div>` : ""}</div>`;
  }
  _go(e, href) {
    if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // a new tab keeps the link's own way
    e.preventDefault();
    try { history.pushState(null, "", href); window.dispatchEvent(new CustomEvent("location-changed")); } catch (x) { location.href = href; }
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const r0 = this.shadowRoot, focus = r0.activeElement && r0.activeElement.matches && r0.activeElement.matches("[data-draft]");
    if (!this._body || this._body.getRootNode() !== r0) {  // review F4: the body is drawn again, the live region stays
      this._body = document.createElement("div");
      this._live = document.createElement("div");
      [["class", "sr"], ["role", "status"], ["aria-live", "polite"], ["aria-atomic", "true"], ["data-vadjlive", ""]]
        .forEach(([k, v]) => this._live.setAttribute(k, v));
      r0.replaceChildren(this._body, this._live);
    }
    const vaFocus = !!(r0.activeElement && r0.activeElement.matches && r0.activeElement.matches("[data-vaon]"));
    const adjFocus = r0.activeElement && r0.activeElement.getAttribute ? r0.activeElement.getAttribute("data-vadj") : null;
    const toFocus = !!(r0.activeElement && r0.activeElement.matches && r0.activeElement.matches("[data-to]"));
    const prevCity = r0.querySelector("[data-city]");
    const { s, a, hark, w } = this._pick();
    const p = this._c.prefix, n = this._st(`sensor.${p}_layover_notes`);
    let main;
    if (!a.pairing) {
      main = `<div class="hd"><div class="lt"><div class="fl">&#9992;&#65039; Working flight</div>
        <div class="u">${s ? "No trip on your schedule." : "Waiting for Flight Watcher."}${a.next ? ` Next: ${this._e(a.next)}` : ""}</div></div></div>`;
    } else {
      // the pairings package's van (the Watcher read it for this pairing's layover) comes first, then Hark's
      const va = (this._st(`sensor.${p}_layover_van`) || {}).attributes || {};
      const pk = va.at && va.source === "package" && this._same(va.pairing, a.pairing) && va.local && va.date
        ? { local: String(va.local), date: String(va.date), wd: String(va.weekday || ""), place: String(va.place || "") } : null;
      // 1.7.11 (FW-0075): Ryan moved the Watcher's van: Hark's text still says its own time, the moved van shows
      const mv = this._moved(va, a);
      let vt = pk || (hark ? this._vanText(a, s.state) : null);
      if (vt && !pk && mv && vt.local === mv.local && vt.date === mv.date) {
        vt = { local: String(va.local || ""), date: String(va.date || ""), wd: String(va.weekday || ""), place: vt.place };
      }
      const vs = this._vanSensor(a, vt);
      // Hark gave a van the Watcher could not place: its text shows, and that no alert comes for it
      const unread = hark && !vt && String(a.van || "").trim() ? String(a.van).trim() : "";
      // on a layover (Hark's layover mode, or the Watcher's next leg out of a station that is not home) with no van:
      // the van time is not known, so no van alert comes
      const o = String(a.origin || "").toUpperCase();
      const onLay = /^[A-Z]{3}$/.test(o) && o !== "HNL" && (hark ? a.mode === "layover" : !a.status || a.status === "Scheduled");
      const unknown = !vt && !unread && onLay && !va.at;  // never while the Watcher has a van (and its alerts)
      // the package's van wins; Hark's own van text, when it says another time than the package, shows under it
      const hv = pk && hark ? this._harkVan(a, s.state) : null, pko = pk && mv ? mv : pk;
      const hsays = hv && (hv.local !== pko.local || hv.date !== pko.date) ? `Hark says ${hv.local}${hv.date !== pko.date ? ` ${hv.wd}` : ""}` : "";
      const rep = this._when("report", a, hark, w, va), dsc = this._when("dep_sched", a, hark, w, va);
      let big;
      if (vt) {
        const l = vs ? this._left(vs.at) : { t: "", c: "" };
        big = `<div class="van" data-van><div class="vl">Van</div><div class="vt">${this._e(vt.local)}</div>
          <div class="vz">${this._e(vs ? vs.abbr : "local")}${vt.wd || (vs && vs.weekday) ? ` &middot; ${this._e(vt.wd || vs.weekday)}` : ""}</div>
          ${vs ? `<div class="vh">${this._e(vs.hst)} HST ${this._e(vs.hst_weekday || "")}</div>` : ""}
          <div class="cd ${l.c}" data-cd${vs ? ` data-at="${this._e(vs.at)}"` : ""}>${this._e(l.t)}</div>
          <div class="u vsrc" data-vansrc>${pk ? "from the pairings package" : "from Hark"}</div>
          ${hsays ? `<div class="u vsrc" data-harkvan>${this._e(hsays)}</div>` : ""}</div>`;
      } else {
        const rp = this._timeParts(rep);
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
        ${a.gin_dep ? this._gin("GIN dep", a.gin_dep) : ""}${a.gin_arr ? this._gin("GIN arr", a.gin_arr) : ""}
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
      // 1.7.24: the timeout box right of the report time: beside the header's Report block, or the Report line
      const to = this._toOf(a, hark, w), toHd = !!(to && !vt), toBox = to ? this._toBox(to, a) : "";
      main = `<div class="hd${toHd ? " wt" : ""}"><div class="lt"><div class="fl">&#9992;&#65039; ${this._e(a.flight || a.pairing)} ${this._e(a.origin || "")} &rarr; ${this._e(a.dest || "")}</div>
          <div class="u">${this._e(a.pairing)}${a.leg ? ` &middot; leg ${this._e(a.leg)}` : ""}${a.date ? ` &middot; ${this._e(a.date)}` : ""}${a.tail ? ` &middot; ${this._e(a.tail)}` : ""}</div>
          ${a.mode ? `<span class="mode">${this._e(a.mode === "layover" ? `Layover ${a.origin || ""}` : a.mode)}</span>` : ""}</div>${toHd ? `<div class="rt" data-rt>${big}${toBox}</div>` : big}</div>
        ${toHd ? this._toDet(to) : ""}
        ${vt ? this._adjHtml(va, vs, mv) : ""}
        ${vt ? this._vaHtml() : ""}
        ${vt && vt.place ? `<div class="vp">&#128656; Van at ${this._e(vt.place)}${alerts.length && this._vaShown() ? ` <span class="u">&middot; alerts ${alerts.map((x) => `${x.minutes} min ${x.status === "sent" ? "&#10003;" : x.status === "pending" ? `at ${this._e(x.at_hst)} HST` : this._e(x.status)}`).join(", ")}</span>` : ""}</div>` : ""}
        ${unread ? `<div class="vp" data-vanunread>&#128656; Van: ${this._e(unread)} <span class="u">&middot; no van alert: its time could not be read for sure</span></div>` : ""}
        ${unknown ? `<div class="vp" data-vanunknown>&#128656; Van time not known: not in the pairings package and not from Hark, so no van alert comes.${!va.at && va.why ? ` <span class="u">(${this._e(va.why)})</span>` : ""}</div>` : ""}
        ${to && vt ? `<div class="tmw"><div class="tm tmr">${rep ? `<div><span class="k">Report</span> ${this._e(rep)}</div>` : ""}</div>${toBox}</div><div class="tm tms">` : `<div class="tm">${rep ? `<div><span class="k">Report</span> ${this._e(rep)}</div>` : ""}`}
          ${dep ? `<div><span class="k">Departs</span> ${this._e(dsc)}</div>` : ""}${arr ? `<div><span class="k">Arrives</span> ${this._e(a.arr_sched)}</div>` : ""}</div>${to && vt ? this._toDet(to) : ""}
        ${status}${links ? `<div class="chips">${links}</div>` : ""}${rel}${lay}`;
    }
    const city = prevCity && prevCity.dataset.touched ? prevCity.value.toUpperCase() : this._cityNow(a, hark);
    const notes = n ? this._notesHtml(n, city) : "";
    const foot = a.updated ? `<div class="u ft">Updated ${this._e(a.updated)}${a.updated_by ? ` by ${this._e(a.updated_by)}` : ""}${a.next ? ` &middot; Next: ${this._e(a.next)}` : ""}</div>` : "";
    this._body.innerHTML = `<style>
      :host{display:block} .sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
      .gin code{white-space:nowrap;display:inline-block;max-width:100%;overflow-x:auto;vertical-align:bottom}
      ha-card{padding:12px 14px;font-size:14px;line-height:1.4;color:var(--primary-text-color);overflow-wrap:anywhere}
      .u{color:var(--secondary-text-color);font-size:12px}
      .warn{color:#fff;background:#b71c1c;border-radius:6px;padding:4px 8px;margin:4px 0;font-size:12px;font-weight:600}
      .hd{display:flex;align-items:flex-start;gap:10px}.lt{flex:1;min-width:0}
      .fl{font-size:20px;font-weight:700;line-height:1.25;overflow-wrap:anywhere}
      .mode{display:inline-block;margin-top:4px;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:#fff;background:#01579b;text-transform:capitalize}
      .van{flex:none;text-align:right;min-width:104px}
      .vl{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--secondary-text-color)}
      .vt{font-size:44px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
      .vz,.vh{font-size:12px;color:var(--secondary-text-color);white-space:nowrap}.vz{font-weight:700;color:var(--primary-text-color)}
      .rep .vt{font-size:36px}.rep .vz{white-space:normal;max-width:150px;font-weight:400}
      .cd{font-size:14px;font-weight:700;margin-top:2px;color:var(--primary-text-color)}.vsrc{max-width:104px;margin-left:auto}
      .cd.soon,.cd.now{color:#fff;border-radius:6px;padding:0 6px;display:inline-block}.cd.soon{background:#8a5300}.cd.now{background:#b71c1c}
      .cd.past{color:var(--secondary-text-color);font-weight:400}
      .vp{margin:8px 0 2px;font-weight:600}
      .hd.wt{flex-wrap:wrap}.hd.wt .lt{flex:1 1 160px}.rt{flex:0 1 auto;min-width:0;max-width:100%;display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:flex-start;gap:8px;margin-left:auto}
      button.to{flex:none;display:inline-flex;flex-direction:column;align-items:flex-end;gap:1px;text-align:right;min-width:104px;min-height:44px;margin:0;padding:6px 10px;border:2px solid #c2410c;border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);font-size:14px;font-weight:700;line-height:1.15}
      button.to:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
      .to .tol{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--secondary-text-color)}
      .to .tot{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}.to .ton{white-space:nowrap}.to .tod,.to .toz{font-size:13px;font-weight:700;white-space:nowrap}
      .to .tox{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
      .to .tob{font-size:12px;font-weight:400;color:var(--secondary-text-color);max-width:136px}.to .nw{white-space:nowrap}
      .to .toh{font-size:12px;font-weight:600;color:var(--secondary-text-color);font-variant-numeric:tabular-nums;white-space:nowrap}
      .to .toq{margin-left:2px}.to .tonl{display:inline-block;font-size:18px;text-transform:uppercase;letter-spacing:.02em;color:#fff;background:#b71c1c;border-radius:4px;padding:1px 6px}
      .to .tow{font-size:12px;font-weight:700;color:#fff;background:#b71c1c;border-radius:4px;padding:0 4px}
      .tmw{display:flex;align-items:flex-start;gap:10px;margin:8px 0 2px}.tmw .tm{flex:0 1 auto;min-width:0;margin:0}.tm.tms{margin-top:2px}
      .tdet{border:2px solid #c2410c;border-radius:8px;padding:6px 10px;margin:8px 0;font-size:13px}.tdet[hidden]{display:none}.tdet .trw{margin:2px 0 6px}
      .tdet .tnl{margin:4px 0 8px}.tdet .tnlb{color:#fff;background:#b71c1c;border-radius:4px;padding:0 4px}
      @media (max-width:360px){.hd.wt .rep .vt{font-size:30px}.hd.wt .van.rep{min-width:84px}}
      .tdet details{margin:4px 0}.tdet summary{cursor:pointer;font-weight:600;padding:6px 0}.tdet ul{margin:2px 0 6px;padding-left:20px}
      .va{display:flex;flex-direction:column;align-items:flex-end;text-align:right;margin:4px 0 0}
      .vck{position:relative;display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 4px;cursor:pointer;font-weight:600}
      .vck input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
      .vck .bx{flex:none;width:20px;height:20px;box-sizing:border-box;border:2px solid var(--primary-text-color);border-radius:4px;display:inline-flex;align-items:center;justify-content:center}
      .vck input:checked+.bx{background:#01579b}.vck input:checked+.bx::after{content:"\\2713";color:#fff;font-size:14px;font-weight:800;line-height:1}
      .vck input:focus-visible+.bx{outline:2px solid var(--primary-color);outline-offset:2px}
      .vck.pend,.vck.pend input{cursor:default}.vck.pend .bx{opacity:.6}
      .vas a{display:inline-flex;align-items:center;min-height:44px}
      .vadj{display:flex;flex-direction:column;align-items:flex-end;text-align:right;gap:4px;margin:6px 0 0}
      .vab{display:flex;gap:8px;justify-content:flex-end}
      button.vbt{min-width:64px;min-height:44px;padding:0 12px;font-size:15px;font-variant-numeric:tabular-nums;background:none;color:var(--primary-text-color);border:1px solid var(--secondary-text-color)}
      button.vbt:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
      button.vbt[aria-disabled="true"]{opacity:.5;cursor:default}
      .vmv{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:4px 8px;font-size:13px;font-weight:600}
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
      @media (max-width:700px){textarea,.cl input{font-size:16px}}
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
    const vi = r.querySelector("[data-vaon]");
    if (vi && vaFocus) vi.focus({ preventScroll: true });  // a tap or Space keeps the focus on the box
    if (vi) vi.onchange = async () => {
      if (vi.getAttribute("aria-disabled") === "true") { vi.checked = !vi.checked; return; }  // waiting, or not known
      const want = vi.checked;
      this._vaWant = want; this._vaMsg = "";
      this._vaWait();
      this._render();
      try { await this._h.callService("mqtt", "publish", { topic: `${p}/van/alerts/set`, payload: want ? "ON" : "OFF" }); }
      catch (e) {
        if (this._vaT) { clearTimeout(this._vaT); this._vaT = null; }
        this._vaWant = null; this._vaSay(`Didn't send: ${(e && e.message) || "no connection"}. Try again.`); this._render();
      }
    };
    if (this._live && this._live.textContent !== (this._liveMsg || "")) this._live.textContent = this._liveMsg || "";
    const vadj = [...r.querySelectorAll("[data-vadj]")];
    if (adjFocus !== null) {  // the same button, else (Back went with its answer) the first one left: never the page
      const b = vadj.find((x) => x.getAttribute("data-vadj") === adjFocus) || vadj[0];
      if (b) b.focus({ preventScroll: true });
    }
    vadj.forEach((b) => {
      b.onclick = async () => {  // 1.7.11 (FW-0075): the absolute move, from the Watcher's; one at a time (review F1)
        if (b.getAttribute("aria-disabled") === "true" || this._adj || !this._adjVan) return;
        const d = Number(b.dataset.vadj), { lo, hi } = FW_VAN_ADJUST, van = this._adjVan;
        const want = d === 0 ? 0 : this._adjCur + d;
        if (!Number.isInteger(want) || want < lo || want > hi || want === this._adjCur) return;
        this._adj = { van, minutes: want }; this._adjMsg = ""; this._liveMsg = "Saving";
        this._adjWait();
        this._render();
        try { await this._pub("van/adjust/set", { van, minutes: want }); }
        catch (e) {
          if (this._adj && this._adj.van === van && this._adj.minutes === want) {
            if (this._adjT) { clearTimeout(this._adjT); this._adjT = null; }
            this._adj = null;
          }
          this._adjSay(`Not saved, try again (${(e && e.message) || "no connection"})`); this._render();
        }
      };
    });
    const tb = r.querySelector("[data-to]");  // 1.7.24: the timeout box opens and closes its basis
    if (tb && toFocus) tb.focus({ preventScroll: true });
    if (tb) tb.onclick = () => { this._open.to = !this._open.to; this._render(); };
    const vl = r.querySelector("[data-vaset]");
    if (vl) vl.onclick = (e) => this._go(e, vl.getAttribute("href"));
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

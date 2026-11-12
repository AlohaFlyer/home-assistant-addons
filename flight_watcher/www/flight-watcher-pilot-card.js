/* Flight Watcher: pilot schedule card (v3, Ryan 2026-11-04). v3: free-text lookup with a pick list.
   Tap a pilot's name on the pickers list or in Recently added (link #pilot=EMP) and the Watcher reads that
   pilot's current month from Tools > Schedule Lookup (read only) and publishes sensor.flight_watcher_pilot_schedule;
   this card draws it in the same calendar shape as the schedule card: Day, Date, Trip, Layover (boxed per
   trip), Block, Credit, Soft, Crew. Nothing is written to FLICA.
   1.4.8 (FW-0066): when the pilot contact list (uploaded on the Settings tab) has the looked-up pilot, the Watcher adds
   that one pilot's entry (attribute contact: name, phones, emails) and the card shows tap-to-call, tap-to-text and mail
   links beside the name, and beside the pilot's own name in the crew lists.
   1.4.11 (FW-0069): schedule versions for the looked-up pilot, M.NNN like the schedule card's. A bar under the header
   (older / newer arrows, the version, the house back to the current one, "Changes in v11.003") for the month the card
   shows; the counts come from the sensor (attribute versions), each version's days and trips from pilotver_<key>.json
   under /local/ (only the pilot on the card). The current version draws the live payload as before; an older one
   draws its own days and trips in the same grid, with the live block, credit, crew and pay.
   1.6.2 (Release A item 11): the header names the pilot asked for (never the sensor's previous one); a reply with no
   month (no match, a pick list, a wait) always shows its status line with its time (HST); a pick-list entry may carry an
   opaque pick id instead of the employee number (a pilot instance), and the number is shown only once a pilot is
   chosen; the loading line says when the Watcher reads it and gives up after 2 minutes past that, with a reason. */
const DOW = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const PILOT_EV = "flight-watcher-pilot";  // the lookup event (pickers, pilot lookup, the pick list, #pilot= links)
const PILOT_SAME_MS = 2000;  // FW-0025: the same lookup again inside 2 s is one tap heard twice, not a new request
// FW-0062: the viewer's own tax settings (the schedule card's), for the pay line's Pay-Net estimate
const TAX_HELPERS = ["input_number.flight_watcher_federal_tax_pct", "input_number.flight_watcher_state_tax_pct"];
const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
// FW-0066: only these reach a link (a tel: number of digits, an address with no space, quote or angle bracket)
const PILOT_TEL_RE = /^\+?\d{7,15}$/;
const PILOT_MAIL_RE = /^[^\s@<>"'&]+@[^\s@<>"'&]+\.[A-Za-z]{2,}$/;
const pilotNameKey = (n) => {  // 'Doe, Jane A' / 'DOE, JANE' -> 'doe,jane' (contacts._key)
  const s = String(n || "").toLowerCase().replace(/[^a-z, ]/g, "");
  if (!s.includes(",")) return "";
  const [last, first] = [s.slice(0, s.indexOf(",")), s.slice(s.indexOf(",") + 1)];
  return `${last.trim().split(/\s+/).join(" ")},${first.trim().split(/\s+/)[0] || ""}`;
};
// FW-0069: the pilot's versions file (a second pilot's copy reads its own folder: cards.pilot_copy moves this path)
const PILOTVER_URL = "/local/flight-watcher/pilotver_";
const VER_SRC = { lookup: "FLICA schedule", rebuild: "rebuilt", award: "awarded line" };
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;
const PILOT_WAIT_MS = 120000;  // 1.6.2: the loading line gives up this long after the Watcher's next check
const hstHM = (iso) => { const t = Date.parse(iso || ""); return isNaN(t) ? "" : new Date(t - 10 * 3600e3).toISOString().slice(11, 16); };

class FlightWatcherPilotCard extends HTMLElement {
  // FW-0025: HA calls setConfig more than once per card and keeps replaced card elements alive, and each call used to
  // add another window listener (never removed), so one lookup published 2 to 4 times. Now a card listens only while
  // it is on the page (one bound handler, added on connect, removed on disconnect), and one lookup publishes once
  // however many cards hear it (an editor preview, a stale copy).
  constructor() {
    super();
    this._onPilot = (e) => this._lookup(e);
  }
  setConfig(config) {
    this._config = { entity: "sensor.flight_watcher_pilot_schedule", ...config };
    this._hidden = false;
    FlightWatcherPilotCard._hook();
  }
  connectedCallback() {
    if (this._on) return;
    this._on = true;
    FlightWatcherPilotCard._live = (FlightWatcherPilotCard._live || 0) + 1;
    window.addEventListener(PILOT_EV, this._onPilot);
    FlightWatcherPilotCard._hook();
    FlightWatcherPilotCard._fromHash();  // a #pilot= link opened before this card was on the page (a deep link, another view)
  }
  disconnectedCallback() {
    if (!this._on) return;
    this._on = false;
    FlightWatcherPilotCard._live = Math.max(0, (FlightWatcherPilotCard._live || 0) - 1);
    window.removeEventListener(PILOT_EV, this._onPilot);
  }
  static _hook() {  // the #pilot=EMP[,Name] links: hooked once per page
    if (FlightWatcherPilotCard._hooked) return;
    FlightWatcherPilotCard._hooked = true;
    const fire = () => FlightWatcherPilotCard._fromHash();
    for (const ev of ["hashchange", "popstate", "location-changed"]) window.addEventListener(ev, fire);  // HA routes markdown links via pushState: location-changed
  }
  static _fromHash() {  // the link becomes one lookup event, once a card is on the page to hear it (the hash waits till then)
    if (!FlightWatcherPilotCard._live) return;
    const m = /#pilot=(\d+)(?:,([^#&]*))?/.exec(location.hash || "");
    if (!m) return;
    history.replaceState(null, "", location.pathname + location.search);
    let name = m[2] || "";
    try { name = decodeURIComponent(name); } catch (e) { /* a stray % : keep it as typed */ }
    window.dispatchEvent(new CustomEvent(PILOT_EV, { detail: { emp: m[1], name } }));
  }
  // 1.7.2 (contract 1 revision 3, F#49): what pilot/set may carry, as the portal and the Watcher check it: emp 1 to 7
  // digits, q and name one line of at most 60 code points (no control, separator or bidi character), pick 12 hex
  static _clean(d) {
    const one = (s) => Array.from(String(s == null ? "" : s).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/g, " ").trim()).slice(0, 60).join("").trim();
    const out = {}, src = d || {};
    const emp = String(src.emp == null ? "" : src.emp).replace(/[^0-9]/g, "");
    if (/^[0-9]{1,7}$/.test(emp)) out.emp = emp;
    const q = one(src.q);
    if (q) out.q = q;
    if (/^[0-9a-f]{12}$/.test(String(src.pick || ""))) out.pick = String(src.pick);
    if (src.name != null && (out.emp || out.pick)) out.name = one(src.name);
    return out;
  }
  static _first(detail) {  // true for the first card to hear a lookup; false for the same lookup again inside PILOT_SAME_MS
    const p = JSON.stringify(detail || {}), now = Date.now(), last = FlightWatcherPilotCard._sent;
    if (last && last.p === p && now - last.t >= 0 && now - last.t < PILOT_SAME_MS) return false;
    FlightWatcherPilotCard._sent = { p, t: now };
    return true;
  }
  _lookup(e) {
    const d = (e && e.detail) || {};
    this._hidden = false;
    this._want = d.emp || d.q;
    // 1.6.2: what was asked for draws the loading header (the sensor still holds the previous answer)
    const q0 = String(d.q || "").trim();
    this._ask = { emp: String(d.emp || "") || (/^\d+$/.test(q0) ? q0 : ""), name: String(d.name || ""), q: /^\d+$/.test(q0) ? "" : q0, at: Date.now() };
    if (!this._h) return;
    const q = String(d.q || "").trim();
    this._askQ = !d.emp && q && !/^\d+$/.test(q) ? q.toLowerCase() : "";  // a name: learn which pilot it found (_shows)
    const c = FlightWatcherPilotCard._clean(d);  // 1.7.2: the pilot/set shape only (contract 1 revision 3)
    if ((c.emp || c.q || c.pick) && FlightWatcherPilotCard._first(c)) this._h.callService("mqtt", "publish", { topic: "flight_watcher/pilot/set", payload: JSON.stringify(c) });
    // FW-0025: the loading line only while the reply is still to come. When the sensor already holds the answer (a
    // double tap after a quick cached reply, the same pilot asked again), draw it: HA fires no state change for an
    // identical reply, so the loading line would never clear. A stale cache still answers "loading" (a change).
    const shown = this._shows(d);
    if (shown) this._askQ = "";  // nothing to learn: the sensor already shows this name's answer
    this._paint(!shown);
    this.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  _shows(d) {  // FW-0025: does the sensor already hold the Watcher's answer to this lookup?
    const st = this._h && this._h.states && this._h.states[this._config.entity];
    const a = (st && st.attributes) || {};
    const q = String(d.q || "").trim();
    const emp = String(d.emp || "").replace(/\D/g, "") || (/^\d+$/.test(q) ? q : "");  // the Watcher reads an all-digit q as an emp
    if (emp) return String(a.emp || "") === emp;
    if (!q) return false;
    if (!a.emp) return String(a.name || "").trim().toLowerCase() === q.toLowerCase() && !!a.status;  // the pick list or "no pilot named"
    return (FlightWatcherPilotCard._qEmp || {})[q.toLowerCase()] === String(a.emp);  // one match: the pilot this name found before
  }
  set hass(h) {
    this._h = h;
    const st = h.states[this._config.entity];
    const sig = st ? st.last_updated : "";
    const tsig = TAX_HELPERS.map((e) => (h.states[e] || {}).last_updated || "").join("|");  // FW-0062: Pay-Net follows the tax settings
    if (sig === this._sig && this._root) {
      if (tsig !== this._tsig) { this._tsig = tsig; if (!this._busy) this._paint(); }
      return;
    }
    if (sig !== this._sig && st && st.attributes && st.attributes.status !== "loading") this._ask = null;  // 1.6.2: answered
    if (sig !== this._sig && this._askQ && st && st.attributes) {  // the reply to a name lookup: remember the pilot it found
      if (st.attributes.emp) (FlightWatcherPilotCard._qEmp = FlightWatcherPilotCard._qEmp || {})[this._askQ] = String(st.attributes.emp);
      this._askQ = "";
    }
    this._sig = sig;
    this._tsig = tsig;
    this._paint();
  }
  getCardSize() { return 8; }
  _recon(a, readable) {  // FW-0002: the crew index's rebuilt month, drawn in the same grid as a readable schedule
    const r = a.reconstructed || [];
    const cov = a.reconstructed_coverage_pct;
    if (!r.length) return cov != null ? `<div class="u" style="margin-top:6px">Crew index: no trips found for this pilot in ${this._esc(a.reconstructed_month || "")} yet (${this._esc(cov)}% of trips read).</div>` : "";
    const g = this._rebuild(a);
    const [y, m] = String(a.reconstructed_month || "").split("-").map(Number);
    const mon = m >= 1 && m <= 12 ? `${MONTHS[m - 1]} ${y}` : (a.reconstructed_month || "");
    const head = `<b>Reconstructed from pairing crew lists</b> <span class="u">${this._esc(mon)}${cov != null ? ` · ${this._esc(cov)}% of trips read · updated 00/06/12/18 HST` : ""}</span>`;  // 1.6.2: no coverage on a pilot
    const tot = g.items.filter((it) => it.start >= g.from);  // totals: trips in the bid period, as drawn (not the day-before row, not the overlaps below)
    const sum = (k) => { let t = 0; for (const it of tot) { const x = /^(\d+):(\d{2})$/.exec(it[k] || ""); if (!x) return "?"; t += +x[1] * 60 + +x[2]; } return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
    const md = (d) => `${MONTHS[+d.slice(5, 7) - 1].slice(0, 3)} ${+d.slice(8)}`;
    const days = (x) => (x.start === x.end ? md(x.start) : x.start.slice(0, 7) === x.end.slice(0, 7) ? `${md(x.start)}-${+x.end.slice(8)}` : `${md(x.start)}-${md(x.end)}`);
    const also = g.also.length ? `<div class="u also">Also on crew lists, on days of a trip above (one of them was likely traded after it was read): ${g.also.map((x) => `<b>${this._esc(x.pairing)}</b> ${days(x)}${x.seat ? " " + this._esc(x.seat) : ""}${x.checked_at ? ", read " + this._esc(String(x.checked_at).slice(5, 16).replace("T", " ")) : ""}${x.overlap === "reread" ? ", re-read queued" : x.overlap === "older" ? ", older read" : ""}`).join(" · ")}</div>` : "";
    const left = [g.also.length ? `+${g.also.length} overlapping` : "", g.items.length > tot.length ? `+${g.items.length - tot.length} before ${md(g.from)}` : ""].filter(Boolean);
    const src = `Source: crew lines on FLICA pairing pages (crew index, read only); Block / Credit / layover from the pairing package, else from the month's pairing file (layover from its route), blank where neither has them. A trip picked up or dropped after it was read shows as it was then.`;
    const body = !g.items.length ? "" : `${this._grid(g.days, g.items, g.month)}${also}` + (a.pay_line ? this._payLine(a.pay_line, left, md, src) :
      `<div class="tot"><span>Trips<b>${tot.length}</b>${left.length ? ` <small class="u">(${left.join(", ")}: not totaled)</small>` : ""}</span><span>Block<b>${sum("blk")}</b></span><span>Credit<b>${sum("credit")}</b></span><span class="u">${src}</span></div>`);
    return readable ? `<details class="rb"><summary>${head}</summary>${body}</details>` : `<div class="rb"><div class="rbh">${head}</div>${body}</div>`;
  }
  _payLine(pl, left, md, src) {  // FW-0062: the rebuilt month's totals and pay, in the schedule card's totals style (groups that wrap as units)
    const e = (s) => this._esc(s);
    const S = (this._h && this._h.states) || {};
    const num = (id) => { const v = parseFloat((S[id] || {}).state); return isNaN(v) ? null : v; };
    const [fed, stt] = TAX_HELPERS.map(num);
    const tax = Math.round((fed == null && stt == null ? Number(pl.tax_pct) || 0 : (fed == null ? 22 : fed) + (stt == null ? 0 : stt)) * 100) / 100;
    const m = Number(pl.trips) || 0;
    const of = (n) => (Number(n) < m ? ` <span class="k">(${e(n)} of ${e(m)})</span>` : "");
    const ti = (k, v, t) => `<span class="ti"${t ? ` title="${e(t)}"` : ""}><span class="k">${k}</span> ${v}</span>`;
    const grp = (cls, s) => (s ? `<span class="tgrp ${cls}">${s}</span>` : "");
    const ds = (x) => `${e(x.pairing)} ${/^\d{4}-\d{2}-\d{2}$/.test(x.start || "") ? md(x.start) : e(x.start)}`;
    const priced = pl.doh_known && pl.gross != null;
    const hrsG = ti("Trips", e(m)) + ti("Credit", e(pl.credit) + of(pl.credit_n)) + ti("Block", e(pl.block) + of(pl.block_n)) + ti("Soft", e(pl.soft) + of(pl.soft_n));
    const payG = priced ? ti("Pay-Gross", e(usd(pl.gross)) + (Number(pl.trips_priced) < m ? ` <span class="k">(${e(pl.trips_priced)} of ${e(m)} trips)</span>` : "")) +
      ti("Pay-Net", `${e(usd(pl.gross * (1 - tax / 100)))} <span class="k">est. at your ${e(tax)}% tax</span>`, "Pay-Gross less your federal and state tax settings (the schedule card's); an estimate") : "";
    const daysG = ti("Days Off", pl.days_off == null ? "?" : e(pl.days_off), "Bid period days with no trip on the crew lists. Reserve, training and other duty without a pairing are not on crew lists, so they count here as days off.");
    const why = `Totals over the ${m} trips that start in the bid period, as drawn.` + (!priced ? "" : ` Pay-Gross = credit x the hourly rate of the seat flown on each trip, for the pilot's longevity year from the date of hire (PWA 3.B.1; Captain PWA 3.C.4, First Officer and RO PWA 3.D.6), plus PWA 4.O.1: Captain $5.00 per block hour on a crew of 3 or more, RO $4.00, First Officer $3.00 on a 3-pilot crew, and the Extended Range +15% for an FO or RO on a 4-pilot crew or a SIN layover. Credit from the pairing package (minimums per PWA 4.C.3).`);
    let rate;
    if (pl.doh_known) {
      const seats = (pl.seats && pl.seats.length ? pl.seats : ["FO"]).map((s) => String(s).toUpperCase());
      const r = pl.seat_rates || {};
      const parts = [];
      if (seats.includes("CA") && r.CA != null) parts.push(`$${e(Number(r.CA).toFixed(2))}/cr h CA (PWA 3.C.4)`);
      if (seats.some((s) => s !== "CA") && r.FO != null) parts.push(`$${e(Number(r.FO).toFixed(2))}/cr h ${seats.includes("RO") ? "FO/RO" : "FO"} (PWA 3.D.6)`);
      rate = [`Year ${e(pl.year)}${pl.year_to ? ` to ${e(pl.year_to)}` : ""} (DOH ${e(pl.doh)})`, ...parts].join(" · ");
    } else if (pl.list_status === "not_on_list") {
      // 1.4.5: the dates of hire may come from an award packet (list_source "award YYYY-MM"); uploads are on the Settings tab
      const aw = /^award (\d{4}-\d{2})$/.exec(String(pl.list_source || ""));
      rate = aw ? `Not in the dates of hire on file (from the ${e(aw[1])} award): upload a newer award or the seniority list (Settings tab) for this pilot's pay`
        : `Not on the seniority list on file${pl.list_date ? ` (${e(pl.list_date)})` : pl.list_newest_doh ? ` (newest DOH on it ${e(pl.list_newest_doh)})` : ""}: upload a newer list (Settings tab) for this pilot's pay`;
    } else rate = "Upload the seniority list or the month's award (Settings tab) for this pilot's pay";
    const notes = [left.length ? `${left.join(", ")}: not totaled` : "",
      (pl.missing || []).length ? `No credit for ${(pl.missing || []).map(ds).join(", ")}: not priced` : "",
      (pl.no_block || []).length ? `No block for ${(pl.no_block || []).map(ds).join(", ")}: its PWA 4.O.1 override is not in Pay-Gross` : ""].filter(Boolean);
    return `<div class="ptot" title="${e(why)}">${grp("thrs", hrsG)}${grp("tpay", payG)}${grp("tdays", daysG)}</div>` +
      `<div class="u prate">${rate}</div>${notes.length ? `<div class="u prate">${notes.join(" · ")}</div>` : ""}<div class="u psrc">${src}</div>`;
  }
  _rebuild(a) {  // FW-0002: reconstructed trips -> the readable schedule's {days: [[iso, code, lay]], items} shape, plus also (overlaps)
    const ok = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d || "");
    const cmp = (u, v) => (u < v ? -1 : u > v ? 1 : 0);
    const month = /^\d{4}-\d{2}$/.test(a.reconstructed_month || "") ? a.reconstructed_month : "";
    const add = (d, n) => { const t = new Date(d + "T00:00:00Z"); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
    if (!month) return { month, from: "", days: [], items: [], also: [] };
    const [y, m] = month.split("-").map(Number);
    const from = ok(a.reconstructed_from) ? a.reconstructed_from : `${month}-01`;  // the bid period's first day
    const fd = a.month === month && Array.isArray(a.days) && a.days.length && ok((a.days[0] || [])[0]) && ok((a.days[a.days.length - 1] || [])[0]);
    let first = fd ? a.days[0][0] : add(from, -1);  // FLICA's grid starts on the day before the bid period: line up with it
    let last = fd ? a.days[a.days.length - 1][0] : ok(a.reconstructed_to) ? a.reconstructed_to : "";  // and ends on its last day (Dec 1 for November)
    // The crew index can hold two trips on the same days (a trade between reads): newest read goes in the grid, the rest in `also`
    const used = {}, trips = [], also = [];
    const all = (a.reconstructed || []).filter((x) => x && x.pairing && ok(x.start)).map((x) => ({ ...x, end: ok(x.end) && x.end >= x.start ? x.end : x.start }));
    all.sort((p, q) => cmp(q.checked_at || "", p.checked_at || "") || cmp(p.start, q.start) || cmp(p.pairing, q.pairing));
    for (const x of all) {
      const ds = []; for (let d = x.start, k = 0; d <= x.end && k < 15; d = add(d, 1), k++) ds.push(d);
      if (ds.some((d) => used[d])) { also.push(x); continue; }
      for (const d of ds) used[d] = 1;
      trips.push(x);
    }
    trips.sort((p, q) => cmp(p.start, q.start)); also.sort((p, q) => cmp(p.start, q.start) || cmp(p.pairing, q.pairing));
    if (!last) { last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10); for (const x of trips) if (x.end > last) last = x.end; }  // a publish without reconstructed_to
    for (const x of trips) { if (x.start < first) first = x.start; if (x.start > last) last = x.end; }  // never drop a trip; one running past the end stays open at the bottom, like FLICA's
    const at = {}, items = [];
    for (const x of trips) {
      const st = String(x.route || "").split("-").filter(Boolean);
      const base = st[0] || "HNL";
      const outs = [...new Set(st.filter((s) => s !== base))];
      const lay = x.start === x.end ? base : (x.lay || (outs.length === 1 ? outs[0] : ""));  // out and back: the one outstation
      for (let d = add(x.start, 1), k = 0; d <= x.end && k < 14; d = add(d, 1), k++) if (!(at[d] && at[d][0])) at[d] = ["", d === x.end ? base : "-"];
      at[x.start] = [x.pairing, lay];
      items.push({ trip: x.pairing, start: x.start, end: x.end, blk: x.blk || "", credit: x.credit || "", soft: x.soft || "", crew: x.crew || [],
        legs: st.slice(1).map((s, i) => ({ route: `${st[i]}-${s}` })), seat: x.seat || "", read: x.checked_at || "" });
    }
    const days = [];
    for (let d = first, k = 0; d <= last && k < 45; d = add(d, 1), k++) days.push([d, ...(at[d] || ["", ""])]);
    return { month, from, days, items, also };
  }
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // FW-0069: the versions file, like the schedule card's fwListFile: <PILOTVER_URL><key>.json fetched once per key|rev
  // (no-store); null until it is in, or when the sensor has no key. A failed fetch is not retried until rev changes.
  _vfile(a) {
    const key = /^[0-9a-f]{32}$/.test(String(a.versions_file_key || "")) ? a.versions_file_key : "";
    if (!key || typeof fetch !== "function") return null;
    const box = this._vf || (this._vf = {});
    const rev = a.versions_rev == null ? "" : String(a.versions_rev);
    const want = `${key}|${rev}`;
    if (box.want !== want && !box.busy) {
      box.busy = true;
      const done = (j) => { box.busy = false; box.want = want; if (j && typeof j === "object") { box.key = key; box.data = j; } };
      fetch(`${PILOTVER_URL}${key}.json?r=${encodeURIComponent(rev)}`, { cache: "no-store" })
        .then((r) => (r && r.ok ? r.json() : null))
        .then((j) => { done(j); if (this._root && !this._busy) this._paint(); })
        .catch(() => done(null));
    }
    return box.key === key ? box.data : null;
  }
  _hst(at) {  // a capture time (UTC ISO) as 'Nov 8 15:20 HST' (HST is UTC-10 all year)
    const s = String(at || "");
    const t = s ? Date.parse(/(Z|[+-]\d{2}:?\d{2})$/i.test(s) ? s : s + "Z") : NaN;
    if (isNaN(t)) return this._esc(s.slice(0, 10));
    const d = new Date(t - 10 * 3600e3), p = (n) => String(n).padStart(2, "0");
    return `${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCDate()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} HST`;
  }
  // FW-0069: the versions bar for the pilot and month the card shows: {html, rec} (rec: the older version picked, null
  // for the current one), or null when the sensor has no versions for that month (an older Watcher, a pick list)
  _vstate(a, month) {
    const emp = String(a.emp || "");
    const vs = a.versions && typeof a.versions === "object" ? a.versions : {};
    const vm = emp && month ? vs[month] : null;
    if (!vm || typeof vm !== "object") return null;
    const f = this._vfile(a);
    const p = f && typeof f === "object" ? f[emp] : null;
    const ml = p && p.months && typeof p.months === "object" ? p.months[month] : null;
    const list = (Array.isArray(ml) ? ml : []).filter((r) => r && typeof r === "object" && r.ver);
    const n = Number(vm.count) > 0 ? Math.round(Number(vm.count)) : list.length;
    if (!n) return null;
    const k = `${emp}|${month}`, last = list.length - 1;
    if (this._vsel && this._vsel.k !== k) this._vsel = null;  // a new pilot or month starts at the current version
    const s = this._vsel;
    let i = last;
    if (s) { const j = list.findIndex((r) => r.ver === s.ver && r.at === s.at); if (j >= 0) i = j; }
    const cur = i >= last, shown = i >= 0 ? list[i] : null, e = (x) => this._esc(x);
    this._vnow = { k, list, i };
    const ver = cur ? vm.current || (shown && shown.ver) || "" : shown.ver;
    const lab = cur ? `<span class="nw">${n} version${n === 1 ? "" : "s"} (current)</span>`
      : `${n} versions · viewing <span class="nw">${this._hst(shown.at)}</span> <span class="nw">(${e(VER_SRC[shown.source] || shown.source || "?")})</span>`;
    let html = `<div class="vbar"><span class="nw"><span class="vb${i <= 0 ? " off" : ""}" data-v="prev" title="Older version">&#9664;</span> <b>v${e(ver)}</b> <span class="vb${cur ? " off" : ""}" data-v="next" title="Newer version">&#9654;</span> <span class="vb${cur ? " here" : ""}" data-v="home" title="Current version">&#127968;</span></span> <span class="k">${lab}</span></div>`;
    if (shown && (!cur || !vm.current || shown.ver === vm.current)) {  // a file a rev behind the sensor: no changes list for "current"
      const chg = (Array.isArray(shown.changes) ? shown.changes : []).map(String);
      html += `<details class="chg"${this._chgOpen ? " open" : ""}><summary>Changes in v${e(shown.ver)}${shown.at ? ` (${this._hst(shown.at)})` : ""}</summary>` +
        (chg.length ? `<ul>${chg.map((c) => `<li>${e(c)}</li>`).join("")}</ul>` : "<div>No pairing changes.</div>") + "</details>";
    }
    return { html, rec: cur ? null : shown };
  }
  _vstep(d) {  // FW-0069: the arrows step older / newer and stop at the ends; the house returns to the current version
    const v = this._vnow;
    if (!v || !v.list.length) return;
    const last = v.list.length - 1;
    const i = d === "home" ? last : d === "prev" ? Math.max(0, v.i - 1) : d === "next" ? Math.min(last, v.i + 1) : v.i;
    this._vsel = i >= last ? null : { k: v.k, ver: v.list[i].ver, at: v.list[i].at };
    this._paint();
  }
  // FW-0069: an older version: its own days and trips in the same grid. A trip still on the live line (same pairing and
  // start) shows the live block, credit and crew; the totals are the version's own (FLICA's, for a lookup).
  _vold(a, rec, month) {
    const key = (it) => `${String(it.trip || "").toUpperCase()}|${it.start || ""}`;
    const live = {};
    if (a.reconstructed_month === month) for (const it of this._rebuild(a).items) live[key(it)] = it;
    if (a.month === month) for (const it of a.items || []) if (it) live[key(it)] = it;
    const items = (Array.isArray(rec.items) ? rec.items : []).filter((it) => it && it.trip && ISO_RE.test(it.start || "")).map((it) => {
      const o = { ...(live[key(it)] || {}) };
      for (const [k, v] of Object.entries(it)) if (v != null && v !== "") o[k] = v;
      if (!ISO_RE.test(o.end || "") || o.end < o.start) o.end = o.start;
      return o;
    });
    let days = (Array.isArray(rec.days) ? rec.days : []).filter((d) => Array.isArray(d) && ISO_RE.test(d[0] || ""));
    if (!days.length) days = this._rebuild({ reconstructed_month: month, reconstructed: items.map((it) => ({ pairing: it.trip, start: it.start, end: it.end, lay: it.lay })) }).days;
    const t = rec.totals && typeof rec.totals === "object" ? rec.totals : {};
    const from = `${month}-01`, to = days.length ? days[days.length - 1][0] : "";
    const trips = items.filter((it) => /^[A-Z]\d{4}/.test(it.trip) && it.start >= from && (!to || it.start <= to)).length;
    const e = (x) => this._esc(x);
    const tot = [`<span>Trips<b>${trips}</b></span>`, t.block ? `<span>Block<b>${e(t.block)}</b></span>` : "", t.credit ? `<span>Credit<b>${e(t.credit)}</b></span>` : "",
      t.days_off != null && t.days_off !== "" ? `<span>Days Off<b>${e(t.days_off)}</b></span>` : ""].join("");
    const src = rec.source === "lookup" ? `FLICA Tools > Schedule Lookup${rec.updated ? ` (FLICA updated ${e(rec.updated)})` : ""}`
      : rec.source === "rebuild" ? "rebuilt from pairing crew lists" : rec.source === "award" ? "the awarded line" : e(rec.source || "");
    return `${this._grid(days, items, month)}<div class="tot">${tot}<span class="u vnote">v${e(rec.ver)} as captured ${this._hst(rec.at)}${src ? `, ${src}` : ""}. Block / Credit per trip, crew and pay shown are the live ones.</span></div>`;
  }
  _contact(a, mini) {  // FW-0066: call / text / mail links for the looked-up pilot (attribute contact), '' when none
    const c = a && a.contact;
    if (!c || typeof c !== "object") return "";
    const out = [];
    for (const p of (Array.isArray(c.phones) ? c.phones : []).slice(0, 3)) {
      const tel = String((p && p.tel) || "");
      if (!PILOT_TEL_RE.test(tel)) continue;
      const lab = p.label && p.label !== "phone" ? ` ${this._esc(p.label)}` : "";
      const num = this._esc(p.number || tel);
      out.push(`<a class="ct" href="tel:${tel}" title="Call ${num}">Call${mini ? "" : lab}</a>`);
      if (p.label !== "home" && p.label !== "work") out.push(`<a class="ct" href="sms:${tel}" title="Text ${num}">Text${mini ? "" : lab}</a>`);  // no text to a landline
      if (mini) break;  // in a crew list: the first number only
    }
    const mails = (Array.isArray(c.emails) ? c.emails : []).map(String).filter((m) => PILOT_MAIL_RE.test(m));
    for (const m of mails.slice(0, mini ? 1 : 2)) out.push(`<a class="ct" href="mailto:${this._esc(m)}" title="Mail ${this._esc(m)}">Mail</a>`);
    return out.length ? `<span class="cts${mini ? " mini" : ""}">${out.join("")}</span>` : "";
  }
  _hol(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const nth = (mo, dow, n) => { const f = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay(); return 1 + ((dow - f + 7) % 7) + (n - 1) * 7; };
    const last = (mo, dow) => { const l = new Date(Date.UTC(y, mo, 0)); return l.getUTCDate() - ((l.getUTCDay() - dow + 7) % 7); };
    const list = [[1, 1], [1, nth(1, 1, 3)], [2, nth(2, 1, 3)], [5, last(5, 1)], [6, 19], [7, 4], [9, nth(9, 1, 1)], [10, nth(10, 1, 2)], [11, 11], [11, nth(11, 4, 4)], [12, 25]];
    return list.some(([mo, dd]) => mo === m && dd === d);
  }
  _paint(loading) {
    this._busy = !!loading;  // FW-0062: a tax setting change does not redraw over the loading line
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        ha-card{padding:10px 8px 12px;font-size:12.5px;line-height:1.25;box-sizing:border-box}
        .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 6px}
        h3{margin:0;font-size:16px}.u{font-size:11px;color:var(--secondary-text-color)}
        .x{margin-left:auto;cursor:pointer;font-size:18px;line-height:1;padding:2px 8px;border-radius:6px;color:var(--secondary-text-color)}.x:hover{background:rgba(0,0,0,.06)}
        .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
        table{border-collapse:collapse;margin:0 auto}
        .cal{border:1px solid var(--divider-color)}
        .cal td{padding:1px 6px;white-space:nowrap;vertical-align:top;border-left:1px solid var(--divider-color,#e0e0e0);border-bottom:1px solid var(--divider-color,#e0e0e0)}
        .cal th{padding:2px 6px;font-size:10.5px;font-weight:600;text-align:left;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color);border-left:1px solid var(--divider-color,#e0e0e0);white-space:nowrap}
        .cal td:first-child,.cal th:first-child,.cal td:nth-child(2){border-left:none}
        .cal td.n{text-align:right;padding-right:10px}
        .cal tr.wk td:nth-child(1),.cal tr.wk td:nth-child(2){background:#dde6f3;color:#1f2a44}
        .cal tr.hol td:nth-child(1),.cal tr.hol td:nth-child(2){background:#fff0a8;color:#4e3b00}
        .cal tr.oth td:nth-child(1),.cal tr.oth td:nth-child(2){opacity:.6}
        .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444}
        .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444}
        .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 -2px 0 #444}
        .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444,inset 0 -2px 0 #444}
        .trip{font-weight:700;color:var(--primary-color)}
        .crew{font-size:11px;color:var(--secondary-text-color)}
        .legs{font-size:10.5px;color:var(--secondary-text-color)}
        .tot{margin:6px 0 0;font-size:12px}.tot b{margin-left:4px}.tot span{margin-right:14px}
        .ptot{margin:8px 0 2px;font-size:13px;font-weight:700;text-align:center;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 16px}
        .ptot .tgrp{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 16px}.ptot .ti{white-space:nowrap}
        .ptot .k{font-weight:600;color:var(--secondary-text-color);font-size:11.5px;margin-right:3px}
        .prate{text-align:center;margin:2px 0;overflow-wrap:anywhere}.psrc{margin-top:4px}
        .none{padding:8px;color:var(--secondary-text-color)}
        .rb{margin-top:10px}.rbh{margin:0 0 4px}details.rb summary{cursor:pointer;margin:0 0 4px}.also{margin:6px 0 0}.also b{color:var(--primary-text-color)}
        .picks{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
        .cts{display:inline-flex;flex-wrap:wrap;gap:6px}.ct{padding:4px 10px;border-radius:14px;background:var(--primary-color);color:var(--text-primary-color,#fff);text-decoration:none;font-size:12px;font-weight:600;line-height:1.3}
        .cts.mini{gap:6px;margin-left:4px}.cts.mini .ct{padding:4px 8px;font-size:11px;font-weight:400;line-height:16px}
        .pk{padding:6px 10px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);cursor:pointer;font-size:13px}
        .vbar{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 14px;font-size:12px;margin:0 0 4px}.vbar .nw{white-space:nowrap}.vbar .k{color:var(--secondary-text-color);font-size:11.5px}
        .vbar .vb{cursor:pointer;padding:0 6px;color:var(--primary-color);user-select:none}.vbar .vb.here{opacity:.5}.vbar .vb.off{opacity:.3;cursor:default}
        .chg{margin:0 0 6px;font-size:11px;color:var(--secondary-text-color)}.chg summary{cursor:pointer;font-weight:600;list-style:none}.chg summary::-webkit-details-marker{display:none}
        .chg summary::before{content:"\\25B8\\a0"}.chg[open] summary::before{content:"\\25BE\\a0"}.chg ul{margin:4px 0 0;padding-left:16px}.chg li{margin:1px 0}.vnote{display:block;margin-top:2px}
        @media (prefers-color-scheme: dark){
          .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb}
          .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb}
          .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 -2px 0 #bbb}
          .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb,inset 0 -2px 0 #bbb}}
        @media (max-width:700px){ha-card{font-size:10.5px;padding:6px 3px 8px}.cal td{padding:1px 3px}.ptot{font-size:12px;gap:3px 12px}.ptot .tgrp{gap:3px 12px}.vbar{font-size:11px;column-gap:10px}.vbar .vb{font-size:12px}}
      </style><ha-card><div class="body"></div></ha-card>`;
      this._root.addEventListener("click", (e) => {
        if (e.target.closest(".x")) { this._hidden = true; this._paint(); return; }
        const vb = e.target.closest(".vb");  // FW-0069: schedule versions
        if (vb) { this._vstep(vb.dataset.v); return; }
        const pk = e.target.closest(".pk");  // 1.6.2: a pilot instance's pick list carries an opaque pick id, not the number
        if (pk) window.dispatchEvent(new CustomEvent(PILOT_EV, { detail: pk.dataset.pick ? { pick: pk.dataset.pick, name: pk.dataset.name } : { emp: pk.dataset.emp, name: pk.dataset.name } }));
      });
    }
    const body = this._root.querySelector(".body");
    const was = typeof body.querySelector === "function" ? body.querySelector("details.chg") : null;
    if (was) this._chgOpen = !!was.open;  // FW-0069: an opened changes list stays open while stepping through versions
    this._vnow = null;
    const st = this._h && this._h.states[this._config.entity];
    const a = (st && st.attributes) || {};
    if (this._hidden || (!a.emp && !a.status && !loading)) { body.innerHTML = ""; this.style.display = "none"; return; }  // v4: a "no match" or pick-list reply shows too
    this.style.display = "";
    const name = a.name || "";
    const emp = a.emp || this._want || "";
    // FW-0066: the contact belongs to the pilot the sensor holds; while a new lookup is still to answer, none is shown
    const ct = loading ? "" : this._contact(a, false);
    // the pilot's own name in a crew list: FLICA's spelling (the sensor's name) or the contact list's ('Lane Jr, Chris')
    this._ctKeys = ct ? [pilotNameKey(name), pilotNameKey(a.contact && a.contact.name)].filter(Boolean) : [];
    this._ctMini = ct ? this._contact(a, true) : "";
    if (loading || a.status === "loading") {
      body.innerHTML = this._loadingHtml(a, ct);
      return;
    }
    clearTimeout(this._waitT);
    // FW-0069: the versions bar for the month shown (FLICA's, else the crew index's rebuilt month); "" without versions
    let vs = null;
    try { vs = this._vstate(a, a.month || a.reconstructed_month || ""); } catch (err) { vs = null; this._vnow = null; }
    const vb = vs ? vs.html : "";
    let old = "";  // an older version picked: its own grid (a record the card cannot draw says so, never throws)
    if (vs && vs.rec) try { old = this._vold(a, vs.rec, a.month || a.reconstructed_month); } catch (err) { old = `<div class="none">This version could not be drawn.</div>`; }
    if (!a.month) {
      const picks = (a.matches || []).map((m) => `<button class="pk" data-emp="${this._esc(m.emp || "")}" data-pick="${this._esc(m.pick || "")}" data-name="${this._esc(m.name)}">${this._esc(m.name)} <span class="u">${this._esc(m.pos)}${m.emp ? " " + this._esc(m.emp) : ""}</span></button>`).join("");
      // 1.6.2: the header names a pilot only from the reply itself (its emp), never from an earlier lookup; a reply
      // with no pilot (no match, a pick list) names the query; the status line always shows, with its time (HST)
      const h3 = a.emp ? `${this._esc(name || "Pilot")} (${this._esc(a.emp)})` : (a.matches || []).length ? `Pick the pilot for '${this._esc(name)}'` : name ? `No pilot found for '${this._esc(name)}'` : "Pilot lookup";
      const when = hstHM(a.at || (st && st.last_updated));
      const said = /application error|customer care/i.test(a.status || "") ? "FLICA showed its error page for this schedule (often a pilot who has hidden it, or a FLICA hiccup). Nothing to read; try again later." : (a.status || "no data");
      body.innerHTML = `<div class="hd"><h3>${h3}</h3>${ct}<span class="u st">${this._esc(said)}${when ? ` (${when} HST)` : ""}</span><span class="x" title="close">&times;</span></div>${vb}${picks ? `<div class="picks">${picks}</div>` : ""}`;
      if (old) { body.insertAdjacentHTML("beforeend", old + this._recon(a, true)); return; }  // the live rebuild, folded under it
      body.insertAdjacentHTML("beforeend", this._recon(a, false));  // 0.10.1 crew index; FW-0002: in the schedule grid
      return;
    }
    const [y, m] = a.month.split("-").map(Number);
    const t = a.totals || {};
    const hd = `<div class="hd"><h3>${this._esc(name)} (${this._esc(emp)})</h3>${ct}<span class="u">${MONTHS[m - 1]} ${y} · FLICA updated ${this._esc(a.updated || "?")} · read ${a.fetched ? this._hst(a.fetched) : ""}${a.status === "cached" ? " (cached)" : ""}</span><span class="x" title="close">&times;</span></div>`;
    if (old) {  // FW-0069: an older version of a readable month
      body.innerHTML = hd + vb + old;
      body.insertAdjacentHTML("beforeend", this._recon(a, true));
      return;
    }
    body.innerHTML = `${hd}${vb}
      ${this._grid(a.days, a.items || [], a.month)}
      <div class="tot"><span>Block<b>${this._esc(t.block || "?")}</b></span><span>Credit<b>${this._esc(t.credit || "?")}</b></span><span>Days Off<b>${t.days_off != null ? t.days_off : "?"}</b></span><span class="u">Source: FLICA Tools > Schedule Lookup, read only. Block / Credit per trip from the pairing pages.</span></div>`;
    body.insertAdjacentHTML("beforeend", this._recon(a, true));  // 0.10.1: crew index (reconstructed from pairing crew lists), folded under a readable month
  }
  // 1.6.2: the loading line from what was asked (_ask), when the Watcher reads it, and a reason once it is overdue
  _loadingHtml(a, ct) {
    // 1.6.2 review: a card opened on a lookup asked earlier times it from the sensor's own 'at' (pub_pilot), not now
    const asked = Date.parse(a.at || "");
    const ask = this._ask || { emp: String(a.emp || this._want || ""), name: String(a.name || ""), q: "", at: isNaN(asked) ? Date.now() : Math.min(asked, Date.now()) };
    const h3 = ask.name ? `${this._esc(ask.name)}${ask.emp ? ` (${this._esc(ask.emp)})` : ""}` : ask.emp ? `Pilot ${this._esc(ask.emp)}` : `Looking up '${this._esc(ask.q)}'`;
    const S = (this._h && this._h.states) || {};
    const nx = Date.parse((S["sensor.flight_watcher_next_check"] || {}).state || "");
    const state = String((S["sensor.flight_watcher_state"] || {}).state || "");
    const due = Math.max(ask.at, isNaN(nx) ? ask.at : nx) + PILOT_WAIT_MS;
    // a next check already past is no time to promise
    let line = `reading this pilot's month from FLICA (Schedule Lookup, read only) on the Watcher's next check${isNaN(nx) ? ", usually under 2 minutes" : nx > Date.now() ? `, about ${hstHM(new Date(nx).toISOString())} HST` : ""}`;
    if (Date.now() > due) {
      const why = /^(paused|yielded|backoff|needs_settings|stopped)/.test(state) ? `the Watcher is ${state.replace(/_/g, " ")}; the lookup runs once it checks FLICA again` : state ? `no answer from the Watcher (it is ${state.replace(/_/g, " ")}); try again in a few minutes` : "no answer from the Watcher: it may not be running";
      line = `Still waiting after ${Math.round((Date.now() - ask.at) / 60000)} min: ${why}.`;
    } else {
      clearTimeout(this._waitT);
      this._waitT = setTimeout(() => { if (this._ask && this._root) this._paint(this._busy); }, Math.min(due - Date.now() + 500, 2147483000));
      if (this._waitT && this._waitT.unref) this._waitT.unref();  // a test's node process need not wait for it
    }
    return `<div class="hd"><h3>${h3}</h3>${ct}<span class="u st">${this._esc(line)}</span><span class="x" title="close">&times;</span></div>`;
  }
  _grid(days, items, month) {  // the calendar: one row per day, trips boxed in the Layover column (readable and rebuilt months)
    const byStart = {}; for (const it of items) byStart[it.start] = it;
    const span = (d) => items.find((it) => /^[A-Z]\d{4}/.test(it.trip) && it.start <= d && d <= it.end);
    let rows = "";
    for (const [d, code, lay] of days || []) {
      const dt = new Date(d + "T00:00:00");
      const wk = dt.getDay() === 0 || dt.getDay() === 6;
      const oth = d.slice(0, 7) !== month;
      const tr = span(d);
      const bx = tr ? " bx" + (tr.start === d ? " bxs" : "") + (tr.end === d ? " bxe" : "") : "";
      const it = byStart[d];
      let tripCell = "", layCell = "", blk = "", cr = "", soft = "", crew = "";
      if (code) {
        const read = it && it.read ? ` title="crew read ${this._esc(String(it.read).slice(5, 16).replace("T", " "))} HST"` : "";
        tripCell = /^[A-Z]\d{4}/.test(code) ? `<span class="trip"${read}>${this._esc(code)}</span>` : this._esc(code);
        if (it && it.legs && it.legs.length) {
          tripCell += ` <span class="legs" title="${this._esc(it.legs.map((l) => [l.dow, l.route, l.dep && l.arr ? `${l.dep}-${l.arr}` : "", l.blk].filter(Boolean).join(" ")).join("\n"))}">${it.legs.length} legs</span>`;
        }
        if (it && it.seat) tripCell += ` <span class="legs" title="seat on the crew list">${this._esc(it.seat)}</span>`;
      }
      if (lay && lay !== "-") layCell = lay === "HNL" ? `<span class="u">HNL</span>` : `<b>${this._esc(lay)}</b>`;
      if (it && /^[A-Z]\d{4}/.test(it.trip)) {
        blk = this._esc(it.blk || ""); cr = this._esc(it.credit || ""); soft = this._esc(it.soft || "");
        crew = (it.crew || []).map(([p, n]) => `${this._esc(p)} ${this._esc(n)}${(this._ctKeys || []).includes(pilotNameKey(n)) ? this._ctMini : ""}`).join(" · ");
      }
      rows += `<tr class="${wk ? "wk" : ""}${this._hol(d) ? " hol" : ""}${oth ? " oth" : ""}${bx}"><td>${DOW[dt.getDay()]}</td><td class="n">${d.slice(8)}</td><td>${tripCell}</td><td>${layCell}</td><td class="n">${blk}</td><td class="n">${cr}</td><td class="n">${soft}</td><td class="crew">${crew}</td></tr>`;
    }
    return `<div class="wrap"><table class="cal"><thead><tr><th></th><th></th><th>Trip</th><th>Layover</th><th>Block</th><th>Credit</th><th>Soft</th><th>Crew</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
}
customElements.define("flight-watcher-pilot-card", FlightWatcherPilotCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-card", name: "Flight Watcher pilot schedule", description: "A tapped pilot's month" });

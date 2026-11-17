// Flight Watcher finds card (0.9.4, Ryan; 1.1.1 FW-0001: month picker pinned top-right so the table gets the
// card's full width on a phone, times built from parts; FW-0005: only today's finds (HST) show, the rest of the
// month folds under "N earlier this month" in the same table, fold remembered per browser): "Recently added to the
// pot" with a month picker. A past month picked in the picker opens in full. Live rows: sensor.flight_watcher_finds;
// month history (24 months): /local/flight-watcher/finds_<YYYY-MM>_<key>.json written by the Watcher. Times HST.
// FW-0010: HA serves /local/ with no login and the files name crew, so their names carry a random key that only the
// sensor's file_key attribute (behind HA's login) tells; the card keeps the last key it saw (and this browser keeps
// it too), because HA drops the attributes while the Watcher is offline. FW-0026: the sensor keeps a short list of
// short rows (HA's recorder limit), so the month file is the full source and a sensor row only adds to it (a new
// find, a fresher pickup); the sensor's rev changes with every change to this month's or last month's file, which
// makes the card fetch the month it shows again; a sensor change inside the 60 s refetch guard schedules one refetch
// when it ends. FW-0042 (1.4.13): Comm (Hark's commute check from the pilot's own smart.json: two scheduled nonstops
// arriving HNL before report, PWA 26.QQ.2, and one home 60+ min after release; the airports that work, joined with
// "/", or No; hover for the times) and Value (credit x the pilot's rate) after Credit; both blank when the Watcher has
// no smart.json.
// 1.6.2 (Release A item 14): in the pilot portal (FW_PORTAL, turned on only in the portal's copy: portal.portal_card)
// the Key leaves out what a portal pilot does not have: the FLICA alert email and, until a row carries Comm or Value,
// the smart.json line.
// 1.7.7 (Ryan, Nov 14): in "Picked up by" only the picker (the newcomer in the find's open seat: the row's pickers, the
// employee numbers the Watcher stored; an older row without them: its open_seats and the seat before each name, none
// when that leaves it ambiguous) is the blue link to his month; a pilot already on the pairing is plain text. InFlt
// names the flight the picker was airborne on, "AS808/06NOV" (the leg's local departure date at its origin), with the
// leg and the pairing on hover; the airplane alone when the flight is not on file.
// 1.7.9 (Ryan, Nov 15): a pickup whose picker is not known shows the own in-flight verdict of each pilot it names
// (the row's inflt_named), marked "picker not known"; the names stay plain text (only a known picker is a link).
const FW_PORTAL = false;
const FW_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
class FlightWatcherFindsCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flight_watcher_finds", ...c }; this._files = {}; this._m = this._hstMonth(Date.now()); }
  getCardSize() { return 8; }
  _hstMonth(ms) { return new Date(ms - 10 * 3600e3).toISOString().slice(0, 7); }
  _hstDay(ms) { return new Date(ms - 10 * 3600e3).toISOString().slice(0, 10); }  // HST is UTC-10 all year
  // FW-0005: the "earlier this month" fold, closed until opened; remembered per browser (try/catch: private mode,
  // blocked storage). The key starts flight_watcher_, so a second pilot's copy gets a key of its own.
  _earlierOpen() {
    if (this._earlier === undefined) { let v = null; try { v = localStorage.getItem("flight_watcher_finds_earlier"); } catch (e) { v = null; } this._earlier = v === "1"; }
    return this._earlier;
  }
  _setEarlier(open) {
    if (open === this._earlierOpen()) return;
    this._earlier = open;
    try { localStorage.setItem("flight_watcher_finds_earlier", open ? "1" : "0"); } catch (e) { /* not saved, still works */ }
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    // FW-0005: the HST day is in the signature, so the first hass push after midnight HST redraws: "today" moves on
    // (and on the 1st the month) even when the finds sensor itself has not changed overnight.
    const sig = `${st ? st.last_updated : "none"}|${this._hstDay(Date.now())}`;
    if (sig === this._sig) return;
    this._sig = sig;
    // FW-0010: the files' key. HA drops the attributes while the sensor is unavailable (the Watcher offline or
    // restarting), so no key never clears the one in hand, and the browser keeps the last one for a page opened while
    // the Watcher is down. A new key (a reset /data) drops every file read under the old one.
    const fk = st && st.attributes ? st.attributes.file_key : "";
    const key = /^[0-9a-f]{32}$/.test(fk || "") ? fk : "";
    if (key) this._keepKey(key);
    const k = key || this._key || this._keptKey();
    if (k && k !== this._key) { this._key = k; this._files = {}; clearTimeout(this._later); }
    // FW-0005: left on this month, the card moves on with the clock (a past month opens in full, so a page open
    // over the month's end would otherwise show all of last month); a month picked in the picker stays.
    if (!this._picked) this._m = this._hstMonth(Date.now());
    // FW-0026: the Watcher rewrites this month's and last month's files on every check and the sensor (rev) changes
    // with them: the one shown is fetched again now, the other one when it is picked
    const cur = this._hstMonth(Date.now());
    for (const x of [cur, this._prevMonth(cur)]) {
      if (x === this._m) this._load(x, true);
      else if (this._files[x]) this._files[x].stale = true;
    }
    this._render();
  }
  _prevMonth(m) { const [y, mo] = m.split("-").map(Number); return new Date(Date.UTC(y, mo - 2, 1)).toISOString().slice(0, 7); }
  // the last file key per browser (try/catch: private mode, blocked storage); the key starts flight_watcher_, so a
  // second pilot's copy keeps his own
  _keptKey() {
    let v = "";
    try { v = localStorage.getItem("flight_watcher_finds_key") || ""; } catch (e) { v = ""; }
    return /^[0-9a-f]{32}$/.test(v) ? v : "";
  }
  _keepKey(k) {
    if (k === this._kept) return;
    this._kept = k;
    try { localStorage.setItem("flight_watcher_finds_key", k); } catch (e) { /* not kept, still works */ }
  }
  _offline() { const st = this._h && this._h.states[this._c.entity]; return !st || st.state === "unavailable"; }
  disconnectedCallback() { clearTimeout(this._later); }
  async _load(m, force) {
    const files = this._files;
    if (files[m] && !force) return;
    // FW-0010: no key known (the Watcher has never published one to this card or browser, or is offline): no fetch;
    // the card says history is not available, and the key's arrival clears this entry (set hass), which loads the file
    if (!this._key) { files[m] = { finds: [], at: 0, missing: true, nokey: true }; return; }
    if (files[m] && force) {
      const wait = 60e3 - (Date.now() - (files[m].at || 0));
      if (wait > 0) {  // FW-0026: refetch once the guard ends, so the file catches up with a sensor change made inside it
        clearTimeout(this._later);
        this._later = setTimeout(() => { if (this._m === m) this._load(m, true); }, wait + 500);
        return;
      }
    }
    // one fetch per month at a time (set hass and the first draw both ask for this month's file)
    const busy = this._busy || (this._busy = new Set()), tag = `${this._key}|${m}`;
    if (busy.has(tag)) return;
    busy.add(tag);
    let f;
    try {
      const r = await fetch(`/local/flight-watcher/finds_${m}_${encodeURIComponent(this._key)}.json?t=${Date.now()}`, { cache: "no-store" });
      f = r.ok ? { ...(await r.json()), at: Date.now() } : { finds: [], at: Date.now(), missing: true };
    } catch (e) { f = { finds: [], at: Date.now(), missing: true }; }
    busy.delete(tag);
    if (files !== this._files) return;  // the key changed while this was in flight
    files[m] = f;
    this._render();
  }
  _t(iso) {
    // 1.1.1 (FW-0001): built from parts, so every browser shows "Nov 5 12:23" (iOS Safari's
    // toLocaleString says "Nov 5 at 12:23", which widened every row); h23 keeps midnight as 00:xx.
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return this._e(iso);
    const p = {};
    for (const x of new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Honolulu", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d)) p[x.type] = x.value;
    return `${p.month} ${p.day} ${p.hour}:${p.minute}`;
  }
  _dates(f) {
    const m = String(f.dates || "").match(/^(\d{2})([A-Za-z]{3})(?:-(\d{2})([A-Za-z]{3}))?/);
    if (!m) return this._e(f.dates);
    const a = `${m[2]} ${+m[1]}`;
    if (!m[3]) return a;
    return m[4].toLowerCase() === m[2].toLowerCase() ? `${a}-${+m[3]}` : `${a}-${m[4]} ${+m[3]}`;
  }
  // 1.7.7: the employee numbers of the open-seat picker(s): the row's pickers (the Watcher's), else from its open seats
  // and the seat before each name (store.pickers_of's rule): a seat's names are its pickers when they are no more than
  // its open seats; no open seat on file: a lone FO / RO name. Anything else links nobody rather than the wrong pilot.
  _pickers(f) {
    if (Array.isArray(f.pickers)) return new Set(f.pickers.map(String));
    const parts = String(f.picked_by || "").split("; ").map((p) => ({ seat: p.split(" ")[0].toUpperCase(), emp: (p.match(/\((\d{3,7})\)\s*$/) || [])[1] }))
      .filter((p) => p.seat === "FO" || p.seat === "RO");
    const seats = String(f.open_seats || "").split(",").map((x) => x.trim().toUpperCase()).filter(Boolean);
    const out = new Set();
    if (!seats.length) { if (parts.length === 1 && parts[0].emp) out.add(parts[0].emp); return out; }
    for (const pos of ["FO", "RO"]) {
      const n = seats.filter((x) => x === pos).length, c = parts.filter((p) => p.seat === pos);
      if (n && c.length && c.length <= n) c.forEach((p) => { if (p.emp) out.add(p.emp); });
    }
    return out;
  }
  _who(f) {
    const pk = this._pickers(f);
    return String(f.picked_by || "").split("; ").map((part) => {
      const sp = part.indexOf(" ");
      const seat = sp > 0 ? part.slice(0, sp) : "", nm = sp > 0 ? part.slice(sp + 1) : part;
      const em = nm.match(/\((\d{3,7})\)\s*$/);
      // only the picker links (blue); a pilot who was already on the pairing is plain text
      if (!em || !pk.has(em[1])) return `${this._e(seat)} <span class="np">${this._e(nm)}</span>`;
      const lnk = `<a href="#pilot=${em[1]},${encodeURIComponent(nm.replace(/\s*\(\d+\)\s*$/, ""))}">${this._e(nm)}</a>`;
      return `${this._e(seat)} ${f.pickup_known ? `<b>${lnk}</b>` : lnk}`;
    }).join("; ");
  }
  // 1.7.7: "06NOV" from "2030-11-06"; "Nov 3" from "2030-11-03"
  _ddmon(iso) { const m = String(iso || "").match(/^\d{4}-(\d{2})-(\d{2})$/); return m && +m[1] >= 1 && +m[1] <= 12 ? `${m[2]}${FW_MON[+m[1] - 1].toUpperCase()}` : ""; }
  _mdy(iso) { const m = String(iso || "").match(/^\d{4}-(\d{2})-(\d{2})$/); return m && +m[1] >= 1 && +m[1] <= 12 ? `${FW_MON[+m[1] - 1]} ${+m[2]}` : ""; }
  // 1.7.7 (Ryan, Nov 14: "I want to know what flight he was flying to be certain. Add the flight number... i.e
  // AS808/06NOV and date"): the airplane, then AS<flight>/<DDMON> (the leg's local departure date at its origin); the
  // leg, its local departure and the pairing on hover; DH for a deadhead (airborne all the same). No leg on file: the
  // airplane alone, "flight not on file".
  // 1.7.7 review: a pickup gets one in-flight lookup (no new FLICA load): with two pickers the verdict is the first
  // one's, and the hover names him; a verdict from before 1.7.7 that was for the other pilot on the pairing is dropped
  // and not checked again ("-", the hover says why).
  // 1.7.9 (Ryan, Nov 15): a pickup whose open-seat picker is not known (the pot showed no open seat and it names two
  // pilots) has no verdict of its own: each pilot it names was looked up for himself (inflt_named, by employee
  // number). One line a pilot, by his seat (FO no, RO airplane AS808/06NOV, - not checked yet or not readable), his
  // name on hover, then "picker not known". Nobody becomes the picker: the names stay plain text, no link.
  _named(f) {
    const nm = f.inflt_named && typeof f.inflt_named === "object" ? f.inflt_named : null;
    if (!nm || (f.pickup_status || "") !== "filled" || this._pickers(f).size) return "";
    const lines = String(f.picked_by || "").split("; ").map((part) => {
      const em = (part.match(/\((\d{3,7})\)\s*$/) || [])[1];
      if (!em || !Object.prototype.hasOwnProperty.call(nm, em)) return "";
      const v = nm[em] && typeof nm[em] === "object" ? nm[em] : {};
      const sp = part.indexOf(" "), seat = sp > 0 ? `${part.slice(0, sp)} ` : "";
      const who = `${part.replace(/\s*\(\d+\)\s*$/, "")}: `, end = "; picker not known";
      if (v.inflt === true) return this._air(who, v.trip, v.leg, seat, end);
      const tip = v.inflt === false ? "on the ground at pickup" : "not checked (yet, or his schedule could not be read)";
      return `<span class="if" title="${this._e(`${who}${tip}${end}`)}">${this._e(seat)}${v.inflt === false ? "no" : "-"}</span>`;
    }).filter(Boolean);
    return lines.length ? `${lines.map((l) => `<div class="nk">${l}</div>`).join("")}<div class="nk pk">picker not known</div>` : "";
  }
  // the airplane and AS<flight>/<DDMON> of one in-flight verdict; nm starts the hover (whose verdict), pre the cell
  // text (a seat), end closes the hover
  _air(nm, trip, leg, pre = "", end = "") {
    const tr = String(trip || "").match(/^([A-Z]\d{4}[A-Z]?)\s+(\d{4}-\d{2}-\d{2})$/);
    const pr = tr ? ` (pairing ${tr[1]} ${this._mdy(tr[2])})` : "";
    const lg = leg && typeof leg === "object" ? leg : null;
    const flt = lg && /^\d{1,4}[A-Z]?$/.test(String(lg.flt || "")) ? `AS${lg.flt}` : "";
    const dd = lg ? this._ddmon(lg.date) : "";
    if (!flt || !dd) return `<span class="if" title="${this._e(`${nm}picked up while airborne${pr}; flight not on file${end}`)}">${this._e(pre)}<ha-icon icon="mdi:airplane"></ha-icon></span>`;
    const rt = /^[A-Z]{3}$/.test(lg.frm || "") && /^[A-Z]{3}$/.test(lg.to || "") ? ` ${lg.frm}-${lg.to}` : "";
    const dep = /^\d{2}:\d{2}$/.test(lg.dep_l || "") ? ` ${lg.dep_l}` : "";
    const tip = `${nm}picked up while airborne on ${flt}${rt}${lg.dh ? " (DH, deadhead)" : ""}, departed ${dd}${dep} local${pr}` +
      (lg.src === "package" ? "; flight from the pairings package" : "") + end;
    return `<span class="if" title="${this._e(tip)}">${this._e(pre)}<ha-icon icon="mdi:airplane"></ha-icon> ${this._e(flt)}/${this._e(dd)}</span>`;
  }
  _inflt(f) {
    const st = f.pickup_status || "";
    const named = this._named(f);
    if (named) return named;
    const nm = (() => {  // two pickers: name the one the verdict is for
      if (this._pickers(f).size < 2 || !f.inflt_emp) return "";
      const p = String(f.picked_by || "").split("; ").find((x) => x.endsWith(`(${f.inflt_emp})`));
      return p ? `${p.replace(/\s*\(\d+\)\s*$/, "")} ` : "";
    })();
    if (f.inflt === false) return nm ? `<span class="if" title="${this._e(`${nm}on the ground at pickup; the other picker not checked`)}">no</span>` : "no";
    if (f.inflt !== true && f.inflt_skip && st === "filled") return `<span class="if" title="not checked for the picker: the check before 1.7.7 looked up the other pilot on the pairing">-</span>`;
    // not looked up yet; never, when no open-seat picker with an employee number is known (blank)
    if (f.inflt !== true) return st === "filled" && f.picked_by && this._pickers(f).size ? "-" : "";
    return this._air(nm, f.inflt_trip, f.inflt_leg);
  }
  _speed(f) {
    if (f.dwell_s == null || !f.gone) return "";
    const a = +f.dwell_s, pm = +(f.dwell_pm_s || 0);
    const txt = a >= 3600 ? `${Math.floor(a / 3600)}h ${String(Math.floor(a % 3600 / 60)).padStart(2, "0")}m` : a >= 60 ? `${Math.floor(a / 60)}m ${String(a % 60).padStart(2, "0")}s` : `${a}s`;
    const pmt = pm < 5 ? "" : ` ±${pm >= 60 ? Math.floor(pm / 60) + "m" : pm + "s"}`;
    const av = f.picker_avg_s;
    const avg = av != null ? `picker avg ${av >= 60 ? Math.floor(av / 60) + "m " + String(av % 60).padStart(2, "0") + "s" : av + "s"} over ${f.picker_n} pickup${f.picker_n !== 1 ? "s" : ""}` : "";
    // 1.7.10 (Ryan, Nov 15): FLICA denied your own request for this trip because this pilot had picked it up, so he
    // asked before you did: the speed is an upper bound, capped at your request time ("at most", the sign ≤)
    const cap = f.dwell_cap ? `at most ${txt}: capped at your request time (FLICA denied your request because this pilot picked it up first)` : "";
    const tip = [cap, avg].filter(Boolean).join("; ");
    const lead = f.dwell_cap ? `<span class="cap" aria-hidden="true">≤</span>` : f.picker_approx ? "~" : "";
    return `<span title="${this._e(tip)}"${cap ? ` aria-label="${this._e(cap)}"` : ""}>${lead}${a < 60 ? `<b>${txt}</b>` : txt}<sub>${pmt}</sub></span>`;
  }
  // FW-0042: the commute result ('' blank), green when an airport works, red on No; the why on hover. A blank result
  // with a why is an unknown (the last leg's origin is not on file and only a customs release decides it): '?'.
  _comm(f) {
    const c = f.comm == null ? "" : String(f.comm);
    if (!c && !f.comm_why) return "";
    const why = [f.comm_why, f.month_rule ? `Month: ${f.month_rule}` : ""].filter(Boolean).join(" | ");
    return `<span class="cm${c ? (c === "No" ? " no" : " ok") : ""}" title="${this._e(why)}">${c ? this._e(c) : "?"}</span>`;
  }
  _value(f) {
    const v = f.value;
    if (v === "" || v == null || isNaN(Number(v))) return "";
    return `$${Math.round(Number(v)).toLocaleString("en-US")}`;
  }
  _row(f) {
    const st = f.pickup_status || "";
    let by;
    if (!f.gone) by = "still open";
    else if (st === "open") by = `<ha-icon icon="mdi:eye-off"></ha-icon> <b>Open, not in pot (hidden?)</b>${f.picked_by ? ` (${this._e(f.picked_by)})` : ""}`;
    else if (st === "unchanged") by = "left pot, same crew";
    else if (f.picked_by) by = this._who(f);
    else by = "checking";
    const inflt = this._inflt(f);
    const prem = f.prem && f.gone && st === "filled" ? `<ha-icon icon="mdi:alpha-x"></ha-icon>` : f.prem ? "X" : "";
    const lay = f.layover && !["-none-", "none"].includes(f.layover) ? this._e(f.layover) : (f.turn ? `<b>${this._e(f.turn)}</b>` : "none");
    const cls = st === "open" && f.gone ? "hid" : (f.prem && f.gone && st === "filled" ? "prem" : "");
    return `<tr class="${cls}"><td>${this._t(f.seen)}</td><td>${this._t(f.gone)}</td><td><b>${this._e(f.pairing)}</b>${f.source === "email" ? ` <ha-icon icon="mdi:email-outline"></ha-icon>` : ""}</td><td>${this._dates(f)}</td><td>${lay}</td><td class="n">${this._e(f.days)}</td><td class="n">${this._e(f.credit)}</td><td class="n">${this._value(f)}</td><td class="c">${this._comm(f)}</td><td>${this._e(f.captain)}</td><td>${by}</td><td class="c">${inflt}</td><td class="n">${this._speed(f)}</td><td class="c">${prem}</td></tr>`;
  }
  _rows() {
    const cur = this._m === this._hstMonth(Date.now());
    const file = (this._files[this._m] || {}).finds || [];
    const live = cur ? ((this._h && this._h.states[this._c.entity] || {}).attributes || {}).finds || [] : [];
    const byKey = new Map();
    for (const f of file) byKey.set(`${f.pairing}|${f.seen}`, f);
    // FW-0026: a sensor row is short (no Pickup Speed, InFlt, Prem fields), so it updates the file's row, never replaces it
    for (const f of live) if (this._hstMonth(Date.parse(f.seen)) === this._m) { const k = `${f.pairing}|${f.seen}`; byKey.set(k, { ...(byKey.get(k) || {}), ...f }); }
    return [...byKey.values()].sort((a, b) => Date.parse(b.seen) - Date.parse(a.seen));
  }
  _split(all, now) {
    // FW-0005: rows first seen today (HST calendar day) and the rest; a row without a readable time counts as earlier.
    const day = this._hstDay(now), today = [], earlier = [];
    for (const f of all) { const t = Date.parse(f.seen); (!isNaN(t) && this._hstDay(t) === day ? today : earlier).push(f); }
    return { today, earlier };
  }
  _list(all, now, loading) {
    // FW-0005 (Ryan): this month shows today's finds (HST) only; every earlier one folds under one line. A past month
    // picked in the picker has no today: picking it is the ask to see it, so its table opens in full (a fold there
    // would only repeat the header count and cost a second tap).
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [y, m] = this._m.split("-").map(Number);
    const head = `<tr><th>Seen</th><th>Picked up</th><th>Trip</th><th>Dates</th><th>Layover</th><th>Days</th><th>Credit</th><th title="Credit x your hourly rate (smart.json)">Value</th><th title="Commute: 2 nonstops arriving HNL before report (PWA 26.QQ.2) and 1 home 60+ min after release">Comm</th><th>CA</th><th>Picked up by</th><th>InFlt</th><th>Pickup Speed</th><th>Prem</th></tr>`;
    const rows = (a) => a.map((f) => this._row(f)).join("");
    if (this._m !== this._hstMonth(now)) return all.length ? `<div class="wrap"><table><thead>${head}</thead><tbody>${rows(all)}</tbody></table></div>` : (loading ? "" : `<div class="k">Nothing added in ${MON[m - 1]} ${y}.</div>`);
    const { today, earlier } = this._split(all, now);
    const d = this._hstDay(now);
    const h = today.length || loading ? "" : `<div class="k">Nothing new today (${MON[+d.slice(5, 7) - 1]} ${+d.slice(8, 10)} HST).</div>`;
    if (!today.length && !earlier.length) return h;
    // One table: today's rows and the folded ones share column widths and one sideways scroll on a phone. The fold
    // line is a row of its own (a button: tap, keyboard); the earlier rows are a tbody shown or hidden in place. With
    // nothing today the header row moves into the fold, so a closed fold is one line.
    const open = this._earlierOpen();
    const top = today.length ? `<thead>${head}</thead><tbody>${rows(today)}</tbody>` : "";
    const fold = earlier.length ? `<tbody class="fold"><tr><td colspan="14"><button type="button" class="fb" aria-expanded="${open}">${earlier.length} earlier this month</button></td></tr></tbody><tbody class="old"${open ? "" : " hidden"}>${today.length ? "" : head}${rows(earlier)}</tbody>` : "";
    return `${h}<div class="wrap"><table>${top}${fold}</table></div>`;
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const have = this._files[this._m];
    if (!have || have.stale) this._load(this._m, !!have);  // stale: kept on screen until the new file is in
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [y, m] = this._m.split("-").map(Number);
    const all = this._rows();
    const loading = !this._files[this._m];
    // FW-0010: no key, no history: say so instead of "Nothing new today" (which would be false)
    const nokey = !!(this._files[this._m] || {}).nokey, offline = this._offline();
    const off = nokey ? (offline ? "Flight Watcher offline: history not available." : "Finds history not available yet (no file key from the Watcher).")
      : offline ? "Flight Watcher offline: list as of its last check." : "";
    const openTop = this._top !== false;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 14px;font-size:12.5px}
      .hd{position:relative}.hd summary{cursor:pointer;font-weight:700;font-size:14px;padding-right:140px}
      .mp{position:absolute;top:-4px;right:0;display:flex;align-items:center;gap:4px;font-weight:700;white-space:nowrap}.mp .nv{cursor:pointer;font-size:20px;color:var(--primary-color);padding:0 6px;user-select:none}
      .wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin-top:6px}
      th,td{border:1px solid var(--divider-color);padding:4px 6px;text-align:left;white-space:nowrap}th{font-weight:700}
      td.n{text-align:right}td.c{text-align:center}
      tr.hid td{background:rgba(244,67,54,.14)}tr.prem td{background:rgba(76,175,80,.16)}
      .cm{font-weight:600}.cm.ok{color:var(--success-color,#2e7d32)}.cm.no{color:var(--error-color,#c62828)}
      a{color:var(--primary-color);text-decoration:underline}.np{color:var(--primary-text-color)}
      .if{white-space:nowrap}.nk{white-space:nowrap}.nk.pk{color:var(--secondary-text-color);font-size:11px}
      tbody.fold td{border:0;padding:0}
      .fb{position:sticky;left:0;appearance:none;-webkit-appearance:none;background:none;border:0;margin:0;padding:8px 6px 6px 0;font:inherit;font-size:13px;font-weight:600;color:var(--secondary-text-color);cursor:pointer;-webkit-tap-highlight-color:transparent}
      .fb::before{content:"\\25B6";display:inline-block;width:1.5em;font-size:.72em}.fb[aria-expanded="true"]::before{content:"\\25BC"}
      .key{margin-top:4px}.key summary{cursor:pointer;font-size:12px;color:var(--secondary-text-color)}
      .k{color:var(--secondary-text-color);font-size:12px;margin-top:6px}
      .k.off{color:var(--error-color,#c62828);font-weight:600}
      ha-icon{--mdc-icon-size:16px}
    </style><ha-card>
      <div class="hd"><details class="top"${openTop ? " open" : ""}><summary><ha-icon icon="mdi:new-box"></ha-icon> Recently added to the pot <span class="k">${nokey && !all.length ? "" : `${all.length} in ${MON[m - 1]}`}</span></summary>
        ${off ? `<div class="k off"><ha-icon icon="mdi:lan-disconnect"></ha-icon> ${off}</div>` : ""}
        ${loading ? `<div class="k">Loading ${MON[m - 1]} ${y}...</div>` : ""}
        ${this._list(all, Date.now(), loading || nokey)}
        <details class="key"><summary>Key</summary><div class="k">
          ${FW_PORTAL ? "" : `<div><ha-icon icon="mdi:email-outline"></ha-icon> caught from your FLICA alert email (gone before a pot check)</div>`}
          <div>Picked up by: the picker (blue) opens his month; a pilot who was already on the pairing is plain text.</div>
          <div>InFlt <ha-icon icon="mdi:airplane"></ha-icon> AS808/06NOV = picked up while airborne on flight AS808, which departed on 06NOV (the local date at its origin), from the picker's own trip; hover for the leg and the pairing (DH = a deadhead, airborne all the same). <ha-icon icon="mdi:airplane"></ha-icon> alone = airborne, flight not on file; no = on the ground (two pickers: the first one, hover); - = not checked (yet; hover says why when it will not be); blank = no picker known to check</div>
          <div>picker not known = the pot did not show which seat was open, so each pilot named was looked up for himself: one line a pilot by his seat (FO no, RO <ha-icon icon="mdi:airplane"></ha-icon> AS808/06NOV, - = not checked yet), his name on hover. Neither name is a link: only a known picker is.</div>
          <div>Pickup Speed = how long the trip sat in open time, ± half the check window;${FW_PORTAL ? "" : " ~ = timed from your alert email;"} ≤ = at most: capped at your own request time, when FLICA denied your request because that pilot picked the trip up first; bold under 1 min. Hover for the picker's average.</div>
          <div>Red row: seat still open but not in the pot (hidden?). Green row: Premium trip picked up.</div>
          ${FW_PORTAL && !all.some((f) => f.comm || f.value) ? "" : `<div>Comm = airports you can commute from: 2 scheduled nonstops arriving HNL before report (PWA 26.QQ.2) and 1 home 60+ min after release, same day; No = neither works; ? = not known yet (only a customs release, origin not on file, decides it). Hover for the times and the month rule. Value = credit x your hourly rate. Both blank until your smart.json is on file.</div>`}
          <div>Today's finds (HST) show; the rest of the month folds under "earlier this month" (this device remembers it open or closed). A past month opens in full. History kept 24 months.</div></div></details>
      </details>
      <span class="mp"><span class="nv" data-m="-1">&#8249;</span>${MON[m - 1]} ${y}<span class="nv" data-m="1">&#8250;</span></span></div>
    </ha-card>`;
    const r = this.shadowRoot;
    r.querySelector("details.top").ontoggle = (e) => { this._top = e.target.open; };
    const fb = r.querySelector("button.fb");
    if (fb) fb.onclick = () => {
      // in place, no redraw: the sideways scroll and the Key stay where they are
      const open = !this._earlierOpen();
      this._setEarlier(open);
      fb.setAttribute("aria-expanded", String(open));
      r.querySelector("tbody.old").hidden = !open;
    };
    r.querySelectorAll("[data-m]").forEach((el) => el.onclick = () => {
      const d = new Date(Date.UTC(y, m - 1 + Number(el.dataset.m), 1));
      const nm = d.toISOString().slice(0, 7);
      if (nm > this._hstMonth(Date.now())) return;
      this._m = nm;
      this._picked = nm !== this._hstMonth(Date.now());
      this._render();
    });
  }
}
customElements.define("flight-watcher-finds-card", FlightWatcherFindsCard);

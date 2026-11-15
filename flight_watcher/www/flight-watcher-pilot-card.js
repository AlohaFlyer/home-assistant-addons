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
   chosen; the loading line says when the Watcher reads it and gives up after 2 minutes past that, with a reason.
   1.7.7 (Ryan, Nov 14: "my schedule and other pilots schedule and reconstructed schedules should be exactly the same
   style including this latest detail panel"): another pilot's month FLICA showed, an older version of it, and the month
   reconstructed from pairing crew lists are drawn with the schedule card's own grid (the shared block below, byte for
   byte the schedule card's: day column colours, the bold blue pairing, the layover box with R and Rel times from the
   pairings package, row heights, the totals line, light and dark) and the same pairing detail (a tap on a pairing: a
   panel below the grid on a wide card, a bottom sheet on a phone). Columns: Trip, Layover, Block, Credit, Soft,
   Pay-Gross (that pilot's, priced by the Watcher from his date of hire and the seat flown, when known) and Crew. The
   seat and legs move into the pairing's hint and its detail; the source and pay notes sit under the grid. */
const DOW = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const PILOT_EV = "flight-watcher-pilot";  // the lookup event (pickers, pilot lookup, the pick list, #pilot= links)
const PILOT_SAME_MS = 2000;  // FW-0025: the same lookup again inside 2 s is one tap heard twice, not a new request
// FW-0062: the viewer's own tax settings (the schedule card's), for the pay line's Pay-Net estimate
const TAX_HELPERS = ["input_number.flight_watcher_federal_tax_pct", "input_number.flight_watcher_state_tax_pct"];
const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
// FW-0066: only these reach a link (a tel: number of digits, an address with no space, quote or angle bracket)
const PILOT_TEL_RE = /^\+?\d{7,15}$/;
const PILOT_MAIL_RE = /^[^\s@<>"'&?%#,;]+@[^\s@<>"'&?%#,;]+\.[A-Za-z]{2,}$/;  // 1.7.9 review: no mailto parameters
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
// 1.7.7: the shared pairings package files (pairings_YYYY-MM.json; cards.pilot_copy keeps them shared), the schedule card's
const PAIRINGS_URL = "/local/flight-watcher/pairings_";

// ---- shared schedule grid: keep identical in every card that holds it (tests/test_sched_grid_shared.py) ----
// 1.7.7 (Nov 14: "my schedule and other pilots schedule and reconstructed schedules should be exactly the same style
// including this latest detail panel"): one look for every month grid and one pairing detail panel, in each card that
// draws a month. FWG_CSS: the grid (sticky day and date columns, weekend and holiday colours, the trip box in the
// Layover column, the trip, R / Rel, layover and totals marks, light and dark) and the panel; .fwgf gives a grid the
// font sizes of the schedule card's ha-card. fwgHol: US and Hawaii holidays. fwgPack / fwgPackFor: the month's pairings
// package file and the one whose bid period holds a date. fwgDetail: the pairing detail model (the package's legs,
// duties, layovers and totals, else what the card read from FLICA), drawn by fwgPanelHtml (a wide card: below the grid,
// the trip's rows tr[data-d].pdh tinted) or fwgSheetHtml in an FwgSheet (a narrow card: a bottom sheet in a host the
// card never redraws). Pure: no entity ids, topics, file names or people; each card passes what it reads. The cards
// load as ES modules (import() on Home Assistant, type=module on the portal), so these names stay inside each card.
const FWG_DOW = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const FWG_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const FWG_WD = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const FWG_ISO = /^\d{4}-\d{2}-\d{2}$/;
const fwgEsc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fwgDay = (iso, n) => new Date(Date.parse(String(iso).slice(0, 10) + "T00:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const fwgWday = (iso) => new Date(String(iso).slice(0, 10) + "T00:00:00Z").getUTCDay();
const fwgDd = (iso) => `${FWG_DOW[fwgWday(iso)]} ${String(iso).slice(8, 10)}`;  // 'TH 05', FLICA's DY DD
const fwgMd = (iso) => { const mo = FWG_MON[Number(String(iso).slice(5, 7)) - 1] || ""; return `${mo.slice(0, 1)}${mo.slice(1).toLowerCase()} ${Number(String(iso).slice(8, 10)) || ""}`.trim(); };
const fwgMins = (v) => { const m = /^(\d{1,3})[h:](\d{2})$/.exec(String(v == null ? "" : v).trim()); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };
const fwgDur = (m) => (m == null || !(m >= 0) ? "" : `${Math.floor(m / 60)}:${String(Math.round(m) % 60).padStart(2, "0")}`);
const fwgHM = (v) => fwgDur(fwgMins(v));  // the package's '5h42' (or '5:42') as '5:42'
const fwgStr = (v, n) => String(v == null ? "" : v).slice(0, n || 80);
function fwgEaster(y) { // Anonymous Gregorian algorithm -> [month, day]
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, dd = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - dd - g + 15) % 30, i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, mm = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * mm + 114) / 31), day = ((h + l - 7 * mm + 114) % 31) + 1;
  return [month, day];
}
// US federal holidays (observed on the actual date) and Hawaii state holidays (Prince Kuhio Mar 26, Good Friday,
// Kamehameha Jun 11, Statehood 3rd Fri Aug): the hatched yellow day and date cells
function fwgHol(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  const nth = (mo, dow, n) => { const f = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay(); return 1 + ((dow - f + 7) % 7) + (n - 1) * 7; };
  const last = (mo, dow) => { const l = new Date(Date.UTC(y, mo, 0)); return l.getUTCDate() - ((l.getUTCDay() - dow + 7) % 7); };
  if (m === 1 && (d === 1 || d === nth(1, 1, 3))) return true;
  if (m === 2 && d === nth(2, 1, 3)) return true;
  if (m === 5 && d === last(5, 1)) return true;
  if (m === 6 && d === 19) return true;
  if (m === 7 && d === 4) return true;
  if (m === 9 && d === nth(9, 1, 1)) return true;
  if (m === 10 && d === nth(10, 1, 2)) return true;
  if (m === 11 && (d === 11 || d === nth(11, 4, 4))) return true;
  if (m === 12 && d === 25) return true;
  if (m === 3 && d === 26) return true;
  if (m === 6 && d === 11) return true;
  if (m === 8 && d === nth(8, 5, 3)) return true;
  const e = fwgEaster(y); const gf = new Date(Date.UTC(y, e[0] - 1, e[1] - 2));
  if (m === gf.getUTCMonth() + 1 && d === gf.getUTCDate()) return true;
  return false;
}
// The month's pairings package (url + 'YYYY-MM.json', the Watcher's file): box[key] is undefined until asked, null while
// it loads, false when there is none, else {key, map, start, end, dv}: map {id: {id, report, dep, release, relDays,
// firstDuty, route, credit, tafb, days (a Set of ISO dates), block, crew, det (the pairing's detail, or null)}}, start
// and end the bid period (ISO), dv the parser that wrote the file (0 before the detail came). redraw() runs once it
// settles, either way (1.7.1, F#32: a package known to be missing redraws too), outside the fetch's error path, so a
// redraw that fails never marks a package it read as missing.
function fwgPack(box, url, key, redraw) {
  if (box[key] !== undefined) return box[key];
  box[key] = null;
  fetch(`${url}${key}.json?v=1`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).then((j) => {
    if (!j) { box[key] = false; return; }
    const [y, mo] = key.split("-").map(Number);
    const nxt = new Date(Date.UTC(y, mo, 1)).toISOString().slice(0, 7);
    const prv = new Date(Date.UTC(y, mo - 2, 1)).toISOString().slice(0, 7);
    // FW-0014: a period that starts last month ("start": "2026-12-31" in January): a day from its first day up is last month's
    const sd = typeof j.start === "string" && j.start.slice(0, 7) === prv ? Number(j.start.slice(8, 10)) : 99;
    const ix = Object.fromEntries(j.cols.map((c, i) => [c, i]));
    const det = j.detail && typeof j.detail === "object" && !Array.isArray(j.detail) ? j.detail : {};
    const map = {};
    for (const r of j.rows) {
      const days = String(r[ix.days]).split(" ").filter(Boolean)
        .map((d) => (d[0] === "D" ? `${nxt}-${d.slice(1).padStart(2, "0")}` : `${Number(d) >= sd ? prv : key}-${d.padStart(2, "0")}`));
      map[r[ix.id]] = { id: r[ix.id], report: r[ix.report], dep: r[ix.dep], release: r[ix.release], relDays: r[ix.rel_days],
        firstDuty: r[ix.first_duty_min], route: r[ix.route], credit: r[ix.credit], tafb: r[ix.tafb], days: new Set(days),
        block: ix.block != null ? r[ix.block] : "", crew: ix.crew != null ? r[ix.crew] : "",
        det: Object.prototype.hasOwnProperty.call(det, r[ix.id]) ? det[r[ix.id]] : null };
    }
    const last = new Date(Date.UTC(y, mo, 0)).toISOString().slice(0, 10);
    box[key] = { key, map, start: FWG_ISO.test(j.start || "") ? j.start : `${key}-01`, end: FWG_ISO.test(j.end || "") ? j.end : last,
      dv: Number(j.dv) || 0, dcut: Number(j.dcut) || 0 };
  }).catch(() => { box[key] = false; }).then(() => redraw());
  return null;
}
// The package whose bid period holds iso (a trip's first day): that month's, else the next month's (a period that
// starts on the last day of the month before, Dec 31 in January), else the month before's; with id, the first of them
// that lists that pairing on iso, else the first whose period holds iso. null while one it needs loads.
function fwgPackFor(box, url, iso, redraw, id) {
  const ym = String(iso).slice(0, 7), [y, m] = ym.split("-").map(Number);
  let hold = false;
  for (const k of [ym, new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 7), new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 7)]) {
    const e = fwgPack(box, url, k, redraw);
    if (e === null) return null;
    if (!e || !(e.start <= iso && iso <= e.end)) continue;
    if (!id || (Object.prototype.hasOwnProperty.call(e.map, id) && e.map[id].days.has(iso))) return e;
    hold = hold || e;
  }
  return hold;
}
// "Operates": the first to the last day the package lists the pairing, and FLICA's pattern (DAILY, EXCEPT SUN,
// THU ONLY, or how many dates)
function fwgOperates(days) {
  const ds = [...(days || [])].filter((d) => FWG_ISO.test(d)).sort();
  if (!ds.length) return { range: "", pat: "" };
  const a = ds[0], b = ds[ds.length - 1], on = new Set(ds), wk = new Set(ds.map(fwgWday));
  let all = 0, every = true;
  for (let d = a; d <= b && all < 400; d = fwgDay(d, 1)) { all += 1; if (wk.has(fwgWday(d)) !== on.has(d)) every = false; }
  const pat = ds.length === 1 ? "" : ds.length === all ? "DAILY" : !every ? `${ds.length} DATES`
    : wk.size >= 4 ? "EXCEPT " + [0, 1, 2, 3, 4, 5, 6].filter((w) => !wk.has(w)).map((w) => FWG_WD[w]).join(" ")
      : [...wk].sort().map((w) => FWG_WD[w]).join(" ") + " ONLY";
  return { range: a === b ? fwgMd(a) : `${fwgMd(a)}-${fwgMd(b)}`, pat };
}
// The pairing detail model. o: {id, start (ISO), p (the package's entry when it lists this exact pairing on start,
// else null), why (why the package detail is not shown), own (what the card read from FLICA's pairing page: report,
// duties [{d, dep_l, arr_l, stn, blk}], blk, credit, soft, seat, crew; or, with no duties, plegs [{dow, flt, dps, ars,
// dep, arr, blk}] as another pilot's pairing page lists them, one duty a day), rep / rel (report and release, HST, as
// the card gives them), seat, crew ([string] or [[pos, name]]), base, notes ([string])}. Every field is text, escaped
// when drawn.
function fwgDetail(o) {
  const own = (o && o.own) || {}, p = (o && o.p) || null;
  const det = p && p.det && typeof p.det === "object" && Array.isArray(p.det.duties) ? p.det : null;
  const st = FWG_ISO.test(String(o.start || "")) ? String(o.start) : "";
  const base = fwgStr(o.base || "HNL", 4);
  const m = { id: fwgStr(o.id, 12), start: st, k: `${fwgStr(o.id, 12)}|${st}`, src: det ? "pkg" : "none", head: [], duties: [], tot: {},
    rep: fwgStr(o.rep, 40), rel: fwgStr(o.rel, 40), seat: fwgStr(o.seat || own.seat, 4).toUpperCase(), crew: [], notes: [] };
  const ops = p ? fwgOperates(p.days) : { range: "", pat: "" };
  m.head.push(["", `${m.id}${st ? ` : ${st.slice(8, 10)}${FWG_MON[Number(st.slice(5, 7)) - 1] || ""}` : ""}`]);
  if (ops.pat) m.head.push(["", ops.pat]);
  const rep = det ? det.rept : p ? p.report : own.report;
  if (rep) m.head.push(["BSE REPT", `${fwgStr(rep, 5)}L`]);
  if (ops.range) m.head.push(["Operates", ops.range]);
  if (det) m.head.push(["Base/Equip", `${base}/${fwgStr(det.eq || "", 4)}`]);
  if (det) {
    let dutyAll = 0, dutyOk = true;
    // the hotel and van are not in the shared pairing file: the pilot's own trip carries them (own.hotels, a duty each)
    const hs = Array.isArray(own.hotels) ? own.hotels : [];
    det.duties.slice(0, 12).forEach((du, i) => {
      du = du && typeof du === "object" ? du : {};
      const h = Array.isArray(hs[i]) && fwgStr(hs[i][0], 4) === fwgStr(du.stn, 4) ? hs[i] : [];
      const legs = (Array.isArray(du.legs) ? du.legs : []).slice(0, 30).map((l) => {
        const [day, dh, flt, dps, ars, depl, arrl, blk, , gr, eq] = (Array.isArray(l) ? l : []).map((x) => fwgStr(x, 8));
        const n = Number(day);
        const date = st && Number.isInteger(n) && n >= 1 && n <= 40 ? fwgDay(st, n - 1) : "";
        return { date, dd: date ? fwgDd(date) : day, dh: dh === "DH", flt, dps, ars, dep: depl, arr: arrl, blk: fwgHM(blk), grnt: fwgHM(gr), eq };
      });
      const dm = fwgMins(du.duty);
      if (dm == null) dutyOk = false; else dutyAll += dm;
      m.duties.push({ n: i + 1, dd: legs.length ? legs[0].dd : "", rept: fwgStr(du.rept, 5), legs, dend: fwgStr(du.dend, 5),
        stn: fwgStr(du.stn, 4), layo: fwgHM(du.layo), hotel: fwgStr(du.hotel || h[1], 80), van: fwgStr(du.van || h[2], 5), tblk: fwgHM(du.tblk),
        tdhd: fwgHM(du.tdhd), tcrd: fwgHM(du.tcrd), duty: fwgHM(du.duty), fdp: fwgHM(du.fdp) });
    });
    const t = det.tot && typeof det.tot === "object" ? det.tot : {};
    m.tot = { block: fwgHM(t.block), dhd: fwgHM(t.dhd), credit: fwgHM(t.credit), tafb: fwgHM(t.tafb), rig: fwgHM(t.rig),
      rigC: !!t.rig_c, fdp: fwgHM(t.fdp), duty: dutyOk && m.duties.length ? fwgDur(dutyAll) : "", dend: m.duties.length ? m.duties[m.duties.length - 1].dend : "" };
  } else {
    const ds = Array.isArray(own.duties) ? own.duties.slice(0, 12) : [];
    const ol = ds.length || !Array.isArray(own.plegs) ? [] : own.plegs.slice(0, 30);
    if (ds.length || own.report || own.blk || own.credit) m.src = "own";
    if (!ds.length && ol.length) m.src = "legs";
    let at = st, cur = null;
    ol.forEach((l) => {  // each leg on the first day from the last one on whose weekday is its own; a duty a day
      l = l && typeof l === "object" ? l : {};
      const w = FWG_DOW.indexOf(fwgStr(l.dow, 2).toUpperCase());
      let date = "";
      for (let k = 0; at && w >= 0 && k < 7 && !date; k++) if (fwgWday(fwgDay(at, k)) === w) date = fwgDay(at, k);
      if (date) at = date;
      const leg = { date, dd: date ? fwgDd(date) : fwgStr(l.dow, 2).toUpperCase(), dh: false, flt: fwgStr(l.flt, 6),
        dps: fwgStr(l.dps, 4), ars: fwgStr(l.ars, 4), dep: fwgStr(l.dep, 5), arr: fwgStr(l.arr, 5), blk: fwgHM(l.blk), grnt: "", eq: "" };
      if (!cur || cur.dd !== leg.dd) {
        if (m.duties.length >= 12) return;
        cur = { n: m.duties.length + 1, dd: leg.dd, rept: m.duties.length ? "" : fwgStr(own.report, 5), legs: [], dend: "", stn: "",
          layo: "", hotel: "", van: "", tblk: "", tdhd: "", tcrd: "", duty: "", fdp: "", bm: 0 };
        m.duties.push(cur);
      }
      cur.legs.push(leg); cur.stn = leg.ars;
      const b = fwgMins(l.blk); cur.bm = cur.bm == null || b == null ? null : cur.bm + b; cur.tblk = fwgDur(cur.bm);
    });
    for (const du of m.duties) delete du.bm;
    ds.forEach((du, i) => {
      du = du && typeof du === "object" ? du : {};
      const date = st && Number.isInteger(du.d) && du.d >= 0 && du.d < 40 ? fwgDay(st, du.d) : "";
      const blk = Number.isFinite(du.blk) ? fwgDur(du.blk) : "";
      m.duties.push({ n: i + 1, dd: date ? fwgDd(date) : "", rept: i === 0 ? fwgStr(own.report, 5) : "",
        legs: [{ date, dd: date ? fwgDd(date) : "", dh: false, flt: "", dps: "", ars: fwgStr(du.stn, 4), dep: fwgStr(du.dep_l, 5), arr: fwgStr(du.arr_l, 5), blk, grnt: "", eq: "", sum: true }],
        dend: "", stn: fwgStr(du.stn, 4), layo: "", hotel: "", van: "", tblk: blk, tdhd: "", tcrd: "", duty: "", fdp: "" });
    });
    m.tot = { block: fwgHM(own.blk), credit: fwgHM(own.credit), soft: fwgHM(own.soft) };
  }
  m.crew = (Array.isArray(o.crew) ? o.crew : Array.isArray(own.crew) ? own.crew : []).slice(0, 12).map((c) => {
    if (Array.isArray(c)) return fwgStr(`${c[0] || ""} ${c[1] || ""}`.trim(), 60);
    const s = fwgStr(c, 60), mm = /^([A-Z]{2,3})\s+(.+?)\s*\((\d{3,7})\)\s*$/.exec(s);
    return mm ? `${mm[1]} ${mm[3]} ${mm[2]}` : s;
  }).filter(Boolean);
  if (o.why) m.notes.push(fwgStr(o.why, 300));
  for (const n of (Array.isArray(o.notes) ? o.notes : []).slice(0, 4)) m.notes.push(fwgStr(n, 300));
  return m;
}
const FWG_SRC = { pkg: "From the pairings package: local times (L) at each station, as the package prints them (HNL = HST). TDHD and FDP are figured from its GMT columns: FDP runs from report to the last flight's block-in (FAR 117.3); a deadhead after it is duty, not FDP.",
  own: "From FLICA's pairing page: each duty's first departure to its last arrival, local times.",
  legs: "From FLICA's pairing page: each leg's departure and arrival as the page shows them (local times), a duty a day.", none: "" };
const fwgRig = (t) => (t.rig ? `${t.rig}${t.rigC ? " (credit less the legs' credit)" : ""}` : "");
// wide: a FLICA style printout below the grid (role region, labelled by its title; the close button is .pdx)
function fwgPanelHtml(m) {
  const e = fwgEsc, cols = ["DY DD", "DH", "FLTNO", "DPS-ARS", "DEPL", "ARRL", "BLKT", "GRNT", "TBLK", "TDHD", "TCRD", "TDUTY/FDP", "LAYOVER"];
  const head = m.head.map(([k, v], i) => (i === 0 ? `<h4 id="fwgpt">${e(v)}</h4>` : `<span>${k ? `<span class="k">${e(k)}:</span> ` : ""}${e(v)}</span>`)).join("");
  let rows = "";
  m.duties.forEach((du, i) => {
    du.legs.forEach((l, j) => {
      const end = j === du.legs.length - 1;
      rows += `<tr class="lg${l.dh ? " dh" : ""}"><td>${e(l.dd)}</td><td>${l.dh ? "DH" : ""}</td><td>${l.sum ? "Duty" : e(l.flt)}</td><td>${l.sum ? `to ${e(l.ars)}` : `${e(l.dps)}-${e(l.ars)}`}</td>` +
        `<td class="r">${e(l.dep)}</td><td class="r">${e(l.arr)}</td><td class="r">${e(l.blk)}</td><td class="r">${e(l.grnt)}</td>` +
        (end ? `<td class="r">${e(du.tblk)}</td><td class="r">${e(du.tdhd)}</td><td class="r">${e(du.tcrd)}</td><td class="r">${e(du.duty)}${du.fdp ? "/" + e(du.fdp) : ""}</td><td>${du.layo ? `${e(du.stn)} ${e(du.layo)}` : ""}</td>`
          : "<td></td><td></td><td></td><td></td><td></td>") + "</tr>";
    });
    const nx = m.duties[i + 1];
    const bits = [du.dend ? `D-END: ${e(du.dend)}L` : "", nx && nx.rept ? `<b>REPT: ${e(nx.rept)}L</b>` : "",
      du.hotel ? `<b>${e(du.hotel)}</b>` : "", du.van ? `VAN ${e(du.van)}L` : ""].filter(Boolean);
    if (bits.length && i < m.duties.length - 1) rows += `<tr class="de"><td colspan="13">${bits.join(" &nbsp; ")}</td></tr>`;
  });
  const t = m.tot;
  const foot = m.src === "pkg" ? `<tr class="ft"><td colspan="8">Total</td><td class="r">${e(t.block)}</td><td class="r">${e(t.dhd)}</td><td class="r">${e(t.credit)}</td><td class="r">${e(t.duty)}${t.fdp ? "/" + e(t.fdp) : ""}</td><td></td></tr>` : "";
  const sum = [t.dend ? `D-END: ${e(t.dend)}L` : "", t.tafb ? `T.A.F.B.: ${e(t.tafb)}` : "", t.rig ? `TRIP RIG: ${e(fwgRig(t))}` : "",
    m.src !== "pkg" && t.block ? `Block ${e(t.block)}` : "", m.src !== "pkg" && t.credit ? `Credit ${e(t.credit)}` : "", m.src !== "pkg" && t.soft ? `Soft ${e(t.soft)}` : "",
    m.rep ? `Report ${e(m.rep)} HST` : "", m.rel ? `Release ${e(m.rel)} HST` : ""].filter(Boolean);
  return `<div class="fwgp" role="region" aria-labelledby="fwgpt"><div class="fwgph">${head}<button type="button" class="pdx" aria-label="Close the pairing detail">&#10005;</button></div>` +
    (m.duties.length ? `<div class="fwgpw"><table class="fwgpt"><thead><tr>${cols.map((c, i) => `<th${i >= 4 && i <= 11 ? ' class="r"' : ""}>${c}</th>`).join("")}</tr></thead><tbody>${rows}</tbody>${foot ? `<tfoot>${foot}</tfoot>` : ""}</table></div>` : "") +
    (sum.length ? `<div class="fwgpl">${sum.join(" &nbsp; ")}</div>` : "") +
    (m.crew.length || m.seat ? `<div class="fwgpl">${m.crew.length ? `<span class="k">Crew:</span> ${m.crew.map(e).join(" &nbsp; ")}` : ""}${m.seat ? `${m.crew.length ? " &nbsp; " : ""}<span class="k">Seat:</span> ${e(m.seat)}` : ""}</div>` : "") +
    m.notes.map((n) => `<div class="fwgpn">${e(n)}</div>`).join("") + (FWG_SRC[m.src] ? `<div class="fwgpn">${e(FWG_SRC[m.src])}</div>` : "") + "</div>";
}
// narrow: the same detail as stacked lines for the bottom sheet ("900 HNL-SEA 23:00-06:42 blk 5:42"); the header
// (.fwgsh) is the sheet's drag area, its title labels the dialog
function fwgSheetHtml(m) {
  const e = fwgEsc, t = m.tot;
  const meta = m.head.slice(1).map(([k, v]) => (k ? `${e(k)} ${e(v)}` : e(v))).join(" · ");
  const duties = m.duties.map((du, i) => {
    const nx = m.duties[i + 1];
    const legs = du.legs.map((l) => `<div class="fwgsl${l.dh ? " dh" : ""}">${l.sum ? `Duty to ${e(l.ars)}` : `${l.dh ? "DH " : ""}${e(l.flt)} ${e(l.dps)}-${e(l.ars)}`} ${e(l.dep)}-${e(l.arr)}${l.blk ? ` blk ${e(l.blk)}` : ""}${l.grnt ? ` · grnd ${e(l.grnt)}` : ""}</div>`).join("");
    const end = [du.dend ? `D-END ${e(du.dend)}L` : "", du.duty ? `duty ${e(du.duty)}` : "", du.fdp ? `FDP ${e(du.fdp)}` : "",
      du.tblk && !du.legs.every((l) => l.sum) ? `block ${e(du.tblk)}` : "", du.tdhd ? `DH ${e(du.tdhd)}` : "", du.tcrd ? `credit ${e(du.tcrd)}` : ""].filter(Boolean).join(" · ");
    const lay = i < m.duties.length - 1 && (du.layo || du.hotel || du.van) ? [du.layo ? `<b>${e(du.stn)} ${e(du.layo)}</b>` : `<b>${e(du.stn)}</b>`, du.hotel ? e(du.hotel) : "", du.van ? `VAN ${e(du.van)}L` : "", nx && nx.rept ? `REPT ${e(nx.rept)}L` : ""].filter(Boolean).join(" · ") : "";
    return `<div class="fwgsd"><div class="fwgsdh">${e(du.dd)}${du.rept ? ` · Report ${e(du.rept)}L` : ""}</div>${legs}${end ? `<div class="fwgse">${end}</div>` : ""}${lay ? `<div class="fwgso">${lay}</div>` : ""}</div>`;
  }).join("");
  const tot = [t.block ? `Block ${e(t.block)}` : "", t.dhd && t.dhd !== "0:00" ? `DH ${e(t.dhd)}` : "", t.credit ? `Credit ${e(t.credit)}` : "", t.soft ? `Soft ${e(t.soft)}` : "",
    t.tafb ? `TAFB ${e(t.tafb)}` : "", t.rig ? `Trip rig ${e(fwgRig(t))}` : "", t.duty || t.fdp ? `Duty/FDP ${e(t.duty)}/${e(t.fdp)}` : "",
    m.rep ? `Report ${e(m.rep)} HST` : "", m.rel ? `Release ${e(m.rel)} HST` : ""].filter(Boolean).join(" · ");
  return `<div class="fwgs"><div class="fwgsh"><h4 id="fwgst">${e(m.head[0] ? m.head[0][1] : m.id)}</h4><span class="sp"></span><button type="button" class="pdx" aria-label="Close the pairing detail">&#10005;</button></div>` +
    (meta ? `<div class="fwgsm">${meta}</div>` : "") + duties + (tot ? `<div class="fwgstot">${tot}</div>` : "") +
    (m.crew.length || m.seat ? `<div class="fwgsc">${m.crew.length ? `Crew: ${m.crew.map(e).join(" · ")}` : ""}${m.seat ? `${m.crew.length ? " · " : ""}Seat ${e(m.seat)}` : ""}</div>` : "") +
    m.notes.map((n) => `<div class="fwgsn">${e(n)}</div>`).join("") + (FWG_SRC[m.src] ? `<div class="fwgsn">${e(FWG_SRC[m.src])}</div>` : "") + "</div>";
}
// narrow = a phone (a viewport 700 px wide or less, the grid's own breakpoint) or a card under 560 px
const fwgNarrow = (hc) => { const vw = (typeof innerWidth === "number" && innerWidth) || 0; const w = hc && hc.getBoundingClientRect ? hc.getBoundingClientRect().width : 0;
  return (vw > 0 && vw <= 700) || (w > 0 && w < 560); };
// The narrow card's bottom sheet: built once in host, an element of the card's shadow root that its redraws never
// write, so a Watcher update keeps its scroll, its drag and the focus. show(k, sig, html) writes the content only when
// sig changes (back to the top for another pairing); a drag down on the handle or the header past 80 px calls
// onClose(); the card closes it on the backdrop (.fwsb), the close button (.pdx) and Esc, and keeps Tab inside (trap).
class FwgSheet {
  constructor(host, onClose) {
    this.host = host; this.onClose = onClose; this.k = null; this.sig = null; this.y0 = null; this.dy = 0;
    host.hidden = true;
    host.innerHTML = '<div class="fwsb"></div><div class="fwss" role="dialog" aria-modal="true" aria-labelledby="fwgst" tabindex="-1">' +
      '<div class="fwsg"><span class="fwsk"></span></div><div class="fwsc"></div></div>';
    this.box = host.querySelector(".fwss"); this.body = host.querySelector(".fwsc");
    this.box.addEventListener("pointerdown", (ev) => {
      if (this.y0 != null || !ev.target.closest(".fwsg, .fwgsh") || ev.target.closest("button, a")) return;
      this.y0 = ev.clientY; this.dy = 0; this.pid = ev.pointerId;
      try { this.box.setPointerCapture(ev.pointerId); } catch (x) { /* an old browser: the drag still works while over the sheet */ }
      this.box.style.transition = "none";
    });
    this.box.addEventListener("pointermove", (ev) => {
      if (this.y0 == null || ev.pointerId !== this.pid) return;
      this.dy = Math.max(0, ev.clientY - this.y0); this.box.style.transform = this.dy ? `translateY(${this.dy}px)` : "";
    });
    const up = (ev) => {
      if (this.y0 == null || ev.pointerId !== this.pid) return;
      const dy = this.dy; this.y0 = null; this.dy = 0; this.box.style.transition = ""; this.box.style.transform = "";
      if (ev.type === "pointerup" && dy > 80) this.onClose("drag");
    };
    this.box.addEventListener("pointerup", up); this.box.addEventListener("pointercancel", up);
  }
  get open() { return !this.host.hidden; }
  show(k, sig, html) {
    if (sig !== this.sig) { this.body.innerHTML = html; this.sig = sig; if (k !== this.k) this.body.scrollTop = 0; this.k = k; }
    if (this.host.hidden) {
      this.host.hidden = false; void this.box.offsetHeight; this.host.classList.add("on");
      const b = this.body.querySelector(".pdx"); (b || this.box).focus({ preventScroll: true });
    }
  }
  hide() {
    if (this.host.hidden) return;
    this.host.classList.remove("on"); this.host.hidden = true; this.body.innerHTML = ""; this.k = null; this.sig = null;
    this.y0 = null; this.box.style.transform = ""; this.box.style.transition = "";
  }
  trap(ev) {
    if (this.host.hidden || ev.key !== "Tab") return;
    const f = [...this.host.querySelectorAll("button, a[href]")], a = this.host.getRootNode().activeElement, i = f.indexOf(a);
    if (!f.length) { ev.preventDefault(); this.box.focus(); return; }
    if (i < 0 || (ev.shiftKey ? i === 0 : i === f.length - 1)) { ev.preventDefault(); f[ev.shiftKey ? f.length - 1 : 0].focus(); }
  }
}
const FWG_CSS = `
      :host([dark]){--fw-ok:#81c784;--fw-err:#ef9a9a;--fw-warn:#ffb74d;--fw-info:#90caf9}
      :host{--fwg-hl:rgba(0,116,200,.13)}:host([dark]){--fwg-hl:rgba(120,180,255,.2)}
      .fwgf{font-size:12.5px;line-height:1.25}
      .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
      .cal td:nth-child(1),.cal td:nth-child(2),.cal th:nth-child(1),.cal th:nth-child(2){position:sticky;background:var(--card-background-color,#fff);z-index:1}
      .cal td:nth-child(1),.cal th:nth-child(1){left:0}.cal td:nth-child(2),.cal th:nth-child(2){left:34px}
      .cal th{background:var(--card-background-color,#fff)}
      @media (max-width:700px){.fwgf{font-size:10.5px}.cal td{padding:1px 3px}
        .cal td:nth-child(1),.cal th:nth-child(1){position:static}.cal td:nth-child(2),.cal th:nth-child(2){left:0;border-left:none}}
      .frame{width:fit-content;max-width:100%;margin:0 auto}
      .u{font-size:11px;color:var(--secondary-text-color)}
      .cal{border-collapse:collapse;margin:0 auto}
      .cal{border:1px solid var(--divider-color)}
      .cal td{padding:1px 6px;white-space:nowrap;vertical-align:top;border-left:1px solid var(--divider-color,#e0e0e0);border-bottom:1px solid var(--divider-color,#e0e0e0)}
      .cal th{border-left:1px solid var(--divider-color,#e0e0e0)}.cal td:first-child,.cal th:first-child{border-left:none}
      .cal td:nth-child(2){border-left:none}
      .cal th{padding:2px 6px;font-size:10.5px;font-weight:600;text-align:left;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color);white-space:nowrap}
      .cal td.t{text-align:right;font-size:11px}
      .cal td.n{text-align:right;padding-right:10px}
      .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444}
      .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444}
      .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 -2px 0 #444}
      .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444,inset 0 -2px 0 #444}
      .cal tr.wk td:nth-child(1),.cal tr.wk td:nth-child(2){background:#dde6f3;color:#1f2a44}
      .cal tr.hol td:nth-child(1),.cal tr.hol td:nth-child(2){background:#fff0a8;color:#4e3b00}
      .cal tr.hol2 td:nth-child(1),.cal tr.hol2 td:nth-child(2){background:#fff0a8;color:#4e3b00;background-image:repeating-linear-gradient(135deg,transparent 0 5px,rgba(0,0,0,.06) 5px 7px)}
      :host([dark]) .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb}
      :host([dark]) .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb}
      :host([dark]) .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 -2px 0 #bbb}
      :host([dark]) .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb,inset 0 -2px 0 #bbb}
      .cal tr.oth td{color:var(--secondary-text-color)}
      .trip{color:var(--primary-color);font-weight:600}
      .vac{font-weight:600}
      .cal tr.vac[data-d] td.n::after{content:" \\2298";color:#e53935;font-weight:700;opacity:.8}
      .payp{font-weight:600;color:var(--fw-info,#1565c0)}
      .tm{font-size:10.5px;color:var(--secondary-text-color)}
      .tag{cursor:help}.lay{display:inline-block;min-width:28px}
      .st{color:var(--fw-ok,#2e7d32);font-weight:700;cursor:help}.st.fly{color:var(--fw-info,#1565c0)}
      .tot{margin-top:8px;font-size:14px;font-weight:700;text-align:center;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px}.tot .tgrp{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px}.tot .tpay{flex-wrap:nowrap}.tot .ti{white-space:nowrap}.tot .k{font-weight:600;color:var(--secondary-text-color);font-size:12px;margin-right:4px}.tot .bad{color:var(--fw-err,#c62828)}
      .trip[data-k]{cursor:pointer}.trip[aria-expanded="true"]{text-decoration:underline;text-underline-offset:2px}
      .trip:focus-visible,.pdx:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px;border-radius:3px}.fwss .pdx:focus-visible{outline-offset:-3px}
      .cal tr.pdh[data-d] td:nth-child(n){background-image:linear-gradient(var(--fwg-hl),var(--fwg-hl))}
      .cal tr.pdh.hol2[data-d] td:nth-child(-n+2){background-image:linear-gradient(var(--fwg-hl),var(--fwg-hl)),repeating-linear-gradient(135deg,transparent 0 5px,rgba(0,0,0,.06) 5px 7px)}
      .fwgp{margin:8px 0 2px;padding:6px 8px 8px;border:1px solid var(--divider-color,#ccc);border-radius:8px;max-width:100%;box-sizing:border-box;text-align:left;font-size:12px;line-height:1.3;scroll-margin:12px}
      .fwgph{display:flex;flex-wrap:wrap;align-items:center;gap:2px 14px;margin:0 0 4px}.fwgph h4{margin:0;font-size:14px;color:var(--primary-color)}
      .fwgp .k,.fwgs .k{color:var(--secondary-text-color);font-weight:600}
      .pdx{margin-left:auto;min-width:44px;min-height:44px;padding:0 10px;border:0;border-radius:8px;background:transparent;color:var(--primary-text-color);font:inherit;font-size:18px;line-height:1;cursor:pointer}.pdx:hover{background:rgba(127,127,127,.15)}
      .fwgpw{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
      .fwgpt{border-collapse:collapse;margin:0;font-size:11.5px;font-variant-numeric:tabular-nums}
      .fwgpt th{padding:2px 6px;font-size:10px;font-weight:600;text-align:left;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color,#e0e0e0);white-space:nowrap}
      .fwgpt td{padding:1px 6px;white-space:nowrap;vertical-align:top}.fwgpt .r{text-align:right}
      .fwgpt tr.dh td{color:var(--secondary-text-color);font-style:italic}
      .fwgpt tr.de td{padding:0 6px 5px;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color,#e0e0e0);white-space:normal}.fwgpt tr.de b{color:var(--primary-text-color)}
      .fwgpt tr.ft td{padding-top:3px;font-weight:700}
      .fwgpl{margin-top:5px}.fwgpn{margin-top:4px;font-size:11px;color:var(--secondary-text-color)}
      .fwm{display:contents}.fwsh[hidden]{display:none}
      .fwsb{position:fixed;left:0;top:0;right:0;bottom:0;z-index:7;background:rgba(0,0,0,.35);touch-action:none}
      .fwss{position:fixed;left:0;right:0;bottom:0;z-index:8;margin:0 auto;max-width:640px;height:60vh;height:60dvh;max-height:calc(100vh - 40px);display:flex;flex-direction:column;box-sizing:border-box;padding:0 12px calc(12px + env(safe-area-inset-bottom,0px));background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121);border-radius:14px 14px 0 0;box-shadow:0 -6px 24px rgba(0,0,0,.35);transform:translateY(105%);transition:transform .22s ease-out;font-size:13px;line-height:1.35;outline:none}
      .fwsh.on .fwss{transform:translateY(0)}
      .fwsg{flex:none;display:flex;justify-content:center;padding:8px 0 6px;cursor:grab;touch-action:none}.fwsk{width:40px;height:5px;border-radius:3px;background:var(--secondary-text-color,#888);opacity:.6}
      .fwsc{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
      .fwgs{font-variant-numeric:tabular-nums}
      .fwgsh{display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:1;background:var(--card-background-color,#fff);touch-action:none;cursor:grab}.fwgsh h4{margin:0;font-size:16px;color:var(--primary-color)}.fwgsh .sp{flex:1}
      .fwgsm{margin:0 0 6px;font-size:12px;color:var(--secondary-text-color)}
      .fwgsd{padding:5px 0 6px;border-top:1px solid var(--divider-color,#e0e0e0)}.fwgsdh{font-weight:700;margin-bottom:2px}
      .fwgsl{padding:1px 0 1px 8px}.fwgsl.dh{color:var(--secondary-text-color);font-style:italic}
      .fwgse,.fwgso{padding-left:8px;font-size:12px;color:var(--secondary-text-color)}.fwgso b{color:var(--primary-text-color)}
      .fwgstot{padding:6px 0 2px;border-top:1px solid var(--divider-color,#e0e0e0);font-weight:600}
      .fwgsc{margin-top:4px;font-size:12px}.fwgsn{margin-top:4px;font-size:11.5px;color:var(--secondary-text-color)}
      @media (prefers-reduced-motion: reduce){.fwss{transition:none}}
`;
// ---- end shared schedule grid ----
// 1.7.7: FLICA's pairing page writes times as '0830' and block as '0530'; the grid writes '08:30' and '5:30'
const pcHM = (s) => { const t = String(s == null ? "" : s).trim(); return /^\d{4}$/.test(t) ? `${t.slice(0, 2)}:${t.slice(2)}` : t; };
const pcDur = (s) => { const t = String(s == null ? "" : s).trim(); return /^\d{3,4}$/.test(t) ? `${Number(t.slice(0, -2))}:${t.slice(-2)}` : fwgHM(t) || t; };
const pcMin = (hm) => { const m = /^(\d{1,2}):(\d{2})$/.exec(String(hm || "")); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };
const pcClock = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const PC_WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const PC_SEAT_SRC = { "pairing page": "the pairing page's crew line", "crew index": "the crew index", "seniority list": "the seniority list", assumed: "assumed FO" };
// The card's own look around the shared grid (FWG_CSS): the header, the lookup, the versions bar and the notes; the
// schedule card's ha-card, table and number column rules where the grid needs them
const PILOT_CSS = `
      ha-card{padding:10px 8px 12px;font-size:12.5px;line-height:1.25;box-sizing:border-box}
      @media (max-width:700px){ha-card{font-size:10.5px;padding:6px 3px 8px}}
      div.hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 6px}
      h3{margin:0;font-size:16px}
      .x{margin-left:auto;cursor:pointer;font-size:18px;line-height:1;padding:2px 8px;border-radius:6px;color:var(--secondary-text-color)}.x:hover{background:rgba(0,0,0,.06)}
      table{border-collapse:collapse;margin:0 auto}
      .cal th.r{text-align:right}
      .tot1{font-weight:600}.pay{cursor:help}
      .tot .tpay{flex-wrap:wrap}  /* another pilot's Pay-Gross carries "(n of m trips)" and Pay-Net its tax note: they wrap on a phone */
      .crew{font-size:11px;color:var(--secondary-text-color)}
      .cal td.crew::after{content:"\\200b"}  /* every row one 11 px line, as the schedule card's FAR columns give each of its rows */
      .prate{text-align:center;margin:2px 0;overflow-wrap:anywhere}.psrc{margin-top:4px;text-align:center}
      .none{padding:8px;color:var(--secondary-text-color)}
      .rb{margin-top:10px}.rbh{margin:0 0 4px}details.rb summary{cursor:pointer;margin:0 0 4px}.also{margin:6px 0 0}.also b{color:var(--primary-text-color)}
      .picks{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
      .cts{display:inline-flex;flex-wrap:wrap;gap:6px}.ct{padding:4px 10px;border-radius:14px;background:var(--primary-color);color:var(--text-primary-color,#fff);text-decoration:none;font-size:12px;font-weight:600;line-height:1.3}
      .cts.mini{gap:6px;margin-left:4px}.cts.mini .ct{padding:4px 8px;font-size:11px;font-weight:400;line-height:16px}
      .pk{padding:6px 10px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);cursor:pointer;font-size:13px}
      .vbar{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 14px;font-size:12px;margin:0 0 4px}.vbar .nw{white-space:nowrap}.vbar .k{color:var(--secondary-text-color);font-size:11.5px}
      .vbar .vb{cursor:pointer;padding:0 6px;color:var(--primary-color);user-select:none}.vbar .vb.here{opacity:.5}.vbar .vb.off{opacity:.3;cursor:default}
      .chg{margin:0 0 6px;font-size:11px;color:var(--secondary-text-color)}.chg summary{cursor:pointer;font-weight:600;list-style:none}.chg summary::-webkit-details-marker{display:none}
      .chg summary::before{content:"\\25B8\\a0"}.chg[open] summary::before{content:"\\25BE\\a0"}.chg ul{margin:4px 0 0;padding-left:16px}.chg li{margin:1px 0}.vnote{display:block;margin-top:2px;text-align:center}
      @media (max-width:700px){.vbar{font-size:11px;column-gap:10px}.vbar .vb{font-size:12px}}
`;

class FlightWatcherPilotCard extends HTMLElement {
  // FW-0025: HA calls setConfig more than once per card and keeps replaced card elements alive, and each call used to
  // add another window listener (never removed), so one lookup published 2 to 4 times. Now a card listens only while
  // it is on the page (one bound handler, added on connect, removed on disconnect), and one lookup publishes once
  // however many cards hear it (an editor preview, a stale copy).
  constructor() {
    super();
    this._onPilot = (e) => this._lookup(e);
    this._pk = {};  // 1.7.7: the pairings package files (fwgPack)
    this._pkRedraw = () => { if (this._root && !this._busy) { try { this._paint(); } catch (err) { /* the next update draws it */ } } };
  }
  setConfig(config) {
    this._config = { entity: "sensor.flight_watcher_pilot_schedule", ...config };
    this._hidden = false;
    FlightWatcherPilotCard._hook();
  }
  connectedCallback() {
    // 1.7.7: Esc closes the pairing detail, Tab stays inside its sheet; a rotation or resize past the phone width redraws it
    if (!this._kd) {
      this._kd = (e) => { if (!this._pd) return; if (e.key === "Escape") { this._pdClose(true); return; } if (this._sheet) this._sheet.trap(e); };
      this._rz = () => { if (this._pd && this._h && this._root && fwgNarrow(this._hc()) !== this._pdNarrow) this._paint(); };
    }
    if (typeof document !== "undefined" && document.addEventListener) document.addEventListener("keydown", this._kd);
    if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("resize", this._rz);
    if (this._on) return;
    this._on = true;
    FlightWatcherPilotCard._live = (FlightWatcherPilotCard._live || 0) + 1;
    window.addEventListener(PILOT_EV, this._onPilot);
    FlightWatcherPilotCard._hook();
    FlightWatcherPilotCard._fromHash();  // a #pilot= link opened before this card was on the page (a deep link, another view)
  }
  disconnectedCallback() {
    if (this._kd && typeof document !== "undefined" && document.removeEventListener) document.removeEventListener("keydown", this._kd);
    if (this._rz && typeof window !== "undefined" && window.removeEventListener) window.removeEventListener("resize", this._rz);
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
    // 1.7.7: the schedule card's dark colours (hass.themes.darkMode, which the portal sets from the device), the same way
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(h && h.themes && typeof h.themes.darkMode === "boolean" ? h.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
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
    const pay = !!(a.pay_line && a.pay_line.doh_known) && g.items.some((it) => it.gross != null);
    const tl = a.pay_line ? this._payLine(a.pay_line, left, md, src)  // the totals line under the grid, the notes under that
      : { tot: `<div class="tot">${this._tgrp("thrs", [["Trips", `${tot.length}${left.length ? ` <span class="k">(${this._esc(left.join(", "))}: not totaled)</span>` : ""}`], ["Block", sum("blk")], ["Credit", sum("credit")]])}</div>`,
        notes: `<div class="u psrc">${src}</div>` };
    const body = !g.items.length ? "" : `<div class="frame">${this._grid(g.days, g.items, g.month, { g: "rb", pay })}${tl.tot}</div>${also}${tl.notes}`;
    const open = readable && (this._rbOpen || (this._pd && this._pd.g === "rb"));
    return readable ? `<details class="rb"${open ? " open" : ""}><summary>${head}</summary>${body}</details>` : `<div class="rb"><div class="rbh">${head}</div>${body}</div>`;
  }
  // the schedule card's totals groups (FW-0009): [label, value (HTML), title?] entries that wrap as units
  _tgrp(cls, list) {
    const s = list.filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v, t]) => `<span class="ti"${t ? ` title="${this._esc(t)}"` : ""}><span class="k">${k}</span> ${v}</span>`).join("");
    return s ? `<span class="tgrp ${cls}">${s}</span>` : "";
  }
  _tax(pl) {  // FW-0062: the viewer's own tax settings (the schedule card's helpers), else the Watcher's
    const S = (this._h && this._h.states) || {};
    const num = (id) => { const v = parseFloat((S[id] || {}).state); return isNaN(v) ? null : v; };
    const [fed, stt] = TAX_HELPERS.map(num);
    return Math.round((fed == null && stt == null ? Number((pl || {}).tax_pct) || 0 : (fed == null ? 22 : fed) + (stt == null ? 0 : stt)) * 100) / 100;
  }
  // the pay groups of a priced month: Pay-Gross (n of m trips) and Pay-Net at the viewer's tax ([] when not priced)
  _payG(pl, m) {
    const e = (s) => this._esc(s);
    if (!(pl && pl.doh_known && pl.gross != null)) return [];
    const tax = this._tax(pl);
    return [["Pay-Gross", e(usd(pl.gross)) + (Number(pl.trips_priced) < m ? ` <span class="k">(${e(pl.trips_priced)} of ${e(m)} trips)</span>` : "")],
      ["Pay-Net", `${e(usd(pl.gross * (1 - tax / 100)))} <span class="k">est. at your ${e(tax)}% tax</span>`, "Pay-Gross less your federal and state tax settings (the schedule card's); an estimate"]];
  }
  // the rate line: the longevity year and the seat rates (or why there is no pay), as the rebuilt month's pay line says it
  _rate(pl) {
    const e = (s) => this._esc(s);
    if (pl.doh_known) {
      const seats = (pl.seats && pl.seats.length ? pl.seats : ["FO"]).map((s) => String(s).toUpperCase());
      const r = pl.seat_rates || {};
      const rt = (x, ca, fo) => [seats.includes("CA") && x.CA != null ? `$${e(Number(x.CA).toFixed(2))}/cr h CA${ca}` : "",
        seats.some((s) => s !== "CA") && x.FO != null ? `$${e(Number(x.FO).toFixed(2))}/cr h ${seats.includes("RO") ? "FO/RO" : "FO"}${fo}` : ""].filter(Boolean);
      const parts = rt(r, " (PWA 3.C.4)", " (PWA 3.D.6)");
      // 1.7.7 review: the list's fleet when the Watcher has no rates for it (the A330 PAX tables only), and the day a
      // new longevity year or rate date changes the rates inside the month (each trip is priced on its own day)
      const miss = pl.equip ? [...new Set(seats.map((s) => (s === "CA" ? "CA" : "FO")))].filter((s) => r[s] == null) : [];
      if (miss.length) parts.push(`rates for the ${e(pl.equip)} ${e(miss.join("/"))} seat${miss.length > 1 ? "s" : ""} are not on file (only the A330 PAX tables, PWA 3.C.4 and 3.D.6): ${parts.length ? "those trips are not priced" : "no Pay-Gross"}`);
      for (const x of Array.isArray(pl.rate_steps) ? pl.rate_steps.slice(0, 3) : []) {
        const y = x ? rt(x, "", "") : [];
        if (x && ISO_RE.test(x.from || "") && y.length) parts.push(`from ${e(fwgMd(x.from))}${x.year != null ? ` year ${e(x.year)}` : ""}: ${y.join(", ")}`);
      }
      // the DOH when the line carries it (1.7.7: a pilot instance's Watcher sends it again, Ryan, Nov 14)
      return [`Year ${e(pl.year)}${pl.year_to ? ` to ${e(pl.year_to)}` : ""}${pl.doh ? ` (DOH ${e(pl.doh)})` : ""}`, ...parts].join(" · ");
    }
    if (pl.list_status === "not_on_list") {
      // 1.4.5: the dates of hire may come from an award packet (list_source "award YYYY-MM"); uploads are on the Settings tab
      const aw = /^award (\d{4}-\d{2})$/.exec(String(pl.list_source || ""));
      return aw ? `Not in the dates of hire on file (from the ${e(aw[1])} award): upload a newer award or the seniority list (Settings tab) for this pilot's pay`
        : `Not on the seniority list on file${pl.list_date ? ` (${e(pl.list_date)})` : pl.list_newest_doh ? ` (newest DOH on it ${e(pl.list_newest_doh)})` : ""}: upload a newer list (Settings tab) for this pilot's pay`;
    }
    return "Upload the seniority list or the month's award (Settings tab) for this pilot's pay";
  }
  // FW-0062: the rebuilt month's totals and pay, in the schedule card's totals style (groups that wrap as units):
  // {tot: the totals line, notes: the rate, what is not totaled or priced, the source}
  _payLine(pl, left, md, src) {
    const e = (s) => this._esc(s);
    const m = Number(pl.trips) || 0;
    const of = (n) => (Number(n) < m ? ` <span class="k">(${e(n)} of ${e(m)})</span>` : "");
    const ds = (x) => `${e(x.pairing)} ${/^\d{4}-\d{2}-\d{2}$/.test(x.start || "") ? md(x.start) : e(x.start)}`;
    const priced = pl.doh_known && pl.gross != null;
    const why = `Totals over the ${m} trips that start in the bid period, as drawn.` + (!priced ? "" : ` Pay-Gross = credit x the hourly rate of the seat flown on each trip, for the pilot's longevity year from the date of hire (PWA 3.B.1; Captain PWA 3.C.4, First Officer and RO PWA 3.D.6), plus PWA 4.O.1: Captain $5.00 per block hour on a crew of 3 or more, RO $4.00, First Officer $3.00 on a 3-pilot crew, and the Extended Range +15% for an FO or RO on a 4-pilot crew or a SIN layover. Credit from the pairing package (minimums per PWA 4.C.3).`);
    const hrsG = this._tgrp("thrs", [["Trips", e(m)], ["Credit", e(pl.credit) + of(pl.credit_n)], ["Block", e(pl.block) + of(pl.block_n)], ["Soft", e(pl.soft) + of(pl.soft_n)]]);
    const daysG = this._tgrp("tdays", [["Days Off", pl.days_off == null ? "?" : e(pl.days_off), "Bid period days with no trip on the crew lists. Reserve, training and other duty without a pairing are not on crew lists, so they count here as days off."]]);
    const notes = [left.length ? `${left.join(", ")}: not totaled` : "",
      (pl.missing || []).length ? `No credit for ${(pl.missing || []).map(ds).join(", ")}: not priced` : "",
      (pl.no_block || []).length ? `No block for ${(pl.no_block || []).map(ds).join(", ")}: its PWA 4.O.1 override is not in Pay-Gross` : ""].filter(Boolean);
    return { tot: `<div class="tot" title="${e(why)}">${hrsG}${this._tgrp("tpay", this._payG(pl, m))}${daysG}</div>`,
      notes: `<div class="u prate">${this._rate(pl)}</div>${notes.length ? `<div class="u prate">${notes.join(" · ")}</div>` : ""}<div class="u psrc">${src}</div>` };
  }
  // 1.7.7: a month FLICA showed: Credit and Block over its pairings (checked against FLICA's), Soft, Pay-Gross and
  // Pay-Net (items_pay, the Watcher's), FLICA's Days Off; the rate and source notes go under it
  _readTot(a) {
    const e = (s) => this._esc(s), t = a.totals || {}, ip = a.items_pay && typeof a.items_pay === "object" ? a.items_pay : null;
    const mins = (v) => { const x = /^(\d+)[.:](\d{2})$/.exec(String(v == null ? "" : v).trim()); return x ? Number(x[1]) * 60 + Number(x[2]) : null; };
    const chk = (mine, fl) => { const a0 = mins(mine), b0 = mins(fl); return a0 == null || b0 == null ? "" : Math.abs(a0 - b0) < 1 ? ` <span class="okc" title="matches FLICA">&#10003;</span>` : ` <span class="bad" title="FLICA shows ${e(fl)}">FLICA ${e(fl)}</span>`; };
    if (!ip) {  // an older Watcher: FLICA's own totals only
      return { tot: `<div class="tot">${this._tgrp("thrs", [["Block", e(t.block || "?")], ["Credit", e(t.credit || "?")]])}${this._tgrp("tdays", [["Days Off", t.days_off != null ? e(t.days_off) : "?"]])}</div>`,
        notes: `<div class="u psrc">Source: FLICA Tools > Schedule Lookup, read only. Block / Credit per trip from the pairing pages.</div>` };
    }
    const m = Number(ip.trips) || 0;
    const why = `Credit, Block and Soft over the ${m} pairings that start in the month, each its share flown in the month (PWA 4.A: a segment pays on the date it originates), plus vacation days at 4:00 (PWA 6.J.1.c) and the PAYP's pay protected credit (PWA Definitions 57); FLICA's figures also hold reserve, training and other credited days.` +
      (ip.doh_known && ip.gross != null ? " Pay-Gross = credit x the hourly rate of the seat flown on each pairing, for the pilot's longevity year from the date of hire (PWA 3.B.1; Captain PWA 3.C.4, First Officer and RO PWA 3.D.6), plus the PWA 4.O.1 overrides." : "");
    const tot = `<div class="tot" title="${e(why)}">${this._hoursPay(ip, t, m, "FLICA's days off for the month")}</div>`;
    const ss = ip.seat_src && typeof ip.seat_src === "object" ? Object.entries(ip.seat_src).filter(([, n]) => Number(n) > 0) : [];
    const seatN = ss.length ? `Seat: ${ss.map(([k, n]) => `${e(n)} from ${e(PC_SEAT_SRC[k] || k)}`).join(", ")}` : "";
    const ds = (x) => `${e(x.pairing)} ${ISO_RE.test(x.start || "") ? e(fwgMd(x.start)) : e(x.start)}`;
    const notes = [(ip.missing || []).length ? `No credit for ${(ip.missing || []).map(ds).join(", ")}: not priced` : "",
      (ip.no_block || []).length ? `No block for ${(ip.no_block || []).map(ds).join(", ")}: its PWA 4.O.1 override is not in Pay-Gross` : "",
      ip.payp_unk ? "A PAYP's credit is not known (FLICA's month credit leaves none, or a trip's credit is missing): not counted" : ""].filter(Boolean);
    return { tot, notes: `<div class="u prate">${[this._rate(ip), seatN].filter(Boolean).join(" · ")}</div>${notes.length ? `<div class="u prate">${notes.join(" · ")}</div>` : ""}` +
      `<div class="u psrc">Source: FLICA Tools > Schedule Lookup, read only. Block / Credit per pairing from its pairing page (the first few), else the pairings package.</div>` };
  }
  // 1.7.7 review: a month's hours and pay groups, the schedule card's (its order, check marks, Vacation and PAYP):
  // Credit (with the vacation and PAYP credit), Block, Soft, Vacation, PAYP, Pay-Gross, Pay-Net, Days Off. ip: the
  // Watcher's price (items_pay, or a version's pay); t: FLICA's totals it is checked against; m: the trips counted
  _hoursPay(ip, t, m, daysT) {
    const e = (s) => this._esc(s);
    const mins = (v) => { const x = /^(\d+)[.:](\d{2})$/.exec(String(v == null ? "" : v).trim()); return x ? Number(x[1]) * 60 + Number(x[2]) : null; };
    // a FLICA figure the month does not fully count (a PAYP of unknown credit) is shown, never flagged red
    const chk = (mine, fl, skip) => { const a0 = mins(mine), b0 = mins(fl); return a0 == null || b0 == null ? "" : Math.abs(a0 - b0) < 1 ? ` <span class="okc" title="matches FLICA">&#10003;</span>` : skip ? ` <span class="k" title="${e(skip)}">FLICA ${e(fl)}</span>` : ` <span class="bad" title="FLICA shows ${e(fl)}">FLICA ${e(fl)}</span>`; };
    const of = (n) => (n != null && Number(n) < m ? ` <span class="k">(${e(n)} of ${e(m)})</span>` : "");
    const skip = ip.payp_unk ? "Not compared: a PAYP's credit is not known, so it is not counted" : "";
    const est = ip.payp_est ? ` <span class="k" title="Not checked: the PAYP estimate is FLICA's month credit less everything else counted, so Credit matches it by construction.">est</span>` : "";
    const pp = ip.payp || ip.payp_unk ? `<span class="ppt" title="${e(`Pay protected credit inside Credit and Pay-Gross (PWA Definitions 57). Not in Block: not flown.${ip.payp_est ? " Estimate: FLICA's month credit less everything else counted." : ""}${ip.payp_unk ? " A PAYP's credit is unknown and not counted." : ""}`)}">${ip.payp ? e(ip.payp) : ""}${ip.payp_est ? ' <span class="k">estimate</span>' : ""}${ip.payp_unk ? `${ip.payp ? " +" : ""} <span class="bad">credit unknown</span>` : ""}</span>` : "";
    return this._tgrp("thrs", [["Credit", ip.credit != null ? e(ip.credit) + of(ip.credit_n) + (est || chk(ip.credit, t.credit, skip)) : t.credit ? e(t.credit) : ""],
      ["Block", ip.block != null ? e(ip.block) + of(ip.block_n) + chk(ip.block, t.block) : t.block ? e(t.block) : ""],
      ["Soft", ip.soft != null ? e(ip.soft) + of(ip.soft_n) : ""],
      ["Vacation", ip.vac_days ? `${e(ip.vac)} <span class="k">(${e(ip.vac_days)} d x 4:00)</span>` : ""], ["PAYP", pp]]) +
      `${this._tgrp("tpay", this._payG(ip, m))}${this._tgrp("tdays", [["Days Off", t.days_off != null && t.days_off !== "" ? e(t.days_off) : "", daysT]])}`;
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
      // 1.7.7 review: the days after the first show where the pilot is that night, as FLICA's grid does: the station the
      // duty departing that day ends at (a layover), '-' on the day the last duty leaves for base, the base on the last
      // day; from the package's duties when it lists this pairing on that day, else '-' as before
      const pe = this._packOf(x.start), pp = pe && Object.prototype.hasOwnProperty.call(pe.map, x.pairing) ? pe.map[x.pairing] : null;
      const det = pp && pp.days.has(x.start) && pp.det && Array.isArray(pp.det.duties) ? pp.det : null;
      const dstn = {};
      for (const du of det ? det.duties.slice(0, 12) : []) {
        const n = Number(du && Array.isArray(du.legs) && Array.isArray(du.legs[0]) ? du.legs[0][0] : NaN);
        if (Number.isInteger(n) && n >= 1 && n <= 15) dstn[add(x.start, n - 1)] = String(du.stn || "").slice(0, 4);
      }
      let cur = det ? (dstn[x.start] && dstn[x.start] !== base ? dstn[x.start] : "-") : "-";
      for (let d = add(x.start, 1), k = 0; d <= x.end && k < 14; d = add(d, 1), k++) {
        if (det && dstn[d] !== undefined) cur = dstn[d] && dstn[d] !== base ? dstn[d] : "-";
        if (!(at[d] && at[d][0])) at[d] = ["", d === x.end ? base : det ? cur : "-"];
      }
      at[x.start] = [x.pairing, lay];
      items.push({ trip: x.pairing, start: x.start, end: x.end, blk: x.blk || "", credit: x.credit || "", soft: x.soft || "", crew: x.crew || [],
        legs: st.slice(1).map((s, i) => ({ route: `${st[i]}-${s}` })), seat: x.seat || "", read: x.checked_at || "", route: x.route || "",
        gross: x.gross != null ? x.gross : null, seat_src: x.seat ? "crew index" : "" });
    }
    const days = [];
    for (let d = first, k = 0; d <= last && k < 45; d = add(d, 1), k++) days.push([d, ...(at[d] || ["", ""])]);
    return { month, from, days, items, also };
  }
  // 1.7.7 review: the trips that started before FLICA's grid and run into it (FLICA's grid gives them no code day, so
  // the month has no item for them): the crew index's (a.reconstructed keeps a trip running into the grid), so their
  // days are boxed with their release, as the schedule card boxes Ryan's from the month before. Drawn, never totaled.
  _carry(a, days, items) {
    const d0 = (days || []).map((x) => (Array.isArray(x) ? x[0] : "")).filter((d) => ISO_RE.test(d || "")).sort()[0];
    if (!d0) return [];
    const have = new Set((items || []).filter(Boolean).map((it) => `${it.trip}|${it.start}`));
    return (Array.isArray(a.reconstructed) ? a.reconstructed : []).filter((x) => x && /^[A-Z]\d{4}/.test(x.pairing || "") && ISO_RE.test(x.start || "")
      && x.start < d0 && ISO_RE.test(x.end || "") && x.end >= d0 && !have.has(`${x.pairing}|${x.start}`)).slice(0, 2)
      .map((x) => ({ trip: x.pairing, start: x.start, end: x.end, route: x.route || "", crew: x.crew || [], legs: [], carry: true }));
  }
  // 1.7.8 (pilot database spec 12): the single quote too, so no text can close a single-quoted attribute
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
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
  // start) shows the live block, credit and crew; the totals are the version's own (FLICA's, for a lookup), and 1.7.7
  // its Pay-Gross the Watcher's price of this version (pilotver_<key>.json: each item's gross and the record's pay)
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
    const pv = rec.pay && typeof rec.pay === "object" ? rec.pay : {};
    const from = `${month}-01`, to = days.length ? days[days.length - 1][0] : "";
    const trips = items.filter((it) => /^[A-Z]\d{4}/.test(it.trip) && it.start >= from && (!to || it.start <= to)).length;
    const e = (x) => this._esc(x);
    const m = Number(pv.trips) || trips;
    const pay = pv.gross != null && items.some((it) => it.gross != null);
    // 1.7.7 review: the live month's groups in its order; a versions file from before the review (no hours in its pay)
    // shows FLICA's own Credit and Block, and Soft from them
    const ip = { ...pv, trips: m, doh_known: pv.gross != null && !!pay };
    if (pv.credit == null) {
      const mm = (v) => { const x = /^(\d+)[.:](\d{2})$/.exec(String(v == null ? "" : v).trim()); return x ? Number(x[1]) * 60 + Number(x[2]) : null; };
      const c0 = mm(t.credit), b0 = mm(t.block);
      ip.soft = c0 != null && b0 != null && c0 >= b0 ? `${Math.floor((c0 - b0) / 60)}:${String((c0 - b0) % 60).padStart(2, "0")}` : null;
    }
    const tot = `<div class="tot" title="${e(`This version's pairings priced as the live month is (each trip from the best figures on file for it: the live read, the crew index, the pairings package); the totals line of the live month, in the same order.`)}">${this._hoursPay(ip, t, m, "")}</div>`;
    const src = rec.source === "lookup" ? `FLICA Tools > Schedule Lookup${rec.updated ? ` (FLICA updated ${e(rec.updated)})` : ""}`
      : rec.source === "rebuild" ? "rebuilt from pairing crew lists" : rec.source === "award" ? "the awarded line" : e(rec.source || "");
    return `<div class="frame">${this._grid(days, items, month, { g: "main", pay, carry: this._carry(a, days, items) })}${tot}</div><div class="u vnote">v${e(rec.ver)} as captured ${this._hst(rec.at)}${src ? `, ${src}` : ""}. Block / Credit per trip and crew shown are the live ones; Pay-Gross is this version's.</div>`;
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
  // 1.7.7: US federal and Hawaii state holidays, the shared grid's (never the admin's school calendar on another pilot)
  _hol(iso) { return fwgHol(iso); }
  _hc() { return this._root && typeof this._root.querySelector === "function" ? this._root.querySelector("ha-card") : null; }
  _paint(loading) {
    this._busy = !!loading;  // FW-0062: a tax setting change does not redraw over the loading line
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      // 1.7.7: .body is redrawn; .fwsh holds the phone's bottom sheet (FwgSheet), kept across the redraws
      this._root.innerHTML = `<style>${FWG_CSS}${PILOT_CSS}</style><ha-card><div class="body"></div></ha-card><div class="fwsh" hidden></div>`;
      this._root.addEventListener("click", (e) => {
        // 1.7.7: a tap on a pairing opens its detail (below its grid, or a sheet on a phone); the same pairing again, the
        // close button, the sheet's backdrop or Esc closes it, another pairing swaps it. It only reads.
        if (e.target.closest(".pdx, .fwsb")) { this._pdClose(true); return; }
        const pt = e.target.closest(".trip[data-k]");
        if (pt) { this._pdToggle(pt.dataset.k, pt.dataset.g); return; }
        if (e.target.closest(".x")) { this._hidden = true; this._paint(); return; }
        const vb = e.target.closest(".vb");  // FW-0069: schedule versions
        if (vb) { this._vstep(vb.dataset.v); return; }
        const pk = e.target.closest(".pk");  // 1.6.2: a pilot instance's pick list carries an opaque pick id, not the number
        if (pk) window.dispatchEvent(new CustomEvent(PILOT_EV, { detail: pk.dataset.pick ? { pick: pk.dataset.pick, name: pk.dataset.name } : { emp: pk.dataset.emp, name: pk.dataset.name } }));
      });
      this._root.addEventListener("keydown", (e) => {  // a pairing is a button: Enter or Space opens its detail
        const t = e.target && e.target.closest ? e.target.closest(".trip[data-k]") : null;
        if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); this._pdToggle(t.dataset.k, t.dataset.g); }
      });
    }
    const body = this._root.querySelector(".body");
    const q = (s) => (typeof body.querySelector === "function" ? body.querySelector(s) : null);
    const was = q("details.chg");
    if (was) this._chgOpen = !!was.open;  // FW-0069: an opened changes list stays open while stepping through versions
    const rbw = q("details.rb");
    if (rbw) this._rbOpen = !!rbw.open;  // 1.7.7: an unfolded rebuild stays unfolded through a redraw
    const ae = this._root.activeElement;
    const fk = ae && ae.matches && ae.matches(".body .trip[data-k]") ? [ae.dataset.k, ae.dataset.g] : null;  // the pairing that has the focus
    this._vnow = null;
    this._pdM = null;
    const st = this._h && this._h.states[this._config.entity];
    const a = (st && st.attributes) || {};
    // 1.7.7: the pairing detail belongs to the pilot and month it was opened on
    const ctx = `${a.emp || ""}|${a.month || a.reconstructed_month || ""}`;
    this._bp = { month: a.month || a.reconstructed_month || "", from: a.reconstructed_from || "", to: a.reconstructed_to || "" };
    if (this._pd && (this._pd.ctx !== ctx || loading || a.status === "loading" || this._hidden)) this._pd = null;
    this._narrow = !!this._pd && fwgNarrow(this._hc());
    this._draw(body, a, st, loading);
    this._pdAfter(body, fk);
  }
  _draw(body, a, st, loading) {
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
      body.innerHTML = `<div class="hd"><h3>${h3}</h3>${ct}<span class="u pst">${this._esc(said)}${when ? ` (${when} HST)` : ""}</span><span class="x" title="close">&times;</span></div>${vb}${picks ? `<div class="picks">${picks}</div>` : ""}`;
      if (old) { body.insertAdjacentHTML("beforeend", old + this._recon(a, true)); return; }  // the live rebuild, folded under it
      body.insertAdjacentHTML("beforeend", this._recon(a, false));  // 0.10.1 crew index; FW-0002: in the schedule grid
      return;
    }
    const [y, m] = a.month.split("-").map(Number);
    const hd = `<div class="hd"><h3>${this._esc(name)} (${this._esc(emp)})</h3>${ct}<span class="u">${MONTHS[m - 1]} ${y} · FLICA updated ${this._esc(a.updated || "?")} · read ${a.fetched ? this._hst(a.fetched) : ""}${a.status === "cached" ? " (cached)" : ""}</span><span class="x" title="close">&times;</span></div>`;
    if (old) {  // FW-0069: an older version of a readable month
      body.innerHTML = hd + vb + old;
      body.insertAdjacentHTML("beforeend", this._recon(a, true));
      return;
    }
    const ip = a.items_pay && typeof a.items_pay === "object" ? a.items_pay : null;
    const items = a.items || [];
    const pay = !!(ip && ip.doh_known) && items.some((it) => it && it.gross != null);
    const rt = this._readTot(a);
    body.innerHTML = `${hd}${vb}<div class="frame">${this._grid(a.days, items, a.month, { g: "main", pay, carry: this._carry(a, a.days, items) })}${rt.tot}</div>${rt.notes}`;
    body.insertAdjacentHTML("beforeend", this._recon(a, true));  // 0.10.1: crew index (reconstructed from pairing crew lists), folded under a readable month
  }
  // 1.7.7: after a redraw: the sheet (narrow) shown, updated or hidden; the wide panel scrolled into view once a
  // pairing; a detail whose pairing is no longer drawn closed; the focus back on the pairing that had it
  _pdAfter(body, fk) {
    if (this._pd && !this._pdM) this._pd = null;
    const m = this._pdM;
    this._pdNarrow = this._narrow;
    const sh = m && this._narrow ? this._sheetBox() : this._sheet;
    if (sh) { if (m && this._narrow) sh.show(m.k, JSON.stringify(m), fwgSheetHtml(m)); else sh.hide(); }
    if (m && !this._narrow && this._pd && !this._pd.shown) {
      this._pd.shown = true;
      const pn = typeof body.querySelector === "function" ? body.querySelector(".fwgp") : null;
      const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (pn && pn.scrollIntoView) pn.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
    }
    if (fk && !(this._sheet && this._sheet.open)) { const t = this._tripEl(fk[0], fk[1]); if (t) t.focus({ preventScroll: true }); }
  }
  _sheetBox() {
    if (!this._sheet && this._root && typeof this._root.querySelector === "function") {
      const host = this._root.querySelector(".fwsh");
      if (host) this._sheet = new FwgSheet(host, () => this._pdClose(true));
    }
    return this._sheet || null;
  }
  // 1.7.7: the pairing detail: open, swap to another pairing, or close (the same one again)
  _pdToggle(k, g) {
    g = g || "main";
    if (this._pd && this._pd.k === k && this._pd.g === g) { this._pdClose(true); return; }
    const st = this._h && this._h.states[this._config.entity];
    const a = (st && st.attributes) || {};
    this._pd = { k, g, ctx: `${a.emp || ""}|${a.month || a.reconstructed_month || ""}`, shown: false };
    this._paint();
  }
  _pdClose(refocus) {
    if (!this._pd) return;
    const { k, g } = this._pd;
    this._pd = null;
    this._paint();
    if (refocus) { const t = this._tripEl(k, g); if (t) t.focus({ preventScroll: true }); }
  }
  _tripEl(k, g) {
    if (!this._root || typeof this._root.querySelectorAll !== "function") return null;
    return [...this._root.querySelectorAll(".body .trip[data-k]")].find((x) => x.dataset.k === k && (x.dataset.g || "main") === (g || "main")) || null;
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
    return `<div class="hd"><h3>${h3}</h3>${ct}<span class="u pst">${this._esc(line)}</span><span class="x" title="close">&times;</span></div>`;
  }
  // 1.7.7: a trip's report and release (HST) and the day it is released: from the pairings package when it lists the
  // pairing (the id without a trailing letter, as the schedule card times a trip) on that day, else from the legs the
  // pairing page gave (report = first departure - 1:00, release = last arrival + 0:15, PWA 2), else none (FLICA's end)
  _times(it) {
    const id5 = String(it.trip || "").slice(0, 5), st = it.start, end = ISO_RE.test(it.end || "") && it.end >= st ? it.end : st;
    const pe = this._packOf(st);
    const p = pe && Object.prototype.hasOwnProperty.call(pe.map, id5) && pe.map[id5].days.has(st) ? pe.map[id5] : null;
    const out = { rep: "", rel: "", relDay: end, route: String((p && p.route) || it.route || "") };
    if (p && pcMin(p.report) != null) out.rep = p.report;
    if (p && pcMin(p.release) != null && Number.isInteger(Number(p.relDays))) { out.rel = p.release; out.relDay = fwgDay(st, Number(p.relDays)); }
    const legs = (Array.isArray(it.legs) ? it.legs : []).filter((l) => l && /^\d{4}$/.test(String(l.dep || "")) && /^\d{4}$/.test(String(l.arr || "")));
    if (!out.route && legs.length) out.route = [String(legs[0].route || "").split("-")[0], ...legs.map((l) => String(l.route || "").split("-")[1] || "")].filter(Boolean).join("-");
    if (!p && legs.length) {
      const w0 = DOW.indexOf(String(legs[0].dow || "").toUpperCase());
      if (w0 === fwgWday(st)) out.rep = pcClock((pcMin(pcHM(legs[0].dep)) + 1440 - 60) % 1440);
      const l = legs[legs.length - 1], w = DOW.indexOf(String(l.dow || "").toUpperCase());
      let d = "";
      for (let x = end, k = 0; w >= 0 && x >= st && k < 15 && !d; x = fwgDay(x, -1), k++) if (fwgWday(x) === w) d = x;
      if (d) {
        const dep = pcMin(pcHM(l.dep)), arr = pcMin(pcHM(l.arr)), rel = arr + 15 + (arr < dep ? 1440 : 0);
        out.rel = pcClock(rel); out.relDay = fwgDay(d, Math.floor(rel / 1440));
      }
    }
    return out;
  }
  // 1.7.7 review: the package of the bid period a trip's first day belongs to (the grid's month, the month before for a
  // day before its bid period, the month after past it; this._bp from the sensor), and only that one: a plain render
  // never fetches a neighbouring month's file for a pairing the package lacks. null while it loads, false when none.
  _packOf(st) {
    const b = this._bp || {}, mon = /^\d{4}-\d{2}$/.test(b.month || "") ? b.month : "";
    let k = String(st).slice(0, 7);
    if (mon && ISO_RE.test(b.from || "") && ISO_RE.test(b.to || "")) {
      const [y, m] = mon.split("-").map(Number);
      k = st < b.from ? new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 7) : st > b.to ? new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 7) : mon;
    }
    const e = fwgPack(this._pk, PAIRINGS_URL, k, this._pkRedraw);
    return e && e.start <= st && st <= e.end ? e : e === null ? null : false;
  }
  // 1.7.7: the pairing detail model (the shared fwgDetail) for another pilot's trip: the package's legs and layovers
  // when it lists this exact pairing on that day, else the legs the pairing page gave, and why
  _pdModel(it, tm) {
    const id = String(it.trip || ""), st = it.start;
    const pe = fwgPackFor(this._pk, PAIRINGS_URL, st, this._pkRedraw, id);
    const has = !!pe && Object.prototype.hasOwnProperty.call(pe.map, id);
    const p = has && pe.map[id].days.has(st) ? pe.map[id] : null;
    const pmo = pe ? `${MONTHS[parseInt(pe.key.slice(5, 7), 10) - 1]} ${pe.key.slice(0, 4)}` : "";
    const legs = (Array.isArray(it.legs) ? it.legs : []).filter((l) => l && l.dep && l.arr);
    let why = p && p.det ? "" : pe === null ? "Loading the pairings package."
      : pe === false ? `No pairings package on file for the bid period of ${fwgMd(st)}: the package detail is not on file.`
      : !has && /^[A-Z]\d{4}[A-Z]$/.test(id) && Object.prototype.hasOwnProperty.call(pe.map, id.slice(0, 5)) ? `${id} is a pairing FLICA rebuilt: the ${pmo} pairings package has ${id.slice(0, 5)}, not this trip, so the package detail is not on file.`
      : !has ? `${id} is not in the ${pmo} pairings package: the package detail is not on file.`
      : !p ? `The ${pmo} pairings package does not list ${id} on ${fwgMd(st)}: the package detail is not on file.`
      : pe.dcut ? `The ${pmo} pairings file holds the leg detail of its first pairings only (a size limit): the package detail of ${id} is not on file.`
        : `The ${pmo} pairings file has no leg detail yet: an older Watcher wrote it, and the next update reads the package again.`;
    if (why && !legs.length && !it.blk && !it.credit) why += " The Watcher read no pairing page for this trip either.";
    const wmd = (iso, hm) => (hm && ISO_RE.test(iso || "") ? `${hm} ${PC_WD[fwgWday(iso)]} ${fwgMd(iso)}` : "");
    const notes = [];
    if (it.seat) notes.push(`Seat ${String(it.seat).toUpperCase()}${it.seat_src ? ` from ${PC_SEAT_SRC[it.seat_src] || it.seat_src}` : ""}.`);
    if (it.read) notes.push(`From the crew list read ${String(it.read).slice(5, 16).replace("T", " ")} HST (crew index)${it.route ? `, route ${it.route}` : ""}.`);
    if (it.gross != null) notes.push(`Pay-Gross ${usd(it.gross)} for this seat (the Watcher's price from the date of hire on file).`);
    return fwgDetail({ id, start: st, p, why, seat: it.seat, crew: it.crew, rep: wmd(st, tm.rep), rel: wmd(tm.relDay, tm.rel), notes,
      own: { blk: it.blk, credit: it.credit, soft: it.soft,
        plegs: legs.map((l) => ({ dow: l.dow, flt: l.flt, dps: String(l.route || "").split("-")[0], ars: String(l.route || "").split("-")[1], dep: pcHM(l.dep), arr: pcHM(l.arr), blk: pcDur(l.blk) })) } });
  }
  // the calendar: one row per day, the schedule card's (FWG_CSS): the day and date cells, the bold blue pairing (a tap
  // opens its detail), the layover with R and Rel times in the trip's box from its report day to its release day, Block,
  // Credit, Soft, Pay-Gross (o.pay: the Watcher priced it) and Crew. o.g names the grid (main, rb) for the detail
  _grid(days, items, month, o) {
    o = o || {};
    const g = o.g || "main", e = (s) => this._esc(s);
    const trips = (items || []).concat(o.carry || []).filter((it) => it && /^[A-Z]\d{4}/.test(it.trip || "") && ISO_RE.test(it.start || ""));
    const byStart = {}; for (const it of trips) if (!it.carry) byStart[it.start] = it;
    // the trip status mark of the schedule card (its first day: a check once flown, an airplane while it flies), HST
    const nowH = new Date(Date.now() - 10 * 3600e3), today = nowH.toISOString().slice(0, 10), nowHM = nowH.toISOString().slice(11, 16);
    const tm = new Map(trips.map((it) => [it, this._times(it)]));
    const repOn = {}, relOn = {};
    for (const it of trips) { const t = tm.get(it); if (t.rep) repOn[it.start] = t.rep; if (t.rel) relOn[t.relDay] = t.rel; }
    const boxOf = (d) => trips.find((it) => it.start <= d && d <= tm.get(it).relDay);
    const cover = (d) => trips.find((it) => it.start <= d && d <= (ISO_RE.test(it.end || "") ? it.end : it.start));
    const crewT = (it) => (it.crew || []).map(([p, n]) => `${p} ${n}`).join("\n") || "crew not read yet";
    const pd = this._pd && this._pd.g === g ? this._pd : null;
    const pdIt = pd ? trips.find((it) => `${it.trip}|${it.start}` === pd.k) : null;
    const pdDays = new Set();
    if (pdIt) for (let x = pdIt.start, n = 0; x <= tm.get(pdIt).relDay && n < 40; x = fwgDay(x, 1), n++) pdDays.add(x);
    let rows = "";
    for (const [d, code, lay] of days || []) {
      if (!ISO_RE.test(d || "")) continue;
      const w = fwgWday(d), wk = w === 0 || w === 6, oth = d.slice(0, 7) !== month;
      const bt = boxOf(d), rel = bt ? tm.get(bt).relDay : "";
      const bx = bt ? " bx" + (bt.start === d ? " bxs" : "") + (rel === d ? " bxe" : "") : "";
      const it = byStart[d] && byStart[d].trip === code ? byStart[d] : null;
      let tc = "";
      if (code === "VAC") tc = `<span class="vac">VAC</span>`;
      else if (code === "PAYP") tc = `<span class="payp tag" title="Pay protected (PWA Definitions 57): a trip removed from this pilot's line, its pay kept">PAYP</span>`;
      else if (it) {
        const k = `${it.trip}|${it.start}`;
        const legs = Array.isArray(it.legs) ? it.legs : [];
        const hint = [it.seat ? `Seat ${String(it.seat).toUpperCase()}${it.seat_src ? ` (${PC_SEAT_SRC[it.seat_src] || it.seat_src})` : ""}` : "",
          legs.length ? `${legs.length} leg${legs.length === 1 ? "" : "s"}:\n${legs.map((l) => [l.dow, l.flt, l.route, l.dep && l.arr ? `${pcHM(l.dep)}-${pcHM(l.arr)}` : "", l.blk ? pcDur(l.blk) : ""].filter(Boolean).join(" ")).join("\n")}` : "",
          it.read ? `crew read ${String(it.read).slice(5, 16).replace("T", " ")} HST` : "", "Tap for the pairing detail"].filter(Boolean).join("\n");
        tc = `<span class="trip" data-k="${e(k)}" data-g="${g}" role="button" tabindex="0" aria-expanded="${pdIt === it ? "true" : "false"}" title="${e(hint)}">${e(it.trip)}</span>`;
      } else if (/^[A-Z]\d{4}/.test(code || "")) tc = `<span class="trip">${e(code)}</span>`;  // a pairing with no item: shown, not tappable
      else if (code) tc = e(code);
      // a turn (no layover: FLICA's '-', or the base on a rebuilt day trip) shows its turn station(s) in bold, as the
      // schedule card does; a layover station is plain, in the trip's crew hint
      const cv = cover(d);
      const turn = it ? [...new Set(tm.get(it).route.split("-").slice(1, -1).filter((x) => x && x !== "HNL"))].join("/") : "";
      const dayTrip = it && it.start === (ISO_RE.test(it.end || "") ? it.end : it.start);
      const l0 = !lay ? "" : lay === "-" && !cv ? "" : (it && turn && (lay === "-" || (dayTrip && lay === "HNL"))) ? `<b>${e(turn)}</b>` : e(lay);
      let stm = "";
      if (cv && d === cv.start) {
        const t = tm.get(cv), cend = ISO_RE.test(cv.end || "") ? cv.end : cv.start;
        const lastArr = t.rel && t.relDay === cend ? pcClock((pcMin(t.rel) + 1440 - 15) % 1440) : "";  // block-in = release - 0:15
        const done = cend < today || (cend === today && !!lastArr && nowHM >= lastArr);
        const flying = !done && (cv.start < today || (cv.start === today && (!t.rep || nowHM >= t.rep)));
        stm = done ? ` <span class="st" title="Trip complete">&#10004;</span>` : flying ? ` <span class="st fly" title="Trip in progress">&#9992;</span>` : "";
      }
      const l = l0 && cv ? `<span class="tag lay" title="${e(`${cv.trip} ${cv.start} crew:\n${crewT(cv)}`)}">${l0}</span>${stm}` : l0;
      const rp = repOn[d] && it ? ` <span class="tm tag" title="${e(`${it.trip} crew:\n${crewT(it)}\n\nReport ${repOn[d]}`)}">R ${e(repOn[d])}</span>` : "";
      const rl = relOn[d] ? ` <span class="tm">Rel ${e(relOn[d])}</span>` : "";
      let blk = "", cr = "", soft = "", pay = "", crew = "", split = "";
      if (it) {
        blk = e(it.blk || ""); cr = e(it.credit || ""); soft = e(it.soft || "");
        // PWA 4.A (the Watcher's split, the schedule card's rule): this month's share of a trip into the next month
        const sp = it.split && typeof it.split === "object" ? it.split : null;
        if (sp && sp.credit) {
          blk = e(sp.blk || ""); cr = e(sp.credit); soft = e(sp.soft || "");
          split = `${it.trip}: ${sp.all_blk || "?"} block / ${sp.all_credit || "?"} credit in all; ${sp.out_blk || "?"} block flown from ${sp.next || "next month"} pays next month (PWA 4.A). Credit split by block share.`;
        }
        if (it.gross != null) pay = `<span class="pay" title="${e(`Pay-Gross for the ${String(it.seat || "FO").toUpperCase()} seat${it.seat_src ? ` (${PC_SEAT_SRC[it.seat_src] || it.seat_src})` : ""}: credit x the seat's hourly rate for this pilot's longevity year, plus the PWA 4.O.1 overrides`)}">${e(usd(it.gross))}</span>`;
        crew = (it.crew || []).map(([p, n]) => `${e(p)} ${e(n)}${(this._ctKeys || []).includes(pilotNameKey(n)) ? this._ctMini : ""}`).join(" · ");
      }
      const sc = split ? ` split" title="${e(split)}` : "";
      rows += `<tr data-d="${d}" class="${wk ? "wk" : ""}${fwgHol(d) ? " hol2" : ""}${oth ? " oth" : ""}${code === "VAC" ? " vac" : ""}${bx}${pdDays.has(d) ? " pdh" : ""}"><td>${DOW[w]}</td><td class="n">${d.slice(8)}</td>` +
        `<td>${tc}</td><td>${l}${rp}${rl}</td><td class="t${sc}">${blk}</td><td class="t${sc}">${cr}</td><td class="t">${soft}</td>${o.pay ? `<td class="t tot1">${pay}</td>` : ""}<td class="crew">${crew}</td></tr>`;
    }
    const head = `<tr class="hd"><th></th><th></th><th>Trip</th><th>Layover</th><th class="r">Block</th><th class="r">Credit</th><th class="r">Soft</th>${o.pay ? `<th class="r" title="This pilot's Pay-Gross for the seat flown on each pairing, from his date of hire on file; hover a figure for its seat">Pay-Gross</th>` : ""}<th>Crew</th></tr>`;
    let html = `<div class="wrap"><table class="cal">${head}${rows}</table></div>`;
    if (pdIt) {
      const m = this._pdModel(pdIt, tm.get(pdIt));
      this._pdM = m;
      if (!this._narrow) html += fwgPanelHtml(m);
    }
    return html;
  }
}
customElements.define("flight-watcher-pilot-card", FlightWatcherPilotCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-card", name: "Flight Watcher pilot schedule", description: "A tapped pilot's month" });

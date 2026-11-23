// Flight Watcher: compact month schedule in FLICA's own layout (narrow, weekend rows shaded).
// Reads sensor.flight_watcher_schedule (months[YYYY-MM].days/items/totals), input_number.flight_watcher_month_offset,
// sensor.flight_watcher_pot_count (open trips starting each day: bold = fits, struck = clashes),
// sensor.flight_watcher_blocked_days (tap a day to block it) and, since v3 (Nov 2 2026):
//  - sensor.flight_watcher_own_trip_times (app 0.4.7+) and the monthly pairing package
//    /local/flight-watcher/pairings_YYYY-MM.json for report and release times of Ryan's own trips;
//  - tag-on suggestions: package pairings that operate on the release day or the day after and leave
//    the in-domicile rest Ryan needs (PWA 10.E.1.a: 11 h; 10.E.1.b: 18 h before a 12 h+ duty that
//    departs 1400-0359 local). Release = block-in + 15 min (PWA 2 Duty Period ends), report = 1 h
//    before departure in domicile. Also keeps 11 h before his next trip and skips VAC / blocked days.
// Pako HI, HOM t1218/t1225. Usage: type: custom:flight-watcher-schedule-card
// 1.7.1 (F#32): the month's Improved-Pay-Gross goes to the Watcher once the pairings package is in or known missing,
// never priced without it first. (F#119) The status text colors (green, red, orange, blue) are this card's own
// variables, lighter on dark cards (Home Assistant's dark mode, the portal's from the device; the dark overrides written before
// the light rules never applied): WCAG AA 4.5:1 on light and dark cards. For the same reason the reserve grid's tint
// is lighter on a light card, a trip marked "would trade" is in the text color on its orange mark, the faint marks
// (no ideas, the trade and drop arrows, FAR '-') use the secondary text color, and another month's days lose their
// extra fade.
// 1.7.1 review: on a phone (700 px or less) the Pay settings selects are 16 px: iOS Safari zooms into a smaller one
// when it is tapped and leaves the page wider than the screen (as F#43 found for the pilot lookup).
// 1.7.11 (FW-0080, Ryan, Nov 17: "Everywhere"): the totals are the bid period's, as FLICA's are (PWA 4.A: a segment pays
// on the date it originates; December 2026 runs Dec 2 to Dec 31, so a trip Dec 1 to 3 pays its Dec 1 duty in November
// and its Dec 3 duty in December): each trip its part flown in the bid period (fwSplit, each duty's TCRD from the
// pairings package, else its block share), the VAC and PAYP days in it, the versions' prices the same. The bid period
// is the pairings package's, else the Watcher's (sensor periods), else the calendar month, which the totals then say.
// 1.7.12 (Ryan, Nov 17): the header's "updated" gives way to the clock card's "Data age 12 min" stamp (the shared data
// age block below: the time since the Watcher's last good read, amber "stale" past 1x the check interval, red "very
// stale" past 2x). FLICA's own schedule time is only in its hover text, "FLICA updated ...". The stamp ticks each second
// by itself (that span only; the card redraws only when its entities change, as before).
// 1.7.12 review: the thresholds follow the Watcher's own longest cycle (the shared block; pending Ryan's yes on that
// meaning of "1x"), "Watcher offline" in red when the app is down, and the hover text (a tap shows it, as every title
// here) has the last good read in HST. The stamp keeps one width and weight at every level, at the header's right
// (its own line on a phone), so the month arrows and Now never slide as the age ticks.
// 1.7.18 (cross-item review): one box whatever the text says, so that holds for the long texts too ("2 h 10 min,
// very stale", "over 1 h 5 min, Watcher offline" slid them up to 59 px): 21em at the right of a wide header (every
// text on one line in the usual fonts; a wider font wraps inside it), and on a phone the rest of the Lock switch's
// line, at its right (a long text wraps inside it, under the switch's 44 px), so the arrows, the month and Now keep
// the second line to themselves and the header two lines.
const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const DOW = ["SU","MO","TU","WE","TH","FR","SA"];
const MON3 = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
const H = 3600e3;
// Pay (Ryan): hourly rate per credit hour; PWA 4.O.1.a IRO override $4.00 per block hour; 4.O.1.b Extended Range type-rated FO 15% hourly premium
// FW-0010: DOH is a placeholder only. HA serves this file at /local/ with no login, so the pilot's date of hire is
// never written here; the Watcher publishes it in sensor.flight_watcher_state (attribute doh, from /data/cards.json).
const IRO_OVERRIDE = 4.00, ER_PCT = 0.15, DOH = "2000-01-01";
const VAC_H = 4.0;  // PWA 6.J.1.c: vacation day Paid and Credited at 4:00 from 1 Jan 2026 (3.75 if the AA/DL/UA trigger had failed); FLICA's totals confirm 4:00
// 1.7.2 (Ryan, Nov 13: "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?"):
// PWA Definitions 57, a Flight Grouping removed from the schedule keeps its Pay and Credit. The Watcher's own trips
// record PAYP|<start> carries the removed trip's credit (block 0:00): it counts in Credit, Pay-Gross and Pay-Net on the
// PAYP's first day at the hourly rate (no IRO or Extended Range override by itself: they go with block flown in a seat,
// PWA 4.O.1, and a PAYP flies none; the RO+15% tap still turns one on), never in Block, Block Avail or FAR 117. With no
// record (a version stored before 1.7.2, or the removed trip not on file) the credit is estimated: FLICA's month credit
// minus everything else counted, when above zero, split by days over the PAYP items without one, labeled "est". A trip
// added on PAYP days counts in full on top (PWA 4.R.1). Fix pass: a removed trip whose duties depart in two months
// counts each month's share there (the record's split, PWA 4.A); the estimate and a PAYP kept under a trip added over
// all its days count only when the card counts everything else in the month, else "credit unknown".
const PAYP = "PAYP";
const PAYP_REF = "PWA Definitions 57; 4.R.1 if you add a trip on these days";
// PWA 3.D.6 A330 PAX / B787 First Officer hourly rate by longevity year (1-12) and effective date
const RATE_DATES = ["2023-03-02", "2024-03-02", "2025-03-02", "2026-03-02", "2027-01-31"];
const RATE_TABLE = [
  [81.00, 84.00, 87.00, 90.00, 93.00], [181.30, 188.55, 196.09, 203.93, 210.05], [208.37, 216.70, 225.37, 234.39, 241.42],
  [221.09, 229.94, 239.13, 248.70, 256.16], [230.29, 239.50, 249.08, 259.04, 266.81], [241.46, 251.12, 261.16, 271.61, 279.76],
  [251.28, 261.33, 271.79, 282.66, 291.13], [256.66, 266.93, 277.61, 288.71, 297.37], [262.48, 272.98, 283.90, 295.26, 304.12],
  [266.03, 276.67, 287.74, 299.24, 308.22], [270.00, 280.80, 292.03, 303.71, 312.82], [273.62, 284.56, 295.95, 307.78, 317.02]];
const rateFor = (year, iso) => { let i = 0; RATE_DATES.forEach((d, k) => { if (iso >= d) i = k; }); return RATE_TABLE[Math.min(12, Math.max(1, year)) - 1][i]; };
// Longevity year: year 1 from the DOH, a new year on each anniversary (PWA 3.B.1, 3.D.2); pay.doh_year counts the same way
// 1.6.2 (item 12): the pay settings the Watcher may flag as copied from never-set helpers (attribute unconfirmed)
const PAY_PREFS = ["input_number.flight_watcher_federal_tax_pct", "input_number.flight_watcher_state_tax_pct", "input_number.flight_watcher_longevity_year"];
const PAY_PREF_LABEL = { [PAY_PREFS[0]]: "federal tax", [PAY_PREFS[1]]: "state tax", [PAY_PREFS[2]]: "longevity year" };
const dohYear = (iso, doh) => { const [a, b] = [doh || DOH, iso].map((s) => String(s).slice(0, 10).split("-").map(Number)); return b[0] - a[0] - (b[1] < a[1] || (b[1] === a[1] && b[2] < a[2]) ? 1 : 0) + 1; };
const hrs = (t) => { const mm = /^(\d+):(\d{2})$/.exec(String(t || "").trim()); return mm ? Number(mm[1]) + Number(mm[2]) / 60 : null; };
// 1.7.13 (Ryan, Nov 17: "Give FAR-30/7, FAR-100/672 and Room real headers with units, and show headroom against each
// limit (e.g. "100h/672h: 10:57 left")"): the 100h in 672h and Room to 100h cells say what is left of the FAR
// 117.23(b)(1) limit (100 flight hours in any 672 consecutive hours), to the minute: "10:57 left", "0:00 left" at the
// limit, "1:20 over" past it (both red: the words say it too, never the colour alone); "~" in front when a window
// reaches past the schedule on file or holds a trip with no times on file (1.7.13 F3). 1.7.13 review: the caller
// rounds the block to the minute once and passes 100:00 less that, so a cell and its title (the block) add up to 100:00.
const farLeft = (left, approx) => {
  const m = Math.round(left * 60), a = Math.abs(m);
  return { txt: `${approx ? "~" : ""}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")} ${m < 0 ? "over" : "left"}`, bad: m <= 0 };
};
// 1.7.13 (F1, Ryan Nov 18: "fix all of these things"): an own trip's flight time spans as far.py counts them for a
// pickup's FAR check (recall._trip, read by far._cum): one per duty period, from its start (the trip's report; a later
// one 1:00 before departure from HNL, 1:15 elsewhere, PWA 2.19.b) to its block-in, with that duty's block; with a duty
// block missing, one span from report to last block-in with the trip's Block; with no duty times, that one span; none
// with the dates only (far.py: whole days, block not known). [{s, e, h}]: ms (HST as UTC) and hours, h null = block not
// known. at(iso, minutes) is the card's clock. The rules follow recall._trip step by step (its int() and time parsing
// included), so Room to 100h and far.py count a line alike.
const farInt = (x) => (typeof x === "number" ? (Number.isFinite(x) ? Math.trunc(x) : null)
  : /^\s*[+-]?\d+\s*$/.test(String(x)) ? parseInt(x, 10) : null);
const farHm = (x) => {  // far._t: "HH:MM" (or HH.MM) -> minutes, or null
  const p = String(x == null ? "None" : x).replace(/\./g, ":").split(":");
  const h = p.length > 1 ? farInt(p[0]) : null, m = p.length > 1 ? farInt(p[1]) : null;
  return h != null && m != null && h >= 0 && h < 24 && m >= 0 && m < 60 ? h * 60 + m : null;
};
const farBlk = (x) => {  // recall._hrs: "H:MM" -> hours, or null
  const p = String(x == null ? "None" : x).split(":");
  const h = p.length > 1 ? farInt(p[0]) : null, m = p.length > 1 ? farInt(p[1]) : null;
  return h != null && m != null ? h + m / 60 : null;
};
const farSpans = (it, t, at) => {
  const a = it.start, b = it.end || it.start, base = at(a, 0), DEB = 15 * 60e3, DAY = 24 * 3600e3;
  const dus = Array.isArray(t.duties) ? t.duties : [];
  let rep = null, rel = null;
  const r = farHm(t.report), la = farHm(t.last_arr);
  if (a && r != null && la != null) { rep = at(a, r); rel = at(b, la) + DEB; if (rel <= rep) rel += DAY; }
  if (rep == null && dus.length) {  // no report or last block-in: the first duty's departure - 1:00 to the last + 0:15
    const d0 = farInt(dus[0] && dus[0].dep), arrs = dus.map((x) => farInt(x && x.arr));
    if (d0 != null && arrs.every((v) => v != null)) { rep = base + (d0 - 60) * 60e3; rel = base + (Math.max(...arrs) + 15) * 60e3; }
  }
  if (rep == null) return [];
  const bh = farBlk(t.blk), one = [{ s: rep, e: rel - DEB, h: bh }];
  let du = [];
  try {
    if (dus.some((x) => farInt(x && x.dep) == null)) throw new Error("dep");
    let prev = "HNL";
    dus.slice().sort((x, y) => farInt(x.dep) - farInt(y.dep)).forEach((x, i) => {
      const dep = base + farInt(x.dep) * 60e3, am = farInt(x.arr);
      if (am == null || base + am * 60e3 <= dep) throw new Error("arr");
      let h = null;
      if (x.blk != null && x.blk !== "") { const v = farInt(x.blk); if (v == null) throw new Error("blk"); h = v / 60; }
      du.push({ s: Math.min(i === 0 ? rep : dep - (prev === "HNL" ? 60 : 75) * 60e3, dep), e: base + am * 60e3, h });
      prev = String(x.stn || x.to || "");
    });
  } catch (e) { du = []; }
  if (du.length && Math.abs(du[du.length - 1].e + DEB - rel) <= 3600e3) return du.some((x) => x.h == null) ? one : du;
  return one;
};
// The 30h in 7d cell (FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h before a report): today's
// states with units: "✓ 36h MM/DD" (the longest break off duty in the 168 h before a report at that day's first duty
// start, 00:01 on a day off, in whole hours, and the day it ended), "need 30h off", "?" (the 168 h reach before the
// schedule on file), "–" (mid-trip, no report). 1.7.13 review: no "off" in the tick, so the grid is about as wide as
// in 1.7.11 (the header and the Key say the hours are off duty).
const far30Txt = (st, h, md) => st === "ok" ? `&#10003; ${Math.floor(h)}h <span class="k">${md}</span>`
  : st === "need" ? "need 30h off" : st === "unknown" ? "?" : "&#8211;";
const usd = (v) => (v == null || Number.isNaN(v) ? "" : "$" + Math.round(v).toLocaleString("en-US"));  // 1.6.2 review: no rate, no figure
// Paychecks (Ryan, Nov 19, 2026): per-check paycheck engine. Inputs from the admin's Pay model sensor (attributes), which a
// routine keeps current from the pay stubs in Drive. Federal: IRS Pub 15-T 2026 percentage method, semimonthly (24
// periods), table by W-4 (rows [annual wage from, tax at that point, rate]); supplemental pay at the flat rate.
// Social Security 6.2% to the wage base, Medicare 1.45%, Additional Medicare 0.9% over the threshold, 401(k) deferral
// to the 402(g) and 415(c) limits; once 415(c) is full the employer's contribution is paid as taxable cash on the
// true-up (stub line "ER 415(c) Excess"). Backtest: within $1 of net on every regular 2026 stub from Mar 6 given its
// earnings lines, except Sep 22 (the month 415(c) filled part way).
const fwgR2 = (v) => Math.round(v * 100) / 100;
const fwgWh = (T, w4, P) => {
  const tb = (P.tables || {})[w4] || (P.tables || {}).single || [];
  const A = T * 24;
  let tax = 0;
  for (let i = tb.length - 1; i >= 0; i--) { const [lo, base, r] = tb[i]; if (A > lo) { tax = base + (A - lo) * r; break; } }
  return Math.max(0, fwgR2(tax / 24));
};
// g: {date, gross, eligible (401(k) base), erBase (employer base), meal (non-taxable meal pay), supp}; ytd is updated
const fwgCheck = (g, ytd, P) => {
  const yr = +g.date.slice(0, 4);
  if (ytd.year !== yr) Object.assign(ytd, { year: yr, ss_wages: 0, med_wages: 0, c415: P.c415_start || 0, ee401: 0 });
  const pre = (P.medical || 0) + (P.dental || 0);
  const room = Math.max(0, (P.cap_415c || 0) - ytd.c415);
  const def = fwgR2(Math.min((P.k401_pct || 0) * (g.eligible || 0), Math.max(0, (P.cap_402g || 0) - ytd.ee401), room));
  const er = (P.er_pct || 0) * (g.erBase || 0), erPlan = Math.min(er, Math.max(0, room - def)), erCash = fwgR2(er - erPlan);
  const gross = fwgR2(g.gross + erCash);
  const T = fwgR2(gross - (g.meal || 0) - pre - def + (pre ? P.imputed || 0 : 0));
  const supp = g.supp || 0;
  const fed = fwgR2(fwgWh(T - supp, P.w4, P) + supp * (P.supp_rate || 0.22));
  const mw = fwgR2(T + def), ssRoom = Math.max(0, (P.ss_base || 0) - ytd.ss_wages);
  const ss = fwgR2(Math.min(mw, ssRoom) * 0.062), med = fwgR2(mw * 0.0145);
  const at = P.addl_med_at || 200000;
  const addl = fwgR2((Math.max(0, ytd.med_wages + mw - at) - Math.max(0, ytd.med_wages - at)) * 0.009);
  ytd.ss_wages += Math.min(mw, ssRoom); ytd.med_wages += mw; ytd.c415 += def + erPlan; ytd.ee401 += def;
  const aft = P.aftertax || 0;
  const net = fwgR2(gross - fed - ss - med - addl - def - pre - aft);
  return { date: g.date, gross, erCash, T, fed, ss, med, addl, def, pre, aft, net, toChk: fwgR2(net - (P.allot || 0)) };
};
// FW-0072 (Ryan, Nov 19): a pilot's pay stub (PDF) read in his browser to set his tax rates. Nothing leaves the device
// and nothing of the stub is kept: the file's bytes and text live in this function's locals only, and the caller keeps
// just the three percentages it returns. Reads the PeopleSoft pay advice Hawaiian Airlines issues (text in Type1 or
// Type0 fonts, Flate streams, the Standard security handler RC4 or AES-128 with an empty open password).
const fwpMd5 = (msg) => {
  const K = new Uint32Array(64), S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
  for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296) >>> 0;
  const n = msg.length, L = ((n + 8) >> 6) + 1, w = new Uint32Array(L * 16);
  for (let i = 0; i < n; i++) w[i >> 2] |= msg[i] << ((i % 4) * 8);
  w[n >> 2] |= 0x80 << ((n % 4) * 8); w[L * 16 - 2] = (n * 8) >>> 0; w[L * 16 - 1] = Math.floor(n / 536870912) >>> 0;
  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  for (let o = 0; o < w.length; o += 16) {
    let a = a0, b = b0, c = c0, d = d0;
    for (let i = 0; i < 64; i++) {
      let f, g;
      if (i < 16) { f = (b & c) | (~b & d); g = i; } else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16; }
      else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16; } else { f = c ^ (b | ~d); g = (7 * i) % 16; }
      const t = d; d = c; c = b;
      const x = (a + f + K[i] + w[o + g]) >>> 0, s = S[(i >> 4) * 4 + (i % 4)];
      b = (b + ((x << s) | (x >>> (32 - s)))) >>> 0; a = t;
    }
    a0 = (a0 + a) >>> 0; b0 = (b0 + b) >>> 0; c0 = (c0 + c) >>> 0; d0 = (d0 + d) >>> 0;
  }
  const out = new Uint8Array(16);
  [a0, b0, c0, d0].forEach((v, j) => { for (let k = 0; k < 4; k++) out[j * 4 + k] = (v >>> (8 * k)) & 255; });
  return out;
};
const fwpRc4 = (key, data) => {
  const s = new Uint8Array(256); for (let i = 0; i < 256; i++) s[i] = i;
  for (let i = 0, j = 0; i < 256; i++) { j = (j + s[i] + key[i % key.length]) & 255; [s[i], s[j]] = [s[j], s[i]]; }
  const out = new Uint8Array(data.length);
  for (let k = 0, i = 0, j = 0; k < data.length; k++) {
    i = (i + 1) & 255; j = (j + s[i]) & 255; [s[i], s[j]] = [s[j], s[i]]; out[k] = data[k] ^ s[(s[i] + s[j]) & 255];
  }
  return out;
};
const fwpCat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let p = 0; for (const x of a) { o.set(x, p); p += x.length; } return o; };
const fwpLatin = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192)); return s; };
const fwpBytes = (s) => { const o = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) o[i] = s.charCodeAt(i) & 255; return o; };
// a PDF string token's bytes: (literal, with its escapes) or <hex>
const fwpStr = (t) => {
  if (t[0] === "<") { const h = t.slice(1, -1).replace(/[^0-9a-fA-F]/g, ""); const o = []; for (let i = 0; i < h.length; i += 2) o.push(parseInt((h[i] + (h[i + 1] || "0")), 16)); return Uint8Array.from(o); }
  const o = [], s = t.slice(1, -1), E = { n: 10, r: 13, t: 9, b: 8, f: 12 };
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c !== "\\") { o.push(c.charCodeAt(0) & 255); continue; }
    const d = s[++i];
    if (d === undefined) break;
    if (E[d] !== undefined) o.push(E[d]);
    else if (d >= "0" && d <= "7") { let v = d; while (v.length < 3 && s[i + 1] >= "0" && s[i + 1] <= "7") v += s[++i]; o.push(parseInt(v, 8) & 255); }
    else if (d === "\r") { if (s[i + 1] === "\n") i++; } else if (d !== "\n") o.push(d.charCodeAt(0) & 255);
  }
  return Uint8Array.from(o);
};
// the string token that starts at s[i] ("(" or "<"), as text
const fwpStrTok = (s, i) => {
  if (s[i] === "<") { const j = s.indexOf(">", i); return s.slice(i, j + 1); }
  let depth = 0, j = i;
  for (; j < s.length; j++) { const c = s[j]; if (c === "\\") { j++; continue; } if (c === "(") depth++; else if (c === ")" && --depth === 0) break; }
  return s.slice(i, j + 1);
};
const fwpInflate = async (u8) => new Uint8Array(await new Response(new Blob([u8]).stream().pipeThrough(new DecompressionStream("deflate"))).arrayBuffer());
const FWP_PAD = Uint8Array.from([0x28, 0xBF, 0x4E, 0x5E, 0x4E, 0x75, 0x8A, 0x41, 0x64, 0x00, 0x4E, 0x56, 0xFF, 0xFA, 0x01, 0x08,
  0x2E, 0x2E, 0x00, 0xB6, 0xD0, 0x68, 0x3E, 0x80, 0x2F, 0x0C, 0xA9, 0xFE, 0x64, 0x53, 0x69, 0x7A]);
class FwpError extends Error {}

// PDF bytes -> its text, one string a line (top to bottom, left to right)
const fwpPdfLines = async (buf) => {
  const raw = new Uint8Array(buf), s = fwpLatin(raw);
  if (!s.startsWith("%PDF")) throw new FwpError("not a PDF");
  const objs = {};  // num -> {gen, dict, data (raw stream bytes) | null}
  const re = /(\d+)\s+(\d+)\s+obj\b/g;
  let m;
  while ((m = re.exec(s))) {
    const st = re.lastIndex, end = s.indexOf("endobj", st);
    if (end < 0) break;
    const body = s.slice(st, end), k = body.search(/\bstream(\r\n|\n|\r)/);
    let dict = body, data = null;
    if (k >= 0) {
      dict = body.slice(0, k);
      const d0 = st + k + body.slice(k).match(/^stream(\r\n|\n|\r)/)[0].length;
      const lm = dict.match(/\/Length\s+(\d+)(?!\s+\d+\s+R)/);
      let d1 = lm ? d0 + +lm[1] : s.lastIndexOf("endstream", end);
      if (!lm) { while (d1 > d0 && (s[d1 - 1] === "\n" || s[d1 - 1] === "\r")) d1--; }
      data = raw.subarray(d0, Math.min(d1, raw.length));
    }
    objs[+m[1]] = { num: +m[1], gen: +m[2], dict, data };
    re.lastIndex = end;
  }
  // the Standard security handler (an empty open password)
  let crypt = null;
  const em = s.match(/\/Encrypt\s+(\d+)\s+\d+\s+R/g);
  if (em) {
    const en = objs[+em[em.length - 1].match(/(\d+)/)[1]];
    if (!en || !/\/Filter\s*\/Standard/.test(en.dict)) throw new FwpError("protected in a way this can't open");
    const g = (k) => { const x = en.dict.match(new RegExp("\\/" + k + "\\s+(-?\\d+)")); return x ? +x[1] : null; };
    const V = g("V") || 0, R = g("R") || 2;
    if (V > 4 || R > 4) throw new FwpError("protected in a way this can't open");
    const tok = (k) => { const i = en.dict.search(new RegExp("\\/" + k + "\\s*[(<]")); if (i < 0) return null; const j = en.dict.indexOf(k, i) + k.length; const p = en.dict.slice(j).search(/[(<]/); return fwpStr(fwpStrTok(en.dict, j + p)); };
    const O = tok("O"), U = tok("U"), P = g("P"), ids = [...s.matchAll(/\/ID\s*\[\s*[(<]/g)];
    if (!O || !U || P === null || !ids.length) throw new FwpError("protected in a way this can't open");
    const lastId = ids[ids.length - 1], id0 = fwpStr(fwpStrTok(s, lastId.index + lastId[0].length - 1));
    const n = R === 2 ? 5 : (g("Length") || 40) / 8;
    const cfm = (en.dict.match(/\/CFM\s*\/(\w+)/) || [])[1];
    const aes = V === 4 && cfm === "AESV2";
    if (V === 4 && cfm && cfm !== "AESV2" && cfm !== "V2") throw new FwpError("protected in a way this can't open");
    const p4 = Uint8Array.from([P & 255, (P >> 8) & 255, (P >> 16) & 255, (P >>> 24) & 255]);
    const noMeta = R >= 4 && /\/EncryptMetadata\s+false/.test(en.dict) ? Uint8Array.from([255, 255, 255, 255]) : new Uint8Array(0);
    let h = fwpMd5(fwpCat(FWP_PAD, O.subarray(0, 32), p4, id0, noMeta));
    if (R >= 3) for (let i = 0; i < 50; i++) h = fwpMd5(h.subarray(0, n));
    const key = h.slice(0, n);
    // the empty open password check (Algorithm 4 / 5)
    let u;
    if (R === 2) u = fwpRc4(key, FWP_PAD);
    else { u = fwpRc4(key, fwpMd5(fwpCat(FWP_PAD, id0))); for (let i = 1; i < 20; i++) u = fwpRc4(key.map((b) => b ^ i), u); }
    const cmpN = R === 2 ? 32 : 16;
    for (let i = 0; i < cmpN; i++) if (u[i] !== U[i]) throw new FwpError("needs a password to open");
    crypt = { key, n, aes };
  }
  const objKey = (o) => {
    const k = fwpCat(crypt.key, Uint8Array.from([o.num & 255, (o.num >> 8) & 255, (o.num >> 16) & 255, o.gen & 255, (o.gen >> 8) & 255]),
      crypt.aes ? Uint8Array.from([0x73, 0x41, 0x6C, 0x54]) : new Uint8Array(0));
    return fwpMd5(k).slice(0, Math.min(crypt.n + 5, 16));
  };
  const streamOf = async (o) => {
    if (!o || !o.data) return null;
    let d = o.data;
    if (crypt && !/\/Type\s*\/XRef/.test(o.dict)) {
      if (crypt.aes) {
        if (d.length < 32) return new Uint8Array(0);
        if (!(globalThis.crypto && crypto.subtle)) throw new FwpError("needs Flight Watcher open over https to read it");
        const ck = await crypto.subtle.importKey("raw", objKey(o), "AES-CBC", false, ["decrypt"]);
        d = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-CBC", iv: d.slice(0, 16) }, ck, d.slice(16, 16 + ((d.length - 16) & ~15))));
      } else d = fwpRc4(objKey(o), d);
    }
    if (/\/FlateDecode|\/Fl\b/.test(o.dict)) d = await fwpInflate(d);
    else if (/\/Filter/.test(o.dict)) return null;  // a filter this reader has no use for (images)
    return d;
  };
  // objects packed in object streams (their dicts only; a stream is never in one)
  for (const o of Object.values(objs)) {
    if (!/\/Type\s*\/ObjStm/.test(o.dict)) continue;
    const d = fwpLatin(await streamOf(o)), first = +(o.dict.match(/\/First\s+(\d+)/) || [0, 0])[1];
    const nums = d.slice(0, first).trim().split(/\s+/).map(Number);
    for (let i = 0; i + 1 < nums.length; i += 2) {
      const a = first + nums[i + 1], b = i + 3 < nums.length ? first + nums[i + 3] : d.length;
      if (!objs[nums[i]]) objs[nums[i]] = { num: nums[i], gen: 0, dict: d.slice(a, b), data: null };
    }
  }
  const ref = (txt, k) => { const x = txt.match(new RegExp("\\/" + k + "\\s+(\\d+)\\s+\\d+\\s+R")); return x ? objs[+x[1]] : null; };
  // fonts by resource name: Type0 ones with a ToUnicode map read 2-byte codes through it
  const fonts = {};
  for (const o of Object.values(objs)) {
    const fd = o.dict.match(/\/Font\s*<<([^>]*)>>/);
    if (!fd) continue;
    for (const f of fd[1].matchAll(/\/([^\s/<>[\]()]+)\s+(\d+)\s+\d+\s+R/g)) {
      if (fonts[f[1]]) continue;
      const fo = objs[+f[2]];
      if (!fo) continue;
      const map = {}, type0 = /\/Subtype\s*\/Type0/.test(fo.dict);
      const tu = ref(fo.dict, "ToUnicode");
      if (tu) {
        const cm = fwpLatin((await streamOf(tu)) || new Uint8Array(0));
        const hx = (x) => parseInt(x, 16);
        const u16 = (x) => { let o = ""; for (let i = 0; i + 3 < x.length; i += 4) o += String.fromCharCode(hx(x.slice(i, i + 4))); return o; };
        for (const b of cm.matchAll(/beginbfchar([\s\S]*?)endbfchar/g)) for (const p of b[1].matchAll(/<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>/g)) map[hx(p[1])] = u16(p[2]);
        for (const b of cm.matchAll(/beginbfrange([\s\S]*?)endbfrange/g)) {
          for (const p of b[1].matchAll(/<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(<[0-9a-fA-F]+>|\[[^\]]*\])/g)) {
            const lo = hx(p[1]), hi = hx(p[2]);
            if (p[3][0] === "<") { const base = p[3].slice(1, -1); for (let c = lo; c <= hi && c - lo < 65536; c++) map[c] = u16(base.slice(0, -4) + (hx(base.slice(-4)) + c - lo).toString(16).padStart(4, "0")); }
            else [...p[3].matchAll(/<([0-9a-fA-F]+)>/g)].forEach((q, i) => { map[lo + i] = u16(q[1]); });
          }
        }
      }
      fonts[f[1]] = { type0, map, uni: !!tu };
    }
  }
  const dec = (font, b) => {
    let o = "";
    if (font && font.type0) { for (let i = 0; i + 1 < b.length; i += 2) { const c = (b[i] << 8) | b[i + 1]; o += font.map[c] !== undefined ? font.map[c] : ""; } return o; }
    for (const c of b) o += font && font.uni && font.map[c] !== undefined ? font.map[c] : String.fromCharCode(c);
    return o;
  };
  // the pages in order, their content streams
  const pages = [], walk = (o, depth) => {
    if (!o || depth > 32) return;
    if (/\/Type\s*\/Pages\b/.test(o.dict)) { const k = o.dict.match(/\/Kids\s*\[([^\]]*)\]/); if (k) for (const r of k[1].matchAll(/(\d+)\s+\d+\s+R/g)) walk(objs[+r[1]], depth + 1); }
    else if (/\/Type\s*\/Page\b/.test(o.dict)) pages.push(o);
  };
  const cat = Object.values(objs).find((o) => /\/Type\s*\/Catalog/.test(o.dict));
  walk(cat && ref(cat.dict, "Pages"), 0);
  const items = [];
  for (const [pi, pg] of pages.entries()) {
    const cs = [], c1 = pg.dict.match(/\/Contents\s*\[([^\]]*)\]/);
    if (c1) for (const r of c1[1].matchAll(/(\d+)\s+\d+\s+R/g)) cs.push(objs[+r[1]]); else cs.push(ref(pg.dict, "Contents"));
    let txt = "";
    for (const c of cs) { const d = await streamOf(c); if (d) txt += fwpLatin(d) + "\n"; }
    // a small content-stream interpreter: text position (Tm and the CTM) and the strings shown
    const mul = (a, b) => [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
      a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]];
    let ctm = [1, 0, 0, 1, 0, 0], tm = ctm.slice(), tlm = ctm.slice(), lead = 0, font = null, size = 10;
    const qs = [], ops = [];
    const show = (str) => {
      const p = mul(tm, ctm);
      items.push({ pg: pi, x: p[4], y: p[5], s: str });
      tm = mul([1, 0, 0, 1, str.length * size * 0.5, 0], tm);
    };
    const td = (x, y) => { tlm = mul([1, 0, 0, 1, x, y], tlm); tm = tlm.slice(); };
    for (let i = 0; i < txt.length;) {
      const c = txt[i];
      if (/\s/.test(c)) { i++; continue; }
      if (c === "%") { const j = txt.indexOf("\n", i); i = j < 0 ? txt.length : j; continue; }
      if (c === "(" || (c === "<" && txt[i + 1] !== "<")) { const t = fwpStrTok(txt, i); ops.push({ str: fwpStr(t) }); i += t.length; continue; }
      if (c === "[") { ops.push("["); i++; continue; }
      if (c === "]") { const a = []; while (ops.length && ops[ops.length - 1] !== "[") a.unshift(ops.pop()); ops.pop(); ops.push({ arr: a }); i++; continue; }
      if (c === "<" || c === ">") { i += 2; continue; }  // a dict (inline image parameters): not text
      if (c === "/") { const m2 = txt.slice(i).match(/^\/[^\s/<>[\]()%]*/); ops.push({ name: m2[0].slice(1) }); i += m2[0].length; continue; }
      const m3 = txt.slice(i, i + 64).match(/^[+-]?(\d+\.?\d*|\.\d+)/);
      if (m3) { ops.push(+m3[0]); i += m3[0].length; continue; }
      const m4 = txt.slice(i, i + 16).match(/^[A-Za-z'"*]+/);
      if (!m4) { i++; continue; }
      const op = m4[0], A = ops.splice(0);
      i += op.length;
      if (op === "BI") { const j = txt.indexOf("EI", i); i = j < 0 ? txt.length : j + 2; continue; }
      const nums = A.filter((x) => typeof x === "number");
      if (op === "q") qs.push(ctm.slice()); else if (op === "Q") ctm = qs.pop() || [1, 0, 0, 1, 0, 0];
      else if (op === "cm" && nums.length === 6) ctm = mul(nums, ctm);
      else if (op === "BT") { tm = [1, 0, 0, 1, 0, 0]; tlm = tm.slice(); }
      else if (op === "Tf") { const nm = A.find((x) => x && x.name); font = nm ? fonts[nm.name] : null; size = nums[0] || size; }
      else if (op === "TL") lead = nums[0] || 0;
      else if (op === "Td" && nums.length === 2) td(nums[0], nums[1]);
      else if (op === "TD" && nums.length === 2) { lead = -nums[1]; td(nums[0], nums[1]); }
      else if (op === "Tm" && nums.length === 6) { tm = nums.slice(); tlm = nums.slice(); }
      else if (op === "T*") td(0, -lead);
      else if (op === "Tj" || op === "'" || op === "\"") { if (op !== "Tj") td(0, -lead); const st = A.find((x) => x && x.str); if (st) show(dec(font, st.str)); }
      else if (op === "TJ") { const ar = A.find((x) => x && x.arr); if (ar) show(ar.arr.map((x) => (x && x.str ? dec(font, x.str) : typeof x === "number" && x < -200 ? " " : "")).join("")); }
    }
  }
  // lines: items within 2.5 pt of height together, left to right
  items.sort((a, b) => a.pg - b.pg || b.y - a.y);
  const lines = [];
  let cur = null;
  for (const it of items) {
    if (!it.s.trim()) continue;
    if (!cur || cur.pg !== it.pg || Math.abs(cur.y - it.y) > 2.5) { cur = { pg: it.pg, y: it.y, its: [] }; lines.push(cur); }
    cur.its.push(it);
  }
  return lines.map((l) => l.its.sort((a, b) => a.x - b.x).map((x) => x.s.trim()).join(" ").replace(/\s+/g, " "));
};

// the pay advice's text -> the year-to-date rates (percent of total gross). Hawaiian Airlines' PeopleSoft pay advice:
// TOTAL GROSS / FED TAXABLE GROSS / TOTAL TAXES / TOTAL DEDUCTIONS / NET PAY, Current and YTD rows; the federal tax
// lines Fed Withholding, Fed MED/EE, Fed OASDI/EE, Fed Addl Med. State and local = total taxes less the federal lines.
const FWP_M = "(-?[\\d,]+\\.\\d\\d)";
const fwpAmt = (x) => +String(x).replace(/,/g, "");
const fwpRates = (lines) => {
  const hi = lines.findIndex((l) => /TOTAL GROSS/i.test(l) && /NET PAY/i.test(l));
  if (hi < 0) throw new FwpError("not a pay advice this can read");
  const row = (w) => { for (let i = hi + 1; i < Math.min(lines.length, hi + 4); i++) { const m = lines[i].match(new RegExp("^" + w + "\\b(.*)", "i")); if (m) { const v = m[1].match(new RegExp(FWP_M, "g")); if (v && v.length >= 5) return v.slice(0, 5).map(fwpAmt); } } return null; };
  const ytd = row("YTD");
  if (!ytd) throw new FwpError("not a pay advice this can read");
  const [gross, , taxes, deds, net] = ytd;
  if (!(gross > 0)) throw new FwpError("shows no pay this year yet");
  if (Math.abs(gross - taxes - deds - net) > 1.005) throw new FwpError("its totals don't add up as read");
  const fedLine = (rx) => { for (const l of lines) { const m = l.match(new RegExp(rx + "\\s+" + FWP_M + "\\s+" + FWP_M, "i")); if (m) return fwpAmt(m[2]); } return 0; };
  const fwh = fedLine("Fed Withholding"), fmed = fedLine("Fed MED\\/EE"), fss = fedLine("Fed OASDI\\/EE"), fadd = fedLine("Fed Addl Med");
  if (!lines.some((l) => /Fed Withholding/i.test(l))) throw new FwpError("not a pay advice this can read");
  const fed = fwh + fmed + fss + fadd, state = Math.max(0, taxes - fed);
  if (fed > taxes + 0.005) throw new FwpError("its totals don't add up as read");
  const pct = (v) => Math.round((v / gross) * 10000) / 100;
  return { federal: pct(fed), state: pct(state), deductions: pct(deds) };
};
const fwpStep = (v, step, lo, hi) => Math.min(hi, Math.max(lo, Math.round(v / step) * step));
// a File (or ArrayBuffer) -> {federal, state, deductions} percents; throws FwpError with a short reason
const fwpReadStub = async (file) => fwpRates(await fwpPdfLines(file.arrayBuffer ? await file.arrayBuffer() : file));
// FW-0072: each state's 2026 wage income tax, Tax Foundation, "State Individual Income Tax Rates and Brackets, 2026"
// (as of January 1, 2026; taxfoundation.org): [name, n(one) | f(lat) | g(raduated), single brackets, married brackets
// ([from $, rate %]), standard deduction single, married, personal exemption single, married (null: none on the page,
// or a credit, which is not counted)]. A rate listed from a threshold above $0 leaves the income below it untaxed.
const FWP_SRC = "Tax Foundation, State Individual Income Tax Rates and Brackets, 2026 (as of January 1, 2026)";
const FWP_STATES = {
  AL: ["Alabama","g",[[0,2.0],[500,4.0],[3000,5.0]],[[0,2.0],[1000,4.0],[6000,5.0]],3000,8500,1500,3000],
  AK: ["Alaska","n",[],[],null,null,null,null],
  AZ: ["Arizona","f",[[0,2.5]],[[0,2.5]],8350,16700,null,null],
  AR: ["Arkansas","g",[[0,2.0],[4600,3.9]],[[0,2.0],[4600,3.9]],2470,4940,null,null],
  CA: ["California","g",[[0,1.0],[11079,2.0],[26264,4.0],[41452,6.0],[57542,8.0],[72724,9.3],[371479,10.3],[445771,11.3],[742953,12.3],[1000000,13.3]],[[0,1.0],[22158,2.0],[52528,4.0],[82904,6.0],[115084,8.0],[145448,9.3],[742958,10.3],[891542,11.3],[1000000,12.3],[1485906,13.3]],5540,11080,null,null],
  CO: ["Colorado","f",[[0,4.4]],[[0,4.4]],16100,32200,null,null],
  CT: ["Connecticut","g",[[0,2.0],[10000,4.5],[50000,5.5],[100000,6.0],[200000,6.5],[250000,6.9],[500000,6.99]],[[0,2.0],[20000,4.5],[100000,5.5],[200000,6.0],[400000,6.5],[500000,6.9],[1000000,6.99]],null,null,15000,24000],
  DE: ["Delaware","g",[[2000,2.2],[5000,3.9],[10000,4.8],[20000,5.2],[25000,5.55],[60000,6.6]],[[2000,2.2],[5000,3.9],[10000,4.8],[20000,5.2],[25000,5.55],[60000,6.6]],3250,6500,null,null],
  DC: ["District of Columbia","g",[[0,4.0],[10000,6.0],[40000,6.5],[60000,8.5],[250000,9.25],[500000,9.75],[1000000,10.75]],[[0,4.0],[10000,6.0],[40000,6.5],[60000,8.5],[250000,9.25],[500000,9.75],[1000000,10.75]],16100,32200,null,null],
  FL: ["Florida","n",[],[],null,null,null,null],
  GA: ["Georgia","f",[[0,5.19]],[[0,5.19]],12000,24000,null,null],
  HI: ["Hawaii","g",[[0,1.4],[9600,3.2],[14400,5.5],[19200,6.4],[24000,6.8],[36000,7.2],[48000,7.6],[125000,7.9],[175000,8.25],[225000,9.0],[275000,10.0],[325000,11.0]],[[0,1.4],[19200,3.2],[28800,5.5],[38400,6.4],[48000,6.8],[72000,7.2],[96000,7.6],[250000,7.9],[350000,8.25],[450000,9.0],[550000,10.0],[650000,11.0]],4400,8800,1144,2288],
  ID: ["Idaho","f",[[4811,5.3]],[[9622,5.3]],16100,32200,null,null],
  IL: ["Illinois","f",[[0,4.95]],[[0,4.95]],null,null,2925,5850],
  IN: ["Indiana","f",[[0,2.95]],[[0,2.95]],null,null,1000,2000],
  IA: ["Iowa","f",[[0,3.8]],[[0,3.8]],16100,32200,null,null],
  KS: ["Kansas","g",[[0,5.2],[23000,5.58]],[[0,5.2],[46000,5.58]],3605,8240,9160,18320],
  KY: ["Kentucky","f",[[0,3.5]],[[0,3.5]],3360,3360,null,null],
  LA: ["Louisiana","f",[[0,3.0]],[[0,3.0]],12875,25750,null,null],
  ME: ["Maine","g",[[0,5.8],[27399,6.75],[64849,7.15]],[[0,5.8],[54849,6.75],[129749,7.15]],8350,16700,5300,10600],
  MD: ["Maryland","g",[[0,2.0],[1000,3.0],[2000,4.0],[3000,4.75],[100000,5.0],[125000,5.25],[150000,5.5],[250000,5.75],[500000,6.25],[1000000,6.5]],[[0,2.0],[1000,3.0],[2000,4.0],[3000,4.75],[150000,5.0],[175000,5.25],[225000,5.5],[300000,5.75],[600000,6.25],[1200000,6.5]],3350,6700,3200,6400],
  MA: ["Massachusetts","g",[[0,5.0],[1083150,9.0]],[[0,5.0],[1083150,9.0]],null,null,4400,8800],
  MI: ["Michigan","f",[[0,4.25]],[[0,4.25]],null,null,5900,11800],
  MN: ["Minnesota","g",[[0,5.35],[33310,6.8],[109430,7.85],[203150,9.85]],[[0,5.35],[48700,6.8],[193480,7.85],[337930,9.85]],15300,30600,null,null],
  MS: ["Mississippi","f",[[10000,4.0]],[[10000,4.0]],2300,4600,6000,12000],
  MO: ["Missouri","g",[[1348,2.0],[2696,2.5],[4044,3.0],[5392,3.5],[6740,4.0],[8088,4.5],[9436,4.7]],[[1348,2.0],[2696,2.5],[4044,3.0],[5392,3.5],[6740,4.0],[8088,4.5],[9436,4.7]],16100,32200,null,null],
  MT: ["Montana","g",[[0,4.7],[47500,5.65]],[[0,4.7],[95000,5.65]],16100,32200,null,null],
  NE: ["Nebraska","g",[[0,2.46],[4130,3.51],[24760,4.55]],[[0,2.46],[8250,3.51],[49530,4.55]],8850,17700,null,null],
  NV: ["Nevada","n",[],[],null,null,null,null],
  NH: ["New Hampshire","n",[],[],null,null,null,null],
  NJ: ["New Jersey","g",[[0,1.4],[20000,1.75],[35000,3.5],[40000,5.53],[75000,6.37],[500000,8.97],[1000000,10.75]],[[0,1.4],[20000,1.75],[50000,2.45],[70000,3.5],[80000,5.53],[150000,6.37],[500000,8.97],[1000000,10.75]],null,null,1000,2000],
  NM: ["New Mexico","g",[[0,1.5],[5500,3.2],[16500,4.3],[33500,4.7],[66500,4.9],[210000,5.9]],[[0,1.5],[8000,3.2],[25000,4.3],[50000,4.7],[100000,4.9],[315000,5.9]],16100,32200,null,null],
  NY: ["New York","g",[[0,3.9],[8500,4.4],[11700,5.15],[13900,5.4],[80650,5.9],[215400,6.85],[1077550,9.65],[5000000,10.3],[25000000,10.9]],[[0,3.9],[17150,4.4],[23600,5.15],[27900,5.4],[161550,5.9],[323200,6.85],[2155350,9.65],[5000000,10.3],[25000000,10.9]],8000,16050,null,null],
  NC: ["North Carolina","f",[[0,3.99]],[[0,3.99]],12750,25500,null,null],
  ND: ["North Dakota","g",[[48475,1.95],[244825,2.5]],[[80975,1.95],[298075,2.5]],16100,32200,null,null],
  OH: ["Ohio","f",[[26050,2.75]],[[26050,2.75]],null,null,2400,4800],
  OK: ["Oklahoma","g",[[3750,2.5],[4900,3.5],[7200,4.5]],[[7500,2.5],[9800,3.5],[14400,4.5]],6350,12700,1000,2000],
  OR: ["Oregon","g",[[0,4.75],[4550,6.75],[11400,8.75],[125000,9.9]],[[0,4.75],[9100,6.75],[22800,8.75],[250000,9.9]],2910,5820,null,null],
  PA: ["Pennsylvania","f",[[0,3.07]],[[0,3.07]],null,null,null,null],
  RI: ["Rhode Island","g",[[0,3.75],[82050,4.75],[186450,5.99]],[[0,3.75],[82050,4.75],[186450,5.99]],11200,22400,5250,10500],
  SC: ["South Carolina","g",[[0,0.0],[3640,3.0],[18230,6.0]],[[0,0.0],[3640,3.0],[18230,6.0]],8350,16700,null,null],
  SD: ["South Dakota","n",[],[],null,null,null,null],
  TN: ["Tennessee","n",[],[],null,null,null,null],
  TX: ["Texas","n",[],[],null,null,null,null],
  UT: ["Utah","f",[[0,4.5]],[[0,4.5]],null,null,null,null],
  VT: ["Vermont","g",[[0,3.35],[49400,6.6],[119700,7.6],[249700,8.75]],[[0,3.35],[82500,6.6],[199450,7.6],[304000,8.75]],7650,15300,5300,10600],
  VA: ["Virginia","g",[[0,2.0],[3000,3.0],[5000,5.0],[17000,5.75]],[[0,2.0],[3000,3.0],[5000,5.0],[17000,5.75]],8750,17500,930,1860],
  WA: ["Washington","n",[],[],null,null,null,null],
  WV: ["West Virginia","g",[[0,2.22],[10000,2.96],[25000,3.33],[40000,4.44],[60000,4.82]],[[0,2.22],[10000,2.96],[25000,3.33],[40000,4.44],[60000,4.82]],null,null,2000,4000],
  WI: ["Wisconsin","g",[[0,3.5],[15110,4.4],[51950,5.3],[332720,7.65]],[[0,3.5],[20150,4.4],[69260,5.3],[443630,7.65]],13960,25840,700,1400],
  WY: ["Wyoming","n",[],[],null,null,null,null]
};
// a state's tax as a percent of a year's gross: {name, type, pct (null with no gross), low, top}
const fwpStateTax = (st, filing, annual) => {
  const r = FWP_STATES[st];
  if (!r) return null;
  const [name, type, bs, bm, ss, sm, es, em] = r, mar = filing === "married", br = mar ? bm : bs;
  if (type === "n") return { name, type, pct: 0, low: 0, top: 0 };
  const top = br[br.length - 1][1], low = (br.find((b) => b[1] > 0) || br[0])[1];
  if (!(annual > 0)) return { name, type, pct: null, low, top };
  const taxable = Math.max(0, annual - ((mar ? sm : ss) || 0) - ((mar ? em : es) || 0));
  let tax = 0;
  for (let i = 0; i < br.length; i++) {
    const lo = br[i][0], hi = i + 1 < br.length ? br[i + 1][0] : Infinity;
    if (taxable > lo) tax += (Math.min(taxable, hi) - lo) * br[i][1] / 100;
  }
  return { name, type, pct: Math.round((tax / annual) * 10000) / 100, low, top };
};
const PAIRINGS_URL = "/local/flight-watcher/pairings_";  // the shared pairings package files (pairings_YYYY-MM.json)
// 1.7.18: the lock switch's icon, an inline SVG (24 x 24): a shut shackle, or one lifted clear of the body, over a body
// with a keyhole. Drawn the same on every phone (the emoji it replaces was each phone's own)
const FWS_LOCK_BODY = "M6.5 10h11a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2V12a2 2 0 0 1 2-2zM12 13.4a1.8 1.8 0 0 0-.9 3.36V18.6h1.8v-1.84A1.8 1.8 0 0 0 12 13.4z";
const fwsLockSvg = (shut) => `<svg class="lki" data-lock="${shut ? "shut" : "open"}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">` +
  `<path d="${shut ? "M8 10.5V7.5a4 4 0 0 1 8 0v3" : "M8 10.5V5.5a4 4 0 0 1 8 0v1"}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>` +
  `<path d="${FWS_LOCK_BODY}" fill="currentColor" fill-rule="evenodd"/></svg>`;

// FW-0060: a sensor's full list from its file under /local/ (<url><file_key>.json, the pilot's own www folder). Fetched
// again whenever the sensor's rev changes; null until it is in (or when the sensor has no key), so the caller falls
// back to the sensor's own short list. A failed fetch is not retried until rev changes.
function fwListFile(box, url, st, redraw) {
  const a = (st && st.attributes) || {};
  const key = /^[0-9a-f]{32}$/.test(String(a.file_key || "")) ? a.file_key : "";
  if (!key) return null;
  const want = `${key}|${a.rev || ""}`;
  if (box.want !== want && !box.busy) {
    box.busy = true;
    fetch(`${url}${key}.json?r=${encodeURIComponent(a.rev || "")}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { box.busy = false; box.want = want; if (j) { box.key = key; box.data = j; } redraw(); })
      .catch(() => { box.busy = false; box.want = want; });
  }
  return box.key === key ? box.data : null;
}

// 1.7.11 (FW-0080, Ryan, Nov 17: "Everywhere"; PWA 4.A: a segment pays on the date it originates): FLICA totals the bid
// period, not the calendar month (December 2026 runs Dec 2 to Dec 31, November Nov 1 to Dec 1). fwSplit: a trip's part
// in the bid period from..to (ISO). Each duty counts in the bid period that holds its HST departure date (dep: HST
// minutes from 00:00 HST of the trip's first day st), its credit the duty's TCRD (the pairings package's) when every
// duty outside the trip's home period (the one holding st) has one, else its block share (est); the home period keeps
// the rest of the trip credit (rig, minimums), so the parts always add up to the trip. cr, bl: the trip's credit and
// block in hours (null: unknown). null when no duty is placed (the whole trip pays in its home period), else {in, whole,
// cr, bl (minutes here; null unknown), outCr, outBl (minutes paid in the other bid period), side ('before' / 'after' /
// ''), est}. pay.split_by_period and period_share are the same rule (tests/test_fw1711_totals.py runs both).
function fwSplit(st, duties, from, to, cr, bl) {
  const where = (d) => (from <= d && d <= to ? "in" : d < from ? "before" : "after");
  const t0 = Date.parse(String(st).slice(0, 10) + "T00:00:00Z");
  if (Number.isNaN(t0)) return null;
  const mins = (v) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : fwgMins(v));
  const du = (Array.isArray(duties) ? duties : []).filter((x) => x && typeof x.dep === "number" && typeof x.blk === "number" && Number.isFinite(x.dep) && Number.isFinite(x.blk))
    .map((x) => ({ d: new Date(t0 + Math.floor(x.dep / 1440) * 864e5).toISOString().slice(0, 10), b: Math.trunc(x.blk), t: mins(x.tcrd) }));
  const totB = du.reduce((a, x) => a + x.b, 0);
  if (!du.length || totB <= 0) return null;
  const home = where(String(st).slice(0, 10)), parts = {};
  for (const x of du) { const k = where(x.d); const p = parts[k] || (parts[k] = { b: 0, t: 0, ok: true }); p.b += x.b; if (x.t == null) p.ok = false; else p.t += x.t; }
  if (!parts[home]) parts[home] = { b: 0, t: 0, ok: true };
  const others = Object.keys(parts).filter((k) => k !== home), est = !others.every((k) => parts[k].ok);
  const cM = cr == null || Number.isNaN(cr) ? null : Math.round(cr * 60), bM = bl == null || Number.isNaN(bl) ? null : Math.round(bl * 60);
  const by = {};
  for (const k of Object.keys(parts)) by[k] = { c: null, b: null };
  if (bM != null) { for (const k of others) by[k].b = Math.floor(bM * parts[k].b / totB + 0.5); by[home].b = Math.max(0, bM - others.reduce((a, k) => a + by[k].b, 0)); }
  if (cM != null) { for (const k of others) by[k].c = Math.min(cM, est ? Math.floor(cM * parts[k].b / totB + 0.5) : parts[k].t); by[home].c = Math.max(0, cM - others.reduce((a, k) => a + by[k].c, 0)); }
  const mine = by.in || { c: cM == null ? null : 0, b: bM == null ? null : 0 }, side = Object.keys(by).find((k) => k !== "in") || "";
  return { in: !!by.in, whole: !side, cr: mine.c, bl: mine.b, outCr: side && cM != null ? cM - (mine.c || 0) : null,
    outBl: side && bM != null ? bM - (mine.b || 0) : null, side, est: est && !!side };
}

// 1.7.11 review (FW-0080): a trip whose own times are not read yet places its duties from the pairings package's detail
// (fwPkgDuties: each duty's first leg, its day number and local departure, made HST with FW_TZ, the Watcher's pot.TZ;
// tests/test_fw1711_review.py keeps them equal), so it splits as the Watcher splits it from the package
const FW_TZ = { HNL: -10, OGG: -10, KOA: -10, ITO: -10, LIH: -10, PPT: -10, RAR: -10, PPG: -11, ANC: -9,
  LAX: -8, SFO: -8, SEA: -8, SAN: -8, OAK: -8, SMF: -8, LAS: -8, PDX: -8, SJC: -8, ONT: -8, LGB: -8,
  PHX: -7, SLC: -7, DEN: -7, ORD: -6, DFW: -6, AUS: -6, MSP: -6, IAH: -6,
  JFK: -5, BOS: -5, MCO: -5, IAD: -5, ATL: -5, MIA: -5, EWR: -5,
  NRT: 9, HND: 9, KIX: 9, CTS: 9, FUK: 9, NGO: 9, ICN: 9, SYD: 10, BNE: 10, MEL: 10,
  AKL: 12, SIN: 8, MNL: 8, CRK: 8, TPE: 8, PEK: 8, PVG: 8, HKG: 8 };
// [{dep (HST minutes from 00:00 HST of the trip's first day), blk, tcrd}] of a package entry's duties (det.duties: legs
// [day, dh, flt, from, to, dep local, ...], tblk, tcrd), [] when any duty's first leg, departure or block is unreadable
function fwPkgDuties(pr) {
  const dd = pr && pr.det && Array.isArray(pr.det.duties) ? pr.det.duties : [];
  const out = [];
  for (const x of dd) {
    const l = x && Array.isArray(x.legs) && Array.isArray(x.legs[0]) ? x.legs[0] : null;
    const n = l ? Number(l[0]) : NaN, t = l ? /^(\d{1,2}):?(\d{2})$/.exec(String(l[5] == null ? "" : l[5]).trim()) : null, b = x ? fwgMins(x.tblk) : null;
    if (!Number.isInteger(n) || n < 1 || n > 40 || !t || Number(t[1]) > 23 || b == null) return [];
    const shift = l[3] in FW_TZ && l[4] in FW_TZ ? (FW_TZ[l[3]] + 10) * 60 : 0;  // pot.leg_shift
    out.push({ dep: (n - 1) * 1440 + Number(t[1]) * 60 + Number(t[2]) - shift, blk: b, tcrd: x.tcrd });
  }
  return out;
}

// 1.7.20 (Hark, pay engine; Ryan, Nov 20, 2026: "Update my pay in FW ... so that our numbers are always 100% perfect").
// Pilots on a crew: the package crew line (CA01FO01RO01 = 3), a number, or FLICA's own crew list (["CA Doe, Jane (1)",
// "FO ..."]: one per seat listed, plus the Captain when the list names none; a 4-pilot charter lists only its FOs and RO)
function fwCrewOwn(list) {
  const seats = (Array.isArray(list) ? list : []).map((s) => (/^\s*(CA|FO|RO|SO)\b/.exec(String(s || "")) || [])[1]).filter(Boolean);
  return seats.length + (seats.length && !seats.includes("CA") ? 1 : 0);
}
// PWA 4.O.1 override of one trip: {v ($), kind}. IRO crew (3 pilots, 4.O.1.a): Captain $5.00, IRO $4.00, First Officer
// $3.00 per block hour. Extended Range crew (4 pilots, Definitions 25, 4.O.1.b): Captain $5.00, the type-rated FO a 15%
// hourly pay premium, every other First Officer (an RO seat too) $3.00. The 15% only when the trip is marked as flown in
// the type-rated FO seat (erPlus, the Pay-Gross tap): never by itself (a SIN trip or 4 pilots alone is $3.00).
// A Captain is paid the Captain override "under all circumstances" (4.O.1), never the 15%.
function fwOverride(seat, n, blk, cr, rate, erPlus) {
  const s = String(seat || "FO").toUpperCase();
  if (erPlus && s !== "CA") return { v: cr == null ? 0 : cr * rate * ER_PCT, kind: "er" };
  if (blk == null) return { v: 0, kind: "" };
  if (s === "CA") return n >= 3 ? { v: blk * 5.00, kind: "ca" } : { v: 0, kind: "" };
  if (n >= 4) return { v: blk * 3.00, kind: "erfo" };
  if (s === "RO") return { v: blk * IRO_OVERRIDE, kind: "iro" };
  if (n === 3) return { v: blk * 3.00, kind: "fo3" };
  return { v: 0, kind: "" };
}
// PWA pay of an own trip (minutes): o = {start (ISO, the trip's first day HST), ot (the Watcher's own trip times: report,
// duties [{dep, arr, blk, stn}] in HST minutes from the first day, credit), pr (the pairings package entry that lists the
// pairing on that day, or null), isOff(iso) (a day off on the schedule: no other assignment), rcl (true: the whole trip
// was a recall; [i, ...]: those duties were)}. null without duty times.
// - Credit = the greater of (PWA 4.C.3.a): GOP (4.B.1: each segment the greater of actual or scheduled block; a duty of
//   one leg is one segment), Trip Rig 1:3.5 of TAFB (report to release, release = last block-in + 0:15), MDG 5:00 x the
//   calendar days the trip touches (from Mar 2, 2025).
// - mine === false (1.7.20 review: the duty times came from a pairing page whose crew list does not name the pilot, as
//   H3036A Oct 2026 with its crew OPEN): the tests are shown but nothing is changed: no fix, no LODO (recall marks
//   still count).
// - Delay vs reassignment (2.A.15.a.1): a leg whose only change is its time, left less than 24 h after its scheduled
//   departure (before the next day's operation of the same flight), is a delay: ONE segment. FLICA has counted a delayed
//   leg twice (the original and the delayed one, H3606A Nov 2026): when every duty matches the package one leg each, a leg
//   is delayed and FLICA's credit is 0:30 or more over every PWA test, the PWA credit is used (fix) and the cut kept.
//   A leg 24 h or more late, or legs unlike the package, keep FLICA's credit (pay protection, 4.D.2.b).
// - LODO (4.D.2.e): released in domicile after the scheduled footprint on a scheduled day off: 4:00 PAY, no credit, for
//   each lost day off.
// - Recall (4.M.1.a): 200% pay, 100% credit: the extra 100% of the recall duties' credit (pay only).
// 1.7.25 (Hark, Ryan's override of Nov 22, 2026; ALPA DART 417120, HAL ALPA Paycheck Issues, on H3606A/B): a delayed
// leg whose duty was BROKEN (reported, released, re-reported for the same flight on a later duty period) is credited
// twice: the original duty at its scheduled credit (pay protection, PWA 4.C.3.a) and the re-reported operation as its
// own duty period (4.B.1), no delay cut (2.A.15.a.1's one segment does not apply); LODO 4:00 pay, no credit, when the
// release lands on a day off (4.D.2.e). Read from CrewTrac (a protected NF2 duty with no block, fwCtProt) or the duty
// limit: the scheduled report to the delayed leg's release is longer than any duty the crew can be held on (PWA 10.D.1
// 16:00 two pilots, 18:00 IRO; 21:00 for 4 or unknown, Part 117 Table C + 117.19). pay.pwa_trip 'brk' is the same.
const FW_BRK_REPORT = 60, FW_BRK_MAX = { 2: 16 * 60, 3: 18 * 60 }, FW_BRK_MAX_ELSE = 21 * 60;
function fwBrkMax(n) { return n >= 2 && FW_BRK_MAX[n] ? FW_BRK_MAX[n] : FW_BRK_MAX_ELSE; }
function fwRepLead(x) {
  const r = /^(\d{1,2}):?(\d{2})$/.exec(String((x && x.rept) || "").trim());
  const l = x && Array.isArray(x.legs) && Array.isArray(x.legs[0]) ? x.legs[0] : null;
  const t = l ? /^(\d{1,2}):?(\d{2})$/.exec(String(l[5] == null ? "" : l[5]).trim()) : null;
  if (!r || !t) return FW_BRK_REPORT;
  const d = ((Number(t[1]) * 60 + Number(t[2]) - Number(r[1]) * 60 - Number(r[2])) % 1440 + 1440) % 1440;
  return d > 0 && d <= 300 ? d : FW_BRK_REPORT;
}
// CrewTrac's protected credit (minutes) on duties with no block carrying an NF2 leg, a later duty flown; null if none
// (the check sensor's card view carries it as 'prot', crewtrac.card_view; a full snapshot trip is read here)
function fwCtProt(ct) {
  if (!ct || typeof ct !== "object") return null;
  const nf2 = new Set();
  for (const x of ct.legs || []) {
    if (x && typeof x === "object" && String(x.flt || "").toUpperCase() === "NF2") nf2.add(String(x.date || "").slice(5, 10));
    else if (typeof x === "string" && x.toUpperCase().startsWith("NF2")) { const m = /(\d{2}-\d{2})\s*$/.exec(x); nf2.add(m ? m[1] : ""); }
  }
  if (!nf2.size) return null;
  const du = (ct.duties || []).filter((x) => x && typeof x === "object");
  let tot = 0;
  du.forEach((x, i) => {
    const b = fwCtM(x.blkt), c = fwCtM(x.tcrd), dd = String(x.date || "").slice(5, 10);
    if (b === 0 && c && (nf2.has(dd) || nf2.has("")) && du.slice(i + 1).some((y) => (fwCtM(y.blkt) || 0) > 0)) tot += c;
  });
  return tot || null;
}
function fwPwaTrip(o) {
  const ot = (o && o.ot) || {}, st = String((o && o.start) || "");
  const du = Array.isArray(ot.duties) && ot.duties.length && ot.duties.every((x) => x && typeof x.dep === "number" && typeof x.arr === "number" && typeof x.blk === "number") ? ot.duties : null;
  if (!du || !FWG_ISO.test(st)) return null;
  const pr = (o && o.pr) || null, pd = fwPkgDuties(pr), pdet = pr && pr.det && Array.isArray(pr.det.duties) ? pr.det.duties : [];
  const match = pd.length > 0 && pd.length === du.length && du.every((x, i) => !x.stn || !pdet[i] || !pdet[i].stn || x.stn === pdet[i].stn);
  const single = match && pdet.every((x) => x && Array.isArray(x.legs) && x.legs.length === 1);
  const segs = du.map((x, i) => {
    const act = Math.round(x.blk), sch = match ? pd[i].blk : null;
    return { stn: String(x.stn || ""), act, sch, cr: Math.max(act, sch == null ? 0 : sch), delay: match ? Math.round(x.dep - pd[i].dep) : null, day: fwgDay(st, Math.floor(x.dep / 1440)) };
  });
  const gop = segs.reduce((a, s) => a + s.cr, 0);
  const rep = fwgMins(ot.report), rel = Math.max(...du.map((x) => x.arr)) + 15;
  const tafb = rep != null && rel > rep ? rel - rep : null;
  const rig = tafb != null ? Math.round(tafb / 3.5) : 0;
  const days = Math.floor(rel / 1440) + 1, mdg = st >= "2025-03-02" ? 300 * days : 0;
  const pwa = Math.max(gop, rig, mdg), won = pwa === gop ? "gop" : pwa === rig ? "rig" : "mdg";
  const flica = fwgMins(ot.credit);
  const delayed = segs.filter((s) => s.delay != null && s.delay >= 60 && s.delay < 1440).length;
  const passed = segs.filter((s) => s.delay != null && s.delay >= 1440).length;
  const mine = o.mine !== false;
  // 1.7.25: a broken duty (ALPA DART 417120), see fwRepLead / fwCtProt above
  const n = Math.max((String((pr && pr.det && pr.det.crew) || "").match(/\d{2}/g) || []).reduce((a, x) => a + parseInt(x, 10), 0), fwCrewOwn(Array.isArray(ot.crew) ? ot.crew : []));
  let brk = "", prot = 0, brkSpan = null, gopB = gop;
  const byCt = typeof o.ctp === "number" && o.ctp > 0;
  segs.forEach((s, i) => {
    if (!(single && s.delay != null && s.delay >= 60 && s.delay < 1440)) return;
    const span = du[i].arr + 15 - (pd[i].dep - fwRepLead(pdet[i]));
    if (byCt || span > fwBrkMax(n)) {
      brk = byCt ? "ct" : "duty"; brkSpan = Math.round(span); s.brk = true;
      if (!byCt) prot += fwgMins(pd[i].tcrd) || pd[i].blk;
    }
  });
  if (brk === "ct") prot = Math.trunc(o.ctp);
  if (brk) gopB = gop + prot;
  const pwaB = brk ? Math.max(gopB, rig, mdg) : pwa, wonB = brk ? (pwaB === gopB ? "gop" : pwaB === rig ? "rig" : "mdg") : won;
  // 1.7.23 (Hark, Ryan Nov 21, 2026, H3606B): CrewTrac controls. A 'K+KEY' mark (o.keep) or CrewTrac's credit for the
  // trip (o.ct, minutes) within 0:01 of FLICA's: the company booked FLICA's credit (a reassignment with a protected leg,
  // NF2, PWA 4.D.2.b), so FLICA's credit is kept and no delay cut is made (pay.pwa_trip 'kept')
  const kept = o.keep ? "mark" : typeof o.ct === "number" && flica != null && Math.abs(o.ct - flica) <= 1 ? "ct" : "";
  const fix = mine && single && delayed > 0 && !passed && flica != null && flica - pwaB >= 30 && !kept && !brk;
  const use = fix ? pwaB : flica != null ? flica : pwaB;
  const sRel = pr && pr.relDays !== "" && pr.relDays != null && Number.isFinite(Number(pr.relDays)) ? Number(pr.relDays) : null;
  const aRel = Math.floor(rel / 1440), lodoDays = [];
  if (mine && sRel != null && aRel > sRel) for (let k = sRel + 1; k <= aRel; k++) { const iso = fwgDay(st, k); if (!o.isOff || o.isOff(iso)) lodoDays.push(iso); }
  const r = o.rcl, rcl = r === true ? use : Array.isArray(r) ? segs.reduce((a, s, i) => a + (r.includes(i) ? s.cr : 0), 0) : 0;
  return { segs, gop: gopB, rig, tafb, days, mdg, pwa: pwaB, won: wonB, flica, use, fix, cut: fix ? flica - use : 0, match, single, delayed, passed,
    sRel, aRel, rel, lodoDays, lodo: 240 * lodoDays.length, rcl, rclAll: r === true, mine, kept,
    brk, prot, brkSpan, brkMax: fwBrkMax(n), n };
}
// Recall marks in the per-trip list (input_text.flight_watcher_er_trips, beside the '+KEY' / '-KEY' type-rated FO
// marks): 'R+KEY' the whole trip, 'R+KEY@0.2' its duties 0 and 2 (from the first). Returns true, [i, ...] or null.
function fwRclOf(list, k) {
  for (const x of list || []) {
    const m = /^R\+(.+?)(?:@([\d.]+))?$/.exec(String(x || ""));
    if (m && m[1] === k) return m[2] ? m[2].split(".").filter(Boolean).map(Number) : true;
  }
  return null;
}

// 1.7.22 (Hark, Ryan Nov 20, 2026, option 1): the CrewTrac per-trip pay check. CrewTrac (CTWeb) controls the schedule;
// Hark reads it once a day and hands FW a snapshot (the Watcher's CrewTrac check sensor, attribute snapshot). crewtrac.py
// mirrors these (find_trip, compare_trip, trip_line, month_line, not_compared; tests/test_fw1722_crewtrac.py runs both).
// A difference of 0:01 or more is a mismatch; a snapshot over 36 h old is not compared.
const FW_CT_STALE_H = 36;
function fwCtHm(n) { if (n == null) return ""; const a = Math.abs(Math.round(n)); return `${n < 0 ? "-" : ""}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`; }
function fwCtM(v) { const m = /^\s*(\d{1,3}):?(\d{2})\s*$/.exec(String(v == null ? "" : v)); return m ? Number(m[1]) * 60 + Number(m[2]) : null; }
function fwCtD(n) { return (n > 0 ? "+" : "-") + fwCtHm(Math.abs(n)); }
function fwCtStatus(snap, nowMs) {
  if (!snap || !Array.isArray(snap.trips)) return { st: "missing", age: null };
  const t = Date.parse(String(snap.pulled_at || "")), age = Number.isFinite(t) ? (nowMs - t) / 36e5 : null;
  return { st: age == null || age > FW_CT_STALE_H ? "stale" : "ok", age };
}
function fwCtNot(st, age) {
  if (st === "missing") return "CrewTrac not compared (snapshot missing)";
  return age != null ? `CrewTrac not compared (snapshot ${Math.round(age)} h old)` : "CrewTrac not compared (snapshot unreadable)";
}
function fwCtFind(snap, pid, start) {
  const key = String(pid || "").slice(0, 5), cand = ((snap && snap.trips) || []).filter((t) => t && t.key === key);
  const t0 = Date.parse(`${start}T00:00:00Z`);
  if (!Number.isFinite(t0)) return null;
  for (const d of [0, -1, 1]) { const iso = new Date(t0 + d * 864e5).toISOString().slice(0, 10); const hit = cand.find((t) => t.start === iso); if (hit) return hit; }
  return null;
}
function fwCtLine(cc, fc, cb, fb) {
  if (cc == null) return "CrewTrac: no credit for this trip in the snapshot";
  const bad = [];
  if (fc != null && fc !== cc) bad.push(`credit off by ${fwCtD(fc - cc)}`);
  if (cb != null && fb != null && fb !== cb) bad.push(`block CrewTrac ${fwCtHm(cb)}, FW ${fwCtHm(fb)} (${fwCtD(fb - cb)})`);
  return `CrewTrac ${fwCtHm(cc)}, FW ${fc != null ? fwCtHm(fc) : "?"}` + (bad.length ? ` \u2717 ${bad.join("; ")} (CrewTrac controls)` : " \u2713");
}
// one trip: {st, ok, line, ct (the snapshot trip)}; ok null when not compared
function fwCtTrip(snap, pid, start, fwCr, fwBlk, nowMs) {
  const s = fwCtStatus(snap, nowMs);
  if (s.st !== "ok") return { st: s.st, ok: null, line: fwCtNot(s.st, s.age), ct: null };
  if (!Object.prototype.hasOwnProperty.call(snap.months || {}, String(start).slice(0, 7))) return { st: "out", ok: null, line: "CrewTrac not compared (month not in the snapshot)", ct: null };
  const ct = fwCtFind(snap, pid, start);
  if (!ct) return { st: "ok", ok: false, line: `CrewTrac has no ${pid} on ${start} \u2717 (CrewTrac controls)`, ct: null };
  const cc = fwCtM(ct.credit), fc = fwCtM(fwCr), cb = fwCtM(ct.block), fb = fwCtM(fwBlk);
  const ok = cc != null && (fc == null || fc === cc) && (cb == null || fb == null || fb === cb);
  return { st: "ok", ok, line: fwCtLine(cc, fc, cb, fb), ct };
}
function fwCtMonth(snap, month, fwCr, nowMs) {
  const s = fwCtStatus(snap, nowMs);
  if (s.st !== "ok") return { ok: null, line: fwCtNot(s.st, s.age) };
  const pr = ((((snap.months || {})[month]) || {}).pay_report) || {}, cc = fwCtM((pr.totals || {}).credit), fc = fwCtM(fwCr);
  if (cc == null) return { ok: null, line: "" };
  const ok = fc === cc;
  return { ok, line: `CrewTrac Pay Report ${fwCtHm(cc)} credit (as of ${pr.as_of || "?"}), FW ${fc != null ? fwCtHm(fc) : "?"}` + (ok ? " \u2713" : fc != null ? ` \u2717 off by ${fwCtD(fc - cc)} (CrewTrac controls)` : "") };
}

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
      .tot{margin-top:8px;font-size:14px;font-weight:700;text-align:center;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px}.tot .tgrp{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px}.tot .tpay{flex-wrap:nowrap}.tot .ti{white-space:nowrap}.tot .k{font-weight:600;color:var(--secondary-text-color);font-size:12px;margin-right:4px}.tot .bad{color:var(--fw-err,#c62828)}.tot .tchk{flex-wrap:nowrap;font-weight:600}
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

// ---- shared data age: keep identical in every card that holds it (tests/test_fw1712_data_age.py) ----
// 1.7.12 (Nov 17: "Replace the two clocks ("updated" and "Last check") with one "data age" stamp. Turn it amber
// past 1x the normal interval and red past 2x."): the time since the Watcher's last good read (its last check time,
// which a check sets only when it succeeds), with the word "stale" or "very stale" beside the colour, so the colour is
// never the only cue (colour-blind users, screen readers).
// 1.7.12 review (its meaning of "1x" is pending a yes): 1x and 2x of the Watcher's own longest cycle between two
// good reads, not of the bare setting, so a healthy Watcher never reads stale. Each wait is the interval x 0.7 to 1.3
// (watcher.py JITTER), starts when a check ends, and the next check takes time too (a crew index chunk: about 2 min in
// normal mode, 20 s hunting). The cycle is the interval (or the pace the Watcher is held to: a pilot's FLICA budget,
// since 1.7.26 also the admin's share of the host's hour; when the state note says "at least N s apart" and that is
// longer) x 1.3, plus FW_AGE_ROOM_S for the check, which also covers a
// few seconds of a phone's clock running fast. It counts from the last good read, or later: from a change of hunt or
// of the interval after that read (the Watcher's wait starts over then; a next check it planned before the change
// counts too), and from the next check while the FLICA budget or host limit holds it (the gate's note). Very stale
// no later than the Watcher's own Stuck limit (watcher.py stuck_after_s: 10 min hunting, else 2.5x the normal interval
// and at least 30 min), so the clock card's "Stuck." always comes with a red stamp. "Data age
// unknown" with no colour when the read time is unknown, missing or not a time; red "Watcher offline" when the entity
// is unavailable (the app is down: "over N" from the moment it went), so the stamp warns when the data is stalest. An
// interval that is unknown or 0 shows the age with no colour. Each card passes its own entity ids (fwAgeFrom): none
// here, a pilot's copy rewrites them.
const FW_AGE_JITTER = 0.3;
const FW_AGE_ROOM_S = { hunt: 45, normal: 180 };
const FW_AGE_PACE = / is held to \d+ FLICA loads an hour: checks wait for the budget, at least (\d+) s apart/;
const FW_AGE_GATE = /^(?:(?:Hunting every \d+ s|Checking every \d+ min) is held to \d+ FLICA loads an hour: checks wait for the budget \(next at |FLICA (?:budget|host limit): )/;
const FW_AGE_HST = new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Honolulu", year: "numeric", month: "short",
  day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
function fwAgeDur(sec) {
  const s = Math.max(0, Math.floor(sec)), m = Math.floor(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
  if (s < 60) return `${s} s`;
  if (m < 60) return `${m} min`;
  if (h < 24) return `${h} h` + (m % 60 ? ` ${m % 60} min` : "");
  return `${d} d` + (h % 24 ? ` ${h % 24} h` : "");
}
function fwAgeSpan(sec) {  // a threshold in the hover text, to the second: "10 min 48 s"
  const s = Math.max(0, Math.round(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return [h ? `${h} h` : "", m ? `${m} min` : "", r || !(h || m) ? `${r} s` : ""].filter(Boolean).join(" ");
}
function fwAgeWhen(t, now) {  // HST, with the day when it is not today's (HST): "01:27:00 HST", "Nov 9 23:30:00 HST"
  const p = (d) => Object.fromEntries(FW_AGE_HST.formatToParts(new Date(d)).map((x) => [x.type, x.value]));
  const a = p(t), b = p(now), day = a.year !== b.year ? `${a.month} ${a.day}, ${a.year} ` : a.month !== b.month || a.day !== b.day ? `${a.month} ${a.day} ` : "";
  return `${day}${a.hour}:${a.minute}:${a.second} HST`;
}
function fwAgeMs(x) { const v = Date.parse(x == null ? "" : String(x)); return isNaN(v) ? NaN : v; }
function fwDataAge(last, hunting, normalMin, huntSec, now, more) {
  const o = more || {}, mode = hunting ? "hunt" : "normal", unit = hunting ? "s" : "min";
  if (last === "unavailable") {  // the app is down (MQTT availability): no read comes until it is back
    const went = fwAgeMs(o.lastChanged), gone = (now - went) / 1000;
    return { sec: null, t: null, level: "red", word: "Watcher offline",
      text: `Data age ${gone >= 60 ? `over ${fwAgeDur(gone)}` : "unknown"}, Watcher offline`,
      read: isNaN(went) ? "The Watcher is offline." : `The Watcher is offline since ${fwAgeWhen(went, now)}.`,
      rule: "No read comes until the Watcher app answers again." };
  }
  const per = parseFloat(hunting ? huntSec : normalMin), set = hunting ? per : per * 60;
  const known = isFinite(set) && set > 0, note = String(o.note || ""), pm = FW_AGE_PACE.exec(note);
  const pace = pm ? Number(pm[1]) : 0, room = FW_AGE_ROOM_S[mode];
  const cyc = Math.ceil(+(Math.max(set, pace) * (1 + FW_AGE_JITTER)).toFixed(3)) + room;  // whole seconds
  const why = (pace > set ? `the ${pace} s the FLICA budget holds the checks apart` : `the ${mode} check interval `
    + `(${Math.round(per * 10) / 10} ${unit})`) + ` plus its 30 % jitter, and ${fwAgeSpan(room)} for the check`;
  const stuck = hunting ? 600 : Math.max(1800, per * 150);  // watcher.py stuck_after_s
  const rule = (a, b, x) => known ? `Stale past ${fwAgeSpan(a)}, very stale past ${fwAgeSpan(b)}: 1x and 2x the Watcher's `
    + `longest ${mode} cycle, ${why}${b < a + cyc ? ", or its Stuck limit when that comes first" : ""}.${x || ""}`
    : `No ${mode} check interval is known, so the age is not judged.`;
  const t = fwAgeMs(last);
  if (isNaN(t)) return { sec: null, t: null, level: "", word: "", text: "Data age unknown", read: "No good read on file.", rule: rule(cyc, Math.min(2 * cyc, stuck)) };
  const sec = Math.max(0, (now - t) / 1000), nx = fwAgeMs(o.next);
  const ch = Math.max(-Infinity, ...(o.changed || []).map(fwAgeMs).filter((v) => !isNaN(v)));
  let due = t + cyc * 1000, from = "";
  if (ch > t) {  // hunt or the interval changed after the read: the wait starts over, a next check planned before counts
    const d = Math.max(ch + cyc * 1000, nx > t ? nx + room * 1000 : -Infinity);
    if (d > due) { due = d; from = " Counted from the hunt or interval change after that read."; }
  }
  if (FW_AGE_GATE.test(note) && nx > t && nx + room * 1000 > due) {
    due = nx + room * 1000; from = ` The FLICA budget or host limit holds the next check until ${fwAgeWhen(nx, now)}: counted from then.`;
  }
  const amber = (due - t) / 1000, red = from ? amber + cyc : Math.min(amber + cyc, stuck);
  const level = !known ? "" : sec > red ? "red" : sec > amber ? "amber" : "";
  const word = level === "red" ? "very stale" : level === "amber" ? "stale" : "";
  return { sec, t, level, word, text: `Data age ${fwAgeDur(sec)}` + (word ? `, ${word}` : ""),
    read: `Last good read ${fwAgeWhen(t, now)}.`, rule: rule(amber, red, from) };
}
// the stamp from a card's own entities (ids: last, state, next, hunt, normal, huntEvery); hunting by the switch or the
// Watcher's state; the interval change that counts is the one in use (hunt's while hunting)
function fwAgeFrom(states, ids, now) {
  const e = (k) => (states && states[ids[k]]) || {};
  const hunting = e("hunt").state === "on" || e("state").state === "hunting";
  return fwDataAge(e("last").state, hunting, e("normal").state, e("huntEvery").state, now, {
    note: (e("state").attributes || {}).note, next: e("next").state, lastChanged: e("last").last_changed,
    changed: [e("hunt").last_changed, e(hunting ? "huntEvery" : "normal").last_changed] });
}
// 1.7.26 (Nov 22: "the Data age popup would show why reads are held and get its own Check now button"): the box a tap
// on the stamp opens says why reads are held when the Watcher's state note is a FLICA gate, host limit, budget, held
// pace or stopped read path note ("Reads held: FLICA host limit, 480 page loads in the last hour from this host (every
// pilot's Watcher); the next read at 13:21 HST."), and has a Check now button that presses the card's own check now
// entity (ids.chk: the clock card's service call). It shows where the clock card shows its Check now (idle or hunting,
// Pause off); while the gate holds the next check (the note names its time) it is marked unavailable with the reason
// beside it, as the Watcher would ignore the press; after a press it reads "Check now sent" until the next good read or
// FW_AGE_SENT_MS, and "Sending..." while a portal command is in flight. A tap on its row never closes the box.
const FW_AGE_HELD = new RegExp([
  String.raw`(?:Hunting every \d+ s|Checking every \d+ min) is held to \d+ FLICA loads an hour: checks wait for the `
    + String.raw`budget(?: \(next at [0-9:]+ HST\)|, at least \d+ s apart)?`,
  String.raw`FLICA (?:budget|host limit): [^;]*; the next one waits until [0-9:]+ HST`,
  String.raw`FLICA [a-z_]+ read paused until [0-9:]+ HST(?:: [^;]*)?`].join("|"), "g");
const FW_AGE_SENT_MS = 60000;
const FW_AGE_BOX_CSS = `.fwa-h{margin-top:6px;font-weight:600}
  .fwa-c{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px;cursor:default}
  .fwa-b{font:inherit;font-size:13px;font-weight:600;line-height:1.2;min-height:36px;padding:6px 14px;
    border-radius:18px;border:1px solid var(--primary-text-color,#212121);background:var(--card-background-color,#fff);
    color:var(--primary-text-color,#212121);cursor:pointer}
  .fwa-b[aria-disabled="true"]{cursor:default;border-style:dashed}
  .fwa-b:focus-visible,div.info:focus-visible{outline:2px solid var(--primary-text-color,#212121);outline-offset:2px}
  .ag:focus-visible{outline:2px solid var(--primary-color,#03a9f4);outline-offset:2px}
  .fwa-r{flex:1 1 12em;min-width:0}
  @media (max-width:700px),(pointer:coarse){.fwa-b{min-height:44px;min-width:44px}}`;
// {line, hold}: the hold line for the box ('' when nothing holds reads), and the reason a press would be ignored now
// ('' unless the gate holds the next check)
function fwAgeHeld(note) {
  const n = String(note || ""), parts = (n.match(FW_AGE_HELD) || []).map((p) => p.replace(/\.$/, "")
    .replace(/^FLICA (budget|host limit): /, "FLICA $1, ")
    .replace(/; the next one waits until /, "; the next read at "));
  const at = FW_AGE_GATE.test(n) ? /(?:waits until|next at) ([0-9:]+) HST/.exec(n) : null;
  return { line: parts.length ? `Reads held: ${parts.join("; ")}.` : "",
    hold: at ? `The FLICA ${/^FLICA host limit/.test(n) ? "host limit" : "budget"} holds the next check until `
      + `${at[1]} HST: a press now would be ignored.` : "" };
}
// the box's Check now from a card's hass (its states and, in the portal, fwPending) and the card's own memory of a
// press (mem: {at, last}): {line, show, busy, off, label, reason}
function fwAgeChk(hass, ids, mem, now) {
  const s = (hass && hass.states) || {}, e = (k) => s[ids[k]] || {}, m = mem || {}, p = hass && hass.fwPending;
  const st = e("state").state, held = fwAgeHeld((e("state").attributes || {}).note);
  if (m.at && (now - m.at >= FW_AGE_SENT_MS || e("last").state !== m.last)) m.at = 0;
  const busy = !!(p && Object.prototype.hasOwnProperty.call(p, ids.chk));
  const show = ["idle", "hunting"].includes(st) && e("pause").state !== "on";
  return { line: held.line, show, busy, off: busy || !!m.at || !!held.hold, reason: show ? held.hold : "",
    label: busy ? "Sending..." : m.at ? "Check now sent" : "Check now" };
}
function fwAgePress(hass, ids, mem, now) {
  if (!hass || !ids.chk || typeof hass.callService !== "function") return;
  mem.at = now; mem.last = ((hass.states || {})[ids.last] || {}).state;
  hass.callService("button", "press", { entity_id: ids.chk });
}
// fills the box (built once while it stays open, so the button keeps its focus as the age ticks): the stamp's text,
// the hold line and the button's row. on: {press, close}. A button that does nothing now is aria-disabled (dashed,
// and a tap is ignored), never disabled, so the keyboard's focus stays on it. 1.7.26 review: the box itself takes the
// focus when the keyboard opens it (tabindex -1, the card calls box.focus()), so its Check now is the next Tab stop
// whatever follows the stamp; Esc anywhere in it, or Enter or Space on the box itself, closes it (on.close gives the
// stamp the focus back)
function fwAgeBox(box, text, c, on) {
  box._fwaOn = on;
  if (!box._fwaKey) {
    box._fwaKey = true;
    if (!box.hasAttribute("tabindex")) box.tabIndex = -1;
    box.addEventListener("keydown", (ev) => {
      if (!box._fwaOn || !box.querySelector(":scope > .fwa-t")) return;  // a card's other tip in the same box
      if (ev.key === "Escape" || (ev.target === box && (ev.key === "Enter" || ev.key === " "))) {
        ev.preventDefault(); ev.stopPropagation(); box._fwaOn.close();
      }
    });
  }
  let t = box.querySelector(":scope > .fwa-t");
  if (!t) {
    const mk = (tag, cls) => { const x = document.createElement(tag); x.className = cls; return x; };
    const row = mk("div", "fwa-c"), b = mk("button", "fwa-b"), r = mk("span", "fwa-r");
    box.textContent = "";
    t = mk("div", "fwa-t");
    b.type = "button"; r.id = "fwa-r"; r.setAttribute("aria-live", "polite");
    b.setAttribute("aria-describedby", "fwa-r");
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (b.getAttribute("aria-disabled") !== "true") box._fwaOn.press();
    });
    row.addEventListener("click", (ev) => ev.stopPropagation());  // a tap beside the button keeps the box open too
    row.append(b, r); box.append(t, mk("div", "fwa-h"), row);
  }
  const h = box.querySelector(":scope > .fwa-h"), row = box.querySelector(":scope > .fwa-c");
  const b = row.querySelector(".fwa-b"), r = row.querySelector(".fwa-r");
  if (t.textContent !== text) t.textContent = text;
  if (h.textContent !== c.line) h.textContent = c.line;
  h.style.display = c.line ? "" : "none";
  row.style.display = c.show ? "" : "none";
  if (b.textContent !== c.label) b.textContent = c.label;
  b.setAttribute("aria-disabled", String(c.off));  // not disabled: it keeps the focus after a press
  b.setAttribute("aria-busy", String(c.busy));
  if (r.textContent !== c.reason) r.textContent = c.reason;
  r.style.display = c.reason ? "" : "none";
}
// ---- end shared data age ----

const FW_AGE_IDS = { last: "sensor.flight_watcher_last_check", state: "sensor.flight_watcher_state",
  next: "sensor.flight_watcher_next_check", hunt: "switch.flight_watcher_hunt_mode",
  normal: "number.flight_watcher_normal_check_every", huntEvery: "number.flight_watcher_hunt_check_every",
  chk: "button.flight_watcher_check_now", pause: "switch.flight_watcher_pause" };  // 1.7.26: the box's Check now

class FlightWatcherScheduleCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; this._pk = {}; }
  set hass(h) {
    // review r4: the dark colors follow Home Assistant's own dark mode (hass.themes.darkMode, which the portal sets from the device), not the phone's: a profile forced to Light on a phone in dark mode kept the light-on-dark reds
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(h && h.themes && typeof h.themes.darkMode === "boolean" ? h.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
    const sig = ["sensor.flight_watcher_schedule", "input_number.flight_watcher_month_offset", "sensor.flight_watcher_pot_count",
      "sensor.flight_watcher_blocked_days", "sensor.flight_watcher_own_trip_times", "sensor.flight_watcher_tradeboard_pickups",
      "sensor.flight_watcher_would_trade", "sensor.flight_watcher_swap_ideas", "sensor.flight_watcher_reserve_grid",
      "input_number.flight_watcher_federal_tax_pct", "input_number.flight_watcher_state_tax_pct", "input_number.flight_watcher_longevity_year", "input_text.flight_watcher_er_trips", "sensor.flight_watcher_schedule_versions"]
      .map((e) => h.states[e] && `${h.states[e].last_updated}/${h.states[e].state}`).join("|") + "|" + this._doh(h) + (this._isAdmin(h) ? "|admin" : "|pilot") + "|" + this._role(h) + (this._isAdmin(h) ? "|" + ((h.states["sensor.flight_watcher_crewtrac_check"] || {}).last_updated || "") : "");  // 1.7.22: admin only
    // 1.6.2 (Release A item 15): each state too, not only last_updated: the pilot portal keeps the month helper
    // (input_number.flight_watcher_month_offset) in the page, and a step there need not move last_updated
    this._h = h;
    if (!this._ageT && this.isConnected) this._ageT = setInterval(() => this._ageTick(), 1000);  // 1.7.12: it ticks
    if (sig === this._sig) { this._ageTick(); return; }
    this._sig = sig;
    this._render();
  }
  // 1.7.12: the data age stamp (the clock card's), from this card's own entities (the shared block's fwAgeFrom)
  _age() { return fwAgeFrom(this._h && this._h.states, FW_AGE_IDS, Date.now()); }
  // its hover text: FLICA's own schedule time ("FLICA updated ...", the header showed it as "updated" before 1.7.12)
  _ageTitle(a) { return (this._updT ? `FLICA updated ${this._updT}. ` : "") + `Data age: the time since the Watcher's last good read. ${a.read} ${a.rule}`; }
  _ageHtml(upd) {
    this._updT = upd || "";
    const a = this._age();
    // 1.7.26: a button for the keyboard too (Enter or Space opens its box, as a tap does; the redraw closes the box)
    return `<span class="ag" data-age="${a.level}" role="button" tabindex="0" aria-expanded="false" `
      + `title="${this._esc(this._ageTitle(a))}">${this._esc(a.text)}</span>`;
  }
  // 1.7.26: the stamp's box (the shared block's fwAgeBox): its hover text, why reads are held, and its own Check now;
  // opened by a tap (or Enter / Space) on the stamp, refreshed each second while open (_ageTick). 1.7.26 review: the
  // stamp toggles it (a tap, Enter or Space), Esc in the card closes it, the stamp's aria-expanded says which, and from
  // the keyboard the box takes the focus (its Check now is the next Tab, not one after every trip of the month)
  _ageOn() {
    this._fwa = this._fwa || {};
    return { press: () => { fwAgePress(this._h, FW_AGE_IDS, this._fwa, Date.now()); this._ageTick(); },
      close: () => this._ageClose(true) };
  }
  _ageStamp() { return this.shadowRoot && this.shadowRoot.querySelector(".fwm .hd2 .ag[data-age]"); }
  // the box while it is open on the data age (not on another tip), else null
  _ageShown() {
    const box = this.shadowRoot && this.shadowRoot.querySelector(".fwm .info");
    return box && box.style.display === "block" && box.querySelector(":scope > .fwa-t") ? box : null;
  }
  _ageAria() {
    const el = this._ageStamp(), on = String(!!this._ageShown());
    if (el && el.getAttribute("aria-expanded") !== on) el.setAttribute("aria-expanded", on);
  }
  _ageClose(focus) {
    const box = this._ageShown(), el = this._ageStamp();
    if (box) box.style.display = "none";
    this._ageAria();
    if (focus && el) el.focus();
  }
  _ageBoxFill(box, el) {
    fwAgeBox(box, el.title, fwAgeChk(this._h, FW_AGE_IDS, this._fwa || (this._fwa = {}), Date.now()), this._ageOn());
  }
  _ageBoxOpen(el, kb) {
    const box = this.shadowRoot.querySelector(".fwm .info");
    if (!box || !el) return;
    box.textContent = "";  // it may hold another tip
    box.style.whiteSpace = "normal";
    this._ageBoxFill(box, el);
    box.style.display = "block";
    this._ageAria();
    if (kb) box.focus();
  }
  // each second: that span only, never a redraw
  _ageTick() {
    const el = this.shadowRoot && this.shadowRoot.querySelector(".fwm .hd2 .ag[data-age]");
    if (!el || !this._h) return;
    const a = this._age(), title = this._ageTitle(a);
    if (el.textContent !== a.text) el.textContent = a.text;
    if (el.dataset.age !== a.level) el.dataset.age = a.level;
    if (el.title !== title) el.title = title;
    const box = this._ageShown();  // 1.7.26: its box, while open
    if (box) this._ageBoxFill(box, el);
    this._ageAria();  // 1.7.26 review: another tip took the box
  }
  // FW-0010: the pilot's DOH from the state sensor ("" when none is on file or the Watcher is offline); only this
  // value is in the redraw signature, not the sensor's last_updated (its note changes on every check)
  _doh(h) {
    const d = (((h || this._h).states["sensor.flight_watcher_state"] || {}).attributes || {}).doh;
    return /^\d{4}-\d{2}-\d{2}$/.test(d || "") ? d : "";
  }
  // FW-0060 (1.4.7): the schedule versions (each one's items, days, totals and trips) come from versions_<key>.json under
  // /local/; sensor.flight_watcher_schedule_versions keeps only each month's counts (it ran about 33 KB, over HA's
  // 16 KB recorder limit). Until the file is in, no versions bar (and no Improved-Pay-Gross report) is drawn. An older
  // Watcher still sends every version on the sensor.
  _vmonths() {
    const st = this._h.states["sensor.flight_watcher_schedule_versions"];
    const f = fwListFile(this._vf || (this._vf = {}), "/local/flight-watcher/versions_", st, () => { this._sig = null; this.hass = this._h; });
    return (f && f.months) || ((st || {}).attributes || {}).months || {};
  }
  _key() {
    const off =parseInt((this._h.states["input_number.flight_watcher_month_offset"] || {}).state || "0", 10) || 0;
    const d = new Date(); const m = d.getMonth() + off; const y = d.getFullYear() + Math.floor(m / 12);
    return { y, m: ((m % 12) + 12) % 12, key: `${y}-${String(((m % 12) + 12) % 12 + 1).padStart(2, "0")}` };
  }
  _iso(s, y) { // '26Nov' -> '2026-11-26'
    const mm = MON3.indexOf((s || "").slice(2, 5).toUpperCase()); if (mm < 0) return "";
    return `${y}-${String(mm + 1).padStart(2, "0")}-${(s || "").slice(0, 2)}`;
  }
  // US federal and Hawaii state holidays: the shared grid's (fwgHol)
  _hol(iso) { return fwgHol(iso); }
  _easter(y) { return fwgEaster(y); }
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // wall-clock HST as a UTC-based ms value (no time zone maths: everything is HNL local)
  _t(iso, hhmm) { const [h, m] = String(hhmm || "0:0").split(":").map((x) => parseInt(x, 10) || 0); return Date.parse(iso + "T00:00:00Z") + (h * 60 + m) * 60e3; }
  _d(ms) { return new Date(ms).toISOString().slice(0, 10); }
  _hm(ms) { return new Date(ms).toISOString().slice(11, 16); }
  _dur(ms) { const m = Math.round(ms / 60e3); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`; }
  _school(iso) {
    // school year starts in July: 2026-07-01 .. 2027-06-30 -> school_2026-27.json (swaps by itself each July)
    const y = parseInt(iso.slice(0, 4), 10), m = parseInt(iso.slice(5, 7), 10);
    const sy = m >= 7 ? y : y - 1; const key = `${sy}-${String((sy + 1) % 100).padStart(2, "0")}`;
    this._sc = this._sc || {};
    if (this._role() !== "admin") return false;  // 1.6.2: a pilot has no school calendar file; holidays only, no fetch
    if (this._sc[key] !== undefined) return this._sc[key];
    this._sc[key] = null;
    fetch(`/local/flight-watcher/school_${key}.json?v=1`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : false)).then((j) => {
      if (!j) { this._sc[key] = false; return; }
      const days = new Set(j.closed || []);
      for (const [a, b] of (j.ranges || [])) { for (let t = Date.parse(a + "T00:00:00Z"); t <= Date.parse(b + "T00:00:00Z"); t += 864e5) days.add(new Date(t).toISOString().slice(0, 10)); }
      this._sc[key] = { name: j.name || key, days }; this._sig = null; this.hass = this._h;
    }).catch(() => { this._sc[key] = false; });
    return null;
  }
  // the month's pairings package (fwgPack): its {id: entry} map, null while it loads, false when there is none.
  // 1.7.1 (F#32): a package known to be missing redraws too, so the month's Improved-Pay-Gross is reported then
  _pack(key) { const e = this._packE(key); return e ? e.map : e; }
  _packE(key) { return fwgPack(this._pk, PAIRINGS_URL, key, () => { this._sig = null; if (this._h) this.hass = this._h; }); }
  // FW-0048 (Ryan, Nov 6): the auto swap / auto drop / auto add tools stay hidden for every user but Ryan until he
  // turns them on for others. Here that is the DROP mark (it composes a drop request, Test mode); the trade mark and the
  // swap / pick-up ideas are read only and stay for everyone. Ryan is the HA owner (HA has exactly one), so the viewer
  // test is is_owner, not is_admin: Pako has another admin login, and a second pilot's account may be made an admin.
  // 1.5.0 (FW-0063): the Watcher's role must say so too: sensor.<prefix>_state attribute role is "admin" on Ryan's
  // instance only, so a pilot's copy of this card never shows the drop mark, even to the owner, and Ryan's card shows it
  // to the owner only, as in 1.4.12. A hass with no user yet is not the owner (the card redraws when the user arrives).
  // 1.6.2 (item 14): the Watcher's role ("admin" on the admin's own instance only); the school calendar (HPA, the
  // admin's household) is read and named on the admin's card only, never on a pilot's
  _role(h) { const s = ((h || this._h || {}).states || {})["sensor.flight_watcher_state"]; return (s && s.attributes && s.attributes.role) || ""; }
  _isAdmin(h) { const hh = h || this._h || {}; const s = (hh.states || {})["sensor.flight_watcher_state"]; return !!(s && s.attributes && s.attributes.role === "admin" && hh.user && hh.user.is_owner); }
  // 1.7.20 (Hark, Ryan Nov 20, 2026): the PWA credit lines of a trip's Pay-Gross breakdown (fwPwaTrip): which test won,
  // each segment, the rig, the minimum, delay vs reassignment, and the check against FLICA's credit
  _pwaLines(pa, F, hm, mdy) {
    const t = (m) => (m == null ? "?" : hm(m / 60)), out = [];
    const seg = pa.segs.map((s) => `${s.stn ? `to ${s.stn} ` : ""}${mdy(s.day)} ${t(s.act)} actual${s.sch != null ? ` / ${t(s.sch)} sched = ${t(s.cr)}` : ""}${s.delay != null && s.delay >= 60 ? ` (left ${t(s.delay)} late)` : ""}`).join("; ");
    const won = { gop: "GOP", rig: "Trip Rig", mdg: "MDG" }[pa.won];
    out.push(`PWA credit ${t(pa.pwa)} = the greater of (PWA 4.C.3.a): GOP ${t(pa.gop)} (4.B.1, each segment the greater of actual or scheduled block: ${seg}); Trip Rig ${t(pa.rig)} (1:3.5 of TAFB ${t(pa.tafb)}, 4.C.3.a.4); MDG ${t(pa.mdg)} (5:00 x ${pa.days} calendar day${pa.days > 1 ? "s" : ""}, 4.C.3.a.5). ${won} wins.`);
    if (!pa.mine) { out.push("These duty times come from a pairing page whose crew list does not name you (crew OPEN or not read): the PWA tests above are not applied; FLICA's credit kept, no LODO."); return out; }
    if (!pa.match) out.push(pa.sRel == null ? "Scheduled block not on file (no pairings package for this trip on this day): GOP uses actual block only." : "The legs differ from the pairings package (a reassignment or a rebuilt trip): FLICA's credit kept (pay protection, PWA 4.D.2.b).");
    if (pa.brk) {
      const b = pa.segs.find((s) => s.brk) || {};
      out.push(`Broken duty (ALPA DART 417120, HAL ALPA Paycheck Issues, Nov 22, 2026): you reported for the original ${mdy(b.day || "")} duty, were released, and re-reported for the delayed operation (${pa.brk === "ct" ? "CrewTrac books the original duty as a protected NF2 duty" : `scheduled report to release ${t(pa.brkSpan)}, over the ${t(pa.brkMax)} duty a ${pa.n || "?"}-pilot crew can be held on (PWA 10.D.1), so it was not one continuous duty`}). The original duty is credited at its scheduled ${t(pa.prot)} (pay protection, PWA 4.C.3.a) and the re-reported operation is its own duty period (greater of actual or scheduled, 4.B.1): no delay cut (PWA 2.A.15.a.1's one segment does not apply). LODO 4:00 pay, no credit, when the release lands on a day off (PWA 4.D.2.e).`);
      if (pa.flica != null) out.push(Math.abs(pa.flica - pa.pwa) <= 5 ? `PWA check: FLICA's ${t(pa.flica)} matches the broken-duty credit ${t(pa.pwa)}${pa.flica !== pa.pwa ? " (within 0:05)" : ""}; FLICA kept.` : `PWA check: FLICA ${t(pa.flica)}, broken-duty PWA credit ${t(pa.pwa)} (${pa.flica > pa.pwa ? "FLICA higher" : "FLICA lower: check it"}; FLICA kept).`);
      if (pa.kept && pa.flica != null) out.push(`FLICA's ${t(pa.flica)} kept: ${pa.kept === "ct" ? "CrewTrac books the same credit" : "marked to match CrewTrac"} (CrewTrac controls).`);
    } else if (pa.kept && pa.delayed && !pa.passed && pa.flica != null && pa.flica - pa.pwa >= 30) out.push(`FLICA's ${t(pa.flica)} kept: ${pa.kept === "ct" ? "CrewTrac books the same credit" : "marked to match CrewTrac"} (a reassignment with a protected leg, PWA 4.D.2.b; CrewTrac controls), so no delay cut.`);
    else if (pa.fix) out.push(`FLICA shows ${t(pa.flica)}: the delayed leg counted twice (the original and the delayed one). A delay, not a reassignment (PWA 2.A.15.a.1: only the time changed, before the next day's operation of that flight): one segment (4.B.1). FW counts ${t(pa.use)}, ${t(pa.cut)} less.`);
    else if (pa.passed) out.push("A leg left 24 h or more late (it may pass the next operation of that flight: a reassignment, PWA 2.A.15): FLICA's credit kept (pay protection, 4.D.2.b).");
    else if (pa.flica != null) out.push(Math.abs(pa.flica - pa.pwa) <= 1 ? `PWA check: matches FLICA's ${t(pa.flica)}.` : `PWA check: FLICA ${t(pa.flica)}, PWA tests ${t(pa.pwa)}${pa.flica > pa.pwa ? " (FLICA higher: segment credits or legs the duty times do not show; FLICA kept)" : " (FLICA lower: check it; FLICA kept)"}.`);
    if (pa.sRel != null && pa.aRel > pa.sRel && !pa.lodoDays.length) out.push(`Released after the scheduled footprint, but not on a day off: no LODO (PWA 4.D.2.e).`);
    if (pa.delayed && !pa.fix && !pa.passed && !pa.kept && !pa.brk) out.push("Delayed leg counted once (PWA 2.A.15.a.1, 4.B.1).");
    return out;
  }
  _marks() { return this._isAdmin() ? "availability, trade and drop marks" : "availability and trade marks"; }
  // 1.7.18 (Nov 17: the lock did not show well on a Samsung phone, and it was not obvious when it was locked or
  // unlocked): a switch, On = locked (the default). The lock icon (fwsLockSvg), the word Lock, a track with its knob
  // (right = On) and the word On or Off, so the state never rests on colour alone. One button with role switch and
  // the name "Lock schedule marks": a tap, Enter or Space flips it (the click handler's .lock), its title says what it
  // freezes as before, and the stored value is the same (flight_watcher_lock, "0" = unlocked). On a phone (700 px or
  // less) it has the header's first line to itself, so the month's arrows, title and Now stay together on the next
  _lockHtml() {
    const on = this._locked;
    const t = on ? `Locked: ${this._marks()} cannot be changed by a tap. Tap to unlock.` : `Unlocked: taps change ${this._marks()}. Tap to lock.`;
    return `<button type="button" class="lock ${on ? "shut" : "open"}" role="switch" aria-checked="${on ? "true" : "false"}" aria-label="Lock schedule marks" title="${t}">` +
      `${fwsLockSvg(on)} <span class="lkl">Lock</span> <span class="lkt"><span class="lkk"></span></span> <span class="lks">${on ? "On" : "Off"}</span></button>`;
  }
  _say(msg) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = msg; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } }
  _render() {
    if (this._locked === undefined) { let v = "1"; try { const g = localStorage.getItem("flight_watcher_lock"); v = g === null ? "1" : g; } catch (e) { v = "1"; } this._locked = v !== "0"; }  // v48: locked by default
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      // 1.7.7: the redraws write .fwm only; .fwsh holds the narrow card's bottom sheet (FwgSheet), kept across them
      this.shadowRoot.innerHTML = '<div class="fwm"></div><div class="fwsh" hidden></div>';
      this._sheet = new FwgSheet(this.shadowRoot.querySelector(".fwsh"), () => this._pdClose(true));
      this.shadowRoot.addEventListener("keydown", (e) => {  // a pairing is a button: Enter or Space opens its detail
        const t = e.target && e.target.closest ? e.target.closest(".trip[data-k]") : null;
        if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); this._pdToggle(t.dataset.k); }
        const ag = e.target && e.target.closest ? e.target.closest(".hd2 .ag[data-age]") : null;  // 1.7.26
        if (ag && (e.key === "Enter" || e.key === " ")) {  // 1.7.26 review: it toggles the box
          e.preventDefault();
          if (this._ageShown()) this._ageClose(false); else this._ageBoxOpen(ag, true);
        } else if (e.key === "Escape" && this._ageShown() && !(e.target.closest && e.target.closest(".fwsh"))) {
          this._ageClose(true);  // Esc in the card (not in a pairing's sheet) closes the data age box
        }
      });
      this.shadowRoot.addEventListener("click", (e) => {
        // 1.7.7 (Ryan, Nov 14): a tap on a pairing opens its detail (below the grid, or a bottom sheet on a phone); the
        // same pairing again, the close button, the sheet's backdrop or Esc closes it, another pairing swaps it. It only
        // reads, so the lock does not apply; "would trade" is the arrow mark's (.trb) alone
        if (e.target.closest(".pdx, .fwsb")) { this._pdClose(true); return; }
        const pt = e.target.closest(".trip[data-k]");
        if (pt) { this._pdToggle(pt.dataset.k); return; }
        const vb = e.target.closest(".vb");  // v51: schedule versions
        if (vb) { const k = this._key().key; const n = ((this._vmonths()[k] || {}).versions || []).length;
          let i = this._vsel && this._vsel[k] != null ? this._vsel[k] : n - 1; const a = vb.dataset.v;
          i = a === "home" ? n - 1 : a === "prev" ? Math.max(0, i - 1) : Math.min(n - 1, i + 1);
          this._vsel = this._vsel || {}; this._vsel[k] = i; this._sig = null; this._render(); return; }
        const ib2 = e.target.closest(".idb");  // v51: ideas panel below the schedule
        if (ib2) { const k = this._key().key; const cur = this._idea; this._idea = cur && cur.key === k && cur.d === ib2.dataset.d ? null : { key: k, d: ib2.dataset.d, trip: ib2.dataset.trip };
          this._render(); const pn = this.shadowRoot.querySelector(".ipanel"); if (pn) pn.scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
        if (e.target.closest(".ix")) { this._idea = null; this._render(); return; }
        const lk = e.target.closest(".lock");  // v48 (Ryan): lock / unlock the tap settings (blocked days, trade, drop)
        if (lk) { this._locked = !this._locked; try { localStorage.setItem("flight_watcher_lock", this._locked ? "1" : "0"); } catch (e2) { /* ignore */ } this._render(); return; }
        const locked = this._locked;
        const db = e.target.closest(".drb");
        if (db && !this._isAdmin()) return;  // FW-0048, FW-0063: drawn for the owner on the admin's card only; ignore a stale one
        if (db && locked) { this._say(`Settings are locked: turn the Lock switch at the top left Off to change ${this._marks().replace(" and ", " or ")}.`); return; }
        if (db && db.dataset.k) {
          db.classList.toggle("on");
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/drop/set", payload: JSON.stringify({ key: db.dataset.k }) });
          return;
        }
        const tp = e.target.closest(".trb");  // 1.7.7: the pairing itself opens its detail
        if (tp && tp.dataset.k && tp.dataset.k.split("|")[1] <= new Date(Date.now() - 10 * H).toISOString().slice(0, 10)) return;  // v46: a started trip cannot be traded
        if (tp && tp.dataset.k && locked) { this._say(`Settings are locked: turn the Lock switch at the top left Off to change ${this._marks().replace(" and ", " or ")}.`); return; }
        if (tp && tp.dataset.k) {
          const row = tp.closest("td"); row.querySelector(".trip").classList.toggle("tr"); row.querySelector(".trb").classList.toggle("on");
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/trade/set", payload: JSON.stringify({ key: tp.dataset.k }) });
          return;
        }
        // 1.6.2 review: the RO+15% toggle sits inside the Pay-Gross info box, so it is read before a tap there closes it
        // 1.7.20: the recall mark ('R+KEY' in the same list) sits in the Pay-Gross info box too
        const rc = e.target.closest(".rcl");
        if (rc && rc.dataset.k) {
          const cur = String((this._h.states["input_text.flight_watcher_er_trips"] || {}).state || "").split(",").filter(Boolean);
          const k = rc.dataset.k, on = rc.classList.contains("on");
          const next = cur.filter((x) => !(x === "R+" + k || x.startsWith("R+" + k + "@"))).concat(on ? [] : ["R+" + k]);
          this._h.callService("input_text", "set_value", { entity_id: "input_text.flight_watcher_er_trips", value: next.join(",") });
          return;
        }
        const er = e.target.closest(".er");
        if (er && er.dataset.k) {
          const cur = String((this._h.states["input_text.flight_watcher_er_trips"] || {}).state || "").split(",").filter(Boolean);
          const k = er.dataset.k, on = er.classList.contains("on");
          const next = cur.filter((x) => x.slice(1) !== k || x.startsWith("R+")).concat(on ? ["-" + k] : ["+" + k]);
          this._h.callService("input_text", "set_value", { entity_id: "input_text.flight_watcher_er_trips", value: next.join(",") });
          return;
        }
        const ib = e.target.closest(".info"); if (ib) { ib.style.display = "none"; this._ageAria(); return; }
        const nv = e.target.closest(".nav");
        if (nv) {
          const d = parseInt(nv.dataset.nav, 10), ent = { entity_id: "input_number.flight_watcher_month_offset" };
          if (d === 0) this._h.callService("input_number", "set_value", { ...ent, value: 0 });
          else this._h.callService("input_number", d > 0 ? "increment" : "decrement", ent);
          return;
        }
        const py = e.target.closest(".pay");
        if (py) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.innerHTML = this._esc(py.dataset.info).replace(/\n/g, "<br>") + "<br>" + py.dataset.btn; box.style.display = "block"; } return; }
        const tg = e.target.closest(".tag");
        if (tg) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = tg.title; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } return; }
        if (e.target.closest(".set")) return;
        const ag = e.target.closest(".hd2 .ag[data-age]");  // 1.7.26: the data age stamp opens its own box
        if (ag) { if (this._ageShown()) this._ageClose(false); else this._ageBoxOpen(ag); return; }  // review: toggles
        const tt = e.target.closest("span[title], th[title], b[title]");
        if (tt && tt.title) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = tt.title; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } return; }
        const dc = e.target.closest("td"); if (!dc || dc.cellIndex > 1) return;  // v43 (Ryan): only the day/date cells toggle a blocked day
        const tr = e.target.closest("tr[data-d]"); if (!tr || !this._h) return;
        if (tr.classList.contains("vac")) { this._say("Vacation day: always unavailable."); return; }  // v48 (Ryan): VAC days cannot be toggled
        if (locked) { this._say(`Settings are locked: turn the Lock switch at the top left Off to change ${this._marks().replace(" and ", " or ")}.`); return; }
        tr.classList.toggle("blk");
        this._h.callService("mqtt", "publish", { topic: "flight_watcher/blocked/set", payload: JSON.stringify({ date: tr.dataset.d }) });
      });
    }
    const S = this._h.states;
    const hm = (h) => { const mm = Math.round(h * 60); return `${Math.floor(mm / 60)}:${String(mm % 60).padStart(2, "0")}`; };
    const num = (e, d) => { const v = parseFloat((S[e] || {}).state); return isNaN(v) ? d : v; };
    const fed = num("input_number.flight_watcher_federal_tax_pct", 22), stt = num("input_number.flight_watcher_state_tax_pct", 0);
    const today = new Date(Date.now() - 10 * H).toISOString().slice(0, 10);
    const doh = this._doh();
    const admin = this._isAdmin();  // FW-0048, FW-0063: the drop mark (auto drop) for the HA owner on the admin's (Ryan's) card only
    // 1.6.2 review: no longevity year set and no real DOH: no rate at all (the placeholder DOH gave year 12), the
    // banner asks for it and no Improved-Pay-Gross goes out until it is set
    // 1.6.4: with a DOH on file (the Settings card's Date of hire), a year still flagged unconfirmed (copied from a
    // never-set helper) yields to the DOH's year; a year the pilot chose (set here, or Keep these) still wins, as the
    // admin's own helper does (it is never flagged)
    const lySt = S["input_number.flight_watcher_longevity_year"] || {};
    const lyByDoh = !!doh && (lySt.attributes || {}).unconfirmed === true;
    const lyPicked = !lyByDoh && !isNaN(parseFloat(lySt.state));
    const noYear = !lyPicked && !doh;
    const lyr = noYear ? null : lyPicked ? parseFloat(lySt.state) : Math.min(12, dohYear(today, doh));
    const RATE = noYear ? NaN : rateFor(lyr, today);
    const rateTxt = noYear ? "your rate (set your longevity year)" : `$${RATE.toFixed(2)}`;
    const erOv = String((S["input_text.flight_watcher_er_trips"] || {}).state || "").split(",").filter(Boolean);
    // 1.7.20 (Hark, Ryan Nov 20, 2026): the type-rated FO's 15% (PWA 4.O.1.b) only on a trip marked '+KEY' (the Pay-Gross
    // tap): never by itself for SIN or a 4-pilot crew, where an FO or RO is paid $3.00 per block hour
    const erOn = (k) => !erOv.includes("-" + k) && erOv.includes("+" + k);
    // v51: pilots on the pairing from the package crew line (CA01FO01RO01 = 3 = IRO crew; CA02FO02 = 4 = Extended Range crew, PWA 2.A.25); 1.7.20: a number, or FLICA's crew list (fwCrewOwn)
    const crewN = (c) => typeof c === "number" ? c : Array.isArray(c) ? fwCrewOwn(c) : (String(c || "").match(/\d{2}/g) || []).reduce((a, x) => a + parseInt(x, 10), 0);
    // 1.7.20: a trip's pilots: the most of the package crew line (the row, else its detail) and FLICA's own crew list
    const nOf = (pr, ot) => Math.max(crewN((pr && (pr.crew || (pr.det && pr.det.crew))) || ""), crewN(Array.isArray(ot && ot.crew) ? ot.crew : []));
    const hx = (v) => hrs(String(v || "").replace("h", ":"));
    const blocked = new Set(((S["sensor.flight_watcher_blocked_days"] || {}).attributes || {}).days || []);
    const dropA = admin ? (S["sensor.flight_watcher_would_drop"] || {}).attributes || {} : {};  // FW-0063: no Would drop on a pilot
    const dropM = new Set(dropA.keys || []), dropR = dropA.ready || {};
    const st = S["sensor.flight_watcher_schedule"];
    const SM = (st && st.attributes && st.attributes.months) || {};  // 1.6.2: no month read yet is no error
    const { y, m, key } = this._key();
    if (this._pd && this._pd.key !== key) this._pd = null;  // 1.7.7: the pairing detail closes on a month change
    const narrow = !!this._pd && fwgNarrow(this._hc());
    let mon = SM[key] || null;
    // v51 (Ryan): schedule versions MM.NNN; arrows step through them, the house returns to the current one
    const VS = this._vmonths();
    const vl = (VS[key] || {}).versions || [];
    this._vsel = this._vsel || {};
    let vi = this._vsel[key]; if (vi == null || vi < 0 || vi >= vl.length - 1) vi = null;
    const vsel = vi != null ? vl[vi] : null;
    const liveMon = mon;
    if (vsel && mon) mon = { ...mon, items: vsel.items || [], days: vsel.days || [], totals: vsel.totals || {}, updated: vsel.updated || "" };
    // 1.6.2 (Release A): no FLICA read of this month yet, but the award file's line is on file (version .001): draw it,
    // labeled, until a read lands (no versions bar and no Improved-Pay-Gross report from it)
    const awd0 = !mon ? (vl.find((v) => v.award) || null) : null;
    if (awd0) mon = { items: awd0.items || [], days: awd0.days || [], totals: awd0.totals || {}, updated: awd0.updated || "" };
    // 1.6.2: the last FLICA read's status (sensor read_status): why it was not read, when, and the next try (HST)
    const rs = (st && st.attributes && st.attributes.read_status) || {};
    const rsLine = rs.ok === false ? `FLICA schedule not read: ${rs.why || "no page accepted"}${rs.at_hst ? ` at ${rs.at_hst} HST` : ""}${rs.next_hst ? `; next try ${rs.next_hst} HST` : ""}` : "";
    const pot = ((S["sensor.flight_watcher_pot_count"] || {}).attributes || {}).pairings || [];
    const tb = ((S["sensor.flight_watcher_tradeboard_pickups"] || {}).attributes || {}).pairings || [];
    const liveOwnT = ((S["sensor.flight_watcher_own_trip_times"] || {}).attributes || {}).trips || {};
    // 1.7.22 (Hark): the CrewTrac check, the admin's only (Hark reads CrewTrac for Ryan; a pilot's card shows nothing)
    const ctSnap = admin ? ((S["sensor.flight_watcher_crewtrac_check"] || {}).attributes || {}).snapshot || null : null;
    // v51c: a version keeps its own block / credit / times but inherits fields it never recorded (seat, crew) from the live
    // record of the same trip, so an early version of a trip still pays the seat override (PWA 4.O.1)
    const mergeT = (live, ver) => { const o = { ...live }; for (const [k, v] of Object.entries(ver || {})) o[k] = { ...(live[k] || {}), ...v }; return o; };
    const ownT = vsel ? mergeT(liveOwnT, vsel.trips) : awd0 ? mergeT(liveOwnT, awd0.trips) : liveOwnT;
    const pk = this._pack(key);
    // 1.7.11 (FW-0080): the bid period this month's totals cover, as FLICA's do (never the calendar month): the month's
    // pairings package's start..end, else the Watcher's (sensor periods: the pairing files, else the schedule pages),
    // else the calendar month; the totals line says which
    const pkE = this._packE(key), perW = ((st && st.attributes && st.attributes.periods) || {})[key] || null;
    const bp = pkE && FWG_ISO.test(pkE.start || "") && FWG_ISO.test(pkE.end || "") ? { from: pkE.start, to: pkE.end, src: "package" }
      : perW && FWG_ISO.test(perW.start || "") && FWG_ISO.test(perW.end || "") ? { from: perW.start, to: perW.end, src: ["package", "schedule"].includes(perW.src) ? perW.src : "calendar" }
        : { from: `${key}-01`, to: new Date(Date.UTC(y, m + 1, 0)).toISOString().slice(0, 10), src: "calendar" };
    const inBp = (d) => bp.from <= d && d <= bp.to;
    const bpNext = (side) => new Date(Date.UTC(y, m + (side === "before" ? -1 : 1), 1)).toISOString().slice(0, 7);
    const grid = ((S["sensor.flight_watcher_reserve_grid"] || {}).attributes || {}).days || {};
    const trade = new Set(((S["sensor.flight_watcher_would_trade"] || {}).attributes || {}).keys || []);
    const swaps = ((S["sensor.flight_watcher_swap_ideas"] || {}).attributes || {}).ideas || [];
    const swapFor = {};
    for (const i of swaps) (swapFor[i.for] = swapFor[i.for] || []).push(i);
    let body = "", note = "", chtml = "", vhtml = "", panel = "";
    let pdM = null, pdK = "";
    const pdDays = new Set();
    if (!mon) {
      body = `<div class="none">No schedule for ${MONTHS[m]} yet.</div>`;
    } else {
      const items = mon.items || [];
      const prevKey = new Date(Date.UTC(y, m - 1, 1)).toISOString().slice(0, 7);
      const prevItems = (SM[prevKey] || {}).items || [];
      const nextKey = new Date(Date.UTC(y, m + 1, 1)).toISOString().slice(0, 7);
      const nextItems = (SM[nextKey] || {}).items || [];
      // 1.7.11 review: the three months' items, each trip and start once (the own list's rule, this month's copy
      // first). A trip in progress from the month before (H3607 Nov 30 to Dec 2) has no code day on a page that
      // starts Dec 1, so this month's items alone miss it: the Open column's clash test, the layover cell and the
      // in-progress mark read these, as the Watcher's schedule_fit reads every month
      const near = [], nearSeen = new Set();
      for (const it of [...items, ...prevItems, ...nextItems]) {
        if (!it || !it.trip || nearSeen.has(`${it.trip}|${it.start}`)) continue;
        nearSeen.add(`${it.trip}|${it.start}`);
        near.push(it);
      }
      const busy = (a, b) => near.find((it) => a <= (it.end || it.start) && b >= it.start);
      const inTrip = (d) => near.some((it) => it.trip !== "VAC" && it.trip !== PAYP && it.start <= d && d <= (it.end || it.start));
      const opens = {};
      for (const p of pot) {
        const a = this._iso(p.start || (p.dates || "").split("-")[0], y);
        const b = this._iso(p.end || (p.dates || "").split("-")[1] || p.start, y) || a;
        if (!a) continue;
        const clash = busy(a, b) || ([...blocked].find((d) => a <= d && d <= b) ? { trip: "a blocked day" } : null);
        const city = (p.layover && !/none/i.test(p.layover)) ? p.layover : (p.turn || "");
        (opens[a] = opens[a] || []).push(`<span class="${clash ? "clash" : "fit"}" title="${clash ? "clashes with " + this._esc(clash.trip) : "fits"}">${city ? this._esc(city) : ""}(${this._esc(p.pairing)})</span>`);
      }
      // own trips: report / release (app times first, then the pairing package)
      const own = [];
      // 1.7.11 (Ryan, Nov 17: "over block on Dec 02?"): a trip across a month end (H3607 Nov 30 to Dec 2) is on both
      // months' schedules; it is ONE trip, so it enters own (and the FAR legs, duties, rest) once (recall.line_records'
      // rule). FLICA gives a trip in progress no code day on a later page: a page lists it at its start or not at all
      const ownSeen = new Set();
      for (const it of [...prevItems, ...items, ...nextItems]) {
        if (it.trip === "VAC" || !/^[A-Z]\d{4}/.test(it.trip || "")) continue;
        if (ownSeen.has(`${it.trip}|${it.start}`)) continue;
        ownSeen.add(`${it.trip}|${it.start}`);
        const t = ownT[`${it.trip}|${it.start}`] || {};
        const p = pk ? pk[it.trip.slice(0, 5)] : null;
        let rep = null, rel = null;
        if (t.report) rep = this._t(it.start, t.report);
        else if (p && p.days.has(it.start)) rep = this._t(it.start, p.report);
        if (p && p.days.has(it.start)) rel = this._t(it.start, p.release) + p.relDays * 24 * H;
        else if (t.last_arr) {
          // trip not in the package: it ends on the first later day the schedule shows back in HNL. 1.7.11 review: a
          // day of its own only (after its start, up to its end), on this page or its own month's: the first HNL day
          // on this page after a trip from the month before is a later trip's (Dec 2 for every November trip in the
          // December view), and an end with no HNL day (the next trip starts that day) is the item's end
          const last = it.end || it.start;
          const back = [...(mon.days || []), ...((SM[String(it.start).slice(0, 7)] || {}).days || [])]
            .filter(([d, tr, ly]) => d > it.start && d <= last && !tr && ly === "HNL").map(([d]) => d).sort()[0];
          const end = back || last;
          rel = this._t(end, t.last_arr) + 15 * 60e3; if (rep && rel <= rep) rel += 24 * H;
        }
        own.push({ it, rep, rel });
      }
      own.sort((a, b) => (a.it.start < b.it.start ? -1 : 1));
      const repOn = {}, relOn = {}, legalOn = {};
      for (const o of own) {
        if (o.rep) repOn[o.it.start] = this._hm(o.rep);
        if (o.rel) {
          relOn[this._d(o.rel)] = this._hm(o.rel);
          // legal to report for another trip: release + 11 h (PWA 10.E.1.a; covers FAR 117 10 h rest).
          // 18 h applies instead before a 12 h+ duty period departing 1400-0359 (PWA 10.E.1.b).
          const l11 = o.rel + 11 * H, l18 = o.rel + 18 * H;
          const dd = (ms) => (this._d(ms) === this._d(o.rel) ? "" : " +1");
          legalOn[this._d(o.rel)] = { t: this._hm(l11) + dd(l11), t18: this._hm(l18) + dd(l18), rel: this._hm(o.rel) };
        }
      }
      // Duty periods (app 0.4.15 `duties`: HST minutes from the trip's first day) or, without them, the whole trip.
      // Report = first departure - 1:00 (trip report when known), release = last arrival + 0:15 (PWA 2, 4.2.2).
      const duties = [];
      for (const o of own) {
        const t = ownT[`${o.it.trip}|${o.it.start}`] || {};
        const base = this._t(o.it.start, "0:0");
        if (t.duties && t.duties.length) {
          t.duties.forEach((du, k) => duties.push({
            start: k === 0 && o.rep ? o.rep : base + (du.dep - 60) * 60e3, end: base + (du.arr + 15) * 60e3, stn: du.stn, trip: o.it.trip }));
        } else if (o.rep && o.rel) duties.push({ start: o.rep, end: o.rel, stn: "", trip: o.it.trip });
      }
      // v49 (Ryan, Nov 5): training and reserve days are duty too (FAR 117.25(b) needs 30 h free from ALL duty): whole day HST.
      // VAC, SICK, GDO, O/K, RISK and other codes stay free.
      const DUTY_CODE = /^(SIM|OEB|OE\b|IOE|GS|GRD|TRN|TRG|TRAIN|CQ|RQ|PC|PT\b|LOE|LOFT|CBT|SCR|RSV|RES|SBY|ASB|AIR)/;
      for (const mk of Object.keys(SM)) for (const it of (SM[mk].items || [])) {
        if (!it.trip || /^[A-Z]\d{4}/.test(it.trip) || !DUTY_CODE.test(it.trip)) continue;
        duties.push({ start: this._t(it.start, "0:0"), end: this._t(it.end || it.start, "0:0") + 24 * H, stn: "", trip: it.trip });
      }
      duties.sort((a, b) => a.start - b.start);
      const nowHst = Date.now() - 10 * H;
      const mkeys = Object.keys(SM).sort();
      const dataStart = Date.parse((mkeys[0] || key) + "-01T00:00:00Z");
      const lastK = mkeys[mkeys.length - 1] || key;
      const dataEnd = Date.UTC(+lastK.slice(0, 4), +lastK.slice(5, 7), 1);
      // free windows between duties (and the open one after the last duty)
      const frees = [];
      for (let i = 0; i < duties.length; i++) {
        const a = duties[i].end, b = i + 1 < duties.length ? duties[i + 1].start : Infinity;
        if (b > a) frees.push({ a, b, at: duties[i].stn, after: duties[i].trip });
      }
      if (duties.length && duties[0].start > dataStart) frees.unshift({ a: dataStart, b: duties[0].start, at: "HNL", after: "" });
      // v50 (Ryan, Nov 5): mark EVERY 30 h+ break (FAR 117.25(b)), past and future; a long layover counts. Each break
      // covers any report up to 138 h after it ends (168 h look-back minus the 30 h it must fill).
      // FW-0004 (Ryan, Nov 6): no teal row background any more (FAR-30/7 carries the check and date); a thin teal edge
      // on the day cell is the only mark, and the date cell's hover still gives the break's window.
      const r30 = new Set(); const r30Notes = {};
      for (const f of frees) {
        const b = Math.min(f.b, dataEnd);
        if (b - f.a < 30 * H) continue;
        const txt = `30 h break: ${this._hm(f.a)} ${this._d(f.a)}${f.at && f.at !== "HNL" ? " at " + f.at : ""} to ${f.b >= dataEnd ? "end of schedule on file" : this._hm(f.b) + " " + this._d(f.b)}, ${f.b >= dataEnd ? "" : this._dur(f.b - f.a) + ", "}covers reports until ${f.b >= dataEnd ? "beyond the schedule on file" : this._hm(f.b + 138 * H) + " " + this._d(f.b + 138 * H)}`;
        for (let t = f.a; t < b; t += 24 * H) { const k = this._d(t); r30.add(k); r30Notes[k] = txt; }
        const ke = this._d(b - 60e3); r30.add(ke); r30Notes[ke] = txt;
      }
      // v49 (Ryan, Nov 5): FAR columns on EVERY day, looking back and forward.
      // 30/7 (117.25(b)): longest free block in the 168 h before a report that day: the real duty start on a duty day,
      // 00:01 on an open day; blank on a mid-trip day with no duty start. 1.7.13 review: 00:01 is not the worst case (a
      // later report that day can lose the break off the back of its 168 h), so the tick speaks for that one report
      // and its title gives 'covers reports until'.
      // 100/672 (117.23(b)(1)): leg block in the 672 h ending 24:00 that day (the 100h in 672h cell). Room = 100:00 minus
      // the busiest 672 h window that holds any part of the day, back and forward. 1.7.13 (F1, Ryan Nov 18: "fix all of
      // these things"): it tries the windows ending 24:00 HST (k = 0 to 27 below, leg by leg as the 100h cell counts
      // them, so Room never shows more room than that cell) and far._cum's: each 672 h starting at a duty's start or
      // ending at its block-in, where the busiest one always is, a block counting when its whole span is in the window
      // (far._cum's sure count on recall._trip's spans, farSpans), so Room reads over wherever a pickup's FAR check finds
      // a window over 100:00 that holds the day. A window holds the day when it holds part of it (far._cum: a window
      // holding part of the pickup), so it ends after 00:00 that day and starts before 24:00.
      // 1.7.13: headed "30h in 7d", "100h in 672h" and "Room to 100h"; the two flight time cells show what is left of
      // the 100:00 (farLeft), the 30 h cell its states with units (far30Txt).
      // 1.7.13 FAR review (R2, R3): a trip with a duty block missing counts its whole Block, as far.py does (recall._trip
      // puts it on one span from report to last block-in): the duties with a block as before, the rest of the Block on
      // the duties without one (departure to arrival, shared by their length), else on far.py's span (farSpans); with no
      // trip Block its duties with a block count and it reads "~". A trip with no duties ends its leg at the last
      // block-in (o.rel less the 15 min debrief, PWA 2.19.b), as far.py's span does
      const legs = [], unk = [];
      const atMin = (iso, mn) => this._t(iso, "0:0") + mn * 60e3;
      for (const o of own) {
        const t = ownT[`${o.it.trip}|${o.it.start}`] || {}; const base = this._t(o.it.start, "0:0"), n0 = legs.length;
        // duty blk can carry credit on some trips, so each trip's legs are scaled to FLICA's trip Block
        const dsum = (t.duties || []).reduce((sm, du) => sm + (du.blk || 0), 0) / 60, tb = hrs(t.blk), sc = tb != null && dsum > 0 ? Math.min(1, tb / dsum) : 1;
        const noBlk = (t.duties || []).filter((du) => du.blk == null || du.blk === ""), miss = noBlk.length > 0;
        const span = (du) => { const d0 = farInt(du && du.dep), d1 = farInt(du && du.arr); return d0 != null && d1 != null && d1 > d0 ? d1 - d0 : 0; };
        const nbLen = noBlk.reduce((sm, du) => sm + span(du), 0), rest = tb != null ? Math.max(0, tb - dsum * sc) : null;
        const one = miss && tb != null && !noBlk.every((du) => span(du) > 0) ? farSpans(o.it, t, atMin).filter((sp) => sp.e > sp.s)[0] : null;
        if (one) legs.push({ a: one.s, b: one.e, h: tb });
        else if (t.duties && t.duties.length) {
          t.duties.forEach((du) => { if (du.blk) legs.push({ a: base + (du.arr - du.blk) * 60e3, b: base + du.arr * 60e3, h: du.blk / 60 * sc }); });
          if (miss && rest) noBlk.forEach((du) => legs.push({ a: base + farInt(du.dep) * 60e3, b: base + farInt(du.arr) * 60e3, h: rest * span(du) / nbLen }));
        } else { const bh = hrs(t.blk); if (bh != null && o.rep && o.rel) legs.push({ a: o.rep, b: Math.max(o.rep, o.rel - 15 * 60e3), h: bh }); }
        // 1.7.13 (F3): a trip that adds no block (no times on file: no Block and no duties, a {} record, no record) is
        // not known in full, so a window holding it (its report to release, else its whole days) reads with "~"; so
        // does one whose duties count without the trip's Block when a duty has none (R2: part)
        const part = miss && tb == null && legs.length > n0;
        if ((legs.length === n0 && tb !== 0) || part) {
          const known = o.rep && o.rel && o.rel > o.rep;
          unk.push({ a: known ? o.rep : base, b: known ? o.rel : this._t(o.it.end || o.it.start, "0:0") + 24 * H,
            txt: `${o.it.trip} ${String(o.it.start).slice(5).replace("-", "/")}`, part });
        }
      }
      const blkIn = (w0, w1) => legs.reduce((sm, l) => { const ov = Math.min(l.b, w1) - Math.max(l.a, w0); return ov > 0 ? sm + l.h * Math.min(1, ov / Math.max(1, l.b - l.a)) : sm; }, 0);
      const unkIn = (w0, w1) => unk.filter((u) => u.a < w1 && w0 < u.b);
      const unkTxt = (u) => {
        const none = u.filter((x) => !x.part).map((x) => x.txt), part = u.filter((x) => x.part).map((x) => x.txt);
        return "~ = not known in full: " + [none.length ? `no block times on file yet for ${none.join(", ")} (counted 0:00)` : "",
          part.length ? `no block time on file yet for a duty of ${part.join(", ")} (counted the duties with a block)` : ""].filter(Boolean).join("; ");
      };
      // far._cum's windows (1.7.13 F1), each with its sure block in whole minutes, earliest end first
      const fsp = [];
      for (const o of own) for (const sp of farSpans(o.it, ownT[`${o.it.trip}|${o.it.start}`] || {}, (iso, mn) => this._t(iso, "0:0") + mn * 60e3)) if (sp.h != null) fsp.push(sp);
      const sureIn = (w0, w1) => fsp.reduce((sm, sp) => (sp.s >= w0 && sp.e <= w1 ? sm + sp.h : sm), 0);
      const farWin = fsp.flatMap((sp) => [[sp.s, sp.s + 672 * H], [sp.e - 672 * H, sp.e]])
        .map(([w0, w1]) => ({ a: w0, b: w1, m: Math.round(sureIn(w0, w1) * 60) })).sort((x, y) => x.b - y.b);
      const winEnd = (ms) => (ms % (24 * H) === 0 ? `24:00 ${this._d(ms - 1)}` : `${this._hm(ms)} ${this._d(ms)}`);
      const free30 = (R) => { const w0 = R - 168 * H; let big = null;
        for (const f of frees) { const a0 = Math.max(f.a, w0), a1 = Math.min(f.b, R); if (a1 > a0 && (!big || a1 - a0 > big.b - big.a)) big = { a: a0, b: a1, at: f.at }; }
        return big; };
      const inDuty = (ms) => duties.some((du) => du.start <= ms && ms < du.end);
      const dutyStartOn = {};
      for (const du of duties) { const k = this._d(du.start); if (dutyStartOn[k] == null || du.start < dutyStartOn[k]) dutyStartOn[k] = du.start; }
      const farOn = {};
      for (const [d] of (mon.days || [])) {
        const R = dutyStartOn[d] != null ? dutyStartOn[d] : this._t(d, "0:01");
        const mid = dutyStartOn[d] == null && (inDuty(R) || own.some((o) => o.rep && o.rel && o.rep < R && R < o.rel));  // layover day inside a trip
        let t30 = far30Txt("mid"), t30t = "Mid-trip (layover): no report this day. The layover itself gets the teal edge if it is 30 h or more.", bad30 = false;
        if (!mid) {
          const big = free30(R); const ok = !!big && big.b - big.a >= 30 * H; const unknown = !ok && R - 168 * H < dataStart;
          const gu = ok ? Math.min(big.b, R) + 138 * H : null;
          const endD = ok ? this._d(Math.min(big.b, R)) : "";
          // 1.7.13: worded with units (far30Txt); the check itself is today's
          t30 = far30Txt(ok ? "ok" : unknown ? "unknown" : "need", ok ? (big.b - big.a) / H : 0, endD.slice(5).replace("-", "/"));
          bad30 = !ok && !unknown;
          t30t = `${dutyStartOn[d] != null ? "Duty starts " + this._hm(R) : "If you reported at 00:01"}: longest free block in the 168 h before was ${big ? this._dur(big.b - big.a) + " from " + this._hm(big.a) + " " + this._d(big.a) + (big.at && big.at !== "HNL" ? " at " + big.at : "") : "none"}. ` + (ok ? `30 h free in 7 days met (FAR 117.25(b)): this break covers reports until ${this._hm(gu)} ${this._d(gu)}.` : unknown ? "The window reaches before the schedule on file." : "Under 30:00: 30 h free in 7 days NOT met (FAR 117.25(b)).");
        }
        const E = this._t(d, "0:0") + 24 * H, D0 = E - 24 * H;
        const back = blkIn(E - 672 * H, E);
        let worst = back, wE = E;
        for (let k = 1; k < 28; k++) { const e2 = E + k * 24 * H; const v = blkIn(e2 - 672 * H, e2); if (v > worst) { worst = v; wE = e2; } }
        // 1.7.13: both cells are what is left of the 100:00 (farLeft): back = the 672 h ending that day, worst = the
        // busiest window that holds the day, back and forward. 1.7.13 review: each block is rounded to the minute once
        // (bm, wm) and the cell is 100:00 less that, so the cell and its title add up. 1.7.13 (F1): far._cum's windows
        // holding part of the day; a tie keeps the window ending 24:00
        const bm = Math.round(back * 60);
        let wm = Math.round(worst * 60);
        for (const w of farWin) if (w.a < E && D0 < w.b && w.m > wm) { wm = w.m; wE = w.b; }
        // "~": a window before or after the schedule on file, or holding a trip with no times (1.7.13 F3); the windows
        // that hold part of the day start after 00:00 28 days before and end before 24:00 28 days after
        const outB = E - 672 * H < dataStart, outR = D0 - 672 * H < dataStart || E + 672 * H > dataEnd;
        const uB = unkIn(E - 672 * H, E), uR = unkIn(D0 - 672 * H, E + 672 * H);
        const bl = farLeft((6000 - bm) / 60, outB || uB.length > 0), rl = farLeft((6000 - wm) / 60, outR || uR.length > 0);
        farOn[d] = { t30, t30t, bad30, ok30: t30.startsWith("&#10003;"), b: bl.txt, over: bl.bad,
          bt: `100h/672h: ${bl.txt}. ${hm(bm / 60)} block flown or scheduled in the 672 h (28 days) ending 24:00 ${d}, leg by leg${outB ? "; ~ = part of the window is before the schedule on file" : ""}${uB.length ? "; " + unkTxt(uB) : ""}. FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours; this cell checks the 672 h ending 24:00 that day.`,
          room: rl.txt, rbad: rl.bad,
          rt: `Room to 100h: ${rl.txt}. 100:00 minus the busiest 672 h window that holds part of this day (${hm(wm / 60)} flown or scheduled in the 672 h ending ${winEnd(wE)}), looking back and forward (FAR 117.23(b)(1)).${outR ? " ~ = a window reaches past the schedule on file." : ""}${uR.length ? ` ${unkTxt(uR)}.` : ""}` };
      }
      // when the next 30 h off is needed: first report time after now with no 30 h free block in the 168 h before it
      let need30 = null;
      {
        const step = 15 * 60e3, t0 = Math.ceil(nowHst / step) * step, tEnd = Math.min(dataEnd, t0 + 40 * 24 * H);
        const cand = duties.filter((du) => du.start >= t0 && du.start < tEnd).map((du) => du.start);
        for (let T = t0; T < tEnd; T += step) if (!inDuty(T)) cand.push(T);
        cand.sort((a, b) => a - b);
        for (const T of cand) { const big = free30(T); if (!(big && big.b - big.a >= 30 * H)) { need30 = T; break; } }
      }
      // tag-on suggestions keyed by the day they report
      const tags = {};
      const avail = new Set([...pot.map((p) => `${p.pairing}|${this._iso(p.start, y)}`)]);
      const tbAvail = new Set(tb.map((p) => `${p.pairing}|${this._iso(p.start, y)}`));
      const vacDays = (a, b) => items.some((it) => it.trip === "VAC" && a <= it.end && b >= it.start);
      const blkDays = (a, b) => [...blocked].some((d) => a <= d && d <= b);
      if (pk) {
        for (let i = 0; i < own.length; i++) {
          const o = own[i]; if (!o.rel || o.it.start < key) continue;
          const nextRep = own.slice(i + 1).map((x) => x.rep).find((x) => x) || Infinity;
          const d0 = this._d(o.rel), d1 = this._d(o.rel + 24 * H);
          const found = [];
          for (const p of Object.values(pk)) {
            if (own.some((x) => x.it.trip.slice(0, 5) === p.id)) continue;
            for (const sd of [d0, d1]) {
              if (!p.days.has(sd)) continue;
              const rep = this._t(sd, p.report);
              const depH = parseInt(p.dep, 10);
              const need = (p.firstDuty >= 720 && (depH >= 14 || depH < 4)) ? 18 : 11;
              const gap = rep - o.rel;
              if (gap < need * H || gap > 36 * H) continue;
              const rel = this._t(sd, p.release) + p.relDays * 24 * H;
              if (nextRep - rel < 11 * H) continue;
              if (vacDays(sd, this._d(rel)) || blkDays(sd, this._d(rel))) continue;
              found.push({ p, sd, rep, rel, gap, need });
            }
          }
          found.sort((a, b) => a.rep - b.rep);
          for (const f of found.slice(0, 4)) {
            const k = `${f.p.id}|${f.sd}`;
            const src = avail.has(k) ? "O" : (tbAvail.has(k) ? "T" : "");
            const dest = f.p.route.split("-").slice(1, -1).join("/");
            const md = (iso) => `${MON3[parseInt(iso.slice(5, 7), 10) - 1][0]}${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(1).toLowerCase()} ${parseInt(iso.slice(8), 10)}`;
            const hc = (v) => String(v || "").replace("h", ":");
            const title = [`${f.p.id}  ${f.p.route}`, `Report ${f.p.report} ${md(f.sd)}`, `Release ${this._hm(f.rel)} ${md(this._d(f.rel))}`,
              `Credit ${hc(f.p.credit)}   TAFB ${hc(f.p.tafb)}`, `Rest after ${o.it.trip}: ${this._dur(f.gap)} (need ${f.need}:00)`,
              src === "O" ? "In open time now" : src === "T" ? "On the Tradeboard now" : "Not in open time"].join("\n");
            (tags[f.sd] = tags[f.sd] || []).push(`<span class="tag${src ? " avail" : ""}" title="${this._esc(title)}">` +
              `${this._esc(dest)}(${this._esc(f.p.id)}) ${this._esc(f.p.report)}${src ? ` <b>${src}</b>` : ""}</span>`);
          }
        }
      } else if (pk === false) note = `No ${MONTHS[m]} pairing package on file, so no tag-on ideas.`;
      { const sc0 = this._school(key + "-15"); if (sc0 === false && this._role() === "admin") note += (note ? " " : "") + `No HPA school calendar file for this school year (school_YYYY-YY.json); holidays shown instead.`; }
      const sum = { blk: 0, cr: 0, soft: 0, gross: 0, net: 0, vac: 0, vacDays: 0, payp: 0, ppEst: false, ppCov: [], ppUnk: "", lodo: 0, rcl: 0, cut: 0, cutT: [], ctBad: [] };
      const tt = mon.totals || {};
      const fl = (v) => { const m = /^(\d+)[.:](\d{2})$/.exec(String(v || "")); return m ? parseInt(m[1], 10) + parseInt(m[2], 10) / 60 : null; };
      const mdy = (iso) => { const mo = MON3[parseInt(String(iso).slice(5, 7), 10) - 1] || ""; return `${mo.slice(0, 1)}${mo.slice(1).toLowerCase()} ${parseInt(String(iso).slice(8, 10), 10) || ""}`.trim(); };
      const srcFl = awd0 ? "the award file" : "FLICA";
      // 1.7.2 (Ryan, Nov 13): the PAYP items with days in this month. p.rec = the Watcher's PAYP|<start> record (the
      // removed trip's credit, PWA Definitions 57), counted on the PAYP's first day (p.row) when that day is this month's;
      // with none, p.h = the estimate: FLICA's month credit less everything else counted (other: the trips and VAC, got:
      // the records), only when above zero, split by days over the PAYP items without a record (p.est)
      // Fix pass: a record with a split (the removed trip's duties depart in two months) counts this month's share on
      // its first PAYP day here (PWA 4.A, as FLICA's month credit does). A record whose PAYP left the schedule because a
      // trip was added over all its days (PWA 4.R.1) counts in the totals (p.cov) only when FLICA's month credit holds it.
      // Both, and the estimate, only when the card counts everything else in the month (why: no other credited codes
      // such as SIM or SICK, no trip whose credit is not read, no trip from last month running into this one); else
      // p.unk: the PAYP's credit is unknown and the Credit check stays red
      const isP = (t) => /^[A-Z]\d{4}/.test(t || "");
      const paypPlan = (mm, tr, other, flica) => {
        const out = [], its = ((mm && mm.items) || []).filter(Boolean), dys = (mm && mm.days) || [];
        for (const it of its) {
          if (it.trip !== PAYP || !it.start) continue;
          const all = dys.filter(([d, t]) => t === PAYP && it.start <= d && d <= (it.end || it.start)).map(([d]) => d);
          const ds = all.filter((d) => inBp(d));  // FW-0080: the PAYP days in this bid period
          if (!ds.length) continue;
          let rec = tr[`${PAYP}|${it.start}`] || null, c = rec ? hrs(rec.credit) : null;
          // 1.7.11 review (FW-0080): no record of its own (a PAYP listed again on this page, from Dec 1, the bid period
          // before's last day): the record of the PAYP it continues gives its share when its split names this bid period
          if (c == null) {
            const prev = Object.entries(tr || {}).find(([k, r]) => k.startsWith(PAYP + "|") && r && r.payp && !r.of && r.split && typeof r.split === "object"
              && hrs(r.split[key]) != null && k.slice(PAYP.length + 1) < it.start && it.start <= fwgDay(r.end || k.slice(PAYP.length + 1), 1));
            if (prev) { rec = { ...prev[1], credit: prev[1].split[key], split: null, of: prev[0] }; c = hrs(rec.credit); }
          }
          const sp = c != null && rec.split && typeof rec.split === "object" ? rec.split : null;
          // a continuation record (of) holds this bid period's share already (versions.payp_entries)
          out.push({ it, ds, all, row: ds[0], rec: c != null ? rec : null, h: c == null ? null : sp ? hrs(sp[key]) : (rec.of || ds.includes(it.start) ? c : null), est: false });
        }
        for (const [k, r] of Object.entries(tr || {})) {
          if (!r || !r.payp || !k.startsWith(PAYP + "|") || hrs(r.credit) == null) continue;
          const s0 = k.slice(PAYP.length + 1), e0 = r.end || s0, prot = String(r.protected || "").split(",").filter(Boolean);
          if (its.some((it) => it.trip === PAYP && it.start <= e0 && s0 <= (it.end || it.start))) continue;
          const cov = its.find((it) => isP(it.trip) && s0 <= it.start && it.start <= e0 && !prot.some((q) => q === `${it.trip}|${it.start}` || q.slice(0, 5) === it.trip.slice(0, 5)));
          const w = !cov ? null : r.split && typeof r.split === "object" ? hrs(r.split[key]) : (inBp(s0) ? hrs(r.credit) : null);
          if (w) out.push({ it: null, cov, k, ds: [], all: [], row: null, rec: r, h: null, want: w, est: false });
        }
        const mds = dys.filter(([d]) => inBp(d)), one = bp.from;
        const known = (d, t) => hrs((tr[`${t}|${d}`] || {}).credit) != null || !!(pk && pk[t.slice(0, 5)] && hx(pk[t.slice(0, 5)].credit) != null);
        const why = flica == null ? `no ${srcFl} month credit to check it against`
          : mds.some(([, t]) => t && t !== "VAC" && t !== PAYP && !isP(t)) ? `${srcFl}'s month credit holds codes the card does not count (${[...new Set(mds.map(([, t]) => t).filter((t) => t && t !== "VAC" && t !== PAYP && !isP(t)))].join(", ")})`
          : mds.some(([d, t]) => isP(t) && !known(d, t)) ? "a trip's credit is not read yet"
          : [...prevItems, ...its].some((it) => isP(it.trip) && it.start < one && (it.end || it.start) >= one && !carried.has(`${it.trip}|${it.start}`) && !(figs(it.start, it.trip).sp)) ? "a trip from the bid period before runs into this one" : "";
        let left = why ? null : Math.round((flica - other - out.reduce((a, p) => a + (p.h || 0), 0)) * 60);
        for (const p of out.filter((x) => x.want)) if (left != null && left >= Math.round(p.want * 60) - 1) { p.h = p.want; left -= Math.round(p.want * 60); }
        const need = out.filter((p) => p.it && !p.rec);
        if (need.length && left != null && left > 0) {
          const nd = need.reduce((a, p) => a + p.ds.length, 0); let rest = left;
          need.forEach((p, i) => { const mm2 = i === need.length - 1 ? rest : Math.round(left * p.ds.length / nd); rest -= mm2; p.h = mm2 / 60; p.est = true; });
        }
        for (const p of need) if (left == null) { p.unk = true; p.why = why; }
        return out;
      };
      const ppTitle = (p) => {
        const prot = String((p && p.rec && p.rec.protected) || "").split(",").filter(Boolean).map((k) => `${k.split("|")[0]} ${mdy(k.split("|")[1] || "")}`).join(" and ");
        const head = `Pay protected: ${prot || "the removed trip is not on file"} (${PAYP_REF})`;
        if (!p) return head;
        const sp = p.rec && p.rec.split && typeof p.rec.split === "object" ? Object.entries(p.rec.split).sort().map(([m0, v]) => `${MONTHS[parseInt(m0.slice(5, 7), 10) - 1]} ${v}`).join(", ") : "";
        const by = sp ? ` by bid period: ${sp} (PWA 4.A: each bid period counts the duties departing in it)` : "";
        if (p.rec && p.h == null) return `${head}\nIts credit ${p.rec.credit} counts ${sp ? by.trim() : "in the bid period the PAYP starts in"}.`;
        if (p.rec) return `${head}\nCredit ${p.rec.credit} kept${p.rec.src ? ` (from ${p.rec.src})` : ""}${p.rec.of ? `, this bid period's share of the PAYP from ${mdy(p.rec.of.split("|")[1] || "")} (PWA 4.A)` : ""}${by}; no block (not flown).`;
        if (p.est) return `${head}\nCredit ${hm(p.h)} is an estimate: ${srcFl}'s month credit ${hm(fl(tt.credit))} less everything else counted${p.ds.length ? `, over ${p.ds.length} PAYP day${p.ds.length > 1 ? "s" : ""}` : ""}.`;
        if (p.unk) return `${head}\nCredit unknown, not counted: ${p.why}.`;
        return `${head}\nNo credit counted: ${srcFl}'s month credit leaves none for it.`;
      };
      // FW-0080: the package of the bid period a trip's first day is in (this month's, the one before or after), for its
      // duties' TCRD: fetched only for a trip that starts outside this bid period
      // 1.7.11 review (F#32): packWait = a package a price or a split asked for is still loading, so the month's
      // Improved-Pay-Gross waits for it too (priced before it, a trip across the edge counts its block share)
      let packWait = false;
      const packAt = (d) => { if (inBp(d)) return pkE; const e = this._packE(bpNext(d < bp.from ? "before" : "after")); if (e === null) packWait = true; return e; };
      // the package map that lists a trip starting on d: this month's in the bid period, else the bid period's of d
      const pkOf = (d) => { if (inBp(d)) return pk; const e = packAt(d); return e ? e.map : null; };
      // a row's Block / Credit / Soft as this bid period counts them (PWA 4.A, fwSplit), for the rows, the carried trips
      // and the PAYP estimate. FW-0080: the trip's own duties (FLICA's pairing page), each one's TCRD from its pairings
      // package's detail (the exact pairing, listed on that day, as many duties), else the block share (an estimate);
      // a trip with no duty on file pays in the bid period of its first day (inP: any part of it counts here)
      // 1.7.11 review (FW-0080): a trip whose own times are not read yet places the package detail's duties
      // (fwPkgDuties, their TCRD with them), so it splits as the Watcher splits it (pilot_price, package_details)
      const splitOf = (d, trip, ot, cH, bH) => {
        if (!trip || trip === "VAC" || trip === PAYP || !isP(trip)) return null;
        const own = Array.isArray(ot.duties) && ot.duties.length && ot.duties.every((x) => x && typeof x.dep === "number" && typeof x.blk === "number") ? ot.duties : null;
        if (!own && Array.isArray(ot.duties) && ot.duties.length) return null;
        const pe = packAt(d), pr = pe && Object.prototype.hasOwnProperty.call(pe.map, trip) && pe.map[trip].days.has(d) ? pe.map[trip] : null;
        if (!own) { const pdu = fwPkgDuties(pr); return pdu.length ? fwSplit(d, pdu, bp.from, bp.to, cH, bH) : null; }
        const pd = pr && pr.det && Array.isArray(pr.det.duties) && pr.det.duties.length === own.length ? pr.det.duties : null;
        return fwSplit(d, own.map((x, i) => ({ dep: x.dep, blk: x.blk, tcrd: pd && pd[i] && typeof pd[i] === "object" ? pd[i].tcrd : null })), bp.from, bp.to, cH, bH);
      };
      // 1.7.20 (Hark, Ryan Nov 20, 2026): the PWA pay engine on an own trip (fwPwaTrip: greater of GOP / Trip Rig / MDG,
      // delay vs reassignment, LODO, recall). A day off = no other assignment on the schedule that day (a VAC, PAYP or
      // reserve code is not off). pwaAdj: the trip's own times with FLICA's credit replaced only where FLICA counted a
      // delayed leg twice (fix), so Credit, Soft, Pay-Gross, the totals and the paychecks all use the PWA credit
      const isOffFor = (iso, self) => !near.some((it) => it && it.trip && `${it.trip}|${it.start}` !== self && it.start <= iso && iso <= (it.end || it.start));
      const pwaOf = (d, trip, ot, pr) => (isP(trip) && trip !== PAYP ? fwPwaTrip({ start: d, ot, pr: pr && pr.days && pr.days.has(d) ? pr : null,
        isOff: (iso) => isOffFor(iso, `${trip}|${d}`), rcl: fwRclOf(erOv, `${trip}|${d}`), mine: !!String((ot && ot.seat) || "").trim(),
        keep: erOv.includes(`K+${trip}|${d}`), ct: ctSnap ? (() => { const c = fwCtFind(ctSnap, trip, d); return c ? fwCtM(c.credit) : null; })() : null,
        ctp: ctSnap ? (() => { const c = fwCtFind(ctSnap, trip, d); return c ? (c.prot ? fwCtM(c.prot) : fwCtProt(c)) : null; })() : null }) : null);
      const pwaAdj = (ot, pa) => {
        if (!pa || !pa.fix) return ot;
        const b = fwgMins(ot.blk);
        return { ...ot, credit: hm(pa.use / 60), soft: b == null ? ot.soft : hm(Math.max(0, pa.use - b) / 60), flica_credit: ot.credit };
      };
      const figs = (d, trip, tr) => {
        const ot0 = trip && trip !== "VAC" ? ((tr || ownT)[`${trip}|${d}`] || {}) : {};
        // 1.7.11 review: the package of the bid period the trip starts in (a trip from the bid period before is in
        // that one's package, not this month's)
        const pkm = isP(trip) ? pkOf(d) : null;  // a pairing only (a code never asks for another package)
        const pkr = pkm ? (pkm[trip.slice(0, 5)] || {}) : {};
        const pa = pwaOf(d, trip, ot0, pkm ? pkm[trip.slice(0, 5)] : null), ot = pwaAdj(ot0, pa);
        // 1.6.3: the pairings package writes credit as "15h00"; hrs() reads "15:00", so a trip whose own times are not
        // read yet (a pilot's first days, or any new trip) counted 0:00 and $0 in the row and the month totals
        const pkC = pkr.credit ? String(pkr.credit).trim().replace(/^(\d+)h(\d{2})$/, "$1:$2") : "";
        const bcsAll = trip && trip !== "VAC" ? [ot.blk || "", ot.credit || pkC || "", ot.soft || ""] : ["", "", ""];
        const bAll = hrs(bcsAll[0]) != null ? hrs(bcsAll[0]) : ot.blk ? null : hx(pkr.block);  // the package's block for a split
        const sp = splitOf(d, trip, ot, hrs(bcsAll[1]), bAll);
        const inP = sp ? sp.in : inBp(d), whole = sp ? sp.whole : inP;
        const z = (v) => (v ? "0:00" : "");
        const bcs = whole ? bcsAll : sp ? [sp.bl != null ? hm(sp.bl / 60) : "", sp.cr != null ? hm(sp.cr / 60) : "", sp.cr != null && sp.bl != null ? hm(Math.max(0, sp.cr - sp.bl) / 60) : ""]
          : [z(bcsAll[0]), z(bcsAll[1]), z(bcsAll[2])];
        return { ot, pkr, bcsAll, bcs, inP, whole, sp, pa };
      };
      // FW-0080: what a row's split mark says (its part here, and what part pays in the other bid period, PWA 4.A)
      const splitWhy = (d, trip, F) => {
        // 1.7.11 review: only a pairing splits (a reserve or other code on a grid day outside the bid period is plain)
        if (F.whole || !trip || trip === "VAC" || trip === PAYP || !isP(trip)) return "";
        const sd = F.sp && F.sp.side ? F.sp.side : d < bp.from ? "before" : "after";
        const edge = sd === "before" ? `before ${mdy(bp.from)}` : `after ${mdy(bp.to)}`;
        const other = `the ${MONTHS[parseInt(bpNext(sd).slice(5, 7), 10) - 1]} bid period`;
        const all = `${F.bcsAll[0] || "?"} block / ${F.bcsAll[1] || "?"} credit in all`;
        // 1.7.11 review: no duty times on file, so nothing says when any of it flew: it pays where its first day is
        if (!F.sp) return `${trip}: ${all}, starts ${mdy(d)}; no duty times on file, so the whole trip pays in ${other}, the bid period of its first day (PWA 4.A), not in these totals.`;
        const sp = F.sp, oc = sp.outCr != null ? hm(sp.outCr / 60) : "?", ob = sp.outBl != null ? hm(sp.outBl / 60) : "?";
        if (!sp.in) return `${trip}: ${all}, all flown ${edge}: it pays in ${other} (PWA 4.A), not in these totals.`;
        return `${trip}: ${all}; ${ob} block, ${oc} credit flown ${edge} pay in ${other} (PWA 4.A).` +
          (sp.est ? " Credit split by block share (no duty credit on file): an estimate." : " Credit of each duty from the pairings package (TCRD); the rest of the trip credit (rig, minimums) stays with the bid period of its first day.");
      };
      // FW-0080: a trip with no row on this page (it starts before the page's first day, or after its last) whose duties
      // fly part of this bid period: that part counts in the totals, named under them (carried)
      const rowK = new Set((mon.days || []).filter(([, t]) => t).map(([d, t]) => `${t}|${d}`));
      const carried = new Map();
      for (const it of [...prevItems, ...items, ...nextItems]) {
        if (!it || !/^[A-Z]\d{4}/.test(it.trip || "") || !FWG_ISO.test(it.start || "")) continue;
        const k = `${it.trip}|${it.start}`;
        if (carried.has(k) || rowK.has(k) || (it.end || it.start) < bp.from || it.start > bp.to) continue;
        const F = figs(it.start, it.trip);
        if (F.inP && F.sp) carried.set(k, { it, F });
      }
      let crOther = 0;
      for (const [d, trip] of (mon.days || [])) {
        if (!trip || trip === PAYP) continue;
        if (trip === "VAC") { if (inBp(d)) crOther += VAC_H; continue; }
        const F = figs(d, trip);
        if (F.inP) crOther += hrs(F.bcs[1]) || 0;
      }
      for (const c of carried.values()) crOther += hrs(c.F.bcs[1]) || 0;
      const ppl = paypPlan(mon, ownT, crOther, fl(tt.credit));
      const ppDay = {};  // fix pass: every day of the PAYP, the next month's too, names its record
      for (const p of ppl) for (const d of p.all) ppDay[d] = p;
      const tripFull = (cr, blk, crew, lay, k, seat) => { const n = crewN(crew);
        return cr == null ? null : cr * RATE + fwOverride(seat, n, blk, cr, RATE, erOn(k, lay, n)).v; };
      // month price of a version (same rules as the rows): Awarded-Pay-Gross and Improved-Pay-Gross
      // 1.7.2: a PAYP is priced as on the rows (paypPlan: the record's credit, else the estimate from the version's own
      // FLICA credit), so Awarded-Pay-Gross, Improved-Pay-Gross and a version's Pay-Gross count it too
      const price = (mm, tr) => { let g = 0, other = 0;
        // FW-0080: the rows' rule (figs): each trip its part in this bid period, the trips carried in from no row too
        const one = (d, trip, lay) => {
          const ot0 = tr[`${trip}|${d}`] || {}; const pm = pkOf(d), pr = pm ? (pm[trip.slice(0, 5)] || {}) : {};
          const pa = pwaOf(d, trip, ot0, pm ? pm[trip.slice(0, 5)] : null), ot = pwaAdj(ot0, pa);  // 1.7.20
          let cH = hrs(ot.credit); if (cH == null) cH = hx(pr.credit); let bH = hrs(ot.blk); if (bH == null) bH = hx(pr.block);
          const sp = splitOf(d, trip, ot, cH, bH);
          if (!(sp ? sp.in : inBp(d))) return;
          const c = sp && !sp.whole ? (sp.cr == null ? null : sp.cr / 60) : cH, b = sp && !sp.whole ? (sp.bl == null ? null : sp.bl / 60) : bH;
          other += c == null ? 0 : c;
          g += tripFull(c, b, nOf(pr, ot), lay, `${trip}|${d}`, ot.seat) || 0;
          if (pa) g += ((pa.lodoDays.filter(inBp).length * 4) + (pa.rclAll ? (c || 0) : pa.rcl / 60)) * RATE;  // 1.7.20: LODO, recall (pay only)
        };
        const rows = new Set(((mm && mm.days) || []).filter(([, t]) => t).map(([d, t]) => `${t}|${d}`));
        for (const [d, trip, lay] of ((mm && mm.days) || [])) {
          if (trip === "VAC") { if (inBp(d)) { g += VAC_H * RATE; other += VAC_H; } continue; }
          if (!trip || !/^[A-Z]\d{4}/.test(trip)) continue;
          one(d, trip, lay);
        }
        const seen = new Set();
        for (const it of [...prevItems, ...((mm && mm.items) || []), ...nextItems]) {
          const k = it && it.trip ? `${it.trip}|${it.start}` : "";
          if (!k || seen.has(k) || rows.has(k) || !/^[A-Z]\d{4}/.test(it.trip) || !FWG_ISO.test(it.start || "") || (it.end || it.start) < bp.from || it.start > bp.to) continue;
          seen.add(k);
          if (splitOf(it.start, it.trip, tr[k] || {}, 0, 0)) one(it.start, it.trip, it.lay || "");
        }
        for (const p of paypPlan(mm, tr, other, fl(((mm && mm.totals) || {}).credit))) if (p.h != null) g += tripFull(p.h, 0, "", "", p.it ? `${PAYP}|${p.row}` : p.k, "") || 0;
        return g; };
      const tripPay = {};
      // v51 (Ryan): swap / pick-up ideas. A swap may move off the trip's footprint onto any neighbouring day that is not
      // blocked and has no other assignment; legal rest before and after (11 h at domicile, PWA 10.E.1.a); pay from the
      // package credit (PWA 4.C.3 min 5:00 per calendar day already in it) with crew overrides (PWA 4.O.1).
      // 1.7.11 review: the trip a swap replaces is skipped by its trip and start, not by the copy own kept: a trip
      // across a month end is on both months' pages (Schedule Lookup rows start in late November), and its other copy
      // made every day of it busy, so no swap for it was ever offered
      const busyDay = (iso, excl) => blocked.has(iso) || near.some((it) => it.trip && !(excl && it.trip === excl.trip && it.start === excl.start)
        && it.start <= iso && iso <= (it.end || it.start));
      const addD = (iso, n) => this._d(Date.parse(iso + "T00:00:00Z") + n * 24 * H);
      const ideasFor = (d, trip) => {
        if (!pk) return null;
        const o = trip && trip !== "VAC" ? own.find((x) => x.it.trip === trip && x.it.start === d) : null;
        if (trip && !o) return null;
        if (!trip && busyDay(d, null)) return null;
        const oEnd = o ? (o.rel ? this._d(o.rel) : o.it.end) : d;
        let a = o ? o.it.start : d, b = oEnd;
        for (let k = 0; k < 4 && !busyDay(addD(a, -1), o && o.it); k++) a = addD(a, -1);
        for (let k = 0; k < 4 && !busyDay(addD(b, 1), o && o.it); k++) b = addD(b, 1);
        if (!o) a = d;
        const others = own.filter((x) => x !== o);
        const cur = o ? (tripPay[o.it.trip + "|" + o.it.start] || 0) : 0;
        const out = [];
        for (const p of Object.values(pk)) {
          for (const sd of p.days) {
            if (sd < a || sd > b || (!o && sd !== d)) continue;
            const end = addD(sd, p.relDays || 0);
            if (end > b) continue;
            if (o && (end < o.it.start || sd > oEnd)) continue;  // a swap overlaps the trip it replaces
            if (o && p.id === o.it.trip.slice(0, 5) && sd === o.it.start) continue;
            let clash = false; for (let x = sd; x <= end; x = addD(x, 1)) if (busyDay(x, o && o.it)) { clash = true; break; }
            if (clash) continue;
            const rep = this._t(sd, p.report), rel = this._t(sd, p.release) + (p.relDays || 0) * 24 * H;
            const prev = others.filter((x) => x.rel && x.rel <= rep).map((x) => x.rel).sort((u, v) => v - u)[0];
            const next = others.filter((x) => x.rep && x.rep >= rel).map((x) => x.rep).sort((u, v) => u - v)[0];
            if ((prev && rep - prev < 11 * H) || (next && next - rel < 11 * H)) continue;
            const lay = (p.route || "").split("-").filter((x) => x !== "HNL").join("/");
            const pay = tripFull(hx(p.credit), hx(p.block), p.crew, lay, `${p.id}|${sd}`, "FO");
            const k = `${p.id}|${sd}`;
            out.push({ p, sd, end, rep, rel, lay, pay, delta: pay - cur, src: avail.has(k) ? "O" : (tbAvail.has(k) ? "T" : ""),
              rest: [prev ? `${this._dur(rep - prev)} rest before` : "", next ? `${this._dur(next - rel)} rest after` : ""].filter(Boolean).join(", ") });
          }
        }
        out.sort((u, v) => (!!v.src - !!u.src) || (v.delta - u.delta));
        return { o, a, b, cur, list: out };
      };
      const ideaBtn = (d, trip) => {
        const r = ideasFor(d, trip); if (!r || !r.list.length) return "";
        const nO = r.list.filter((x) => x.src).length, best = Math.max(...r.list.map((x) => x.delta));
        return `<span class="idb${nO ? " live" : ""}" data-d="${d}" data-trip="${this._esc(trip || "")}" title="${r.o ? "Swap ideas" : "Pick-up ideas"}: ${nO} open now, ${r.list.length} in the package">&#9992;&#xFE0E;${nO ? " " + nO : ""}${best > 0 ? ` <small>+${usd(best)}</small>` : ""}</span>`;
      };
      // 1.7.7: the open pairing detail (this._pd {key, k}): its model (the package's legs when it lists this exact pairing
      // on that day; else what FLICA's pairing page gave, with why) and its rows, the report day to the release day
      if (this._pd) {
        pdK = this._pd.k;
        const [ptr, pst] = pdK.split("|");
        // 1.7.7 review: a version (or month) that does not draw this trip on that day closes its detail
        if (!(mon.days || []).some(([d, tr]) => d === pst && tr === ptr) && !own.some((x) => x.it.trip === ptr && x.it.start === pst)) { this._pd = null; pdK = ""; }
      }
      if (this._pd) {
        const [ptr, pst] = pdK.split("|");
        const o = own.find((x) => x.it.trip === ptr && x.it.start === pst);
        const t = ownT[pdK] || {};
        const pe = /^\d{4}-\d{2}-\d{2}$/.test(pst || "") ? fwgPackFor(this._pk, PAIRINGS_URL, pst, () => { this._sig = null; if (this._h) this.hass = this._h; }, ptr) : false;
        const has = !!pe && Object.prototype.hasOwnProperty.call(pe.map, ptr);
        const p = has && pe.map[ptr].days.has(pst) ? pe.map[ptr] : null;
        const pmo = pe ? `${MONTHS[parseInt(pe.key.slice(5, 7), 10) - 1]} ${pe.key.slice(0, 4)}` : "";
        const wmd = (ms) => `${this._hm(ms)} ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date(ms).getUTCDay()]} ${mdy(this._d(ms))}`;
        let why = p && p.det ? "" : pe === null ? "Loading the pairings package."
          : pe === false ? `No pairings package on file for the bid period of ${mdy(pst)}: the package detail is not on file.`
          : !has && /^[A-Z]\d{4}[A-Z]$/.test(ptr) && Object.prototype.hasOwnProperty.call(pe.map, ptr.slice(0, 5)) ? `${ptr} is a pairing FLICA rebuilt: the ${pmo} pairings package has ${ptr.slice(0, 5)}, not this trip, so the package detail is not on file.`
          : !has ? `${ptr} is not in the ${pmo} pairings package: the package detail is not on file.`
          : !p ? `The ${pmo} pairings package does not list ${ptr} on ${mdy(pst)}: the package detail is not on file.`
          : pe.dcut ? `The ${pmo} pairings file holds the leg detail of its first pairings only (a size limit): the package detail of ${ptr} is not on file.`
            : `The ${pmo} pairings file has no leg detail yet: an older Watcher wrote it, and the next update reads the package again.`;
        if (why && !(t.duties && t.duties.length) && !t.report) why += " FLICA's pairing page for this trip is not read yet either.";
        pdM = fwgDetail({ id: ptr, start: pst, p, why, own: t, seat: t.seat, crew: t.crew,
          rep: o && o.rep ? wmd(o.rep) : "", rel: o && o.rel ? wmd(o.rel) : "" });
        const end = o ? (o.rel ? this._d(o.rel) : o.it.end) : pst;
        for (let x = pst, n = 0; x && x <= end && n < 40; x = this._d(Date.parse(x + "T00:00:00Z") + 24 * H), n++) pdDays.add(x);
      }
      const rows = (mon.days || []).map(([d, trip, lay]) => {
        const dt = new Date(d + "T12:00:00"); const wk = dt.getDay() === 0 || dt.getDay() === 6;
        const other = dt.getMonth() !== m;
        const sc = this._school(d); const noSchool = !!(sc && sc.days.has(d));
        const pp = trip === PAYP ? (ppDay[d] || null) : null;  // 1.7.2: a PAYP day (pay protected, PWA Definitions 57)
        const t = trip === "VAC" ? `<span class="vac">VAC</span>` : trip === PAYP ? `<span class="payp tag" title="${this._esc(ppTitle(pp))}">PAYP</span>` : (trip ? `<span class="trip${trade.has(trip + "|" + d) ? " tr" : ""}" data-k="${this._esc(trip + "|" + d)}" role="button" tabindex="0" aria-expanded="${pdK === trip + "|" + d ? "true" : "false"}" title="${this._esc(((ownT[`${trip}|${d}`] || {}).crew || []).join("\n") || "crew not read yet")}">${this._esc(trip)}</span>${d <= today ? "" : `<span class="trb${trade.has(trip + "|" + d) ? " on" : ""}" data-k="${this._esc(trip + "|" + d)}" title="${trade.has(trip + "|" + d) ? "Marked: would trade this trip for a better one. Tap to unmark." : "Tap to mark this trip as one you would trade for a better one."}">&#8644;</span>`}${d <= today || !admin ? "" : `<span class="drb${dropM.has(trip + "|" + d) ? (dropR[trip + "|" + d] ? " on rdy" : " on") : ""}" data-k="${this._esc(trip + "|" + d)}" title="${dropR[trip + "|" + d] ? "Grid green on every day: drop request drafted (draft only, never sent: drop it yourself in FLICA). Tap to unmark." : dropM.has(trip + "|" + d) ? "Marked: would DROP this trip once the reserve grid is green on every day of it. Tap to unmark." : "Tap to mark this trip as one you would DROP when the grid allows it."}">&#8615;</span>`}` : "");
        const sw = (swapFor[trip + "|" + d] || []).slice(0, 2).map((i) => `<span class="tag sw" title="${this._esc([`Swap ${trip} for ${i.pairing}`, `${i.dates}  ${i.layover || i.turn || ""}`, i.why, i.src === "T" ? "On the Tradeboard" : "In open time"].join("\n"))}">&#8644; ${this._esc(i.layover || i.turn || "")}(${this._esc(i.pairing)}) ${this._esc(i.soft_gain)}</span>`).join("<br>");
        const crewT = this._esc(((ownT[`${trip}|${d}`] || {}).crew || []).join("\n") || "crew not read yet");
        const rp = repOn[d] ? ` <span class="tm tag" title="${trip && trip !== "VAC" ? `${trip} crew:\n${crewT}\n\nReport ${repOn[d]}` : `Report ${repOn[d]}`}">R ${repOn[d]}</span>` : "";
        const rl = relOn[d] ? ` <span class="tm">Rel ${relOn[d]}</span>` : "";
        // a turn (no layover) shows "-" on FLICA; show the turn station(s) from the pairing package instead (HNL-PPG-HNL -> PPG)
        const pkt = lay === "-" && trip && pk ? pk[trip.slice(0, 5)] : null;
        const turn = pkt && pkt.route ? [...new Set(pkt.route.split("-").slice(1, -1).filter((x) => x !== "HNL"))].join("/") : "";
        const l0 = lay === "-" && !inTrip(d) ? "" : (lay === "-" && turn ? `<b>${this._esc(turn)}</b>` : this._esc(lay));
        // v44 (Ryan): the layover cell carries the trip's crew (tap on a phone, hover on a Mac)
        const cov = near.find((it) => it.trip !== "VAC" && it.trip !== PAYP && it.start <= d && d <= (it.end || it.start));
        const covT = cov ? (ownT[`${cov.trip}|${cov.start}`] || {}) : null;
        const nowH = new Date(Date.now() - 10 * H); const nowHM = `${String(nowH.getUTCHours()).padStart(2, "0")}:${String(nowH.getUTCMinutes()).padStart(2, "0")}`;
        const tOwn = cov ? (ownT[`${cov.trip}|${cov.start}`] || {}) : {};
        const done = cov && (cov.end < today || (cov.end === today && tOwn.last_arr && nowHM >= tOwn.last_arr));
        const flying = cov && !done && (cov.start < today || (cov.start === today && (!tOwn.report || nowHM >= tOwn.report)));
        const st = cov && d === cov.start ? (done ? ` <span class="st" title="Trip complete: Block and Credit are the final times">&#10004;</span>` : (flying ? ` <span class="st fly" title="Trip in progress: Block and Credit update every 6 h">&#9992;</span>` : "")) : "";
        const l = l0 && cov ? `<span class="tag lay" title="${this._esc(`${cov.trip} ${cov.start} crew:\n${(covT && covT.crew || []).join("\n") || "crew not read yet"}`)}">${l0}</span>${st}` : l0;
        const g = grid[d]; const gc = g ? g.color : ""; const gb = gc === "green";
        const gcell = g ? `<span class="g ${gc}" title="Net reserves ${g.net}: ${gb ? "drop or swap off this day OK" : "add only (no drop/swap off this day)"}">${g.net}</span>` : "";
        const F = figs(d, trip), ot = F.ot, pkr = F.pkr;
        // 1.7.2: a PAYP's credit on its first day (the record's, or the estimate), no block and no soft (not flown)
        const ppH = pp && pp.row === d && pp.h != null ? pp.h : null;
        const bcsAll = trip === PAYP ? ["", ppH != null ? hm(ppH) : "", ""] : F.bcsAll, bcs = trip === PAYP ? bcsAll : F.bcs;
        const splitNote = trip === PAYP ? ppTitle(pp) : splitWhy(d, trip, F);
        const cH = hrs(bcs[1]), bH = hrs(bcs[0]);
        const gross = cH != null ? cH * RATE : null;
        const seat = trip === PAYP ? "" : (ot.seat || "").toUpperCase();  // 1.7.2: a PAYP flies no seat (no override)
        // 1.7.20 (Hark, Ryan Nov 20, 2026): PWA 4.O.1 by crew size (fwOverride), LODO and recall pay (fwPwaTrip), pay only
        const nP = trip === PAYP ? 0 : nOf(pkr, ot);
        const erK = trip + "|" + d;
        const ovO = gross != null ? fwOverride(seat, nP, bH, cH, RATE, erOn(erK, l, nP)) : { v: 0, kind: "" };
        const erIs = ovO.kind === "er", roV = erIs ? 0 : ovO.v, erV = erIs ? ovO.v : 0;
        const pa = F.pa, lodoD = pa && gross != null ? pa.lodoDays.filter(inBp) : [];
        const rclH = pa && gross != null && F.inP ? (pa.rclAll ? cH : pa.rcl / 60) : 0;
        const lodoV = lodoD.length * 4 * RATE, rclV = rclH * RATE;
        const total = gross != null ? gross + roV + erV + lodoV + rclV : null;
        const net = total != null ? total * (1 - (fed + stt) / 100) : null;
        if (trip && trip !== "VAC" && trip !== PAYP) tripPay[trip + "|" + d] = tripFull(hrs(bcsAll[1]) != null ? hrs(bcsAll[1]) : hx(pkr.credit), hrs(bcsAll[0]) != null ? hrs(bcsAll[0]) : hx(pkr.block), nP, l, trip + "|" + d, seat);
        // FW-0080: the bid period's (a trip its part flown in it; a PAYP or VAC day in it), never the calendar month's
        if (trip && trip !== "VAC" && (trip === PAYP ? inBp(d) : F.inP)) { sum.blk += bH || 0; sum.cr += cH || 0; sum.soft += hrs(bcs[2]) || 0; sum.gross += total || 0; sum.net += net || 0; }
        if (pa && F.inP && gross != null) { sum.lodo += lodoD.length * 4; sum.rcl += rclH; sum.cut += pa.cut / 60; if (pa.fix) sum.cutT.push(`${trip} ${mdy(d)}: FLICA ${pa.flica != null ? hm(pa.flica / 60) : "?"}, PWA ${hm(pa.use / 60)}`); }
        if (trip === PAYP && inBp(d) && cH != null) { sum.payp += cH; sum.ppEst = sum.ppEst || !!pp.est; }
        if (trip === "VAC" && inBp(d)) { sum.vacDays += 1; sum.vac += VAC_H; sum.gross += VAC_H * RATE; sum.net += VAC_H * RATE * (1 - (fed + stt) / 100); }
        // 1.7.22 (Hark): the CrewTrac check of the whole trip (CrewTrac controls), from Hark's daily snapshot
        const ctT = admin && trip && trip !== "VAC" && trip !== PAYP && isP(trip) ? fwCtTrip(ctSnap, trip, d, bcsAll[1], bcsAll[0], Date.now()) : { ok: null, line: "", ct: null };
        if (ctT.ok === false) sum.ctBad.push(`${trip} ${mdy(d)}`);
        const ovLine = { iro: `IRO override ${usd(roV)} (${bcs[0]} block x $${IRO_OVERRIDE.toFixed(2)}, IRO seat on a ${nP || 3}-pilot crew, PWA 4.O.1.a)`,
          fo3: `IRO crew FO override ${usd(roV)} (${bcs[0]} block x $3.00, 3-pilot crew, PWA 4.O.1.a)`,
          erfo: `Extended Range crew FO override ${usd(roV)} (${bcs[0]} block x $3.00, ${nP}-pilot crew, ${seat || "FO"} seat; the 15% is only for the type-rated FO, PWA Definitions 25, 4.O.1.b)`,
          ca: `Captain override ${usd(roV)} (${bcs[0]} block x $5.00, PWA 4.O.1)`,
          er: `Extended Range type-rated FO +15% ${usd(erV)} (${bcs[1]} x ${rateTxt} x 15%, marked as the type-rated FO seat, PWA 4.O.1.b)` }[ovO.kind];
        const lines = gross != null ? [`Pay-Credit ${usd(gross)} (${bcs[1]} x ${rateTxt})`]
          .concat(ovLine ? [ovLine] : [])
          .concat(lodoD.length ? [`LODO ${usd(lodoV)} (4:00 x ${lodoD.length} lost day${lodoD.length > 1 ? "s" : ""} off: ${lodoD.map(mdy).join(", ")}; released in domicile after the scheduled footprint, PAY only, no credit, PWA 4.D.2.e${pa && pa.brk ? "; ALPA DART 417120" : ""})`] : [])
          .concat(rclV ? [`Recall +100% ${usd(rclV)} (${hm(rclH)} x ${rateTxt}: 200% pay, 100% credit on the recall ${pa.rclAll ? "trip" : "duties"}, PWA 4.M.1.a)`] : [])
          .concat(trip === PAYP ? [ppTitle(pp)] : [])
          .concat(pa ? this._pwaLines(pa, F, hm, mdy) : [])
          .concat(gross != null && trip !== PAYP && isP(trip) ? [`Pay-Gross ${usd(total)}: credit pay ${usd(gross)}${roV || erV ? ` + override ${usd(roV + erV)}` : ""}${lodoV ? ` + LODO ${usd(lodoV)}` : ""}${rclV ? ` + recall ${usd(rclV)}` : ""}. Credit ${bcs[1]}${lodoD.length || rclV ? `; pay hours ${hm(cH + lodoD.length * 4 + rclH)} (LODO and recall are pay, not credit)` : ""}.${pa && pa.brk ? " Broken duty paid per ALPA DART 417120 (original duty protected, re-report its own duty period, PWA 4.C.3.a; LODO PWA 4.D.2.e)." : ""}`].concat(ctT.line ? [
            ctT.line + (ctT.ct && ctT.ct.projected ? ` [${ctT.ct.projected}]` : "") + (ctT.ok === false && ctT.ct ? `. Authoritative: CrewTrac ${ctT.ct.credit} credit / ${ctT.ct.block || "?"} block` : "")] : []) : []) : [];
        const payT = lines.join("\n");
        const erBtn = cH != null ? `<span class="er tag${erIs ? " on" : ""}" data-k="${this._esc(erK)}">Type-rated FO +15% ${erIs ? "ON, tap to turn off" : "off, tap to turn on (only if you flew the Extended Range type-rated FO seat, PWA 4.O.1.b; else FO/RO $3.00)"}</span>` +
          (pa ? ` <span class="rcl tag${fwRclOf(erOv, erK) ? " on" : ""}" data-k="${this._esc(erK)}">Recall ${fwRclOf(erOv, erK) ? "ON, tap to turn off" : "off, tap if this trip was a recall (200% pay, PWA 4.M.1.a)"}</span>` : "") : "";
        const fo = farOn[d] || null;
        // trip box in the Layover column: top edge on the report day, bottom edge on the release day
        const tripSpan = own.find((o) => o.it.start <= d && d <= (o.rel ? this._d(o.rel) : o.it.end));
        const bx = tripSpan ? " bx" + (tripSpan.it.start === d ? " bxs" : "") + ((o => o.rel ? this._d(o.rel) : o.it.end)(tripSpan) === d ? " bxe" : "") : "";
        const lg = legalOn[d]; const lcell = lg ? `<span class="tag lgl" title="${this._esc([`Released ${lg.rel}`, `Legal to report ${lg.t} (11 h, PWA 10.E.1.a)`, `For a 12 h+ duty leaving 1400-0359: ${lg.t18} (18 h, PWA 10.E.1.b)`].join("\n"))}">${lg.t}</span>` : "";
        return `<tr data-d="${d}" class="${wk ? "wk" : ""}${noSchool ? " hol" : (this._hol(d) ? " hol2" : "")}${other ? " oth" : ""}${blocked.has(d) ? " blk" : ""}${trip === "VAC" ? " vac" : ""}${gb ? " gg" : (gc ? " gx" : "")}${r30.has(d) ? " r30" : ""}${bx}${pdDays.has(d) ? " pdh" : ""}"><td>${DOW[dt.getDay()]}</td><td class="n" title="${r30.has(d) ? this._esc(r30Notes[d]) : ""}">${d.slice(8)}</td>` +
          `<td>${t}</td><td>${l}${rp}${rl}</td><td class="t${splitNote && trip !== PAYP ? " split" : ""}" title="${this._esc(splitNote)}">${this._esc(bcs[0])}</td><td class="t${splitNote && trip !== PAYP ? " split" : ""}${trip === PAYP ? " ppc" : ""}" title="${this._esc(splitNote)}">${this._esc(bcs[1])}${ppH != null && pp.est ? ' <span class="k">est</span>' : ""}</td><td class="t">${this._esc(bcs[2])}</td><td class="t tot1"><span class="pay${ctT.ok === false ? " ctbad" : ""}" data-info="${this._esc(payT)}" data-btn="${this._esc(erBtn)}" title="${this._esc(payT)}">${usd(total)}</span></td><td class="t" title="Pay-Gross less ${fed}% federal and ${stt}% state">${usd(net)}</td><td class="gr">${gcell}</td><td class="t far${fo && fo.bad30 ? " bad" : ""}${fo && fo.ok30 ? " ok30" : ""}${fo && fo.t30 === "&#8211;" ? " mid" : ""}" title="${fo ? this._esc(fo.t30t) : ""}">${fo ? fo.t30 : ""}</td><td class="t far${fo && fo.over ? " bad" : ""}" title="${fo ? this._esc(fo.bt) : ""}">${fo ? fo.b : ""}</td><td class="t far${fo && fo.rbad ? " bad" : ""}" title="${fo ? this._esc(fo.rt) : ""}">${fo ? fo.room : ""}</td><td class="lg">${lcell}</td><td class="o">${(opens[d] || []).join("<br>")}</td><td class="tg">${ideaBtn(d, trip)}</td></tr>`;
      }).join("");
      // FW-0080: the trips carried in (no row on this page) count their part flown in this bid period, as FLICA does
      const carryT = [];
      for (const { it, F } of carried.values()) {
        const cH = hrs(F.bcs[1]), bH = hrs(F.bcs[0]), seat = (F.ot.seat || "").toUpperCase(), nP = nOf(F.pkr, F.ot);
        const lodoC = F.pa ? F.pa.lodoDays.filter(inBp).length * 4 : 0;  // 1.7.20: a LODO day in this bid period (pay only)
        const total = cH != null ? cH * RATE + fwOverride(seat, nP, bH, cH, RATE, erOn(`${it.trip}|${it.start}`, it.lay || "", nP)).v + lodoC * RATE : null;
        sum.lodo += cH != null ? lodoC : 0;
        sum.blk += bH || 0; sum.cr += cH || 0; sum.soft += hrs(F.bcs[2]) || 0; sum.gross += total || 0; sum.net += total != null ? total * (1 - (fed + stt) / 100) : 0;
        carryT.push(`${it.trip} ${mdy(it.start)}: ${F.bcs[0] || "?"} block, ${F.bcs[1] || "?"} credit flown in this bid period${F.sp && F.sp.est ? " (credit by block share, an estimate)" : ""}`);
      }
      // fix pass (PWA 4.R.1): a PAYP with a trip added over all its days has no row; FLICA's month credit holds it
      for (const p of ppl) if (!p.it && p.h != null) { const g0 = tripFull(p.h, 0, "", "", p.k, "") || 0; sum.cr += p.h; sum.payp += p.h; sum.gross += g0; sum.net += g0 * (1 - (fed + stt) / 100); sum.ppCov.push(p); }
      for (const p of ppl) if (p.unk) sum.ppUnk = p.why;
      const fBlk = fl(tt.block), fCr = fl(tt.credit), crAll = sum.cr + sum.vac;
      // 1.6.2 review: in the award-only view the figures checked against come from the award file, not FLICA
      const srcW = awd0 ? "award" : "FLICA", srcT = awd0 ? "the award file shows" : "FLICA shows";
      const chk = (mine, flica) => flica == null ? "" : Math.abs(mine - flica) < 1 / 60 ? ` <span class="okc" title="matches ${awd0 ? "the award file" : "FLICA"}">&#10003;</span>` : ` <span class="bad" title="${srcT} ${hm(flica)}">${srcW} ${hm(flica)}</span>`;
      const bAv = 98 - (fBlk != null ? fBlk : sum.blk);
      const n30 = need30 ? `<span class="${need30 - nowHst < 48 * H ? "bad" : ""}" title="The first report after which you need 30 h off first (FAR 117.25(b)), from the schedule on file">${this._d(need30).slice(5).replace("-", "/")} ${this._hm(need30)}</span>` : `<span title="FAR 117.25(b) met for any report through the end of the schedule on file">end of sched</span>`;
      // FW-0009 (Ryan, Nov 6): three groups (hours, pay, days) that wrap as units; Pay-Gross and Pay-Net share one
      // unbreakable row (on an iPhone their own line) and no label is ever split from its value
      const tgrp = (cls, list) => { const s = list.filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `<span class="ti"><span class="k">${k}</span> ${v}</span>`).join(""); return s ? `<span class="tgrp ${cls}">${s}</span>` : ""; };
      // fix pass: the PAYP estimate is FLICA's credit less the rest, so Credit matches FLICA by construction: no check mark
      const ppCovT = sum.ppCov.map((p) => `${String(p.rec.protected || "").split(",").filter(Boolean).map((q) => `${q.split("|")[0]} ${mdy(q.split("|")[1] || "")}`).join(" and ") || "The removed trip"}: ${hm(p.h)} kept with ${p.cov.trip} ${mdy(p.cov.start)} added on its days (PWA 4.R.1: Pay and Credit of the PAYP day and of the added trip).`).join(" ");
      // Paychecks (Ryan, Nov 19, 2026): this month's pay as the next month's two paychecks. PWA 2.A.56: the 7th pays the
      // next month's advance (half the 75:00 MMG, 37:30 x rate) and the 22nd pays this month's actuals less the advance
      // already paid on this month's 7th; a payday on a weekend moves to the Friday before (2.A.56.b; holidays not
      // checked). Per-check model (Ryan, Nov 19): on the admin's card, with the Pay model sensor on file (kept
      // current from the pay stubs), each check is worked out per check (fwgCheck: Pub 15-T withholding, Social
      // Security, Medicare, 401(k), benefits, after-tax deductions, the ER 415(c) excess on the 22nd) from the flying
      // of the month it pays: Pay-Gross plus FLICA credit the card does not price (SIM, sick, training) at the month's
      // rate, never below the 75:00 MMG. Checks between the last stub and these are worked through in order so the
      // year-to-date limits carry. Otherwise (a pilot's card, no model): the flat tax settings, as Pay-Net does.
      // FW-0072: the state picker's month of pay (x 12 for a year): this month's Pay-Gross, or 75:00 (the MMG) at his rate
      this._payGrossMo = noYear ? 0 : sum.gross > 0 ? sum.gross : RATE * 75; this._payGrossWhy = sum.gross > 0 ? "this month's Pay-Gross x 12" : "75:00 a month at your rate x 12";
      const chkGrp = (() => {
        if (noYear || !(sum.gross > 0)) return "";
        const ny = m === 11 ? y + 1 : y, nm = (m + 1) % 12;  // the month the checks land in (m is 0-based)
        const pd = (yy, mm0, dd) => { const t = new Date(Date.UTC(yy, mm0, dd)); const w = t.getUTCDay(); if (w === 6) t.setUTCDate(dd - 1); if (w === 0) t.setUTCDate(dd - 2); return t; };
        const lbl = (t) => `${MONTHS[t.getUTCMonth()].slice(0, 3)} ${t.getUTCDate()}`;
        const iso = (t) => t.toISOString().slice(0, 10);
        const mk = (yy, mm0) => new Date(Date.UTC(yy, mm0, 1)).toISOString().slice(0, 7);
        const d7 = pd(ny, nm, 7), d22 = pd(ny, nm, 22);
        const adv = (yy, mm0) => 37.5 * rateFor(lyr, `${mk(yy, mm0)}-01`);
        const PM = admin ? (S["sensor.flight_watcher_pay_model"] || {}).attributes || null : null;
        if (PM && Array.isArray((PM.tables || {}).single) && PM.ytd && FWG_ISO.test(PM.last_stub || "")) {
          const imp = ((S["sensor.flight_watcher_improved_pay_gross"] || {}).attributes || {}).months || [];
          const mPay = (yy, mm0) => {  // the bid period's pay that the 22nd check settles
            const k = mk(yy, mm0), R = rateFor(lyr, `${k}-15`), mmg = 75 * R;
            if (k === key) {
              const xh = Math.max(0, (fCr || 0) - crAll - sum.cut), p = sum.gross + xh * R;  // 1.7.20: never FLICA's double-counted delayed leg
              return { pay: Math.max(p, mmg), why: p < mmg ? `${MONTHS[mm0]} flying ${usd(p)} is under the 75:00 MMG, so ${usd(mmg)}` : `${MONTHS[mm0]} Pay-Gross ${usd(sum.gross)}${xh > 0.01 ? ` plus ${hm(xh)} FLICA credit the card does not price (SIM, sick, training) at $${R.toFixed(2)}` : ""}` };
            }
            const row = imp.find((r) => r && r.month === k), cr = fl(((SM[k] || {}).totals || {}).credit);
            const p = Math.max((row && +row.current) || 0, (cr || 0) * R);
            return { pay: Math.max(p, mmg), why: p > 0 ? `${MONTHS[mm0]} pay ${usd(Math.max(p, mmg))} from FW (that month's view prices it more closely)` : `no ${MONTHS[mm0]} schedule in FW, so the 75:00 MMG` };
          };
          const ytd = { year: +(PM.ytd.year || PM.last_stub.slice(0, 4)), ss_wages: +PM.ytd.ss_wages || 0, med_wages: +PM.ytd.med_wages || 0, c415: +PM.ytd.c415 || 0, ee401: +PM.ytd.ee401 || 0 };
          const paid = PM.paid || {}, out = {};
          let cy = +PM.last_stub.slice(0, 4), cm = +PM.last_stub.slice(5, 7) - 1;
          for (let guard = 0; guard < 36 && (cy < ny || (cy === ny && cm <= nm)); guard++) {
            const a = pd(cy, cm, 7), t = pd(cy, cm, 22), pm0 = cm === 0 ? 11 : cm - 1, py0 = cm === 0 ? cy - 1 : cy;
            const ga = adv(cy, cm), mp = mPay(py0, pm0), gt = mp.pay - adv(py0, pm0);
            const evs = [[a, { gross: ga, eligible: ga, erBase: 0 }, `${MONTHS[cm]} advance, 37:30 x $${(ga / 37.5).toFixed(2)}`],
              [t, { gross: gt, eligible: gt, erBase: mp.pay, meal: +PM.meal_nt || 0 }, `${MONTHS[pm0]} true-up: ${mp.why}, less the ${usd(adv(py0, pm0))} advance`]];
            for (const [dt, g, what] of evs) {
              const di = iso(dt);
              if (di <= PM.last_stub) { if (paid[di] != null) out[di] = { paid: +paid[di], what }; continue; }
              out[di] = { ...fwgCheck({ ...g, date: di }, ytd, PM), what };
            }
            cm += 1; if (cm > 11) { cm = 0; cy += 1; }
          }
          for (const dt of [d7, d22]) if (!out[iso(dt)] && paid[iso(dt)] != null) out[iso(dt)] = { paid: +paid[iso(dt)] };  // an earlier month's checks, already paid
          const yr = (+PM.tax_year) || 2026;
          const c2 = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          const tipOf = (di, r) => {
            if (r.paid != null) return this._esc(`${di}: paid. Net ${c2(r.paid)} (pay stub).`);
            return this._esc([`${di}: ${r.what}.`, `Gross ${c2(r.gross)}${r.erCash ? ` (with ${c2(r.erCash)} ER 415(c) excess)` : ""}`,
              `Federal ${c2(r.fed)}, Social Security ${c2(r.ss)}, Medicare ${c2(fwgR2(r.med + r.addl))}`,
              `401(k) ${c2(r.def)}, benefits ${c2(r.pre)}, after-tax deductions ${c2(r.aft)}`,
              `Net ${c2(r.net)}; to main checking after ${c2(+PM.allot || 0)} allotments ${c2(r.toChk)}`,
              `Estimate from pay stubs through ${PM.last_stub}${+di.slice(0, 4) > yr ? `; ${yr} tax tables until ${di.slice(0, 4)}'s are loaded` : ""}.`].join("\n"));
          };
          const val = (r) => r ? (r.paid != null ? r.paid : r.net) : null;
          const cell = (di) => { const r = out[di]; return r && val(r) != null ? `<span title="${tipOf(di, r)}">${usd(val(r))}</span>` : ""; };
          const a7 = out[iso(d7)], a22 = out[iso(d22)];
          const both = val(a7) != null && val(a22) != null ? val(a7) + val(a22) : null;
          const chk2 = a7 && a22 && a7.toChk != null && a22.toChk != null ? `; to main checking ${c2(fwgR2(a7.toChk + a22.toChk))}` : "";
          return tgrp("tchk", [[lbl(d7), cell(iso(d7))], [lbl(d22), cell(iso(d22))],
            [`${MONTHS[nm].slice(0, 3)} total`, both == null ? "" : `<span title="${this._esc(`${MONTHS[nm]} paychecks together: net ${c2(fwgR2(both))}${chk2}.`)}">${usd(both)}</span>`]]);
        }
        // FW-0072: a pilot's deductions percent from his pay stub (this device only) comes out of the checks too
        const ded = admin ? 0 : this._payDed(), g7 = adv(ny, nm), g22 = sum.gross - adv(y, m), k = 1 - (fed + stt + ded) / 100;
        const tip = (g, what) => this._esc(`${what}. Gross ${usd(g)}, net after ${fed}% federal and ${stt}% state${ded ? ` and ${ded}% deductions (benefits, 401(k), dues: from your pay stub)` : ""} ${usd(g * k)}.${ded ? "" : " Benefit, 401(k) loan and dues deductions not taken out."} Estimate (PWA 2.A.56).`);
        const cell = (g, what) => `<span title="${tip(g, what)}">${usd(g * k)}</span>`;
        return tgrp("tchk", [[lbl(d7), cell(g7, `${lbl(d7)} (${iso(d7)}): ${MONTHS[nm]} advance, 37:30 x ${"$" + (g7 / 37.5).toFixed(2)}`)],
          [lbl(d22), cell(g22, `${lbl(d22)} (${iso(d22)}): ${MONTHS[m]} true-up, Pay-Gross ${usd(sum.gross)} less the ${usd(adv(y, m))} advance paid on the 7th`)],
          [`${MONTHS[nm].slice(0, 3)} total`, cell(g7 + g22, `${MONTHS[nm]} paychecks together`)]]);
      })();
      const cutT = sum.cut > 0.01 ? ` <span class="k" title="${this._esc(`FW counts ${hm(sum.cut)} less than FLICA: a delayed leg FLICA counted twice (PWA 2.A.15.a.1, 4.B.1). ${sum.cutT.join("; ")}. Tap the trip's Pay-Gross for the breakdown.`)}">PWA -${hm(sum.cut)}</span>` : "";
      const tot = tgrp("thrs", [["Credit", hm(crAll) + cutT + (sum.ppEst ? ` <span class="k" title="${this._esc(`Not checked: the PAYP estimate is ${srcFl}'s month credit less everything else counted, so Credit matches it by construction.`)}">est</span>` : chk(crAll, fCr))], ["CrewTrac", !admin ? "" : (() => { const c = fwCtMonth(ctSnap, key, hm(crAll), Date.now()); const bad = c.ok === false || sum.ctBad.length > 0;
          return c.line || sum.ctBad.length ? `<span class="${bad ? "bad" : "okc"}" title="${this._esc([c.line, sum.ctBad.length ? `Trips off CrewTrac (tap the Pay-Gross): ${sum.ctBad.join(", ")}` : ""].filter(Boolean).join("\n"))}">${c.ok === true && !sum.ctBad.length ? "&#10003;" : c.ok === null && !sum.ctBad.length ? this._esc(c.line.replace(/^CrewTrac /, "")) : `&#10007; ${sum.ctBad.length ? sum.ctBad.length + " trip" + (sum.ctBad.length > 1 ? "s" : "") : ""}${c.ok === false ? `${sum.ctBad.length ? ", " : ""}month ${this._esc(c.line.replace(/^.*off by /, "").replace(/ \(CrewTrac controls\)$/, ""))}` : ""}`}</span>` : ""; })()],
        ["Block", hm(sum.blk) + chk(sum.blk, fBlk)], ["Block Avail", `<span class="${bAv <= 0 ? "bad" : ""}" title="98:00 bid-month block cap (crew scheduling) minus FLICA's bid-period Block">${bAv < 0 ? "-" + hm(-bAv) : hm(bAv)}</span>`], ["Soft", hm(sum.soft)],
        ["Vacation", sum.vacDays ? `${hm(sum.vac)} <span class="k">(${sum.vacDays} d x ${hm(VAC_H)})</span>` : ""],
        // 1.7.20: pay with no credit (PWA 4.D.2.e LODO, the recall's extra 100%, 4.M.1.a): inside Pay-Gross, never in Credit
        ["LODO", sum.lodo ? `<span class="ppt" title="${this._esc(`Loss of Day Off: 4:00 pay, no credit, per day off lost (PWA 4.D.2.e). Inside Pay-Gross and the paychecks, not in Credit.`)}">${hm(sum.lodo)} <span class="k">pay only</span></span>` : ""],
        ["Recall", sum.rcl ? `<span class="ppt" title="${this._esc(`Recall: 200% pay, 100% credit (PWA 4.M.1.a). The extra 100% is inside Pay-Gross, not in Credit.`)}">+${hm(sum.rcl)} <span class="k">pay only</span></span>` : ""],
        // 1.7.2: the pay protected credit inside Credit (never in Block or Block Avail: not flown)
        ["PAYP", sum.payp || sum.ppUnk ? `<span class="ppt" title="${this._esc(`Pay protected credit inside Credit, Pay-Gross and Pay-Net (${PAYP_REF}). Not in Block or Block Avail: not flown.${sum.ppEst ? ` Estimate: ${srcFl}'s month credit less everything else counted.` : ""}${ppCovT ? " " + ppCovT : ""}${sum.ppUnk ? ` A PAYP's credit is unknown and not counted: ${sum.ppUnk}.` : ""}`)}">${sum.payp ? hm(sum.payp) : ""}${sum.ppEst ? ' <span class="k">estimate</span>' : ""}${sum.ppUnk ? `${sum.payp ? " +" : ""} <span class="bad">credit unknown</span>` : ""}</span>` : ""]]) +
        tgrp("tpay", noYear ? [["Pay", "set your longevity year in Pay settings"]] : [["Pay-Gross", usd(sum.gross)], ["Pay-Net", usd(sum.net)]]) + chkGrp +
        tgrp("tdays", [["Days Off", tt.days_off == null ? "" : this._esc(tt.days_off)], ["Need 30 h off by", n30]]);
      if (this._idea && this._idea.key === key) {
        const r = ideasFor(this._idea.d, this._idea.trip);
        const md = (iso) => `${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(0, 1)}${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(1).toLowerCase()} ${parseInt(iso.slice(8), 10)}`;
        if (r) {
          const rowsI = r.list.slice(0, 25).map((x) => `<tr class="${x.src ? "on" : "off"}"><td><b>${this._esc(x.p.id)}</b></td><td>${md(x.sd)}${x.end !== x.sd ? " - " + md(x.end) : ""}</td><td>${this._esc(x.lay || x.p.route)}</td><td class="t">${(x.p.relDays || 0) + 1}</td><td class="t">${this._esc(String(x.p.credit).replace("h", ":"))}</td><td class="t">${usd(x.pay)}</td><td class="t ${x.delta >= 0 ? "up" : "dn"}">${Number.isNaN(x.delta) ? "" : (x.delta >= 0 ? "+" : "-") + usd(Math.abs(x.delta))}</td><td>${x.src === "O" ? "Open time" : x.src === "T" ? "Tradeboard" : "not open now"}</td><td class="k">R ${this._esc(x.p.report)} ${x.p.crew ? "· " + this._esc(x.p.crew) : ""}${x.rest ? " · " + x.rest : ""}</td></tr>`).join("");
          panel = `<div class="ipanel"><div class="ihd"><b>${r.o ? `Swap ideas for ${this._esc(r.o.it.trip)} ${md(r.o.it.start)} (yours ${usd(r.cur)})` : `Pick-up ideas starting ${md(this._idea.d)}`}</b> <span class="k">window ${md(r.a)} - ${md(r.b)}: days you have not blocked and have nothing else on</span><span class="ix" title="Close">&#10005;</span></div>` +
            (rowsI ? `<div class="wrap"><table class="itab"><tr><th>Trip</th><th>Dates</th><th>Layover</th><th>Days</th><th>Credit</th><th>Pay-Gross</th><th>${r.o ? "vs yours" : "adds"}</th><th>Where</th><th>Report · crew · rest</th></tr>${rowsI}</table></div>` : `<div class="k">Nothing fits that window.</div>`) +
            `<div class="k">Pay-Gross = package credit x ${rateTxt} (min 5:00 per calendar day, PWA 4.C.3) + IRO crew FO $3.00 per block hour or Extended Range type-rated FO +15% (PWA 4.O.1). Rest: 11 h at domicile (PWA 10.E.1.a). FAR 117 is not checked here: see the FAR columns once it is on your line. Swaps go through FLICA; nothing is filed from here.</div></div>`;
        }
      }
      // versions bar: Awarded-Pay-Gross (version .001, the awarded line) and Improved-Pay-Gross (current minus awarded)
      if (vl.length && liveMon) {
        const awd = price(vl[0], mergeT(liveOwnT, vl[0].trips)), curG = price(liveMon, liveOwnT), imp = curG - awd;
        const shown = vsel || vl[vl.length - 1];
        const cg = vsel ? price(mon, ownT) : curG;
        const isCur = !vsel;
        // FW-0008 (Ryan, Nov 6): two groups that wrap as units: the version arrows, then Awarded-Pay-Gross with
        // Improved-Pay-Gross (on an iPhone their own line); a label never wraps away from its value
        vhtml = `<div class="vbar"><span class="vg"><span class="nw"><span class="vb" data-v="prev" title="Older version">&#9664;</span> <b>v${this._esc(shown.ver)}</b> <span class="vb" data-v="next" title="Newer version">&#9654;</span> <span class="vb${isCur ? " here" : ""}" data-v="home" title="Current version">&#127968;</span></span> <span class="k">${isCur ? `<span class="nw">${vl.length} versions (current)</span>` : `${vl.length} versions · viewing <span class="nw">${this._esc((shown.at || "").slice(0, 10))},</span> <span class="nw">Pay-Gross ${usd(cg)}</span>`}</span></span>` +
          (noYear ? `<span class="vg vpay"><span class="k">Pay: set your longevity year in Pay settings</span></span>` :
          `<span class="vg vpay"><span class="nw"><span class="k">Awarded-Pay-Gross</span> <b>${usd(awd)}</b> <span class="k">(v${this._esc(vl[0].ver)})</span></span>` +
          `<span class="nw"><span class="k">Improved-Pay-Gross</span> <b class="${imp >= 0 ? "up" : "dn"}">${imp >= 0 ? "+" : "-"}${usd(Math.abs(imp))}</b></span></span>`) +
          `</div>`;
        const chg = (shown.changes || []).filter((c) => !/ \? -> /.test(c));
        chtml = `<details class="chg"><summary>Changes in v${this._esc(shown.ver)}${shown.at ? " (" + this._esc(String(shown.at).slice(0, 10)) + ")" : ""}</summary>${chg.length ? "<ul>" + chg.map((c) => "<li>" + this._esc(c) + "</li>").join("") + "</ul>" : "<div>No trip or pay changes (first reads of seat or times only).</div>"}</details>`;
        const sig = `${key}|${Math.round(awd)}|${Math.round(curG)}|${vl[vl.length - 1].ver}`;
        this._impSig = this._impSig || {};
        // 1.7.1 (F#32): only once the pairings package is in or known to be missing (pk null = still loading). Priced
        // before that, a trip without its own times pays 0 and no crew override, and the Watcher would store that low
        // figure until the redraw sent the right one (two reports a load, one of them wrong)
        // 1.7.11 review: and every other bid period's package a price or split asked for (packWait), so a trip across
        // the bid period's edge is priced with its duties' TCRD, not its block share first
        if (this._impSig[key] !== sig && this._h && !noYear && pk !== null && !packWait) {
          this._impSig[key] = sig;
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/improved/set", payload: JSON.stringify({ month: key, awarded: Math.round(awd * 100) / 100, current: Math.round(curG * 100) / 100, ver: vl[vl.length - 1].ver, awarded_ver: vl[0].ver }) });
        }
      }
      const head = `<tr class="hd"><th></th><th></th><th>Trip</th><th>Layover</th><th>Block</th><th>Credit</th><th>Soft</th><th title="Credit pay + crew override (PWA 4.O.1) + LODO and recall pay; hover or tap for the breakdown with PWA cites">Pay-Gross</th><th>Pay-Net</th><th title="Reserve grid net reserves">Res Grid</th><th class="fh" title="FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h (7 days) before a report. &#10003; 36h MM/DD = a report at that day's first duty start (00:01 on a day off) is covered: the longest break off duty in the 168 h before it, in whole hours, and the day it ended. A later report that day may not be: hover a cell for the hours and 'covered until'. The teal edge on a day marks the break itself.">30h in 7d</th><th class="fh" title="FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours (28 days). Left = 100:00 minus the block flown or scheduled in the 672 h ending 24:00 that day; over = past the limit by that much.">100h in <br class="hb">672h</th><th class="fh" title="FAR 117.23(b)(1) (100 flight hours in any 672 consecutive hours): 100:00 minus the busiest 672 h window that holds any part of the day, back and forward: the windows starting at a duty's start or ending at its block-in, as a pickup's FAR check tries them, and those ending 24:00 HST.">Room to <br class="hb">100h</th><th title="Earliest report for another trip">Legal next</th><th>Open</th><th title="Tap the airplane: swap or pick-up ideas for that day, with the Pay-Gross difference">Ideas</th></tr>`;
      const bpTxt = `${mdy(bp.from)} to ${mdy(bp.to)}${bp.src === "package" ? " (the pairings package)" : bp.src === "schedule" ? " (the schedule pages: no pairings package on file)" : " (the calendar month: no pairings package or schedule page gives the bid period)"}`;
      const totT = `${MONTHS[m]} totals: flown in the bid period, ${bpTxt}: each segment credited to the bid period it originates in (PWA 4.A), a trip across the bid period's edge its part here, plus vacation days at ${hm(VAC_H)} (PWA 6.J) and pay protected (PAYP) credit (PWA Definitions 57). Pay at ${rateTxt}/credit h incl. the PWA 4.O.1 crew override, LODO (4.D.2.e) and recall (4.M.1.a) pay where due; net after the tax settings. Checked against FLICA's Block and Credit.${carryT.length ? ` Also counted: ${carryT.join("; ")}.` : ""}`;
      body = `<div class="wrap"><table class="cal">${head}${rows}</table></div>${pdM && !narrow ? fwgPanelHtml(pdM) : ""}<div class="tot" title="${this._esc(totT)}">${tot}</div>${carryT.length ? `<div class="cin">Also counted (PWA 4.A): ${this._esc(carryT.join("; "))}.</div>` : ""}${bp.src === "calendar" ? `<div class="cin">Totals over the calendar month: no pairings package or schedule page on file gives this bid period.</div>` : ""}`;
    }
    const upd = awd0 ? "" : st && st.attributes ? (st.attributes.updated || "") : "";
    // 1.6.2: the award label and the read status sit above the grid (or the 'No schedule' line)
    // 1.6.2 (item 12): pay settings copied from never-set helpers (0 %, 0 %, year 1) are flagged, never silently used
    // 1.6.4: once a DOH is saved the longevity year comes from it (unless he picked one): no longer asked for
    const unconf = PAY_PREFS.filter((e) => e === PAY_PREFS[2] ? !doh && (((S[e] || {}).attributes || {}).unconfirmed === true || noYear)
      : ((S[e] || {}).attributes || {}).unconfirmed === true || (this._role() !== "admin" && isNaN(parseFloat((S[e] || {}).state))));
    const shead = (awd0 ? `<div class="awl">Awarded line from the award file. FLICA schedule not read yet.</div>` : "") +
      (rsLine ? `<div class="rsl">${this._esc(rsLine)}</div>` : "") +
      (unconf.length ? `<div class="unc ubn">Set your tax and longevity in Pay settings (below): ${unconf.map((e) => PAY_PREF_LABEL[e]).join(", ")} ${unconf.length > 1 ? "are" : "is"} not set yet; ${noYear ? "no pay is figured until your longevity year is set" : "pay is estimated with them as shown"}.</div>` : "");
    const flagged = PAY_PREFS.filter((e) => ((S[e] || {}).attributes || {}).unconfirmed === true && !(e === PAY_PREFS[2] && lyByDoh));  // values to keep
    const sel = (lo, hi, step, cur, suf) => { const o = []; for (let v = lo; v <= hi + 1e-9; v += step) { const r = Math.round(v * 100) / 100; o.push(`<option value="${r}"${Math.abs(r - cur) < 1e-9 ? " selected" : ""}>${r}${suf}</option>`); } return o.join(""); };
    const main = this.shadowRoot.querySelector(".fwm");
    const ae = this.shadowRoot.activeElement;
    const fk = ae && ae.matches && ae.matches(".fwm .trip[data-k]") ? ae.dataset.k : "";  // the pairing that has the focus
    const lf = !!(ae && ae.matches && ae.matches(".fwm .lock"));  // 1.7.18: the lock switch keeps the focus across a redraw
    main.innerHTML = `<style>${FWG_CSS}
      ha-card{padding:10px 8px 12px;font-size:12.5px;line-height:1.25;box-sizing:border-box}
      @media (max-width:700px){ha-card{font-size:10.5px;padding:6px 3px 8px}
        .lt td:first-child{width:90px}.set span{display:block;margin:2px 0}.nav{font-size:20px}}
      .vbar{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 14px;text-align:left;font-size:12px;margin:0 0 6px;padding-left:0}.vbar .vpay{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 10px}.vbar .nw{white-space:nowrap}
      @media (max-width:700px){.vbar{font-size:11px;column-gap:10px}.vbar .vpay{column-gap:8px}.vbar .vb{font-size:12px}}.vbar .vb{cursor:pointer;padding:0 6px;color:var(--primary-color)}.vbar .vb.here{opacity:.5}.vbar .vch{opacity:.7;font-size:11px}.vbar .up,.ipanel .up{color:var(--fw-ok,#2e7d32)}.vbar .dn,.ipanel .dn{color:var(--fw-err,#c62828)}
      .idb{cursor:pointer;color:var(--secondary-text-color,#727272);white-space:nowrap}.idb.live{color:var(--primary-color);font-weight:700}.idb small{color:var(--fw-ok,#2e7d32)}
      .ipanel{margin:10px 0;padding:8px;border:1px solid var(--divider-color,#ccc);border-radius:8px}.ipanel .ihd{margin-bottom:6px}.ipanel .ix{float:right;cursor:pointer;padding:0 6px}
      .itab{border-collapse:collapse;font-size:12px;width:100%}.itab td,.itab th{border-bottom:1px solid var(--divider-color,#ddd);padding:3px 5px;text-align:left}.itab td.t{text-align:right}.itab tr.off{opacity:.55}
      .hd2{display:flex;align-items:center;gap:8px;margin:0 0 6px;flex-wrap:wrap}.hd2 .sp{flex:1}.chg{margin:6px auto 0;max-width:620px;font-size:11px;color:var(--secondary-text-color);text-align:center}.chg summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none}.chg summary::-webkit-details-marker{display:none}.chg summary::before{content:"\\25B8 "}.chg[open] summary::before{content:"\\25BE "}.chg ul{display:inline-block;text-align:left;margin:4px 0 0;padding-left:16px}.chg li{margin:1px 0}
      .nav{cursor:pointer;font-size:22px;line-height:1;padding:0 8px;border-radius:6px;color:var(--primary-color);user-select:none}
      .nav.now{font-size:11px;padding:3px 8px;border:1px solid var(--divider-color)}.nav:hover{background:rgba(0,0,0,.06)}
      h3{margin:0;font-size:16px}
      table{border-collapse:collapse;margin:0 auto}
      .cal th:nth-child(n+5):nth-child(-n+12){text-align:right}
      .far{font-size:11px;white-space:nowrap}@media (min-width:701px){.cal td.far,.cal th.fh{padding-left:4px;padding-right:4px}}@media (max-width:700px){.cal th .hb{display:none}}.far.bad{color:var(--fw-err,#c62828);font-weight:700}.far.ok30{color:var(--fw-ok,#2e7d32);font-weight:700;text-align:center;white-space:nowrap}.far.ok30 .k{font-weight:400;font-size:10px;color:var(--secondary-text-color,#555)}
      .cal tr.r30 td:nth-child(1){box-shadow:inset 4px 0 0 #00897b}
      .cal td.t.split{color:var(--fw-split,#7b1fa2);cursor:help}:host([dark]){--fw-split:#ce93d8}
      .cin{margin:4px auto 0;max-width:620px;font-size:11px;text-align:center;color:var(--secondary-text-color)}
      .cal td.far.mid{color:var(--secondary-text-color,#727272);text-align:center}
      .tot1{font-weight:600}
      .cal tr.gg td:nth-child(4),.cal tr.gg td:nth-child(10){background:rgba(76,175,80,.12)}
      .cal tr.gx td:nth-child(4),.cal tr.gx td:nth-child(10){background:rgba(229,57,53,.12)}
      :host([dark]) .cal tr.gg td:nth-child(4),:host([dark]) .cal tr.gg td:nth-child(10){background:rgba(76,175,80,.28)}
      :host([dark]) .cal tr.gx td:nth-child(4),:host([dark]) .cal tr.gx td:nth-child(10){background:rgba(229,57,53,.3)}
      :host([dark]) .trip.tr{background:rgba(255,160,0,.4)}
      :host([dark]) .nav:hover{background:rgba(255,255,255,.1)}
      .cal tr[data-d] td:nth-child(-n+2){cursor:pointer}
      .cal tr.blk td.n::after{content:" \\2298";color:#e53935;font-weight:700}
      :host{--fws-on:#1565c0;--fws-off:#5f6368;--fws-knob:#fff;--fws-ring:#1565c0}:host([dark]){--fws-on:#90caf9;--fws-off:#a7b0b8;--fws-knob:#0d2235;--fws-ring:#90caf9}
      .lock{display:inline-flex;align-items:center;gap:6px;box-sizing:border-box;min-height:44px;min-width:44px;margin:0 auto 0 0;padding:0 8px 0 4px;border:0;border-radius:8px;background:none;color:var(--primary-text-color);font:600 12px/1 sans-serif;cursor:pointer;user-select:none;-webkit-user-select:none;-webkit-tap-highlight-color:transparent}
      @media (hover:hover){.lock:hover{background:rgba(0,0,0,.06)}:host([dark]) .lock:hover{background:rgba(255,255,255,.1)}}.lock:focus-visible{outline:3px solid var(--fws-ring);outline-offset:1px}
      @media (max-width:700px){.hd2{row-gap:2px}.hd2 .sp{flex:0 0 100%;height:0}}
      .lock .lki{flex:none;width:20px;height:20px}.lock .lkt{position:relative;flex:none;box-sizing:border-box;width:40px;height:24px;border:2px solid var(--fws-off);border-radius:12px;background:transparent}
      .lock .lkk{position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:var(--fws-off)}.lock .lks{min-width:22px;text-align:left}
      .lock.shut .lkt{background:var(--fws-on);border-color:var(--fws-on)}.lock.shut .lkk{left:19px;background:var(--fws-knob)}.lock.shut .lks{font-weight:700}
      @media (forced-colors:active){.lock .lkk{forced-color-adjust:none;background:CanvasText}.lock.shut .lkt{forced-color-adjust:none;background:Highlight;border-color:Highlight}.lock.shut .lkk{background:Canvas}}
      .ppt{cursor:help}.ppc .k{font-size:9.5px;color:var(--secondary-text-color)}
      .cal tr.gg td:nth-child(1),.cal tr.gg td:nth-child(2){font-weight:700}
      .gr{text-align:right;font-size:11px}.g.green{color:var(--fw-ok,#2e7d32);font-weight:700}.g.red{color:var(--fw-err,#c62828);font-weight:700}.g.black{color:var(--primary-text-color)}
      .er{color:var(--secondary-text-color);cursor:pointer;text-decoration:underline dotted}.er.on{color:var(--fw-ok,#2e7d32);font-weight:700}.pay{cursor:help}.pay.ctbad{color:var(--fw-err,#c62828);font-weight:700;text-decoration:underline wavy var(--fw-err,#c62828)}
      .set{margin:8px auto 0;max-width:620px;font-size:11px;color:var(--secondary-text-color);text-align:center}
      .set summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none;margin-bottom:3px}.set summary::before{content:"\\25B8 "}.set[open] summary::before{content:"\\25BE "}
      .set span{margin:0 8px;white-space:nowrap}.set select{font-size:11px;margin-left:3px}.set .r{margin-top:3px}
      @media (max-width:700px){.set select,.set input[type=file]{font-size:16px}}
      .lg{font-size:11px}.lgl{color:var(--fw-info,#1565c0);font-weight:600;cursor:help}
      .trip.tr{background:rgba(255,160,0,.28);border-radius:4px;padding:0 3px;color:var(--primary-text-color)}
      .trb{display:inline-block;font-size:19px;line-height:1;padding:0 6px;margin:-4px 0 -4px 2px;color:var(--secondary-text-color,#727272);cursor:pointer;vertical-align:middle;border-radius:5px}
      .trb.on{color:var(--fw-warn,#8a5300);background:rgba(255,160,0,.28)}
      .drb{display:inline-block;font-size:17px;line-height:1;padding:0 5px;margin:-4px 0 -4px 1px;color:var(--secondary-text-color,#727272);cursor:pointer;vertical-align:middle;border-radius:5px}
      .drb.on{color:var(--fw-err,#c62828);background:rgba(229,57,53,.18)}.drb.on.rdy{color:#fff;background:#2e7d32}
      .trb:hover{background:rgba(0,0,0,.08)}:host([dark]) .trb:hover{background:rgba(255,255,255,.12)}
      .sw{color:var(--fw-warn,#8a5300);font-weight:600;cursor:help}
      .o{font-size:11px}.fit{font-weight:700;color:var(--fw-ok,#2e7d32)}
      .clash{text-decoration:line-through;color:var(--secondary-text-color)}
      .tg{font-size:10.5px;color:var(--secondary-text-color)}
      .more{color:var(--primary-color);font-weight:700;padding:0 3px}.tag.avail{color:var(--fw-ok,#2e7d32);font-weight:600}
      .lt{margin:0 auto;text-align:left}.lt td{padding:1px 6px;vertical-align:top}.lt td:first-child{font-weight:700;white-space:nowrap}
      .leg{font-size:10.5px;color:var(--secondary-text-color);text-align:center;margin-top:6px}
      .leg summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none}.leg summary::before{content:"\\25B8 "}.leg[open] summary::before{content:"\\25BE "}
      .info{display:none;position:fixed;left:8px;right:8px;bottom:14px;z-index:9;margin:0 auto;max-width:460px;font-size:12px;padding:8px 10px 8px;border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);box-shadow:0 4px 18px rgba(0,0,0,.35);cursor:pointer}
      .info::after{content:"tap to close";display:block;margin-top:6px;font-size:10px;color:var(--secondary-text-color);text-align:right}
      ${FW_AGE_BOX_CSS}
      .none{text-align:center;color:var(--secondary-text-color);padding:12px}
      .awl,.rsl{margin:2px auto 6px;max-width:620px;text-align:center;font-size:12px;line-height:1.3}.awl{font-weight:600}.rsl{color:var(--fw-warn,#8a5300)}
      .ag{font-size:11px;font-weight:600;color:var(--secondary-text-color);white-space:nowrap;font-variant-numeric:tabular-nums;cursor:pointer}
      .ag[data-age="amber"]{color:var(--fw-warn,#8a5300)}.ag[data-age="red"]{color:var(--fw-err,#c62828)}
      .hd2 .ag{margin-left:auto;text-align:right;white-space:normal;min-width:0;flex:0 0 21em}
      @media (max-width:700px){.hd2 .ag{order:1;flex:1 1 0}.hd2 .sp{order:2}.hd2 .nav,.hd2 h3{order:3}}
      .unc{color:var(--fw-warn,#8a5300);font-weight:700}.ubn{margin:2px auto 6px;max-width:620px;text-align:center;font-size:12px;line-height:1.3}.set .keep{min-height:44px;padding:6px 12px;font:inherit;border-radius:6px;cursor:pointer}
    </style><ha-card><div class="frame"><div class="hd2">${this._lockHtml()}<span class="sp"></span><span class="nav" data-nav="-1" title="Previous month">&#8249;</span><h3>${MONTHS[m]} ${y}</h3><span class="nav" data-nav="1" title="Next month">&#8250;</span><span class="nav now" data-nav="0" title="This month">Now</span>${this._ageHtml(upd)}</div>${shead}${vhtml}${body}</div>${panel}
    <div class="info"></div>
    <details class="leg"><summary>Key</summary><table class="lt">
    <tr><td>Trip</td><td>Your pairing. Tap it for the pairing detail (legs, layovers, hotel, totals and crew, from the pairings package; below the schedule, or a sheet from the bottom on a phone); tap it again, the &#10005; or Esc to close. R = report time. Tap &#8644; to mark it "would trade" (orange).</td></tr>
    <tr><td>Layover</td><td>Layover city. <b>Bold</b> = turn, no layover. Rel = release time (block-in + 15 min).</td></tr>
    <tr><td>Block / Credit / Soft</td><td>Your trip's block, credit and soft time (credit minus block), from FLICA's pairing page. Purple = this bid period's part only (FLICA totals the bid period: December 2026 runs Dec 2 to Dec 31); the rest pays in the bid period its duties depart in (PWA 4.A), hover for the split. A trip from the bid period before that flies into this one counts its part here, named under the totals.</td></tr>
    <tr><td>Totals</td><td>Month totals incl. vacation at ${hm(VAC_H)} a day (PWA 6.J); &#10003; = matches FLICA's figure, red = FLICA differs.</td></tr>
    <tr><td>PAYP</td><td>Pay protected: a trip removed from your schedule keeps its Pay and Credit (PWA Definitions 57). Its credit counts in Credit, Pay-Gross and Pay-Net on the PAYP's first day, at your rate; never in Block, Block Avail or the FAR columns (not flown). A trip whose duties depart in two bid periods counts each bid period's part there (PWA 4.A). est = the removed trip is not on file, so the credit is FLICA's month credit less everything else (only when the card counts everything else in the month; Credit then shows est, not a check). Credit unknown = not counted (no FLICA total, other credited codes, a trip not read yet). A trip you add on PAYP days pays on top (PWA 4.R.1), also when it covers every PAYP day.</td></tr>
    <tr><td>Pay-Gross / Pay-Net</td><td>Gross = credit x ${rateTxt} + crew override + LODO and recall pay; hover or tap it for the breakdown (which credit test won, segments, rig, LODO, override, recall, with PWA cites). Net = gross after the tax settings below.</td></tr>
    <tr><td>Teal edge</td><td>Thin teal mark left of the day = that day falls inside a break of 30+ consecutive hours free of all duty (FAR 117.25(b)), between duty periods, a long layover included. Hover the date for the break's start, end and 'covers reports until'. The 30h in 7d column gives the date that counts: &#10003; 36h MM/DD = the day the qualifying break ended (on a day still inside a break, usually that day's own date).</td></tr>
    <tr><td>Override / +15%</td><td>Add-ons inside Pay-Gross by crew size (PWA 4.O.1). IRO crew (3 pilots, 4.O.1.a): RO $${IRO_OVERRIDE.toFixed(2)}, FO $3.00, CA $5.00 per block hour. Extended Range crew (4 pilots, Definitions 25, 4.O.1.b): FO or RO $3.00 per block hour, CA $5.00; the 15% premium is only for the type-rated FO: tap Pay-Gross to mark a trip you flew in that seat. Recall (200% pay, 100% credit, 4.M.1.a): tap Pay-Gross to mark a recall trip. LODO (4.D.2.e): 4:00 pay, no credit, per day off lost to a late release.</td></tr>
    <tr><td>Res Grid</td><td>FLICA net reserves. <span class="g green">Green</span> = drop or swap off this day OK. <span class="g red">Red</span> = add only.</td></tr>
    <tr><td>30h in 7d</td><td>FAR 117.25(b): 30 consecutive hours free from all duty within the past 168 consecutive hours (7 days) before a report. A break of 30 h+ off all duty (teal edge on its days, a long layover counts) covers any report up to 138 h after it ends. &#10003; 36h MM/DD = a report at that day's first duty start (00:01 on a day off) is covered: the longest break off duty in the 168 h before it, in whole hours, and the date that break ended; a later report that day may not be (hover for the hours and 'covered until'); red 'need 30h off' = that report is not covered; ? = the window reaches before the schedule on file; &#8211; = mid-trip, no report that day. Training (SIM, OEB, ground school) and reserve days count as duty; a trip whose report and release are not on file yet (its times not read) counts as time off. Need 30 h off by (totals): the first report time after which you need 30 h off first.</td></tr>
    <tr><td>100h in 672h</td><td>FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours (28 days). This cell checks the 672 h ending 24:00 that day: what is left, in hours and minutes, of 100:00 less the block flown or scheduled in it, leg by leg (10:57 left = 89:03 flown or scheduled). Red '0:00 left' = at the limit; red '1:20 over' = past it by that much. ~ = part of the window is before the schedule on file, or holds a trip whose times are not read yet (it adds 0:00, or only its duties with a block; hover for which). A trip with a duty's block missing counts its whole trip Block, as a pickup's FAR check does: the rest of it on the duties without one. Hover for the block.</td></tr>
    <tr><td>Room to 100h</td><td>What is left, in hours and minutes (h:mm), under FAR 117.23(b)(1) (100 flight hours in any 672 consecutive hours): 100:00 minus the block flown or scheduled in the busiest 672 h (28-day) window that holds any part of that day, looking back and forward, so trips already on your line after that day count too (100h in 672h looks back only). It tries every window that starts at a duty's start or ends at its block-in, where the busiest one always is, counting a duty's block when the whole duty is in the window, as a pickup's FAR check does, and the windows ending 24:00 HST counted leg by leg as in 100h in 672h, so it never shows more room than 100h in 672h. 'left' = room under the limit; red '0:00 left' = none; red '1:20 over' = such a window is over 100:00 by that much. ~ = a window reaches past the schedule on file, or holds a trip whose times are not read yet (it adds 0:00, or only its duties with a block; hover for which). Block Avail (totals): 98:00 bid-month cap minus FLICA's bid-period Block.</td></tr>
    <tr><td>Legal next</td><td>Earliest report for another trip: release + 11 h (PWA 10.E.1.a). Tap for the 18 h case.</td></tr>
    <tr><td>Open</td><td>Open time trips starting that day: <span class="fit">fits</span>, <span class="clash">clashes or blocked</span>.</td></tr>
    <tr><td>Ideas</td><td>Tag-ons after your release with legal rest, <b>O</b> = in open time, <b>T</b> = on the Tradeboard. Orange = better trip for a marked one. Tap for details.</td></tr>
    <tr><td>Day</td><td>Blue = weekend, ${this._role() === "admin" ? "yellow = no school at HPA (from the school year file), hatched yellow = US or Hawaii holiday with no school file loaded" : "hatched yellow = US or Hawaii holiday"}. Tap a day to block it (&#8856;), tap again to unblock; VAC days are always &#8856; and cannot be changed. The lock switch at the top left (a lock, the word Lock, then On or Off) freezes ${admin ? "availability, trade and drop" : "availability and trade"} taps while it is On (the default); switch it Off to change them and On again to lock them. All times HNL.</td></tr>
    </table>${note ? `<div>${note}</div>` : ""}</details>
    <details class="set"${unconf.length || this._paySetOpen ? " open" : ""}><summary>Pay settings${unconf.length ? " (not set yet)" : ""}</summary>
      <span>Federal tax <select data-e="input_number.flight_watcher_federal_tax_pct"${flagged.includes(PAY_PREFS[0]) ? ' data-f="1"' : ""}>${sel(0, 45, 0.5, fed, "%")}</select></span>
      <span>State tax <select data-e="input_number.flight_watcher_state_tax_pct"${flagged.includes(PAY_PREFS[1]) ? ' data-f="1"' : ""}>${sel(0, 15, 0.25, stt, "%")}</select></span>
      <span>Longevity year <select data-e="input_number.flight_watcher_longevity_year"${flagged.includes(PAY_PREFS[2]) ? ' data-f="1"' : ""}>${noYear ? `<option value="" selected disabled>set</option>` : ""}${sel(1, 12, 1, lyr, "")}</select></span>
      ${admin ? "" : this._payPickHtml()}
      ${flagged.length ? `<div class="r unc">These came from settings that were never set. Pick your own, or <button type="button" class="keep">Keep these</button></div>` : ""}
      <div class="r">${noYear ? "Rate: set your longevity year here (A330 PAX FO, PWA 3.D.6; the table caps at 12). No pay is figured until it is set." : `Rate $${RATE.toFixed(2)}/credit h: A330 PAX FO, PWA 3.D.6, year ${lyr} ${doh ? `(DOH ${doh} = year ${dohYear(today, doh)}, table caps at 12)` : "(set your longevity year here; table caps at 12)"}, effective ${RATE_DATES.filter((x) => x <= today).pop()}. Net = gross less federal and state only${!admin && this._payDed() ? "; the paycheck estimates also take out your deductions" : ""}; estimate.`}</div>
    </details>${chtml}</ha-card>`;
    this._wire();
    // 1.7.7: the pairing detail after the redraw: the sheet (narrow) shown, updated or hidden; the wide panel scrolled into
    // view once a pairing; the focus back on the pairing that had it
    this._pdNarrow = narrow;
    if (pdM && narrow) this._sheet.show(pdM.k, JSON.stringify(pdM), fwgSheetHtml(pdM)); else this._sheet.hide();
    if (pdM && !narrow && this._pd && !this._pd.shown) {
      this._pd.shown = true;
      const pn = main.querySelector(".fwgp");
      const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (pn && pn.scrollIntoView) pn.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
    }
    if (fk && !this._sheet.open) { const t = this._tripEl(fk); if (t) t.focus({ preventScroll: true }); }
    if (lf) { const l = main.querySelector(".lock"); if (l) l.focus({ preventScroll: true }); }
  }
  // 1.7.7: the pairing detail: open, swap to another pairing, or close (the same one again)
  _pdToggle(k) {
    const key = this._key().key;
    if (this._pd && this._pd.k === k && this._pd.key === key) { this._pdClose(true); return; }
    this._pd = { key, k, shown: false };
    this._render();
  }
  _pdClose(refocus) {
    if (!this._pd) return;
    const k = this._pd.k;
    this._pd = null;
    this._render();
    if (refocus) { const t = this._tripEl(k); if (t) t.focus({ preventScroll: true }); }
  }
  _tripEl(k) { return [...this.shadowRoot.querySelectorAll(".fwm .trip[data-k]")].find((x) => x.dataset.k === k) || null; }
  _hc() { return this.shadowRoot ? this.shadowRoot.querySelector(".fwm ha-card") : null; }
  // Esc closes the pairing detail, Tab stays inside the sheet; a rotation or resize past the phone width redraws it
  connectedCallback() {
    if (this._h && !this._ageT) this._ageT = setInterval(() => this._ageTick(), 1000);  // 1.7.12: back on the page
    if (!this._kd) {
      this._kd = (e) => { if (!this._pd) return; if (e.key === "Escape") { this._pdClose(true); return; } if (this._sheet) this._sheet.trap(e); };
      this._rz = () => { if (this._pd && this._h && fwgNarrow(this._hc()) !== this._pdNarrow) this._render(); };
    }
    document.addEventListener("keydown", this._kd);
    window.addEventListener("resize", this._rz);
  }
  disconnectedCallback() {
    clearInterval(this._ageT); this._ageT = null;  // 1.7.12: no tick off the page
    if (!this._kd) return;
    document.removeEventListener("keydown", this._kd);
    window.removeEventListener("resize", this._rz);
  }
  // one line per day: the first item, then "+N" that opens the rest in the info box
  _one(items, what) {
    if (!items.length) return "";
    if (items.length === 1) return items[0];
    const rest = items.slice(1).map((h) => h.replace(/<[^>]+>/g, "")).join("\n");
    return `${items[0]} <span class="tag more" title="${this._esc(`${items.length - 1} more ${what}${items.length > 2 ? "s" : ""}:\n${rest}`)}">+${items.length - 1}</span>`;
  }
  _wire() {
    this.shadowRoot.querySelectorAll(".set select[data-e]").forEach((inp) => {
      inp.addEventListener("change", () => { this._h.callService("input_number", "set_value", { entity_id: inp.dataset.e, value: parseFloat(inp.value) }); });
    });
    const keep = this.shadowRoot.querySelector(".set .keep");  // 1.6.2: confirm the flagged values as they are
    if (keep) keep.addEventListener("click", () => {
      // 1.6.4: only the values listed as flagged (data-f): a longevity year the DOH now gives is not kept as a fixed year
      this.shadowRoot.querySelectorAll(".set select[data-f]").forEach((inp) => {
        const st = this._h.states[inp.dataset.e];
        if (st && st.attributes && st.attributes.unconfirmed === true) this._h.callService("input_number", "set_value", { entity_id: inp.dataset.e, value: parseFloat(inp.value) });
      });
      keep.disabled = true;
      keep.textContent = "Kept";
    });    this._payWire();
  }
  // FW-0072 (Ryan, Nov 19): a pilot's state picker (2026 rates) and his pay stub, read once on this device. What this
  // device keeps (localStorage, per pilot): the state and filing picked, the deductions percent and where the rates
  // came from; the federal and state rates go to his own Pay settings helpers. Never the stub or anything read off it.
  _ls(k) { try { return localStorage.getItem("flight_watcher_" + k); } catch (e) { return null; } }
  _lsSet(k, v) { try { if (v === null) localStorage.removeItem("flight_watcher_" + k); else localStorage.setItem("flight_watcher_" + k, v); } catch (e) { /* ignore */ } }
  _payDed() { const v = parseFloat(this._ls("pay_ded")); return v > 0 && v < 60 ? v : 0; }
  _payPickHtml() {
    const st = this._ls("pay_state") || "", fs = this._ls("pay_filing") === "married" ? "married" : "single", src = this._ls("pay_src");
    const opts = Object.keys(FWP_STATES).sort((a, b) => FWP_STATES[a][0].localeCompare(FWP_STATES[b][0]))
      .map((c) => `<option value="${c}"${c === st ? " selected" : ""}>${FWP_STATES[c][0]}</option>`).join("");
    const pct = (v) => `${+v.toFixed(2)}%`;
    let line = "";
    const r = st ? fwpStateTax(st, fs, (this._payGrossMo || 0) * 12) : null;
    if (r) {
      line = r.type === "n" ? `${r.name}: no state income tax on wages.` : r.type === "f" && r.low === r.top
        ? `${r.name}: flat ${pct(r.top)}${r.pct != null ? `, about ${pct(r.pct)} of your pay after its deduction and exemption` : ""}.`
        : `${r.name}: ${pct(r.low)} to ${pct(r.top)} in brackets${r.pct != null ? `; about ${pct(r.pct)} of your pay (${this._payGrossWhy || "a year's pay"}, ${fs}, the state's standard deduction and exemption; credits not counted)` : "; the top rate is used until your longevity year is set"}.`;
      line += src === "stub" ? " State tax is set from your pay stub for now (Clear stub rates to use this rate)." : ` State tax is set to the nearest 0.25%.`;
    }
    const ded = this._payDed();
    const stubNote = src === "stub" ? `<div class="r">Federal and state tax set from your pay stub (federal includes Social Security and Medicare)${ded ? `; ${pct(ded)} deductions come out of the paycheck estimates` : ""}. <button type="button" class="fwpclr">Clear stub rates</button></div>` : "";
    return `<span>State <select class="fwst" aria-label="State you pay income tax in"><option value=""${st ? "" : " selected"}>pick</option>${opts}</select></span>
      <span>Filing <select class="fwfs" aria-label="Filing status"><option value="single"${fs === "single" ? " selected" : ""}>single</option><option value="married"${fs === "married" ? " selected" : ""}>married</option></select></span>
      ${line ? `<div class="r">${this._esc(line)}</div>` : ""}<div class="r">State rates: ${this._esc(FWP_SRC)}.</div>
      <div class="r">Or set them from your pay stub: <input type="file" class="fwstub" accept="application/pdf,.pdf" aria-label="Pay stub PDF"></div>
      <div class="r">Your pay stub is read once on this device to set your tax rates, then discarded. Only the resulting rates are saved to your settings: federal, state and deductions, as percentages.</div>
      ${this._stubMsg ? `<div class="r">${this._esc(this._stubMsg)}</div>` : ""}${stubNote}`;
  }
  _payWire() {
    const sr = this.shadowRoot, fst = sr.querySelector(".set .fwst"), ffs = sr.querySelector(".set .fwfs"), stub = sr.querySelector(".set .fwstub");
    const det = sr.querySelector("details.set");
    if (det) det.addEventListener("toggle", () => { this._paySetOpen = det.open; });
    // the two rate helpers only (named here so the portal's manifest check sees them): pref/set on the portal
    const setFed = (v) => this._h.callService("input_number", "set_value", { entity_id: "input_number.flight_watcher_federal_tax_pct", value: v });
    const setStt = (v) => this._h.callService("input_number", "set_value", { entity_id: "input_number.flight_watcher_state_tax_pct", value: v });
    const applyState = (msg) => {
      this._paySetOpen = true; this._stubMsg = typeof msg === "string" ? msg : "";
      this._lsSet("pay_state", fst.value || null); this._lsSet("pay_filing", ffs.value);
      const r = fst.value ? fwpStateTax(fst.value, ffs.value, (this._payGrossMo || 0) * 12) : null;
      if (r) { setStt(fwpStep(r.pct != null ? r.pct : r.top, 0.25, 0, 15)); this._lsSet("pay_src", "table"); }
      this._render();
    };
    if (fst) fst.addEventListener("change", () => applyState());
    if (ffs) ffs.addEventListener("change", () => { if (fst && fst.value && this._ls("pay_src") !== "stub") applyState(); else { this._lsSet("pay_filing", ffs.value); this._paySetOpen = true; this._render(); } });
    if (stub) stub.addEventListener("change", async () => {
      const f = stub.files && stub.files[0];
      if (!f) return;
      stub.disabled = true; this._paySetOpen = true;
      let r = null, why = "";
      try { r = await fwpReadStub(f); } catch (e) { why = e instanceof FwpError ? e.message : "it could not be read"; }
      stub.value = "";
      if (!r) { this._stubMsg = `That file was not used (${why}). Nothing was saved.`; this._render(); return; }
      const fv = fwpStep(r.federal, 0.5, 0, 45), sv = fwpStep(r.state, 0.25, 0, 15);
      setFed(fv); setStt(sv);
      this._lsSet("pay_ded", String(r.deductions)); this._lsSet("pay_src", "stub");
      this._stubMsg = `Read and discarded. This year so far: federal ${r.federal}% (income tax, Social Security and Medicare), set as ${fv}%; state ${r.state}%, set as ${sv}%; deductions ${r.deductions}%.`;
      this._render();
    });
    const clr = sr.querySelector(".set .fwpclr");
    if (clr) clr.addEventListener("click", () => {
      this._lsSet("pay_ded", null); this._lsSet("pay_src", null); this._paySetOpen = true;
      this._stubMsg = fst && fst.value ? "Stub rates cleared; state tax is from the state table again. Set federal above." : "Stub rates cleared; pick your rates above.";
      if (fst && fst.value) applyState(this._stubMsg); else this._render();
    });
  }
  getCardSize() { return 12; }
}
customElements.define("flight-watcher-schedule-card", FlightWatcherScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-schedule-card", name: "Flight Watcher schedule", description: "Compact month schedule like FLICA" });

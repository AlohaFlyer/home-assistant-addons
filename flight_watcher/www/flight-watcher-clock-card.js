// Flight Watcher status line (v3, Nov 3 2026, Ryan): state + last/next check, live per second, with the
// controls inline: Check now, Hunt (with its interval), Pause, Normal interval, Re-arm when parked.
// Replaces the status alert card, the clock card and the Controls section. Pako HI, HOM t1218.
// Usage: type: custom:flight-watcher-clock-card (no options needed).
// 1.6.2 (Release A items 14 and 15): Last and Next are HST (Pacific/Honolulu, labeled), whatever zone the phone is in;
// buttons and selects are at least 44 px tall on a phone; the interval selects offer only what the number entities
// allow (their min and max attributes: hunt 5 to 90 s and normal 1 to 90 min on every instance since Ryan's ranges of
// 2026-11-10, roles.WATCHER_FREQ_LIMITS) and, in the pilot portal (FW_PORTAL, turned on only in the portal's copy:
// portal.portal_card), only what the portal contract passes (hunt 5 to 90 s, normal 1 to 90 min: contract 1
// revision 2's freq_limits, 1.7.0; normal stopped at 20 min before): with nothing left the interval shows as text. No
// Home Assistant steps in the portal.
// 1.6.2 review: the state note (a FLICA budget wait, a stopped read path) shows while idle or hunting, and a budget
// wait reads "Waiting for the FLICA budget until HH:MM HST", never "Stuck. Press Re-arm". A pilot's hunt faster than his
// budget (100 FLICA loads an hour) says so plainly: "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait
// for the budget, at least 89 s apart" (the Watcher's held_note; the Watcher spreads it over the hour), with the next
// check's time while it waits.
// 1.7.1 (F#4): an interval the pilot picks stays shown until the Watcher's state shows it (or 20 s pass, or the portal
// settles the command another way: refused or no answer), instead of jumping back to the old value on the next 1 s
// tick; the focus guard looks in the card's own shadow root (document.activeElement is the card itself). In the portal
// (hass.fwPending: commands in flight, keyed by entity) Check now, Hunt, Pause and Re-arm read "Sending..." and take no
// second tap while theirs is in flight, and an interval select waits for its command too.
// 1.7.1 (F#119): the red status text is this card's own variable, as before on a light card and a lighter red on a
// dark one (Home Assistant's dark mode, the portal's from the device), so it keeps WCAG AA contrast (4.5:1) on both; the Hunt
// button's orange is darker so its white label reads too (3.1:1 before); the | separators are decoration only.
// 1.7.1 review: on a phone the interval selects are 16 px: iOS Safari zooms into a smaller one when it is tapped and
// leaves the page wider than the screen (as F#43 found for the pilot lookup).
// Review r4: in the red state ("Stuck. Press Re-arm.") the Last, Next and interval labels are the primary text color
// (the secondary one was 4.07:1 and 3.89:1 on the red tint with Home Assistant's own light theme), and Check now is the
// primary text color in bold (Home Assistant's default blue #009ac7 was 3.26:1 on a white card).
// 1.7.9 (F#92): the Re-arm confirm names the state the Watcher is in and what Re-arm does there, as the Watcher's own
// rearm_answer does: stuck (idle or hunting with no check): a full check now, no new FLICA login; stepped aside for
// the pilot's own FLICA login: a login when the step-aside ends, not before; reconnecting: a login at the next login
// try; stopped: one FLICA login, with the stop's note. The button's tooltip says the same.
// 1.7.12 (Ryan, Nov 17): "Last" and its "(N ago)" give way to one "Data age 12 min" stamp (the shared data age block
// below): amber with "stale" past 1x the check interval (normal, or hunt while hunting), red with "very stale" past 2x,
// "Data age unknown" with no colour when the last check time is not known; its hover text has the last good read in
// HST. It ticks with the card's 1 s redraw. With mode: age (the Details view, in place of the "Last check" tile) the
// card is that stamp alone, no controls.
// 1.7.12 review: the thresholds are 1x and 2x of the Watcher's own longest cycle (the shared block says how; pending
// Ryan's yes on that meaning of "1x"), and "Watcher offline" in red when the app is down. A tap (or Enter) on the stamp
// shows its hover text in a box (phones have no hover): the last good read in HST, with its day when that is not
// today, and the thresholds. On a phone the stamp starts its own line and Next the one after it, and the stamp (and
// Next) keep one width and the stamp one weight at every level, so the card and its buttons never move as time ticks. mode: age is a tile
// (56 px, one grid row, "Data age" over its value, never wrapped), and a mode change on the same card builds it again.
// 1.8.1 (Ryan, Nov 23: "I'm working on Dec now"): a Pot select beside the intervals (select.flight_watcher_pot_month:
// This month, Next month, Both; the same look and 44 px phone target as the interval selects) and, beside it, the
// month(s) each check reads with their BCIDs ("December 2026 (003.153)"), then a month of the select not read yet with
// why ("January 2027 not open yet"), from the state's pot_months. In the pilot portal the select is no command (no
// portal sub, roles.NOT_ON_PORTAL): the card shows the mode and the months as text, read only.
const FW_PORTAL = false;
const FC_POT = ["This month", "Next month", "Both"];  // the Watcher's POT_MODES
// 1.8.1: the months of the state's pot_months: each read every check with its BCID, then the others with their status
function fcPotText(list) {
  const ok = (r) => r && typeof r.month === "string";
  const read = list.filter((r) => ok(r) && r.read).map((r) => `${r.name || r.month} (${r.bcid || "?"})`);
  const rest = list.filter((r) => ok(r) && !r.read)
    .map((r) => `${r.name || r.month} ${r.how === "not found yet" ? "not found yet" : r.status || "not read yet"}`);
  return [...read, ...rest].join(" \u00b7 ");
}
const FW_AGE_IDS = { last: "sensor.flight_watcher_last_check", state: "sensor.flight_watcher_state",
  next: "sensor.flight_watcher_next_check", hunt: "switch.flight_watcher_hunt_mode",
  normal: "number.flight_watcher_normal_check_every", huntEvery: "number.flight_watcher_hunt_check_every",
  chk: "button.flight_watcher_check_now", pause: "switch.flight_watcher_pause" };  // 1.7.26: the box's Check now
const FC_HUNT = [5, 10, 15, 20, 30, 45, 60, 90];  // seconds (number.flight_watcher_hunt_check_every 5-90)
const FC_NORM = [1, 2, 3, 5, 6, 10, 15, 20, 30, 45, 60, 90];  // minutes (number.flight_watcher_normal_check_every 1-90)
const FC_PORTAL_MAX = { hunt: 90, normal: 90 };  // portal contract 1 revision 2 freq_limits (hunt_s 5-90, normal_min 1-90)
const FC_DEFAULT = { hunt: [5, 90], normal: [1, 90] };  // an entity with no min / max attributes: roles.WATCHER_FREQ_LIMITS
const FC_WANT_MS = 20000;  // 1.7.1 (F#4): how long a picked interval waits for the state to show it
const FC_HELD = /^(Hunting every \d+ s|Checking every \d+ min) is held to \d+ FLICA loads an hour/;  // the Watcher's held_note
const FC_TIME = new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Honolulu", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
// 1.7.12 review: the box a tap on the data age stamp opens (its hover text), as the schedule card's for its titles.
// 1.7.26: div.info, the box only: a bare .info also hid the card itself (ha-card class "info": Waiting., Slowed.)
const FC_INFO_CSS = `div.info{display:none;position:fixed;left:8px;right:8px;bottom:14px;z-index:9;margin:0 auto;max-width:460px;font-size:12px;line-height:1.4;font-weight:400;padding:8px 10px;border-radius:8px;background:var(--secondary-background-color,#e5e5e5);color:var(--primary-text-color);box-shadow:0 4px 18px rgba(0,0,0,.35);cursor:pointer;white-space:normal;text-align:left}
        div.info::after{content:"tap to close";display:block;margin-top:6px;font-size:10px;color:var(--secondary-text-color);text-align:right}
        .ag{cursor:pointer;border-radius:4px}.ag:focus-visible{outline:2px solid var(--primary-color,#03a9f4);outline-offset:2px}`;
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
class FlightWatcherClockCard extends HTMLElement {
  setConfig(c) {
    this.c = c || {};
    // 1.7.12 review: a mode change on the same element (Home Assistant's card editor) builds the card again
    if (this._root && this._built !== (this._ageOnly() ? "age" : "full")) {
      clearInterval(this._tick); this._tick = null;
      this._root.innerHTML = ""; this._root = null;
      if (this._h) this.hass = this._h;
    }
  }
  set hass(h) {
    // review r4: the dark colors follow Home Assistant's own dark mode (hass.themes.darkMode, which the portal sets from the device), not the phone's: a profile forced to Light on a phone in dark mode kept the light-on-dark reds
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(h && h.themes && typeof h.themes.darkMode === "boolean" ? h.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
    this._h = h;
    if (!this._root && this._ageOnly()) {  // 1.7.12: the stamp alone (mode: age), ticking each second
      // review: a tile, 56 px like the tiles beside it, "Data age" over its value, never wrapped (an ellipsis)
      this._root = this.shadowRoot || this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        :host([dark]){--fw-err:#ef9a9a;--fw-warn:#ffb74d}
        ha-card{box-sizing:border-box;height:56px;padding:0 12px;display:flex;flex-direction:column;justify-content:center;overflow:hidden}
        .ag{display:block;min-width:0}
        .lb,.v{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .lb{font-size:14px;line-height:20px;font-weight:500;color:var(--primary-text-color)}
        .v{font-size:12px;line-height:16px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--secondary-text-color)}
        .ag[data-age="amber"] .v{color:var(--fw-warn,#8a5300)}.ag[data-age="red"] .v{color:var(--fw-err,#c62828)}
        ${FC_INFO_CSS}
        ${FW_AGE_BOX_CSS}
      </style><ha-card><span class="ag" id="age" data-age="" role="button" tabindex="0" aria-expanded="false"><span class="lb">Data age </span><span class="v" id="agv">unknown</span></span></ha-card><div class="info" id="agi"></div>`;
      this._built = "age"; this._ageOpen = false;
      this._ageWire();
      this._tick = setInterval(() => this._render(), 1000);
    }
    if (!this._root) {
      this._root = this.shadowRoot || this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        :host([dark]){--fw-err:#ef9a9a;--fw-warn:#ffb74d}
        ha-card{padding:5px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;line-height:1.3;border-left:5px solid var(--divider-color)}
        ha-card.ok{border-left-color:#2e7d32}ha-card.warn{border-left-color:#f9a825}ha-card.err{border-left-color:#c62828;background:rgba(198,40,40,.08)}ha-card.info{border-left-color:#1565c0}ha-card.err .k,ha-card.err .iv{color:var(--primary-text-color)}
        .st{font-weight:700}.m{color:var(--primary-text-color)}
        .k{color:var(--secondary-text-color)}.t{font-weight:600;font-variant-numeric:tabular-nums}
        .sep{color:var(--divider-color)}
        .ag{font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap;min-width:14em}.nx{min-width:17em}
        .ag[data-age="amber"]{color:var(--fw-warn,#8a5300)}.ag[data-age="red"]{color:var(--fw-err,#c62828)}
        ${FC_INFO_CSS}
        .ctl{margin-left:auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
        button{font:inherit;font-size:12px;padding:3px 9px;border-radius:14px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}
        button:hover{background:rgba(0,0,0,.05)}
        button:disabled{cursor:default;opacity:1;border-style:dashed}
        button.on{background:#b84d00;border-color:#b84d00;color:#fff}
        button.pz.on{background:#f9a825;border-color:#f9a825;color:#111}
        button.rearm{background:#2e7d32;border-color:#2e7d32;color:#fff}
        button.chk{color:var(--primary-text-color);font-weight:600}
        select{font:inherit;font-size:12px;padding:2px 2px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
        .iv{display:inline-flex;align-items:center;gap:3px;font-size:12px;color:var(--secondary-text-color)}
        .ivt{font-weight:600;color:var(--primary-text-color)}
        .pmm{font-size:12px;font-weight:600;color:var(--primary-text-color);overflow-wrap:anywhere;min-width:0}
        @media (max-width:700px){ha-card{font-size:12px;gap:6px}.ctl{margin-left:0;width:100%}.ag{flex-basis:100%}.s1,.s2{display:none}
          button{min-height:44px;min-width:44px;padding:6px 12px;font-size:13px}select{min-height:44px;min-width:56px;font-size:16px}}
        ${FW_AGE_BOX_CSS}
      </style><ha-card><span class="st" id="st"></span><span class="m" id="msg"></span>
      <span class="sep s1" aria-hidden="true">|</span><span class="ag" id="age" data-age="" role="button" tabindex="0" aria-expanded="false">Data age unknown</span>
      <span class="sep s2" aria-hidden="true">|</span><span class="nx"><span class="k">Next</span> <span class="t" id="nt">-</span> <span class="k" id="na"></span></span>
      <span class="ctl">
        <button class="chk" id="chk" title="Read the pot right away">&#8635; Check now</button>
        <button id="hunt" title="Hunt: check at hunt speed; off = normal speed">&#127939; Hunt</button>
        <span class="iv" title="Hunt interval (each wait varies by 30 %)">every <select id="hs"></select><b class="ivt" id="hst"></b> s</span>
        <span class="iv" title="Normal interval when Hunt is off (each wait varies by 30 %)">normal <select id="ns"></select><b class="ivt" id="nst"></b> min</span>
        <span class="iv" title="Which bid month's open time pot each check reads">Pot
          <select id="pm" aria-label="Pot month"></select><b class="ivt" id="pmt"></b></span>
        <span class="pmm" id="pmm" aria-live="polite"></span>
        <button class="pz" id="pz" title="Pause only if you will be in FLICA 30+ min; for a quick look just log in, the Watcher steps aside for 30 min">&#10074;&#10074; Pause</button>
        <button class="rearm" id="rearm" title="Logs into FLICA once and resumes" style="display:none">&#8634; Re-arm</button>
      </span></ha-card><div class="info" id="agi"></div>`;
      this._built = "full"; this._ageOpen = false;
      this._ageWire();
      const $ = (i) => this._root.getElementById(i);
      $("chk").addEventListener("click", () => this._h.callService("button", "press", { entity_id: "button.flight_watcher_check_now" }));
      $("hunt").addEventListener("click", () => this._h.callService("switch", "toggle", { entity_id: "switch.flight_watcher_hunt_mode" }));
      $("pz").addEventListener("click", () => this._h.callService("switch", "toggle", { entity_id: "switch.flight_watcher_pause" }));
      $("rearm").addEventListener("click", () => { if (confirm(`${this._rearmSays || "Re-arm logs into FLICA once."}\n\nRe-arm the Watcher now?`)) this._h.callService("button", "press", { entity_id: "button.flight_watcher_re_arm" }); });
      $("hs").addEventListener("change", (e) => { const v = this._wish("number.flight_watcher_hunt_check_every", e.target.value); this._h.callService("number", "set_value", { entity_id: "number.flight_watcher_hunt_check_every", value: v }); });
      $("ns").addEventListener("change", (e) => { const v = this._wish("number.flight_watcher_normal_check_every", e.target.value); this._h.callService("number", "set_value", { entity_id: "number.flight_watcher_normal_check_every", value: v }); });
      if (!FW_PORTAL) $("pm").addEventListener("change", (e) => {  // 1.8.1: never in the portal (no such command)
        const option = e.target.value;
        this._pmWant = { v: option, at: Date.now() };
        this._h.callService("select", "select_option", { entity_id: "select.flight_watcher_pot_month", option });
      });
      this._tick = setInterval(() => this._render(), 1000);
    }
    this._render();
  }
  // 1.8.1 (D4): the Pot select (Home Assistant only) and the months each check reads (the state's pot_months). A pick
  // stays shown until the select's state shows it or FC_WANT_MS pass; in the portal the mode is text
  _pot($) {
    const ent = this._h.states["select.flight_watcher_pot_month"], sel = $("pm"), live = !FW_PORTAL && !!ent;
    const mode = ent && FC_POT.includes(ent.state) ? ent.state : this._attr("sensor.flight_watcher_state", "pot_mode");
    if (sel.dataset.opts !== "1") {
      sel.innerHTML = FC_POT.map((o) => `<option value="${o}">${o}</option>`).join("");
      sel.dataset.opts = "1";
    }
    if (sel.style.display !== (live ? "" : "none")) sel.style.display = live ? "" : "none";
    const txt = live ? "" : (FC_POT.includes(mode) ? mode : "?");
    if ($("pmt").textContent !== txt) $("pmt").textContent = txt;
    const w = this._pmWant;
    if (w && (w.v === mode || Date.now() - w.at > FC_WANT_MS)) this._pmWant = null;
    const shown = this._pmWant ? this._pmWant.v : mode;
    if (live && FC_POT.includes(shown) && this._root.activeElement !== sel && sel.value !== shown) sel.value = shown;
    const pm = this._attr("sensor.flight_watcher_state", "pot_months");
    const months = fcPotText(Array.isArray(pm) ? pm : []);
    if ($("pmm").textContent !== months) $("pmm").textContent = months;
  }
  disconnectedCallback() { clearInterval(this._tick); this._root = null; }
  _ageOnly() { return !!(this.c && this.c.mode === "age"); }
  // 1.7.12 review: mode: age is one row of a sections view (56 px, as the tiles beside it), half width unless set
  getGridOptions() { return this._ageOnly() ? { columns: 6, rows: 1, min_rows: 1 } : {}; }
  // 1.7.12: the data age stamp, from this card's own entities (the shared block's fwAgeFrom)
  _stamp() {
    const el = this._root.getElementById("age"), v = this._root.getElementById("agv");
    const a = fwAgeFrom(this._h && this._h.states, FW_AGE_IDS, Date.now()), title = `${a.read} ${a.rule}`;
    if (v) { const val = a.text.replace(/^Data age /, ""); if (v.textContent !== val) v.textContent = val; }  // mode: age
    else if (el.textContent !== a.text) el.textContent = a.text;
    if (el.dataset.age !== a.level) el.dataset.age = a.level;
    if (el.title !== title) el.title = title;
    if (this._ageOpen) this._ageBox();
  }
  // 1.7.12 review: a tap, Enter or Space on the stamp opens its hover text in a box (no hover on a phone): the last
  // good read in HST and the thresholds; a tap on the box, another on the stamp or Esc closes it. 1.7.26: the box also
  // says why reads are held and has its own Check now (the shared block's fwAgeBox); a tap on that row keeps it open.
  // 1.7.26 review: opened from the keyboard the box takes the focus (its Check now is the next Tab, not the last of the
  // card's controls); Esc in it, or Enter or Space on it, closes it and gives the stamp the focus back
  _ageWire() {
    const el = this._root.getElementById("age"), box = this._root.getElementById("agi");
    const flip = (on) => { this._ageOpen = on; this._ageBox(); };
    el.addEventListener("click", () => flip(!this._ageOpen));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        flip(!this._ageOpen);
        if (this._ageOpen) box.focus();
      } else if (e.key === "Escape") flip(false);
    });
    box.addEventListener("click", () => flip(false));
    this._fwa = this._fwa || {};
    this._ageOn = { press: () => { fwAgePress(this._h, FW_AGE_IDS, this._fwa, Date.now()); this._ageBox(); },
      close: () => { flip(false); el.focus(); } };
  }
  _ageBox() {
    const el = this._root.getElementById("age"), box = this._root.getElementById("agi"), on = !!this._ageOpen;
    if (on) fwAgeBox(box, el.title, fwAgeChk(this._h, FW_AGE_IDS, this._fwa, Date.now()), this._ageOn);
    else if (box.firstChild) box.textContent = "";  // closed: nothing (no button) is left in it
    if (box.style.display !== (on ? "block" : "")) box.style.display = on ? "block" : "";
    if (el.getAttribute("aria-expanded") !== String(on)) el.setAttribute("aria-expanded", String(on));
  }
  _st(id) { const s = this._h && this._h.states[id]; return s ? s.state : "unavailable"; }
  _attr(id, a) { const s = this._h && this._h.states[id]; return s && s.attributes ? s.attributes[a] : undefined; }
  _time(d) { return FC_TIME.format(d); }  // 1.6.2: HST on any phone (the rows below and FLICA are HST)
  // the options an interval select may offer: within the entity's own min / max and, in the portal, the contract's max
  _opts(list, id, kind) {
    const dflt = FC_DEFAULT[kind], a = parseFloat(this._attr(id, "min")), b = parseFloat(this._attr(id, "max"));
    const lo = isNaN(a) ? dflt[0] : a, hi = isNaN(b) ? dflt[1] : b;
    return list.filter((v) => v >= lo && v <= hi && (!FW_PORTAL || v <= FC_PORTAL_MAX[kind]));
  }
  _menu(el, txt, opts, v, id) {
    const key = opts.join(",");
    if (el.dataset.opts !== key) { el.innerHTML = opts.map((o) => `<option value="${o}">${o}</option>`).join(""); el.dataset.opts = key; }
    el.style.display = opts.length ? "" : "none";
    txt.textContent = opts.length ? "" : (isNaN(v) ? "?" : String(Math.round(v)));
    const busy = this._pending(id);
    if (el.disabled !== busy) el.disabled = busy;
    if (opts.length) this._sel(el, this._shown(id, v, busy));
  }
  // 1.7.1 (F#4): the interval just picked, kept until the state shows it
  _wish(id, raw) {
    const v = parseFloat(raw);
    (this._want = this._want || {})[id] = { v, at: Date.now(), seen: false };
    return v;
  }
  _pending(id) { const p = this._h && this._h.fwPending; return !!(p && Object.prototype.hasOwnProperty.call(p, id)); }
  // what an interval select shows: the value picked, until the state matches it, FC_WANT_MS pass, or the portal settles
  // the command without it (its pending mark was there and is gone: refused, or no answer)
  _shown(id, v, busy) {
    const w = (this._want || {})[id];
    if (!w) return v;
    if (busy) w.seen = true;
    if ((!isNaN(v) && Math.round(v) === Math.round(w.v)) || Date.now() - w.at > FC_WANT_MS || (w.seen && !busy)) {
      delete this._want[id];
      return v;
    }
    return w.v;
  }
  _dur(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + " h " : "") + (h || m ? m + " min " : "") + s + " s";
  }
  _sel(el, v) {
    // 1.7.1 (F#4): the select is in this card's shadow root, where document.activeElement never is (it is the card)
    if (isNaN(v) || (this._root && this._root.activeElement === el)) return;
    const want = String(Math.round(v));
    if (![...el.options].some((o) => o.value === want)) {  // 1.6.2: an off-list value goes in its sorted place
      const o = document.createElement("option"); o.value = want; o.textContent = want;
      const after = [...el.options].find((x) => Number(x.value) > Number(want));
      el.insertBefore(o, after || null);
    }
    if (el.value !== want) el.value = want;
  }
  _render() {
    if (!this._root || !this._h) return;
    this._stamp();
    if (this._built === "age") return;
    const $ = (i) => this._root.getElementById(i), now = Date.now();
    const card = this._root.querySelector("ha-card");
    const lc = Date.parse(this._st("sensor.flight_watcher_last_check"));
    const st = this._st("sensor.flight_watcher_state");
    const hunt = this._st("switch.flight_watcher_hunt_mode") === "on";
    const paused = this._st("switch.flight_watcher_pause") === "on";
    const nc = Date.parse(this._st("sensor.flight_watcher_next_check"));
    const note = this._attr("sensor.flight_watcher_state", "note") || "";
    const nmv = parseFloat(this._st("number.flight_watcher_normal_check_every"));
    const hs = parseFloat(this._st("number.flight_watcher_hunt_check_every"));
    const age = isNaN(lc) ? null : (now - lc) / 1000;
    const lim = hunt ? 600 : Math.max(1800, (isNaN(nmv) ? 20 : nmv) * 150);
    // 1.6.2 review: a wait for the FLICA budget (next_check ahead, the gate's note) is no stuck Watcher (Re-arm does
    // nothing for it); the gate's and the breakers' note shows in the idle and hunting lines
    const held = FC_HELD.test(note);
    const gateWait = (held || /^FLICA (budget|host limit)/.test(note)) && !isNaN(nc) && nc > now;
    const blind = age != null && age > lim && !["paused", "yielded"].includes(st) && !gateWait;
    let cls = "ok", label = "", msg = "";
    const cap = (t) => String(t || "").replace(/^[a-z]/, (c) => c.toUpperCase());
    const quiet = /^(logged in|starting|un-paused|new settings)/i.test(note);
    const extra = note && !quiet ? " " + cap(note).replace(/\.?$/, ".") : "";
    const hm = (t) => this._time(new Date(t)).slice(0, 5);
    if (["unavailable", "unknown"].includes(st)) { cls = "err"; label = FW_PORTAL ? "Watcher not answering." : "App not running."; msg = FW_PORTAL ? "It normally restarts itself; if this stays red, ask the Flight Watcher admin to restart it." : "It normally restarts itself; if this stays red, restart Flight Watcher in Settings > Apps."; }
    else if (st === "needs_settings") { cls = "err"; label = "Needs your FLICA login."; msg = "Enter your FLICA username and password on the Settings tab; the Watcher logs in by itself."; }
    else if (st === "paused" || paused) { cls = "warn"; label = "Paused."; msg = "Not watching FLICA. Turn Pause off when you have signed out of FLICA."; }
    else if (["idle", "hunting"].includes(st) && held && !blind) {  // 1.6.2: a hunt the budget holds, waiting or checking
      const rest = note.split("; ").slice(1).join("; ");
      cls = "info"; label = "Slowed.";
      msg = note.split("; ")[0].replace(/ \(next at [0-9:]+ HST\)$/, "") + (gateWait ? `. Next check ${hm(nc)} HST.` : ".")
        + (rest ? " " + cap(rest).replace(/\.?$/, ".") : "");
    }
    else if (["idle", "hunting"].includes(st) && gateWait) {
      cls = "info"; label = "Waiting.";
      const rest = note.split("; ").slice(1).join("; ");
      msg = `Waiting for the FLICA ${/^FLICA host/.test(note) ? "host limit" : "budget"} until ${hm(nc)} HST.` + (rest ? " " + cap(rest).replace(/\.?$/, ".") : "");
    }
    else if (["idle", "hunting"].includes(st) && blind) { cls = "err"; label = "Stuck."; msg = `No check for ${this._dur(age)}. Press Re-arm.`; }
    else if (st === "hunting") { cls = extra ? "info" : "ok"; label = "Hunting."; msg = `Checking about every ${isNaN(hs) ? "?" : Math.round(hs)} s.` + extra; }
    else if (st === "idle") { cls = extra ? "info" : "ok"; label = "Watching."; msg = `Checking about every ${isNaN(nmv) ? "?" : Math.round(nmv)} min.` + extra; }
    else if (st === "yielded") { cls = "info"; label = "Stepped aside."; msg = "Someone signed into FLICA with your account. " + cap(note); }
    else if (st === "backoff") { cls = "info"; label = "Reconnecting."; msg = cap(note); }
    else { cls = "err"; label = "Stopped, needs you."; msg = cap(note || st.replace(/_/g, " ")) + ". Fix that, then press Re-arm."; }
    card.className = cls; $("st").textContent = label; $("msg").textContent = msg;
    if (!["idle", "hunting"].includes(st)) { $("nt").textContent = "none"; $("na").textContent = ""; }
    else if (!isNaN(nc) && nc > now - 30000) { $("nt").textContent = this._time(new Date(nc)) + " HST"; $("na").textContent = nc > now ? "(in " + this._dur((nc - now) / 1000) + ")" : "(due now)"; }
    else if (!isNaN(lc)) {
      const mid = hunt ? hs : nmv * 60;
      const [lo, hi] = !isNaN(mid) ? [mid * 0.7, mid * 1.3] : (hunt ? [20, 60] : [120, 600]);
      const a = lc + lo * 1000, b = lc + hi * 1000;
      $("nt").textContent = this._time(new Date(a)) + " to " + this._time(new Date(b)) + " HST";
      $("na").textContent = now < a ? "(in " + this._dur((a - now) / 1000) + ")" : now < b ? "(any moment)" : "(overdue " + this._dur((now - b) / 1000) + ")";
    }
    // controls
    $("hunt").classList.toggle("on", hunt);
    $("pz").classList.toggle("on", paused);
    this._menu($("hs"), $("hst"), this._opts(FC_HUNT, "number.flight_watcher_hunt_check_every", "hunt"), hs, "number.flight_watcher_hunt_check_every");
    this._menu($("ns"), $("nst"), this._opts(FC_NORM, "number.flight_watcher_normal_check_every", "normal"), nmv, "number.flight_watcher_normal_check_every");
    this._pot($);  // 1.8.1
    // 1.7.5 review ("Pause wins"): no Re-arm while Pause is on (the Watcher refuses it then), as Check now
    const needRearm = (["stopped_unexpected", "stopped_login_failed", "yielded", "backoff"].includes(st) || blind) && !paused;
    $("rearm").style.display = needRearm ? "" : "none";
    // 1.7.9 (F#92): what the confirm and the tooltip say, by state
    const mins = Math.round((age || 0) / 60);
    const stopNote = String(note || st.replace(/_/g, " ")).replace(/\s+/g, " ").slice(0, 140).replace(/\.$/, "");
    this._rearmSays = ["idle", "hunting"].includes(st) && blind ? `The Watcher is stuck: no check for ${mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`}. Re-arm starts a full check now, with no new FLICA login.`
      : st === "yielded" ? "The Watcher stepped aside for your own FLICA login. Re-arm logs into FLICA once when the step-aside ends, not before."
      : st === "backoff" ? "The Watcher is reconnecting to FLICA. Re-arm logs in at its next login try."
      // 1.7.9 review: the same cases as the Watcher's rearm_answer. FLICA refused the saved details (the stop's note
      // says so): no login is made; no login saved yet; the app not answering; any other state that is not stopped
      : st.startsWith("stopped") && /\brefused\b/i.test(stopNote) ? `The Watcher is stopped: ${stopNote}. Re-arm makes no login with details FLICA refused: save new FLICA details on the Settings tab first.`
      : st === "stopped_login_failed" ? `The Watcher is stopped: the FLICA login failed (${stopNote}). Re-arm logs into FLICA once with the saved login.`
      : st.startsWith("stopped") ? `The Watcher is stopped (${stopNote}). Re-arm logs into FLICA once and resumes.`
      : st === "needs_settings" ? "The Watcher has no FLICA login yet. Re-arm does nothing: enter your FLICA login on the Settings tab."
      : ["unavailable", "unknown", ""].includes(st) ? "The Watcher app is not answering (its state is unavailable). Re-arm cannot reach it: check that the app is running."
      : `The Watcher is ${st.replace(/_/g, " ")}, not stopped${age != null ? `, with no check for ${mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`}` : ""}. Re-arm does nothing in this state: it acts when the Watcher is stopped or stuck.`;
    if ($("rearm").title !== this._rearmSays) $("rearm").title = this._rearmSays;
    $("chk").style.display = ["idle", "hunting"].includes(st) && !paused ? "" : "none";
    // 1.7.1 (F#4): a command in flight (the portal's hass.fwPending) reads "Sending..." and takes no second tap
    for (const [bid, id] of [["chk", "button.flight_watcher_check_now"], ["hunt", "switch.flight_watcher_hunt_mode"],
      ["pz", "switch.flight_watcher_pause"], ["rearm", "button.flight_watcher_re_arm"]]) {
      const b = $(bid), busy = this._pending(id);
      if (b.dataset.l === undefined) b.dataset.l = b.innerHTML;
      if (b.disabled !== busy) { b.disabled = busy; b.innerHTML = busy ? "Sending..." : b.dataset.l; b.setAttribute("aria-busy", String(busy)); }
    }
  }
  getCardSize() { return 1; }
}
customElements.define("flight-watcher-clock-card", FlightWatcherClockCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-clock-card", name: "Flight Watcher clock", description: "Flight Watcher status, data age, next check and controls in one line (mode: age, the data age alone)" });

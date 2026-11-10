// Flight Watcher status line (v3, Nov 3 2026, Ryan): state + last/next check, live per second, with the
// controls inline: Check now, Hunt (with its interval), Pause, Normal interval, Re-arm when parked.
// Replaces the status alert card, the clock card and the Controls section. Pako HI, HOM t1218.
// Usage: type: custom:flight-watcher-clock-card (no options needed).
// 1.6.2 (Release A items 14 and 15): Last and Next are HST (Pacific/Honolulu, labeled), whatever zone the phone is in;
// buttons and selects are at least 44 px tall on a phone; the interval selects offer only what the number entities
// allow (their min and max attributes: hunt 5 to 90 s and normal 1 to 90 min on every instance since Ryan's ranges of
// 2026-11-10, roles.WATCHER_FREQ_LIMITS) and, in the pilot portal (FW_PORTAL, turned on only in the portal's copy:
// portal.portal_card), only what the portal contract passes (hunt 5 to 90 s, normal 1 to 20 min: contract 1's
// freq_limits until Release C revises it; a portal pilot's number entity says 20 too): with nothing left the interval
// shows as text. No Home Assistant steps in the portal.
// 1.6.2 review: the state note (a FLICA budget wait, a stopped read path) shows while idle or hunting, and a budget
// wait reads "Waiting for the FLICA budget until HH:MM HST", never "Stuck. Press Re-arm". A pilot's hunt faster than his
// budget (100 FLICA loads an hour) says so plainly: "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait
// for the budget, at least 89 s apart" (the Watcher's held_note; the Watcher spreads it over the hour), with the next
// check's time while it waits.
const FW_PORTAL = false;
const FC_HUNT = [5, 10, 15, 20, 30, 45, 60, 90];  // seconds (number.flight_watcher_hunt_check_every 5-90)
const FC_NORM = [1, 2, 3, 5, 6, 10, 15, 20, 30, 45, 60, 90];  // minutes (number.flight_watcher_normal_check_every 1-90)
const FC_PORTAL_MAX = { hunt: 90, normal: 20 };  // portal contract 1 freq_limits (hunt_s 5-90, normal_min 1-20) until Release C
const FC_DEFAULT = { hunt: [5, 90], normal: [1, 90] };  // an entity with no min / max attributes: roles.WATCHER_FREQ_LIMITS
const FC_HELD = /^(Hunting every \d+ s|Checking every \d+ min) is held to \d+ FLICA loads an hour/;  // the Watcher's held_note
const FC_TIME = new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Honolulu", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
class FlightWatcherClockCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    if (!this._root) {
      this._root = this.shadowRoot || this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        ha-card{padding:5px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;line-height:1.3;border-left:5px solid var(--divider-color)}
        ha-card.ok{border-left-color:#2e7d32}ha-card.warn{border-left-color:#f9a825}ha-card.err{border-left-color:#c62828;background:rgba(198,40,40,.08)}ha-card.info{border-left-color:#1565c0}
        .st{font-weight:700}.m{color:var(--primary-text-color)}
        .k{color:var(--secondary-text-color)}.t{font-weight:600;font-variant-numeric:tabular-nums}
        .sep{color:var(--divider-color)}
        .blind{color:#c62828;font-weight:700}
        .ctl{margin-left:auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
        button{font:inherit;font-size:12px;padding:3px 9px;border-radius:14px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}
        button:hover{background:rgba(0,0,0,.05)}
        button.on{background:#ef6c00;border-color:#ef6c00;color:#fff}
        button.pz.on{background:#f9a825;border-color:#f9a825;color:#111}
        button.rearm{background:#2e7d32;border-color:#2e7d32;color:#fff}
        button.chk{color:var(--primary-color)}
        select{font:inherit;font-size:12px;padding:2px 2px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
        .iv{display:inline-flex;align-items:center;gap:3px;font-size:12px;color:var(--secondary-text-color)}
        .ivt{font-weight:600;color:var(--primary-text-color)}
        @media (max-width:700px){ha-card{font-size:12px;gap:6px}.ctl{margin-left:0;width:100%}
          button{min-height:44px;min-width:44px;padding:6px 12px;font-size:13px}select{min-height:44px;min-width:56px;font-size:14px}}
      </style><ha-card><span class="st" id="st"></span><span class="m" id="msg"></span>
      <span class="sep">|</span><span class="k">Last</span> <span class="t" id="lt">-</span> <span class="k" id="la"></span>
      <span class="sep">|</span><span class="k">Next</span> <span class="t" id="nt">-</span> <span class="k" id="na"></span>
      <span class="ctl">
        <button class="chk" id="chk" title="Read the pot right away">&#8635; Check now</button>
        <button id="hunt" title="Hunt: check at hunt speed; off = normal speed">&#127939; Hunt</button>
        <span class="iv" title="Hunt interval (each wait varies by 30 %)">every <select id="hs"></select><b class="ivt" id="hst"></b> s</span>
        <span class="iv" title="Normal interval when Hunt is off (each wait varies by 30 %)">normal <select id="ns"></select><b class="ivt" id="nst"></b> min</span>
        <button class="pz" id="pz" title="Pause only if you will be in FLICA 30+ min; for a quick look just log in, the Watcher steps aside for 30 min">&#10074;&#10074; Pause</button>
        <button class="rearm" id="rearm" title="Logs into FLICA once and resumes" style="display:none">&#8634; Re-arm</button>
      </span></ha-card>`;
      const $ = (i) => this._root.getElementById(i);
      $("chk").addEventListener("click", () => this._h.callService("button", "press", { entity_id: "button.flight_watcher_check_now" }));
      $("hunt").addEventListener("click", () => this._h.callService("switch", "toggle", { entity_id: "switch.flight_watcher_hunt_mode" }));
      $("pz").addEventListener("click", () => this._h.callService("switch", "toggle", { entity_id: "switch.flight_watcher_pause" }));
      $("rearm").addEventListener("click", () => { if (confirm("Re-arm the Watcher? It logs into FLICA once.")) this._h.callService("button", "press", { entity_id: "button.flight_watcher_re_arm" }); });
      $("hs").addEventListener("change", (e) => this._h.callService("number", "set_value", { entity_id: "number.flight_watcher_hunt_check_every", value: parseFloat(e.target.value) }));
      $("ns").addEventListener("change", (e) => this._h.callService("number", "set_value", { entity_id: "number.flight_watcher_normal_check_every", value: parseFloat(e.target.value) }));
      this._tick = setInterval(() => this._render(), 1000);
    }
    this._render();
  }
  disconnectedCallback() { clearInterval(this._tick); this._root = null; }
  _st(id) { const s = this._h && this._h.states[id]; return s ? s.state : "unavailable"; }
  _attr(id, a) { const s = this._h && this._h.states[id]; return s && s.attributes ? s.attributes[a] : undefined; }
  _time(d) { return FC_TIME.format(d); }  // 1.6.2: HST on any phone (the rows below and FLICA are HST)
  // the options an interval select may offer: within the entity's own min / max and, in the portal, the contract's max
  _opts(list, id, kind) {
    const dflt = FC_DEFAULT[kind], a = parseFloat(this._attr(id, "min")), b = parseFloat(this._attr(id, "max"));
    const lo = isNaN(a) ? dflt[0] : a, hi = isNaN(b) ? dflt[1] : b;
    return list.filter((v) => v >= lo && v <= hi && (!FW_PORTAL || v <= FC_PORTAL_MAX[kind]));
  }
  _menu(el, txt, opts, v) {
    const key = opts.join(",");
    if (el.dataset.opts !== key) { el.innerHTML = opts.map((o) => `<option value="${o}">${o}</option>`).join(""); el.dataset.opts = key; }
    el.style.display = opts.length ? "" : "none";
    txt.textContent = opts.length ? "" : (isNaN(v) ? "?" : String(Math.round(v)));
    if (opts.length) this._sel(el, v);
  }
  _dur(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + " h " : "") + (h || m ? m + " min " : "") + s + " s";
  }
  _sel(el, v) {
    if (isNaN(v) || document.activeElement === el) return;
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
    if (isNaN(lc)) { $("lt").textContent = "never"; $("la").textContent = ""; }
    else { $("lt").textContent = this._time(new Date(lc)) + " HST"; $("la").textContent = "(" + this._dur(age) + " ago)"; $("la").className = blind ? "blind" : "k"; }
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
    this._menu($("hs"), $("hst"), this._opts(FC_HUNT, "number.flight_watcher_hunt_check_every", "hunt"), hs);
    this._menu($("ns"), $("nst"), this._opts(FC_NORM, "number.flight_watcher_normal_check_every", "normal"), nmv);
    const needRearm = ["stopped_unexpected", "stopped_login_failed", "yielded", "backoff"].includes(st) || blind;
    $("rearm").style.display = needRearm ? "" : "none";
    $("chk").style.display = ["idle", "hunting"].includes(st) && !paused ? "" : "none";
  }
  getCardSize() { return 1; }
}
customElements.define("flight-watcher-clock-card", FlightWatcherClockCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-clock-card", name: "Flight Watcher clock", description: "Flight Watcher status, last and next check, and controls in one line" });

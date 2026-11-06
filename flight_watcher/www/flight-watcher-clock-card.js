// Flight Watcher status line (v3, Nov 3 2026, Ryan): state + last/next check, live per second, with the
// controls inline: Check now, Hunt (with its interval), Pause, Normal interval, Re-arm when parked.
// Replaces the status alert card, the clock card and the Controls section. Pako HI, HOM t1218.
// Usage: type: custom:flight-watcher-clock-card (no options needed).
const FC_HUNT = [5, 10, 15, 20, 30, 45, 60, 90];          // seconds (number.flight_watcher_hunt_check_every 5-90)
const FC_NORM = [1, 2, 3, 4, 5, 6, 8, 10, 15, 20];       // minutes (number.flight_watcher_normal_check_every 1-20)
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
        @media (max-width:700px){ha-card{font-size:12px;gap:6px}.ctl{margin-left:0;width:100%}}
      </style><ha-card><span class="st" id="st"></span><span class="m" id="msg"></span>
      <span class="sep">|</span><span class="k">Last</span> <span class="t" id="lt">-</span> <span class="k" id="la"></span>
      <span class="sep">|</span><span class="k">Next</span> <span class="t" id="nt">-</span> <span class="k" id="na"></span>
      <span class="ctl">
        <button class="chk" id="chk" title="Read the pot right away">&#8635; Check now</button>
        <button id="hunt" title="Hunt: check at hunt speed; off = normal speed">&#127939; Hunt</button>
        <span class="iv" title="Hunt interval (each wait varies by 30 %)">every <select id="hs"></select> s</span>
        <span class="iv" title="Normal interval when Hunt is off (each wait varies by 30 %)">normal <select id="ns"></select> min</span>
        <button class="pz" id="pz" title="Pause only if you will be in FLICA 30+ min; for a quick look just log in, the Watcher steps aside for 30 min">&#10074;&#10074; Pause</button>
        <button class="rearm" id="rearm" title="Logs into FLICA once and resumes" style="display:none">&#8634; Re-arm</button>
      </span></ha-card>`;
      const $ = (i) => this._root.getElementById(i);
      $("hs").innerHTML = FC_HUNT.map((v) => `<option value="${v}">${v}</option>`).join("");
      $("ns").innerHTML = FC_NORM.map((v) => `<option value="${v}">${v}</option>`).join("");
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
  _time(d) { return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); }
  _dur(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + " h " : "") + (h || m ? m + " min " : "") + s + " s";
  }
  _sel(el, v) {
    if (isNaN(v) || document.activeElement === el) return;
    const want = String(Math.round(v));
    if (![...el.options].some((o) => o.value === want)) { const o = document.createElement("option"); o.value = want; o.textContent = want; el.appendChild(o); }
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
    const blind = age != null && age > lim && !["paused", "yielded"].includes(st);
    let cls = "ok", label = "", msg = "";
    if (["unavailable", "unknown"].includes(st)) { cls = "err"; label = "App not running."; msg = "It normally restarts itself; if this stays red, restart Flight Watcher in Settings > Apps."; }
    else if (st === "paused" || paused) { cls = "warn"; label = "Paused."; msg = "Not watching FLICA. Turn Pause off when you have signed out of FLICA."; }
    else if (["idle", "hunting"].includes(st) && blind) { cls = "err"; label = "Stuck."; msg = `No check for ${this._dur(age)}. Press Re-arm.`; }
    else if (st === "hunting") { cls = "ok"; label = "Hunting."; msg = `Checking about every ${isNaN(hs) ? "?" : Math.round(hs)} s.`; }
    else if (st === "idle") { cls = "ok"; label = "Watching."; msg = `Checking about every ${isNaN(nmv) ? "?" : Math.round(nmv)} min.`; }
    else if (st === "yielded") { cls = "info"; label = "Stepped aside."; msg = "Someone signed into FLICA with your account. " + note; }
    else if (st === "backoff") { cls = "info"; label = "Reconnecting."; msg = note; }
    else { cls = "err"; label = "Stopped, needs you."; msg = (note || st.replace(/_/g, " ")) + ". Fix that, then press Re-arm."; }
    card.className = cls; $("st").textContent = label; $("msg").textContent = msg;
    if (isNaN(lc)) { $("lt").textContent = "never"; $("la").textContent = ""; }
    else { $("lt").textContent = this._time(new Date(lc)); $("la").textContent = "(" + this._dur(age) + " ago)"; $("la").className = blind ? "blind" : "k"; }
    if (!["idle", "hunting"].includes(st)) { $("nt").textContent = "none"; $("na").textContent = ""; }
    else if (!isNaN(nc) && nc > now - 30000) { $("nt").textContent = this._time(new Date(nc)); $("na").textContent = nc > now ? "(in " + this._dur((nc - now) / 1000) + ")" : "(due now)"; }
    else if (!isNaN(lc)) {
      const mid = hunt ? hs : nmv * 60;
      const [lo, hi] = !isNaN(mid) ? [mid * 0.7, mid * 1.3] : (hunt ? [20, 60] : [120, 600]);
      const a = lc + lo * 1000, b = lc + hi * 1000;
      $("nt").textContent = this._time(new Date(a)) + " to " + this._time(new Date(b));
      $("na").textContent = now < a ? "(in " + this._dur((a - now) / 1000) + ")" : now < b ? "(any moment)" : "(overdue " + this._dur((now - b) / 1000) + ")";
    }
    // controls
    $("hunt").classList.toggle("on", hunt);
    $("pz").classList.toggle("on", paused);
    this._sel($("hs"), hs); this._sel($("ns"), nmv);
    const needRearm = ["stopped_unexpected", "stopped_login_failed", "yielded", "backoff"].includes(st) || blind;
    $("rearm").style.display = needRearm ? "" : "none";
    $("chk").style.display = ["idle", "hunting"].includes(st) && !paused ? "" : "none";
  }
  getCardSize() { return 1; }
}
customElements.define("flight-watcher-clock-card", FlightWatcherClockCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-clock-card", name: "Flight Watcher clock", description: "Flight Watcher status, last and next check, and controls in one line" });

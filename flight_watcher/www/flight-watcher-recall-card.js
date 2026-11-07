// Flight Watcher Recall / Over 75 card (0.9.2). mode: "tab" (full review) or "alert" (RECALL ALERT bar on the main view).
// Data: sensor.flight_watcher_recall_o75 (watcher recall.py). Answers go back on MQTT flight_watcher/recall/act.
// PWA 22.G.2.d (Over 75, 4.N), 22.G.2.e-g (Recall, 22.E, 4.M 200%), 10.E.1.a, 2.19.b; FAR 117.25(b)(e), 117.23(b)(1), 117.23(c).
// 1.4.6 (Nov 6): a red RECALL ALERT bar (one line per MISSED row with an open CCR draft) on top of the tab and as the
// alert card; days fold (closed by default when nothing on them is a miss, remembered in this browser); an approved
// narrative can go to Hark ("Have Hark file this CCR", recall/act file_request), who files it on hal.alpa.org and
// sends the CCR number back; the copy-and-open hal.alpa.org button stays as the manual way.
const RC_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const RC_DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const RC_LIVE = ["MISSED", "POSSIBLE"];
const RC_OPEN = ["new", "confirmed", "approved", "filing", "blocked", "cancelled"];
const RC_STATUS = { new: "new", confirmed: "confirmed", approved: "approved", filing: "sent to Hark", blocked: "Hark blocked", cancelled: "Hark cancelled", filed: "filed", dismissed: "dismissed", superseded: "superseded" };
const RC_FOLD = "flight_watcher_recall_fold";
class FlightWatcherRecallCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flight_watcher_recall_o75", mode: "tab", tab: "/flight-watcher/recall", ...c }; this._open = {}; this._drafts = {}; this._pending = {}; }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    const sig = st ? st.last_updated + JSON.stringify(st.attributes.me || {}) : "none";
    if (sig === this._sig) return;
    const ae = this.shadowRoot && this.shadowRoot.activeElement;  // never redraw under someone typing
    if (ae && (ae.tagName === "TEXTAREA" || (ae.tagName === "INPUT" && ae.dataset.ccr !== undefined))) return;
    this._sig = sig;
    this._render(st);
  }
  getCardSize() { return this._c.mode === "alert" ? 1 : 8; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
  _send(topic, obj) { this._h.callService("mqtt", "publish", { topic: `flight_watcher/${topic}`, payload: JSON.stringify(obj) }); }
  // HST "Nov 6 09:52" from an ISO time, built from parts (iOS Safari's toLocale strings vary, FW-0001)
  _hst(iso) {
    const t = Date.parse(iso || "");
    if (isNaN(t)) return "";
    const d = new Date(t - 10 * 3600e3);
    return `${RC_MON[d.getUTCMonth()]} ${d.getUTCDate()} ${d.toISOString().slice(11, 16)}`;
  }
  // "Tue Nov 10" from "2026-11-10"
  _day(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ""));
    if (!m) return String(s || "");
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return `${RC_DOW[d.getUTCDay()]} ${RC_MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
  }
  _kind(v) { return v.kind === "o75" ? "Over 75" : v.kind === "junior" ? "Junior manning" : "Recall"; }
  // Ryan (Nov 6): Refresh asks the Watcher to re-judge every list on file (recall/act {refresh}); the card redraws
  // when the sensor comes back with a new "checked" time, or says so after 15 s.
  _refresh() {
    if (this._busy) return;
    const st = this._h.states[this._c.entity];
    this._busy = { since: Date.now(), was: st ? st.attributes.checked || st.last_updated : "" };
    this._send("recall/act", { refresh: true });
    this._sig = null;
    this._render(st);
    clearTimeout(this._busyT);
    this._busyT = setTimeout(() => { if (this._busy) { this._busy = null; this._note = "No answer from the Watcher yet. Is it running?"; this._render(this._h.states[this._c.entity]); } }, 15000);
  }
  _go() { history.pushState(null, "", this._c.tab); window.dispatchEvent(new CustomEvent("location-changed")); }
  // 1.4.6: fold state per list day, kept only where it differs from the default (closed unless a row is MISSED / POSSIBLE)
  _folds() {
    if (!this._fold) { this._fold = {}; try { const v = JSON.parse(localStorage.getItem(RC_FOLD) || "null"); if (v && typeof v === "object") this._fold = v; } catch (e) {} }
    return this._fold;
  }
  _saveFolds() {
    const keys = Object.keys(this._fold).sort();
    for (const k of keys.slice(0, Math.max(0, keys.length - 200))) delete this._fold[k];
    try { localStorage.setItem(RC_FOLD, JSON.stringify(this._fold)); } catch (e) {}
  }
  _dayOpenByDefault(d) { return (d.verdicts || []).some((v) => RC_LIVE.includes(v.verdict)); }
  _isOpen(d) { const f = this._folds(); return Object.prototype.hasOwnProperty.call(f, d.date) ? !!f[d.date] : this._dayOpenByDefault(d); }
  _alerts(days) {
    return days.flatMap((d) => (d.verdicts || []).filter((v) => v.verdict === "MISSED" && RC_OPEN.includes((v.act || {}).status)).map((v) => ({ ...v, listDay: d.date })));
  }
  _bar(alert, withJump) {
    if (!alert.length) return "";
    const li = alert.map((v) => `<li${withJump ? "" : ` data-goday="${this._e(v.listDay)}" tabindex="0"`}><b>${this._e(this._day(v.date))}</b> ${this._e(this._kind(v))} <b>${this._e(v.pairing)}</b> went to #${this._e(v.sen)} <span class="bs">${this._e(RC_STATUS[(v.act || {}).status] || (v.act || {}).status)}</span></li>`).join("");
    return `<div class="bar" role="alert"><div class="bh">RECALL ALERT<span class="bn">${alert.length}</span></div><div class="bsub">The Watcher says ${alert.length > 1 ? "these recalls" : "this recall"} should have been yours:</div><ul>${li}</ul>${withJump ? `<button class="w" data-go="1">Review and file CCR on Recall/O75</button>` : ""}</div>`;
  }
  _css() {
    return `<style>
      :host{display:block}
      ha-card{padding:12px 14px;font-size:13px;overflow-wrap:anywhere}
      .bar{background:#b71c1c;color:#fff;border-radius:10px;padding:10px 12px;margin:0 0 10px;box-sizing:border-box;max-width:100%}
      .bh{font-weight:900;letter-spacing:1px;font-size:16px;display:flex;align-items:center;gap:8px}
      .bn{background:#fff;color:#b71c1c;border-radius:10px;padding:0 8px;font-size:13px;letter-spacing:0}
      .bsub{font-size:12px;opacity:.9;margin-top:2px}
      .bar ul{margin:6px 0 0;padding-left:18px}.bar li{margin:3px 0;line-height:1.35}.bar li[data-goday]{cursor:pointer}
      .bs{display:inline-block;background:rgba(255,255,255,.2);border-radius:8px;padding:0 6px;font-size:11px;font-weight:700;text-transform:uppercase}
      .bar button{margin-top:8px}
      button{cursor:pointer;border:0;border-radius:6px;padding:6px 10px;font-weight:600;background:var(--primary-color);color:#fff;margin:2px 4px 2px 0;max-width:100%;white-space:normal}
      button.g{background:#757575}button.r{background:#c62828}button.w{background:#fff;color:#b71c1c}button.h{background:#2e7d32}button:disabled{opacity:.6;cursor:default}
      details.day{border-top:1px solid var(--divider-color);padding:6px 0}
      details.day>summary{cursor:pointer;font-size:14px;padding:2px 0;list-style-position:inside}
      .row{margin:4px 0 4px 8px}
      .chip{display:inline-block;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:#fff;margin-right:6px}
      .MISSED{background:#c62828}.POSSIBLE{background:#ef6c00}.NO{background:#9e9e9e}.row.vMISSED{background:rgba(198,40,40,.12);border-left:4px solid #c62828;padding:4px 8px;border-radius:6px}.row.vNO{opacity:.55}.row.vPOSSIBLE{border-left:4px solid #ef6c00;padding:2px 8px}
      .why{color:var(--secondary-text-color);font-size:12px}
      .hk{margin:4px 0;padding:4px 8px;border-radius:6px;background:rgba(46,125,50,.12);border-left:4px solid #2e7d32}.hk.bad{background:rgba(239,108,0,.14);border-left-color:#ef6c00}
      textarea{width:100%;min-height:150px;font:12px/1.4 var(--paper-font-body1_-_font-family,sans-serif);box-sizing:border-box;margin:6px 0}
      pre.n{white-space:pre-wrap;font:12px/1.4 var(--paper-font-body1_-_font-family,sans-serif);margin:4px 0}
      .me{display:flex;gap:8px 12px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
      .me input[type=number]{width:70px}.mp{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:15px}.mp .nv{cursor:pointer;font-size:20px;color:var(--primary-color);padding:0 6px;user-select:none}.k{color:var(--secondary-text-color);font-size:12px}
      .st{font-weight:700;text-transform:uppercase;font-size:11px}
    </style>`;
  }
  _render(st) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const a = st ? st.attributes : {};
    const days = a.days || [];
    const alert = this._alerts(days);
    const css = this._css();
    if (this._c.mode === "alert") {
      this.shadowRoot.innerHTML = alert.length ? `${css}<ha-card style="padding:0;background:none;box-shadow:none">${this._bar(alert, true)}</ha-card>` : "";
      const b = this.shadowRoot.querySelector("[data-go]");
      if (b) b.onclick = () => this._go();
      return;
    }
    if (this._busy && (a.checked || (st && st.last_updated)) !== this._busy.was) { this._busy = null; this._note = ""; clearTimeout(this._busyT); }
    const me = a.me || {};
    if (!this._m) { const n = new Date(Date.now() - 10 * 3600e3); this._m = n.toISOString().slice(0, 7); }
    const [my, mm] = this._m.split("-").map(Number);
    if (!this._show) { this._show = { FO: true, CA: false }; try { const v = JSON.parse(localStorage.getItem("flight_watcher_recall_show") || "null"); if (v) this._show = v; } catch (e) {} }
    const show = this._show;
    const hark = !!a.hark_files;
    const mdays = days.filter((d) => String(d.date || "").startsWith(this._m));
    const nmiss = mdays.flatMap((d) => d.verdicts || []).filter((v) => v.verdict === "MISSED").length;
    const rows = mdays.map((d) => this._dayHtml(d, show, hark)).join("");
    this.shadowRoot.innerHTML = `${css}<ha-card>
      ${this._bar(alert, false)}
      <div class="me"><b>Recall / Over 75</b>
        <span>My seniority # <input type="number" data-me="sen" value="${this._e(me.sen ?? "")}"></span>
        <span><label><input type="checkbox" data-show="FO"${show.FO ? " checked" : ""}> FO</label> <label><input type="checkbox" data-show="CA"${show.CA ? " checked" : ""}> CA</label></span>
        <span><label><input type="checkbox" data-me="o75"${me.o75 !== false ? " checked" : ""}> Over 75 eligible (Reserve Run, 22.G.2.d)</label></span>
        <span class="k">last list ${this._e(a.last || "none yet")}${a.received ? ` (came in ${this._e(this._hst(a.received))})` : ""}</span>
        <button class="g" data-refresh${this._busy ? " disabled" : ""}>&#8635; ${this._busy ? "Refreshing..." : "Refresh"}</button>
        <span class="k" data-checked>${this._note ? `<span style="color:var(--error-color,#c62828)">${this._e(this._note)}</span>` : a.checked ? `checked ${this._e(this._hst(a.checked))} HST` : ""}</span>
        <span class="mp"><span class="nv" data-m="-1">&#8249;</span><b>${RC_MON[mm - 1]} ${my}</b><span class="nv" data-m="1">&#8250;</span>${nmiss ? `<span class="chip MISSED">${nmiss} missed</span>` : ""}</span></div>
      <div class="k">Hark reads the daily HNL recall list from Flight Ops SharePoint and posts it here. Each award to a pilot junior to you is checked against your line as you held it that day (the schedule version in force then, not today's): open days, no blocked day, trip or vacation in the way (22.G.2.e first, 22.G.2.f/g after), FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h in 672 h, 117.23(c) FDP 60 h in 168 h and 190 h in 672 h, PWA 10.E.1.a 11 h domicile rest. Anything not on file makes it CHECK, never SHOULD HAVE BEEN YOU.</div>
      ${rows || `<div class="day why">No recall lists on file for ${RC_MON[mm - 1]} ${my}.</div>`}
      <details style="margin-top:8px"><summary class="k">Paste a recall list (manual)</summary><textarea data-paste placeholder='{"date":"2026-11-04","rows":[{"kind":"recall","seat":"FO","pilot":"","sen":900,"pairing":"H3601"}]}'></textarea><button data-paste-go>Check this list</button></details>
    </ha-card>`;
    this._wire();
  }
  _dayHtml(d, show, hark) {
    const vs = d.verdicts || [];
    const shown = vs.filter((v) => show[(v.seat || "FO").toUpperCase()]);
    const n = (k) => vs.filter((v) => v.verdict === k).length;
    const file = String(d.file || "");
    const tag = n("MISSED") ? `<span class="chip MISSED">${n("MISSED")} should have been you</span>` : "";
    const tag2 = n("POSSIBLE") ? `<span class="chip POSSIBLE">${n("POSSIBLE")} check</span>` : "";
    const quiet = !tag && !tag2 && file === "ok" ? `<span class="k">${vs.length ? "no miss" : "no rows"}</span>` : "";
    const body = shown.length ? shown.map((v) => this._row(v, hark)).join("") : `<div class="row why">No ${["FO", "CA"].filter((k) => show[k]).join(" or ") || "seat"} Recall or Over 75 awards on this list.</div>`;
    return `<details class="day" data-day="${this._e(d.date)}"${this._isOpen(d) ? " open" : ""}><summary><b>${this._e(this._day(d.date))}</b> <span class="k">list ${this._e(file || "not posted")}</span> ${tag}${tag2}${quiet}</summary>${body}</details>`;
  }
  _harkLine(act) {
    const s = act.status;
    if (s === "filing") return `<div class="hk">Sent to Hark ${this._e(this._hst(act.requested_at))} HST, waiting for the CCR number${act.task_id ? ` (HOM task ${this._e(act.task_id)})` : ""}. To stop it, cancel the task in HOM.</div>`;
    if (s === "filed" && act.ccr) return `<div class="hk">Filed: CCR ${this._e(act.ccr)}${act.filed_by ? ` by ${this._e(act.filed_by.charAt(0).toUpperCase() + act.filed_by.slice(1))}` : ""}${act.filed_at ? ` ${this._e(this._hst(act.filed_at))} HST` : ""}${act.filed_note ? `<div class="why">${this._e(act.filed_note)}</div>` : ""}</div>`;
    if (["blocked", "cancelled"].includes(s)) return `<div class="hk bad">Hark ${this._e(s)}${act.hark_at ? ` ${this._e(this._hst(act.hark_at))} HST` : ""}: ${this._e(act.hark_reason || "no reason given")}. You can send it again or file it yourself.</div>`;
    if (act.hark_reason) return `<div class="hk bad">${this._e(act.hark_reason)}</div>`;
    return "";
  }
  _row(v, hark) {
    const act = v.act || {};
    const s = act.status;
    const live = RC_LIVE.includes(v.verdict) && s && s !== "superseded";
    const id = this._e(v.id);
    let ctl = "";
    if (live) {
      const txt = this._drafts[v.id] ?? act.narrative ?? "";
      const edit = ["confirmed", "approved", "blocked", "cancelled"].includes(s);
      const canHark = hark && (s === "approved" || (["blocked", "cancelled"].includes(s) && act.approved_at));
      const pend = this._pending[v.id] && Date.now() - this._pending[v.id] < 15000 && s !== "filing";
      if (this._pending[v.id] && s === "filing") delete this._pending[v.id];
      const late = this._pending[v.id] && !pend ? `<div class="hk bad">The Watcher did not take the request. It only sends an approved narrative on a row that is still a miss; see its log.</div>` : "";
      ctl = `<div><span class="st">${this._e(RC_STATUS[s] || s)}</span>${act.ccr && s !== "filed" ? ` <span class="k">CCR ${this._e(act.ccr)}</span>` : ""}</div>
        ${this._harkLine(act)}${late}
        ${s === "new" ? `<button class="r" data-a="confirm" data-id="${id}">Yes, I missed this</button><button class="g" data-a="dismiss" data-id="${id}">Not a miss</button>` : ""}
        ${edit ? `<div class="k">CCR narrative: edit until it is right, then approve. Nothing is filed until you approve it. Then Have Hark file this CCR sends it to Hark, who files it on hal.alpa.org and sends back the CCR number; or file it yourself.</div><textarea data-n="${id}">${this._e(txt)}</textarea>
          <button data-a="approve" data-id="${id}">${s === "confirmed" ? "Approve narrative" : "Re-approve edited narrative"}</button>
          ${canHark ? `<button class="h" data-hark="${id}"${pend ? " disabled" : ""}>${pend ? "Sending to Hark..." : "Have Hark file this CCR"}</button>` : ""}
          ${s !== "confirmed" ? `<button class="r" data-file="${id}">File it myself on hal.alpa.org</button>` : ""}
          <button class="g" data-a="dismiss" data-id="${id}">Not a miss</button>
          <span>CCR # <input data-ccr="${id}" style="width:90px"></span><button class="g" data-a="filed" data-id="${id}">Mark filed</button>` : ""}
        ${s === "filing" ? `<details><summary class="k">Narrative sent to Hark</summary><pre class="n">${this._e(act.narrative)}</pre></details>
          <button class="r" data-file="${id}">File it myself on hal.alpa.org</button>
          <span>CCR # <input data-ccr="${id}" style="width:90px"></span><button class="g" data-a="filed" data-id="${id}">Mark filed</button>` : ""}
        ${["dismissed", "filed"].includes(s) ? `<button class="g" data-a="reopen" data-id="${id}">Reopen</button>` : ""}`;
    } else if (s === "superseded") {
      ctl = `<div class="k"><span class="st">superseded</span> CCR draft closed, no longer a miss (was ${this._e(RC_STATUS[act.was] || act.was || "new")}${act.ccr ? `, CCR ${this._e(act.ccr)}` : ""}). It comes back if the row turns into a miss again.</div>`;
    }
    const lab = { MISSED: "SHOULD HAVE BEEN YOU", POSSIBLE: "CHECK", NO: "NO MISS" }[v.verdict] || v.verdict;
    return `<div class="row v${this._e(v.verdict)}"><span class="chip ${this._e(v.verdict)}">${this._e(lab)}</span><b>${this._e(this._kind(v))} ${this._e(v.pairing)}</b> ${this._e(v.seat)} to #${this._e(v.sen)} ${this._e(v.pilot)}
      <div class="why">${(v.why || []).map((w) => this._e(w)).join(" · ")}${(v.refs || []).length ? ` <i>(${(v.refs || []).map((r) => this._e(r)).join(", ")})</i>` : ""}</div>${ctl}</div>`;
  }
  _narrative(id) {
    const t = this.shadowRoot.querySelector(`textarea[data-n="${CSS.escape(id)}"]`);
    if (t) return t.value;
    const st = this._h.states[this._c.entity];
    for (const d of (st && st.attributes.days) || []) for (const v of d.verdicts || []) if (v.id === id) return (v.act || {}).narrative || "";
    return "";
  }
  _wire() {
    const r = this.shadowRoot;
    const rf = r.querySelector("[data-refresh]");
    if (rf) rf.onclick = () => this._refresh();
    r.querySelectorAll("[data-m]").forEach((el) => el.onclick = () => {
      const [y, m] = this._m.split("-").map(Number);
      const d = new Date(Date.UTC(y, m - 1 + Number(el.dataset.m), 1));
      this._m = d.toISOString().slice(0, 7);
      this._render(this._h.states[this._c.entity]);
    });
    r.querySelectorAll("details.day").forEach((el) => el.addEventListener("toggle", () => {
      const st = this._h.states[this._c.entity];
      const d = ((st && st.attributes.days) || []).find((x) => x.date === el.dataset.day);
      if (!d) return;
      const f = this._folds(), was = JSON.stringify(f[d.date]);
      if (el.open === this._dayOpenByDefault(d)) delete f[d.date]; else f[d.date] = el.open;
      if (JSON.stringify(f[d.date]) !== was) this._saveFolds();
    }));
    r.querySelectorAll("[data-goday]").forEach((el) => {
      const go = () => {
        const dk = el.dataset.goday;
        this._m = dk.slice(0, 7);
        const f = this._folds();
        delete f[dk];  // a day with a miss is open by default
        this._saveFolds();
        this._render(this._h.states[this._c.entity]);
        const t = this.shadowRoot.querySelector(`details.day[data-day="${CSS.escape(dk)}"]`);
        if (t) { t.open = true; t.scrollIntoView({ behavior: "smooth", block: "start" }); }
      };
      el.onclick = go;
      el.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } };
    });
    r.querySelectorAll("[data-show]").forEach((el) => el.onchange = () => {
      this._show = { ...this._show, [el.dataset.show]: el.checked };
      try { localStorage.setItem("flight_watcher_recall_show", JSON.stringify(this._show)); } catch (e) {}
      this._render(this._h.states[this._c.entity]);
    });
    r.querySelectorAll("[data-me]").forEach((el) => el.onchange = () => {
      const me = { sen: parseInt(r.querySelector('[data-me="sen"]').value, 10) || null, seat: "FO", o75: r.querySelector('[data-me="o75"]').checked };
      this._send("recall/act", { me });
    });
    r.querySelectorAll("textarea[data-n]").forEach((t) => t.oninput = () => { this._drafts[t.dataset.n] = t.value; });
    r.querySelectorAll("button[data-a]").forEach((b) => b.onclick = () => {
      const id = b.dataset.id, msg = { id, action: b.dataset.a };
      const t = r.querySelector(`textarea[data-n="${CSS.escape(id)}"]`);
      if (t && b.dataset.a === "approve") msg.narrative = t.value;
      const c = r.querySelector(`input[data-ccr="${CSS.escape(id)}"]`);
      if (c && b.dataset.a === "filed") msg.ccr = c.value;
      this._send("recall/act", msg);
      if (b.dataset.a === "approve") delete this._drafts[id];
      this._sig = null;
    });
    // 1.4.6: the Watcher writes the request for Hark only for an approved narrative on a row that is still a miss
    r.querySelectorAll("button[data-hark]").forEach((b) => b.onclick = () => {
      const id = b.dataset.hark;
      this._pending[id] = Date.now();
      this._send("recall/act", { id, action: "file_request" });
      b.disabled = true;
      b.textContent = "Sending to Hark...";
      this._sig = null;
      setTimeout(() => { if (this._pending[id]) { this._sig = null; this._render(this._h.states[this._c.entity]); } }, 15500);
    });
    r.querySelectorAll("button[data-file]").forEach((b) => b.onclick = () => {
      const txt = this._narrative(b.dataset.file);
      if (txt && navigator.clipboard) navigator.clipboard.writeText(txt).catch(() => {});
      window.open("https://hal.alpa.org", "_blank", "noopener");
    });
    const pg = r.querySelector("[data-paste-go]");
    if (pg) pg.onclick = () => {
      try { let j = JSON.parse(r.querySelector("[data-paste]").value); const fix = (d) => ({ ...d, rows: (d.rows || []).map((x) => ({ date: d.date, ...x })) }); j = Array.isArray(j) ? j.map(fix) : fix(j); this._h.callService("mqtt", "publish", { topic: "flight_watcher/recall/set", payload: JSON.stringify(j) }); pg.textContent = "Sent"; }
      catch (e) { pg.textContent = "Not valid JSON"; }
    };
  }
}
customElements.define("flight-watcher-recall-card", FlightWatcherRecallCard);

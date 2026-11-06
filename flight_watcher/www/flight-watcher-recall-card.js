// Flight Watcher Recall / Over 75 card (0.9.2). mode: "tab" (full review) or "alert" (red banner on the main view).
// Data: sensor.flight_watcher_recall_o75 (watcher recall.py). Answers go back on MQTT flight_watcher/recall/act.
// PWA 22.G.2.d (Over 75, 4.N), 22.G.2.e-g (Recall, 22.E, 4.M 200%), 10.E.1.a; FAR 117.25(b)(e), 117.23(b)(1).
class FlightWatcherRecallCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flight_watcher_recall_o75", mode: "tab", tab: "/flight-watcher/recall", ...c }; this._open = {}; this._drafts = {}; }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    const sig = st ? st.last_updated + JSON.stringify(st.attributes.me || {}) : "none";
    if (sig === this._sig) return;
    if (this.shadowRoot && this.shadowRoot.activeElement && this.shadowRoot.activeElement.tagName === "TEXTAREA") return;
    this._sig = sig;
    this._render(st);
  }
  getCardSize() { return this._c.mode === "alert" ? 1 : 8; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  _send(topic, obj) { this._h.callService("mqtt", "publish", { topic: `flight_watcher/${topic}`, payload: JSON.stringify(obj) }); }
  // HST "Nov 6 09:52" from an ISO time, built from parts (iOS Safari's toLocale strings vary, FW-0001)
  _hst(iso) {
    const t = Date.parse(iso || "");
    if (isNaN(t)) return "";
    const d = new Date(t - 10 * 3600e3);
    return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()]} ${d.getUTCDate()} ${d.toISOString().slice(11, 16)}`;
  }
  // Ryan (Nov 6): Refresh asks the Watcher to re-judge every list on file against the current line (recall/act
  // {refresh}); the card redraws when the sensor comes back with a new "checked" time, or says so after 15 s.
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
  _render(st) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const a = st ? st.attributes : {};
    const days = a.days || [];
    const all = days.flatMap((d) => (d.verdicts || []).map((v) => ({ ...v, file: d.file })));
    // FW-0012: a CCR draft counts only while its row is MISSED or POSSIBLE (a row that turned NO keeps its act as history)
    const alert = all.filter((v) => ["MISSED", "POSSIBLE"].includes(v.verdict) && ["new", "confirmed", "approved"].includes((v.act || {}).status) && (v.verdict === "MISSED" || ["confirmed", "approved"].includes((v.act || {}).status)));
    const css = `<style>
      ha-card{padding:12px 14px;font-size:13px}
      .red{background:#b71c1c;color:#fff;border-radius:10px;padding:8px 12px}
      .red summary{cursor:pointer;font-weight:800;letter-spacing:.5px}
      .red li{margin:3px 0}.red button{margin-top:6px}
      button{cursor:pointer;border:0;border-radius:6px;padding:5px 10px;font-weight:600;background:var(--primary-color);color:#fff;margin:2px 4px 2px 0}
      button.g{background:#757575}button.r{background:#c62828}button.w{background:#fff;color:#b71c1c}button:disabled{opacity:.6;cursor:default}
      .day{border-top:1px solid var(--divider-color);padding:8px 0}
      .day h4{margin:0 0 4px;font-size:14px}
      .row{margin:4px 0 4px 8px}
      .chip{display:inline-block;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:#fff;margin-right:6px}
      .MISSED{background:#c62828}.POSSIBLE{background:#ef6c00}.NO{background:#9e9e9e}.row.vMISSED{background:rgba(198,40,40,.12);border-left:4px solid #c62828;padding:4px 8px;border-radius:6px}.row.vNO{opacity:.55}.row.vPOSSIBLE{border-left:4px solid #ef6c00;padding:2px 8px}
      .why{color:var(--secondary-text-color);font-size:12px}
      textarea{width:100%;min-height:150px;font:12px/1.4 var(--paper-font-body1_-_font-family,sans-serif);box-sizing:border-box;margin:6px 0}
      .me{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
      .me input{width:70px}.mp{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:15px}.mp .nv{cursor:pointer;font-size:20px;color:var(--primary-color);padding:0 6px;user-select:none}.k{color:var(--secondary-text-color);font-size:12px}
      .st{font-weight:700;text-transform:uppercase;font-size:11px}
    </style>`;
    if (this._c.mode === "alert") {
      this.shadowRoot.innerHTML = alert.length ? `${css}<ha-card style="padding:0;background:none;box-shadow:none"><details class="red" open><summary>RED ALERT: ${alert.length} recall${alert.length > 1 ? "s" : ""} you may have missed</summary><ul>${alert.map((v) => `<li>${this._e(v.date)} ${this._e(v.kind === "o75" ? "Over 75" : "Recall")} ${this._e(v.pairing)} went to #${this._e(v.sen)} (${this._e((v.act || {}).status)})</li>`).join("")}</ul><button class="w" data-go="1">Review and file CCR on Recall/O75</button></details></ha-card>` : "";
      const b = this.shadowRoot.querySelector("[data-go]");
      if (b) b.onclick = () => this._go();
      return;
    }
    if (this._busy && (a.checked || (st && st.last_updated)) !== this._busy.was) { this._busy = null; this._note = ""; clearTimeout(this._busyT); }
    const me = a.me || {};
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    if (!this._m) { const n = new Date(Date.now() - 10 * 3600e3); this._m = n.toISOString().slice(0, 7); }
    const [my, mm] = this._m.split("-").map(Number);
    if (!this._show) { this._show = { FO: true, CA: false }; try { const v = JSON.parse(localStorage.getItem("flight_watcher_recall_show") || "null"); if (v) this._show = v; } catch (e) {} }
    const show = this._show;
    const mdays = days.filter((d) => String(d.date || "").startsWith(this._m));
    const nmiss = mdays.flatMap((d) => d.verdicts || []).filter((v) => v.verdict === "MISSED").length;
    const rows = mdays.map((d) => `<div class="day"><h4>${this._e(d.date)} <span class="k">list ${this._e(d.file)}</span></h4>${(d.verdicts || []).filter((v) => show[(v.seat || "FO").toUpperCase()]).length ? d.verdicts.filter((v) => show[(v.seat || "FO").toUpperCase()]).map((v) => this._row(v)).join("") : `<div class="row why">No ${["FO", "CA"].filter((k) => show[k]).join(" or ") || "seat"} Recall or Over 75 awards on this list.</div>`}</div>`).join("");
    this.shadowRoot.innerHTML = `${css}<ha-card>
      <div class="me"><b>Recall / Over 75</b>
        <span>My seniority # <input type="number" data-me="sen" value="${this._e(me.sen ?? "")}"></span>
        <span><label><input type="checkbox" data-show="FO"${show.FO ? " checked" : ""}> FO</label> <label><input type="checkbox" data-show="CA"${show.CA ? " checked" : ""}> CA</label></span>
        <span><label><input type="checkbox" data-me="o75"${me.o75 !== false ? " checked" : ""}> Over 75 eligible (Reserve Run, 22.G.2.d)</label></span>
        <span class="k">last list ${this._e(a.last || "none yet")}${a.received ? ` (came in ${this._e(this._hst(a.received))})` : ""}</span>
        <button class="g" data-refresh${this._busy ? " disabled" : ""}>&#8635; ${this._busy ? "Refreshing..." : "Refresh"}</button>
        <span class="k" data-checked>${this._note ? `<span style="color:var(--error-color,#c62828)">${this._e(this._note)}</span>` : a.checked ? `checked ${this._e(this._hst(a.checked))} HST` : ""}</span>
        <span class="mp"><span class="nv" data-m="-1">&#8249;</span><b>${MON[mm - 1]} ${my}</b><span class="nv" data-m="1">&#8250;</span>${nmiss ? `<span class="chip MISSED">${nmiss} missed</span>` : ""}</span></div>
      <div class="k">Hark reads the daily HNL recall list from Flight Ops SharePoint and posts it here. Each award to a pilot junior to you is checked against your line: open days, no blocked day, trip or vacation in the way (22.G.2.e first, 22.G.2.f/g after), FAR 117 rest and 30 h in 168 h, 100 h in 672 h, PWA 10.E.1.a 11 h domicile rest.</div>
      ${rows || `<div class="day why">No recall lists on file for ${MON[mm - 1]} ${my}.</div>`}
      <details style="margin-top:8px"><summary class="k">Paste a recall list (manual)</summary><textarea data-paste placeholder='{"date":"2026-11-04","rows":[{"kind":"recall","seat":"FO","pilot":"","sen":900,"pairing":"H3601"}]}'></textarea><button data-paste-go>Check this list</button></details>
    </ha-card>`;
    this._wire();
  }
  _row(v) {
    const act = v.act || {};
    const live = ["MISSED", "POSSIBLE"].includes(v.verdict) && act.status && act.status !== "superseded";
    const id = this._e(v.id);
    let ctl = "";
    if (live) {
      const txt = this._drafts[v.id] ?? act.narrative ?? "";
      ctl = `<div><span class="st">${this._e(act.status)}</span>${act.ccr ? ` <span class="k">CCR ${this._e(act.ccr)}</span>` : ""}</div>
        ${act.status === "new" ? `<button class="r" data-a="confirm" data-id="${id}">Yes, I missed this</button><button class="g" data-a="dismiss" data-id="${id}">Not a miss</button>` : ""}
        ${["confirmed", "approved"].includes(act.status) ? `<div class="k">CCR narrative: edit until it is right, then approve. Nothing is filed until you approve it and tell Claude "file CCR ${this._e(v.date)} ${this._e(v.pairing)}".</div><textarea data-n="${id}">${this._e(txt)}</textarea>
          <button data-a="approve" data-id="${id}">${act.status === "approved" ? "Re-approve edited narrative" : "Approve narrative"}</button>
          ${act.status === "approved" ? `<button class="r" data-file="${id}">File CCR on hal.alpa.org</button>` : ""}
          <button class="g" data-a="dismiss" data-id="${id}">Not a miss</button>
          <span>CCR # <input data-ccr="${id}" style="width:90px"></span><button class="g" data-a="filed" data-id="${id}">Mark filed</button>` : ""}
        ${["dismissed", "filed"].includes(act.status) ? `<button class="g" data-a="reopen" data-id="${id}">Reopen</button>` : ""}`;
    } else if (act.status === "superseded") {
      ctl = `<div class="k"><span class="st">superseded</span> CCR draft closed, no longer a miss (was ${this._e(act.was || "new")}${act.ccr ? `, CCR ${this._e(act.ccr)}` : ""}). It comes back if the row turns into a miss again.</div>`;
    }
    const lab = { MISSED: "SHOULD HAVE BEEN YOU", POSSIBLE: "CHECK", NO: "NO MISS" }[v.verdict] || v.verdict;
    return `<div class="row v${this._e(v.verdict)}"><span class="chip ${this._e(v.verdict)}">${this._e(lab)}</span><b>${this._e(v.kind === "o75" ? "Over 75" : v.kind === "junior" ? "Junior manning" : "Recall")} ${this._e(v.pairing)}</b> ${this._e(v.seat)} to #${this._e(v.sen)} ${this._e(v.pilot)}
      <div class="why">${(v.why || []).map((w) => this._e(w)).join(" · ")}${(v.refs || []).length ? ` <i>(${(v.refs || []).map((r) => this._e(r)).join(", ")})</i>` : ""}</div>${ctl}</div>`;
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
    r.querySelectorAll("button[data-file]").forEach((b) => b.onclick = () => {
      const t = r.querySelector(`textarea[data-n="${CSS.escape(b.dataset.file)}"]`);
      if (t && navigator.clipboard) navigator.clipboard.writeText(t.value).catch(() => {});
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

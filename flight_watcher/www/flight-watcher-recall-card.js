// Flight Watcher Recall / Over 75 card (0.9.2). mode: "tab" (full review) or "alert" (RECALL ALERT bar on the main view).
// Data: sensor.flight_watcher_recall_o75 (watcher recall.py). Answers go back on MQTT flight_watcher/recall/act.
// PWA 22.G.2.d (Over 75, 4.N), 22.G.2.e-g (Recall, 22.E, 4.M 200%), 10.E.1.a, 2.19.b; FAR 117.25(b)(e), 117.23(b)(1), 117.23(c).
// 1.4.6 (Nov 6): a red RECALL ALERT bar (one line per MISSED row with an open CCR draft) on top of the tab and as the
// alert card; days fold (closed by default when nothing on them is a miss, remembered in this browser); an approved
// narrative can go to Hark ("Have Hark file this CCR", recall/act file_request), who files it on hal.alpa.org and
// sends the CCR number back; the copy-and-open hal.alpa.org button stays as the manual way.
// 1.4.6 review (Nov 7): the Hark button is off while the box differs from the approved narrative; while Hark may
// still file a draft (sent, blocked, cancelled), a warning names the HOM task and Withdraw from Hark, Not a miss and
// Mark filed wait for "I completed HOM task ... as skipped" (they send hom_cleared); no second request once HOM made a
// task; Over 75 eligibility is answered per month (me.o75_months).
// 1.6.2 (Release A item 10): the seniority # is a whole number 1 to 99999 (nothing else is sent; blank forgets the typed
// one), its source is shown (typed, the award, the seniority list); a row whose seniority or line is not on file says
// so and gets no CCR draft; the Hark hint only where Hark files (hark_files); day rows tell a list not posted from an
// empty one; "came in" carries HST.
// FW-0060 (1.4.7): every list day comes from recall_<key>.json under /local/ too; the sensor keeps the newest days that
// fit HA's 16 KB recorder limit (and the counts over all of them), and its days win over the file's.
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
const RC_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const RC_DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const RC_LIVE = ["MISSED", "POSSIBLE"];
const RC_OPEN = ["new", "confirmed", "approved", "filing", "blocked", "cancelled"];
const RC_HARK = ["filing", "blocked", "cancelled"];  // Hark's HOM task (or the request) may still file it
const RC_STATUS = { new: "new", confirmed: "confirmed", approved: "approved", filing: "sent to Hark", blocked: "Hark blocked", cancelled: "Hark cancelled", filed: "filed", dismissed: "dismissed", superseded: "superseded" };
const RC_FOLD = "flight_watcher_recall_fold";
class FlightWatcherRecallCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flight_watcher_recall_o75", mode: "tab", tab: "/flight-watcher/recall", ...c }; this._open = {}; this._drafts = {}; this._pending = {}; this._approved = {}; }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    const sig = st ? st.last_updated + JSON.stringify(st.attributes.me || {}) : "none";
    if (sig === this._sig) return;
    const ae = this.shadowRoot && this.shadowRoot.activeElement;  // never redraw under someone typing
    if (ae && (ae.tagName === "TEXTAREA" || (ae.tagName === "INPUT" && (ae.dataset.ccr !== undefined || ae.dataset.me !== undefined)) || ae.tagName === "SELECT")) return;
    this._sig = sig;
    this._render(st);
  }
  getCardSize() { return this._c.mode === "alert" ? 1 : 8; }
  // FW-0060: the sensor's days (newest, fresher) plus the older days only the file has, newest first
  _days(st) {
    const a = (st && st.attributes) || {};
    const sens = a.days || [];
    const f = fwListFile(this._lf || (this._lf = {}), "/local/flight-watcher/recall_", st,
      () => { this._sig = null; if (this._h) this.hass = this._h; });
    if (!f || !Array.isArray(f.days)) return sens;
    const have = new Set(sens.map((d) => d.date));
    return sens.concat(f.days.filter((d) => !have.has(d.date))).sort((x, y) => (x.date < y.date ? 1 : x.date > y.date ? -1 : 0));
  }
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
      .hw{margin:4px 0;padding:4px 8px;border-radius:6px;background:rgba(198,40,40,.10);border-left:4px solid #c62828;font-weight:600}
      .gate{display:block;margin:4px 0}.dn{color:#c62828;font-size:12px;margin:2px 0}
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
    const days = this._days(st);
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
    const om = (me.o75_months && typeof me.o75_months === "object") ? me.o75_months[this._m] : undefined;
    const o75 = om === true ? "yes" : om === false ? "no" : "";
    const mdays = days.filter((d) => String(d.date || "").startsWith(this._m));
    const nmiss = mdays.flatMap((d) => d.verdicts || []).filter((v) => v.verdict === "MISSED").length;
    const rows = mdays.map((d) => this._dayHtml(d, show, hark)).join("");
    this.shadowRoot.innerHTML = `${css}<ha-card>
      ${this._bar(alert, false)}
      <div class="me"><b>Recall / Over 75</b>
        <span>My seniority # <input type="number" data-me="sen" min="1" max="99999" step="1" inputmode="numeric" value="${this._e(me.sen ?? "")}">${this._srcLine(a)}</span>
        <span><label><input type="checkbox" data-show="FO"${show.FO ? " checked" : ""}> FO</label> <label><input type="checkbox" data-show="CA"${show.CA ? " checked" : ""}> CA</label></span>
        <span><label>Over 75 in ${RC_MON[mm - 1]} (Reserve Run only, 22.G.2.d): <select data-o75="${this._e(this._m)}">${[["", "not set (CHECK)"], ["yes", "I was on reserve"], ["no", "not on reserve"]].map(([k, t]) => `<option value="${k}"${o75 === k ? " selected" : ""}>${t}</option>`).join("")}</select></label></span>
        <span class="k">last list ${this._e(a.last || "none yet")}${a.received ? ` (came in ${this._e(this._hst(a.received))} HST)` : ""}</span>
        <button class="g" data-refresh${this._busy ? " disabled" : ""}>&#8635; ${this._busy ? "Refreshing..." : "Refresh"}</button>
        <span class="k" data-checked>${this._note ? `<span style="color:var(--error-color,#c62828)">${this._e(this._note)}</span>` : a.checked ? `checked ${this._e(this._hst(a.checked))} HST` : ""}</span>
        <span class="mp"><span class="nv" data-m="-1">&#8249;</span><b>${RC_MON[mm - 1]} ${my}</b><span class="nv" data-m="1">&#8250;</span>${nmiss ? `<span class="chip MISSED">${nmiss} missed</span>` : ""}</span></div>
      ${this._needs(a, me)}
      <div class="k">Hark reads the daily HNL recall list from Flight Ops SharePoint and posts it here. Each award to a pilot junior to you is checked against your line as you held it that day (the schedule version in force then, not today's): open days, no blocked day, trip or vacation in the way (22.G.2.e first, 22.G.2.f/g after), FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h in 672 h, 117.23(c) FDP 60 h in 168 h and 190 h in 672 h, PWA 10.E.1.a 11 h domicile rest. Anything not on file makes it CHECK, never SHOULD HAVE BEEN YOU; so does an Over 75 row in a month you have not said whether you were on reserve.</div>
      ${rows || `<div class="day why">No recall lists on file for ${RC_MON[mm - 1]} ${my}.</div>`}
      <details style="margin-top:8px"><summary class="k">Paste a recall list (manual)</summary><textarea data-paste placeholder='{"date":"2026-11-04","rows":[{"kind":"recall","seat":"FO","pilot":"","sen":900,"pairing":"H3601"}]}'></textarea><button data-paste-go>Check this list</button></details>
    </ha-card>`;
    this._wire();
  }
  // 1.6.2: where the seniority # comes from, beside the box
  _srcLine(a) {
    const s = String(a.sen_source || "");
    const m = /^award (\d{4})-(\d{2})$/.exec(s);
    const t = s === "typed" ? "typed here" : m ? `from your ${RC_MON[+m[2] - 1]} ${m[1]} award` : s === "seniority list" ? "from the seniority list" : "";
    return t ? ` <span class="k">${this._e(t)}</span>` : "";
  }
  // 1.6.2: what keeps rows at CHECK with no CCR draft (seniority first, then the line)
  _needs(a, me) {
    const out = [];
    if (me.sen == null) out.push("Your seniority # is not on file: type it above (the number before your employee number on the award). Until then no row is judged against it and none gets a CCR draft or an alert.");
    if (a.missing_line) out.push(`Your FLICA schedule is not on file for the days of ${a.missing_line} row${a.missing_line > 1 ? "s" : ""}: they stay CHECK, with no CCR draft or alert, until the Watcher has read it.`);
    return out.map((t) => `<div class="hk bad">${this._e(t)}</div>`).join("");
  }
  _dayHtml(d, show, hark) {
    const vs = d.verdicts || [];
    const shown = vs.filter((v) => show[(v.seat || "FO").toUpperCase()]);
    const n = (k) => vs.filter((v) => v.verdict === k).length;
    const file = String(d.file || "");
    const tag = n("MISSED") ? `<span class="chip MISSED">${n("MISSED")} should have been you</span>` : "";
    const tag2 = n("POSSIBLE") ? `<span class="chip POSSIBLE">${n("POSSIBLE")} check</span>` : "";
    const quiet = !tag && !tag2 && file === "ok" ? `<span class="k">${vs.length ? "no miss" : "no rows"}</span>` : "";
    const seats = ["FO", "CA"].filter((k) => show[k]);
    const none = file === "not posted" || !file ? "Flight Ops did not post a list for this day."
      : file === "blank" ? "The posted list was empty."
      : !seats.length ? "Tick FO or CA above to see the awards."
      : `No ${seats.join(" or ")} Recall or Over 75 awards on this list.`;
    const body = shown.length ? shown.map((v) => this._row(v, hark)).join("") : `<div class="row why">${none}</div>`;
    return `<details class="day" data-day="${this._e(d.date)}"${this._isOpen(d) ? " open" : ""}><summary><b>${this._e(this._day(d.date))}</b> <span class="k">list ${this._e(file || "not posted")}</span> ${tag}${tag2}${quiet}</summary>${body}</details>`;
  }
  _harkLine(act) {
    const s = act.status, tid = act.task_id;
    let out = "";
    if (s === "filing") out = `<div class="hk">Sent to Hark ${this._e(this._hst(act.requested_at))} HST, waiting for the CCR number${tid ? ` (HOM task ${this._e(tid)})` : "; HOM has not made a task yet"}. To stop it, ${tid ? "complete the task as skipped in HOM, then Withdraw from Hark" : "Withdraw from Hark"}.</div>`;
    else if (s === "filed" && act.ccr) out = `<div class="hk">Filed: CCR ${this._e(act.ccr)}${act.filed_by ? ` by ${this._e(act.filed_by.charAt(0).toUpperCase() + act.filed_by.slice(1))}` : ""}${act.filed_at ? ` ${this._e(this._hst(act.filed_at))} HST` : ""}${act.filed_note ? `<div class="why">${this._e(act.filed_note)}</div>` : ""}</div>`;
    else if (["blocked", "cancelled"].includes(s)) out = `<div class="hk bad">Hark ${this._e(s)}${act.hark_at ? ` ${this._e(this._hst(act.hark_at))} HST` : ""}: ${this._e(act.hark_reason || "no reason given")}. ${tid ? `HOM task ${this._e(tid)} is not done; HOM makes one task per request, so it cannot be sent again. File it yourself.` : "You can send it again or file it yourself."}</div>`;
    else if (act.hark_reason) out = `<div class="hk bad">${this._e(act.hark_reason)}</div>`;
    if (act.hark_note) out += `<div class="hk bad">${this._e(act.hark_note)}</div>`;
    if (act.hark_alert) out += `<div class="hw">${this._e(act.hark_alert)}</div>`;
    return out;
  }
  // 1.4.6 review: the Hark button sends the approved narrative only; the box must hold exactly that
  _differs(id, txt) { return String(txt || "").trim() !== String(this._approved[id] || "").trim(); }
  _row(v, hark) {
    const act = v.act || {};
    const s = act.status;
    const live = RC_LIVE.includes(v.verdict) && s && s !== "superseded";
    const id = this._e(v.id);
    let ctl = "";
    if (live) {
      const txt = this._drafts[v.id] ?? act.narrative ?? "";
      this._approved[v.id] = act.narrative || "";
      const edit = ["confirmed", "approved", "blocked", "cancelled"].includes(s);
      const tid = act.task_id || "";
      const hl = RC_HARK.includes(s) && !!act.rid;  // Hark may still file it: warn, and gate the manual endings
      const canHark = hark && !tid && (s === "approved" || (["blocked", "cancelled"].includes(s) && act.approved_at));
      const differs = s !== "confirmed" && this._differs(v.id, txt);
      const pend = this._pending[v.id] && Date.now() - this._pending[v.id] < 15000 && s !== "filing";
      if (this._pending[v.id] && s === "filing") delete this._pending[v.id];
      const late = this._pending[v.id] && !pend && !act.hark_note ? `<div class="hk bad">The Watcher did not take the request. It only sends an approved narrative on a row that is still a miss; see its log.</div>` : "";
      const warn = hl ? `<div class="hw" data-warn="${id}">${tid ? `Hark still has HOM task ${this._e(tid)}. Complete it as skipped in HOM first, or Hark will file it too.` : "The request may still reach Hark: Withdraw from Hark, Not a miss and Mark filed take it back first."}</div>` : "";
      const gate = hl && tid ? `<label class="gate k"><input type="checkbox" data-cleared="${id}"> I completed HOM task ${this._e(tid)} as skipped</label>` : "";
      const g = gate ? ` data-gate="${id}" disabled` : "";
      const endings = `${s === "filing" || s === "blocked" ? `<button class="g" data-a="withdraw" data-id="${id}"${g}>Withdraw from Hark</button>` : ""}
          <button class="g" data-a="dismiss" data-id="${id}"${g}>Not a miss</button>
          <span>CCR # <input data-ccr="${id}" style="width:90px"></span><button class="g" data-a="filed" data-id="${id}"${g}>Mark filed</button>`;
      ctl = `<div><span class="st">${this._e(RC_STATUS[s] || s)}</span>${act.ccr && s !== "filed" ? ` <span class="k">CCR ${this._e(act.ccr)}</span>` : ""}</div>
        ${this._harkLine(act)}${late}
        ${s === "new" ? `<button class="r" data-a="confirm" data-id="${id}">Yes, I missed this</button><button class="g" data-a="dismiss" data-id="${id}">Not a miss</button>` : ""}
        ${edit ? `<div class="k">${hark ? "CCR narrative: edit until it is right, then approve. Nothing is filed until you approve it. Then Have Hark file this CCR sends the approved text to Hark, who files it on hal.alpa.org and sends back the CCR number; or file it yourself." : "CCR narrative: edit until it is right, then approve. Nothing is filed for you. After you approve it, File it myself copies the text and opens hal.alpa.org."}</div><textarea data-n="${id}">${this._e(txt)}</textarea>
          <button data-a="approve" data-id="${id}" data-approve="${id}" data-st="${this._e(s)}">${differs ? "Re-approve edited narrative" : "Approve narrative"}</button>
          ${canHark ? `<button class="h" data-hark="${id}"${pend || differs ? " disabled" : ""}>${pend ? "Sending to Hark..." : "Have Hark file this CCR"}</button><div class="dn" data-diff="${id}"${differs ? "" : " hidden"}>Re-approve first: the box differs from what you approved.</div>` : ""}
          ${warn}
          ${s !== "confirmed" ? `<button class="r" data-file="${id}">File it myself on hal.alpa.org</button>` : ""}
          ${gate}${endings}` : ""}
        ${s === "filing" ? `<details><summary class="k">Narrative sent to Hark</summary><pre class="n">${this._e(act.narrative)}</pre></details>
          ${warn}
          <button class="r" data-file="${id}">File it myself on hal.alpa.org</button>
          ${gate}${endings}` : ""}
        ${["dismissed", "filed"].includes(s) ? `<button class="g" data-a="reopen" data-id="${id}">Reopen</button>` : ""}`;
    } else if (s === "superseded") {
      const hw = act.hark_alert || (RC_HARK.includes(act.was) && act.rid ? `Hark still has ${act.task_id ? `HOM task ${act.task_id}` : "the request"} for this CCR: complete it as skipped in HOM, or Hark files a CCR for a row that is no longer a miss.` : "");
      ctl = `<div class="k"><span class="st">superseded</span> CCR draft closed, no longer a miss (was ${this._e(RC_STATUS[act.was] || act.was || "new")}${act.ccr ? `, CCR ${this._e(act.ccr)}` : ""}). It comes back if the row turns into a miss again.</div>${hw ? `<div class="hw">${this._e(hw)}</div>` : ""}`;
    }
    if (v.missing && !live) ctl += `<div class="dn">No CCR draft and no alert until ${v.missing === "seniority" ? "your seniority # is on file (type it above)" : "your FLICA schedule for these days is on file"}.</div>`;
    const lab = { MISSED: "SHOULD HAVE BEEN YOU", POSSIBLE: "CHECK", NO: "NO MISS" }[v.verdict] || v.verdict;
    return `<div class="row v${this._e(v.verdict)}"><span class="chip ${this._e(v.verdict)}">${this._e(lab)}</span><b>${this._e(this._kind(v))} ${this._e(v.pairing)}</b> ${this._e(v.seat)} to #${this._e(v.sen)} ${this._e(v.pilot)}
      <div class="why">${(v.why || []).map((w) => this._e(w)).join(" · ")}${(v.refs || []).length ? ` <i>(${(v.refs || []).map((r) => this._e(r)).join(", ")})</i>` : ""}</div>${ctl}</div>`;
  }
  _narrative(id) {
    const t = this.shadowRoot.querySelector(`textarea[data-n="${CSS.escape(id)}"]`);
    if (t) return t.value;
    const st = this._h.states[this._c.entity];
    for (const d of this._days(st)) for (const v of d.verdicts || []) if (v.id === id) return (v.act || {}).narrative || "";
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
      const d = this._days(st).find((x) => x.date === el.dataset.day);
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
    // 1.6.2: a whole number 1..99999 or blank (forget the typed one); nothing else is sent, and no seat (no control)
    r.querySelectorAll("[data-me]").forEach((el) => el.onchange = () => {
      const raw = String(el.value || "").trim();
      const n = Number(raw);
      if (raw && !(Number.isInteger(n) && n >= 1 && n <= 99999)) {
        this._note = "Seniority # is a whole number from 1 to 99999. Nothing was sent.";
        const k = r.querySelector("[data-checked]");
        if (k) k.innerHTML = `<span style="color:var(--error-color,#c62828)">${this._e(this._note)}</span>`;
        this._note = "";
        return;
      }
      this._send("recall/act", { me: { sen: raw ? n : null } });
      el.blur();
    });
    // 1.4.6 review: Over 75 (PWA 22.G.2.d) is answered per month; not set leaves an Over 75 miss at CHECK
    r.querySelectorAll("select[data-o75]").forEach((el) => el.onchange = () => {
      const v = { yes: true, no: false }[el.value];
      this._send("recall/act", { me: { o75_months: { [el.dataset.o75]: v === undefined ? null : v } } });
      el.blur();
    });
    r.querySelectorAll("textarea[data-n]").forEach((t) => t.oninput = () => {
      const id = t.dataset.n;
      this._drafts[id] = t.value;
      const differs = this._differs(id, t.value);
      const q = (sel) => r.querySelector(`${sel}="${CSS.escape(id)}"]`);
      const h = q("button[data-hark"), dn = q("[data-diff"), ap = q("button[data-approve");
      if (h && !(this._pending[id] && Date.now() - this._pending[id] < 15000)) h.disabled = differs;
      if (dn) dn.hidden = !differs;
      if (ap && ap.dataset.st !== "confirmed") ap.textContent = differs ? "Re-approve edited narrative" : "Approve narrative";
    });
    r.querySelectorAll("input[data-cleared]").forEach((c) => c.onchange = () => {
      r.querySelectorAll(`button[data-gate="${CSS.escape(c.dataset.cleared)}"]`).forEach((b) => { b.disabled = !c.checked; });
    });
    r.querySelectorAll("button[data-a]").forEach((b) => b.onclick = () => {
      const id = b.dataset.id, msg = { id, action: b.dataset.a };
      const t = r.querySelector(`textarea[data-n="${CSS.escape(id)}"]`);
      if (t && b.dataset.a === "approve") msg.narrative = t.value;
      const c = r.querySelector(`input[data-ccr="${CSS.escape(id)}"]`);
      if (c && b.dataset.a === "filed") msg.ccr = c.value;
      const ok = r.querySelector(`input[data-cleared="${CSS.escape(id)}"]`);
      if (ok && ["withdraw", "dismiss", "filed"].includes(b.dataset.a)) msg.hom_cleared = ok.checked;
      this._send("recall/act", msg);
      if (b.dataset.a === "approve") delete this._drafts[id];
      this._sig = null;
    });
    // 1.4.6: the Watcher writes the request for Hark only for an approved narrative on a row that is still a miss
    r.querySelectorAll("button[data-hark]").forEach((b) => b.onclick = () => {
      const id = b.dataset.hark;
      const t = r.querySelector(`textarea[data-n="${CSS.escape(id)}"]`);
      const narrative = t ? t.value : this._approved[id] || "";
      if (this._differs(id, narrative)) return;  // re-approve first
      this._pending[id] = Date.now();
      this._send("recall/act", { id, action: "file_request", narrative });
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

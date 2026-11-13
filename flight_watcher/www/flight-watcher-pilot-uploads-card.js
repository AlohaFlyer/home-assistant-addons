// Flight Watcher pilot uploads card (1.7.2, FW-0066, Ryan Nov 11: "either I or James can upload them; the pairings and
// awards are the same doc for each of us"). The pilot portal's Settings tab: a pilot uploads the month's pairings
// package or award PDF (never the seniority list or the contact list), for this month or one of the next two (HST).
// The file is read in the browser (FileReader, no blob: URL: the portal's CSP stays as it is), its sha256 taken with
// WebCrypto, and its base64 sent in parts of FW_PUP_CHUNK characters, one upload/pdf command each
// ({uid, kind, month, size, sha, part, parts, data}: contract 1 revision 3, roles.SHAPE_CMDS), one part every
// FW_PUP_GAP_MS so the portal's 30 commands a minute leave room for the pilot's other presses. His own Watcher puts
// the parts together and checks the whole file (a PDF, its text, that month's package or award with his own line)
// before anything is stored: used at once when nothing is on file for that month, else held for the admin.
// Data: sensor.flight_watcher_pilot_uploads (synthesized by the Watcher for the portal): what is on file for each month
// and from whom (you, the admin or another pilot; never a name), his uploads, the answers and his limits.
// FW_PORTAL: on in the portal's copy (portal.portal_card); the card is the portal's (no Home Assistant dashboard has it).
const FW_PORTAL = false;
const FW_PUP_ENTITY = "sensor.flight_watcher_pilot_uploads";
const FW_PUP_MAX = 4 * 1024 * 1024;  // roles.PILOT_UPLOAD_LIMITS file_bytes (the sensor's limits win when given)
const FW_PUP_CHUNK = 60000;  // chunk_chars: one command's base64
const FW_PUP_GAP_MS = 2500;  // one part every 2.5 s: 24 a minute of the portal's 30
const FW_PUP_RETRY_MS = 10000;  // a part the portal refused (too many commands a minute) is sent again after this
const FW_PUP_TRIES = 4;
// 1.7.2 (review): with every part sent and no final answer this long after the last one (the Watcher drops an upload
// with no part for stale_s, then a check takes up to 30 s), the card stops waiting: its Watcher restarted, or a part
// was lost on the way, and Upload is offered again
const FW_PUP_ANSWER_S = 60;  // beyond stale_s
const fwPupWaitMs = (lim) => ((Number.isFinite(lim && lim.stale_s) ? lim.stale_s : 120) + FW_PUP_ANSWER_S) * 1000;
const FW_PUP_KINDS = [["pairings", "Pairings package"], ["award", "Award"]];
const FW_PUP_WHAT = { pairings: "pairings package", award: "award" };
const FW_PUP_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const fwPupPad = (n) => String(n).padStart(2, "0");
// this HST month and the next two (Hawaii has no DST)
const fwPupMonths = (now) => {
  const h = new Date(now - 10 * 3600e3);
  const out = [];
  for (let k = 0; k < 3; k++) {
    const t = h.getUTCFullYear() * 12 + h.getUTCMonth() + k;
    out.push(`${Math.floor(t / 12)}-${fwPupPad((t % 12) + 1)}`);
  }
  return out;
};
const fwPupName = (m) => (/^\d{4}-(0[1-9]|1[0-2])$/.test(m || "") ? `${FW_PUP_MON[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}` : "");
const fwPupSize = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const fwPupHst = (iso) => {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  const h = new Date(t - 10 * 3600e3);
  return `${FW_PUP_MON[h.getUTCMonth()].slice(0, 3)} ${h.getUTCDate()} ${fwPupPad(h.getUTCHours())}:${fwPupPad(h.getUTCMinutes())}`;
};
const FW_PUP_STATE = { live: "in use", pending: "waiting for the admin", approved: "approved by the admin, in use",
  rejected: "not used (the admin kept the file on file)", removed: "removed by the admin", replaced: "replaced by a later file",
  superseded: "replaced by your later upload", same: "the same as the file on file" };

class FlightWatcherPilotUploadsCard extends HTMLElement {
  setConfig(c) { this._c = { entity: FW_PUP_ENTITY, ...c }; this._send = null; this._sig = null; this._note = null; }
  getCardSize() { return 5; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }
  set hass(h) {
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(h && h.themes && typeof h.themes.darkMode === "boolean" ? h.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
    this._h = h;
    const st = h.states[this._c.entity];
    const sig = st ? `${st.last_updated}|${JSON.stringify(st.attributes || {})}` : "none";
    if (!this._root) this._build();
    if (sig !== this._sig) { this._sig = sig; this._paint(); }
  }
  _a() { const st = this._h && this._h.states[this._c.entity]; return (st && st.attributes) || null; }
  _lim() { const a = this._a(); return (a && a.limits) || {}; }
  _build() {
    this._root = this.shadowRoot || this.attachShadow({ mode: "open" });
    this._root.innerHTML = `<style>${this._css()}</style><ha-card><div class="ttl">Pairings package and award</div>
      <div class="u">Upload the month's pairings package or award PDF when it posts. Your Watcher and the admin's read the
      same files, so one upload serves both. Only these two: never the seniority list or the contact list.</div>
      <div data-files></div>
      <div class="form"><div class="grid">
        <label>What <select data-kind>${FW_PUP_KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
        <label>Month <select data-month></select></label>
        <label class="wide">PDF <input type="file" data-pdf accept="application/pdf,.pdf"></label></div>
        <div class="act"><button data-up>Upload</button><span class="u" data-prog aria-live="polite"></span></div>
        <div class="msg" data-msg role="status" aria-live="polite" aria-atomic="true"></div>
        <div class="u" data-lim></div></div>
      <div data-mine></div></ha-card>`;
    this._root.querySelector("[data-up]").addEventListener("click", () => this._upload());
  }
  _css() {
    return `:host{--ok:#2e7d32;--err:#c62828}:host([dark]){--ok:#81c784;--err:#ef9a9a}
      ha-card{display:block;padding:12px 14px;font-size:14px;overflow-wrap:anywhere;color:var(--primary-text-color)}
      .ttl{font-size:16px;font-weight:600;margin-bottom:6px}.u{color:var(--secondary-text-color);font-size:13px}
      .form{border:1px solid var(--divider-color,#ccc);border-radius:8px;padding:10px;margin:10px 0}
      .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0 12px}.wide{grid-column:1/-1}
      label{display:block;margin:6px 0;font-weight:600;font-size:13px;min-width:0}
      select,input{display:block;width:100%;max-width:100%;box-sizing:border-box;margin-top:2px;font:14px sans-serif;padding:6px;
        border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color)}
      button{cursor:pointer;border:0;border-radius:6px;padding:8px 16px;font:600 14px sans-serif;background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff)}
      button:disabled{opacity:.5;cursor:default}
      .act{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}.msg{margin-top:6px}
      .ok{color:var(--ok)}.err{color:var(--err)}
      .m{border-top:1px solid var(--divider-color,#ccc);padding:6px 0}.m b{display:block}
      .lbl{font-weight:600;margin:8px 0 2px}
      @media (max-width:700px){select,input{font-size:16px}button{min-height:44px}}`;
  }
  _paint() {
    const a = this._a(), r = this._root, e = (s) => this._e(s);
    if (!r) return;
    const files = r.querySelector("[data-files]"), mine = r.querySelector("[data-mine]"), lim = r.querySelector("[data-lim]");
    const sel = r.querySelector("[data-month]");
    const months = (a && Array.isArray(a.months) && a.months.length ? a.months.map((m) => m.month) : fwPupMonths(Date.now())).filter(fwPupName);
    const keep = sel.value;
    sel.innerHTML = months.map((m) => `<option value="${e(m)}">${e(fwPupName(m))}</option>`).join("");
    if (months.includes(keep)) sel.value = keep;
    else if (months[1]) sel.value = months[1];  // the coming bid month by default
    if (!a) {
      files.innerHTML = `<div class="u">Waiting for your Watcher's list of files.</div>`;
      lim.textContent = "";
      mine.innerHTML = "";
      return;
    }
    const by = (x) => (x.by === "you" ? "from you" : x.by === "the admin" ? "from the admin" : x.by ? "from another pilot" : "");
    files.innerHTML = (a.months || []).filter((m) => fwPupName(m.month)).map((m) => {
      const one = (k) => {
        const x = m[k] || {};
        const on = x.on_file ? `<span class="ok">on file</span> ${e(by(x))}` : "not on file yet";
        return `${FW_PUP_KINDS.find((q) => q[0] === k)[1]}: ${on}${x.pending ? `; <span class="err">your copy waits for the admin</span>` : ""}`;
      };
      return `<div class="m"><b>${e(fwPupName(m.month))}</b><span class="u">${one("pairings")}<br>${one("award")}</span></div>`;
    }).join("");
    const l = this._lim(), max = l.file_bytes || FW_PUP_MAX;
    lim.textContent = `Up to ${Math.round(max / 1048576)} MB a file and ${l.per_day || 4} uploads a day` +
      (Number.isFinite(l.left_today) ? ` (${l.left_today} left today)` : "") +
      ". One upload at a time: keep this page open while it sends, about 1 min for each MB.";
    const rows = (a.mine || []).filter((x) => x && fwPupName(x.month)).slice(0, 5);
    mine.innerHTML = rows.length ? `<div class="lbl">Your uploads</div>` + rows.map((x) =>
      `<div class="m">${e(fwPupName(x.month))} ${e(FW_PUP_WHAT[x.kind] || x.kind)}: ${e(FW_PUP_STATE[x.state] || x.state)}<div class="u">${e(fwPupSize(+x.size || 0))}, uploaded ${e(fwPupHst(x.at))} HST</div></div>`).join("") : "";
    this._status();
  }
  _answer(uid) {
    const a = this._a();
    return ((a && a.answers) || []).find((x) => x && x.uid === uid) || null;
  }
  _say(text, ok) {
    const m = this._root && this._root.querySelector("[data-msg]");
    if (m) m.innerHTML = text ? `<span class="${ok ? "ok" : "err"}">${this._e(text)}</span>` : "";
  }
  _status() {
    const s = this._send, prog = this._root && this._root.querySelector("[data-prog]"), btn = this._root && this._root.querySelector("[data-up]");
    if (btn) btn.disabled = !!(s && !s.done);
    if (!s) { if (this._note) this._say(this._note[0], this._note[1]); return; }
    const ans = this._answer(s.uid);
    const fin = !!(ans && ["live", "pending", "same", "error"].includes(ans.state));
    if (!s.done && !fin && s.lastAt && Date.now() - s.lastAt > fwPupWaitMs(this._lim())) {
      s.done = true;
      s.error = "No answer from your Watcher: it may have restarted, or a part was lost on the way. Nothing is used " +
        "until it answers; upload the file again.";
    }
    if (s.done || fin) {
      s.done = true;
      if (s.timer) { clearTimeout(s.timer); s.timer = null; }
      if (btn) btn.disabled = false;
      if (prog) prog.textContent = "";
      if (fin) this._say(ans.message, !!ans.ok);  // a final answer wins, even one that came after the card stopped waiting
      else if (s.error) this._say(s.error, false);
      else this._say("All parts sent: your Watcher is checking the file (up to a minute).", true);
      return;
    }
    if (prog) {
      const left = Math.max(0, s.parts - s.sent) * FW_PUP_GAP_MS / 1000;
      prog.textContent = s.sent < s.parts ? `Sending part ${s.sent + 1} of ${s.parts}${left >= 60 ? ` (about ${Math.ceil(left / 60)} min left)` : ""}` : "Checking the file...";
    }
  }
  _uid() {
    const abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", b = new Uint8Array(24);
    crypto.getRandomValues(b);
    return Array.from(b, (x) => abc[x % abc.length]).join("");
  }
  _read(file) {
    return new Promise((ok, bad) => {
      const fr = new FileReader();
      fr.onload = () => ok(new Uint8Array(fr.result));
      fr.onerror = () => bad(new Error("the file could not be read"));
      fr.readAsArrayBuffer(file);
    });
  }
  _b64(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  async _upload() {
    const r = this._root, file = r.querySelector("[data-pdf]").files[0];
    const kind = r.querySelector("[data-kind]").value, month = r.querySelector("[data-month]").value;
    const l = this._lim(), max = l.file_bytes || FW_PUP_MAX;
    this._note = null;
    if (this._send && !this._send.done) return;
    if (!file) return this._say("Pick the PDF first.", false);
    if (!FW_PUP_WHAT[kind] || !fwPupName(month)) return this._say("Pick what it is and its month.", false);
    if (file.size > max) return this._say(`That file is ${fwPupSize(file.size)}: up to ${Math.round(max / 1048576)} MB.`, false);
    if (Number.isFinite(l.left_today) && l.left_today <= 0) return this._say("No uploads left today: try again tomorrow.", false);
    if (!(window.crypto && crypto.subtle && crypto.getRandomValues)) return this._say("This browser cannot check the file before it sends it: open the portal at its https address.", false);
    let bytes;
    try { bytes = await this._read(file); } catch (err) { return this._say(String(err.message || err), false); }
    const head = String.fromCharCode.apply(null, bytes.subarray(0, 5));
    if (head !== "%PDF-") return this._say("That file is not a PDF.", false);
    const sha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (x) => x.toString(16).padStart(2, "0")).join("");
    const b64 = this._b64(bytes), parts = Math.max(1, Math.ceil(b64.length / FW_PUP_CHUNK));
    const s = this._send = { uid: this._uid(), kind, month, parts, sent: 0, done: false, error: "" };
    this._say(`Sending the ${fwPupName(month)} ${FW_PUP_WHAT[kind]} (${fwPupSize(file.size)}).`, true);
    this._status();
    for (let p = 1; p <= parts && this._send === s; p++) {
      const data = b64.slice((p - 1) * FW_PUP_CHUNK, p * FW_PUP_CHUNK);
      const payload = JSON.stringify({ uid: s.uid, kind, month, size: file.size, sha, part: p, parts, data });
      let sent = false;
      for (let t = 0; t < FW_PUP_TRIES && !sent; t++) {
        try { await this._h.callService("mqtt", "publish", { topic: "flight_watcher/upload/pdf", payload }); sent = true; }
        catch (err) { await new Promise((ok) => setTimeout(ok, FW_PUP_RETRY_MS)); }
      }
      if (!sent) { s.error = `Not sent: part ${p} of ${parts} did not go through. Try again in a few minutes.`; s.done = true; break; }
      s.sent = p;
      this._status();
      if (p < parts) await new Promise((ok) => setTimeout(ok, FW_PUP_GAP_MS));
    }
    if (!s.done && this._send === s) {
      s.lastAt = Date.now();
      s.timer = setTimeout(() => { s.timer = null; this._status(); }, fwPupWaitMs(this._lim()) + 1000);
    }
    this._status();
  }
}
customElements.define("flight-watcher-pilot-uploads-card", FlightWatcherPilotUploadsCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-uploads-card", name: "Flight Watcher pilot uploads", description: "A pilot uploads the pairings package or award from his portal" });

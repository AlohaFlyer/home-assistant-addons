/* Flight Watcher: uploads card (1.4.5, Ryan Nov 6). Upload the monthly award, the pilot pairings package and the
   pilot seniority list from the dashboard (Settings tab, under Credentials, above Tickets) and see what is on file,
   instead of the app's Web UI. Home Assistant admin only: a user who is not an admin sees a note and the card makes
   no call at all. The card reaches the app's Web UI (an HA ingress panel) the way Home Assistant's own app panels
   do: the app's ingress address from supervisor/api /addons/<slug>/info, an ingress session from /ingress/session set
   as the ingress_session cookie (path /api/hassio_ingress/, SameSite=Strict, Secure on https), re-validated with
   /ingress/validate_session before it can lapse (the Supervisor keeps a session 15 min from its last validation),
   then GET api/uploads and POST api/upload (the Web UI's own form fields: kind, month, list_date, pdf). The files
   stay on this Home Assistant; nothing is sent to FLICA. FW-0057: a pairings package the crew index still needs
   (api/uploads 'wanted': this bid month's or the previous one's) is asked for above the files. Card options: slug
   (the app's slug), title. */
const FW_UP_SLUG = ["43b22650", "flight", "watcher"].join("_");  // in parts: a second pilot's copy keeps the one app's slug
const FW_UP_KINDS = [["award", "Monthly award"], ["pairings", "Pairings package"], ["seniority", "Pilot seniority list"]];
const FW_UP_LABEL = { award: "Award", pairings: "Pairings package", seniority: "Seniority list", other: "Other file" };
const FW_UP_REFRESH_MS = 5 * 60 * 1000;
// web.INGRESS_MAX: the Supervisor's ingress proxy refuses a body over 16 MiB (HTTP 413) after it has all arrived, so
// a larger PDF is refused here, before it is sent; 64 KiB is left for the form around it. api/uploads gives the
// app's own figure and the card takes the lower of the two.
const FW_UP_MAX = 16 * 1024 * 1024 - 64 * 1024;
const FW_UP_SHOW = 6;  // files listed before the rest fold away
const FW_UP_URL_RE = /^\/api\/hassio_ingress\/[A-Za-z0-9_-]+\/?$/;
const FW_UP_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fwUpPad = (n) => String(n).padStart(2, "0");
// next month in HST (Hawaii has no DST): the award and the package are posted for the coming bid period
const fwUpNextMonth = (now) => {
  const h = new Date(now - 10 * 3600e3);
  const m = h.getUTCMonth() + 1;
  return m === 12 ? `${h.getUTCFullYear() + 1}-01` : `${h.getUTCFullYear()}-${fwUpPad(m + 1)}`;
};
// FW-0057: a bid month k months on ('2026-10', 1 -> '2026-11')
const fwUpAdd = (ym, k) => {
  const n = +ym.slice(0, 4) * 12 + (+ym.slice(5) - 1) + k;
  return `${Math.floor(n / 12)}-${fwUpPad((n % 12) + 1)}`;
};
const fwUpMonth = (ym) => (/^\d{4}-\d{2}$/.test(String(ym || "")) && +ym.slice(5) >= 1 && +ym.slice(5) <= 12
  ? `${FW_UP_MON[+ym.slice(5) - 1]} ${ym.slice(0, 4)}` : "");
const fwUpHst = (iso) => {
  const t = Date.parse(String(iso || ""));
  if (isNaN(t)) return "";
  const h = new Date(t - 10 * 3600e3);
  return `${FW_UP_MON[h.getUTCMonth()]} ${h.getUTCDate()} ${fwUpPad(h.getUTCHours())}:${fwUpPad(h.getUTCMinutes())}`;
};
const fwUpSize = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((+n || 0) / 1024))} KB`);
const fwUpHttpErr = (status) => {
  const why = {
    401: "Home Assistant did not accept the app session (HTTP 401). Reload the page and try again.",
    403: "The app refused the request (HTTP 403).",
    404: "The app does not know this request (HTTP 404): is it updated to 1.4.5 or later?",
    413: "Home Assistant's app proxy refused the file as too large (HTTP 413).",
    502: "The Flight Watcher app did not answer (HTTP 502): is it running?",
    503: "The Flight Watcher app did not answer (HTTP 503): is it running?",
    504: "The Flight Watcher app took too long to answer (HTTP 504).",
  }[status] || `The app answered HTTP ${status}.`;
  const err = new Error(why);
  err.status = status;
  return err;
};

class FlightWatcherUploadsCard extends HTMLElement {
  setConfig(c) {
    const slug = String((c && c.slug) || FW_UP_SLUG);
    if (!/^[a-z0-9_]{1,64}$/.test(slug)) throw new Error("slug: lowercase letters, digits and _ only");
    this._c = { ...c, slug };
    this._mode = null; this._base = null; this._sess = null; this._sessAt = 0; this._timer = null;
    this._data = null; this._err = ""; this._loading = false; this._busy = false; this._msg = null;
  }
  getCardSize() { return 6; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }
  _admin() { return !!(this._h && this._h.user && this._h.user.is_admin === true); }
  set hass(h) {
    this._h = h;
    const mode = this._admin() ? "admin" : "user";
    if (mode === this._mode) return;
    this._mode = mode;
    this._build();
    if (mode === "admin") this._load();
  }
  connectedCallback() {
    if (this._mode === "admin" && !this._loading && (this._data || this._err)) this._load();  // back on the view: what is on file now
  }
  disconnectedCallback() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  }
  _root() { return this.shadowRoot || this.attachShadow({ mode: "open" }); }
  _q(sel) { return this.shadowRoot ? this.shadowRoot.querySelector(sel) : null; }
  _build() {
    const root = this._root(), e = (s) => this._e(s);
    const title = this._c && this._c.title ? `<div class="ttl">${e(this._c.title)}</div>` : "";
    if (this._mode !== "admin") {  // no supervisor call, no cookie, no request for a user who is not an admin
      root.innerHTML = `<style>${this._css()}</style><ha-card>${title}<div class="u">Uploads are for the Home Assistant admin.</div></ha-card>`;
      return;
    }
    root.innerHTML = `<style>${this._css()}</style><ha-card>${title}
      <div class="u">The award and the pilot pairings package for each bid period when they post, and the pilot seniority
      list when a new one comes out. They stay on this Home Assistant (never in git); the Watcher reads them for your
      starting schedule, trip details and other pilots' dates of hire. Nothing is sent to FLICA.</div>
      ${this._formHtml()}
      <div class="hd"><b>On file</b><button class="g" data-reload>Refresh</button></div>
      <div data-list>${this._listHtml(null)}</div><div data-sen></div></ha-card>`;
    const kind = this._q("[data-kind]");
    if (kind) kind.addEventListener("change", () => this._kind());
    const up = this._q("[data-up]");
    if (up) up.addEventListener("click", () => this._upload());
    const rl = this._q("[data-reload]");
    if (rl) rl.addEventListener("click", () => this._load());
  }
  _css() {
    return `ha-card{padding:12px 14px;font-size:13px;overflow-wrap:anywhere}
      .ttl{font-size:16px;font-weight:600;margin-bottom:6px}.u{color:var(--secondary-text-color);font-size:12px}
      .form{border:1px solid var(--divider-color,#ccc);border-radius:8px;padding:10px;margin:8px 0}
      .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0 12px}
      .form label{display:block;margin:6px 0;font-weight:600;font-size:12px;min-width:0}
      .form select,.form input{display:block;width:100%;max-width:100%;box-sizing:border-box;margin-top:2px;font:13px sans-serif;padding:6px;
        border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color)}
      .form input[type=file]{padding:4px}.form .u{font-weight:400}
      button{cursor:pointer;border:0;border-radius:6px;padding:8px 16px;font:600 13px sans-serif;background:var(--primary-color);color:var(--text-primary-color,#fff)}
      button.g{background:#757575;padding:4px 10px;font-size:12px}button:disabled{opacity:.5;cursor:default}
      .act{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}
      .msg{margin-top:6px}.ok{color:#2e7d32}.err{color:var(--error-color,#c62828)}
      .hd{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:10px 0 2px}
      .f{border-top:1px solid var(--divider-color,#ccc);padding:5px 0}
      .w{border-left:3px solid var(--warning-color,#f57c00);padding:4px 8px;margin:6px 0}
      details summary{cursor:pointer;color:var(--secondary-text-color);font-size:12px;padding:4px 0}
      .sen{border-top:1px solid var(--divider-color,#ccc);margin-top:6px;padding-top:6px}.lbl{font-weight:600;margin-bottom:2px}
      [hidden]{display:none!important}`;
  }
  _formHtml() {
    const opts = FW_UP_KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    return `<div class="form"><div class="grid">
      <label>What <select data-kind>${opts}</select></label>
      <label data-ml>Bid period <input type="month" data-month value="${this._e(fwUpNextMonth(Date.now()))}"></label>
      <label data-dl hidden>List date <span class="u">(optional, when the PDF does not print one)</span><input type="date" data-date></label>
      <label>PDF <input type="file" data-pdf accept="application/pdf,.pdf"></label></div>
      <div class="act"><button data-up>Upload</button><span class="u" data-prog aria-live="polite"></span></div>
      <div class="msg" data-msg role="status" aria-live="polite" aria-atomic="true"></div></div>`;
  }
  _kind() {  // the seniority list has no bid period; it takes an optional list date instead
    const sen = (this._q("[data-kind]") || {}).value === "seniority";
    const ml = this._q("[data-ml]"), dl = this._q("[data-dl]");
    if (ml) ml.hidden = sen;
    if (dl) dl.hidden = !sen;
  }
  _listHtml(d) {
    const e = (s) => this._e(s);
    if (this._err) return `<div class="err">${e(this._err)}</div>`;
    if (!d) return `<div class="u">Loading...</div>`;
    const files = Array.isArray(d.files) ? d.files.slice() : [];
    const want = this._wantHtml(d);
    if (!files.length) return want + `<div class="u">Nothing uploaded yet.</div>`;
    const order = { award: 0, pairings: 1, seniority: 2 };
    const key = (f) => (f.kind === "award" || f.kind === "pairings" ? `1${f.month}` : `0${f.day || ""}`);
    files.sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : (order[a.kind] ?? 3) - (order[b.kind] ?? 3)));
    const row = (f) => {
      const what = FW_UP_LABEL[f.kind] || FW_UP_LABEL.other;
      const per = f.kind === "award" || f.kind === "pairings" ? fwUpMonth(f.month) || f.month : f.kind === "other" ? f.name : "";
      const read = f.has_text ? `<span class="ok">read</span>` : `<span class="err">not read: no text copy</span>`;
      return `<div class="f"><div><b>${e(what)}</b>${per ? ` ${e(per)}` : ""}</div>
        <div class="u">${e(fwUpSize(f.size))} · uploaded ${e(fwUpHst(f.uploaded_at) || "?")} HST · ${read}</div></div>`;
    };
    const top = files.slice(0, FW_UP_SHOW).map(row).join(""), rest = files.slice(FW_UP_SHOW);
    return want + top + (rest.length ? `<details><summary>${rest.length} older</summary>${rest.map(row).join("")}</details>` : "");
  }
  _wantHtml(d) {  // FW-0057: the pairings packages the crew index still needs (api/uploads 'wanted'), oldest first
    const e = (s) => this._e(s);
    const w = (Array.isArray(d && d.wanted) ? d.wanted : []).filter((x) => x && fwUpMonth(x.month));
    return w.map((x) => {
      const m = fwUpMonth(x.month);
      const why = x.why === "previous"
        ? `Trips other pilots started in ${m} that run into ${fwUpMonth(fwUpAdd(x.month, 1))} reach the crew index only from pilot lookups until it is on file.`
        : `The trip details and the crew index for ${m} need it.`;
      return `<div class="w"><b>Wanted:</b> the ${e(m)} pairings package<div class="u">${e(why)}</div></div>`;
    }).join("");
  }
  _senHtml(s) {
    const e = (x) => this._e(x);
    const head = `<div class="lbl">Dates of hire (pay lines under other pilots' months)</div>`;
    if (!s) return `<div class="sen">${head}<div class="u">None on file yet: upload the pilot seniority list, or an award whose packet lists the dates of hire.</div></div>`;
    const src = String(s.source || "list");
    const from = src === "list" ? "the pilot seniority list" : /^award \d{4}-\d{2}$/.test(src) ? `the ${fwUpMonth(src.slice(6))} award` : src;
    const parts = [`<b>${e(s.pilots)} pilots</b> from ${e(from)}`,
      s.list_date ? `list date ${e(s.list_date)}` : s.as_of ? `as of ${e(s.as_of)}` : "",
      s.uploaded_at ? `uploaded ${e(fwUpHst(s.uploaded_at))} HST` : "",
      s.carried ? `${e(s.carried)} more kept from the seniority list${s.base && s.base.as_of ? ` of ${e(s.base.as_of)}` : ""}` : "",
      s.rejects ? `${e(s.rejects)} lines not read` : ""].filter(Boolean);
    return `<div class="sen">${head}<div>${parts.join(" · ")}</div></div>`;
  }
  _render() {
    const list = this._q("[data-list]"), sen = this._q("[data-sen]");
    if (list) list.innerHTML = this._listHtml(this._data);
    if (sen) sen.innerHTML = this._data && !this._err ? this._senHtml(this._data.seniority) + (this._data.version ? `<div class="u">Flight Watcher ${this._e(this._data.version)}</div>` : "") : "";
  }
  _why(err) {
    if (err && err.message) return String(err.message);
    if (err && err.code) return `Home Assistant: ${err.code}`;
    return String(err || "failed");
  }
  // ---- ingress: the app's address and a session cookie, as Home Assistant's own app panels set them
  async _ingress() {
    if (!this._admin()) throw new Error("Uploads are for the Home Assistant admin.");
    if (!this._base) {
      const info = await this._h.callWS({ type: "supervisor/api", endpoint: `/addons/${this._c.slug}/info`, method: "get" });
      const u = String((info && (info.ingress_url || info.ingress_entry)) || "");
      if (!FW_UP_URL_RE.test(u)) throw new Error(info && info.ingress === false ? "The app has no Web UI to upload to." : "The app's Web UI address was not found.");
      if (info.state && info.state !== "started") throw new Error(`The Flight Watcher app is not running (${info.state}).`);
      this._base = u.endsWith("/") ? u : `${u}/`;
    }
    await this._session(false);
    return this._base;
  }
  async _session(force) {
    const now = Date.now();
    if (this._sess && !force && now - this._sessAt < FW_UP_REFRESH_MS) return;
    if (this._sess) {
      try {
        await this._h.callWS({ type: "supervisor/api", endpoint: "/ingress/validate_session", method: "post", data: { session: this._sess } });
        this._sessAt = now;
        this._cookie();
        return;
      } catch (err) { this._sess = null; }  // lapsed: a new one below
    }
    const r = await this._h.callWS({ type: "supervisor/api", endpoint: "/ingress/session", method: "post" });
    const s = String((r && r.session) || "");
    if (!/^[A-Za-z0-9]{16,256}$/.test(s)) throw new Error("Home Assistant gave no app session.");
    this._sess = s;
    this._sessAt = now;
    this._cookie();
    this._keepAlive();
  }
  _cookie() {
    const secure = typeof location !== "undefined" && location.protocol === "https:" ? ";Secure" : "";
    document.cookie = `ingress_session=${this._sess};path=/api/hassio_ingress/;SameSite=Strict${secure}`;
  }
  _keepAlive() {  // while the card is on screen, re-validate before the Supervisor's 15 min lapse
    if (this._timer || !this.isConnected) return;
    this._timer = setInterval(() => {
      if (!this.isConnected || !this._sess || (typeof document !== "undefined" && document.visibilityState === "hidden")) return;
      this._session(true).catch(() => {});
    }, FW_UP_REFRESH_MS);
  }
  async _call(fn) {  // one retry with a new session when the proxy says the cookie lapsed
    const base = await this._ingress();
    try {
      return await fn(base);
    } catch (err) {
      if (!err || err.status !== 401) throw err;
      this._sess = null;
      await this._session(true);
      return fn(base);
    }
  }
  async _load() {
    if (this._loading || !this._admin()) return;
    this._loading = true;
    try {
      this._data = await this._call(async (base) => {
        const r = await fetch(`${base}api/uploads`, { credentials: "same-origin", cache: "no-store" });
        if (!r.ok) throw fwUpHttpErr(r.status);
        return r.json();
      });
      this._err = "";
    } catch (err) {
      this._err = this._why(err);
    }
    this._loading = false;
    this._render();
  }
  _post(url, fd, onp) {
    return new Promise((res, rej) => {
      const x = new XMLHttpRequest();
      x.open("POST", url);
      x.withCredentials = true;
      if (x.upload) x.upload.onprogress = (ev) => { if (ev.lengthComputable && ev.total) onp(Math.round((ev.loaded * 100) / ev.total)); };
      x.onload = () => {
        let j = null;
        try { j = JSON.parse(x.responseText); } catch (err) { j = null; }
        if (j && typeof j === "object" && "ok" in j) res(j); else rej(fwUpHttpErr(x.status));
      };
      x.onerror = () => rej(new Error("The upload did not reach the app (network)."));
      x.send(fd);
    });
  }
  _say(ok, text) {
    this._msg = { ok, text };
    const m = this._q("[data-msg]");
    if (m) m.innerHTML = `<span class="${ok ? "ok" : "err"}">${this._e(text)}</span>`;
  }
  async _upload() {
    if (this._busy || !this._admin()) return;
    const kind = (this._q("[data-kind]") || {}).value || "award";
    const month = ((this._q("[data-month]") || {}).value || "").trim();
    const day = ((this._q("[data-date]") || {}).value || "").trim();
    const input = this._q("[data-pdf]"), f = input && input.files && input.files[0];
    const max = Math.min((this._data && +this._data.max_bytes) || FW_UP_MAX, FW_UP_MAX);
    if (kind !== "seniority" && !fwUpMonth(month)) return this._say(false, "Pick the bid period (month).");
    if (!f) return this._say(false, "Pick the PDF.");
    if (!/\.pdf$/i.test(f.name || "") && f.type !== "application/pdf") return this._say(false, "That file is not a PDF.");
    if (f.size > max) return this._say(false, `Too large: ${fwUpSize(f.size)}. Home Assistant's app proxy takes a PDF of up to ${fwUpSize(max)}.`);
    const what = kind === "seniority" ? "the pilot seniority list" : `the ${fwUpMonth(month)} ${kind === "award" ? "award" : "pairings package"}`;
    const btn = this._q("[data-up]"), prog = this._q("[data-prog]");
    const show = (t) => { if (prog && prog.textContent !== t) prog.textContent = t; };
    this._busy = true;
    if (btn) btn.disabled = true;
    this._say(true, "");
    show(`Uploading ${what} (${fwUpSize(f.size)})...`);
    try {
      const r = await this._call((base) => {
        const fd = new FormData();
        fd.append("kind", kind);
        fd.append("month", kind === "seniority" ? "" : month);
        if (kind === "seniority" && /^\d{4}-\d{2}-\d{2}$/.test(day)) fd.append("list_date", day);
        fd.append("pdf", f, f.name || "upload.pdf");
        // 10 % steps: the progress line is read out (aria-live), so it changes a few times, not at every event
        return this._post(`${base}api/upload`, fd, (p) => show(p >= 100 ? `Reading ${what}...` : `Uploading ${what} (${fwUpSize(f.size)})... ${Math.floor(p / 10) * 10}%`));
      });
      this._say(!!r.ok, r.message || (r.ok ? "Saved." : "Not saved."));
      if (r.ok && input) input.value = "";
    } catch (err) {
      this._say(false, this._why(err));
    } finally {
      this._busy = false;
      if (btn) btn.disabled = false;
      show("");
    }
    await this._load();
  }
}
customElements.define("flight-watcher-uploads-card", FlightWatcherUploadsCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-uploads-card", name: "Flight Watcher uploads", description: "Upload the monthly award, pairings package and seniority list (Home Assistant admin only)" });

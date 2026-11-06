// Flight Watcher tickets card (0.10.1, Ryan): bug reports and feature requests with a screenshot.
// New tickets go to MQTT flica_watcher/ticket/new; the Watcher numbers them FW-0001... and lists them on
// sensor.flica_watcher_tickets. Answers (verify / reopen / note) go to flica_watcher/ticket/act.
class FlicaTicketsCard extends HTMLElement {
  setConfig(c) { this._c = { prefix: "flica_watcher", ...c }; this._form = null; this._img = null; this._open = {}; }
  getCardSize() { return 6; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  set hass(h) {
    this._h = h;
    const st = h.states[`sensor.${this._c.prefix}_tickets`];
    const sig = st ? st.last_updated : "none";
    if (sig === this._sig || this._form) return;  // never redraw over a form being filled
    this._sig = sig;
    this._render();
  }
  _pub(topic, obj) { this._h.callService("mqtt", "publish", { topic: `${this._c.prefix}/${topic}`, payload: JSON.stringify(obj) }); }
  _shrink(file) {
    return new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => {
        const k = Math.min(1, 1600 / Math.max(img.width, img.height));
        const cv = document.createElement("canvas");
        cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
        let q = 0.82, url = cv.toDataURL("image/jpeg", q);
        while (url.length > 1.8e6 && q > 0.4) { q -= 0.1; url = cv.toDataURL("image/jpeg", q); }
        URL.revokeObjectURL(img.src);
        res(url);
      };
      img.onerror = rej;
      img.src = URL.createObjectURL(file);
    });
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const st = this._h && this._h.states[`sensor.${this._c.prefix}_tickets`];
    const a = st ? st.attributes : {};
    const tix = a.tickets || [];
    const ver = (this._h && this._h.states[`sensor.${this._c.prefix}_state`] || { attributes: {} }).attributes.version || "";
    const chip = { new: "#1976d2", triaged: "#6a1b9a", in_progress: "#ef6c00", fixed: "#2e7d32", closed: "#757575", reopened: "#c62828" };
    const f = this._form;
    const form = f ? `<div class="form">
        <h4>${f.kind === "bug" ? "&#128027; Submit a bug" : "&#128161; Submit a feature request"}</h4>
        <label>Title<input data-f="title" maxlength="120" placeholder="${f.kind === "bug" ? "e.g. Pay-Gross wrong on v11.003" : "e.g. Show reserve days on the schedule"}"></label>
        <label>${f.kind === "bug" ? "What happened?" : "What do you want, and why?"}<textarea data-f="narrative" rows="4"></textarea></label>
        ${f.kind === "bug" ? `<label>Steps to see it<textarea data-f="steps" rows="2" placeholder="Tab, what you tapped"></textarea></label>
        <label>What did you expect?<textarea data-f="expected" rows="2"></textarea></label>` : ""}
        <label>Where<select data-f="page"><option>Watcher</option><option>Schedule</option><option>Recall/O75</option><option>Details</option><option>Aviation Wx</option><option>Phone alert</option><option>Other</option></select></label>
        <label>Screenshot (optional)<input type="file" accept="image/*" data-img></label>
        <div class="u" data-imginfo>${this._img ? "Screenshot attached" : ""}</div>
        <button data-send>Submit</button> <button class="g" data-cancel>Cancel</button> <span class="u" data-msg></span>
      </div>` : "";
    const rows = tix.map((t) => {
      const op = this._open[t.id];
      const acts = t.status === "fixed" ? `<button data-a="verify" data-id="${this._e(t.id)}">Verified, close</button><button class="g" data-a="reopen" data-id="${this._e(t.id)}">Still broken</button>`
        : t.status === "closed" ? `<button class="g" data-a="reopen" data-id="${this._e(t.id)}">Reopen</button>` : "";
      return `<div class="t"><div class="th" data-t="${this._e(t.id)}"><b>${this._e(t.id)}</b> ${t.kind === "bug" ? "&#128027;" : "&#128161;"} ${this._e(t.title)}
        <span class="chip" style="background:${chip[t.status] || "#757575"}">${this._e(String(t.status).replace("_", " "))}${t.version_fixed ? " v" + this._e(t.version_fixed) : ""}</span>
        <span class="u">${this._e(t.reporter)} · ${this._e(String(t.created_at || "").slice(0, 10))}${t.has_image ? " · &#128247;" : ""}</span></div>
        ${op ? `<div class="tb"><div class="n">${this._e(t.narrative)}</div>${acts}
          <div><input data-note="${this._e(t.id)}" placeholder="Add a note" style="width:70%"> <button class="g" data-a="note" data-id="${this._e(t.id)}">Add</button></div></div>` : ""}</div>`;
    }).join("");
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:12px 14px;font-size:13px}
      button{cursor:pointer;border:0;border-radius:6px;padding:6px 12px;font-weight:600;background:var(--primary-color);color:#fff;margin:2px 4px 2px 0}
      button.g{background:#757575}.big{font-size:14px;padding:8px 14px}
      .form{border:1px solid var(--divider-color);border-radius:8px;padding:10px;margin:8px 0}
      .form label{display:block;margin:6px 0;font-weight:600;font-size:12px}
      .form input:not([type=file]),.form textarea,.form select{display:block;width:100%;box-sizing:border-box;margin-top:2px;font:13px sans-serif;padding:4px}
      .u{color:var(--secondary-text-color);font-size:12px}
      .t{border-top:1px solid var(--divider-color);padding:6px 0}.th{cursor:pointer}
      .chip{display:inline-block;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:#fff;margin:0 6px}
      .tb{margin:6px 0 0 12px}.n{white-space:pre-wrap;margin-bottom:6px}
    </style><ha-card>
      <div><button class="big" data-new="bug">&#128027; Submit a bug</button><button class="big" data-new="feature">&#128161; Submit a feature request</button>
        <span class="u">${a.open != null ? `${a.open} open of ${a.total}` : ""}</span></div>
      ${form}
      ${tix.length ? `<div style="margin-top:6px"><b>Ticket log</b>${rows}</div>` : `<div class="u" style="margin-top:6px">No tickets yet.</div>`}
    </ha-card>`;
    const r = this.shadowRoot;
    r.querySelectorAll("[data-new]").forEach((b) => b.onclick = () => { this._form = { kind: b.dataset.new }; this._img = null; this._render(); });
    r.querySelectorAll("[data-t]").forEach((el) => el.onclick = () => { this._open[el.dataset.t] = !this._open[el.dataset.t]; this._render(); });
    r.querySelectorAll("button[data-a]").forEach((b) => b.onclick = () => {
      const m = { id: b.dataset.id, action: b.dataset.a };
      if (b.dataset.a === "note") { const i = r.querySelector(`input[data-note="${CSS.escape(b.dataset.id)}"]`); if (!i || !i.value.trim()) return; m.text = i.value.trim(); }
      this._pub("ticket/act", m); b.textContent = "Sent";
    });
    if (f) {
      r.querySelector("[data-cancel]").onclick = () => { this._form = null; this._img = null; this._sig = null; this._render(); };
      r.querySelector("[data-img]").onchange = async (ev) => {
        const file = ev.target.files && ev.target.files[0];
        const info = r.querySelector("[data-imginfo]");
        if (!file) return;
        try { this._img = await this._shrink(file); info.textContent = `Screenshot attached (${Math.round(this._img.length * 0.75 / 1024)} KB)`; }
        catch (e) { this._img = null; info.textContent = "That file isn't an image I can read."; }
      };
      r.querySelector("[data-send]").onclick = () => {
        const v = (k) => { const el = r.querySelector(`[data-f="${k}"]`); return el ? el.value.trim() : ""; };
        const msg = r.querySelector("[data-msg]");
        if (!v("title") || !v("narrative")) { msg.textContent = "Add a title and a description."; return; }
        const t = { kind: f.kind, title: v("title"), narrative: v("narrative"), steps: v("steps"), expected: v("expected"), page: v("page"), version: ver };
        if (this._img) t.image = this._img;
        this._pub("ticket/new", t);
        this._form = null; this._img = null; this._sig = null;
        setTimeout(() => this._render(), 1500);
        this._render();
      };
    }
  }
}
customElements.define("flica-tickets-card", FlicaTicketsCard);

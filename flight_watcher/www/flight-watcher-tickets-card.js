// Flight Watcher tickets card (0.10.1, Ryan; 1.1.2: completed tickets fold away): bug reports and feature requests.
// FW-0006 (Ryan): one "Submit a ticket" button and one form, Bug or Feature request chosen at its top (Bug first);
// the bug-only fields (steps, expected) show for Bug only. The payload keeps "kind" (bug | feature) as before.
// New tickets go to MQTT flight_watcher/ticket/new; the Watcher numbers them FW-0001... and lists them on
// sensor.flight_watcher_tickets. Answers (verify / reopen / note) go to flight_watcher/ticket/act. When a ticket is
// marked fixed the Watcher sends flight_watcher/event/ticket_fixed (FW-0007) for a quiet push to its reporter.
// FW-0003 (Ryan): up to 10 photos per ticket (photo library, camera or files). The ticket goes first with a
// card-made cid and the photo count, then each photo as its own flight_watcher/ticket/image {cid, i, n, image}
// message, so no MQTT message carries more than one photo (each photo's data URL stays under MAX_URL).
// FW-0049 (Ryan): an open ticket's Edit (only while new or reopened, the Watcher's "editable") changes its title,
// description, steps, expected and Where in place, sending only what changed to flight_watcher/ticket/edit; Delete
// (any status, the completed fold too) asks first in a dialog, then sends flight_watcher/ticket/delete. Each carries
// a card-made rid; the Watcher's answer comes back as "last" on the tickets sensor and shows under the button.
const FW_TICKET_MAX_PHOTOS = 10;
const FW_TICKET_MAX_URL = 1.75e6;  // one photo's data URL; its whole message stays under about 1.8e6 chars
// FW-0006: the choice at the top of the one ticket form (Bug first): its label, the description prompt, a title hint
const FW_TICKET_PAGES = ["Watcher", "Schedule", "Recall/O75", "Details", "Aviation Wx", "Phone alert", "Other"];
const FW_TICKET_EDIT = { title: 200, narrative: 10000, steps: 5000, expected: 5000, page: 300 };  // tickets.MAX_TEXT
const FW_TICKET_KINDS = {
  bug: { label: "&#128027; Bug", narrative: "What happened?", title: "e.g. Pay-Gross wrong on v11.003" },
  feature: { label: "&#128161; Feature request", narrative: "What do you want, and why?", title: "e.g. Show reserve days on the schedule" },
};
class FlightWatcherTicketsCard extends HTMLElement {
  setConfig(c) {
    this._c = { prefix: "flight_watcher", ...c };
    this._form = null; this._imgs = []; this._prep = null; this._note = ""; this._gen = 0; this._send = null; this._sending = false;
    this._open = {}; this._doneOpen = false; this._req = null; this._dlg = false; this._fk = "";
  }
  getCardSize() { return 6; }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  set hass(h) {
    this._h = h;
    const st = h.states[`sensor.${this._c.prefix}_tickets`];
    const sig = st ? st.last_updated : "none";
    if (sig === this._sig || this._form || this._dlg) return;  // never redraw over a form being filled or the dialog
    this._sig = sig;
    this._render();
  }
  _pub(topic, obj) { return this._h.callService("mqtt", "publish", { topic: `${this._c.prefix}/${topic}`, payload: JSON.stringify(obj) }); }
  _cid() {
    const b = new Uint8Array(8);
    try { crypto.getRandomValues(b); } catch (e) { b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); }); }
    return "c" + Date.now().toString(36) + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  // A picked photo -> { url: JPEG data URL under FW_TICKET_MAX_URL (longest side 1600 px or less), thumb }.
  _shrink(file) {
    return new Promise((res, rej) => {
      const img = new Image(), src = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(src);
        const W = img.naturalWidth || img.width, H = img.naturalHeight || img.height;
        if (!W || !H) { rej(new Error("empty image")); return; }
        const cv = document.createElement("canvas"), g = cv.getContext("2d");
        let side = Math.min(1600, Math.max(W, H)), url = "";
        for (let pass = 0; pass < 5 && !(url && url.length <= FW_TICKET_MAX_URL); pass++, side *= 0.75) {
          const k = side / Math.max(W, H);
          cv.width = Math.max(1, Math.round(W * k)); cv.height = Math.max(1, Math.round(H * k));
          g.fillStyle = "#fff"; g.fillRect(0, 0, cv.width, cv.height);  // a transparent PNG turns white, not black
          g.drawImage(img, 0, 0, cv.width, cv.height);
          for (let q = 0.82; q > 0.4; q -= 0.1) { url = cv.toDataURL("image/jpeg", q); if (url.length <= FW_TICKET_MAX_URL) break; }
        }
        if (!url.startsWith("data:image/jpeg") || url.length > FW_TICKET_MAX_URL) { rej(new Error("too big")); return; }
        const tc = document.createElement("canvas"), s = Math.min(W, H);
        tc.width = tc.height = 144;
        const tg = tc.getContext("2d");
        tg.fillStyle = "#fff"; tg.fillRect(0, 0, 144, 144);
        tg.drawImage(img, (W - s) / 2, (H - s) / 2, s, s, 0, 0, 144, 144);
        res({ url, thumb: tc.toDataURL("image/jpeg", 0.7) });
      };
      img.onerror = () => { URL.revokeObjectURL(src); rej(new Error("unreadable")); };
      img.src = src;
    });
  }
  _kb(n) { return n >= 1024 * 1024 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`; }
  // The photo strip inside the open form; redrawn on its own so typed text is never lost.
  _photos() {
    const box = this.shadowRoot && this.shadowRoot.querySelector("[data-photos]");
    if (!box) return;
    const n = this._imgs.length, full = n >= FW_TICKET_MAX_PHOTOS, p = this._prep;
    const bytes = this._imgs.reduce((a, x) => a + x.url.length * 0.75, 0);
    box.innerHTML = `<div class="lbl">Photos <span class="u">(optional, up to ${FW_TICKET_MAX_PHOTOS})</span></div>
      ${n ? `<div class="thumbs">${this._imgs.map((x, i) => `<div class="ph"><img src="${x.thumb}" alt="Photo ${i + 1}"><button class="x" data-rm="${i}" aria-label="Remove photo ${i + 1}">&times;</button></div>`).join("")}</div>` : ""}
      <button class="g" data-add${full || p ? " disabled" : ""}>&#128247; ${full ? `${FW_TICKET_MAX_PHOTOS} of ${FW_TICKET_MAX_PHOTOS} photos` : n ? "Add more photos" : "Add photos"}</button>${n ? `<button class="g" data-clear${p ? " disabled" : ""}>Remove all</button>` : ""}
      <div class="u" data-count>${p ? `Preparing photo ${p.i} of ${p.n}...` : n ? `${n} photo${n === 1 ? "" : "s"} attached (${this._kb(bytes)})` : "Photo library, camera or files."}</div>
      ${this._note ? `<div class="warn">${this._e(this._note)}</div>` : ""}`;
    box.querySelector("[data-add]").onclick = () => { if (!this._prep && this._imgs.length < FW_TICKET_MAX_PHOTOS) this.shadowRoot.querySelector("[data-img]").click(); };
    const cl = box.querySelector("[data-clear]");
    if (cl) cl.onclick = () => { this._imgs = []; this._note = ""; this._photos(); };
    box.querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => { this._imgs.splice(+b.dataset.rm, 1); this._note = ""; this._photos(); });
    const send = this.shadowRoot.querySelector("[data-send]");
    if (send && !this._sending) send.disabled = !!p;
  }
  // Every picked file is tried in order: an unreadable one is skipped and takes no slot, and reading stops once the
  // ticket holds FW_TICKET_MAX_PHOTOS. "Left out" counts only the files that were not tried because it was full.
  async _addFiles(list) {
    const files = Array.from(list || []);
    if (!files.length || this._prep) return;
    if (this._imgs.length >= FW_TICKET_MAX_PHOTOS) {
      this._note = `Already ${FW_TICKET_MAX_PHOTOS} photos, the most a ticket takes. Remove one to add another.`;
      this._photos();
      return;
    }
    this._note = "";
    const gen = this._gen, bad = [];
    let i = 0;
    for (; i < files.length && this._imgs.length < FW_TICKET_MAX_PHOTOS; i++) {
      this._prep = { i: i + 1, n: Math.min(files.length, i + FW_TICKET_MAX_PHOTOS - this._imgs.length) };
      this._photos();
      try {
        const x = await this._shrink(files[i]);
        if (gen !== this._gen) return;  // the form was closed meanwhile
        this._imgs.push(x);
      } catch (e) { if (gen !== this._gen) return; bad.push(files[i].name || `file ${i + 1}`); }
    }
    this._prep = null;
    const left = files.length - i, notes = [];
    if (left) notes.push(`A ticket takes ${FW_TICKET_MAX_PHOTOS} photos at most: left out ${left} of the ${files.length} you picked.`);
    if (bad.length) notes.push(`Couldn't read ${bad.length === 1 ? "this one as an image" : `${bad.length} of them as images`}: ${bad.join(", ")}.`);
    this._note = notes.join(" ");
    this._photos();
  }
  _closeForm() { this._form = null; this._imgs = []; this._prep = null; this._note = ""; this._gen++; this._sending = false; }
  async _submit(t, imgs) {
    const r = this.shadowRoot, msg = r.querySelector("[data-msg]"), btn = r.querySelector("[data-send]");
    const cid = this._cid(), n = imgs.length;
    this._sending = true; btn.disabled = true; btn.textContent = "Sending...";
    try { await this._pub("ticket/new", { ...t, cid, images: n }); }
    catch (e) {
      this._sending = false; btn.disabled = false; btn.textContent = "Submit";
      msg.textContent = `Didn't send: ${(e && e.message) || "no connection"}. Try again.`;
      return;
    }
    this._closeForm(); this._sig = null;
    // s is this ticket's own progress: only it is written here, and it is shown only while it is still this._send
    // (the Submit buttons stay off until its photos are done, so a second ticket cannot take over the status line).
    const s = this._send = { n, i: 0, failed: [], done: !n };
    const show = () => { if (this._send === s) this._status(); };
    this._render();
    for (let i = 0; i < n; i++) {  // one photo per message, in order, each after the one before has gone
      s.i = i + 1; show();
      try { await this._pub("ticket/image", { cid, i: i + 1, n, image: imgs[i].url }); }
      catch (e) { s.failed.push(i + 1); }
    }
    s.done = true; show();
    // a success line clears itself; a failed photo stays until the next ticket is started
    if (!s.failed.length) setTimeout(() => { if (this._send === s) { this._send = null; this._status(); } }, 10000);
  }
  _busy() { return !!(this._send && !this._send.done); }
  // "1", "1 and 2", "1, 2 and 5"
  _and(a) { return a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`; }
  _statusText() {
    const s = this._send;
    if (!s) return "";
    if (!s.done) return s.n ? `Ticket sent. Sending photo ${s.i} of ${s.n}...` : "Ticket sent.";
    const f = s.failed;
    if (f.length) {
      if (s.n === 1) return "Ticket sent, but the photo didn't go through.";
      if (f.length === s.n) return `Ticket sent, but none of the ${s.n} photos went through.`;
      return `Ticket sent, but photo${f.length === 1 ? "" : "s"} ${this._and(f)} of ${s.n} didn't go through.`;
    }
    return s.n ? `Ticket sent with ${s.n} photo${s.n === 1 ? "" : "s"}.` : "Ticket sent.";
  }
  _status() {
    const r = this.shadowRoot, el = r && r.querySelector("[data-status]");
    if (el) { el.textContent = this._statusText(); el.className = this._send && this._send.failed.length ? "warn" : "u"; }
    if (r) r.querySelectorAll("[data-new]").forEach((b) => { b.disabled = this._busy(); });
  }
  // FW-0049: the edit message, {id, ...only the fields that changed}, or why there is nothing to send. t is the
  // ticket as listed (an editable one carries its whole text), vals the form's values.
  _editMsg(t, vals) {
    const v = {};
    Object.keys(FW_TICKET_EDIT).forEach((k) => { if (k in vals) v[k] = String(vals[k] == null ? "" : vals[k]).trim().slice(0, FW_TICKET_EDIT[k]); });
    if (!v.title || !v.narrative) return "Add a title and a description.";
    const m = { id: t.id };
    let n = 0;
    Object.keys(v).forEach((k) => { if (v[k] !== String(t[k] == null ? "" : t[k]).trim()) { m[k] = v[k]; n++; } });
    return n ? m : "Nothing changed.";
  }
  // FW-0049: the line under the buttons for the last edit / delete this card sent; last = the sensor's "last".
  _reqText(last) {
    const q = this._req;
    if (!q) return "";
    const del = q.action === "delete", what = del ? "deleted" : "saved";
    if (q.err) return `${q.id} not ${what}: didn't send (${q.err}). Try again.`;
    const L = last && last.rid && last.rid === q.rid ? last : null;
    if (!L) return q.slow ? `${q.id}: sent, no answer from the Watcher yet.` : `${del ? "Deleting" : "Saving"} ${q.id}...`;
    if (L.ok) return `${q.id} ${what}.`;
    const e = L.error || "refused";
    return e.includes(q.id) ? `Not ${what}: ${e}.` : `${q.id} not ${what}: ${e}.`;
  }
  _reqBad(last) { const q = this._req; return !!(q && (q.err || (last && last.rid && last.rid === q.rid && !last.ok))); }
  _sent(q) {
    this._req = q;
    setTimeout(() => { if (this._req === q) { q.slow = true; this._sig = null; if (!this._form && !this._dlg) this._render(); } }, 30000);
  }
  _editForm(t) {
    const K = FW_TICKET_KINDS[t.kind] || FW_TICKET_KINDS.bug, bug = t.kind === "bug" || !!(t.steps || t.expected);
    const pages = FW_TICKET_PAGES.slice();
    if (t.page && !pages.includes(t.page)) pages.push(t.page);
    const opt = (p) => `<option${p === (t.page || "") ? " selected" : ""}>${this._e(p)}</option>`;
    return `<div class="form ef" data-editform>
        <h4>&#9998; Edit ${this._e(t.id)}</h4>
        <div class="u">Open to edits while it is new or reopened. Photos stay as they are.</div>
        <label>Title<input data-f="title" maxlength="${FW_TICKET_EDIT.title}" value="${this._e(t.title)}"></label>
        <label>${K.narrative}<textarea data-f="narrative" rows="6">${this._e(t.narrative)}</textarea></label>
        ${bug ? `<label>Steps to see it<textarea data-f="steps" rows="2">${this._e(t.steps)}</textarea></label>
        <label>What did you expect?<textarea data-f="expected" rows="2">${this._e(t.expected)}</textarea></label>` : ""}
        <label>Where<select data-f="page">${t.page ? "" : `<option value="" selected>(not set)</option>`}${pages.map(opt).join("")}</select></label>
        <button data-save>Save</button> <button class="g" data-cancel>Cancel</button> <span class="u" data-msg></span>
      </div>`;
  }
  // FW-0049: Delete asks first. A real dialog where the browser has one, else the browser's own confirm.
  _askDelete(t) {
    const d = this.shadowRoot.querySelector("dialog[data-dlg]");
    const q = `Delete ${t.id}?`;
    if (!d || typeof d.showModal !== "function") { if (window.confirm(`${q} ${t.title}`)) this._delete(t.id); return; }
    const st = String(t.status || "").replace("_", " ");
    d.innerHTML = `<form method="dialog"><h4>${this._e(q)}</h4><div class="dt">${this._e(t.title)}</div>
      <p class="u">It comes off the ticket log${st && st !== "new" ? ` (it is ${this._e(st)})` : ""}. The Watcher keeps a copy in its deleted folder.</p>
      <div class="dr"><button value="keep" class="g" autofocus>Keep</button><button value="delete" class="del">Delete</button></div></form>`;
    d.returnValue = "";
    d.onclose = () => {
      this._dlg = false;
      if (d.returnValue === "delete") this._delete(t.id);
      else { this._sig = null; if (!this._form) this._render(); }  // anything that came in while it was open
    };
    this._dlg = true;
    d.showModal();
  }
  async _delete(id) {
    const q = { rid: this._cid(), id, action: "delete" };
    this._sent(q);
    this._sig = null;
    if (!this._form) this._render();
    try { await this._pub("ticket/delete", { id, rid: q.rid }); }
    catch (e) { q.err = (e && e.message) || "no connection"; if (!this._form && !this._dlg) this._render(); }
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    // what is typed in an open form survives a redraw of the same form (a ticket opened or closed under it)
    const fk = this._form ? (this._form.mode === "edit" ? `edit:${this._form.id}` : "new") : "";
    const keep = {};
    if (fk && fk === this._fk) this.shadowRoot.querySelectorAll("[data-f]").forEach((el) => { keep[el.dataset.f] = el.value; });
    this._fk = fk;
    const st = this._h && this._h.states[`sensor.${this._c.prefix}_tickets`];
    const a = st ? st.attributes : {};
    const tix = a.tickets || [];
    const ver = (this._h && this._h.states[`sensor.${this._c.prefix}_state`] || { attributes: {} }).attributes.version || "";
    const chip = { new: "#1976d2", triaged: "#6a1b9a", in_progress: "#ef6c00", fixed: "#2e7d32", closed: "#757575", reopened: "#c62828" };
    const f = this._form, nf = f && f.mode !== "edit" ? f : null, K = nf ? FW_TICKET_KINDS[nf.kind] || FW_TICKET_KINDS.bug : null;
    const last = a.last || {};
    const form = nf ? `<div class="form">
        <h4>&#127915; New ticket</h4>
        <div class="seg" role="radiogroup" aria-label="Ticket type">${Object.keys(FW_TICKET_KINDS).map((k) =>
          `<label><input type="radio" name="fw-ticket-kind" value="${k}" data-kind${k === nf.kind ? " checked" : ""}><span>${FW_TICKET_KINDS[k].label}</span></label>`).join("")}</div>
        <label>Title<input data-f="title" maxlength="120" placeholder="${K.title}"></label>
        <label><span data-narr>${K.narrative}</span><textarea data-f="narrative" rows="4"></textarea></label>
        <div data-bugonly${nf.kind === "bug" ? "" : " hidden"}><label>Steps to see it<textarea data-f="steps" rows="2" placeholder="Tab, what you tapped"></textarea></label>
        <label>What did you expect?<textarea data-f="expected" rows="2"></textarea></label></div>
        <label>Where<select data-f="page">${FW_TICKET_PAGES.map((p) => `<option>${p}</option>`).join("")}</select></label>
        <div class="photos" data-photos></div>
        <input class="vh" type="file" accept="image/*" multiple data-img tabindex="-1" aria-hidden="true">
        <button data-send>Submit</button> <button class="g" data-cancel>Cancel</button> <span class="u" data-msg></span>
      </div>` : "";
    // 1.1.2 (Ryan): completed tickets (fixed, closed) fold away under "N completed"; open ones stay in the log.
    const DONE = ["fixed", "closed"];
    const active = tix.filter((t) => !DONE.includes(t.status)), done = tix.filter((t) => DONE.includes(t.status));
    const waiting = done.filter((t) => t.status === "fixed").length;
    // FW-0049: the answer to the last edit / delete shows in that ticket's open row (where Save or Delete was
    // tapped), or at the top when the row is gone (deleted) or shut
    const rq0 = this._req, rqHtml = `<div data-req class="${this._reqBad(last) ? "warn" : "u"}">${this._e(this._reqText(last))}</div>`;
    const rqRow = rq0 && this._open[rq0.id] && !(f && f.mode === "edit" && f.id === rq0.id)
      && (active.some((t) => t.id === rq0.id) || (this._doneOpen && done.some((t) => t.id === rq0.id))) ? rq0.id : "";
    const row = (t) => {
      const op = this._open[t.id];
      const np = t.image_count != null ? +t.image_count || 0 : t.has_image ? 1 : 0;  // FW-0003; older Watchers send has_image only
      const acts = t.status === "fixed" ? `<button data-a="verify" data-id="${this._e(t.id)}">Verified, close</button><button class="g" data-a="reopen" data-id="${this._e(t.id)}">Still broken</button>`
        : t.status === "closed" ? `<button class="g" data-a="reopen" data-id="${this._e(t.id)}">Reopen</button>` : "";
      // FW-0049: Edit only while the Watcher lists it editable (new or reopened); Delete in any status
      const eds = `<div class="eds">${t.editable ? `<button class="g" data-edit="${this._e(t.id)}">&#9998; Edit</button>` : ""}<button class="del" data-del="${this._e(t.id)}">Delete</button></div>`;
      const editing = f && f.mode === "edit" && f.id === t.id;
      return `<div class="t"><div class="th" data-t="${this._e(t.id)}"><b>${this._e(t.id)}</b> ${t.kind === "bug" ? "&#128027;" : "&#128161;"} ${this._e(t.title)}
        <span class="chip" style="background:${chip[t.status] || "#757575"}">${this._e(String(t.status).replace("_", " "))}${t.version_fixed ? (/^\d+(\.\d+)+$/.test(String(t.version_fixed)) ? " v" : " in ") + this._e(t.version_fixed) : ""}</span>
        <span class="u">${this._e(t.reporter)} · ${this._e(String(t.created_at || "").slice(0, 10))}${np ? ` · <span title="${np} photo${np === 1 ? "" : "s"}">&#128247;${np > 1 ? " " + np : ""}</span>` : ""}</span></div>
        ${editing ? `<div class="tb">${this._editForm(f.t)}</div>` : op ? `<div class="tb">${rqRow === t.id ? rqHtml : ""}<div class="n">${this._e(t.narrative)}</div>${np ? `<div class="u" style="margin-bottom:6px">&#128247; ${np} photo${np === 1 ? "" : "s"} attached</div>` : ""}${acts}
          <div><input data-note="${this._e(t.id)}" placeholder="Add a note" style="width:70%"> <button class="g" data-a="note" data-id="${this._e(t.id)}">Add</button></div>${eds}</div>` : ""}</div>`;
    };
    const rows = active.map(row).join("");
    const doneRows = done.length ? `<details class="done"${this._doneOpen ? " open" : ""}><summary>${done.length} completed${waiting ? ` <span class="u">(${waiting} waiting for your verify)</span>` : ""}</summary>${done.map(row).join("")}</details>` : "";
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:12px 14px;font-size:13px}
      button{cursor:pointer;border:0;border-radius:6px;padding:6px 12px;font-weight:600;background:var(--primary-color);color:#fff;margin:2px 4px 2px 0}
      button.g{background:#757575}.big{font-size:14px;padding:8px 14px}button:disabled{opacity:.5;cursor:default}
      .form{border:1px solid var(--divider-color);border-radius:8px;padding:10px;margin:8px 0}
      .form label{display:block;margin:6px 0;font-weight:600;font-size:12px}
      .form input:not([type=file]):not([type=radio]),.form textarea,.form select{display:block;width:100%;box-sizing:border-box;margin-top:2px;font:13px sans-serif;padding:4px}
      .form h4{margin:2px 0 0;font-size:14px}
      .seg{display:flex;border:1px solid var(--primary-color);border-radius:8px;overflow:hidden;margin:8px 0 10px}
      .form .seg label{flex:1;position:relative;margin:0;font-size:13px}.seg label+label{border-left:1px solid var(--primary-color)}
      .seg input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
      .seg span{display:flex;align-items:center;justify-content:center;gap:4px;min-height:40px;padding:0 6px;text-align:center;color:var(--primary-color)}
      .seg input:checked+span{background:var(--primary-color);color:#fff}
      .seg input:focus-visible+span{outline:2px solid var(--primary-text-color);outline-offset:-4px}
      .photos{margin:8px 0}.photos .lbl{font-weight:600;font-size:12px;margin-bottom:4px}
      .thumbs{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}
      .ph{position:relative;width:64px;height:64px}
      .ph img{width:64px;height:64px;object-fit:cover;border-radius:6px;border:1px solid var(--divider-color);display:block}
      .ph button.x{position:absolute;top:-7px;right:-7px;width:24px;height:24px;padding:0;margin:0;border-radius:50%;background:rgba(0,0,0,.72);border:2px solid #fff;font-size:15px;line-height:18px}
      .vh{position:absolute;width:1px;height:1px;opacity:0;overflow:hidden;pointer-events:none}
      .warn{color:var(--error-color,#c62828);font-size:12px;font-weight:600}
      .u{color:var(--secondary-text-color);font-size:12px}
      .t{border-top:1px solid var(--divider-color);padding:6px 0}.th{cursor:pointer}
      .chip{display:inline-block;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700;color:#fff;margin:0 6px}
      .tb{margin:6px 0 0 12px}.n{white-space:pre-wrap;margin-bottom:6px}.tb [data-req]:not(:empty){margin-bottom:6px}
      details.done{border-top:1px solid var(--divider-color);padding-top:6px}details.done summary{cursor:pointer;font-weight:600;color:var(--secondary-text-color)}
      .eds{margin-top:6px}button.del{background:none;color:var(--error-color,#c62828);border:1px solid currentColor;padding:5px 11px}
      .form.ef{margin:4px 0 2px}
      dialog{border:0;border-radius:12px;padding:16px 18px;width:min(340px,calc(100vw - 48px));box-sizing:border-box;background:var(--card-background-color,#fff);color:var(--primary-text-color);box-shadow:0 8px 28px rgba(0,0,0,.35)}
      dialog::backdrop{background:rgba(0,0,0,.45)}dialog h4{margin:0 0 6px;font-size:16px}dialog .dt{font-weight:600;margin-bottom:6px;overflow-wrap:anywhere}
      dialog p{margin:6px 0 14px}.dr{display:flex;gap:8px;justify-content:flex-end}.dr button{margin:0;min-height:40px;padding:8px 18px;font-size:14px}
      .dr button.del{background:var(--error-color,#c62828);color:#fff;border:0}
    </style><ha-card>
      <div><button class="big" data-new${this._busy() ? " disabled" : ""}>&#127915; Submit a ticket</button>
        <span class="u">${tix.length ? `${active.length} open · ${done.length} completed` : ""}</span></div>
      <div data-status class="${this._send && this._send.failed.length ? "warn" : "u"}">${this._e(this._statusText())}</div>
      ${rqRow ? "" : rqHtml}
      ${form}
      ${tix.length ? `<div style="margin-top:6px"><b>Ticket log</b>${rows || `<div class="u" style="padding:6px 0">Nothing open.</div>`}${doneRows}</div>` : `<div class="u" style="margin-top:6px">No tickets yet.</div>`}
      <dialog data-dlg aria-label="Delete ticket"></dialog>
    </ha-card>`;
    const r = this.shadowRoot;
    Object.keys(keep).forEach((k) => { const el = r.querySelector(`[data-f="${k}"]`); if (el) el.value = keep[k]; });
    // a finished edit / delete line clears itself after 10 s; a refusal stays until the next one
    const q = this._req, L = last.rid && q && last.rid === q.rid ? last : null;
    if (L && L.ok && !q.clear) q.clear = setTimeout(() => { if (this._req === q) { this._req = null; const el = this.shadowRoot.querySelector("[data-req]"); if (el) el.textContent = ""; } }, 10000);
    r.querySelectorAll("[data-new]").forEach((b) => b.onclick = () => {
      if (this._busy()) return;  // the last ticket's photos are still going
      if (this._form) { const ti = r.querySelector('[data-f="title"]'); if (ti) ti.focus(); return; }  // open already: keep what is typed
      this._closeForm(); this._form = { kind: "bug" };  // FW-0006: Bug first, Feature one tap away
      if (this._send && this._send.done) this._send = null;
      this._render();
    });
    r.querySelectorAll("[data-t]").forEach((el) => el.onclick = () => { this._open[el.dataset.t] = !this._open[el.dataset.t]; this._render(); });
    const dd = r.querySelector("details.done");
    if (dd) dd.ontoggle = () => { this._doneOpen = dd.open; };
    r.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => {
      const t = tix.find((x) => x.id === b.dataset.edit);
      if (!t || !t.editable) return;
      if (this._form) { const ti = r.querySelector('[data-f="title"]'); if (ti) ti.focus(); return; }  // finish or cancel the open form first
      this._form = { mode: "edit", id: t.id, t: { ...t } };
      this._open[t.id] = true;
      this._render();
      const ti = this.shadowRoot.querySelector('[data-editform] [data-f="title"]');
      if (ti) ti.focus();
    });
    r.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => {
      const t = tix.find((x) => x.id === b.dataset.del);
      if (t) this._askDelete(t);
    });
    r.querySelectorAll("button[data-a]").forEach((b) => b.onclick = () => {
      const m = { id: b.dataset.id, action: b.dataset.a };
      if (b.dataset.a === "note") { const i = r.querySelector(`input[data-note="${CSS.escape(b.dataset.id)}"]`); if (!i || !i.value.trim()) return; m.text = i.value.trim(); }
      this._pub("ticket/act", m); b.textContent = "Sent";
    });
    if (f && f.mode === "edit") {
      const box = r.querySelector("[data-editform]");
      if (box) {
        box.querySelector("[data-cancel]").onclick = () => { this._closeForm(); this._sig = null; this._render(); };
        const save = box.querySelector("[data-save]"), msg = box.querySelector("[data-msg]");
        save.onclick = async () => {
          if (save.disabled) return;
          const vals = {};
          box.querySelectorAll("[data-f]").forEach((el) => { vals[el.dataset.f] = el.value; });
          const m = this._editMsg(f.t, vals);
          if (typeof m === "string") { msg.textContent = m; return; }
          m.rid = this._cid();
          save.disabled = true; save.textContent = "Saving...";
          try { await this._pub("ticket/edit", m); }
          catch (e) { save.disabled = false; save.textContent = "Save"; msg.textContent = `Didn't send: ${(e && e.message) || "no connection"}. Try again.`; return; }
          this._sent({ rid: m.rid, id: f.id, action: "edit" });
          this._closeForm(); this._sig = null; this._render();
        };
      }
    }
    if (nf) {
      this._photos();
      r.querySelector("[data-cancel]").onclick = () => { this._closeForm(); this._sig = null; this._render(); };
      // FW-0006: switching Bug / Feature changes the form in place, so nothing typed (or picked) is lost
      r.querySelectorAll("[data-kind]").forEach((el) => el.onchange = () => {
        if (!el.checked || !FW_TICKET_KINDS[el.value]) return;
        f.kind = el.value;
        const k = FW_TICKET_KINDS[f.kind];
        r.querySelector("[data-bugonly]").hidden = f.kind !== "bug";
        r.querySelector("[data-narr]").textContent = k.narrative;
        r.querySelector('[data-f="title"]').placeholder = k.title;
      });
      const inp = r.querySelector("[data-img]");
      inp.onchange = () => { const fl = Array.from(inp.files || []); inp.value = ""; this._addFiles(fl); };  // cleared so the same photo can be picked again
      r.querySelector("[data-send]").onclick = () => {
        if (this._sending || this._prep) return;
        const v = (k, n) => { const el = r.querySelector(`[data-f="${k}"]`); return el ? el.value.trim().slice(0, n) : ""; };
        const msg = r.querySelector("[data-msg]");
        if (!v("title") || !v("narrative")) { msg.textContent = "Add a title and a description."; return; }
        const bug = f.kind === "bug";  // a feature request sends no steps / expected, even if typed under Bug first
        const t = { kind: f.kind, title: v("title", 200), narrative: v("narrative", 10000), steps: bug ? v("steps", 5000) : "", expected: bug ? v("expected", 5000) : "", page: v("page", 300), version: ver };
        this._submit(t, this._imgs.slice());
      };
    }
  }
}
customElements.define("flight-watcher-tickets-card", FlightWatcherTicketsCard);

/* Flight Watcher: FO / RO pickers card (v4, Ryan 2026-11-04). v3: Fastest Pickup Speed. v2: tap a name for that pilot's month.
   Sortable table of sensor.flight_watcher_pickers: tap a column header to sort by it, tap again to flip.
   Columns: Pilot, Emp, Pos, Ttl / Month / Year / InFlt Pickups, Common Layover (most picked first,
   count as a small subscript, latest pickup's layover first when tied), Avg Pickup Speed.
   Search box filters by last name, first name or employee number. Read only.
   FW-0060 (1.4.7): every picker comes from pickers_<key>.json under /local/; the sensor keeps the count and the
   fastest few (the list passed HA's 16 KB recorder limit as it grew). The key is only in the sensor's attributes.
   1.7.1 (F#52): the box is labeled as this list's filter (the pilot lookup card above it asks FLICA). On a card 500 px
   wide or less (a phone; a container query, so the desktop table is unchanged) the table keeps Pilot, Pos, Best
   (Fastest Pickup Speed) and Avg (Avg Pickup Speed), so the speeds show without a sideways scroll; the employee number,
   the pickup counts and the common layovers go on a small line under the name. The sorted column's header is bold in
   the text color (the theme's blue on the header's gray was under WCAG AA's 4.5:1, F#119). */
const FMT = (a) => a == null ? "-" : a >= 3600 ? `${Math.floor(a / 3600)}h ${String(Math.floor((a % 3600) / 60)).padStart(2, "0")}m`
  : a >= 60 ? `${Math.floor(a / 60)}m ${String(a % 60).padStart(2, "0")}s` : `${a}s`;
// [key, header, sort kind, header on a narrow card ("" = folded under the name there)]
const COLS = [
  ["name", "Pilot", "s", "Pilot"], ["emp", "Emp", "s", ""], ["pos", "Pos", "s", "Pos"], ["n", "Ttl Pickups", "n", ""],
  ["month_n", "Month Pickups", "n", ""], ["year_n", "Year Pickups", "n", ""], ["inflt_n", "InFlt Pickups", "n", ""],
  ["lays", "Common Layover", "l", ""], ["min_s", "Fastest Pickup Speed", "n", "Best"], ["avg_s", "Avg Pickup Speed", "n", "Avg"],
];

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

class FlightWatcherPickersCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.flight_watcher_pickers", title: "FO / RO pickers", open: false, ...config };
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("flight_watcher_pickers_sort") || "{}"); } catch (e) { saved = {}; }
    this._sort = saved.key ? saved : { key: "avg_s", dir: 1 };
    this._q = "";
    this._open = !!this._config.open;
  }
  set hass(hass) {
    this._h = hass;
    const st = hass.states[this._config.entity];
    // FW-0060: the file's full list once it is in, else the sensor's fastest few
    const f = fwListFile(this._lf || (this._lf = {}), "/local/flight-watcher/pickers_", st, () => { if (this._h) this.hass = this._h; });
    const rows = (f && Array.isArray(f.pickers) ? f.pickers : null) || (st && st.attributes.pickers) || [];
    const sig = JSON.stringify(rows);
    if (sig === this._sig && this._root) return;
    this._sig = sig;
    this._rows = rows;
    this._render();
  }
  getCardSize() { return 6; }
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  _sorted() {
    const { key, dir } = this._sort;
    const q = this._q.trim().toLowerCase();
    const rows = this._rows.filter((p) => {
      if (!q) return true;
      const nm = (p.name || "").toLowerCase();
      const rev = nm.split(",").map((x) => x.trim()).reverse().join(" ");
      return nm.includes(q) || rev.includes(q) || String(p.emp || "").includes(q) || (p.lays || []).some((l) => l[0].toLowerCase().includes(q));
    });
    const col = COLS.find((c) => c[0] === key) || COLS[8];
    const val = (p) => {
      if (col[2] === "l") return (p.lays && p.lays.length) ? p.lays[0][1] * 1000 + (p.lays[0][0] === p.last_lay ? 1 : 0) : -1;
      if (col[2] === "n") return p[key] == null ? (dir === 1 ? 1e12 : -1) : p[key];
      return (p[key] || "").toString().toLowerCase();
    };
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      const r = x < y ? -1 : x > y ? 1 : (a.name || "").localeCompare(b.name || "");
      return col[2] === "s" ? r * dir : (x === y ? r : r * dir);
    });
    return rows;
  }
  _render() {
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        :host{display:block}
        ha-card{padding:8px 12px 12px}
        .hd{display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:600;padding:4px 0}
        .hd .tri{display:inline-block;width:0;height:0;border-left:6px solid currentColor;border-top:5px solid transparent;border-bottom:5px solid transparent;transition:transform .15s}
        .hd.open .tri{transform:rotate(90deg)}
        .body{display:none;container-type:inline-size}.body.open{display:block}
        .fl{display:block;font-size:12px;color:var(--secondary-text-color);margin:6px 0 0}
        input{width:100%;box-sizing:border-box;padding:8px 10px;margin:2px 0 8px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font-size:14px}
        .wrap{overflow-x:auto}
        table{border-collapse:collapse;font-size:13px;width:100%}
        th,td{border:1px solid var(--divider-color,#ddd);padding:3px 6px;white-space:nowrap}
        th{text-align:left;cursor:pointer;user-select:none;background:var(--secondary-background-color,#f4f4f4);position:sticky;top:0}
        th.on{color:var(--primary-text-color);font-weight:700}
        th.on:after{content:" \\25B2";font-size:9px}
        th.on.d:after{content:" \\25BC"}
        td.n{text-align:right}
        tr.fast td{font-weight:600}
        sub{font-size:9px;opacity:.75;margin-right:5px}.sm sub{opacity:1}
        .lay b{font-weight:700}
        td.pn{cursor:pointer}td.pn .nm{color:var(--primary-color);text-decoration:underline dotted}
        .sm{display:none;font-size:11px;font-weight:400;color:var(--secondary-text-color)}th .sh{display:none}
        @container (max-width:500px){.wide{display:none}th .lg{display:none}th .sh{display:inline}.sm{display:block}
          td.pn{white-space:normal}table{font-size:12px}th,td{padding:3px 4px}}
        .key{font-size:11px;opacity:.8;margin:6px 0 0}
        details summary{cursor:pointer;font-size:12px}
      </style><ha-card><div class="hd"><span class="tri"></span><span class="ttl"></span></div><div class="body">
        <label class="fl" for="flt">Filter this list (it does not ask FLICA)</label>
        <input id="flt" type="search" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="Filter this list (name, emp or layover)">
        <div class="wrap"><table><thead><tr></tr></thead><tbody></tbody></table></div>
        <details><summary>&#9656; Key</summary><div class="key">Tap a column header to sort, tap again to flip. Bold row = 1 min or under. Ttl = all pickups seen; Month / Year = this HST month and year; InFlt = picked up while airborne; Common Layover = stations they pick up most, with how many (bold = their latest pickup); Fastest / Avg Pickup Speed = the pilot's quickest grab and their average time a trip sat in open time.</div></details>
      </div></ha-card>`;
      this._root.querySelector(".hd").addEventListener("click", () => { this._open = !this._open; this._paint(); });
      this._root.querySelector("input").addEventListener("input", (e) => { this._q = e.target.value; this._paint(); });
      this._root.querySelector("input").addEventListener("keydown", (e) => e.stopPropagation());  // v4: keep HA's e/a/c shortcuts out of the field
      this._root.querySelector("tbody").addEventListener("click", (e) => {  // v2: tap a name -> pilot schedule card
        const td = e.target.closest("td.pn");
        if (td) window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { emp: td.dataset.emp, name: td.dataset.name } }));
      });
      const tr = this._root.querySelector("thead tr");
      tr.innerHTML = COLS.map((c) => `<th data-k="${c[0]}"${c[3] ? "" : ` class="wide"`}><span class="lg">${c[1]}</span><span class="sh">${c[3]}</span></th>`).join("");
      tr.addEventListener("click", (e) => {
        const th = e.target.closest("th");
        if (!th) return;
        const k = th.dataset.k;
        this._sort = this._sort.key === k ? { key: k, dir: -this._sort.dir } : { key: k, dir: k === "avg_s" || k === "min_s" || k === "name" || k === "emp" || k === "pos" ? 1 : -1 };
        try { localStorage.setItem("flight_watcher_pickers_sort", JSON.stringify(this._sort)); } catch (e2) { /* ignore */ }
        this._paint();
      });
    }
    this._paint();
  }
  _paint() {
    const rows = this._sorted();
    const r = this._root;
    r.querySelector(".ttl").textContent = `${this._config.title} (${rows.length}${this._q ? " of " + this._rows.length : ""})`;
    r.querySelector(".hd").classList.toggle("open", this._open || !!this._q);
    r.querySelector(".body").classList.toggle("open", this._open || !!this._q);
    r.querySelectorAll("th").forEach((th) => {
      th.classList.toggle("on", th.dataset.k === this._sort.key);
      th.classList.toggle("d", th.dataset.k === this._sort.key && this._sort.dir === -1);
    });
    r.querySelector("tbody").innerHTML = rows.length ? rows.map((p) => {
      const lays = (p.lays || []).slice(0, 4).map((l) => `${l[0] === p.last_lay ? "<b>" + this._esc(l[0]) + "</b>" : this._esc(l[0])}<sub>${l[1]}</sub>`).join("");
      // 1.7.1 (F#52): what a narrow card folds under the name (the Emp to Common Layover columns)
      const sm = `Emp ${this._esc(p.emp)} &middot; ${p.n} pickups: ${p.month_n || 0} this month, ${p.year_n || 0} this year, ${p.inflt_n || 0} in flight${lays ? ` &middot; <span class="lay">${lays}</span>` : ""}`;
      return `<tr class="${p.avg_s != null && p.avg_s <= 60 ? "fast" : ""}"><td class="pn" data-emp="${this._esc(p.emp)}" data-name="${this._esc(p.name)}" title="tap: this pilot's month"><span class="nm">${this._esc(p.name)}</span><div class="sm">${sm}</div></td><td class="wide">${this._esc(p.emp)}</td><td>${this._esc(p.pos)}</td>
        <td class="n wide">${p.n}</td><td class="n wide">${p.month_n || 0}</td><td class="n wide">${p.year_n || 0}</td><td class="n wide">${p.inflt_n || 0}</td>
        <td class="lay wide">${lays || "-"}</td><td class="n">${FMT(p.min_s)}</td><td class="n">${FMT(p.avg_s)}</td></tr>`;
    }).join("") : `<tr><td colspan="10">${this._q ? "No match." : "No pickups scored yet."}</td></tr>`;
  }
}
customElements.define("flight-watcher-pickers-card", FlightWatcherPickersCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pickers-card", name: "Flight Watcher pickers", description: "Sortable FO / RO pickers table" });

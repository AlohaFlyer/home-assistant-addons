/* Flight Watcher: FO / RO pickers card (v4, Ryan 2026-11-04). v3: Fastest Pickup Speed. v2: tap a name for that pilot's month.
   Sortable table of sensor.flight_watcher_pickers: tap a column header to sort by it, tap again to flip.
   Columns: Pilot, Emp, Pos, Ttl / Month / Year / InFlt Pickups, Common Layover (most picked first,
   count as a small subscript, latest pickup's layover first when tied), Avg Pickup Speed.
   Search box filters by last name, first name or employee number. Read only. */
const FMT = (a) => a == null ? "-" : a >= 3600 ? `${Math.floor(a / 3600)}h ${String(Math.floor((a % 3600) / 60)).padStart(2, "0")}m`
  : a >= 60 ? `${Math.floor(a / 60)}m ${String(a % 60).padStart(2, "0")}s` : `${a}s`;
const COLS = [
  ["name", "Pilot", "s"], ["emp", "Emp", "s"], ["pos", "Pos", "s"], ["n", "Ttl Pickups", "n"],
  ["month_n", "Month Pickups", "n"], ["year_n", "Year Pickups", "n"], ["inflt_n", "InFlt Pickups", "n"],
  ["lays", "Common Layover", "l"], ["min_s", "Fastest Pickup Speed", "n"], ["avg_s", "Avg Pickup Speed", "n"],
];

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
    const st = hass.states[this._config.entity];
    const rows = (st && st.attributes.pickers) || [];
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
        .body{display:none}.body.open{display:block}
        input{width:100%;box-sizing:border-box;padding:8px 10px;margin:6px 0 8px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font-size:14px}
        .wrap{overflow-x:auto}
        table{border-collapse:collapse;font-size:13px;width:100%}
        th,td{border:1px solid var(--divider-color,#ddd);padding:3px 6px;white-space:nowrap}
        th{text-align:left;cursor:pointer;user-select:none;background:var(--secondary-background-color,#f4f4f4);position:sticky;top:0}
        th.on{color:var(--primary-color)}
        th.on:after{content:" \\25B2";font-size:9px}
        th.on.d:after{content:" \\25BC"}
        td.n{text-align:right}
        tr.fast td{font-weight:600}
        sub{font-size:9px;opacity:.75;margin-right:5px}
        .lay b{font-weight:700}
        td.pn{cursor:pointer;color:var(--primary-color);text-decoration:underline dotted}
        .key{font-size:11px;opacity:.8;margin:6px 0 0}
        details summary{cursor:pointer;font-size:12px}
      </style><ha-card><div class="hd"><span class="tri"></span><span class="ttl"></span></div><div class="body">
        <input type="search" placeholder="Find a pilot (last name, first name, employee number or layover)">
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
      tr.innerHTML = COLS.map((c) => `<th data-k="${c[0]}">${c[1]}</th>`).join("");
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
      return `<tr class="${p.avg_s != null && p.avg_s <= 60 ? "fast" : ""}"><td class="pn" data-emp="${this._esc(p.emp)}" data-name="${this._esc(p.name)}" title="tap: this pilot's month">${this._esc(p.name)}</td><td>${this._esc(p.emp)}</td><td>${this._esc(p.pos)}</td>
        <td class="n">${p.n}</td><td class="n">${p.month_n || 0}</td><td class="n">${p.year_n || 0}</td><td class="n">${p.inflt_n || 0}</td>
        <td class="lay">${lays || "-"}</td><td class="n">${FMT(p.min_s)}</td><td class="n">${FMT(p.avg_s)}</td></tr>`;
    }).join("") : `<tr><td colspan="10">${this._q ? "No match." : "No pickups scored yet."}</td></tr>`;
  }
}
customElements.define("flight-watcher-pickers-card", FlightWatcherPickersCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pickers-card", name: "Flight Watcher pickers", description: "Sortable FO / RO pickers table" });

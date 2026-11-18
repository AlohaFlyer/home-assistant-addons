/* Flight Watcher: FO / RO pickers card (v4, Ryan 2026-11-04). v3: Fastest Pickup Speed. v2: tap a name for that pilot's month.
   Sortable table of sensor.flight_watcher_pickers: tap a column header to sort by it, tap again to flip.
   Columns: Pilot, Emp, Pos, Ttl / Month / Year / InFlt Pickups, Common Layover (most picked first,
   count as a small subscript, latest pickup's layover first when tied), Avg Pickup Speed.
   Search box filters by last name, first name or employee number. Read only.
   FW-0060 (1.4.7): every picker comes from pickers_<key>.json under /local/; the sensor keeps the count and the
   fastest few (the list passed HA's 16 KB recorder limit as it grew). The key is only in the sensor's attributes.
   1.7.1 (F#52): the box is labeled as this list's filter (the pilot lookup card above it asks FLICA). On a card 500 px (700 px since
   1.7.8) wide or less (a phone; a container query, so the desktop table is unchanged) the table keeps Pilot, Pos, Best
   (Fastest Pickup Speed) and Avg (Avg Pickup Speed), so the speeds show without a sideways scroll; the employee number,
   the pickup counts and the common layovers go on a small line under the name. The sorted column's header is bold in
   the text color (the theme's blue on the header's gray was under WCAG AA's 4.5:1, F#119). 1.7.1 review: on a phone
   (700 px or less) the filter box is 16 px: iOS Safari zooms into a smaller one when it is tapped and leaves the page
   wider than the screen (as F#43 found for the pilot lookup). 1.7.8: a header's words wrap, and on a card 900 px wide or
   less (an iPad) the name and layover cells wrap too and the cells are tighter, so the whole table, Avg Pickup Speed included, fits a Mac or
   iPad card without a sideways scroll. The phone layout (Pilot, Pos, Best, Avg) now starts at a 700 px card, not
   500, so an iPad in split view or a phone on its side gets it too.
   1.7.16 (Ryan, Nov 17: "show median time to pickup by layover city and by day of week/time of day, so I know when to
   run Hunt"): a When to hunt section at the top: the tip (the fastest HST day and time of day with 5 or more pickups)
   and three small tables, by layover, by the HST day and by the HST time of day the trip entered the pot, each by
   median (the groups of 5 or more first; fewer are grey, too few to trust). It reads the sensor's speed attribute
   (the Watcher's aggregates of the pickups this card counts), so it is the same on the pilot portal; collapsed when
   its tables run long, and as the viewer left it after that.
   1.7.16 review: the section sits under the header, outside the pickers list, so the tip shows while the list is
   collapsed (the dashboard and the portal mount the card collapsed, R1); an open or close the viewer made any way
   (a tap, the keyboard, find in page: the details' toggle event) is kept, and an update changes the tip and tables
   in place, so a focused summary keeps its focus (R3); an empty table says so (R4); the tip's day and time of day
   never split across two lines (R5). */
const FMT = (a) => a == null ? "-" : a >= 3600 ? `${Math.floor(a / 3600)}h ${String(Math.floor((a % 3600) / 60)).padStart(2, "0")}m`
  : a >= 60 ? `${Math.floor(a / 60)}m ${String(a % 60).padStart(2, "0")}s` : `${a}s`;
// 1.7.10 (Ryan, Nov 15): a speed capped at your own request time (FLICA denied your request for the trip because
// this pilot had picked it up, so he asked before you did) is an upper bound: "at most", shown with the sign ≤
const CAPPED = (on, a, what) => (!on || a == null ? FMT(a)
  : `<span title="${what} ${FMT(a)}, capped at your request time" aria-label="${what} ${FMT(a)}, capped at your request time"><span aria-hidden="true">≤</span>${FMT(a)}</span>`);
// 1.7.16: When to hunt. A median with a capped speed among its pickups is an upper bound too ("at most")
const HUNT_OPEN_ROWS = 12;  // the three tables open by default with this many rows or fewer, else collapsed
const HCAP = (on, a, title) => (!on || a == null ? FMT(a)
  : `<span title="${title}" aria-label="${title}"><span aria-hidden="true">≤</span>${FMT(a)}</span>`);
// [speed key, caption, first header, what an empty table says (review R4)]
const HUNT_TABLES = [["city", "Layover", "Station", "No layover on file yet."],
  ["dow", "Day (HST)", "Day", "No pot entry time on file yet."], ["band", "Time (HST)", "Entered", "No pot entry time on file yet."]];
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
    const sp = st && st.attributes && st.attributes.speed && typeof st.attributes.speed === "object" ? st.attributes.speed : null;
    const sig = JSON.stringify(rows) + "|" + JSON.stringify(sp);
    if (sig === this._sig && this._root) return;
    this._sig = sig;
    this._rows = rows;
    this._speed = sp;  // 1.7.16: When to hunt
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
        @media (max-width:700px){input{font-size:16px}}
        .wrap{overflow-x:auto}
        table{border-collapse:collapse;font-size:13px;width:100%}
        th,td{border:1px solid var(--divider-color,#ddd);padding:3px 6px;white-space:nowrap}th{white-space:normal;vertical-align:bottom}
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
        @container (max-width:900px){td.pn,td.lay{white-space:normal}th,td{padding:3px 4px}}
        @container (max-width:700px){.wide{display:none}th .lg{display:none}th .sh{display:inline}.sm{display:block}
          td.pn{white-space:normal}table{font-size:12px}th,td{padding:3px 4px}}
        .key{font-size:11px;opacity:.8;margin:6px 0 0}
        details summary{cursor:pointer;font-size:12px}
        .hunt{margin:4px 0 6px;padding:8px 10px;border:1px solid var(--divider-color,#ddd);border-radius:8px}
        .htl{font-weight:600;font-size:14px}.tip{margin:4px 0 6px;font-size:13px}
        .hunt summary{padding:4px 0}
        .tbls{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px 12px;margin-top:6px;align-items:start}
        .nb{white-space:nowrap}
        .tbls table{font-size:12px}.tbls caption{text-align:left;font-weight:600;padding:2px 0}
        .tbls th{cursor:default;position:static;white-space:nowrap}
        tr.few td{color:var(--secondary-text-color);font-style:italic}
        .tbls td.none{white-space:normal;color:var(--secondary-text-color)}
        .note,.more{font-size:11px;color:var(--secondary-text-color);margin:6px 0 0}
        .vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
      </style><ha-card><div class="hd"><span class="tri"></span><span class="ttl"></span></div><div class="hunt-box"></div><div class="body">
        <label class="fl" for="flt">Filter this list (it does not ask FLICA)</label>
        <input id="flt" type="search" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="Filter this list (name, emp or layover)">
        <div class="wrap"><table class="pk"><thead><tr></tr></thead><tbody></tbody></table></div>
        <details><summary>&#9656; Key</summary><div class="key">Tap a column header to sort, tap again to flip. Bold row = 1 min or under. Ttl = all pickups seen; Month / Year = this HST month and year; InFlt = picked up while airborne; Common Layover = stations they pick up most, with how many (bold = their latest pickup); Fastest / Avg Pickup Speed = the pilot's quickest grab and their average time a trip sat in open time; ≤ = at most: a speed capped at your own request time, when FLICA denied your request because that pilot picked the trip up first.</div></details>
      </div></ha-card>`;
      this._root.querySelector(".hd").addEventListener("click", () => { this._open = !this._open; this._paint(); });
      this._root.querySelector("input").addEventListener("input", (e) => { this._q = e.target.value; this._paint(); });
      this._root.querySelector("input").addEventListener("keydown", (e) => e.stopPropagation());  // v4: keep HA's e/a/c shortcuts out of the field
      const hb = this._root.querySelector(".hunt-box");
      hb.addEventListener("click", (e) => {  // 1.7.16: the viewer's open / closed stays
        const s = e.target.closest("summary");
        if (!s) return;
        this._huntOpen = this._huntShown = !s.parentElement.open;
      });
      // review R3: an open or close without a click (find in page opens a closed details) comes as a toggle event, which
      // does not bubble: caught on the way down. One the card made itself (_huntShown) is not the viewer's
      hb.addEventListener("toggle", (e) => {
        const d = e.target;
        if (!d || d.tagName !== "DETAILS" || !d.isConnected || d.open === this._huntShown) return;
        this._huntOpen = this._huntShown = d.open;
      }, true);
      this._root.querySelector(".pk tbody").addEventListener("click", (e) => {  // v2: tap a name -> pilot schedule card
        const td = e.target.closest("td.pn");
        if (td) window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { emp: td.dataset.emp, name: td.dataset.name } }));
      });
      const tr = this._root.querySelector(".pk thead tr");
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
    this._paintHunt();
    r.querySelectorAll(".pk th").forEach((th) => {
      th.classList.toggle("on", th.dataset.k === this._sort.key);
      th.classList.toggle("d", th.dataset.k === this._sort.key && this._sort.dir === -1);
    });
    r.querySelector(".pk tbody").innerHTML = rows.length ? rows.map((p) => {
      const lays = (p.lays || []).slice(0, 4).map((l) => `${l[0] === p.last_lay ? "<b>" + this._esc(l[0]) + "</b>" : this._esc(l[0])}<sub>${l[1]}</sub>`).join("");
      // 1.7.1 (F#52): what a narrow card folds under the name (the Emp to Common Layover columns)
      const sm = `Emp ${this._esc(p.emp)} &middot; ${p.n} pickups: ${p.month_n || 0} this month, ${p.year_n || 0} this year, ${p.inflt_n || 0} in flight${lays ? ` &middot; <span class="lay">${lays}</span>` : ""}`;
      return `<tr class="${p.avg_s != null && p.avg_s <= 60 ? "fast" : ""}"><td class="pn" data-emp="${this._esc(p.emp)}" data-name="${this._esc(p.name)}" title="tap: this pilot's month"><span class="nm">${this._esc(p.name)}</span><div class="sm">${sm}</div></td><td class="wide">${this._esc(p.emp)}</td><td>${this._esc(p.pos)}</td>
        <td class="n wide">${p.n}</td><td class="n wide">${p.month_n || 0}</td><td class="n wide">${p.year_n || 0}</td><td class="n wide">${p.inflt_n || 0}</td>
        <td class="lay wide">${lays || "-"}</td><td class="n">${CAPPED(p.min_cap, p.min_s, "at most")}</td><td class="n">${CAPPED(p.cap_n > 0, p.avg_s, `at most: ${p.cap_n} of ${p.n} pickups`)}</td></tr>`;
    }).join("") : `<tr><td colspan="10">${this._q ? "No match." : "No pickups scored yet."}</td></tr>`;
  }
  // 1.7.16: When to hunt, from the sensor's speed attribute ({n, min_n, city, dow, band, tip, more}; each group
  // [label, n, median_s, fastest_s, capped_n, fastest_capped]). Review R3: the section is built once and its tip,
  // summary and tables are changed in place when the speed changes (a focused summary keeps its focus)
  _paintHunt() {
    const box = this._root.querySelector(".hunt-box");
    const sp = this._speed;
    const lists = HUNT_TABLES.map(([k]) => (sp && Array.isArray(sp[k]) ? sp[k] : []));
    if (!sp || !(sp.n > 0) || !lists.some((l) => l.length)) {
      if (box.innerHTML) box.innerHTML = "";
      this._huntSig = "";
      return;
    }
    const total = lists.reduce((a, l) => a + l.length, 0);
    const open = this._huntOpen == null ? total <= HUNT_OPEN_ROWS : this._huntOpen;
    if (!box.firstElementChild) {
      box.innerHTML = `<section class="hunt" aria-label="When to hunt"><div class="htl">When to hunt</div><p class="tip"></p>
        <details><summary></summary><div class="tbls"></div><p class="more" hidden></p><p class="note"></p></details></section>`;
      this._huntSig = "";
      this._huntShown = false;
    }
    const det = box.querySelector("details");
    if (det.open !== open) {
      this._huntShown = open;  // the card's own change: its toggle event is not the viewer's
      det.open = open;
    }
    const sig = JSON.stringify(sp);
    if (sig === this._huntSig) return;
    this._huntSig = sig;
    const min = sp.min_n || 5;
    const table = ([, cap, head, none], list) => `<table><caption>${cap}</caption><thead><tr><th scope="col">${head}</th>
      <th scope="col">Median</th><th scope="col">Fastest</th><th scope="col">n</th></tr></thead><tbody>${list.length ? "" : `<tr><td colspan="4" class="none">${none}</td></tr>`}${list.map((g) => {
        const [k, n, med, fast, capN, fastCap] = g;
        const few = n < min;
        return `<tr${few ? ` class="few" title="${n} pickup${n === 1 ? "" : "s"}: too few to trust (under ${min})"` : ""}>`
          + `<td>${this._esc(k)}${few ? `<span class="vh"> (too few to trust)</span>` : ""}</td>`
          + `<td class="n">${HCAP(capN > 0, med, `median at most ${FMT(med)}: ${capN} of ${n} capped at your request time`)}</td>`
          + `<td class="n">${HCAP(!!fastCap, fast, `at most ${FMT(fast)}: capped at your request time`)}</td>`
          + `<td class="n">${n}</td></tr>`;
      }).join("")}</tbody></table>`;
    // review R5: the day and the time of day of a slot ("Tue 18-24 HST") stay on one line
    box.querySelector(".tip").innerHTML = this._esc(sp.tip || `No tip yet: no day or time of day has ${min} pickups.`)
      .replace(/\b((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?\d\d-\d\d HST)\b/g, '<span class="nb">$1</span>');
    box.querySelector("summary").textContent = `By layover, day and time (${sp.n} pickup${sp.n === 1 ? "" : "s"})`;
    box.querySelector(".tbls").innerHTML = HUNT_TABLES.map((t, i) => table(t, lists[i])).join("");
    const more = box.querySelector(".more");
    more.hidden = !(sp.more > 0);
    more.textContent = sp.more > 0 ? `${sp.more} more layover${sp.more === 1 ? "" : "s"} with fewer pickups not shown.` : "";
    box.querySelector(".note").textContent = `The median time a trip sat in open time before it was picked up, by where
      it lays over (the first station of its layover, else of its turn) and the HST day and time it entered the pot:
      the pickups the pickers list counts, a trip with both seats open once. Grey = fewer than ${min} pickups, too few
      to trust (never the tip). ≤ = at most: a speed capped at your own request time is among them.`.replace(/\s+/g, " ");
  }
}
customElements.define("flight-watcher-pickers-card", FlightWatcherPickersCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pickers-card", name: "Flight Watcher pickers", description: "Sortable FO / RO pickers table" });

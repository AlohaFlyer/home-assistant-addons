"""FW-0069 (1.4.11): schedule versions on the pilot card, M.NNN like the schedule card's. Rendered in node with a small
stub DOM and a stub fetch: the bar under the header (count, version, arrows that stop at the ends, the house back to the
current one, "Changes in vX"), the list file fetched once per key|rev from /local/flight-watcher/pilotver_<key>.json, an
older version drawn from its own days and trips (not the live ones), the current version drawn exactly as before, a
quiet card when the sensor has no versions or the file fails, and the second pilot's copy reading its own folder.
Made-up pilots ("Doe, Jane", 10001) and made-up pairings only."""
import json
import os
import re
import shutil
import subprocess

import pytest

import cards

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-pilot-card.js")
KEY = "0123456789abcdef0123456789abcdef"
STUB = """
globalThis.HTMLElement = class { constructor() { this.style = {}; }
  attachShadow() { const body = {innerHTML: "", insertAdjacentHTML(p, h) { this.innerHTML += h; }};
    this.shadowRoot = {innerHTML: "", body, on: {}, addEventListener(t, f) { this.on[t] = f; },
      querySelector: (s) => (s === ".body" ? body : null)}; return this.shadowRoot; }
  scrollIntoView() {} };
globalThis.customElements = {define() {}, get() {}};
globalThis.window = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, customCards: []};
globalThis.location = {hash: "", pathname: "/", search: ""}; globalThis.history = {replaceState() {}};
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = (o || {}).detail; } };
const FETCHED = []; let FILE = null;
globalThis.fetch = (u, o) => { FETCHED.push([u, (o || {}).cache]); return Promise.resolve({ ok: !!FILE, json: () => Promise.resolve(FILE) }); };
const tick = () => new Promise((r) => setTimeout(r, 10));
const html = (c) => c.shadowRoot.body.innerHTML;
const tap = (c, v) => c.shadowRoot.on.click({ target: { closest: (s) => (s === ".vb" ? { dataset: { v } } : null) } });
const card = (entity) => { const c = new FlightWatcherPilotCard(); c.setConfig({}); c._ent = entity || c._config.entity; return c; };
const show = (c, a, sig) => { c.hass = {states: {[c._ent]: {last_updated: sig || "1", attributes: a}}, callService() {}}; return html(c); };
"""


def _days(first, last, trips):
    """FLICA's grid rows [iso, code, lay] from first to last, each trip's code on its first day, its layovers after."""
    from datetime import date, timedelta
    at = {}
    for trip, s, e, lay in trips:
        d0, d1 = date.fromisoformat(s), date.fromisoformat(e)
        at[s] = [trip, lay]
        d = d0 + timedelta(days=1)
        while d <= d1:
            at[d.isoformat()] = ["", "HNL" if d == d1 else "-"]
            d += timedelta(days=1)
    out, d = [], date.fromisoformat(first)
    while d <= date.fromisoformat(last):
        out.append([d.isoformat(), *at.get(d.isoformat(), ["", ""])])
        d += timedelta(days=1)
    return out


A = ("H3101", "2026-11-03", "2026-11-05", "LAX")
B = ("H3205", "2026-11-12", "2026-11-14", "SFO")
C = ("H3300", "2026-11-20", "2026-11-22", "NRT")


def _items(*trips):
    return [{"trip": t, "start": s, "end": e, "lay": lay} for t, s, e, lay in trips]


def _rec(n, at, source, trips, changes, totals=None, updated=""):
    return {"ver": f"11.{n:03d}", "n": n, "at": at, "source": source, "updated": updated, "items": _items(*trips),
            "days": _days("2026-10-31", "2026-12-01", trips), "totals": totals or {}, "changes": changes}


RECS = [_rec(1, "2026-10-20T02:00:00Z", "award", [A, C], ["first version on file (awarded line)"]),
        _rec(2, "2026-11-02T04:00:00Z", "rebuild", [A, C, B], ["added H3205 Nov 12-14 SFO"]),
        _rec(3, "2026-11-09T01:20:00Z", "lookup", [A, B], ["removed H3300 Nov 20-22 NRT"],
             {"block": "20:00", "credit": "24:00", "days_off": 24}, "11/08/2026 15:10")]
FILE = {"10001": {"name": "Doe, Jane", "months": {"2026-11": RECS}}}
VERS = {"2026-11": {"count": 3, "current": "11.003", "awarded": "11.001"}}


def _live(**kw):
    """The live payload (a readable FLICA month): H3101 and H3205 with their block, credit and crew."""
    items = [{**it, "blk": "9:58", "credit": "12:34", "soft": "2:36", "crew": [["CA", "Roe, Rick"], ["FO", "Doe, Jane"]]}
             for it in _items(A, B)]
    a = {"emp": "10001", "name": "Doe, Jane", "status": "ok", "month": "2026-11", "updated": "11/08/2026 15:10",
         "fetched": "2026-11-09T01:20:00Z", "days": _days("2026-10-31", "2026-12-01", [A, B]), "items": items,
         "totals": {"block": "20:00", "credit": "24:00", "days_off": 24},
         "versions": VERS, "versions_file_key": KEY, "versions_rev": 7}
    a.update(kw)
    return {k: v for k, v in a.items() if v is not None}


def _node(tmp_path, body, src=None, file=FILE):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    f = tmp_path / "t.js"
    f.write_text(STUB + (src if src is not None else open(CARD, encoding="utf-8").read()) +
                 f"\nFILE = {json.dumps(file)};\n(async () => {{\n" + body + "\n})();")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _bar(h):
    """The versions bar (and the changes list right under it), '' when there is none."""
    if '<div class="vbar">' not in h:
        return ""
    i = h.index('<div class="vbar">')
    j = h.index("</div>", i) + len("</div>")
    if h[j:].startswith('<details class="chg"'):
        j = h.index("</details>", j) + len("</details>")
    return h[i:j]


def _grid(h):
    """The main grid only (not the live rebuild folded under it)."""
    return h.split('<details class="rb">')[0]


def test_bar_counts_steps_and_returns_to_current(tmp_path):
    r = _node(tmp_path, f"""
      const c = card(), a = {json.dumps(_live())};
      const r = {{}};
      r.before = show(c, a);  // the sensor's counts at once; the file is still on its way
      await tick();
      r.cur = html(c);
      tap(c, "prev"); r.v2 = html(c);
      tap(c, "prev"); r.v1 = html(c);
      tap(c, "prev"); r.v1again = html(c);  // the oldest: the arrow stops
      tap(c, "next"); r.next = html(c);
      tap(c, "home"); r.home = html(c);
      tap(c, "next"); r.end = html(c);  // the newest: the arrow stops
      show(c, a, "2"); r.repaint = html(c);  // the same rev again: no second fetch
      r.fetched = FETCHED;
      console.log(JSON.stringify(r));
    """)
    b0 = _bar(r["before"])
    assert "<b>v11.003</b>" in b0 and "3 versions (current)" in b0 and "Changes in" not in b0
    assert '<span class="vb off" data-v="prev"' in b0  # nothing older to step to until the file is in
    b = _bar(r["cur"])
    assert "<b>v11.003</b>" in b and '<span class="nw">3 versions (current)</span>' in b
    assert '<span class="vb" data-v="prev"' in b and '<span class="vb off" data-v="next"' in b
    assert '<span class="vb here" data-v="home" title="Current version">&#127968;</span>' in b
    assert "Changes in v11.003 (Nov 8 15:20 HST)" in b and "<li>removed H3300 Nov 20-22 NRT</li>" in b
    assert r["cur"].index('<div class="hd">') < r["cur"].index('<div class="vbar">') < r["cur"].index('<table class="cal">')
    b2 = _bar(r["v2"])
    assert "<b>v11.002</b>" in b2 and "3 versions · viewing" in b2 and "Nov 1 18:00 HST" in b2 and "(rebuilt)" in b2
    assert '<span class="vb" data-v="next"' in b2 and '<span class="vb" data-v="home"' in b2 and "here" not in b2
    assert "Changes in v11.002" in b2 and "<li>added H3205 Nov 12-14 SFO</li>" in b2
    b1 = _bar(r["v1"])
    assert "<b>v11.001</b>" in b1 and "Oct 19 16:00 HST" in b1 and "(awarded line)" in b1
    assert '<span class="vb off" data-v="prev"' in b1 and "first version on file (awarded line)" in b1
    assert r["v1again"] == r["v1"]
    assert "<b>v11.002</b>" in _bar(r["next"])
    assert r["home"] == r["cur"] and r["end"] == r["cur"] and r["repaint"] == r["cur"]
    assert r["fetched"] == [[f"/local/flight-watcher/pilotver_{KEY}.json?r=7", "no-store"]]


def test_older_version_draws_its_own_trips(tmp_path):
    r = _node(tmp_path, f"""
      const c = card(); show(c, {json.dumps(_live())}); await tick();
      const cur = html(c); tap(c, "prev"); tap(c, "prev");
      console.log(JSON.stringify({{cur, v1: html(c)}}));
    """)
    cur, v1 = _grid(r["cur"]), _grid(r["v1"])
    assert ">H3205</span>" in cur and ">H3300</span>" not in cur
    assert ">H3300</span>" in v1 and ">H3205</span>" not in v1 and ">H3101</span>" in v1  # the award's line, not the live one
    assert "<b>NRT</b>" in v1 and "<b>SFO</b>" not in v1
    assert v1.count(" bxs") == 2 and v1.count(" bxe") == 2  # each of its trips boxed, like the live grid
    # H3101 is still on the live line: its live block, credit and crew; H3300 is not: no crew, no block
    row = [x for x in v1.split("<tr")[1:] if ">H3101</span>" in x][0]
    assert "9:58" in row and "12:34" in row and "CA Roe, Rick · FO Doe, Jane" in row
    row = [x for x in v1.split("<tr")[1:] if ">H3300</span>" in x][0]
    assert "Roe, Rick" not in row and "9:58" not in row
    # its own totals (the award has none from FLICA): the trip count; the note says what is live
    assert "<span>Trips<b>2</b></span>" in v1 and "Block<b>20:00</b>" not in v1
    assert "v11.001 as captured Oct 19 16:00 HST, the awarded line. Block / Credit per trip, crew and pay shown are the live ones." in v1
    assert "Source: FLICA Tools > Schedule Lookup" not in v1  # the live totals line belongs to the current version


def test_current_version_is_the_card_as_before(tmp_path):
    """Viewing the newest version draws the live payload exactly as without versions (the bar aside)."""
    r = _node(tmp_path, f"""
      const plain = card(), c = card();
      const p = show(plain, {json.dumps(_live(versions=None, versions_file_key=None, versions_rev=None))});
      show(c, {json.dumps(_live())}); await tick();
      console.log(JSON.stringify({{p, v: html(c), fetched: FETCHED.length}}));
    """)
    b = _bar(r["v"])
    assert b and r["v"].replace(b, "") == r["p"] and "vbar" not in r["p"]
    assert r["fetched"] == 1


def test_lookup_version_shows_flica_totals_and_rebuilt_month_gets_the_bar(tmp_path):
    """An older lookup version shows FLICA's totals as read then; a month FLICA would not show (the crew index's
    rebuilt month) gets the bar too, and an older version there folds the live rebuild under its own grid."""
    v4 = _rec(4, "2026-11-09T19:00:00Z", "rebuild", [A, B, C], ["added H3300 Nov 20-22 NRT"])
    file = {"10001": {"name": "Doe, Jane", "months": {"2026-11": RECS + [v4]}}}
    rb = [{"pairing": t, "start": s, "end": e, "seat": "FO", "route": f"HNL-{lay}-HNL", "checked_at": "2026-11-09T08:00:00",
           "blk": "9:00", "credit": "10:00", "crew": [["CA", "Roe, Rick"], ["FO", "Doe, Jane"]]} for t, s, e, lay in (A, B, C)]
    a = _live(month="", days=None, items=None, totals=None, status="not readable: error",
              versions={"2026-11": {"count": 4, "current": "11.004", "awarded": "11.001"}}, reconstructed_month="2026-11",
              reconstructed_from="2026-11-01", reconstructed_to="2026-12-01", reconstructed_coverage_pct=90, reconstructed=rb)
    r = _node(tmp_path, f"""
      const c = card(); show(c, {json.dumps(a)}); await tick();
      const cur = html(c); tap(c, "prev"); const v3 = html(c); tap(c, "prev"); tap(c, "prev");
      console.log(JSON.stringify({{cur, v3, v1: html(c)}}));
    """, file=file)
    b = _bar(r["cur"])
    assert "<b>v11.004</b>" in b and "4 versions (current)" in b
    assert '<div class="rb"><div class="rbh">' in r["cur"]  # the current version: the rebuild open, as before
    assert r["cur"].index('<div class="vbar">') < r["cur"].index('<div class="rb">')
    v3 = r["v3"]
    assert "<b>v11.003</b>" in _bar(v3) and "(FLICA schedule)" in _bar(v3)
    assert "Block<b>20:00</b>" in v3 and "Credit<b>24:00</b>" in v3 and "Days Off<b>24</b>" in v3
    assert "FLICA Tools > Schedule Lookup (FLICA updated 11/08/2026 15:10)" in v3
    assert ">H3300</span>" not in _grid(v3)
    assert '<details class="rb"><summary>' in v3 and '<div class="rb"><div class="rbh">' not in v3  # the live rebuild, folded
    row = [x for x in _grid(r["v1"]).split("<tr")[1:] if ">H3300</span>" in x][0]
    assert "9:00" in row and "Roe, Rick" in row  # a trip on the live rebuild: its live block and crew


def test_no_versions_or_no_file_is_quiet(tmp_path):
    hostile = {"10001": {"name": "Doe, Jane", "months": {"2026-11": [
        {**RECS[0], "ver": "<img src=x>", "changes": ['<script>alert(1)</script>']}, RECS[2]]}}}
    r = _node(tmp_path, f"""
      const r = {{}};
      const old = card(); r.old = show(old, {json.dumps(_live(versions=None, versions_file_key=None, versions_rev=None))});
      const nokey = card(); r.nokey = show(nokey, {json.dumps(_live(versions_file_key="../../x"))}); tap(nokey, "prev"); r.nokeyTap = html(nokey);
      r.fetchedA = FETCHED.length;
      FILE = null; const fail = card(); show(fail, {json.dumps(_live())}); await tick(); tap(fail, "prev"); r.fail = html(fail);
      FILE = {json.dumps({"10002": FILE["10001"]})}; const other = card(); show(other, {json.dumps(_live(versions_rev="r9"))}); await tick(); r.other = html(other);
      FILE = {json.dumps(hostile)}; const bad = card(); show(bad, {json.dumps(_live(versions_rev="r10"))}); await tick(); tap(bad, "prev"); r.bad = html(bad);
      const odd = card(); r.odd = show(odd, {json.dumps(_live(versions={"2026-11": "x", "2026-12": None}))});
      const pick = card(); r.pick = show(pick, {{name: "Doe", status: "2 pilots named Doe", matches: [{{emp: "10001", name: "Doe, Jane", pos: "FO"}}], versions: {json.dumps(VERS)}}});
      r.fetched = FETCHED.map((f) => f[0]);
      console.log(JSON.stringify(r));
    """)
    assert "vbar" not in r["old"] and r["fetchedA"] == 0  # an older Watcher: no bar, no fetch
    assert "<b>v11.003</b>" in _bar(r["nokey"]) and "Changes in" not in r["nokey"] and r["nokeyTap"] == r["nokey"]
    for k in ("fail", "other"):  # the file did not load, or holds another pilot: the sensor's counts, nothing to step to
        b = _bar(r[k])
        assert "3 versions (current)" in b and '<span class="vb off" data-v="prev"' in b and "Changes in" not in b, k
        assert ">H3205</span>" in _grid(r[k]), k
    assert "<img" not in r["bad"] and "&lt;img src=x&gt;" in r["bad"] and "<script>" not in r["bad"]
    assert "vbar" not in r["odd"] and "vbar" not in r["pick"]
    assert r["fetched"] == [f"/local/flight-watcher/pilotver_{KEY}.json?r=7", f"/local/flight-watcher/pilotver_{KEY}.json?r=r9",
                            f"/local/flight-watcher/pilotver_{KEY}.json?r=r10"]


def test_a_new_pilot_or_month_starts_at_current(tmp_path):
    file2 = {"10002": {"name": "Roe, Rick", "months": {"2026-11": RECS}}}
    r = _node(tmp_path, f"""
      const c = card(); const a = {json.dumps(_live())};
      show(c, a); await tick(); tap(c, "prev"); const older = html(c);
      show(c, a, "2"); const same = html(c);  // the same pilot again (a cached reply): still the version picked
      FILE = {json.dumps(file2)};
      show(c, {{...a, emp: "10002", name: "Roe, Rick", versions_rev: 8}}, "3"); await tick(); const other = html(c);
      FILE = {json.dumps(FILE)};
      show(c, {{...a, versions_rev: 9}}, "4"); await tick(); const back = html(c);
      console.log(JSON.stringify({{older, same, other, back}}));
    """)
    assert "<b>v11.002</b>" in _bar(r["older"]) and r["same"] == r["older"]
    assert "<b>v11.003</b>" in _bar(r["other"]) and "(current)" in _bar(r["other"]) and "Roe, Rick (10002)" in r["other"]
    assert "<b>v11.003</b>" in _bar(r["back"]) and "(current)" in _bar(r["back"])


def test_card_source_keeps_the_list_path_and_no_em_dash():
    src = open(CARD, encoding="utf-8").read()
    assert '"/local/flight-watcher/pilotver_"' in src  # cards.pilot_copy moves this literal for a second pilot
    assert chr(0x2014) not in src


def test_second_pilot_copy_reads_its_own_file(tmp_path):
    """James's copy reads sensor.flight_watcher_james_pilot_schedule and his own www folder. Needs pilotver in the
    cards.pilot_copy list-file regex (the Python side of FW-0069)."""
    src = cards.pilot_copy(open(CARD, encoding="utf-8").read(), "james")
    r = _node(tmp_path, f"""
      const c = card(); show(c, {json.dumps(_live())}); await tick();
      console.log(JSON.stringify({{ent: c._config.entity, h: html(c), fetched: FETCHED.map((f) => f[0])}}));
    """, src=src)
    assert r["ent"] == "sensor.flight_watcher_james_pilot_schedule"
    assert r["fetched"] == [f"/local/flight-watcher/james/pilotver_{KEY}.json?r=7"]
    assert "Changes in v11.003" in r["h"]
    assert not re.search(r'"/local/flight-watcher/pilotver_"', src)

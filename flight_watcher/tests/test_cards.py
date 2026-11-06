"""0.10.2: dashboard cards deployed by the add-on (cards.py). Synthetic dates only."""
import json
import os

import cards
import run


def test_repo_cards_hold_no_real_doh():
    for name, s in cards.sources().items():
        for m in cards.DOH_RE.finditer(s):
            assert m.group(1) == cards.PLACEHOLDER_DOH, name


def test_build_lists_every_card_and_pilot_copy():
    f = cards.build("9.9.9", "1999-02-03", ["pilot2"])
    m = json.loads(f[cards.MANIFEST])
    assert m["version"] == "9.9.9"
    assert "flight-watcher-schedule-card.js" in m["cards"] and "flight-watcher-schedule-card-pilot2.js" in m["cards"]
    assert set(m["cards"]) | {cards.MANIFEST, cards.LOADER} == set(f)
    assert 'DOH = "1999-02-03"' in f["flight-watcher-schedule-card.js"]
    p = f["flight-watcher-schedule-card-pilot2.js"]
    assert f'DOH = "{cards.PLACEHOLDER_DOH}"' in p and "1999-02-03" not in p
    assert 'customElements.define("flight-watcher-schedule-card-pilot2"' in p
    assert "sensor.flight_watcher_pilot2_" in p and "Ryan" not in p
    assert cards.MANIFEST in f[cards.LOADER] and "no-store" in f[cards.LOADER]


def test_pilot_copy_moves_every_per_pilot_name():
    f = cards.build("1", "1999-02-03", ["pilot2"])
    sch, rec, pk = f["flight-watcher-schedule-card-pilot2.js"], f["flight-watcher-recall-card-pilot2.js"], f["flight-watcher-pickers-card-pilot2.js"]
    assert "input_number.flight_watcher_pilot2_month_offset" in sch and "input_number.flight_watcher_month_offset" not in sch
    assert 'localStorage.getItem("flight_watcher_pilot2_' in sch and "flight_watcher_pilot2_pilot2" not in sch
    assert "/local/flight-watcher/pilot2/finds_" in f["flight-watcher-finds-card-pilot2.js"]
    assert "/local/flight-watcher/pairings_" in sch  # pairings stay shared
    assert '"/flight-watcher-pilot2/recall"' in rec and "flight_watcher_pilot2/" in rec
    assert '"flight-watcher-pilot-pilot2"' in pk and '"flight-watcher-pilot"' not in pk
    for name, text in f.items():  # no pre-rename name survives in any card, original or copy
        for old in ("flica_watcher", "flica-", "flica_rule", ".flica_", "/flica/", 'Item("flica_', "FLICA Watcher"):
            assert old not in text, (name, old)


def test_bad_pilot_name_skipped():
    f = cards.build("1", None, ["../x"])
    assert not any("../" in n for n in f)


def test_deploy_migrates_doh_and_writes_only_changes(tmp_path):
    dst, settings = tmp_path / "www", tmp_path / "cards.json"
    dst.mkdir()
    (dst / "flight-watcher-schedule-card.js").write_text('const DOH = "1990-01-01";\n')
    w1 = cards.deploy("1.0", [], dst=str(dst), settings=str(settings))
    assert json.loads(settings.read_text()) == {"doh": "1990-01-01"}
    assert 'DOH = "1990-01-01"' in (dst / "flight-watcher-schedule-card.js").read_text()
    assert cards.LOADER in w1 and "flight-watcher-clock-card.js" in w1
    assert cards.deploy("1.0", [], dst=str(dst), settings=str(settings)) == []
    assert cards.deploy("1.1", [], dst=str(dst), settings=str(settings)) == [cards.MANIFEST]
    assert not any(n.endswith(".tmp") for n in os.listdir(dst))


def test_deploy_without_www_or_doh(tmp_path):
    assert cards.deploy("1", [], dst=str(tmp_path / "missing"), settings=str(tmp_path / "s.json")) == []
    dst = tmp_path / "www"
    dst.mkdir()
    cards.deploy("1", [], dst=str(dst), settings=str(tmp_path / "s.json"))
    assert f'DOH = "{cards.PLACEHOLDER_DOH}"' in (dst / "flight-watcher-schedule-card.js").read_text()
    assert not (tmp_path / "s.json").exists()


def test_app_version_read_without_import():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v = run.app_version(os.path.join(here, "watcher.py"))
    assert v == open(os.path.join(here, "config.yaml")).read().split('version: "')[1].split('"')[0]


def test_every_entity_a_card_reads_is_one_discovery_creates(tmp_path, monkeypatch):
    """1.0.0 review: the cards' entity literals must equal discovery's default_entity_ids (both instances)."""
    import json as _json
    import re as _re
    import sys
    from test_instance import FakeClient, _load
    opts = {"username": "u", "password": "p", "log_level": "info", "category_check": "HNL 332 FO"}
    made = set()
    for inst in ("", "pilot2"):
        (tmp_path / (inst or "ryan")).mkdir()
        W = _load(tmp_path / (inst or "ryan"), monkeypatch, inst, opts)
        c = FakeClient()
        W.discovery(c)
        made |= {_json.loads(p)["default_entity_id"] for t, p, _ in c.msgs if t.endswith("/config") and p}
        sys.modules.pop("watcher", None)
    f = cards.build("1", None, ["pilot2"])
    used = set()
    for text in f.values():
        used |= set(_re.findall(r"\b(?:sensor|switch|button|number|select|binary_sensor)\.flight_watcher_[a-z0-9_]+", text))
    missing = {e for e in used if e not in made and not e.startswith("switch.flight_watcher_rule")}
    assert not missing, sorted(missing)


def test_finds_card_time_format_is_browser_independent(tmp_path):
    """1.1.1 FW-0001: the finds card builds "Nov 5 12:23" from parts (iOS Safari's toLocaleString adds 'at')."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        import pytest
        pytest.skip("node not installed")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-finds-card.js"),
               encoding="utf-8").read()
    js = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n" + src +
          "\nconst c = new FlightWatcherFindsCard();\n"
          "console.log(JSON.stringify([c._t('2026-11-05T22:23:00Z'), c._t('2026-11-06T10:05:00Z'), c._t(''), c._t('bad')]));")
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["Nov 5 12:23", "Nov 6 00:05", "", "bad"]


def test_finds_card_shows_today_hst_and_folds_the_rest(tmp_path):
    """FW-0005 (Ryan): this month shows only the finds first seen today in HST (UTC-10); every earlier one folds under
    "N earlier this month", closed until opened and remembered per browser (localStorage, which may throw). A past
    month opens in full. Synthetic trips and names."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        import pytest
        pytest.skip("node not installed")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-finds-card.js"),
               encoding="utf-8").read()
    now = "2026-11-07T09:30:00Z"  # Nov 6 23:30 HST: the UTC date is already Nov 7

    def find(pid, seen):
        return {"pairing": pid, "seen": seen, "dates": "08Nov-10Nov", "layover": "LAX", "days": "3", "credit": "12:34",
                "captain": "Doe, Jane (12345)"}
    rows = [find("H9001", "2026-11-07T09:00:00Z"),   # Nov 6 23:00 HST: today
            find("H9002", "2026-11-06T10:00:00Z"),   # Nov 6 00:00 HST: today (midnight)
            find("H9003", "2026-11-06T09:59:00Z"),   # Nov 5 23:59 HST: earlier, though the UTC date is Nov 6
            find("H9004", "2026-11-01T10:05:00Z"),   # Nov 1 00:05 HST
            find("H9005", "not a time")]
    js = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n"
          "const store = new Map(); globalThis.localStorage = {getItem: (k) => store.has(k) ? store.get(k) : null,"
          " setItem: (k, v) => store.set(k, String(v))};\n" + src +
          f"\nconst rows = {json.dumps(rows)}; const now = Date.parse({json.dumps(now)});\n"
          "const tr = (h) => (h.match(/<tr class/g) || []).length;\n"
          "const parts = (h) => { const i = h.indexOf('<details'); return i < 0 ? [h, ''] : [h.slice(0, i), h.slice(i)]; };\n"
          "const tag = (h) => parts(h)[1].split('>')[0] + '>';\n"
          "const card = () => { const c = new FlightWatcherFindsCard(); c.setConfig({}); c._m = '2026-11'; return c; };\n"
          "const c = card(); const sp = c._split(rows, now); const first = c._list(rows, now, false);\n"
          "c._setEarlier(true); const opened = c._list(rows, now, false); const saved = store.get('flight_watcher_finds_earlier');\n"
          "const again = card()._list(rows, now, false);\n"
          "c._setEarlier(false); const shut = store.get('flight_watcher_finds_earlier');\n"
          "const none = card()._list(rows.slice(2), now, false);\n"
          "const p = card(); p._m = '2026-10'; const past = p._list(rows, now, false); const pastNone = p._list([], now, false);\n"
          "globalThis.localStorage = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }};\n"
          "const b = card(); const blocked = b._list(rows, now, false); b._setEarlier(true); const blockedOpen = b._list(rows, now, false);\n"
          "console.log(JSON.stringify({today: sp.today.map((f) => f.pairing), earlier: sp.earlier.map((f) => f.pairing),\n"
          "  first: parts(first).map(tr), firstFold: parts(first)[1].slice(0, 60), opened: tag(opened), saved,\n"
          "  again: tag(again), shut, none: parts(none).map(tr), noneText: parts(none)[0],\n"
          "  past: tr(past), pastFold: past.includes('<details'), pastNone, blocked: tag(blocked),\n"
          "  blockedOpen: tag(blockedOpen)}));")
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r["today"] == ["H9001", "H9002"] and r["earlier"] == ["H9003", "H9004", "H9005"]
    assert r["first"] == [2, 3] and r["firstFold"] == '<details class="old"><summary>3 earlier this month</summary>'
    assert r["opened"] == '<details class="old" open>' and r["saved"] == "1"
    assert r["again"] == '<details class="old" open>'  # a new card (page reload) reads the browser's choice
    assert r["shut"] == "0"
    assert r["none"] == [0, 3] and "Nothing new today (Nov 6 HST)." in r["noneText"]
    assert r["past"] == 5 and not r["pastFold"] and r["pastNone"] == '<div class="k">Nothing added in Oct 2026.</div>'
    # storage blocked (private mode): closed by default, the fold still opens for this page, nothing throws
    assert r["blocked"] == '<details class="old">' and r["blockedOpen"] == '<details class="old" open>'
    pilot2 = cards.build("1", None, ["pilot2"])["flight-watcher-finds-card-pilot2.js"]
    assert 'localStorage.getItem("flight_watcher_pilot2_finds_earlier")' in pilot2  # a second pilot's fold is his own


def test_pilot_card_draws_rebuilt_month_in_the_schedule_grid(tmp_path):
    """FW-0002: the crew index's rebuilt trips use the readable schedule's day-by-day grid (synthetic names): FLICA's
    rows (the day before the bid period to its last day, Oct 31 to Dec 1), one trip per day (two trips on the same
    days: the newest read in the grid, the other listed under it) and totals over what the grid counts."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        import pytest
        pytest.skip("node not installed")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-pilot-card.js"),
               encoding="utf-8").read()

    def t(pid, s, e, route, blk, cr, at="", **kw):
        return {"pairing": pid, "start": s, "end": e, "seat": "FO", "route": route, "checked_at": at, "blk": blk, "credit": cr, **kw}
    a = {"reconstructed_month": "2026-11", "reconstructed_from": "2026-11-01", "reconstructed_to": "2026-12-01",
         "reconstructed_coverage_pct": 87.5, "reconstructed": [
             t("H9001", "2026-10-31", "2026-11-02", "HNL-LAX-HNL", "9:58", "12:34", "2026-11-05T13:56:42", lay="LAX", soft="2:36",
               crew=[["CA", "Doe, Jane"], ["FO", "Roe, Rick"]]),
             t("H9005", "2026-11-05", "2026-11-07", "HNL-SEA-HNL", "10:00", "12:00", "2026-11-01T13:10:00"),  # traded away
             t("H9006", "2026-11-05", "2026-11-06", "HNL-SFO-HNL", "5:00", "6:00", "2026-11-04T09:00:00", soft="1:00"),
             {**t("H9002", "2026-11-20", "2026-11-20", "HNL-OGG-HNL", "1:00", "5:00"), "seat": "RO"},
             t("H9003", "2026-11-27", "2026-11-30", "HNL-SYD-HNL", "20:55", "20:55"),
             t("H9004", "2026-12-01", "2026-12-03", "HNL-NRT-HNL", "16:35", "16:35", "2026-11-06T01:00:00", lay="NRT")]}
    readable = ([["2026-11-04", "H3826", "HNL"]],
                [{"trip": "H3826", "start": "2026-11-04", "end": "2026-11-04", "blk": "5:00", "credit": "5:30", "soft": "0:30",
                  "legs": [{"dow": "WE", "route": "HNL-OGG", "dep": "0800", "arr": "0840", "blk": "0:40"}],
                  "crew": [["CA", "Doe, Jane"]]}], "2026-11")
    js = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n" + src +
          f"\nconst c = new FlightWatcherPilotCard(); const a = {json.dumps(a)}; const rd = {json.dumps(readable)};\n"
          "const nob = {...a, reconstructed: a.reconstructed.map((x) => x.pairing === 'H9002' ? {...x, blk: ''} : x)};\n"
          "const bare = {...a, reconstructed_from: undefined, reconstructed_to: undefined};\n"
          "const lined = {...bare, month: '2026-11', days: [['2026-10-31', 'H3082', 'LAX'], ['2026-12-01', '', '']]};\n"
          "console.log(JSON.stringify({g: c._rebuild(a), open: c._recon(a, false), fold: c._recon(a, true), rd: c._grid(...rd),\n"
          "  nob: c._recon(nob, false), bare: c._rebuild(bare).days.map((d) => d[0]), lined: c._rebuild(lined).days.map((d) => d[0])}));")
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    days = {d: (code, lay) for d, code, lay in r["g"]["days"]}
    assert r["g"]["days"][0][0] == "2026-10-31" and r["g"]["days"][-1][0] == "2026-12-01" and len(days) == 32
    assert days["2026-10-31"] == ("H9001", "LAX") and days["2026-11-01"] == ("", "-") and days["2026-11-02"] == ("", "HNL")
    # two trips from Nov 5: the newer read (H9006) is drawn; H9005 does not leak into its box or the day after
    assert days["2026-11-05"] == ("H9006", "SFO") and days["2026-11-06"] == ("", "HNL") and days["2026-11-07"] == ("", "")
    assert [x["pairing"] for x in r["g"]["also"]] == ["H9005"]
    assert days["2026-11-20"] == ("H9002", "HNL")  # a day trip: base, like FLICA
    assert days["2026-11-27"] == ("H9003", "SYD") and days["2026-11-30"] == ("", "HNL")  # out and back: the outstation
    assert days["2026-12-01"] == ("H9004", "NRT")  # the bid period's last day (a 'D1' trip): kept, open at the bottom
    assert days["2026-11-10"] == ("", "")
    it = r["g"]["items"][0]
    assert (it["trip"], it["blk"], it["credit"], it["soft"], it["seat"]) == ("H9001", "9:58", "12:34", "2:36", "FO")
    assert [x["route"] for x in it["legs"]] == ["HNL-LAX", "LAX-HNL"]
    h = r["open"]
    assert h.count("<tr") == 33 and h.count(" bxs") == 5 and h.count(" bxe") == 4
    assert h.count(' bx"') + h.count(" bx ") == 11  # Oct 31-Nov 2, Nov 5-6, Nov 20, Nov 27-30, Dec 1
    assert "CA Doe, Jane · FO Roe, Rick" in h and "2 legs" in h and 'title="crew read 11-05 13:56 HST"' in h
    assert "November 2026 · 87.5% of trips read · updated 00/06/12/18 HST" in h
    assert "Also on crew lists" in h and "<b>H9005</b> Nov 5-7 FO, read 11-01 13:10" in h
    # totals: the 4 trips in the bid period as drawn; the overlap and the Oct 31 row are named, not added
    assert 'Trips<b>4</b> <small class="u">(+1 overlapping, +1 before Nov 1: not totaled)</small>' in h
    assert "Block<b>43:30</b>" in h and "Credit<b>48:30</b>" in h
    assert "Block<b>?</b>" in r["nob"] and "Credit<b>48:30</b>" in r["nob"]  # a trip without block: no block total
    # a readable month: the rebuilt grid takes FLICA's first and last day; an old publish: month end or the last trip
    assert (r["lined"][0], r["lined"][-1], len(r["lined"])) == ("2026-10-31", "2026-12-01", 32)
    assert (r["bare"][0], r["bare"][-1]) == ("2026-10-31", "2026-12-03")
    assert r["fold"].startswith('<details class="rb"><summary>') and not h.startswith("<details")
    assert 'title="WE HNL-OGG 0800-0840 0:40">1 legs</span>' in r["rd"] and "CA Doe, Jane" in r["rd"]

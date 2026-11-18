"""1.7.16 review fixes for When to hunt (pickup speed by layover, HST weekday and HST time of day).

F1: the tip names the fastest (day, time of day) slot with 5 or more pickups, never the slot where the fastest day and
the fastest band cross; with no slot of 5 it gives the fastest day and the fastest time of day as two separate facts.
F2: a both-seats trip is one pickup (one pot entry, one dwell): counted once, not once a picker.
F3: a layover reads as one station for every source ('PPG/PPT' of a pot-seen turn and the 'PPG' of its email-caught
copy are one group; 'SYD/MEL' is SYD).
F4: a pickup's pot entry is kept on its picker_log row when it is scored or rescored, so a find later back in the
pot, cleared or deleted never moves it to another weekday or band.
R1: the When to hunt section shows while the pickers list is collapsed (the dashboard's and portal's config).
R3: an open or close without a click (find in page) is kept, and a speed update keeps the summary's focus.
R4: an empty table says so. R5: the tip's day and time of day never split across two lines.
Synthetic pairings (H9xxx), made-up stations and pilots ("Doe, Jane" 10001, "Roe, Rick" 10002) only."""
import json
import os
from datetime import datetime, timedelta, timezone

from store import Store, speed_summary
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw1716_speed import HUNT, _card_page, _pick, _rows, _utc, _world

HST = timezone(timedelta(hours=-10))
JANE, RICK = "Doe, Jane (10001)", "Roe, Rick (10002)"
SHOTS = os.environ.get("FW_1716_SHOTS", "")


# ---------------------------------------------------------------- F1: the tip names a real slot
def test_the_tip_names_the_fastest_slot_not_where_the_fastest_day_and_band_cross():
    rows = _rows(*[(30, "LAX", 16, 19)] * 10,  # Mon 18-24: 30 s
                 *[(30, "LAX", 17, 8)] * 10,  # Tue 06-12: 30 s
                 *[(900, "LAX", 16, 8)] * 5,  # Mon 06-12: 15 min, the second slowest slot
                 *[(2000, "LAX", 17, 19)] * 10)  # Tue 18-24
    got = speed_summary(rows)
    assert got["dow"][0][:3] == ["Mon", 15, 30] and got["band"][0][:3] == ["06-12", 15, 30]
    # the fastest day and the fastest band cross at Mon 06-12 (15 min): never named the fastest
    assert got["tip"] == "Trips go fastest when they enter the pot Mon 18-24 HST: median 30 s (n 10)."
    rows = _rows(*[(30, "LAX", 16, 19)] * 10, *[(30, "LAX", 17, 8)] * 10, *[(900, "LAX", 16, 8)] * 3,
                 *[(2000, "LAX", 17, 19)] * 10)
    got = speed_summary(rows)
    assert got["tip"] == "Trips go fastest when they enter the pot Mon 18-24 HST: median 30 s (n 10)."
    assert "06-12" not in got["tip"]  # Mon 06-12 has 3 slow pickups only


def test_with_no_slot_of_5_the_fastest_day_and_time_of_day_are_two_separate_facts():
    rows = _rows(*[(50, "LAX", 16, 8)] * 3, *[(50, "LAX", 16, 19)] * 2,  # Mon: 5, median 50 s
                 *[(30, "LAX", 17, 8)] * 2, *[(300, "LAX", 17, 19)] * 3,  # Tue: 5
                 *[(30, "LAX", 18, 8)] * 2)  # Wed: 2
    got = speed_summary(rows)
    assert got["dow"][0] == ["Mon", 5, 50, 50, 0, 0] and got["band"][0] == ["06-12", 7, 30, 30, 0, 0]
    assert got["tip"] == ("Fastest day: Mon (median 50 s, n 5). Fastest time of day: 06-12 HST (median 30 s, n 7). "
                          "No day and time pair has 5 pickups yet.")
    assert "Mon 06-12" not in got["tip"] and " and at " not in got["tip"]


def test_a_trusted_slot_slower_than_the_fastest_day_is_not_called_the_fastest():
    # Monday is fast over three thin slots (4 pickups each); the one slot of 5 is a slow Tuesday evening
    rows = _rows(*[(30, "LAX", 16, 1)] * 4, *[(30, "LAX", 16, 7)] * 4, *[(30, "LAX", 16, 13)] * 4,
                 *[(2000, "LAX", 17, 19)] * 5)
    got = speed_summary(rows)
    assert got["dow"][0] == ["Mon", 12, 30, 30, 0, 0] and got["band"][0] == ["18-24", 5, 2000, 2000, 0, 0]
    assert got["tip"] == ("Fastest day: Mon (median 30 s, n 12). Fastest time of day: 18-24 HST (median 33 min, n 5).")


# ---------------------------------------------------------------- F2: a both-seats trip is one pickup
def test_a_both_seats_trip_counts_once(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    for i in range(3):  # three both-seats SYD trips, each entering Wed 08:0x HST and gone 2 min later
        _pick(db, f"H965{i}|21Nov", _utc(18, 8, i), 120, emps=("10001", "10002"), lay="SYD",
              by=f"FO {JANE}; RO {RICK}", seats="FO,RO")
    assert db.db.execute("SELECT COUNT(*) FROM picker_log").fetchone()[0] == 6  # each picker once, for his card
    got = db.speed_stats()
    assert got["n"] == 3 and got["city"] == [["SYD", 3, 120, 120, 0, 0]]
    assert got["dow"] == [["Wed", 3, 120, 120, 0, 0]] and got["band"] == [["06-12", 3, 120, 120, 0, 0]]
    assert got["tip"] == ""  # 3 trips: under the 5-pickup bar


def test_a_both_seats_trip_does_not_weigh_twice_in_the_median(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    _pick(db, "H9660|21Nov", _utc(18, 8), 60, lay="SYD")
    _pick(db, "H9661|21Nov", _utc(18, 8, 5), 60, lay="SYD")
    _pick(db, "H9662|21Nov", _utc(18, 8, 10), 600, emps=("10001", "10002"), lay="SYD", by=f"FO {JANE}; RO {RICK}",
          seats="FO,RO")
    assert db.speed_stats()["city"] == [["SYD", 3, 60, 60, 0, 0]]  # 60, 60, 600: the middle is 60


def test_a_both_seats_trip_with_one_capped_picker_counts_at_the_cap(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    _pick(db, "H9663|21Nov", _utc(18, 8), 1200, emps=("10001", "10002"), lay="SYD", by=f"FO {JANE}; RO {RICK}",
          seats="FO,RO")
    # Ryan's own request at 08:03 was denied because Rick (the RO picker) had it: Rick's speed is his cap
    assert db.set_req_cap("H9663|21Nov", "2026-11-18T08:03-10:00", "10002") == "capped"
    got = db.speed_stats()
    assert got["n"] == 1 and got["city"] == [["SYD", 1, 239, 239, 1, 1]]


# ---------------------------------------------------------------- F3: one station for every source
def test_a_turn_and_its_email_caught_copy_are_one_station(tmp_path):
    from pot import parse_detail
    turn = parse_detail("<p>Dy Flt Dps-Ars Th 865 HNL-PPG 1630 2115 Th 13 PPG-PPT 2320 0100 "
                        "Fr 14 PPT-HNL 0300 0800</p>")["turn"]
    assert turn == "PPG/PPT"
    db = Store(str(tmp_path / "s.db"))

    def pick(key, entry, secs, row):
        gone = (datetime.fromisoformat(entry) + timedelta(seconds=secs)).isoformat()
        db.add_find(key, "2026-11", dict(row, pairing=key.split("|")[0], open_seats="FO"), entry, gone=gone)
        db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (gone, key))
        db.set_pickup(key, {"status": "filled", "by": f"FO {JANE}", "known": True, "pickers": ["10001"]})
        assert db.score_pickup(key) == secs
    for i in range(3):  # seen in the pot: no layover cell, the turn from the pairing page
        pick(f"H970{i}|20Nov", _utc(17, 19, 5 * i), 120 + 30 * i, {"layover": "-none-", "turn": turn})
    for i in range(3):  # caught from FLICA's alert email: the Watcher files the turn under its first stop
        pick(f"H980{i}|20Nov", _utc(17, 19, 5 * i), 120 + 30 * i, {"layover": turn.split("/")[0], "turn": turn,
                                                                    "source": "email"})
    for i in range(2):  # a layover cell naming two stations
        pick(f"H990{i}|21Nov", _utc(18, 7), 600, {"layover": "SYD/MEL"})
    got = db.speed_stats()
    assert got["city"] == [["PPG", 6, 150, 120, 0, 0], ["SYD", 2, 600, 600, 0, 0]]


def test_a_layover_reads_as_its_first_station():
    rows = [(60, False, lay, _utc(17, 19)) for lay in ("SYD/MEL", "syd mel", "SYD, MEL", " SYD ", "-", "-none-", "")]
    got = speed_summary(rows)
    assert got["city"] == [["SYD", 4, 60, 60, 0, 0]] and got["n"] == 7


# ---------------------------------------------------------------- F4: the entry stays with the pickup
def _gone_window(db, key, entry, last, gone, emps=("10001",)):
    """A find first seen at entry, last listed at last and gone by gone (UTC ISO), scored for Jane."""
    db.add_find(key, "2026-11", {"pairing": key.split("|")[0], "open_seats": "FO", "layover": "LAX"}, entry, gone=gone)
    db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (last, key))
    db.set_pickup(key, {"status": "filled", "by": f"FO {JANE}", "known": True, "pickers": list(emps)})
    return db.score_pickup(key)


def test_a_trip_back_in_the_pot_keeps_its_logged_entry(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    k = "H9701|11Nov"
    # first seen Tue Nov 10 23:50 HST, last listed 23:52, gone by Wed 00:20: scored at the middle of the window
    assert _gone_window(db, k, _utc(10, 23, 50), _utc(10, 23, 52), _utc(11, 0, 20)) == 960
    a = db.speed_stats()
    assert a["dow"] == [["Tue", 1, 960, 960, 0, 0]] and a["band"] == [["18-24", 1, 960, 960, 0, 0]]
    # the trip comes back into the pot (record_pot: a new first sighting, gone_at cleared), then a rescore
    db.record_pot("2026-11", {k: {"pairing": "H9701", "open_seats": "FO", "layover": "LAX"}}, {k})
    db.rescore_all()
    b = db.speed_stats()
    assert b["dow"] == [["Tue", 1, 960, 960, 0, 0]] and b["band"] == [["18-24", 1, 960, 960, 0, 0]]
    db.clear_pickup(k)  # its pickup cleared for a re-check
    db.rescore_all()
    assert db.speed_stats()["band"] == [["18-24", 1, 960, 960, 0, 0]]


def test_a_capped_pickup_whose_find_is_gone_keeps_its_entry(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    k = "H9702|11Nov"
    # entered Tue 17:50 HST, last listed 17:55, gone by 18:25; Ryan's request at 17:56 denied: at most 6m 59s
    _gone_window(db, k, _utc(10, 17, 50), _utc(10, 17, 55), _utc(10, 18, 25))
    assert db.set_req_cap(k, "2026-11-10T17:56-10:00", "10001") == "capped"
    assert db.speed_stats()["band"] == [["12-18", 1, 419, 419, 1, 1]]
    db.db.execute("DELETE FROM finds WHERE key=?", (k,))  # the find gone from the store (never the log)
    db.rescore_all()
    assert db.speed_stats()["band"] == [["12-18", 1, 419, 419, 1, 1]]  # not 18:18 HST, 18-24
    db.record_pot("2026-11", {k: {"pairing": "H9702", "open_seats": "FO", "layover": "LAX"}}, {k})
    db.rescore_all()
    assert db.speed_stats()["band"] == [["12-18", 1, 419, 419, 1, 1]]


def test_a_row_logged_before_1716_gets_its_entry_from_its_find_once(tmp_path):
    path = str(tmp_path / "s.db")
    db = Store(path)
    on_file, gone_k = "H9703|11Nov", "H9704|11Nov"
    _gone_window(db, on_file, _utc(10, 23, 50), _utc(10, 23, 52), _utc(11, 0, 20))
    _gone_window(db, gone_k, _utc(12, 5, 0), _utc(12, 5, 0), _utc(12, 5, 10))
    db.db.execute("UPDATE picker_log SET entry=NULL")  # as 1.7.11 logged them
    db.db.execute("DELETE FROM finds WHERE key=?", (gone_k,))
    db.db.close()
    db = Store(path)  # the next start fills them in: from the find on file, else the pickup's time less its speed
    ent = dict(db.db.execute("SELECT key,entry FROM picker_log").fetchall())
    assert datetime.fromisoformat(ent[f"{on_file}|10001"]) == datetime.fromisoformat(_utc(10, 23, 50))
    # the find no longer on file: its pickup time less its speed (the middle of the gone window, 5 min late here)
    assert datetime.fromisoformat(ent[f"{gone_k}|10001"]) == datetime.fromisoformat(_utc(12, 5, 5))
    db.record_pot("2026-11", {on_file: {"pairing": "H9703", "open_seats": "FO", "layover": "LAX"}}, {on_file})
    db.rescore_all()
    assert db.speed_stats()["dow"] == [["Thu", 1, 300, 300, 0, 0], ["Tue", 1, 960, 960, 0, 0]]


# ---------------------------------------------------------------- the card
DEFAULT = "{entity: 'sensor.flight_watcher_pickers'}"  # ha/dashboard_flight_watcher.json and portal_layout.json


def test_the_hunt_section_shows_with_the_pickers_list_collapsed(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W, many=False)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def cards(node):
        if isinstance(node, dict):
            if str(node.get("type", "")).startswith("custom:flight-watcher-pickers-card"):
                yield node
            node = list(node.values())
        if isinstance(node, list):
            for x in node:
                yield from cards(x)
    for f in (os.path.join(here, "..", "ha", "dashboard_flight_watcher.json"), os.path.join(here, "portal_layout.json")):
        found = list(cards(json.load(open(f, encoding="utf-8"))))
        assert found and all("open" not in c for c in found), f  # neither opens the pickers list
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _card_page(b, 390, 844, scheme, pay, cfg=DEFAULT, ready=".hunt .tip")
            v = pg.evaluate("""() => { const r = PC.shadowRoot, t = r.querySelector('.tip');
              return { body: getComputedStyle(r.querySelector('.body')).display, tip: t.offsetParent !== null,
                h: t.getBoundingClientRect().height, rows: r.querySelectorAll('.hunt tbody tr').length,
                tblH: r.querySelector('.tbls').getBoundingClientRect().height,
                open: r.querySelector('.hunt details').open }; }""")
            assert v["body"] == "none"  # the pickers list stays collapsed
            assert v["tip"] and v["h"] > 10, v
            assert v["open"] and v["rows"] > 0 and v["tblH"] > 20, v  # short: the tables are open too
            assert pg.evaluate(HUNT)["tip"] == pay["speed"]["tip"]
            assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
            c = pg.evaluate("() => fwContrast(PC)")
            assert c["fails"] == [], c["fails"]
            # the header still opens and closes the pickers list under it
            pg.evaluate("() => PC.shadowRoot.querySelector('.hd').click()")
            assert pg.evaluate("() => getComputedStyle(PC.shadowRoot.querySelector('.body')).display") == "block"
            assert pg.errors == []
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.evaluate("() => PC.shadowRoot.querySelector('.hd').click()")
                pg.locator("flight-watcher-pickers-card").first.screenshot(
                    path=os.path.join(SHOTS, f"item7_review_collapsed_390_{scheme}.png"))
            pg.context.close()


def _bump(pg):
    pg.evaluate("() => { const s = JSON.parse(JSON.stringify(ST)); const sp = s['sensor.flight_watcher_pickers']"
                ".attributes.speed; sp.n += (window.BUMP = (window.BUMP || 0) + 1); PC.hass = mkHass(s); }")


def test_an_open_without_a_click_is_kept_and_a_speed_update_keeps_focus(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W)
    with _browser() as b:
        pg = _card_page(b, 390, 844, "light", pay)
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is False  # long: collapsed
        # find in page opens a closed <details> with a toggle event, no click
        pg.evaluate("() => { PC.shadowRoot.querySelector('.hunt details').open = true; }")
        pg.wait_for_timeout(50)
        _bump(pg)
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is True
        pg.evaluate("() => { PC.shadowRoot.querySelector('.hunt details').open = false; }")
        pg.wait_for_timeout(50)
        _bump(pg)
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is False
        # a keyboard user: focus on the summary, Enter opens it, then a new pickup comes in
        pg.evaluate("() => PC.shadowRoot.querySelector('.hunt summary').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(50)
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is True
        _bump(pg)
        _bump(pg)
        assert pg.evaluate("() => (PC.shadowRoot.activeElement || {}).tagName") == "SUMMARY"
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is True
        assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt summary').textContent").endswith(
            f"({pay['speed']['n'] + 4} pickups)")  # the fourth update's count
        assert pg.errors == []
        pg.context.close()


def test_an_empty_table_says_so(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W, many=False)
    sp = dict(pay["speed"], city=[])
    pay = dict(pay, speed=sp)
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _card_page(b, 390, 844, scheme, pay)
            h = pg.evaluate(HUNT)
            lay = h["tables"][0]
            assert lay["cap"] == "Layover" and [r["cells"] for r in lay["rows"]] == [["No layover on file yet."]]
            assert [len(t["rows"]) for t in h["tables"][1:]] == [len(sp["dow"]), len(sp["band"])]
            c = pg.evaluate("() => fwContrast(PC)")
            assert c["fails"] == [], c["fails"]
            if SHOTS:
                pg.locator("flight-watcher-pickers-card").first.screenshot(
                    path=os.path.join(SHOTS, f"item7_review_nolay_390_{scheme}.png"))
            pg.context.close()


def test_the_tips_day_and_time_of_day_stay_on_one_line(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W, many=False)
    tip = pay["speed"]["tip"]
    assert tip.startswith("Trips go fastest when they enter the pot Tue 18-24 HST:")
    with _browser() as b:
        for width in (360, 390, 414):
            pg = _card_page(b, width, 844, "light", pay)
            v = pg.evaluate("""() => { const t = PC.shadowRoot.querySelector('.tip'), s = t.querySelector('.nb');
              return { span: s && s.textContent, rects: s ? s.getClientRects().length : 0, text: t.textContent }; }""")
            assert v["span"] == "Tue 18-24 HST" and v["rects"] == 1 and v["text"] == tip, v
            pg.context.close()
    # the two-facts tip keeps its time of day whole too
    pay2 = dict(pay, speed=dict(pay["speed"], tip=("Fastest day: Mon (median 50 s, n 5). Fastest time of day: 06-12 HST "
                                                   "(median 30 s, n 7). No day and time pair has 5 pickups yet.")))
    with _browser() as b:
        pg = _card_page(b, 390, 844, "light", pay2)
        assert pg.evaluate("() => [...PC.shadowRoot.querySelectorAll('.tip .nb')].map((s) => s.textContent)") == [
            "06-12 HST"]
        pg.context.close()

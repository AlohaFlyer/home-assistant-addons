"""1.7.16 (Ryan, Nov 17): "Using the pot log ("Pickup Speed" exists, so build on it), show median time to pickup by
layover city and by day of week/time of day, so I know when to run Hunt."

From the pickups the FO / RO pickers card counts (picker_log; each pickup once, a both-seats trip too, at its scored
speed; a speed capped at Ryan's request time counts at its cap and is flagged), the median time to pickup, the count
and the fastest, by layover (the first station of the trip's layover, else of its turn, as Common Layover), by the HST
weekday the trip entered the pot and by the HST time of day it entered it (00-06, 06-12, 12-18, 18-24). A group of
fewer than 5 pickups is too few to trust: grey on the card, never the tip. The aggregates ride on
sensor.<prefix>_pickers (speed, under its own size cap), each instance from its own store, recomputed only when a
pickup changes, with no FLICA load. Synthetic pairings (H96xx), stations and made-up pilots ("Doe, Jane" 10001) only."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import portal
from store import (SPEED_ATTR_MAX, SPEED_BANDS, SPEED_DAYS, SPEED_MIN_N, Store, hst_slot, median_s, speed_payload,
                   speed_summary, tip_dur)
from test_crew_index import W  # noqa: F401  (the Watcher fixture)

HST = timezone(timedelta(hours=-10))
JANE, RICK = "Doe, Jane (10001)", "Roe, Rick (10002)"
SHOTS = os.environ.get("FW_1716_SHOTS", "")


def _utc(d, h, mi=0):
    """An HST wall time on 2026-11-<d> as the store keeps it (UTC ISO)."""
    return datetime(2026, 11, d, h, mi, tzinfo=HST).astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------- the median
def test_the_median_of_an_odd_and_an_even_count():
    assert median_s([300]) == 300
    assert median_s([180, 60, 120]) == 120  # the middle one, whatever the order
    assert median_s([240, 60, 180, 120]) == 150  # the mean of the two middle ones
    assert median_s([1, 2]) == 2  # a half second rounds up
    assert median_s([10, 10, 10, 9999]) == 10  # one slow trip does not move it
    assert median_s([]) is None


def test_the_tip_reads_minutes():
    assert tip_dur(45) == "45 s" and tip_dur(60) == "1 min" and tip_dur(240) == "4 min" and tip_dur(269) == "4 min"
    assert tip_dur(270) == "5 min" and tip_dur(3570) == "1 h 00 min" and tip_dur(5400) == "1 h 30 min"


# ---------------------------------------------------------------- HST weekday and band
def test_the_weekday_and_band_are_hst_across_midnight_and_the_date_line():
    # Wed 05:00 UTC is Tue 19:00 in Honolulu: the evening band of Tuesday, not Wednesday's night
    assert hst_slot("2026-11-18T05:00:00+00:00") == ("Tue", "18-24")
    assert hst_slot("2026-11-18T09:59:59+00:00") == ("Tue", "18-24")  # 23:59:59 HST
    assert hst_slot("2026-11-18T10:00:00+00:00") == ("Wed", "00-06")  # HST midnight: the next day's first band
    assert hst_slot("2026-11-18T15:59:00+00:00") == ("Wed", "00-06")
    assert hst_slot("2026-11-18T16:00:00+00:00") == ("Wed", "06-12")
    assert hst_slot("2026-11-18T22:00:00+00:00") == ("Wed", "12-18")
    # across the date line: Thu 09:00 in Sydney (+11) is still Wednesday noon in Honolulu
    assert hst_slot("2026-11-19T09:00:00+11:00") == ("Wed", "12-18")
    assert hst_slot("2026-11-18T12:00-10:00") == ("Wed", "12-18")  # an HST stamp reads as itself
    assert hst_slot("2026-11-18T05:00:00Z") == ("Tue", "18-24")
    assert hst_slot("2026-11-18T05:00:00") == ("Tue", "18-24")  # no offset: UTC, as the store writes
    assert hst_slot("") is None and hst_slot(None) is None and hst_slot("not a time") is None
    assert SPEED_DAYS == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    assert SPEED_BANDS == ("00-06", "06-12", "12-18", "18-24") and SPEED_MIN_N == 5


# ---------------------------------------------------------------- the groups
def _rows(*spec):
    """(secs, capped, lay, entry) rows from (secs, lay, HST day of Nov 2026, HST hour[, capped])."""
    return [(s, bool(c[0]) if c else False, lay, _utc(d, h)) for s, lay, d, h, *c in spec]


def test_groups_by_city_weekday_and_band_with_n_median_and_fastest():
    rows = _rows(*[(s, "LAX", 17, 19) for s in (60, 120, 180, 240, 300)],  # Tue 19:00: 5 LAX trips
                 *[(s, "SYD", 18, 7) for s in (600, 700, 800, 900, 1000, 1100)])  # Wed 07:00: 6 SYD trips
    got = speed_summary(rows)
    assert got["n"] == 11 and got["min_n"] == 5
    assert got["city"] == [["LAX", 5, 180, 60, 0, 0], ["SYD", 6, 850, 600, 0, 0]]  # odd n: the middle; even: the mean
    assert got["dow"] == [["Tue", 5, 180, 60, 0, 0], ["Wed", 6, 850, 600, 0, 0]]
    assert got["band"] == [["18-24", 5, 180, 60, 0, 0], ["06-12", 6, 850, 600, 0, 0]]
    assert got["tip"] == "Trips go fastest when they enter the pot Tue 18-24 HST: median 3 min (n 5)."


def test_each_table_is_sorted_by_median_and_groups_under_5_come_after_grey():
    rows = _rows(*[(s, "LAX", 17, 19) for s in (400, 500, 600, 700, 800)],  # Tue 19:00, median 600
                 *[(s, "SYD", 18, 7) for s in (100, 200, 300, 400, 500)],  # Wed 07:00, median 300
                 *[(s, "NRT", 19, 13) for s in (5, 6, 7, 8)])  # Thu 13:00: the fastest, but only 4 pickups
    got = speed_summary(rows)
    assert [g[0] for g in got["city"]] == ["SYD", "LAX", "NRT"]  # trusted by median, then the too-few
    assert [g[0] for g in got["dow"]] == ["Wed", "Tue", "Thu"]
    assert [g[0] for g in got["band"]] == ["06-12", "18-24", "12-18"]
    nrt = got["city"][-1]
    assert nrt == ["NRT", 4, 7, 5, 0, 0] and nrt[1] < SPEED_MIN_N  # median of 4: (6 + 7 + 1) // 2
    # the tip never takes the four fast Thursday trips
    assert got["tip"] == "Trips go fastest when they enter the pot Wed 06-12 HST: median 5 min (n 5)."


def test_a_tie_in_median_goes_to_the_bigger_group_then_the_calendar():
    rows = _rows(*[(60, "LAX", 16, 1)] * 5, *[(60, "SEA", 17, 1)] * 6, *[(60, "OGG", 18, 1)] * 5)
    got = speed_summary(rows)
    assert [g[0] for g in got["city"]] == ["SEA", "LAX", "OGG"]  # 6 pickups first, then by name
    assert [g[0] for g in got["dow"]] == ["Tue", "Mon", "Wed"]
    rows = _rows(*[(60, "LAX", 16, 1)] * 5, *[(60, "LAX", 18, 1)] * 5)
    assert [g[0] for g in speed_summary(rows)["dow"]] == ["Mon", "Wed"]


def test_a_capped_speed_counts_at_its_cap_and_is_flagged():
    rows = _rows((90, "LAX", 17, 19, 1), (100, "LAX", 17, 19), (110, "LAX", 17, 20), (120, "LAX", 17, 21),
                 (130, "LAX", 17, 22))
    got = speed_summary(rows)
    assert got["city"] == [["LAX", 5, 110, 90, 1, 1]]  # 1 capped; the fastest is the capped one
    assert got["tip"] == "Trips go fastest when they enter the pot Tue 18-24 HST: median at most 2 min (n 5)."
    rows[0] = (90, False, "LAX", rows[0][3])
    rows[-1] = (130, True, "LAX", rows[-1][3])
    got = speed_summary(rows)
    assert got["city"] == [["LAX", 5, 110, 90, 1, 0]]  # a capped one, not the fastest
    assert "at most" in got["tip"]  # the median of a set with an upper bound in it is an upper bound


def test_no_city_and_no_entry_time():
    rows = [(60, False, "", _utc(17, 19))] * 5 + [(60, False, "LAX", "")] * 5
    got = speed_summary(rows)
    assert got["n"] == 10 and got["city"] == [["LAX", 5, 60, 60, 0, 0]]  # no layover: not in the city table
    assert got["dow"] == [["Tue", 5, 60, 60, 0, 0]] and got["band"] == [["18-24", 5, 60, 60, 0, 0]]  # no time: not here
    assert speed_summary([]) == {"n": 0, "min_n": 5, "city": [], "dow": [], "band": [], "tip": ""}
    assert speed_summary([(None, False, "LAX", _utc(17, 19))])["n"] == 0  # no speed: not a pickup


# ---------------------------------------------------------------- the tip
def test_the_tip_names_the_fastest_day_and_band_with_5_or_more():
    # the fastest day (Mon) and the fastest band (06-12) meet in 6 pickups: their own median and count
    rows = _rows(*[(120, "LAX", 16, 7)] * 6, *[(600, "LAX", 16, 14)] * 3, *[(300, "LAX", 17, 8)] * 2,
                 *[(900, "LAX", 17, 20)] * 6)
    got = speed_summary(rows)
    assert [g[0] for g in got["dow"]] == ["Mon", "Tue"] and [g[0] for g in got["band"]] == ["06-12", "18-24", "12-18"]
    assert got["tip"] == "Trips go fastest when they enter the pot Mon 06-12 HST: median 2 min (n 6)."


def test_when_the_fastest_day_and_band_share_under_5_the_tip_gives_each_apart():
    rows = _rows(*[(60, "LAX", 16, 19)] * 5,  # Mon 18-24
                 *[(30, "LAX", 17, 8)] * 5,  # Tue 06-12
                 *[(900, "LAX", 16, 8)] * 2)  # Mon 06-12: only 2
    got = speed_summary(rows)
    assert got["dow"] == [["Tue", 5, 30, 30, 0, 0], ["Mon", 7, 60, 60, 0, 0]]
    assert got["band"] == [["06-12", 7, 30, 30, 0, 0], ["18-24", 5, 60, 60, 0, 0]]
    assert got["tip"] == "Trips go fastest when they enter the pot Tue 06-12 HST: median 30 s (n 5)."
    rows = _rows(*[(60, "LAX", 16, 19)] * 5, *[(40, "LAX", 17, 13)] * 5, *[(30, "LAX", 18, 8)] * 5)
    got = speed_summary(rows)
    # Wed is the fastest day (30 s) and 06-12 the fastest band: they meet in 5, so one median
    assert got["tip"] == "Trips go fastest when they enter the pot Wed 06-12 HST: median 30 s (n 5)."
    rows = _rows(*[(50, "LAX", 16, 8)] * 3, *[(50, "LAX", 16, 19)] * 2,  # Mon: 5 pickups, median 50
                 *[(30, "LAX", 17, 8)] * 2, *[(300, "LAX", 17, 19)] * 3,  # Tue: 5, median 300
                 *[(30, "LAX", 18, 8)] * 2)  # Wed: 2 (too few)
    got = speed_summary(rows)
    assert got["dow"][0] == ["Mon", 5, 50, 50, 0, 0] and got["band"][0] == ["06-12", 7, 30, 30, 0, 0]
    # Mon and 06-12 meet in 3 pickups only, and no slot has 5: two separate facts, each with its own numbers
    # (review F1: never "on Mon and at 06-12", which reads as a Mon 06-12 slot)
    assert got["tip"] == ("Fastest day: Mon (median 50 s, n 5). Fastest time of day: 06-12 HST (median 30 s, n 7). "
                          "No day and time pair has 5 pickups yet.")


def test_a_tip_from_one_table_only_and_none_at_all():
    # 5 pickups on one day spread over four bands: a day to name, no band
    rows = _rows((60, "LAX", 17, 1), (60, "LAX", 17, 7), (60, "LAX", 17, 13), (60, "LAX", 17, 19), (120, "LAX", 17, 20))
    assert speed_summary(rows)["tip"] == "Trips go fastest when they enter the pot on Tue: median 1 min (n 5)."
    # 5 pickups in one band over five days: a band, no day
    rows = _rows(*[(60, "LAX", d, 19) for d in (16, 17, 18, 19, 20)])
    assert speed_summary(rows)["tip"] == "Trips go fastest when they enter the pot at 18-24 HST: median 1 min (n 5)."
    rows = _rows(*[(60, "LAX", d, h) for d, h in ((16, 1), (17, 7), (18, 13), (19, 19))])
    assert speed_summary(rows)["tip"] == ""  # 4 pickups: nothing to trust


# ---------------------------------------------------------------- the size bound
def test_the_payload_stays_under_its_cap_dropping_the_smallest_cities_first():
    rows = []
    for i in range(400):  # 400 made-up stations, station i with 1 + i % 7 pickups
        rows += [(60 + i, False, f"Q{i:03d}", _utc(16 + i % 7, i % 24))] * (1 + i % 7)
    got = speed_payload(speed_summary(rows))
    size = len(json.dumps(got, separators=(",", ":")))
    assert size <= SPEED_ATTR_MAX and got["more"] > 0
    assert len(got["city"]) + got["more"] == 400
    kept = {g[0] for g in got["city"]}
    assert min(g[1] for g in got["city"]) >= max((1 + i % 7) for i in range(400) if f"Q{i:03d}" not in kept)
    assert len(got["dow"]) == 7 and len(got["band"]) == 4 and got["tip"]  # never trimmed
    assert got["n"] == len(rows)
    small = speed_payload(speed_summary(rows[:10]))
    assert small["more"] == 0 and len(small["city"]) == len({r[2] for r in rows[:10]})
    assert SPEED_ATTR_MAX <= 3000


# ---------------------------------------------------------------- the store
def _pick(db, key, entry, secs, emps=("10001",), lay="LAX", by=f"FO {JANE}", seats="FO"):
    """A find that entered the pot at entry (UTC ISO) and was gone secs later, scored for its picker(s)."""
    gone = (datetime.fromisoformat(entry) + timedelta(seconds=secs)).isoformat()
    row = {"pairing": key.split("|")[0], "open_seats": seats, "layover": lay}
    db.add_find(key, "2026-11", row, entry, gone=gone)
    db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (gone, key))
    db.set_pickup(key, {"status": "filled", "by": by, "known": True, "pickers": list(emps)})
    assert db.score_pickup(key) == secs
    return gone


def test_the_store_counts_the_same_pickups_as_the_pickers_card(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    for i, s in enumerate((60, 120, 180, 240, 300)):  # Tue 19:00 to 19:40 HST
        _pick(db, f"H96{i:02d}|20Nov", _utc(17, 19, 10 * i), s)
    # both seats open: each picker once on the pickers card, but one trip (one pot entry, one dwell) here
    _pick(db, "H9610|21Nov", _utc(18, 7), 600, emps=("10001", "10002"), lay="SYD", by=f"FO {JANE}; RO {RICK}",
          seats="FO,RO")
    got = db.speed_stats()
    stats = db.picker_stats()
    assert sum(v["n"] for v in stats.values()) == 7 and got["n"] == 6  # review F2: the pickups, not the pickers
    assert got["city"] == [["LAX", 5, 180, 60, 0, 0], ["SYD", 1, 600, 600, 0, 0]]
    assert got["dow"] == [["Tue", 5, 180, 60, 0, 0], ["Wed", 1, 600, 600, 0, 0]]
    assert got["band"] == [["18-24", 5, 180, 60, 0, 0], ["06-12", 1, 600, 600, 0, 0]]
    assert got["tip"] == "Trips go fastest when they enter the pot Tue 18-24 HST: median 3 min (n 5)." and got["more"] == 0


def test_the_entry_is_the_alert_when_earlier_and_a_cap_counts_capped(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    gone = _pick(db, "H9620|20Nov", _utc(18, 10, 30), 1200)  # seen Wed 10:30 HST
    assert db.speed_stats()["band"] == [["06-12", 1, 1200, 1200, 0, 0]]
    # FLICA's alert says it entered the pot at 05:50: the entry (and the speed) move with it
    assert db.set_alert_at("H9620|20Nov", _utc(18, 5, 50))
    got = db.speed_stats()
    secs = int((datetime.fromisoformat(gone) - datetime.fromisoformat(_utc(18, 5, 50))).total_seconds())
    assert got["band"] == [["00-06", 1, secs, secs, 0, 0]] and got["dow"][0][0] == "Wed"
    # Ryan's own request at 05:53 was denied because Jane had it: her speed is at most 05:53:59 less 05:50
    assert db.set_req_cap("H9620|20Nov", "2026-11-18T05:53-10:00", "10001") == "capped"
    assert db.speed_stats()["band"] == [["00-06", 1, 239, 239, 1, 1]]


def test_a_pickup_whose_find_is_gone_or_back_in_the_pot_keeps_its_entry(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    _pick(db, "H9630|20Nov", _utc(17, 23, 50), 1200)  # Tue 23:50 HST, picked up Wed 00:10
    db.db.execute("DELETE FROM finds WHERE key='H9630|20Nov'")
    db.rescore_all()
    got = db.speed_stats()
    assert got["n"] == 1 and got["dow"] == [["Tue", 1, 1200, 1200, 0, 0]] and got["band"][0][0] == "18-24"
    _pick(db, "H9631|20Nov", _utc(17, 23, 50), 1200)
    # the trip came back into the pot on Thursday (record_pot: a new first sighting, gone_at cleared); the logged
    # pickup keeps its Tuesday entry
    db.db.execute("UPDATE finds SET first_seen=?, last_seen=?, gone_at=NULL WHERE key='H9631|20Nov'",
                  (_utc(19, 9), _utc(19, 9)))
    db.rescore_all()
    assert db.speed_stats()["dow"] == [["Tue", 2, 1200, 1200, 0, 0]]


def test_the_aggregates_are_kept_until_a_pickup_changes(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _pick(db, "H9640|20Nov", _utc(17, 19), 60)
    a = db.speed_stats()
    calls = []
    real = db._speed_rows
    monkeypatch.setattr(db, "_speed_rows", lambda: calls.append(1) or real())
    for _ in range(50):  # every publish of the pickers sensor (each check) between two pickups
        assert db.speed_stats() is a
    assert calls == []
    _pick(db, "H9641|20Nov", _utc(17, 19), 120)  # a pickup scored
    b = db.speed_stats()
    assert b is not a and b["n"] == 2 and calls == [1] and db.speed_stats() is b
    db.rescore_all()  # a rescore
    assert db.speed_stats() is not b and calls == [1, 1]
    c = db.speed_stats()
    db.prune()  # the 24-month log trimmed
    assert db.speed_stats() is not c


# ---------------------------------------------------------------- the Watcher
def test_the_pickers_sensor_carries_the_speed_with_no_flica_load(W, tmp_path, monkeypatch):  # noqa: F811
    # every FLICA page the Watcher loads is counted: none here
    monkeypatch.setattr(W, "count_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no FLICA load")))
    for i, s in enumerate((60, 120, 180, 240, 300)):
        _pick(W.DB, f"H96{i:02d}|20Nov", _utc(17, 19, i), s)
    W.publish_pickers()
    pay = [p for t, p in W.SENT if t == "pickers"][-1]
    assert pay["speed"] == W.DB.speed_stats() and pay["speed"]["n"] == 5 and pay["speed"]["tip"].startswith("Trips go")
    assert pay["count"] == 1 and "speed" not in json.dumps([p for p in pay["pickers"]])
    # the list file the card reads carries the pickers only, as before
    key = pay["file_key"]
    f = json.loads((tmp_path / "www" / f"pickers_{key}.json").read_text())
    assert set(f) == {"count", "pickers"}
    # the portal serves the sensor as Home Assistant has it: the aggregates pass, nothing masked out of them
    assert portal.state_entry({"state": "1", "attributes": pay})["attributes"]["speed"] == pay["speed"]
    # no crew name or employee number in the aggregates
    assert "Doe" not in json.dumps(pay["speed"]) and "10001" not in json.dumps(pay["speed"])


def test_the_pickers_sensor_stays_under_the_recorder_bar_with_the_most_speed(W, monkeypatch):  # noqa: F811
    """test_sensor_size's busy pickers (150 long names, the fastest 20 on the sensor) with the largest speed attribute
    (400 layovers, cut to SPEED_ATTR_MAX): under its 8000-byte bar for the pickers sensor, and 12 KB with HA's own."""
    pad = "Doe-Longername, Janeallison"
    stats = {f"2{i:04d}": {"name": f"{pad}{i}", "pos": "FO", "n": 1 + i % 9, "total_s": 300 * (1 + i % 9),
                           "inflt_n": i % 3, "month_n": i % 4, "year_n": i % 9, "lays": [["LAS", 3], ["SYD", 2]],
                           "last_lay": "LAS", "min_s": 40 + i, "cap_n": 1, "min_cap": True,
                           "last_at": "2026-11-06T10:00:00+00:00"} for i in range(150)}
    monkeypatch.setattr(W.DB, "picker_stats", lambda now=None: stats)
    rows = []
    for i in range(400):
        rows += [(600 + 37 * i, i % 5 == 0, f"Q{i:03d}", _utc(16 + i % 7, i % 24))] * (1 + i % 7)
    big = speed_payload(speed_summary(rows))
    monkeypatch.setattr(W.DB, "speed_stats", lambda: big)
    W.publish_pickers()
    pay = [p for t, p in W.SENT if t == "pickers"][-1]
    assert pay["speed"] is big and len(json.dumps(big, separators=(",", ":"))) <= SPEED_ATTR_MAX
    size = len(json.dumps(pay, separators=(",", ":")))
    assert size < 8000 and size + 160 <= 12 * 1024, size
    assert W.cap_attrs("pickers", pay) is pay  # the backstop (ATTR_MAX) leaves it whole


def test_a_pilots_instance_publishes_its_own(tmp_path, monkeypatch):
    from test_instance import _load
    W2 = _load(tmp_path, monkeypatch, "james", {"username": "u", "password": "p", "log_level": "info",  # noqa: N806
                                                "category_check": "HNL 332 FO"})
    sent = []
    monkeypatch.setattr(W2, "pub", lambda t, p, retain=True: sent.append((t, p)))
    monkeypatch.setattr(W2, "DB", Store(str(tmp_path / "james.db")))
    monkeypatch.setattr(W2, "CARD_PAIRINGS", str(tmp_path / "www"))
    other = Store(str(tmp_path / "ryan.db"))  # another instance's store: never read by this one
    for i in range(6):
        _pick(other, f"H97{i:02d}|20Nov", _utc(17, 19, i), 60)
    _pick(W2.DB, "H9650|20Nov", _utc(18, 7), 300, lay="SYD")
    W2.publish_pickers()
    assert W2.T == "flight_watcher_james"
    pay = [p for t, p in sent if t == "pickers"][-1]
    assert pay["speed"]["n"] == 1 and pay["speed"]["city"] == [["SYD", 1, 300, 300, 0, 0]] and pay["speed"]["tip"] == ""


def test_the_contract_is_unchanged():
    """No new export: the pickers sensor and its list file were exported before (state.json, file:pickers)."""
    import roles
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "portal_contract_v1.json"), encoding="utf-8"))
    assert roles.CONTRACT_REVISION == fx["revision"] == 6
    assert fx["file_kinds"]["pickers"] == "" and "speed" not in json.dumps(fx["file_kinds"])
    assert fx["masks"]["zero"] == ["file_key", "versions_file_key"] and fx["masks"]["drop"] == ["contact"]


# ---------------------------------------------------------------- the card in Chromium
def _world(W, many=True):  # noqa: F811
    """Pickups as the Store scores them: LAX fast on Tuesday evenings, SYD slow mornings, a few NRT trips, one capped."""
    db = W.DB
    n = 0

    def add(lay, d, h, secs, emp="10001"):
        nonlocal n
        n += 1
        _pick(db, f"H9{n:03d}|2{n % 9}Nov", _utc(d, h, n % 50), secs, emps=(emp,), lay=lay, by=f"FO Doe, Jane ({emp})")
    for s in (150, 200, 240, 260, 300, 330, 420):
        add("LAX", 17, 19, s)  # Tue 18-24
    for s in (900, 1100, 1300, 1500, 1700, 2600):
        add("SYD", 18, 8, s, "10002")  # Wed 06-12
    for s in (40, 70, 90):
        add("NRT", 19, 13, s, "10003")  # Thu 12-18: only 3
    if many:  # seven more layovers, none with 5 pickups, on Mon and Fri to Sun
        for lay, d, h, s in (("SEA", 16, 3, 400), ("OGG", 16, 8, 490), ("OGG", 20, 3, 520), ("PPT", 20, 8, 580),
                             ("PPT", 21, 13, 610), ("PPT", 22, 3, 640), ("AKL", 21, 8, 670), ("AKL", 22, 13, 700),
                             ("AKL", 16, 3, 730), ("AKL", 20, 13, 760), ("BNE", 21, 3, 760), ("LAS", 22, 8, 850),
                             ("LAS", 16, 13, 880)):
            add(lay, d, h, s, "10004")
    assert db.set_req_cap("H9001|21Nov", "2026-11-17T19:02-10:00", "10001") == "capped"
    W.publish_pickers()
    return [p for t, p in W.SENT if t == "pickers"][-1]


def _card_page(b, width, height, scheme, pay, cfg="{open: true}", ready="tbody tr"):
    import cards
    from test_fw171_cards import HARNESS_JS, PORTAL_CSS
    built = cards.build("9.9.9", [])
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>"
            + HARNESS_JS + "</script><script type='module'>" + built["flight-watcher-pickers-card.js"] + "</script></body></html>")
    ctx.route("https://ha.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html)
              if r.request.url == "https://ha.test/" else r.fulfill(status=404, body=""))
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.goto("https://ha.test/")
    lu = "2026-11-18T21:00:00+00:00"
    attrs = {k: v for k, v in pay.items() if k not in ("file_key", "rev")}  # the sensor's own short list
    st = {"sensor.flight_watcher_pickers": {"state": str(pay["count"]), "last_updated": lu, "last_changed": lu,
                                            "attributes": attrs}}
    pg.wait_for_function("!!customElements.get('flight-watcher-pickers-card')")
    pg.evaluate("(st) => { window.PC = mount('flight-watcher-pickers-card', " + cfg + ", st); window.ST = st; }", st)
    pg.wait_for_function(f"PC.shadowRoot && PC.shadowRoot.querySelector('{ready}')")
    return pg


HUNT = """() => { const h = PC.shadowRoot.querySelector('.hunt'); if (!h) return null;
  const d = h.querySelector('details');
  return { title: h.querySelector('.htl').textContent, tip: h.querySelector('.tip').textContent, open: d.open,
    summary: d.querySelector('summary').textContent,
    tables: [...h.querySelectorAll('table')].map((t) => ({ cap: t.querySelector('caption').textContent,
      rows: [...t.querySelectorAll('tbody tr')].map((tr) => ({ cells: [...tr.children].map((td) => td.textContent),
        few: tr.classList.contains('few'), color: getComputedStyle(tr.children[0]).color,
        title: tr.getAttribute('title') || '' })) })),
    more: (h.querySelector('.more') || { textContent: '' }).textContent,
    sec: getComputedStyle(h.querySelector('.note')).color }; }"""


def test_the_when_to_hunt_section_on_the_pickers_card(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W)
    sp = pay["speed"]
    assert sp["city"][0][0] == "LAX" and sp["city"][1][0] == "SYD"  # trusted by median
    assert {g[0] for g in sp["city"][2:]} == {"NRT", "SEA", "OGG", "PPT", "AKL", "BNE", "LAS"}
    assert sp["city"][0][4] == 1  # the capped LAX pickup
    with _browser() as b:
        for width, height, scheme in ((390, 844, "light"), (390, 844, "dark"), (1280, 800, "light")):
            pg = _card_page(b, width, height, scheme, pay)
            h = pg.evaluate(HUNT)
            assert h["title"] == "When to hunt" and h["tip"] == sp["tip"]
            assert h["tip"] == "Trips go fastest when they enter the pot Tue 18-24 HST: median at most 4 min (n 7)."
            assert h["open"] is False  # long: collapsed by default
            assert [t["cap"] for t in h["tables"]] == ["Layover", "Day (HST)", "Time (HST)"]
            for t, key in zip(h["tables"], ("city", "dow", "band")):
                assert [r["cells"][0].split(" ")[0] for r in t["rows"]] == [g[0] for g in sp[key]], key
                assert [r["few"] for r in t["rows"]] == [g[1] < 5 for g in sp[key]], key
                for r, g in zip(t["rows"], sp[key]):
                    assert r["cells"][-1] == str(g[1])
                    if g[1] < 5:  # grey, in the theme's secondary text color, with the reason on hover
                        assert r["color"] == h["sec"] and "too few to trust" in r["title"]
                    else:
                        assert r["color"] != h["sec"] and r["title"] == ""
            lax = h["tables"][0]["rows"][0]["cells"]
            # 1 of its 7 capped at Ryan's request time: the median is "at most", and so is the fastest (the capped one)
            assert lax == ["LAX", "≤4m 20s", "≤1m 59s", "7"], lax
            syd = h["tables"][0]["rows"][1]["cells"]
            assert syd[0] == "SYD" and "≤" not in syd[1] + syd[2]
            # the toggle stays as the viewer left it through the next sensor update
            pg.evaluate("() => { PC.shadowRoot.querySelector('.hunt summary').click(); }")
            pg.evaluate("() => { const s = JSON.parse(JSON.stringify(ST)); s['sensor.flight_watcher_pickers'].attributes.speed.n += 1;"
                        " PC.hass = mkHass(s); }")
            assert pg.evaluate("() => PC.shadowRoot.querySelector('.hunt details').open") is True
            assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
            c = pg.evaluate("() => fwContrast(PC)")
            assert c["fails"] == [], c["fails"]
            assert pg.errors == []
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.locator("flight-watcher-pickers-card").first.screenshot(
                    path=os.path.join(SHOTS, f"item7_{width}_{scheme}.png"))
            pg.context.close()


def test_a_short_section_is_open_and_an_old_sensor_shows_none(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W, many=False)
    with _browser() as b:
        pg = _card_page(b, 390, 844, "light", pay)
        h = pg.evaluate(HUNT)
        assert h["open"] is True and sum(len(t["rows"]) for t in h["tables"]) <= 12
        if SHOTS:
            pg.locator("flight-watcher-pickers-card").first.screenshot(path=os.path.join(SHOTS, "item7_390_short.png"))
        old = {k: v for k, v in pay.items() if k != "speed"}
        pg.evaluate("(a) => { const s = JSON.parse(JSON.stringify(ST)); s['sensor.flight_watcher_pickers'].attributes = a;"
                    " PC.hass = mkHass(s); }", old)
        assert pg.evaluate(HUNT) is None and pg.errors == []
        none = dict(pay, speed={"n": 0, "min_n": 5, "city": [], "dow": [], "band": [], "tip": "", "more": 0})
        pg.evaluate("(a) => { const s = JSON.parse(JSON.stringify(ST)); s['sensor.flight_watcher_pickers'].attributes = a;"
                    " PC.hass = mkHass(s); }", {k: v for k, v in none.items() if k not in ("file_key", "rev")})
        assert pg.evaluate(HUNT) is None
        pg.context.close()


def test_a_trimmed_city_list_says_how_many_are_left_out(W, tmp_path):  # noqa: F811
    from test_pilot_grid_look import _browser
    pay = _world(W, many=False)
    pay = dict(pay, speed=dict(pay["speed"], more=12))
    with _browser() as b:
        pg = _card_page(b, 390, 844, "light", pay)
        assert pg.evaluate(HUNT)["more"] == "12 more layovers with fewer pickups not shown."
        pg.context.close()


@pytest.mark.parametrize("path", ["store.py", "watcher.py", "www/flight-watcher-pickers-card.js", "README.md",
                                  "tests/test_fw1716_speed.py", "tests/test_fw1716_review.py"])
def test_no_em_dash(path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert chr(0x2014) not in open(os.path.join(here, path), encoding="utf-8").read()

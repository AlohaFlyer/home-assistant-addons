"""1.2.1: pay.py mirrors the schedule card's pay rules; price_request prices decided requests. Synthetic data."""
import json
import os
import re
import shutil
import subprocess

import pytest

import pay as PAY
import submit as SUB

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-schedule-card.js")


def test_rate_table_matches_the_card():
    src = open(CARD, encoding="utf-8").read()
    dates = json.loads(re.search(r"const RATE_DATES = (\[.*?\]);", src).group(1))
    table = json.loads(re.search(r"const RATE_TABLE = (\[.*?\]);", src, re.S).group(1))
    assert dates == PAY.RATE_DATES and table == PAY.RATE_TABLE
    assert re.search(r"IRO_OVERRIDE = 4\.00, ER_PCT = 0\.15", src)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_trip_gross_matches_the_cards_tripfull(tmp_path):
    src = open(CARD, encoding="utf-8").read()
    head = src[:src.index("class FlightWatcherScheduleCard")]
    erOn = re.search(r"(const erOn = .*?;)\n", src).group(1)
    crewN = re.search(r"(const crewN = .*?;)\n", src).group(1)
    tf = re.search(r"(const tripFull = .*?return cr == null.*?;\s*\};)", src, re.S).group(1)
    cases = [(11 + 20 / 60, 11 + 20 / 60, "CA02FO01", "PPG", "H3601|2026-11-26", "FO", []),
             (16.5, 14.0, "CA01FO01RO01", "NRT", "H3633|2026-11-26", "RO", []),
             (16.5, 14.0, "CA01FO01RO01", "NRT", "H3633|2026-11-26", "FO", []),
             (20.0, 17.5, "CA02FO02", "SIN", "H3700|2026-12-03", "FO", []),
             (20.0, 17.5, "CA02FO02", "SIN", "H3700|2026-12-03", "FO", ["-H3700|2026-12-03"]),
             (9.0, 8.0, "", "SIN", "H3701|2026-12-03", "FO", []),
             (9.0, 8.0, "CA01FO01", "LAX", "H3702|2026-12-03", "CA", ["+H3702|2026-12-03"])]
    js = head.replace("customElements", "//") + "\nconst out = [];\n"
    for i, (cr, blk, crew, lay, key, seat, er) in enumerate(cases):
        js += (f"{{ const RATE = rateFor(7, '2026-11-06'); const erOv = {json.dumps(er)}; {crewN} {erOn} {tf} "
               f"out.push(tripFull({cr}, {blk}, {json.dumps(crew)}, {json.dumps(lay)}, {json.dumps(key)}, {json.dumps(seat)})); }}\n")
    js += "console.log(JSON.stringify(out));"
    f = tmp_path / "t.js"
    f.write_text(js)
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    want = json.loads(res.stdout)
    rate = PAY.rate_for(7, "2026-11-06")
    got = [PAY.trip_gross(cr, blk, crew, lay, key, seat, rate, er) for cr, blk, crew, lay, key, seat, er in cases]
    assert got == pytest.approx(want)


def test_helpers():
    assert PAY.hrs("11h20") == pytest.approx(11 + 1 / 3) and PAY.hrs("5:00") == 5 and PAY.hrs("x") is None
    assert PAY.doh_year("2015-06-01", "2026-11-06") == 12 and PAY.rate_for(12, "2026-11-06") == 307.78
    assert PAY.rate_for(99, "2026-11-06") == 307.78 and PAY.rate_for(1, "2022-01-01") == 81.00
    assert PAY.usd(1234.4) == "+$1,234" and PAY.usd(-567.6) == "-$568"


def test_legs_from_page_words():
    rows = SUB.parse_request_rows("11/05 09:10 swap approved drop h3629 12nov add h3815b 14nov")
    assert rows[0]["legs"] == [{"trip": "H3629", "day": "12NOV", "side": "drop"},
                               {"trip": "H3815B", "day": "14NOV", "side": "add"}]
    rows = SUB.parse_request_rows("11/05 09:10 add approved h3620 28nov")  # the type word is not a leg label
    assert rows[0]["legs"] == [{"trip": "H3620", "day": "28NOV", "side": ""}]


def _w(tmp_path, monkeypatch):
    from test_instance import _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info", "category_check": "HNL 332 FO"})
    www = tmp_path / "www"
    www.mkdir()
    json.dump({"month": "2026-11", "cols": ["id", "route", "credit", "block", "crew"],
               "rows": [["H3629", "HNL-LAX-HNL", "10h00", "9h00", "CA01FO01"], ["H3815", "HNL-NRT-HNL", "16h30", "14h00", "CA01FO01RO01"],
                        ["H3620", "HNL-SFO-HNL", "11h00", "10h00", "CA01FO01"]]}, open(www / "pairings_2026-11.json", "w"))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(www))
    monkeypatch.setattr(W, "ha_state", lambda e: {"input_number.flight_watcher_longevity_year": "7.0",
                                                  "input_text.flight_watcher_er_trips": ""}.get(e))
    W.S["schedule"] = {"2026-11": {"items": []}}
    W.DB.put("sched_versions:2026-11", [{"ver": "11.001", "at": "2026-11-01T10:00:00+00:00",
                                         "items": [{"trip": "H3629", "start": "2026-11-12"}]}])
    W.S["own_trips"] = {"H3629|2026-11-12": {"credit": "10:30", "blk": "9:00", "seat": "FO"}}
    return W


def test_price_swap_pickup_drop(tmp_path, monkeypatch):
    from datetime import datetime
    W = _w(tmp_path, monkeypatch)
    now = datetime(2026, 11, 6, 8, 0, tzinfo=W.HST)
    rate = PAY.rate_for(7, W.local_now().date().isoformat())
    # swap without page words: the trip Ryan held when he filed (H3629) is the one given
    r = SUB.parse_request_rows("11/05 09:10 swap approved h3629 12nov h3815b 14nov")[0]
    p = W.price_request(r, now)
    give = 10.5 * rate                      # his own record's credit, FO, 2-pilot crew
    take = 16.5 * rate + 14.0 * 3.00        # package credit, FO on a 3-pilot crew: $3 per block hour (PWA 4.O.1)
    assert [x["side"] for x in p["parts"]] == ["drop", "add"]
    assert p["delta"] == pytest.approx(round(take - give, 2), abs=0.02) and p["year"] == 7
    assert p["delta_text"] == PAY.usd(take - give)
    # pickup (Add): all gain; drop: all loss
    a = W.price_request(SUB.parse_request_rows("11/05 09:10 add approved h3620 28nov")[0], now)
    assert a["delta"] == pytest.approx(11 * rate, abs=0.02) and a["delta"] > 0
    d = W.price_request(SUB.parse_request_rows("11/05 09:10 drop approved h3629 12nov")[0], now)
    assert d["delta"] == pytest.approx(-10.5 * rate, abs=0.02) and d["delta_text"].startswith("-$")
    # denied, or a trip the package does not know: no amount
    assert W.price_request(SUB.parse_request_rows("11/05 09:10 add denied h3620 28nov")[0], now) is None
    assert W.price_request(SUB.parse_request_rows("11/05 09:10 add approved h9999 28nov")[0], now) is None


def test_no_rate_means_no_amount(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    monkeypatch.setattr(W, "ha_state", lambda e: None)  # no helper, no DOH file
    assert W.price_request(SUB.parse_request_rows("11/05 09:10 add approved h3620 28nov")[0]) is None


def test_type_and_held_trips_decide_the_sides(tmp_path, monkeypatch):
    from datetime import datetime
    W = _w(tmp_path, monkeypatch)
    now = datetime(2026, 11, 6, 8, 0, tzinfo=W.HST)
    rate = PAY.rate_for(7, W.local_now().date().isoformat())
    base = SUB.parse_request_rows("11/05 09:10 add approved")[0]
    add = {**base, "legs": [{"trip": "H3620", "day": "28NOV", "side": "drop"}]}  # a page word said drop: the type wins
    assert W.price_request(add, now)["delta"] == pytest.approx(11 * rate, abs=0.02)
    swap = {**base, "type": "Swap", "legs": [{"trip": "H3629", "day": "12NOV", "side": "add"},
                                            {"trip": "H3815B", "day": "14NOV", "side": "drop"}]}
    p = W.price_request(swap, now)  # inverted page words: the trip he held when he filed is the one given
    assert [(x["trip"], x["side"]) for x in p["parts"]] == [("H3629", "drop"), ("H3815B", "add")]
    W.DB.put("sched_versions:2026-11", [])  # no schedule version on file: page words only when they name both sides
    one = {**swap, "legs": [{"trip": "H3629", "day": "12NOV", "side": "drop"}, {"trip": "H3815B", "day": "14NOV", "side": ""}]}
    assert W.price_request(one, now) is None


def test_trade_prices_taken_ro_seat_and_same_pairing_twice(tmp_path, monkeypatch):
    """1.4.1 (Ryan, Nov 6): a Trade gives the trips he held and takes the rest; a taken trip flown in the RO seat (the
    view page's (R)) gets the PWA 4.O.1 $4.00 per block hour override, and the same pairing taken on two days counts
    twice. Made-up trips and numbers."""
    from datetime import datetime
    W = _w(tmp_path, monkeypatch)
    now = datetime(2026, 11, 6, 8, 0, tzinfo=W.HST)
    rate = PAY.rate_for(7, W.local_now().date().isoformat())
    r = {**SUB.parse_request_rows("11/05 09:10 trade approved")[0], "type": "Trade", "legs": SUB.parse_request_view(
        "trade h3629:12nov (f) with emp #: 12345 for h3620:20nov (r) and h3620:23nov (f) time: 11/05 09:10 status: approved")["legs"]}
    p = W.price_request(r, now)
    assert [(x["trip"], x["start"], x["side"]) for x in p["parts"]] == [
        ("H3629", "2026-11-12", "drop"), ("H3620", "2026-11-20", "add"), ("H3620", "2026-11-23", "add")]
    give = 10.5 * rate
    take = (11 * rate + 10.0 * 4.00) + 11 * rate    # RO seat: $4.00 per block hour; FO on a 2-pilot crew: no override
    assert p["delta"] == pytest.approx(round(take - give, 2), abs=0.02)

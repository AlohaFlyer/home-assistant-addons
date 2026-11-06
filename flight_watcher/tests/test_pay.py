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


# ---------------------------------------------------------------- FW-0062: Captain rates and the rebuilt month's pay line
def test_captain_rate_table_and_seat():
    """PWA 3.C.4 (Captain) next to PWA 3.D.6 (FO): same dates, 12 years; an RO is paid the FO rate; the FO numbers and
    the two-argument call are unchanged."""
    assert len(PAY.RATE_TABLE_CA) == 12 and all(len(r) == len(PAY.RATE_DATES) for r in PAY.RATE_TABLE_CA)
    assert all(ca > fo for rc, rf in zip(PAY.RATE_TABLE_CA, PAY.RATE_TABLE) for ca, fo in zip(rc, rf))
    assert all(a < b for r in PAY.RATE_TABLE_CA for a, b in zip(r, r[1:]))  # each raise date pays more
    assert all(a[i] < b[i] for a, b in zip(PAY.RATE_TABLE_CA, PAY.RATE_TABLE_CA[1:]) for i in range(5))  # and each year
    assert PAY.rate_for(1, "2023-03-02", "CA") == 359.68 and PAY.rate_for(1, "2023-03-02") == 81.00  # 3.D.1: FO year 1 only
    assert PAY.rate_for(9, "2026-11-06", "CA") == 431.04 and PAY.rate_for(12, "2027-02-01", "ca") == 454.18
    assert PAY.rate_for(99, "2026-11-06", "CA") == 440.95 and PAY.rate_for(0, "2022-01-01", "CA") == 359.68
    for seat in ("FO", "RO", "", None):
        assert PAY.rate_for(7, "2026-11-06", seat) == PAY.rate_for(7, "2026-11-06") == 282.66


def test_trip_gross_captain_rules():
    """PWA 4.O.1: a Captain gets $5.00 per block hour on any crew of 3 or more and never the type-rated FO's 15%; off by
    default (the schedule card's tripFull parity above), on for another pilot's pay line."""
    r = PAY.rate_for(9, "2026-11-06", "CA")
    assert PAY.trip_gross(20.0, 17.5, 3, "NRT", "k", "CA", r, ca_rules=True) == pytest.approx(20 * r + 17.5 * 5.00)
    assert PAY.trip_gross(20.0, 17.5, "CA02FO02", "SIN", "k", "CA", r, ca_rules=True) == pytest.approx(20 * r + 17.5 * 5.00)
    assert PAY.trip_gross(10.0, 9.0, 2, "LAX", "k", "CA", r, ["+k"], ca_rules=True) == pytest.approx(10 * r)
    assert PAY.trip_gross(20.0, None, 3, "NRT", "k", "CA", r, ca_rules=True) == pytest.approx(20 * r)
    assert PAY.trip_gross(20.0, 17.5, "CA02FO02", "SIN", "k", "CA", r) == pytest.approx(20 * r * 1.15)  # default: as before
    fo = PAY.rate_for(9, "2026-11-06")
    for seat, n, want in (("FO", 3, 16.5 * fo + 14 * 3.00), ("RO", 3, 16.5 * fo + 14 * 4.00), ("FO", 2, 16.5 * fo),
                          ("FO", 4, 16.5 * fo * 1.15), ("RO", 4, 16.5 * fo + 14 * 4.00 + 16.5 * fo * 0.15)):
        assert PAY.trip_gross(16.5, 14.0, n, "NRT", "k", seat, fo, ca_rules=True) == pytest.approx(want)  # FO / RO unchanged
        assert PAY.trip_gross(16.5, 14.0, n, "NRT", "k", seat, fo) == pytest.approx(want)
    assert PAY.crew_n(3) == 3 and PAY.crew_n("CA01FO01RO01") == 3 and PAY.crew_n(None) == 0
    assert [PAY.overrides_due(s, n) for s, n in (("RO", 2), ("CA", 3), ("CA", 2), ("FO", 3), ("FO", 4))] == [True, True, False, True, False]


def _t(pid, s, e, seat, cr, blk, n, soft="", lay="", route="HNL-NRT-HNL"):
    return {"pairing": pid, "start": s, "end": e, "seat": seat, "credit": cr, "blk": blk, "soft": soft, "n": n,
            "lay": lay, "route": route}


TRIPS = [_t("H9001", "2026-10-31", "2026-11-02", "FO", "12:34", "9:58", 2, "2:36", "LAX"),  # last period's: not totaled
         _t("H9002", "2026-11-05", "2026-11-07", "CA", "20:00", "17:30", 3, "2:30", "NRT"),
         _t("H9003", "2026-11-12", "2026-11-14", "RO", "16:30", "14:00", 3, "2:30"),
         _t("H9004", "2026-11-20", "2026-11-23", "FO", "20:00", "17:30", 4, "2:30", "SIN", "HNL-SIN-HNL"),
         _t("H9005", "2026-11-26", "2026-11-26", "FO", "", "", 2),
         _t("H9006", "2026-11-28", "2026-11-30", "FO", "12:00", "", 3),
         _t("H9007", "2026-12-01", "2026-12-03", "FO", "16:35", "16:35", 2, "0:00", "", "HNL-SYD-HNL")]


def test_pay_line_prices_each_seat():
    line, per = PAY.pay_line(TRIPS, "2018-10-03", "2026-11-01", "2026-12-01", 22.0)
    ca, fo = PAY.rate_for(9, "2026-11-01", "CA"), PAY.rate_for(9, "2026-11-01")
    want = {"H9002|2026-11-05": 20 * ca + 17.5 * 5.00,             # CA on a 3-pilot crew: $5.00 / block h, no 15%
            "H9003|2026-11-12": 16.5 * fo + 14 * 4.00,             # RO: FO rate + $4.00 / block h
            "H9004|2026-11-20": 20 * fo * 1.15,                    # FO on a 4-pilot crew: Extended Range +15%
            "H9006|2026-11-28": 12 * fo,                           # no block: the $3.00 override cannot be added
            "H9007|2026-12-01": (16 + 35 / 60) * fo}
    assert per == pytest.approx({k: round(v, 2) for k, v in want.items()})
    assert line["gross"] == pytest.approx(sum(want.values()), abs=0.01)
    assert line["net"] == pytest.approx(line["gross"] * 0.78, abs=0.01) and line["tax_pct"] == 22.0
    assert (line["doh_known"], line["doh"], line["year"], line["year_to"]) == (True, "2018-10-03", 9, None)
    assert line["seat_rates"] == {"CA": ca, "FO": fo} and line["seats"] == ["CA", "FO", "RO"]
    assert (line["trips"], line["trips_priced"], line["credit"], line["credit_n"]) == (6, 5, "85:05", 5)
    assert (line["block"], line["block_n"], line["soft"], line["soft_n"]) == ("65:35", 4, "7:30", 4)
    assert line["missing"] == [{"pairing": "H9005", "start": "2026-11-26"}]
    assert line["no_block"] == [{"pairing": "H9006", "start": "2026-11-28"}]
    assert line["days_off"] == 31 - 17  # Nov 1-2 (the Oct 31 trip), 5-7, 12-14, 20-23, 26, 28-30, Dec 1


def test_pay_line_longevity_and_no_doh():
    # the DOH anniversary inside the bid period: year 8 to 9, each trip at its own start date
    line, per = PAY.pay_line(TRIPS, "2018-11-15", "2026-11-01", "2026-12-01", 0)
    assert (line["year"], line["year_to"]) == (8, 9)
    assert per["H9002|2026-11-05"] == pytest.approx(round(20 * PAY.rate_for(8, "2026-11-05", "CA") + 17.5 * 5, 2))
    assert per["H9004|2026-11-20"] == pytest.approx(round(20 * PAY.rate_for(9, "2026-11-20") * 1.15, 2))
    assert line["net"] == line["gross"]
    for doh in ("", None, "not a date"):  # no date of hire: hours and days, no amounts
        line, per = PAY.pay_line(TRIPS, doh, "2026-11-01", "2026-12-01", 22.0)
        assert per == {} and line["gross"] is None and line["net"] is None and line["doh_known"] is False
        assert line["year"] is None and line["seat_rates"] == {} and line["trips_priced"] == 0
        assert (line["credit"], line["days_off"], line["trips"]) == ("85:05", 14, 6)
    line, _ = PAY.pay_line([], "2018-10-03", "2026-11-01", "2026-12-01", 22.0)
    assert line["gross"] is None and line["days_off"] == 31 and line["credit"] == "0:00"

"""1.7.7 review fixes, another pilot's pay (Ryan, Nov 14: the totals line shows the month's Pay-Gross "as Ryan's
does"). Synthetic pilots and pairings only (Roe, Rick 10999; Doe, Jane 10001; H9001...).
- The month is the schedule card's: trips that start in the calendar month, each its PWA 4.A share (a segment pays on
  the date it originates), vacation days at 4:00 (PWA 6.J.1.c), a PAYP at FLICA's credit less the rest (estimate).
- A version is priced from the live read of the same trip (crew count, page credit), as the live month is.
- Each trip's package is its own bid period's; another fleet's pilot is not priced at the A330 rates; the rate note
  carries a mid-month step; a pilot instance publishes another pilot's DOH in both pay lines again (1.7.7)."""
import json
import os
import sys

import pytest

import pay as PAY
import versions as VER
from test_crew_index import ROE, FakeFl, W, _file, _row, _sen  # noqa: F401
from test_pilot_price import Fl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CA = PAY.rate_for(9, "2026-11-02", "CA")
FO = PAY.rate_for(9, "2026-11-13", "FO")


def _setup(W, tmp_path, monkeypatch, seniority=None):  # noqa: F811
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=2), _row("H9002", "13", rel=1, route="HNL-SEA-HNL", block="9:30")])
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, seniority or {"10999": ROE}))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    W.S["cm_prompt_captured"] = True
    W.S["pilot_req"] = {"emp": "10999", "name": "Roe, Rick", "at": ""}
    W.DB.put("pkg_details:2026-11", {"H9001": {"credit": "12:30", "block": "11:00", "lay": "LAX", "route": "HNL-LAX-HNL"},
                                     "H9002": {"credit": "12:00", "block": "9:30", "lay": "SEA", "route": "HNL-SEA-HNL"}})


def _vfile(tmp_path, p):
    return json.loads((tmp_path / "www" / f"pilotver_{p['versions_file_key']}.json").read_text())


# ---------------------------------------------------------------- versions priced as the live month
def test_an_unchanged_trip_has_the_same_gross_live_and_in_its_version(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    fl = Fl({"H9001": "ca 10999 roe, rick fo 10001 doe, jane ro 10002 poe, pat",
             "H9002": "ca 10001 doe, jane fo 10999 roe, rick ro 10003 moe, kim"})
    assert W.pilot_check(fl)
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    live = {it["trip"]: it for it in p["items"] if it.get("trip", "").startswith("H")}
    rec = _vfile(tmp_path, p)["10999"]["months"]["2026-11"][-1]
    ver = {it["trip"]: it for it in rec["items"]}
    assert live["H9001"]["gross"] == pytest.approx(round(12.5 * CA + 11 * 5.00, 2))  # PWA 4.O.1: CA on 3 pilots
    assert live["H9002"]["gross"] == pytest.approx(round(12 * FO + 9.5 * 3.00, 2))  # FO on 3 pilots
    for k in ("H9001", "H9002"):
        assert ver[k]["gross"] == pytest.approx(live[k]["gross"])
    assert rec["pay"]["gross"] == pytest.approx(p["items_pay"]["gross"], abs=0.02)
    assert "n" not in ver["H9001"] and "credit" not in ver["H9001"]  # the file's items stay the version's own


def test_a_version_prices_the_pages_credit_the_card_shows(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    fl = Fl({"H9001": "ca 10001 doe, jane fo 10999 roe, rick"},
            legs={"H9001": "mo 900 hnl-lax 0830 1600 0530 we 901 lax-hnl 1000 1300 0530 blk : 1100 pay : 1330"})
    monkeypatch.setattr(W, "PILOT_PAIRINGS_MAX", 1)
    assert W.pilot_check(fl)
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    live = {it["trip"]: it for it in p["items"]}
    ver = {it["trip"]: it for it in _vfile(tmp_path, p)["10999"]["months"]["2026-11"][-1]["items"]}
    assert live["H9001"]["credit"] == "13:30" and live["H9001"]["gross"] == pytest.approx(round(13.5 * FO, 2))
    assert ver["H9001"]["gross"] == pytest.approx(live["H9001"]["gross"])  # 13:30 (the page), not the package's 12:30


# ---------------------------------------------------------------- PWA 4.A and the calendar month
DUTIES = [{"d": 0, "dep": 1380, "arr": 1722, "stn": "SEA", "blk": 342}, {"d": 1, "dep": 2415, "arr": 2720, "stn": "SFO", "blk": 305},
          {"d": 2, "dep": 3900, "arr": 4250, "stn": "HNL", "blk": 350}]


def test_a_trip_into_next_month_counts_its_pwa_4a_share(W, tmp_path, monkeypatch):  # noqa: F811
    """H9103 Nov 29 to Dec 1, duty 3 departs Dec 1: Ryan's card shows Credit 11:41 and $3,596 for it in November
    (DOH 2014-11-15, FO, year 12): the pilot card now shows the same."""
    _setup(W, tmp_path, monkeypatch, {"10999": dict(ROE, doh="2014-11-15")})
    W.DB.put("pkg_details:2026-11", {"H9103": {"credit": "18:00", "block": "16:37", "lay": "SEA", "duties": DUTIES}})
    items = [{"trip": "H9103", "start": "2026-11-29", "end": "2026-12-01", "lay": "SEA", "credit": "18:00", "blk": "16:37",
              "seat": "FO", "n": 2}]
    line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    sp = info["H9103|2026-11-29"]["split"]
    share = (342 + 305) / (342 + 305 + 350)
    assert (sp["credit"], sp["blk"], sp["all_credit"], sp["next"]) == (PAY.hm(18 * share), PAY.hm((16 + 37 / 60) * share),
                                                                         "18:00", "2026-12")
    assert sp["credit"] == "11:41" and sp["out_blk"] == "5:50"
    assert line["credit"] == "11:41"
    assert round(info["H9103|2026-11-29"]["gross"]) == 3596 == round(PAY.hrs("11:41") * PAY.rate_for(12, "2026-11-29"))


def test_a_trip_from_the_bid_periods_last_day_is_next_months(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    items = [{"trip": "H9002", "start": "2026-12-01", "end": "2026-12-02", "lay": "SEA", "credit": "12:00", "blk": "9:30",
              "seat": "FO", "n": 2}]
    line, _ = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    assert line["trips"] == 0 and line.get("gross") is None  # December's on Ryan's card, and here


def test_the_split_also_comes_from_the_pairing_pages_legs(W, tmp_path, monkeypatch):  # noqa: F811
    """No package duties for the trip: the legs the pairing page gave place each duty (weekday) in its month."""
    _setup(W, tmp_path, monkeypatch)
    legs = [{"dow": "MO", "route": "HNL-SEA", "dep": "2300", "arr": "0642", "blk": "0542"},
            {"dow": "TU", "route": "SEA-HNL", "dep": "1830", "arr": "2255", "blk": "0625"}]
    items = [{"trip": "H9105", "start": "2026-11-30", "end": "2026-12-01", "credit": "15:00", "blk": "12:07", "seat": "FO",
              "n": 2, "legs": legs}]
    _line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    sp = info["H9105|2026-11-30"]["split"]
    assert sp["credit"] == PAY.hm(15 * 342 / (342 + 385)) and sp["next"] == "2026-12" and sp["out_blk"] == "6:25"


# ---------------------------------------------------------------- vacation and PAYP
def test_vacation_and_payp_count_as_on_ryans_card(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    trip = {"trip": "H9001", "start": "2026-11-02", "end": "2026-11-04", "lay": "LAX", "credit": "12:30", "blk": "11:00", "seat": "FO", "n": 2}
    vac = {"trip": "VAC", "start": "2026-11-20", "end": "2026-11-26", "lay": ""}  # 7 days = 28:00 (PWA 6.J.1.c)
    payp = {"trip": "PAYP", "start": "2026-11-12", "end": "2026-11-14", "lay": ""}
    only, _ = W.pilot_price([trip], "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01")
    # FLICA's month credit 52:00: the PAYP's credit is the rest, 52:00 - 12:30 - 28:00 = 11:30 (an estimate)
    line, _ = W.pilot_price([trip, vac, payp], "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20,
                            {"credit": "52:00"})
    assert (line["vac"], line["vac_days"], line["payp"], line["payp_est"]) == ("28:00", 7, "11:30", True)
    assert line["credit"] == "52:00"
    rate = PAY.rate_for(9, "2026-11-20", "FO")
    assert line["gross"] == pytest.approx(only["gross"] + 28 * rate + 11.5 * PAY.rate_for(9, "2026-11-12"), abs=0.02)
    # no FLICA credit: the PAYP's credit is unknown and not counted (the card says so, never a red FLICA figure)
    unk, _ = W.pilot_price([trip, vac, payp], "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01")
    assert unk["payp_unk"] is True and "payp" not in unk and unk["credit"] == "40:30"
    assert unk["gross"] == pytest.approx(only["gross"] + 28 * rate, abs=0.02)


def test_a_flica_month_with_a_vac_day_counts_it(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    monkeypatch.setattr(W, "PILOT_PAIRINGS_MAX", 1)
    fl = Fl({"H9001": "ca 10001 doe, jane fo 10999 roe, rick"},
            legs={"H9001": "mo 900 hnl-lax 0830 1600 0530 we 901 lax-hnl 1000 1300 0530 blk : 1100 pay : 1230"})
    assert W.pilot_check(fl)
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    ip = p["items_pay"]
    pairings = sum(it["gross"] for it in p["items"] if it.get("gross") is not None)
    assert ip["gross"] == pytest.approx(pairings + 4 * PAY.rate_for(9, "2026-11-22", "FO"), abs=0.02)
    assert ip["credit"] == "28:30" and ip["vac"] == "4:00"


# ---------------------------------------------------------------- the trip's own bid period, the fleet, the rate note
def test_the_grids_first_day_takes_the_bid_period_before(W, monkeypatch):  # noqa: F811
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    W.DB.put("pkg_details:2026-11", {"H9102": {"credit": "13:15", "block": "11:15", "lay": "LAX", "route": "HNL-LAX-HNL"}})
    W.DB.put("pkg_details:2026-12", {"H9102": {"credit": "5:00", "block": "4:00", "lay": "", "route": "HNL-OGG-HNL"}})
    items = [{"trip": "H9102", "start": "2026-12-01", "end": "2026-12-02", "lay": "LAX"}]  # its page was not read
    _line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 20)
    assert (info["H9102|2026-12-01"]["credit"], info["H9102|2026-12-01"]["blk"]) == ("13:15", "11:15")  # November's


def test_another_fleets_pilot_is_not_priced_at_the_a330_rates(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch, {"10999": dict(ROE, equip="717")})
    items = [{"trip": "H9002", "start": "2026-11-13", "end": "2026-11-14", "lay": "SEA", "credit": "12:00", "blk": "9:30",
              "seat": "FO", "n": 2}]
    line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    assert line["equip"] == "717" and line.get("gross") is None and "gross" not in info["H9002|2026-11-13"]
    assert line["no_rate"] == [{"pairing": "H9002", "start": "2026-11-13", "seat": "FO"}] and line["seat_rates"] == {}
    # a 787 pilot: the PWA 3.C.4 table is the B787 Captain's too, so a Captain seat is priced, an FO seat is not
    _setup(W, tmp_path, monkeypatch, {"10999": dict(ROE, equip="B787")})
    W._SEN_CACHE.clear()
    ca = [dict(items[0], seat="CA")]
    line, info = W.pilot_price(ca, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    assert line["equip"] == "787" and info["H9002|2026-11-13"]["gross"] == pytest.approx(12 * PAY.rate_for(9, "2026-11-13", "CA"))
    assert set(line["seat_rates"]) == {"CA"}


def test_the_rate_note_carries_a_mid_month_step(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch, {"10999": dict(ROE, doh="2017-11-15")})
    items = [{"trip": "H9001", "start": "2026-11-02", "end": "2026-11-04", "credit": "12:30", "blk": "11:00", "seat": "FO", "n": 2},
             {"trip": "H9002", "start": "2026-11-20", "end": "2026-11-21", "credit": "12:00", "blk": "9:30", "seat": "FO", "n": 2}]
    line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 20)
    assert (line["year"], line["year_to"], line["seat_rates"]["FO"]) == (9, 10, PAY.rate_for(9, "2026-11-01"))
    assert line["rate_steps"] == [{"from": "2026-11-15", "year": 10, "CA": PAY.rate_for(10, "2026-11-15", "CA"),
                                   "FO": PAY.rate_for(10, "2026-11-15", "FO")}]
    assert info["H9002|2026-11-20"]["gross"] == pytest.approx(round(12 * PAY.rate_for(10, "2026-11-20"), 2))
    assert PAY.rate_steps("2017-11-15", "2027-01-20", "2027-02-10")[0]["from"] == "2027-01-31"  # a rate date step


# ---------------------------------------------------------------- a pilot instance: the DOH in both pay lines (1.7.7)
def test_a_pilot_instance_sends_another_pilots_doh_as_1_7_5_did(W, tmp_path, monkeypatch):  # noqa: F811
    """1.7.7 (Ryan, Nov 14: "james and I are on a high level of trust. he can be trusted"): both pay lines on a pilot
    instance carry the DOH, the list's dates, year_to and rate_steps, the same as Ryan's own instance."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "9", rel=2), _row("H9002", "20", rel=0, route="HNL-OGG-HNL")])
    W.crew_index_check(FakeFl())
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, {"10999": dict(ROE, doh="2018-11-12")}))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    assert W.ROLES.role(W.INSTANCE) != W.ROLES.ADMIN
    items = [{"trip": "H9001", "start": "2026-11-09", "end": "2026-11-11", "credit": "12:00", "blk": "10:00", "seat": "FO", "n": 2},
             {"trip": "H9002", "start": "2026-11-20", "end": "2026-11-20", "credit": "12:00", "blk": "10:00", "seat": "FO", "n": 2}]
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-11", "days": [], "items": items,
                 "totals": {"days_off": 20}})
    pilot = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    for line in (pilot["items_pay"], pilot["pay_line"]):
        assert line["year"] == 8 and line["doh_known"] is True and line["doh"] == "2018-11-12"
        assert line["year_to"] == 9 and line["rate_steps"][0]["from"] == "2026-11-12" and line["rate_steps"][0]["year"] == 9
        assert "list_date" in line and "list_newest_doh" in line
    # Ryan's own instance: the same lines
    monkeypatch.setattr(W, "INSTANCE", "")
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-11", "days": [], "items": items,
                 "totals": {"days_off": 20}})
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert p["items_pay"]["doh"] == p["pay_line"]["doh"] == "2018-11-12" and p["items_pay"]["year_to"] == 9
    assert {k: p[k] for k in ("items_pay", "pay_line")} == {k: pilot[k] for k in ("items_pay", "pay_line")}


def test_split_rule_matches_versions_split():
    """The pilot card's share is the schedule card's (versions._split, 'the schedule card's way')."""
    import watcher as W0
    share, out_b, nxt = W0._month_share("2026-11-29", "2026-12-01", {"duties": DUTIES}, None, "2026-11")
    assert round(18 * 60 * share) == VER._split("2026-11-29", {"duties": DUTIES}, 18 * 60)["2026-11"]
    assert (out_b, nxt) == (350, "2026-12")

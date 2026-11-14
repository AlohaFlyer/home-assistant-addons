"""1.7.6 (Ryan, Nov 14: "you should be able to calculate their pay by looking at their date of hire and seniority"):
another pilot's month as FLICA's Schedule Lookup showed it is priced like the rebuilt month: each pairing for the
seat that pilot flies on it (from the pairing page already read, else the crew index, else the seniority list's seat,
else FO), at his longevity year from the date of hire (PWA 3.B.1; CA PWA 3.C.4, FO and RO PWA 3.D.6) with the PWA
4.O.1 overrides; the month's totals in items_pay with FLICA's own Days Off. An older version of it is priced in the
versions file (amounts only, never a date of hire). A pilot instance's items_pay leaves out the DOH. No FLICA page is
read for any of it. Made-up pilots and pairings only."""
import json

import pytest

import pay as PAY
import pot
from test_crew_index import ROE, W, _file, _row, _sen  # noqa: F401  (W is the watcher fixture)
from test_crew_index_schedules import CrewFl

CM = ('<select><option value="1126" selected>Nov 2026</option></select><script>'
      'TAry[0]=new Task(1, "MO", "02", "H9001", "LAX", "20261101", 1, 0, \'H9001\');'
      'TAry[1]=new Task(1, "TU", "03", "", "-", "20261101", 1, 0, \'\');'
      'TAry[2]=new Task(1, "WE", "04", "", "HNL", "20261101", 1, 0, \'\');'
      'TAry[3]=new Task(1, "FR", "13", "H9002", "SEA", "20261101", 1, 0, \'H9002\');'
      'TAry[4]=new Task(1, "SA", "14", "", "HNL", "20261101", 1, 0, \'\');'
      'TAry[5]=new Task(1, "SU", "22", "VAC", "", "", 1, 0, \'\');</script>'
      '<p>ROE, RICK (Emp# 10999) Schedule Last Updated: Nov 4, 2026 10:00</p>'
      '<p>Block 21:00 Credit 25:00 Days Off 22</p>')


DET = {"H9001": {"credit": "12:30", "block": "11:00", "lay": "LAX", "route": "HNL-LAX-HNL"},
       "H9002": {"credit": "12:00", "block": "9:30", "lay": "SEA", "route": "HNL-SEA-HNL"}}


class Fl(CrewFl):
    def fetch(self, url):
        if "cmschedules.cgi" in url:
            self.urls.append(url)
            return CM
        return super().fetch(url)


def test_crew_seat_reads_the_pilot_s_seat_and_the_crew_count():
    line = "<p>pairing h9001 crew: ca 10001 doe, jane fo 010999 roe, rick ro open fa 20001 poe, pat</p>"
    assert pot.crew_seat(line, "10999") == ("FO", 3)  # leading zeros ignored; OPEN counts, the FA does not
    assert pot.crew_seat(line, "10001") == ("CA", 3)
    assert pot.crew_seat(line, "12345") == ("", 3) and pot.crew_seat("no crew line", "1") == ("", 0)
    # a seat code inside a name is part of the name (FW-0058)
    assert pot.crew_seat("crew: ca 10001 lee, so young fo 10002 roe, rick", "10002") == ("FO", 2)


def test_a_readable_month_is_priced_for_the_seat_flown(W, tmp_path, monkeypatch):  # noqa: F811
    """H9001 is read (its pairing page gives CA, 3 pilots, block and credit); H9002's page is not read (past
    PILOT_PAIRINGS_MAX here), so its credit and block come from the package and its seat from the seniority list."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=2, block="10:00"), _row("H9002", "13", rel=1, route="HNL-SEA-HNL", block="9:30")])
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, {"10999": ROE}))
    monkeypatch.setattr(W, "PILOT_PAIRINGS_MAX", 1)
    W.DB.put("pkg_details:2026-11", DET)  # the month's pairings package (uploads_check's copy)
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    W.S["cm_prompt_captured"] = True
    W.S["pilot_req"] = {"emp": "10999", "name": "Roe, Rick", "at": ""}
    fl = Fl({"H9001": "ca 10999 roe, rick fo 10001 doe, jane ro open"},
            legs={"H9001": "check in: 07:30 mo 900 hnl-lax 0830 1600 0530 we 901 lax-hnl 1000 1300 0530 blk : 1100 pay : 1230"})
    assert W.pilot_check(fl)
    assert sum("mobilepairing" in u for u in fl.urls) == 1  # no load beyond what the lookup read before
    stored = W.DB.get("pilot_sched:10999")["items"]
    assert (stored[0]["seat"], stored[0]["n"]) == ("CA", 3) and "gross" not in stored[0]  # the record stays as read
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    by = {it["trip"]: it for it in p["items"]}
    ca, fo = PAY.rate_for(9, "2026-11-02", "CA"), PAY.rate_for(9, "2026-11-13", "FO")
    # CA: credit x the Captain rate + $5.00 per block hour on a crew of 3 (PWA 4.O.1), no FO 15%
    assert (by["H9001"]["seat"], by["H9001"]["seat_src"]) == ("CA", "pairing page")
    assert by["H9001"]["gross"] == pytest.approx(round(12.5 * ca + 11 * 5.00, 2))
    assert (by["H9002"]["seat"], by["H9002"]["seat_src"], by["H9002"]["figs"]) == ("FO", "seniority list", "package")
    assert (by["H9002"]["credit"], by["H9002"]["blk"], by["H9002"]["soft"]) == ("12:00", "9:30", "2:30")
    assert by["H9002"]["gross"] == pytest.approx(round(12 * fo, 2))
    assert "gross" not in by["VAC"] and "seat" not in by["VAC"]
    ip = p["items_pay"]
    assert (ip["doh_known"], ip["doh"], ip["year"], ip["trips"], ip["trips_priced"]) == (True, "2018-10-03", 9, 2, 2)
    # 1.7.6 review: the VAC day (Nov 22) is in Credit and Pay-Gross at 4:00 (PWA 6.J.1.c), at the list seat's rate,
    # as on the schedule card's totals line (Vacation 4:00, 1 d)
    vac = 4 * PAY.rate_for(9, "2026-11-22", "FO")
    assert ip["gross"] == pytest.approx(by["H9001"]["gross"] + by["H9002"]["gross"] + vac, abs=0.02)
    assert (ip["vac"], ip["vac_days"]) == ("4:00", 1)
    assert (ip["credit"], ip["block"], ip["list_status"], ip["seat_src"]) == ("28:30", "20:30", "ok", {"pairing page": 1, "seniority list": 1})
    assert ip["days_off"] == p["totals"].get("days_off")  # FLICA's own count, not the trips'
    assert "items_pay" not in W.PILOT_SHOWN["p"] and "gross" not in W.PILOT_SHOWN["p"]["items"][0]
    # the cached answer is priced the same way
    W.SENT.clear()
    W.pilot_cmd(json.dumps({"emp": "10999", "name": "Roe, Rick"}))
    q = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert q["status"] == "cached" and q["items_pay"]["gross"] == pytest.approx(ip["gross"])
    # no list on file: hours and seats, no amounts
    (tmp_path / "uploads" / "seniority.json").unlink()
    W._SEN_CACHE.clear()
    W.pub_pilot(dict(W.PILOT_SHOWN["p"]))
    r = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert (r["items_pay"]["doh_known"], r["items_pay"]["gross"], r["items_pay"]["list_status"]) == (False, None, "none")
    assert all("gross" not in it for it in r["items"]) and {it.get("seat") for it in r["items"]} == {"CA", "FO", None}


def test_older_versions_are_priced_in_the_versions_file(W, tmp_path, monkeypatch):  # noqa: F811
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=2), _row("H9002", "13", rel=1, route="HNL-SEA-HNL", block="9:30")])
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, {"10999": ROE}))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    W.S["cm_prompt_captured"] = True
    W.S["pilot_req"] = {"emp": "10999", "name": "Roe, Rick", "at": ""}
    W.DB.put("pkg_details:2026-11", DET)
    assert W.pilot_check(Fl({"H9001": "ca 10999 roe, rick fo 10001 doe, jane", "H9002": "ca 10001 doe, jane fo 10999 roe, rick"}))
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    f = json.loads((tmp_path / "www" / f"pilotver_{p['versions_file_key']}.json").read_text())
    rec = f["10999"]["months"]["2026-11"][0]
    assert rec["pay"]["trips"] == 2 and rec["pay"]["trips_priced"] == 2 and rec["pay"]["gross"] > 0
    g = {it["trip"]: it.get("gross") for it in rec["items"]}
    assert g["H9001"] == pytest.approx(12.5 * PAY.rate_for(9, "2026-11-02", "CA"), abs=0.01)  # package credit and g["H9002"] > 0
    text = json.dumps(f)
    assert "2018-10-03" not in text and "doh" not in text  # served under /local/: amounts, never a date of hire


def test_a_pilot_instance_never_sends_another_pilot_s_doh_in_items_pay(W, tmp_path, monkeypatch):  # noqa: F811
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=2)])
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, {"10999": ROE}))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    items = [{"trip": "H9001", "start": "2026-11-02", "end": "2026-11-04", "lay": "LAX", "credit": "12:30", "blk": "11:00",
              "seat": "FO", "n": 2}]
    line, info = W.pilot_price(items, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 22)
    assert line["year"] == 9 and line["gross"] == pytest.approx(12.5 * PAY.rate_for(9, "2026-11-02"), abs=0.01)
    assert not set(W.PRICE_PILOT_DROP) & set(line) and "2018-10-03" not in json.dumps(line)
    assert line["days_off"] == 22 and info["H9001|2026-11-02"]["seat_src"] == "pairing page"

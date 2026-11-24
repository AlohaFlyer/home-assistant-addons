"""1.8.2 (transition audit, group g3): pricing, the pairings packages and the months go by bid period, not calendar
month. Hawaiian's bid periods are not calendar months (PWA Section 2 Definitions 47, MONTH: November is 11/1 to 12/1,
31 days; December 12/2 to 12/31, 30 days), and a pairing id repeats across bid periods as another trip (FW-0062), so:

- a trip the pilot holds twice under one number (a carry-in Nov 30 and the same number Dec 12) is priced as the trip the
  request names by its day (P3, S2, T6);
- a Dec 1 trip (November's period) is priced, judged for FAR 117 and the Recall check, and its report and customs origin
  read, from November's package, never December's (P2, S3, S4, POT-7, LIVE-7);
- Over 75 eligibility (PWA 22.G.2.d, Reserve Run pilots of the bid month) of a Dec 1 list row is November's answer
  (C8, S8, LIVE-9);
- the fit tag's days off minimum (PWA 10.G.1.a: 12 in a 30-day month, 13 in a 31-day month) and the pickup days it
  counts are the bid period's (P4, S9);
- a Dec 1 trip of November's period is in November's crew index file too (T11);
- on Dec 1 the pilot lookup takes November and December (T8).

FLICA is never reached. Synthetic data only: made-up pairings H39xx, "Doe, Jane" 10001."""
import json
import os
from datetime import date, datetime

import pytest

import crewidx as CI
import submit as SUB
from test_fw181_pot_month import at
from test_release_a_flica import mk  # noqa: F401

RATE = 100.0  # $ per credit hour: a 2-pilot crew in the FO seat is credit x rate (no PWA 4.O.1 override, no ER)
COLS = ["id", "route", "credit", "block", "crew"]
NOV_ROWS = [["H3907", "HNL-KIX-HNL", "17h35", "15h00", "CA01FO01"],
            ["H3905", "HNL-LAS-HNL", "15h00", "11h00", "CA01FO01"]]
DEC_ROWS = [["H3907", "HNL-JFK-HNL", "21h00", "19h00", "CA01FO01"],
            ["H3905", "HNL-SFO-HNL", "10h00", "9h00", "CA01FO01"],
            ["H3921", "HNL-LAX-HNL", "11h00", "10h00", "CA01FO01"],
            ["H3913", "HNL-SYD-HNL", "16h00", "14h00", "CA01FO01"]]
# the pairings package details (pkg_details_for): the same id is another trip in each bid period
NOV_DET = {"H3907": {"report": "12:45", "route": "HNL-KIX-HNL", "block": "15:00", "rel_days": 2,
                     "duties": [{"d": 0, "dep": 825, "arr": 1500, "stn": "KIX", "blk": 540},
                                {"d": 1, "dep": 2400, "arr": 2700, "stn": "HNL", "blk": 360}]}}
DEC_DET = {"H3907": {"report": "06:00", "route": "HNL-SFO-HNL", "block": "10:00", "rel_days": 1,
                     "duties": [{"d": 0, "dep": 420, "arr": 960, "stn": "HNL", "blk": 600}]}}


def _files(W):
    """The pairing files as pdfs.py writes them: November Nov 1 to Dec 1, December Dec 2 to 31, with rows."""
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    for m, a, b, rows in (("2026-11", "2026-11-01", "2026-12-01", NOV_ROWS),
                          ("2026-12", "2026-12-02", "2026-12-31", DEC_ROWS)):
        with open(os.path.join(W.CARD_PAIRINGS, f"pairings_{m}.json"), "w") as f:
            json.dump({"month": m, "start": a, "end": b, "cols": COLS, "rows": rows}, f)


def _w(mk, t=None):  # noqa: F811
    W = mk("", t=t or at(2026, 11, 20))
    _files(W)
    W.pay_settings = lambda: (RATE, 7, [])
    W.DB.put("pkg_details:2026-11", NOV_DET)
    W.DB.put("pkg_details:2026-12", DEC_DET)
    return W


def _held(W):
    """Ryan's line as his real one is shaped (synthetic ids): H3907 twice, Nov 30 (November's carry-in, KIX) and Dec 12
    (JFK), and H3913 once on Dec 6, on schedule versions in force since Nov 15."""
    nov = [{"trip": "H3907", "start": "2026-11-30", "end": "2026-12-02"}]
    dec = nov + [{"trip": "H3913", "start": "2026-12-06", "end": "2026-12-08"},
                 {"trip": "H3907", "start": "2026-12-12", "end": "2026-12-14"}]
    W.S["schedule"] = {"2026-11": {"month": "2026-11", "items": nov}, "2026-12": {"month": "2026-12", "items": dec}}
    for mk_, its in (("2026-11", nov), ("2026-12", dec)):
        W.DB.put(f"sched_versions:{mk_}", [{"ver": f"{mk_[5:]}.001", "at": "2026-11-15T00:00:00+00:00", "items": its}])
    W.S["own_trips"] = {"H3907|2026-11-30": {"credit": "17:35", "blk": "15:00", "seat": "FO"},
                        "H3907|2026-12-12": {"credit": "21:00", "blk": "19:00", "seat": "FO"},
                        "H3913|2026-12-06": {"credit": "16:00", "blk": "14:00", "seat": "FO"}}


def _req(text):
    return SUB.parse_request_rows(text)[0]


NOW = datetime(2026, 11, 20, 12, 0)


# ---------------------------------------------------------------- P3 / S2 / T6: a number held twice
def test_a_drop_of_the_second_trip_under_one_number_is_priced_as_that_trip(mk):  # noqa: F811
    W = _w(mk)
    _held(W)
    p = W.price_request(_req("11/20 09:10 drop approved h3907 12dec"), NOW.replace(tzinfo=W.HST))
    assert [(x["trip"], x["start"], x["side"], x["credit"]) for x in p["parts"]] == [
        ("H3907", "2026-12-12", "drop", "21:00")]
    assert p["delta"] == -2100.0
    # the carry-in, named by its own day, is still that trip
    p = W.price_request(_req("11/20 09:10 drop approved h3907 30nov"), NOW.replace(tzinfo=W.HST))
    assert [(x["start"], x["credit"]) for x in p["parts"]] == [("2026-11-30", "17:35")]


def test_a_swap_giving_the_second_trip_under_one_number_has_its_amount(mk):  # noqa: F811
    W = _w(mk)
    _held(W)
    p = W.price_request(_req("11/20 09:10 swap approved h3907 12dec h3921 20dec"), NOW.replace(tzinfo=W.HST))
    assert p is not None
    assert [(x["trip"], x["start"], x["side"]) for x in p["parts"]] == [
        ("H3907", "2026-12-12", "drop"), ("H3921", "2026-12-20", "add")]
    assert p["delta"] == 1100.0 - 2100.0


def test_a_leg_with_no_day_is_priced_only_when_its_number_is_held_once(mk):  # noqa: F811
    """No day on the leg: a number held once is that trip; a number held twice cannot be told apart, so no amount (a
    missing Pay-Gross beats a wrong one)."""
    W = _w(mk)
    _held(W)
    p = W.price_request(_req("11/20 09:10 drop approved h3913"), NOW.replace(tzinfo=W.HST))
    assert [(x["start"], x["credit"]) for x in p["parts"]] == [("2026-12-06", "16:00")]
    assert W.price_request(_req("11/20 09:10 drop approved h3907"), NOW.replace(tzinfo=W.HST)) is None


# ---------------------------------------------------------------- P2 / S3: a Dec 1 trip is November's
def test_a_dec_1_pickup_is_priced_from_novembers_package(mk):  # noqa: F811
    W = _w(mk)
    _held(W)
    assert W.bid_period_key("2026-12-01") == "2026-11"
    p = W.price_request(_req("11/20 09:10 add approved h3905 01dec"), NOW.replace(tzinfo=W.HST))
    assert [(x["start"], x["credit"]) for x in p["parts"]] == [("2026-12-01", "15h00")] and p["delta"] == 1500.0
    p = W.price_request(_req("11/20 09:10 add approved h3905 03dec"), NOW.replace(tzinfo=W.HST))  # December's own
    assert [(x["start"], x["credit"]) for x in p["parts"]] == [("2026-12-03", "10h00")]


def test_an_id_novembers_package_lacks_is_never_priced_from_decembers_for_dec_1(mk):  # noqa: F811
    """The calendar month's package is another bid period's: an id November's package lacks is no Dec 1 trip in
    December's (FW-0062), so no amount (a missing Pay-Gross beats a wrong one); the swap ideas' lookup agrees."""
    W = _w(mk)
    _held(W)
    assert W.price_request(_req("11/20 09:10 add approved h3921 01dec"), NOW.replace(tzinfo=W.HST)) is None
    assert W._swap_package("H3921", "2026-12-01", {}, W.bid_period_fn()) == {}
    assert W._swap_package("H3921", "2026-12-03", {}, W.bid_period_fn())["credit"] == "11h00"


def test_a_dec_1_trip_taken_on_the_schedule_is_priced_from_novembers_package(mk):  # noqa: F811
    W = _w(mk)
    _held(W)
    m = {"side": "add", "trip": "H3905", "start": "2026-12-01", "t": "2026-11-20T00:00:00+00:00", "id": "a"}
    p = W.price_moves([m])
    assert p["parts"][0]["credit"] == "15h00" and p["delta"] == 1500.0
    p = W.price_moves([dict(m, start="2026-12-03")])
    assert p["parts"][0]["credit"] == "10h00"


# ---------------------------------------------------------------- P2 / S4 / POT-7 / LIVE-7: the package fallbacks
def test_the_far_report_and_customs_fallbacks_of_a_dec_1_row_read_novembers_package(mk):  # noqa: F811
    """A pot or Tradeboard row with no pairing page read yet: its duties (the FAR column, near misses), its report
    (report_release, the commute check) and its last origin (customs, PWA 2.19.b) come from its bid period's package."""
    W = _w(mk)
    ev = {"pairing": "H3907", "start": "01Dec", "end": "02Dec"}
    assert W._pickup_duties(ev, date(2026, 12, 1)) == NOV_DET["H3907"]["duties"]
    rep, rel = W.report_release(ev)
    assert rep == datetime(2026, 12, 1, 12, 45) and rel == datetime(2026, 12, 2, 21, 15)
    assert W.last_origin(ev) == "KIX" and W.release_customs(ev) is True
    dec = {"pairing": "H3907", "start": "03Dec", "end": "03Dec"}  # December's own trip under the same number
    assert W.report_release(dec)[0] == datetime(2026, 12, 3, 6, 0) and W.last_origin(dec) == "SFO"


def _line(W):
    """An empty line held since Oct 20 (schedule versions of every month the check reaches)."""
    for mk_ in ("2026-10", "2026-11", "2026-12", "2027-01"):
        W.DB.put(f"sched_versions:{mk_}", [{"ver": f"{int(mk_[5:])}.001", "n": 1, "at": "2026-10-20T00:00:00+00:00",
                                           "items": [], "days": [], "totals": {}, "trips": {}}])


def _recall(W, me, rows):
    sent = []
    W.pub = lambda t, p, retain=True: sent.append((t, p))
    _line(W)
    W.DB.put("recall_me", me)
    W.recall_cmd(json.dumps({"date": "2026-12-01", "rows": rows}))
    st = [p for t, p in sent if t == "recall"][-1]
    return {v["id"]: v for d in st["days"] for v in d["verdicts"]}


ROW = {"date": "2026-12-01", "kind": "recall", "seat": "FO", "pilot": "Doe, Jane", "sen": 900, "pairing": "H3907"}


def test_a_dec_1_recall_row_is_judged_with_novembers_package(mk):  # noqa: F811
    W = _w(mk, at(2026, 12, 3))
    v = _recall(W, {"sen": 500}, [ROW])["2026-12-01|H3907|recall"]
    assert (v["report"], v["end"], v["last_arr"]) == ("12:45", "2026-12-02", "21:00"), v


# ---------------------------------------------------------------- C8 / S8 / LIVE-9: Over 75 by the bid month
def test_a_dec_1_over_75_row_takes_novembers_reserve_answer(mk):  # noqa: F811
    W = _w(mk, at(2026, 12, 3))
    o75 = dict(ROW, kind="o75")
    v = _recall(W, {"sen": 500, "o75_months": {"2026-11": False}}, [o75])["2026-12-01|H3907|o75"]
    assert v["verdict"] == "NO" and "not on reserve in Nov 2026" in v["why"][-1], v["why"]
    v = _recall(W, {"sen": 500, "o75_months": {"2026-11": True}}, [o75])["2026-12-01|H3907|o75"]
    assert v["verdict"] == "MISSED" and not any("reserve status" in w for w in v["why"]), v["why"]
    v = _recall(W, {"sen": 500, "o75_months": {"2026-12": True}}, [o75])["2026-12-01|H3907|o75"]
    assert v["verdict"] == "POSSIBLE" and "reserve status for Nov 2026 unknown" in v["why"][-1], v["why"]


def test_recall_without_a_period_function_keeps_the_calendar_month():
    """recall.py stays pure: a details callable with no period_of (or a plain dict) is looked up by the calendar month,
    as before 1.8.2."""
    import recall as RC
    asked = []
    RC.package_entry("H3907", date(2026, 12, 1), lambda p: asked.append(p) or {})
    assert asked == ["2026-12"] and RC.bid_month(date(2026, 12, 1)) == "2026-12"

    def det(p):
        asked.append(p)
        return {}
    det.period_of = lambda iso: "2026-11" if iso == "2026-12-01" else iso[:7]
    RC.package_entry("H3907", date(2026, 12, 1), det)
    assert asked[-1] == "2026-11" and RC.bid_month(date(2026, 12, 1), det) == "2026-11"


# ---------------------------------------------------------------- P4 / S9: the fit tag's days off by bid period
def _page(month, first, last, days_off):
    d0, d1 = date.fromisoformat(first), date.fromisoformat(last)
    days = [[date.fromordinal(o).isoformat(), "", ""] for o in range(d0.toordinal(), d1.toordinal() + 1)]
    return {"month": month, "days": days, "items": [], "totals": {"days_off": days_off}}


NOV_PAGE = ("2026-11", "2026-11-01", "2026-12-02")  # FLICA's November page lists Nov 1 to Dec 2
DEC_PAGE = ("2026-12", "2026-11-30", "2026-12-31")  # December's Nov 30 to Dec 31


def test_the_fit_tag_needs_the_bid_periods_days_off(mk):  # noqa: F811
    """PWA 10.G.1.a: 12 days off in a 30-day month, 13 in a 31-day month, the month being the bid period (Definitions
    47): December (Dec 2 to 31) needs 12, November (Nov 1 to Dec 1) 13, and a pickup's days count where they fall."""
    W = _w(mk)
    W.S["schedule"] = {"2026-12": _page(*DEC_PAGE, 13)}
    assert W.schedule_fit({"pairing": "H3913", "start": "20Dec", "days": 1}) == "Fits"  # 13 - 1 = 12, December's 12
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 13)}
    assert W.schedule_fit({"pairing": "H3905", "start": "30Nov", "end": "01Dec"}) == "Days off 11"
    assert W.schedule_fit({"pairing": "H3905", "start": "20Nov", "days": 1}) == "Days off 12"  # November needs 13
    # a Dec 1 pickup is judged on November's page (its bid period), whichever page comes first
    W.S["schedule"] = {"2026-12": _page(*DEC_PAGE, 20), "2026-11": _page(*NOV_PAGE, 13)}
    assert W.schedule_fit({"pairing": "H3905", "start": "01Dec", "days": 1}) == "Days off 12"


def test_the_fit_tag_without_period_bounds_keeps_the_calendar_month():
    import pot as P
    s = _page(*DEC_PAGE, 13)
    assert P.fit_tag(date(2026, 12, 20), date(2026, 12, 20), s) == "Days off 12"  # 31 calendar days: 13, as before
    assert P.fit_tag(date(2026, 12, 20), date(2026, 12, 20), s, ("2026-12-02", "2026-12-31")) == "Fits"


# ---------------------------------------------------------------- T11: the crew index month files
def _inst(pid, day, month, period):
    return {"key": f"{pid}|{day}", "pairing": pid, "date": day, "end_date": day, "route": "HNL-LAS-HNL", "days": 1,
            "month": month, "period": period, "src": "package"}


def test_a_dec_1_trip_of_novembers_period_is_in_novembers_crew_index_file_too(mk, tmp_path, monkeypatch):  # noqa: F811
    W = _w(mk)
    insts = {"H3905|2026-12-01": _inst("H3905", "2026-12-01", "2026-12", "2026-11"),
             "H3921|2026-11-20": _inst("H3921", "2026-11-20", "2026-11", "2026-11"),
             "H3913|2026-12-06": _inst("H3913", "2026-12-06", "2026-12", "2026-12")}
    crew = [{"pos": "FO", "name": "Doe, Jane", "emp": "10001"}]
    rows = {k: {"status": "ok", "crew": crew} for k in insts}
    nov = CI.render_month("2026-11", insts, rows, "2026-11-20 12:00")
    assert "| 2026-12-01 | H3905 | FO |" in nov and "| 2026-11-20 | H3921 |" in nov and "H3913" not in nov
    assert "Coverage 100.0% (2 of 2 trip instances read" in nov
    monkeypatch.setattr(W, "CREW_DIR", str(tmp_path / "crew_index"))
    W.write_crew_md(insts, rows)
    files = {f: open(tmp_path / "crew_index" / f).read() for f in sorted(os.listdir(tmp_path / "crew_index"))}
    assert sorted(files) == ["2026-11.md", "2026-12.md"]
    assert "| 2026-12-01 | H3905 |" in files["2026-11.md"] and "| 2026-12-01 | H3905 |" in files["2026-12.md"]
    assert "H3913" in files["2026-12.md"] and "H3921" not in files["2026-12.md"]


# ---------------------------------------------------------------- T8: the pilot lookup's months
def test_on_dec_1_the_pilot_lookup_takes_november_and_december(mk):  # noqa: F811
    W = _w(mk, at(2026, 12, 1, 9))
    assert W.lookup_months() == ("2026-11", "2026-12")
    W.pilot_cmd(json.dumps({"emp": "10001", "name": "Doe, Jane", "month": "2026-11"}))
    assert (W.S.get("pilot_req") or {}).get("month") == "2026-11"
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert W.lookup_months() == ("2026-12", "2027-01")
    W.CLOCK.t = at(2026, 11, 30, 23)
    assert W.lookup_months() == ("2026-11", "2026-12")


# ---------------------------------------------------------------- review round (R1, R2, R3, G3-T1, G3-T3)
def test_a_dec_1_row_novembers_package_lacks_asks_for_novembers_pairings_pdf(mk):  # noqa: F811
    """R3, G3-T1: the row was looked up in November's package (Dec 1 is November's), so the advice names November's
    PDF; December's lists the id as another trip (FW-0062) and would not resolve the row."""
    W = _w(mk, at(2026, 12, 3))
    W.DB.put("pkg_details:2026-12", dict(DEC_DET, H3925={"report": "12:45", "rel_days": 3, "duties": []}))
    row = dict(ROW, pairing="H3925", report="12:45", last_arr="21:00")
    v = _recall(W, {"sen": 500}, [row])["2026-12-01|H3925|recall"]
    assert v["verdict"] == "POSSIBLE", v
    assert v["why"][-1] == "pairing length unknown; upload the Nov 2026 pairings PDF or add days to the row", v["why"]
    v = _recall(W, {"sen": 500}, [dict(row, date="2026-12-05")])["2026-12-05|H3925|recall"]  # December's own
    assert "upload the" not in " ".join(v["why"]), v["why"]  # December's package gives its length


def test_a_dec_1_over_75_row_names_the_bid_month_its_answer_comes_from(mk):  # noqa: F811
    """R1: the card files a list day under its calendar month (Dec 1 on December's page), but the row's Over 75 answer
    is November's (PWA 22.G.2.d, Definitions 47): the verdict says which month (o75_month) so the card asks that
    month on the row. A row whose bid month is its calendar month, and a Recall row, carry none."""
    W = _w(mk, at(2026, 12, 3))
    o75 = dict(ROW, kind="o75")
    got = _recall(W, {"sen": 500}, [o75, ROW, dict(o75, date="2026-12-05", pairing="H3905")])
    assert got["2026-12-01|H3907|o75"]["o75_month"] == "2026-11"
    assert "o75_month" not in got["2026-12-01|H3907|recall"]
    assert "o75_month" not in got["2026-12-05|H3905|o75"]


RECALL_CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-recall-card.js")


def _o75v(day, pairing, verdict, why, **kw):
    return dict({"id": f"{day}|{pairing}|o75", "date": day, "kind": "o75", "pairing": pairing, "seat": "FO",
                 "sen": 900, "pilot": "Doe, Jane", "verdict": verdict, "why": why, "refs": [], "act": {}}, **kw)


def test_the_recall_card_asks_the_bid_months_over_75_on_a_dec_1_row():
    """R1: on December's page (the card files Dec 1 under its calendar month) a Dec 1 Over 75 row carries its own
    select for November, the month its answer comes from; setting it sends November's answer, and the page's own
    'Over 75 in Dec' select stays December's. A row of the page's own bid month gets no second select."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    unknown = "reserve status for Nov 2026 unknown: Over 75 goes to Reserve Run pilots only (PWA 22.G.2.d); say on " \
              "the tab whether you were on reserve that month"
    days = [{"date": "2026-12-05", "file": "ok", "verdicts": [_o75v("2026-12-05", "H3905", "NO", ["went to #900"])]},
            {"date": "2026-12-01", "file": "ok", "verdicts": [
                _o75v("2026-12-01", "H3907", "POSSIBLE", ["went to #900", unknown], o75_month="2026-11"),
                dict(_o75v("2026-12-01", "H3913", "NO", ["went to #900"]), id="2026-12-01|H3913|recall",
                     kind="recall")]}]
    attrs = {"open": 1, "alert": 0, "me": {"sen": 500, "seat": "FO", "o75_months": {"2026-12": True}}, "days": days,
             "last": "2026-12-05", "checked": "2026-12-05T20:00:00+00:00"}
    states = {"sensor.flight_watcher_recall_o75": {"state": "1", "attributes": attrs,
                                                   "last_updated": "2026-12-05T20:00:00+00:00"},
              "sensor.flight_watcher_state": {"state": "ok", "attributes": {"role": "admin"}}}
    page = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            "initial-scale=1'></head><body style='margin:0;padding:8px 16px'><script>customElements.define('ha-card',"
            " class extends HTMLElement {});</script><script>" + open(RECALL_CARD, encoding="utf-8").read()
            + "</script></body></html>")
    read = """() => { const r = window.card.shadowRoot;
      const rows = [...r.querySelectorAll('.row')].map((x) => ({text: x.textContent.replace(/\\s+/g, ' ').trim(),
        sel: [...x.querySelectorAll('select[data-o75]')].map((s) => [s.dataset.o75, s.value])}));
      return {rows, head: [...r.querySelectorAll('.me select[data-o75]')].map((s) => [s.dataset.o75, s.value]),
              sent: window.sent, wide: document.documentElement.scrollWidth, vw: window.innerWidth}; }"""
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 900})
            pg.set_content(page)
            pg.evaluate("""(h) => { window.sent = []; const c = document.createElement('flight-watcher-recall-card');
              c.setConfig({mode: 'tab'}); c._m = '2026-12'; document.body.appendChild(c); window.card = c;
              c._fold = {'2026-12-01': true, '2026-12-05': true};
              c.hass = {states: h, themes: {darkMode: false},
                        callService: (d, s, data) => { window.sent.push(data); return Promise.resolve(); }}; }""",
                        states)
            got = pg.evaluate(read)
            assert got["head"] == [["2026-12", "yes"]], got
            dec1 = next(x for x in got["rows"] if "H3907" in x["text"])
            assert dec1["sel"] == [["2026-11", ""]], dec1
            assert "Over 75 in Nov 2026" in dec1["text"] and "bid month of Dec 1" in dec1["text"], dec1["text"]
            assert all(not x["sel"] for x in got["rows"] if "H3907" not in x["text"]), got["rows"]
            assert got["wide"] <= got["vw"], got
            pg.select_option("flight-watcher-recall-card select[data-o75='2026-11']", "no")
            got = pg.evaluate(read)
            assert got["sent"] and json.loads(got["sent"][-1]["payload"]) == {"me": {"o75_months": {"2026-11": False}}}
        finally:
            b.close()


def test_a_pickup_across_the_bid_period_edge_is_judged_in_each_period_it_touches(mk):  # noqa: F811
    """R2 (P4, S9): the days off minimum (PWA 10.G.1.a) holds in each bid period a pickup touches (Definitions 47:
    November Nov 1 to Dec 1, December Dec 2 to 31), each on its own page with its own bounds; the worst answer wins
    (a Conflict, then Check rest, then Days off), Fits only when every period says so. FLICA's November page lists
    Nov 1 to Dec 2 and December's Nov 30 to Dec 31, so a page judges the part of the pickup it lists."""
    W = _w(mk)
    tag = lambda s, e: W.schedule_fit({"pairing": "H3905", "start": s, "end": e})  # noqa: E731
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 15), "2026-12": _page(*DEC_PAGE, 12)}
    assert (tag("01Dec", "02Dec"), tag("30Nov", "02Dec")) == ("Days off 11", "Days off 11")  # Dec 2 is December's
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 13), "2026-12": _page(*DEC_PAGE, 20)}
    assert tag("01Dec", "03Dec") == "Days off 12"  # November's page lists to Dec 2: its Dec 1 still counts
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 20), "2026-12": _page(*DEC_PAGE, 12)}
    assert tag("28Nov", "02Dec") == "Days off 11"  # December's page lists from Nov 30: its Dec 2 still counts
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 17), "2026-12": _page(*DEC_PAGE, 15)}  # Nov 28 to Dec 1: 4 days
    assert (tag("01Dec", "02Dec"), tag("01Dec", "03Dec"), tag("28Nov", "02Dec")) == ("Fits", "Fits", "Fits")
    dec = dict(_page(*DEC_PAGE, 15), items=[{"trip": "H3913", "start": "2026-12-02", "end": "2026-12-04"}])
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 13), "2026-12": dec}
    assert tag("01Dec", "02Dec") == "Conflict H3913"  # December's conflict beats November's days off
    # a day of one bid period is never judged by the other's days off: Dec 2 alone is December's
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 10), "2026-12": _page(*DEC_PAGE, 15)}
    assert tag("02Dec", "02Dec") == "Fits"
    W.S["schedule"] = {"2026-11": _page(*NOV_PAGE, 15)}  # December's page not out yet: November's, as before
    assert tag("30Nov", "02Dec") == "Fits"


def test_on_dec_1_a_month_past_the_next_bid_month_is_refused_naming_the_bid_months(mk):  # noqa: F811
    """G3-T3: on Dec 1 (November's bid period, Definitions 47) the lookup takes November and December; January is
    refused, and the card's line says why in bid months, not calendar months."""
    W = _w(mk, at(2026, 12, 1, 9))
    sent = []
    W.pub = lambda t, p, retain=True: sent.append((t, p))
    W.pilot_cmd(json.dumps({"emp": "10001", "name": "Doe, Jane", "month": "2027-01"}))
    st = [p for t, p in sent if t == "pilot_schedule"][-1]
    assert st["status"] == "Only Nov 2026 and Dec 2026 can be looked up (this bid month and the next, HST).", st
    assert not W.S.get("pilot_req")

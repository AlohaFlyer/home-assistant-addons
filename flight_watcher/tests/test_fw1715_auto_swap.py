"""1.7.15 (Ryan, Nov 17, item 6): automatic swap ideas ranked by pay per day.

Ryan: "Fill Swap ideas without a manual tap: rank my trips against open pot trips by pay per day. Keep legality and
VAC/blocked rules." swap_scan now also compares every own trip he did not mark "would trade" with every open pot trip of
the same bid period it could swap for, ranked by (pot trip Pay-Gross / its days) minus (own trip Pay-Gross / its days),
priced as the swap pushes price a trip (pay.trip_gross, pay_settings' rate). The same legality as a marked trip: FAR 117
with the own trip removed (far_for exclude), the 11 h CBA rest (a plain OK only), no VAC or blocked day, the grid rule.
An automatic idea carries auto: True and never pushes (event/swap, event/swap_test, the auto swap dry run). Marked trips
work as before. Synthetic schedule and made-up pairings (H9xxx), no names, no FLICA (swap_scan reads rows on hand).
1.7.15 review: the sensor's "ideas" keeps the marked trips' ideas only, in their 1.7.11 order (gain_h); the automatic
ones are in "auto_ideas" (R1, F1, F3); a pot trip is priced in its open RO seat (R3) with its own roster (R5); his trip's
layover is its schedule item's (R6); the bid period is the pot's and his trip's page's (R7); the "N more" line counts
the automatic ideas listed (R4, F2)."""
import inspect
import json
import os
import sys
from datetime import date, datetime

import pytest

import pay as PAY
import pot

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
TODAY = date(2026, 11, 17)
RATE = PAY.rate_for(5, "2026-11-17")
K1, K2 = "H9001|2026-11-20", "H9002|2026-11-24"
OWN = {K1: ("2026-11-21", {"credit": "10:00", "blk": "8:00", "soft": "2:00", "seat": "FO"}),
       K2: ("2026-11-26", {"credit": "15:00", "blk": "13:00", "soft": "2:00", "seat": "FO"})}


def _hm(h):
    m = round(h * 60)
    return f"{m // 60}:{m % 60:02d}"


def _row(pid, start, end, credit, blk, src="O", **kw):
    """A pot row as the Watcher holds it after its detail read (FLICA's DDMon dates, H:MM credit, block, soft time)."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    st, en = f"{s.day:02d}{s:%b}", f"{e.day:02d}{e:%b}"
    soft = _hm(max(0.0, PAY.hrs(credit) - PAY.hrs(blk))) if credit and blk else ""
    r = {"pairing": pid, "start": st, "end": en, "dates": st if s == e else f"{st}-{en}", "days": str((e - s).days + 1),
         "credit": credit, "blk": blk, "soft": soft, "layover": "-none-" if s == e else "LAX", "turn": "PPG" if s == e else "",
         "report": "08:00", "arrive": "18:00", "src": src, "month": "2026-11", "detail_url": ""}
    r.update(kw)
    return r


# H9001 (Nov 20-21, 10:00, 2 days: 5:00 a day) and H9002 (Nov 24-26, 15:00, 3 days: 5:00 a day)
P1 = _row("H9101", "2026-11-20", "2026-11-21", "12:00", "9:00")   # 6:00 a day vs H9001: +1:00 x rate a day
P2 = _row("H9102", "2026-11-21", "2026-11-21", "7:00", "5:00")    # a turn, 7:00 a day vs H9001: +2:00 x rate a day
P3 = _row("H9103", "2026-11-20", "2026-11-22", "13:30", "10:00")  # 4:30 a day: less per day than H9001
P4 = _row("H9104", "2026-11-25", "2026-11-26", "10:30", "8:30")   # 5:15 a day vs H9002: +0:15 x rate a day


class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", qos=0, retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, *a, **k):
        pass


def _grid(lo="2026-11-15", n=25, color="green"):
    d0 = date.fromisoformat(lo)
    return {date.fromordinal(d0.toordinal() + k).isoformat(): {"color": color, "net": 3} for k in range(n)}


def _setup(W, monkeypatch, tmp_path, own=OWN, rate=RATE, er=()):
    """The Watcher's state for a scan: Nov 2026 schedule with the own trips, their records, a green grid, no marks; the
    clock on Nov 17 12:00 HST; pay_settings() at the PWA 3.D.6 year 5 rate; far_for a spy (T_FAR: (pairing, exclude) ->
    the column, default OK; the module's own FAR is far.py) that records every call."""
    clock = {"now": datetime(2026, 11, 17, 12, 0)}
    monkeypatch.setattr(W, "local_now", lambda: clock["now"])
    monkeypatch.setattr(W, "row_date", lambda s, today=None: pot.row_date(s, today or TODAY))
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W, "pay_settings", lambda: (rate, 5 if rate else None, list(er)))
    if not hasattr(W, "T_REAL_FAR_FOR"):
        W.T_REAL_FAR_FOR = W.far_for  # the Watcher's own screen, for the test that runs it
    W.T_FAR, W.T_FAR_CALLS = {}, []

    def far_for(ev, exclude=None):
        W.T_FAR_CALLS.append((ev.get("pairing"), exclude))
        return W.T_FAR.get((ev.get("pairing"), exclude), "OK")
    monkeypatch.setattr(W, "far_for", far_for)

    def no_flica(*a, **k):
        raise AssertionError("swap_scan loaded a FLICA page")
    monkeypatch.setattr(W, "count_fetch", no_flica)
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    W.S.clear()
    items = [{"trip": k.split("|")[0], "start": k.split("|")[1], "end": end, "lay": "LAX"} for k, (end, _r) in own.items()]
    W.S.update({"schedule": {"2026-11": {"items": items, "days": [], "totals": {}, "updated": "Nov 17, 2026"}},
                "own_trips": {k: dict(r) for k, (_e, r) in own.items()}, "grid": _grid(), "trade_away": [],
                "blocked_days": []})
    W.CLOCK = clock
    return W


def _load(tmp_path, monkeypatch, instance):
    data = tmp_path / ("data_" + (instance or "admin"))
    data.mkdir(exist_ok=True)
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "my_name": "Doe"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher
    watcher.FAKE = FakeClient()
    monkeypatch.setattr(watcher, "MQ", watcher.FAKE)
    return _setup(watcher, monkeypatch, tmp_path)


@pytest.fixture(params=["", "pilot2"])
def W(request, tmp_path, monkeypatch):
    w = _load(tmp_path, monkeypatch, request.param)
    yield w
    sys.modules.pop("watcher", None)


def _pubs(W, sub):
    return [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"{W.T}/{sub}"]


def _sensor(W):
    return _pubs(W, "swap/state")[-1]


def _auto(W):
    """The automatic ideas on the sensor (1.7.15 review: their own attribute, auto_ideas)."""
    return _sensor(W)["auto_ideas"]


def _gross(credit, blk, crew=None, seat="FO", lay="", key="", er=()):
    return PAY.trip_gross(PAY.hrs(credit), PAY.hrs(blk), crew, lay, key, seat, RATE, er)


# ---------------------------------------------------------------- 1, 2: every own trip, ranked by pay per day
def test_with_no_mark_every_own_trip_is_ranked_against_the_pot_by_pay_per_day(W):
    W.swap_scan([P1, P2, P3, P4])
    s = _sensor(W)
    ideas = s["auto_ideas"]
    assert [(i["for"], i["pairing"]) for i in ideas] == [(K1, "H9102"), (K1, "H9101"), (K2, "H9104")]
    assert all(i["auto"] is True for i in ideas) and s["marked"] == [] and s["count"] == 3 and s["ideas"] == []
    assert s["auto_count"] == s["auto_shown"] == 3 and s["auto_more"] == 0 and s["auto_max"] == W.SWAP_AUTO_MAX == 10
    # (pot trip pay / its days) minus (own trip pay / its days), the existing pricing (pay.trip_gross, the rate of
    # pay_settings); both pay-per-day figures and both trips' totals (pay and days) on each idea
    own1, own2 = _gross("10:00", "8:00", key=K1), _gross("15:00", "13:00", key=K2)
    want = {"H9102": (_gross("7:00", "5:00", key="H9102|2026-11-21"), 1, own1, 2),
            "H9101": (_gross("12:00", "9:00", key="H9101|2026-11-20"), 2, own1, 2),
            "H9104": (_gross("10:30", "8:30", key="H9104|2026-11-25"), 2, own2, 3)}
    for i in ideas:
        pay, days, fpay, fdays = want[i["pairing"]]
        assert (i["pay"], i["pay_days"], i["for_pay"], i["for_days"]) == (round(pay, 2), days, round(fpay, 2), fdays)
        assert i["ppd"] == round(pay / days, 2) and i["for_ppd"] == round(fpay / fdays, 2)
        assert i["ppd_gain"] == round(pay / days - fpay / fdays, 2) > 0
    assert [round(i["ppd_gain"] / RATE, 3) for i in ideas] == [2.0, 1.0, 0.25]
    # H9103 pays less a day than H9001: no idea; a pot trip that shares no day with an own trip is no swap for it
    assert "H9103" not in {i["pairing"] for i in ideas}
    assert {(i["pairing"], i["for"]) for i in ideas}.isdisjoint({("H9101", K2), ("H9102", K2), ("H9104", K1)})
    assert ideas[0]["why"].startswith("pay per day +$") and ideas[0]["grid_ok"] is True and ideas[0]["grid"] == "grid OK"


def test_the_pay_is_the_swap_pushes_pricing_with_the_package_seat_crew_and_er(W, monkeypatch, tmp_path):
    """Credit and block from Ryan's own record (his seat and roster) and from the pot row, else the bid period's
    pairings package (its crew line and route); the ER list of pay_settings; nothing new is invented."""
    pdir = tmp_path / "www" / "flight-watcher"
    pdir.mkdir(parents=True)
    cols = ["id", "credit", "block", "crew", "route"]
    rows = [["H9105", "17:00", "13:00", "CA01FO01RO01", "HNL-LAX-HNL"], ["H9108", "17:30", "13:00", "", "HNL-SIN-HNL"]]
    (pdir / "pairings_2026-11.json").write_text(json.dumps({"month": "2026-11", "cols": cols, "rows": rows}))
    W.S["own_trips"][K2] = {"credit": "15:00", "blk": "13:00", "seat": "RO", "crew": ["CA", "FO", "RO"]}
    er = ["-H9108|2026-11-24"]
    monkeypatch.setattr(W, "pay_settings", lambda: (RATE, 5, er))
    # credit and block not read on the rows: the package's
    W.swap_scan([_row("H9105", "2026-11-24", "2026-11-26", "", ""), _row("H9108", "2026-11-24", "2026-11-26", "", "")])
    got = {i["pairing"]: i for i in _auto(W)}
    assert set(got) == {"H9105", "H9108"}
    own_g = PAY.trip_gross(15.0, 13.0, 3, "LAX", K2, "RO", RATE, er)  # his RO seat on a crew of 3: $4.00 a block hour
    g5 = PAY.trip_gross(17.0, 13.0, "CA01FO01RO01", "LAX", "H9105|2026-11-24", "FO", RATE, er)  # FO on 3: $3.00
    g8 = PAY.trip_gross(17.5, 13.0, "", "SIN", "H9108|2026-11-24", "FO", RATE, er)  # SIN, but -KEY: no ER
    assert got["H9105"]["for_pay"] == got["H9108"]["for_pay"] == round(own_g, 2) == round(15 * RATE + 13 * 4.0, 2)
    assert got["H9105"]["pay"] == round(g5, 2) == round(17 * RATE + 13 * 3.0, 2)
    assert got["H9108"]["pay"] == round(g8, 2) == round(17.5 * RATE, 2)  # not 17:30 x rate x 1.15
    assert got["H9105"]["pay_days"] == got["H9105"]["for_days"] == 3


def test_a_trip_of_novembers_bid_period_is_priced_from_its_package(W, monkeypatch, tmp_path):
    """1.7.11 (PWA 4.A): Dec 1 is in November's bid period, so a trip starting then is found in November's package."""
    pdir = tmp_path / "www" / "flight-watcher"
    pdir.mkdir(parents=True)
    (pdir / "pairings_2026-11.json").write_text(json.dumps({"month": "2026-11", "cols": ["id", "credit", "block"],
                                                            "rows": [["H9106", "16:00", "13:00"]]}))
    own = {"H9003|2026-11-30": ("2026-12-01", {"credit": "10:00", "blk": "8:00", "seat": "FO"})}
    _setup(W, monkeypatch, tmp_path, own=own)
    monkeypatch.setattr(W, "bid_period_fn", lambda: (lambda iso: "2026-11" if str(iso) <= "2026-12-01" else "2026-12"))
    W.swap_scan([_row("H9106", "2026-12-01", "2026-12-01", "", "")])
    (i,) = _auto(W)
    assert i["pay"] == round(16.0 * RATE, 2) and i["pay_days"] == 1 and i["for_ppd"] == round(10.0 * RATE / 2, 2)


# ---------------------------------------------------------------- 1, 4: marked trips work as before
def test_marked_trips_keep_todays_rule_and_push_and_the_rest_are_automatic(W):
    W.S["trade_away"] = [K1]
    W.swap_scan([P1, P2, P3, P4])
    s = _sensor(W)
    marked, auto = s["ideas"], s["auto_ideas"]
    # H9001 (marked): swap.better as before (more soft time or credit): H9101 and H9103, never H9102 (more pay a day
    # but no soft time or credit gain); no automatic idea for a marked trip
    assert {i["pairing"] for i in marked} == {"H9101", "H9103"} and all(i["for"] == K1 for i in marked)
    assert not any(i["auto"] for i in marked) and all(i["auto"] for i in auto)
    assert [(i["for"], i["pairing"]) for i in auto] == [(K2, "H9104")]
    # review R1: marked ideas keep the 1.7.11 order (gain_h: H9103 +1:30 soft, +3:30 cr before H9101 +1:00, +2:00),
    # the order they push in, and also show both pay-per-day figures (H9101 +1:00 a day, H9103 -0:30 a day)
    assert [i["pairing"] for i in marked] == ["H9103", "H9101"] and marked[0]["ppd_gain"] < 0 < marked[1]["ppd_gain"]
    # pushes: once per marked idea (event/swap and its draft), never for the automatic one
    pushed = _pubs(W, "event/swap")
    assert sorted(p["pairing"] for p in pushed) == ["H9101", "H9103"] and not any(p.get("auto") for p in pushed)
    assert sorted(p["take"].split()[0] for p in _pubs(W, "event/swap_test")) == ["H9101", "H9103"]
    assert sorted(W.S["swap_seen"]) == sorted(f"{p}|{d}>{K1}" for p, d in (("H9101", "20Nov"), ("H9103", "20Nov")))
    W.swap_scan([P1, P2, P3, P4])  # again: no new push
    assert len(_pubs(W, "event/swap")) == 2


# ---------------------------------------------------------------- 3: the same legality, each rule rejecting
def _vac(W):
    W.S["schedule"]["2026-11"]["items"].append({"trip": "VAC", "start": "2026-11-21", "end": "2026-11-21", "lay": ""})


def _far(value):
    def f(W):
        W.T_FAR[("H9102", K1)] = value
    return f


def _grid_red(W):
    W.S["grid"]["2026-11-20"]["color"] = "red"


def _bid_period(W):
    """Listed in December's pot (review R7: the pot's own bid month)."""
    W.ROW_KW = {"month": "2026-12"}


def _bid_period_by_day(W):
    """A pot whose key names no month (the mobile pages' keys): the bid period of its first day."""
    W.BID_FN = lambda iso: "2026-12" if str(iso) >= "2026-11-21" else "2026-11"
    W.ROW_KW = {"month": "mobile_003.153"}


RULES = {
    "a VAC day": _vac,
    "a blocked day": lambda W: W.S.update(blocked_days=["2026-11-21"]),
    "FAR 117 conflict with the trip gone": _far("Conflict"),
    "FAR rest short": _far("Rest 8:00 before"),
    "the 11 h CBA rest (PWA 10.E.1.a)": _far("OK (CBA rest 10:30)"),
    "FAR not known": _far("?"),
    "a grid day moved off is red": _grid_red,
    "a grid day moved off has no entry": lambda W: W.S["grid"].pop("2026-11-20"),
    "another bid period": _bid_period,
    "another bid period by its first day": _bid_period_by_day,
    "less pay a day": None,
    "no pay rate on file": None,
}


@pytest.mark.parametrize("rule", list(RULES))
def test_each_legality_rule_rejects_an_automatic_idea(W, monkeypatch, tmp_path, rule):
    own = {K1: OWN[K1]}
    _setup(W, monkeypatch, tmp_path, own=own)
    W.swap_scan([P2])  # the baseline: H9102 for H9001 is an automatic idea, FAR asked with H9001 left out
    assert [(i["for"], i["pairing"], i["auto"]) for i in _auto(W)] == [(K1, "H9102", True)]
    assert ("H9102", K1) in W.T_FAR_CALLS and ("H9102", None) not in W.T_FAR_CALLS
    W.FAKE.msgs.clear()
    W.BID_FN, W.ROW_KW = None, {}
    row = dict(P2)
    if rule == "less pay a day":
        row.update(credit="5:00", blk="4:00", soft="1:00")
    elif rule == "no pay rate on file":
        monkeypatch.setattr(W, "pay_settings", lambda: (None, None, []))
        W._SWAP_PAY.update(at=0.0)
    else:
        RULES[rule](W)
    if W.BID_FN:
        monkeypatch.setattr(W, "bid_period_fn", lambda: W.BID_FN)
    row.update(W.ROW_KW)
    W.swap_scan([row])
    s = _sensor(W)
    assert s["ideas"] == s["auto_ideas"] == [] and s["count"] == 0 and s["auto_count"] == 0, rule
    if rule == "no pay rate on file":
        assert s["priced"] is False


def test_the_same_pairing_a_started_trip_and_a_tradeboard_post_make_no_automatic_idea(W):
    W.swap_scan([_row("H9001", "2026-11-21", "2026-11-21", "9:00", "5:00")])  # his own pairing number
    assert _auto(W) == []
    W.S["tb_details"] = {"H9102|21Nov": dict(P2)}  # a Tradeboard post: not the open pot
    W.swap_scan([])
    assert _auto(W) == []
    W.S.pop("tb_details")
    W.CLOCK["now"] = datetime(2026, 11, 20, 6, 0)  # H9001 starts today: not swapped from here
    W.swap_scan([P2])
    assert [i["for"] for i in _auto(W)] == []


def test_far_is_asked_with_each_own_trip_removed(W, monkeypatch):
    """The automatic path asks far_for with exclude (the own trip it would give up), once per candidate it keeps."""
    seen = []
    monkeypatch.setattr(W, "far_for", lambda ev, exclude=None: seen.append(exclude) or "OK")
    W.swap_scan([P2, P4])
    assert sorted(seen) == [K1, K2]


def _month_days(month, marks=()):
    y, m = int(month[:4]), int(month[5:7])
    out = [[date(y, m, d).isoformat(), "", ""] for d in range(1, 32) if d <= 28 or _valid(y, m, d)]
    for iso, act, lay in marks:
        out[int(iso[8:]) - 1] = [iso, act, lay]
    return out


def _valid(y, m, d):
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def test_the_real_far_screen_runs_with_the_own_trip_removed(W, monkeypatch, tmp_path):
    """The Watcher's own FAR 117 screen (far_for, far.screen, recall.line_records with exclude): H9102 on Nov 21 is a
    clash with H9001 itself, which the swap gives up, so it is legal with H9001 removed; a turn home 23:30 leaves 8:15
    before H9002's report (FAR 117.25(e)), one home 21:15 leaves 10:30 (FAR met, PWA 10.E.1.a's 11 h short): neither
    is an idea, as for a marked trip."""
    from pot import schedule_items
    own = {K1: ("2026-11-21", {}), "H9002|2026-11-22": ("2026-11-23", {})}
    _setup(W, monkeypatch, tmp_path, own=own)
    monkeypatch.setattr(W, "far_for", W.T_REAL_FAR_FOR)
    nov = _month_days("2026-11", [("2026-11-20", "H9001", "LAX"), ("2026-11-21", "", "HNL"),
                                  ("2026-11-22", "H9002", "LAX"), ("2026-11-23", "", "HNL")])
    W.S["schedule"] = {"2026-10": {"items": [], "days": _month_days("2026-10")},
                       "2026-11": {"items": schedule_items(nov), "days": nov}}
    times = {"credit": "10:00", "blk": "8:00", "report": "08:00", "last_arr": "18:00", "duties": []}
    W.S["own_trips"] = {K1: dict(times), "H9002|2026-11-22": dict(times)}
    late = _row("H9109", "2026-11-21", "2026-11-21", "7:00", "5:00", arrive="23:30")
    cba = _row("H9110", "2026-11-21", "2026-11-21", "7:00", "5:00", arrive="21:15")
    assert W.far_for(dict(P2)) == "Conflict" and W.far_for(dict(P2), exclude=K1) == "OK"
    assert W.far_for(dict(late), exclude=K1).startswith("Rest 8:15")
    assert W.far_for(dict(cba), exclude=K1).startswith("OK (CBA rest 10:30")
    W.swap_scan([P2, late, cba])
    assert [(i["for"], i["pairing"], i["auto"]) for i in _auto(W)] == [(K1, "H9102", True)]


# ---------------------------------------------------------------- 4, 5: no push, no draft, no FLICA for auto ideas
def test_an_automatic_idea_never_pushes_never_drafts_and_never_feeds_auto_swap(W):
    W.S["auto_swap"] = True  # the admin's dry run switch (a pilot has none)
    for _ in range(2):
        W.swap_scan([P1, P2, P4])
    assert len(_auto(W)) == 3 and _sensor(W)["ideas"] == []
    assert _pubs(W, "event/swap") == [] and _pubs(W, "event/swap_test") == []
    assert W.S.get("swap_seen") == [] and W.S.get("swap_tests") in (None, []) and W.S.get("auto_swap_log") == {}
    # the backstops: an automatic idea handed to the push path still sends nothing
    idea = dict(_auto(W)[0], key="x>y")
    W.pub("event/swap", idea, retain=False)
    W.swap_test(dict(idea, report=""))
    assert _pubs(W, "event/swap") == [] and _pubs(W, "event/swap_test") == []
    W.pub("event/swap", dict(idea, auto=False), retain=False)  # a marked one still goes
    assert len(_pubs(W, "event/swap")) == 1


def test_swap_scan_takes_no_flica_client_and_loads_nothing(W):
    assert list(inspect.signature(W.swap_scan).parameters) == ["pot_rows"]
    W.swap_scan([P1, P2, P3, P4])  # count_fetch would raise
    assert not [t for t, _p, _r in W.FAKE.msgs if "fetch" in t]


def test_the_push_automation_listens_only_to_the_event_and_reads_no_sensor():
    """The swap idea push (ha/automations_flight_watcher.yaml) is triggered by flight_watcher/event/swap alone and reads
    no sensor, so no condition is needed there: the Watcher never publishes an automatic idea on that topic."""
    yaml = pytest.importorskip("yaml")
    autos = yaml.safe_load(open(os.path.join(REPO, "ha", "automations_flight_watcher.yaml"), encoding="utf-8"))
    (a,) = [x for x in autos if x.get("alias") == "Flight Watcher swap idea"]
    assert a["triggers"] == [{"topic": "flight_watcher/event/swap", "trigger": "mqtt"}] and not a.get("conditions")
    assert "swap_ideas" not in json.dumps(a) and "swap/state" not in json.dumps(a)
    assert not [x.get("alias") for x in autos if "swap_ideas" in json.dumps(x)]  # no push reads the sensor
    import importlib.util
    spec = importlib.util.spec_from_file_location("fw_guard", os.path.join(REPO, "ha", "check_push_isolation.py"))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard.main([os.path.join(REPO, "ha", "automations_flight_watcher.yaml")]) == 0


def test_a_portal_pilot_gets_no_alert_for_an_automatic_idea(portal_pilot, monkeypatch, tmp_path):
    P, _ = portal_pilot("pilot2")
    P.portal_start(threads=False)
    sent = []
    P.EXPORT["ntfy"] = type("N", (), {"enqueue": lambda self, rec: sent.append(rec)})()
    _setup(P, monkeypatch, tmp_path)
    P.swap_scan([P1, P2, P4])
    assert P.EXPORT["events_list"] == [] and sent == []
    P.S["trade_away"] = [K1]  # his own mark: a marked idea is his alert, as before (1.7.9, F#107)
    P.swap_scan([P1, P2, P4])
    assert [e["kind"] for e in P.EXPORT["events_list"]] == ["swap"] and len(sent) == 1
    assert P.EXPORT["events_list"][0]["data"]["for_trip"] == "H9001"


# ---------------------------------------------------------------- 6: bounded
def _many(n, start="2026-11-21"):
    """n turns on Nov 21 that pay more a day than H9001, the best last; 1:00 soft time each (never better than a marked
    H9002 by swap.better: less soft time and less credit)."""
    return [_row(f"H92{k:02d}", start, start, _hm(6 + k / 6), _hm(5 + k / 6)) for k in range(n)]


def test_the_sensor_keeps_the_top_automatic_ideas_and_counts_the_rest(W):
    W.swap_scan(_many(15))
    s = _sensor(W)
    assert s["auto_count"] == 15 and s["count"] == 15 and s["ideas"] == []
    assert len(s["auto_ideas"]) == s["auto_shown"] == W.SWAP_AUTO_MAX == 10 and s["auto_more"] == 5
    gains = [i["ppd_gain"] for i in s["auto_ideas"]]
    assert gains == sorted(gains, reverse=True) and s["auto_ideas"][0]["pairing"] == "H9214"  # the best pay a day first
    assert W.attr_size(s) <= W.ATTR_MAX and "trimmed" not in s


def test_the_size_cap_cuts_automatic_ideas_before_any_marked_one(W, monkeypatch):
    W.S["trade_away"] = [K2]
    monkeypatch.setattr(W, "ATTR_MAX", 4500)
    pm = _row("H9107", "2026-11-25", "2026-11-26", "11:00", "8:00")  # 3:00 soft time: better than H9002's 2:00
    rows = [dict(r, layover="L" * 60) for r in _many(15)] + [pm]
    W.swap_scan(rows)
    s = _sensor(W)
    assert [i["pairing"] for i in s["ideas"]] == ["H9107"]
    shown = len(s["auto_ideas"])
    assert 0 < shown < W.SWAP_AUTO_MAX and s["auto_more"] == 15 - shown and s["auto_count"] == 15
    assert s["auto_shown"] == shown
    assert W.attr_size(s) <= 4500 and "trimmed" not in s


# ---------------------------------------------------------------- 7: both instances, nothing crosses
def test_each_instance_ranks_only_its_own_trips_on_its_own_prefix(tmp_path, monkeypatch):
    A = _load(tmp_path, monkeypatch, "")
    _setup(A, monkeypatch, tmp_path, own={K1: OWN[K1]})
    A.swap_scan([P1, P2, P4])
    P = _load(tmp_path, monkeypatch, "pilot2")
    _setup(P, monkeypatch, tmp_path, own={K2: OWN[K2]})
    P.swap_scan([P1, P2, P4])
    a_topics = {t for t, _p, _r in A.FAKE.msgs}
    p_topics = {t for t, _p, _r in P.FAKE.msgs}
    assert a_topics and all(t.startswith("flight_watcher/") for t in a_topics)
    assert p_topics and all(t.startswith("flight_watcher_pilot2/") for t in p_topics)
    assert {i["for"] for i in _auto(A)} == {K1} and {i["for"] for i in _auto(P)} == {K2}
    assert A.S is not P.S and "H9002|2026-11-24" not in A.S["own_trips"] and K1 not in P.S["own_trips"]
    sys.modules.pop("watcher", None)


# ---------------------------------------------------------------- the dashboard table and the pot card
def _dash_md():
    d = json.load(open(os.path.join(REPO, "ha", "dashboard_flight_watcher.json"), encoding="utf-8"))
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "markdown" and "sensor.flight_watcher_swap_ideas" in (x.get("entity_id") or []):
                out.append(x["content"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
    return out


def _render(md, attrs):
    jinja2 = pytest.importorskip("jinja2")
    import re
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    env = ImmutableSandboxedEnvironment()
    env.filters["regex_replace"] = lambda s, find="", replace="": re.sub(find, replace, str(s))
    env.globals["state_attr"] = lambda eid, a: (attrs.get(eid) or {}).get(a)
    return env.from_string(md).render()


def test_the_dashboard_swap_table_shows_automatic_ideas_with_pay_per_day(W):
    (md,) = _dash_md()
    W.swap_scan(_many(12))
    s = _sensor(W)
    out = _render(md, {"sensor.flight_watcher_swap_ideas": s, "sensor.flight_watcher_would_trade": {"keys": []}})
    assert "No trips marked" not in out and "| Give up |" in out and "Per day" in out
    top = s["auto_ideas"][0]
    assert f"${top['ppd']:,.0f}" in out and f"${top['for_ppd']:,.0f}" in out and f"${top['pay']:,.0f}" in out
    assert "auto" in out and "2 more automatic ideas not shown (the best 10 by pay per day are)" in out
    none = _render(md, {"sensor.flight_watcher_swap_ideas": {"ideas": [], "count": 0, "priced": True},
                        "sensor.flight_watcher_would_trade": {"keys": []}})
    assert "No better-paying swap" in none
    unpriced = _render(md, {"sensor.flight_watcher_swap_ideas": {"ideas": [], "count": 0, "priced": False},
                            "sensor.flight_watcher_would_trade": {"keys": []}})
    assert "date of hire" in unpriced


def _pot_sw(sensor, marks=()):
    """The pot card's states (test_fw171_cards._pot_states, pilot2's ids) with this swap ideas sensor as published."""
    from test_fw171_cards import _pot_states, _s
    st = _pot_states(marks=marks, ideas=())
    st["sensor.flight_watcher_pilot2_swap_ideas"] = _s(str(sensor.get("count", 0)), dict(sensor))
    return st


def test_the_pot_card_lists_automatic_ideas_with_both_pay_per_day_figures(W):
    from test_fw171_cards import SWAP_JS, _browser, _card, _page
    W.swap_scan([P1, P2, P4])
    ideas = _auto(W)
    st = _pot_sw(_sensor(W))
    con = {}
    with _browser() as b:
        narrow = _page(b, [_card("pot-card")]).evaluate(SWAP_JS, st)
        wide = _page(b, [_card("pot-card")], width=1100).evaluate(SWAP_JS, st)
        for width in (390, 1100):  # WCAG AA on the portal's light and dark cards, as the 1.7.1 renders (F#119)
            for scheme in ("light", "dark"):
                pg = _page(b, [_card("pot-card")], width=width, scheme=scheme)
                con[(width, scheme)] = pg.evaluate("(st) => { const c = mount('flight-watcher-pot-card-pilot2', {}, st);"
                                                   " return {con: fwContrast(c), fit: fwFits(c)}; }", st)
                pg.context.close()
    for k, v in con.items():
        assert v["con"]["n"] > 0 and v["con"]["fails"] == [], (k, v["con"]["fails"])
        assert k[0] == 1100 or (v["fit"]["page"] <= 390 and v["fit"]["right"] <= 390), (k, v["fit"])
    assert not narrow["text"].startswith("Swap ideas No trips marked")
    assert wide["heads"] == ["Give up", "For", "Dates", "Layover", "Days", "Credit", "Soft", "Pay", "Per day", "Gain",
                             "Src", "Grid"]
    first = wide["rows"][0]
    top = ideas[0]
    assert first.startswith("H9001 auto H9102") and f"${top['ppd']:,.0f}" in first and f"${top['for_ppd']:,.0f}" in first
    assert f"${top['pay']:,.0f} (1 day) vs ${top['for_pay']:,.0f} (2 days)" in first
    assert narrow["rows"] == wide["rows"] and narrow["fit"]["page"] <= 390 and narrow["fit"]["inner"] <= 0
    assert "pay per day" in wide["key"].lower() and "never pushed" in wide["key"]


# ---------------------------------------------------------------- 1.7.15 review fixes
def _better(n):
    """n open trips on Nov 24-26 (H9002's days), each better than a marked H9002 by soft time; credit rising 0:10 a trip
    from 16:00 while soft time falls 0:04 a trip from 4:30, so the most soft time pays the least a day."""
    out = []
    for k in range(n):
        cr, soft = 16 + k / 6, 4.5 - k / 15
        out.append(_row(f"H93{k:02d}", "2026-11-24", "2026-11-26", _hm(cr), _hm(cr - soft)))
    return out


def test_marked_ideas_keep_the_1711_order_and_the_cap_trims_the_least_soft_time_first(W, monkeypatch):
    """R1, F1: the marked trips' ideas stay in gain_h order (soft time first, the order they push in), and the size cap
    drops the least soft time from the end, as in 1.7.11: the best soft-time idea, the first push, stays listed."""
    W.S["trade_away"] = [K2]
    monkeypatch.setattr(W, "ATTR_MAX", 9000)
    W.swap_scan(_better(30))
    s = _sensor(W)
    shown = s["ideas"]
    pushed = [p["pairing"] for p in _pubs(W, "event/swap")]
    assert len(pushed) == 30 and s.get("trimmed", 0) > 0 and len(shown) == 30 - s["trimmed"]
    assert [i["gain_h"] for i in shown] == sorted((i["gain_h"] for i in shown), reverse=True)
    assert shown[0]["pairing"] == "H9300" == pushed[0]  # +2:30 soft: the best by swap.better, the first push
    assert [i["pairing"] for i in shown] == pushed[:len(shown)]  # what the cap leaves out is the tail of the pushes
    assert shown[0]["ppd_gain"] < shown[-1]["ppd_gain"]  # not by pay per day: a marked trip keeps its own rule
    assert all(not i["auto"] for i in shown) and W.attr_size(s) <= 9000


def test_the_sensor_ideas_keep_their_1711_meaning_and_the_automatic_ones_have_their_own_list(W):
    """F3: "ideas" (the old dashboard card, the schedule card's swap tags) holds only the marked trips' ideas, so the
    dashboard still live on Pako shows no automatic idea, unlabeled, under its Key; the new card reads auto_ideas."""
    W.S["trade_away"] = [K1]
    W.swap_scan([P1, P2, P3, P4])
    s = _sensor(W)
    assert {(i["for"], i["pairing"]) for i in s["ideas"]} == {(K1, "H9101"), (K1, "H9103")}
    assert not any(i.get("auto") for i in s["ideas"])
    assert [(i["for"], i["pairing"], i["auto"]) for i in s["auto_ideas"]] == [(K2, "H9104", True)]
    readme = open(os.path.join(REPO, "ha", "README.md"), encoding="utf-8").read()
    assert "it shows the ideas only while a trip is marked" not in readme
    assert "step of the 1.7.15 go-live" in readme and "`auto_ideas`" in readme


def _crew3(W, key=K2):
    W.S["own_trips"][key]["crew"] = ["CA X", "FO Y", "RO Z"]  # his roster: 3 pilots (positions only)


def test_a_pot_trip_whose_only_open_seat_is_ro_is_priced_in_the_ro_seat(W, monkeypatch, tmp_path):
    """R3 (PWA 4.O.1): RO $4.00 a block hour on any crew, FO $3.00 on a 3-pilot crew: the pot row's open_seats says
    which seat he would fly. FO,RO open: priced FO, as price_moves falls back."""
    pdir = tmp_path / "www" / "flight-watcher"
    pdir.mkdir(parents=True)
    rows = [["H9111", "15:00", "13:00", "CA01FO01RO01", "HNL-LAX-HNL"], ["H9112", "15:00", "13:00", "CA01FO01RO01", "HNL-LAX-HNL"]]
    (pdir / "pairings_2026-11.json").write_text(json.dumps({"month": "2026-11", "cols": ["id", "credit", "block", "crew", "route"],
                                                            "rows": rows}))
    _crew3(W)
    W.swap_scan([_row("H9111", "2026-11-24", "2026-11-26", "15:00", "13:00", open_seats="RO"),
                 _row("H9112", "2026-11-24", "2026-11-26", "15:00", "13:00", open_seats="FO,RO")])
    (i,) = _auto(W)
    assert i["pairing"] == "H9111" and i["for"] == K2
    assert i["for_pay"] == round(15 * RATE + 13 * 3.0, 2)  # his FO seat on 3
    assert i["pay"] == round(PAY.trip_gross(15.0, 13.0, 3, "LAX", "H9111|2026-11-24", "RO", RATE), 2) == round(15 * RATE + 13 * 4.0, 2)
    assert i["ppd_gain"] == round(13 * 1.0 / 3, 2)


def test_a_pot_trip_no_package_lists_is_priced_with_its_own_roster(W):
    """R5: the pot row's crew (its roster, open seats included) gives the FO 3-pilot override when no package lists
    the trip, as his own trip's roster does for his."""
    _crew3(W)
    crew = [["CA", "Doe"], ["FO", "OPEN"], ["RO", "Roe"]]
    W.swap_scan([_row("H9113", "2026-11-24", "2026-11-26", "15:05", "13:00", crew=crew, open_seats="FO")])
    (i,) = _auto(W)
    assert i["pairing"] == "H9113" and i["pay"] == round(PAY.hrs("15:05") * RATE + 13 * 3.0, 2)
    assert i["ppd_gain"] == round((PAY.hrs("15:05") * RATE + 39.0) / 3 - (15 * RATE + 39.0) / 3, 2) == 7.2


def test_his_trip_is_priced_with_its_schedule_layover_for_the_er_rule(W):
    """R6: his trip's own record holds no layover; its schedule item's (SIN) turns the Extended Range +15% on when no
    package or roster says otherwise, so a 10:30 LAX trip that pays less a day is no automatic idea, and a marked
    trip's idea shows his ER pay."""
    for it in W.S["schedule"]["2026-11"]["items"]:
        if it["trip"] == "H9001":
            it["lay"] = "SIN"
    mine = round(10 * RATE * 1.15, 2)
    W.swap_scan([_row("H9120", "2026-11-20", "2026-11-21", "10:30", "8:00")])
    assert _auto(W) == []
    W.S["trade_away"] = [K1]
    W.swap_scan([_row("H9121", "2026-11-20", "2026-11-21", "12:00", "8:00")])  # +2:00 soft: better for a marked H9001
    (i,) = _sensor(W)["ideas"]
    assert i["for_pay"] == mine and i["for_ppd"] == round(mine / 2, 2)


def test_the_same_bid_period_is_the_pots_and_his_trips_page_without_pairing_files(W, monkeypatch, tmp_path):
    """R7: no pairing file gives the bounds. H9005 Dec 1-3 is listed on November's page (Nov 1 to Dec 3) and on
    December's (Dec 1 on, FLICA's next page starts on the period before's last day): it is November's trip, so a trip
    from November's pot (Nov 30-Dec 1) is a swap for it and one from December's pot (Dec 2-3) is not."""
    own = {"H9005|2026-12-01": ("2026-12-03", {"credit": "15:00", "blk": "13:00", "soft": "2:00", "seat": "FO"})}
    _setup(W, monkeypatch, tmp_path, own=own)
    item = {"trip": "H9005", "start": "2026-12-01", "end": "2026-12-03", "lay": "LAX"}
    nov = [[date(2026, 11, d).isoformat(), "", ""] for d in range(1, 31)] + [["2026-12-01", "H9005", "LAX"],
                                                                            ["2026-12-02", "", "LAX"], ["2026-12-03", "", "HNL"]]
    dec = [["2026-12-01", "H9005", "LAX"], ["2026-12-02", "", "LAX"], ["2026-12-03", "", "HNL"]] + \
          [[date(2026, 12, d).isoformat(), "", ""] for d in range(4, 32)]
    W.S["schedule"] = {"2026-11": {"items": [dict(item)], "days": nov}, "2026-12": {"items": [dict(item)], "days": dec}}
    W.S["grid"] = _grid("2026-11-25", 15)
    assert W.bid_period_of(date(2026, 12, 1)) is None and W.bid_period_fn()("2026-12-01") == "2026-12"
    dec_pot = _row("H9130", "2026-12-02", "2026-12-03", "16:00", "13:00", month="2026-12")
    nov_pot = _row("H9131", "2026-11-30", "2026-12-01", "16:00", "13:00", month="2026-11")
    W.swap_scan([dec_pot, nov_pot])
    assert [(i["for"], i["pairing"]) for i in _auto(W)] == [("H9005|2026-12-01", "H9131")]


def test_a_pot_rows_bid_period_is_its_pots_month_when_the_key_names_one(W):
    """R7: the pot's key: 'YYYY-MM', or the desktop menu's month name (the year nearest the trip); the mobile pages'
    keys and the close-in folder name no month, so the trip's first day decides (period_of)."""
    of = lambda iso: "day:" + iso  # noqa: E731
    assert W._pot_period({"month": "2026-11"}, "2026-12-01", of) == "2026-11"
    assert W._pot_period({"month": "November"}, "2026-12-01", of) == "2026-11"
    assert W._pot_period({"month": "January"}, "2026-12-31", of) == "2027-01"
    assert W._pot_period({"month": "December"}, "2027-01-01", of) == "2026-12"
    for key in ("mobile", "mobile_003.153", W.CLOSE_IN_KEY, "", None):
        assert W._pot_period({"month": key}, "2026-12-01", of) == "day:2026-12-01"


def _cap_case(W, monkeypatch, attr_max):
    W.S["trade_away"] = [K2]
    monkeypatch.setattr(W, "ATTR_MAX", attr_max)
    pm = _row("H9107", "2026-11-25", "2026-11-26", "11:00", "8:00")  # better than H9002 by soft time
    W.swap_scan([dict(r, layover="L" * 60) for r in _many(15)] + [pm])
    return _sensor(W)


@pytest.mark.parametrize("room", ["some", "none"])
def test_the_n_more_line_counts_the_automatic_ideas_listed(W, monkeypatch, room):
    """R4, F2: the size cap can list fewer automatic ideas than auto_max (here some, then none): both the dashboard and
    the pot card say how many are listed, never "the top 10"."""
    from test_fw171_cards import SWAP_JS, _browser, _card, _page
    attr_max = 4500
    if room == "none":  # room for the marked idea and the counts only
        full = _cap_case(W, monkeypatch, 10 ** 6)
        attr_max = W.attr_size(dict(full, auto_ideas=[], auto_shown=0, auto_more=15)) + 50
        W.FAKE.msgs.clear()
    s = _cap_case(W, monkeypatch, attr_max)
    k = len(s["auto_ideas"])
    assert s["auto_shown"] == k < W.SWAP_AUTO_MAX and s["auto_more"] == 15 - k and s["auto_max"] == 10
    assert (k > 0) == (room == "some") and [i["pairing"] for i in s["ideas"]] == ["H9107"] and "trimmed" not in s
    want = (f"{15 - k} more automatic ideas not shown (the best {k} by pay per day are)." if k
            else "15 automatic ideas not shown (no room left next to your marked trips' ideas).")
    (md,) = _dash_md()
    out = _render(md, {"sensor.flight_watcher_swap_ideas": s, "sensor.flight_watcher_would_trade": {"keys": [K2]}})
    assert want in out and "the top 10" not in out
    with _browser() as b:
        card = _page(b, [_card("pot-card")], width=1100).evaluate(SWAP_JS, _pot_sw(s, marks=(K2,)))
    assert want in card["text"] and "the top 10" not in card["text"]
    assert len(card["rows"]) == 1 + k and card["rows"][0].startswith("H9002 H9107")


def test_the_portal_contract_says_no_mark_no_alert_and_names_the_automatic_ideas():
    """F5: a portal pilot with no mark now has automatic ideas on his swap ideas sensor (never an alert)."""
    doc = open(os.path.join(HERE, "PORTAL_CONTRACT.md"), encoding="utf-8").read()
    roles = open(os.path.join(HERE, "roles.py"), encoding="utf-8").read()
    assert "no mark, no idea" not in doc and "no mark, no idea" not in roles
    sec = doc[doc.index("- `swap` (revision 4, F#107)"):doc.index("- `bid_calendar` (revision 3, FW-0070)")]
    assert "no mark, no alert" in sec and "`auto_ideas`" in sec and "never published on `event/swap`" in sec
    assert "the fixture is unchanged" in sec

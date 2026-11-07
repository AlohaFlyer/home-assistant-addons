"""FW-0064 (Ryan, Nov 6): a crew-to-crew Trade shows only as schedule changes (FLICA lists it on neither the Open Time
Requests page nor Tradeboard My Requests). The Watcher turns them into the same event/request_decided push the request
path sends, once, priced with pay.py. Synthetic schedules with made-up trips (H39xx), times and crew ("Doe, Jane");
the sequence is the Nov 6 one: an open time swap approved at 10:01, then the trade's drops at 11:30 and 12:04 and its
two adds at 14:01 (FLICA's "Schedule Updated" stamps, HST)."""
import json
import os
import sys

import pytest

import pay as PAY
import submit as SUB
import trades as TR

DOW = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")


def _html(trips, updated):
    """A mobile schedule page for Nov 2026 (Nov 1 is a Sunday) and Dec 1-2. trips: {day: (pairing, layover, days)}."""
    rows, k = {}, 0
    for d, (pid, lay, n) in trips.items():
        rows[d] = (f"<a>{pid}</a>", lay)
        for j in range(1, n):
            rows.setdefault(d + j, ("-", "HNL" if j == n - 1 else "-"))
    for d in range(22, 29):
        rows[d] = ("VAC", "-")
    body = []
    for d in range(1, 33):
        act, lay = rows.get(d, ("-", "-"))
        dd = d if d <= 30 else d - 30
        body.append(f"<tr><td>{DOW[(d - 1) % 7]}</td><td>{dd:02d}</td><td>{act}</td><td>{lay}</td></tr>")
        k += 1
    return ("<html><body><div>Nov 2026 Schedule</div><table><tr><td>Schedule Updated:<br>"
            f"{updated} HA</td></tr></table><table border=1><tr><th>Day</th><th>Pairing</th><th>Layover</th></tr>"
            + "".join(body) + "</table><p>Block 92.33</p><p>Credit 121.48</p><p>Days Off 15</p></body></html>")


BASE = {1: ("H3915", "SIN", 4), 6: ("H3920", "LAS", 3), 9: ("H3981", "SYD", 4), 14: ("H3929", "LAX", 2),
        18: ("H3959", "SEA", 2), 30: ("H3907", "KIX", 3)}


def _crew(n):
    return [f"CA Doe, John ({10000 + i})" if i == 0 else f"{'FO' if i == 1 else 'RO'} Doe, Jane ({20000 + i})" for i in range(n)]


def _rec(credit, blk, seat, n):
    return {"report": "07:00", "last_arr": "11:37", "credit": credit, "blk": blk, "seat": seat, "crew": _crew(n),
            "duties": [], "soft": "0:00"}


@pytest.fixture
def W(tmp_path, monkeypatch):
    from test_instance import FakeClient, _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info", "my_name": "Doe",
                                          "category_check": "HNL 332 FO"})
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "prev_month_check", lambda fl, url, m: None)
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
    monkeypatch.setattr(W, "ha_state", lambda e: {"input_number.flight_watcher_longevity_year": "12.0",
                                                  "input_text.flight_watcher_er_trips": ""}.get(e))
    clock = {"t": "2026-11-06T19:30:00+00:00"}
    monkeypatch.setattr(W, "now_iso", lambda: clock["t"])
    W.CLOCK, W.FAKE, W.PAGE = clock, fake, {"html": ""}

    class FL:
        def fetch(self, url):
            return W.PAGE["html"]
    W.FL = FL()
    return W


def _read(W, hst, trips, updated):
    """One schedule read at hst ('HH:MM' on Nov 6) of a page FLICA last changed at updated ('HH:MM:SS')."""
    h, m = map(int, hst.split(":"))
    W.CLOCK["t"] = f"2026-11-0{6 + (h + 10) // 24}T{(h + 10) % 24:02d}:{m:02d}:00+00:00"
    W.PAGE["html"] = _html(trips, f"Nov 6, 2026 {updated}")
    W.schedule_check(W.FL, force=True)


def _events(W, topic="event/request_decided"):
    return [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"flight_watcher/{topic}"]


def _nov6(W):
    """The Nov 6 sequence up to the trade's adds; returns the trips after each step."""
    _read(W, "09:30", BASE, "08:00:00")
    W.S["own_trips"] = {"H3959|2026-11-18": _rec("13:00", "11:00", "FO", 2), "H3929|2026-11-14": _rec("10:00", "9:00", "FO", 2)}
    # 10:00 open time swap: give H3929 14NOV, take H3904 13NOV; FLICA 10:01:11, read 10:05, the list read 10:07
    swap = {k: v for k, v in BASE.items() if k != 14}
    swap[13] = ("H3904", "NRT", 3)
    _read(W, "10:05", swap, "10:01:11")
    W.CLOCK["t"] = "2026-11-06T20:07:00+00:00"
    row = {"key": "ts:01DD0001:00000001", "date": "11/06", "time": "10:00", "type": "Swap", "status": "Approved",
           "legs": [{"trip": "H3929", "day": "14NOV", "side": "drop"}, {"trip": "H3904", "day": "13NOV", "side": "add"}]}
    W.note_decided(row)
    W.trade_check()
    W.S["own_trips"]["H3904|2026-11-13"] = _rec("16:35", "16:35", "RO", 3)  # read by own_trip_times later
    t1 = {k: v for k, v in swap.items() if k != 18}
    _read(W, "11:33", t1, "11:30:25")          # the trade's first drop
    t2 = {k: v for k, v in t1.items() if k != 13}
    _read(W, "12:05", t2, "12:04:46")          # its second
    t3 = {**t2, 12: ("H3920", "LAS", 3), 15: ("H3920", "LAS", 3)}
    _read(W, "14:13", t3, "14:01:09")          # both adds in one change
    return t3


def test_nov6_trade_pushed_once_as_request_decided_with_pay(W):
    t3 = _nov6(W)
    assert len(_events(W, "event/schedule_changed")) == 4  # the old event still goes out for each change
    assert _events(W) == []  # the swap was the request path's; the trade waits for a quiet read
    _read(W, "14:43", t3, "14:01:09")
    assert _events(W) == []  # quiet, but the trips taken have no credit read yet (waits up to 2 h)
    W.S["own_trips"].update({"H3920|2026-11-12": _rec("15:00", "12:19", "FO", 2),
                             "H3920|2026-11-15": _rec("15:00", "12:19", "FO", 2)})
    W.CLOCK["t"] = "2026-11-07T00:50:00+00:00"
    W.trade_check()  # the next requests read runs it too
    (ev,) = _events(W)
    assert ev["type"] == "Trade" and ev["status"] == "Approved" and ev["source"] == "schedule"
    assert (ev["date"], ev["time"]) == ("11/06", "14:01")  # FLICA's stamp of the last change, HST
    assert [(x["trip"], x["day"], x["side"]) for x in ev["legs"]] == [
        ("H3959", "18NOV", "drop"), ("H3904", "13NOV", "drop"), ("H3920", "12NOV", "add"), ("H3920", "15NOV", "add")]
    assert ev["changes"] == ["Nov 6, 2026 11:30:25", "Nov 6, 2026 12:04:46", "Nov 6, 2026 14:01:09"]
    rate = W.pay_settings()[0]
    assert rate == PAY.rate_for(12, W.local_now().date().isoformat())
    gave = 13.0 * rate + (16 + 35 / 60) * rate + (16 + 35 / 60) * PAY.IRO_OVERRIDE  # RO seat on H3904: PWA 4.O.1
    took = 2 * 15.0 * rate                                                           # FO, 2-pilot crew: no override
    p = ev["pay"]
    assert p["delta"] == pytest.approx(round(took - gave, 2), abs=0.02) and p["delta_text"] == PAY.usd(took - gave)
    assert p["credit_delta"] == "+0:25" and p["year"] == 12
    assert [(x["trip"], x["side"], x["seat"], x["credit"]) for x in p["parts"]] == [
        ("H3959", "drop", "FO", "13:00"), ("H3904", "drop", "RO", "16:35"), ("H3920", "add", "FO", "15:00"),
        ("H3920", "add", "FO", "15:00")]
    # the automation's fields: route words from the parts, the tag from the key
    assert ev["key"].startswith("sched:2026-11-06:") and "|" not in ev["key"].split(":", 2)[2]
    # once: more quiet reads, a requests read, and a restart push nothing more
    _read(W, "15:13", t3, "14:01:09")
    W.trade_check()
    assert len(_events(W)) == 1
    W.save_state(W.S)
    sys.modules.pop("watcher", None)
    import watcher as W2
    W2.MQ, W2.now_iso = W.FAKE, W.now_iso
    W2.prev_month_check, W2.ha_state = W.prev_month_check, W.ha_state
    assert W2.S["sched_trades_pushed"] and W2.S["sched_moves"]  # kept in the state across the restart
    W2.trade_check()
    W.PAGE["html"] = _html(t3, "Nov 6, 2026 14:01:09")
    W2.schedule_check(W.FL, force=True)
    assert len(_events(W)) == 1


def test_swap_alone_and_a_pairing_change_are_not_trades(W):
    """The request path's own decision explains its changes; H3915 turning into H3915B (rerouted) on the same start is
    a change of the pairing, not something given and taken."""
    _read(W, "09:30", BASE, "08:00:00")
    swap = {k: v for k, v in BASE.items() if k != 14}
    swap[13] = ("H3904", "NRT", 3)
    swap[1] = ("H3915B", "SIN", 4)
    _read(W, "10:05", swap, "10:01:11")
    W.note_decided({"key": "k1", "date": "11/06", "time": "10:00", "type": "Swap", "status": "Approved",
                    "legs": [{"trip": "H3929", "day": "14NOV", "side": "drop"}, {"trip": "H3904", "day": "13NOV", "side": "add"}]})
    _read(W, "10:35", swap, "10:01:11")
    _read(W, "11:05", swap, "10:01:11")
    assert _events(W) == []
    assert {m["by"] for m in W.S["sched_moves"]} == {"k1", "pairing change"}


def test_legless_decision_explains_what_changed_while_it_was_decided(W):
    """A decision whose view page was not read (no legs) covers the changes stamped between its filing and 10 min after
    the Watcher saw it, and nothing later."""
    _read(W, "09:30", BASE, "08:00:00")
    swap = {k: v for k, v in BASE.items() if k != 14}
    swap[13] = ("H3904", "NRT", 3)
    _read(W, "10:05", swap, "10:01:11")
    W.CLOCK["t"] = "2026-11-06T20:06:00+00:00"
    W.note_decided({"key": "k2", "date": "11/06", "time": "10:00", "type": "Swap", "status": "Approved", "legs": []})
    later = {k: v for k, v in swap.items() if k != 18}
    later[20] = ("H3970", "LAX", 2)
    _read(W, "11:33", later, "11:30:25")
    W.trade_check()
    by = {(m["side"], m["trip"]): m.get("by") for m in W.S["sched_moves"]}
    assert by[("drop", "H3929")] == by[("add", "H3904")] == "k2"
    assert by[("drop", "H3959")] is None and by[("add", "H3970")] is None  # 11:30 is a different change


def test_pending_trade_decided_on_the_schedule_and_not_again_by_its_list(W):
    """A Trade still Processing on Tradeboard My Requests whose given trips left and taken trips arrived is pushed at
    once under its own key; when the list then reads Approved, request_news() finds it already pushed."""
    _read(W, "09:30", BASE, "08:00:00")
    row = {"key": "11/06|09:58|Trade|H3920+H3929+H3959|1", "date": "11/06", "time": "09:58", "type": "Trade",
           "status": "Processing", "trips": ["H3929", "H3959", "H3920", "H3920"], "detail": "",
           "legs": [{"trip": "H3929", "day": "14NOV", "side": "drop", "seat": "FO"},
                    {"trip": "H3959", "day": "18NOV", "side": "drop", "seat": "FO"},
                    {"trip": "H3920", "day": "12NOV", "side": "add", "seat": "RO"},
                    {"trip": "H3920", "day": "15NOV", "side": "add", "seat": "FO"}]}
    W.S["tb_req_rows"] = {"152": [row]}
    W.S["own_trips"] = {"H3959|2026-11-18": _rec("13:00", "11:00", "FO", 2), "H3929|2026-11-14": _rec("10:00", "9:00", "FO", 2)}
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)  # the trips taken have no own record yet: the month's package prices them
    json.dump({"month": "2026-11", "cols": ["id", "route", "credit", "block", "crew"],
               "rows": [["H3920", "HNL-LAS-HNL", "15h00", "12h19", "CA01FO01RO01"]]},
              open(os.path.join(W.CARD_PAIRINGS, "pairings_2026-11.json"), "w"))
    t1 = {k: v for k, v in BASE.items() if k not in (14, 18)}
    _read(W, "11:33", t1, "11:30:25")
    assert _events(W) == []  # half of it: nothing yet
    _read(W, "14:13", {**t1, 12: ("H3920", "LAS", 3), 15: ("H3920", "LAS", 3)}, "14:01:09")
    (ev,) = _events(W)  # at once, no quiet read needed: the request names every trip
    assert ev["key"] == row["key"] and ev["status"] == "Approved" and ev["bcid"] == "001.152"
    assert [x["side"] for x in ev["pay"]["parts"]] == ["drop", "drop", "add", "add"]
    assert [x["seat"] for x in ev["pay"]["parts"]] == ["FO", "FO", "RO", "FO"]  # a taken trip's seat from the request page
    rate = W.pay_settings()[0]
    took = 15 * rate + (12 + 19 / 60) * PAY.IRO_OVERRIDE + 15 * rate + (12 + 19 / 60) * 3.00  # RO; FO on a 3-pilot crew
    assert ev["pay"]["delta"] == pytest.approx(round(took - 23 * rate, 2), abs=0.02)
    assert SUB.request_news(W.S["ot_req_pushed"], [{**row, "status": "Approved"}]) == []
    _read(W, "14:43", {**t1, 12: ("H3920", "LAS", 3), 15: ("H3920", "LAS", 3)}, "14:01:09")
    assert len(_events(W)) == 1  # its moves are spent: no second push as a trade


def test_drops_alone_adds_alone_and_other_days_are_not_trades():
    mv = TR.moves([{"trip": "H3959", "start": "2026-11-18"}, {"trip": "VAC", "start": "2026-11-22"}], [],
                  "2026-11", "Nov 6, 2026 11:30:25", "2026-11-06T21:33:00+00:00")
    assert [(m["side"], m["trip"], m["day"]) for m in mv] == [("drop", "H3959", "2026-11-06")]  # codes are not trips
    add = TR.moves([], [{"trip": "H3920", "start": "2026-11-12"}], "2026-11", "Nov 7, 2026 08:00:00",
                   "2026-11-07T18:05:00+00:00")
    assert TR.groups(mv) == {} and TR.groups(mv + add) == {}  # a drop one day and an add the next: no trade
    assert TR.stamp("Nov 6, 2026 23:59:00", "2026-11-06T21:00:00+00:00") == "2026-11-06T21:00:00+00:00"  # stamp after the read
    assert TR.stamp("", "2026-11-06T21:00:00+00:00") == "2026-11-06T21:00:00+00:00"
    assert TR.leg_matches({"trip": "H3620", "day": "12NOV"}, {"trip": "H3620A", "start": "2026-11-12", "side": "add"})
    assert not TR.leg_matches({"trip": "H3620", "day": "13NOV"}, {"trip": "H3620", "start": "2026-11-12", "side": "add"})
    assert not TR.leg_matches({"trip": "H3620", "side": "drop"}, {"trip": "H3620", "start": "2026-11-12", "side": "add"})

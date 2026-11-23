"""1.8.1 (T3, S7): the first read of a new request folder. The Open Time Requests list of a bid folder (BCID) and the
Tradeboard My Requests page of a bid number each have their own first read, like the close-in folder's (FW-0034): on
it only decisions filed in the last REQ_FIRST_H hours are pushed, the rest are history (marked seen, never pushed
later). So the moment Ryan sets Pot month to Both, December's 003.153 and Tradeboard 001.153 do not send their whole
history as request_decided pushes, and a pilot on This month gets the same when December's folder joins on Dec 2.
Folders read before the update (November's 003.152 and 001.152, from the state 1.8.0 left) are not new: what is
decided on them still pushes, and nothing already pushed goes out again. FLICA is never reached: a fake browser
answers with synthetic pages (made-up pairings H39xx, made-up employee numbers, no names)."""
import json
from datetime import datetime, timedelta

import submit as SUB
import tradeboard as TB
from pot import visible_text
from test_fw181_pot_month import HST, _periods, at
from test_release_a_flica import mk, real_fl  # noqa: F401

MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
EMPTY_TB = "<html><body>my requests</body></html>"


def _clock_now(W, monkeypatch):
    """requests_check dates each request against datetime.now: make it the test clock's."""
    class DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(W.CLOCK.t, tz)
    monkeypatch.setattr(W, "datetime", DT)


def _t(W, hours_ago):
    return datetime.fromtimestamp(W.CLOCK.t, HST) - timedelta(hours=hours_ago)


def ago(W, hours):
    """A request list row's 'MM/DD HH:MM', hours before the test clock (HST)."""
    return _t(W, hours).strftime("%m/%d %H:%M")


def tb_row(W, hours, st, gave="H3931:05DEC", took="H3932:06DEC"):
    """A Tradeboard My Requests row ('DD MON HH:MM Trade ... With Emp #: ... For ... <status>'), made-up trips."""
    t = _t(W, hours)
    return f"{t.day:02d} {MON[t.month - 1]} {t:%H:%M} Trade {gave} With Emp #: 10001 For {took} {st} [ ]"


def req_page(body):
    return f"<html><body>open time requests {body}</body></html>"


def tb_page(*rows):
    return "<html><body>Requested (HA) Type Status Cancel/Hide " + " ".join(rows) + "</body></html>"


def _fl(W, lists, tbs):
    """The fake browser: a folder's request list by BCID, a Tradeboard number's My Requests page."""
    def answer(u):
        if "TB_MyRequests" in u:
            return tbs.get(u.split("bcid=001.")[1], EMPTY_TB)
        if "mobileotrequest" in u:
            return lists.get(W.bcid(u), req_page(""))
        return "<html><body>x</body></html>"
    return real_fl(W, answer)


def _read(W, fl):
    W.S["req_force"] = True
    W.requests_check(fl)


def _events(W):
    return [json.loads(p) for t, p in W.MQ.msgs if t == f"{W.T}/event/request_decided"]


def _seen(W):
    """(status, bcid, trips) of each request_decided push so far."""
    return [(e["status"], e["bcid"], tuple(e.get("trips") or [])) for e in _events(W)]


def _read_from(fl, n):
    """The request lists and My Requests pages loaded since load n: BCIDs ('001.<n>' for the Tradeboard)."""
    out = []
    for _, u in fl.loads[n:]:
        if "TB_MyRequests" in u:
            out.append("001." + u.split("bcid=001.")[1])
        elif "mobileotrequest" in u:
            out.append(u.split("BCID=")[1].split("&")[0])
    return out


def test_ryan_both_reads_december_history_quietly_and_november_still_pushes(mk, monkeypatch):
    """Ryan (admin), state carried over from 1.8.0 (November's 003.152 and Tradeboard 152 read before), then Pot
    month Both: December's 003.153 and 001.153 are read for the first time. Only their decisions filed in the last
    REQ_FIRST_H hours push; the older ones (Nov 12, Nov 22, Nov 15) are history. November's folders are not new: a
    request filed 3 days ago that FLICA decided after the update still pushes (no lost push), and the decision 1.8.0
    already pushed does not go out again. After the first read, a new decision on December's folders pushes."""
    W = mk("", t=at(2026, 11, 23, 8, 0))
    _clock_now(W, monkeypatch)
    # the state 1.8.0 left: one pot page (003.152), its list and Tradeboard 152 read, the feature's first read done
    nov_list = req_page(f"{ago(W, 100)} swap approved drop h3901 add h3902 {ago(W, 72)} add pending h3903")
    nov_tb = tb_page(tb_row(W, 50, "Processing", "H3933:28NOV", "H3934:29NOV"))
    rows = SUB.parse_request_rows(visible_text(nov_list), nov_list)
    W.S.update(ot_req_init=True, tb_req_init=True, ot_req_rows={"003.152": rows},
               tb_req_rows={"152": TB.parse_my_requests(visible_text(nov_tb))},
               ot_req_pushed={SUB.push_key(r): "2026-11-19T00:00:00+00:00" for r in rows if r["status"] in SUB.DECIDED},
               pot_urls={"2026-11": W.mobile_pot_url("003.152")})
    W.S["pot_month"] = "Both"  # Ryan's choice after the update
    W.S["pot_urls"] = W.pot_plan()[0]
    assert sorted(W.bcid(u) for u in W.S["pot_urls"].values()) == ["003.152", "003.153"]
    lists = {
        "003.152": nov_list.replace("add pending h3903", "add approved h3903"),  # decided after the update
        "003.153": req_page(f"{ago(W, 260)} swap approved drop h3911 add h3912 "  # filed Nov 12
                            f"{ago(W, 30)} swap denied drop h3913 add h3914 "  # filed Nov 22
                            f"{ago(W, 40)} swap pending drop h3916 add h3917 "
                            f"{ago(W, 2)} add approved h3915"),  # filed 2 h ago: still news on the first read
    }
    dec_tb = [tb_row(W, 190, "Approved"),  # filed Nov 15
              tb_row(W, 1, "Denied", "H3935:10DEC", "H3936:11DEC")]
    tbs = {"152": nov_tb.replace("Processing", "Approved"), "153": tb_page(*dec_tb)}
    fl = _fl(W, lists, tbs)
    _read(W, fl)
    assert sorted(_read_from(fl, 0)) == ["001.152", "001.153", "003.152", "003.153"]
    assert sorted(_seen(W)) == [("Approved", "001.152", ("H3933", "H3934")), ("Approved", "003.152", ("H3903",)),
                                ("Approved", "003.153", ("H3915",)), ("Denied", "001.153", ("H3935", "H3936"))]
    n = len(_events(W))
    _read(W, fl)
    assert len(_events(W)) == n  # the same pages again: nothing twice, the history never pushes later
    lists["003.153"] = lists["003.153"].replace("swap pending", "swap approved")  # decided after the first read
    tbs["153"] = tb_page(*dec_tb, tb_row(W, 20, "Approved", "H3937:14DEC", "H3938:15DEC"))  # already decided
    _read(W, fl)
    assert sorted(_seen(W)[n:]) == [("Approved", "001.153", ("H3937", "H3938")),
                                    ("Approved", "003.153", ("H3916", "H3917"))]


def test_pilot_this_month_december_folder_joins_on_dec_2_with_its_own_first_read(mk, monkeypatch):
    """A pilot instance on This month: November's 003.152 and 001.152 are read through Dec 1 (November's bid
    period). On Dec 2 December's 003.153 and 001.153 take over: their first read pushes only what was filed in the
    last REQ_FIRST_H hours; a later decision on them pushes."""
    W = mk("james", t=at(2026, 11, 30, 12, 0))
    _clock_now(W, monkeypatch)
    _periods(W)
    lists, tbs = {"003.152": req_page(f"{ago(W, 1)} add denied h3904")}, {}
    fl = _fl(W, lists, tbs)
    W.S["pot_urls"] = W.pot_plan()[0]
    _read(W, fl)
    assert _read_from(fl, 0) == ["003.152", "001.152"]
    assert _seen(W) == [("Denied", "003.152", ("H3904",))]  # the feature's first read: filed 1 h ago is news
    W.CLOCK.t = at(2026, 12, 1, 9, 0)
    W.S["pot_urls"] = W.pot_plan()[0]
    k = len(fl.loads)
    _read(W, fl)
    assert W.this_month_key() == "2026-11" and _read_from(fl, k) == ["003.152", "001.152"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    W.S["pot_urls"] = W.pot_plan()[0]
    lists["003.153"] = req_page("11/25 10:00 add approved h3911 "  # days old: history
                                "12/01 10:00 swap denied drop h3912 add h3913 "  # 14 h old: history
                                "12/01 12:00 add pending h3915 "
                                "12/01 22:00 add approved h3914")  # 2 h old: news
    tbs["153"] = tb_page(tb_row(W, 16, "Approved"), tb_row(W, 0.5, "Approved", "H3939:20DEC", "H3940:21DEC"))
    k = len(fl.loads)
    _read(W, fl)
    assert W.this_month_key() == "2026-12" and _read_from(fl, k) == ["003.153", "001.153"]
    assert _seen(W)[1:] == [("Approved", "003.153", ("H3914",)), ("Approved", "001.153", ("H3939", "H3940"))]
    lists["003.153"] = lists["003.153"].replace("add pending h3915", "add approved h3915")
    _read(W, fl)
    assert _seen(W)[3:] == [("Approved", "003.153", ("H3915",))]  # decided after the folder's first read


def test_a_first_read_cut_short_stays_a_first_read(mk, monkeypatch):
    """December's list fails to load on its first try: it is still new on the next good read (its history stays
    quiet), and a folder read before the update keeps pushing."""
    W = mk("", t=at(2026, 11, 23, 9, 0))
    _clock_now(W, monkeypatch)
    W.S.update(ot_req_init=True, tb_req_init=True, ot_req_rows={"003.152": []}, tb_req_rows={"152": []})
    W.S["pot_month"] = "Both"
    W.S["pot_urls"] = W.pot_plan()[0]
    lists = {"003.153": RuntimeError("synthetic: net::ERR_TIMED_OUT")}
    fl = _fl(W, lists, {})
    _read(W, fl)
    assert _seen(W) == []
    lists["003.153"] = req_page(f"{ago(W, 50)} add approved h3921")
    lists["003.152"] = req_page(f"{ago(W, 50)} add approved h3922")  # read before: a new decision on it
    _read(W, fl)
    assert _seen(W) == [("Approved", "003.152", ("H3922",))]

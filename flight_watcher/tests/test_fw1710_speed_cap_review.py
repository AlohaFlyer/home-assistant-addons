"""1.7.10, the pickup speed cap's view page reads, review fixes. Synthetic pilots only ("JOHN DOE" 10001).
1. Ryan's log never quotes crew scheduling's comment of a view page, and the log mask knows the real comment
   (first name first, lower case as visible_text gives it), whole or cut short.
2. A pass reads the denials' view pages last, after the lists and the Tradeboard's My Requests pages, so on a pilot
   at his budget's pace the history reads never take the load kept for My Requests.
3. A page that is not the request's own view is a failed try, not a 'no pickup' verdict; each record carries the
   parser's version, and a verdict of another version is read once more.
4. The 'picked up by' pattern costs no time on a long run of letters with no number after it.
5. The trip a swap gives up is no cap on any path: the push, the history read and a captured view page agree."""
import collections
import logging
import os
import time
from datetime import datetime, timedelta

import pytest

import captures as CAPS
import submit as SUB
import test_fw1710_speed_cap as T
import test_pilot_secondary_share as P
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pilot_secondary_share import mk  # noqa: F401  (a pilot instance at his budget's pace)

ONE = T.REAL_IDS[:len(T.REAL_IDS) // 7]
NAMES = ["john doe", "mary-ann o'poe", "john q. doe jr", "sean o’doe", "doe, jane", "JOHN DOE", "Mary Ann Doe-Roe"]
LEAKS = ("john", "doe", "mary", "poe", "sean", "roe", "1000")


# ---------------------------------------------------------------- 1: the log
@pytest.mark.parametrize("name", NAMES)
def test_the_log_mask_knows_the_real_picked_up_by_comment(name):
    txt = ("add/swap/drop requests add h3607:17nov (f) time: 10/30 12:03 status: denied 10/30 12:59 cm: [no comments] "
           f"cs: h3607:17nov picked up by {name} (10003) note: denied requests stay listed")
    out = CAPS.mask_crew(txt, page=True)
    assert "h3607:17nov picked up by" in out and "note: denied requests stay listed" in out  # the rest still reads
    for n in range(40, len(txt) + 1):  # a line cut anywhere (the name or the number cut short too)
        low = CAPS.mask_crew(txt[:n], page=True).lower()
        assert not any(x in low for x in LEAKS), (n, low[-50:])


def test_the_log_mask_is_fast_on_a_long_comment():
    for txt in ("picked up by john " + "a-" * 5000 + " x", "picked up by " + "ab " * 3000, "picked up by " + "a" * 9000):
        t0 = time.time()
        CAPS.mask_crew(txt, page=True)
        assert time.time() - t0 < 1


@pytest.mark.parametrize("name", ["JOHN DOE", "MARY-ANN O'POE", "JOHN Q. DOE JR"])
def test_a_first_view_page_capture_and_a_pushed_denial_log_no_picker(W, tmp_path, monkeypatch, caplog, name):  # noqa: F811
    """A new bid month's first view page capture logs the page text, and a denial that is news logs its detail:
    neither line carries the picker's name or number, in the real comment's format."""
    T._seed(W)
    filed = datetime.now(W.HST) - timedelta(minutes=20)
    W.S["ot_req_init"] = True
    page = T._view("H3607:17NOV", f"H3607:17NOV picked up by {name} (10001)")
    fetched, read = T._watch(W, monkeypatch, tmp_path, body=f"open time requests {filed:%m/%d %H:%M} add denied",
                             ids=ONE, views={"AAAA0:BBBB0": page})
    W.S["req_view_captured"] = {}  # every new folder (BCID) starts so
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert "request view AAAA0:BBBB0 captured; text:" in caplog.text and "request Add Denied" in caplog.text
    assert "status: denied" in caplog.text and "cs: (" in caplog.text  # the layout still reads; the comment is a size
    low = caplog.text.lower()
    for leak in LEAKS + tuple(w for w in name.lower().replace(".", "").split() if len(w) > 1):
        assert leak not in low, leak
    assert os.path.exists(tmp_path / "cap" / "otrequest_view_152.html")  # the private capture holds the page
    assert list(T._pk(W.DB)["req_caps"]) == ["10001"]  # and the cap still reads the comment


def test_the_comment_is_cut_from_a_quoted_view_page(W):  # noqa: F811
    assert W._no_cs("status: denied cm: [no comments] cs: h3607:17nov picked up by john doe (10001) note: x") == \
        "status: denied cm: [no comments] cs: (41 chars) note: x"
    assert W._no_cs("cs: awarded to john doe (10001)") == "cs: (27 chars)" and W._no_cs("no comment here") == "no comment here"


# ---------------------------------------------------------------- 2: the budget
def test_the_view_pages_are_read_after_the_lists_and_my_requests(W, tmp_path, monkeypatch):  # noqa: F811
    T._seed(W)
    fetched, read = T._watch(W, monkeypatch, tmp_path, body=T.REAL, ids=T.REAL_IDS, views=T.REAL_VIEWS)
    read()
    kinds = ["view" if "ShowRequest" in u else "my" if "TB_MyRequests" in u else "list" for u in fetched]
    assert kinds == ["list", "my", "view", "view"]
    assert T._pk(W.DB)["scored"] == 239  # the cap of this pass's view pages is applied in this pass


N = 15
D_LIST = "open time requests " + " ".join(f"10/{10 + i} 12:{i:02d} add denied" for i in range(N))
D_IDS = "".join(f'<a href="x?ShowRequest=1&amp;TimeStamp=AAAA{i:02d}:BBBB{i:02d}">v</a>'
                f'<a href="x?QuickDelete=1&amp;TimeStamp=AAAA{i:02d}:BBBB{i:02d}">d</a>' for i in range(N))


@pytest.mark.parametrize("months", [1, 2])
def test_a_pilot_at_his_budget_keeps_his_my_requests_reads(mk, monkeypatch, caplog, months):  # noqa: F811
    """Four hours of a pilot's Watcher at his budget's pace with 15 denied adds on his list: My Requests is read for
    every watched month every hour (it was left out every hour while the view pages were read before it), the view
    pages use only what is left, and the budget, the pace and the read-only rule hold."""
    W = mk("pilot2")  # noqa: N806
    assert W.REQ_CAP_VIEWS_PER_READ == 2
    base = P._answer

    def answer(W_, slot):  # noqa: N803
        inner = base(W_, slot)

        def ans(u):
            low = u.lower()
            if "mobileotrequest" in low:
                assert "quickdelete" not in low
                return T._view("H3607:17NOV", "Rest short on 21NOV") if "showrequest" in low else \
                    f"<html><body>{D_LIST}{D_IDS}</body></html>"
            return inner(u)
        return ans
    monkeypatch.setattr(P, "_answer", answer)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        fl, _ran, _checks, t0 = P._run(W, monkeypatch, months, hours=4)

    def per_hour(pred):
        return [sum(1 for t, u in fl.loads if pred(u.lower()) and t0 + h * 3600 <= t < t0 + (h + 1) * 3600)
                for h in range(4)]
    assert per_hour(lambda u: "tb_myrequests" in u) == [months] * 4
    assert per_hour(lambda u: "mobileotrequest" in u and "showrequest" not in u) == [months] * 4
    assert not [r for r in caplog.records if r.getMessage().startswith("trade requests skipped")]
    views = [(t, u) for t, u in fl.loads if "ShowRequest" in u]
    assert not [k for k, c in collections.Counter(u for _, u in views).items() if c > 1]  # each page once
    assert all(b - a >= 1.5 for (a, _), (b, _) in zip(views, views[1:]))
    assert P._worst_hour([t for t, _ in fl.loads]) <= P.GT.PILOT_BUDGET_H


# ---------------------------------------------------------------- 3: what counts as a read
def test_a_page_that_is_not_the_requests_view_is_a_failed_try(W, tmp_path, monkeypatch):  # noqa: F811
    T._seed(W)
    views = {"AAAA0:BBBB0": "<html><body>Please wait while your request is processed</body></html>"}
    fetched, read = T._watch(W, monkeypatch, tmp_path, body="open time requests 10/30 12:03 add denied", ids=ONE,
                             views=views)
    read()
    assert W.S["req_cap_views"] == {"003.152|AAAA0:BBBB0": {"reason": None, "ok": False, "tries": 1, "v": W.REQ_CAP_VIEW_V}}
    views["AAAA0:BBBB0"] = T._view("H3607:17NOV", "H3607:17NOV picked up by JOHN DOE (10001)")
    for _ in range(3):
        read()
    assert T._ids(fetched) == ["AAAA0:BBBB0"] * 2 and T._pk(W.DB)["scored"] == 239  # read again, capped, then left alone
    assert SUB.is_view_page(SUB.parse_request_view("add h3607:17nov (f) time: 10/30 12:03 status: denied cs: rest short"))
    assert not SUB.is_view_page(SUB.parse_request_view("please wait")) and not SUB.is_view_page({})


def test_an_odd_page_read_for_a_push_is_a_failed_try_too(W, tmp_path, monkeypatch):  # noqa: F811
    T._seed(W)
    filed = datetime.now(W.HST) - timedelta(minutes=20)
    W.S["ot_req_init"] = True
    views = {"AAAA0:BBBB0": "<html><body>Please wait while your request is processed</body></html>"}
    fetched, read = T._watch(W, monkeypatch, tmp_path, body=f"open time requests {filed:%m/%d %H:%M} add denied",
                             ids=ONE, views=views)
    read()
    assert T._ids(fetched) == ["AAAA0:BBBB0"]  # the push's read, not loaded again in the same pass
    assert W.S["req_cap_views"]["003.152|AAAA0:BBBB0"] == {"reason": None, "ok": False, "tries": 1, "v": W.REQ_CAP_VIEW_V}
    views["AAAA0:BBBB0"] = T._view("H3607:17NOV", "H3607:17NOV picked up by JOHN DOE (10001)")
    read()
    read()
    assert T._ids(fetched) == ["AAAA0:BBBB0"] * 2 and list(T._pk(W.DB)["req_caps"]) == ["10001"]


def test_a_no_pickup_verdict_of_another_parser_version_is_read_once_more(W, tmp_path, monkeypatch):  # noqa: F811
    T._seed(W)
    views = dict(T.REAL_VIEWS)
    fetched, read = T._watch(W, monkeypatch, tmp_path, body=T.REAL, ids=T.REAL_IDS, views=views)
    for _ in range(4):
        read()
    assert len(T._ids(fetched)) == 5 and all(v["v"] == W.REQ_CAP_VIEW_V for v in W.S["req_cap_views"].values())
    # a later parser reads what this one missed: the 'no pickup' verdicts (AAAA0, AAAA6) are read again, once; a
    # reason on file (AAAA1, AAAA2, AAAA4) is kept and never loaded again
    monkeypatch.setattr(W, "REQ_CAP_VIEW_V", W.REQ_CAP_VIEW_V + 1)
    del fetched[:]
    for _ in range(4):
        read()
    assert T._ids(fetched) == ["AAAA0:BBBB0", "AAAA6:BBBB6"]
    assert all(v["v"] == W.REQ_CAP_VIEW_V for v in W.S["req_cap_views"].values())
    assert W.S["req_cap_views"]["003.152|AAAA1:BBBB1"]["reason"] == {"trip": "H3607", "day": "17NOV", "emp": "10001"}
    # a record with no version (kept by an earlier build) is read again too
    W.S["req_cap_views"]["003.152|AAAA0:BBBB0"] = {"reason": None, "ok": True, "tries": 1}
    del fetched[:]
    read()
    read()
    assert T._ids(fetched) == ["AAAA0:BBBB0"]


# ---------------------------------------------------------------- 4: the pattern's cost
@pytest.mark.parametrize("text", [
    "cs: h3677:13nov picked up by john " + "a" * 60 + " x",
    "cs: h3677:13nov picked up by john " + "a" * 5000 + " x",
    "cs: h3677:13nov picked up by another crewmember-before-your-request-was-processed.by.crew.scheduling",
    "cs: h3677:13nov picked up by reserve international-reserve-crewmember-honolulu-domicile (r)",
    "cs: h3677:13nov picked up by " + "ab " * 4000,
    "cs: h3677:13nov picked up by " + "a.b-c'" * 2000 + " (x)",
    ("cs: h3677:13nov picked up by " + "a" * 40 + " ") * 300,
])
def test_a_long_run_after_picked_up_by_costs_no_time(text):
    t0 = time.time()
    assert SUB.picked_up(text) is None
    assert SUB.row_cap({"status": "Denied", "reason": text}) is None
    assert time.time() - t0 < 1  # was 43 s for 60 letters, hours for more


def test_the_pickup_is_still_read_after_a_comment_that_is_none():
    assert SUB.picked_up("cs: h3677:13nov picked up by a reserve. h3678:14nov picked up by JOHN DOE (10001)") == {
        "trip": "H3678", "day": "14NOV", "name": "John Doe", "emp": "10001"}
    assert SUB.picked_up("H3677:13NOV picked up by " + "X" * 31 + " (10001)")["emp"] == "10001"  # a 31-letter word
    assert SUB.picked_up("H3677:13NOV picked up by " + "X" * 32 + " (10001)") is None
    assert SUB.picked_up("H3677:13NOV picked up by JOHNDOE(10001)")["name"] == "Johndoe"
    assert SUB.picked_up("H3677:13NOV picked up by JOHN,DOE , (10001)")["name"] == "John,Doe"


# ---------------------------------------------------------------- 5: the trip a swap gives up
SWAP = "H3911:21NOV (F) For H3609:19NOV"
GIVEN = "H3911:21NOV picked up by JOHN DOE (10001)"  # names the trip the swap gives up
ASKED = "H3609:19NOV picked up by JOHN DOE (10001)"  # names the trip the swap asked for


def test_one_rule_for_the_trip_a_swap_gives_up():
    for cs, want in ((GIVEN, None), (ASKED, {"trip": "H3609", "day": "19NOV", "emp": "10001"})):
        got = SUB.parse_request_view(W_text(cs))
        assert SUB.view_cap(got) == want
        assert SUB.row_cap({"status": "Denied", **got}) == want  # a row the push filled from its view page
    assert SUB.view_cap({}) is None and SUB.view_cap(None) is None
    assert SUB.gives_up({"trip": "H3911", "day": "21NOV"}, [{"trip": "H3911", "day": "", "side": "drop"}])
    assert not SUB.gives_up({"trip": "H3911", "day": "21NOV"}, [{"trip": "H3911", "day": "22NOV", "side": "drop"}])
    assert not SUB.gives_up({"trip": "H3911", "day": "21NOV"}, None)


def W_text(cs):  # noqa: N802
    import pot
    return pot.visible_text(T._view(SWAP, cs, kind="Swap"))


def _seed_3911(W):  # noqa: N803
    key = "H3911|21Nov"
    W.DB.add_find(key, "2026-11", {"pairing": "H3911", "start": "21Nov", "dates": "21Nov-24Nov", "open_seats": "FO",
                                   "layover": "LAX"}, T.FIRST, gone=T.GONE)
    W.DB.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (T.LAST, key))
    W.DB.set_pickup(key, {"status": "filled", "by": f"FO {T.JANE}", "ca": "", "known": True, "pickers": ["10001"]})
    W.DB.score_pickup(key)
    return key


@pytest.mark.parametrize("path", ["history", "push", "capture"])
def test_the_given_up_trip_is_no_cap_whichever_path_reads_the_page(W, tmp_path, monkeypatch, path):  # noqa: F811
    key = _seed_3911(W)
    page = T._view(SWAP, GIVEN, kind="Swap")
    filed = datetime.now(W.HST) - timedelta(minutes=20)
    body = "open time requests 10/30 12:03 swap denied"
    views = {"AAAA0:BBBB0": page}
    if path == "push":
        W.S["ot_req_init"] = True
        body = f"open time requests {filed:%m/%d %H:%M} swap denied"
    if path == "capture":
        os.makedirs(tmp_path / "cap", exist_ok=True)
        (tmp_path / "cap" / "otrequest_view_152.html").write_text(page, encoding="utf-8")
        body, views = "open time requests", {}
    fetched, read = T._watch(W, monkeypatch, tmp_path, body=body, ids=ONE if path != "capture" else "", views=views)
    read()
    read()
    if path == "capture":
        assert W.req_cap_captures() == []
    else:
        assert T._ids(fetched) == ["AAAA0:BBBB0"]
        assert W.S["req_cap_views"]["003.152|AAAA0:BBBB0"] == {"reason": None, "ok": True, "tries": 1, "v": W.REQ_CAP_VIEW_V}
        assert "pu" not in W.S["ot_req_rows"]["003.152"][0]
    if path == "push":
        assert [p["status"] for t, p in W.SENT if t == "event/request_decided"] == ["Denied"]
    assert "req_caps" not in T._pk(W.DB, key) and T._pk(W.DB, key)["scored"] == 600


def test_a_captured_view_page_of_the_asked_trip_still_caps(W, tmp_path, monkeypatch):  # noqa: F811
    T._seed(W, "H3609|19Nov")
    os.makedirs(tmp_path / "cap", exist_ok=True)
    (tmp_path / "cap" / "otrequest_view_152.html").write_text(
        T._view(SWAP, ASKED, kind="Swap", at="10/30 12:04"), encoding="utf-8")
    _fetched, read = T._watch(W, monkeypatch, tmp_path, body="open time requests", ids="")
    read()
    assert T._pk(W.DB, "H3609|19Nov")["req_caps"] == {"10001": "2026-10-30T12:04-10:00"}

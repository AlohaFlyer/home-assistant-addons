"""1.7.1 review fixes in the Watcher (the bid calendar's are in test_bidcal.py, the cards' 16 px fields in
test_fw171_cards.py, Remove CrewTrac login in test_fw171_core.py). Synthetic pages and made-up names only ("Doe, Jane"
10001); FLICA and CrewTrac are never reached.

- A pilot's Tradeboard read whose post details his FLICA budget leaves out (GateSkip) still saves its baseline, reads
  every bid month and publishes the board, so a post goes out once on event/new_pairing, never again on the next read;
  a new post costs one detail load, not two.
- Scan CrewTrac now from the portal answers ok false with the reason when it would start no scan.
"""
import json
import time


import charter as CH
from test_fw171_core import _press
from test_portal_spool import demo  # noqa: F401
from test_release_a_flica import mk, real_fl  # noqa: F401


# ---------------------------------------------------------------- 1. the Tradeboard read and a pilot's budget
def _tb_list(pairings):
    """Tradeboard All Requests with one 'Pickup Trip' post (a Drop) per pairing, in FLICA's JS layout (synthetic)."""
    rows = "".join(
        f'r[{i}]=new A({29600001 + i},0,1,{100001 + i},D,"{p}","Nov 25, 2026","25NOV","20261125","true",S,'
        f'"5550100100","JANE","DOE","",false,"Oct 31, 2026 12:09:41 HA",S,0,1,"12:45","3","17:35","17:35","KIX",'
        f'"13:45","09:20","HNL","332","FO","(10022)","LDD","","","",1,"_",1,"",0,0,"20261031120941","","AT","",0,0)\n'
        for i, p in enumerate(pairings))
    return "<html><script> var D='Drop' var S='&nbsp;'\n" + rows + "</script>Tradeboard All Requests</html>"


def _tb_answer(pairings):
    """pairings: the posts of bid number 152, or {bid number: posts}."""
    by_num = pairings if isinstance(pairings, dict) else {"152": pairings}

    def ans(u):
        low = u.lower()
        num = low.split("bcid=001.")[1][:3] if "bcid=001." in low else ""
        if "mobilepairing" in low:
            pid = low.split("pid=")[1][:5].upper()
            return (f"<html><body>Pairing {pid}:25NOV Check In: 07:00 blk : 1218 tafb : 2609 pay : 1218 "
                    "Crew: CA 10001 DOE, JANE FO Open</body></html>")
        if "tb_frame" in low:
            return f'<html><frameset><frame src="tb_otherrequests.cgi?BCID=001.{num}"></frameset></html>'
        if "tb_otherrequests" in low:
            return _tb_list(by_num.get(num) or [])
        return "<html><body>other</body></html>"
    return ans


def _pilot_at_the_floor(W):
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}  # one bid month: cap 12, shares 8, pool 4
    W.S["tb_baseline"] = {"tb2_152": []}  # an earlier read saw no post


def _tb_read(W, fl):
    W.RUN.update(check=True, aborted="", skipped=set())
    try:
        W.read_guard(W.tradeboard_check, fl, False, optional=True)
    finally:
        W.RUN["check"] = False


def _pushed(W):
    return [json.loads(p)["pairing"] for t, p in W.MQ.msgs if t == f"{W.T}/event/new_pairing"]


def _board(W):
    return W.MQ.last(f"{W.T}/tradeboard/state")


def test_a_pilots_tradeboard_post_goes_out_once_when_his_budget_leaves_its_details_out(mk):
    W = mk("pilot2")
    _pilot_at_the_floor(W)
    fl = real_fl(W, _tb_answer(["H9101", "H9102"]))
    pool = W.opt_cap() - sum(W.opt_shares().values())
    W.RUN["opt"] = [(W.CLOCK.t - 60, "own_trip_times")] * (pool - 1)  # other reads took all of the pool but one load
    _tb_read(W, fl)
    assert _pushed(W) == ["H9101", "H9102"]  # each new post once, the second without its details
    details = [u for _, u in fl.loads if "mobilepairing" in u.lower()]
    assert len(details) == 1 and "PID=H9101" in details[0]  # one detail GET for a new post, not two
    assert sorted(W.S["tb_baseline"]["tb2_152"]) == sorted(W.S["tb_details"]) + ["H9102|25Nov|29600002"]
    board = _board(W)
    assert board and board["count"] == 2  # the read was published, the left-out post too (screened, not cached)
    left = next(json.loads(p) for t, p in W.MQ.msgs if t == f"{W.T}/event/new_pairing" and "H9102" in p)
    assert left["fit"] and "far" in left and not left.get("detail_url")
    W.CLOCK.t += 3601  # an hour later the pool is free again
    _tb_read(W, fl)
    assert _pushed(W) == ["H9101", "H9102"]  # nothing pushed again
    assert sorted(W.S["tb_details"]) == ["H9101|25Nov|29600001", "H9102|25Nov|29600002"]  # its details read now
    assert [u for _, u in fl.loads if "mobilepairing" in u.lower()][1:] == [
        u for _, u in fl.loads[-1:] if "PID=H9102" in u]


def test_a_left_out_detail_never_costs_the_next_bid_months_tradeboard(mk):
    W = mk("pilot2")
    _pilot_at_the_floor(W)
    W.S["pot_urls"]["mobile_003.153"] = f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    W.S["tb_baseline"] = {"tb2_152": [], "tb2_153": []}
    fl = real_fl(W, _tb_answer({"152": ["H9101", "H9102"], "153": ["H9201"]}))
    pool = W.opt_cap() - sum(W.opt_shares().values())
    W.RUN["opt"] = [(W.CLOCK.t - 60, "own_trip_times")] * pool  # other reads took the whole pool
    _tb_read(W, fl)
    tb = [u for _, u in fl.loads if "tb_" in u.lower()]
    assert len(tb) == 4 and sum("001.153" in u for u in tb) == 2  # both bid months' frames and lists
    assert not [u for _, u in fl.loads if "mobilepairing" in u.lower()]  # the details wait, the frames do not
    assert _pushed(W) == ["H9101", "H9102", "H9201"]
    assert _board(W)["count"] == 3
    assert W.S["tb_baseline"] == {"tb2_152": ["H9101|25Nov|29600001", "H9102|25Nov|29600002"],
                                  "tb2_153": ["H9201|25Nov|29600001"]}


def test_the_admins_tradeboard_reads_every_new_posts_details_once(mk):
    A = mk("")
    A.S["pot_urls"] = {"mobile": A.MOBILE_POT}
    A.S["tb_baseline"] = {"tb2_152": []}
    fl = real_fl(A, _tb_answer(["H9101", "H9102"]))
    _tb_read(A, fl)
    assert _pushed(A) == ["H9101", "H9102"]
    details = [u for _, u in fl.loads if "mobilepairing" in u.lower()]
    assert len(details) == 2 and sorted(A.S["tb_details"]) == ["H9101|25Nov|29600001", "H9102|25Nov|29600002"]
    pushed = {json.loads(p)["pairing"]: json.loads(p) for t, p in A.MQ.msgs if t == f"{A.T}/event/new_pairing"}
    assert all(e["detail_url"] and e["captain"] for e in pushed.values())
    assert A.S["tb_details"]["H9101|25Nov|29600001"]["captain"] == pushed["H9101"]["captain"]
    A.CLOCK.t += 3601
    _tb_read(A, fl)
    assert len([u for _, u in fl.loads if "mobilepairing" in u.lower()]) == 2  # cached: not read again


# ---------------------------------------------------------------- Scan CrewTrac now from the portal
def test_an_ignored_scan_crewtrac_now_answers_ok_false_with_the_reason(demo):
    W = demo
    res, sent = _press(W, "charter_scan/press", 1)
    assert res == {"id": res["id"], "ok": False, "why": "ignored: no CrewTrac details saved"} and sent == []
    W.OPTS.update(ctweb_username="doej", ctweb_password="ct pw")  # made up
    res, sent = _press(W, "charter_scan/press", 2)
    assert res["ok"] and res["why"] == "" and sent == [f"{W.T}/charter_scan/press"]  # taken: republished as before
    W.CHARTER_WAKE.clear()
    assert W.charter_press() is True and W.CHARTER_WAKE.is_set()  # the republished press starts the scan
    res, sent = _press(W, "charter_scan/press", 3)  # tapped again: inside the press gap, no scan comes
    assert res == {"id": res["id"], "ok": False,
                   "why": f"ignored: the last pressed scan was under {CH.PRESS_GAP_S // 60} min ago"} and sent == []
    ct = W.DB.get("crewtrac")
    W.DB.put("crewtrac", dict(ct, press_at=time.time() - CH.PRESS_GAP_S - 1))
    W.CHARTER_BUSY.set()  # the scan of a timed turn is running
    try:
        res, sent = _press(W, "charter_scan/press", 4)
        assert res["why"] == "ignored: a scan is running" and not res["ok"] and sent == []
    finally:
        W.CHARTER_BUSY.clear()
    res, sent = _press(W, "charter_scan/press", 5)
    assert res["ok"] and sent == [f"{W.T}/charter_scan/press"]

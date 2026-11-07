"""1.4.6 (Ryan, Nov 6): "Have Hark file this CCR". The request file the Watcher writes for HOM and HOM's answers
(ccr.py contract), and the Watcher flow (recall/act file_request, ccr_poll). Temp folders and made-up data only;
nothing here files anything anywhere."""
import json
import os
import time

import pytest

import ccr as CCR

RID = "2026-11-10_H9001_recall"


def test_rid_rules():
    assert CCR.rid_for("2026-11-10|H9001|recall") == RID
    assert CCR.rid_for("2026-11-10|H3601A|o75") == "2026-11-10_H3601A_o75"
    assert CCR.rid_for("2026-11-10|H9001|recall", "james") == RID + "_james"
    for bad in ("2026-11-10|H9001|junior", "2026-11-10|h9001|recall", "2026-11-10|H9|recall", "2026-1-10|H9001|recall",
                "2026-11-10|H9001/../x|recall", "2026-11-10|H9001|recall|x", "", "2026-11-31|H9001|recall",
                "2026-13-01|H9001|recall"):
        assert CCR.rid_for(bad) is None, bad
    assert CCR.valid_rid(RID) and not CCR.valid_rid(RID + "\n") and not CCR.valid_rid("../" + RID)
    assert not CCR.valid_rid(RID + "_James") and not CCR.valid_rid(RID + "_" + "a" * 21) and not CCR.valid_rid(None)


def _rec(**k):
    r = {"v": 1, "rid": RID, "id": "2026-11-10|H9001|recall", "pilot": "ryan", "date": "2026-11-10", "pairing": "H9001",
         "kind": "recall", "seat": "FO", "narrative": "made-up narrative", "approved_at": "2026-11-10T20:00:00+00:00",
         "requested_at": "2026-11-10T21:00:00+00:00"}
    r.update(k)
    return r


def test_write_request_is_atomic_and_refuses_symlinks_and_size(tmp_path):
    d = tmp_path / "ccr_requests"
    p = CCR.write_request(str(d), _rec())
    assert json.loads(open(p).read()) == _rec() and os.listdir(d) == [f"{RID}.json"]  # no temp file left
    CCR.write_request(str(d), _rec(narrative="second"))  # rename over the old one
    assert json.loads(open(p).read())["narrative"] == "second"
    with pytest.raises(CCR.Refused):
        CCR.write_request(str(d), _rec(rid="../evil"))
    with pytest.raises(CCR.Refused):
        CCR.write_request(str(d), _rec(narrative="x" * (64 * 1024)))
    os.remove(p)
    (tmp_path / "elsewhere.json").write_text("{}")
    os.symlink(tmp_path / "elsewhere.json", p)
    with pytest.raises(CCR.Refused):
        CCR.write_request(str(d), _rec())
    assert (tmp_path / "elsewhere.json").read_text() == "{}"
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "linked")
    with pytest.raises(CCR.Refused):
        CCR.write_request(str(tmp_path / "linked"), _rec())
    assert os.listdir(real) == []


def _reply(d, kind, obj, raw=None):
    d.mkdir(exist_ok=True)
    (d / f"{RID}.{kind}.json").write_bytes(raw if raw is not None else json.dumps(obj).encode())


def test_read_reply_checks_the_contract(tmp_path):
    d = tmp_path / "ccr_requests"
    assert CCR.read_reply(str(d), RID, "done") is None  # no folder yet
    _reply(d, "done", {"v": 1, "rid": RID, "ccr": " 2026-0042\x07 ", "filed_at": "2026-11-11T01:02:03Z", "by": "Hark",
                       "note": "filed\x1b[31m ok‮" + "n" * 600})
    r = CCR.read_reply(str(d), RID, "done")
    assert (r["ccr"], r["filed_at"], r["by"]) == ("2026-0042", "2026-11-11T01:02:03+00:00", "hark")
    assert len(r["note"]) == 500 and "\x1b" not in r["note"] and "‮" not in r["note"]
    _reply(d, "task", {"v": 1, "rid": RID, "task_id": "T-7", "imported_at": "2026-11-10T21:05:00.123Z"})
    assert CCR.read_reply(str(d), RID, "task")["task_id"] == "T-7"
    _reply(d, "status", {"v": 1, "rid": RID, "status": "blocked", "reason": "hal.alpa.org login", "at": "2026-11-10T22:00:00+00:00"})
    assert CCR.read_reply(str(d), RID, "status")["status"] == "blocked"
    for bad in ({"v": 2, "rid": RID, "status": "blocked"}, {"v": 1, "rid": "2026-11-10_H9002_recall", "status": "blocked"},
                {"v": 1, "rid": RID, "status": "done"}, [1, 2]):
        _reply(d, "status", bad)
        with pytest.raises(CCR.Refused):
            CCR.read_reply(str(d), RID, "status")
    _reply(d, "status", None, raw=b"not json")
    with pytest.raises(CCR.Refused):
        CCR.read_reply(str(d), RID, "status")
    _reply(d, "status", None, raw=b" " * (64 * 1024 + 1))
    with pytest.raises(CCR.Refused):
        CCR.read_reply(str(d), RID, "status")
    _reply(d, "done", {"v": 1, "rid": RID, "ccr": ""})
    with pytest.raises(CCR.Refused):
        CCR.read_reply(str(d), RID, "done")
    os.remove(d / f"{RID}.done.json")
    (tmp_path / "secret.json").write_text(json.dumps({"v": 1, "rid": RID, "ccr": "1"}))
    os.symlink(tmp_path / "secret.json", d / f"{RID}.done.json")
    with pytest.raises(CCR.Refused):
        CCR.read_reply(str(d), RID, "done")
    with pytest.raises(CCR.Refused):
        CCR.read_reply(str(d), "../" + RID, "done")


def test_fresh_keeps_an_old_reply_from_closing_a_new_request():
    old = {"at": "2026-11-10T22:00:00+00:00", "mtime": "2026-11-10T22:00:01+00:00"}
    assert CCR.fresh(old, "2026-11-10T21:00:00+00:00", "at")
    assert not CCR.fresh(old, "2026-11-11T09:00:00+00:00", "at")
    assert CCR.fresh({"at": None, "mtime": "2026-11-11T09:00:30+00:00"}, "2026-11-11T09:00:00+00:00", "at")
    assert not CCR.fresh(None, "2026-11-11T09:00:00+00:00", "at")


# ---------------------------------------------------------------- the Watcher flow
DET = {"H9001": {"report": "08:00", "block": "10:00", "rel_days": 2,
                 "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                            {"d": 1, "dep": 2100, "arr": 2400, "stn": "HNL", "blk": 300}]}}
VID = "2026-11-10|H9001|recall"


def _w(tmp_path, monkeypatch, instance=""):
    import sys
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "INSTANCE", instance)
    monkeypatch.setattr(W, "CCR_DIR", str(tmp_path / "ccr_requests"))
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p, retain)))
    W.DB.put("pkg_details:2026-11", DET)
    for mk in ("2026-10", "2026-11", "2026-12"):
        W.DB.put(f"sched_versions:{mk}", [{"ver": f"{int(mk[5:])}.001", "n": 1, "at": "2026-10-20T00:00:00+00:00",
                                          "items": [], "days": [], "totals": {}, "trips": {}}])
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [{"date": "2026-11-10", "kind": "recall", "seat": "FO",
                                                             "pilot": "Doe, Jane", "sen": 900, "pairing": "H9001"}],
                             "me": {"sen": 500}}))
    return W, sent


def _act(W):
    return W.DB.get("recall_acts")[VID]


def _st(sent):
    st = [p for t, p, _ in sent if t == "recall"][-1]
    return st, {v["id"]: v for d in st["days"] for v in d["verdicts"]}


def _files(W):
    return sorted(os.listdir(W.CCR_DIR)) if os.path.isdir(W.CCR_DIR) else []


def test_file_request_needs_an_approved_narrative_and_writes_the_contract(tmp_path, monkeypatch):
    W, sent = _w(tmp_path, monkeypatch)
    st, vs = _st(sent)
    assert vs[VID]["verdict"] == "MISSED" and st["hark_files"] is True and st["alert"] == 1
    for status in ("new", "confirmed"):
        if status == "confirmed":
            W.recall_act(json.dumps({"id": VID, "action": "confirm"}))
        assert W.recall_file_request({"id": VID}) is False
        W.recall_act(json.dumps({"id": VID, "action": "file_request"}))
        assert _files(W) == [] and _act(W)["status"] == status
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "Approved made-up narrative."}))
    W.recall_act(json.dumps({"id": VID, "action": "file_request"}))
    assert _files(W) == ["2026-11-10_H9001_recall.json"]
    rec = json.load(open(os.path.join(W.CCR_DIR, "2026-11-10_H9001_recall.json")))
    assert set(rec) == {"v", "rid", "id", "pilot", "date", "pairing", "kind", "seat", "narrative", "approved_at", "requested_at"}
    assert (rec["v"], rec["rid"], rec["id"], rec["pilot"], rec["date"], rec["pairing"], rec["kind"], rec["seat"]) == (
        1, "2026-11-10_H9001_recall", VID, "ryan", "2026-11-10", "H9001", "recall", "FO")
    a = _act(W)
    assert rec["narrative"] == "Approved made-up narrative." == a["narrative"] and rec["approved_at"] == a["approved_at"]
    assert (a["status"], a["rid"], a["requested_at"]) == ("filing", rec["rid"], rec["requested_at"])
    ev = [(p, r) for t, p, r in sent if t == "event/recall_file_requested"]
    assert len(ev) == 1 and ev[0][1] is False and ev[0][0]["rid"] == rec["rid"]
    st, vs = _st(sent)
    assert vs[VID]["act"]["status"] == "filing" and st["open"] == 1 and st["alert"] == 1
    # while Hark has it: no re-approve, no second request (Withdraw / Not a miss / Mark filed: test_withdraw_*)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "changed"}))
    W.recall_act(json.dumps({"id": VID, "action": "confirm"}))
    W.recall_act(json.dumps({"id": VID, "action": "reopen"}))
    assert W.recall_file_request({"id": VID}) is False
    assert (_act(W)["status"], _act(W)["narrative"]) == ("filing", "Approved made-up narrative.")


def _hom(W, kind, obj, age=0):
    p = os.path.join(W.CCR_DIR, f"2026-11-10_H9001_recall.{kind}.json")
    with open(p, "w") as f:
        json.dump(obj, f)
    if age:
        os.utime(p, (time.time() - age, time.time() - age))


def _iso(age=0):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()


def _hark_alerts(sent):
    return [p for t, p, r in sent if t == "event/recall_hark_alert" and r is False]


def test_hom_answers_blocked_then_filed(tmp_path, monkeypatch):
    """1.4.6 review: HOM makes one task per rid, ever. After Hark parks the task the draft is 'blocked'; a second
    request under the same rid is refused (HOM would never answer it and the draft would sit in 'filing'). When HOM
    removes its status file because the task is open again, the draft is 'filing' again; Hark's done file files it."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    rid = "2026-11-10_H9001_recall"
    assert W.ccr_poll() is False  # nothing from HOM yet
    _hom(W, "task", {"v": 1, "rid": rid, "task_id": "t9", "imported_at": _iso()})
    _hom(W, "status", {"v": 1, "rid": rid, "status": "blocked", "reason": "hal.alpa.org <b>login</b>", "at": _iso()})
    assert W.ccr_poll() is True
    a = _act(W)
    assert (a["status"], a["hark_reason"], a["task_id"]) == ("blocked", "hal.alpa.org <b>login</b>", "t9")
    st, vs = _st(sent)
    assert vs[VID]["act"]["status"] == "blocked" and st["alert"] == 1
    assert W.ccr_poll() is False  # the same answer again changes nothing
    # an edit is kept for filing by hand, Hark's task stays what it was, and no second request goes out
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N2"}))
    assert (_act(W)["status"], _act(W)["narrative"]) == ("blocked", "N2")
    assert W.recall_file_request({"id": VID}) is False
    assert json.load(open(os.path.join(W.CCR_DIR, rid + ".json")))["narrative"] == "N1"
    assert "HOM task t9" in _act(W)["hark_note"] and _act(W)["hark_reason"] == "hal.alpa.org <b>login</b>"
    # Hark resumes: HOM removes the status file (the task is plainly open again)
    os.remove(os.path.join(W.CCR_DIR, rid + ".status.json"))
    assert W.ccr_poll() is True
    a = _act(W)
    assert a["status"] == "filing" and "hark_reason" not in a and a["task_id"] == "t9"
    _hom(W, "done", {"v": 1, "rid": rid, "ccr": "2026-0042", "filed_at": _iso(), "by": "hark", "note": "Filed on hal.alpa.org."})
    assert W.ccr_poll() is True
    a = _act(W)
    assert (a["status"], a["ccr"], a["filed_by"]) == ("filed", "2026-0042", "hark") and a["filed_at"]
    ev = [(p, r) for t, p, r in sent if t == "event/recall_ccr_filed"]
    assert len(ev) == 1 and ev[0][1] is False and ev[0][0]["ccr"] == "2026-0042"
    st, vs = _st(sent)
    assert st["open"] == 0 and st["alert"] == 0 and vs[VID]["act"]["ccr"] == "2026-0042"
    assert W.ccr_poll() is False and not _hark_alerts(sent)  # filed by Hark: nothing more to say
    # the Watcher never wrote HOM's files
    assert _files(W) == [rid + ".done.json", rid + ".json", rid + ".task.json"]


def test_a_rejected_request_without_a_task_can_be_sent_again(tmp_path, monkeypatch):
    """HOM rejected the request (blocked, no task file): HOM reads the request again each pass, so a second request
    under the same rid is allowed; HOM's old status file is older than it and is ignored."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    rid = "2026-11-10_H9001_recall"
    _hom(W, "status", {"v": 1, "rid": rid, "status": "blocked", "reason": "invalid request: narrative", "at": _iso()})
    W.ccr_poll()
    assert _act(W)["status"] == "blocked" and "task_id" not in _act(W)
    _hom(W, "status", {"v": 1, "rid": rid, "status": "blocked", "reason": "invalid request: narrative", "at": _iso(3600)}, age=3600)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N2"}))
    assert _act(W)["status"] == "approved" and rid + ".json" not in _files(W)  # the stale N1 request is taken back
    assert W.recall_file_request({"id": VID, "narrative": "N2"})
    assert json.load(open(os.path.join(W.CCR_DIR, rid + ".json")))["narrative"] == "N2"
    W.ccr_poll()
    assert _act(W)["status"] == "filing" and "hark_reason" not in _act(W)


def test_the_hark_request_carries_only_the_approved_narrative(tmp_path, monkeypatch):
    """Finding (card): the box held an edit Ryan had not approved. The card sends the box text with file_request and
    the Watcher refuses when it is not the approved narrative; nothing is written."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "Approved text."}))
    W.recall_act(json.dumps({"id": VID, "action": "file_request", "narrative": "Approved text. CORRECTED: pairing is H3609."}))
    assert _files(W) == [] and _act(W)["status"] == "approved" and "re-approve" in _act(W)["hark_note"]
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "Approved text. CORRECTED: pairing is H3609."}))
    assert "hark_note" not in _act(W)
    W.recall_act(json.dumps({"id": VID, "action": "file_request", "narrative": "Approved text. CORRECTED: pairing is H3609. "}))
    rec = json.load(open(os.path.join(W.CCR_DIR, "2026-11-10_H9001_recall.json")))
    assert rec["narrative"] == "Approved text. CORRECTED: pairing is H3609." and _act(W)["status"] == "filing"


def test_withdraw_before_hom_made_a_task_takes_the_request_back(tmp_path, monkeypatch):
    """No HOM task yet (HOM not live, or not run yet): Withdraw from Hark removes the Watcher's own request file, so
    HOM never imports it, and the draft is approved again with the Hark button back. If HOM made the task in the same
    moment anyway, its task file fires a Hark alert (late_task) once."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    rid = "2026-11-10_H9001_recall"
    W.recall_act(json.dumps({"id": VID, "action": "withdraw"}))
    a = _act(W)
    assert a["status"] == "approved" and a["withdrawn_at"] and _files(W) == []
    assert W.recall_file_request({"id": VID}) is True and _files(W) == [rid + ".json"]  # can be sent again
    W.recall_act(json.dumps({"id": VID, "action": "dismiss"}))  # Not a miss also takes it back first
    assert _act(W)["status"] == "dismissed" and _files(W) == []
    _hom(W, "task", {"v": 1, "rid": rid, "task_id": "t12", "imported_at": _iso()})  # HOM got it just before
    assert W.ccr_poll() is True
    al = _hark_alerts(sent)
    assert len(al) == 1 and al[0]["what"] == "late_task" and al[0]["task_id"] == "t12" and "t12" in _act(W)["hark_alert"]
    assert W.ccr_poll() is False and len(_hark_alerts(sent)) == 1


def test_withdraw_dismiss_and_mark_filed_with_a_hom_task_need_hom_cleared(tmp_path, monkeypatch):
    """With a HOM task, nothing from the Watcher reaches HOM, so Withdraw from Hark, Not a miss and Mark filed wait
    for Ryan to say he completed that task as skipped (hom_cleared). A Hark CCR number that comes in after a manual
    Mark filed with another number fires a duplicate alert, once; the same number just records who filed it."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    rid = "2026-11-10_H9001_recall"
    _hom(W, "task", {"v": 1, "rid": rid, "task_id": "t7", "imported_at": _iso()})
    for action in ("withdraw", "dismiss", "filed"):
        W.recall_act(json.dumps({"id": VID, "action": action, "ccr": "12345"}))
        a = _act(W)
        assert a["status"] == "filing" and "HOM task t7" in a["hark_note"] and "ccr" not in a, action
    assert _files(W) == [rid + ".json", rid + ".task.json"]  # the request stays; HOM already has it
    st, vs = _st(sent)
    assert "HOM task t7" in vs[VID]["act"]["hark_note"]
    W.recall_act(json.dumps({"id": VID, "action": "withdraw", "hom_cleared": True}))
    a = _act(W)
    assert (a["status"], a["task_id"]) == ("approved", "t7") and "hark_note" not in a
    assert W.recall_file_request({"id": VID}) is False and "HOM task t7" in _act(W)["hark_note"]  # never a 2nd request
    W.recall_act(json.dumps({"id": VID, "action": "filed", "ccr": "12345"}))  # approved: no Hark gate any more
    assert (_act(W)["status"], _act(W)["ccr"]) == ("filed", "12345")
    _hom(W, "status", {"v": 1, "rid": rid, "status": "cancelled", "reason": "skipped", "at": _iso()})
    assert W.ccr_poll() is False and _act(W)["status"] == "filed"  # HOM's answer to the skip: nothing to do
    _hom(W, "done", {"v": 1, "rid": rid, "ccr": "2026-0042", "filed_at": _iso(), "by": "hark", "note": ""})
    assert W.ccr_poll() is True
    al = _hark_alerts(sent)
    assert len(al) == 1 and al[0]["what"] == "duplicate" and "2026-0042" in al[0]["text"] and "12345" in al[0]["text"]
    assert (_act(W)["status"], _act(W)["ccr"], _act(W)["hark_ccr"]) == ("filed", "12345", "2026-0042")
    assert W.ccr_poll() is False and len(_hark_alerts(sent)) == 1
    # the same number Ryan typed: no alert, Hark recorded as the filer
    (tmp_path / "b").mkdir()
    W2, sent2 = _w(tmp_path / "b", monkeypatch)
    W2.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W2.recall_file_request({"id": VID})
    _hom(W2, "task", {"v": 1, "rid": rid, "task_id": "t8", "imported_at": _iso()})
    W2.recall_act(json.dumps({"id": VID, "action": "filed", "ccr": "2026 0043", "hom_cleared": True}))
    _hom(W2, "done", {"v": 1, "rid": rid, "ccr": "2026-0043", "filed_at": _iso(), "by": "hark", "note": ""})
    assert W2.ccr_poll() is True and not _hark_alerts(sent2) and _act(W2)["filed_by"] == "hark"


def test_a_draft_hark_still_has_that_is_superseded_alerts(tmp_path, monkeypatch):
    """A re-judge turns the row NO while Hark has the request: the draft is superseded (was filing) and
    event/recall_hark_alert says to complete HOM task t5 as skipped, once; the card shows it on the history row."""
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    _hom(W, "task", {"v": 1, "rid": "2026-11-10_H9001_recall", "task_id": "t5", "imported_at": _iso()})
    W.ccr_poll()
    W.recall_act(json.dumps({"me": {"sen": 950}}))  # #900 is senior now: NO
    a = _act(W)
    assert (a["status"], a["was"]) == ("superseded", "filing")
    al = _hark_alerts(sent)
    assert len(al) == 1 and al[0]["what"] == "superseded" and "t5" in al[0]["text"] and "skipped" in al[0]["text"]
    st, vs = _st(sent)
    assert vs[VID]["verdict"] == "NO" and "t5" in vs[VID]["act"]["hark_alert"] and vs[VID]["act"]["task_id"] == "t5"
    W.recall_act(json.dumps({"refresh": True}))
    assert len(_hark_alerts(sent)) == 1
    W.recall_act(json.dumps({"me": {"sen": 500}}))  # a miss again: back to filing, the warning goes
    assert _act(W)["status"] == "filing" and "hark_alert" not in _act(W)


def test_a_row_date_that_is_not_a_real_date_is_never_sent(tmp_path, monkeypatch):
    """2026-11-31 fits the rid pattern but is not a date: HOM ignores the name and would never answer."""
    assert CCR.rid_for("2026-11-31|H9001|recall") is None and CCR.rid_for("2026-02-29|H9001|recall") is None
    assert CCR.rid_for("2028-02-29|H9001|recall") == "2028-02-29_H9001_recall"
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_cmd(json.dumps({"date": "2026-11-30", "rows": [{"date": "2026-11-31", "kind": "recall", "seat": "FO",
                                                             "sen": 900, "pairing": "H9001"}]}))
    vid = "2026-11-31|H9001|recall"
    assert _st(sent)[1][vid]["verdict"] == "POSSIBLE"
    W.recall_act(json.dumps({"id": vid, "action": "confirm"}))
    W.recall_act(json.dumps({"id": vid, "action": "approve", "narrative": "N"}))
    assert W.recall_file_request({"id": vid}) is False and _files(W) == []
    assert W.DB.get("recall_acts")[vid]["status"] == "approved"


def test_cancelled_and_a_bad_reply(tmp_path, monkeypatch):
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W.recall_file_request({"id": VID})
    rid = "2026-11-10_H9001_recall"
    _hom(W, "done", {"v": 1, "rid": "2026-11-10_H9002_recall", "ccr": "1"})  # another request's answer in this name
    assert W.ccr_poll() is True and _act(W)["status"] == "filing" and "rid" in _act(W)["hark_bad"]
    os.remove(os.path.join(W.CCR_DIR, rid + ".done.json"))
    _hom(W, "status", {"v": 1, "rid": rid, "status": "cancelled", "reason": "Ryan filed it himself", "at": _iso()})
    W.ccr_poll()
    assert (_act(W)["status"], _act(W)["hark_reason"]) == ("cancelled", "Ryan filed it himself")
    W.recall_act(json.dumps({"id": VID, "action": "filed", "ccr": "2026-0050"}))
    assert (_act(W)["status"], _act(W)["ccr"]) == ("filed", "2026-0050")


def test_superseded_never_files_and_a_second_pilot_never_asks(tmp_path, monkeypatch):
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    W.recall_act(json.dumps({"me": {"sen": 950}}))  # #900 is senior now: NO, the draft is superseded
    assert _act(W)["status"] == "superseded"
    assert W.recall_file_request({"id": VID}) is False and _files(W) == []
    (tmp_path / "james").mkdir()
    W2, sent2 = _w(tmp_path / "james", monkeypatch, instance="james")
    W2.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    assert W2.recall_file_request({"id": VID}) is False and _files(W2) == []
    assert _st(sent2)[0]["hark_files"] is False


def test_a_symlink_at_the_request_name_is_refused(tmp_path, monkeypatch):
    W, sent = _w(tmp_path, monkeypatch)
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "N1"}))
    os.makedirs(W.CCR_DIR)
    (tmp_path / "target").write_text("keep")
    os.symlink(tmp_path / "target", os.path.join(W.CCR_DIR, "2026-11-10_H9001_recall.json"))
    assert W.recall_file_request({"id": VID}) is False
    a = _act(W)
    assert a["status"] == "approved" and "symlink" in a["hark_reason"] and (tmp_path / "target").read_text() == "keep"
    assert not [t for t, _, _ in sent if t == "event/recall_file_requested"]


def test_a_possible_row_that_turns_missed_pushes_once(tmp_path, monkeypatch):
    """The push (event/recall_miss, verdict MISSED) fires once per act: a POSSIBLE act pushes as MISSED the first time
    a list post finds it MISSED, never again; a Refresh never pushes."""
    W, sent = _w(tmp_path, monkeypatch)
    W.DB.put("recall_acts", {})
    W.DB.put("pkg_details:2026-11", {})  # pairing times unknown: POSSIBLE
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [{"date": "2026-11-10", "kind": "recall", "seat": "FO", "sen": 900, "pairing": "H9001"}]}))
    ev = [p for t, p, _ in sent if t == "event/recall_miss"]
    assert ev[-1]["verdict"] == "POSSIBLE"
    W.DB.put("pkg_details:2026-11", DET)
    sent.clear()
    W.recall_act(json.dumps({"refresh": True}))
    assert _st(sent)[1][VID]["verdict"] == "MISSED" and not [t for t, _, _ in sent if t == "event/recall_miss"]
    W.recall_cmd(json.dumps({"date": "2026-11-11", "rows": []}))
    assert [p["verdict"] for t, p, _ in sent if t == "event/recall_miss"] == ["MISSED"]
    W.recall_cmd(json.dumps({"date": "2026-11-12", "rows": []}))
    assert len([1 for t, _, _ in sent if t == "event/recall_miss"]) == 1

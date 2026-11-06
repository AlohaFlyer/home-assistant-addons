import recall as RC

ME = {"sen": 500, "seat": "FO", "o75": True}
DET = {"H9001": {"report": "08:00", "block": "10:00", "rel_days": 2,
                 "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                            {"d": 1, "dep": 2100, "arr": 2400, "stn": "HNL", "blk": 300}]}}


def _row(**k):
    r = {"date": "2026-11-10", "kind": "recall", "seat": "FO", "pilot": "Test Pilot", "sen": 900, "pairing": "H9001"}
    r.update(k)
    return r


def test_junior_award_on_open_legal_day_is_missed():
    v = RC.evaluate(_row(), ME, [], {}, [], DET)
    assert v["verdict"] == "MISSED" and v["end"] == "2026-11-11" and v["last_arr"] == "16:00"
    assert any("22.G.2.e" in r for r in v["refs"])
    assert "junior to me" in RC.narrative(v, ME)


def test_senior_award_blocked_day_and_junior_manning_are_not_missed():
    assert RC.evaluate(_row(sen=100), ME, [], {}, [], DET)["verdict"] == "NO"
    assert RC.evaluate(_row(), ME, [], {}, ["2026-11-11"], DET)["verdict"] == "NO"
    assert RC.evaluate(_row(kind="junior"), ME, [], {}, [], DET)["verdict"] == "NO"
    assert RC.evaluate(_row(seat="CA"), ME, [], {}, [], DET)["verdict"] == "NO"
    assert RC.evaluate(_row(kind="o75"), {**ME, "o75": False}, [], {}, [], DET)["verdict"] == "NO"


def test_trip_or_vacation_in_the_way_is_not_missed():
    trip = [{"trip": "H1234", "start": "2026-11-11", "end": "2026-11-13"}]
    v = RC.evaluate(_row(), ME, trip, {}, [], DET)
    assert v["verdict"] == "NO" and "22.G.2.f" in v["why"][-1]
    vac = [{"trip": "VAC", "start": "2026-11-09", "end": "2026-11-10"}]
    assert "22.G.2.g" in RC.evaluate(_row(), ME, vac, {}, [], DET)["why"][-1]


def test_rest_too_short_is_not_legal():
    # own trip releases 2026-11-09 23:00 -> 9 h before an 08:00 report: under FAR 117.25(e) 10 h
    trip = [{"trip": "H1234", "start": "2026-11-08", "end": "2026-11-09"}]
    own = {"H1234|2026-11-08": {"report": "09:00", "last_arr": "22:45", "blk": "10:00"}}
    v = RC.evaluate(_row(), ME, trip, own, [], DET)
    assert v["verdict"] == "NO" and "not legal" in v["why"][-1]


def test_unknown_times_are_possible():
    v = RC.evaluate(_row(pairing="H9999"), ME, [], {}, [], DET)
    assert v["verdict"] == "POSSIBLE"


def test_watcher_recall_flow(tmp_path, monkeypatch):
    import json, sys
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    W.DB.put("pkg_details:2026-11", DET)
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()], "me": {"sen": 500}}))
    ev = [p for t, p in sent if t == "event/recall_miss"]
    assert ev and ev[0]["verdict"] == "MISSED"
    st = [p for t, p in sent if t == "recall"][-1]
    assert st["open"] == 1 and st["alert"] == 1 and st["days"][0]["verdicts"][0]["act"]["status"] == "new"
    W.recall_act(json.dumps({"id": ev[0]["id"], "action": "approve", "narrative": "edited text"}))
    assert W.DB.get("recall_acts")[ev[0]["id"]] ["narrative"] == "edited text"
    assert any(t == "event/recall_approved" for t, _ in sent)
    W.recall_act(json.dumps({"id": ev[0]["id"], "action": "filed"}))
    assert [p for t, p in sent if t == "recall"][-1]["open"] == 0
    # same list again: no second push
    n = len([1 for t, _ in sent if t == "event/recall_miss"])
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()]}))
    assert len([1 for t, _ in sent if t == "event/recall_miss"]) == n


def _recall_w(tmp_path, monkeypatch):
    import json, sys
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    W.DB.put("pkg_details:2026-11", DET)
    return W, sent


def _last(sent):
    st = [p for t, p in sent if t == "recall"][-1]
    return st, {v["id"]: v for d in st["days"] for v in d["verdicts"]}


def test_recall_draft_superseded_when_row_becomes_no_and_back(tmp_path, monkeypatch):
    """FW-0012: a CCR draft is open only while its row is MISSED / POSSIBLE. When the row turns NO (here Ryan's seniority
    number is corrected so the award went senior to him) the act is superseded, not counted, shown without its narrative,
    and kept; when the row is a miss again it comes back as it was (edited narrative, approved) with no second push."""
    import json
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()], "me": {"sen": 500}}))
    vid = "2026-11-10|H9001|recall"
    W.recall_act(json.dumps({"id": vid, "action": "approve", "narrative": "edited text"}))
    st, vs = _last(sent)
    assert (st["open"], st["alert"], vs[vid]["act"]["status"]) == (1, 1, "approved")
    W.recall_act(json.dumps({"me": {"sen": 950}}))  # #900 is now senior to Ryan: NO
    st, vs = _last(sent)
    assert vs[vid]["verdict"] == "NO" and (st["open"], st["alert"]) == (0, 0)
    a = W.DB.get("recall_acts")[vid]
    assert (a["status"], a["was"], a["narrative"]) == ("superseded", "approved", "edited text") and "senior" in a["superseded_why"]
    assert vs[vid]["act"]["status"] == "superseded" and "narrative" not in vs[vid]["act"]
    # a late tap on the old push changes nothing
    W.recall_act(json.dumps({"id": vid, "action": "confirm"}))
    assert W.DB.get("recall_acts")[vid]["status"] == "superseded"
    pushes = len([1 for t, _ in sent if t == "event/recall_miss"])
    W.recall_act(json.dumps({"me": {"sen": 500}}))  # a miss again
    st, vs = _last(sent)
    a = W.DB.get("recall_acts")[vid]
    assert (a["status"], a["narrative"]) == ("approved", "edited text") and "was" not in a and "superseded_why" not in a
    assert (st["open"], st["alert"], vs[vid]["act"]["status"]) == (1, 1, "approved")
    assert len([1 for t, _ in sent if t == "event/recall_miss"]) == pushes


def test_recall_draft_superseded_when_row_leaves_a_corrected_list(tmp_path, monkeypatch):
    """A corrected list for the day no longer has the row: its draft is superseded. Filed and dismissed acts keep what
    they were in 'was'. An act from a day older than the lists kept is history and left as it stands."""
    import json
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.DB.put("recall_acts", {"2026-06-01|H8000|recall": {"status": "new", "narrative": "old", "at": "2026-06-01T00:00:00"}})
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row(), _row(pairing="H9999")], "me": {"sen": 500}}))
    gone = "2026-11-10|H9999|recall"
    W.recall_act(json.dumps({"id": gone, "action": "filed", "ccr": "12345"}))
    assert _last(sent)[0]["open"] == 1  # filed: not open
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()]}))
    acts = W.DB.get("recall_acts")
    assert (acts[gone]["status"], acts[gone]["was"], acts[gone]["ccr"]) == ("superseded", "filed", "12345")
    assert acts[gone]["superseded_why"] == "no longer on the recall list"
    assert acts["2026-11-10|H9001|recall"]["status"] == "new"
    assert acts["2026-06-01|H8000|recall"] == {"status": "new", "narrative": "old", "at": "2026-06-01T00:00:00"}
    assert _last(sent)[0]["open"] == 1


def test_publish_recall_counts_only_live_verdicts(tmp_path, monkeypatch):
    """Days stored before FW-0012 can carry an open act on a NO row: publish counts it only while MISSED / POSSIBLE."""
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.DB.put("recall_days", {"2026-11-10": {"date": "2026-11-10", "file": "ok", "rows": [], "verdicts": [
        {"id": "a", "verdict": "NO", "act": {"status": "confirmed"}},
        {"id": "b", "verdict": "POSSIBLE", "act": {"status": "new"}},
        {"id": "c", "verdict": "MISSED", "act": {"status": "approved"}},
        {"id": "d", "verdict": "MISSED", "act": {"status": "superseded"}}]}})
    W.publish_recall()
    st = _last(sent)[0]
    assert (st["open"], st["alert"]) == (2, 1)


def test_finds_month_files(tmp_path, monkeypatch):
    import json, sys
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
    now = W.local_now()
    W.DB.db.execute("INSERT INTO finds(key,pairing,month,row,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                    ("k1", "H1", "m", '{"pairing":"H1"}', W.now_iso(), W.now_iso()))
    W.write_finds_months()
    f = tmp_path / "www" / f"finds_{now:%Y-%m}_{W.www_key()}.json"  # FW-0010: keyed name
    assert json.loads(f.read_text())["finds"][0]["pairing"] == "H1"
    assert not (tmp_path / "www" / f"finds_{now:%Y-%m}.json").exists()

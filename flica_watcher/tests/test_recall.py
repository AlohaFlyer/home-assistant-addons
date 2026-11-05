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


def test_trip_or_vacation_in_the_way_is_possible_not_missed():
    trip = [{"trip": "H1234", "start": "2026-11-11", "end": "2026-11-13"}]
    v = RC.evaluate(_row(), ME, trip, {}, [], DET)
    assert v["verdict"] == "POSSIBLE" and "22.G.2.f" in v["why"][-1]
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
    monkeypatch.setenv("FLICA_DATA", str(tmp_path))
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

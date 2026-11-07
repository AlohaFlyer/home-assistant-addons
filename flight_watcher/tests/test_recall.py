import recall as RC

ME = {"sen": 500, "seat": "FO", "o75": True}
DET = {"H9001": {"report": "08:00", "block": "10:00", "rel_days": 2,
                 "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                            {"d": 1, "dep": 2100, "arr": 2400, "stn": "HNL", "blk": 300}]}}


def _row(**k):
    r = {"date": "2026-11-10", "kind": "recall", "seat": "FO", "pilot": "Test Pilot", "sen": 900, "pairing": "H9001"}
    r.update(k)
    return r


def _line(W, items=(), trips=None, at="2026-10-20T00:00:00+00:00", months=("2026-10", "2026-11", "2026-12")):
    """1.4.6: a schedule version on file for each month, seen at `at`, so a list day after it is judged on that line."""
    for mk in months:
        its = [i for i in items if i["start"][:7] == mk]
        W.DB.put(f"sched_versions:{mk}", [{"ver": f"{int(mk[5:])}.001", "n": 1, "at": at, "items": its, "days": [],
                                          "totals": {}, "trips": {k: v for k, v in (trips or {}).items() if k.split("|")[1][:7] == mk}}])


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
    assert RC.evaluate(_row(kind="o75"), {**ME, "o75_months": {"2026-11": False}}, [], {}, [], DET)["verdict"] == "NO"


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
    _line(W)
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
    _line(W)
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


def test_refresh_rejudges_against_the_current_line_without_a_push(tmp_path, monkeypatch):
    """Ryan (Nov 6): the tab's Refresh (recall/act {refresh}) re-judges every list on file now, publishes 'checked'
    and 'received', and never pushes, even when the re-check finds a miss the last one did not."""
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
    _line(W)
    W.S["blocked_days"] = ["2026-11-11"]  # blocked: not a miss when the list comes in
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()], "me": {"sen": 500}}))
    st = [p for t, p in sent if t == "recall"][-1]
    assert st["days"][0]["verdicts"][0]["verdict"] == "NO" and st["received"] and st["checked"]
    W.S["blocked_days"] = []  # the block was lifted: now a miss
    sent.clear()
    W.recall_act(json.dumps({"refresh": True}))
    st = [p for t, p in sent if t == "recall"][-1]
    assert st["days"][0]["verdicts"][0]["verdict"] == "MISSED" and st["open"] == 1
    assert not [t for t, _ in sent if t.startswith("event/")]
    W.recall_act("not json")  # a bad message is logged, never raised


# ---------------------------------------------------------------- 1.4.6 review (Nov 7)
def test_each_list_day_reads_its_own_bid_period_package(tmp_path, monkeypatch):
    """Pairing ids repeat across bid periods: October's H3601 is 4 days, November's is 1 day. With lists for Oct 28 and
    Nov 10 on file, the Oct 28 row uses October's H3601, so Ryan's H1200 on Oct 30-31 is in the way (NO), and the
    Nov 10 row uses November's (MISSED). Before, one merged dict let the month iterated last win (hash seed order)."""
    import json
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.DB.put("pkg_details:2026-10", {"H3601": {"report": "08:00", "block": "20:00", "rel_days": 4,
                                               "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                                                          {"d": 3, "dep": 3 * 1440 + 540, "arr": 3 * 1440 + 840, "stn": "HNL", "blk": 300}]}})
    W.DB.put("pkg_details:2026-11", {"H3601": {"report": "08:00", "block": "5:00", "rel_days": 1,
                                               "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "HNL", "blk": 300}]}})
    _line(W, [{"trip": "H1200", "start": "2026-10-30", "end": "2026-10-31"}],
          {"H1200|2026-10-30": {"report": "08:00", "last_arr": "16:00", "blk": "8:00"}}, months=("2026-09", "2026-10", "2026-11", "2026-12"))
    W.recall_cmd(json.dumps([{"date": "2026-10-28", "rows": [_row(date="2026-10-28", pairing="H3601")]},
                             {"date": "2026-11-20", "rows": [_row(date="2026-11-20", pairing="H3601")]}]))
    W.recall_act(json.dumps({"me": {"sen": 500}}))
    vs = _last(sent)[1]
    old, new = vs["2026-10-28|H3601|recall"], vs["2026-11-20|H3601|recall"]
    assert old["verdict"] == "NO" and old["end"] == "2026-10-31" and "H1200" in old["why"][-1], old["why"]
    assert new["verdict"] == "MISSED" and new["end"] == "2026-11-20", new["why"]


def test_upgrade_counts_a_draft_as_pushed_only_if_it_was_missed(tmp_path, monkeypatch):
    """Acts from 1.4.5 have no 'missed_sent'. One whose stored verdict was POSSIBLE (its push was dropped by the
    MISSED-only automation) and is MISSED now pushes once on the next list post; one stored MISSED was pushed already."""
    import json
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.DB.put("recall_me", {"sen": 500})
    rows = [_row(), _row(pairing="H9003", date="2026-11-10")]
    W.DB.put("pkg_details:2026-11", {**DET, "H9003": DET["H9001"]})
    W.DB.put("recall_days", {"2026-11-10": {"date": "2026-11-10", "file": "ok", "rows": rows, "at": "2026-11-10T20:00:00+00:00",
                                            "verdicts": [{"id": "2026-11-10|H9001|recall", "verdict": "POSSIBLE"},
                                                         {"id": "2026-11-10|H9003|recall", "verdict": "MISSED"}]}})
    W.DB.put("recall_acts", {"2026-11-10|H9001|recall": {"status": "new", "narrative": "n", "at": "2026-11-10T20:00:00+00:00"},
                             "2026-11-10|H9003|recall": {"status": "new", "narrative": "n", "at": "2026-11-10T20:00:00+00:00"}})
    W.recall_eval()  # startup: no push
    acts = W.DB.get("recall_acts")
    assert acts["2026-11-10|H9001|recall"]["missed_sent"] is False and acts["2026-11-10|H9003|recall"]["missed_sent"] is True
    assert not [t for t, _ in sent if t == "event/recall_miss"]
    W.recall_cmd(json.dumps({"date": "2026-11-11", "rows": []}))
    ev = [p for t, p in sent if t == "event/recall_miss"]
    assert [(p["id"], p["verdict"]) for p in ev] == [("2026-11-10|H9001|recall", "MISSED")]
    W.recall_cmd(json.dumps({"date": "2026-11-12", "rows": []}))
    assert len([1 for t, _ in sent if t == "event/recall_miss"]) == 1


def test_over_75_answer_is_kept_per_month(tmp_path, monkeypatch):
    """PWA 22.G.2.d: {me: {o75_months: {YYYY-MM: true | false | null}}} from the tab; bad months and values are
    ignored, null forgets. The old single 'o75' flag is dropped. An Over 75 row is POSSIBLE until the month is set."""
    import json
    W, sent = _recall_w(tmp_path, monkeypatch)
    W.DB.put("recall_me", {"sen": 500, "o75": True})
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row(kind="o75")]}))
    vid = "2026-11-10|H9001|o75"
    st, vs = _last(sent)
    assert vs[vid]["verdict"] == "POSSIBLE" and "reserve status for Nov 2026 unknown" in vs[vid]["why"][-1]
    assert st["me"] == {"sen": 500, "seat": "FO", "o75_months": {}}
    W.recall_act(json.dumps({"me": {"o75_months": {"2026-11": True, "2026-13": True, "nope": False, "2026-12": "yes"}}}))
    st, vs = _last(sent)
    assert st["me"]["o75_months"] == {"2026-11": True} and vs[vid]["verdict"] == "MISSED"
    W.recall_act(json.dumps({"me": {"o75_months": {"2026-11": False}}}))
    assert _last(sent)[1][vid]["verdict"] == "NO"
    W.recall_act(json.dumps({"me": {"o75_months": {"2026-11": None}, "sen": 500}}))
    st, vs = _last(sent)
    assert st["me"]["o75_months"] == {} and vs[vid]["verdict"] == "POSSIBLE"

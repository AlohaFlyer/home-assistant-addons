"""1.7.7 (Ryan, Nov 14): "the person picking up should be blue and clickable... the other person who was already on
the pairing should be black and not clickable". Only the open-seat picker(s) of a pickup count: the finds card links
them, the FO / RO pickers table scores each of them once per pickup, and the in-flight check looks them up. Before,
store.picker_of() read a two-name 'by' ("FO A (n1); RO B (n2)") as the first name with the last number, and the
pickers table showed merged rows like "A (n1); RO B" under n2. Synthetic pilots only ("Doe, Jane" 10001)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pot  # noqa: E402
from store import PICKERS_V, Store, by_parts, picker_of, pickers_of  # noqa: E402
from test_crew_index import W  # noqa: E402,F401  (the Watcher fixture)

JANE, RICK, PAT, MAX = "Doe, Jane (10001)", "Roe, Rick (10002)", "Poe, Pat (10003)", "Moe, Max (10004)"


# ---------------------------------------------------------------- pot.pickup_pickers
def test_with_both_rosters_the_newcomer_in_the_open_seat_is_the_picker():
    before = [("CA", "Doe, John"), ("FO", "OPEN"), ("RO", "Roe, Bob")]
    after = [("CA", "Doe, John"), ("FO", "Doe, Jane"), ("RO", "Roe, Rick")]  # Rick replaced Bob: a crew swap
    assert pot.pickup_pickers([("FO", "Doe, Jane"), ("RO", "Roe, Rick")], ["FO"], before, after) == [0]
    # both seats open: both newcomers took one each
    both = [("CA", "Doe, John"), ("FO", "OPEN"), ("RO", "OPEN")]
    assert pot.pickup_pickers([("FO", "Doe, Jane"), ("RO", "Roe, Rick")], ["FO", "RO"], both, after) == [0, 1]
    # the open seat not shown at all before (FLICA leaves it out): the seat that appeared is the one filled
    hidden = [("CA", "Doe, John"), ("FO", "Doe, Jane")]
    assert pot.pickup_pickers([("RO", "Roe, Rick")], [], hidden, after) == [0]
    # one FO seat open, two new FOs (one swapped in): ambiguous, nobody rather than the wrong pilot
    two = [("CA", "Doe, John"), ("FO", "Doe, Bob"), ("FO", "OPEN")]
    assert pot.pickup_pickers([("FO", "Doe, Jane"), ("FO", "Poe, Pat")], ["FO"], two,
                              [("CA", "Doe, John"), ("FO", "Doe, Jane"), ("FO", "Poe, Pat")]) == []


def test_without_rosters_the_open_seats_and_the_seat_before_each_name_decide():
    parts = [("FO", "Doe, Jane"), ("RO", "Roe, Rick")]
    assert pot.pickup_pickers(parts, ["FO"]) == [0]
    assert pot.pickup_pickers(parts, ["RO"]) == [1]
    assert pot.pickup_pickers(parts, ["FO", "RO"]) == [0, 1]
    assert pot.pickup_pickers(parts, []) == []  # no open seat on file and two names: none
    assert pot.pickup_pickers(parts[:1], []) == [0]  # a lone name is the picker
    assert pot.pickup_pickers([("FO", "Doe, Jane"), ("FO", "Poe, Pat")], ["FO"]) == []  # 2 names, 1 seat


def test_by_parts_and_picker_of():
    assert by_parts(f"FO {JANE}; RO {RICK}") == [("FO", "Doe, Jane", "10001"), ("RO", "Roe, Rick", "10002")]
    assert by_parts("FO Doe, Pat") == [("FO", "Doe, Pat", "")]
    # the old bug, kept visible: picker_of on a two-name 'by' gives a merged name with the last number
    assert picker_of(f"FO {JANE}; RO {RICK}") == ("FO", "Doe, Jane (10001); RO Roe, Rick", "10002")


def test_pickers_of_prefers_the_stored_list_then_derives():
    pk = {"by": f"FO {JANE}; RO {RICK}"}
    assert pickers_of(dict(pk, pickers=["10002"])) == [("RO", "Roe, Rick", "10002")]
    assert pickers_of(dict(pk, pickers=[])) == []  # the check found it ambiguous: nobody
    assert pickers_of(pk, {"open_seats": "FO"}) == [("FO", "Doe, Jane", "10001")]
    assert pickers_of(pk, {"open_seats": "FO,RO"}) == [("FO", "Doe, Jane", "10001"), ("RO", "Roe, Rick", "10002")]
    assert pickers_of(pk, {}) == []


# ---------------------------------------------------------------- the store
def _find(db, key, by, gone, open_seats="", source="pot", pickup=None, first=None):
    row = {"pairing": key.split("|")[0], "open_seats": open_seats, "layover": "LAX"}
    if source != "pot":
        row["source"] = source
    db.add_find(key, "2026-11", row, first or gone, gone=gone)
    db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (gone, key))
    db.set_pickup(key, dict({"status": "filled", "by": by, "ca": "", "known": True}, **(pickup or {})))


def _old_style(db, key, by, secs):
    """A pickup scored the way it was before 1.7.7 (1.7.6.1 on Pako): the merged name and the last number, the log
    keyed by the find."""
    pos, name, emp = picker_of(by)
    db.db.execute("INSERT INTO pickers(emp,name,pos,n,total_s,last_at) VALUES(?,?,?,1,?,?) ON CONFLICT(emp) DO UPDATE SET "
                  "n=n+1, total_s=total_s+excluded.total_s", (emp, name, pos, secs, "2026-11-03T00:00:00+00:00"))
    gone = db.db.execute("SELECT gone_at FROM finds WHERE key=?", (key,)).fetchone()[0]
    db.db.execute("INSERT INTO picker_log(key,emp,at,secs,approx,lay) VALUES(?,?,?,?,0,'LAX')", (key, emp, gone, secs))
    pk = json.loads(db.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()[0])
    pk["scored"] = secs
    db.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), key))


def test_a_both_seats_pickup_scores_each_picker_once(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    _find(db, "H9001|20Nov", f"FO {PAT}; RO {MAX}", "2026-11-03T22:14:00+00:00", "FO,RO",
          pickup={"pickers": ["10003", "10004"]}, first="2026-11-03T22:12:00+00:00")
    assert db.score_pickup("H9001|20Nov") == 120 and db.score_pickup("H9001|20Nov") is None
    st = db.picker_stats()
    assert (st["10003"]["n"], st["10004"]["n"]) == (1, 1) and st["10003"]["name"] == "Poe, Pat"
    assert sorted(k for (k,) in db.db.execute("SELECT key FROM picker_log")) == ["H9001|20Nov|10003", "H9001|20Nov|10004"]
    # one open seat, two names, the stored list naming the picker: only he is scored
    _find(db, "H9002|21Nov", f"FO {JANE}; RO {RICK}", "2026-11-04T22:14:00+00:00", "FO", pickup={"pickers": ["10001"]},
          first="2026-11-04T22:13:00+00:00")
    db.score_pickup("H9002|21Nov")
    assert "10002" not in db.picker_stats() and db.picker_stats()["10001"]["n"] == 1
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H9002"]["pickers"] == ["10001"] and f["H9002"]["picker_emp"] == "10001" and f["H9002"]["open_seats"] == "FO"
    assert f["H9001"]["pickers"] == ["10003", "10004"]


def test_the_rebuild_drops_the_merged_rows_and_counts_each_picker_once(tmp_path):
    db = Store(str(tmp_path / "r.db"))
    # data from before 1.7.7: a two-name 'by' with one open seat (FO), scored to Rick (10002) under
    # "Doe, Jane (10001); RO Roe, Rick"
    _find(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", "2026-11-03T22:14:00+00:00", "FO")
    _old_style(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", 120)
    db.set_inflt("H9001|20Nov", True, "H3648 2026-11-03", tries=1)  # looked up for 10002, the wrong pilot
    # both seats open, scored to Max only; Max was on the ground
    _find(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", "2026-11-04T22:14:00+00:00", "FO,RO")
    _old_style(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", 60)
    db.set_inflt("H9002|21Nov", False, "", tries=1)
    # a plain one-name pickup by Jane, and an email-caught one with two names and no open seat on file (ambiguous)
    _find(db, "H9003|22Nov", f"FO {JANE}", "2026-11-05T22:14:00+00:00", "FO")
    _old_style(db, "H9003|22Nov", f"FO {JANE}", 30)
    _find(db, "H9004|23Nov", f"FO {PAT}; RO {RICK}", "2026-11-06T22:14:00+00:00", "", source="email")
    merged = db.picker_stats()["10002"]["name"]
    assert ";" in merged and "(10001)" in merged  # the bug as it was on Pako
    assert db.get("pickers_rebuild_v") is None
    r = db.rebuild_pickers()
    assert r == {"pickups": 3, "pickers": 3, "inflt_reset": 2} and db.get("pickers_rebuild_v") == PICKERS_V
    st = db.picker_stats()
    assert sorted(st) == ["10001", "10003", "10004"]  # no row for Rick: he was already on the pairing
    assert (st["10001"]["name"], st["10001"]["pos"], st["10001"]["n"], st["10001"]["total_s"]) == ("Doe, Jane", "FO", 2, 150)
    assert (st["10003"]["n"], st["10004"]["n"], st["10004"]["name"]) == (1, 1, "Moe, Max")
    assert not any(";" in v["name"] or "(" in v["name"] for v in st.values())
    # the in-flight check now looks up the right pilots: Jane (the verdict was Rick's), then Pat (Max was on the ground)
    assert sorted(t[:2] for t in db.pickups_without_inflt()) == [("H9001|20Nov", "10001"), ("H9002|21Nov", "10003"),
                                                                  ("H9003|22Nov", "10001")]  # H9003: never looked up
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H9001"]["inflt"] is None and f["H9001"]["pickers"] == ["10001"] and f["H9004"]["pickers"] == []
    # once only, and a reopen (the log backfill on every start) adds nothing
    db.put("pickers_rebuild_v", None)
    assert db.rebuild_pickers()["pickers"] == 3 and db.picker_stats()["10001"]["n"] == 2
    db2 = Store(str(tmp_path / "r.db"))
    assert db2.picker_stats()["10001"]["n"] == 2 and db2.db.execute("SELECT COUNT(*) FROM picker_log").fetchone()[0] == 4


def test_two_pickers_in_flight_check_one_then_the_other(tmp_path):
    db = Store(str(tmp_path / "i.db"))
    _find(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", "2026-11-04T22:14:00+00:00", "FO,RO", pickup={"pickers": ["10003", "10004"]})
    db.score_pickup("H9002|21Nov")
    (k, emp, _g, tries), = db.pickups_without_inflt()
    assert emp == "10003"
    db.set_inflt(k, False, "", tries=tries + 1, emp=emp)  # Pat on the ground: Max is next, no verdict yet
    assert [t[1] for t in db.pickups_without_inflt()] == ["10004"] and db.recent_finds()[0]["inflt"] is None
    leg = {"flt": "808", "frm": "HNL", "to": "LAS", "dep_l": "23:00", "date": "2026-11-06", "dh": False, "src": "page"}
    db.set_inflt(k, True, "H3648 2026-11-03", tries=2, emp="10004", leg=leg)
    f = db.recent_finds()[0]
    assert (f["inflt"], f["inflt_emp"], f["inflt_leg"]) == (True, "10004", leg) and db.pickups_without_inflt() == []
    st = db.picker_stats()
    assert (st["10003"]["inflt_n"], st["10004"]["inflt_n"]) == (0, 1)
    # a re-check of the pickup keeps the verdict, its leg and its picker; a reset drops them all
    db.set_pickup(k, {"status": "filled", "by": f"FO {PAT}; RO {MAX}", "ca": "", "known": True, "pickers": ["10003", "10004"]})
    assert db.recent_finds()[0]["inflt_leg"] == leg
    db.reset_inflt()
    pk = json.loads(db.db.execute("SELECT pickup FROM finds WHERE key=?", (k,)).fetchone()[0])
    assert not {"inflt", "inflt_leg", "inflt_emp", "inflt_no", "inflt_trip", "inflt_tries"} & set(pk)


# ---------------------------------------------------------------- the Watcher's pickup check and start
PAGE = ("<html><body>pairing details h9001:20nov check in: 08:00 dy flt dps-ars dep arr blk "
        "fr 9001 hnl-lax 0900 1600 0500 crew: ca 10009 doe, john fo 10001 doe, jane ro 10002 roe, rick</body></html>")


class _Fl:
    def __init__(self):
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return PAGE


def test_the_pickup_check_stores_the_open_seat_picker(W, monkeypatch):  # noqa: F811
    monkeypatch.setattr(W, "inflt_check", lambda fl, limit=3: False)
    monkeypatch.setattr(W, "pilot_check", lambda fl: False)
    row = {"pairing": "H9001", "start": "20Nov", "dates": "20NOV-21NOV", "open_seats": "FO",
           "detail_url": f"https://{W.SM.HOST}/full/mobilepairing.cgi?PID=H9001&DATE=20261120",  # a fake fetch (_Fl)
           "crew": [["CA", "Doe, John"], ["FO", "OPEN"], ["RO", "Roe, Bob"]]}  # Rick swapped in for Bob
    W.DB.add_find("H9001|20Nov", "2026-11", row, "2026-11-10T20:00:00+00:00", gone="2026-11-10T21:00:00+00:00")
    W.S["pickup_pending"] = {"H9001|20Nov": {"tries": 0, "next": 0}}
    for f in ("email_unchanged_fixed", "email_details_fixed", "pickup_backfilled", "pickers_scored", "ids_backfilled"):
        W.S[f] = True
    W.pickup_check(_Fl())
    f = W.DB.recent_finds()[0]
    assert f["picked_by"] == f"FO {JANE}; RO {RICK}" and f["pickers"] == ["10001"]
    assert sorted(W.DB.picker_stats()) == ["10001"]


def test_the_start_rebuilds_the_pickers_once(W):  # noqa: F811
    _find(W.DB, "H9001|20Nov", f"FO {JANE}; RO {RICK}", "2026-11-03T22:14:00+00:00", "FO")
    _old_style(W.DB, "H9001|20Nov", f"FO {JANE}; RO {RICK}", 120)
    src = open(W.__file__).read()
    assert 'DB.get("pickers_rebuild_v") != PICKERS_V' in src and "DB.rebuild_pickers()" in src
    W.DB.rebuild_pickers()
    W.publish_pickers()
    rows = [p for t, p in W.SENT if t == "pickers"][-1]["pickers"]
    assert [(r["emp"], r["name"], r["n"]) for r in rows] == [("10001", "Doe, Jane", 1)]

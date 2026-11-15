"""1.7.9 (contract 1 revision 4): the admin's Watcher and its two switches on api/pilotdb.

Share with a portal pilot (op share, Ryan's card only, off by default): nothing leaves Ryan's Watcher while it is off;
on, the pilot's file and the roster are written and his inbox is drained; off again, the file is deleted. The AI note
(op ai, off by default): anonymous pickup statistics for HOM's consultant models (pilots with 3 or more pickups; no
name, employee number, record id, seniority number, date of hire, pairing number or exact date; an id made new for
every batch that only Ryan's database maps back) and HOM's notes taken into pilotdb's ai_notes, labeled AI, apart from
the human notes and never in a pilot's file. Log lines carry ops, instance names and counts only.
Synthetic pilots only ("Doe, Jane", 10001)."""
import json
import logging
import os
import re
import stat

import pytest

import pdbshare as PS
import pilotdb as PDBM
import portal as PT
import roles
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pilotdb_pickups import _store
from test_pilotdb_watcher import P, SECRETS  # noqa: F401  (the seeded pilot database fixture)


@pytest.fixture
def A(P):  # noqa: F811
    P.OPTS["pilots"] = [{"name": "james", "portal": True}, {"name": "pilot3"}]
    db = P.pilotdb_start()
    return P, db


def _root(P):  # noqa: N803
    return P.PILOTDB_SHARE


def _post(P, **obj):  # noqa: N803
    return P.pilotdb_post(obj)


def test_nothing_is_shared_until_ryan_taps_the_switch(A):
    P, db = A  # noqa: N806
    assert P.pilotdb_portal_pilots() == ["james"]  # pilot3 has no portal
    st = P.pilotdb_status()
    assert st["shared_with"] == [] and st["pilots"] == [{"name": "james", "shared": False, "pending": 0, "full": False}]
    assert not os.path.exists(PS.export_path("james", _root(P))) and not os.path.exists(PS.roster_path(_root(P)))
    assert P.pilotdb_share_pass(force=True) == {"applied": 0, "refused": 0, "scrub": False}
    assert not os.path.exists(PS.export_path("james", _root(P))) and not os.path.exists(PS.roster_path(_root(P)))
    assert P.pilotdb_sensor()["shared_with"] == []


def test_the_share_switch_writes_the_files_at_once_and_off_deletes_them(A, caplog):
    P, db = A  # noqa: N806
    jane = db.find("10001")
    with caplog.at_level(logging.INFO):
        code, r = _post(P, op="share", pilot="james", on=True)
    assert code == 200 and r["shared_with"] == ["james"]
    ep = PS.export_path("james", _root(P))
    assert stat.S_IMODE(os.stat(ep).st_mode) == 0o600 and os.path.exists(PS.roster_path(_root(P)))
    assert json.load(open(ep))["count"] == 0  # no shared note yet: an empty file, never the roster
    assert "pilot db: shared with james" in caplog.text
    # a change of Ryan's reaches the file after the 2 s debounce (two passes), not on the first pass
    _post(P, op="field", pid=jane, text="Commutes from the mainland.", base=PDBM.ZERO_REV)
    P.pilotdb_share_pass()
    assert json.load(open(ep))["count"] == 0
    P.pilotdb_share_pass()
    assert json.load(open(ep))["count"] == 1
    st = P.pilotdb_status()
    assert st["pilots"][0]["shared"] is True and st["pending"] == {"james": 0}
    # only a pilot with a portal, only true or false, and never from a pilot's name in another shape
    assert _post(P, op="share", pilot="pilot3", on=True)[0] == 400
    assert _post(P, op="share", pilot="james", on="yes")[0] == 400
    assert _post(P, op="share", pilot="james")[0] == 400
    code, r = _post(P, op="share", pilot="james", on=False)
    assert code == 200 and r["shared_with"] == []
    assert not os.path.exists(ep) and not os.path.exists(PS.roster_path(_root(P)))
    for s in SECRETS:
        assert s not in caplog.text, s


def test_the_drain_applies_a_shared_pilots_note_and_edit_and_the_card_sees_the_count(A, caplog):
    P, db = A  # noqa: N806
    jane = db.find("10001")
    _post(P, op="share", pilot="james", on=True)
    rev = db.record(jane)["rev"]
    PS.inbox_put("james", "note", {"op": "add", "pid": jane, "text": "NOTE-SENTINEL", "rid": "rid-adm001"}, _root(P))
    assert P.pilotdb_status()["pending"] == {"james": 1} and P.pilotdb_sensor()["pending"] == {"james": 1}
    PS.inbox_put("james", "edit", {"op": "set", "pid": jane, "field": "seat", "value": "FO", "rev": rev + 1,
                                   "rid": "rid-adm002"}, _root(P))
    with caplog.at_level(logging.INFO):
        r = P.pilotdb_share_pass()
    assert r == {"applied": 2, "refused": 0, "scrub": False}
    d = json.load(open(PS.export_path("james", _root(P))))  # written at once after the drain
    assert [a["rid"] for a in d["answers"]] == ["rid-adm001", "rid-adm002"] and d["count"] == 1
    assert d["records"][0]["seat"] == "FO" and d["records"][0]["entries"][0]["mine"] is True
    rec = db.record(jane)
    assert rec["entries"][0]["by"] == "james" and rec["fields"]["seat"]["by"] == "james"
    assert "pilot db: note add from james: saved" in caplog.text and "NOTE-SENTINEL" not in caplog.text
    for s in SECRETS:
        assert s not in caplog.text, s
    assert P.pilotdb_status()["pending"] == {"james": 0}


def test_a_pilot_instance_never_runs_the_share_pass_or_opens_the_database(A, monkeypatch):
    P, db = A  # noqa: N806
    monkeypatch.setattr(P, "INSTANCE", "james")
    assert P.pilotdb_share_pass(force=True) is None and P.pilotdb_portal_pilots() == []
    assert P.pilotdb_start() is None


# ---------------------------------------------------------------- the AI note
def _pickups(db, tmp_path):
    s = _store(tmp_path)
    return db.sync_pickups(s.pickup_history())


def test_no_statistics_leave_while_the_ai_switch_is_off(A, tmp_path):
    P, db = A  # noqa: N806
    _pickups(db, tmp_path)
    P.pilotdb_share_pass(force=True)
    assert not os.path.exists(os.path.join(_root(P), "ai"))
    assert P.pilotdb_status()["ai"] == {"on": False, "notes": 0}


def test_the_statistics_are_anonymous_and_only_for_three_or_more_pickups(A, tmp_path, caplog):
    P, db = A  # noqa: N806
    _pickups(db, tmp_path)
    jane = db.find("10001")
    assert len(db.pickups(jane)["rows"]) == 3
    with caplog.at_level(logging.INFO):
        code, r = _post(P, op="ai", on=True)  # the first batch is written with the switch
    assert code == 200 and r["ai"] == {"on": True, "cleared": 0}
    _d, path, in_dir = PS.ai_paths(_root(P))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(in_dir).st_mode) == 0o700
    text = open(path, encoding="utf-8").read()
    d = json.loads(text)
    cfg = roles.PILOTDB_AI
    assert set(d) == {"v", "batch", "generated", "min_pickups", "count", "pilots", "note_max", "rules"}
    assert d["count"] == 1 and d["min_pickups"] == 3 and re.fullmatch(cfg["batch_re"], d["batch"])  # only Jane has 3
    row = d["pilots"][0]
    assert set(row) == {"id", "stats"} and re.fullmatch(cfg["id_re"], row["id"])
    assert set(row["stats"]) == set(PT.AI_STATS_KEYS)
    assert row["stats"]["n"] == 3 and row["stats"]["lays"] == [["LAX", 2]] and row["stats"]["turns"] == 1
    assert row["stats"]["first_month"] == "2026-11" and row["stats"]["seats"] == {"FO": 3}
    # no name, employee number, pid, pairing number, exact time, seniority number or date of hire
    for s in ("Doe", "Jane", "10001", jane, "H360", "2026-11-0", "812", "2001-05-01", "emp", "pid", "name"):
        assert s not in text, s
    assert "pilot db: AI statistics written for 1 pilots" in caplog.text
    for s in SECRETS:
        assert s not in caplog.text, s
    # the same statistics make no new batch (the file's batch stays the one HOM answers)
    P.PDB["ai_at"] = 0.0
    P.pilotdb_share_pass()
    assert json.load(open(path))["batch"] == d["batch"]
    # a new batch has new ids: nothing links one batch's id to the next
    doc2, _ = db.ai_stats()
    assert doc2["pilots"][0]["id"] != row["id"] and doc2["batch"] != d["batch"]


def test_homs_note_is_stored_apart_labeled_ai_and_never_goes_to_a_pilot(A, tmp_path, caplog):
    P, db = A  # noqa: N806
    _pickups(db, tmp_path)
    jane = db.find("10001")
    _post(P, op="share", pilot="james", on=True)
    _post(P, op="ai", on=True)
    P.pilotdb_share_pass()
    _d, path, in_dir = PS.ai_paths(_root(P))
    d = json.load(open(path))
    sid = d["pilots"][0]["id"]
    note = "Picks up 3-day trips that report on a weekday, usually within minutes. AI-SENTINEL"
    open(os.path.join(in_dir, d["batch"] + ".json"), "w").write(json.dumps(
        {"v": 1, "batch": d["batch"], "model": "consultant-model-1", "notes": [
            {"id": sid, "text": note},
            {"id": "a" + "0" * 16, "text": "An id that is not in the batch."}]}))
    with caplog.at_level(logging.INFO):
        P.pilotdb_share_pass()
    assert os.listdir(in_dir) == []
    ai = db.record(jane)["ai_note"]
    assert ai["text"] == note and ai["model"] == "consultant-model-1" and ai["label"] == "AI"
    rec = db.record(jane)
    assert rec["notes"] is None and rec["entries"] == []  # apart from the human notes
    assert "pilot db: AI notes in: 1 saved, 1 refused" in caplog.text and "AI-SENTINEL" not in caplog.text
    assert P.pilotdb_status()["ai"] == {"on": True, "notes": 1}
    # never in a pilot's file or the roster
    P.pilotdb_share_pass(force=True)
    assert "AI-SENTINEL" not in open(PS.export_path("james", _root(P))).read()
    assert "AI-SENTINEL" not in open(PS.roster_path(_root(P))).read()
    # off with clear: the statistics file and the notes go
    code, r = _post(P, op="ai", on=False, clear=True)
    assert code == 200 and r["ai"] == {"on": False, "cleared": 1}
    assert not os.path.exists(path) and db.record(jane)["ai_note"] is None
    assert _post(P, op="ai", on=True, clear=True)[0] == 400 and _post(P, op="ai", on="yes")[0] == 400


def test_the_contracts_ai_samples_are_taken_and_refused_as_it_says(A, tmp_path):
    P, db = A  # noqa: N806
    _pickups(db, tmp_path)
    jane = db.find("10001")
    acc = PT.AI_SAMPLE_NOTES
    db.set_meta("ai_map", json.dumps([{"batch": acc["batch"], "at": "x", "ids": {acc["notes"][0]["id"]: jane}}]))
    assert db.ai_take(acc) == {"saved": 1, "refused": 0}
    assert db.record(jane)["ai_note"]["text"] == acc["notes"][0]["text"]
    for s in PT.AI_SAMPLE_REFUSED:
        r = db.ai_take(s["file"])
        assert r["saved"] == 0 and r["refused"] >= 1, s["why"]
    assert db.record(jane)["ai_note"]["text"] == acc["notes"][0]["text"]
    for bad in (None, [], "x", {"v": 2, "batch": acc["batch"], "model": "m", "notes": []},
                {**acc, "extra": 1}, {**acc, "notes": "x"}):
        assert db.ai_take(bad)["saved"] == 0
    # the sample statistics hold the documented keys only
    st = PT.AI_SAMPLE_STATS
    assert set(st["pilots"][0]["stats"]) == set(PT.AI_STATS_KEYS) and re.fullmatch(roles.PILOTDB_AI["id_re"],
                                                                                 st["pilots"][0]["id"])


def test_an_answer_file_that_is_a_symlink_too_big_or_misnamed_is_dropped(A, tmp_path):
    P, db = A  # noqa: N806
    _pickups(db, tmp_path)
    _post(P, op="ai", on=True)
    P.pilotdb_share_pass()
    _d, path, in_dir = PS.ai_paths(_root(P))
    d = json.load(open(path))
    good = {"v": 1, "batch": d["batch"], "model": "m1", "notes": [{"id": d["pilots"][0]["id"], "text": "A note."}]}
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps(good))
    os.symlink(str(secret), os.path.join(in_dir, d["batch"] + ".json"))
    open(os.path.join(in_dir, "notes.json"), "w").write(json.dumps(good))
    open(os.path.join(in_dir, "0123456789abcdef.json"), "w").write(json.dumps(good))  # the name is not its batch
    r = PS.ai_drain(db, _root(P))
    assert r["saved"] == 0 and os.listdir(in_dir) == [] and secret.exists()
    assert db.record(db.find("10001"))["ai_note"] is None

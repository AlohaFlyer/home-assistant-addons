"""1.7.9 (contract 1 revision 4; spec 11.1, 11.2, 11.4), as of 1.7.10 (Ryan's decisions of Nov 15: "The pilot database
should be shared with James 100%"): what leaves Ryan's pilot database for a portal pilot, and how that pilot's notes
and field edits come back.

Sharing is on by default for every portal pilot; Ryan's switch turns one off (his file is deleted) and on again, and
the choice is kept outside the database (pilotdb.Switches). A shared pilot's file is a whitelist of keys that holds
every live record with every field (the employee number, phones and emails too), the notes, the whole log (an entry
an older version marked "Only me" too), the pickup history and, while the AI notes are on, the AI note; never a
hidden or purged text, a field's sources, the history or another pilot's answers; 0600. No roster is written. The
admin's inbox drain applies notes, log entries and field edits with the author taken from the folder's name,
compare-and-set, quotas and fixed answers, and keeps every earlier version.
Synthetic pilots only ("Doe, Jane", 10001, 555-01xx, example.com)."""
import json
import os
import stat
from datetime import timedelta

import pytest

import pdbshare as PS
import pilotdb as P
import portal as PT
import roles
from test_pilotdb_store import CONTACTS, LIST, T0, _jane, mk  # noqa: F401

PILOTS = ["james", "pilot3"]
T0S = T0.timestamp()


@pytest.fixture
def db(mk):  # noqa: F811
    d = mk()
    d.merge_list(LIST)
    d.merge_contacts(CONTACTS)
    return d


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "share" / "pilotdb")


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def _keys(v, out=None):
    """Every dict key anywhere in v."""
    out = set() if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            out.add(k)
            _keys(x, out)
    elif isinstance(v, list):
        for x in v:
            _keys(x, out)
    return out


def _put(root, pilot, cmd, now=T0S, by=None, **inner):
    """A command file in a pilot's inbox, as his Watcher writes it (by: forge another author in the body)."""
    name = PS.inbox_put(pilot, cmd, inner, root, now=now)
    if by is not None:
        p = os.path.join(PS.inbox_dir(pilot, root), name)
        d = json.load(open(p))
        d["by"] = by
        json.dump(d, open(p, "w"))
    return name


def _share(db, root, pilot="james"):
    """Sharing is on by default (1.7.10); the tests of one pilot's file turn the other pilot's off."""
    for p in PILOTS:
        db.set_share(p, p == pilot)
    return PS.write_files(db, PILOTS, root)


# ---------------------------------------------------------------- the switch
def test_every_portal_pilot_is_shared_with_by_default_and_no_roster_is_written(db, root):
    jane = _jane(db)
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    assert db.shared_with(PILOTS) == PILOTS and db.is_shared("james") and db.is_shared("pilot3")
    assert not db.is_shared("../etc") and not db.is_shared(None)
    assert PS.write_files(db, PILOTS, root) == {"james": "on", "pilot3": "on"}
    assert sorted(os.listdir(os.path.join(root, "portal"))) == ["james.json", "pilot3.json"]
    assert not os.path.exists(PS.roster_path(root))


def test_ryans_off_switch_writes_nothing_for_that_pilot(db, root):
    for p in PILOTS:
        db.set_share(p, False)
    assert db.shared_with(PILOTS) == [] and not db.is_shared("james")
    assert PS.write_files(db, PILOTS, root) == {"james": "off", "pilot3": "off"}
    assert os.listdir(os.path.join(root, "portal")) == []


def test_share_on_writes_private_files_and_off_deletes_them(db, root):
    jane = _jane(db)
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    assert _share(db, root) == {"james": "on", "pilot3": "off"}
    assert _mode(PS.export_path("james", root)) == 0o600
    for d in (root, os.path.join(root, "portal"), os.path.join(root, "inbox"), PS.inbox_dir("james", root)):
        assert _mode(d) == 0o700
    assert not os.path.exists(PS.export_path("pilot3", root))  # Ryan turned that pilot's share off
    db.set_share("james", False)
    assert PS.write_files(db, PILOTS, root) == {"james": "off", "pilot3": "off"}
    assert not os.path.exists(PS.export_path("james", root))
    with pytest.raises(P.Bad):
        db.set_share("james", "yes")
    with pytest.raises(P.Bad):
        db.set_share("../etc", True)


def test_a_roster_an_older_version_left_is_removed(db, root, tmp_path):
    rdir = str(tmp_path / "data" / "pilotdb_roster")
    os.makedirs(rdir)
    os.makedirs(root)
    for d in (root, rdir):
        open(PS.roster_path(d), "w").write("{}")
    PS.write_files(db, PILOTS, root, roster_dir=rdir)
    assert not os.path.exists(PS.roster_path(root)) and not os.path.exists(rdir)


def test_a_pilot_no_longer_configured_loses_his_file(db, root):
    _share(db, root)
    assert os.path.exists(PS.export_path("james", root))
    PS.write_files(db, ["pilot3"], root)
    assert not os.path.exists(PS.export_path("james", root))


# ---------------------------------------------------------------- the file: a whitelist
def test_the_file_holds_every_pilot_with_every_field_and_whitelisted_keys(db, root):
    jane, rick = _jane(db), db.find("10002")
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    shared = db.add_entry(jane, "Flew with her in October.", True, "rid-000001")
    only = db.add_entry(jane, "ONCE-ONLY-ME", False, "rid-000002")  # 1.7.10: there is no only-me entry any more
    hidden = db.add_entry(jane, "HIDDEN-SENTINEL", True, "rid-000003")
    db.hide(hidden)
    gone = db.add_entry(jane, "RETRACTED-SENTINEL", True, "rid-000004")
    db.retract(gone)
    db.set_field(jane, "doh", "2001-05-02", db.record(jane)["rev"], "From her award line")
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    db.set_field(jane, "domicile", "HNL", db.record(jane)["rev"])
    db.put_answer("james", "rid-james1", True, "Saved")
    db.put_answer("pilot3", "rid-other1", False, "Busy: try again in a minute")
    _share(db, root)
    text = open(PS.export_path("james", root), encoding="utf-8").read()
    d = json.loads(text)
    allowed = set()
    for ks in PT.PILOTDB_FILE_KEYS.values():
        allowed |= set(ks)
    allowed |= set(PT.pilotdb_limits())
    assert _keys(d) <= allowed, _keys(d) - allowed
    # every live record, by Sen #: Rick (13) has no note, no log and no pickup and is in the file all the same
    assert d["v"] == 1 and d["count"] == 2 and [r["pid"] for r in d["records"]] == [rick, jane]
    r = d["records"][1]
    assert set(r) <= set(PT.PILOTDB_FILE_KEYS["record"])
    assert (r["emp"], r["name"], r["sen"], r["doh"], r["status"], r["seat"], r["base"], r["gone"]) == (
        "10001", "Doe, Jane A.", "812", "2001-05-02", "SLOA", "", "HNL", False)
    assert r["edited"] == ["doh", "domicile", "union_id"] and r["union_id"] == "424242"
    assert r["phones"][0] == {"label": "mobile", "number": "808-555-0101", "tel": "+18085550101"}
    assert r["emails"] == ["jane.doe@example.com"]
    assert r["notes"]["text"] == "Commutes from the mainland." and r["notes"]["by"] == "ryan"
    assert [e["eid"] for e in r["entries"]] == [gone, only, shared] and r["entries_total"] == 3
    assert r["entries"][0] == {"eid": gone, "by": "ryan", "at": r["entries"][0]["at"], "gone": "taken back"}
    assert r["entries"][1]["text"] == "ONCE-ONLY-ME"  # Ryan: "Share those too"
    assert "mine" not in r["entries"][2]  # ryan's entry is not james's
    assert "pickups" not in r and "ai_note" not in r  # nobody picked anything up; no AI note on file
    k = d["records"][0]
    assert (k["emp"], k["name"], k["entries"], k["entries_total"]) == ("10002", "Roe, Rick", [], 0) and "notes" not in k
    assert [a["rid"] for a in d["answers"]] == ["rid-james1"]
    assert d["limits"] == PT.pilotdb_limits()
    # a byte scan: no hidden or taken back text, no other pilot's answer, no reason line, no source or history
    for s in ("HIDDEN-SENTINEL", "RETRACTED-SENTINEL", "rid-other1", "From her award line", "source", "cands",
              "field_log", "conflict"):
        assert s not in text, s


def test_an_only_me_entry_of_an_older_version_becomes_a_shared_one_at_open(db):
    jane = _jane(db)
    eid = db.add_entry(jane, "Kept to myself in 1.7.9.", True, "rid-000009")
    with db._tx():
        db.db.execute("UPDATE entries SET shared=0 WHERE eid=?", (eid,))
    again = P.PilotDB(db.path, clock=db.clock)  # every open (a restored older copy too)
    try:
        assert again.db.execute("SELECT shared FROM entries WHERE eid=?", (eid,)).fetchone()[0] == 1
        assert [e["text"] for e in again.export_for("james")["records"][-1]["entries"]] == ["Kept to myself in 1.7.9."]
        assert "(only me)" not in again.render_md()
    finally:
        again.close()


def test_the_pickup_history_is_on_the_pickers_record(db):
    jane = _jane(db)
    db.sync_pickups([{"key": f"H36{i:02d}|13Nov", "emp": "10001", "name": "Doe, Jane", "pos": "FO",
                      "at": f"2026-11-{10 + i:02d}T03:10:00+00:00", "secs": 90 + i, "approx": False, "lay": "SYD",
                      "pairing": f"H36{i:02d}", "start": "2026-11-20", "days": 3, "turn": False, "credit": "14:05",
                      "report": "07:10", "dow": "Fri", "inflt": False} for i in range(3)])
    d = db.export_for("james")
    r = next(x for x in d["records"] if x["pid"] == jane)
    assert set(r["pickups"]) == {"summary", "rows"} and r["pickups"]["summary"]["n"] == 3
    assert [x["pairing"] for x in r["pickups"]["rows"]] == ["H3602", "H3601", "H3600"]  # newest first
    assert set(r["pickups"]["rows"][0]) <= set(PT.PILOTDB_FILE_KEYS["pickup"])
    assert set(r["pickups"]["summary"]) <= set(PT.PILOTDB_FILE_KEYS["pickup_summary"])
    assert "name" not in r["pickups"]["rows"][0] and "key" not in r["pickups"]["rows"][0]
    assert all("pickups" not in x for x in d["records"] if x["pid"] != jane)


def test_mine_marks_only_the_pilots_own_entries(db, root):
    jane = _jane(db)
    e1 = db.add_entry(jane, "James's note.", True, "rid-000001", by="james")
    db.add_entry(jane, "Another pilot's note.", True, "rid-000002", by="pilot3")
    PS.write_files(db, PILOTS, root)  # both are shared by default
    dj = next(r for r in json.load(open(PS.export_path("james", root)))["records"] if r["pid"] == jane)
    d3 = next(r for r in json.load(open(PS.export_path("pilot3", root)))["records"] if r["pid"] == jane)
    assert [e.get("mine") for e in dj["entries"]] == [None, True]
    assert [e.get("mine") for e in d3["entries"]] == [True, None]
    assert dj["entries"][1]["eid"] == e1


def test_entries_are_cut_to_the_newest_and_a_full_file_says_so(db, root):
    jane = _jane(db)
    for i in range(60):
        db.clock_box["t"] = T0 + timedelta(seconds=i)
        db.add_entry(jane, f"note {i:02d} " + "x" * 300, True, f"rid-{i:06d}")
    lim = dict(roles.PILOTDB_NOTE_LIMITS)

    def rec(d):
        return next(r for r in d["records"] if r["pid"] == jane)
    d = db.export_for("james", lim)
    assert len(rec(d)["entries"]) == 50 and rec(d)["entries_total"] == 60
    assert rec(d)["entries"][0]["text"].startswith("note 59") and "full" not in d
    small = dict(lim, export_bytes=12000)
    d = db.export_for("james", small)
    assert len(rec(d)["entries"]) == 20 and "full" not in d
    tiny = dict(lim, export_bytes=2000)
    d = db.export_for("james", tiny)
    assert d["full"] is True and len(rec(d)["entries"]) == 20
    # the admin then refuses his new notes
    ok, why, _ = db.pilot_op("james", "note", {"op": "add", "pid": jane, "text": "one more", "rid": "rid-full01"},
                             full=True)
    assert (ok, why) == (False, "Not saved: the shared notes file is full")


def test_the_file_never_passes_the_hard_size(db):
    """Under portal.CAPS['file'] whatever the database holds: the older logs and the pickup rows go first, then the
    older texts (the newest notes fields, AI notes and entries stay while they fit), the records last; full says so."""
    jane = _jane(db)
    db.save_notes(jane, "N" * 3000, P.ZERO_REV)
    for i in range(30):
        db.clock_box["t"] = T0 + timedelta(seconds=i)
        db.add_entry(jane, f"note {i:02d} " + "x" * 500, True, f"rid-{i:06d}")
    assert P.EXPORT_HARD < PT.CAPS["file"] and roles.PILOTDB_NOTE_LIMITS["export_bytes"] <= P.EXPORT_HARD

    def size(d):
        return len(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode())

    def rec(d):
        return next(r for r in d["records"] if r["pid"] == jane)
    d = db.export_for("james", hard=9000)  # room for the fields, the notes field and a few entries
    assert size(d) <= 9000 and d["full"] is True and d["count"] == 2 and len(rec(d)["entries"]) == 5
    # 1.7.10 review (round 2): no cliff. The newest texts stay while they fit, newest first: here the newest
    # entries (a run from the newest on), not the older 3000 character notes field
    d = db.export_for("james", hard=5000)
    got = [e["text"][:7] for e in rec(d)["entries"]]
    assert size(d) <= 5000 and d["full"] is True and rec(d)["entries_total"] == 30 and "notes" not in rec(d)
    assert len(got) >= 5 and got == [f"note {i:02d}" for i in range(29, 29 - len(got), -1)]
    db.clock_box["t"] = T0 + timedelta(seconds=60)
    db.save_notes(jane, "M" * 3000, db.record(jane)["notes"]["rev"])  # the notes field is the newest text now
    d = db.export_for("james", hard=5000)
    assert size(d) <= 5000 and rec(d)["notes"]["text"] == "M" * 3000 and len(rec(d)["entries"]) >= 1
    d = db.export_for("james", hard=1500)  # nor for the notes field: every record's fields stay
    assert size(d) <= 1500 and d["count"] == 2 and "notes" not in rec(d) and rec(d)["emp"] == "10001"
    d = db.export_for("james", hard=700)  # absurd: the records themselves are cut, the file still reads
    assert size(d) <= 700 and d["full"] is True and d["count"] < 2


# ---------------------------------------------------------------- the drain: notes, log entries, field edits
def test_a_note_an_entry_and_a_field_edit_are_applied_with_the_folders_author(db, root):
    jane = _jane(db)
    _share(db, root)
    lines = []
    _put(root, "james", "note", op="add", pid=jane, text="Flew with her in October.", rid="rid-add001")
    _put(root, "james", "note", now=T0S + 1, op="field", pid=jane, base=P.ZERO_REV, text="Lives in SEA.",
         rid="rid-fld001")
    _put(root, "james", "edit", now=T0S + 2, op="set", pid=jane, field="seat", value="FO", rev=db.record(jane)["rev"] + 2,
         why="His award line", rid="rid-edt001")
    r = PS.drain(db, PILOTS, root, now=T0S + 3, log=lines.append)
    assert r == {"applied": 3, "refused": 0, "scrub": False}
    assert os.listdir(PS.inbox_dir("james", root)) == []
    rec = db.record(jane)
    assert [(e["by"], e["text"], e["shared"]) for e in rec["entries"]] == [("james", "Flew with her in October.", True)]
    assert (rec["notes"]["text"], rec["notes"]["by"]) == ("Lives in SEA.", "james")
    f = rec["fields"]["seat"]
    assert (f["value"], f["by"], f["hand"], f["why"]) == ("FO", "james", True, "His award line")
    assert [(a["rid"], a["ok"], a["why"]) for a in db.answers("james")] == [
        ("rid-add001", True, "Saved"), ("rid-fld001", True, "Saved"), ("rid-edt001", True, "Saved")]
    assert db.answers("pilot3") == []
    # the log names the op and the instance only
    assert lines == ["pilot db: note add from james: saved", "pilot db: note field from james: saved",
                     "pilot db: edit set from james: saved"]
    for s in ("Flew", "SEA", "award", "10001", "Doe", jane):
        assert all(s not in ln for ln in lines), s
    # every earlier value is kept: Ryan sees the edit in the record's log and can put the upload's value back
    log = [x for x in rec["field_log"] if x["field"] == "seat"]
    assert (log[0]["by"], log[0]["new"], log[0]["how"]) == ("james", "FO", "hand")
    back = db.unset_field(jane, "seat", rec["rev"])
    assert back["fields"]["seat"]["value"] == "" and not back["fields"]["seat"]["hand"]


def test_the_author_is_never_taken_from_the_body(db, root):
    jane = _jane(db)
    _share(db, root)
    lines = []
    _put(root, "james", "note", by="ryan", op="add", pid=jane, text="Forged as Ryan.", rid="rid-forge1")
    r = PS.drain(db, PILOTS, root, now=T0S, log=lines.append)
    assert r["applied"] == 0 and r["refused"] == 1 and db.record(jane)["entries"] == []
    assert db.answers("james")[0]["why"] == "Not saved: it could not be read, send it again"
    assert lines == ["pilot db: a command in james's inbox names another author: refused"]
    assert os.listdir(PS.inbox_dir("james", root)) == []


def test_a_stale_notes_save_is_refused_with_who_and_when_and_nothing_is_overwritten(db, root):
    jane = _jane(db)
    db.clock_box["t"] = T0  # 10:00 HST
    first = db.save_notes(jane, "Ryan's text.", P.ZERO_REV)
    _share(db, root)
    _put(root, "james", "note", op="field", pid=jane, base=P.ZERO_REV, text="James's text.", rid="rid-stale1")
    assert PS.drain(db, PILOTS, root, now=T0S)["refused"] == 1
    assert db.answers("james")[0] == {"rid": "rid-stale1", "ok": False, "at": db.answers("james")[0]["at"],
                                      "why": "Not saved: changed by ryan at 10:00 HST; your text is still in the box"}
    assert db.record(jane)["notes"]["text"] == "Ryan's text."
    # on the current rev it saves, and the replaced version is kept for Ryan's restore
    _put(root, "james", "note", now=T0S + 1, op="field", pid=jane, base=first["rev"], text="James's text.",
         rid="rid-fresh1")
    assert PS.drain(db, PILOTS, root, now=T0S + 1)["applied"] == 1
    rec = db.record(jane)
    assert rec["notes"]["by"] == "james" and [h["text"] for h in rec["notes_hist"]] == ["Ryan's text."]
    back = db.restore_notes(jane, rec["notes_hist"][0]["id"], rec["notes"]["rev"])
    assert back["text"] == "Ryan's text." and back["by"] == "ryan"


def test_a_stale_or_invalid_field_edit_is_refused_without_echoing_the_value(db, root):
    jane = _jane(db)
    _share(db, root)
    rev = db.record(jane)["rev"]
    _put(root, "james", "edit", op="set", pid=jane, field="doh", value="2001-05-02", rev=rev + 5, rid="rid-edit01")
    _put(root, "james", "edit", now=T0S + 1, op="set", pid=jane, field="doh", value="not-a-date-SENTINEL", rev=rev,
         rid="rid-edit02")
    _put(root, "james", "edit", now=T0S + 2, op="set", pid=jane, field="phones",
         value=json.dumps([{"label": "mobile", "number": "808-555-0199"}]), rev=rev, rid="rid-edit03")
    assert PS.drain(db, PILOTS, root, now=T0S + 3) == {"applied": 1, "refused": 2, "scrub": False}
    why = [a["why"] for a in db.answers("james")]
    assert why == ["Not saved: the record changed since you opened it; your change is still in the box",
                   "Not saved: that value is not valid for doh", "Saved"]
    assert "SENTINEL" not in json.dumps(db.answers("james"))
    rec = db.record(jane)
    assert rec["fields"]["doh"]["value"] == "2001-05-01"
    assert rec["fields"]["phones"]["value"] == [{"label": "mobile", "number": "808-555-0199", "tel": "+18085550199"}]
    assert rec["fields"]["phones"]["by"] == "james"


def test_retract_is_for_his_own_entries_only_and_asks_for_a_scrub(db, root):
    jane = _jane(db)
    ryans = db.add_entry(jane, "Ryan's entry.", True, "rid-ryan01")
    his = db.add_entry(jane, "James's entry.", True, "rid-jam001", by="james")
    _share(db, root)
    _put(root, "james", "note", op="retract", pid=jane, entry=ryans, rid="rid-ret001")
    _put(root, "james", "note", now=T0S + 1, op="retract", pid=jane, entry=his, rid="rid-ret002")
    assert PS.drain(db, PILOTS, root, now=T0S + 2) == {"applied": 1, "refused": 1, "scrub": True}
    assert [a["why"] for a in db.answers("james")] == ["Not saved: only your own notes can be taken back", "Saved"]
    ents = {e["eid"]: e for e in db.record(jane)["entries"]}
    assert ents[ryans]["text"] == "Ryan's entry." and ents[his]["text"] == "" and ents[his]["gone"] == "retracted"


def test_an_unshared_pilot_a_stale_file_and_an_unknown_record_are_refused(db, root):
    jane = _jane(db)
    _share(db, root)  # Ryan turned pilot3's share off
    PS.ensure_dirs(root, ["pilot3"])
    _put(root, "pilot3", "note", op="add", pid=jane, text="Not shared with me.", rid="rid-p30001")
    _put(root, "james", "note", now=T0S - 25 * 3600, op="add", pid=jane, text="A day old.", rid="rid-old001")
    _put(root, "james", "note", op="add", pid="p00000fffff", text="Nobody.", rid="rid-none01")
    assert PS.drain(db, PILOTS, root, now=T0S) == {"applied": 0, "refused": 3, "scrub": False}
    assert db.answers("pilot3")[0]["why"] == "Not saved: Ryan has not shared the pilot database with you"
    assert sorted(a["why"] for a in db.answers("james")) == [
        "Not saved: that pilot is not in Ryan's pilot database", "Not saved: too old, send it again"]
    assert db.record(jane)["entries"] == []
    for p in PILOTS:
        assert os.listdir(PS.inbox_dir(p, root)) == []


def test_the_same_rid_again_answers_the_same_and_adds_nothing(db, root):
    jane = _jane(db)
    _share(db, root)
    for i in range(2):
        _put(root, "james", "note", now=T0S + i, op="add", pid=jane, text="Once.", rid="rid-once01")
        assert PS.drain(db, PILOTS, root, now=T0S + i)["applied"] == 1
    assert len(db.record(jane)["entries"]) == 1 and len(db.answers("james")) == 1


def test_quotas_come_from_the_act_log(db, root):
    jane = _jane(db)
    _share(db, root)
    lim = dict(roles.PILOTDB_NOTE_LIMITS, adds_per_day=2, changes_per_day=1, edits_per_day=1)
    for i in range(3):
        _put(root, "james", "note", now=T0S + i, op="add", pid=jane, text=f"note {i}", rid=f"rid-add00{i}")
    assert PS.drain(db, PILOTS, root, limits=lim, now=T0S + 3) == {"applied": 2, "refused": 1, "scrub": False}
    assert db.answers("james")[-1]["why"] == "Not saved: over 2 notes in 24 h"
    base = P.ZERO_REV
    for i in range(2):
        _put(root, "james", "note", now=T0S + 10 + i, op="field", pid=jane, base=base, text=f"field {i}",
             rid=f"rid-fld00{i}")
        PS.drain(db, PILOTS, root, limits=lim, now=T0S + 12)
        base = db.record(jane)["notes"]["rev"]
    assert db.answers("james")[-1]["why"] == "Not saved: over 1 changes in 24 h"
    for i in range(2):
        _put(root, "james", "edit", now=T0S + 20 + i, op="set", pid=jane, field="seat", value="FO",
             rev=db.record(jane)["rev"], rid=f"rid-edt00{i}")
        PS.drain(db, PILOTS, root, limits=lim, now=T0S + 22)
    assert db.answers("james")[-1]["why"] == "Not saved: over 1 edits in 24 h"
    # a day later the quota is free again; Ryan's own writes never count
    db.clock_box["t"] = T0 + timedelta(hours=25)
    assert db.acts("james", ("add",)) == 0 and db.acts("ryan", ("add", "field", "edit")) == 0


def test_only_the_last_answers_are_kept(db):
    for i in range(25):
        db.clock_box["t"] = T0 + timedelta(seconds=i)
        db.put_answer("james", f"rid-{i:06d}", True, "Saved")
    a = db.answers("james")
    assert len(a) == roles.PILOTDB_NOTE_LIMITS["answers"] == 20 and a[-1]["rid"] == "rid-000024"


def test_a_planted_name_a_symlink_and_an_oversized_file_never_reach_the_database(db, root, tmp_path):
    jane = _jane(db)
    _share(db, root)
    box = PS.inbox_dir("james", root)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"v": 1, "by": "james", "cmd": "note", "op": "add", "pid": jane, "text": "via link",
                                  "rid": "rid-link01"}))
    os.symlink(str(secret), os.path.join(box, "1763236800000-rid-link01.json"))
    open(os.path.join(box, "not-a-command.txt"), "w").write("x")
    open(os.path.join(box, "1763236800001-rid-big001.json"), "w").write("{" + " " * (PS.INBOX_MAX_BYTES + 10) + "}")
    r = PS.drain(db, PILOTS, root, now=T0S)
    assert r["applied"] == 0 and r["refused"] == 2 and db.record(jane)["entries"] == []
    assert os.listdir(box) == [] and secret.exists()
    assert {a["why"] for a in db.answers("james")} == {"Not saved: it could not be read, send it again"}


def test_the_inbox_file_is_private_and_made_exclusively(db, root):
    jane = _jane(db)
    _share(db, root)
    name = PS.inbox_put("james", "note", {"op": "add", "pid": jane, "text": "x", "rid": "rid-mode01", "by": "ryan"},
                        root, now=T0S)
    path = os.path.join(PS.inbox_dir("james", root), name)
    assert PT.INBOX_NAME_RE.fullmatch(name) and _mode(path) == 0o600
    body = json.load(open(path))
    assert body["by"] == "james" and body["cmd"] == "note" and set(body) == {"v", "by", "at", "cmd", "op", "pid", "text",
                                                                           "rid"}
    with pytest.raises(OSError):  # no inbox folder: Ryan turned his share off
        PS.inbox_put("pilot3", "note", {"op": "add", "pid": jane, "text": "x", "rid": "rid-mode02"}, root)
    os.rmdir(PS.inbox_dir("pilot3", root)) if os.path.isdir(PS.inbox_dir("pilot3", root)) else None
    os.symlink(PS.inbox_dir("james", root), PS.inbox_dir("pilot3", root))
    with pytest.raises(OSError):  # a symlinked folder is never followed
        PS.inbox_put("pilot3", "note", {"op": "add", "pid": jane, "text": "x", "rid": "rid-mode03"}, root)


def test_the_edit_fields_are_the_databases_fields():
    # 1.7.10: domicile (the base of the award's category) is new in the database; a portal pilot's edit fields are
    # the contract's and do not hold it yet (the contract is unchanged by it), so his edit of it is refused
    assert roles.PILOTDB_EDIT_FIELDS == tuple(f for f in P.FIELDS if f != "domicile")
    assert roles.PILOTDB_NOTE_LIMITS["entry_max"] == P.ENTRY_MAX and roles.PILOTDB_NOTE_LIMITS["field_max"] == P.FIELD_MAX
    assert roles.PILOTDB_NOTE_LIMITS["entries_per_record"] == P.ENTRIES_PER_RECORD
    assert roles.PILOTDB_NOTE_LIMITS["why_max"] == P.WHY_MAX

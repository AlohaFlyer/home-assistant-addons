"""1.7.9 (contract 1 revision 4; spec 11.3), as of 1.7.10 (Ryan's decisions of Nov 15: shared 100%, on by default): a
shared pilot's Watcher and the pilot database.

His Watcher never opens the database. While the database is shared with him (the default), it signs his own file
(every live record) into out/files/pilotdb.json unchanged, synthesizes sensor.<prefix>_pilotdb (state.json only:
which record of the file the pilot his pilot card shows is; the answers; the pending rids) and hands each checked
pilotdb/note and pilotdb/edit to the admin's inbox with the author taken from the instance. While Ryan has his
share off there is no file, the sensor says off and every command is refused. Nothing here loads FLICA, wakes the
loop or logs a text, a name or a number. The whole path (his portal's command, his Watcher, the admin's drain, the
file back) is run end to end.
Synthetic pilots only ("Doe, Jane", 10001, 555-01xx, example.com)."""
import json
import logging
import os
import stat
from datetime import datetime, timezone

import pytest

import pdbshare as PS
import pilotdb as P
import portal as PT
import roles
from test_pilotdb_store import CONTACTS, LIST

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
SECRETS = ("Doe", "Jane", "Roe", "10001", "10002", "555-01", "example.com", "NOTE-SENTINEL")


@pytest.fixture
def james(portal_pilot, tmp_path, monkeypatch):
    """(W, db, root): pilot james's Watcher with its portal started (no threads), Ryan's database in the same share
    folder (the admin's side is driven by hand: pdbshare.write_files and drain)."""
    W, _ha = portal_pilot("james")
    root = str(tmp_path / "share" / "flight_watcher" / "pilotdb")
    monkeypatch.setattr(W, "PILOTDB_SHARE", root)
    monkeypatch.setattr(W, "PDBV", {"view": None, "lock": W.threading.RLock(), "sig": None, "shown": None, "local": None})
    db = P.PilotDB(str(tmp_path / "pilotdb.sqlite"), clock=lambda: T0)
    db.merge_list(LIST)
    db.merge_contacts(CONTACTS)
    assert W.portal_start(threads=False)
    yield W, db, root
    db.close()


def _share(W, db, root, on=True):
    db.set_share("james", on)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()


def _attrs(W):
    return W.pilotdb_state()[f"sensor.{W.T}_pilotdb"]


def _payload(W, name, kind):
    key = PT.load_key(W.PORTAL_KEY_FILE, create=False)
    with open(os.path.join(W.PORTAL_DIR, "out", name), encoding="utf-8") as f:
        return json.loads(PT.verify(PT.public_id(key), json.load(f), kind, W.INSTANCE))


def _show(W, emp, name):
    W.PILOT_SHOWN["p"] = {"emp": emp, "name": name, "status": "ok"}


def _inbox(root):
    d = PS.inbox_dir("james", root)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _note(**kw):
    return json.dumps(kw)


# ---------------------------------------------------------------- Ryan's off switch
def test_while_ryan_has_his_share_off_there_is_no_file_and_every_command_is_refused(james, caplog):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "NOTE-SENTINEL", P.ZERO_REV)
    _share(W, db, root, on=False)  # the admin's pass with his share turned off
    W.portal_export_once(full=True)
    st = _attrs(W)
    assert st["state"] == "off" and st["attributes"]["shown"] is None and st["attributes"]["count"] == 0
    assert "pilotdb.json" not in os.listdir(os.path.join(W.PORTAL_DIR, "out", "files"))
    assert "pilotdb" not in _payload(W, "manifest.json", "manifest")["files"]
    _show(W, "10001", "Doe, Jane")
    assert _attrs(W)["attributes"]["shown"] is None  # nothing while not shared
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        ok, why = W.pilotdb_cmd("note", _note(op="add", pid=jane, text="NOTE-SENTINEL", rid="rid-off001"))
    assert (ok, why) == (False, "Not saved: Ryan has not shared the pilot database with you")
    assert _inbox(root) == []
    a = _attrs(W)["attributes"]["answers"]
    assert [(x["rid"], x["ok"], x["why"]) for x in a] == [("rid-off001", False, why)]
    assert "pilotdb note add from portal: refused" in caplog.text
    for s in SECRETS:
        assert s not in caplog.text, s


def test_the_subscriptions_are_a_portal_pilots_only(james):
    W, _db, _root = james
    subs = dict(roles.subscriptions("james", portal=True))
    assert subs["pilotdb/note"] == 1 and subs["pilotdb/edit"] == 1
    assert "pilotdb/note" not in dict(roles.subscriptions("james", portal=False))
    assert not [s for s, _ in roles.subscriptions("", portal=True) if s.startswith("pilotdb/")]  # never the admin
    assert not roles.sub_allowed("pilotdb/note", "", portal=True)
    assert not roles.sub_allowed("pilotdb/edit", "james", portal=False)


# ---------------------------------------------------------------- shared: the file and the sensor
def test_the_file_is_signed_unchanged_and_exported_before_the_state_that_names_it(james):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    order = []
    orig = W.EXPORT["writer"].write
    W.EXPORT["writer"].write = lambda kind, text: (order.append(kind), orig(kind, text))[1]
    _share(W, db, root)
    W.portal_export_once()
    assert order.index("file:pilotdb") < order.index("state")
    assert "manifest" in order and order.index("file:pilotdb") < order.index("manifest")
    text = open(PS.export_path("james", root), encoding="utf-8").read()
    served = _payload(W, "files/pilotdb.json", "file:pilotdb")
    assert served == json.loads(text)
    st = _payload(W, "state.json", "state")["states"][f"sensor.{W.T}_pilotdb"]
    a = st["attributes"]
    assert st["state"] == "on" and a["count"] == 2 and a["file_key"] == "0" * 32  # every live record
    assert a["rev"] == __import__("hashlib").sha256(text.encode()).hexdigest()[:12]
    assert a["limits"] == PT.pilotdb_limits() and a["pending"] == [] and a["answers"] == []
    assert set(a) == set(PT.PILOTDB_STATE_KEYS["attributes"])
    assert "pilotdb" in _payload(W, "manifest.json", "manifest")["files"]
    # share off: the file leaves out/files and the manifest, the sensor says off
    _share(W, db, root, on=False)
    W.portal_export_once()
    assert "pilotdb.json" not in os.listdir(os.path.join(W.PORTAL_DIR, "out", "files"))
    assert "pilotdb" not in _payload(W, "manifest.json", "manifest")["files"]
    assert _payload(W, "state.json", "state")["states"][f"sensor.{W.T}_pilotdb"]["state"] == "off"


def test_shown_says_which_record_of_the_file_the_pilot_cards_pilot_is(james):
    W, db, root = james
    _share(W, db, root)
    assert _attrs(W)["attributes"]["shown"] is None  # nobody looked up
    # 1.7.10: at once, whatever the lookup's status (the 1.7.9 "only after the lookup ran" rule is gone)
    W.PILOT_SHOWN["p"] = {"emp": "10001", "name": "Doe, Jane", "status": "loading"}
    assert W.pilotdb_watch()
    W.portal_export_once()
    state = _payload(W, "state.json", "state")
    sh = state["states"][f"sensor.{W.T}_pilotdb"]["attributes"]["shown"]
    assert sh == {"emp": "10001", "pid": db.find("10001")} and set(sh) <= set(PT.PILOTDB_STATE_KEYS["shown"])
    # the record itself is in the file (every field, phones and emails), never in the state
    assert "555-01" not in json.dumps(state["states"][f"sensor.{W.T}_pilotdb"]) and "example.com" not in json.dumps(
        state["states"][f"sensor.{W.T}_pilotdb"])
    rec = next(r for r in _payload(W, "files/pilotdb.json", "file:pilotdb")["records"] if r["pid"] == sh["pid"])
    assert (rec["emp"], rec["name"], rec["sen"], rec["doh"], rec["status"]) == (
        "10001", "Doe, Jane A.", "812", "2001-05-01", "SLOA")
    assert rec["phones"] == [{"label": "mobile", "number": "808-555-0101", "tel": "+18085550101"}]
    assert rec["emails"] == ["jane.doe@example.com"] and rec["rev"] == db.record(sh["pid"])["rev"]
    # the pilot_schedule contact read from HA is still dropped (MASK_DROP unchanged)
    assert PT.mask({"contact": {"phones": ["x"]}, "emp": "1"}) == {"emp": "1"}
    _show(W, "10002", "Roe, Rick")
    W.pilotdb_watch()
    assert _attrs(W)["attributes"]["shown"] == {"emp": "10002", "pid": db.find("10002")}
    # somebody the database does not hold
    _show(W, "99999", "Nobody, Nell")
    assert _attrs(W)["attributes"]["shown"] == {"emp": "99999", "none": True}
    assert len(json.dumps(_attrs(W))) < 4096


def test_no_limit_on_how_many_pilots_the_card_follows(james):
    """The 1.7.9 cap of 20 distinct pilots an hour limited what a shared pilot saw of the database; his file holds
    every record now, so it is gone. (The FLICA lookup's own hourly cap and budgets are untouched: test_release_a_lookup.)"""
    W, db, root = james
    _share(W, db, root)
    assert not hasattr(W, "PILOTDB_BRIEF_PER_H")
    for i in range(30):
        _show(W, str(20000 + i), "")
        assert _attrs(W)["attributes"]["shown"] == {"emp": str(20000 + i), "none": True}
    _show(W, "10001", "Doe, Jane")
    assert _attrs(W)["attributes"]["shown"]["pid"] == db.find("10001")
    assert "pdb_briefs" not in W.S


def test_the_name_lookup_rows_come_from_his_file(james):
    W, db, root = james
    assert W.pilotdb_name_rows() == ([], "")  # no file yet
    _share(W, db, root)
    rows, sig = W.pilotdb_name_rows()
    # 1.7.11 (FW-0078): each row carries the record's base too ('' when it has none)
    assert sorted(rows) == [("10001", "Doe", "Jane A.", "", ""), ("10002", "Roe", "Rick", "CA", "")] and sig.startswith("file:")
    _share(W, db, root, on=False)
    assert W.pilotdb_name_rows() == ([], "")  # Ryan turned his share off: nothing of the database is searched


def test_no_roster_is_written_and_nothing_of_the_database_is_logged(james, caplog, tmp_path):
    W, db, root = james
    with caplog.at_level(logging.DEBUG):
        _share(W, db, root)
        _show(W, "10001", "Doe, Jane")
        W.pilotdb_watch()
        W.portal_export_once(full=True)
    names = [f for _, _, fs in os.walk(str(tmp_path)) for f in fs]
    assert not [n for n in names if "roster" in n]
    for s in SECRETS:
        assert s not in caplog.text, s


# ---------------------------------------------------------------- commands
def test_a_note_goes_to_the_admins_inbox_with_the_instance_as_author(james, caplog, monkeypatch):
    W, db, root = james
    jane = db.find("10001")
    _share(W, db, root)
    _show(W, "10001", "Doe, Jane")
    W.pilotdb_watch()
    # nothing of this may touch FLICA, the gate, pilot_cmd or the loop
    for name in ("pilot_cmd", "gate_wait", "pilot_check"):
        if hasattr(W, name):
            monkeypatch.setattr(W, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)))
    W.WAKE.clear()
    W.S.pop("pilot_req", None)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        ok, why = W.pilotdb_cmd("note", _note(op="add", pid=jane, text="NOTE-SENTINEL flew with her", rid="rid-add001"))
    assert (ok, why) == (True, "")
    assert not W.WAKE.is_set() and "pilot_req" not in W.S
    names = _inbox(root)
    assert len(names) == 1 and PT.INBOX_NAME_RE.fullmatch(names[0]) and names[0].endswith("-rid-add001.json")
    path = os.path.join(PS.inbox_dir("james", root), names[0])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    body = json.load(open(path))
    assert body["by"] == "james" and body["cmd"] == "note" and body["op"] == "add" and body["pid"] == jane
    assert _attrs(W)["attributes"]["pending"] == ["rid-add001"]
    assert "pilotdb note add from portal: queued" in caplog.text
    for s in SECRETS:
        assert s not in caplog.text, s
    # the same command again (a retry) makes no second file
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="NOTE-SENTINEL flew with her", rid="rid-add001"))[0]
    assert len(_inbox(root)) == 1
    # the admin applies it; the answer comes back through his file and the rid leaves pending
    assert PS.drain(db, ["james"], root)["applied"] == 1
    PS.write_files(db, ["james"], root)
    assert W.pilotdb_watch()
    a = _attrs(W)["attributes"]
    assert a["pending"] == [] and [(x["rid"], x["ok"], x["why"]) for x in a["answers"]] == [("rid-add001", True, "Saved")]
    e = db.record(jane)["entries"][0]
    assert (e["by"], e["text"]) == ("james", "NOTE-SENTINEL flew with her")
    W.portal_export_once()
    rec = next(r for r in _payload(W, "files/pilotdb.json", "file:pilotdb")["records"] if r["pid"] == jane)
    assert rec["entries"][0]["mine"] is True


def test_a_payload_author_or_employee_number_is_refused(james):
    W, db, root = james
    jane = db.find("10001")
    _share(W, db, root)
    _show(W, "10001", "Doe, Jane")
    for extra in ({"by": "ryan"}, {"emp": "10001"}, {"name": "Doe, Jane"}):
        ok, why = W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x", rid="rid-by0001", **extra))
        assert (ok, why) == (False, "Not saved: it could not be read, send it again")
    assert _inbox(root) == []


def test_every_record_of_his_file_takes_a_note_and_a_pid_that_is_not_in_it_is_refused(james):
    W, db, root = james
    jane, rick = db.find("10001"), db.find("10002")
    _share(W, db, root)
    # 1.7.10: his file holds every live record, so no lookup and no note is needed first
    assert W.pilotdb_cmd("note", _note(op="add", pid=rick, text="x", rid="rid-rick01")) == (True, "")
    assert W.pilotdb_cmd("edit", _note(op="set", pid=jane, field="seat", value="FO", rev=1, rid="rid-jane02")) == (
        True, "")
    assert W.pilotdb_cmd("note", _note(op="add", pid="p00000fffff", text="x", rid="rid-none01")) == (
        False, "Not saved: that pilot is not in Ryan's pilot database")
    assert len(_inbox(root)) == 2


def test_the_op_rules_the_generic_checker_cannot_say(james):
    W, db, root = james
    jane = db.find("10001")
    ryans = db.add_entry(jane, "Ryan's entry.", True, "rid-ryan01")
    his = db.add_entry(jane, "James's entry.", True, "rid-jam001", by="james")
    _share(W, db, root)
    bad = "Not saved: it could not be read, send it again"
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x", entry=his, rid="rid-op0001")) == (False, bad)
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x", base=P.ZERO_REV, rid="rid-op0002")) == (False, bad)
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x" * 2001, rid="rid-op0003")) == (
        False, "Not saved: a note is at most 2000 characters")
    assert W.pilotdb_cmd("note", _note(op="retract", pid=jane, entry=ryans, rid="rid-op0004")) == (
        False, "Not saved: only your own notes can be taken back")
    assert W.pilotdb_cmd("edit", _note(op="unset", pid=jane, field="seat", value="FO", rev=1, rid="rid-op0005")) == (
        False, bad)
    assert W.pilotdb_cmd("edit", _note(op="set", pid=jane, field="emp", value="1", rev=1, rid="rid-op0006")) == (
        False, bad)
    assert _inbox(root) == []
    assert W.pilotdb_cmd("note", _note(op="retract", pid=jane, entry=his, rid="rid-op0007")) == (True, "")
    assert W.pilotdb_cmd("note", _note(op="field", pid=jane, base=P.ZERO_REV, text="", rid="rid-op0008")) == (True, "")
    assert W.pilotdb_cmd("something", "{}") == (False, "off")


def test_at_most_ten_commands_wait_and_the_rest_are_busy(james):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)
    for i in range(10):
        assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text=f"n{i}", rid=f"rid-pend{i:02d}")) == (True, "")
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="n10", rid="rid-pend10")) == (
        False, "Busy: try again in a minute")
    assert len(_inbox(root)) == roles.PILOTDB_NOTE_LIMITS["pending"] == 10
    assert len(_attrs(W)["attributes"]["pending"]) == 10


def test_pending_commands_are_answered_when_the_share_goes_off(james):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="late", rid="rid-late01")) == (True, "")
    _share(W, db, root, on=False)
    a = _attrs(W)["attributes"]
    assert a["pending"] == [] and a["answers"][-1]["why"] == "Not saved: Ryan has not shared the pilot database with you"
    # the admin's drain refuses the waiting file too and writes nothing
    assert PS.drain(db, ["james"], root)["refused"] == 1 and db.record(jane)["entries"] == []


def test_a_field_edit_travels_the_same_way_and_a_stale_one_comes_back_refused(james):
    W, db, root = james
    jane = db.find("10001")
    _share(W, db, root)
    _show(W, "10001", "Doe, Jane")
    W.pilotdb_watch()

    def rec():
        W.portal_export_once()
        return next(r for r in _payload(W, "files/pilotdb.json", "file:pilotdb")["records"] if r["pid"] == jane)
    rev = rec()["rev"]
    assert W.pilotdb_cmd("edit", _note(op="set", pid=jane, field="seat", value="FO", rev=rev, why="Award line",
                                       rid="rid-edit01")) == (True, "")
    assert W.pilotdb_cmd("edit", _note(op="set", pid=jane, field="equip", value="330", rev=rev, rid="rid-edit02")) == (
        True, "")
    assert json.load(open(os.path.join(PS.inbox_dir("james", root), _inbox(root)[0])))["cmd"] == "edit"
    assert PS.drain(db, ["james"], root) == {"applied": 1, "refused": 1, "scrub": False}
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    a = _attrs(W)["attributes"]
    assert [(x["rid"], x["ok"]) for x in a["answers"]] == [("rid-edit01", True), ("rid-edit02", False)]
    assert a["answers"][1]["why"] == ("Not saved: the record changed since you opened it; your change is still in "
                                      "the box")
    assert a["shown"] == {"emp": "10001", "pid": jane}
    r = rec()
    assert r["seat"] == "FO" and r["edited"] == ["seat"] and r["rev"] == rev + 1
    assert db.record(jane)["fields"]["seat"]["by"] == "james"


def test_on_message_routes_both_subs_and_the_admin_refuses_them(james, portal_pilot):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)

    class Msg:
        def __init__(self, topic, payload):
            self.topic, self.payload = topic, payload.encode()
    W.on_message(None, None, Msg(f"{W.T}/pilotdb/note", _note(op="add", pid=jane, text="via mqtt", rid="rid-mqtt01")))
    W.on_message(None, None, Msg(f"{W.T}/pilotdb/edit",
                                 _note(op="set", pid=jane, field="seat", value="FO", rev=1, rid="rid-mqtt02")))
    assert len(_inbox(root)) == 2


def test_the_manifest_names_revision_4_and_the_pilotdb_subs(james):
    W, _db, _root = james
    W.portal_export_once(full=True)
    m = _payload(W, "manifest.json", "manifest")
    assert m["revision"] == 6 and {"pilotdb/note", "pilotdb/edit"} <= set(m["mqtt_subs"])  # 1.7.11: 6
    assert "flight-watcher-pilotdb-card-james.js" in m["cards"]
    pilot_tab = next(t for t in m["layout"]["tabs"] if t["id"] == "pilot")
    types = [c["type"] for c in pilot_tab["cards"]]
    assert types.index("custom:flight-watcher-pilotdb-card-james") == types.index("custom:flight-watcher-pilot-card-james") + 1
    assert [t["id"] for t in m["layout"]["tabs"]] == list(roles.PORTAL_TABS)


def test_the_spool_takes_both_subs_and_no_other_pilotdb_sub(james):
    W, _db, _root = james
    sp = PT.Spool("james", now=lambda: 1763600000.0)
    for i, (sub, ok) in enumerate((("pilotdb/note", True), ("pilotdb/edit", True), ("pilotdb/share", False),
                                   ("pilotdb/ai", False), ("pilotdb/forget", False))):
        d = {"fwp": 1, "pilot": "james", "ts": 1763600000000, "session": "5e55105e55105e55", "sub": sub,
             "payload": _note(op="add", pid="p0123456789", text="x", rid="rid-spool1") if sub == "pilotdb/note" else
             _note(op="set", pid="p0123456789", field="seat", value="FO", rev=1, rid="rid-spool2")}
        if ok:
            assert sp._check(d, "%016x" % i)[1] == sub
        else:
            with pytest.raises(PT.PortalError, match="sub not allowed"):
                sp._check(d, "%016x" % i)


def test_a_command_whose_file_vanished_is_answered_and_leaves_pending(james):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="lost", rid="rid-lost01")) == (True, "")
    for n in _inbox(root):
        os.unlink(os.path.join(PS.inbox_dir("james", root), n))
    W.pilotdb_watch()
    assert _attrs(W)["attributes"]["pending"] == ["rid-lost01"]  # the admin may be mid-pass: wait
    W.pilotdb_watch(now=__import__("time").time() + W.PILOTDB_LOST_S + 1)
    a = _attrs(W)["attributes"]
    assert a["pending"] == [] and a["answers"][-1] == {"rid": "rid-lost01", "ok": False, "at": a["answers"][-1]["at"],
                                                       "why": "Not saved: it could not be read, send it again"}


def test_the_synthesized_sensor_stays_small_at_its_worst(james):
    """The longest answers and a full pending list: under the 12 KB a sensor may have (it is state.json only, never
    an HA entity). 1.7.10: a record's phones and emails are in the file, never in the sensor."""
    W, db, root = james
    jane = db.find("10001")
    db.set_field(jane, "phones", json.dumps([{"label": "mobile", "number": f"808-555-01{i:02d}"} for i in range(4)]),
                 db.record(jane)["rev"])
    db.set_field(jane, "emails", json.dumps([f"jane.{'x' * 60}{i}@example.com" for i in range(3)]),
                 db.record(jane)["rev"])
    longest = max(roles.PILOTDB_ANSWERS, key=len)
    for i in range(20):
        db.put_answer("james", ("rid-%02d" % i).ljust(40, "x"), False, longest)
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)
    _show(W, "10001", "Doe, Jane")
    for i in range(10):
        W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x", rid=("pend-%02d" % i).ljust(40, "x")))
    W.pilotdb_watch()
    st = _attrs(W)
    assert len(st["attributes"]["answers"]) == 20 and len(st["attributes"]["pending"]) == 10
    assert st["attributes"]["shown"] == {"emp": "10001", "pid": jane} and "555-01" not in json.dumps(st)
    assert len(json.dumps(st)) < 12 * 1024

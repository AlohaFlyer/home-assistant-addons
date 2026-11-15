"""1.7.9 (contract 1 revision 4; spec 11.3; Ryan's Nov 14 decisions): a shared pilot's Watcher and the pilot database.

His Watcher never opens the database. While Ryan shares it, it signs his own file into out/files/pilotdb.json
unchanged, synthesizes sensor.<prefix>_pilotdb (state.json only: the brief of the pilot his pilot card shows, with
that one pilot's phones and emails, B23; the answers; the pending rids) and hands each checked pilotdb/note and
pilotdb/edit to the admin's inbox with the author taken from the instance. While it is off there is no file, the
sensor says off and every command is refused. Nothing here loads FLICA, wakes the loop or logs a text, a name or a
number. The whole path (his portal's command, his Watcher, the admin's drain, the file back) is run end to end.
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
    monkeypatch.setattr(W, "PILOTDB_ROSTER", root)  # the admin's side is driven by hand into one folder here
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
    W.PILOT_SHOWN["p"] = {"emp": emp, "name": name, "status": "ok"}  # a lookup that ran (1.7.9 review: only then a brief)


def _inbox(root):
    d = PS.inbox_dir("james", root)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _note(**kw):
    return json.dumps(kw)


# ---------------------------------------------------------------- off by default
def test_while_ryan_has_not_shared_there_is_no_file_and_every_command_is_refused(james, caplog):
    W, db, root = james
    jane = db.find("10001")
    db.save_notes(jane, "NOTE-SENTINEL", P.ZERO_REV)
    PS.write_files(db, ["james"], root)  # the admin's pass with every share off
    W.pilotdb_watch()
    W.portal_export_once(full=True)
    st = _attrs(W)
    assert st["state"] == "off" and st["attributes"]["shown"] is None and st["attributes"]["count"] == 0
    assert "pilotdb.json" not in os.listdir(os.path.join(W.PORTAL_DIR, "out", "files"))
    assert "pilotdb" not in _payload(W, "manifest.json", "manifest")["files"]
    _show(W, "10001", "Doe, Jane")
    assert _attrs(W)["attributes"]["shown"] is None  # no brief, no contact while not shared
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
    assert st["state"] == "on" and a["count"] == 1 and a["file_key"] == "0" * 32
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


def test_the_shown_brief_carries_that_one_pilots_phones_and_emails_and_nobody_elses(james):
    W, db, root = james
    _share(W, db, root)
    assert _attrs(W)["attributes"]["shown"] is None  # nobody looked up
    _show(W, "10001", "Doe, Jane")
    assert W.pilotdb_watch()
    W.portal_export_once()
    text = json.dumps(_payload(W, "state.json", "state"))
    sh = _payload(W, "state.json", "state")["states"][f"sensor.{W.T}_pilotdb"]["attributes"]["shown"]
    assert set(sh) <= set(PT.PILOTDB_STATE_KEYS["shown"])
    assert (sh["emp"], sh["pid"], sh["name"], sh["sen"], sh["doh"], sh["status"]) == (
        "10001", db.find("10001"), "Doe, Jane A.", "812", "2001-05-01", "SLOA")
    assert sh["rev"] == db.record(sh["pid"])["rev"]
    assert sh["contact"] == {"phones": [{"label": "mobile", "number": "808-555-0101", "tel": "+18085550101"}],
                             "emails": ["jane.doe@example.com"]}
    assert "Roe" not in text and "10002" not in text  # the other record of the roster is nowhere
    # the pilot_schedule contact read from HA is still dropped (MASK_DROP unchanged)
    assert PT.mask({"contact": {"phones": ["x"]}, "emp": "1"}) == {"emp": "1"}
    # another pilot looked up: his brief, no contact (he has none), and Jane's is gone
    _show(W, "10002", "Roe, Rick")
    W.pilotdb_watch()
    W.portal_export_once()
    text = json.dumps(_payload(W, "state.json", "state"))
    assert "555-01" not in text and "example.com" not in text and "Roe, Rick" in text
    # somebody the database does not hold
    _show(W, "99999", "Nobody, Nell")
    assert _attrs(W)["attributes"]["shown"] == {"emp": "99999", "none": True}
    assert len(json.dumps(_attrs(W))) < 4096


def test_the_roster_is_never_exported_or_logged(james, caplog):
    W, db, root = james
    with caplog.at_level(logging.DEBUG):
        _share(W, db, root)
        _show(W, "10001", "Doe, Jane")
        W.pilotdb_watch()
        W.portal_export_once(full=True)
    out = os.path.join(W.PORTAL_DIR, "out")
    names = [f for _, _, fs in os.walk(out) for f in fs]
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
    rec = _payload(W, "files/pilotdb.json", "file:pilotdb")["records"][0]
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


def test_a_pid_he_did_not_look_up_is_no_oracle(james):
    W, db, root = james
    jane, rick = db.find("10001"), db.find("10002")
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    _share(W, db, root)
    # Rick has no shared note and is not shown: refused, and exactly like a pid that does not exist
    a = W.pilotdb_cmd("note", _note(op="add", pid=rick, text="x", rid="rid-rick01"))
    b = W.pilotdb_cmd("note", _note(op="add", pid="p00000fffff", text="x", rid="rid-none01"))
    assert a == b == (False, "Not saved: look the pilot up first")
    assert W.pilotdb_cmd("edit", _note(op="set", pid=rick, field="seat", value="FO", rev=1, rid="rid-rick02")) == a
    # a noted pilot is reachable without a lookup; a looked-up pilot too
    assert W.pilotdb_cmd("note", _note(op="add", pid=jane, text="x", rid="rid-jane01")) == (True, "")
    _show(W, "10002", "Roe, Rick")
    assert W.pilotdb_cmd("note", _note(op="add", pid=rick, text="x", rid="rid-rick03")) == (True, "")
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
    rev = _attrs(W)["attributes"]["shown"]["rev"]
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
    assert a["shown"]["seat"] == "FO" and a["shown"]["edited"] == ["seat"] and a["shown"]["rev"] == rev + 1
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
    assert m["revision"] == 4 and {"pilotdb/note", "pilotdb/edit"} <= set(m["mqtt_subs"])
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
    """The longest answers, a full pending list and a shown pilot with 4 phones and 3 emails: under the 12 KB a
    sensor may have (it is state.json only, never an HA entity)."""
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
    assert len(st["attributes"]["shown"]["contact"]["phones"]) == 4
    assert len(json.dumps(st)) < 12 * 1024

"""1.7.8 (spec 10.1, B4): the admin-only ingress API of the pilot database, GET and POST api/pilotdb, on a real server
with the Watcher's own callbacks (pilotdb_get, pilotdb_post) over a database seeded from the synthetic contact list
(test_pilotdb_watcher's fixture). The ingress IP guard; a POST needs Content-Type application/json and the header
X-FW-Card: pilotdb, a body of at most 64 KB, a JSON object and known keys only; every op and its answer; the 409 shapes
(a stale field edit answers the fresh record, a stale notes save the text there now); errors and log lines never
carry a value, a name, a number or a note; search rows hold no phones or emails; the author is always ryan; the share
op is 1.7.9's; nothing loads FLICA or publishes pilot/set. Synthetic data only ("Doe, Jane" 10001, 555-01xx,
example.com)."""
import http.client
import json
import logging
import os
import socket

import pytest

import web
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pilotdb_watcher import P, SECRETS  # noqa: F401  (the seeded pilot database fixture)


class _Store:
    def recent_finds(self, n):
        return []

    def recent_matches(self, n):
        return []


def _server(get=None, post=None):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = web.serve(port, "9.9.9", lambda: [], lambda d: [], _Store(), logging.getLogger("t"), pilotdb_get=get,
                    pilotdb_post=post)
    return srv, port


@pytest.fixture
def api(P):  # noqa: F811
    db = P.pilotdb_start()
    srv, port = _server(P.pilotdb_get, P.pilotdb_post)
    yield P, db, port
    srv.shutdown()
    srv.server_close()


def _req(port, method, path, body=None, headers=None, source="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10, source_address=(source, 0))
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


CARD = {"Content-Type": "application/json", "X-FW-Card": "pilotdb"}


def _post(port, obj, headers=CARD, **kw):
    body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
    return _req(port, "POST", "/api/pilotdb", body, dict(headers, **{"Content-Length": str(len(body))}), **kw)


def _get(port, query="", **kw):
    st, h, data = _req(port, "GET", "/api/pilotdb" + (f"?{query}" if query else ""), **kw)
    return st, json.loads(data), h


def _op(port, **obj):
    st, h, data = _post(port, obj)
    assert h.get("Cache-Control") == "no-store"
    return st, json.loads(data)


def test_the_guards(api):
    P, db, port = api
    jane = db.find("10001")
    # the ingress guard: only the Supervisor's proxy (and the host itself)
    assert _req(port, "GET", "/api/pilotdb", source="127.0.0.2")[0] == 403
    assert _post(port, {"op": "keep", "pid": jane, "field": "sen"}, source="127.0.0.2")[0] == 403
    ok = {"op": "add", "pid": jane, "text": "a note", "rid": "rid-guard-1"}
    # a plain cross-site form can send neither the JSON content type nor the card's header
    st, h, data = _post(port, ok, {"Content-Type": "application/x-www-form-urlencoded", "X-FW-Card": "pilotdb"})
    assert st == 415 and json.loads(data)["field"] == "Content-Type" and h["Cache-Control"] == "no-store"
    st, _h, data = _post(port, ok, {"Content-Type": "text/plain"})
    assert st == 415
    st, _h, data = _post(port, ok, {"Content-Type": "application/json"})
    assert st == 403 and json.loads(data) == {"ok": False, "field": "X-FW-Card", "why": "is missing"}
    st, _h, data = _post(port, ok, {"Content-Type": "application/json", "X-FW-Card": "uploads"})
    assert st == 403
    # 64 KB at most; an empty body, a body that is not a JSON object, NaN
    big = json.dumps(dict(ok, text="x" * (64 * 1024))).encode()
    assert _post(port, big)[0] == 413
    assert _post(port, b"")[0] == 400
    for raw in (b"[1, 2]", b"not json", b'{"op": "add", "pid": NaN}', b"\xff\xfe"):
        st, _h, data = _post(port, raw)
        assert st == 400 and json.loads(data) == {"ok": False, "field": "body", "why": "must be a JSON object"}
    assert db.record(jane)["entries"] == []  # nothing got through
    # the content type may carry a charset
    st, _h, data = _post(port, ok, {"Content-Type": "application/json; charset=utf-8", "X-FW-Card": "pilotdb"})
    assert st == 200 and json.loads(data)["ok"]
    # unknown keys and ops are refused, never echoed
    st, r = _op(port, op="add", pid=jane, text="x", rid="rid-guard-2", by="james")
    assert (st, r) == (400, {"ok": False, "field": "keys", "why": "holds a key this op does not take"})
    st, r = _op(port, op="share", pilot="james", on=True)  # B6: sharing is 1.7.9's
    assert (st, r) == (400, {"ok": False, "field": "op", "why": "is not an operation of the pilot database"})
    st, r = _op(port, op="set", pid=jane, field="sen")
    assert (st, r["field"], r["why"]) == (400, "value", "is missing")
    # the API answers 404 on a server the Watcher gave no pilot database callbacks (a pilot instance has no Web UI)
    srv, port2 = _server()
    try:
        assert _req(port2, "GET", "/api/pilotdb")[0] == 404
        assert _post(port2, ok)[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_reads(api):
    P, db, port = api
    st, r, h = _get(port)
    assert st == 200 and h["Cache-Control"] == "no-store" and r["ok"] and r["total"] == 4 and r["page"] == 0
    assert [x["name"] for x in r["rows"]][:1] == ["Roe, Rick Jr"]  # by Sen # (13 first)
    text = json.dumps(r)
    assert "phones" not in text and "emails" not in text and "555-01" not in text and "example.com" not in text
    st, r, _h = _get(port, "q=doe")
    assert [x["emp"] for x in r["rows"]] == ["10001"]
    assert set(r["rows"][0]) == {"pid", "emp", "sen", "name", "status", "doh", "retire", "seat", "gone", "notes_n",
                                 "notes_at", "pickups_n", "flags"}
    assert _get(port, "q=s812")[1]["rows"][0]["emp"] == "10001"
    assert _get(port, "q=1000")[1]["total"] == 4
    assert _get(port, "f=status:SLOA")[1]["total"] == 1
    # the record: every field with its source and date, phones and emails (Ryan's only), the notes, the pickups
    jane = db.find("10001")
    st, r, _h = _get(port, f"pid={jane}")
    rec = r["record"]
    assert st == 200 and rec["pid"] == jane and rec["emp"] == "10001"
    f = rec["fields"]
    assert (f["sen"]["value"], f["sen"]["source"], f["sen"]["ref"]) == ("812", "contacts", "contacts 2026-11-14")
    assert f["phones"]["value"][0]["tel"] == "+18085550101" and f["emails"]["value"] == ["jane.doe@example.com"]
    assert rec["notes"] is None and rec["entries"] == [] and rec["pickups"]["summary"]["n"] == 0
    assert rec["ai_note"] is None  # the AI note (1.7.9, HOM's models) is never written in 1.7.8
    # follow mode: the pilot card's pilot
    st, r, _h = _get(port, "emp=10001&name=Doe%2C%20Jane")
    assert st == 200 and r["record"]["pid"] == jane
    st, r, _h = _get(port, "emp=99999&name=Doe%2C%20Nobody")
    assert (st, r["record"], r["why"]) == (200, None, "Not in the pilot database")
    # views
    st, r, _h = _get(port, "view=status")
    assert st == 200 and r["status"]["db"] == "ok" and r["status"]["live"] == 4
    assert [b["file"] for b in r["backups"]] == ["0/pilotdb-2026-11-15.sqlite", "1/pilotdb-2026-11-15.sqlite"]
    assert set(r["backups"][0]) == {"file", "day", "rev", "size"}  # no host path
    st, r, _h = _get(port, "view=conflicts")
    assert st == 200 and [(c["kind"], c["answers"]) for c in r["conflicts"]] == [("contact_unmatched", ["attach", "ignore"])]
    # refused reads name the key, never echo it
    for q, field in (("evil=1", "query"), ("pid=x1", "pid"), ("page=-1", "page"), ("view=all", "view"),
                     ("emp=12a", "emp"), ("q=" + "a" * 61, "q"), ("f=whatever", "f")):
        st, r, _h = _get(port, q)
        assert st == 400 and r["field"] == field, q
        assert "evil" not in json.dumps(r) and "whatever" not in json.dumps(r)
    st, r, _h = _get(port, "pid=p0000000000")
    assert (st, r) == (404, {"ok": False, "why": "record not found"})
    # the database not open: the reads say so, the status view still answers
    P.PDB["db"] = None
    assert _get(port)[0] == 503 and _get(port, "view=status")[1]["status"]["db"] == "ok"
    st, r = _op(port, op="keep", pid=jane, field="sen")
    assert (st, r["why"]) == (503, "The pilot database is not open")
    P.PDB["db"] = db


def test_hand_edits_and_the_409(api, caplog):
    P, db, port = api
    jane = db.find("10001")
    rev = db.record(jane)["rev"]
    with caplog.at_level(logging.INFO):
        st, r = _op(port, op="set", pid=jane, field="sen", value="799", why="the Nov list is wrong", rev=rev)
        assert st == 200 and r["ok"] and r["rev"] == db.rev
        f = r["record"]["fields"]["sen"]
        assert (f["value"], f["source"], f["hand"], f["drift"], f["why"], f["by"]) == (
            "799", "hand", True, True, "the Nov list is wrong", "ryan")
        # the rev it was read at is gone: 409 with the fresh record, nothing written
        st, r = _op(port, op="set", pid=jane, field="sen", value="700", rev=rev)
        assert st == 409 and r["why"] == "changed" and r["record"]["fields"]["sen"]["value"] == "799"
        rev = r["record"]["rev"]
        # Keep my edit dismisses the drift; Use upload value goes back to the uploads
        st, r = _op(port, op="keep", pid=jane, field="sen")
        assert st == 200 and r["record"]["fields"]["sen"]["drift"] is False
        st, r = _op(port, op="unset", pid=jane, field="sen", rev=r["record"]["rev"])
        assert st == 200 and r["record"]["fields"]["sen"]["value"] == "812" and not r["record"]["fields"]["sen"]["hand"]
        log_rows = [x["how"] for x in r["record"]["field_log"] if x["field"] == "sen"]
        assert log_rows[:3] == ["unset", "keep", "hand"]
        # phones as a list; a refused value names the field and never echoes it
        st, r = _op(port, op="set", pid=jane, field="phones", rev=r["record"]["rev"],
                    value=[{"label": "mobile", "number": "808-555-0199"}])
        assert st == 200 and r["record"]["fields"]["phones"]["value"][0]["tel"] == "+18085550199"
        for field, value in (("doh", "<img src=x onerror=alert(1)>"), ("sen", "evil 12"), ("status", "EVIL"),
                             ("emails", ["evil@@example"]), ("name", "Evil‮Name, X")):
            st, r = _op(port, op="set", pid=jane, field=field, value=value, rev=r.get("record", {}).get("rev", 0) or db.record(jane)["rev"])
            assert st == 400 and r["field"] == field and r["ok"] is False, field
            assert "evil" not in json.dumps(r).lower() and "img" not in json.dumps(r), field
        st, r = _op(port, op="set", pid=jane, field="favorite", value="x", rev=1)
        assert (st, r["field"]) == (400, "field")
        st, r = _op(port, op="set", pid=jane, field="sen", value=812, rev=db.record(jane)["rev"])
        assert (st, r["field"], r["why"]) == (400, "sen", "must be text")
        st, r = _op(port, op="set", pid=jane, field="sen", value="5", rev=True)
        assert (st, r["field"]) == (400, "rev")
    assert "pilot db: set from the card: saved" in caplog.text and "pilot db: set from the card: stale" in caplog.text
    for s in SECRETS + ("799", "wrong", "evil", "0199"):
        assert s not in caplog.text, s


def test_the_notes_field_and_the_log(api, caplog):
    P, db, port = api
    jane = db.find("10001")
    with caplog.at_level(logging.INFO):
        st, r = _op(port, op="field", pid=jane, text="Good on reserve.\r\nCommutes from Maui.", base="000000000000")
        assert st == 200 and r["notes"]["text"] == "Good on reserve.\nCommutes from Maui." and r["notes"]["by"] == "ryan"
        first = r["notes"]["rev"]
        st, r = _op(port, op="field", pid=jane, text="Second version", base=first)
        assert st == 200
        second = r["notes"]["rev"]
        # a save on the first rev again: 409 with the text there now, nothing overwritten
        st, r = _op(port, op="field", pid=jane, text="a blind overwrite", base=first)
        assert st == 409 and r["conflict"]["text"] == "Second version" and r["conflict"]["rev"] == second
        assert db.record(jane)["notes"]["text"] == "Second version"
        # Restore a kept version (a save on the current base)
        hist = db.record(jane)["notes_hist"]
        st, r = _op(port, op="restore_field", pid=jane, hist_id=hist[0]["id"], base=second)
        assert st == 200 and r["notes"]["text"] == "Good on reserve.\nCommutes from Maui."
        st, r = _op(port, op="restore_field", pid=jane, hist_id=hist[0]["id"], base=second)
        assert st == 409 and "conflict" in r
        st, r = _op(port, op="field", pid=jane, text="x‮y", base=r["conflict"]["rev"])
        assert (st, r["field"]) == (400, "text")
        # the log: add (a repeated rid adds nothing), Only me, retract own, hide, restore, purge
        st, r = _op(port, op="add", pid=jane, text="Flew with her in Oct: great CRM.", rid="rid-0001", shared=True)
        assert st == 200 and r["eid"].startswith("n")
        eid = r["eid"]
        st, r = _op(port, op="add", pid=jane, text="Flew with her in Oct: great CRM.", rid="rid-0001")
        assert st == 200 and r["eid"] == eid and len(r["record"]["entries"]) == 1
        st, r = _op(port, op="add", pid=jane, text="Only for me", rid="rid-0002", shared=False)
        mine = r["eid"]
        assert [e["shared"] for e in r["record"]["entries"] if e["eid"] == mine] == [False]
        st, r = _op(port, op="add", pid=jane, text="x", rid="rid-0003", shared="yes")
        assert (st, r["field"]) == (400, "shared")
        st, r = _op(port, op="retract", eid=mine)
        e = next(x for x in r["record"]["entries"] if x["eid"] == mine)
        assert st == 200 and e["gone"] == "retracted" and e["text"] == ""
        raw = b"".join(open(P.PILOTDB_FILE + sfx, "rb").read() for sfx in ("", "-wal") if os.path.exists(P.PILOTDB_FILE + sfx))
        assert b"Only for me" not in raw  # the retract scrubbed the file and its WAL
        st, r = _op(port, op="hide", eid=eid)
        assert st == 200 and next(x for x in r["record"]["entries"] if x["eid"] == eid)["gone"] == "hidden"
        st, r = _op(port, op="restore", eid=eid)
        assert st == 200 and "gone" not in next(x for x in r["record"]["entries"] if x["eid"] == eid)
        st, r = _op(port, op="purge", eid=eid)
        assert (st, r["field"], r["why"]) == (400, "entry", "hide it first")
        _op(port, op="hide", eid=eid)
        st, r = _op(port, op="purge", eid=eid)
        assert st == 200 and next(x for x in r["record"]["entries"] if x["eid"] == eid)["gone"] == "purged"
        for d in P.pilotdb_dirs():  # a purge leaves only the fresh copy, without the text
            names = [n for n in os.listdir(d) if n.endswith(".sqlite")]
            assert len(names) == 1 and names[0].startswith("pilotdb-")  # the database's own clock names the day
            assert b"great CRM" not in open(os.path.join(d, names[0]), "rb").read()
        st, r = _op(port, op="purge", hist_id=hist[0]["id"])
        assert st == 200 and next(h for h in r["record"]["notes_hist"] if h["id"] == hist[0]["id"])["purged"]
        st, r = _op(port, op="purge", backups=True)
        assert st == 200 and r["ok"]
        st, r = _op(port, op="purge", eid=eid, hist_id=1)
        assert (st, r["field"]) == (400, "purge")
        st, r = _op(port, op="retract", eid="n0000000000")
        assert (st, r["why"]) == (404, "entry not found")
    for s in SECRETS + ("reserve", "Maui", "CRM", "Only for me", "Second version"):
        assert s not in caplog.text, s


def test_records_conflicts_and_the_copies(api, caplog):
    P, db, port = api
    jane, rick = db.find("10001"), db.find("10002")
    with caplog.at_level(logging.INFO):
        # Ryan's own record, then Merge it into Jane's
        st, r = _op(port, op="new", emp="10077", name="Doe, Jane A", doh="2001-05-01")
        assert st == 200 and r["record"]["emp"] == "10077" and r["record"]["fields"]["name"]["source"] == "hand"
        dup = r["pid"]
        _op(port, op="add", pid=dup, text="on the duplicate", rid="rid-dup-1")
        st, r = _op(port, op="merge", pid=dup, into=jane)
        assert st == 200 and r["pid"] == jane and [e["text"] for e in r["record"]["entries"]] == ["on the duplicate"]
        assert _get(port, f"pid={dup}")[1]["record"]["merged_into"] == jane
        st, r = _op(port, op="new", emp="10001", name="Doe, Jane")
        assert (st, r["field"]) == (400, "name")  # this number and last name are a record already
        # a renumbering Ryan confirms
        st, r = _op(port, op="move", pid=rick, emp="10088")
        assert st == 200 and r["record"]["emp"] == "10088" and db.find("10088") == rick
        st, r = _op(port, op="move", pid=rick, emp="1x")
        assert (st, r["field"]) == (400, "emp")
        # the conflicts queue: the contact row with no HAL Notes, attached to a record
        c = _get(port, "view=conflicts")[1]["conflicts"][0]
        st, r = _op(port, op="resolve", conflict_id=c["id"], how="move")
        assert (st, r["field"]) == (400, "how")
        st, r = _op(port, op="resolve", conflict_id=c["id"], how="attach", pid=rick)
        assert st == 200 and r["pid"] == rick and r["record"]["fields"]["phones"]["value"][0]["tel"] == "+18085550105"
        assert _get(port, "view=conflicts")[1]["conflicts"] == []
        st, r = _op(port, op="resolve", conflict_id=c["id"], how="ignore")
        assert (st, r["why"]) == (404, "conflict not found")
        # Delete record needs DELETE typed
        st, r = _op(port, op="forget", pid=rick, confirm="delete")
        assert (st, r["field"], r["why"]) == (400, "confirm", "type DELETE")
        st, r = _op(port, op="forget", pid=rick, confirm="DELETE")
        assert st == 200 and r["ok"] and _get(port, f"pid={rick}")[0] == 404
        # put a copy back: RESTORE typed, a copy on the list only
        st, r = _op(port, op="restore_db", file="0/pilotdb-2026-11-15.sqlite", confirm="restore")
        assert (st, r["field"]) == (400, "confirm")
        st, r = _op(port, op="restore_db", file="../../etc/passwd", confirm="RESTORE")
        assert (st, r["field"], r["why"]) == (400, "file", "is not a copy on file")
        copy = _get(port, "view=status")[1]["backups"][0]["file"]  # the forget replaced the copies
        assert copy.startswith("0/") or copy.startswith("1/")
        st, r = _op(port, op="restore_db", file=copy, confirm="RESTORE")
        assert st == 200 and r["status"]["db"] in ("ok", "restore_offered")
        assert P.PDB["db"] is not None and P.PDB["db"] is not db
        assert any(n.startswith("pilotdb.sqlite.before-restore-") for n in os.listdir(os.path.dirname(P.PILOTDB_FILE)))
    for s in SECRETS + ("10077", "10088", "duplicate"):
        assert s not in caplog.text, s


def test_no_flica_no_pilot_set_and_the_author_is_ryan(api, monkeypatch):
    P, db, port = api
    jane = db.find("10001")

    def boom(*a, **k):
        raise AssertionError("the pilot database never reaches FLICA or the pilot lookup")
    monkeypatch.setattr(P, "pilot_cmd", boom)
    P.S["pilot_req"] = None
    P.WAKE.clear()
    _op(port, op="field", pid=jane, text="a note", base="000000000000")
    _op(port, op="add", pid=jane, text="an entry", rid="rid-auth-1")
    _get(port, "emp=10001&name=Doe%2C%20Jane")
    _get(port, f"pid={jane}")
    rec = db.record(jane)
    assert rec["notes"]["by"] == "ryan" and [e["by"] for e in rec["entries"]] == ["ryan"]
    assert P.S.get("pilot_req") is None and not P.WAKE.is_set()
    pubs = [t for t, _p in P.SENT]
    assert "pilot/set" not in pubs and not any(t.startswith("event/") for t in pubs)


def test_the_sensor_counts_only(api):
    P, db, port = api
    jane = db.find("10001")
    _op(port, op="field", pid=jane, text="Doe, Jane is great 808-555-0101", base="000000000000")
    _op(port, op="add", pid=jane, text="an entry about Roe, Rick", rid="rid-sens-1")
    sent = [p for t, p in P.SENT if t == "pilotdb"]
    assert sent, "a write publishes the sensor"
    d = sent[-1]
    assert d["db"] == "ok" and d["live"] == 4 and d["noted"] == 1 and d["entries"] == 1 and d["rev"] == db.rev
    assert set(d) == set(P.PILOTDB_SENSOR_KEYS) | {"offer"}
    assert d["sources"]["contacts"] == {"date": "2026-11-14", "count": 5, "merged_at": d["sources"]["contacts"]["merged_at"]}
    text = json.dumps(d)
    for s in SECRETS + ("great", "entry"):
        assert s not in text, s
    assert len(json.dumps(d, separators=(",", ":"))) < 2048
    # unchanged: not published again
    n = len(sent)
    assert P.publish_pilotdb() is False and len([1 for t, _p in P.SENT if t == "pilotdb"]) == n
    # a pilot instance has neither the sensor nor the API
    assert P.ROLES.ENTITY_FEATURE["pilotdb"] == "one_writer" and not P.ROLES.allowed("one_writer", "james")

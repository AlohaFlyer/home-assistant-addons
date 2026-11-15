"""1.7.8: the pilot database in the admin's Watcher (spec 4, 8.1, 13 and 18, with Ryan's Nov 14 answers). The first
start seeds it from the kept contact CSV (contacts.json from parser 1 is read again from it, its Notes' HAL data) and
seniority.json; a source whose signature moves is merged again (an upload nudges it at once); each picker's pickup
history follows the scored pickups; seniority.md (the 1.7.7 path, mode 600) is written from the database and again each
HST day; the nightly copies at 02:47 HST; the start checks; a pilot instance never opens it; nothing of it loads FLICA
and the log carries counts only. Synthetic pilots only ("Doe, Jane" 10001)."""
import inspect
import json
import logging
import os
import stat
from datetime import datetime, timedelta

import pytest

import contacts as CT
import pilotdb as PDBM
import seniority as SEN
import web
from test_contacts_hal_notes import ROWS, _csv
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw177_pickers import JANE, _find


@pytest.fixture
def P(W, tmp_path, monkeypatch):  # noqa: F811
    share = tmp_path / "share"
    up = share / "uploads"
    up.mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))
    monkeypatch.setattr(web, "CONTACTS_FILE", str(share / "contacts.json"))
    monkeypatch.setattr(web, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setattr(web, "SENIORITY_MD_HOOK", None)
    monkeypatch.setenv("FLIGHT_WATCHER_PILOTDB", "1")  # conftest keeps it closed for every other test
    monkeypatch.setattr(W, "PILOTDB_FILE", str(data / "pilotdb.sqlite"))
    monkeypatch.setattr(W, "PILOTDB_BACKUP", str(data / "pilotdb_backup"))
    monkeypatch.setattr(W, "PILOTDB_SHARE", str(share / "pilotdb"))
    monkeypatch.setattr(W, "PDB", {"db": None, "status": {"db": "off", "offer": None}, "wake": W.threading.Event(),
                                   "md_rev": None, "md_at": 0.0, "md_day": "", "merged": False, "contacts": "",
                                   "thread": "test: no thread"})
    monkeypatch.setattr(W, "review", lambda: (_ for _ in ()).throw(OSError("no review store in this test")))
    W.TEST_CLOCK["t"] = datetime(2026, 11, 15, 9, 0)
    # the kept contact list as Pako has it: the CSV (mode 600) and a contacts.json written by parser 1 (no hal)
    src = up / "contacts_2026-11-14.csv"
    src.write_bytes(_csv(ROWS))
    os.chmod(src, 0o600)
    old = CT.build(CT.parse(_csv(ROWS), "csv"), "contacts_2026-11-14.csv", "2026-11-14T09:30:00-10:00")
    for e in old["pilots"]:
        e.pop("hal", None)
        e.pop("name_full", None)
    old.update(parser=1, hal_only=[])
    old.pop("with_hal", None)
    CT.store(web.CONTACTS_FILE, old)
    W.share_dir = share
    W.data_dir = data
    yield W
    db = W.PDB.get("db")
    if db is not None:
        db.close()


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


SECRETS = ("Doe", "Jane", "Roe", "Poe", "10001", "10002", "10003", "555-01", "example.com", "SLOA", "MLOA")


def test_the_first_start_seeds_from_the_kept_contact_csv(P, caplog):
    with caplog.at_level(logging.INFO):
        db = P.pilotdb_start()
    assert db is not None and P.PDB["status"]["db"] == "ok"
    cj = json.loads(open(web.CONTACTS_FILE).read())
    assert cj["parser"] == CT.PARSER == 2 and cj["with_hal"] == 4  # read again from the kept CSV, once
    jane = db.find("10001")
    rec = db.record(jane)
    assert (rec["fields"]["sen"]["value"], rec["fields"]["doh"]["value"], rec["fields"]["status"]["value"],
            rec["fields"]["retire"]["value"]) == ("812", "2001-05-01", "SLOA", "2041-03")
    assert db.find("10003")  # a HAL row with no phone or email (hal_only) is a record too
    assert db.find("10005") is None  # a row with no Notes makes no record (contact_unmatched)
    assert db.meta("seeded_at")
    # the files: the database 0600, the copies 0600 in 0700 folders, seniority.md (1.7.7's path) 0600
    assert _mode(P.PILOTDB_FILE) == 0o600
    for d in P.pilotdb_dirs():
        assert _mode(d) == 0o700 and os.listdir(d) == ["pilotdb-2026-11-15.sqlite"]
        assert _mode(os.path.join(d, "pilotdb-2026-11-15.sqlite")) == 0o600
    md = P.share_dir / "seniority.md"
    assert md.exists() and _mode(md) == 0o600 and md.read_text().startswith("# Pilot database\n")
    assert "| 812 | 10001 | Doe, Jane A |" in md.read_text()
    assert "555-01" not in md.read_text() and "example.com" not in md.read_text()
    assert "pilot db: contacts 2026-11-14 merged: 4 added" in caplog.text and "1 conflict" in caplog.text
    for s in SECRETS:
        assert s not in caplog.text, s
    # a second start is no new seed and adds nothing
    n = db.summary()["live"]
    db.close()
    P.PDB["db"] = None
    db = P.pilotdb_start()
    assert db.summary()["live"] == n


def test_a_list_upload_is_merged_and_wins_on_sen_doh_status(P, fx, caplog):
    db = P.pilotdb_start()
    jane = db.find("10001")
    assert web.SENIORITY_MD_HOOK == P.pilotdb_nudge
    from test_seniority_hal import hal_text
    with caplog.at_level(logging.INFO):
        web.seniority_store(SEN.parse(hal_text()), "seniority_2026-11-15.pdf", "2026-11-15T09:00:00-10:00",
                            out=os.path.join(P.UPLOADS_SHARED, "seniority.json"))
        assert P.PDB["wake"].is_set()  # the json write nudged the database (no md written from the json)
        assert P.pilotdb_tick()
    rec = db.record(jane)
    assert rec["fields"]["sen"]["source"] == "list" and rec["fields"]["doh"]["source"] == "list"
    assert "pilot db: list 2026-07-01 merged:" in caplog.text
    md = (P.share_dir / "seniority.md").read_text()
    assert md.startswith("# Pilot database\n") and "list 2026-07-01 (uploaded by ryan" in md
    for s in SECRETS:
        assert s not in caplog.text, s
    # unchanged files: nothing merged again
    assert P.pilotdb_tick() is False


def test_pickups_follow_the_scored_pickups(P):
    db = P.pilotdb_start()
    _find(P.DB, "H3601|20Nov", f"FO {JANE}", "2026-11-14T20:00:00+00:00", "FO", first="2026-11-14T19:00:00+00:00")
    P.DB.patch_row("H3601|20Nov", {"layover": "LAX", "start": "20Nov", "days": "3", "credit": "15:30", "report": "08:00"})
    assert P.DB.score_pickup("H3601|20Nov") is not None
    P.pilotdb_tick()
    h = db.pickups(db.find("10001"))
    assert h["summary"]["n"] == 1 and h["rows"][0]["lay"] == "LAX" and h["rows"][0]["n_lay"] == 1


def test_seniority_md_daily_and_the_nightly_copies(P):
    db = P.pilotdb_start()
    md = P.share_dir / "seniority.md"
    t0 = md.stat().st_mtime_ns
    P.pilotdb_tick()
    assert md.stat().st_mtime_ns == t0  # nothing changed: not written again
    P.TEST_CLOCK["t"] = datetime(2026, 11, 16, 2, 40)  # the next HST day, before 02:47
    P.pilotdb_tick()
    assert md.stat().st_mtime_ns > t0  # the pay year column follows the day
    assert "Pay year today (" in md.read_text()
    assert not any("2026-11-16" in f for d in P.pilotdb_dirs() for f in os.listdir(d))
    P.TEST_CLOCK["t"] = datetime(2026, 11, 16, 2, 48)
    P.pilotdb_tick()
    assert all("pilotdb-2026-11-16.sqlite" in os.listdir(d) for d in P.pilotdb_dirs())
    assert db.meta("backup_day") == "2026-11-16"
    # a change: seniority.md 30 s later, not at once
    db.add_entry(db.find("10001"), "a note")
    t1 = md.stat().st_mtime_ns
    P.pilotdb_tick()
    assert md.stat().st_mtime_ns == t1
    P.PDB["md_at"] = 1.0  # the 30 s are up
    P.pilotdb_tick()
    assert md.stat().st_mtime_ns > t1 and "a note" in md.read_text()


def test_the_start_checks(P):
    db = P.pilotdb_start()
    db.close()
    P.PDB["db"] = None
    with open(P.PILOTDB_FILE, "wb") as fh:  # a damaged file
        fh.write(b"SQLite format 3\x00" + b"\xff" * 4096)
    for sfx in ("-wal", "-shm"):
        if os.path.exists(P.PILOTDB_FILE + sfx):
            os.remove(P.PILOTDB_FILE + sfx)
    assert P.pilotdb_start() is None
    st = P.pilotdb_status()
    assert st["db"] == "error" and st["offer"]["day"] == "2026-11-15"
    assert any(".bad-" in f for f in os.listdir(P.data_dir))
    assert web.SENIORITY_MD_HOOK is None or P.PDB["db"] is None


def test_a_pilot_instance_never_opens_it(P, monkeypatch):
    monkeypatch.setattr(P, "INSTANCE", "pilot2")
    assert P.pilotdb_start() is None and not os.path.exists(P.PILOTDB_FILE)
    assert P.pilotdb_tick() is False
    monkeypatch.setattr(P, "INSTANCE", "")
    monkeypatch.setenv("FLIGHT_WATCHER_PILOTDB", "0")
    assert P.pilotdb_start() is None and not os.path.exists(P.PILOTDB_FILE)


def test_no_flica_path_in_the_pilot_database():
    """D8: no pilotdb code calls the FLICA fetch, the gate or pilot_cmd, or sets pilot_req or WAKE."""
    import watcher as Wm
    import pdbshare
    srcs = [inspect.getsource(PDBM), inspect.getsource(pdbshare)] + [  # 1.7.9: the share files and both sides' glue
        inspect.getsource(getattr(Wm, n)) for n in dir(Wm) if n.startswith(("pilotdb_", "_pdbv_"))
        and callable(getattr(Wm, n))]
    for src in srcs:
        for bad in ("fl.fetch", ".fetch(", "pilot_cmd", "pilot_req", "WAKE", "GT.", "BRK.", "sync_playwright"):
            assert bad not in src, bad


def test_the_status_holds_counts_only(P):
    P.pilotdb_start()
    st = P.pilotdb_status()
    assert st["db"] == "ok" and st["live"] >= 3 and st["contacts"] in ("reparsed", "current")
    text = json.dumps(st)
    for s in SECRETS:
        assert s not in text, s
    assert len(text) < 2048


def test_restore_and_scrub_helpers(P):
    db = P.pilotdb_start()
    jane = db.find("10001")
    eid = db.add_entry(jane, "SCRUB-ME-QXZ")
    P.TEST_CLOCK["t"] = datetime(2026, 11, 16, 3, 0)
    P.pilotdb_tick()  # the nightly copy holds it
    db.hide(eid)
    db.purge(eid=eid)
    assert P.pilotdb_scrub(purged=True)
    for d in P.pilotdb_dirs():
        for f in os.listdir(d):
            assert b"SCRUB-ME-QXZ" not in open(os.path.join(d, f), "rb").read()
    files = PDBM.backups(P.pilotdb_dirs())
    st = P.pilotdb_restore(files[0]["file"])
    assert st["db"] == "ok" and P.PDB["db"] is not db and P.PDB["db"].find("10001") == jane
    assert any("before-restore" in f for f in os.listdir(P.data_dir))
    with pytest.raises(PDBM.Bad):
        P.pilotdb_restore("0/../../etc/passwd")
    assert P.PDB["db"] is not None  # still open after a refused restore

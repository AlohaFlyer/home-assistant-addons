"""1.0.0: old app (flica_watcher 0.10.4 export.py) -> Flight Watcher (migrate.py). Synthetic files only."""
import importlib.util
import os
import sqlite3

import migrate

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("old_export", os.path.join(HERE, "..", "..", "flica_watcher", "export.py"))
old_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_export)


def _old_data(root):
    d = root / "old_data"
    (d / "pilot2").mkdir(parents=True)
    con = sqlite3.connect(d / "watcher.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('kept-in-wal')")
    con.commit()  # left open: the row is only in watcher.db-wal while this connection lives
    for name, text in {"state.json": "{}", "rules.json": "[]", "cards.json": '{"doh": "1999-01-02"}',
                       "options.json": "SECRET-OPTS", "storage_state.json": "COOKIES", "x.tmp": "t"}.items():
        (d / name).write_text(text)
    (d / "pilot2" / "creds.json").write_text("SECRET-CREDS")
    sqlite3.connect(d / "pilot2" / "watcher.db").close()
    return d, con


def test_export_then_import_round_trip(tmp_path):
    (old, _c), share, new = _old_data(tmp_path), tmp_path / "share", tmp_path / "new_data"
    new.mkdir()
    (new / "options.json").write_text("NEW-OPTS")
    assert old_export.export(str(old), str(share)) == 5
    exported = share / "import" / "data"
    assert (exported / "READY").exists()
    for secret in ("options.json", "storage_state.json", "x.tmp", "pilot2/creds.json", "watcher.db-wal"):
        assert not (exported / secret).exists()
    got = migrate.import_data(str(new), str(share))
    assert sorted(got) == ["cards.json", "pilot2/watcher.db", "rules.json", "state.json", "watcher.db"]
    assert (new / "options.json").read_text() == "NEW-OPTS"
    assert (new / "cards.json").read_text() == '{"doh": "1999-01-02"}'
    assert sqlite3.connect(new / "watcher.db").execute("SELECT v FROM t").fetchall() == [("kept-in-wal",)]
    assert not (share / "import").exists() and (share / ".imported").exists()
    # the old app restarting later does not export again, and a second import is a no-op
    assert old_export.export(str(old), str(share)) == 0 and not (share / "import").exists()
    assert migrate.import_data(str(new), str(share)) == []


def test_import_never_overwrites_a_running_instance(tmp_path):
    (old, _c), share, new = _old_data(tmp_path), tmp_path / "share", tmp_path / "new_data"
    new.mkdir()
    (new / "watcher.db").write_text("live")
    old_export.export(str(old), str(share))
    assert migrate.import_data(str(new), str(share)) == []
    assert (new / "watcher.db").read_text() == "live" and (share / "import" / "data" / "READY").exists()


def test_fresh_start_then_late_export_is_imported(tmp_path):
    (old, _c), share, new = _old_data(tmp_path), tmp_path / "share", tmp_path / "new_data"
    new.mkdir()
    migrate.note_fresh(str(new))  # new app started before the old one exported
    (new / "watcher.db").write_text("fresh")
    (new / "watcher.db-wal").write_text("fresh-wal")
    old_export.export(str(old), str(share))
    assert "watcher.db" in migrate.import_data(str(new), str(share))
    assert sqlite3.connect(new / "watcher.db").execute("SELECT v FROM t").fetchall() == [("kept-in-wal",)]
    assert not (new / "watcher.db-wal").exists() or (new / "watcher.db-wal").read_text() != "fresh-wal"
    assert (new / ".migrated").exists() and not (new / ".fresh").exists()


def test_interrupted_import_is_redone(tmp_path):
    (old, _c), share, new = _old_data(tmp_path), tmp_path / "share", tmp_path / "new_data"
    new.mkdir()
    old_export.export(str(old), str(share))
    (new / ".import.tmp").mkdir()
    (new / "watcher.db").write_text("truncated")  # placed before the cut, no .migrated
    assert "watcher.db" in migrate.import_data(str(new), str(share))
    assert sqlite3.connect(new / "watcher.db").execute("SELECT v FROM t").fetchall() == [("kept-in-wal",)]


def test_export_refreshes_until_imported(tmp_path):
    (old, con), share = _old_data(tmp_path), tmp_path / "share"
    old_export.export(str(old), str(share))
    con.execute("INSERT INTO t VALUES ('newer')")
    con.commit()
    old_export.export(str(old), str(share))
    rows = sqlite3.connect(share / "import" / "data" / "watcher.db").execute("SELECT v FROM t").fetchall()
    assert ("newer",) in rows


def test_import_waits_for_ready(tmp_path):
    share, new = tmp_path / "share", tmp_path / "new_data"
    (share / "import" / "data").mkdir(parents=True)
    (share / "import" / "data" / "watcher.db").write_text("half")
    new.mkdir()
    assert migrate.import_data(str(new), str(share)) == [] and not (new / "watcher.db").exists()


def test_move_tree_keeps_existing_and_removes_empty_old(tmp_path):
    old, new = tmp_path / "flica", tmp_path / "flight-watcher"
    (old / "james").mkdir(parents=True)
    (old / "pairings_2026-11.json").write_text("old")
    (old / "finds_2026-11.json").write_text("old")
    new.mkdir()
    (new / "finds_2026-11.json").write_text("new")
    assert migrate.move_tree(str(old), str(new)) == ["james", "pairings_2026-11.json"]
    assert (new / "finds_2026-11.json").read_text() == "new" and (new / "pairings_2026-11.json").read_text() == "old"
    assert old.exists()  # the clash stays behind for a look by hand
    (old / "finds_2026-11.json").unlink()
    assert migrate.move_tree(str(old), str(new)) == [] and not old.exists()


def test_run_never_raises(tmp_path):
    migrate.run(data=str(tmp_path / "missing"), share_old=str(tmp_path / "a"), share_new=str(tmp_path / "b"),
                www_old=str(tmp_path / "c"), www_new=str(tmp_path / "d" / "e"))

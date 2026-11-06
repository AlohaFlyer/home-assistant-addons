"""FW-0010 (finds files under /local/ carry a random key) and FW-0026 (sensor.flight_watcher_finds kept under HA's
16 KiB recorder limit). Synthetic data only ("Doe, Jane")."""
import json
import logging
import os
import re
import stat
import sys

import wwwfiles as WF

KEY = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


def test_load_key_made_once_private_and_stable(tmp_path):
    p = tmp_path / "d" / "www_key"
    k = WF.load_key(str(p))
    assert re.fullmatch(r"[0-9a-f]{32}", k)  # 128 bits from secrets
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert WF.load_key(str(p)) == k  # kept, not remade
    assert WF.load_key(str(tmp_path / "other_key")) != k
    p.write_text("not a key\n")  # unreadable: a new one
    k2 = WF.load_key(str(p))
    assert re.fullmatch(r"[0-9a-f]{32}", k2) and k2 != k and WF.load_key(str(p)) == k2


def test_stale_names():
    own = {n: WF.stale(n, KEY, True) for n in (
        "finds_2026-11.json", "finds_2026-11.json.tmp", f"finds_2026-11_{KEY}.json", f"finds_2026-11_{KEY}.json.tmp",
        f"finds_2026-11_{OTHER}.json", "pairings_2026-11.json", "school_2026-27.json", "finds_notes.txt",
        "finds_2026-11_short.json")}
    assert own == {"finds_2026-11.json": True, "finds_2026-11.json.tmp": True, f"finds_2026-11_{KEY}.json": False,
                   f"finds_2026-11_{KEY}.json.tmp": True, f"finds_2026-11_{OTHER}.json": True,
                   "pairings_2026-11.json": False, "school_2026-27.json": False, "finds_notes.txt": False,
                   "finds_2026-11_short.json": False}
    # another pilot's folder: only the guessable names go; that pilot's keyed files are his instance's business
    assert WF.stale("finds_2026-11.json", KEY, False) and WF.stale("finds_2026-11.json.tmp", KEY, False)
    assert not WF.stale(f"finds_2026-11_{OTHER}.json", KEY, False) and not WF.stale("pairings_2026-11.json", KEY, False)


def test_cleanup_and_scrub(tmp_path):
    www = tmp_path / "www"
    (www / "pilot2").mkdir(parents=True)
    for n in ("finds_2026-10.json", "finds_2026-11.json", f"finds_2026-11_{KEY}.json", f"finds_2026-09_{OTHER}.json",
              "pairings_2026-11.json", "school_2026-27.json"):
        (www / n).write_text("{}")
    for n in ("finds_2026-11.json", f"finds_2026-11_{OTHER}.json"):
        (www / "pilot2" / n).write_text("{}")
    assert WF.cleanup(str(www), KEY, WF.subdirs(str(www)) + [str(tmp_path / "missing")]) == 4
    assert sorted(os.listdir(www)) == sorted([f"finds_2026-11_{KEY}.json", "pairings_2026-11.json", "school_2026-27.json",
                                             "pilot2"])
    assert os.listdir(www / "pilot2") == [f"finds_2026-11_{OTHER}.json"]
    assert WF.cleanup(str(www), KEY, WF.subdirs(str(www))) == 0  # idempotent
    assert WF.subdirs(str(tmp_path / "missing")) == []
    assert WF.scrub(f"[Errno 21] Is a directory: '/x/finds_2026-11_{KEY}.json'", KEY) == \
        "[Errno 21] Is a directory: '/x/finds_2026-11_<key>.json'"
    assert WF.scrub("plain", None) == "plain"


def _watcher(tmp_path, monkeypatch, instance=""):
    data = tmp_path / ("data_" + (instance or "default"))
    data.mkdir()
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    monkeypatch.setattr(W, "DB", Store(str(data / "t.db")))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    monkeypatch.setattr(W, "WWW_OLD", str(tmp_path / "www" / "flica"))
    return W


def _add_find(W, key, pid, seen, picked_by="FO Doe, Jane (12345)"):
    row = {"pairing": pid, "dates": "08Nov-10Nov", "days": "3", "layover": "LAX", "report": "07:00", "credit": "16:30",
           "turn": "", "captain": "Doe, John (23456)", "source": "pot"}
    W.DB.db.execute("INSERT INTO finds(key,pairing,month,row,first_seen,last_seen,gone_at,pickup,alert_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, pid, "Nov", json.dumps(row), seen, seen, seen,
                     json.dumps({"by": picked_by, "status": "filled", "ca": "Doe, John (23456)"}), seen))


def test_month_files_keyed_and_old_names_swept_on_start(tmp_path, monkeypatch, caplog):
    """FW-0010: Ryan's instance writes finds_<YYYY-MM>_<key>.json (key in /data/www_key) and, once per start, removes
    the guessable finds_<YYYY-MM>.json files from www/flight-watcher, every second-pilot folder and the old
    www/flica tree. pairings and school files stay. The key is never in the log."""
    W = _watcher(tmp_path, monkeypatch)
    fw, old = tmp_path / "www" / "flight-watcher", tmp_path / "www" / "flica"
    (fw / "pilot2").mkdir(parents=True)
    (old / "pilot2").mkdir(parents=True)
    month = f"{W.local_now():%Y-%m}"
    for p in (fw / f"finds_{month}.json", fw / "finds_2025-01.json", fw / "pilot2" / f"finds_{month}.json",
              old / "finds_2025-01.json", old / "pilot2" / "finds_2025-01.json", fw / "pairings_2026-11.json",
              fw / "school_2026-27.json", fw / "pilot2" / f"finds_{month}_{OTHER}.json"):
        p.write_text('{"finds": [{"picked_by": "FO Doe, Jane (12345)"}]}')
    _add_find(W, "k1", "H9001", W.now_iso())
    caplog.set_level(logging.INFO, logger="flight_watcher")
    W.finds_files_cleanup()
    W.write_finds_months()
    key = W.www_key()
    assert re.fullmatch(r"[0-9a-f]{32}", key) and (tmp_path / "data_default" / "www_key").read_text().strip() == key
    assert sorted(os.listdir(fw)) == sorted([f"finds_{month}_{key}.json", "pairings_2026-11.json", "school_2026-27.json",
                                            "pilot2"])
    assert os.listdir(fw / "pilot2") == [f"finds_{month}_{OTHER}.json"]  # the second pilot's keyed file is his
    assert os.listdir(old / "pilot2") == [] and [x for x in os.listdir(old) if x.startswith("finds_")] == []
    assert json.loads((fw / f"finds_{month}_{key}.json").read_text())["finds"][0]["pairing"] == "H9001"
    assert "removed 5 finds file(s)" in caplog.text
    # an error naming the keyed file is logged with the key taken out
    os.remove(fw / f"finds_{month}_{key}.json")
    os.mkdir(fw / f"finds_{month}_{key}.json")
    W.FINDS_FILES["all"] = False
    W.write_finds_months()
    assert "finds month files skipped" in caplog.text and "_<key>.json" in caplog.text
    assert key not in caplog.text


def test_second_pilot_sweeps_its_own_folder_only(tmp_path, monkeypatch):
    W = _watcher(tmp_path, monkeypatch, "pilot2")
    fw = tmp_path / "www" / "flight-watcher"
    (fw / "pilot2").mkdir(parents=True)
    for p in (fw / "finds_2026-11.json", fw / "pilot2" / "finds_2026-11.json", fw / "pilot2" / f"finds_2026-11_{OTHER}.json"):
        p.write_text("{}")
    W.finds_files_cleanup()
    assert W.finds_dir() == str(fw / "pilot2")
    assert os.listdir(fw / "pilot2") == []  # predictable and old-key files of its own folder
    assert (fw / "finds_2026-11.json").exists()  # Ryan's folder is Ryan's instance's to sweep
    assert W.www_key() != _watcher_key(tmp_path)  # each instance has its own key


def _watcher_key(tmp_path):
    return WF.load_key(str(tmp_path / "data_default" / "www_key"))


def test_finds_sensor_payload_small_and_keeps_what_automations_read(tmp_path, monkeypatch):
    """FW-0026: 50 finds with long names used to publish ~28 KB of attributes (HA's recorder drops attributes over 16384
    bytes and logs every update). Now: the newest 30, short rows, at most 12000 bytes, plus file_key and rev for the
    card."""
    W = _watcher(tmp_path, monkeypatch)
    long = "; ".join(f"FO Doe-Longername, Janeallison Q ({10000 + i})" for i in range(3))
    for i in range(50):
        _add_find(W, f"k{i}", f"H9{i:03d}", f"2026-11-{1 + i % 28:02d}T{i % 24:02d}:00:00+00:00", long)
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    monkeypatch.setattr(W, "publish_pickers", lambda: None)
    monkeypatch.setattr(W, "write_finds_months", lambda: None)
    W.publish_finds()
    (topic, p), = sent
    assert topic == "finds"
    size = len(json.dumps(p, separators=(",", ":")))
    assert size <= W.FINDS_ATTR_MAX <= 12000  # well under the recorder's 16384
    assert 15 <= p["count"] == len(p["finds"]) <= 30 and p["file_key"] == W.www_key()
    newest = W.DB.recent_finds(1)[0]
    assert p["finds"][0]["pairing"] == newest["pairing"] and p["finds"][0]["seen"] == newest["seen"]
    # fields the Pako automations read (FLICA alert push: pairing, layover, turn, dates, days, credit, captain) and the
    # ones the ticket names (seen, pickup_status, picked_by, alert_at, report)
    need = {"pairing", "dates", "seen", "pickup_status", "picked_by", "alert_at", "report", "credit", "days", "layover",
            "turn", "captain", "gone"}
    for r in p["finds"]:
        assert need <= set(r) and set(r) == set(W.FINDS_ATTR_KEYS)
    assert p["finds"][0]["picked_by"] == long and p["finds"][0]["captain"] == "Doe, John (23456)"
    # typical rows: all 30 fit (the FLICA alert push finds a trip that left the pot even after a burst of new finds)
    short = W.finds_payload([{**newest, "picked_by": "FO Doe, Jane (12345)"}] * 40, KEY, "abc")
    assert short["count"] == 30 and len(json.dumps(short)) < 12000 and short["rev"] == "abc"
    assert W.finds_payload([], KEY) == {"count": 0, "finds": [], "file_key": KEY, "rev": None}


def test_finds_files_written_before_the_sensor_and_rev_follows_file_only_changes(tmp_path, monkeypatch):
    """FW-0026 fix: InFlt, Prem and the picker's average live only in the month files. An InFlt verdict (inflt_check,
    some time after the pickup) leaves every sensor row as it was, so the sensor carries rev, a hash of this month's
    and last month's files: the payload changes, HA updates the sensor, and an open finds card fetches the file
    again. The files are written before the sensor is published, so that fetch reads the new file. Synthetic rows."""
    W = _watcher(tmp_path, monkeypatch)
    seen = W.now_iso()
    _add_find(W, "k1", "H9001", seen)
    sent = []
    fw = tmp_path / "www" / "flight-watcher"

    def pub(t, p, retain=True):
        if t == "finds":  # what the card would fetch at the moment the sensor changes
            f = fw / f"finds_{W.local_now():%Y-%m}_{W.www_key()}.json"
            sent.append((p, json.loads(f.read_text())["finds"][0]))
    monkeypatch.setattr(W, "pub", pub)
    W.publish_finds()
    W.publish_finds()  # nothing changed: the same payload (HA keeps the state, no recorder row)
    W.DB.set_inflt("k1", True, "H8001")
    W.publish_finds()
    (p1, f1), (p2, _), (p3, f3) = sent
    assert p1 == p2 and re.fullmatch(r"[0-9a-f]{12}", p1["rev"])
    assert p3["finds"] == p1["finds"]  # the sensor rows do not carry InFlt ...
    assert p3["rev"] != p1["rev"]  # ... so rev moves the sensor
    assert f1["inflt"] is None and f3["inflt"] is True  # the file already held the verdict when the sensor changed
    # a file that cannot be written: no rev, the rows still go out
    monkeypatch.setattr(W, "finds_dir", lambda: str(tmp_path / "www" / "flight-watcher" / f"finds_{W.local_now():%Y-%m}_{W.www_key()}.json"))
    sent.clear()
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)) if t == "finds" else None)
    W.publish_finds()
    (_, p4), = sent
    assert p4["rev"] is None and p4["finds"][0]["pairing"] == "H9001"


def test_state_attr_carries_the_doh_from_data_only(tmp_path, monkeypatch):
    """FW-0010 (survey): the pilot's DOH no longer goes into the schedule card file under /local/ (no login); the
    Watcher publishes it in sensor.<prefix>_state from <data>/cards.json, and nothing when there is none or it is not
    a date. Synthetic date."""
    W = _watcher(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    W.set_machine("watching", "ok")
    assert dict(sent)["state_attr"]["doh"] == ""
    (tmp_path / "data_default" / "cards.json").write_text('{"doh": "1999-02-03"}')
    W.set_machine("watching", "ok")
    assert sent[-1] == ("state_attr", {"note": "ok", "version": W.VERSION, "since": W.S["since"], "instance": "",
                                       "doh": "1999-02-03"})
    for bad in ('{"doh": "soon"}', '["1999-02-03"]', "not json"):
        (tmp_path / "data_default" / "cards.json").write_text(bad)
        assert W.pilot_doh() == ""


def test_dockerfile_copies_every_local_module():
    """wwwfiles.py is new in FW-0010: the image must carry every module watcher.py and run.py import."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    copy = next(ln for ln in open(os.path.join(here, "Dockerfile")) if ln.startswith("COPY run.py"))
    local = {f[:-3] for f in os.listdir(here) if f.endswith(".py")}
    for src in ("watcher.py", "run.py"):
        text = open(os.path.join(here, src), encoding="utf-8").read()
        mods = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", text, re.M)) & local
        missing = [m for m in mods if f"{m}.py" not in copy.split()]
        assert not missing, (src, missing)

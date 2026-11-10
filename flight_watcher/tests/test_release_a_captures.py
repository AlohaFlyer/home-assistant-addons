"""1.6.2 (Release A item 8): page captures per instance (captures.py). The admin's are unchanged (his folder, as read).
A pilot takes none by default, loads no page only to save it, and never writes into the admin's folder; only while
/share/flight_watcher/<pilot>/captures_on is under 24 h old are his captures written, masked (tokens, crew names,
employee numbers, his own logins), into his own 0700 folder as 0600 files, and deleted after 7 days. Synthetic pages
only ("Doe, Jane", 10001)."""
import json
import os
import stat
import sys
import time

import pytest

import captures as CAPS
import inflt as IF

PAGE = ("<html><a href='/full/x.cgi?token=AbCdEf0123456789AbCdEf0123456789&BCID=003.152'>H9001</a>"
        "<input type='hidden' name='t' value='SeCrEt0123'><p>Crew: CA 10001 DOE, JANE FO 10002 ROE JR, RICK RO Open</p>"
        "<div>DOE, JANE (Emp# 10001) Schedule</div><div>logged in as doej2</div></html>")
LEAKS = ("AbCdEf0123456789", "SeCrEt0123", "10001", "10002", "DOE, JANE", "ROE JR, RICK", "doej2")


def test_mask_hides_tokens_names_numbers_and_own_logins():
    out = CAPS.mask(PAGE, ["doej2", "pw-synthetic"])
    for leak in LEAKS:
        assert leak not in out, leak
    assert "token=MASKED" in out and "BCID=003.152" in out and "H9001" in out  # the page's shape stays
    assert "CA ##### xxx, xxxx FO ##### xxx xx, xxxx RO Open" in out  # crewidx.crew_mask style


def _pilot(tmp_path, name="pilot2", **k):
    logs = []
    c = CAPS.Captures(name, root=str(tmp_path / "share"), log=logs.append, secrets=lambda: ["doej2"], **k)
    return c, logs


def _flag(tmp_path, name="pilot2", age=0.0):
    d = tmp_path / "share" / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / CAPS.FLAG
    f.write_text("")
    t = time.time() - age
    os.utime(f, (t, t))
    return f


def test_admin_writes_as_before(tmp_path):
    c = CAPS.Captures("", root=str(tmp_path / "share"))
    assert c.on() is True
    p = c.write("pot_2026-11.html", PAGE, admin_dir=str(tmp_path / "admincap"))
    assert p == str(tmp_path / "admincap" / "pot_2026-11.html") and open(p).read() == PAGE  # unmasked, as read
    p = c.write("swapmap/01.html", "x", admin_dir=str(tmp_path / "admincap"))
    assert open(p).read() == "x"


def test_pilot_takes_none_by_default(tmp_path):
    c, logs = _pilot(tmp_path)
    assert c.on() is False and c.write("schedule.html", PAGE) is None
    assert not (tmp_path / "share" / "pilot2" / "captures").exists()
    assert logs == ["page captures off for this pilot"]
    assert c.write("schedule.html", PAGE, admin_dir=str(tmp_path / "admincap")) is None
    assert not (tmp_path / "admincap").exists()  # never the admin's folder


def test_pilot_with_a_fresh_flag_writes_masked_private_files(tmp_path):
    _flag(tmp_path)
    c, logs = _pilot(tmp_path)
    p = c.write("cmschedule_10001.html", PAGE, admin_dir=str(tmp_path / "admincap"))
    d = tmp_path / "share" / "pilot2" / "captures"
    assert p == str(d / "cmschedule_NNNNN.html")  # the file name is masked too
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700 and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    text = open(p).read()
    for leak in LEAKS:
        assert leak not in text, leak
    assert not (tmp_path / "admincap").exists()
    assert logs[0].startswith("page captures on for this pilot")
    for bad in ("../x.html", "a/../../b", ".hidden"):
        q = c.write(bad, "x")
        assert q is None or os.path.dirname(q) == str(d), bad


@pytest.mark.parametrize("age", [CAPS.FLAG_MAX_S + 1, -CAPS.FLAG_AHEAD_S - 60])
def test_an_old_or_future_flag_is_off(tmp_path, age):
    _flag(tmp_path, age=age)
    c, _ = _pilot(tmp_path)
    assert c.on() is False and c.write("schedule.html", PAGE) is None


def test_a_symlinked_flag_or_folder_is_refused(tmp_path):
    d = tmp_path / "share" / "pilot2"
    d.mkdir(parents=True)
    real = tmp_path / "elsewhere"
    real.write_text("")
    os.symlink(real, d / CAPS.FLAG)
    c, _ = _pilot(tmp_path)
    assert c.on() is False
    os.remove(d / CAPS.FLAG)
    _flag(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, d / "captures")
    assert c.write("schedule.html", PAGE) is None and os.listdir(outside) == []


@pytest.mark.parametrize("name", ["Pilot2", "a__b", "captures", "../x", "pilot2/.."])
def test_a_bad_pilot_name_never_writes(tmp_path, name):
    c, _ = _pilot(tmp_path, name=name)
    assert c.folder() is None and c.on() is False and c.write("x.html", "x") is None


def test_old_captures_are_deleted_after_7_days(tmp_path):
    c, logs = _pilot(tmp_path)
    d = tmp_path / "share" / "pilot2" / "captures"
    d.mkdir(parents=True)
    old, new = d / "old.html", d / "new.html"
    old.write_text("x")
    new.write_text("y")
    t = time.time() - CAPS.KEEP_S - 60
    os.utime(old, (t, t))
    assert c.on() is False  # pruned while captures are off too
    assert not old.exists() and new.exists() and "page captures: 1 older than 7 days deleted" in logs


# ---------------------------------------------------------------- the Watcher's capture sites
@pytest.fixture
def load(tmp_path, monkeypatch):
    def _load(instance="pilot2"):
        data = tmp_path / ("data_" + (instance or "admin"))
        data.mkdir(exist_ok=True)
        (data / "options.json").write_text(json.dumps({"username": "doej2", "password": "pw-synthetic",
                                                       "log_level": "info", "category_check": "HNL 332 FO"}))
        if instance:  # a pilot's own logins come from creds.json (the add-on options are the admin's)
            (data / "creds.json").write_text(json.dumps({"username": "doej2", "password": "pw-synthetic"}))
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        for k in ("FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL"):
            monkeypatch.delenv(k, raising=False)
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        sys.modules.pop("watcher", None)
        import watcher as W
        monkeypatch.setattr(W.time, "sleep", lambda s: None)
        monkeypatch.setattr(W.CAP, "root", str(tmp_path / "share"))
        if not instance:
            monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "share" / "captures"))
        monkeypatch.setattr(IF, "CAPTURE_DIR", str(tmp_path / "share" / "captures"))
        monkeypatch.setattr(IF, "PROBE", {"logged": 0})
        W.MQ = type("MQ", (), {"msgs": [], "publish": lambda self, t, p=None, qos=0, retain=False: self.msgs.append((t, p))})()
        W.S.clear()
        W.S.update(pot_urls={"2026-11": "https://ha2.flica.net/full/otopentimepot.cgi?BCID=003.152"})
        return W
    yield _load
    sys.modules.pop("watcher", None)
    IF.WRITE = None


class FL:
    def __init__(self):
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return PAGE


POT = "<html><a href='https://ha2.flica.net/full/mobilepairing.cgi?PID=H9001'>H9001 view</a></html>"


def test_a_pilot_writes_nothing_and_loads_nothing_for_captures(load, tmp_path):
    W = load("pilot2")
    assert W.CAPTURE_DIR == "/share/flight_watcher/pilot2/captures" and IF.CAPTURE_DIR.endswith("captures")
    fl = FL()
    W.capture(fl, "2026-11", POT)  # the 6-hourly pot capture: no page saved, and no pairing page loaded for it
    assert fl.urls == []
    IF.capture(PAGE, "10001", W.log)  # inflt's other-pilot schedule capture
    W.trade_pages_scan(PAGE, "left menu")
    assert not (tmp_path / "share").exists()  # nothing in the admin's folder or the pilot's
    W.S["pilot_req"] = {"emp": "10001", "name": "Doe, Jane"}
    fl2 = FL()
    W.pilot_check(fl2)
    assert not any("Prompt=1&SchBrowser=1" in u and "EmployeeID" not in u for u in fl2.urls)  # no prompt page probe
    assert not (tmp_path / "share").exists()


def test_a_pilot_with_captures_on_gets_masked_files_in_his_folder(load, tmp_path):
    W = load("pilot2")
    _flag(tmp_path)
    W.S["own_emp"], W.S["own_name"] = "10001", "Doe, Jane"
    fl = FL()
    W.capture(fl, "2026-11", POT)
    IF.capture(PAGE, "10002", W.log)
    d = tmp_path / "share" / "pilot2" / "captures"
    names = sorted(os.listdir(d))
    assert "pot_2026-11.html" in names and "links_2026-11.json" in names and "cmschedule_NNNNN.html" in names
    for f in names:
        text = open(d / f).read()
        for leak in LEAKS + ("pw-synthetic",):
            assert leak not in text, (f, leak)
        assert stat.S_IMODE(os.stat(d / f).st_mode) == 0o600
    assert not (tmp_path / "share" / "captures").exists()  # never the admin's folder


def test_the_admin_captures_as_before(load, tmp_path):
    W = load("")
    fl = FL()
    W.capture(fl, "2026-11", POT)
    IF.capture(PAGE, "10002", W.log)
    d = tmp_path / "share" / "captures"
    assert open(d / "pot_2026-11.html").read() == POT and open(d / "cmschedule_10002.html").read() == PAGE
    assert json.load(open(d / "links_2026-11.json"))[0]["text"] == "H9001 view"
    assert fl.urls  # his pot capture still opens a pairing page, as in 1.6.1

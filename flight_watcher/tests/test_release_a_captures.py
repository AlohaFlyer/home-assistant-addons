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


def test_mask_by_structure_tradeboard_names_mails_phones():
    """1.6.2 review: the Tradeboard's 'FIRST LAST' cells and its JS rows ("JANE","DOE"), e-mail addresses, phone
    numbers and 3-7 digit numbers after Emp are masked too; the page's shape (pairings, dates, times) stays."""
    from test_tradeboard import HTML, JS
    out = CAPS.mask(HTML, []) + CAPS.mask(JS, [])
    for leak in ("JOHN ROE", "JOHN", "PAT POE", "DAN MOE", '"JANE"', '"DOE"', '"PAT"', '"POE"', "x@y.com",
                 "5550100100", "10021", "Trade%20for"):
        assert leak not in out, leak
    assert "H3612:10NOV" in out and "Oct 25, 2026 07:30:44 HA" in out and '"H3606"' in out and '"14:45"' in out
    assert "Propose Trade" in out and "HNL 332 FO" in out and '"20261104"' in out
    for text, leak in (("Jane Doe 10001", "Jane Doe"), ("JANE DOE", "JANE DOE"), ("Name: Jane Doe", "Jane"),
                       ("Posted by DOE J (10001)", "DOE"), ("DE LA CRUZ, MARIA", "CRUZ"), ("With Emp #: 1004", "1004"),
                       ("Call 808-555-0100", "555-0100"), ("mail doe.j@example.com", "example")):
        assert leak not in CAPS.mask(text, []), text


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


# ---------------------------------------------------------------- 1.6.2 review
def test_prune_never_follows_a_symlinked_pilot_folder(tmp_path):
    root = tmp_path / "share"
    (root / "captures").mkdir(parents=True)
    admin_old = root / "captures" / "admin_old.html"
    admin_old.write_text("the admin's")
    t = time.time() - 8 * 86400
    os.utime(admin_old, (t, t))
    os.symlink(root, root / "pilot2")  # <root>/pilot2 -> <root>: its 'captures' is the admin's folder
    c = CAPS.Captures("pilot2", root=str(root), log=lambda m: None)
    assert c.on() is False and c.prune(force=True) == 0 and c.cleanup_pilot() == 0
    assert admin_old.exists()


def test_the_one_time_cleanup_of_what_161_left(tmp_path):
    root = tmp_path / "share"
    adm = root / "captures"
    adm.mkdir(parents=True)
    for f in ("leftmenu.html", "scheduledetail_1126.html", "cmschedules_prompt.html", "ctweb_x.html",
              "cmschedule_10002.html", "pot_2026-11.html", "swapmap"):
        (adm / f).mkdir() if f == "swapmap" else (adm / f).write_text("x")
    assert CAPS.cleanup_admin(str(adm)) == 5
    assert sorted(os.listdir(adm)) == ["pot_2026-11.html", "swapmap"]  # his own other captures stay
    p = root / "pilot2"
    (p / "captures").mkdir(parents=True)
    (p / "last_login.png").write_bytes(b"\x89PNG")
    os.chmod(p / "captures", 0o755)
    c = CAPS.Captures("pilot2", root=str(root), log=lambda m: None)
    assert c.cleanup_pilot() == 1 and not (p / "last_login.png").exists()
    assert stat.S_IMODE(os.stat(p / "captures").st_mode) == 0o700


def test_the_watcher_runs_the_cleanup_once(load, tmp_path, monkeypatch):
    W = load("")
    adm = tmp_path / "share" / "captures"
    adm.mkdir(parents=True)
    (adm / "leftmenu.html").write_text("x")
    assert W.captures_cleanup() == 1 and not (adm / "leftmenu.html").exists()
    (adm / "leftmenu.html").write_text("x")
    assert W.captures_cleanup() == 0 and (adm / "leftmenu.html").exists()  # once (DB caps_cleanup_v)


def test_a_pilots_log_holds_no_page_names_mails_or_phones(load, tmp_path, caplog):
    import logging
    W = load("pilot2")
    W.S["pot_urls"] = {"mobile": "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"}
    page = ("<html><body>Tradeboard All Requests DOE, JANE JOHN ROE x@y.com 5550100100 Emp #: 10021"
            "<script>r=[\"JANE\",\"DOE\"]</script></body></html>")

    class F:
        def fetch(self, url):
            return page
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.S.pop("tb_raw_logged2", None)
        W.tradeboard_check(F(), full=True)  # the 'no trip rows' dump, captures off
        W.S["sched_probe_logged"] = False
        W.S["own_emp"] = "10001"
        W.schedule_check(F(), force=True)  # 'schedule page not parsed'
        W.log.info("a page line: %s", "Posted by DOE J; Jane Doe; x@y.com; 808-555-0100; doej2")
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in ("JANE", "DOE", "Jane Doe", "JOHN ROE", "x@y.com", "5550100100", "555-0100", "10021", "doej2"):
        assert leak not in text, leak
    assert "not logged: page captures are off" in text


def test_the_admins_log_is_as_before(load, caplog):
    import logging
    W = load("")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.log.info("a page line: %s", "Doe, Jane 10001")
    assert "Doe, Jane 10001" in caplog.text and W.page_log("Doe, Jane") == "Doe, Jane"

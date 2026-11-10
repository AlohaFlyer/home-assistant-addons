"""1.6.2 review fixes (Release A), group 1: account safety and FLICA load. A refused FLICA login is not retried by
Re-arm and a pilot's logins are 10 min apart; a pilot's un-pause checks with the session it has; a pilot's checks
start at least 120 s apart whatever wakes them (hunt, pause, Check now) and the jitter never takes him under it; a load
waiting for the budget gives up on Pause, and the reads that may be left out never eat the pot's budget; a CAPTCHA on
the main menu or the pot stops the Watcher (no new login); the admin's learned mobile schedule shape survives one
hiccup; a schedule read loads at most 2 pages in all and a listed month that fails backs off; a Tradeboard, pairing or
grid page no parser knows stops its path. FLICA is never reached: synthetic pages only ("Doe, Jane" 10001)."""
import collections
import contextlib
import json
import os
import types

import pytest

import gate as GT
from test_release_a_flica import (FORWARD, FX, INVALID, NOV, _lookup, mk, real_fl)  # noqa: F401


class Stop(Exception):
    pass


def _cmd(W, sub, payload=b"PRESS"):
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/{sub}", payload=payload))


def _run_main(W, monkeypatch, script, login="ok", check=None, max_sleeps=60, step=None):
    """The real main() with a fake browser: script(i) runs at every loop sleep (it may send commands). Returns
    (logins, checks): the clock times of each FLICA login and each check start. step: every sleep ends after at most
    that many seconds, as if something woke the loop each time (the worst case for the floors)."""
    monkeypatch.setenv("FLIGHT_WATCHER_WEB", "0")
    W.OPTS.update(username="u", password="p")
    logins, checks = [], []

    class FakeFlica:
        def __init__(self, pw):
            self.login_error = None

        def login(self):
            logins.append(W.CLOCK.t)  # when the login starts
            W.GATE.acquire()
            W.GATE.acquire()  # the login page and its submit: two gated loads, as Flica.login
            return login() if callable(login) else login

    def fake_check(fl):
        checks.append(W.CLOCK.t)
        W.S["last_check_ts"] = W.CLOCK.t
        return check() if callable(check) else (check or "ok")
    for f in ("migrate_swap_mode", "enforce_role", "captures_cleanup", "start_upload_janitor", "portal_start",
              "finds_files_cleanup",
              "publish_finds", "publish_blocked", "publish_tradeboard", "publish_own_trips", "publish_working_flight",
              "publish_trade", "publish_charters", "publish_improved", "publish_tickets", "publish_crew_index",
              "versions_check", "uploads_check", "recall_eval", "crew_split_repair", "charter_thread", "ccr_thread",
              "publish_rules"):
        monkeypatch.setattr(W, f, lambda *a, **k: None)
    monkeypatch.setattr(W, "mqtt_start", lambda: W.MQ)
    monkeypatch.setattr(W, "load_rules", lambda: [])
    monkeypatch.setattr(W, "sync_playwright", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(W, "Flica", FakeFlica)
    monkeypatch.setattr(W, "check", fake_check)
    W.DB.put("crew_dir_v", 1)
    W.DB.put("crew_fix_v", 1)
    W.DB.put("score_v", 2)
    n = {"i": 0}

    def fake_sleep(sec):
        n["i"] += 1
        if n["i"] > max_sleeps:
            raise Stop("enough")
        W.WAKE.clear()
        script(n["i"])
        due = W.WAKE_DUE["at"]
        if step:
            W.CLOCK.t += min(sec, step)
        elif W.WAKE.is_set():
            W.CLOCK.t += 1
        elif due and due - W.CLOCK.t < sec:
            W.CLOCK.t = max(W.CLOCK.t, due)
            W.WAKE_DUE["at"] = 0.0
        else:
            W.CLOCK.t += sec
    monkeypatch.setattr(W, "sleep", fake_sleep)
    try:
        W.main()
    except Stop:
        pass
    return logins, checks


# ------------------------------------------------------------------ 1: Re-arm after a refused FLICA login
def test_ten_rearm_presses_on_refused_details_make_no_login(mk, monkeypatch):
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": W.flica_creds_hash(), "at": W.CLOCK.t - 600}
    presses = {"n": 0}

    def script(i):
        if presses["n"] < 10:
            presses["n"] += 1
            _cmd(W, "rearm/press")
    logins, _ = _run_main(W, monkeypatch, script, login="failed", max_sleeps=30)
    assert presses["n"] == 10 and logins == []
    assert W.S["note"].startswith("FLICA refused these login details at ") and "Settings tab" in W.S["note"]


def test_a_refusal_is_kept_so_later_presses_make_no_second_login(mk, monkeypatch):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "one login attempt failed (re-arm)"  # from 1.6.1: no hash
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press"), login="failed", max_sleeps=40)
    assert len(logins) == 1  # the first press tries once; FLICA's refusal blocks the 39 after it
    assert W.S["flica_refused"]["hash"] == W.flica_creds_hash() and W.S["machine"] == "stopped_login_failed"
    assert "p" not in json.dumps(W.S["flica_refused"]).replace("hash", "")  # a hash and a time only


def test_a_captcha_login_stop_is_no_refusal_but_logins_stay_10_min_apart(mk, monkeypatch):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "FLICA asked for captcha/MFA/password change during login"
    t0 = W.S["login_ts"] = W.CLOCK.t - 60
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press"), login="blocked", max_sleeps=400, step=5)
    gaps = [b - a for a, b in zip([t0] + logins, logins)]
    assert len(logins) >= 2 and min(gaps) >= W.LOGIN_MIN_GAP_S - 1e-6, gaps  # a press every 5 s: one login a 10 min
    assert "flica_refused" not in W.S  # a CAPTCHA/MFA stop: Re-arm may try again (Ryan dealt with FLICA himself)
    assert "the FLICA login waits until" in W.S["note"] or W.S["note"].startswith("FLICA asked")


def test_new_details_clear_the_block_and_the_same_ones_give_one_more_try(mk, monkeypatch):
    W = mk("pilot2")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    W.OPTS.update(username="u", password="p")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": W.flica_creds_hash(), "at": W.CLOCK.t}
    W.S["login_ts"] = W.CLOCK.t
    json.dump({"username": "u", "password": "p"}, open(W.CREDS_FILE, "w"))
    W.WAKE.clear()
    W.settings_cmd(json.dumps({"username": "u", "password": "p"}))  # the same again: one more try (Re-arm's path)
    assert "flica_refused" not in W.S and W.FLAGS["rearm"] and W.WAKE.is_set() and W.S["login_ts"] == W.CLOCK.t
    W.FLAGS["rearm"] = False
    W.S["flica_refused"] = {"hash": W.flica_creds_hash(), "at": W.CLOCK.t}
    assert W.settings_cmd(json.dumps({"username": "u", "password": "p2"})) is True  # new details
    assert "flica_refused" not in W.S and "login_ts" not in W.S and W.S["machine"] == "idle"


def test_the_admin_keeps_his_rearm(mk, monkeypatch):
    W = mk("")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "one login attempt failed (re-arm)"
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i <= 3 else None, login="failed",
                          max_sleeps=6)
    assert len(logins) == 3 and "flica_refused" not in W.S


# ------------------------------------------------------------------ 2: un-pause on a pilot
def _pause_cycles(W):
    seq = {"on": True}

    def script(i):
        seq["on"] = not seq["on"]
        _cmd(W, "pause/set", b"ON" if seq["on"] else b"OFF")
    return script


def test_five_pause_cycles_make_no_login_with_a_live_session(mk, monkeypatch):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "paused", "paused"
    W.FLAGS["pause"] = True
    t0 = W.CLOCK.t
    logins, checks = _run_main(W, monkeypatch, _pause_cycles(W), login="ok", check="ok", max_sleeps=10)
    assert logins == [] and checks and W.CLOCK.t - t0 < 300


def test_five_pause_cycles_in_5_min_make_at_most_one_login(mk, monkeypatch):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "paused", "paused"
    W.FLAGS["pause"] = True
    t0 = W.CLOCK.t
    logins, checks = _run_main(W, monkeypatch, _pause_cycles(W), login="ok", check="needs_login", max_sleeps=10)
    assert len(logins) <= 1 and W.CLOCK.t - t0 <= 300, (logins, W.CLOCK.t - t0)


def test_the_admins_unpause_still_logs_in(mk, monkeypatch):
    W = mk("")
    W.S["machine"], W.S["note"] = "paused", "paused"
    W.FLAGS["pause"] = True
    logins, _ = _run_main(W, monkeypatch, _pause_cycles(W), login="ok", check="ok", max_sleeps=4)
    assert len(logins) >= 1


# ------------------------------------------------------------------ 3: a pilot's checks are 120 s apart
def _woke(W, sub, payload=b"PRESS"):
    W.WAKE.clear()
    _cmd(W, sub, payload)
    return W.WAKE.is_set()


def test_thirty_hunt_toggles_in_a_minute_give_at_most_one_wake(mk):
    W = mk("pilot2")
    W.S["machine"], W.S["last_check_ts"] = "hunting", W.CLOCK.t - 300
    wakes = 0
    for i in range(30):
        wakes += _woke(W, "hunt/set", b"ON" if i % 2 == 0 else b"OFF")
        W.CLOCK.t += 2
    assert wakes == 1 and W.WAKE_DUE["at"] >= W.S["wake_ts"] + 120 - 1


def test_thirty_portal_toggles_in_a_minute_start_at_most_one_check(mk, monkeypatch):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "hunting", ""
    W.S["last_check_ts"] = W.S["check_started_ts"] = W.CLOCK.t - 10
    t0 = W.CLOCK.t
    k = {"n": 0}

    def script(i):
        if W.CLOCK.t - t0 < 60:
            k["n"] += 1
            sub = ("hunt/set", "pause/set", "check_now/press")[k["n"] % 3]
            _cmd(W, sub, b"PRESS" if "press" in sub else (b"ON" if k["n"] % 2 else b"OFF"))
    _, checks = _run_main(W, monkeypatch, script, check="ok", max_sleeps=200, step=2)
    first_min = [c for c in checks if c - t0 < 110]
    assert k["n"] >= 29 and len(first_min) == 0, (k["n"], [c - t0 for c in checks])  # 2 s apart: 29 in a minute
    assert all(b - a >= 120 - 1e-6 for a, b in zip(checks, checks[1:])), [c - t0 for c in checks]


def test_check_now_on_a_pilot_waits_120_s_the_admin_10(mk):
    W = mk("pilot2")
    W.S["machine"], W.S["last_check_ts"] = "hunting", W.CLOCK.t - 11
    assert not _woke(W, "check_now/press")
    W.S["last_check_ts"] = W.CLOCK.t - 121
    assert _woke(W, "check_now/press")
    A = mk("")
    A.S["machine"], A.S["last_check_ts"] = "hunting", A.CLOCK.t - 11
    assert _woke(A, "check_now/press") and _woke(A, "hunt/set", b"ON")


# ------------------------------------------------------------------ 4: the jitter never takes a pilot under 120 s
def test_a_pilots_gap_never_goes_under_his_floor(mk):
    W = mk("pilot2")
    W.S["freq"] = {"hunt_s": 120, "normal_min": 2}
    W.FLAGS["hunt"] = True
    hunt = [W.gap() for _ in range(3000)]
    W.FLAGS["hunt"] = False
    normal = [W.gap() for _ in range(3000)]
    assert min(hunt) >= 120 and min(normal) >= 120 and max(hunt) <= 156 + 1e-6
    assert len({round(g) for g in hunt}) > 20  # still irregular
    A = mk("")
    A.S["freq"] = {"hunt_s": 40}
    A.FLAGS["hunt"] = True
    assert min(A.gap() for _ in range(3000)) < 30  # the admin's jitter is as before (40 s +-30 %)


# ------------------------------------------------------------------ 5: the gate gives up on Pause, keeps the pot's budget
def _fill(W, n, path="other.cgi"):
    fl = real_fl(W, lambda u: "<html>ok</html>")
    for i in range(n):
        fl.fetch(f"{W.BASE}/full/{path}?n={i}")
    return fl


def test_pause_during_a_budget_wait_loads_nothing(mk):
    W = mk("pilot2")
    fl = _fill(W, 100)
    W.S["machine"], W.S["note"] = "hunting", ""
    W.RUN["check"] = True
    real = W.GATE.on_wait

    def on_wait(why, until):
        if why:
            _cmd(W, "pause/set", b"ON")
        real(why, until)
    W.GATE.on_wait = on_wait
    t0 = W.CLOCK.t
    with pytest.raises(GT.GateAbort):
        fl.fetch(f"{W.BASE}/full/other.cgi?n=101")
    assert W.FLAGS["pause"] and len(fl.loads) == 100 and W.CLOCK.t - t0 <= GT.WAIT_CHUNK_S + 1e-6
    assert W.S["note"] == ""  # the budget note is cleared with the wait


def test_gate_abort_and_keep_unit(tmp_path):
    t = {"now": 1000.0}
    g = GT.Gate(str(tmp_path / "g.lock"), "p", budget=5, clock=lambda: t["now"],
                sleep=lambda s: t.__setitem__("now", t["now"] + s), rand=lambda: 1.5)
    for _ in range(2):
        g.acquire()
    with pytest.raises(GT.GateAbort):
        g.acquire(abort=lambda: "Pause is on")
    with pytest.raises(GT.GateSkip):
        g.acquire(keep=4)  # 2 used + this one would leave fewer than 4 of 5 free
    g.acquire(keep=2)  # 2 used + this one leaves 2 free: it goes (after pacing only)
    assert g.counts()["own"] == 3


def test_optional_reads_skip_instead_of_waiting_and_the_pot_still_loads(mk):
    W = mk("pilot2")
    pot_html = open(os.path.join(FX, "mobile_pot_rows.html")).read()
    fl = real_fl(W, lambda u: pot_html if "opentimepot" in u else "<html><body>Tradeboard</body></html>")
    for i in range(97):
        fl.fetch(f"{W.BASE}/full/other.cgi?n={i}")
    W.RUN.update(check=True, optional=True)
    with pytest.raises(GT.GateSkip):
        fl.fetch(f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr")  # 97 + 1 would leave under 4 of 100 free
    W.RUN.update(optional=False)
    n = len(fl.loads)
    fl.fetch(W.MOBILE_POT)  # the pot itself never skips (it waits for the budget instead)
    assert len(fl.loads) == n + 1


def test_optional_loads_never_take_the_pots_share_of_the_hour(mk):
    W = mk("pilot2")
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 120}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT, "mobile_003.153": W.MOBILE_POT + "&x=1"}
    cap = W.opt_cap()
    assert cap == 100 - 60 - 4 - 3  # 2 pot pages x 30 checks an hour, the schedule, one check's start
    fl = real_fl(W, lambda u: "<html><body>Tradeboard</body></html>")
    W.RUN.update(check=True, optional=True)
    for i in range(cap):
        fl.fetch(f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr")
    with pytest.raises(GT.GateSkip):
        fl.fetch(f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr")
    assert len(fl.loads) == cap


def test_three_hours_of_pilot_hunting_never_wait_inside_a_check(mk):
    """The main loop's own wait (check_tokens) and the optional reads' keep: a check never waits for the budget inside
    the gate, the budget holds, and the pot gets its reads."""
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 120, "normal_min": 2}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT,
                       "mobile_003.153": f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"}
    pot_html = open(os.path.join(FX, "mobile_pot_rows.html")).read()

    def ans(u):
        if "opentimepot" in u:
            return pot_html
        if "cmschedules" in u and "bd=1126" in u:
            return _lookup("1126")
        if "tb_" in u.lower():
            return "<html><body>Tradeboard All Requests</body></html>"
        if "reservegridservice" in u.lower():
            return "{}"
        return "<html><body>Pairing H9001 Check-In 08:00</body></html>"
    fl = real_fl(W, ans)
    W.Flica.render = lambda self, url, wait_for=None, timeout=30000: (self.fetch(url), [])
    waits = []
    real_acq = W.GATE.acquire

    def acq(**k):
        t = W.CLOCK.t
        real_acq(**k)
        waits.append(W.CLOCK.t - t)
    W.GATE.acquire = acq
    t0, checks = W.CLOCK.t, 0
    while W.CLOCK.t - t0 < 3 * 3600:
        wait, _ = W.GATE.free_in(min(W.check_tokens(), W.GATE.budget))
        if wait > 0:
            W.CLOCK.t += wait
            continue
        checks += 1
        W.RUN.update(check=True, aborted="", skipped=set())
        try:
            W.check(fl)
        finally:
            W.RUN["check"] = False
        W.CLOCK.t += W.gap()
    loads = [t for t, _ in fl.loads]
    worst = max(sum(1 for x in loads if t - 3600 < x <= t) for t in loads)
    kinds = collections.Counter("pot" if "opentimepot" in u else "other" for _, u in fl.loads)
    assert max(waits) <= GT.PACE_MAX_S + GT.HOST_GAP_S + 1e-6, max(waits)  # pacing only, never a budget wait
    # every check read both pot pages (none waited or was left out) and checks came at the hunt pace (120 to 156 s)
    assert worst <= 101 and kinds["pot"] == 2 * checks and checks >= int(3 * 3600 / 160), (worst, kinds, checks)


# ------------------------------------------------------------------ 6: a CAPTCHA on the main menu is a stop
def test_a_captcha_main_menu_and_pot_stop_with_no_login(mk):
    W = mk("pilot2")

    class Page:
        url = f"{W.BASE}/online/mainmenu.cgi"
        frames = []

        def goto(self, *a, **k):
            pass

        def content(self):
            return FORWARD

        def close(self):
            pass
    fl = real_fl(W, lambda u: FORWARD)
    fl.ctx.new_page = lambda: Page()
    W.S["pot_urls"] = {}
    assert W.check(fl) == "stop"
    assert W.S["machine"] == "stopped_unexpected" and "CAPTCHA page on the main menu (never answered)" in W.S["note"]
    assert len([u for _, u in fl.loads if "opentimepot" in u]) == 1  # the mobile pot once; no login follows a stop


def test_a_captcha_pot_page_is_a_stop_not_a_retry(mk):
    W = mk("pilot2")
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    for f in ("schedule_check", "own_trip_times", "publish_working_flight", "versions_check", "uploads_check"):
        setattr(W, f, lambda *a, **k: None)
    fl = real_fl(W, lambda u: FORWARD)
    assert W.check(fl) == "stop" and "CAPTCHA page on the open time pot" in W.S["note"]
    assert W.S.get("parse_fail", 0) == 0


def test_the_admins_menu_captcha_still_falls_back_to_the_mobile_pot(mk):
    W = mk("")
    pot_html = open(os.path.join(FX, "mobile_pot_rows.html")).read()

    class Page:
        url = f"{W.BASE}/online/mainmenu.cgi"
        frames = []

        def goto(self, *a, **k):
            pass

        def content(self):
            return FORWARD

        def close(self):
            pass
    fl = real_fl(W, lambda u: pot_html)
    fl.ctx.new_page = lambda: Page()
    fl.save = lambda: None
    urls = fl.discover_pot_urls()
    assert isinstance(urls, dict) and urls.get("mobile") == W.MOBILE_POT


# ------------------------------------------------------------------ 7: the admin's mobile shape survives a hiccup
NOV_NOTOT = NOV.replace("<p>Block 80.00</p><p>Credit 90.00</p>", "")


def test_one_timeout_does_not_lose_the_admins_bcid_shape(mk):
    W = mk("")
    W.S["own_emp"] = "10001"
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"  # as 1.6.2 stored it
    state = {"hiccup": True, "lookup_ok": True}

    def ans(u):
        if "BCID=001.152" in u:
            if state["hiccup"]:
                state["hiccup"] = False
                return TimeoutError("one slow answer")
            return NOV_NOTOT
        if "cmschedules" in u:
            return _lookup("1126") if state["lookup_ok"] else INVALID
        return INVALID
    fl = real_fl(W, ans)
    W.schedule_check(fl, force=True)
    assert W.S["sched_shape"] == "lookup"  # Schedule Lookup answered this read
    state["lookup_ok"] = False
    W.CLOCK.t += 4 * 3600
    n = len(fl.loads)
    W.schedule_check(fl)
    tried = [u for _, u in fl.loads[n:]]
    assert any("BCID=001.152" in u for u in tried) and len(tried) <= 2, tried
    assert W.S["sched_shape"] == "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"


# ------------------------------------------------------------------ 8: 2 loads a read, a failing month backs off
def _lookup_multi(bd):
    h = _lookup(bd)
    opts = "".join(f'<option value="{b}"{" selected" if b == bd else ""}> {b}' for b in ("1026", "1126", "1226"))
    return h.replace(f'<option value="{bd}" selected> M</select>', opts + '</select>')


def test_a_schedule_read_loads_at_most_2_pages_in_all(mk):
    W = mk("")
    W.S["own_emp"] = "10001"
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"

    def ans(u):
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4]
            return _lookup_multi(bd) if bd != "1226" else INVALID
        if "mobileschedule" in u and "BCID=001.152" in u:
            return NOV_NOTOT
        return INVALID
    fl = real_fl(W, ans)
    per = []
    for k in range(5):
        n = len(fl.loads)
        W.schedule_check(fl, force=(k == 0))
        per.append(len(fl.loads) - n)
        W.CLOCK.t += W.SCHED_GAP_S + 1
    assert max(per) <= 2 and "2026-10" in W.S["schedule"], per  # October came in on a later read


def test_a_pilots_failing_month_is_not_reloaded_every_read(mk):
    W = mk("pilot2")
    W.S["own_emp"] = "10001"

    def ans(u):
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4]
            return _lookup_multi(bd) if bd != "1226" else INVALID
        return INVALID
    fl = real_fl(W, ans)
    dec, per = [], []
    for k in range(6):  # 3 hours of 30-min reads
        n = len(fl.loads)
        W.schedule_check(fl, force=(k == 0))
        got = fl.loads[n:]
        per.append(len(got))
        dec += [t for t, u in got if "bd=1226" in u]
        W.CLOCK.t += W.SCHED_GAP_S + 1
    assert max(per) <= 2, per
    assert len(dec) <= 2 and all(b - a >= 3600 for a, b in zip(dec, dec[1:])), dec
    assert W.S["sched_prev_at"] and "2026-10" in W.S["schedule"]
    assert W.BRK.allow("lookup")  # one month's odd answer while Schedule Lookup works: the path is not stopped


# ------------------------------------------------------------------ 9: unknown Tradeboard, pairing, grid pages
UNAVAIL = "<html><body>Service Temporarily Unavailable</body></html>"


def test_an_unknown_tradeboard_page_stops_it_for_30_min(mk):
    W = mk("pilot2")
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    fl = real_fl(W, lambda u: UNAVAIL)
    for k in range(10):
        try:
            W.tradeboard_check(fl, full=True)
        except GT.BreakerOpen:
            pass
    tb = [u for _, u in fl.loads if "tb_" in u.lower()]
    assert len(tb) == 1 and not W.BRK.allow("tradeboard")
    assert W.BRK.until("tradeboard") - W.CLOCK.t == pytest.approx(1800, abs=60)
    assert W.S["breakers"]["tradeboard"]["kind"] == "unknown"


def test_an_unknown_pairing_page_stops_pairings_and_a_good_one_is_a_good_read(mk):
    W = mk("pilot2")
    fl = real_fl(W, lambda u: UNAVAIL)
    fl.fetch(f"{W.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261106")
    assert not W.BRK.allow("pairing")
    with pytest.raises(GT.BreakerOpen):
        fl.fetch(f"{W.BASE}/full/mobilepairing.cgi?PID=H9002&DATE=20261106")
    W2 = mk("pilot3")
    fl2 = real_fl(W2, lambda u: "<html><body>H9001 nothing readable</body></html>")
    for _ in range(2):
        fl2.fetch(f"{W2.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261106")
    assert W2.BRK.allow("pairing")  # the asked pairing's own page: a failed read (3 in a row stop), not unknown
    fl2.fetch(f"{W2.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261106")
    assert not W2.BRK.allow("pairing")


def test_an_unknown_grid_answer_stops_the_grid(mk):
    W = mk("pilot2")
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    fl = real_fl(W, lambda u: UNAVAIL)
    W.Flica.render = lambda self, url, wait_for=None, timeout=30000: (self.fetch(url), [])
    try:
        W.grid_check(fl, full=True)
    except GT.BreakerOpen:
        pass
    assert not W.BRK.allow("grid") and len(fl.loads) == 1
    good = mk("pilot3")
    fl3 = real_fl(good, lambda u: "{}")
    fl3.fetch(f"{good.BASE}/full/reserveGridService.cgi?bcid=003.152&json=1")
    assert good.BRK.allow("grid")

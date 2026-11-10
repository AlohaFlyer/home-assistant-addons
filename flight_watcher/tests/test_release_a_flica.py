"""1.6.2 (Release A, group 1): FLICA load and the schedule read in watcher.py. Items: 1 the host-wide gate in Flica
(every load paced, a pilot's budget, the state note), 2 a pilot's hunt floor of 120 s, 3 the read-path breakers and
pot.classify's CAPTCHA kind, 4 the schedule read (2 loads, pages already in use, a shape that survives the bid period
rollover, the month asked for), 5 the awarded line published and the read status, 6 which commands wake a check, 7 the
portal export order. FLICA is never reached: a fake browser context answers with synthetic pages (made-up names and
numbers, "Doe, Jane" 10001)."""
import json
import logging
import os
import sys
import types
from datetime import datetime, timezone

import pytest

import gate as GT
import pot

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NOV6 = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc).timestamp()  # Nov 6 08:00 HST
DEC5 = datetime(2026, 12, 5, 18, 0, tzinfo=timezone.utc).timestamp()
KILLED = "<html>a new session under this account was detected</html>"
INVALID = "<html><body>flica.net - Mobile Schedule Invalid or unspecified bid period</body></html>"
FORWARD = ("<html><head><script src='https://www.google.com/recaptcha/api.js'></script><script>function goContinue()"
           " { if (grecaptcha.getResponse() == '') { alert('Please check the check box I`m not a robot'); } }</script>"
           "</head><body>Schedule Details. This is going to forward to the schedule details page."
           "<div class='g-recaptcha' data-sitekey='x'></div></body></html>")
DOW = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")


def _mobile(year, month, ndays, first_dow, trips=None):
    """A mobile schedule page (pot.parse_schedule's layout) for one month. trips: {day: (pairing, layover, days)}."""
    name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month - 1]
    rows = {}
    for d, (pid, lay, n) in (trips or {}).items():
        rows[d] = (f"<a>{pid}</a>", lay)
        for j in range(1, n):
            rows.setdefault(d + j, ("-", "HNL" if j == n - 1 else "-"))
    body = "".join(f"<tr><td>{DOW[(first_dow + d - 1) % 7]}</td><td>{d:02d}</td><td>{rows.get(d, ('-', '-'))[0]}</td>"
                   f"<td>{rows.get(d, ('-', '-'))[1]}</td></tr>" for d in range(1, ndays + 1))
    return (f"<html><body><div>{name} {year} Schedule</div><table><tr><td>Schedule Updated:<br>{name} 1, {year} 09:00:00"
            " HA</td></tr></table><table border=1><tr><th>Day</th><th>Pairing</th><th>Layover</th></tr>" + body +
            "</table><p>Block 80.00</p><p>Credit 90.00</p><p>Days Off 16</p></body></html>")


NOV = _mobile(2026, 11, 30, 0, {6: ("H9001", "LAX", 2), 18: ("H9002", "SEA", 2)})
DEC = _mobile(2026, 12, 31, 2, {3: ("H9003", "SYD", 4)})


def _lookup(bd, trips=(("02", "H9101", "SFO"),)):
    """Tools > Schedule Lookup for the pilot's own number (inflt.parse_cm_month's layout), synthetic."""
    y, m = 2000 + int(bd[2:]), int(bd[:2])
    import calendar
    n, dow0 = calendar.monthrange(y, m)[1], (calendar.monthrange(y, m)[0] + 1) % 7
    code = {d: (t, lay) for d, t, lay in trips}
    tasks = "".join(f'TAry[TAry.length]=new Task(1, "{DOW[(dow0 + d - 1) % 7]}", "{d:02d}", '
                    f'"{code.get(f"{d:02d}", ("", ""))[0]}", "{code.get(f"{d:02d}", ("", ""))[1]}", "{y}{m:02d}{d:02d}");'
                    for d in range(1, n + 1))
    return (f'<html><script>function pair(pr){{}} {tasks}</script><select name="BlockDates">'
            f'<option value="{bd}" selected> M</select> DOE, JANE (Emp# 10001) Schedule Last Updated: Nov 4, 2026 13:52:55'
            " HA<TABLE><TR><TD Colspan=2 Class='left'>Block &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>70.00 &nbsp;&nbsp;"
            "</TD></TR><TR><TD Colspan=2 Class='left'>Credit &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>85.00"
            " &nbsp;&nbsp;</TD></TR></TABLE></html>")


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, float(s))


class FakeMQ:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.msgs.append((topic, payload))

    def last(self, topic):
        return next((json.loads(p) for t, p in reversed(self.msgs) if t == topic), None)


@pytest.fixture
def mk(tmp_path, monkeypatch):
    def load(instance="", t=NOV6):
        data = tmp_path / ("d_" + (instance or "admin"))
        data.mkdir(exist_ok=True)
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        for k in ("FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL", "FLIGHT_WATCHER_GATE"):
            monkeypatch.delenv(k, raising=False)
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "category_check": "HNL 332 FO"}))
        sys.modules.pop("watcher", None)
        import watcher as W
        clock = Clock(t)
        monkeypatch.setattr("time.time", clock)
        monkeypatch.setattr("time.sleep", clock.sleep)
        monkeypatch.setattr(W, "local_now", lambda: datetime.fromtimestamp(clock.t, W.HST).replace(tzinfo=None))
        monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "cap"))
        monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
        monkeypatch.setattr(W, "UPLOADS", str(tmp_path / "uploads"))
        W.MQ = FakeMQ()
        W.OPTS.update(idle_min_s=300, idle_max_s=420, hunt_min_s=30, hunt_max_s=50)  # the add-on's option defaults
        W.S.clear()
        for k, v in json.loads(json.dumps(W.DEFAULT_STATE)).items():
            W.S.setdefault(k, v)
        W.S["sched_probe_logged"] = True  # the once-ever capture of an unparsed page is done
        W.CLOCK = clock
        return W
    yield load
    sys.modules.pop("watcher", None)


def real_fl(W, answer):
    """W.Flica with a fake browser context: answer(url) gives the page (or an Exception to raise). .loads keeps
    (time, url) of every load that reached the context, i.e. FLICA."""
    fl = W.Flica.__new__(W.Flica)
    fl.loads = []

    class Resp:
        def __init__(self, t):
            self._t = t

        def text(self):
            return self._t

    def get(url, timeout=None):
        fl.loads.append((W.CLOCK.t, url))
        v = answer(url)
        if isinstance(v, Exception):
            raise v
        return Resp(v)
    fl.ctx = types.SimpleNamespace(request=types.SimpleNamespace(get=get))
    return fl


def _sched_loads(fl):
    return [u for _, u in fl.loads if "schedule" in u or "cmschedules" in u]


# ------------------------------------------------------------------ item 1: the gate inside Flica
def test_every_flica_load_is_paced_including_the_pot_after_the_schedule(mk):
    W = mk()
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    W.S["own_emp"] = "10001"
    for f in ("own_trip_times", "publish_working_flight", "versions_check", "uploads_check"):
        setattr(W, f, lambda *a, **k: None)
    fl = real_fl(W, lambda u: KILLED if "opentimepot" in u else INVALID)
    assert W.check(fl) == "killed"
    urls = [u for _, u in fl.loads]
    assert len(_sched_loads(fl)) == 2 and "opentimepot" in urls[-1]  # two schedule tries, then the pot
    ts = [t for t, _ in fl.loads]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert gaps and min(gaps) >= 1.5 - 1e-6, gaps  # the pot read too (it came about 0 s after the schedule before)
    log = json.loads(open(W.GATE_FILE).read())["log"]
    assert len(log) == len(fl.loads) and {w for _, w in log} == {"admin"}  # every load counted on the host's log


def test_a_pilot_waits_for_his_hourly_budget_and_the_note_says_so(mk):
    W = mk("pilot2")
    assert W.GATE.budget == 100
    fl = real_fl(W, lambda u: "<html>ok</html>")
    t0 = W.CLOCK.t
    for i in range(100):  # a path no parser judges (a pairing page must now read as one: 1.6.2 review)
        fl.fetch(f"{W.BASE}/full/other.cgi?n={i:03d}")
    W.S["machine"], W.S["note"] = "hunting", ""
    notes = []
    real = W.set_machine
    W.set_machine = lambda st, note="": (notes.append(note), real(st, note))
    fl.fetch(f"{W.BASE}/full/other.cgi?n=999")  # the 101st: waits, never skipped
    assert len(fl.loads) == 101 and fl.loads[-1][0] >= t0 + 3600
    assert notes[0].startswith("FLICA budget: 100 page loads in the last hour; the next one waits until ")
    assert notes[0].endswith(" HST") and notes[-1] == ""  # cleared once the load went


def test_the_main_loop_waits_out_an_empty_bucket_before_a_check(mk, monkeypatch):
    """A check starts only with GATE_CHECK_TOKENS loads free; until then the loop sleeps (WAKE-able) with the note."""
    W = mk("pilot2")
    now = W.CLOCK.t
    log = [[now - 3500 + i * 30, "pilot2"] for i in range(99)]
    open(W.GATE_FILE, "w").write(json.dumps({"v": 1, "last": log[-1][0], "log": log}))
    w, why = W.GATE.free_in(W.GATE_CHECK_TOKENS)
    assert why == "budget" and 0 < w <= 3600 and abs(w - (log[1][0] + 3600 - now)) < 1e-6


# ------------------------------------------------------------------ item 2: a pilot hunts every 120 s at the fastest
def test_pilot_hunt_floor_slider_clamp_and_migration(mk, caplog):
    W = mk("pilot2")
    nums = {cfg["command_topic"].split("/")[-2]: (cfg["min"], cfg["max"]) for comp, _, cfg, _ in W.entity_defs()
            if comp == "number" and "/freq/" in (cfg.get("command_topic") or "")}
    assert nums["hunt_s"][0] == 120 and nums["normal_min"][0] == 2
    W.S["freq"] = {"hunt_s": 40, "normal_min": 6}  # a pilot's 40 s stored before 1.6.2
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.freq_migrate() == ["hunt_s 40 -> 120"]
    assert W.S["freq"]["hunt_s"] == 120 and W.freq()["hunt_s"] == 120
    assert len([r for r in caplog.records if "check frequency moved" in r.getMessage()]) == 1
    assert W.freq_migrate() == []  # once
    msg = types.SimpleNamespace(topic="flight_watcher_pilot2/freq/hunt_s/set", payload=b"30")  # the portal allows 5-90
    W.on_message(W.MQ, None, msg)
    assert W.S["freq"]["hunt_s"] == 120 and ("flight_watcher_pilot2/freq/hunt_s/state", "120") in W.MQ.msgs


def test_admin_keeps_his_hunt_range(mk):
    W = mk("")
    nums = {cfg["command_topic"].split("/")[-2]: (cfg["min"], cfg["max"]) for comp, _, cfg, _ in W.entity_defs()
            if comp == "number" and "/freq/" in (cfg.get("command_topic") or "")}
    assert nums == {"normal_min": (1, 20), "hunt_s": (5, 90)}
    W.S["freq"] = {"hunt_s": 40}
    assert W.freq_migrate() == [] and W.freq()["hunt_s"] == 40
    W.on_message(W.MQ, None, types.SimpleNamespace(topic="flight_watcher/freq/hunt_s/set", payload=b"30"))
    assert W.S["freq"]["hunt_s"] == 30


# ------------------------------------------------------------------ item 3: breakers and the CAPTCHA kind
def test_classify_never_calls_the_recaptcha_forward_page_ok(fx):
    assert pot.classify(FORWARD) == "captcha"
    assert pot.classify(fx("mobile_pot_rows.html")) == "ok"  # loads recaptcha/api.js like every FLICA page
    assert pot.classify(fx("mainmenu.html")) == "ok"
    assert pot.classify(fx("blocked.html")) == "blocked" and pot.classify(fx("expired.html")) == "expired"


def test_a_captcha_page_stops_its_read_path_for_6_hours_once(mk, caplog):
    W = mk()
    W.S["machine"], W.S["note"] = "idle", ""
    fl = real_fl(W, lambda u: FORWARD)
    url = f"{W.BASE}/full/mobileotrequest.cgi?BCID=003.152&From=MainMenu"
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert fl.fetch(url) == FORWARD
        with pytest.raises(GT.BreakerOpen):
            fl.fetch(url)  # refused before the load: FLICA never sees it again
    assert len(fl.loads) == 1
    assert W.BRK.until("requests") == pytest.approx(W.CLOCK.t + 6 * 3600, abs=10)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("FLICA requests read stopped")]
    assert len(lines) == 1 and "6 h" in lines[0] and "CAPTCHA" in lines[0]
    assert W.S["note"].startswith("FLICA requests read paused until ") and "CAPTCHA page (never answered)" in W.S["note"]
    assert W.S["breakers"]["requests"]["kind"] == "captcha"  # kept in the state: a restart keeps the stop
    W.CLOCK.t += 6 * 3600 + 1
    assert W.BRK.allow("requests")


def test_the_pot_page_has_no_breaker(mk):
    W = mk()
    fl = real_fl(W, lambda u: FORWARD)
    for _ in range(4):
        fl.fetch(W.MOBILE_POT)
    assert len(fl.loads) == 4 and not W.BRK.open_paths()  # the pot watch keeps its own stop rules


def test_three_failed_reads_stop_a_path_30_min_then_60_and_a_good_read_resets(mk):
    W = mk()
    state = {"err": True}
    fl = real_fl(W, lambda u: RuntimeError("synthetic: net::ERR_TIMED_OUT") if state["err"] else
                 "<html><frameset><frame src='tb_otherrequests.cgi?BCID=001.152'></frameset></html>")
    url = f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr"
    for i in range(3):
        with pytest.raises(RuntimeError):
            fl.fetch(url)
        assert W.BRK.allow("tradeboard") is (i < 2)
    t_open = W.BRK.until("tradeboard")
    assert t_open - W.CLOCK.t == pytest.approx(1800, abs=10)
    W.CLOCK.t = t_open
    with pytest.raises(RuntimeError):
        fl.fetch(url)  # the first read after the stop fails too: stopped again, twice as long
    assert W.BRK.until("tradeboard") - W.CLOCK.t == pytest.approx(3600, abs=10)
    W.CLOCK.t = W.BRK.until("tradeboard")
    state["err"] = False
    fl.fetch(url)
    assert W.S["breakers"]["tradeboard"] == {"open_until": 0, "trips": 0, "fails": 0}
    assert len(fl.loads) == 5


def test_a_page_the_request_parser_does_not_know_stops_the_list_at_once(mk):
    W = mk()
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    W.S["req_force"] = True
    fl = real_fl(W, lambda u: "<html><body>Maintenance tonight, back soon</body></html>")
    W.requests_check(fl)
    assert not W.BRK.allow("requests") and W.S["breakers"]["requests"]["kind"] == "unknown"
    assert W.BRK.until("requests") - W.CLOCK.t == pytest.approx(1800, abs=30)
    lists = lambda: [u for _, u in fl.loads if "mobileotrequest" in u]  # noqa: E731
    n = len(lists())
    assert n == 1
    W.S["req_force"] = True
    W.requests_check(fl)
    assert len(lists()) == n  # stopped: the list is not loaded


def test_a_stopped_read_path_never_ends_the_check(mk):
    W = mk()
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    for f in ("schedule_check", "own_trip_times", "publish_working_flight", "versions_check", "uploads_check",
              "email_check", "pickup_check", "requests_check", "grid_check", "crew_index_check", "close_in_check"):
        setattr(W, f, (lambda *a, **k: ({}, "ok")) if f == "close_in_check" else (lambda *a, **k: "ok"))

    def tradeboard(fl, full=False):
        raise GT.BreakerOpen("tradeboard", "12:00 HST")
    W.tradeboard_check = tradeboard
    pot_html = open(os.path.join(FX, "mobile_pot_rows.html")).read()
    fl = real_fl(W, lambda u: pot_html)
    W.S["fingerprints"] = {}
    assert W.check(fl) == "ok"


# ------------------------------------------------------------------ item 4: the schedule read
def test_a_fresh_pilot_reads_his_month_on_schedule_lookup_in_one_load(mk):
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    fl = real_fl(W, lambda u: _lookup("1126") if "cmschedules" in u and "bd=1126" in u else INVALID)
    W.schedule_check(fl, force=True)
    nov = W.S["schedule"]["2026-11"]
    assert nov["src"] == "lookup" and nov["items"][0]["trip"] == "H9101" and nov["totals"]["credit"] == "85:00"
    assert len(_sched_loads(fl)) == 1 and W.S["sched_shape"] == "lookup"
    sched = W.MQ.last("flight_watcher_pilot2/schedule")
    assert sched["source"] == "FLICA Schedule Lookup (Watcher)" and sched["read_status"]["ok"] is True
    assert "2026-11" in sched["months"]
    W.CLOCK.t += 1801
    W.schedule_check(fl)
    assert len(_sched_loads(fl)) == 2 and "bd=1126" in _sched_loads(fl)[1]  # the next read: the shape, one load
    assert not [u for _, u in fl.loads if "scheduledetail" in u or "BCID=" in u and "mobileschedule" in u]


def test_at_most_two_loads_per_read_only_pages_in_use_never_scheduledetail(mk):
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    fl = real_fl(W, lambda u: INVALID)
    for k in range(4):
        W.CLOCK.t = NOV6 + k * 4 * 3600
        n = len(fl.loads)
        W.schedule_check(fl, force=(k == 0))
        got = [u for _, u in fl.loads[n:]]
        assert len(got) <= W.SCHED_TRIES_PER_READ, got
    urls = [u for _, u in fl.loads]
    assert urls and not [u for u in urls if "scheduledetail" in u]
    assert {u.split("?")[0].rsplit("/", 1)[-1] for u in urls} <= {"cmschedules.cgi", "mobileschedule.cgi"}
    assert not [u for u in urls if "BCID=" in u]  # no BCID guesses for a pilot with no shape learned
    assert all("BlockDate=1126" in u for u in urls if "mobileschedule" in u)


def test_the_admins_learned_url_follows_the_bid_period_rollover(mk):
    """The verifier's Dec 5 case: a literal BCID=001.152 kept from November, the pot rediscovered on 003.153; the
    shape is filled with December's period (153), December is read, and November is never taken for December."""
    W = mk("", t=DEC5)
    W.S["sched_url_ok"] = f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&From=MainMenu"
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT, "mobile_003.153": f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153"}
    W.S["schedule"] = {"2026-11": {"month": "2026-11", "items": [], "days": [], "totals": {}, "updated": "x"}}
    fl = real_fl(W, lambda u: DEC if "BCID=001.153" in u else NOV if "BCID=001.152" in u else INVALID)
    W.schedule_check(fl, force=True)
    assert [u for _, u in fl.loads][0].endswith("BCID=001.153&From=MainMenu")
    assert "2026-12" in W.S["schedule"] and W.S["schedule"]["2026-12"]["items"][0]["trip"] == "H9003"
    assert W.S["sched_shape"] == "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"


def test_a_page_for_another_month_is_refused(mk):
    W = mk("", t=DEC5)
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"
    fl = real_fl(W, lambda u: NOV)  # FLICA still answers with November
    W.schedule_check(fl, force=True)
    assert "2026-12" not in W.S.get("schedule", {}) and W.S["sched_fail"] == 1
    st = W.MQ.last("flight_watcher/schedule")["read_status"]
    assert st["ok"] is False and "FLICA gave the 2026-11 schedule, not 2026-12" in st["why"]


def test_a_failed_read_publishes_why_and_the_next_try_in_hst(mk):
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    fl = real_fl(W, lambda u: INVALID)
    W.schedule_check(fl, force=True)
    sched = W.MQ.last("flight_watcher_pilot2/schedule")
    st = sched["read_status"]
    assert sched["months"] == {} and st["ok"] is False and st["tries"] == 2
    assert st["at_hst"] == "08:00" and st["next_hst"] == "08:10"  # the 1.6.1 back-off: 10 min after the first
    assert "mobile schedule: FLICA answered 'invalid or unspecified bid period'" in st["why"]
    assert "10001" not in json.dumps(sched) and "http" not in st["why"]  # no employee number, no URL


def test_previous_month_never_loads_scheduledetail(mk):
    W = mk()
    W.S["sched_prev_at"] = 0
    fl = real_fl(W, lambda u: INVALID)
    W.prev_month_check(fl, f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&From=MainMenu", "2026-11")
    urls = [u for _, u in fl.loads]
    assert urls == [f"{W.BASE}/full/mobileschedule.cgi?BlockDate=1026&From=MainMenu"]
    assert not hasattr(W, "desktop_schedule")


def test_schedule_tries_are_paced_1_5_to_3_5_s(mk):
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    fl = real_fl(W, lambda u: INVALID)
    W.schedule_check(fl, force=True)
    (a, _), (b, _) = fl.loads
    assert 1.5 <= b - a <= 7.0  # the explicit 1.5-3.5 s pause, then the gate's own


# ------------------------------------------------------------------ item 5: the awarded line is published
def _award(W, month="2026-11"):
    days = [[f"{month}-{d:02d}", "", ""] for d in range(1, 31)]
    days[1] = [f"{month}-02", "H9101", "SFO"]
    sched = {"items": [{"trip": "H9101", "start": f"{month}-02", "end": f"{month}-02", "lay": "SFO"}], "days": days,
             "totals": {"credit": "86:32"}}
    return W.VER.set_award(W.DB, month, sched, W.now_iso())


def test_the_award_version_is_published_with_no_flica_month(mk):
    W = mk("pilot2")
    _award(W)
    W.versions_check(force_pub=True)
    sv = W.MQ.last("flight_watcher_pilot2/schedule_versions")
    assert sv["count"] == 1 and sv["months"]["2026-11"]["awarded"] == "11.001"
    key = sv["file_key"]
    body = json.load(open(os.path.join(W.finds_dir(), f"versions_{key}.json")))
    assert body["months"]["2026-11"]["versions"][0]["award"] is True


def test_the_admins_published_months_are_unchanged(mk):
    W = mk()
    months = {m: {"month": m, "items": [], "days": [[f"{m}-01", "", ""]], "totals": {}, "updated": "x"}
              for m in ("2026-10", "2026-11", "2026-12")}
    W.S["schedule"] = months
    assert W.versions_months(months) == set(months)
    W.DB.put("sched_versions:2027-01", [{"ver": "1.001", "items": [], "days": []}])  # not an award: not added
    assert W.versions_months(months) == set(months)


# ------------------------------------------------------------------ item 6: which commands wake a FLICA check
def _woke(W, sub, payload=b"PRESS"):
    W.WAKE.clear()
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/{sub}", payload=payload))
    return W.WAKE.is_set()


def test_on_a_pilot_only_check_now_and_switch_changes_wake_a_check(mk, monkeypatch):
    W = mk("pilot2")
    monkeypatch.setattr(W, "charter_press", lambda: None)
    W.S["machine"] = "hunting"
    W.S["last_check_ts"] = W.CLOCK.t - 130  # 1.6.2 review: past the pilot's 120 s floor
    assert not _woke(W, "charter_scan/press")
    assert not _woke(W, "pilot/set", json.dumps({"q": "10001"}).encode())
    assert not _woke(W, "freq/hunt_s/set", b"150")
    assert not _woke(W, "freq/normal_min/set", b"6")
    assert not _woke(W, "rearm/press")  # hunting: Re-arm does nothing, so no check either
    assert not _woke(W, "anything/else")
    assert _woke(W, "hunt/set", b"ON") and not _woke(W, "hunt/set", b"ON")  # a change wakes; the same value does not
    assert _woke(W, "pause/set", b"ON") and not _woke(W, "pause/set", b"ON")  # Pause on loads nothing: always wakes
    W.S["wake_ts"] = 0
    assert _woke(W, "check_now/press")
    W.S["wake_ts"], W.S["last_check_ts"] = 0, W.CLOCK.t - 119
    assert not _woke(W, "check_now/press")  # a pilot's gap is his 120 s floor (the admin's 10 s)
    W.S["machine"] = "stopped_unexpected"
    assert _woke(W, "rearm/press")


def test_the_admin_keeps_his_wakes_except_scan_crewtrac(mk, monkeypatch):
    W = mk("")
    monkeypatch.setattr(W, "charter_press", lambda: None)
    W.S["machine"] = "idle"
    assert not _woke(W, "charter_scan/press")
    assert _woke(W, "pilot/set", json.dumps({"q": "10001"}).encode())
    assert _woke(W, "freq/hunt_s/set", b"40")


# ------------------------------------------------------------------ item 7: files before the state
def test_the_export_writes_list_files_and_manifest_before_the_state(portal_pilot):
    from conftest import ha_state
    W, ha = portal_pilot("pilot2", states={"sensor.flight_watcher_pilot2_schedule_versions":
                                           ha_state("sensor.flight_watcher_pilot2_schedule_versions", "1", {"rev": "a"})})
    assert W.portal_start(threads=False)
    W.portal_export_once(full=True)
    order = []
    w = W.EXPORT["writer"]
    real = w.write
    w.write = lambda kind, body: (order.append(kind), real(kind, body))[1]
    W.write_list_file("versions", {"months": {"2026-11": {"count": 1}}})
    ha.states["sensor.flight_watcher_pilot2_schedule_versions"] = ha_state(
        "sensor.flight_watcher_pilot2_schedule_versions", "1", {"rev": "b"})
    W.pub("schedule_versions", {"count": 1, "rev": "b"})
    W.portal_export_once()
    assert "file:versions" in order and "state" in order and "manifest" in order, order
    assert order.index("file:versions") < order.index("manifest") < order.index("state"), order


def test_two_pages_of_one_path_in_a_read_are_one_failed_read(mk):
    """The breaker counts reads, not loads: the admin's learned BCID page and the BlockDate page both fail in each read
    (one path, 'schedule'); it stops the read on the 3rd failed read, not the 2nd."""
    W = mk()
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"
    fl = real_fl(W, lambda u: INVALID)
    for k, (loads, stopped) in enumerate(((2, False), (2, False), (1, True))):  # the 3rd stops after its first page
        W.CLOCK.t = NOV6 + k * 3 * 3600
        n = len(fl.loads)
        W.schedule_check(fl, force=(k == 0))
        assert len(fl.loads) - n == loads and (not W.BRK.allow("schedule")) is stopped, k
    assert W.BRK.until("schedule") - W.CLOCK.t == pytest.approx(1800, abs=30)
    assert W.S["sched_next_at"] >= W.BRK.until("schedule")  # the next read waits for the breaker
    st = W.MQ.last("flight_watcher/schedule")["read_status"]
    assert st["next_hst"] == W.hst_hm(W.S["sched_next_at"])


def test_an_old_literal_url_becomes_a_shape_once(mk, caplog):
    W = mk()
    W.S["sched_url_ok"] = f"{W.BASE}/full/scheduledetail.cgi?BlockDate=1126"  # never kept: the reCAPTCHA page
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.sched_cands("2026-11")
        W.sched_cands("2026-11")
    assert W.S["sched_shape"] == "" and len([r for r in caplog.records if "kept as a shape" in r.getMessage()]) == 1
    assert [u for _, u in W.sched_cands("2026-11")] == [f"{W.BASE}/full/mobileschedule.cgi?BlockDate=1126&From=MainMenu"]
    assert W.sched_shape_of(f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&Priority=1&From=MobileOTDrop") == \
        "/full/mobileschedule.cgi?BCID=001.{n}&Priority=1&From=MobileOTDrop"
    assert W.bid_period_n("2026-10") == 151 and W.bid_period_n("2027-01") == 154

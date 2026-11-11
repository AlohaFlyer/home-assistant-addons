"""1.6.2 (Ryan 2026-11-10, replacing the pilot's 120 s hunt floor): every instance hunts every 5 to 90 s and checks
every 1 to 90 min in normal mode. The number entities, the Watcher's clamp of freq/*/set and of a stored value, and
the check timing floors follow it on the admin and on a pilot; a stored 40 s survives a start; a pilot's Check now gap
is the admin's 10 s. Contract 1 revision 2 (1.7.0, Release C) brings the portal's normal to 1 to 90 min as well
(roles.FREQ_LIMITS; 1 to 20 before): a pilot whose portal is on advertises the same ranges. The safety limits stay: a pilot's 100 FLICA loads an hour holds a 5 s hunt, and
his state note says so plainly. FLICA is never reached: synthetic pages only ("Doe, Jane" 10001)."""
import json
import logging
import os
import types

import pytest

import gate as GT
import roles
from test_release_a_flica import FX, _lookup, mk, real_fl  # noqa: F401
from test_release_a_review import Stop, _run_main

ADMIN_AND_PILOT = {"normal_min": (1, 90), "hunt_s": (5, 90)}


def _nums(W):
    return {cfg["command_topic"].split("/")[-2]: (cfg["min"], cfg["max"]) for comp, _, cfg, _ in W.entity_defs()
            if comp == "number" and "/freq/" in (cfg.get("command_topic") or "")}


def _set(W, key, payload):
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/freq/{key}/set", payload=payload))
    return W.S["freq"][key]


# ------------------------------------------------------------------ the ranges
@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_admin_and_pilot_ranges(mk, instance):
    W = mk(instance)
    assert W.FREQ_LIMITS == ADMIN_AND_PILOT and roles.freq_limits(instance) == ADMIN_AND_PILOT
    assert _nums(W) == ADMIN_AND_PILOT  # the number entities (no portal on either)
    assert roles.FREQ_LIMITS == ADMIN_AND_PILOT  # contract 1 revision 2 (normal 1 to 20 before)
    assert W.check_now_gap() == 10
    assert W.PILOT_CHECK_FLOOR_S == (5 if instance else 0)  # a pilot's checks start at least his fastest hunt apart


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_the_clamp_at_5_and_90_s_and_1_and_90_min(mk, instance):
    W = mk(instance)
    for sent, got in ((b"1", 5), (b"4.4", 5), (b"5", 5), (b"40", 40), (b"90", 90), (b"91", 90), (b"300", 90)):
        assert _set(W, "hunt_s", sent) == got, sent
    for sent, got in ((b"0", 1), (b"1", 1), (b"20", 20), (b"45", 45), (b"90", 90), (b"91", 90), (b"600", 90)):
        assert _set(W, "normal_min", sent) == got, sent
    assert (f"{W.T}/freq/normal_min/state", "90") in W.MQ.msgs
    W.S["freq"] = {"hunt_s": 2, "normal_min": 200}  # stored values outside the ranges are clamped when read
    assert W.freq() == {"hunt_s": 5, "normal_min": 90}
    W.S["freq"] = {"hunt_s": 120, "normal_min": 30}  # a 120 s from a 1.6.2 test build reads as 90 s
    assert W.freq() == {"hunt_s": 90, "normal_min": 30}


def test_the_check_timing_floors_follow_the_ranges(mk, monkeypatch):
    """The floors are 5 s and 1 min (no 120 s); on a pilot his budget's pace (budget_pace_s) spreads a shorter hunt."""
    W = mk("pilot2")
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}
    pace = W.budget_pace_s()
    W.FLAGS["hunt"] = True
    g = [W.gap() for _ in range(2000)]
    assert pace <= min(g) and max(g) <= pace * 1.3 + 1e-6
    with monkeypatch.context() as m:  # the floor itself, under the pace
        m.setattr(W, "budget_pace_s", lambda: 0.0)
        g = [W.gap() for _ in range(2000)]
        assert 5 <= min(g) and max(g) <= 6.5 + 1e-6
        W.FLAGS["hunt"] = False
        assert 60 <= min(W.gap() for _ in range(2000))
    W.FLAGS["hunt"] = False
    W.S["freq"] = {"normal_min": 90}
    g = [W.gap() for _ in range(2000)]
    assert 63 * 60 - 1e-6 <= min(g) and max(g) <= 117 * 60 + 1e-6  # 90 min +-30 %, nothing holds it
    A = mk("")
    A.S["freq"] = {"hunt_s": 5, "normal_min": 90}
    A.FLAGS["hunt"] = True
    assert A.budget_pace_s() == 0 and min(A.gap() for _ in range(2000)) < 5  # the admin: 5 s +-30 %, as before
    A.FLAGS["hunt"] = False
    assert max(A.gap() for _ in range(2000)) > 90 * 60
    W.S["last_check_ts"] = W.S["check_started_ts"] = W.CLOCK.t - 4
    assert 0 < W.check_floor_wait() <= 1 + 1e-6  # 5 s after the last check, not 120
    W.S["last_check_ts"] = W.S["check_started_ts"] = W.CLOCK.t - 6
    assert W.check_floor_wait() == 0


def test_a_portal_pilots_entity_says_normal_up_to_90_min(portal_pilot):
    """Contract 1 revision 2 (1.7.0) sends normal 1 to 90 min: a pilot whose portal is on advertises 90, the same as his
    Watcher's own clamp (his portal offers only what it can send; it stopped at 20 before Release C)."""
    W, _ = portal_pilot("pilot2")
    assert W.portal_on()
    assert _nums(W) == {"normal_min": (1, 90), "hunt_s": (5, 90)} == roles.FREQ_LIMITS
    assert roles.entity_freq_limits("pilot2", portal=True) == roles.FREQ_LIMITS
    assert roles.entity_freq_limits("pilot2", portal=False) == ADMIN_AND_PILOT
    assert roles.entity_freq_limits("", portal=True) == ADMIN_AND_PILOT  # the admin has no portal
    W.S["freq"] = {}  # the fixture's options are minimal: freq() falls back to config.yaml's defaults
    assert W.freq() == {"normal_min": 6, "hunt_s": 40}
    assert _set(W, "normal_min", b"45") == 45 and _set(W, "hunt_s", b"5") == 5  # the Watcher takes 1 to 90
    W.discovery(W.MQ)
    disc = [json.loads(p) for t, p, *_ in W.MQ.raw.msgs if t.endswith("normal_minutes/config") and p]
    assert disc and disc[-1]["min"] == 1 and disc[-1]["max"] == 90


# ------------------------------------------------------------------ a start keeps a stored 40 s
def test_a_stored_40_s_hunt_survives_a_start(mk, monkeypatch, caplog):
    W = mk("pilot2")
    W.S["freq"] = {"hunt_s": 40, "normal_min": 6}  # James's stored 40 s
    W.S["switches"] = {"hunt": True, "pause": False}
    W.FLAGS["hunt"] = True
    gaps = []
    real_gap = W.gap
    monkeypatch.setattr(W, "gap", lambda: gaps.append(real_gap()) or gaps[-1])
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        _, checks = _run_main(W, monkeypatch, lambda i: None, check="ok", max_sleeps=12)
    assert W.S["freq"] == {"hunt_s": 40, "normal_min": 6} and W.freq()["hunt_s"] == 40
    assert W.DB.load_state()["freq"]["hunt_s"] == 40  # what the next start reads
    assert not [r for r in caplog.records if "check frequency moved" in r.getMessage()]
    # 40 s with 2 pot pages is more than 100 loads an hour: his budget spreads it (about 89 to 116 s), never 120 s
    pace = W.budget_pace_s()
    assert len(checks) >= 3 and gaps and all(pace - 1e-6 <= g <= pace * 1.3 + 1e-6 for g in gaps), gaps
    assert W.S["note"] == f"Hunting every 40 s is held to 100 FLICA loads an hour: checks wait for the budget, at " \
        f"least {int(-(-pace // 1))} s apart"
    A = mk("")
    A.S["freq"] = {"hunt_s": 40}
    A.FLAGS["hunt"] = True
    assert all(28 - 1e-6 <= A.gap() <= 52 + 1e-6 for _ in range(500))  # the admin: 40 s +-30 %


# ------------------------------------------------------------------ the budget holds a 5 s hunt
def _pilot_pages(W):
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
        if "mobileotrequest" in u.lower():  # 1.7.1 (LIVE-1): the request lists now get their share, so they are read
            return "<html><body>Open Time Requests: no requests</body></html>"
        return "<html><body>Pairing H9001 Check In: 08:00</body></html>"  # a page the pairing parser knows
    return ans


def test_the_budget_holds_a_5_s_hunt_to_100_loads_an_hour_spread_over_the_hour(mk, monkeypatch):
    """The real main loop, a pilot hunting every 5 s for 2 h: no rolling hour has more than his 100 FLICA loads, every
    check reads both pot pages, the checks are spread over the hour (no burst of 100 loads and then most of an hour
    blind), no load waits inside the gate beyond its pacing, and the state note says plainly that the hunt is held."""
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    W.S["freq"] = {"hunt_s": 5, "normal_min": 6}
    W.S["switches"] = {"hunt": True, "pause": False}
    W.FLAGS["hunt"] = True
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT,
                       "mobile_003.153": f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"}
    fl = real_fl(W, _pilot_pages(W))
    W.Flica.render = lambda self, url, wait_for=None, timeout=30000: (self.fetch(url), [])
    real_check = W.check
    waits, own = [], []  # every gated FLICA load (the login's two and each check's): its wait and its time
    real_acq = W.GATE.acquire

    def acq(**k):
        t = W.CLOCK.t
        real_acq(**k)
        waits.append(W.CLOCK.t - t)
        own.append(W.CLOCK.t)
    W.GATE.acquire = acq

    def run_check():
        n = len(fl.loads)
        res = real_check(fl)
        pots.append(len([u for _, u in fl.loads[n:] if "opentimepot" in u]))
        return res
    pots, notes, t0 = [], [], W.CLOCK.t

    def script(i):
        notes.append((W.S.get("machine"), W.S.get("note") or ""))
        if W.CLOCK.t - t0 > 2 * 3600:
            raise Stop("2 h")
    _run_main(W, monkeypatch, script, check=run_check, max_sleeps=5000)
    assert len(own) >= len(fl.loads)  # every load FLICA saw went through the gate
    worst = max(sum(1 for x in own if t - GT.WINDOW_S < x <= t) for t in own)
    assert len(own) > 150 and worst <= GT.PILOT_BUDGET_H, (len(own), worst)  # 2 h at under 100 an hour
    assert pots and all(p == 2 for p in pots), pots  # every check read both pot pages
    assert 2 * 30 <= len(pots) <= 2 * 42, len(pots)  # about 35 checks an hour, not 720
    pot_t = [t for t, u in fl.loads if "opentimepot" in u]
    assert max(b - a for a, b in zip(pot_t, pot_t[1:])) < 3 * 60  # spread: never most of an hour blind
    assert max(waits) <= GT.PACE_MAX_S + GT.HOST_GAP_S + 1e-6, max(waits)  # pacing only inside a check
    held = "Hunting every 5 s is held to 100 FLICA loads an hour: checks wait for the budget, at least 96 s apart"
    hunting = [n for m, n in notes[3:] if m == "hunting"]
    assert hunting and all(n.startswith(held) for n in hunting), hunting[:3]
    assert not [n for _, n in notes if "(next at" in n]  # the pace kept it: the budget never had to stop a check


def test_the_held_note_follows_the_hunt_and_the_budget(mk):
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "hunting", ""
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 10, "normal_min": 6}
    W.held_apply()
    held = "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget"
    assert W.S["note"] == held + ", at least 89 s apart"
    W.gate_note("budget", W.CLOCK.t + 300)  # a load waits for the budget: the next check's time
    assert W.S["note"].startswith(held + " (next at ") and W.S["note"].endswith(" HST)")
    W.gate_note("", None)  # the load went: back to the pace
    assert W.S["note"] == held + ", at least 89 s apart"
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/hunt/set", payload=b"OFF"))  # normal 6 min: free
    assert W.S["note"] == ""
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/freq/normal_min/set", payload=b"1"))
    assert W.S["note"] == ("Checking every 1 min is held to 100 FLICA loads an hour: checks wait for the budget, at "
                           "least 89 s apart")
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/freq/normal_min/set", payload=b"2"))
    assert W.S["note"] == ""
    W.gate_note("budget", W.CLOCK.t + 300)  # normal mode keeps the budget's own words
    assert W.S["note"].startswith("FLICA budget: 100 page loads in the last hour; the next one waits until ")
    A = mk("")
    A.S["machine"], A.S["note"] = "hunting", ""
    A.FLAGS["hunt"] = True
    A.S["freq"] = {"hunt_s": 5}
    A.held_apply()
    assert A.S["note"] == "" and A.held_note() == ""  # the admin has no budget: his 5 s is 5 s
    A.gate_note("host", A.CLOCK.t + 300)  # only the host cap can hold him
    assert A.S["note"].startswith("FLICA host limit: 480 page loads in the last hour")


# ------------------------------------------------------------------ 1.6.2 review: the close-in folder in the pace
CLOSE_IN = "007.153"  # a made-up close-in BCID


def test_the_close_in_folder_is_an_hourly_cost_of_a_hunt_and_a_page_of_each_normal_check(mk):
    """Hunting, the close-in folder is read at most every CLOSE_IN_READ_S (about 12 loads an hour), so the pace charges
    it by the hour, not on every check: 105 s with 2 pot pages, under the 120 s floor Ryan removed. In normal mode
    every check reads it, so it is a page of each check. The optional reads keep their hour at the pace (opt_cap)
    either way: the pot details of a new find are optional reads, so that share is not dropped. 1.7.1 (LIVE-1): with
    two bid months the secondary reads' shares (opt_shares) need 18 loads an hour, not 12, so the pace is 96 s (89 s
    before) and 115 s with the folder (105 s before), still under the removed 120 s floor."""
    W = mk("pilot2")
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT,
                       "mobile_003.153": f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"}
    W.FLAGS["hunt"] = True
    assert W.close_in_h() == 0 and W.pot_pages() == 2
    assert W.opt_hour() == 18
    assert W.budget_pace_s() == pytest.approx(2 * 3600 / 75)  # 96 s, about one check every 1.6 min
    assert W.opt_cap() == W.opt_hour()
    W.S["close_in"] = {"bcid": CLOSE_IN, "verified": True}
    assert W.close_in_h() == pytest.approx(3600 / W.CLOSE_IN_READ_S) == pytest.approx(12)
    assert W.pot_pages() == 2  # hunting: the folder is no page of every check
    pace = W.budget_pace_s()
    assert pace == pytest.approx(2 * 3600 / 63) and 100 < pace < 120  # about 114 s (it was 133 s in 1.6.2)
    assert all(pace - 1e-6 <= W.gap() <= pace * 1.3 + 1e-6 for _ in range(500))  # every hunt from 5 to 90 s
    W.S["freq"]["hunt_s"] = 90
    assert all(pace - 1e-6 <= W.gap() <= pace * 1.3 + 1e-6 for _ in range(500))
    assert W.opt_cap() == W.opt_hour()  # the pot (63 an hour), the folder (12), the schedule (4), a check's start (3)
    assert W.held_note() == ("Hunting every 90 s is held to 100 FLICA loads an hour: checks wait for the budget, at "
                             "least 115 s apart")
    W.FLAGS["hunt"] = False  # normal mode: every check reads the folder
    assert W.close_in_h() == 0 and W.pot_pages() == 3
    assert W.budget_pace_s() == pytest.approx(3 * 3600 / 75)
    assert W.held_note() == ("Checking every 1 min is held to 100 FLICA loads an hour: checks wait for the budget, at "
                             "least 144 s apart")
    assert W.opt_cap() == W.opt_hour()
    W.S["freq"]["normal_min"] = 6
    assert W.held_note() == "" and W.opt_cap() == 100 - 30 - 4 - 3  # 3 pages every 6 min: free
    A = mk("")
    A.S["close_in"] = {"bcid": CLOSE_IN, "verified": True}
    A.FLAGS["hunt"] = True
    assert A.budget_pace_s() == 0 and A.opt_cap() is None  # the admin has no budget


def test_a_5_s_hunt_with_the_close_in_folder_paces_under_120_s_and_holds_the_budget(mk, monkeypatch):
    """The real main loop and check(), a pilot whose close-in folder is known hunting every 5 s for 2 h: checks come
    faster than the removed 120 s floor allowed (about 26 an hour; 23 before 1.6.2's fix), every check reads both pot
    pages, the folder at most every CLOSE_IN_READ_S, no rolling hour passes his 100 FLICA loads and the state note says
    the hunt is held at 117 s (1.7.1, LIVE-1: 105 s before the secondary reads, the folder's request list among them,
    got their shares)."""
    W = mk("pilot2")
    W.S["own_emp"] = "10001"
    W.S["freq"] = {"hunt_s": 5, "normal_min": 6}
    W.S["switches"] = {"hunt": True, "pause": False}
    W.FLAGS["hunt"] = True
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT,
                       "mobile_003.153": f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"}
    W.S["close_in"] = {"bcid": CLOSE_IN, "verified": True, "menu_at": W.CLOCK.t}
    W.S["close_in_bcid"] = CLOSE_IN  # as close_in_check keeps it: its request list is read too
    fl = real_fl(W, _pilot_pages(W))
    W.Flica.render = lambda self, url, wait_for=None, timeout=30000: (self.fetch(url), [])
    real_check = W.check
    own, waits = [], []
    real_acq = W.GATE.acquire

    def acq(**k):
        t = W.CLOCK.t
        real_acq(**k)
        waits.append(W.CLOCK.t - t)
        own.append(W.CLOCK.t)
    W.GATE.acquire = acq
    pots, notes, t0 = [], [], W.CLOCK.t

    def run_check():
        n = len(fl.loads)
        res = real_check(fl)
        pots.append(len([u for _, u in fl.loads[n:] if "opentimepot" in u and CLOSE_IN not in u]))
        return res

    def script(i):
        notes.append((W.S.get("machine"), W.S.get("note") or ""))
        if W.CLOCK.t - t0 > 2 * 3600:
            raise Stop("2 h")
    _run_main(W, monkeypatch, script, check=run_check, max_sleeps=5000)
    assert W.S["close_in"].get("bcid") == CLOSE_IN  # the folder stayed known (its page read as open time)
    worst = max(sum(1 for x in own if t - GT.WINDOW_S < x <= t) for t in own)
    assert worst <= GT.PILOT_BUDGET_H, worst
    assert pots and all(p == 2 for p in pots), pots  # every check read both pot pages
    assert 2 * 26 <= len(pots) <= 2 * 33, len(pots)  # about 26 checks an hour (the 120 s floor gave at most 26)
    # the folder's open time page (1.7.1: its request list is read too now, within the requests' share)
    ci = [t for t, u in fl.loads if CLOSE_IN in u and "opentimepot" in u]
    assert ci and min(b - a for a, b in zip(ci, ci[1:])) >= W.CLOSE_IN_READ_S - 1e-6  # at most every 5 min
    assert max(sum(1 for x in ci if t - GT.WINDOW_S < x <= t) for t in ci) <= 12
    pot_t = [t for t, u in fl.loads if "opentimepot" in u and CLOSE_IN not in u]
    # spread over the hour: at most the pace +30 % and one check that also read the Tradeboard, the grid and the
    # request lists of three folders (1.7.1, LIVE-1: those now run within their shares, about 40 s of paced loads)
    assert max(b - a for a, b in zip(pot_t, pot_t[1:])) < 4 * 60
    assert max(waits) <= GT.PACE_MAX_S + GT.HOST_GAP_S + 1e-6, max(waits)  # pacing only inside a check
    held = "Hunting every 5 s is held to 100 FLICA loads an hour: checks wait for the budget, at least 117 s apart"
    hunting = [n for m, n in notes[3:] if m == "hunting"]
    assert hunting and all(n.startswith(held) for n in hunting), hunting[:3]
    assert not [n for _, n in notes if "(next at" in n]  # the pace kept it: the budget never had to stop a check

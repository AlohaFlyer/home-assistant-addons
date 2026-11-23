"""1.7.26 (Nov 22, 2026, Ryan: "the crew index would only read while the hour still leaves room for your pot checks,
and the Data age popup would show why reads are held and get its own Check now button", plus no new FLICA loads).

Live that day the FLICA host gate (480 page loads a rolling hour for every Watcher in the container) filled: the 12:00
HST crew index run read 300 pairing pages while the admin hunted every 10 s and the pilot's Watcher used its 100, so
every load waited until 13:21 HST and Check now was ignored. Now:
- D1: every crew index load on the admin goes to the gate with keep=host_keep() (the loads the coming hour needs for
  his pot checks, each pilot's budget and his schedule reads): one the hour cannot spare is left out (GateSkip), never
  waited for; the chunk stops quietly (not read, not failed, no breaker) and the run goes on at a later check.
- D2: the admin's checks are held to his share of the host's hour (host_pace_s), with the pilot's held note words.
- D3: the data age stamp's box says why reads are held and has its own Check now.
FLICA is never reached: synthetic pages and made-up names only ("Doe, Jane")."""
import json
import logging
import math
import re
import types

import pytest

import gate as GT
from test_crew_index import FakeFl, W, _file, _row  # noqa: F401  (W is the crew index's watcher fixture)
from test_crew_variants import _setup9646
from test_fw171_cards import _browser, _card, _page as _portal_page, _pilot, _s
from test_fw1712_data_age import OLD, _clock, _sched
from test_release_a_flica import mk, real_fl  # noqa: F401
from test_release_a_cards import _run, _src
from test_release_a_review import Stop, _run_main

HOST_NOTE = ("FLICA host limit: 480 page loads in the last hour from this host (every pilot's Watcher); the next one "
             "waits until 13:21 HST")
HOST_LINE = ("Reads held: FLICA host limit, 480 page loads in the last hour from this host (every pilot's Watcher); "
             "the next read at 13:21 HST.")
HOST_WHY = "The FLICA host limit holds the next check until 13:21 HST: a press now would be ignored."


def _admin(mk, hunt=True, hs=10, nm=6, close_in=False, pilots=("pilot2",)):
    """The admin's Watcher as on Nov 22: one pot page (the mobile one), the pilots option, hunt or normal."""
    A = mk("")
    A.OPTS["pilots"] = [{"name": n} for n in pilots]
    A.S["pot_urls"] = {"mobile": A.MOBILE_POT}
    A.S["freq"] = {"hunt_s": hs, "normal_min": nm}
    A.FLAGS["hunt"] = hunt
    if close_in:
        A.S["close_in"] = {"bcid": "007.153", "verified": True}
    return A


# ---------------------------------------------------------------- D2: the admin's pace, by hand
def test_host_pace_and_host_keep_by_hand(mk):
    """Ryan's setting Nov 22 (hunt 10 s, 1 pot page, one pilot's Watcher):
    host_share_h = 480 - 100 = 380; room = 380 - 4 x 2 (schedule) - 3 (a check's start) - 40 (his other reads) = 329;
    host_pace_s = 1 x 3600 / 329 = 10.94 s, so his 10 s (and a 5 s) hunt is held to at least 11 s apart.
    host_keep = 3600 / 10.94 (= 329 pot loads) + 3 + 100 + 8 = 440, 452 once the close-in folder is known (+ 12 an
    hour hunting): the crew index reads only while the host's last hour holds fewer than 40 (28) loads.
    Normal 6 min with the close-in folder (2 pages a check): host_pace_s = 7200 / 329 = 21.9 s (nothing held),
    host_keep = 2 x 10 + 3 + 100 + 8 = 131: the crew index reads while the last hour holds fewer than 349."""
    A = _admin(mk)
    assert (A.pilots_running(), A.host_share_h(), A.pot_pages(), A.ADMIN_OPT_RESERVE_H) == (1, 380, 1, 40)
    assert A.host_pace_s() == pytest.approx(3600 / 329) == pytest.approx(10.942, abs=1e-3)
    assert A.budget_pace_s() == 0 and A.pace_s() == A.host_pace_s() and A.check_every_s() == A.host_pace_s()
    assert A.host_keep() == 329 + 3 + 100 + 8 == 440
    A.S["freq"]["hunt_s"] = 5
    assert A.host_pace_s() == pytest.approx(3600 / 329) and A.host_keep() == 440
    A.S["close_in"] = {"bcid": "007.153", "verified": True}
    assert A.close_in_h() == 12 and A.pot_pages() == 1 and A.host_keep() == 452
    A.FLAGS["hunt"] = False  # normal 6 min: the folder is a page of each check
    assert A.pot_pages() == 2 and A.host_pace_s() == pytest.approx(7200 / 329) and A.check_every_s() == 360
    assert A.host_keep() == 2 * 10 + 3 + 100 + 8 == 131 and A.held_note() == ""
    A.FLAGS["hunt"] = True
    A.S["freq"]["hunt_s"] = 30  # a hunt slower than the pace: 120 pot loads, nothing held
    assert A.check_every_s() == 30 and A.host_keep() == 120 + 12 + 3 + 100 + 8 and A.held_note() == ""
    A.OPTS["pilots"] = [{"name": "pilot2"}, {"name": "jane_doe"}, {"name": "bad__name"}]  # run.py leaves one out
    assert A.pilots_running() == 2 and A.host_share_h() == 280
    A.OPTS["pilots"] = []
    assert A.pilots_running() == 0 and A.host_pace_s() == pytest.approx(3600 / 429)  # 480 - 51
    A.OPTS["second_pilot"] = "pilot2"  # the older option, read while pilots is empty
    assert A.pilots_running() == 1
    P = mk("pilot2")  # a pilot keeps his own budget's pace; no host pace, no keep
    P.FLAGS["hunt"] = True
    assert P.host_pace_s() == 0 and P.host_keep() == 0 and P.pace_s() == P.budget_pace_s() > 0


def test_a_10_s_and_a_5_s_hunt_are_held_with_the_pilots_words(mk):
    """D2: the admin's state note says his hunt is held, in the held note's words (FW_AGE_PACE and the clock card's
    FC_HELD read it), and every wait is at least the pace."""
    for hs in (10, 5):
        A = _admin(mk, hs=hs)
        A.S["machine"], A.S["note"] = "hunting", ""
        A.held_apply()
        want = (f"Hunting every {hs} s is held to 380 FLICA loads an hour: checks wait for the budget, at least 11 s "
                "apart")
        assert A.S["note"] == A.held_note() == want
        assert re.search(r" is held to \d+ FLICA loads an hour: checks wait for the budget, at least (\d+) s apart",
                         want).group(1) == "11"  # the data age block's FW_AGE_PACE
        g = [A.gap() for _ in range(3000)]
        assert A.host_pace_s() - 1e-6 <= min(g) and max(g) <= A.host_pace_s() * 1.3 + 1e-6
        A.on_message(A.MQ, None, types.SimpleNamespace(topic=f"{A.T}/hunt/set", payload=b"OFF"))  # normal: free
        assert A.S["note"] == ""
    A.gate_note("host", A.CLOCK.t + 300)  # a wait for the host limit keeps its own words
    assert A.S["note"].startswith("FLICA host limit: 480 page loads in the last hour")


def test_the_admins_held_hunt_keeps_his_pot_inside_his_share_of_the_hour(mk, monkeypatch):
    """The real main loop, the admin hunting every 5 s for 2 h with one pot page and one pilot: his checks are never
    closer than the pace, and no rolling hour holds more than his share less his reserved reads (329 pot loads)."""
    A = _admin(mk, hs=5)
    A.S["switches"] = {"hunt": True, "pause": False}
    monkeypatch.setattr(A, "crewtrac_thread", lambda: None)  # its own thread would move the test's clock
    A.S["discovered_at"] = A.CLOCK.t  # one pot page found just now (no rediscovery for the next month in these 2 h)
    loads, t0 = [], A.CLOCK.t

    def check():
        A.GATE.acquire()  # the pot page
        loads.append(A.CLOCK.t)
        return "ok"

    def script(i):
        if A.CLOCK.t - t0 > 2 * 3600:
            raise Stop("2 h")
    _, checks = _run_main(A, monkeypatch, script, check=check, max_sleeps=5000)
    assert len(checks) > 400
    gaps = [b - a for a, b in zip(checks[3:], checks[4:])]
    assert min(gaps) >= A.host_pace_s() - 1e-6, min(gaps)
    worst = max(sum(1 for x in loads if t - GT.WINDOW_S < x <= t) for t in loads)
    assert worst <= 329, worst  # 720 an hour at 5 s before 1.7.26
    assert A.S["note"].startswith("Hunting every 5 s is held to 380 FLICA loads an hour")


# ---------------------------------------------------------------- D1: the crew index yields to the pot checks
PAGE = ("<html><body>flica.net - mobile pairing pairing details {pid} check in: 07:30 blk : 1000 tafb : 3030 "
        "pay : 1200 crew: ca {ca} doe, jane fo {fo} roe, rick ro open</body></html>")


def _page(u):
    """A pairing page the parsers know, one CA and one FO a pairing (no pilot on two overlapping trips, FW-0059)."""
    pid = u.split("PID=")[1].split("&")[0]
    return PAGE.format(pid=pid.lower(), ca=10000 + int(pid[1:5]) % 1000, fo=11000 + int(pid[1:5]) % 1000)


def _fill(A, n, who="pilot2"):
    """n loads of the host's last hour in the gate's file, spread over the 50 min before now, from another Watcher."""
    now = A.CLOCK.t
    log = [[now - 3000 + i * (2900 / max(1, n)), who] for i in range(n)]
    with open(A.GATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "last": log[-1][0] if log else 0, "log": log}, f)


def test_a_crew_index_chunk_stops_on_gate_skip_and_resumes_later(mk, monkeypatch, tmp_path, caplog):
    """Normal 6 min (host_keep 121: 10 pot loads, 3, the pilot's 100, 8): with 355 loads in the host's hour, 4 pages fit
    (359 = 480 - 121), the fifth is left out by the gate (GateSkip): the chunk stops there, nothing is failed, no
    breaker counts it, the run keeps its place and says so once. The next check loads nothing (no room), and once the
    hour has room the run goes on, 50 pages a chunk, to its end."""
    A = _admin(mk, hunt=False)
    monkeypatch.setattr(A, "CREW_DIR", str(tmp_path / "crew_index"))
    _file(tmp_path / "www", "2026-11", [_row(f"H{9000 + i}", " ".join(str(d) for d in range(1, 31)), rel=0)
                                        for i in range(4)])
    fl = real_fl(A, _page)
    assert A.host_keep() == 121
    _fill(A, 355)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert A.crew_index_check(fl) == "ok"
        assert len(fl.loads) == 4 and A.S["crew_run"]["pages"] == 4 and A.RUN["host_keep"] == 0
        rows = A.DB.crew_rows()
        assert len(rows) == 4 and {r["status"] for r in rows.values()} == {"ok"}  # nothing failed
        assert A.BRK.allow("pairing") and not A.S.get("breakers", {}).get("pairing", {}).get("fails")
        assert A.crew_index_check(fl) == "ok" and len(fl.loads) == 4  # no room: nothing loaded, not even waited for
    held = [r.getMessage() for r in caplog.records if "crew index: paused" in r.getMessage()]
    assert held == ["crew index: paused, the FLICA host hour is kept for the pot checks (359 of 480 used)"]
    assert not [r for r in caplog.records if "left out of this check" in r.getMessage()]
    A.CLOCK.t += 3600  # the hour moved on: the run goes on where it stopped
    assert A.crew_index_check(fl) == "ok"
    assert len(fl.loads) == 54 and A.S["crew_run"]["pages"] == 54
    for _ in range(3):
        A.crew_index_check(fl)
    assert "crew_run" not in A.S and A.S["crew_last"]["pages"] == 120 and len(fl.loads) == 120  # all 4 x 30 read
    assert len({u for _, u in fl.loads}) == 120  # none read twice


def test_a_hunt_held_at_the_pace_leaves_the_crew_index_no_room(mk, monkeypatch, tmp_path):
    """Hunting at the held pace the keep is 440: with the hour holding the admin's own pot loads the crew index loads
    nothing at all, so it can no longer fill the hour in front of his checks."""
    A = _admin(mk)
    monkeypatch.setattr(A, "CREW_DIR", str(tmp_path / "crew_index"))
    _file(tmp_path / "www", "2026-11", [_row("H9001", "1 2 3 4 5", rel=0)])
    fl = real_fl(A, _page)
    _fill(A, 200, who="admin")  # a quarter of an hour's held hunt would be more
    assert A.crew_index_check(fl) == "ok" and fl.loads == [] and A.S["crew_run"]["pages"] == 0


def test_a_pilots_gate_skip_in_the_crew_index_keeps_its_old_rule(W, tmp_path):  # noqa: F811
    """With no host keep (a pilot's Watcher, whose budget left the load out) the GateSkip goes up to read_guard as
    before 1.7.26: the page is not counted and the check says it left the read out."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "1 2 3", rel=0)])

    class SkipFl(FakeFl):
        def fetch(self, url):
            raise GT.GateSkip("budget", 0)
    W.RUN["host_keep"] = 0
    with pytest.raises(GT.GateSkip):
        W.crew_index_chunk(SkipFl())
    assert W.S["crew_run"]["pages"] == 0


def test_a_variant_probe_left_out_for_the_host_hour_keeps_its_letters(W, tmp_path, monkeypatch, caplog):  # noqa: F811
    """FW-0068's probe through the same keep: H9646A read (a miss), H9646B left out by the gate. No try is counted,
    A stays answered, the pause is said once, and the next run reads on from B."""
    insts = _setup9646(W, tmp_path)
    rows = W.DB.crew_rows()
    pages = {("H9646B", "20261106"): GT.GateSkip("host", 0)}

    class Fl:
        urls = []

        def fetch(self, url):
            pid, d = url.split("PID=")[1].split("&")[0], url.split("DATE=")[1][:8]
            self.urls.append(pid)
            v = pages.get((pid, d))
            if isinstance(v, Exception):
                raise v
            return f"<html><p>flica.net - mobile pairing pairing details {pid.lower()}:06nov</p></html>"
    fl = Fl()
    monkeypatch.setitem(W.RUN, "host_keep", 440)
    W.S["crew_run"] = {"started": "2026-11-10T12:00:00", "pages": 0, "why": "slot", "slot": "2026-11-10T12"}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", True)
        assert W.DB.get(W.CREW_VARIANT_TRIES_KEY) == {"H9646|2026-11-06": {"n": 0, "at": "2026-11-10T12:05:00",
                                                                           "done": "A", "fail": ""}}
        assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", True)  # still no room: B again, nothing read
    assert sum("crew index: paused" in r.getMessage() for r in caplog.records) == 1
    assert not [r for r in caplog.records if "variant probe stopped" in r.getMessage()]
    pages.clear()
    assert W.crew_variants(fl, insts, rows, 50) == (3, "ok", False)
    assert fl.urls == ["H9646A", "H9646B", "H9646B", "H9646B", "H9646C", "H9646D"]  # A never read again
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"]["found"] == ""


# ---------------------------------------------------------------- D3: the hold line, from the Watcher's own notes
HELD_JS = """(notes) => notes.map((n) => { const h = fwAgeHeld(n); return [h.line, h.hold]; })"""


def test_the_hold_line_reads_every_note_the_watcher_writes(mk):
    """The notes come from the Watcher itself (gate_note, held_note, the breakers), so the card's patterns follow it."""
    A = _admin(mk)
    t = A.CLOCK.t + 1800
    A.gate_note("host", t)
    host = A.HEALTH["gate"]
    P = mk("pilot2")
    P.FLAGS["hunt"] = True
    P.S["freq"] = {"hunt_s": 10, "normal_min": 6}
    P.gate_note("budget", t)
    held_next = P.HEALTH["gate"]
    P.FLAGS["hunt"] = False
    P.gate_note("budget", t)
    budget = P.HEALTH["gate"]
    A.gate_note("", None)
    A.S["machine"], A.S["note"] = "hunting", ""
    A.held_apply()
    held = A.S["note"]
    A.BRK.fail("pairing", "a CAPTCHA page (never answered)", "captcha")
    brk = A.BRK.note()
    hm = A.hst_hm(t)
    cases = [host, held_next, budget, held, brk, f"{host}; {brk}", "", "logged in", "starting"]
    got = _run([("a", f"({HELD_JS})({json.dumps(cases)})")], _src("clock-card"))["a"]
    assert got[0] == [f"Reads held: FLICA host limit, 480 page loads in the last hour from this host (every pilot's "
                      f"Watcher); the next read at {hm} HST.",
                      f"The FLICA host limit holds the next check until {hm} HST: a press now would be ignored."]
    assert got[1] == [f"Reads held: {held_next}.",
                      f"The FLICA budget holds the next check until {hm} HST: a press now would be ignored."]
    assert got[2] == [f"Reads held: FLICA budget, 100 page loads in the last hour; the next read at {hm} HST.",
                      f"The FLICA budget holds the next check until {hm} HST: a press now would be ignored."]
    assert got[3] == [f"Reads held: {held}.", ""]  # a pace names no time: a press is read
    assert got[4] == [f"Reads held: {brk}.", ""] and "FLICA pairing read paused until " in brk
    assert got[5][0] == got[0][0][:-1] + f"; {brk}." and got[5][1] == got[0][1]
    assert got[6:] == [["", ""]] * 3


# ---------------------------------------------------------------- D3: the box in Chromium
BOX_JS = """async ([tag, cfg, st, press]) => {
  const c = mount(tag, cfg, st), r = c.shadowRoot;
  await new Promise((ok) => setTimeout(ok, 300));  // the schedule card redraws once its files answer 404
  r.querySelector('.ag[data-age]').click();
  await new Promise((ok) => setTimeout(ok, 60));
  const box = r.querySelector('#agi') || r.querySelector('.info');
  const b = box.querySelector('.fwa-b'), row = box.querySelector('.fwa-c'), why = box.querySelector('.fwa-r');
  const h = box.querySelector('.fwa-h'), vis = (x) => !!x && x.checkVisibility();
  const look = () => ({open: getComputedStyle(box).display !== 'none', line: vis(h) ? h.textContent : '',
    shown: vis(b), label: b ? b.textContent : null, off: b ? b.getAttribute('aria-disabled') === 'true' : null,
    dis: b ? b.disabled : null, why: vis(why) ? why.textContent : '',
    tag: b ? b.tagName : null, type: b ? b.type : null, hgt: b ? Math.round(b.getBoundingClientRect().height) : 0});
  const before = look(), con = fwContrast(c), fit = fwFits(c), br = box.getBoundingClientRect();
  fit.box = [Math.round(br.left), Math.round(br.right)];
  if (press && b && b.checkVisibility()) b.click();
  await new Promise((ok) => setTimeout(ok, 60));
  return {before, after: look(), calls: window.calls.filter((x) => x[0] === 'button'), con, fit,
    text: box.textContent}; }"""


def _states(card, pilot, st="idle", note="", pause="off", last="2026-11-10T11:27:00+00:00"):
    if card == "clock":
        s = _clock(st=st, note=note, pilot=False, last=last)
    else:
        s = _sched(pilot=False, last=last)
        s["sensor.flight_watcher_state"] = _s(st, {"note": note, "role": "admin"})
        s["sensor.flight_watcher_next_check"] = _s("2026-11-10T11:33:00+00:00")
    s["switch.flight_watcher_pause"] = _s(pause, lu=OLD)
    return _pilot(s) if pilot else s


CASES = {  # name: (state, note, pause, press)
    "ready": ("idle", "", "off", True),
    "held pace": ("hunting", "Hunting every 10 s is held to 380 FLICA loads an hour: checks wait for the budget, at "
                  "least 11 s apart", "off", True),
    "gate": ("hunting", HOST_NOTE, "off", True),
    "paused": ("paused", "", "on", True),
    "stopped": ("stopped_unexpected", "3 check errors in a row", "off", True),
}


@pytest.mark.parametrize("width,scheme", [(390, "light"), (320, "dark")])
def test_the_box_says_why_and_has_its_own_check_now(width, scheme):
    with _browser() as b:
        for card in ("clock", "schedule"):
            for pilot in (True, False):
                for cfg in (({},) if card == "schedule" else ({}, {"mode": "age"})):
                    for name, (st, note, pause, press) in CASES.items():
                        pg = _portal_page(b, [_card(f"{card}-card", pilot=pilot)], width=width, scheme=scheme)
                        tag = f"flight-watcher-{card}-card" + ("-pilot2" if pilot else "")
                        g = pg.evaluate(BOX_JS, [tag, cfg, _states(card, pilot, st, note, pause), press])
                        pg.context.close()
                        where = (card, pilot, cfg, name, scheme)
                        eid = "button.flight_watcher" + ("_pilot2" if pilot else "") + "_check_now"
                        a, z = g["before"], g["after"]
                        assert a["open"] and z["open"], where  # a tap on the button keeps the box open
                        assert g["text"].startswith("Last good read 01:27:00 HST.") or card == "schedule", where
                        assert "Last good read 01:27:00 HST." in g["text"], where
                        mine = [f for f in g["con"]["fails"] if re.match(r"(div|span|button)\.(fwa-|info|ag)",
                                                                         f["cls"])]
                        assert not mine, (where, json.dumps(mine, indent=1))  # the box and the stamp, both themes
                        if card == "clock":  # the clock card as a whole too, as the 1.7.12 tap test checks it
                            assert not g["con"]["fails"], (where, json.dumps(g["con"]["fails"], indent=1))
                        assert 0 <= g["fit"]["box"][0] and g["fit"]["box"][1] <= width, (where, g["fit"])
                        # the schedule card's grid is wider than 320 px with no box open, as on main: the page check is
                        # the clock card's (and the schedule card's at 390, as the 1.7.12 tests have it)
                        if card == "clock" or width >= 390:
                            assert g["fit"]["page"] <= width, (where, g["fit"])
                        if name in ("paused", "stopped"):  # hidden where the clock card hides its Check now
                            assert not a["shown"] and g["calls"] == [], where
                            continue
                        assert a["shown"] and a["tag"] == "BUTTON" and a["type"] == "button" and not a["dis"], where
                        assert a["hgt"] >= 44, (where, a["hgt"])  # a phone's touch target
                        if name == "gate":
                            assert a["line"] == HOST_LINE and a["off"] and a["why"] == HOST_WHY, (where, a)
                            assert g["calls"] == [] and z["label"] == "Check now", where  # the Watcher would ignore it
                            continue
                        assert not a["off"] and a["label"] == "Check now" and a["why"] == "", (where, a)
                        assert a["line"] == ("" if name == "ready" else "Reads held: " + note + "."), (where, a)
                        assert g["calls"] == [["button", "press", {"entity_id": eid}]], (where, g["calls"])
                        assert z["label"] == "Check now sent" and z["off"], (where, z)


SENT_JS = """(() => { const r = C.shadowRoot, b = r.querySelector('.fwa-b');
  return b ? [b.textContent, b.getAttribute('aria-disabled') === 'true', r.activeElement === b] : null; })()"""


def test_check_now_sent_lasts_until_the_next_good_read_or_60_s():
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card")], clock=True)
        st = _states("clock", True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card-pilot2', {}, st); "
                    "C.shadowRoot.getElementById('age').click(); C.shadowRoot.querySelector('.fwa-b').click(); }", st)
        assert pg.evaluate(SENT_JS)[:2] == ["Check now sent", True]
        pg.clock.run_for(30_000)
        assert pg.evaluate(SENT_JS)[:2] == ["Check now sent", True]
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _states("clock", True, last="2026-11-10T11:30:20+00:00"))
        assert pg.evaluate(SENT_JS)[:2] == ["Check now", False]  # the next good read
        pg.evaluate("() => C.shadowRoot.querySelector('.fwa-b').click()")
        assert pg.evaluate(SENT_JS)[:2] == ["Check now sent", True]
        pg.clock.run_for(61_000)
        assert pg.evaluate(SENT_JS)[:2] == ["Check now", False]  # or 60 s
        assert len(pg.evaluate("window.calls")) == 2
        # the portal's command in flight reads "Sending..." and takes no tap
        pg.evaluate("([st, id]) => { C.hass = mkHass(st, {fwPending: {[id]: {label: 'Check now'}}}); }",
                    [st, "button.flight_watcher_pilot2_check_now"])
        assert pg.evaluate(SENT_JS)[:2] == ["Sending...", True]


KEY_JS = """async () => { const r = C.shadowRoot, el = r.getElementById('age');
  const b = () => r.querySelector('.fwa-b'), box = r.getElementById('agi');
  return {focus: r.activeElement === b(), ring: b() ? getComputedStyle(b()).outlineStyle + ' '
    + getComputedStyle(b()).outlineWidth : '', open: getComputedStyle(box).display !== 'none',
    stamp: r.activeElement === el}; }"""


def test_the_button_is_reached_and_used_from_the_keyboard():
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _portal_page(b, [_card("clock-card", pilot=False)], width=390, scheme=scheme)
            pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card', {mode: 'age'}, st); "
                        "C.shadowRoot.getElementById('age').focus(); }", _states("clock", False))
            pg.keyboard.press("Enter")  # opens the box
            pg.keyboard.press("Tab")  # the stamp, then the box's button
            g = pg.evaluate(KEY_JS)
            assert g["focus"] and g["open"] and g["ring"] == "solid 2px", (scheme, g)  # a visible focus ring
            pg.keyboard.press("Enter")
            press = ["button", "press", {"entity_id": "button.flight_watcher_check_now"}]
            assert pg.evaluate("window.calls") == [press]
            g = pg.evaluate(KEY_JS)
            assert g["focus"] and g["open"], g  # the press keeps the box open and the focus on the button
            assert pg.evaluate(SENT_JS) == ["Check now sent", True, True]
            pg.keyboard.press("Enter")  # "sent": a second press does nothing
            assert len(pg.evaluate("window.calls")) == 1
            pg.keyboard.press("Escape")
            g = pg.evaluate(KEY_JS)
            assert not g["open"] and g["stamp"], g  # Esc closes it and gives the stamp the focus back
            pg.context.close()


def test_a_tap_on_the_box_text_still_closes_it_and_the_schedule_stamp_opens_by_keyboard():
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card")], width=390)
        g = pg.evaluate("""(st) => { const c = mount('flight-watcher-clock-card-pilot2', {}, st), r = c.shadowRoot;
          r.getElementById('age').click(); const box = r.getElementById('agi');
          box.querySelector('.fwa-r').click(); const kept = getComputedStyle(box).display;
          box.querySelector('.fwa-t').click();
          return [kept, getComputedStyle(box).display, box.querySelectorAll('button').length,
            window.calls.length]; }""",
                        _states("clock", True, st="hunting", note=HOST_NOTE))
        assert g == ["block", "none", 0, 0]  # the row keeps it open; its text closes it, and nothing is left in it
        pg.context.close()
        pg = _portal_page(b, [_card("schedule-card")], width=390)
        g = pg.evaluate("""async (st) => { const c = mount('flight-watcher-schedule-card-pilot2', {}, st);
          await new Promise((ok) => setTimeout(ok, 300)); const r = c.shadowRoot, el = r.querySelector('.hd2 .ag');
          el.focus(); el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          const box = r.querySelector('.fwm .info'), b = box.querySelector('.fwa-b');
          return [el.getAttribute('role'), el.tabIndex, getComputedStyle(box).display, b ? b.textContent : null,
            box.querySelector('.fwa-h').textContent]; }""",
                        _states("schedule", True, st="hunting", note=HOST_NOTE))
        assert g == ["button", 0, "block", "Check now", HOST_LINE]
        pg.context.close()


def test_the_box_code_is_in_the_shared_block_and_names_no_entity():
    from test_fw1712_data_age import HOLDERS, block
    import cards
    srcs = cards.sources()
    ref = block(srcs[HOLDERS[0]])
    for f in ("function fwAgeHeld(", "function fwAgeChk(", "function fwAgeBox(", "function fwAgePress(",
              "FW_AGE_BOX_CSS", "FW_AGE_SENT_MS = 60000"):
        assert f in ref, f
    assert "check_now" not in ref and "button." not in ref  # each card passes its own ids (FW_AGE_IDS chk)
    for name in HOLDERS:
        assert 'chk: "button.flight_watcher_check_now", pause: "switch.flight_watcher_pause"' in srcs[name], name
        built = cards.build("9.9.9", ["pilot2"])[f"{name}-pilot2.js"]
        assert 'chk: "button.flight_watcher_pilot2_check_now"' in built, name
        assert "${FW_AGE_BOX_CSS}" in srcs[name], name


def test_no_new_flica_load_and_the_budgets_stand():
    """No new FLICA URL or page load: the gate's caps and the pilot's budget are what they were (Ryan's yes needed)."""
    import roles
    assert (GT.HOST_CAP_H, GT.PILOT_BUDGET_H, GT.PACE_MIN_S, GT.PACE_MAX_S) == (480, 100, 1.5, 3.5)
    assert "check_now/press" in roles.PORTAL_CMDS
    assert math.isclose(3600 / (480 - 100 - 8 - 3 - 40), 10.942, abs_tol=1e-3)


SHOWN_JS = """async (st) => { const c = mount('flight-watcher-clock-card-pilot2', {}, st);
  await new Promise((ok) => setTimeout(ok, 80)); const hc = c.shadowRoot.querySelector('ha-card');
  return [hc.className, Math.round(hc.getBoundingClientRect().height), getComputedStyle(hc).display,
    c.shadowRoot.getElementById('st').textContent]; }"""


def test_a_slowed_or_waiting_clock_card_stays_on_screen():
    """1.7.26 review: the box's CSS (a bare .info, 1.7.12) also matched the card itself in its 'info' look, so a
    "Slowed." or "Waiting." clock card had display none; with the admin's held hunt that would be most of a hunt."""
    held = "Hunting every 10 s is held to 380 FLICA loads an hour: checks wait for the budget, at least 11 s apart"
    with _browser() as b:
        for note, label in ((held, "Slowed."), (HOST_NOTE, "Waiting.")):
            pg = _portal_page(b, [_card("clock-card")], width=390)
            st = _states("clock", True, st="hunting", note=note)
            st["sensor.flight_watcher_pilot2_next_check"] = _s("2026-11-10T11:40:00+00:00")
            cls, h, disp, got = pg.evaluate(SHOWN_JS, st)
            pg.context.close()
            assert (cls, got, disp) == ("info", label, "flex") and h > 40, (label, cls, h, disp)

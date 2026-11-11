"""1.7.1 (LIVE-1): a pilot's secondary FLICA reads get a fair, bounded share of his 100 loads an hour.

Seen live on Nov 11, 2026 (a pilot instance hunting at its budget's pace): every few minutes the log said
"tradeboard_check left out of this check: FLICA budget kept for the open time pot", and the same for grid_check,
pot_details and the trade requests. The optional loads an hour (opt_cap) were one first come, first served pool, so the
reads that come first in a check (his own trips, pickups, the in-flight lookups) took every load that came free and the
Tradeboard, the reserve grid, the request lists and the pot details never ran. Now each of those four has its own
share of the hour (opt_shares: one whole read an hour), the rest stays a shared pool, the hunt's pace is sized from the
budget less those shares, and the hard caps (a pilot's 100 an hour, the host's 480) still hold. The admin is
untouched: no budget, no shares, his 376 an hour (FW-0035) as before.

The real check() runs for 3 hours on a fake clock with synthetic pages only ("Doe, Jane" 10001); FLICA is never
reached."""
import collections
import functools
import os

import pytest

import gate as GT
from test_release_a_flica import FX, _lookup, mk, real_fl  # noqa: F401

SECONDARY = ("tradeboard_check", "grid_check", "requests_check", "pot_details")
POT = open(os.path.join(FX, "mobile_pot_rows.html"), encoding="utf-8").read()


def _pot_page(W, n):
    """The pot fixture with its last row renamed every 10 min (a trip that leaves and a new one), so pot_details has a
    row to read each hour."""
    return POT.replace("H3649", f"H{3700 + n % 90}")


def _answer(W, slot):
    def ans(u):
        low = u.lower()
        if "mobilepairing" in low:  # first: a pot row's detail link names the pot (FROM=MobileOpentimePot)
            return "<html><body>Pairing H9999:01NOV Check In: 07:00 Crew: CA 10001 DOE, JANE</body></html>"
        if "opentimepot" in low:
            return _pot_page(W, slot["n"])
        if "cmschedules" in low and "bd=1126" in low:
            return _lookup("1126")
        if "tb_" in low:
            return "<html><body>Tradeboard All Requests</body></html>"
        if "reservegridservice" in low:
            return "{}"
        if "mobileotrequest" in low:
            return "<html><body>Open Time Requests: no requests</body></html>"
        return "<html><body>Pairing H9001 Check In: 08:00</body></html>"
    return ans


def _run(W, monkeypatch, months, hours=3):
    """The real check() at the main loop's pace (free_in, gap()) for `hours`; own_trip_times is a greedy optional read
    that loads one page every check (the reads that used to take every free load). Returns (fl, ran, checks): ran is
    {read: [check times when it loaded at least one page]}."""
    W.S["own_emp"] = "10001"
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}  # the floor: the pace is his budget's
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    if months == 2:
        W.S["pot_urls"]["mobile_003.153"] = f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    slot = {"n": 0}
    fl = real_fl(W, _answer(W, slot))
    W.Flica.render = lambda self, url, wait_for=None, timeout=30000: (self.fetch(url), [])
    ran = collections.defaultdict(list)
    for name in SECONDARY:
        real = getattr(W, name)

        def wrap(*a, _real=real, _name=name, **k):
            n0 = len(fl.loads)
            try:
                return _real(*a, **k)
            finally:
                if len(fl.loads) > n0:
                    ran[_name].append(W.CLOCK.t)
        monkeypatch.setattr(W, name, functools.wraps(real)(wrap))

    def own_trip_times(fl_, full=False):  # greedy: one pairing page every check
        fl_.fetch(f"{W.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261106&n={len(fl_.loads)}")
    monkeypatch.setattr(W, "own_trip_times", own_trip_times)
    t0, checks = W.CLOCK.t, []
    while W.CLOCK.t - t0 < hours * 3600:
        slot["n"] = int((W.CLOCK.t - t0) // 600)
        wait, _ = W.GATE.free_in(min(W.check_tokens(), W.GATE.budget or W.GATE_CHECK_TOKENS))
        if wait > 0:
            W.CLOCK.t += wait
            continue
        checks.append(W.CLOCK.t)
        W.RUN.update(check=True, aborted="", skipped=set())
        try:
            W.check(fl)
        finally:
            W.RUN["check"] = False
        W.CLOCK.t += W.gap()
    return fl, ran, checks, t0


def _worst_hour(times):
    return max((sum(1 for x in times if t - 3600 < x <= t) for t in times), default=0)


@pytest.mark.parametrize("months", [1, 2])
def test_each_secondary_read_runs_every_hour_under_a_hunt_at_the_floor(mk, monkeypatch, months):
    W = mk("pilot2")
    fl, ran, checks, t0 = _run(W, monkeypatch, months)
    for h in range(3):
        lo, hi = t0 + h * 3600, t0 + (h + 1) * 3600
        for name in SECONDARY:
            assert any(lo <= t < hi for t in ran[name]), (name, h, {k: len(v) for k, v in ran.items()})
    loads = [t for t, _ in fl.loads]
    pot = [t for t, u in fl.loads if "opentimepot" in u]
    assert _worst_hour(loads) <= GT.PILOT_BUDGET_H  # his hard cap
    assert len(pot) == months * len(checks)  # the pot was read on every check, none left out
    pace = W.budget_pace_s()
    gaps = [b - a for a, b in zip(checks, checks[1:])]
    assert min(gaps) >= pace - 1e-6  # the hunt at its pace: the shares came out of the budget, not out of the pot


def test_the_shares_are_sized_from_his_folders_and_bounded_by_his_optional_loads(mk):
    W = mk("pilot2")
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    sh = W.opt_shares()
    assert sh == {"tradeboard_check": 2, "grid_check": 2, "requests_check": 2, "pot_details": 2}
    assert W.opt_hour() == W.PACE_OPT_H  # one bid month: 8 shared out of the 12 he always kept, 4 left in the pool
    assert W.budget_pace_s() == pytest.approx(3600 / (100 - 4 - 3 - 12))  # unchanged: about 44 s
    assert W.opt_cap() == W.PACE_OPT_H
    W.S["pot_urls"]["mobile_003.153"] = f"{W.BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    sh = W.opt_shares()
    assert sh == {"tradeboard_check": 4, "grid_check": 4, "requests_check": 4, "pot_details": 2}
    assert W.opt_hour() == sum(sh.values()) + W.OPT_POOL_H == 18
    assert W.budget_pace_s() == pytest.approx(2 * 3600 / (100 - 4 - 3 - 18))  # 96 s (89 s before)
    assert W.opt_cap() == 18
    W.S["close_in"], W.S["close_in_bcid"] = {"bcid": "008.153", "verified": True}, "008.153"
    assert W.opt_shares()["requests_check"] == 5  # the close-in folder's request list too
    assert W.budget_pace_s() == pytest.approx(2 * 3600 / (100 - 4 - 3 - 19 - 12))  # its 12 reads an hour too: 116 s


def test_a_read_past_its_share_uses_the_pool_and_the_total_never_passes_the_cap(mk):
    W = mk("pilot2")
    W.FLAGS["hunt"] = True
    W.S["freq"] = {"hunt_s": 5, "normal_min": 1}
    W.S["pot_urls"] = {"mobile": W.MOBILE_POT}
    fl = real_fl(W, lambda u: "<html><body>Tradeboard All Requests</body></html>")
    W.RUN.update(check=True, optional=True, opt_name="own_trip_times")
    cap, pool = W.opt_cap(), W.opt_cap() - sum(W.opt_shares().values())
    for i in range(pool):  # a busy read takes the whole pool...
        fl.fetch(f"{W.BASE}/full/other.cgi?n={i}")
    with pytest.raises(GT.GateSkip):
        fl.fetch(f"{W.BASE}/full/other.cgi?n=x")  # ...and no more
    W.RUN["opt_name"] = "tradeboard_check"  # the Tradeboard still has its own share
    assert W.opt_fits(2)
    fl.fetch(f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr")
    fl.fetch(f"{W.BASE}/online/tb_otherrequests.cgi?BCID=001.152")
    assert not W.opt_fits(1)
    with pytest.raises(GT.GateSkip):
        fl.fetch(f"{W.BASE}/online/tb_frame.cgi?BCID=001.152&dp=mr")
    for name in ("grid_check", "requests_check", "pot_details"):
        W.RUN["opt_name"] = name
        for _ in range(W.opt_shares()[name]):
            fl.fetch(f"{W.BASE}/full/other.cgi?{name}")
        with pytest.raises(GT.GateSkip):
            fl.fetch(f"{W.BASE}/full/other.cgi?{name}")
    assert len(fl.loads) == cap  # every share and the pool, never more


def test_the_admin_has_no_shares_and_his_reads_are_never_left_out(mk):
    A = mk("")
    A.FLAGS["hunt"] = True
    A.S["pot_urls"] = {"mobile": A.MOBILE_POT}
    assert A.opt_shares() == {} and A.opt_cap() is None and A.budget_pace_s() == 0
    A.RUN.update(check=True, optional=True, opt_name="tradeboard_check")
    assert A.opt_fits(50)
    fl = real_fl(A, lambda u: "<html><body>Tradeboard All Requests</body></html>")
    for i in range(30):
        fl.fetch(f"{A.BASE}/online/tb_frame.cgi?BCID=001.152&n={i}")
    assert len(fl.loads) == 30

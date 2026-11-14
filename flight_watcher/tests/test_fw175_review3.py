"""1.7.5 third review ("Pause wins"), on a fake clock with a fake FLICA (never reached). F1 a pilot's 10 min login floor
counts from the end of his last login: its submit, the login's second gated load, can wait in the gate for his budget
long after its page passed (login_reached), and the next login came 62 s after that submit. A login cut short after
its page passed the gate still counts from there (login_reached). Synthetic details only (u / p)."""
import json

import pytest

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd
from test_fw175_review2 import _budget_full, _run_main_gated, _stopped_pilot


def _gapped_budget(W):
    """The pilot's last hour: one load 59 min 50 s ago, then 99 in a burst 20 min ago (a quiet spell between them, a
    Pause say): a login page now goes in 10 s, and its submit waits about 40 min for his budget."""
    now = W.CLOCK.t
    log = [[now - 3590, W.GATE.who]] + [[now - 1200 + i * 0.4, W.GATE.who] for i in range(99)]
    with open(W.GATE.path, "w") as f:
        json.dump({"v": 1, "last": now - 1160, "log": log}, f)


def test_the_next_login_waits_the_floor_after_a_submit_the_gate_held(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    _gapped_budget(W)
    loads = []
    real = W.Flica._load

    def load(self, url=None):  # each gated load's pass: a login's page, then its submit
        out = real(self, url)
        loads.append(W.CLOCK.t)
        return out
    monkeypatch.setattr(W.Flica, "_load", load)
    res = iter(["needs_login"] + ["ok"] * 50)  # the new session is gone at its first check: a back-off login
    logins, _ = _run_main_gated(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None,
                                check=lambda: next(res), max_sleeps=12)
    assert len(logins) >= 2 and len(loads) >= 3, (logins, loads)
    page1, submit1, page2 = loads[:3]
    assert submit1 - page1 > 1800, loads  # the first login's submit waited in the gate for his budget
    assert page2 - submit1 >= W.LOGIN_MIN_GAP_S, loads  # the next login no sooner than the floor after it


def test_a_login_cut_short_after_its_page_passed_the_gate_counts_from_there(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    _budget_full(W)  # the login page waits about 50 min for his budget
    real = W.Flica._load

    class Cut(Exception):
        pass

    class Fl:
        login_error = None

        def login(self):
            real(self)  # the login page passes the gate: FLICA is reached
            self.reached = W.CLOCK.t
            raise Cut()  # a restart before its submit
    fl = Fl()
    with pytest.raises(Cut):
        W.try_login(fl, "re-arm")
    assert fl.reached - W.load_state()["login_ts"] == 0  # saved when the page passed, not before its wait
    assert not W.RUN["login"]

"""1.6.2 (Release A, item 1): the host-wide FLICA gate (gate.Gate). Every Watcher in the container loads FLICA through
one lock file: any two loads from the host at least 1.5 s apart, a Watcher's own loads uniform(1.5, 3.5) s apart, at
most 480 loads an hour from the host and 100 an hour from a pilot (a token comes back an hour after its load); an
empty bucket makes the load wait (never skipped), and the wait is told for the state note. Never a deadlock: a lock
held elsewhere, a dead holder, a broken or stale file. No FLICA, no network: a fake clock."""
import fcntl
import json
import os
import subprocess
import sys
import time

import pytest

import gate as GT


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t, self.slept = t, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _gate(path, who="admin", budget=None, clock=None, pace=2.0, notes=None, log=None):
    clock = clock or Clock()
    return GT.Gate(str(path), who, budget=budget, clock=clock, sleep=clock.sleep, rand=lambda: pace, log=log,
                   on_wait=(lambda why, until: notes.append((why, until))) if notes is not None else None), clock


def _times(path):
    return [t for t, _ in json.loads(open(path).read())["log"]]


def test_one_watcher_paces_every_load_from_its_last(tmp_path):
    g, c = _gate(tmp_path / "g.lock", pace=2.7)
    t0 = c.t
    for _ in range(4):
        g.acquire()
    ts = _times(tmp_path / "g.lock")
    assert ts[0] == t0 and len(ts) == 4
    assert all(b - a >= 2.7 - 1e-6 for a, b in zip(ts, ts[1:]))  # uniform(1.5, 3.5) drawn per load; 2.7 here


def test_the_pace_is_drawn_between_1_5_and_3_5_s(tmp_path):
    g = GT.Gate(str(tmp_path / "g.lock"), "admin")
    draws = [g.rand() for _ in range(300)]
    assert min(draws) >= 1.5 and max(draws) <= 3.5 and max(draws) - min(draws) > 1


def test_two_watchers_on_one_host_stay_1_5_s_apart(tmp_path):
    c = Clock()
    a, _ = _gate(tmp_path / "g.lock", "admin", clock=c, pace=1.5)
    j, _ = _gate(tmp_path / "g.lock", "james", budget=100, clock=c, pace=1.5)
    a.acquire()
    j.acquire()  # the pilot's own last load is long ago, but the host's was just now
    a.acquire()
    j.acquire()
    ts = _times(tmp_path / "g.lock")
    assert len(ts) == 4 and all(b - a_ >= GT.HOST_GAP_S - 1e-6 for a_, b in zip(ts, ts[1:]))
    who = [w for _, w in json.loads(open(tmp_path / "g.lock").read())["log"]]
    assert who == ["admin", "james", "admin", "james"]


def test_a_pilot_budget_of_100_an_hour_waits_and_says_so(tmp_path):
    notes = []
    g, c = _gate(tmp_path / "g.lock", "james", budget=GT.PILOT_BUDGET_H, pace=1.5, notes=notes)
    first = c.t
    for _ in range(100):
        g.acquire()
    assert c.t - first < 200 and notes == []  # 100 loads go at the pacing
    g.acquire()  # the 101st: waits until the first load is an hour old (never skipped)
    ts = _times(tmp_path / "g.lock")
    assert len(ts) == 100 and ts[-1] >= first + GT.WINDOW_S  # the oldest left the window: 100 in any hour
    assert notes[0][0] == "budget" and abs(notes[0][1] - (first + GT.WINDOW_S)) < 2 and notes[-1] == ("", None)
    assert g.counts()["own"] == 100


def test_the_admin_has_no_budget_but_the_host_cap(tmp_path):
    c = Clock()
    path = tmp_path / "g.lock"
    now = c.t
    # the pilot made 100 loads and the admin 379 in the last hour: 479, one below the cap
    log = [[now - 3000 + i * 6, "james"] for i in range(100)] + [[now - 2999 + i * 7, "admin"] for i in range(379)]
    path.write_text(json.dumps({"v": 1, "last": now - 10, "log": log}))
    notes = []
    a, _ = _gate(path, "admin", clock=c, pace=1.5, notes=notes)
    a.acquire()
    assert c.t - now < 5 and notes == []  # the 480th goes
    a.acquire()  # the 481st waits for the oldest load to leave the hour
    oldest = min(t for t, _ in log)
    assert c.t >= oldest + GT.WINDOW_S and notes[0][0] == "host"
    assert len(json.loads(path.read_text())["log"]) <= GT.HOST_CAP_H


def test_free_in_tells_the_main_loop_how_long_a_check_must_wait(tmp_path):
    g, c = _gate(tmp_path / "g.lock", "james", budget=3, pace=1.5)
    assert g.free_in(3) == (0.0, "")
    first = c.t
    g.acquire()
    g.acquire()
    w, why = g.free_in(2)  # one token left, two wanted: wait for the first load to age out
    assert why == "budget" and abs(w - (first + GT.WINDOW_S - c.t)) < 1e-6
    assert g.free_in(1) == (0.0, "")


def test_a_lock_held_elsewhere_never_blocks_the_load(tmp_path, monkeypatch):
    monkeypatch.setattr(GT, "LOCK_TRIES", 3)
    monkeypatch.setattr(GT, "LOCK_POLL_S", 0.001)
    path = tmp_path / "g.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)  # another Watcher hung while holding it (a separate open file: it conflicts)
    msgs = []

    class Log:
        def info(self, m, *a):
            msgs.append(m % a)
    try:
        g, c = _gate(path, "james", budget=100, pace=1.5, log=Log())
        t0 = time.time()
        g.acquire()
        g.acquire()
        assert time.time() - t0 < 5  # a bounded wait, then this Watcher's own pacing and budget only
        assert c.slept and min(c.slept) >= 1.5 - 1e-6  # still paced by itself
        assert len(msgs) == 1 and "lock held elsewhere" in msgs[0]  # logged once, not per load
    finally:
        os.close(fd)


def test_a_watcher_that_dies_holding_the_lock_releases_it(tmp_path):
    path = tmp_path / "g.lock"
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, sys, time\n"
        f"fd = os.open({str(path)!r}, os.O_RDWR | os.O_CREAT, 0o600)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\nprint('held', flush=True)\ntime.sleep(60)\n")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        holder.kill()  # a crash: the kernel drops its lock with its open file
        holder.wait(10)
        g, _ = _gate(path, "admin", pace=1.5)
        t0 = time.time()
        g.acquire()
        assert time.time() - t0 < 2 and len(_times(path)) == 1  # written through the lock, not the fallback
    finally:
        if holder.poll() is None:
            holder.kill()


def test_a_broken_or_stale_file_never_holds_a_load_back(tmp_path):
    path = tmp_path / "g.lock"
    path.write_text("{not json")
    g, c = _gate(path, "james", budget=100, pace=1.5)
    t0 = c.t
    g.acquire()
    assert c.t == t0 and len(_times(path)) == 1  # read as empty
    # the clock went back: times in the future are dropped, not waited for
    path.write_text(json.dumps({"v": 1, "last": c.t + 86400, "log": [[c.t + 86400 + i, "james"] for i in range(100)]}))
    t1 = c.t
    g2, _ = _gate(path, "james", budget=100, clock=c, pace=1.5)
    g2.acquire()
    assert c.t - t1 < 5 and len(_times(path)) == 1


def test_the_watcher_wires_one_gate_file_for_every_instance(portal_pilot, tmp_path):
    W, _ = portal_pilot("pilot2")
    assert W.GATE_FILE == os.path.join(os.path.dirname(W.DATA), "flica_gate.lock")  # the parent of /data/<name>
    assert W.GATE.budget == GT.PILOT_BUDGET_H and W.GATE.who == "pilot2"
    A, _ = portal_pilot("", portal=False)
    assert A.GATE_FILE == os.path.join(A.DATA, "flica_gate.lock") and A.GATE.budget is None and A.GATE.who == "admin"


def test_the_budget_and_the_host_gap_hold_to_the_last_microsecond(tmp_path):
    """1.6.2 review: the file keeps each load's time in full, so a token comes back no earlier than one hour after its
    load and the host gap is never cut short by rounding (rounded to 1 ms, 101 loads fit in 3599.9995 s)."""
    import random
    rnd = random.Random(7)
    c = Clock(1_800_000_000.123456789)
    p, _ = _gate(tmp_path / "g.lock", "james", budget=100, clock=c, pace=1.5)
    a, _ = _gate(tmp_path / "g.lock", "admin", clock=c, pace=1.5)
    ts, host = [], []
    while c.t < 1_800_000_000 + 2 * 3600:
        p.acquire()
        ts.append(c.t)
        host.append(c.t)
        c.t += rnd.uniform(0, 0.0009)
        if rnd.random() < 0.1:
            a.acquire()
            host.append(c.t)
            c.t += rnd.uniform(0, 0.0009)
    assert len(ts) > 150
    assert min(b - a for a, b in zip(ts, ts[100:])) >= GT.WINDOW_S  # 101 loads never inside one hour
    assert max(sum(1 for x in ts if t - GT.WINDOW_S < x <= t) for t in ts) == GT.PILOT_BUDGET_H
    assert min(b - a for a, b in zip(host, host[1:])) >= GT.HOST_GAP_S  # never a sub-ms short gap
    assert _times(tmp_path / "g.lock")[-1] == host[-1]  # stored as loaded, not rounded

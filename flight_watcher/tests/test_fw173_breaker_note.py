"""1.7.3: a stopped read path leaves the state note when its stop ends. The note was put together again only on a trip,
a good read on that path, a gate change, a login or a sweep that moved the machine state, so a stop's end (open_until
passing) changed nothing: "FLICA pairing read paused until 05:52 HST" was still up at 06:25 (seen live). The loop's wait
looks again every tick and publishes once when the note changed. A fake clock and fake wake; FLICA is never reached and
no page is loaded."""
import json

import pytest

import gate as GT
from test_release_a_flica import mk, real_fl  # noqa: F401


class FakeWake:
    """W.WAKE for the loop's wait: wait() moves the fake clock by its timeout instead of blocking, never woken."""

    def __init__(self, clock):
        self.clock = clock

    def clear(self):
        pass

    def set(self):
        pass

    def is_set(self):
        return False

    def wait(self, timeout=None):
        self.clock.t += float(timeout or 0)
        return False


def _notes(W):
    """Every note published in sensor.<prefix>_state's attributes, oldest first."""
    return [json.loads(p)["note"] for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"]


def _stopped(W, path, why):
    assert W.BRK.fail(path, why, kind="unknown")  # a page none of its parsers knows: the path stops at once (30 min)
    return W.BRK.until(path)


def _start(mk):
    W = mk()
    W.WAKE = FakeWake(W.CLOCK)
    W.set_machine("idle", "")
    return W


def test_a_stops_note_drops_a_tick_after_its_end_and_is_published_once(mk):
    W = _start(mk)
    until = _stopped(W, "pairing", "not a pairing page")
    note = f"FLICA pairing read paused until {W.hst_hm(until)} HST: not a pairing page"
    assert W.S["note"] == note and _notes(W)[-1] == note
    n = len(_notes(W))
    W.sleep(until - W.CLOCK.t - 1)  # the whole stop, ticking every minute: nothing changed, nothing published
    assert W.S["note"] == note and len(_notes(W)) == n
    W.sleep(2)  # T + 1: the stop is over and the note no longer names it, published once
    assert W.CLOCK.t == until + 1
    assert W.S["note"] == "" and _notes(W)[n:] == [""]
    W.sleep(3 * 3600)  # three more hours of ticks with nothing new: nothing published again
    assert W.S["note"] == "" and _notes(W)[n:] == [""]


def test_a_long_wait_drops_the_note_within_a_minute_of_the_stops_end(mk):
    W = _start(mk)
    until = _stopped(W, "pairing", "not a pairing page")
    seen, publish = [], W.MQ.publish

    def timed(topic, payload=None, qos=0, retain=False):  # the fake clock at each state note published
        if topic == f"{W.T}/state_attr":
            seen.append(W.CLOCK.t)
        publish(topic, payload, qos, retain)
    W.MQ.publish = timed
    W.sleep(90 * 60)  # Ryan's normal check every 90 min: one wait that outlasts the 30 min stop
    assert W.S["note"] == "" and len(seen) == 1
    assert until <= seen[0] <= until + W.WORKING_TICK_S


def test_one_stop_ends_and_the_other_stays_in_the_note(mk):
    W = _start(mk)
    t_pair = _stopped(W, "pairing", "not a pairing page")
    W.sleep(10 * 60)
    t_tb = _stopped(W, "tradeboard", "not a Tradeboard page")
    tb = f"FLICA tradeboard read paused until {W.hst_hm(t_tb)} HST: not a Tradeboard page"
    assert W.S["note"] == f"FLICA pairing read paused until {W.hst_hm(t_pair)} HST: not a pairing page; " + tb
    n = len(_notes(W))
    W.sleep(t_pair - W.CLOCK.t + 1)
    assert W.S["note"] == tb and _notes(W)[n:] == [tb]
    W.sleep(t_tb - W.CLOCK.t + 1)
    assert W.S["note"] == "" and _notes(W)[n:] == [tb, ""]


def test_a_budget_wait_note_stays_when_the_stop_under_it_ends(mk):
    W = _start(mk)
    until = _stopped(W, "pairing", "not a pairing page")
    W.gate_note("host", W.CLOCK.t + 3 * 3600)
    host = W.HEALTH["gate"]
    assert host and W.S["note"].startswith(host + "; FLICA pairing read paused until ")
    n = len(_notes(W))
    W.sleep(until - W.CLOCK.t + 1)
    assert W.S["note"] == host and _notes(W)[n:] == [host]


def test_a_yield_or_pause_note_is_never_replaced_when_a_stop_ends(mk):
    W = _start(mk)
    until = _stopped(W, "pairing", "not a pairing page")
    W.set_machine("yielded", "you are in FLICA: the Watcher waits 30 min")
    n = len(_notes(W))
    W.sleep(until - W.CLOCK.t + 5 * 60)
    assert W.S["note"] == "you are in FLICA: the Watcher waits 30 min" and len(_notes(W)) == n


# ---- 1.7.3 review: inside a check the loop's sleep() never runs, so a stop that ended while a load waited in the gate
# (or while a check's paced loads ran) stayed in the note until that wait or the check ended.
def _timed(W):
    """(fake clock, note) of every state note published from now on."""
    seen, publish = [], W.MQ.publish

    def timed(topic, payload=None, qos=0, retain=False):
        if topic == f"{W.T}/state_attr":
            seen.append((W.CLOCK.t, json.loads(payload)["note"]))
        publish(topic, payload, qos, retain)
    W.MQ.publish = timed
    return seen


def test_a_stop_that_ends_while_a_load_waits_for_the_budget_drops_within_a_wait_chunk(mk):
    W = mk("pilot2")
    fl = real_fl(W, lambda u: "<html>ok</html>")
    t0 = W.CLOCK.t
    for i in range(100):  # his whole hour's budget: the next load waits about 56 min
        fl.fetch(f"{W.BASE}/full/other.cgi?n={i:03d}")
    W.set_machine("hunting", "")
    until = _stopped(W, "pairing", "not a pairing page")
    stop = f"FLICA pairing read paused until {W.hst_hm(until)} HST: not a pairing page"
    seen = _timed(W)
    fl.fetch(f"{W.BASE}/full/other.cgi?n=999")  # the 101st waits for the budget; the 30 min stop ends meanwhile
    assert len(fl.loads) == 101 and fl.loads[-1][0] >= t0 + 3600  # no extra FLICA load
    notes = [n for _, n in seen]
    budget = notes[0][:-len("; " + stop)]
    assert budget.startswith("FLICA budget: 100 page loads in the last hour") and notes[0] == budget + "; " + stop
    assert notes == [budget + "; " + stop, budget, ""]  # each change published once, the budget note stays
    assert until <= seen[1][0] <= until + GT.WAIT_CHUNK_S


@pytest.mark.parametrize("load_s", [0.0, 4.0])  # pages the gate paces, and pages slower than the pace (no gate wait)
def test_a_stop_that_ends_during_a_checks_paced_loads_drops_by_the_next_load(mk, load_s):
    W = mk()
    W.set_machine("idle", "")

    def page(u):
        W.CLOCK.t += load_s
        return "<html>ok</html>"
    fl = real_fl(W, page)
    until = _stopped(W, "tradeboard", "not a Tradeboard page")
    W.CLOCK.t = until - 5  # the stop ends 5 s into the check's 60 loads of other pages (the crew index's, say)
    seen = _timed(W)
    for i in range(60):
        fl.fetch(f"{W.BASE}/full/other.cgi?n={i:03d}")
    assert len(fl.loads) == 60 and fl.loads[-1][0] > until + 60
    assert [n for _, n in seen] == [""]  # published once, nothing while unchanged
    assert until <= seen[0][0] <= until + max(GT.PACE_MAX_S, load_s)

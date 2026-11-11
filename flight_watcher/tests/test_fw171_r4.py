"""1.7.1, review r4 fixes in the Watcher: (1) a van alert's key uses the pairing's base id, so FLICA's rebuilt H3681B on
Ryan's schedule and Hark's H3681 (the same trip, layover.same_pairing) never send the same van alert twice when the
layover leg switches between the two; (2) after an MQTT (re)connect the van and notes sensors go again at the next
van_tick, so a payload dropped while the broker was down (QoS 0) is not lost until it changes again; (3) a pilot's
card copy names the admin in no letter case. Synthetic data only (made-up hotel, "Doe, Jane")."""
import json
import os
import re
from datetime import timedelta

import cards
import layover as LO
from test_layover import FakeClient, _last, _load, _vans, hark  # noqa: F401
from test_layover import _unload  # noqa: F401  (the autouse fixture)
from test_van_package import HARK_VAN, PKG_VAN, _own, _put, package

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- (1) one key per van, whatever the id's spelling
def test_the_key_of_a_rebuilt_pairing_is_its_base_ids():
    info = {"pairing": "H3681B", "at": PKG_VAN}
    assert LO.key(info, 30) == LO.key({**info, "pairing": "H3681"}, 30) == "H3681|2026-11-12T08:25Z|30"
    assert LO.key({**info, "pairing": "H3682"}, 30) != LO.key(info, 30)  # another trip is another key


def test_a_rebuilt_pairing_never_sends_the_same_van_alert_twice(tmp_path, monkeypatch):
    """The reviewer's probe: Ryan's trip is H3681B (FLICA rebuilt it), Hark's sensor and the package say H3681, the
    package VAN 19:25. The 30 min alert goes from Ryan's legs; then his legs are gone (the next tick takes the layover
    from Hark's sensor), and the same van must not alert again; nor when his legs come back."""
    states = {"sensor.hark_working_flight": ("Layover SYD, van 2026-11-12 19:40", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _own(W, pairing="H3681B")
    _put(W, package())
    assert W.van_tick(PKG_VAN - timedelta(minutes=30), mono=0) == [30]
    assert _last(fake, "layover_van")["pairing"] == "H3681B"
    own, sched = W.S.pop("own_trips"), W.S.pop("schedule")  # the own legs gone: Hark's layover leg (H3681) instead
    assert W.van_tick(PKG_VAN - timedelta(minutes=29), mono=10) == []
    assert _last(fake, "layover_van")["pairing"] == "H3681"
    assert [a["status"] for a in _last(fake, "layover_van")["alerts"]] == ["sent", "pending"]
    assert W.van_tick(PKG_VAN - timedelta(minutes=10), mono=20) == [10]
    W.S["own_trips"], W.S["schedule"] = own, sched  # and back to Ryan's H3681B
    assert W.van_tick(PKG_VAN - timedelta(minutes=9), mono=30) == []
    assert [(e["minutes"], e["van_local"]) for e, _ in _vans(fake)] == [(30, "19:25"), (10, "19:25")]
    assert len({e["key"].rsplit("|", 1)[0] for e, _ in _vans(fake)}) == 1


def test_ryans_legs_read_between_the_marks_send_no_second_alert(tmp_path, monkeypatch):
    """The other order: Hark's layover first (H3681), Ryan's H3681B legs read between the 30 and 10 min marks."""
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _put(W, package())
    assert W.van_tick(PKG_VAN - timedelta(minutes=30), mono=0) == [30]
    _own(W, pairing="H3681B")
    assert W.van_tick(PKG_VAN - timedelta(minutes=20), mono=10) == []
    assert W.van_tick(PKG_VAN - timedelta(minutes=10), mono=20) == [10]
    assert [e["minutes"] for e, _ in _vans(fake)] == [30, 10]


# ---------------------------------------------------------------- (2) a reconnect sends the van and notes again
class DropClient(FakeClient):
    """A broker that drops what is published while it is down (QoS 0), as paho does when not connected."""

    def publish(self, topic, payload="", retain=False):
        if self.up:
            FakeClient.publish(self, topic, payload, retain)


def _reconnect(W, monkeypatch):
    class Client(FakeClient):
        def __init__(self, *a, **k):
            FakeClient.__init__(self)

        def username_pw_set(self, *a):
            pass

        def will_set(self, *a, **k):
            pass

        def connect(self, *a):
            pass

        def loop_start(self):
            pass

    class Timer:
        def __init__(self, *a, **k):
            self.daemon = False

        def start(self):
            pass
    monkeypatch.setattr(W.mqtt, "Client", Client)
    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    monkeypatch.setattr(W.threading, "Timer", Timer)
    c = W.mqtt_start()
    c.on_connect(c, None, None, 0)


def test_a_van_and_a_note_changed_while_the_broker_was_down_go_after_the_reconnect(tmp_path, monkeypatch):
    fake = DropClient()
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states, fake=fake)
    LO.add(W.LAYOVERS_DIR, "SYD", "Coffee at the corner cart, 6 AM.", "2026-11-10T20:00:00+00:00")
    now = HARK_VAN - timedelta(hours=3)
    W.van_tick(now, mono=0)
    assert _last(fake, "layover_van")["local"] == "19:40"
    assert _last(fake, "layover_notes")["cities"]["SYD"]["total"] == 1
    n_van = sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_van")
    n_notes = sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_notes")
    # Mosquitto restarts: Hark revises the van to 19:55 and a note is added while it is down
    fake.up = False
    st["sensor.hark_working_flight"] = ("x", hark(van="7:55 PM (19:55) Thu 2026-11-12, Example Harbour Hotel lobby"))
    LO.add(W.LAYOVERS_DIR, "SYD", "Harbour loop run, about 5 km.", "2026-11-11T20:00:00+00:00")
    W.van_tick(now + timedelta(minutes=2), mono=100)
    assert _last(fake, "layover_van")["local"] == "19:40"  # dropped
    # the broker is back: unchanged since the dropped publish, both go again at the next sweep
    fake.up = True
    _reconnect(W, monkeypatch)
    W.van_tick(now + timedelta(minutes=2, seconds=10), mono=110)
    assert _last(fake, "layover_van")["local"] == "19:55"
    assert _last(fake, "layover_notes")["cities"]["SYD"]["total"] == 2
    assert sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_van") == n_van + 1
    assert sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_notes") == n_notes + 1
    W.van_tick(now + timedelta(minutes=2, seconds=20), mono=120)  # then only when they change, as before
    assert sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_van") == n_van + 1
    assert sum(1 for t, _, _ in fake.msgs if t == "flight_watcher/layover_notes") == n_notes + 1


# ---------------------------------------------------------------- (3) a pilot's copy names the admin in no case
def test_a_pilots_card_copies_never_name_the_admin_or_his_house():
    built = cards.build("9.9.9", ["pilot2"])
    copies = {n: t for n, t in built.items() if n.endswith("-pilot2.js")}
    assert copies
    for n, t in copies.items():
        assert not re.search(r"\bryan\b", t, re.I), n
        assert not re.search(r"\bpako\b", t, re.I), n
    tk = copies["flight-watcher-tickets-card-pilot2.js"]
    m = re.search(r'const FW_TICKET_CC_PROMPT = "([^"]*)"', tk)
    assert m and "reporter is not the admin" in m.group(1) and "summarize it for the admin" in m.group(1)
    # the admin's own cards keep the words (his copy is his prompt: reporter ryan is what tickets.py stores)
    own = built["flight-watcher-tickets-card.js"]
    assert "reporter is not ryan" in own and "on Pako HI" in own


def test_scrub_names_in_any_case_keeps_the_sentence_whole():
    assert cards.scrub_names("Reporter ryan. ryan's card (Ryan)") == "Reporter the admin. The admin's card (the admin)"
    assert cards.scrub_names("// Pako HI, HOM t1218.") == "// The admin's Home Assistant, HOM t1218."
    assert cards.scrub_names("test is is_owner: Pako has another admin login") == \
        "test is is_owner: the admin's Home Assistant has another admin login"
    assert cards.scrub_names("ryanair, Bryan, pakora") == "ryanair, Bryan, pakora"  # whole words only
    assert json.dumps(cards.scrub_names('"on Pako HI: fix"')) == json.dumps('"on the admin\'s Home Assistant: fix"')

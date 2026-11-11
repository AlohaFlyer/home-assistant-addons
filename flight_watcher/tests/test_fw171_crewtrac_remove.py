"""1.7.1 (F#155), across both halves: the settings card's Remove CrewTrac login and the Watcher's settings_cmd were
built on two branches (cards and core), each tested against its own idea of the other. Here the card runs on the state
the real Watcher publishes (a pilot's settings_state, its real sealing key), its sealed message goes into the real
settings_cmd, and the state the Watcher publishes back goes to the card again: the login is gone from creds.json, the
FLICA one stays, the card says so in green and offers Remove no more. On a page without the Watcher's key the card
sends nothing (removing goes sealed or not at all) and the Watcher ignores a plain ctweb_off anyway. Synthetic data
and made-up names only ("Doe, Jane")."""
import json

import cards
from test_fw171_cards import NOW_TS, P, _browser, _card, _page, _pilot, _s, _sent

EARLIER = "2026-11-10T11:00:00+00:00"  # the state the card first shows (any time before the Watcher's answer)


def _states(attrs):
    return _pilot({"sensor.flight_watcher_settings": _s("ok", attrs), "sensor.flight_watcher_state": _s("idle", {"role": "pilot"})})


def _last_state(W):
    return json.loads([p for t, p, *_ in W.MQ.raw.msgs if t == f"{W.T}/settings/state"][-1])


def _msg(pg):
    return pg.evaluate("[(C.shadowRoot.querySelector('#msg span') || {}).className, C.shadowRoot.querySelector('#msg').textContent]")


def test_the_cards_remove_crewtrac_login_is_what_the_watcher_takes(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    assert W.T == P
    restarts = []
    monkeypatch.setattr(W, "restart_later", lambda: restarts.append(1))
    json.dump({"username": "doej2", "password": "fl pw", "ctweb_username": "doej", "ctweb_password": "ct pw"},
              open(W.CREDS_FILE, "w"))
    W.OPTS = W.load_opts()  # 1.7.1 review: as at a start, the options hold creds.json's logins
    st = {**W.settings_state(creds=W.load_creds()), "at": EARLIER}
    assert st["instance"] == "pilot2" and st["ctweb_username"] == "doej" and st["has_ctweb_password"] and st["pubkey"]

    # no key on the page: the card sends nothing, and a plain ctweb_off would change nothing on the Watcher either
    plain = {k: v for k, v in st.items() if k not in ("pubkey", "kid")}
    with _browser() as b:
        pg = _page(b, [cards.build("9.9.9", ["pilot2"])["flight-watcher-settings-card-pilot2.js"]])  # his HA copy
        pg.evaluate("(st) => { window.C = mount('flight-watcher-settings-card-pilot2', {}, st); }", _states(plain))
        pg.once("dialog", lambda d: d.accept())
        pg.locator("flight-watcher-settings-card-pilot2").locator("#ctoff").click()
        pg.wait_for_timeout(50)
        assert _sent(pg) == [] and "Removing a login is sent encrypted only" in _msg(pg)[1]
    assert W.settings_cmd(json.dumps({"ctweb_off": True})) is False and W.load_creds()["ctweb_username"] == "doej"

    with _browser() as b:
        pg = _page(b, [_card("settings-card")])  # the portal's copy (FW_PORTAL on), sealing with the Watcher's key
        pg.evaluate("(st) => { window.C = mount('flight-watcher-settings-card-pilot2', {}, st); }", _states(st))
        pg.once("dialog", lambda d: d.accept())
        pg.locator("flight-watcher-settings-card-pilot2").locator("#ctoff").click()
        pg.wait_for_function("window.calls.length === 1")
        assert pg.evaluate("window.calls[0][2].topic") == f"{W.T}/settings/set"
        sent = _sent(pg)
        assert len(sent) == 1 and list(sent[0]) == ["enc"]
        with monkeypatch.context() as m:
            m.setattr("time.time", lambda: NOW_TS)  # the page's clock is fixed at NOW: the sealed message is that fresh
            assert W.settings_cmd(json.dumps(sent[0])) is True
        assert W.load_creds() == {"username": "doej2", "password": "fl pw"} and restarts == [1]
        back = _last_state(W)
        assert back["result"] == "saved: CrewTrac login removed"
        assert back["ctweb_username"] == "" and back["has_ctweb_password"] is False and back["has_password"] is True
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _states(back))
        assert pg.evaluate("C.shadowRoot.querySelector('#ctoff')") is None  # nothing saved: nothing to remove
        assert _msg(pg) == ["ok", "saved: CrewTrac login removed"]

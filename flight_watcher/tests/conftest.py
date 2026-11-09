import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def fx():
    def load(name):
        return open(os.path.join(FIX, name), encoding="utf-8").read()
    return load


# ---------------------------------------------------------------- 1.6.0 (FW-0061): a pilot whose portal is on
class FakeMQ:
    """An MQTT client that records (topic, payload, qos, retain)."""

    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.msgs.append((topic, payload, qos, retain))

    def subscribe(self, topic, *a, **k):
        pass


class FakeHA:
    """Home Assistant's /core/api/states/<id> through the Supervisor proxy: answers from `states`, records each URL
    asked for. `down` makes every answer a 502."""

    def __init__(self, states=None):
        self.states, self.urls, self.down = dict(states or {}), [], False

    def get(self, url, headers=None, timeout=None, **k):
        self.urls.append(url)
        eid = url.rsplit("/", 1)[-1]
        ha = self

        class R:
            status_code = 502 if ha.down else (200 if eid in ha.states else 404)
            ok = status_code == 200

            def json(self):
                return ha.states[eid]
        return R()


def ha_state(eid, state, attrs=None):
    return {"entity_id": eid, "state": state, "attributes": dict(attrs or {}),
            "last_changed": "2026-11-09T20:00:00+00:00", "last_updated": "2026-11-09T20:00:00+00:00",
            "context": {"id": "01J0000000000000000000000", "user_id": "u-secret-context"}}


@pytest.fixture
def portal_pilot(tmp_path, monkeypatch):
    """load(instance="pilot2", portal=True, states=None) -> (watcher module, FakeHA): watcher.py imported as that
    instance under tmp_path, its portal folders (portal.prepare, not as root) and the signing key made like run.py does,
    MQ a recording FakeMQ wrapped the way mqtt_start wraps it. The portal is not started (call W.portal_start(False))."""
    import json as _json
    import portal as PT

    def load(instance="pilot2", portal=True, states=None):
        data = tmp_path / ("data_" + (instance or "default"))
        data.mkdir(exist_ok=True)
        (data / "options.json").write_text(_json.dumps({"username": "u", "password": "p", "log_level": "info",
                                                        "category_check": "HNL 332 FO"}))
        root = tmp_path / "share" / "fw_portal"
        root.parent.mkdir(exist_ok=True)
        key = tmp_path / "keydata" / "portal_ed25519.pem"
        if not key.exists():
            PT.load_key(str(key))
        if instance:
            PT.prepare(str(root), [instance], log=lambda m: None)  # as root: the real owners (2061 on in/)
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
        for k in ("FLIGHT_WATCHER_PORTAL", "FLIGHT_WATCHER_PORTAL_DIR", "FLIGHT_WATCHER_PORTAL_KEY",
                  "FLIGHT_WATCHER_PORTAL_ORIGIN", "FLIGHT_WATCHER_PORTAL_PUB"):
            monkeypatch.delenv(k, raising=False)
        if portal:
            monkeypatch.setenv("FLIGHT_WATCHER_PORTAL", "1")
            monkeypatch.setenv("FLIGHT_WATCHER_PORTAL_DIR", str(root / (instance or "admin")))
            monkeypatch.setenv("FLIGHT_WATCHER_PORTAL_KEY", str(key))
        sys.modules.pop("watcher", None)
        import watcher as W
        monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
        ha = FakeHA(states)
        monkeypatch.setattr(W.requests, "get", ha.get)
        mq = FakeMQ()
        monkeypatch.setattr(W, "MQ", W.portal_wrap(mq) if W.portal_on() else mq)
        W.MQ.raw = mq
        W.S.clear()
        return W, ha

    yield load
    sys.modules.pop("watcher", None)

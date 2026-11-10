"""1.6.1 stage 0 (CrewTrac): a login tells ok, refused and outage apart; a refusal blocks every later login (timer and
Scan CrewTrac now) until other details are saved; an outage backs off 30 min doubling to 6 h; Scan CrewTrac now keeps
30 min between the scans it starts and never queues a second one; the status in plain words for a pilot and the
admin; passwords kept exactly as typed end to end; the admin's working login scans as before.
Synthetic pages, names and numbers only ("Doe, Jane", 10001); nothing here reaches CrewTrac or FLICA."""
import json
import logging
import sys
from datetime import datetime

import pytest
import requests

import charter as CH
import inflt as IF
import sealed as SEAL
import web
from test_charter import LOGIN, TABLE
from test_ntfy import _node, CARD

NOW = datetime(2026, 11, 10, 8, 5)  # HST, as local_now() gives it
USER, BAD, GOOD = "10001", "pw-synthetic-wrong", "pw synthetic right "  # the good one ends in a space
REFUSAL = LOGIN.replace("<form", "<span id='lblMsg'>Invalid User ID or Password</span><form")
MENU = "<html><body>CrewTrac Menu Home | Sign Out Options View Schedule Change Password</body></html>"
MENU_URL = CH.BASE + "/Pilot/ctwcmainmenu.aspx"


class R:
    def __init__(self, text, url):
        self.text, self.url = text, url


class FakeCrewTrac:
    """CrewTrac as the Scanner sees it. mode: ok | refused | noform | unexpected | down | timeout | dropped."""

    def __init__(self, mode="ok", on_login=None):
        self.mode, self.calls, self.on_login = mode, [], on_login
        self.page = self.answer = None  # the login page GET gives / the page a login POST gives (overrides mode)

    def session(self):
        ct = self

        class Sess:
            def __init__(self):
                self.headers = {}

            def get(self, url, timeout=0):
                ct.calls.append(("GET", url))
                if ct.mode == "down":
                    raise requests.ConnectionError("synthetic: no route")
                if "ctw4190" in url:
                    return R(LOGIN if ct.mode == "dropped" else TABLE, url)
                if ct.mode == "noform":
                    return R("<html><body>CrewTrac is down for maintenance</body></html>", url)
                if ct.mode == "menu":  # a session that is still logged in
                    return R(MENU, MENU_URL)
                return R(ct.page or LOGIN, url)

            def post(self, url, data=None, timeout=0, allow_redirects=True):
                ct.calls.append(("POST", url, dict(data or {})))
                if ct.on_login:
                    ct.on_login()
                if ct.mode == "timeout":
                    raise requests.Timeout("synthetic: read timed out")
                if ct.answer is not None:
                    return R(ct.answer, CH.LOGIN)
                if ct.mode == "refused":
                    return R(REFUSAL, CH.LOGIN)
                if ct.mode == "unexpected":
                    return R("<html><body>Server Error in '/Pilot' Application.</body></html>", CH.LOGIN)
                return R(MENU, MENU_URL)
        return Sess()

    def logins(self):
        return [c for c in self.calls if c[0] == "POST"]


class FakeMQ:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.msgs.append((topic, payload, qos, retain))

    def charters(self, prefix):
        return [json.loads(p) for t, p, _, _ in self.msgs if t == f"{prefix}/charters"]


class FakeEvent:
    def __init__(self):
        self.flag, self.waits = False, []

    def set(self):
        self.flag = True

    def is_set(self):
        return self.flag

    def clear(self):
        self.flag = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.flag


@pytest.fixture
def load(tmp_path, monkeypatch):
    """load(instance="", opts=None, creds=None, mode="ok") -> (watcher, FakeCrewTrac); load() again with the same
    instance is a restart (same /data, new process)."""
    monkeypatch.setattr(IF, "CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 0)
    state = {}

    def _load(instance="", opts=None, creds=None, mode="ok"):
        data = tmp_path / ("data_" + (instance or "admin"))
        data.mkdir(exist_ok=True)
        (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "log_level": "info",
                                                       **(opts or {})}))
        if creds is not None:
            (data / "creds.json").write_text(json.dumps(creds))
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        for k in ("FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL", "FLIGHT_WATCHER_PORTAL_DIR",
                  "FLIGHT_WATCHER_PORTAL_KEY", "FLIGHT_WATCHER_PORTAL_ORIGIN", "FLIGHT_WATCHER_PORTAL_PUB"):
            monkeypatch.delenv(k, raising=False)
        sys.modules.pop("watcher", None)
        import watcher as W
        monkeypatch.setattr(W, "local_now", lambda: NOW)
        monkeypatch.setattr(W, "restart_later", lambda: None)
        monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "captures"))  # 1.6.2: the charter capture is per instance
        monkeypatch.setattr(W.CAP, "root", str(tmp_path / "share"))
        W.MQ = FakeMQ()
        ct = FakeCrewTrac(mode)
        monkeypatch.setattr(W.requests, "Session", ct.session)
        state["W"] = W
        return W, ct

    yield _load
    sys.modules.pop("watcher", None)


def _pilot(load, mode="refused", password=BAD):
    return load("pilot2", creds={"ctweb_username": USER, "ctweb_password": password}, mode=mode)


# ---------------------------------------------------------------- charter.Scanner.login: three outcomes
@pytest.mark.parametrize("mode,want", [("ok", CH.OK), ("refused", CH.REFUSED), ("noform", CH.OUTAGE),
                                       ("unexpected", CH.OUTAGE), ("down", CH.OUTAGE), ("timeout", CH.OUTAGE)])
def test_login_tells_ok_refused_and_outage_apart(mode, want, caplog):
    ct = FakeCrewTrac(mode)
    with caplog.at_level(logging.INFO, logger="t"):
        got = CH.Scanner(ct.session(), USER, GOOD, logging.getLogger("t")).login()
    assert got == want
    assert GOOD.strip() not in caplog.text and USER not in caplog.text  # never a typed value in the log
    for c in ct.logins():
        assert c[2]["ctl00$txtPassword"] == GOOD and c[2]["ctl00$txtUsername"] == USER  # the password byte for byte
    if mode == "refused":
        assert "charter: login refused (" in caplog.text and "Invalid User ID or Password" in caplog.text


def test_refusal_text_and_backoff_steps():
    for t in ("Invalid User ID or Password", "invalid username or password.", "The password is incorrect",
              "Your account has been locked"):
        assert CH.refused(t), t
    for t in ("CrewTrac Menu Home | Sign Out Change Password", "User ID Password Login", "Server Error"):
        assert not CH.refused(t), t
    assert [CH.backoff_s(n) for n in range(1, 8)] == [1800, 3600, 7200, 14400, 21600, 21600, 21600]
    assert CH.backoff_s(10 ** 6) == 6 * 3600
    h = CH.creds_hash(USER, BAD)
    assert len(h) == 64 and USER not in h and h != CH.creds_hash(USER, BAD + " ")
    assert h != CH.creds_hash(USER + "1", BAD)  # the user name is part of the key too


# ---------------------------------------------------------------- the refusal block
def test_a_refusal_blocks_every_later_login_until_new_details(load, caplog):
    W, ct = _pilot(load)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.charter_scan() is False
    assert len(ct.logins()) == 1
    rec = W.DB.get("crewtrac")
    assert rec["state"] == "refused" and rec["block"] == CH.creds_hash(USER, BAD) == rec["creds"]
    assert BAD not in json.dumps(rec) and USER not in json.dumps(rec)  # a hash, never the values
    last = W.MQ.charters("flight_watcher_pilot2")[-1]
    assert last["status"] == ("CrewTrac refused your user ID or password at 08:05 HST. No more tries until you save "
                              "new CrewTrac details in Settings.")
    assert last["crewtrac"] == {"state": "refused", "at": "2026-11-10T08:05:00-10:00", "next_try": ""}
    assert BAD not in caplog.text
    # the timer: no wait, no login
    assert W.charter_wait() is None
    for _ in range(3):
        assert W.charter_scan() is False
    W.CHARTER_WAKE = FakeEvent()
    assert W.charter_turn() is False and W.CHARTER_WAKE.waits == [W.CHARTER_IDLE_S]
    # Scan CrewTrac now: the status again, never a login
    n = len(W.MQ.charters("flight_watcher_pilot2"))
    assert W.charter_press() is False and not W.CHARTER_WAKE.is_set()
    assert len(W.MQ.charters("flight_watcher_pilot2")) == n + 1
    W.on_message(None, None, type("M", (), {"topic": "flight_watcher_pilot2/charter_scan/press", "payload": b"PRESS"})())
    assert not W.CHARTER_WAKE.is_set() and len(W.MQ.charters("flight_watcher_pilot2")) == n + 2  # the MQTT button too
    assert len(ct.logins()) == 1
    # a restart with the same details keeps the block
    W, ct = _pilot(load)
    assert W.charter_wait() is None and W.charter_scan() is False and ct.logins() == []
    # new details saved in Settings (the card's sealed path) lift it
    sealed = SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], {"ctweb_password": GOOD})
    assert W.settings_cmd(json.dumps(sealed))
    W, ct = load("pilot2", mode="ok")  # the restart settings_cmd asks for
    assert W.OPTS["ctweb_password"] == GOOD
    assert W.charter_wait() == 0  # due now (no scan yet)
    rec = W.DB.get("crewtrac")
    assert not rec.get("block") and rec["state"] == "" and rec["creds"] == CH.creds_hash(USER, GOOD)
    assert W.DB.get("charter_status") == "New CrewTrac details saved: the next scan tries them."
    assert W.charter_press() is True  # the first press after new details is never held by the gap
    W.CHARTER_WAKE = FakeEvent()
    W.CHARTER_WAKE.set()
    assert W.charter_turn() is True and len(ct.logins()) == 1
    assert ct.logins()[0][2]["ctl00$txtPassword"] == GOOD
    assert W.DB.get("crewtrac")["state"] == "ok"


def test_a_refusal_after_new_details_blocks_those_too(load):
    W, ct = _pilot(load)
    W.charter_scan()
    W.OPTS["ctweb_password"] = BAD + "2"  # other details in use (as after a restart)
    assert W.charter_wait() == 0 and W.charter_scan() is False and len(ct.logins()) == 2
    assert W.DB.get("crewtrac")["block"] == CH.creds_hash(USER, BAD + "2")
    assert W.charter_scan() is False and len(ct.logins()) == 2


def test_status_texts_for_pilot_and_admin(load):
    W, _ = load("pilot2", creds={})
    assert W.charter_scan() is False
    last = W.MQ.charters("flight_watcher_pilot2")[-1]
    assert last["status"] == "Enter your CrewTrac user ID and password in Settings."
    assert last["crewtrac"]["state"] == "not_configured" and W.charter_wait() is None
    assert W.charter_press() is False
    W, ct = load("", mode="refused")  # the admin, nothing in the Configuration tab
    W.charter_scan()
    assert W.MQ.charters("flight_watcher")[-1]["status"] == ("Enter your CrewTrac user ID and password in the app "
                                                              "Configuration tab.")
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": BAD}, mode="refused")
    W.charter_scan()
    assert W.MQ.charters("flight_watcher")[-1]["status"] == (
        "CrewTrac refused your user ID or password at 08:05 HST. No more tries until you save new CrewTrac details in "
        "the app Configuration tab.")
    assert W.charter_scan() is False and len(ct.logins()) == 1
    # the add-on options changed (the app restarts with them): the block is lifted
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": GOOD}, mode="ok")
    assert W.charter_wait() == 0 and W.charter_scan() is True and len(ct.logins()) == 1


# ---------------------------------------------------------------- outages
@pytest.mark.parametrize("mode", ["noform", "unexpected", "down", "timeout", "dropped"])
def test_outage_backs_off_doubling_to_six_hours_and_a_success_resets_it(load, mode):
    import time
    W, ct = _pilot(load, mode=mode, password=GOOD)
    W.CHARTER_WAKE = FakeEvent()
    for want in (1800, 3600, 7200, 14400, 21600, 21600):
        t0 = time.time()
        assert W.charter_scan() is False
        rec = W.DB.get("crewtrac")
        assert rec["state"] == "outage" and t0 + want - 1 <= rec["retry_at"] <= time.time() + want + 1
        assert want - 5 <= W.charter_wait() <= want
    assert len(ct.logins()) == (0 if mode in ("noform", "down") else 6)
    st = W.MQ.charters("flight_watcher_pilot2")[-1]
    assert st["status"] == "CrewTrac could not be reached at 08:05 HST. Next try at 14:05 HST."
    assert st["crewtrac"] == {"state": "outage", "at": "2026-11-10T08:05:00-10:00", "next_try": "2026-11-10T14:05:00-10:00"}
    # the thread waits the back-off (not 30 s to 10 min)
    W.charter_turn()
    assert W.CHARTER_WAKE.waits[0] >= 21600 - 5
    ct.mode = "ok"
    assert W.charter_scan() is True
    rec = W.DB.get("crewtrac")
    assert rec["state"] == "ok" and rec["outages"] == 0 and rec["retry_at"] == 0
    assert W.charter_wait() > CH.SCAN_EVERY_S - 60
    ct.mode = mode
    W.charter_scan()
    assert 1795 <= W.charter_wait() <= 1800  # the sequence starts again at 30 min
    if mode == "unexpected":
        st = W.MQ.charters("flight_watcher_pilot2")[-1]
        assert st["status"] == "CrewTrac could not be reached at 08:05 HST. Next try at 08:35 HST."


# ---------------------------------------------------------------- Scan CrewTrac now
def test_scan_now_keeps_30_min_between_its_scans_and_never_queues_a_second(load, caplog):
    import time
    W, ct = _pilot(load, mode="ok", password=GOOD)
    W.CHARTER_WAKE = FakeEvent()
    t = time.time()
    assert W.charter_press(now=t) is True and W.CHARTER_WAKE.is_set()
    assert W.charter_turn() is True and len(ct.logins()) == 1 and not W.CHARTER_WAKE.is_set()
    n = len(W.MQ.charters("flight_watcher_pilot2"))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.charter_press(now=t + 60) is False and not W.CHARTER_WAKE.is_set()
        assert W.charter_press(now=t + 1799) is False
    assert len(W.MQ.charters("flight_watcher_pilot2")) == n + 2  # the status republished, nothing more
    assert "the last pressed scan was under 30 min ago" in caplog.text
    assert W.charter_press(now=t + 1800) is True
    W.charter_turn()
    assert len(ct.logins()) == 2
    # a press while a scan runs: not queued, and nothing left set for the thread
    seen = []
    ct.on_login = lambda: seen.append((W.charter_press(now=t + 99999), W.CHARTER_BUSY.is_set()))
    W.CHARTER_WAKE.set()
    assert W.charter_turn() is True
    assert seen == [(False, True)] and not W.CHARTER_WAKE.is_set() and not W.CHARTER_BUSY.is_set()
    ct.on_login = lambda: W.CHARTER_WAKE.set()  # a press that slipped in as the scan began
    W.CHARTER_WAKE.set()
    W.charter_turn()
    assert not W.CHARTER_WAKE.is_set()
    assert len(ct.logins()) == 4
    # new details: the first press is not held by the gap
    W.charter_press(now=t + 99999)
    assert W.charter_press(now=t + 99999 + 60) is False
    W.OPTS["ctweb_password"] = GOOD + "x"
    assert W.charter_press(now=t + 99999 + 61) is True


def test_admin_working_login_scans_as_before(load, caplog):
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": GOOD}, mode="ok")
    W.DB.put("charter_scan_at", "2026-11-10T00:00:00+00:00")  # a 1.6.0 success, no crewtrac record yet
    assert W.crewtrac_info() == {"state": "ok", "at": "2026-11-09T14:00:00-10:00", "next_try": "2026-11-09T20:00:00-10:00"}
    W.DB.put("charter_scan_at", "")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.charter_scan() is True
    assert len(ct.logins()) == 1 and len([c for c in ct.calls if "ctw4190" in c[1]]) == 2 * len(CH.scan_dates(NOW.date()))
    assert W.DB.get("charter_status") == "ok: 410 rows, 2 unusual A330, 2 new"
    assert set(W.DB.get("charters")) == {"9980|SIN-HNL|2026-11-04", "471|HNL-MNL|2026-11-05"}
    ev = [json.loads(p) for t, p, _, r in W.MQ.msgs if t == "flight_watcher/event/charter"]
    assert sorted(e["key"] for e in ev) == ["471|HNL-MNL|2026-11-05", "9980|SIN-HNL|2026-11-04"]
    last = W.MQ.charters("flight_watcher")[-1]
    assert last["status"] == "ok: 410 rows, 2 unusual A330, 2 new" and last["count"] == 2 and last["last_scan"]
    assert last["crewtrac"] == {"state": "ok", "at": "2026-11-10T08:05:00-10:00", "next_try": "2026-11-10T14:05:00-10:00"}
    for line in ("charter: login page ", "charter: login response ", "logged in: True", "charter scan: 410 rows, 2 unusual",
                 "CHARTER 2026-11-04 9980 SIN-HNL 332/3 (99xx charter)"):
        assert line in caplog.text, line
    assert CH.SCAN_EVERY_S - 60 < W.charter_wait() <= CH.SCAN_EVERY_S
    assert W.charter_scan() is True and len(ct.logins()) == 2  # one login per scan, as before


# ---------------------------------------------------------------- passwords kept exactly
def test_passwords_are_kept_with_their_spaces_end_to_end(load):
    W, _ = load("pilot2", creds={})
    assert W.settings_cmd(json.dumps({"username": " doej ", "password": "  pw flica  ", "ctweb_username": f" {USER} ",
                                      "ctweb_password": GOOD, "my_name": " Doe "}))
    c = W.load_creds()
    assert c == {"username": "doej", "password": "  pw flica  ", "ctweb_username": USER, "ctweb_password": GOOD,
                 "my_name": "Doe"}
    assert not W.settings_cmd(json.dumps({"password": "   "}))  # all blank: keeps what is saved
    assert W.settings_cmd(json.dumps({"password": "  pw flica"}))  # the spaces alone are a change
    sealed = SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], {"ctweb_password": "\tpw séaled  "})
    assert SEAL.open_sealed(W.settings_key(), sealed["enc"]) == {"ctweb_password": "\tpw séaled  "}
    assert W.settings_cmd(json.dumps(sealed))
    assert W.load_creds()["ctweb_password"] == "\tpw séaled  "
    W, ct = load("pilot2", mode="ok")  # restarted with them
    assert W.OPTS["password"] == "  pw flica" and W.OPTS["username"] == "doej"
    assert W.crewtrac_login() == (USER, "\tpw séaled  ")
    W.charter_scan()
    assert ct.logins()[0][2]["ctl00$txtPassword"] == "\tpw séaled  "
    st = W.settings_state()
    assert st["has_password"] and st["has_ctweb_password"] and "pw" not in json.dumps({k: v for k, v in st.items()
                                                                                      if k not in ("pubkey", "kid")})
    # the Web UI form keeps a password as typed too
    assert web.parse_settings("username=+doej+&password=+a+b+&ctweb_password=%09x&my_name=+Doe+") == {
        "username": "doej", "password": " a b ", "ctweb_password": "\tx", "my_name": "Doe"}
    assert web.parse_settings("password=+++") == {}


def test_settings_card_sends_a_password_exactly_as_typed():
    r = _node("""
const calls = [];
const card = new FlightWatcherSettingsCard();
card.setConfig({ entity: "sensor.flight_watcher_pilot2_settings", topic: "flight_watcher_pilot2/settings/set" });
card.hass = { states: { "sensor.flight_watcher_pilot2_settings": { attributes: { has_password: false } } },
              callService: async (d, s, data) => calls.push(data) };
const set = (k, v) => card.shadowRoot._inputs.find((i) => i.dataset.k === k).value = v;
set("username", "  doej "); set("password", "  pw synthetic 1 "); set("ctweb_username", " 10001 "); set("ctweb_password", "   ");
await card._save();
console.log(JSON.stringify({ sent: calls.map((c) => c.payload) }));
""", open(CARD, encoding="utf-8").read())
    assert [json.loads(p) for p in r["sent"]] == [{"username": "doej", "password": "  pw synthetic 1 ",
                                                   "ctweb_username": "10001"}]


# ---------------------------------------------------------------- review fixes (1.6.1 before release)
HELP = "<p>Passwords are case sensitive. Three incorrect password attempts lock your account. Wrong password? " \
       "Call the help desk.</p>"
WORDINGS = ("Incorrect User ID or Password", "Invalid username and/or password.", "Invalid user id and/or password",
            "The user name or password you entered is incorrect.", "Login failed. Please try again.",
            "Too many failed login attempts. Try again later.")


def _login(ct, caplog=None):
    sc = CH.Scanner(ct.session(), USER, GOOD, logging.getLogger("t"))
    return sc.login(), sc


def test_static_help_text_on_the_login_page_is_no_refusal(caplog):
    """The login page's own help text ("three incorrect password attempts ...") never counts as CrewTrac refusing:
    the same page back is unconfirmed (one more try), a new message on it is a refusal."""
    ct = FakeCrewTrac()
    ct.page = LOGIN.replace("<form", HELP + "<form")
    ct.answer = ct.page
    with caplog.at_level(logging.INFO, logger="t"):
        got, sc = _login(ct)
    assert got == CH.OUTAGE and sc.unconfirmed and len(ct.logins()) == 1
    assert "charter: login not confirmed, the login form came back (" in caplog.text
    assert "charter: login refused" not in caplog.text
    ct.answer = ct.page.replace("<form", "<span id='lblError'>Incorrect password</span><form")
    got, sc = _login(ct)
    assert got == CH.REFUSED and not sc.unconfirmed  # "incorrect password" twice now, once in the help text
    ct.answer = "<html><body>Server Error " + HELP + "</body></html>"  # a site footer on an error page
    got, sc = _login(ct)
    assert got == CH.OUTAGE and not sc.unconfirmed


@pytest.mark.parametrize("wording", WORDINGS)
@pytest.mark.parametrize("shape", ["label", "page", "alert"])
def test_other_refusal_wordings_are_refusals(wording, shape):
    assert CH.refused(wording), wording
    ct = FakeCrewTrac()
    ct.answer = {"label": LOGIN.replace("<form", f"<span id='lblMsg'>{wording}</span><form"),
                 "page": f"<html><body><h2>{wording}</h2><a href='ctwc.aspx'>Back</a></body></html>",
                 "alert": LOGIN.replace("</body>", f"<script>alert('{wording}');</script></body>")}[shape]
    got, sc = _login(ct)
    assert got == CH.REFUSED, (shape, wording)


def test_a_session_still_logged_in_is_ok_without_a_login_post():
    ct = FakeCrewTrac("menu")
    got, sc = _login(ct)
    assert got == CH.OK and ct.logins() == []


def test_the_login_form_back_twice_is_a_refusal_and_presses_wait_for_it(load):
    """A refusal CrewTrac words in a way not on the list (or with no message at all) is not retried on and on: the
    first time the login form comes back is an outage marked unconfirmed (presses held), the second is a refusal."""
    import time
    W, ct = _pilot(load, mode="ok", password=BAD)
    ct.answer = LOGIN  # the same login form back, no message
    W.CHARTER_WAKE = FakeEvent()
    t0 = time.time()
    assert W.charter_scan() is False and len(ct.logins()) == 1
    rec = W.DB.get("crewtrac")
    assert rec["state"] == "outage" and rec["unconfirmed"] == 1 and 1795 <= W.charter_wait() <= 1800
    st = W.MQ.charters("flight_watcher_pilot2")[-1]
    assert st["status"] == ("CrewTrac did not let the login through at 08:05 HST. One more try at 08:35 HST; if that "
                            "fails the same way, no more tries until you save new CrewTrac details in Settings.")
    for i in range(4):  # Scan CrewTrac now, 30 min apart: held, the timer's next try decides
        assert W.charter_press(now=t0 + 1800 * (i + 1)) is False
    assert len(ct.logins()) == 1 and not W.CHARTER_WAKE.is_set()
    assert W.charter_scan() is False and len(ct.logins()) == 2  # the timer's try
    rec = W.DB.get("crewtrac")
    assert rec["state"] == "refused" and rec["block"] == CH.creds_hash(USER, BAD) and W.charter_wait() is None
    for _ in range(72):  # three days of timer turns and presses: nothing more is sent
        W.charter_scan()
        W.charter_press()
    assert len(ct.logins()) == 2


def test_the_unconfirmed_mark_is_cleared_by_a_success(load):
    W, ct = _pilot(load, mode="ok", password=GOOD)
    ct.answer = LOGIN
    W.charter_scan()
    assert W.DB.get("crewtrac")["unconfirmed"] == 1
    ct.answer = None
    assert W.charter_scan() is True and W.DB.get("crewtrac")["unconfirmed"] == 0
    ct.answer = LOGIN
    W.charter_scan()
    assert W.DB.get("crewtrac")["state"] == "outage"  # one hiccup again: not a refusal


def test_an_error_after_a_good_login_backs_off(load, monkeypatch):
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": GOOD}, mode="ok")
    W.DB.put("charter_scan_at", "2026-11-01T00:00:00+00:00")
    monkeypatch.setattr(W.CH, "merge", lambda *a: (_ for _ in ()).throw(KeyError("synthetic")))
    W.CHARTER_WAKE = FakeEvent()  # its wait() returns at once: each turn scans; what counts is what it waited
    assert W.charter_turn() is False and len(ct.logins()) == 1
    rec = W.DB.get("crewtrac")
    assert rec["state"] == "outage" and 1795 <= W.charter_wait() <= 1800
    W.charter_turn()
    W.charter_turn()
    w = W.CHARTER_WAKE.waits
    assert w[0] == 30 and 1795 <= w[1] <= 1800 and 3595 <= w[2] <= 3600  # the back-off, not 30 s each time


def test_a_scan_error_after_a_good_login_is_an_outage(load, monkeypatch):
    W, ct = _pilot(load, mode="ok", password=GOOD)
    monkeypatch.setattr(W.CH.Scanner, "scan", lambda self, today: (_ for _ in ()).throw(ValueError("synthetic")))
    assert W.charter_scan() is False and len(ct.logins()) == 1
    assert W.DB.get("crewtrac")["state"] == "outage" and 1795 <= W.charter_wait() <= 1800


def test_admin_details_saved_in_settings_are_changed_in_settings(load):
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": GOOD},
                 creds={"ctweb_password": BAD}, mode="refused")
    W.charter_scan()
    assert W.MQ.charters("flight_watcher")[-1]["status"] == (
        "CrewTrac refused your user ID or password at 08:05 HST. No more tries until you save new CrewTrac details in "
        "Settings.")


def test_the_charter_thread_survives_an_error(load, monkeypatch):
    W, ct = _pilot(load, mode="ok", password="")  # no details: the turn that only republishes the status

    class Stop(BaseException):
        pass

    real, turns = W.charter_turn, []

    def turn():
        turns.append(1)
        if len(turns) > 2:
            raise Stop()
        return real()

    def boom(*a, **k):
        raise OSError("synthetic: broker gone")

    monkeypatch.setattr(W, "charter_turn", turn)
    monkeypatch.setattr(W, "pub", boom)
    W.CHARTER_WAKE = FakeEvent()
    with pytest.raises(Stop):
        W.charter_thread()
    assert len(turns) == 3 and W.CHARTER_WAKE.waits == [60, 60]


def test_a_press_error_never_reaches_mqtt(load, monkeypatch, caplog):
    W, _ = _pilot(load, mode="ok", password=GOOD)
    monkeypatch.setattr(W, "charter_press", lambda: (_ for _ in ()).throw(OSError("synthetic")))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.on_message(None, None, type("M", (), {"topic": "flight_watcher_pilot2/charter_scan/press",
                                                "payload": b"PRESS"})())
    assert "charter scan press: synthetic" in caplog.text


def test_a_new_user_name_alone_lifts_the_block(load):
    W, ct = _pilot(load)
    W.charter_scan()
    assert W.charter_wait() is None
    assert W.settings_cmd(json.dumps({"ctweb_username": USER + "9"}))
    W, ct = load("pilot2", mode="ok")
    assert W.crewtrac_login() == (USER + "9", BAD) and W.charter_wait() == 0
    assert W.charter_scan() is True and len(ct.logins()) == 1


def test_a_refusal_stays_after_the_details_are_cleared_and_come_back(load):
    """Cleared (not configured) and the same refused details back later (restored file, or the admin's Configuration
    tab) still send nothing: the refused hash is kept apart from the per-details record."""
    import os
    W, ct = _pilot(load)
    W.charter_scan()
    os.remove(W.CREDS_FILE)
    W, ct = load("pilot2", mode="ok")
    assert W.crewtrac_info()["state"] == "not_configured"
    W, ct = load("pilot2", creds={"ctweb_username": USER, "ctweb_password": BAD}, mode="ok")  # restored file
    assert W.charter_wait() is None and W.charter_scan() is False and W.charter_press() is False
    assert ct.logins() == [] and W.crewtrac_info()["state"] == "refused"
    assert W.MQ.charters("flight_watcher_pilot2")[-1]["status"].startswith("CrewTrac refused your user ID or "
                                                                          "password at 08:05 HST.")
    # the admin: blanked in the Configuration tab, then the same password put back
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": BAD}, mode="refused")
    W.charter_scan()
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": ""}, mode="ok")
    assert W.crewtrac_info()["state"] == "not_configured"
    W, ct = load("", opts={"ctweb_username": USER, "ctweb_password": BAD}, mode="ok")
    assert W.charter_wait() is None and W.charter_scan() is False and ct.logins() == []


def test_saving_the_same_details_again_in_settings_allows_one_more_try(load):
    """After CrewTrac unlocked an account (or a refusal that was not one), saving the same details in Settings is the
    way back without sending a wrong password: one more try; refused again, blocked again."""
    W, ct = _pilot(load)
    W.charter_scan()
    W.CHARTER_WAKE = FakeEvent()
    assert W.settings_cmd(json.dumps({"ctweb_password": BAD})) is False  # nothing new: no restart
    st = json.loads([p for t, p, _, _ in W.MQ.msgs if t == "flight_watcher_pilot2/settings/state"][-1])
    assert st["result"] == "nothing new; CrewTrac gets one more try with these details"
    assert W.CHARTER_WAKE.is_set() and W.charter_wait() == 0
    assert W.DB.get("charter_status") == "CrewTrac details saved again: the next scan tries them once more."
    assert W.charter_scan() is False and len(ct.logins()) == 2
    assert W.charter_wait() is None and W.charter_scan() is False and len(ct.logins()) == 2
    # a plain settings save that carries no CrewTrac field lifts nothing
    assert W.settings_cmd(json.dumps({"my_name": "Doe"}))
    W, ct = load("pilot2", mode="ok")
    assert W.charter_wait() is None and ct.logins() == []
    assert W.settings_cmd(json.dumps({"my_name": "Doe"})) is False  # nothing new, no CrewTrac field either
    assert W.charter_wait() is None and ct.logins() == []
    # cleared, then the same details typed in Settings again: a save, so one more try (the restart uses them)
    import os
    os.remove(W.CREDS_FILE)
    W, ct = load("pilot2", mode="ok")
    assert W.settings_cmd(json.dumps({"ctweb_username": USER, "ctweb_password": BAD}))
    W, ct = load("pilot2", mode="ok")
    assert W.charter_wait() == 0 and W.charter_scan() is True and len(ct.logins()) == 1


@pytest.mark.parametrize("last", ["not a date", 12345])
def test_a_first_start_with_an_unreadable_last_scan(load, last):
    W, _ = _pilot(load, mode="ok", password=GOOD)
    W.DB.put("charter_scan_at", last)
    W.DB.put("crewtrac", None)
    assert W.crewtrac_info()["state"] == ""

"""1.6.4 (Ryan, 2026-11-11: "You can have DOH be a field in the settings tab"): a Date of hire field on the Settings
card (the admin's HA card and a pilot's portal copy alike), sent like the other non-secret fields (sealed when it can
be, sealed only in the portal), checked again by the Watcher and kept in <data>/cards.json where pilot_doh() reads it;
a date of hire alone restarts nothing. The longevity year then follows it (PWA 3.B.1, 3.D.2; the PWA 3.D.6 table caps
at 12) unless the pilot chose a year himself; the admin's figures stay as they were. Synthetic data only: made-up
names, logins and dates, a throwaway key."""
import hashlib
import json
import logging
import os
import stat
from datetime import datetime

import pytest

import cards
import pay as PAY
import portal as PT
import roles
import sealed as SEAL
from conftest import ha_state
from test_cards import _chromium
from test_ntfy import _node
from test_portal_contract import CONTRACT_SHA256, DOC, FIXTURE
from test_release_a_schedule_card import _award

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(HERE, "www")
NOW = datetime(2026, 11, 11, 9, 0)  # HST wall clock (local_now)
NOW_UTC = "2026-11-11T20:00:00Z"  # the same moment for the browser's clock
TODAY = "2026-11-11"
DOH = "2019-03-01"  # made up: year 8 on TODAY
# PORTAL_CONTRACT.md as 1.6.3 shipped it: the portal only relays ciphertext, so a date of hire changes no contract
CONTRACT_DOC_SHA256 = "8060970d02f54e4a5bbda5d97be0bdef5eb646235c38484d1a58e7aa1dd67665"  # 1.7.0: contract 1 revision 2


def _src(name):
    return open(os.path.join(WWW, f"flight-watcher-{name}.js"), encoding="utf-8").read()


def _watcher(portal_pilot, monkeypatch, instance="pilot2", portal=True, states=None):
    W, ha = portal_pilot(instance, portal=portal, states=states)
    monkeypatch.setattr(W, "local_now", lambda: NOW)
    restarts = []
    monkeypatch.setattr(W, "restart_later", lambda: restarts.append(1))
    return W, ha, restarts


def _result(W):
    return json.loads([p for t, p, *_ in W.MQ.raw.msgs if t.endswith("/settings/state")][-1])


def _cards_file(W):
    return os.path.join(W.DATA, "cards.json")


def _sealed(W, fields):
    return json.dumps(SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], fields))


# ---------------------------------------------------------------- the Watcher's check
@pytest.mark.parametrize("bad,why", [
    ("2015-6-1", "use YYYY-MM-DD"), ("06/01/2015", "use YYYY-MM-DD"), (20150601, "use YYYY-MM-DD"),
    (" 2015-06-01x", "use YYYY-MM-DD"), ("2015-02-30", "not a real date"), ("2015-13-01", "not a real date"),
    ("2026-11-12", "it is in the future"), ("2099-01-01", "it is in the future"), ("1959-12-31", "it is before 1960"),
])
@pytest.mark.parametrize("sealed", [True, False])
def test_a_bad_date_of_hire_is_refused_with_the_reason(portal_pilot, monkeypatch, caplog, bad, why, sealed):
    W, _, restarts = _watcher(portal_pilot, monkeypatch)
    msg = {"doh": bad, "username": "doej2"}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(_sealed(W, msg) if sealed else json.dumps(msg)) is False
    assert _result(W)["result"] == f"refused: date of hire: {why}; nothing was saved"
    assert not os.path.exists(_cards_file(W)) and W.load_creds() == {} and restarts == []  # nothing saved at all
    assert str(bad).strip() not in caplog.text  # the reason is logged, never the value


@pytest.mark.parametrize("good", ["1960-01-01", TODAY, DOH])
def test_the_edges_are_taken(portal_pilot, monkeypatch, good):
    W, _, restarts = _watcher(portal_pilot, monkeypatch)
    assert W.doh_refusal(good) == ""
    assert W.settings_cmd(json.dumps({"doh": f" {good} "})) is True  # trimmed like the other non-secret fields
    assert W.pilot_doh() == good and restarts == []


# ---------------------------------------------------------------- where it is kept, and no restart for it alone
def test_a_date_of_hire_alone_is_saved_to_cards_json_with_no_restart(portal_pilot, monkeypatch, caplog):
    W, _, restarts = _watcher(portal_pilot, monkeypatch, instance="", portal=False)  # the admin's HA card (plain http)
    json.dump({"doh": "2001-02-03", "theme": "made-up", "layout": {"a": 1}}, open(_cards_file(W), "w"))
    W.S["machine"], W.S["note"], W.S["since"] = "idle", "watching", "2026-11-11T18:00:00+00:00"
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(json.dumps({"doh": "2012-07-08"})) is True
    assert json.load(open(_cards_file(W))) == {"doh": "2012-07-08", "theme": "made-up", "layout": {"a": 1}}
    assert stat.S_IMODE(os.stat(_cards_file(W)).st_mode) == 0o600
    assert not [f for f in os.listdir(W.DATA) if f.startswith(".cards.json")]  # no temp file left behind
    assert restarts == [] and "settings_last" not in W.S and not os.path.exists(W.CREDS_FILE)
    st = _result(W)
    assert st["result"] == "saved: date of hire (no restart needed)" and st["doh"] == "2012-07-08"
    attr = json.loads([p for t, p, *_ in W.MQ.raw.msgs if t == "flight_watcher/state_attr"][-1])
    assert attr["doh"] == "2012-07-08" and attr["note"] == "watching" and attr["version"] == W.VERSION
    assert "2012-07-08" not in caplog.text
    # the same date again: nothing new, nothing written, no restart
    before = os.stat(_cards_file(W)).st_mtime_ns
    assert W.settings_cmd(json.dumps({"doh": "2012-07-08"})) is False
    assert _result(W)["result"] == "nothing new" and restarts == [] and os.stat(_cards_file(W)).st_mtime_ns == before
    # with a login change it is saved too, and the restart is the login's
    assert W.settings_cmd(json.dumps({"doh": "2013-01-02", "username": "doej3"})) is True
    assert restarts == [1] and W.load_creds() == {"username": "doej3"} and W.pilot_doh() == "2013-01-02"
    assert _result(W)["result"] == "saved: username, date of hire"
    assert json.load(open(_cards_file(W)))["theme"] == "made-up"


def test_a_cards_json_that_is_not_an_object_is_replaced(portal_pilot, monkeypatch):
    W, _, _ = _watcher(portal_pilot, monkeypatch, instance="", portal=False)
    open(_cards_file(W), "w").write("not json")
    assert W.settings_cmd(json.dumps({"doh": DOH})) is True
    assert json.load(open(_cards_file(W))) == {"doh": DOH}


def test_a_failed_write_saves_nothing(portal_pilot, monkeypatch):
    W, _, restarts = _watcher(portal_pilot, monkeypatch)

    def boom(*a, **k):
        raise PermissionError("made up")
    monkeypatch.setattr(W.PT, "write_private", boom)
    assert W.settings_cmd(_sealed(W, {"doh": DOH, "username": "doej2"})) is False
    assert _result(W)["result"] == "refused: the date of hire could not be saved; nothing was saved"
    assert W.load_creds() == {} and W.pilot_doh() == "" and restarts == []


def test_a_portal_pilots_sealed_date_of_hire_reaches_his_state_at_once(portal_pilot, monkeypatch):
    W, _, restarts = _watcher(portal_pilot, monkeypatch)
    W.portal_start(threads=False)
    W.EXPORT["dirty"] = set()
    assert W.settings_cmd(_sealed(W, {"doh": DOH})) is True
    assert restarts == [] and W.pilot_doh() == DOH and W.settings_state()["doh"] == DOH
    assert json.load(open(_cards_file(W))) == {"doh": DOH}  # his own data folder, not the admin's
    assert {"sensor.flight_watcher_pilot2_state", "sensor.flight_watcher_pilot2_settings"} <= W.EXPORT["dirty"]


# 1.6.4 review: a date of hire saved with the same logins again still lifts their refusal blocks, as they do alone
FL_CREDS = {"username": "doej2", "password": "made-up pw 1", "ctweb_username": "doej2ct", "ctweb_password": "made-up 2"}


def _refused(W, flica=True, crewtrac=True):
    json.dump(FL_CREDS, open(W.CREDS_FILE, "w"))
    W.OPTS.clear()
    W.OPTS.update(W.load_opts())
    if flica:
        W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
        W.S["flica_refused"] = {"hash": W.flica_creds_hash(), "at": 1794400000.0}
    if crewtrac:
        W.DB.put("crewtrac_refused", {W.CH.creds_hash(FL_CREDS["ctweb_username"], FL_CREDS["ctweb_password"]): 1})
    W.FLAGS["rearm"] = False
    W.WAKE.clear()
    W.CHARTER_WAKE.clear()


@pytest.mark.parametrize("flica,crewtrac,tail", [
    (True, True, "; CrewTrac gets one more try with these details; FLICA gets one more login try with these details"),
    (True, False, "; FLICA gets one more login try with these details"),
    (False, True, "; CrewTrac gets one more try with these details"),
    (False, False, ""),
])
@pytest.mark.parametrize("sealed", [True, False])
def test_the_same_logins_saved_with_a_date_of_hire_still_get_one_more_try(portal_pilot, monkeypatch, flica, crewtrac,
                                                                          tail, sealed):
    W, _, restarts = _watcher(portal_pilot, monkeypatch)
    _refused(W, flica, crewtrac)
    charters = []
    monkeypatch.setattr(W, "publish_charters", lambda *a: charters.append(1))
    msg = {**FL_CREDS, "doh": DOH}
    assert W.settings_cmd(_sealed(W, msg) if sealed else json.dumps(msg)) is True
    assert _result(W)["result"] == "saved: date of hire (no restart needed)" + tail
    assert W.pilot_doh() == DOH and restarts == [] and W.load_creds() == FL_CREDS
    assert "flica_refused" not in W.S and W.FLAGS["rearm"] is flica and W.WAKE.is_set() is flica  # lifted, or none
    assert not W.DB.get("crewtrac_refused") and W.CHARTER_WAKE.is_set() is crewtrac
    assert charters == ([1] if crewtrac else [])
    if flica:  # the state attributes that go out at once say so too
        attr = json.loads([p for t, p, *_ in W.MQ.raw.msgs if t == "flight_watcher_pilot2/state_attr"][-1])
        assert attr["note"] == "FLICA details saved again: one more login try" and attr["doh"] == DOH


def test_the_same_logins_alone_still_say_nothing_new(portal_pilot, monkeypatch):
    """The nothing-new path is as in 1.6.3: the lifts, the words, no restart, False."""
    W, _, restarts = _watcher(portal_pilot, monkeypatch)
    _refused(W)
    monkeypatch.setattr(W, "publish_charters", lambda *a: None)
    assert W.settings_cmd(_sealed(W, FL_CREDS)) is False
    assert _result(W)["result"] == ("nothing new; CrewTrac gets one more try with these details; FLICA gets one more "
                                    "login try with these details")
    assert "flica_refused" not in W.S and W.CHARTER_WAKE.is_set() and restarts == [] and W.pilot_doh() == ""


# ---------------------------------------------------------------- the longevity year follows it
def _prefs(W, values, unconfirmed):
    json.dump({"values": values, "updated": {k: "2026-11-09T20:14:01+00:00" for k in values},
               "seeded": "2026-11-09T20:14:01+00:00", "checked": "2026-11-10T00:00:00+00:00",
               "unconfirmed": unconfirmed}, open(W.PREFS_FILE, "w"))


def test_an_unconfirmed_longevity_year_yields_to_the_doh_and_a_chosen_one_wins(portal_pilot, monkeypatch):
    W, _, _ = _watcher(portal_pilot, monkeypatch)
    W.portal_start(threads=False)
    _prefs(W, {"federal_tax_pct": 0, "state_tax_pct": 0, "longevity_year": 1},
           ["federal_tax_pct", "longevity_year", "state_tax_pct"])
    rate, yr, _ = W.pay_settings()
    assert yr == 1 and rate == PAY.rate_for(1, TODAY) == 90.00  # no DOH yet: the flagged year 1, as in 1.6.3
    assert W.settings_cmd(_sealed(W, {"doh": DOH})) is True
    rate, yr, _ = W.pay_settings()
    assert yr == PAY.doh_year(DOH, TODAY) == 8 and rate == PAY.rate_for(8, TODAY)
    assert W.pref_cmd(json.dumps({"key": "longevity_year", "value": 5}))  # he picks a year: it wins over the DOH
    rate, yr, _ = W.pay_settings()
    assert yr == 5 and rate == PAY.rate_for(5, TODAY)
    _prefs(W, {"longevity_year": 3}, [])  # a year he set before the DOH: confirmed, it still wins
    assert W.pay_settings()[1] == 3
    _prefs(W, {}, [])  # no year at all: the DOH's
    assert W.pay_settings()[1] == 8


def test_a_doh_past_twelve_years_caps_at_twelve(portal_pilot, monkeypatch):
    W, _, _ = _watcher(portal_pilot, monkeypatch)
    W.portal_start(threads=False)
    _prefs(W, {"longevity_year": 1}, ["longevity_year"])
    assert W.settings_cmd(_sealed(W, {"doh": "1990-01-15"}))
    assert W.pay_settings()[1] == 12


def _helpers(prefix, yr):
    return {f"input_number.{prefix}_longevity_year": ha_state(f"input_number.{prefix}_longevity_year", yr)}


@pytest.mark.parametrize("helper,want", [("6.0", 6), (None, 5)])
def test_the_admins_figures_are_unchanged(portal_pilot, monkeypatch, helper, want):
    """His own longevity helper when set, else his DOH from /data/cards.json (made up here: year 5 on TODAY), as in
    1.6.3; a prefs.json planted in his folder is never read."""
    W, _, _ = _watcher(portal_pilot, monkeypatch, instance="", portal=True,
                       states=_helpers("flight_watcher", helper) if helper else {})
    json.dump({"doh": "2021-12-01"}, open(_cards_file(W), "w"))
    json.dump({"values": {"longevity_year": 1}, "unconfirmed": ["longevity_year"]}, open(W.PREFS_FILE, "w"))
    rate, yr, _ = W.pay_settings()
    assert yr == want and rate == PAY.rate_for(want, TODAY)
    assert W.state_attrs("")["doh"] == "2021-12-01" and W.settings_state()["doh"] == "2021-12-01"


# ---------------------------------------------------------------- the Settings card
def _settings_page(src):
    return ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.calls = [];</script><script>" + src + "</script></body></html>")


SETTINGS_JS = """async ([tag, ent, attrs, typed, extra]) => { window.calls = [];
  const c = document.createElement(tag); c.setConfig({}); document.body.appendChild(c);
  const st = {state: 'True', attributes: attrs, last_updated: 'a'};
  c.hass = {states: {[ent]: st, ...(extra || {})}, callService: async (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot, inp = r.querySelector('input[data-k="doh"]');
  const out = {type: inp.type, value: inp.value, min: inp.min, max: inp.max, status: r.querySelector('b[data-s="doh"]').textContent,
               note: r.getElementById('dohnote').textContent.replace(/\\s+/g, ' '), top: r.querySelector('.note').textContent,
               label: inp.closest('label').querySelector('span').textContent, wide: document.documentElement.scrollWidth};
  if (typed !== null) { inp.value = typed; await c._save(); }
  out.calls = window.calls; out.msg = r.getElementById('msg').textContent; out.after = inp.value;
  c.remove(); return out; }"""


def _settings_run(src, cases):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time(NOW_UTC)
            # an https page (answered here, nothing leaves the test), so WebCrypto is on as on HA and the portal
            html = _settings_page(src)
            pg.route("https://fw.invalid/**", lambda r: r.fulfill(body=html, content_type="text/html"))
            pg.goto("https://fw.invalid/")
            assert pg.evaluate("!!(window.isSecureContext && crypto.subtle)")
            return [pg.evaluate(SETTINGS_JS, c) for c in cases]
        finally:
            b.close()


def _key(tmp_path):
    k = SEAL.load_key(str(tmp_path / "k.pem"))  # a throwaway key for this test only
    return k, SEAL.public_info(k)


def test_the_admins_card_shows_the_field_and_sends_the_date(tmp_path):
    k, info = _key(tmp_path)
    ent, base = "sensor.flight_watcher_settings", {"username": "doej", "has_password": True, "doh": DOH}
    tag = "flight-watcher-settings-card"
    sealed, plain, same, future, early = _settings_run(_src("settings-card"), [
        [tag, ent, {**base, **info}, "2020-04-05"], [tag, ent, base, "2020-04-05"], [tag, ent, {**base, **info}, DOH],
        [tag, ent, {**base, **info}, "2099-01-01"], [tag, ent, {**base, **info}, "1959-12-31"]])
    assert sealed["type"] == "date" and sealed["value"] == DOH and sealed["label"] == "Date of hire"
    assert sealed["min"] == "1960-01-01" and sealed["max"] == TODAY and sealed["wide"] <= 390
    assert sealed["status"] == "longevity year 8"
    assert sealed["note"] == ("Your date of hire sets your longevity year for pay estimates (PWA 3.B.1); it stays on "
                              "this Watcher only. Optional; a blank field keeps what is saved, and saving only a date "
                              "of hire does not restart the Watcher.")
    assert "a date of hire alone does not" in sealed["top"]
    # sealed: the date only inside the ciphertext (the saved username is not sent again)
    [(d, s, data)] = sealed["calls"]
    assert (d, s, data["topic"]) == ("mqtt", "publish", "flight_watcher/settings/set")
    assert "2020-04-05" not in data["payload"]
    body = json.loads(data["payload"])
    assert list(body) == ["enc"] and SEAL.open_sealed(k, body["enc"], now=1794427200) == {"doh": "2020-04-05"}
    # plain http (no key): like the other non-secret fields on the admin's HA card
    assert [json.loads(c[2]["payload"]) for c in plain["calls"]] == [{"doh": "2020-04-05"}]
    assert same["calls"] == [] and same["msg"] == "Nothing to save: no field changed."
    assert future["calls"] == [] and future["msg"] == "Date of hire: it is in the future. Nothing was sent."
    assert early["calls"] == [] and early["msg"] == "Date of hire: it is before 1960. Nothing was sent."


def test_the_portal_copy_sends_the_date_sealed_only(tmp_path):
    k, info = _key(tmp_path)
    src = PT.portal_card(cards.build("1.6.4", ["pilot2"])["flight-watcher-settings-card-pilot2.js"])
    ent, tag = "sensor.flight_watcher_pilot2_settings", "flight-watcher-settings-card-pilot2"
    sealed, nokey, empty = _settings_run(src, [[tag, ent, {"has_password": True, "doh": "", **info}, DOH],
                                               [tag, ent, {"has_password": True}, DOH],
                                               [tag, ent, {"has_password": True}, None]])
    [(_, _, data)] = sealed["calls"]
    assert data["topic"] == "flight_watcher_pilot2/settings/set" and DOH not in data["payload"]
    body = json.loads(data["payload"])
    assert list(body) == ["enc"] and SEAL.open_sealed(k, body["enc"], now=1794427200) == {"doh": DOH}
    assert sealed["after"] == DOH  # not a secret: it stays in the field
    assert nokey["calls"] == [] and "Nothing was sent" in nokey["msg"]  # no key yet: the portal sends nothing plain
    assert empty["value"] == "" and empty["status"] == "not set"
    assert "Encrypted in your browser" in sealed["top"] and "a date of hire alone does not" in sealed["top"]
    assert "Home Assistant" not in sealed["note"]
    # 1.6.4 review: the portal holds the date readable (state.json shows it back on his page), so the copy says so
    assert sealed["note"] == ("Your date of hire sets your longevity year for pay estimates (PWA 3.B.1); your Watcher "
                              "keeps it and shows it back to you on this page, so unlike your logins the portal can "
                              "read it. Optional; a blank field keeps what is saved, and saving only a date of hire "
                              "does not restart the Watcher.")
    assert ("only your Watcher can read it (the portal passes on ciphertext only). Your date of hire is shown back to "
            "you on this page, so the portal can read that one.") in sealed["top"]


def _ly(prefix, state, unconfirmed=False):
    return {f"input_number.{prefix}_longevity_year": {"state": state, "last_updated": "a",
                                                      "attributes": {"unconfirmed": True} if unconfirmed else {}}}


def test_the_status_says_which_longevity_year_pay_uses(tmp_path):
    """1.6.4 review: a year set in Pay settings wins over the DOH (the admin's helper; a year the pilot chose or kept),
    as on the schedule card and in the Watcher's pay figures, so the Settings card says that year is the one pay uses;
    the DOH's own year alone only when the DOH decides it (no year set, or one still flagged unconfirmed)."""
    _, info = _key(tmp_path)
    base = {"has_password": True, "doh": DOH, **info}
    picked = "year 8 from this date; pay uses year {}, set in Pay settings"
    ent, tag = "sensor.flight_watcher_settings", "flight-watcher-settings-card"
    helper, nohelper, unknown = _settings_run(_src("settings-card"), [
        [tag, ent, base, None, _ly("flight_watcher", "6.0")], [tag, ent, base, None, {}],
        [tag, ent, base, None, _ly("flight_watcher", "unavailable")]])
    assert helper["status"] == picked.format(6) and helper["wide"] <= 390  # the admin's own helper
    assert nohelper["status"] == unknown["status"] == "longevity year 8"
    src = PT.portal_card(cards.build("1.6.4", ["pilot2"])["flight-watcher-settings-card-pilot2.js"])
    P, ent, tag = "flight_watcher_pilot2", "sensor.flight_watcher_pilot2_settings", "flight-watcher-settings-card-pilot2"
    chosen, kept1, flagged, unset, nodoh = _settings_run(src, [
        [tag, ent, base, None, _ly(P, "5.0")], [tag, ent, base, None, _ly(P, "1.0")],
        [tag, ent, base, None, _ly(P, "1.0", unconfirmed=True)], [tag, ent, base, None, _ly(P, "unknown")],
        [tag, ent, {**base, "doh": ""}, None, _ly(P, "5.0")]])
    assert chosen["status"] == picked.format(5) and chosen["wide"] <= 390
    assert kept1["status"] == picked.format(1)  # year 1 confirmed with Keep these: it still wins, and the card says so
    assert flagged["status"] == unset["status"] == "longevity year 8"  # the DOH decides
    assert nodoh["status"] == "not set"


def test_the_card_refuses_what_a_date_input_cannot_hold():
    """Browsers without a date picker show a text box: the card's own check (fwDohWhy) catches what is typed."""
    r = _node("""
const calls = [];
const out = {};
for (const v of ["2015-02-30", "15-06-01", "2015/06/01", "2099-01-01", "1959-12-31", "2015-06-01"]) {
  const c = new FlightWatcherSettingsCard();
  c.setConfig({});
  c.hass = { states: { "sensor.flight_watcher_settings": { attributes: { has_password: true } } }, callService: async (d, s, data) => calls.push(data.payload) };
  c.shadowRoot._inputs.find((i) => i.dataset.k === "doh").value = v;
  await c._save();
  out[v] = c.shadowRoot.getElementById("msg").innerHTML;
}
console.log(JSON.stringify({ out, calls, why: [fwDohWhy("2024-02-29", "2026-11-11"), fwDohWhy("2023-02-29", "2026-11-11"), fwDohWhy("2026-11-11", "2026-11-11")] }));
""")
    assert "Date of hire: not a real date. Nothing was sent." in r["out"]["2015-02-30"]
    assert "Date of hire: use YYYY-MM-DD." in r["out"]["15-06-01"] and "use YYYY-MM-DD" in r["out"]["2015/06/01"]
    assert "in the future" in r["out"]["2099-01-01"] and "before 1960" in r["out"]["1959-12-31"]
    assert [json.loads(x) for x in r["calls"]] == [{"doh": "2015-06-01"}]  # plain here (no WebCrypto in this harness)
    assert r["why"] == ["", "not a real date", ""]


# ---------------------------------------------------------------- the schedule card
def _sched_states(prefix, role, doh, pay):
    st = {f"sensor.{prefix}_schedule": {"state": "", "last_updated": "a", "attributes": {"updated": "Nov 9, 2026",
          "months": {"2026-11": {"items": _award()["items"], "days": _award()["days"], "totals": {},
                                 "updated": "Nov 9, 2026"}}}},
          f"input_number.{prefix}_month_offset": {"state": "0", "last_updated": "a"},
          f"sensor.{prefix}_state": {"state": "idle", "last_updated": "a", "attributes": {"role": role, "doh": doh}}}
    for k, (v, flag) in pay.items():
        st[f"input_number.{prefix}_{k}"] = {"state": v, "last_updated": "a",
                                           "attributes": {"unconfirmed": True} if flag else {}}
    return st


SCHED_JS = """(h) => { window.calls = [];
  const c = document.createElement(h.tag); c.setConfig({}); document.body.appendChild(c);
  c.hass = {states: h.states, user: {is_owner: true}, callService: async (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot; const q = (s) => r.querySelector(s);
  const ly = [...r.querySelectorAll('.set select')].find((s) => s.dataset.e.endsWith('_longevity_year'));
  const out = {ubn: q('.ubn') && q('.ubn').textContent, keep: !!q('.set .keep'), ly: ly.value,
               rate: [...r.querySelectorAll('.set .r')].map((x) => x.textContent).pop(), wide: document.documentElement.scrollWidth,
               tot: q('.tot') ? q('.tot').textContent : null};
  if (q('.set .keep')) q('.set .keep').click();
  out.calls = window.calls.map((c) => [c[2].entity_id, c[2].value]);
  c.remove(); return out; }"""


def _sched_run(src, cases):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time(NOW_UTC)
            pg.set_content(_settings_page(src))
            return [pg.evaluate(SCHED_JS, c) for c in cases]
        finally:
            b.close()


def test_the_schedule_card_takes_the_doh_over_an_unconfirmed_year():
    P = "flight_watcher_james"
    tag = "flight-watcher-schedule-card-james"
    flagged = {"federal_tax_pct": ("0.0", True), "state_tax_pct": ("0.0", True), "longevity_year": ("1.0", True)}
    by_doh, ly_only, chosen, none, no_doh = _sched_run(cards.pilot_copy(_src("schedule-card"), "james"), [
        {"tag": tag, "states": _sched_states(P, "pilot", DOH, flagged)},
        {"tag": tag, "states": _sched_states(P, "pilot", DOH, {"federal_tax_pct": ("22.0", False),
                                                               "state_tax_pct": ("0.0", False),
                                                               "longevity_year": ("1.0", True)})},
        {"tag": tag, "states": _sched_states(P, "pilot", DOH, {**flagged, "longevity_year": ("5.0", False)})},
        {"tag": tag, "states": _sched_states(P, "pilot", DOH, {"federal_tax_pct": ("22.0", False),
                                                               "state_tax_pct": ("0.0", False)})},
        {"tag": tag, "states": _sched_states(P, "pilot", "", flagged)}])
    r8, r5, r1 = (f"Rate ${PAY.rate_for(y, TODAY):.2f}/credit h" for y in (8, 5, 1))
    assert by_doh["ubn"] == ("Set your tax and longevity in Pay settings (below): federal tax, state tax are not set "
                             "yet; pay is estimated with them as shown.")  # longevity no longer asked for
    assert by_doh["rate"].startswith(r8) and f"year 8 (DOH {DOH} = year 8, table caps at 12)" in by_doh["rate"]
    assert by_doh["ly"] == "8" and by_doh["wide"] <= 390
    assert by_doh["calls"] == [[f"input_number.{P}_federal_tax_pct", 0], [f"input_number.{P}_state_tax_pct", 0]]
    assert ly_only["ubn"] is None and not ly_only["keep"] and ly_only["rate"].startswith(r8)
    assert chosen["rate"].startswith(r5) and f"year 5 (DOH {DOH} = year 8" in chosen["rate"] and chosen["ly"] == "5"
    assert none["ubn"] is None and none["rate"].startswith(r8)
    # no DOH: 1.6.2's flagged year 1 and banner, unchanged
    assert no_doh["rate"].startswith(r1) and "federal tax, state tax, longevity year are not set yet" in no_doh["ubn"]
    assert [c[0] for c in no_doh["calls"]] == [f"input_number.{P}_{k}" for k in
                                              ("federal_tax_pct", "state_tax_pct", "longevity_year")]


def test_the_admins_schedule_card_figures_are_unchanged():
    """His own longevity helper when set, else his DOH's year (both made up here), the same rate line as 1.6.3."""
    tag, P, doh = "flight-watcher-schedule-card", "flight_watcher", "2021-12-01"
    pay = {"federal_tax_pct": ("24.0", False), "state_tax_pct": ("7.25", False)}
    helper, by_doh = _sched_run(_src("schedule-card"), [
        {"tag": tag, "states": _sched_states(P, "admin", doh, {**pay, "longevity_year": ("6.0", False)})},
        {"tag": tag, "states": _sched_states(P, "admin", doh, pay)}])
    assert helper["rate"] == (f"Rate ${PAY.rate_for(6, TODAY):.2f}/credit h: A330 PAX FO, PWA 3.D.6, year 6 (DOH "
                              f"{doh} = year 5, table caps at 12), effective 2026-03-02. Net = gross less federal and "
                              "state only; estimate.")
    assert by_doh["rate"].startswith(f"Rate ${PAY.rate_for(5, TODAY):.2f}/credit h") and "year 5 (DOH" in by_doh["rate"]
    assert helper["ubn"] is None and by_doh["ubn"] is None and helper["ly"] == "6" and by_doh["ly"] == "5"


# ---------------------------------------------------------------- the pot card's Value
POT_JS = """(h) => { const c = document.createElement(h.tag); c.setConfig({}); document.body.appendChild(c);
  c.hass = {states: h.states, callService: () => {}};
  const t = c.shadowRoot.textContent; c.remove(); return t; }"""


def test_the_pot_cards_value_follows_the_doh_too():
    sync_api = pytest.importorskip("playwright.sync_api")
    P, tag = "flight_watcher_james", "flight-watcher-pot-card-james"
    pot = {"pairings": [{"pairing": "H9001", "dates": "20NOV-22NOV", "credit": "15:00", "fit": "Fits", "far": "OK"}]}

    def states(doh, ly, flag):
        return {f"sensor.{P}_pot_count": {"state": "1", "last_updated": "a", "attributes": pot},
                f"sensor.{P}_state": {"state": "idle", "last_updated": "a",
                                      "attributes": {"role": "pilot", "doh": doh}},
                f"input_number.{P}_longevity_year": {"state": ly, "last_updated": "a",
                                                     "attributes": {"unconfirmed": True} if flag else {}}}
    src = cards.pilot_copy(_src("pot-card"), "james")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time(NOW_UTC)
            pg.set_content(_settings_page(src))
            by_doh, chosen, no_doh = (pg.evaluate(POT_JS, {"tag": tag, "states": s}) for s in (
                states(DOH, "1.0", True), states(DOH, "5.0", False), states("", "1.0", True)))
        finally:
            b.close()
    assert f"Value = credit x ${PAY.rate_for(8, TODAY):.2f}/h (PWA 3.D.6, longevity year 8)." in by_doh
    assert f"${round(15 * PAY.rate_for(8, TODAY)):,}" in by_doh
    assert "longevity year 5)." in chosen
    assert "longevity year 1, not confirmed yet" in no_doh  # no DOH: 1.6.2's wording, unchanged


# ---------------------------------------------------------------- the portal contract stays as it is
def test_the_portal_contract_files_are_unchanged():
    raw = open(FIXTURE, "rb").read()
    assert hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256 and PT.contract_text().encode("utf-8") == raw
    assert hashlib.sha256(open(DOC, "rb").read()).hexdigest() == CONTRACT_DOC_SHA256
    assert "settings/set" in roles.PORTAL_CMDS and not [s for s in roles.PORTAL_CMDS if "doh" in s]
    # the settings card still publishes to settings/set only, so the manifest's mqtt_subs stay the same
    built = cards.build("1.6.4", ["pilot2"])
    assert PT.card_subs(built["flight-watcher-settings-card-pilot2.js"], "flight_watcher_pilot2") == {"settings/set"}


def test_no_real_doh_and_no_em_dash_in_what_ships():
    for n in ("settings-card", "schedule-card", "pot-card"):
        s = _src(n)
        assert chr(0x2014) not in s
        assert 'DOH = "2000-01-01"' in s or n != "schedule-card"  # the placeholder only (FW-0010)
    assert chr(0x2014) not in open(__file__, encoding="utf-8").read()

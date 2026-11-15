"""1.7.9 (F#92; Ryan, Nov 14: "the Re-arm confirm names the state"): the clock card's Re-arm confirm, and the
button's tooltip, name the state the Watcher is in and what Re-arm does there, as the Watcher's own rearm_answer
does: stuck, a full check now with no new FLICA login; stepped aside, a login when the step-aside ends; reconnecting,
a login at the next login try; stopped, one FLICA login, with the stop's note. Declined, nothing is sent. The same
words on the portal's copy. Synthetic states only."""
import json

import portal as PT
from test_release_a_cards import _clock_states, _run, _src, _st

REARM_JS = """(h, yes) => { const asked = []; window.confirm = (m) => { asked.push(m); return yes; };
  const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: (d, s, data) => window.calls.push([d, s, data])};
  const b = c.shadowRoot.getElementById('rearm'); const shown = b.style.display !== 'none'; if (shown) b.click();
  return {shown, asked, title: b.title, calls: window.calls}; }"""


def _case(st, note="", last="2026-11-10T11:29:30+00:00"):
    h = _clock_states(st=st)
    h["sensor.flight_watcher_state"] = _st(st, {"note": note, "role": "pilot"})
    h["sensor.flight_watcher_last_check"] = _st(last)
    return h


def test_the_rearm_confirm_names_the_state_and_what_rearm_does():
    cases = {
        "stuck": _case("idle", last="2026-11-10T10:00:00+00:00"),
        "yielded": _case("yielded", "stepped aside until 01:55 HST"),
        "backoff": _case("backoff", "login failed, next try 01:40 HST"),
        "failed": _case("stopped_login_failed", "FLICA showed a CAPTCHA page on the main menu (never answered)."),
        "stopped": _case("stopped_unexpected", "pot page did not parse"),
    }
    for src in (_src("clock-card"), PT.portal_card(_src("clock-card"))):
        got = _run([(k, f"({REARM_JS})({json.dumps(h)}, true)") for k, h in cases.items()]
                   + [("no", f"({REARM_JS})({json.dumps(cases['stopped'])}, false)"),
                      ("fine", f"({REARM_JS})({json.dumps(_case('idle'))}, true)")], src)
        says = {k: v["asked"][0] for k, v in got.items() if v["asked"]}
        assert says["stuck"] == ("The Watcher is stuck: no check for 1 h 30 min. Re-arm starts a full check now, with no "
                                 "new FLICA login.\n\nRe-arm the Watcher now?")
        assert says["yielded"].startswith("The Watcher stepped aside for your own FLICA login. Re-arm logs into FLICA "
                                          "once when the step-aside ends, not before.")
        assert says["backoff"].startswith("The Watcher is reconnecting to FLICA. Re-arm logs in at its next login try.")
        assert says["failed"].startswith("The Watcher is stopped: the FLICA login failed (FLICA showed a CAPTCHA page on "
                                         "the main menu (never answered)). Re-arm logs into FLICA once with the saved login.")
        assert says["stopped"].startswith("The Watcher is stopped (pot page did not parse). Re-arm logs into FLICA once "
                                          "and resumes.")
        for k in cases:  # asked once, the tooltip says the same, and a yes presses Re-arm once
            assert got[k]["shown"] and len(got[k]["asked"]) == 1 and says[k].startswith(got[k]["title"]), k
            assert got[k]["calls"] == [["button", "press", {"entity_id": "button.flight_watcher_re_arm"}]], k
        assert got["no"]["asked"] and got["no"]["calls"] == []  # declined: nothing sent
        assert not got["fine"]["shown"] and got["fine"]["asked"] == []  # watching normally: no Re-arm to press

"""1.4.6 (Ryan, Nov 6): the Recall / Over 75 card. RECALL ALERT bar (tab and alert mode), day folds (closed by default
unless a row is MISSED / POSSIBLE, remembered in localStorage, still working when storage is blocked), the Hark states
and the "Have Hark file this CCR" button, escaping, and no sideways scroll at 390 px. In Chromium through node
Playwright (tests/recall_card_render.js); made-up data only."""
import json
import os
import shutil
import subprocess

import pytest

import cards

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-recall-card.js")


def test_card_syntax_and_second_pilot_copy():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    assert subprocess.run(["node", "--check", CARD], capture_output=True).returncode == 0
    src = open(CARD, encoding="utf-8").read()
    j = cards.pilot_copy(src, "james")
    assert "flight_watcher/recall/act" not in j and "`flight_watcher_james/${topic}`" in j
    assert '"flight_watcher_james_recall_fold"' in j and '"/flight-watcher-james/recall"' in j
    assert 'customElements.define("flight-watcher-recall-card-james"' in j and "Ryan" not in j


def test_renders_at_390_px(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    shots = os.environ.get("FW_RECALL_SHOTS") or str(tmp_path)
    out = subprocess.run(["node", os.path.join(HERE, "recall_card_render.js"), CARD, shots],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    tab, al = r["tab"], r["alert"]
    lines = ["Tue Nov 10 Recall H3601 went to #900 approved", "Fri Nov 6 Recall H3606 went to #900 sent to Hark",
             "Thu Nov 5 Recall H3607 went to #900 Hark blocked"]  # MISSED with an open act; the filed one is not here
    assert tab["bar"]["head"].startswith("RECALL ALERT") and tab["bar"]["lines"] == lines and tab["bar"]["first"]
    assert not tab["bar"]["jump"] and al["bar"]["jump"] and al["bar"]["lines"] == lines and al["bar"]["first"]
    assert r["quiet"] == ""  # alert mode with nothing to alert draws nothing
    assert tab["open"] == {"2026-11-10": True, "2026-11-09": False, "2026-11-08": False, "2026-11-07": False,
                           "2026-11-06": True, "2026-11-05": True, "2026-11-04": True}
    assert json.loads(r["after_toggle"]) == {"2026-11-09": True, "2026-11-10": False}
    assert r["reloaded"]["2026-11-09"] is True and r["reloaded"]["2026-11-10"] is False
    assert r["goday"] is True  # a tap on an alert line opens its day
    assert r["nostore"]["open"] == tab["open"] and r["nostore"]["bar"] == 3 and r["nostore"]["after"] is True
    assert tab["hark"] == ["2026-11-10|H3601|recall", "2026-11-05|H3607|recall"]  # approved, and blocked after approval
    assert tab["manual"] == ["2026-11-10|H3601|recall", "2026-11-06|H3606|recall", "2026-11-05|H3607|recall"]
    hk = tab["hk"]
    assert hk[0] == "Sent to Hark Nov 6 09:52 HST, waiting for the CCR number (HOM task T-42). To stop it, cancel the task in HOM."
    assert hk[1].startswith("Hark blocked Nov 5 10:30 HST: hal.alpa.org asked for a login <img")
    assert hk[2] == "Filed: CCR 12345 by Hark Nov 4 15:15 HST"
    assert r["sent"] == [{"d": "mqtt", "s": "publish", "topic": "flight_watcher/recall/act",
                          "payload": {"id": "2026-11-05|H3607|recall", "action": "file_request"}}]
    assert r["hark_btn"] == "Sending to Hark..." and r["opened"] == ["https://hal.alpa.org"]
    for st in (tab, al):
        assert st["imgs"] == 0 and st["pwned"] is None
        m = st["fit"]
        assert m["doc"] <= m["win"] == 390 and m["card"] <= 390.5 and m["inner"] <= 0, m
    for name in r["shots"]:
        assert os.path.getsize(os.path.join(shots, name)) > 1000

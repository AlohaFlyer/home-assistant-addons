"""1.7.23 (Hark, Ryan Nov 21, 2026): CrewTrac controls. A delayed trip whose FLICA credit CrewTrac books as well (a
reassignment with the original leg protected, NF2, PWA 4.D.2.b), or one marked 'K+PID|start', keeps FLICA's credit:
no delay cut. LODO is unchanged. pay.pwa_trip and the card's fwPwaTrip agree. Made-up crew only."""
import json
import shutil

import pytest

import pay as PAY
from test_fw1720_pay_engine import DET, OT, _node

FL = 32 * 60 + 19


def test_crewtrac_booking_keeps_flica_credit():
    cut = PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: True)
    assert cut["fix"] and cut["use"] < FL and cut["kept"] == ""
    pa = PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: True, ct=FL)
    assert not pa["fix"] and pa["use"] == FL and pa["cut"] == 0 and pa["kept"] == "ct"
    assert pa["lodo_days"] == ["2026-11-21"] and pa["lodo"] == 240  # LODO 4:00 pay still due (4.D.2.e)
    assert PAY.pwa_trip("2026-11-18", OT, DET, 2, ct=FL + 1)["kept"] == "ct"  # within 0:01
    # CrewTrac at the cut figure (it agrees with the delay math): the cut stands
    assert PAY.pwa_trip("2026-11-18", OT, DET, 2, ct=cut["use"])["fix"]


def test_mark_keeps_flica_credit():
    er = ["+H3815B|2026-11-01", "K+H3606B|2026-11-18"]
    assert PAY.keep_of(er, "H3606B|2026-11-18") and not PAY.keep_of(er, "H3606B|2026-11-19")
    pa = PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: True, keep=True)
    assert not pa["fix"] and pa["use"] == FL and pa["kept"] == "mark" and pa["lodo"] == 240


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_card_matches_pay_py(tmp_path):
    js = ("const r = [];"
          f"for (const o of [{{}}, {{ct: {FL}}}, {{keep: true}}, {{ct: 1000}}]) {{ const p = fwPwaTrip({{start: '2026-11-18', ot: {json.dumps(OT)}, "
          f"pr: {{det: {json.dumps(DET)}, relDays: 2}}, isOff: () => true, ...o}}); r.push([p.use, p.fix, p.kept, p.lodo]); }}"
          "console.log(JSON.stringify(r));")
    got = _node(js, tmp_path)
    want = []
    for kw in ({}, {"ct": FL}, {"keep": True}, {"ct": 1000}):
        p = PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: True, **kw)
        want.append([p["use"], p["fix"], p["kept"], p["lodo"]])
    assert got == want
    assert got[1] == [FL, False, "ct", 240]

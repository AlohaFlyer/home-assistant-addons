"""1.7.25 (Hark, Ryan's override of Nov 22, 2026): ALPA's delay ruling as a general rule (DART 417120, HAL ALPA Paycheck
Issues, closed Nov 22, 2026, on H3606A/B). A delayed leg whose duty was BROKEN (the pilot reported, was released, then
re-reported for the same flight on a later duty period) is credited twice: the original duty at its scheduled credit
(PWA 4.C.3.a pay protection) and the re-reported operation as its own duty period (4.B.1), so the 1.7.20 delay cut
(2.A.15.a.1, one segment) is not made; LODO 4:00 pay, no credit, when the release lands on a day off (4.D.2.e). A
continuous delay (held on one duty) keeps the 1.7.20 cut. pay.pwa_trip and the card's fwPwaTrip agree. Made-up crew."""
import json
import shutil

import pytest

import pay as PAY
from test_fw1720_pay_engine import DET, OT, OT_C, _node

FL = 32 * 60 + 19

# H3606B as FW holds it on Pako (FLICA own trip times, Nov 22, 2026; crew made up) and its pairings package entry
# (scheduled report 07:25 EST for AS829 08:40 EST Nov 20): reported 07:25, released, re-reported 21:30, out 23:20 EST,
# in 05:26 HST Nov 21 (a scheduled day off)
H_OT = {"report": "14:45", "last_arr": "05:26", "blk": "20:50", "credit": "32:19", "soft": "11:29", "seat": "FO",
        "crew": ["CA Doe, John (1001)", "FO Roe, Jane (1002)", "RO Poe, Jim (1003)"],
        "duties": [{"d": 0, "dep": 947, "arr": 1531, "stn": "JFK", "blk": 584},
                   {"d": 2, "dep": 3980, "arr": 4646, "stn": "HNL", "blk": 666}]}
H_DET = {"crew": "CA01FO01RO01", "rept": "14:45", "duties": [
    {"legs": [["1", "", "830", "HNL", "JFK", "15:45", "06:30", "9h45", "9:45", "", "332"]], "rept": "14:45", "stn": "JFK",
     "tblk": "9h45", "tcrd": "9h45"},
    {"legs": [["3", "", "829", "JFK", "HNL", "08:40", "14:55", "11h15", "11:15", "", "332"]], "rept": "07:25", "stn": "HNL",
     "tblk": "11h15", "tcrd": "11h15"}]}
# CrewTrac's H3606B (compact snapshot as posted to HA, and the full one)
CT_COMPACT = {"pairing": "H3606B", "key": "H3606", "start": "2026-11-18", "credit": "32:19", "block": "20:50",
              "codes": ["DHD", "FLT", "NF2", "PO3"],
              "legs": ["0830 HNL-JFK 11-18", "NF2 DH JFK-JFK 11-20", "0829 JFK-HNL 11-20"],
              "duties": [{"date": "2026-11-18", "blkt": "9:44", "tcrd": "9:49"}, {"date": "2026-11-20", "blkt": "0:00", "tcrd": "11:15"},
                         {"date": "2026-11-20", "blkt": "11:06", "tcrd": "11:15"}]}
CT_FULL = dict(CT_COMPACT, legs=[{"date": "2026-11-18", "flt": "0830"}, {"date": "2026-11-20", "flt": "NF2", "dh": True},
                                 {"date": "2026-11-20", "flt": "0829"}])


def test_h3606b_without_the_mark_is_32_19_with_lodo():
    pa = PAY.pwa_trip("2026-11-18", H_OT, H_DET, 2, lambda iso: iso == "2026-11-21")
    assert pa["brk"] == "duty" and pa["prot"] == 11 * 60 + 15 and not pa["fix"] and pa["cut"] == 0 and pa["kept"] == ""
    assert pa["brk_span"] == 4646 + 15 - (3100 - 75) and pa["brk_max"] == 18 * 60 and pa["n"] == 3  # 27:16 over 18:00
    assert pa["use"] == FL  # 9:49 + 11:15 + 11:15, the company's (FLICA, CrewTrac) and ALPA's figure
    assert pa["gop"] == 9 * 60 + 45 + 11 * 60 + 15 + 11 * 60 + 15 and pa["won"] == "gop"  # PWA check 32:15 (package 9:45)
    assert pa["lodo_days"] == ["2026-11-21"] and pa["lodo"] == 240  # one LODO, pay only (4.D.2.e)
    # Nov 21 not a day off: no LODO; the credit stands
    pb = PAY.pwa_trip("2026-11-18", H_OT, H_DET, 2, lambda iso: False)
    assert pb["lodo"] == 0 and pb["use"] == FL
    # the mark and CrewTrac still keep it (1.7.23), and give one LODO, not two
    pk = PAY.pwa_trip("2026-11-18", H_OT, H_DET, 2, lambda iso: True, keep=True, ct=FL, ctp=675)
    assert pk["use"] == FL and pk["kept"] == "mark" and pk["brk"] == "ct" and pk["lodo"] == 240


def test_crewtrac_nf2_marks_the_break():
    assert PAY.ct_protected(CT_COMPACT) == 675 and PAY.ct_protected(CT_FULL) == 675
    plain = dict(CT_COMPACT, codes=["FLT", "DHD"], legs=["0830 HNL-JFK 11-18", "0831 DH JFK-HNL 11-20"])
    assert PAY.ct_protected(plain) is None  # a deadhead duty with no block is not a protected NF2 duty
    last = dict(CT_COMPACT, duties=CT_COMPACT["duties"][:2])
    assert PAY.ct_protected(last) is None  # nothing flown after it: no re-report
    assert PAY.ct_protected(None) is None
    # CrewTrac's NF2 alone (a delay the duty limit would not show) breaks it: the CrewTrac credit is the protected one
    pa = PAY.pwa_trip("2026-11-18", OT_C, DET, 2, lambda iso: True, ctp=675)
    assert pa["brk"] == "ct" and pa["prot"] == 675 and not pa["fix"] and pa["use"] == FL


def test_continuous_delay_keeps_the_1720_cut():
    pa = PAY.pwa_trip("2026-11-18", OT_C, DET, 2, lambda iso: True)
    assert pa["brk"] == "" and pa["fix"] and pa["use"] == 9 * 60 + 45 + 11 * 60 + 24 and pa["prot"] == 0
    # the same span on a 2-pilot crew is over the 16:00 PWA 10.D.1.a Maximum only when it really is
    two = json.loads(json.dumps(DET))
    two["crew"] = "CA01FO01"
    ot2 = json.loads(json.dumps(OT_C))
    ot2["crew"] = ["CA Doe, John (1001)", "FO Roe, Jane (1002)"]
    assert PAY.pwa_trip("2026-11-18", ot2, two, 2)["brk"] == ""  # 14:54, held on one duty
    ot3 = json.loads(json.dumps(ot2))
    ot3["duties"][1].update({"dep": 3220 + 150, "arr": 3904 + 150})  # 17:24 report to release: > 16:00, < 18:00
    p2 = PAY.pwa_trip("2026-11-18", ot3, two, 2)
    assert p2["brk"] == "duty" and p2["brk_max"] == 16 * 60 and not p2["fix"]
    ot3["crew"] = OT["crew"]
    assert PAY.pwa_trip("2026-11-18", ot3, DET, 2)["brk"] == ""  # a 3-pilot crew can be held 18:00
    # a leg 24 h or more late stays a reassignment (FLICA kept), never a broken duty
    late = json.loads(json.dumps(OT))
    late["duties"][1]["dep"] += 1440
    late["duties"][1]["arr"] += 1440
    assert PAY.pwa_trip("2026-11-18", late, DET, 2)["brk"] == ""


def test_rep_lead():
    assert PAY.rep_lead(H_DET["duties"][1]) == 75 and PAY.rep_lead(DET["duties"][1]) == 60 and PAY.rep_lead(None) == 60


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_card_matches_pay_py(tmp_path):
    cases = [("2026-11-18", H_OT, H_DET, {}), ("2026-11-18", H_OT, H_DET, {"keep": True, "ct": FL, "ctp": 675}),
             ("2026-11-18", OT, DET, {}), ("2026-11-18", OT_C, DET, {}), ("2026-11-18", OT_C, DET, {"ctp": 675}),
             ("2026-11-18", OT_C, dict(DET, crew="CA01FO01"), {})]
    js = "const r = [];"
    for st, ot, det, kw in cases:
        js += (f"{{ const p = fwPwaTrip({{start: '{st}', ot: {json.dumps(ot)}, pr: {{det: {json.dumps(det)}, relDays: 2}}, "
               f"isOff: () => true, ...{json.dumps(kw)}}}); r.push([p.use, p.fix, p.kept, p.lodo, p.brk, p.prot, p.brkSpan, p.pwa, p.gop]); }}")
    js += (f"r.push([fwCtProt({json.dumps(CT_COMPACT)}), fwCtProt({json.dumps(CT_FULL)}), fwRepLead({json.dumps(H_DET['duties'][1])})]);"
           "console.log(JSON.stringify(r));")
    got = _node(js, tmp_path)
    want = []
    for st, ot, det, kw in cases:
        p = PAY.pwa_trip(st, ot, det, 2, lambda iso: True, **kw)
        want.append([p["use"], p["fix"], p["kept"], p["lodo"], p["brk"], p["prot"], p["brk_span"], p["pwa"], p["gop"]])
    want.append([675, 675, 75])
    assert got == want
    assert got[0][:5] == [FL, False, "", 240, "duty"]


def test_check_sensor_card_view_carries_the_protected_credit():
    import crewtrac as CTR
    v = CTR.card_view({"pulled_at": "2026-11-22T10:00:00-08:00", "months": {}, "trips": [CT_COMPACT, dict(CT_COMPACT, key="H3815",
                       pairing="H3815B", codes=["FLT"], legs=["9981 HNL-SIN 11-01"])]})
    assert v["trips"][0]["prot"] == "11:15" and "prot" not in v["trips"][1]

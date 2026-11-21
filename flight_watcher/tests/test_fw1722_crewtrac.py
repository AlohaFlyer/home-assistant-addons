"""1.7.22 (Hark, Ryan Nov 20, 2026, option 1): the CrewTrac per-trip pay check (crewtrac.py, the Watcher's
crewtrac_check, the schedule card's fwCt*). SYNTHESIZED reports in the layout pdftotext -layout prints from CTWeb's
printer friendly PDFs: made-up pilot, pairings and numbers only (real CrewTrac pages never go in git)."""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

import crewtrac as CT

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js")
L, R = 71, 7  # the right column starts at 71; an extra duty on the same day is indented 7 more


def two_col(left, right):
    n = max(len(left), len(right))
    left, right = left + [""] * (n - len(left)), right + [""] * (n - len(right))
    return "\n".join((a.ljust(L) + b).rstrip() if b else a for a, b in zip(left, right))


HEAD = ["                                                   Schedule Detail Report", "",
        "                                   1234 DOE,JANE SEN# 00999 BID HNL 332 FO",
        "                                            PERIOD 0327 TIMES ARE IN LOCAL", ""]
SD_MAR = "\n".join(HEAD) + "\n" + two_col([
    "01 MAR H9815B/0301 POS RO DAY 01 REPORT 0400",
    "9981 HNL SIN 0520 1241",
    "D-END 1256/02 BLKT 1321 TCRD 1330",
    "TDTY 1456 LYOV 4604 SIN",
    "Made Up Hotel Changi      (011)000-0000000",
    "",
    "02 MAR OFF",
    "",
    "04 MAR H9815B/0301 POS RO DAY 02 REPORT 1100",
    "9980 SIN HNL 1218 0808",
    "D-END 0838    BLKT 1350 TCRD 1350",
    "TDTY 1538",
    "",
    "06 MAR H9620 /0306 POS FO DAY 01 REPORT 2245",
    "0808 HNL LAS 2342 0735",
    "D-END 0750/07 BLKT 0553 TCRD 0557",
    "",
    "08 MAR H9620 /0306 POS FO DAY 02 REPORT 0545",
    "0875 LAS HNL 0704 1135",
    "D-END 1150    BLKT 0631 TCRD 0637",
    "       PAYP 2245 2400    TCRD 0542",
    "",
    "09 MAR PAYP 0001 1152              TCRD 0918  Copyright (c) 1999-2027 Sabre Inc. All Rights Reserved.",
], [
    "20 MAR H9606B/0318 POS FO DAY 02 REPORT 0725",
    "NF2 JFK JFK 0725 0923 DHD",
    "D-END 0923    BLKT 0000 TCRD 1115",
    "TDTY 0158 LYOV 1207 JFK",
    " " * R + "H9606B/0318 POS FO DAY 03 REPORT 2130",
    "0829 JFK HNL 2245 0509",
    "D-END 0524/21 BLKT 1124 TCRD 1115",
    "",
    "22 MAR VAC       0001 2400   TCRD 0400",
    "",
    "30 MAR H9607 /0330 POS FO DAY 01 REPORT 1245",
    "0849 HNL KIX 1345 1845",
    "D-END 1915/01 BLKT 1000 TCRD 1000",
    "PAIRING ENDS IN NEXT BID PERIOD",
    "",
    "18 MAR H9606B/0318 POS FO DAY 01 REPORT 1445",
    "0830 HNL JFK 1547 0631",
    "D-END 0646/19 BLKT 0944 TCRD 0949",
])
SD_APR = "\n".join(h.replace("0327", "0427") for h in HEAD) + "\n" + "\n".join([
    "PAIRING STARTED IN PREVIOUS BID PERIOD",
    "01 APR H9607 /0330 POS FO DAY 02 REPORT 1930",
    "0850 KIX HNL 2045 0920",
    "D-END 0950    BLKT 0735 TCRD 0735",
    "",
    "03 APR H9665 /0403 POS FO DAY 01 REPORT 2200",
    "0900 HNL SEA 2300 0642",
    "D-END 0657/04 BLKT 0542 TCRD 0542",
    "",
    "05 APR H9665 /0403 POS FO DAY 02 REPORT 1715",
    "0941 SEA HNL 1830 2255",
    "D-END 2310    BLKT 0625 TCRD 0625",
])

PH1 = "              ACTIVE                     ZULU                                        FLT            PAY         CREDIT    ACTUAL           -- DEPART ---"
PH2 = "NAME           DATE     EQP   POS        DATE         FLT#   FR   TO     CODE       HOURS          HOURS        HOURS  CREDIT HOURS         DATE    OUT"


def prow(act, pos, zulu, flt, code, flt_h="", pay="", credit="", actual=""):
    s = f"            {act}    332   {pos}    {zulu}      {flt:<20s}{code}"
    s = s.ljust(PH2.index("CODE") + 4)
    for col, v in (("flt", flt_h), ("pay", pay), ("credit", credit), ("actual", actual)):
        end = {"flt": PH2.index("HOURS") + 5, "pay": PH2.index("HOURS", PH2.index("HOURS") + 5) + 5,
               "credit": PH2.index("HOURS", PH2.index("HOURS", PH2.index("HOURS") + 5) + 5) + 5,
               "actual": PH2.rindex("HOURS") + 5}[col]
        if v:
            s = s.ljust(end - len(v)) + v
    return s


PAY_MAR = "\n".join([
    "       Date: 03/20/27                    HAWAIIAN AIRLINES PILOTS", "                                    As Of 04/01/27", "", PH1, PH2, "",
    "       DOE,JANE           332   FO     BID          1234", "",
    prow("03/01/27", "RO", "03/01/27", "9981 HNL SIN", "FLT", "13:21", "13:30", "13:30", "13:27"),
    prow("03/01/27", "RO", "03/01/27", "", "MNN"),
    prow("03/04/27", "RO", "03/04/27", "9980 SIN HNL", "FLT", "13:50", "13:50", "13:50", "13:50"),
    prow("03/06/27", "FO", "03/07/27", "0808 HNL LAS", "FLT", "5:53", "5:57", "5:57", "5:57"),
    prow("03/08/27", "FO", "03/08/27", "0875 LAS HNL", "FLT", "6:31", "6:37", "6:37", "6:36"),
    prow("03/08/27", "FO", "03/08/27", "", "MFG", "", "2:26", "2:26"),
    prow("03/08/27", "FO", "03/09/27", "", "NF5", "", "5:42", "5:42"),
    prow("03/09/27", "FO", "03/09/27", "", "NF5", "", "9:18", "9:18"),
    prow("03/18/27", "FO", "03/19/27", "0830 HNL JFK", "FLT", "9:44", "9:49", "9:49", "9:49"),
    prow("03/18/27", "FO", "03/19/27", "0830 HNL JFK", "PO3", "", "9:49"),
    prow("03/20/27", "FO", "03/20/27", "NF2 JFK JFK", "NF2", "", "11:15", "11:15"),
    prow("03/20/27", "FO", "03/20/27", "0829 JFK HNL", "FLT", "11:24", "11:15", "11:15"),
    prow("03/22/27", "FO", "03/22/27", "", "VC1", "", "4:00", "4:00"),
    prow("03/30/27", "FO", "03/30/27", "0849 HNL KIX", "FLT", "10:00", "10:00", "10:00"),
    "", " " * 36 + "EMPLOYEE TOTALS" + prow("", "", "", "", "", "70:43", "113:28", "103:39", "49:39")[51:],
    "                                                                  Copyright (c) 1999-2027 Sabre Inc. All Rights Reserved. www.sabre.com",
])
PULLED = "2027-03-20T14:22:00-10:00"
NOW = datetime(2027, 3, 21, 1, 0, tzinfo=timezone.utc)  # 0.6 h after PULLED


def snap():
    return CT.build_snapshot([CT.parse_schedule_detail(SD_MAR), CT.parse_schedule_detail(SD_APR)],
                             {"2027-03": CT.parse_pay_report(PAY_MAR)}, PULLED)


def test_pay_report_columns_add_up():
    pr = CT.parse_pay_report(PAY_MAR)
    assert pr["as_of"] == "2027-04-01" and len(pr["rows"]) == 14
    r0 = pr["rows"][0]
    assert (r0["flt"], r0["fr"], r0["to"], r0["code"], r0["flt_h"], r0["pay"], r0["credit"], r0["actual"]) == \
        ("9981", "HNL", "SIN", "FLT", "13:21", "13:30", "13:30", "13:27")
    po = next(r for r in pr["rows"] if r["code"] == "PO3")
    assert po["pay"] == "9:49" and "credit" not in po  # an override row is pay only
    assert pr["sums"]["credit"] == "103:39" and pr["totals"]["credit"] == "103:39"
    assert pr["sums"]["pay"] == pr["totals"]["pay"] and pr["sums"]["flt_h"] == pr["totals"]["flt_h"]


def test_schedule_detail_two_columns_and_trip_credit():
    sd = CT.parse_schedule_detail(SD_MAR)
    assert sd["month"] == "2027-03" and sd["bid"] == "HNL 332 FO"
    assert [c["code"] for c in sd["codes"]] == ["OFF", "PAYP", "PAYP", "VAC"]
    s = snap()
    t = {f"{x['pairing']}|{x['start']}": x for x in s["trips"]}
    assert set(t) == {"H9815B|2027-03-01", "H9620|2027-03-06", "H9606B|2027-03-18", "H9607|2027-03-30", "H9665|2027-04-03"}
    assert (t["H9815B|2027-03-01"]["credit"], t["H9815B|2027-03-01"]["block"], t["H9815B|2027-03-01"]["seat"]) == ("27:20", "27:11", "RO")
    # a trip's minimum guarantee row (MFG) is part of its credit; the PAYP days (NF5) are not
    assert (t["H9620|2027-03-06"]["tcrd"], t["H9620|2027-03-06"]["min_guar"], t["H9620|2027-03-06"]["credit"]) == ("12:34", "2:26", "15:00")
    # the protected segment (NF2) is paid and credited beside the flown leg, as CrewTrac counts it
    h = t["H9606B|2027-03-18"]
    assert (h["credit"], h["block"], h["pay_report_credit"], h["end"]) == ("32:19", "21:08", "32:19", "2027-03-21")
    assert "NF2" in h["codes"] and "DHD" in h["codes"] and len(h["legs"]) == 3
    # a trip over two bid periods is one trip; not flown yet, under the MDG: projected and marked
    assert (t["H9607|2027-03-30"]["credit"], t["H9607|2027-03-30"]["months"]) == ("17:35", ["2027-03", "2027-04"])
    assert t["H9665|2027-04-03"]["credit"] == "15:00" and "MDG" in t["H9665|2027-04-03"]["projected"]


def test_compact_is_small_and_idempotent():
    c = CT.compact(snap())
    assert len(json.dumps(c, separators=(",", ":"))) < 12000
    assert c["months"]["2027-03"]["pay_report"]["totals"]["credit"] == "103:39" and "rows" not in c["months"]["2027-03"]["pay_report"]
    assert CT.compact(c) == c


def test_compare_lines_and_snapshot_age():
    s = CT.compact(snap())
    fw = {"H9815A|2027-03-01": {"credit": "27:20", "blk": "27:11"}, "H9606A|2027-03-18": {"credit": "21:09", "blk": "21:08"},
          "H9620|2027-03-07": {"credit": "15:00", "blk": "12:24"}, "H9999|2027-03-12": {"credit": "10:00", "blk": "9:00"},
          "PAYP|2027-03-08": {"credit": "15:00"}, "H9001|2027-06-01": {"credit": "9:00"}}
    r = CT.compare_trips(s, fw, NOW)
    rows = {x["trip"] + "|" + x["start"]: x for x in r["rows"]}
    assert r["status"] == "ok" and set(rows) == {"H9815A|2027-03-01", "H9606A|2027-03-18", "H9620|2027-03-07", "H9999|2027-03-12"}
    assert rows["H9815A|2027-03-01"]["line"] == "CrewTrac 27:20, FW 27:20 \u2713"  # FLICA's letter differs, same trip
    assert rows["H9620|2027-03-07"]["ok"]  # one day off (a late evening report): the same trip
    assert rows["H9606A|2027-03-18"]["line"] == "CrewTrac 32:19, FW 21:09 \u2717 credit off by -11:10 (CrewTrac controls)"
    assert not rows["H9999|2027-03-12"]["ok"] and r["mismatches"] == 2
    one = CT.compare_trip({"credit": "10:00", "block": "9:00"}, "10:01", "9:00")
    assert not one["ok"] and one["d_credit"] == 1  # 0:01 is a mismatch
    assert CT.month_line(s, "2027-03", "103:39").endswith("\u2713")
    assert CT.month_line(s, "2027-03", "92:29").endswith("off by -11:10 (CrewTrac controls)")
    late = datetime(2027, 3, 22, 13, 0, tzinfo=timezone.utc)
    st = CT.compare_trips(s, fw, late)
    assert st["status"] == "stale" and st["line"] == "CrewTrac not compared (snapshot 37 h old)" and not st["rows"]
    assert CT.compare_trips(None, fw, NOW)["line"] == "CrewTrac not compared (snapshot missing)"


def _node(js, tmp_path):
    src = open(CARD, encoding="utf-8").read()
    f = tmp_path / "t.mjs"
    f.write_text(src[:src.index("class FlightWatcherScheduleCard")].replace("customElements", "//") + "\n" + js)
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_card_and_crewtrac_py_agree(tmp_path):
    s = CT.compact(snap())
    now_ms = int(NOW.timestamp() * 1000)
    cases = [("H9815A", "2027-03-01", "27:20", "27:11"), ("H9606A", "2027-03-18", "21:09", "21:08"),
             ("H9620", "2027-03-07", "15:00", "12:24"), ("H9620", "2027-03-06", "15:00", "12:30"),
             ("H9999", "2027-03-12", "10:00", "9:00"), ("H9665", "2027-04-03", "15:00", "12:07")]
    js = f"const S = {json.dumps(s)}; const out = [];\n"
    for pid, st, cr, bl in cases:
        js += f"out.push(fwCtTrip(S, {json.dumps(pid)}, {json.dumps(st)}, {json.dumps(cr)}, {json.dumps(bl)}, {now_ms}));\n"
    js += (f"const m = [fwCtMonth(S, '2027-03', '92:29', {now_ms}), fwCtMonth(S, '2027-03', '103:39', {now_ms}), "
           f"fwCtMonth(S, '2027-03', '103:39', {now_ms + 40 * 3600e3}), fwCtMonth(null, '2027-03', '1:00', {now_ms})];\n"
           "console.log(JSON.stringify({out: out.map((o) => [o.ok, o.line]), m: m.map((o) => [o.ok, o.line])}));")
    got = _node(js, tmp_path)
    for (pid, st, cr, bl), (ok, line) in zip(cases, got["out"]):
        r = CT.compare_trips(s, {f"{pid}|{st}": {"credit": cr, "blk": bl}}, NOW)["rows"][0]
        assert (ok, line) == (r["ok"], r["line"])
    assert got["m"][0] == [False, CT.month_line(s, "2027-03", "92:29")]
    assert got["m"][1] == [True, CT.month_line(s, "2027-03", "103:39")]
    assert got["m"][2] == [None, "CrewTrac not compared (snapshot 41 h old)"]
    assert got["m"][3] == [None, "CrewTrac not compared (snapshot missing)"]


def test_card_draws_the_check_in_the_pay_tooltip():
    src = open(CARD, encoding="utf-8").read()
    assert "CrewTrac check: not compared by FW yet" not in src
    assert "fwCtTrip(ctSnap, trip, d, bcsAll[1], bcsAll[0], Date.now())" in src
    assert '(h.states["sensor.flight_watcher_crewtrac_check"] || {}).last_updated' in src and 'pay${ctT.ok === false ? " ctbad" : ""}' in src


def test_watcher_publishes_the_check(tmp_path, monkeypatch):
    from test_instance import _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info", "category_check": "HNL 332 FO"})
    snap_full = snap()
    monkeypatch.setattr(W, "CT_FILE", str(tmp_path / "share" / "crewtrac_snapshot.json"))
    monkeypatch.setattr(W, "ha_state_full", lambda e: (200, {"state": PULLED, "attributes": {**CT.compact(snap_full), "friendly_name": "x"}}))
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: None)
    sent = {}
    monkeypatch.setattr(W, "pub", lambda topic, payload, retain=True: sent.__setitem__(topic, payload))
    W.S["own_trips"] = {"H9815A|2027-03-01": {"credit": "27:20", "blk": "27:11", "seat": "RO"},
                        "H9606A|2027-03-18": {"credit": "32:19", "blk": "21:08", "seat": "FO"}}
    W.S["schedule"] = {"2027-03": {"totals": {"credit": "103:39"}}}
    W.crewtrac_check(NOW)
    p = sent["crewtrac_check"]
    assert p["status"] == "ok" and p["mismatches"] == 0 and len(p["rows"]) == 2 and p["months"][0]["ok"]
    assert p["rows"][0] == {"trip": "H9815A", "start": "2027-03-01", "ok": True}
    assert p["snapshot"]["pulled_at"] == PULLED and os.path.exists(W.CT_FILE)
    # HA restarted (the REST-posted state is gone): the kept copy is used
    monkeypatch.setattr(W, "ha_state_full", lambda e: (404, None))
    W.S["own_trips"]["H9606A|2027-03-18"]["credit"] = "21:09"
    W.crewtrac_check(NOW)
    p = sent["crewtrac_check"]
    assert p["status"] == "mismatch" and p["mismatches"] == 1
    assert [r["line"] for r in p["rows"] if not r["ok"]] == ["CrewTrac 32:19, FW 21:09 \u2717 credit off by -11:10 (CrewTrac controls)"]
    W.crewtrac_check(datetime(2027, 3, 23, tzinfo=timezone.utc))
    assert sent["crewtrac_check"]["status"] == "stale" and sent["crewtrac_check"]["line"].startswith("CrewTrac not compared (snapshot")


def test_admin_card_flags_the_trip_and_the_month(tmp_path):
    """The schedule card on the admin's own login: the trip's Pay-Gross turns red with CrewTrac's figures as the
    authoritative ones, and the totals line carries the CrewTrac item."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    from test_fw1720_pay_engine import DET, OT
    sn = CT.compact(CT.build_snapshot([CT.parse_schedule_detail(SD_MAR.replace("0327", "1126").replace(" MAR", " NOV")
                                                                .replace("/03", "/11"))],
                                      {"2026-11": None}, "2026-11-20T14:22:00-10:00"))
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    days[17] = ["2026-11-18", "H9606A", "JFK"]
    package = {"month": "2026-11", "source": "synthetic", "start": "2026-11-01", "end": "2026-11-30",
               "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
               "rows": [["H9606", "14:45", "15:45", "15:10", 2, 960, "HNL-JFK-HNL", "21h00", "48h25", "18"]],
               "detail": {"H9606": DET}}
    st = {"sensor.flight_watcher_schedule": {"state": "", "last_updated": "a", "attributes": {"updated": "Nov 20, 2026", "months": {
              "2026-11": {"items": [{"trip": "H9606A", "start": "2026-11-18", "end": "2026-11-21", "lay": "JFK"}],
                          "days": days, "totals": {"credit": "32:19", "block": "21:08"}, "updated": "Nov 20, 2026"}}}},
          "sensor.flight_watcher_own_trip_times": {"state": "1", "last_updated": "a", "attributes": {"trips": {"H9606A|2026-11-18": dict(OT)}}},
          "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
          "input_number.flight_watcher_longevity_year": {"state": "12.0", "last_updated": "a", "attributes": {}},
          "input_text.flight_watcher_er_trips": {"state": "", "last_updated": "a", "attributes": {}},
          "sensor.flight_watcher_crewtrac_check": {"state": "mismatch", "last_updated": "a", "attributes": {"snapshot": sn}},
          "sensor.flight_watcher_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "admin"}}}
    stub = ("window.fetch = async (u) => ({ok: String(u).includes('pairings_2026-11'), json: async () => ("
            + json.dumps(package) + ")});")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            + stub + "</script><script>" + open(CARD, encoding="utf-8").read() + "</script></body></html>")
    js = """(h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
      const hs = {states: h, user: {is_owner: true}, callService: async () => {}};
      document.body.appendChild(c); c.hass = hs;
      return new Promise((res) => setTimeout(() => { c.hass = {...hs};
        const r = c.shadowRoot, tr = [...r.querySelectorAll('tr[data-d]')].find((x) => x.dataset.d === '2026-11-18');
        const p = tr.querySelector('.pay');
        res({tot: (r.querySelector('.tot') || {}).textContent || '', info: p.dataset.info, cls: p.className}); }, 400)); }"""
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 1200, "height": 900})
            pg.clock.set_fixed_time("Fri 2026-11-20 6:30 PM EST (UTC-05:00)")
            pg.set_content(page)
            got = pg.evaluate(js, st)
        finally:
            b.close()
    assert "CrewTrac 32:19, FW 21:09 \u2717 credit off by -11:10 (CrewTrac controls). Authoritative: CrewTrac 32:19 credit / 21:08 block" in got["info"], got["info"]
    assert "ctbad" in got["cls"]
    assert "CrewTrac" in " ".join(got["tot"].split()) and "1 trip" in got["tot"], got["tot"]

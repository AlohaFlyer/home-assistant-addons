"""1.7.14 (Ryan, Nov 17: "In the open time pot, for each trip hidden by a VAC or blocked day, show what I'd have to drop
or swap to fly it, plus the pay difference."): the near misses. Each pot trip hidden today because it touches a VAC day,
a blocked day, or overlaps one of the pilot's own trips is listed with what stands in the way, what to change to fly it,
the pay difference (the trip's pay less what is given up: VAC at 4:00 a day, PWA 6.J.1.c; a dropped own trip its
credit; a blocked day nothing; every trip priced by pay.trip_gross, the schedule card's tripFull: PWA 3.D.6 rate, 4.O.1
overrides) and FAR 117 legality with the conflict removed (far_screen, as swap_scan: plain OK only, the 11 h home rest
of PWA 10.E.1.a). Information only: no FLICA load, nothing sent. Its own sensor (near/state), never the pot sensor;
each instance computes its own; off the portal export (a contract change for later). The card renders at 390 px, light
and dark. Synthetic pairings and made-up data only."""
import hashlib
import inspect
import json
import os
import sys
from datetime import date, datetime, timedelta

import pytest

import pay as PAY
import pot as P
import recall as RC
import roles
from conftest import FakeMQ

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
CARD = os.path.join(HERE, "www", "flight-watcher-near-card.js")
RATE = 259.04  # PWA 3.D.6 FO rate, longevity year 5, from 2026-03-02 (pay.rate_for(5, "2026-11-02"))
SHOTS = os.environ.get("FW_SHOTS", "")  # a folder: the card renders are saved there too


# ---------------------------------------------------------------- a made-up line and pot
def _w(tmp_path, monkeypatch, year="5"):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2026, 11, 2)))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
    # the longevity year helper (Pay settings), read through pay_settings as the schedule card reads it
    monkeypatch.setattr(W, "ha_state", lambda eid: year if eid.endswith("_longevity_year") else None)
    monkeypatch.setattr(W, "MQ", FakeMQ())
    _line(W)
    return W


def _month(mk, n):
    y, m = int(mk[:4]), int(mk[5:])
    return {"month": mk, "days": [[(date(y, m, 1) + timedelta(days=i)).isoformat(), "", ""] for i in range(n)],
            "items": [], "totals": {}}


def _line(W):
    """October and November on file. Nov 5 PAYP; H1019 Nov 19 (released 23:45); VAC Nov 20 to 22; H3620 Nov 25 to 27;
    Nov 14 and Nov 23 blocked."""
    W.S["schedule"] = {"2026-10": _month("2026-10", 31), "2026-11": _month("2026-11", 30)}
    W.S["schedule"]["2026-11"]["items"] = [
        {"trip": "PAYP", "start": "2026-11-05", "end": "2026-11-05", "lay": ""},
        {"trip": "H1019", "start": "2026-11-19", "end": "2026-11-19", "lay": ""},
        {"trip": "VAC", "start": "2026-11-20", "end": "2026-11-22", "lay": ""},
        {"trip": "H3620", "start": "2026-11-25", "end": "2026-11-27", "lay": "LAX"}]
    W.S["own_trips"] = {
        "H1019|2026-11-19": {"report": "14:00", "last_arr": "23:30", "blk": "7:00", "credit": "7:30", "seat": "FO"},
        "H3620|2026-11-25": {"report": "08:00", "last_arr": "15:00", "blk": "12:00", "credit": "15:30", "seat": "FO",
                             "duties": [{"d": 0, "dep": 540, "arr": 900, "stn": "LAX", "blk": 360},
                                        {"d": 2, "dep": 3420, "arr": 3780, "stn": "HNL", "blk": 360}]}}
    W.S["blocked_days"] = ["2026-11-14", "2026-11-23"]
    W.S["details"] = {"H9004|22Nov": {"duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                                                 {"d": 1, "dep": 2040, "arr": 2340, "stn": "HNL", "blk": 300}]}}


def _row(pid, start, end=None, credit="6:00", blk="5:00", report="08:00", arrive="14:00", seats="FO", lay="-none-"):
    end = end or start
    return {"pairing": pid, "start": start, "end": end, "dates": f"{start}-{end}" if end != start else start,
            "days": str((P.row_date(end, date(2026, 11, 2)) - P.row_date(start, date(2026, 11, 2))).days + 1),
            "layover": lay, "credit": credit, "blk": blk, "report": report, "arrive": arrive, "open_seats": seats,
            "month": "mobile"}


POT = [
    _row("H9001", "21Nov", "22Nov", credit="10:00", blk="8:00", report="09:00", arrive="15:00", lay="LAX"),  # VAC
    _row("H9002", "14Nov", credit="6:00", blk="5:00", seats="RO"),  # blocked day, the RO seat open
    _row("H9003", "26Nov", credit="7:00", blk="6:00", report="07:00", arrive="13:00"),  # overlaps H3620
    _row("H9004", "22Nov", "23Nov", credit="11:00", blk="10:00", report="08:00", arrive="15:00", lay="LAX"),  # both
    _row("H9005", "20Nov", credit="6:00", blk="5:00", report="06:00", arrive="12:00"),  # VAC, 6:15 rest after H1019
    _row("H9006", "21Nov", report=""),  # VAC, report not read yet
    _row("H9007", "20Nov", credit="6:00", blk="5:00", report="10:15", arrive="16:00"),  # VAC, 10:30 rest: CBA short
    _row("H9008", "08Nov"),  # fits: not a near miss
    _row("H9009", "05Nov"),  # on the PAYP day: free for a pickup (PWA 4.R.1), not a near miss
    _row("H3620", "25Nov", "27Nov", credit="15:30", blk="12:00"),  # his own trip's open seat: not a near miss
]


def _rows():
    return [dict(r) for r in POT]


def _by(misses):
    return {m["pairing"]: m for m in misses}


def _sent(W, topic="flight_watcher/near/state"):
    msgs = [json.loads(p) for t, p, _q, _r in W.MQ.msgs if t == topic]
    assert msgs, [t for t, *_ in W.MQ.msgs]
    return msgs[-1]


# ---------------------------------------------------------------- what is in the way, and the fix
def test_each_conflict_type_names_what_stands_in_the_way_and_the_fix(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    got = _by(W.near_misses(_rows()))
    assert set(got) == {"H9001", "H9002", "H9003", "H9004", "H9005", "H9006", "H9007"}  # no H9008, H9009, H3620
    vac = got["H9001"]["blockers"]
    assert [(b["kind"], b["what"], b["fix"]) for b in vac] == [("vac", "VAC Nov 21 to 22", "give up VAC Nov 21 to 22")]
    blk = got["H9002"]["blockers"]
    assert [(b["kind"], b["what"], b["fix"]) for b in blk] == [("blocked", "blocked Nov 14", "unblock Nov 14")]
    own = got["H9003"]["blockers"]
    assert [(b["kind"], b["what"], b["fix"]) for b in own] == [
        ("trip", "overlaps your H3620 Nov 25 to 27", "drop or swap H3620")]
    assert own[0]["key"] == "H3620|2026-11-25"
    assert got["H9001"]["kinds"] == ["vac"] and got["H9002"]["kinds"] == ["blocked"] and got["H9003"]["kinds"] == ["trip"]
    assert got["H9001"]["start"] == "2026-11-21" and got["H9001"]["end"] == "2026-11-22"
    assert got["H9001"]["dates"] == "21Nov-22Nov" and got["H9001"]["lay"] == "LAX" and got["H9002"]["lay"] == ""


def test_a_trip_hidden_for_two_reasons_lists_both(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    m = _by(W.near_misses(_rows()))["H9004"]
    assert m["kinds"] == ["vac", "blocked"]
    assert [(b["what"], b["fix"]) for b in m["blockers"]] == [("VAC Nov 22", "give up VAC Nov 22"),
                                                              ("blocked Nov 23", "unblock Nov 23")]
    # only the VAC day the trip touches is given up (Nov 22), not the whole Nov 20 to 22 block
    assert m["blockers"][0]["credit"] == "4:00" and m["blockers"][1]["credit"] == "0:00"
    assert m["diff_text"] == "+$1,813" and m["hours"] == "+7:00" and m["legal"] is True


def test_spans_across_a_month_and_runs_of_days(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    assert W._near_when("2026-11-30", "2026-12-01") == "Nov 30 to Dec 1"
    assert W._near_when("2026-11-26", "2026-11-26") == "Nov 26" and W._near_when("2026-11-25", "2026-11-27") == "Nov 25 to 27"
    assert W._near_runs(["2026-11-14", "2026-11-15", "2026-11-17"]) == [("2026-11-14", "2026-11-15"),
                                                                        ("2026-11-17", "2026-11-17")]
    W.S["blocked_days"] = ["2026-11-14", "2026-11-15", "2026-11-17"]
    m = _by(W.near_misses([_row("H9010", "13Nov", "17Nov", credit="25:00", blk="20:00")]))["H9010"]
    assert [b["what"] for b in m["blockers"]] == ["blocked Nov 14 to 15", "blocked Nov 17"]


# ---------------------------------------------------------------- the pay difference
def test_pay_difference_uses_the_watchers_rate_and_the_pwa_rules(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    rate, yr, _er = W.pay_settings()
    assert (rate, yr) == (RATE, 5) == (PAY.rate_for(5, "2026-11-02"), 5)  # PWA 3.D.6, the helper's longevity year
    got = _by(W.near_misses(_rows()))
    # VAC: 4:00 a day at the rate (PWA 6.J.1.c, the schedule card's VAC_H x RATE); 2 days given up
    a = got["H9001"]
    assert a["blockers"][0]["credit"] == "8:00" and a["blockers"][0]["pay"] == round(2 * PAY.VAC_H * RATE, 2) == 2072.32
    assert a["pay_trip"] == round(PAY.trip_gross(10.0, 8.0, 0, "LAX", "H9001|2026-11-21", "FO", RATE), 2) == 2590.40
    assert a["diff"] == 518.08 and a["diff_text"] == "+$518" and a["hours"] == "+2:00"
    # a blocked day loses nothing; the RO seat open: the PWA 4.O.1 override $4.00 per block hour
    b = got["H9002"]
    assert b["blockers"][0]["pay"] == 0.0 and b["pay_trip"] == round(6 * RATE + 5 * PAY.IRO_OVERRIDE, 2) == 1574.24
    assert b["seat"] == "RO" and b["diff_text"] == "+$1,574" and b["hours"] == "+6:00"
    # a dropped own trip loses its credit, priced from his own trip record (pay.trip_gross, as price_moves)
    c = got["H9003"]
    assert c["blockers"][0]["credit"] == "15:30" and c["blockers"][0]["pay"] == round(15.5 * RATE, 2) == 4015.12
    assert c["pay_trip"] == 1813.28 and c["diff"] == -2201.84 and c["diff_text"] == "-$2,202" and c["hours"] == "-8:30"
    W.publish_near_misses(_rows())
    p = _sent(W)
    assert p["rate"] == RATE and p["year"] == 5 and "pay_note" not in p


def test_without_a_rate_the_hours_show_and_no_dollars(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch, year=None)  # no longevity year and no DOH on file
    got = _by(W.near_misses(_rows()))
    assert got["H9001"]["diff"] is None and got["H9001"]["diff_text"] == "" and got["H9001"]["hours"] == "+2:00"
    assert got["H9001"]["blockers"][0]["pay"] is None and got["H9002"]["blockers"][0]["pay"] == 0.0
    W.publish_near_misses(_rows())
    p = _sent(W)
    assert p["rate"] is None and "longevity year" in p["pay_note"]


def test_an_unknown_credit_leaves_the_difference_unknown(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    W.S["own_trips"]["H3620|2026-11-25"].pop("credit")  # not read yet, no package: no amount (never a wrong one)
    c = _by(W.near_misses(_rows()))["H9003"]
    assert c["blockers"][0]["credit"] == "" and c["blockers"][0]["pay"] is None
    assert c["diff"] is None and c["diff_text"] == "" and c["hours"] == ""


# ---------------------------------------------------------------- FAR 117 with the conflict removed
def test_far_legal_with_the_conflict_removed(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    got = _by(W.near_misses(_rows()))
    for pid in ("H9001", "H9002", "H9003", "H9004"):
        assert (got[pid]["far"], got[pid]["legal"], got[pid]["legal_text"]) == ("OK", True, "legal"), (pid, got[pid])
    # H9003 overlaps H3620: as it stands it is a Conflict; with H3620 dropped it is legal (far_screen's exclude)
    row = _row("H9003", "26Nov", credit="7:00", blk="6:00", report="07:00", arrive="13:00")
    assert W.far_screen(dict(row))["far"] == "Conflict"
    assert W.far_screen(dict(row), exclude=("H3620|2026-11-25",))["far"] == "OK"


def test_far_not_legal_and_unknown(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    got = _by(W.near_misses(_rows()))
    e = got["H9005"]  # 6:15 after H1019's release (FAR 117.25(e) 10 h)
    assert e["legal"] is False and e["legal_text"] == "not legal: Rest 6:15 before" and "117.25(e)" in e["far_why"]
    i = got["H9007"]  # FAR met, 10:30 at home: under the PWA 10.E.1.a 11 h (swap_scan's rule: plain OK only)
    assert i["legal"] is False and i["far"] == "OK (CBA rest 10:30)"
    assert i["legal_text"] == "not legal: CBA rest 10:30, under the 11 h home rest (PWA 10.E.1.a)"
    h = got["H9006"]  # report not read yet: never called legal
    assert h["legal"] is None and h["far"] == "?" and h["legal_text"].startswith("not known yet: ")
    assert "not read yet" in h["legal_text"]
    assert all(len(m["far_why"]) <= W.NEAR_WHY_MAX for m in got.values())


def test_line_records_leaves_out_every_trip_given_up():
    months = {"2026-11": {"items": [{"trip": "H1001", "start": "2026-11-10", "end": "2026-11-10"},
                                    {"trip": "H1002", "start": "2026-11-11", "end": "2026-11-11"},
                                    {"trip": "H1003", "start": "2026-11-12", "end": "2026-11-12"}],
                          "days": [[(date(2026, 11, 1) + timedelta(days=i)).isoformat(), "", ""] for i in range(30)]}}
    lab = lambda recs: [r["label"] for r in recs if not r.get("unknown_line")]  # noqa: E731
    d = date(2026, 11, 11)
    assert lab(RC.line_records(months, {}, d, d, date(2026, 11, 2))) == ["H1001 Nov 10", "H1002 Nov 11", "H1003 Nov 12"]
    assert lab(RC.line_records(months, {}, d, d, date(2026, 11, 2), "H1002|2026-11-11")) == ["H1001 Nov 10", "H1003 Nov 12"]
    assert lab(RC.line_records(months, {}, d, d, date(2026, 11, 2), ("H1001|2026-11-10", "H1002|2026-11-11"))) == [
        "H1003 Nov 12"]


# ---------------------------------------------------------------- order, information only, the sensor
def test_the_list_runs_legal_first_then_by_the_pay_difference(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    order = [m["pairing"] for m in W.near_misses(_rows())]
    assert order == ["H9004", "H9002", "H9001", "H9003", "H9006", "H9005", "H9007"]


def test_no_flica_load_and_nothing_sent(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)

    def no(*a, **k):
        raise AssertionError("a FLICA load or a request")
    monkeypatch.setattr(W.Flica, "fetch", no)
    monkeypatch.setattr(W.Flica, "_load", no)
    monkeypatch.setattr(W.GATE, "acquire", no)
    monkeypatch.setattr(W, "count_fetch", no)
    monkeypatch.setattr(W, "enrich", no)
    monkeypatch.setattr(W.requests, "get", no)
    monkeypatch.setattr(W.requests, "post", no)
    monkeypatch.setattr(W, "swap_test", no)  # never a draft either
    before = (W.FETCHES.get("n"), dict(W.S.get("own_trips")), list(W.S["blocked_days"]))
    W.publish_near_misses(_rows())
    p = _sent(W)
    assert p["count"] == 7 and len(p["misses"]) == 7
    assert (W.FETCHES.get("n"), dict(W.S.get("own_trips")), list(W.S["blocked_days"])) == before
    assert [t for t, *_ in W.MQ.msgs] == ["flight_watcher/near/state"]  # no event, no command, no other topic
    src = inspect.getsource(W.near_misses) + inspect.getsource(W.publish_near_misses) + inspect.getsource(W.near_blockers)
    for word in ("fetch(", "fl.", "submit", "SUB.", "event/", "requests."):
        assert word not in src, word


def test_check_publishes_the_list_each_pass_after_the_pot(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    src = inspect.getsource(W.check)
    assert src.index("publish_pot(flat)") < src.index("publish_near_misses(flat)") < src.index("swap_scan(flat)")
    # the pot sensor is as it was: no near miss fields on it (its 12 KB cap)
    W.publish_pot(_rows())
    pot = json.loads([p for t, p, _q, _r in W.MQ.msgs if t == "flight_watcher/pot/state"][-1])
    assert all("blockers" not in r and "legal" not in r for r in pot["pairings"])


def test_the_sensor_is_a_discovery_entity_of_both_roles_and_off_the_portal(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    ent = {oid: (comp, cfg, f) for comp, oid, cfg, f in W.entity_defs()}
    comp, cfg, feat = ent["near_misses"]
    assert comp == "sensor" and feat == "core" and cfg["default_entity_id"] == "sensor.flight_watcher_near_misses"
    assert cfg["state_topic"] == cfg["json_attributes_topic"] == "flight_watcher/near/state"
    assert cfg["value_template"] == "{{ value_json.count }}"
    assert roles.allowed(feat, "pilot2") and not roles.entity_on_portal("near_misses", "pilot2")
    assert "near_misses" in roles.ENTITY_OFF_PORTAL and "near" in roles.RESERVED
    assert "near" in roles.name_refusal("near") and "near" in roles.name_refusal("near_x")
    assert W.ATTR_TRIM["near/state"] == ("misses", "end")


def test_the_sensor_stays_under_the_attribute_cap(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    rows = [_row(f"H{8000 + k}", "14Nov", credit="6:00", blk="5:00", lay="SYD/MEL") for k in range(200)]
    W.publish_near_misses(rows)
    p = _sent(W)
    assert p["count"] == 200 and 0 < len(p["misses"]) <= W.NEAR_ROWS
    assert W.attr_size(p) <= W.ATTR_MAX
    W.MQ.msgs.clear()
    monkeypatch.setattr(W, "NEAR_ROWS", 200)  # even with every row asked for, cap_attrs cuts from the end
    W.publish_near_misses(rows)
    p = _sent(W)
    assert W.attr_size(p) <= W.ATTR_MAX and p["trimmed"] > 0 and len(p["misses"]) + p["trimmed"] == 200


def test_an_empty_pot_or_no_misses_publishes_zero(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    W.publish_near_misses([])
    assert _sent(W)["count"] == 0 and _sent(W)["misses"] == []
    W.publish_near_misses([_row("H9008", "08Nov")])
    assert _sent(W)["count"] == 0


def test_a_pilot_instance_computes_its_own_and_its_portal_export_is_unchanged(portal_pilot, monkeypatch):
    W, _ha = portal_pilot("pilot2")
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2026, 11, 2)))
    _line(W)
    W.publish_near_misses(_rows())
    topics = [t for t, *_ in W.MQ.raw.msgs]
    assert "flight_watcher_pilot2/near/state" in topics and not [t for t in topics if t.startswith("flight_watcher/")]
    p = json.loads([pl for t, pl, *_ in W.MQ.raw.msgs if t == "flight_watcher_pilot2/near/state"][-1])
    assert p["count"] == 7
    assert not [e for e in W.portal_ids() if "near" in e]  # contract 1 revision 6 as it is: not exported
    assert "flight_watcher_pilot2/near/state" not in W.portal_topics()
    ent = {oid: f for _c, oid, _cfg, f in W.entity_defs()}
    assert W.has(ent["near_misses"])  # his own HA entity (discovery), for a later contract revision


def test_the_card_is_off_the_portal_bundle(portal_pilot):
    W, _ = portal_pilot("pilot2")
    assert "near-card" in W.PORTAL_CARDS_OUT
    assert not [f for f in W.portal_cards() if "near" in f]
    import cards
    assert "flight-watcher-near-card-pilot2.js" in cards.build("1", ["pilot2"])  # still deployed under /local/


# ---------------------------------------------------------------- the dashboard snapshot
def test_the_watcher_view_shows_the_card_under_the_pot_table():
    path = os.path.join(ROOT, "ha", "dashboard_flight_watcher.json")
    text = open(path, encoding="utf-8").read()
    v = next(v for v in json.loads(text)["data"]["config"]["views"] if v.get("path") == "watcher")
    sec = next(s for s in v["sections"] if any(c.get("heading") == "Open time pot / Tradeboard Pickups"
                                                 for c in s["cards"]))
    cs = sec["cards"]
    i = next(i for i, c in enumerate(cs) if c.get("type") == "custom:flight-watcher-near-card")
    assert cs[i] == {"grid_options": {"columns": "full"}, "type": "custom:flight-watcher-near-card"}
    assert cs[i - 1]["type"] == "markdown" and "pot_table" in cs[i - 1]["content"]
    assert cs[i + 1] == {"heading": "Swap ideas", "type": "heading"} or cs[i + 1].get("heading") == "Swap ideas"
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"  # the Refresh format
    readme = open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read()
    sec = readme[readme.index("## Pending on Pako (1.7.14): near misses card"):]
    sec = sec[:sec.index("\n## ", 5)]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() in sec
    assert "be03a0a48b9df66962e49a86c285921858768f5f97d27fda88288c26a0595435" in readme  # Pako's, until the release
    assert "Ryan" in sec and "yes" in sec and "Undo" in sec
    assert chr(0x2014) not in readme and chr(0x2014) not in text


# ---------------------------------------------------------------- the card (Chromium, 390 px, light and dark)
LIGHT = ("--primary-color:#009ac7;--text-primary-color:#ffffff;--secondary-text-color:#727272;"
         "--divider-color:rgba(0,0,0,.12);--card-background-color:#ffffff;--primary-text-color:#212121;"
         "--error-color:#db4437;--warning-color:#ffa600;background:#fafafa;color:#212121")
DARK = ("--primary-color:#009ac7;--text-primary-color:#ffffff;--secondary-text-color:#9b9b9b;"
        "--divider-color:rgba(225,225,225,.12);--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
        "--error-color:#db4437;--warning-color:#ffa600;background:#111111;color:#e1e1e1")


def test_the_card_source():
    src = open(CARD, encoding="utf-8").read()
    assert "sensor.flight_watcher_near_misses" in src and 'customElements.define("flight-watcher-near-card"' in src
    assert "PWA 6.J.1.c" in src and "PWA 3.D.6" in src and "PWA 4.O.1" in src and "PWA 10.E.1.a" in src
    assert "117.25(e)" in src and "callService" not in src and "fetch(" not in src  # read only
    assert chr(0x2014) not in src


@pytest.fixture(scope="module")
def near_payload(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        W = _w(tmp_path_factory.mktemp("near"), mp)
        W.publish_near_misses(_rows())
        p = _sent(W)
    finally:
        mp.undo()
        sys.modules.pop("watcher", None)
    return p


def _page(payload, theme, dark, eid="sensor.flight_watcher_near_misses"):
    from test_layover_card import FW_CONTRAST
    src = open(CARD, encoding="utf-8").read()
    states = {eid: {"state": str(payload["count"]), "attributes": payload, "last_updated": "2026-11-02T19:00:00+00:00"}}
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<style>body{{margin:0;padding:8px 16px;font-family:Roboto,sans-serif;{theme}}}</style></head><body><script>"
            + FW_CONTRAST +
            "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML ="
            " '<style>:host{display:block;background:var(--card-background-color);border-radius:12px}</style><slot></slot>'; } });"
            "</script><script>" + src + "</script><script>"
            "const c = document.createElement('flight-watcher-near-card'); c.setConfig({}); document.body.appendChild(c);"
            f"window.H = {{states: {json.dumps(states)}, themes: {{darkMode: {json.dumps(dark)}}}, callService: () => {{ throw new Error('no'); }}}};"
            "c.hass = window.H; window.root = () => c.shadowRoot;"
            "window.again = () => { window.H = {...window.H, states: {...window.H.states}}; "
            "window.H.states['sensor.flight_watcher_near_misses'] = {...window.H.states['sensor.flight_watcher_near_misses'], last_updated: 'x2'}; c.hass = window.H; };"
            "</script></body></html>")


READ_JS = """() => { const r = window.root(), d = r.querySelector('details.nm'), s = d.querySelector('summary');
  const items = [...r.querySelectorAll('.m')].map((x) => x.innerText.replace(/\\s+/g, ' ').trim());
  const vis = [...r.querySelectorAll('.m')].filter((x) => x.checkVisibility()).length;
  return {open: d.open, summary: s.innerText.replace(/\\s+/g, ' ').trim(), sumH: s.getBoundingClientRect().height,
          items, vis, wide: document.documentElement.scrollWidth}; }"""


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_render_the_card_at_390(near_payload, theme):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.set_content(_page(near_payload, LIGHT if theme == "light" else DARK, theme == "dark"))
            shut = pg.evaluate(READ_JS)
            assert shut["open"] is False and shut["vis"] == 0  # collapsed by default
            assert shut["summary"].startswith("Near misses") and "7" in shut["summary"] and shut["sumH"] >= 44
            assert shut["wide"] <= 390
            if SHOTS:
                pg.screenshot(path=os.path.join(SHOTS, f"item5_near_390_{theme}_closed.png"), full_page=True)
            pg.locator("flight-watcher-near-card summary").first.click()
            got = pg.evaluate(READ_JS)
            assert got["open"] is True and got["vis"] == 7 and got["wide"] <= 390
            first = got["items"][0]
            assert first.startswith("H9004") and "22Nov-23Nov" in first and "+$1,813" in first and "+7:00" in first
            assert "VAC Nov 22" in first and "blocked Nov 23" in first and "give up VAC Nov 22" in first
            assert "unblock Nov 23" in first and "legal" in first and "not legal" not in first
            c = next(x for x in got["items"] if x.startswith("H9003"))
            assert "overlaps your H3620 Nov 25 to 27" in c and "drop or swap H3620" in c and "-$2,202" in c
            assert "-15:30" in c and "-$4,015" in c
            e = next(x for x in got["items"] if x.startswith("H9005"))
            assert "not legal: Rest 6:15 before" in e
            h = next(x for x in got["items"] if x.startswith("H9006"))
            assert "not known yet" in h
            con = pg.evaluate("window.fwContrast(window.root().host)")
            assert con["n"] > 20 and not con["fails"], json.dumps(con["fails"], indent=1)
            pg.evaluate("window.again()")  # a new state while open: it stays open
            assert pg.evaluate(READ_JS)["open"] is True
            if SHOTS:
                pg.screenshot(path=os.path.join(SHOTS, f"item5_near_390_{theme}_open.png"), full_page=True)
            pg.close()
        finally:
            b.close()


def test_render_the_card_with_no_sensor_or_no_misses():
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    empty = {"count": 0, "misses": [], "rate": RATE, "year": 5}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.set_content(_page(empty, LIGHT, False))
            t = pg.evaluate("window.root().textContent")
            assert "Near misses" in t and "No pot trip is hidden" in t
            pg.close()
            pg = b.new_page(viewport={"width": 390, "height": 844})  # a fresh page: a card element is defined once
            pg.set_content(_page(empty, LIGHT, False, eid="sensor.other"))  # no near misses sensor (before 1.7.14)
            t = pg.evaluate("window.root().textContent")
            assert "Near misses" in t and "1.7.14" in t
            pg.close()
        finally:
            b.close()

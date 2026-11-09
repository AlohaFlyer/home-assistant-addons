"""FW-0060: every Flight Watcher sensor stays under 12 KB of attributes (HA's recorder keeps no history and logs a
warning on every update past 16 KiB; sensor.flight_watcher_tickets ran about 39 KB and schedule_versions about 33 KB
on Pako in Nov 2026). The long lists go to <name>_<key>.json under the pilot's www folder, which the cards fetch with
the key the sensor publishes. Realistic synthetic data only ("Doe, Jane"), sized like a busy month or more."""
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta

import pytest

import cards
import tickets as TK
import wwwfiles as WF
from pot import parse_legs

LIMIT = 12 * 1024  # the ticket's bar for the attributes HA stores
HA_OWN = 160  # friendly_name, icon, unit_of_measurement HA adds to each state's attributes
KEY_RE = r"[0-9a-f]{32}"
PAD = "Doe-Longername, Janeallison"


class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


def _load(tmp_path, monkeypatch, instance=""):
    data = tmp_path / ("data_" + (instance or "default"))
    data.mkdir()
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "my_name": "Doe",
                                                   "category_check": "HNL 332 FO"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    monkeypatch.setattr(W, "WWW_OLD", str(tmp_path / "www" / "flica"))
    monkeypatch.setattr(W, "TICKETS_DIR", str(tmp_path / "tickets"))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    W.S.clear()
    W.LIST_REV.clear()
    return W, fake


# ---------------------------------------------------------------- realistic synthetic data
def _crew(i):
    return [f"CA {PAD} (1{i:04d})", f"FO Doe, Jane (2{i:04d})", f"RO Roe, Rick (3{i:04d})"]


# FW-0067: a SYD trip's legs as own_trip_times keeps them in the state
LEGS = parse_legs("mo 451 hnl-syd 1155 1945 1050 th 452 syd-hnl 2140 1045 1005")


def _own(i):
    return {"report": "10:55", "last_arr": "10:45", "blk": "20:55", "credit": "21:06", "soft": "0:11",
            "read_at": "2026-11-06T10:23:34.302824", "final": False, "seat": "FO", "crew": _crew(i),
            "duties": [{"d": 0, "dep": 715, "arr": 1425, "dep_l": "11:55", "arr_l": "19:45", "blk": 650, "stn": "SYD"},
                       {"d": 3, "dep": 4420, "arr": 4965, "dep_l": "21:40", "arr_l": "10:45", "blk": 605, "stn": "HNL"}],
            "legs": [dict(lg) for lg in LEGS]}


def _month(y, m):
    """A FLICA month as the mobile schedule gives it: 33 day rows, 8 trips of 3 days, a week of VAC."""
    first = date(y, m, 1)
    days, items = [], []
    for k in range(33):
        d = (first + timedelta(days=k)).isoformat()
        if k % 4 == 0 and k < 30:
            days.append([d, f"H9{m:02d}{k // 4}", "SYD"])
            items.append({"trip": f"H9{m:02d}{k // 4}", "start": d, "end": (first + timedelta(days=k + 2)).isoformat(), "lay": "SYD"})
        else:
            days.append([d, "", "HNL" if k % 4 == 2 else "-"])
    return {"month": f"{y}-{m:02d}", "updated": "Nov 6, 2026 14:01:09", "days": days, "items": items,
            "totals": {"block": "95:03", "credit": "131:15", "ytd": "812:40", "days_off": 15}}


def _versions(W, mk, n=30):
    sch = _month(int(mk[:4]), int(mk[5:7]))
    trips = {f"{it['trip']}|{it['start']}": {f: v for f, v in _own(i).items() if f in W.VER.TRIP_FIELDS}
             for i, it in enumerate(sch["items"])}
    out = []
    for v in range(1, n + 1):
        rec = {"ver": f"{int(mk[5:7])}.{v:03d}", "n": v, "at": f"2026-11-0{1 + v % 6}T{v % 24:02d}:00:00+00:00",
               "updated": "Nov 6, 2026 14:01:09", "items": sch["items"], "days": sch["days"], "totals": sch["totals"],
               "trips": trips, "changes": [f"added H9{v:03d} 2026-11-12", f"dropped H8{v:03d} 2026-11-13",
                                           "FLICA block 70:25 -> 95:03", "FLICA credit 101:15 -> 131:15",
                                           f"H9{v:03d} seat ? -> FO"]}
        rec["fp"] = W.VER.fingerprint(rec, trips)
        out.append(rec)
    return sch, out


def _pot_row(i, src=None):
    r = {"pairing": f"H3{i:03d}", "start": "12Nov", "end": "15Nov", "credit": "15:00", "layover": "LAS",
         "depart": "23:45", "arrive": "11:37", "days": "3", "prem": False, "dates": "12Nov-15Nov", "blk": "12:19",
         "report": "22:45", "captain": f"{PAD} (1{i:04d})", "tafb": "60:52", "soft": "2:41", "turn": "",
         "route": "HNL-LAS-HNL", "open_seats": "FO", "crew": _crew(i),
         "detail_url": "https://ha2.flica.net/full/mobilepairing.cgi?PID=H3620&DATE=20261112&FROM=MobileOpentimePot&CurrentPage=1",
         "fit": "Conflict H3681", "vac": False, "blocked": False, "far": "OK", "month": "2026-11"}
    if src:
        r.update(poster=f"{PAD} (2{i:04d})", posted="2026-11-06T10:00:00-10:00", post_type="Pickup", comments="",
                 request_id=f"{i:09d}", source="tradeboard", last_arr="11:37", duties=_own(i)["duties"])
    return r


def _verdict(d, i):
    return {"id": f"{d}|H36{i:02d}|recall", "date": d, "kind": "recall", "pairing": f"H36{i:02d}", "sen": 900 + i,
            "pilot": f"{PAD} (4{i:04d})", "seat": "FO", "verdict": ["MISSED", "POSSIBLE", "NO"][i % 3],
            "why": [f"went to #{900 + i}, junior to you (#850)", "your line as held at Nov 6 00:00 HST (version 11.004)",
                    "FAR 117.25(e) 10 h rest: 26:15 before the report"],
            "refs": ["PWA 22.G.2.e, 22.E, 4.M (200%)", "FAR 117.25(e)"], "start": d, "end": d, "report": "10:55",
            "last_arr": "10:45", "asof": "2026-11-06T10:00:00+00:00", "line": "11.004",
            "act": {"status": "new" if i % 3 != 2 else "dismissed", "at": "2026-11-06T10:00:00+00:00"}}


def _fill(W, fake, tmp_path, monkeypatch):
    """Every publisher fed a busy month's worth of synthetic data; returns {topic: last payload dict}."""
    today = W.local_now().date()
    months = [f"{(today.replace(day=1) + timedelta(days=31 * k)).replace(day=1):%Y-%m}" for k in (-1, 0, 1)]
    sched = {}
    for mk in months:
        sched[mk], vers = _versions(W, mk)
        W.DB.put(f"sched_versions:{mk}", vers)
    W.S["schedule"] = sched
    W.S["ends_fix_v"] = W.ENDS_FIX_V
    W.S["own_trips"] = {f"{it['trip']}|{it['start']}": _own(i) for mk in months for i, it in enumerate(sched[mk]["items"])}
    W.S["blocked_days"] = [(today + timedelta(days=k)).isoformat() for k in range(1, 25)]
    W.S["drop_away"] = list(W.S["own_trips"])[-5:]
    W.S["trade_away"] = list(W.S["own_trips"])[-5:]
    W.S["swap_tests"] = [{"at": "2026-11-06T10:00:00+00:00", "idea": {"for": "H9110|2026-11-12", "pairing": f"H3{i:03d}"},
                          "post": "mobileotswap.cgi?" + "x" * 120, "mode": "test"} for i in range(30)]
    W.S["tb_details"] = {f"{i:09d}|H3{i:03d}": _pot_row(i, src=True) for i in range(12)}
    # tickets: 80, 25 still open, long texts
    for i in range(80):
        t, err = TK.create(W.TICKETS_DIR, {"kind": "bug", "title": f"Ticket {i} " + "t" * 150, "narrative": "n" * 2500,
                                           "steps": "s" * 400, "expected": "e" * 400, "page": "Schedule"}, "ryan", "t0")
        assert t, err
        if i < 55:
            TK.act(W.TICKETS_DIR, {"id": t["id"], "action": "fixed" if i % 2 else "close", "version": "1.4.6"}, "ryan", "t1")
    # pickers: 150 FO / RO who took a trip
    stats = {f"2{i:04d}": {"name": f"{PAD}{i}", "pos": "FO", "n": 1 + i % 9, "total_s": 300 * (1 + i % 9),
                           "inflt_n": i % 3, "month_n": i % 4, "year_n": i % 9, "lays": ["LAS", "SYD", "NRT", "LAX"],
                           "last_lay": "LAS", "min_s": 40 + i, "last_at": "2026-11-06T10:00:00+00:00"} for i in range(150)}
    monkeypatch.setattr(W.DB, "picker_stats", lambda now=None: stats)
    # recall: 45 list days, 3 awards each
    W.DB.put("recall_days", {d: {"date": d, "file": f"recall_{d}.pdf", "at": "2026-11-06T10:00:00+00:00",
                                 "verdicts": [_verdict(d, i) for i in range(3)], "rows": [{"pilot": "Doe, Jane"}] * 3}
                             for d in ((today - timedelta(days=k)).isoformat() for k in range(45))})
    W.DB.put("improved_pay", {f"20{24 + k // 12}-{1 + k % 12:02d}": {"month": f"20{24 + k // 12}-{1 + k % 12:02d}", "awarded": 18234.5,
                                                                      "current": 19876.25, "ver": "11.009", "awarded_ver": "11.001",
                                                                      "improved": 1641.75, "at": "2026-11-06T10:00:00+00:00"}
                              for k in range(30)})
    W.DB.put("charters", {f"c{i}": {"date": f"2026-11-{1 + i:02d}", "scheduled": "09:00", "flight": f"HA{900 + i}",
                                    "route": "HNL-PPT-HNL", "aircraft": "A330", "status": "scheduled", "seen": "2026-11-06T10:00:00",
                                    "note": "charter " + "x" * 120, "gone": i % 5 == 0} for i in range(25)})
    W.RULES["list"] = [{"id": f"r{i}", "name": f"Rule {i} " + "x" * 40, "mode": "alert", "enabled": True,
                        "created_at": "2026-11-06T10:00:00+00:00"} for i in range(12)]
    for i in range(50):  # finds, as test_wwwfiles adds them
        seen = f"{today:%Y-%m}-{1 + i % 27:02d}T{i % 24:02d}:00:00+00:00"
        row = {"pairing": f"H9{i:03d}", "dates": "08Nov-10Nov", "days": "3", "layover": "LAX", "report": "07:00",
               "credit": "16:30", "turn": "", "captain": f"{PAD} (23456)", "source": "pot"}
        W.DB.db.execute("INSERT INTO finds(key,pairing,month,row,first_seen,last_seen,gone_at,pickup,alert_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (f"k{i}", f"H9{i:03d}", "Nov", json.dumps(row), seen, seen, seen,
                                                      json.dumps({"by": f"FO {PAD} (12345)", "status": "filled"}), seen))

    # the real publishers
    W.set_machine("idle", "checked")
    W.count_fetch()
    W.publish_settings(fake)
    W.publish_swap_mode(fake)
    W.publish_rules(fake)
    W.publish_blocked()
    W.publish_drop()
    W.publish_trade()
    W.publish_swap_tests()
    W.publish_tradeboard()
    W.publish_own_trips()
    W.publish_working_flight(force=True)  # FW-0067
    W.publish_charters()
    W.publish_improved()
    W.publish_tickets(force=True)
    W.publish_crew_index()
    W.versions_check(force_pub=True)
    W.publish_recall()
    W.publish_finds()  # and the pickers
    # FW-0066: the uploads list with 90 files on file, and an upload status carrying its recent results
    busy = tmp_path / "uploads_busy"
    busy.mkdir()
    for k in range(30):
        for kind in ("award", "pairings"):
            (busy / f"20{24 + k // 12}-{1 + k % 12:02d}_{kind}.pdf").write_bytes(b"%PDF-1.4")
        (busy / f"seniority_2026-{1 + k % 12:02d}-{1 + k:02d}.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(W.web, "UPLOAD_DIR", str(busy))
    monkeypatch.setattr(W.web, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(W.web, "PAIRINGS_DIR", str(tmp_path / "www" / "flight-watcher"))
    W.publish_uploads(force=True)
    for i in range(8):
        W.publish_upload_status({"id": f"{'a' * 15}{i}", "kind": "award", "state": "done", "ok": True, "got": 99,
                                 "total": 99, "message": "Saved 2026-12_award.pdf (1743 KB). " + "m" * 560})
    # the ones published inline in a FLICA read: the payloads those reads build, through the same pub()
    W.pub("pot/state", {"count": 25, "pairings": [_pot_row(i) for i in range(25)]})
    W.pub("schedule", {"updated": "Nov 6, 2026 14:01:09", "source": "FLICA mobile schedule (Watcher)", "checked": W.now_iso(),
                       "months": {k: {kk: v[kk] for kk in ("items", "days", "totals", "updated")} for k, v in sched.items()}})
    W.pub("ot_requests", {"pending": 1, "count": 20, "checked_at": W.now_iso(), "requests": [
        {"key": f"ts:01DD6E29:{i:08X}", "alt": f"11/06|10:00|Swap|H3604+H3629|{i}", "date": "11/06", "time": "10:00",
         "type": "Swap", "status": "Approved", "trips": ["H3604", "H3629"], "detail": "d" * 200, "bcid": "003.152",
         "legs": [{"trip": "H3629", "day": "14NOV", "side": "drop", "seat": "FO"},
                  {"trip": "H3604", "day": "13NOV", "side": "add", "seat": "RO"}]} for i in range(20)]})
    W.pub("grid/state", {"green": 20, "count": 31, "read": W.now_iso(), "days": {
        (today + timedelta(days=k)).isoformat(): {"color": "green", "net": 4, "res": 9, "need": 5, "seen": W.now_iso()}
        for k in range(31)}})
    W.pub("swap/state", {"count": 30, "marked": W.S["trade_away"], "ideas": [
        {"for": "H9110|2026-11-12", "for_trip": "H9110", "for_credit": "21:06", "for_soft": "0:11", "pairing": f"H3{i:03d}",
         "start": "12Nov", "end": "15Nov", "dates": "12Nov-15Nov", "days": "3", "layover": "LAS", "turn": "", "credit": "15:00",
         "soft": "2:41", "src": "O", "soft_gain": "+2:30", "credit_gain": "-6:06", "why": "w" * 80,
         "detail_url": _pot_row(i)["detail_url"], "gain_h": 1.9} for i in range(30)]})
    W.pub("pilot_schedule", {"emp": "12345", "name": "Doe, Jane", "status": "ok", "month": months[1], "days": sched[months[1]]["days"],
                             "items": sched[months[1]]["items"], "totals": sched[months[1]]["totals"], "updated": "x", "fetched": W.now_iso(),
                             "reconstructed": [{"pairing": f"H9{i:03d}", "start": "2026-11-12", "end": "2026-11-15", "seat": "FO",
                                                "route": "HNL-LAS-HNL", "checked_at": W.now_iso(), "lay": "LAS", "blk": "12:19",
                                                "credit": "15:00", "soft": "2:41", "crew": [["CA", f"{PAD} (1)"], ["FO", "Doe, Jane (2)"]]}
                                               for i in range(12)],
                             "reconstructed_coverage_pct": 88.5, "reconstructed_month": months[1], "pay_line": {"gross": 41234.5}})
    W.pub("last_new", _pot_row(1))
    W.pub("last_match", {"rule_id": "r1", "row": _pot_row(2), "at": W.now_iso()})
    out = {}
    for t, p, _ in fake.msgs:
        if t.startswith(f"{W.T}/") and p and p[:1] == "{":
            out[t[len(W.T) + 1:]] = json.loads(p)
    return out


def _attr_topics(W):
    c = FakeClient()
    W.discovery(c)
    return {json.loads(p)["json_attributes_topic"][len(W.T) + 1:] for t, p, _ in c.msgs
            if p and "/sensor/" in t and "json_attributes_topic" in json.loads(p)}


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_every_sensor_under_12_kb_on_a_busy_month(tmp_path, monkeypatch, instance):
    """The bar: every sensor's attributes as HA stores them (compact JSON plus HA's own fields) stay under 12 KB, for
    Ryan's instance and a second pilot's; every attribute topic discovery announces is covered here, so a new sensor
    that can grow fails this test until it is capped."""
    W, fake = _load(tmp_path, monkeypatch, instance)
    got = _fill(W, fake, tmp_path, monkeypatch)
    topics = _attr_topics(W)
    assert topics - set(got) == set()  # every sensor with attributes was published above
    sizes = {t: len(json.dumps(got[t], separators=(",", ":"))) for t in topics}
    over = {t: n for t, n in sizes.items() if n + HA_OWN > LIMIT}
    assert over == {}, over
    assert got["state_attr"]["role"] == ("pilot" if instance else "admin") and got["state_attr"]["features"]  # FW-0063
    for t in W.ATTR_TRIM:  # the backstop holds every capped sensor at ATTR_MAX
        if t in got:
            assert sizes.get(t, len(json.dumps(got[t], separators=(",", ":")))) <= W.ATTR_MAX, t
    # the four lists the ticket names moved to files: not trimmed, just short
    for t in ("tickets", "schedule_versions", "pickers"):
        assert sizes[t] < 8000 and "trimmed" not in got[t], (t, sizes[t])
    # FW-0067: the own trips carry their legs in the state, not on the sensor, so every trip of the three months fits
    own = got["own_trips"]
    assert "trimmed" not in own and len(own["trips"]) == own["count"] == len(W.S["own_trips"]) == 24
    assert all("legs" not in t for t in own["trips"].values()) and all("legs" in t for t in W.S["own_trips"].values())


def test_long_lists_live_in_keyed_files_the_cards_read(tmp_path, monkeypatch):
    """tickets, versions, pickers and recall: the whole list is in <name>_<key>.json in the pilot's www folder, under the
    same key as the finds files; the sensor names the key (file_key) and a hash of the file (rev); the sensor keeps
    what a card shows before the file comes in."""
    W, fake = _load(tmp_path, monkeypatch)
    got = _fill(W, fake, tmp_path, monkeypatch)
    key, fw = W.www_key(), tmp_path / "www" / "flight-watcher"
    for t in ("tickets", "schedule_versions", "pickers", "recall"):
        assert got[t]["file_key"] == key and len(got[t]["rev"]) == 12, t
    tk = json.loads((fw / f"tickets_{key}.json").read_text())
    assert tk["total"] == 80 and len(tk["tickets"]) == 80 and tk["tickets"][0]["id"] == "FW-0080"
    assert got["tickets"]["total"] == 80 and got["tickets"]["open"] == tk["open"] == 25 + 27
    assert got["tickets"]["rows"] == "open" and len(got["tickets"]["tickets"]) == W.TICKET_ATTR_ROWS  # newest open
    assert all("narrative" not in r and r["status"] in TK.OPEN for r in got["tickets"]["tickets"])
    assert any(len(r.get("narrative") or "") == 2500 for r in tk["tickets"])  # editable rows carry the whole text
    vs = json.loads((fw / f"versions_{key}.json").read_text())["months"]
    mk = sorted(vs)[1]
    assert len(vs[mk]["versions"]) == W.VER.MAX_PUBLISHED and vs[mk]["count"] == 30
    assert vs[mk]["versions"][-1]["items"] and vs[mk]["versions"][-1]["days"] and vs[mk]["versions"][-1]["trips"]
    assert got["schedule_versions"]["months"][mk] == {"count": 30, "current": f"{int(mk[5:7])}.030",
                                                     "awarded": f"{int(mk[5:7])}.001",
                                                     "current_at": vs[mk]["versions"][-1]["at"]}
    pk = json.loads((fw / f"pickers_{key}.json").read_text())
    assert pk["count"] == got["pickers"]["count"] == 150 and len(pk["pickers"]) == 150
    assert got["pickers"]["pickers"] == pk["pickers"][:W.PICKERS_ATTR_ROWS]  # the fastest few
    rc = json.loads((fw / f"recall_{key}.json").read_text())
    assert len(rc["days"]) == got["recall"]["days_total"] == 45
    assert 0 < len(got["recall"]["days"]) < 45 and got["recall"]["trimmed"] == 45 - len(got["recall"]["days"])
    assert got["recall"]["days"] == rc["days"][:len(got["recall"]["days"])]  # the newest days stay on the sensor
    assert got["recall"]["open"] == 45 * 2 and got["recall"]["alert"] == 45  # counted over every day
    # rev follows the file: a ticket change moves it, a republish of the same list does not rewrite the file
    before = got["tickets"]["rev"]
    mt = os.path.getmtime(fw / f"tickets_{key}.json")
    W.publish_tickets(force=True)
    assert json.loads(fake.msgs[-1][1])["rev"] == before and os.path.getmtime(fw / f"tickets_{key}.json") == mt
    TK.act(W.TICKETS_DIR, {"id": "FW-0080", "action": "note", "text": "seen"}, "ryan", "t2")
    W.publish_tickets(force=True)
    assert json.loads(fake.msgs[-1][1])["rev"] != before


def test_second_pilot_files_in_his_own_folder_under_his_own_key(tmp_path, monkeypatch):
    W, fake = _load(tmp_path, monkeypatch, "pilot2")
    TK.create(str(tmp_path / "tickets"), {"kind": "bug", "title": "Ryan's", "narrative": "x"}, "ryan", "t0")
    TK.create(str(tmp_path / "tickets"), {"kind": "bug", "title": "His", "narrative": "y"}, "pilot2", "t0")
    W.publish_tickets(force=True)
    key = W.www_key()
    f = tmp_path / "www" / "flight-watcher" / "pilot2" / f"tickets_{key}.json"
    assert [t["title"] for t in json.loads(f.read_text())["tickets"]] == ["His"]  # his tickets only
    assert not (tmp_path / "www" / "flight-watcher" / f"tickets_{key}.json").exists()
    p = json.loads([m for m in fake.msgs if m[0] == "flight_watcher_pilot2/tickets"][-1][1])
    assert p["file_key"] == key and [t["title"] for t in p["tickets"]] == ["His"]


def test_no_key_no_file_the_sensor_still_lists_open_tickets(tmp_path, monkeypatch, caplog):
    W, fake = _load(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger="flight_watcher")
    monkeypatch.setattr(W, "www_key", lambda: (_ for _ in ()).throw(OSError("read-only /data")))
    TK.create(W.TICKETS_DIR, {"kind": "bug", "title": "Grid blank", "narrative": "x"}, "ryan", "t0")
    W.publish_tickets(force=True)
    p = json.loads(fake.msgs[-1][1])
    assert p["file_key"] is None and p["rev"] is None and p["tickets"][0]["title"] == "Grid blank"
    assert "tickets file skipped" in caplog.text


def test_cap_attrs_cuts_the_least_useful_end(tmp_path, monkeypatch):
    """The backstop for the sensors whose lists stay on the sensor: oldest recall days, the oldest improved-pay months,
    the oldest own trips (dict keyed TRIP|start) and pot rows from the end; "trimmed" counts them; small payloads and
    unknown topics pass untouched."""
    W, _ = _load(tmp_path, monkeypatch)
    days = [{"date": f"2026-11-{30 - k:02d}", "verdicts": ["v" * 400]} for k in range(45)]  # newest first
    p = W.cap_attrs("recall", {"open": 1, "days": days})
    assert W.attr_size(p) <= W.ATTR_MAX and p["days"] == days[:len(p["days"])] and p["trimmed"] == 45 - len(p["days"])
    months = [{"month": f"2026-{k:02d}", "x": "y" * 600} for k in range(1, 31)]  # oldest first
    p = W.cap_attrs("improved_pay", {"months": months})
    assert p["months"][-1]["month"] == "2026-30" and p["months"][0] != months[0]
    trips = {f"H9{k:03d}|2026-{1 + k // 28:02d}-{1 + k % 28:02d}": {"crew": ["x" * 500]} for k in range(40)}
    p = W.cap_attrs("own_trips", {"count": 40, "trips": trips})
    kept = sorted(p["trips"], key=lambda k: k.split("|")[1])
    assert kept == sorted(trips, key=lambda k: k.split("|")[1])[-len(kept):] and p["trimmed"] == 40 - len(kept)
    small = {"count": 1, "pairings": [{"pairing": "H3620"}]}
    assert W.cap_attrs("pot/state", small) is small
    assert W.cap_attrs("event/new_pairing", {"x": "y" * 20000})["x"] == "y" * 20000


def test_list_files_are_swept_like_finds_files(tmp_path):
    key, old = "0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"
    www = tmp_path / "www"
    (www / "pilot2").mkdir(parents=True)
    for n in (f"tickets_{key}.json", f"tickets_{old}.json", f"versions_{key}.json.tmp", f"pickers_{old}.json",
              f"recall_{key}.json", "pairings_2026-11.json"):
        (www / n).write_text("{}")
    (www / "pilot2" / f"tickets_{old}.json").write_text("{}")
    assert WF.cleanup(str(www), key, WF.subdirs(str(www))) == 3
    assert sorted(os.listdir(www)) == sorted([f"tickets_{key}.json", f"recall_{key}.json", "pairings_2026-11.json", "pilot2"])
    assert os.listdir(www / "pilot2") == [f"tickets_{old}.json"]  # the second pilot's own file is his instance's


def test_pilot_copy_reads_his_own_list_files():
    f = cards.build("1.4.7", ["pilot2"])
    for card, name in (("tickets", "tickets"), ("schedule", "versions"), ("pickers", "pickers"), ("recall", "recall")):
        src, cp = f[f"flight-watcher-{card}-card.js"], f[f"flight-watcher-{card}-card-pilot2.js"]
        assert f'"/local/flight-watcher/{name}_"' in src
        assert f'"/local/flight-watcher/pilot2/{name}_"' in cp and f'"/local/flight-watcher/{name}_"' not in cp
    assert "/local/flight-watcher/pairings_" in f["flight-watcher-schedule-card-pilot2.js"]  # the package stays shared


# ---------------------------------------------------------------- the cards (node, stub DOM, stub fetch)
WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www")


def _node(tmp_path, card, body):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    src = open(os.path.join(WWW, card), encoding="utf-8").read()
    js = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}, get() {}}; globalThis.window = {customCards: []};\n"
          "globalThis.localStorage = {getItem() { return null; }, setItem() {}};\n"
          "const FETCHED = []; let FILE = null;\n"
          "globalThis.fetch = (u) => { FETCHED.push(u); return Promise.resolve({ ok: !!FILE, json: () => Promise.resolve(FILE) }); };\n"
          + src + "\n(async () => {\n" + body + "\n})();")
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


KEY = "0123456789abcdef0123456789abcdef"


LONG = "Crew index misses trips from the previous bid period that run into the month, and lookups of them (made up)"


def test_tickets_card_merges_file_and_sensor(tmp_path):
    """The file gives every ticket with its text; the sensor's open rows are newer and win on their fields; a ticket
    only the sensor has shows too; Edit needs the file's text; one fetch per rev, none without a key."""
    file = {"open": 2, "total": 3, "tickets": [
        {"id": "FW-0003", "status": "new", "title": "Old title", "narrative": "Full text", "editable": True},
        {"id": "FW-0002", "status": "fixed", "title": LONG, "narrative": "b"},
        {"id": "FW-0001", "status": "closed", "title": "A", "narrative": "a"}]}
    sens = {"rows": "open", "file_key": KEY, "rev": "abc", "tickets": [
        {"id": "FW-0004", "status": "new", "title": "Brand new", "editable": True},
        {"id": "FW-0003", "status": "triaged", "title": "New title", "editable": False},
        {"id": "FW-0002", "status": "fixed", "title": LONG[:80]}]}
    body = (f"FILE = {json.dumps(file)}; const st = {{ attributes: {json.dumps(sens)} }};\n"
            "const c = new FlightWatcherTicketsCard(); c.setConfig({}); c._render = () => {};\n"
            "const before = c._tickets(st).map((t) => t.id);\n"
            "await new Promise((r) => setTimeout(r, 10));\n"
            "const after = c._tickets(st);\n"
            "const again = FETCHED.length;\n"
            "const noKey = new FlightWatcherTicketsCard(); noKey.setConfig({});\n"
            "const nk = noKey._tickets({ attributes: { ...st.attributes, file_key: null } }).map((t) => t.id);\n"
            "const older = c._tickets({ attributes: { tickets: [{ id: 'FW-0009', narrative: 'x' }] } }).map((t) => t.id);\n"
            "console.log(JSON.stringify([before, after, FETCHED, again, nk, older]));")
    before, after, fetched, again, nk, older = _node(tmp_path, "flight-watcher-tickets-card.js", body)
    assert before == ["FW-0004", "FW-0003", "FW-0002"]  # the sensor's rows until the file is in
    assert [(t["id"], t["status"], t["title"], t.get("narrative")) for t in after] == [
        ("FW-0004", "new", "Brand new", None), ("FW-0003", "triaged", "New title", "Full text"),
        ("FW-0002", "fixed", LONG, "b"), ("FW-0001", "closed", "A", "a")]  # a title the sensor cut: the file's whole one
    assert fetched == [f"/local/flight-watcher/tickets_{KEY}.json?r=abc"] and again == 1
    assert nk == ["FW-0004", "FW-0003", "FW-0002"] and older == ["FW-0009"]


def test_schedule_card_versions_from_the_file(tmp_path):
    vmonths = {"2026-11": {"count": 2, "current": "11.002", "awarded": "11.001",
                           "versions": [{"ver": "11.001", "items": []}, {"ver": "11.002", "items": []}]}}
    sens = {"file_key": KEY, "rev": "r1", "months": {"2026-11": {"count": 2, "current": "11.002", "awarded": "11.001"}}}
    body = (f"FILE = {json.dumps({'months': vmonths})};\n"
            f"const c = new FlightWatcherScheduleCard(); c.setConfig({{}}); let redraws = 0;\n"
            f"c._h = {{ states: {{ 'sensor.flight_watcher_schedule_versions': {{ attributes: {json.dumps(sens)} }} }} }};\n"
            "Object.defineProperty(c, 'hass', { set() { redraws++; } });\n"
            "const first = (c._vmonths()['2026-11'] || {}).versions || [];\n"
            "await new Promise((r) => setTimeout(r, 10));\n"
            "const then = c._vmonths()['2026-11'].versions.map((v) => v.ver);\n"
            "console.log(JSON.stringify([first.length, then, FETCHED, redraws]));")
    n0, then, fetched, redraws = _node(tmp_path, "flight-watcher-schedule-card.js", body)
    assert n0 == 0 and then == ["11.001", "11.002"] and redraws == 1
    assert fetched == [f"/local/flight-watcher/versions_{KEY}.json?r=r1"]


def test_recall_card_adds_the_older_days_from_the_file(tmp_path):
    file = {"days": [{"date": "2026-11-06", "verdicts": [{"id": "a", "act": {"status": "new"}}]},
                     {"date": "2026-11-05", "verdicts": []}, {"date": "2026-10-01", "verdicts": [{"id": "old"}]}]}
    sens = {"file_key": KEY, "rev": "r", "days": [{"date": "2026-11-06", "verdicts": [{"id": "a", "act": {"status": "approved"}}]},
                                                  {"date": "2026-11-05", "verdicts": []}]}
    body = (f"FILE = {json.dumps(file)}; const st = {{ attributes: {json.dumps(sens)} }};\n"
            "const c = new FlightWatcherRecallCard(); c.setConfig({});\n"
            "c._days(st); await new Promise((r) => setTimeout(r, 10));\n"
            "const d = c._days(st);\n"
            "console.log(JSON.stringify([d.map((x) => x.date), d[0].verdicts[0].act.status]));")
    dates, status = _node(tmp_path, "flight-watcher-recall-card.js", body)
    assert dates == ["2026-11-06", "2026-11-05", "2026-10-01"] and status == "approved"  # the sensor's day wins

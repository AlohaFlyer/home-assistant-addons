"""1.7.17 (Ryan, Nov 17: tag the pot trips whose report and release times line up with his commutes; he chose the
existing commute check and its smart.json timetables, no new windows). Each pot and Tradeboard sensor row
carries cm: the airports smart.comm passed both ways (two scheduled nonstops arriving HNL before report, PWA 26.QQ.2;
one home 60+ min after release, same day; the customs release, PWA 2.19.b, as far.py's sure / worst rule), in the
config's order. Nothing when none passes, when one is only unknown, or when smart.json has no timetables: never a guess.
The full comm object stays off the sensors (SENSOR_DROP), the pot sensor stays under its cap, the pot card shows a chip
("Commutable KOA LAS"), the portal passes it through as signed (no contract change). No FLICA load.
Synthetic only: made-up timetables for KOA and LAS, made-up pairings, "Doe, Jane"."""
import hashlib
import json
import os
import sys
from datetime import date, datetime

import pytest

import cards
import pot as P
import portal as PT
import roles as ROLES
import smart as SM
from test_fw171_cards import _browser, _card, _page as _portal_page, _pilot, _s
from test_layover_card import HA_DARK, HA_LIGHT
from test_sensor_size import HA_OWN, LIMIT, _pot_row
from test_smart import ROW, months

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("FW_ITEM8_SHOTS", "")  # a folder: the chip renders are saved there as item8_*.png
FIXTURE_SHA = "a066d935367dfc736383bb4a6b1fa71d114fee26defcb2de8479695759ed2ec9"

# made-up timetables (HST): KOA arrivals 05:45, 06:25, 09:45; LAS arrivals 09:40, 10:50
RAW = {"v": 1, "updated": "2030-01-01", "source": "synthetic", "airports": ["KOA", "LAS"],
       "in": {"KOA": {"dep": ["05:00", "05:40", "09:00"], "block_max": 45},
              "LAS": {"dep": ["03:30", "04:40"], "block_max": 370}},
       "home": {"KOA": ["12:00", "18:30"], "LAS": ["13:30", "22:00"]},
       "home_gap_min": 60}
CFG = SM.normalize(RAW)


def at(d, hm):
    return datetime(2030, 3, d, int(hm[:2]), int(hm[3:]))


# ---------------------------------------------------------------- the tag from comm()'s result
def test_the_tag_is_the_airports_comm_passed_both_ways():
    assert SM.comm_tag("KOA/LAS") == ["KOA", "LAS"] and SM.comm_tag("LAS") == ["LAS"]
    for none in ("No", "", None, "?", 0):
        assert SM.comm_tag(none) == [], none
    # only three-letter codes, once each, in the order given (the config's)
    assert SM.comm_tag("KOA/<b>/koa/LAS/KOA") == ["KOA", "LAS"]


def test_commutable_both_ways_from_both_airports():
    r, _ = SM.comm(at(24, "11:30"), at(24, "13:15"), CFG)
    assert r == "KOA/LAS" and SM.comm_tag(r) == ["KOA", "LAS"]


def test_one_way_only_is_never_tagged():
    # IN from KOA (05:45, 06:25), none from LAS: KOA only, LAS's home flight alone does not tag it
    r, why = SM.comm(at(24, "08:30"), at(24, "13:15"), CFG)
    assert r == "KOA" and SM.comm_tag(r) == ["KOA"] and "LAS in 0 (needs 2), home 22:00" in why
    # in both ways, no flight home 60 min after a 21:45 release: no tag
    r, why = SM.comm(at(24, "11:30"), at(24, "21:45"), CFG)
    assert r == "No" and SM.comm_tag(r) == [] and "KOA in 3 by 09:45, no home" in why
    # home both ways, one arrival before a 06:00 report: no tag
    r, why = SM.comm(at(24, "06:00"), at(24, "13:15"), CFG)
    assert r == "No" and SM.comm_tag(r) == [] and "KOA in 1 by 05:45 (needs 2), home 18:30" in why


def test_no_timetables_no_tag():
    for raw in ({"v": 1, "airports": ["KOA", "LAS"]},
                dict(RAW, home={}),  # IN tables only
                dict(RAW, **{"in": {}}),  # home tables only
                {"v": 2, **{k: v for k, v in RAW.items() if k != "v"}}):  # another format: not read
        r, why = SM.comm(at(24, "11:30"), at(24, "13:15"), SM.normalize(raw))
        assert (r, why) == ("", "") and SM.comm_tag(r) == [], raw
    assert SM.comm_tag(SM.comm(at(24, "11:30"), at(24, "13:15"), {})[0]) == []


# ---------------------------------------------------------------- the Watcher: pot and Tradeboard sensors
class NoFlica:
    """A FLICA session that fails the test on any page load."""

    def fetch(self, url, *a, **k):
        raise AssertionError(f"FLICA page load: {url}")


def _w(tmp_path, monkeypatch, smart=RAW, instance="", real_pub=False):
    data = tmp_path / ("data_" + (instance or "default"))
    data.mkdir(parents=True, exist_ok=True)
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "category_check": "HNL 332 FO"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    real = W.SMART_FILE
    monkeypatch.setattr(W, "DB", Store(str(data / "t.db")))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2030, 3, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2030, 3, 2)))
    share = tmp_path / "share" / (instance or "")
    share.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(W, "SMART_FILE", str(share / "smart.json"))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(data / "www"))
    if smart is not None:
        (share / "smart.json").write_text(smart if isinstance(smart, str) else json.dumps(smart))
    W.S["schedule"] = months()
    sent = []
    if not real_pub:  # else watcher.pub itself: cap_attrs, then MQ.publish
        monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    return W, sent, real


def _pot(W, pairing, report, arrive, route=""):
    """A pot row of 24Mar 2030 through pot_details, its details cached (no page load)."""
    k = f"{pairing}|24Mar"
    W.S.setdefault("details", {})[k] = {"crew": [], "duties": [], "report": report, "captain": "Doe, Jane (10001)",
                                        "route": route}
    pot = {k: dict(ROW, pairing=pairing, arrive=arrive)}
    W.pot_details(NoFlica(), pot)
    return pot[k]


def _sensor(sent, topic="pot/state"):
    return {r["pairing"]: r for r in [p for t, p in sent if t == topic][-1]["pairings"]}


def test_pot_sensor_rows_carry_the_tag_and_nothing_else_of_the_commute(tmp_path, monkeypatch):
    W, sent, _ = _w(tmp_path, monkeypatch)
    rows = [_pot(W, "H9301", "11:30", "13:00"),  # both airports both ways
            _pot(W, "H9302", "08:30", "13:00"),  # KOA only (no LAS arrival before report)
            _pot(W, "H9303", "11:30", "21:30"),  # in, but no flight home: not tagged
            _pot(W, "H9304", "06:00", "13:00")]  # home, but one arrival: not tagged
    assert [r["comm"] for r in rows] == ["KOA/LAS", "KOA", "No", "No"]
    W.publish_pot([dict(r, month="2030-03") for r in rows])
    s = _sensor(sent)
    assert s["H9301"]["cm"] == ["KOA", "LAS"] and s["H9302"]["cm"] == ["KOA"]
    assert "cm" not in s["H9303"] and "cm" not in s["H9304"]
    for r in s.values():  # the full comm object and the other smart fields stay off (SENSOR_DROP)
        assert not set(W.SMART_FIELDS) & set(r) and "far_why" not in r
    # the rest of the row is byte for byte what the sensor carried before 1.7.17
    assert {k: v for k, v in s["H9301"].items() if k != "cm"} == {k: v for k, v in dict(rows[0], month="2030-03").items()
                                                                  if k not in W.SENSOR_DROP}
    assert "cm" not in rows[0]  # the row itself (the DB, the finds files, the push) keeps comm, not the tag


def test_customs_release_from_a_us_station_and_from_abroad(tmp_path, monkeypatch):
    """Block-in 17:15, KOA's last flight home 18:30, LAS's 22:00. A last leg from a US station releases 17:30 (PWA
    2.19.b) and makes KOA's exactly; one from abroad releases 17:45 (customs) and does not; one whose origin is not on
    file is judged both ways and KOA is unknown, never tagged (never a guess). LAS makes it every way."""
    W, sent, _ = _w(tmp_path, monkeypatch)
    us = _pot(W, "H9311", "11:30", "17:15", route="HNL-SFO-HNL")
    las = _pot(W, "H9312", "11:30", "17:15", route="HNL-LAS-HNL")
    abroad = _pot(W, "H9313", "11:30", "17:15", route="HNL-SYD-HNL")
    unknown = _pot(W, "H9314", "11:30", "17:15")
    assert (us["comm"], las["comm"], abroad["comm"], unknown["comm"]) == ("KOA/LAS", "KOA/LAS", "LAS", "LAS")
    assert "(customs, PWA 2.19.b)" in abroad["comm_why"] and "only if no customs" in unknown["comm_why"]
    W.publish_pot([dict(r, month="2030-03") for r in (us, las, abroad, unknown)])
    s = _sensor(sent)
    assert [s[p]["cm"] for p in ("H9311", "H9312", "H9313", "H9314")] == [["KOA", "LAS"], ["KOA", "LAS"], ["LAS"], ["LAS"]]
    # the pilot's smart.json "domestic" makes a station a no-customs origin
    W2, sent2, _ = _w(tmp_path / "dom", monkeypatch, smart=dict(RAW, domestic=["ZZZ"]))
    r = _pot(W2, "H9315", "11:30", "17:15", route="HNL-ZZZ-HNL")
    W2.publish_pot([r])
    assert _sensor(sent2)["H9315"]["cm"] == ["KOA", "LAS"]


@pytest.mark.parametrize("smart", [None, {"v": 1, "airports": ["KOA", "LAS"]}, "{not json", ""])
def test_no_timetables_no_tag_on_the_sensors(tmp_path, monkeypatch, smart):
    W, sent, _ = _w(tmp_path, monkeypatch, smart=smart)
    row = _pot(W, "H9301", "11:30", "13:00")
    assert row["comm"] == ""
    W.publish_pot([row])
    W.publish_tradeboard({"000000001|H9303": dict(ROW, pairing="H9303", report="11:30", comm="KOA/LAS", src="T")})
    assert "cm" not in _sensor(sent)["H9301"] and "cm" not in _sensor(sent, "tradeboard/state")["H9303"]


def test_the_tradeboard_carries_the_same_tag_read_fresh(tmp_path, monkeypatch):
    """A post's enriched row (tb_details) keeps the comm of its read; the sensor's tag is judged again from the
    timetables on hand every publish (no FLICA load), so a smart.json edit reaches it like the pot's."""
    W, sent, _ = _w(tmp_path, monkeypatch)
    post = dict(ROW, pairing="H9321", report="11:30", source="tradeboard", poster="Doe, Jane", comm="No", comm_why="x")
    W.publish_tradeboard({"000000001|H9321": post, "000000002|H9322": dict(ROW, pairing="H9322", report="08:30")})
    s = _sensor(sent, "tradeboard/state")
    assert s["H9321"]["cm"] == ["KOA", "LAS"] and s["H9322"]["cm"] == ["KOA"]
    assert s["H9321"]["src"] == "T" and not set(W.SMART_FIELDS) & set(s["H9321"]) and "far_why" not in s["H9321"]
    assert post["comm"] == "No"  # the cached post is not changed
    (tmp_path / "share" / "smart.json").write_text(json.dumps(dict(RAW, airports=["LAS"])))
    W.publish_tradeboard({"000000001|H9321": post})
    assert _sensor(sent, "tradeboard/state")["H9321"]["cm"] == ["LAS"]


def test_both_instances_read_their_own_smart_json(tmp_path, monkeypatch):
    """Ryan's instance and a second pilot's: each its own smart.json (never the other's) and its own MQTT prefix."""
    W, sent, real = _w(tmp_path, monkeypatch)
    assert real == "/share/flight_watcher/smart.json" and W.T == "flight_watcher"
    W.publish_pot([_pot(W, "H9301", "11:30", "13:00")])
    assert _sensor(sent)["H9301"]["cm"] == ["KOA", "LAS"]
    W2, sent2, real2 = _w(tmp_path, monkeypatch, smart=dict(RAW, airports=["LAS"]), instance="pilot2")
    assert real2 == "/share/flight_watcher/pilot2/smart.json" and W2.T == "flight_watcher_pilot2"
    assert W2.SMART_FILE != W.SMART_FILE
    W2.publish_pot([_pot(W2, "H9301", "11:30", "13:00")])
    assert _sensor(sent2)["H9301"]["cm"] == ["LAS"]
    W3, sent3, _ = _w(tmp_path / "none", monkeypatch, smart=None, instance="pilot2")  # his file gone: no tag
    W3.publish_pot([_pot(W3, "H9301", "11:30", "13:00")])
    assert "cm" not in _sensor(sent3)["H9301"]


# ---------------------------------------------------------------- review F2: close-in rows between reads
CI_REG = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
CI_PAGE = ("<html><body>Mar 2030 Open Time as of: 03/02 09:00 HA [HNL 332 FO] <table><tr><td>H9331</td></tr></table>"
           "[HNL 332 FO]</body></html>")


def test_close_in_rows_between_reads_are_judged_again_from_smart_json(tmp_path, monkeypatch):
    """1.7.17 review (F2): hunting, the close-in page is read at most every CLOSE_IN_READ_S, and between reads (or
    after a failed read) the last good read's rows are used. Their commute is judged again from smart.json on hand
    each time, as the regular pot's rows are: an edit or removal of the file reaches their cm with no page load, and a
    tag is never kept without timetables."""
    W, sent, _ = _w(tmp_path, monkeypatch)
    now = [1_000_000.0]
    monkeypatch.setattr(W.time, "time", lambda: now[0])
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    W.S["pot_urls"] = {"mobile": CI_REG}
    W.S["close_in"] = {"bcid": "008.152", "verified": True, "menu_at": now[0], "via": "left menu"}
    k = "H9331|24Mar"
    W.S.setdefault("details", {})[k] = {"crew": [], "duties": [], "report": "11:30", "captain": "Doe, Jane (10001)",
                                        "route": ""}
    monkeypatch.setattr(W, "parse_pot", lambda html: {k: dict(ROW, pairing="H9331", arrive="13:00")})
    fetched, fail = [], [False]

    class FL:  # a synthetic folder page; never FLICA
        def fetch(self, url, *a, **kw):
            fetched.append(url)
            if fail[0]:
                raise RuntimeError("synthetic fetch failure")
            return CI_PAGE

    fl, smart = FL(), tmp_path / "share" / "smart.json"
    W.FLAGS["hunt"] = True

    def cm():
        rows, kind = W.close_in_check(fl, {"mobile": {}})
        assert kind == "ok" and list(rows) == [k]
        W.publish_pot([dict(v, month=W.CLOSE_IN_KEY) for v in rows.values()])
        return rows[k], _sensor(sent)["H9331"].get("cm")

    row, tag = cm()  # the good read
    assert len(fetched) == 1 and row["comm"] == "KOA/LAS" and tag == ["KOA", "LAS"]
    smart.write_text(json.dumps(dict(RAW, airports=["LAS"])))  # an edit: LAS only
    now[0] += 60
    row, tag = cm()  # between reads (hunting): no page load, the edit reaches the tag
    assert len(fetched) == 1 and row["comm"] == "LAS" and tag == ["LAS"]
    smart.unlink()  # the file removed: no timetables, no tag
    now[0] += 60
    row, tag = cm()
    assert len(fetched) == 1 and row["comm"] == "" and row["comm_why"] == "" and tag is None
    fail[0] = True  # a failed read after CLOSE_IN_READ_S: the cached rows, judged again, still no tag
    now[0] += W.CLOSE_IN_READ_S
    row, tag = cm()
    assert len(fetched) == 2 and row["comm"] == "" and tag is None
    for _ in range(3):  # reads that keep failing: never the old tag back from the cache
        now[0] += W.CLOSE_IN_READ_S
        assert cm()[1] is None
    smart.write_text(json.dumps(RAW))  # the file back: the cached row is tagged again from it, still no page load
    n = len(fetched)
    now[0] += W.CLOSE_IN_READ_S
    row, tag = cm()
    assert len(fetched) == n + 1 and row["comm"] == "KOA/LAS" and tag == ["KOA", "LAS"]
    assert not any(set(W.SMART_FIELDS) & set(r) for r in [p for t, p in sent if t == "pot/state"][-1]["pairings"])


class Rec:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.msgs.append((topic, payload))


def _published_pot(W, rows):
    rec = Rec()
    W.MQ = rec
    W.publish_pot(rows)
    return json.loads([p for t, p in rec.msgs if t.endswith("/pot/state")][-1])


def test_a_worst_case_pot_stays_under_the_cap(tmp_path, monkeypatch):
    """60 pot rows as big as the busiest synthetic ones (crew, detail URL, a long captain; test_sensor_size), every one
    commutable from both airports: the sensor stays at or under ATTR_MAX (under 12 KB as HA stores it), every row it
    keeps has its tag, and the tag costs at most one row of the 19 the busiest pot kept before (two of 36 lighter
    rows), the rows cap_attrs cuts from the end as it does today."""
    W, _, _ = _w(tmp_path, monkeypatch, real_pub=True)
    big = [dict(_pot_row(i), comm="KOA/LAS", comm_why="w" * 240, value=6123, month_rule="OK", b672="97:59",
                b672_ok=True, far_why="f" * 400) for i in range(60)]
    plain = [{k: v for k, v in r.items() if k != "comm"} for r in big]
    tagged, before = _published_pot(W, big), _published_pot(W, plain)
    n = len(json.dumps(tagged, separators=(",", ":")))
    assert n <= W.ATTR_MAX and n + HA_OWN <= LIMIT
    assert all(r["cm"] == ["KOA", "LAS"] for r in tagged["pairings"]) and tagged["count"] == 60
    kept, kept0 = len(tagged["pairings"]), len(before["pairings"])
    assert tagged["trimmed"] == 60 - kept and kept >= kept0 - 1 and kept >= 15, (kept, kept0)
    assert not any(set(W.SMART_FIELDS) & set(r) or "far_why" in r for r in tagged["pairings"])
    assert (kept0, kept) == (19, 18)  # the numbers the CHANGELOG and CM_KEY's note give
    # a lighter row (no crew list, URL or captain read yet): 36 rows fit untagged, 34 with every row tagged
    light = [{k: v for k, v in r.items() if k not in ("crew", "detail_url", "captain", "route")} for r in big]
    p = _published_pot(W, light)
    p0 = _published_pot(W, [{k: v for k, v in r.items() if k != "comm"} for r in light])
    assert len(json.dumps(p, separators=(",", ":"))) <= W.ATTR_MAX and all(r["cm"] == ["KOA", "LAS"] for r in p["pairings"])
    assert (len(p0["pairings"]), len(p["pairings"])) == (36, 34)
    # the cost is the tag alone, about 19 bytes a row, and only on a row commutable both ways
    row = W.sensor_row(big[0])
    assert len(json.dumps(row, separators=(",", ":"))) - len(json.dumps(W.sensor_row(plain[0]), separators=(",", ":"))) \
        == len(',"cm":["KOA","LAS"]') == 19
    # a pilot's smart.json with ten airports, every one passing: still capped (cap_attrs cuts rows, never the cap)
    ten = [dict(r, comm="/".join(f"A{c}A" for c in "BCDEFGHIJK")) for r in big]
    p = _published_pot(W, ten)
    assert len(json.dumps(p, separators=(",", ":"))) <= W.ATTR_MAX and len(p["pairings"][0]["cm"]) == 10


# ---------------------------------------------------------------- the portal: passed through as signed
def test_the_portal_passes_the_tag_through_without_a_contract_change():
    """state.json masks only contact (dropped) and the www file keys (zeroed): a new attribute on an exported state is
    served as signed, so a portal pilot's pot card reads cm with no contract change. The fixture is unchanged."""
    attrs = {"count": 2, "pairings": [{"pairing": "H9301", "cm": ["KOA", "LAS"]}, {"pairing": "H9302"}]}
    e = PT.state_entry({"state": "2", "attributes": attrs, "context": {"id": "x"}, "last_changed": "a", "last_updated": "b"})
    assert e["attributes"] == attrs and "context" not in e
    assert "cm" not in PT.MASK_ZERO + PT.MASK_DROP
    for pilot in ("pilot2", "james"):
        assert ROLES.entity_on_portal("pot_count", pilot) and ROLES.entity_on_portal("tradeboard", pilot)
    fx = os.path.join(HERE, "tests", "fixtures", "portal_contract_v1.json")
    assert hashlib.sha256(open(fx, "rb").read()).hexdigest() == FIXTURE_SHA
    assert PT.contract_text() == open(fx, encoding="utf-8").read()
    # the pilot's copy of the pot card is the admin's with his prefix: it reads the same attribute
    built = cards.build("9.9.9", ["pilot2"])
    assert "p.cm" in built["flight-watcher-pot-card-pilot2.js"] and "p.cm" in built["flight-watcher-pot-card.js"]


# ---------------------------------------------------------------- the pot card's chip
POT = [{"pairing": "H9301", "start": "24Nov", "end": "24Nov", "dates": "24Nov", "days": "1", "layover": "-none-",
        "turn": "OGG", "credit": "6:00", "soft": "0:30", "report": "11:30", "captain": "Doe, Jane", "fit": "Fits",
        "far": "OK", "vac": False, "blocked": False, "cm": ["KOA", "LAS"]},
       {"pairing": "H9302", "start": "25Nov", "end": "27Nov", "dates": "25Nov-27Nov", "days": "3", "layover": "LAX",
        "credit": "16:30", "soft": "1:10", "report": "08:30", "captain": "Roe, Max", "fit": "Conflict H9100",
        "far": "Rest 8:00 before", "vac": False, "blocked": False, "cm": ["KOA"]},
       {"pairing": "H9303", "start": "26Nov", "end": "26Nov", "dates": "26Nov", "days": "1", "layover": "-none-",
        "turn": "LIH", "credit": "5:10", "report": "06:00", "fit": "Fits", "far": "OK (CBA rest 10:30)",
        "vac": False, "blocked": False},
       {"pairing": "H9304", "start": "27Nov", "end": "27Nov", "dates": "27Nov", "days": "1", "layover": "-none-",
        "turn": "KOA", "credit": "5:00", "fit": "Fits", "far": "OK", "vac": False, "blocked": False,
        "cm": ["<img src=x onerror=window.pwned=1>", "LAS", "las", 7, None]},
       {"pairing": "H9305", "start": "28Nov", "end": "28Nov", "dates": "28Nov", "days": "1", "layover": "-none-",
        "turn": "ITO", "credit": "5:00", "fit": "Fits", "far": "OK", "vac": False, "blocked": False, "cm": []}]
TB = [{"pairing": "H9306", "start": "29Nov", "end": "30Nov", "dates": "29Nov-30Nov", "days": "2", "layover": "SFO",
       "credit": "12:00", "soft": "2:00", "fit": "Fits", "far": "OK", "vac": False, "blocked": False, "src": "T",
       "cm": ["LAS"]}]


def _states(pot=POT, tb=TB):
    return _pilot({"sensor.flight_watcher_pot_count": _s(str(len(pot)), {"count": len(pot), "pairings": pot}),
                   "sensor.flight_watcher_tradeboard_pickups": _s(str(len(tb)), {"count": len(tb), "pairings": tb}),
                   "sensor.flight_watcher_last_check": _s("2026-11-10T11:29:00+00:00"),
                   "sensor.flight_watcher_state": _s("hunting", {"role": "pilot", "doh": "2016-03-02"}),
                   "input_number.flight_watcher_longevity_year": _s("5")})


CM_JS = """(st) => { const c = mount('flight-watcher-pot-card-pilot2', {}, st); const r = c.shadowRoot;
  const chips = (x) => [...x.querySelectorAll('.c.cm')].map((s) => ({text: s.textContent, title: s.title,
    w: s.getBoundingClientRect().width, cls: s.className}));
  const rows = {}; for (const x of r.querySelectorAll('.r')) rows[x.querySelector('.trip').textContent] = chips(x);
  return {rows, key: [...r.querySelectorAll('details')].map((d) => d.textContent.replace(/\\s+/g, ' ')).join(' | '),
          img: r.querySelectorAll('img').length, pwned: !!window.pwned, fit: fwFits(c), contrast: fwContrast(c)}; }"""


def _shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"item8_{name}.png"), full_page=True)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_pot_card_shows_the_commutable_chip_at_390(scheme):
    with _browser() as b:
        pg = _portal_page(b, [_card("pot-card")], width=390, scheme=scheme)
        got = pg.evaluate(CM_JS, _states())
        _shot(pg, f"portal_390_{scheme}")
        opened = pg.evaluate("() => { const c = document.querySelector('flight-watcher-pot-card-pilot2');"
                             " for (const d of c.shadowRoot.querySelectorAll('details')) d.open = true;"
                             " return {contrast: fwContrast(c), fit: fwFits(c)}; }")
        _shot(pg, f"portal_390_{scheme}_key")
        none = _portal_page(b, [_card("pot-card")], scheme=scheme).evaluate(
            CM_JS, _states([{k: v for k, v in r.items() if k != "cm"} for r in POT], []))
    rows = got["rows"]
    assert [c["text"] for c in rows["H9301"]] == ["Commutable KOA LAS"]
    assert [c["text"] for c in rows["H9302"]] == ["Commutable KOA"]
    assert rows["H9303"] == [] and rows["H9305"] == []
    assert [c["text"] for c in rows["H9304"]] == ["Commutable LAS"]  # only three-letter codes; nothing else is drawn
    assert got["img"] == 0 and not got["pwned"]
    assert [c["text"] for c in rows["H9306"]] == ["Commutable LAS"]  # the Tradeboard post, the same tag
    t = rows["H9301"][0]["title"]
    assert "KOA and LAS" in t and "PWA 26.QQ.2" in t and "smart.json" in t
    assert "Commutable" in got["key"] and "PWA 26.QQ.2" in got["key"] and "PWA 2.19.b" in got["key"]
    assert got["fit"]["page"] <= 390 and got["fit"]["inner"] <= 0 and got["fit"]["right"] <= 390
    assert got["contrast"]["fails"] == [], got["contrast"]["fails"]
    assert opened["contrast"]["fails"] == [] and opened["fit"]["page"] <= 390 and opened["fit"]["inner"] <= 0
    # no tag anywhere (no smart.json, or no commutable trip): no chip and no key line about it
    assert all(v == [] for v in none["rows"].values()) and "Commutable" not in none["key"]


@pytest.mark.parametrize("theme,name", [(HA_LIGHT, "light"), (HA_DARK, "dark")])
def test_the_admins_pot_card_shows_the_chip_on_home_assistants_theme(theme, name):
    """The admin's own copy (Home Assistant) on HA's light and dark themes, 390 px."""
    src = cards.build("9.9.9")["flight-watcher-pot-card.js"]
    st = {k.replace("flight_watcher_pilot2_", "flight_watcher_", 1): v for k, v in _states().items()}
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>body{margin:0;padding:8px 16px;"
            f"font-family:Roboto,sans-serif;{theme}}}</style></head><body><script>"
            "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); "
            "this.attachShadow({mode: 'open'}).innerHTML = '<style>:host{display:block;background:var(--card-background-color);"
            "border-radius:12px}</style><slot></slot>'; } });</script><script>" + src + "</script><script>"
            "const c = document.createElement('flight-watcher-pot-card'); c.setConfig({}); document.body.appendChild(c);"
            f"c.hass = {{states: {json.dumps(st)}, themes: {{darkMode: {'true' if name == 'dark' else 'false'}}},"
            " callService: () => {}};</script></body></html>")
    with _browser() as b:
        pg = b.new_page(viewport={"width": 390, "height": 900})
        pg.set_content(html)
        got = pg.evaluate("""() => { const c = document.querySelector('flight-watcher-pot-card'), r = c.shadowRoot;
          return {chips: [...r.querySelectorAll('.c.cm')].map((s) => [s.textContent, getComputedStyle(s).color]),
                  dark: c.hasAttribute('dark'), wide: document.documentElement.scrollWidth}; }""")
        _shot(pg, f"ha_390_{name}")
    assert [c[0] for c in got["chips"]] == ["Commutable KOA LAS", "Commutable KOA", "Commutable LAS", "Commutable LAS"]
    assert got["dark"] == (name == "dark") and got["wide"] <= 390
    # the ok color of each theme (F#119: lighter on dark cards)
    assert {c[1] for c in got["chips"]} == {"rgb(129, 199, 132)" if name == "dark" else "rgb(46, 125, 50)"}


KEY_JS = """(st) => { const c = mount('flight-watcher-pot-card-pilot2', {}, st); const r = c.shadowRoot;
  for (const d of r.querySelectorAll('details')) d.open = true;
  return [...r.querySelectorAll('details li')].map((li) => li.textContent.replace(/\\s+/g, ' ')).filter((t) =>
    t.startsWith('Commutable')); }"""


def test_the_key_gives_the_pilots_home_gap_not_a_fixed_60(tmp_path, monkeypatch):
    """1.7.17 review (F1): the commute check's home flight is the pilot's smart.json home_gap_min (0 to 600; 60 unless
    set) after release, so the chip's Key (and the README) never promise a fixed 60 min: with a 45 min gap a trip
    whose home flight is 50 min after release is tagged, with 90 one 70 min after is not."""
    gap45, gap90 = SM.normalize(dict(RAW, home_gap_min=45)), SM.normalize(dict(RAW, home_gap_min=90))
    tag = lambda rel, cfg: SM.comm_tag(SM.comm(at(24, "11:30"), at(24, rel), cfg)[0])  # noqa: E731
    assert tag("21:10", gap45) == ["LAS"] and tag("21:10", CFG) == []  # LAS home 22:00, 50 min after release
    assert tag("20:50", gap90) == [] and tag("20:50", CFG) == ["LAS"]  # 70 min after: not with a 90 min gap
    with _browser() as b:
        key = _portal_page(b, [_card("pot-card")]).evaluate(KEY_JS, _states())
    assert len(key) == 1, key
    assert "home_gap_min" in key[0] and "60 min unless set" in key[0] and "60+" not in key[0], key[0]
    assert "PWA 26.QQ.2" in key[0] and "PWA 2.19.b" in key[0]
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    assert "home 60+ min after release" not in readme and "`home_gap_min` after release" in readme


FAR_ROWS = [  # the FAR chip "c warn" (CBA rest) beside Fits and the commute chip
    {"pairing": "H9401", "start": "24Nov", "dates": "24Nov", "days": "1", "layover": "-none-", "turn": "LIH",
     "credit": "5:10", "report": "06:00", "fit": "Fits", "far": "OK (CBA rest 10:30)", "vac": False, "blocked": False,
     "cm": ["KOA"]},
    {"pairing": "H9402", "start": "25Nov", "dates": "25Nov", "days": "1", "layover": "-none-", "turn": "OGG",
     "credit": "5:00", "fit": "Fits", "far": "OK", "vac": False, "blocked": False, "cm": ["KOA"]},
    {"pairing": "H9403", "start": "26Nov", "dates": "26Nov", "days": "1", "layover": "-none-", "turn": "ITO",
     "credit": "5:00", "fit": "Fits", "far": "OK (CBA rest 10:30)", "vac": False, "blocked": False}]
CHIP_JS = """(st) => { const c = mount('flight-watcher-pot-card-pilot2', {}, st); const r = c.shadowRoot, out = {};
  for (const x of r.querySelectorAll('.r')) out[x.querySelector('.trip').textContent] =
    [...x.querySelectorAll('.l3 .c')].map((s) => { const b = s.getBoundingClientRect(), cs = getComputedStyle(s);
      return {text: s.textContent, h: b.height, m: cs.marginTop + ' ' + cs.marginBottom, bg: cs.backgroundColor}; });
  const w = r.querySelector('div.warn'), ws = w && getComputedStyle(w);
  return {rows: out, banner: w ? {m: ws.marginTop + ' ' + ws.marginBottom, bg: ws.backgroundColor,
    bl: ws.borderLeftWidth} : null}; }"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_far_chip_keeps_the_chip_size_beside_the_commute_chip(scheme):
    """1.7.17 review: the stale-pot banner's rule (margin, tint) is the banner's only (div.warn), not the FAR chip's
    ("c warn", CBA rest): every chip on a row's line is one chip high, so "Commutable KOA" beside a CBA rest chip is
    not stretched with its text at the top. The banner keeps its look."""
    st = _states(FAR_ROWS, [])
    st[next(k for k in st if k.endswith("_last_check"))] = _s("2026-11-01T00:00:00+00:00")  # stale: the banner shows
    with _browser() as b:
        pg = _portal_page(b, [_card("pot-card")], width=390, scheme=scheme)
        got = pg.evaluate(CHIP_JS, st)
        _shot(pg, f"fix_far_chip_390_{scheme}")
    rows = got["rows"]
    assert [c["text"] for c in rows["H9401"]] == ["Fits", "FAR OK (CBA rest 10:30)", "Commutable KOA"]
    hs = [c["h"] for r in rows.values() for c in r]
    assert max(hs) - min(hs) < 0.5 and max(hs) < 24, rows
    far = rows["H9401"][1]
    assert far["m"] == "0px 0px" and far["bg"] == "rgba(0, 0, 0, 0)", far
    assert got["banner"] == {"m": "4px 6px", "bg": "rgba(178, 106, 0, 0.12)", "bl": "4px"}, got["banner"]


def test_no_em_dash_in_the_change():
    dash = chr(0x2014)
    for f in ("smart.py", "watcher.py", "www/flight-watcher-pot-card.js", "README.md", "tests/test_fw1717_comm_tag.py"):
        assert dash not in open(os.path.join(HERE, f), encoding="utf-8").read(), f

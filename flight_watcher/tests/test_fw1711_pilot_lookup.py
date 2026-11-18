"""1.7.11, the pilot lookup on both instances (Ryan's yes of Nov 17, 2026, naming FW-0078 and FW-0076).

FW-0078 (Ryan: "show up to 12 matches as Last, First, seat, base and employee #"): a name lookup lists up to
LOOKUP_MAX = 12 pilots (more is no list: "More than 12 pilots match ..."); each entry carries the name, the seat as
before (pick_seats), the base (the pilot database record's, else the award's or the seniority list's, else none) and
the employee number, shown only: on a pilot's instance the entry is still picked by its opaque pick id, never by the
number. The admin's pick list carries the base too.

FW-0076 (Ryan: "This month and next month buttons on the pilot lookup, on both instances. One FLICA load per tap,
inside the budget."): pilot/set takes an optional month (YYYY-MM), this HST month or the next only; any other is
refused with one log line and a status line. With a month only that month's Schedule Lookup page is read (bd=MMYY),
paced, then the pairing pages as before; the 6 h cache is per month; FW-0057's previous month follows the month read.
No month: exactly as before. Synthetic pilots only ("Doe, Jane", 10001)."""
import json
import logging
import re
from datetime import datetime

import pytest

import pdbshare as PS
import portal as PT
import roles
from test_fw1710_award_sen import award
from test_pilotdb_portal import james  # noqa: F401  (pilot james with a portal and Ryan's database)
from test_pilotdb_watcher import P as PW  # noqa: F401  (the admin's Watcher with a pilot database)
from test_crew_index import W  # noqa: F401  (the admin's Watcher, a test clock)
from test_release_a_lookup import load  # noqa: F401  (a pilot's or the admin's Watcher with files on hand)

NOV17 = datetime(2026, 11, 17, 10, 0)  # HST: FLICA's default month is already December (after the award)


def _ask(W, sent, **d):  # noqa: N803
    W.pilot_cmd(json.dumps(d))
    return [p for t, p in sent if t == "pilot_schedule"][-1]


def _dir(W, monkeypatch, rows):  # noqa: N803
    monkeypatch.setattr(W, "name_directory", lambda: rows)


def _doe(n, base="HNL"):
    """n namesakes 'Doe, <first>' with made-up numbers 10001 on."""
    firsts = ["Ann", "Bea", "Cal", "Dee", "Eve", "Fay", "Gus", "Hal", "Ida", "Jan", "Kai", "Lou", "Max", "Ned"]
    return [{"emp": str(10001 + i), "last": "Doe", "first": firsts[i], "seat": "FO" if i % 2 else "CA",
             "base": base if i % 3 else "", "name": f"Doe, {firsts[i]}"} for i in range(n)]


# ---------------------------------------------------------------- FW-0078: up to 12, with seat, base and number
def test_ten_namesakes_are_all_listed_with_seat_base_and_number(load, monkeypatch):  # noqa: F811
    W, sent = load()
    assert W.LOOKUP_MAX == 12
    rows = _doe(10)
    _dir(W, monkeypatch, rows)
    p = _ask(W, sent, q="Doe")
    assert p["emp"] == "" and p["status"] == "10 pilots match 'Doe', pick one" and not W.S.get("pilot_req")
    by = {m["emp"]: m for m in p["matches"]}
    assert len(p["matches"]) == 10 and set(by) == {r["emp"] for r in rows}
    for r in rows:
        m = by[r["emp"]]
        assert (m["name"], m["pos"]) == (r["name"], r["seat"])
        assert m.get("base", "") == r["base"]  # left out when no source has one
        assert re.fullmatch(r"[0-9a-f]{12}", m["pick"]) and m["pick"] != m["emp"]
    assert "base" not in by["10001"] and by["10002"]["base"] == "HNL"
    # the pick stays the opaque pick id: the number shown is never the pick, and the pick runs the lookup
    m = by["10005"]
    q = _ask(W, sent, pick=m["pick"], name=m["name"])
    assert (q["emp"], q["status"]) == ("10005", "loading") and W.S["pilot_req"]["emp"] == "10005"
    W.S.pop("pilot_req")
    with pytest.raises(PT.PortalError):  # the number is no pick (the shape takes 12 hex only)
        PT.check_shape("pilot/set", json.dumps({"pick": m["emp"]}))
    assert _ask(W, sent, pick="0" * 12, name=m["name"])["status"].startswith("That pick list is old")


def test_twelve_are_listed_and_thirteen_are_no_list(load, monkeypatch):  # noqa: F811
    W, sent = load()
    _dir(W, monkeypatch, _doe(12))
    p = _ask(W, sent, q="Doe")
    assert len(p["matches"]) == 12 and p["status"] == "12 pilots match 'Doe', pick one"
    _dir(W, monkeypatch, _doe(13))
    p = _ask(W, sent, q="Doe")
    assert p["matches"] == [] and p["status"].startswith("More than 12 pilots match 'Doe'. Type more of the last name")
    assert "Last, First" in p["status"] and "10001" not in json.dumps(p)
    # Last, First narrows it again
    p = _ask(W, sent, q="Doe, Ann")
    assert [(m["name"], m["emp"]) for m in p["matches"]] == [("Doe, Ann", "10001")]


def test_a_pilots_own_pilotdb_file_gives_the_base(james, monkeypatch, tmp_path):  # noqa: F811
    """On a portal pilot's instance the base comes from the record in his own pilotdb file (the award's category
    merged into the shared database as its domicile)."""
    W, db, root = james  # noqa: N806
    sent = []
    monkeypatch.setattr(W, "pub_pilot", lambda p: sent.append(p))
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    db.merge_award_sen("2026-12", [{"sen": 72, "emp": "10001", "last": "Doe", "base": "HNL", "equip": "332",
                                    "seat": "FO"}])
    db.new_record("10031", "Doe, Jane")
    db.set_share("james", True)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    W.pilot_cmd(json.dumps({"q": "Doe, Jane"}))
    ms = sent[-1]["matches"]
    assert sorted(m["emp"] for m in ms) == ["10001", "10031"]
    jane = next(m for m in ms if m["emp"] == "10001")
    assert jane["base"] == "HNL"  # the pilot database record's base (domicile from the award)


def test_the_base_comes_from_the_database_else_the_award_else_none(load, monkeypatch, tmp_path):  # noqa: F811
    W, sent = load()
    up = tmp_path / "uploads"
    # the award's seniority lines name a base (HNL-332-FO), its pilot lines do not
    (up / "2026-12_award.txt").write_text(award([(72, "HNL-332-FO", "DOE", 10001), (73, "LAX-321-CA", "DOE", 10002)]))
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    # the pilot database (here a pilot's own file rows) wins: 10002 is based in OGG there; 10021 has no base at all
    monkeypatch.setattr(W, "pilotdb_name_rows", lambda: ([("10002", "Doe", "John", "CA", "OGG"),
                                                          ("10021", "Doe", "Jill", "FO", "")], "file:x"))
    rows = {r["emp"]: r for r in W.name_directory()}
    assert rows["10001"]["base"] == "HNL"  # the award's line
    assert rows["10002"]["base"] == "OGG"  # the database's record over the award's
    assert rows["10021"]["base"] == ""  # none known: left out of the label
    assert rows["10004"]["base"] == ""  # the award's pilot line names no base
    p = _ask(W, sent, q="Doe")
    by = {m["emp"]: m for m in p["matches"]}
    assert by["10001"]["base"] == "HNL" and by["10002"]["base"] == "OGG" and "base" not in by["10021"]
    # a seniority list record that carries a base (the parser keeps one when a list prints it) is used too
    (up / "seniority.json").write_text(json.dumps({"pilots": {"10003": {"sen": 5, "name": "Doerr, Pat", "seat": "FO",
                                                                         "base": "HNL"}}}))
    W._SEN_CACHE.clear()
    assert {r["emp"]: r for r in W.name_directory()}["10003"]["base"] == "HNL"


def test_the_pilot_database_rows_carry_the_base(james):  # noqa: F811
    W, db, root = james  # noqa: N806
    db.merge_award_sen("2026-12", [{"sen": 72, "emp": "10001", "last": "Doe", "base": "HNL", "equip": "332",
                                    "seat": "FO"}])
    db.set_share("james", True)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    rows, sig = W.pilotdb_name_rows()
    by = {r[0]: r for r in rows}
    assert by["10001"] == ("10001", "Doe", "Jane A.", "FO", "HNL") and by["10002"][4] == "" and sig.startswith("file:")
    assert all(len(r) == 5 for r in db.name_rows())


def test_the_admin_pick_list_carries_the_base_and_the_number(PW, monkeypatch):  # noqa: F811
    W = PW  # noqa: N806
    db = W.pilotdb_start()
    sent = []
    monkeypatch.setattr(W, "pub_pilot", lambda p: sent.append(p))
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    db.new_record("10777", "Zoe, Zed")
    db.new_record("10778", "Zoe, Amy")
    db.merge_award_sen("2026-12", [{"sen": 9, "emp": "10777", "last": "Zoe", "base": "HNL", "equip": "332",
                                    "seat": "CA"}])
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    by = {m["emp"]: m for m in sent[-1]["matches"]}
    assert set(by) == {"10777", "10778"} and by["10777"]["base"] == "HNL" and "base" not in by["10778"]
    assert by["10777"]["name"] == "Zoe, Zed" and "pick" not in by["10777"]  # the admin picks by number, as before


def test_the_portal_masks_keep_the_pick_list_fields():
    """James's portal shows the pilot card from his Watcher's states: the pick list's emp and base pass the masks
    (only contact is dropped and the file keys zeroed; no mask changed for FW-0078)."""
    ms = [{"pick": "0123456789ab", "name": "Doe, Jane", "pos": "FO", "base": "HNL", "emp": "10001"}]
    e = PT.state_entry({"state": "x", "attributes": {"emp": "", "matches": ms, "contact": {"phones": ["x"]}}})
    assert e["attributes"]["matches"] == ms and "contact" not in e["attributes"]
    assert PT.MASK_DROP == ("contact",) and PT.MASK_ZERO == ("file_key", "versions_file_key")


# ---------------------------------------------------------------- FW-0076: the lookup's month
class MonthFl:
    """Fake FLICA: Schedule Lookup gives the month its bd names (MMYY); with no bd, FLICA's default month after the
    award (December). Pairing pages: a crew line."""

    def __init__(self, default_bd="1226"):
        self.urls, self.default_bd = [], default_bd

    def fetch(self, url):
        self.urls.append(url)
        if "cmschedules.cgi" in url:
            m = re.search(r"[?&]bd=(\d{4})", url)
            return cm_page(m.group(1) if m else self.default_bd)
        pid = url.split("PID=")[1].split("&")[0]
        return f"<html><p>pairing {pid.lower()} crew: ca 10999 roe, rick fo 10001 doe, jane ro open</p></html>"

    def sched(self):
        return [u for u in self.urls if "cmschedules.cgi" in u]


def cm_page(bd, emp="10999"):
    mm, yy = bd[:2], bd[2:]
    trip = f"H9{mm}1"
    return (f'<select><option value="{bd}" selected>x</option></select><script>'
            f'TAry[0]=new Task(1, "MO", "02", "{trip}", "LAX", "20{yy}{mm}01", 1, 0, \'{trip}\');'
            f'TAry[1]=new Task(1, "TU", "03", "", "-", "20{yy}{mm}01", 1, 0, \'\');'
            f'TAry[2]=new Task(1, "WE", "04", "", "HNL", "20{yy}{mm}01", 1, 0, \'\');</script>'
            f'<p>ROE, RICK (Emp# {emp}) Schedule Last Updated: Nov 4, 2026 10:00</p>'
            '<p>Block 21:00 Credit 25:00 Days Off 22</p>')


def _clocked(W, monkeypatch, now=NOV17):  # noqa: N803
    monkeypatch.setattr(W, "local_now", lambda: now)
    W.S["cm_prompt_captured"] = True
    waits = []
    monkeypatch.setattr(W.time, "sleep", lambda s: waits.append(s))
    return waits


def test_the_months_offered_are_this_hst_month_and_the_next(load, monkeypatch):  # noqa: F811
    W, _ = load()
    monkeypatch.setattr(W, "local_now", lambda: NOV17)
    assert W.lookup_months() == ("2026-11", "2026-12")
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 12, 31, 23, 59))
    assert W.lookup_months() == ("2026-12", "2027-01")
    assert W.month_label("2026-11") == "Nov 2026" and W.month_label("2027-01") == "Jan 2027"


@pytest.mark.parametrize("instance", ["pilot2", ""])
def test_a_month_other_than_this_or_the_next_is_refused_with_a_status_line(load, monkeypatch, caplog, instance):  # noqa: F811
    W, sent = load(instance)
    _clocked(W, monkeypatch)
    for month in ("2026-10", "2027-01", "2025-11"):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="flight_watcher"):
            p = _ask(W, sent, emp="10001", name="Doe, Jane", month=month)
        assert not W.S.get("pilot_req")
        assert p["status"] == "Only Nov 2026 and Dec 2026 can be looked up (this month and the next, HST)."
        assert (p["emp"], p["name"], p["month"]) == ("10001", "Doe, Jane", "")
        lines = [r.getMessage() for r in caplog.records if "pilot lookup" in r.getMessage()]
        assert [x for x in lines if "refused" in x] == ["pilot lookup refused: month not this HST month or the next"]
        assert not [x for x in lines if "requested" in x or "read" in x], lines
        assert month not in caplog.text and "10001" not in caplog.text
    # a bad string never reaches the month rule: the shape refuses it (one log line, nothing published)
    n = len(sent)
    for bad in ("2026-13", "2026-1", "Dec 2026", "2026-12\n", 202612, None, ""):
        W.pilot_cmd(json.dumps({"emp": "10001", "month": bad}))
    assert len(sent) == n and not W.S.get("pilot_req")
    with pytest.raises(PT.PortalError):
        PT.check_shape("pilot/set", json.dumps({"month": "2026-11"}))  # a month alone names no pilot


@pytest.mark.parametrize("instance", ["pilot2", ""])
def test_a_month_reads_only_that_months_page_once(load, monkeypatch, instance):  # noqa: F811
    W, sent = load(instance)
    waits = _clocked(W, monkeypatch)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    prev = []  # FW-0057's previous month read (the admin's crew index) has a test of its own below
    monkeypatch.setattr(W, "lookup_prev_month", lambda fl, emp, cur: prev.append((cur.year, cur.month)) or 0)
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-11")
    assert p["status"] == "loading" and p.get("asked_month") == "2026-11"
    assert W.S["pilot_req"]["month"] == "2026-11"
    fl = MonthFl()
    assert W.pilot_check(fl)
    sched = fl.sched()
    assert len(sched) == 1 and "bd=1126" in sched[0] and "GO=1" not in sched[0]  # IF.CM_SCHED_MONTH only
    assert sched[0] == W.IF.CM_SCHED_MONTH.format(base=W.BASE, emp="10999", bd="1126")
    assert sum("mobilepairing" in u for u in fl.urls) == 1  # then the pairing pages as before
    assert waits and all(1.5 <= s <= 3.5 for s in waits)  # paced
    out = [p for t, p in sent if t == "pilot_schedule"][-1]
    assert (out["status"], out["month"], out["emp"]) == ("ok", "2026-11", "10999")
    assert W.DB.get("pilot_sched:10999:2026-11")["bd"] == "1126" and W.DB.get("pilot_sched:10999") is None
    assert not W.S.get("pilot_req") and prev == [(2026, 11)]  # from the month read


def test_no_month_is_exactly_as_before(load, monkeypatch):  # noqa: F811
    W, sent = load()
    waits = _clocked(W, monkeypatch)
    p = _ask(W, sent, emp="10999", name="Roe, Rick")
    assert p["status"] == "loading" and "asked_month" not in p and "month" not in W.S["pilot_req"]
    fl = MonthFl()
    assert W.pilot_check(fl)
    # FLICA's default page first (it reads, December here), no second load
    assert fl.sched() == [W.IF.CM_SCHED.format(base=W.BASE, emp="10999")]
    out = [p for t, p in sent if t == "pilot_schedule"][-1]
    assert out["month"] == "2026-12" and W.DB.get("pilot_sched:10999")["bd"] == "1126"  # bd as it always was
    assert W.DB.get("pilot_sched:10999:2026-12") is None
    # a default page that does not read: the current month's page next, as before
    W.DB.put("pilot_sched:10999", {})
    _ask(W, sent, emp="10999", name="Roe, Rick")

    class Bad(MonthFl):
        def fetch(self, url):
            if "GO=1" in url:
                self.urls.append(url)
                return "<html>no schedule</html>"
            return super().fetch(url)
    fl = Bad()
    assert W.pilot_check(fl)
    assert len(fl.sched()) == 2 and "bd=1126" in fl.sched()[1]
    assert waits and all(1.5 <= s <= 3.5 for s in waits)


def test_the_cache_is_per_month(load, monkeypatch):  # noqa: F811
    W, sent = load()
    _clocked(W, monkeypatch)
    _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-11")
    W.pilot_check(MonthFl())
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-11")
    assert (p["status"], p["month"]) == ("cached", "2026-11") and not W.S.get("pilot_req")
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")  # another month: a new read
    assert p["status"] == "loading" and W.S["pilot_req"]["month"] == "2026-12"
    fl = MonthFl()
    W.pilot_check(fl)
    assert len(fl.sched()) == 1 and "bd=1226" in fl.sched()[0]
    assert _ask(W, sent, emp="10999", month="2026-12")["month"] == "2026-12"
    assert _ask(W, sent, emp="10999", month="2026-11")["month"] == "2026-11"
    # the no-month lookup keeps its own cache (FLICA's default month), and a month tap for the month it holds uses it
    W.DB.put("pilot_sched:10999:2026-12", None)
    _ask(W, sent, emp="10999", name="Roe, Rick")
    W.pilot_check(MonthFl())
    p = _ask(W, sent, emp="10999", month="2026-12")
    assert (p["status"], p["month"]) == ("cached", "2026-12") and not W.S.get("pilot_req")
    # a stale entry is read again
    rec = W.DB.get("pilot_sched:10999:2026-11")
    W.DB.put("pilot_sched:10999:2026-11", {**rec, "fetched_ts": rec["fetched_ts"] - W.PILOT_CACHE_S - 1})
    assert _ask(W, sent, emp="10999", month="2026-11")["status"] == "loading"


def test_the_previous_month_follows_the_month_read(W, monkeypatch, tmp_path):  # noqa: F811
    """FW-0057 on the admin: a December read notes November's trips that run into December (no November file)."""
    W.TEST_CLOCK["t"] = NOV17
    W.S["cm_prompt_captured"] = True
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    seen = []
    monkeypatch.setattr(W, "lookup_prev_month", lambda fl, emp, cur: seen.append((emp, cur.year, cur.month)) or 0)
    W.pilot_cmd(json.dumps({"emp": "10999", "name": "Roe, Rick", "month": "2026-12"}))
    W.pilot_check(MonthFl())
    W.pilot_cmd(json.dumps({"emp": "10998", "name": "Roe, Rob", "month": "2026-11"}))
    W.pilot_check(MonthFl())
    W.pilot_cmd(json.dumps({"emp": "10997", "name": "Roe, Ray"}))
    W.pilot_check(MonthFl())
    assert seen == [("10999", 2026, 12), ("10998", 2026, 11), ("10997", 2026, 11)]  # no month: today's, as before


def test_a_pilots_month_tap_names_the_pilot_the_way_he_was_found(load, monkeypatch):  # noqa: F811
    """On a pilot's instance the card's month buttons send the same field that found the pilot it shows (the pick,
    the number of a #pilot= link, the typed number), which the Watcher publishes as ask; the pick of the pilot shown
    stays usable for his month buttons after the pick list's 30 min."""
    W, sent = load()
    _clocked(W, monkeypatch)
    _dir(W, monkeypatch, _doe(3))
    p = _ask(W, sent, q="Doe")
    m = p["matches"][1]
    q = _ask(W, sent, pick=m["pick"], name=m["name"])
    assert q["emp"] == "10002" and q["ask"] == {"pick": m["pick"]}
    W.S.pop("pilot_req")
    W.S["pilot_picks"][m["pick"]]["at"] = 0  # the list is old
    q = _ask(W, sent, pick=m["pick"], name=m["name"], month="2026-11")
    assert (q["emp"], q["status"], q["ask"]) == ("10002", "loading", {"pick": m["pick"]})
    assert W.S["pilot_req"] == {**W.S["pilot_req"], "emp": "10002", "month": "2026-11"}
    W.S.pop("pilot_req")
    # without a month an old pick is old, as before
    assert _ask(W, sent, pick=m["pick"], name=m["name"])["status"].startswith("That pick list is old")
    # another pick nobody was shown is never taken
    assert _ask(W, sent, pick="0" * 12, month="2026-11")["status"].startswith("That pick list is old")
    assert _ask(W, sent, emp="10003", name="Doe, Cal")["ask"] == {"emp": "10003"}
    W.S.pop("pilot_req")
    assert _ask(W, sent, q="#10003")["ask"] == {"q": "10003"}
    # the admin's card sends the number: no ask there
    W2, sent2 = load("")
    _clocked(W2, monkeypatch)
    assert "ask" not in _ask(W2, sent2, emp="10003", name="Doe, Cal")


def test_the_month_is_in_the_shape_and_its_log_line_carries_no_text(load, caplog):  # noqa: F811
    W, sent = load()
    sh = roles.SHAPE_CMDS["pilot/set"]
    assert sh["keys"] == ["emp", "q", "name", "pick", "month"] and sh["any_of"] == ["emp", "q", "pick"]
    assert sh["fields"]["month"] == {"type": "text", "min": 7, "max": 7, "pattern": roles.MONTH_PATTERN}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pilot_cmd(json.dumps({"emp": "10001", "month": "Dec 2026"}))
    assert "pilot lookup refused" in caplog.text and "Dec 2026" not in caplog.text and "10001" not in caplog.text
    assert not W.S.get("pilot_req") and not sent

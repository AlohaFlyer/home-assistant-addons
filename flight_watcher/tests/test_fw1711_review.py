"""1.7.11 review fixes for the pilot lookup (FW-0076 / FW-0078), on the Watcher. Synthetic pilots only ("Doe, Jane",
made-up numbers).

F1: a month tap takes the newer read of its month, whichever key holds it (the month's own read or the read with no
month, when that shows the same month), so a tap never reads FLICA again or shows an older read while a newer one of
its month is on hand; pilotver_price prices a month from that same newest read. No month: the default read, as before.
F3: the admin's pick list takes a pilot database hit's base from its own record; a crew directory hit takes the
directory's base only when that row names the same last name (a number two records share).
F4: name_directory gives a seniority list record the seat and base of an earlier row of its number only when that row
names the same last name (the 'also' records of a shared number).
F5: a month tap whose page cannot be read (or whose read fails) rebuilds the month asked for, names it in the reply
(asked_month) and the crew index view is that month's."""
import json
import os
import time

from test_crew_index import W  # noqa: F401  (the admin's Watcher, for PW)
from test_fw1710_award_sen import award
from test_fw1711_pilot_lookup import MonthFl, _ask, _clocked
from test_pilotdb_watcher import P as PW  # noqa: F401  (the admin's Watcher with a pilot database)
from test_release_a_lookup import load  # noqa: F401  (a pilot's or the admin's Watcher with files on hand)


def _age(W, key, hours, **extra):  # noqa: N803
    rec = W.DB.get(key)
    W.DB.put(key, {**rec, "fetched_ts": time.time() - hours * 3600, **extra})


# ---------------------------------------------------------------- F1: the newer read of a month wins
def test_a_month_tap_uses_a_newer_read_of_its_month_with_no_flica_load(load, monkeypatch):  # noqa: F811
    W, sent = load()
    _clocked(W, monkeypatch)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    # 08:00 a Dec tap stores the month's own read; 7 h later a lookup with no month reads FLICA's default (December)
    _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
    W.pilot_check(MonthFl())
    _age(W, "pilot_sched:10999:2026-12", 7, marker="old 7h")
    _ask(W, sent, emp="10999", name="Roe, Rick")
    W.pilot_check(MonthFl())
    assert W.DB.get("pilot_sched:10999")["month"] == "2026-12"
    # a Dec tap now: the 5 min old December read answers it, cached; nothing is queued, no FLICA load
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
    assert (p["status"], p["month"]) == ("cached", "2026-12") and "marker" not in p
    assert not W.S.get("pilot_req")
    fl = MonthFl()
    assert not W.pilot_check(fl) and fl.urls == []


def test_a_month_tap_never_shows_an_older_read_than_one_on_hand(load, monkeypatch):  # noqa: F811
    W, sent = load()
    _clocked(W, monkeypatch)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
    W.pilot_check(MonthFl())
    _age(W, "pilot_sched:10999:2026-12", 3, marker="old 3h")
    _ask(W, sent, emp="10999", name="Roe, Rick")
    W.pilot_check(MonthFl())
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
    assert p["status"] == "cached" and "marker" not in p  # the newer default read, never the 3 h old one
    # and the other way round: a newer month read wins over an older default read of the same month
    _age(W, "pilot_sched:10999", 4, marker="default 4h")
    W.DB.put("pilot_sched:10999:2026-12", {**W.DB.get("pilot_sched:10999"), "fetched_ts": time.time() - 60,
                                           "marker": "month 1m"})
    assert W.pilot_cached("10999", "2026-12")["marker"] == "month 1m"
    # the default read of another month is never a month's answer; with no month the default read alone, as before
    W.DB.put("pilot_sched:10999", {**W.DB.get("pilot_sched:10999"), "month": "2027-01", "fetched_ts": time.time()})
    assert W.pilot_cached("10999", "2026-12")["marker"] == "month 1m"
    assert W.pilot_cached("10999", "2026-11") is None
    assert W.pilot_cached("10999")["month"] == "2027-01"


def test_versions_are_priced_from_the_newest_read_of_their_month(load, monkeypatch):  # noqa: F811
    W, _ = load()
    seen = []
    monkeypatch.setattr(W, "pilot_cached", lambda emp, month="": seen.append((emp, month)) or None)
    W.pilotver_price("10999", {"months": {"2026-12": [], "2026-11": []}})
    assert sorted(seen) == [("10999", "2026-11"), ("10999", "2026-12")]


# ---------------------------------------------------------------- F3: the admin's pick list base is the hit's own
def test_a_shared_number_never_shows_another_pilots_base_on_the_admin(PW, monkeypatch):  # noqa: F811
    W = PW  # noqa: N806
    db = W.pilotdb_start()
    sent = []
    monkeypatch.setattr(W, "pub_pilot", lambda p: sent.append(p))
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    db.new_record("10777", "Zoe, Zed")
    db.new_record("10777", "Moe, Amy")  # the same number: a shared one
    db.new_record("10888", "Zoe, Ann")
    with open(os.path.join(W.UPLOADS, "2026-12_award.txt"), "w") as f:
        f.write(award([(9, "OGG-332-CA", "MOE", 10777)]))  # the award names Moe, OGG, under 10777
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    assert [h["base"] for h in db.name_hits("Zoe")] == ["", ""]  # each hit carries its own record's base
    assert {r["emp"]: r for r in W.name_directory()}["10777"]["base"] == "OGG"  # Moe's row
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    by = {m["emp"]: m for m in sent[-1]["matches"]}
    assert by["10777"]["name"] == "Zoe, Zed" and "base" not in by["10777"]  # never Moe's OGG
    # Zoe's own record's domicile is the one shown
    db.merge_award_sen("2026-12", [{"sen": 8, "emp": "10777", "last": "Zoe", "base": "HNL", "equip": "332",
                                    "seat": "CA"}])
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    by = {m["emp"]: m for m in sent[-1]["matches"]}
    assert by["10777"]["base"] == "HNL" and by["10777"]["name"] == "Zoe, Zed"


def test_pick_bases_checks_the_last_name_of_a_directory_row(load, monkeypatch):  # noqa: F811
    W, _ = load("")
    monkeypatch.setattr(W, "name_directory", lambda: [{"emp": "10777", "last": "Moe", "first": "", "base": "OGG"},
                                                      {"emp": "10001", "last": "Doe", "first": "Jane", "base": "LAX"}])
    hits = [{"emp": "10777", "name": "Zoe, Zed", "pos": "CA"},  # a crew directory hit: no base of its own
            {"emp": "10001", "name": "Doe, Jane", "pos": "FO"},
            {"emp": "10002", "name": "Doe, Jo", "pos": "FO", "base": "KOA"}]  # a pilot database hit with its own
    assert W.pick_bases(hits) == {"10001": "LAX", "10002": "KOA"}


# ---------------------------------------------------------------- F4: 'also' records on a shared number
def test_an_also_record_never_takes_another_pilots_seat_or_base(load, tmp_path, monkeypatch):  # noqa: F811
    W, sent = load()
    up = tmp_path / "uploads_f4"
    up.mkdir()
    (up / "2026-11_award.txt").write_text(award([(72, "LAX-321-FO", "DOE", 10001)]))
    sen = {"pilots": {"10001": {"sen": 72, "name": "DOE, JANE", "last": "DOE", "doh": "2010-01-01", "seat": "",
                                "equip": "", "also": [{"sen": 73, "name": "ROE, RICK", "last": "ROE",
                                                       "doh": "2011-01-01", "seat": "", "equip": ""}]}}}
    (up / "seniority.json").write_text(json.dumps(sen))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    row = {r["emp"]: r for r in W.name_directory()}["10001"]
    assert (row["last"], row["first"], row["seat"], row["base"]) == ("Roe", "Rick", "", "")
    p = _ask(W, sent, q="Roe")
    assert [(m["name"], m["pos"], m.get("base"), m["emp"]) for m in p["matches"]] == [("Roe, Rick", "", None, "10001")]
    # the record of the pilot the award names still gets the award's seat and base
    sen["pilots"]["10001"].pop("also")
    (up / "seniority.json").write_text(json.dumps(sen))
    W._SEN_CACHE.clear()
    row = {r["emp"]: r for r in W.name_directory()}["10001"]
    assert (row["last"], row["first"], row["seat"], row["base"]) == ("Doe", "Jane", "FO", "LAX")


# ---------------------------------------------------------------- F5: an unreadable month tap rebuilds that month
class Unreadable(MonthFl):
    def fetch(self, url):
        self.urls.append(url)
        return "<html>ok no schedule</html>"


class Broken(MonthFl):
    def fetch(self, url):
        self.urls.append(url)
        raise RuntimeError("page gone")


def test_an_unreadable_month_tap_rebuilds_and_names_the_month_asked(load, monkeypatch):  # noqa: F811
    for inst in ("pilot2", ""):
        W, sent = load(inst)
        _clocked(W, monkeypatch)
        monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
        rebuilt = []
        monkeypatch.setattr(W, "pilotver_capture_rebuild",
                            lambda emp, name="", month=None, *a, **k: rebuilt.append((emp, month)) or [])
        for fl in (Unreadable(), Broken()):
            _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
            assert W.pilot_check(fl)
            assert len(fl.sched()) == 1 and "bd=1226" in fl.sched()[0]  # one load, as designed
            p = [p for t, p in sent if t == "pilot_schedule"][-1]
            assert p["month"] == "" and p["asked_month"] == "2026-12" and p["reconstructed_month"] == "2026-12"
            assert p["status"] != "loading"
            assert rebuilt[-1] == ("10999", "2026-12")
        # no month: the current month's rebuild, as before, and no asked_month
        _ask(W, sent, emp="10999", name="Roe, Rick")
        W.pilot_check(Unreadable())
        p = [p for t, p in sent if t == "pilot_schedule"][-1]
        assert "asked_month" not in p and p["reconstructed_month"] == "2026-11" and rebuilt[-1] == ("10999", None)


def test_a_waiting_month_tap_shows_the_month_asked(load, monkeypatch):  # noqa: F811
    W, sent = load()
    _clocked(W, monkeypatch)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    W.S["machine"] = "yielded"
    p = _ask(W, sent, emp="10999", name="Roe, Rick", month="2026-12")
    assert p["status"].startswith("waiting: your Watcher is yielded") and p["asked_month"] == "2026-12"
    assert p["reconstructed_month"] == "2026-12"

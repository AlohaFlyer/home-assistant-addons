"""1.7.8 (Ryan, Nov 14: "each picker's record carries his full pickup history (running count per layover station, trip
length, turn or layover, credit, report time, weekday, pickup speed), linked by employee #"): the Watcher's scored
pickups (store.pickup_history, from the picker_log 1.7.7 rebuilt) mirrored into the pilot database, each linked to the
picker's record by employee number (a number two pilots share decided by the picker's last name), kept up to date as
new pickups are scored, and shown per record and in seniority.md. Synthetic pilots only ("Doe, Jane" 10001)."""
from datetime import datetime, timezone

import pilotdb as P
from store import Store
from test_fw177_pickers import JANE, MAX, PAT, _find

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def _row(db, key, start, layover="LAX", days="3", credit="15:30", report="08:00", turn=""):
    r = {"pairing": key.split("|")[0], "start": start, "layover": layover, "days": days, "credit": credit,
         "report": report}
    if turn:
        r["turn"] = turn
    db.patch_row(key, r)


def _store(tmp_path):
    s = Store(str(tmp_path / "w.db"))
    # Jane: three pickups (two LAX layovers, one OGG turn); Pat and Max share a both-seats pickup
    for i, (key, gone, lay, start, turn) in enumerate((
            ("H3601|03Nov", "2026-11-01T20:00:00+00:00", "LAX", "03Nov", ""),
            ("H3602|07Nov", "2026-11-05T21:00:00+00:00", "", "07Nov", "OGG"),
            ("H3603|10Nov", "2026-11-08T22:00:00+00:00", "LAX", "10Nov", ""))):
        _find(s, key, f"FO {JANE}", gone, "FO", first=gone.replace("T2", "T1"))
        _row(s, key, start, layover=lay or "-NONE-", days="1" if turn else "3", turn=turn)
        assert s.score_pickup(key) is not None
    _find(s, "H3604|12Nov", f"FO {PAT}; RO {MAX}", "2026-11-09T20:00:00+00:00", "FO,RO",
          pickup={"pickers": ["10003", "10004"]}, first="2026-11-09T19:58:00+00:00")
    _row(s, "H3604|12Nov", "12Nov", layover="SYD", days="5", credit="30:00", report="21:15")
    s.score_pickup("H3604|12Nov")
    s.set_inflt("H3604|12Nov", False, "", tries=1, emp="10003")
    s.set_inflt("H3604|12Nov", True, "H3604 2026-11-12", tries=1, emp="10004")
    return s


def _pdb(tmp_path):
    db = P.PilotDB(str(tmp_path / "p.sqlite"), (), lambda: T0)
    db.merge_list({"list_date": "2026-07-01", "pilots": {
        "10001": {"sen": 812, "name": "Doe, Jane", "doh": "2001-05-01"},
        "10003": {"sen": 900, "name": "Poe, Pat", "doh": "2019-03-03",
                  "also": [{"sen": 901, "name": "Lee, Lou", "doh": "2019-04-04"}]},
        "10004": {"sen": 950, "name": "Moe, Max", "doh": "2020-12-09"}}})
    return db


def test_store_pickup_history_rows(tmp_path):
    s = _store(tmp_path)
    rows = s.pickup_history()
    assert [(r["key"], r["emp"]) for r in rows] == [
        ("H3601|03Nov", "10001"), ("H3602|07Nov", "10001"), ("H3603|10Nov", "10001"),
        ("H3604|12Nov", "10003"), ("H3604|12Nov", "10004")]
    j = rows[0]
    assert (j["name"], j["pos"], j["lay"], j["start"], j["days"], j["turn"], j["credit"], j["report"], j["dow"]) == (
        "Doe, Jane", "FO", "LAX", "2026-11-03", "3", False, "15:30", "08:00", "Tue")
    assert isinstance(j["secs"], int) and j["secs"] >= 0
    turn = rows[1]
    assert (turn["turn"], turn["lay"], turn["days"]) == (True, "OGG", "1")
    assert (rows[3]["inflt"], rows[4]["inflt"]) == (False, True)  # each picker's own verdict (1.7.8 inflt_no)


def test_sync_links_by_employee_number_with_running_counts(tmp_path):
    s, db = _store(tmp_path), _pdb(tmp_path)
    r = db.sync_pickups(s.pickup_history())
    assert r == {"rows": 5, "linked": 5, "added": 5, "removed": 0}
    jane = db.find("10001")
    h = db.pickups(jane)
    # newest first; LAX twice; the OGG turn is no layover station (review: it was counted as one)
    assert [(x["pairing"], x["n"], x["lay"], x["n_lay"], x["station"]) for x in h["rows"]] == [
        ("H3603", 3, "LAX", 2, "LAX"), ("H3602", 2, "", 0, "OGG"), ("H3601", 1, "LAX", 1, "LAX")]
    sm = h["summary"]
    assert (sm["n"], sm["lays"], sm["turn_stations"], sm["turns"], sm["layovers"], sm["days"]) == (
        3, [["LAX", 2]], [["OGG", 1]], 1, 2, {"1": 1, "3": 2})
    assert sm["dow"] == {"Tue": 2, "Sat": 1}  # the trips start Tue Nov 3, Sat Nov 7 and Tue Nov 10
    assert sm["report"] == {"first": "08:00", "last": "08:00"} and sm["credit_avg"] == "15:30"
    assert sm["speed"]["avg_s"] is not None and sm["speed"]["min_s"] <= sm["speed"]["max_s"]
    # 10003 is shared by Pat and Lou on the list: the picker's last name (Poe) decides
    pat, lou = db.find("10003", "Poe, Pat"), db.find("10003", "Lee, Lou")
    assert db.pickups(pat)["summary"]["n"] == 1 and db.pickups(lou)["summary"]["n"] == 0
    assert db.pickups(db.find("10004"))["summary"]["inflt"] == 1
    assert db.record(jane)["pickups"]["summary"]["n"] == 3
    assert db.search("", "all")["rows"][0]["pickups_n"] == 3  # Jane is Sen 812, first


def test_kept_up_to_date_as_new_pickups_are_scored(tmp_path):
    s, db = _store(tmp_path), _pdb(tmp_path)
    db.sync_pickups(s.pickup_history())
    _find(s, "H3605|20Nov", f"FO {JANE}", "2026-11-18T20:00:00+00:00", "FO", first="2026-11-18T19:00:00+00:00")
    _row(s, "H3605|20Nov", "20Nov", layover="LAX")
    s.score_pickup("H3605|20Nov")
    r = db.sync_pickups(s.pickup_history())
    assert (r["added"], r["removed"]) == (1, 0)
    top = db.pickups(db.find("10001"))["rows"][0]
    assert (top["pairing"], top["n"], top["n_lay"]) == ("H3605", 4, 3)  # the 3rd LAX pickup
    assert db.sync_pickups(s.pickup_history()) == {"rows": 6, "linked": 6, "added": 0, "removed": 0}  # idempotent


def test_a_picker_without_a_record_links_once_his_record_comes(tmp_path):
    s = _store(tmp_path)
    db = P.PilotDB(str(tmp_path / "p.sqlite"), (), lambda: T0)
    assert db.sync_pickups(s.pickup_history())["linked"] == 0
    db.merge_contacts({"uploaded_at": "2026-11-14T09:30:00-10:00", "pilots": [], "hal_only": [
        {"emp": "10001", "name": "Doe, Jane", "hal": {"emp": "10001", "sen": "812", "sen_month": "2026-07"}}]})
    assert db.pickups(db.find("10001"))["summary"]["n"] == 3
    # the picker's crew-line spelling is a search token of his record
    assert db.search("doe")["total"] == 1


def test_the_md_carries_the_pickup_history(tmp_path):
    s, db = _store(tmp_path), _pdb(tmp_path)
    db.sync_pickups(s.pickup_history())
    md = db.render_md("1.7.8", "2026-11-15 10:00 HST")
    assert "## Pickup history" in md
    assert "### Doe, Jane (Emp 10001, 3 pickups)" in md and "- Layover stations: LAX 2; turns: OGG 1" in md
    assert "Layovers 2, turns 1" in md

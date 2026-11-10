"""1.6.2 (Release A item 11): the pilot name lookup on a pilot instance. Names come only from the award and seniority
files every instance already receives (never the admin's crew index or contact list, nor the pilot's own crew
directory); a query needs 3 letters of a last name, letters only (no wildcard, no listing); at most 5 matches, each
with name and seat and an opaque pick id instead of the employee number; the number runs the lookup and is shown only
for the chosen pilot. A lookup while the Watcher is paused says it waits; a pilot's reply has no crew index coverage.
The card: the status line with its time on no match, the header of the pilot asked for, the loading line's timeout.
Synthetic names only ("Doe, Jane", 10001)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

import cards

HERE = os.path.dirname(os.path.abspath(__file__))
AWARD = "\n".join(["                                      A332FO PBS BIDLINE AWARD", ""] + [
    f"{i:05d} / {e}\n{n}\nCr:080:00\nDays Off: 17\n" for i, (e, n) in enumerate([
        ("10001", "DOE"), ("10002", "DOE"), ("10003", "DOERR"), ("10004", "ROE"), ("10011", "SMITH"),
        ("10012", "SMITHE"), ("10013", "SMITHERS"), ("10014", "SMITHSON"), ("10015", "SMITHY"), ("10016", "SMITHEN")],
        start=100)])
SENIORITY = {"pilots": {"10001": {"sen": 100, "name": "Doe, Jane", "seat": "FO"},
                        "10002": {"sen": 101, "name": "Doe, John", "seat": "CA"}}}


@pytest.fixture
def load(tmp_path, monkeypatch):
    def _load(instance="pilot2"):
        data = tmp_path / ("data_" + (instance or "admin"))
        data.mkdir(exist_ok=True)
        (data / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        for k in ("FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL"):
            monkeypatch.delenv(k, raising=False)
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        sys.modules.pop("watcher", None)
        import watcher as W
        from store import Store
        W.S.clear()
        W.S["machine"] = "hunting"
        monkeypatch.setattr(W, "DB", Store(str(tmp_path / f"{instance or 'admin'}.db")))
        up = tmp_path / "uploads"
        up.mkdir(exist_ok=True)
        (up / "2026-11_award.txt").write_text(AWARD)
        (up / "seniority.json").write_text(json.dumps(SENIORITY))
        monkeypatch.setattr(W, "UPLOADS", str(up))
        monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
        monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
        monkeypatch.setattr(W, "contacts_data", lambda: None)
        sent = []
        monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
        W.DB.remember_crew("Crew: CA 10077 ZED, ZOE FO 10078 DOE, JILL")  # his own crew directory: never searched
        return W, sent
    yield _load
    sys.modules.pop("watcher", None)


def _ask(W, sent, **d):
    W.pilot_cmd(json.dumps(d))
    return [p for t, p in sent if t == "pilot_schedule"][-1]


def test_name_directory_is_the_award_and_the_seniority_list(load):
    W, _ = load()
    rows = {r["emp"]: r for r in W.name_directory()}
    assert rows["10001"]["name"] == "Doe, Jane" and rows["10001"]["seat"] == "FO"  # the list wins (a first name)
    assert rows["10002"]["seat"] == "CA" and rows["10004"] == {"emp": "10004", "last": "Roe", "first": "", "seat": "FO",
                                                              "name": "Roe"}  # award only: seat from its title
    assert "10077" not in rows and "10078" not in rows


@pytest.mark.parametrize("q,why", [("Do", "at least 3 letters"), ("D*", "letters only"), ("%oe", "letters only"),
                                   ("Doe?", "letters only"), ("Zed", "No pilot named 'Zed'"),
                                   ("Smit", "No pilot named 'Smit'")])
def test_a_query_that_lists_nothing(load, q, why):
    W, sent = load()
    p = _ask(W, sent, q=q)
    assert p["emp"] == "" and p["matches"] == [] and why.lower() in p["status"].lower() and p["at"]
    assert not W.S.get("pilot_req")


def test_one_match_is_a_pick_list_of_one(load):
    """1.6.2 review: one match is not run at once: its employee number is used (and shown) only after the pick."""
    W, sent = load()
    p = _ask(W, sent, q="roe")
    assert p["emp"] == "" and [m["name"] for m in p["matches"]] == ["Roe"] and "10004" not in json.dumps(p)
    assert "tap the name" in p["status"] and not W.S.get("pilot_req")
    q = _ask(W, sent, pick=p["matches"][0]["pick"], name="Roe")
    assert (q["emp"], q["name"], q["status"]) == ("10004", "Roe", "loading") and W.S["pilot_req"]["emp"] == "10004"
    p = _ask(W, sent, q="Doe, Jane")
    assert p["emp"] == "" and [m["name"] for m in p["matches"]] == ["Doe, Jane"]
    p = _ask(W, sent, q="#10002")  # an employee number with '#'
    assert p["emp"] == "10002"


def test_a_prefix_needs_5_letters_so_the_roster_cannot_be_walked(load):
    W, sent = load()
    assert _ask(W, sent, q="Doer")["matches"] == []  # 4 letters: the whole last name only (DOERR is not listed)
    assert [m["name"] for m in _ask(W, sent, q="Doerr")["matches"]] == ["Doerr"]
    assert [m["name"] for m in _ask(W, sent, q="Smiths")["matches"]] == ["Smithson"]  # 5 letters on: a prefix too
    # walking every 3-letter start of the synthetic roster finds only whole names typed (none of these)
    found = set()
    for a in "DRS":
        for b in "MO":
            for c in "EIT":
                found |= {m["name"] for m in _ask(W, sent, q=a + b + c)["matches"]}
    assert found <= {"Doe, Jane", "Doe, John", "Roe"}


def test_more_than_5_matches_is_no_list(load, monkeypatch):
    W, sent = load()
    rows = [{"emp": str(20001 + i), "last": f"Hallo{c}", "first": "", "seat": "FO", "name": f"Hallo{c}"}
            for i, c in enumerate("abcdef")]
    monkeypatch.setattr(W, "name_directory", lambda: rows)
    p = _ask(W, sent, q="Hallo")
    assert p["matches"] == [] and "More than 5 pilots match" in p["status"]


def test_name_queries_are_capped_at_20_an_hour(load):
    W, sent = load()
    for i in range(W.LOOKUP_PER_H):
        _ask(W, sent, q="Zed")
    p = _ask(W, sent, q="Roe")
    assert p["matches"] == [] and p["status"].startswith("20 name lookups in the last hour: the next one at ")
    assert "HST" in p["status"]
    assert _ask(W, sent, q="10004")["emp"] == "10004"  # an employee number is no name query


def test_several_matches_give_name_and_seat_and_a_pick_id(load):
    W, sent = load()
    p = _ask(W, sent, q="Doe")  # DOE exactly: DOERR is left out
    assert p["emp"] == "" and [(m["name"], m["pos"]) for m in p["matches"]] == [("Doe, Jane", "FO"), ("Doe, John", "CA")]
    blob = json.dumps(p)
    assert "10001" not in blob and "10002" not in blob  # no employee number in the list
    pick = p["matches"][1]["pick"]
    q = _ask(W, sent, pick=pick, name="Doe, John")
    assert (q["emp"], q["status"]) == ("10002", "loading")
    W.S["pilot_picks"][pick]["at"] = 0
    assert "old" in _ask(W, sent, pick=pick)["status"] and _ask(W, sent, pick="nope")["emp"] == ""


def test_a_lookup_while_paused_says_it_waits(load):
    W, sent = load()
    W.S["machine"] = "paused"
    p = _ask(W, sent, q="10004")
    assert p["status"].startswith("waiting: your Watcher is paused") and W.S["pilot_req"]["emp"] == "10004"


def test_no_crew_index_coverage_on_a_pilot(load):
    W, sent = load()
    W.pub_pilot({"emp": "10004", "name": "Roe", "status": "not readable", "month": "", "days": [], "items": []})
    p = [p for t, p in sent if t == "pilot_schedule"][-1]
    assert p["reconstructed_coverage_pct"] is None


def test_the_admin_keeps_his_crew_directory(load):
    W, sent = load("")
    p = _ask(W, sent, q="Zed")
    assert p["emp"] == "10077" and p["status"] == "loading"  # his crew directory, as before
    p = _ask(W, sent, q="o")  # no 3-letter rule there; his pick list shows the numbers as before
    assert sorted(m["emp"] for m in p["matches"]) == ["10077", "10078"]


def test_pilot_card_states_at_390_px(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    card = tmp_path / "pc_james.js"
    card.write_text(cards.pilot_copy(open(os.path.join(HERE, "..", "www", "flight-watcher-pilot-card.js"),
                                          encoding="utf-8").read(), "james"))
    out = subprocess.run(["node", os.path.join(HERE, "release_a_pilot_render.js"), str(card)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    assert r["loading"].startswith("Looking up 'Roe'") and "10001" not in r["loading"] and "Doe" not in r["loading"]
    assert r["nomatch"].startswith("No pilot found for 'Roe'") and "(10:00 HST)" in r["nomatch"]
    assert "No pilot named 'Roe'" in r["nomatch"] and "10001" not in r["nomatch"]
    assert "Moe, Kai FO" in r["picks"] and not any(ch.isdigit() for ch in r["picks"].split("\n", 2)[2].split("HST")[-1])
    assert [json.loads(x) for x in r["pickSent"]] == [{"pick": "a1b2c3d4e5f6", "name": "Moe, Kai"}]
    assert r["pickLoading"].startswith("Moe, Kai\n")
    assert "Still waiting after 5 min: the Watcher is paused" in r["overdue"] and r["wide"] <= 390
    # 1.6.2 review: opened cold on a lookup asked 10 min ago (next check 4 min past): it gives up, from the sensor's at
    assert "Still waiting after 10 min" in r["coldOld"] and "about" not in r["coldOld"]
    assert "on the Watcher's next check" in r["coldNew"] and " HST" not in r["coldNew"].split("next check")[1]

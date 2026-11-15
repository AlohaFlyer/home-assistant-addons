"""1.7.10 (Ryan, Nov 15): "Look up a pilot's month" also searches the pilot database (all pilots: the contact list and
the award seniority), so a whole last name or 'Last, First' finds any pilot, not only those on an award's pilot lines
or a seniority list. Before, a portal pilot's lookup of a surname that is in the database answered "No pilot named
... on the award or seniority list on file". Ryan's lookup searches his database; a portal pilot's searches the
award's seniority lines (the award text every instance has) and, while Ryan shares the database with him, the roster
his Watcher already holds. The FLICA lookup then runs exactly as before: the pick list still shows a name and a seat,
never a number, and no budget or limit changed. Synthetic pilots only ("Doe, Jane" 10001)."""
import json

import pdbshare as PS
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw1710_award_sen import ROWS, award
from test_pilotdb_portal import james  # noqa: F401
from test_pilotdb_watcher import P as PW  # noqa: F401  (the admin's Watcher with a pilot database)


def _uploads(W, tmp_path, monkeypatch, text=None):  # noqa: N803
    up = tmp_path / "up"
    up.mkdir(exist_ok=True)
    if text:
        (up / "2026-12_award.txt").write_text(text)
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    W._SEN_CACHE.clear()
    W._NAME_DIR.clear()
    W._NAME_DIR.update(sig=None, rows=[])


def _asked(W, monkeypatch):  # noqa: N803
    sent = []
    monkeypatch.setattr(W, "pub_pilot", lambda p: sent.append(p))
    return sent


def test_the_awards_seniority_lines_are_in_the_name_directory(W, tmp_path, monkeypatch):  # noqa: F811
    _uploads(W, tmp_path, monkeypatch, award(ROWS))
    hits, why = W.name_lookup("Roe")
    assert why == "" and [(h["emp"], h["name"], h["seat"]) for h in hits] == [("10002", "Roe", "FO")]
    assert [h["seat"] for h in W.name_lookup("Van Doe")[0]] == ["CA"]
    assert [h["emp"] for h in W.name_lookup("O’Doe")[0]] == ["10004"]  # 'O'Doe Jr' without the Jr
    assert "in the pilot database or on the award or seniority list on file" in W.name_lookup("Zed")[1]


def test_a_portal_pilot_finds_a_pilot_only_the_database_has(james, tmp_path, monkeypatch):  # noqa: F811
    W, db, root = james  # noqa: N806
    _uploads(W, tmp_path, monkeypatch)
    sent = _asked(W, monkeypatch)
    db.new_record("10777", "Zoe, Zed")  # in Ryan's database (a contact, say): on no award and no seniority list
    # not shared: nothing of the database is searched
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    assert sent[-1]["matches"] == [] and "No award or seniority list is on file" in sent[-1]["status"]
    db.set_share("james", True)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    p = sent[-1]
    assert [m["name"] for m in p["matches"]] == ["Zoe, Zed"] and p["emp"] == "" and "10777" not in json.dumps(p)
    assert "tap the name" in p["status"] and not W.S.get("pilot_req")  # a pick list of one, as before
    W.pilot_cmd(json.dumps({"pick": p["matches"][0]["pick"], "name": "Zoe, Zed"}))
    assert W.S["pilot_req"]["emp"] == "10777"  # the FLICA lookup is queued the way it always was
    W.pilot_cmd(json.dumps({"q": "Zoe, Zed"}))
    assert [m["name"] for m in sent[-1]["matches"]] == ["Zoe, Zed"]
    W.pilot_cmd(json.dumps({"q": "Zoe, Amy"}))
    assert sent[-1]["matches"] == []
    # the lookup's own limits are as they were
    assert (W.LOOKUP_PER_H, W.LOOKUP_MAX, W.LOOKUP_MIN_LETTERS, W.LOOKUP_PREFIX_MIN) == (20, 5, 3, 5)
    # sharing switched off again: the database is not searched any more
    db.set_share("james", False)
    PS.write_files(db, [], root)
    W.pilotdb_watch()
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    assert sent[-1]["matches"] == []


def test_ryans_lookup_searches_his_pilot_database(PW, monkeypatch):  # noqa: F811
    W = PW  # noqa: N806
    db = W.pilotdb_start()
    sent = _asked(W, monkeypatch)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    assert W.DB.find_crew("zoe") == []  # the crew the Watcher has seen does not have him
    db.new_record("10777", "Zoe, Zed")
    W.pilot_cmd(json.dumps({"q": "Zoe"}))
    assert W.S["pilot_req"] == {"emp": "10777", "name": "Zoe, Zed", "at": W.S["pilot_req"]["at"]}
    assert sent[-1]["status"] == "loading"
    W.S.pop("pilot_req")
    db.new_record("10778", "Zoe, Amy")
    W.pilot_cmd(json.dumps({"q": "zoe"}))  # two pilots of that name: Ryan picks
    assert sorted(m["name"] for m in sent[-1]["matches"]) == ["Zoe, Amy", "Zoe, Zed"] and not W.S.get("pilot_req")
    W.pilot_cmd(json.dumps({"q": "Zoe, Amy"}))
    assert W.S["pilot_req"]["emp"] == "10778"
    W.S.pop("pilot_req")
    W.pilot_cmd(json.dumps({"q": "Zzz"}))
    assert "no pilot named 'Zzz' in the pilot database or the" in sent[-1]["status"]
    assert db.name_hits("Zo") == [] and db.name_hits("") == []  # the whole last name, never a prefix walk

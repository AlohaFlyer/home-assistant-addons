"""1.6.2 (Release A item 10): Recall/O75 (PWA 22.G.2) on a pilot. His seniority number comes from the uploaded award
or seniority list by his own employee number (a typed one wins); recall/act me.sen takes only an int 1..99999; no CCR
draft and no recall_miss alert while his seniority or his line for the row's days is unknown, and the row says what is
missing; a forwarded list's 'me' never sets a pilot's number; the narrative never prints None and says 'an FO'. The
card: no Hark hint on a pilot, the missing-data notes, day rows for a list not posted or empty, 'came in ... HST'.
Synthetic data only ("Doe, Jane", 10001)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

import cards
import recall as RC

HERE = os.path.dirname(os.path.abspath(__file__))
DET = {"H9001": {"report": "08:00", "block": "10:00", "rel_days": 2,
                 "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                            {"d": 1, "dep": 2100, "arr": 2400, "stn": "HNL", "blk": 300}]}}
AWARD = ("                                      A332FO PBS BIDLINE AWARD\n"
         "00123 / 10001\nDOE\nCr:080:00\nDays Off: 17\n\n00900 / 10009\nROE\nCr:070:00\nDays Off: 18\n")


def _row(**k):
    r = {"date": "2026-11-10", "kind": "recall", "seat": "FO", "pilot": "Doe, Jane", "sen": 900, "pairing": "H9001"}
    r.update(k)
    return r


def _line(W, months=("2026-10", "2026-11", "2026-12")):
    for mk in months:
        W.DB.put(f"sched_versions:{mk}", [{"ver": f"{int(mk[5:])}.001", "n": 1, "at": "2026-10-20T00:00:00+00:00",
                                          "items": [], "days": [], "totals": {}, "trips": {}}])


@pytest.fixture
def load(tmp_path, monkeypatch):
    def _load(instance="pilot2", line=True):
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
        monkeypatch.setattr(W, "DB", Store(str(tmp_path / f"{instance or 'admin'}.db")))
        up = tmp_path / "uploads"
        up.mkdir(exist_ok=True)
        monkeypatch.setattr(W, "UPLOADS", str(up))
        monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
        from datetime import datetime
        monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 10, 8, 0))
        sent = []
        monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
        W.DB.put("pkg_details:2026-11", DET)
        if line:
            _line(W)
        return W, sent, up
    yield _load
    sys.modules.pop("watcher", None)


def _last(sent):
    st = [p for t, p in sent if t == "recall"][-1]
    return st, {v["id"]: v for d in st["days"] for v in d["verdicts"]}


VID = "2026-11-10|H9001|recall"


def test_seniority_from_the_award_by_own_employee_number(load):
    W, sent, up = load()
    W.S["own_emp"] = "10001"
    assert W.recall_me(with_source=True) == ({"sen": None, "seat": "FO", "o75_months": {}}, "")
    (up / "2026-11_award.txt").write_text(AWARD)
    me, src = W.recall_me(with_source=True)
    assert me["sen"] == 123 and src == "award 2026-11"
    W.recall_act(json.dumps({"me": {"sen": 4567}}))  # typed wins
    assert W.recall_me(with_source=True)[0]["sen"] == 4567 and W.recall_me(with_source=True)[1] == "typed"
    W.recall_act(json.dumps({"me": {"sen": None}}))  # forget the typed one: the award applies again
    assert W.recall_me(with_source=True) == ({"sen": 123, "seat": "FO", "o75_months": {}}, "award 2026-11")
    st, _ = _last(sent)
    assert st["sen_source"] == "award 2026-11" and st["me"]["sen"] == 123


def test_seniority_from_the_seniority_list(load):
    W, _, up = load()
    W.S["own_emp"] = "10001"
    (up / "seniority.json").write_text(json.dumps({"pilots": {"10001": {"sen": 321, "name": "Doe, Jane", "seat": "FO"}}}))
    assert W.recall_me(with_source=True) == ({"sen": 321, "seat": "FO", "o75_months": {}}, "seniority list")


@pytest.mark.parametrize("bad", [-5, 0, 100000, 12.7, "abc", "123", True, [5], {"x": 1}])
def test_recall_act_takes_only_a_whole_number_1_to_99999(load, bad):
    W, _, _ = load()
    W.recall_act(json.dumps({"me": {"sen": 4567}}))
    W.recall_act(json.dumps({"me": {"sen": bad, "seat": "XX"}}))
    assert W.DB.get("recall_me")["sen"] == 4567 and W.recall_me()["seat"] == "FO"


def test_a_forwarded_list_never_sets_a_pilots_number(load):
    W, _, _ = load()
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [], "me": {"sen": 269}}))
    assert (W.DB.get("recall_me") or {}).get("sen") is None
    W, _, _ = load("")  # the admin keeps taking it (Hark's post may carry it), as before
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [], "me": {"sen": "269"}}))
    assert W.DB.get("recall_me")["sen"] == 269


def test_no_draft_and_no_alert_while_seniority_is_unknown(load):
    W, sent, up = load()
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()]}))
    st, vs = _last(sent)
    v = vs[VID]
    assert v["verdict"] == "POSSIBLE" and v["missing"] == "seniority" and "seniority number is not on file" in v["why"][-1]
    assert not W.DB.get("recall_acts") and not [t for t, _ in sent if t == "event/recall_miss"]
    assert st["missing_sen"] == 1 and st["open"] == 0
    # the award comes in: the row is judged, a draft is made and the alert goes once, without 'None'
    W.S["own_emp"] = "10001"
    (up / "2026-11_award.txt").write_text(AWARD)
    W.recall_cmd(json.dumps({"date": "2026-11-11", "rows": []}))
    st, vs = _last(sent)
    a = W.DB.get("recall_acts")[VID]
    assert vs[VID]["verdict"] == "MISSED" and "missing" not in vs[VID]
    assert "None" not in a["narrative"] and "#123" in a["narrative"] and "awarded to an FO" in a["narrative"]
    assert [p["id"] for t, p in sent if t == "event/recall_miss"] == [VID]


def test_no_draft_and_no_alert_while_the_line_is_unknown(load):
    W, sent, _ = load(line=False)
    W.recall_act(json.dumps({"me": {"sen": 500}}))
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()]}))
    st, vs = _last(sent)
    assert vs[VID]["verdict"] == "POSSIBLE" and vs[VID]["missing"] == "line" and "not on file" in vs[VID]["why"][-1]
    assert not W.DB.get("recall_acts") and not [t for t, _ in sent if t == "event/recall_miss"]
    assert st["missing_line"] == 1


def test_a_draft_follows_its_row_until_it_is_approved(load):
    W, sent, _ = load()
    W.recall_act(json.dumps({"me": {"sen": 500}}))
    W.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [_row()]}))
    assert "#500" in W.DB.get("recall_acts")[VID]["narrative"]
    W.recall_act(json.dumps({"me": {"sen": 600}}))
    assert "#600" in W.DB.get("recall_acts")[VID]["narrative"]  # new: the Watcher's own text, rebuilt
    W.recall_act(json.dumps({"id": VID, "action": "approve", "narrative": "my own words"}))
    W.recall_act(json.dumps({"me": {"sen": 700}}))
    assert W.DB.get("recall_acts")[VID]["narrative"] == "my own words"  # approved: never rewritten


def test_narrative_wording():
    me = {"sen": None, "seat": "FO"}
    v = {"date": "2026-11-10", "kind": "recall", "pairing": "H9001", "seat": "FO", "sen": 900, "verdict": "POSSIBLE",
         "why": ["went to #900", "pairing times unknown"]}
    t = RC.narrative(v, me)
    assert "None" not in t and "an FO" in t and "a FO" not in t and t.startswith("DRAFT TO CHECK")
    assert "awarded to a CA" in RC.narrative({**v, "seat": "CA", "verdict": "MISSED"}, {"sen": 5})


def test_pilot_card_wording_at_390_px(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    card = tmp_path / "rc_james.js"
    card.write_text(cards.pilot_copy(open(os.path.join(HERE, "..", "www", "flight-watcher-recall-card.js"),
                                          encoding="utf-8").read(), "james"))
    out = subprocess.run(["node", os.path.join(HERE, "release_a_recall_render.js"), str(card)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    t = r["nosen"]["text"]
    assert "Hark" not in t.split("Mon Nov 9")[1]  # no Hark hint on a pilot's rows
    assert "Nothing is filed for you. After you approve it, File it myself" in t
    assert "Your seniority # is not on file" in t and "Your FLICA schedule is not on file for the days of 1 row" in t
    assert "No CCR draft and no alert until your FLICA schedule for these days is on file." in t
    assert "Flight Ops did not post a list for this day." in t and "The posted list was empty." in t
    assert "came in Nov 8 17:30 HST" in t
    assert "from your Nov 2026 award" in r["award"]["text"] and "Your seniority # is not on file" not in r["award"]["text"]
    tries = r["nosen"]["tries"]
    assert tries["-5"] == [] and tries["123456"] == [] and tries["12.7"] == []
    assert [json.loads(x) for x in tries["1234"]] == [{"me": {"sen": 1234}}]  # no seat sent
    assert [json.loads(x) for x in tries[""]] == [{"me": {"sen": None}}]
    assert r["nosen"]["attrs"] == {"min": "1", "max": "99999", "mode": "numeric"} and r["nosen"]["wide"] <= 390

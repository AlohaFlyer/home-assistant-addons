import json

import versions as VER
from store import Store


def _sched(trips, totals=None):
    items = [{"trip": t, "start": s, "end": s, "lay": "LAX"} for t, s in trips]
    days = [[s, t, "LAX"] for t, s in trips]
    return {"items": items, "days": days, "totals": totals or {"days_off": 15}, "updated": "Nov 2"}


def test_versions_number_and_detect_every_change(tmp_path):
    db = Store(str(tmp_path / "v.db"))
    own = {"H1000|2026-11-01": {"blk": "10:00", "credit": "11:00", "crew": ["x"]}}
    s1 = _sched([("H1000", "2026-11-01"), ("VAC", "2026-11-20")])
    assert VER.update(db, {"2026-11": s1}, own, "t1") == [("2026-11", "11.001")]
    assert VER.update(db, {"2026-11": s1}, own, "t2") == []  # nothing changed
    # FLICA's days_off flip is not a change
    assert VER.update(db, {"2026-11": _sched([("H1000", "2026-11-01"), ("VAC", "2026-11-20")], {"days_off": 19})}, own, "t3") == []
    # actuals move block: a new version
    own2 = {"H1000|2026-11-01": {"blk": "10:20", "credit": "11:00"}}
    assert VER.update(db, {"2026-11": s1}, own2, "t4") == [("2026-11", "11.002")]
    # a swap: a new version that names it
    s3 = _sched([("H2000", "2026-11-03"), ("VAC", "2026-11-20")])
    assert VER.update(db, {"2026-11": s3}, own2, "t5") == [("2026-11", "11.003")]
    vers = db.get("sched_versions:2026-11")
    assert vers[1]["changes"] == ["H1000 block 10:00 -> 10:20"]
    assert "added H2000 2026-11-03" in vers[2]["changes"] and "dropped H1000 2026-11-01" in vers[2]["changes"]
    assert "crew" not in vers[0]["trips"]["H1000|2026-11-01"]
    pubd = VER.published(db, {"2026-11": s3})
    assert pubd["2026-11"]["current"] == "11.003" and pubd["2026-11"]["awarded"] == "11.001"
    assert all("fp" not in v for v in pubd["2026-11"]["versions"])


def test_published_keeps_awarded_and_latest(tmp_path):
    db = Store(str(tmp_path / "v.db"))
    for i in range(30):
        VER.update(db, {"2026-12": _sched([("H1000", "2026-12-01")])}, {"H1000|2026-12-01": {"blk": f"10:{i:02d}"}}, f"t{i}")
    p = VER.published(db, {"2026-12": {}})["2026-12"]
    vs = [v["ver"] for v in p["versions"]]
    assert p["count"] == 30 and len(vs) == VER.MAX_PUBLISHED and vs[0] == "12.001" and vs[-1] == "12.030"


def test_seed_imports_once(tmp_path):
    db = Store(str(tmp_path / "v.db"))
    snaps = [{"ts": 1793600000, **_sched([("H1000", "2026-11-06")]), "trips": {"H1000|2026-11-06": {"credit": "11:27"}}},
             {"ts": 1793650000, **_sched([("H2000", "2026-11-05")]), "trips": {"H2000|2026-11-05": {"credit": "11:20"}}}]
    p = tmp_path / "seed.json"
    p.write_text(json.dumps({"2026-11": snaps}))
    made = VER.seed(db, str(p), lambda ts: f"at{ts}")
    assert made == [("2026-11", "11.001"), ("2026-11", "11.002")]
    assert VER.seed(db, str(p), lambda ts: "x") == []  # months that already have versions are left alone
    # the live line equal to the last seeded version makes no new version
    assert VER.update(db, {"2026-11": _sched([("H2000", "2026-11-05")])}, {"H2000|2026-11-05": {"credit": "11:20"}}, "now") == []

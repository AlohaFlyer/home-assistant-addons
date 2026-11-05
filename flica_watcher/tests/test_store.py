import json

from pot import parse_pot
from store import Store


def test_legacy_state_import(tmp_path):
    legacy = tmp_path / "state.json"
    legacy.write_text(json.dumps({"baseline": {"mobile": ["H3644|01Nov"]}, "machine": "idle"}))
    st = Store(str(tmp_path / "w.db"), legacy_json=str(legacy))
    assert st.load_state()["baseline"]["mobile"] == ["H3644|01Nov"]
    assert not legacy.exists() and (tmp_path / "state.json.imported").exists()


def test_finds_history(tmp_path, fx):
    st = Store(str(tmp_path / "w.db"))
    base = parse_pot(fx("mobile_pot_rows.html"))
    st.record_pot("mobile", base, set())             # baseline: not a find
    assert st.recent_finds() == []
    after = parse_pot(fx("mobile_pot_rows_sin.html"))
    st.record_pot("mobile", after, {"H3655|12Nov"})
    f = st.recent_finds()
    assert [x["pairing"] for x in f] == ["H3655"] and f[0]["layover"] == "SIN" and f[0]["gone"] is None
    st.record_pot("mobile", base, set())             # SIN trip picked up by someone
    assert st.recent_finds()[0]["gone"] is not None


def test_live_flags_and_counts(tmp_path):
    st = Store(str(tmp_path / "w.db"))
    st.set_live("sin", True)
    assert st.live_flags() == {"sin": True}
    st.add_match({"at": "2026-10-31T20:00:00+00:00", "rule_id": "sin", "dry_run": False,
                  "would_submit": True, "reason": "live", "row": {"pairing": "H3655"}}, "k")
    assert st.would_submits_since("2026-10-31T10:00:00+00:00") == {"sin": 1}
    st.drop_live("sin")
    assert st.live_flags() == {}


def test_find_row_stays_current_while_open(tmp_path):
    st = Store(str(tmp_path / "w.db"))
    row = {"pairing": "H3633", "start": "26Nov", "dates": "26Nov-27Nov", "credit": "11:56"}
    st.record_pot("mobile", {"H3633|26Nov": row}, {"H3633|26Nov"})
    assert st.recent_finds()[0]["captain"] == ""
    st.record_pot("mobile", {"H3633|26Nov": dict(row, captain="Lane Jr, Chris", x1="X")}, set())
    f = st.recent_finds()[0]
    assert f["captain"] == "Lane Jr, Chris" and f["prem"] is True
    st.set_pickup("H3633|26Nov", {"status": "filled", "by": "FO Roe, Rick", "ca": "Lane Jr, Chris", "known": True})
    f = st.recent_finds()[0]
    assert f["picked_by"] == "FO Roe, Rick" and f["pickup_known"] is True


def test_add_find_from_email(tmp_path):
    st = Store(str(tmp_path / "w.db"))
    st.add_find("H3627|18Nov", "mobile", {"pairing": "H3627", "start": "18Nov", "source": "email"},
                "2026-11-02T01:36:31+00:00", "2026-11-02T01:40:00+00:00")
    assert st.has_find("H3627|18Nov") and not st.has_find("H1|01Nov")
    f = st.recent_finds()[0]
    assert f["source"] == "email" and f["gone"] == "2026-11-02T01:40:00+00:00"
    st.add_find("H3627|18Nov", "mobile", {"pairing": "X"}, "2026-11-03T00:00:00+00:00")  # ignored
    assert st.recent_finds()[0]["pairing"] == "H3627"


def test_email_unchanged_cleared(tmp_path):
    st = Store(str(tmp_path / "w.db"))
    st.add_find("H3627|18Nov", "mobile", {"pairing": "H3627", "source": "email", "crew": [["FO", "Roe, Rick"]]},
                "2026-11-02T01:36:31+00:00", "2026-11-02T01:40:00+00:00")
    st.set_pickup("H3627|18Nov", {"status": "unchanged", "by": ""})
    assert st.email_unchanged() == ["H3627|18Nov"]
    st.clear_pickup("H3627|18Nov")
    assert st.email_unchanged() == [] and "crew" not in st.find_row("H3627|18Nov")
    assert st.recent_finds()[0]["pickup_status"] == ""


def test_patch_row_and_email_finds(tmp_path):
    st = Store(str(tmp_path / "w.db"))
    st.add_find("H3627|18Nov", "mobile", {"pairing": "H3627", "source": "email", "credit": "158:39"},
                "2026-11-02T01:36:31+00:00", "2026-11-02T01:40:00+00:00")
    assert st.email_finds() == ["H3627|18Nov"]
    st.patch_row("H3627|18Nov", {"credit": "15:00", "days": "3"})
    f = st.recent_finds()[0]
    assert f["credit"] == "15:00" and f["days"] == "3"


def test_picker_scoring(tmp_path):
    from store import Store, picker_of, fmt_dur
    assert picker_of("FO Lane Jr, Chris (10007)") == ("FO", "Lane Jr, Chris", "10007")
    assert picker_of("FO Doe, Pat") is None
    assert fmt_dur(137) == "2m 17s" and fmt_dur(42) == "42s" and fmt_dur(3900) == "1h 05m"
    db = Store(str(tmp_path / "t.db"))
    db.add_find("H3825|03Nov", "2026-11", {"pairing": "H3825", "start": "03Nov"}, "2026-11-03T22:12:00+00:00", gone="2026-11-03T22:14:17+00:00")
    db.set_pickup("H3825|03Nov", {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
    db.db.execute("UPDATE finds SET last_seen='2026-11-03T22:14:17+00:00' WHERE key='H3825|03Nov'")  # still listed at the last check
    assert db.score_pickup("H3825|03Nov") == 137
    assert db.score_pickup("H3825|03Nov") is None  # once
    db.add_find("H3606|18Nov", "2026-11", {"pairing": "H3606", "start": "18Nov"}, "2026-11-02T19:07:00+00:00", gone="2026-11-02T19:08:00+00:00")
    db.set_pickup("H3606|18Nov", {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
    db.db.execute("UPDATE finds SET last_seen='2026-11-02T19:08:00+00:00' WHERE key='H3606|18Nov'")
    db.score_pickup("H3606|18Nov")
    st = db.picker_stats()["10007"]
    assert st["n"] == 2 and st["total_s"] == 197
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H3825"]["picker_avg_s"] == 98 and f["H3825"]["picker_n"] == 2
    # unknown seat or email source: not scored
    db.add_find("H3609|06Nov", "2026-11", {"pairing": "H3609", "source": "email"}, "2026-11-03T21:25:00+00:00", gone="2026-11-03T21:26:00+00:00")
    db.set_pickup("H3609|06Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    assert db.score_pickup("H3609|06Nov") == 30  # 0.5.6/0.7.6: email-caught pickups score from the alert time to the middle of the gone window (approx)


def test_recheck_keeps_score(tmp_path):
    db = Store(str(tmp_path / "t.db"))
    db.add_find("H3657|16Nov", "2026-11", {"pairing": "H3657"}, "2026-11-03T05:00:00+00:00", gone="2026-11-03T05:07:00+00:00")
    db.set_pickup("H3657|16Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    db.db.execute("UPDATE finds SET last_seen='2026-11-03T05:07:00+00:00' WHERE key='H3657|16Nov'")
    assert db.score_pickup("H3657|16Nov") == 420
    db.set_pickup("H3657|16Nov", {"status": "filled", "by": "FO Roe, Rick (10009)", "ca": "", "known": True})  # re-check after a new alert
    assert db.score_pickup("H3657|16Nov") is None and db.picker_stats()["10008"]["n"] == 1 and "10009" not in db.picker_stats()


def test_inflt_backfill_and_counts(tmp_path):
    db = Store(str(tmp_path / "i.db"))
    db.add_find("H3647|07Nov", "2026-11", {"pairing": "H3647", "start": "07Nov"}, "2026-11-04T14:24:00+00:00", gone="2026-11-04T14:25:00+00:00")
    db.set_pickup("H3647|07Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    db.add_find("H3609|06Nov", "2026-11", {"pairing": "H3609", "start": "06Nov"}, "2026-11-03T21:25:00+00:00", gone="2026-11-03T21:26:00+00:00")
    db.set_pickup("H3609|06Nov", {"status": "filled", "by": "FO Roe, Rick", "ca": "", "known": True})  # no employee number
    todo = db.pickups_without_inflt()
    assert [t[:3] for t in todo] == [("H3647|07Nov", "10008", "2026-11-04T14:25:00+00:00")]
    db.set_inflt("H3647|07Nov", None, tries=1)        # a failed lookup only counts a try
    assert db.pickups_without_inflt()[0][3] == 1
    db.set_inflt("H3647|07Nov", True, "H3648 2026-11-03", tries=2)
    assert db.pickups_without_inflt() == []
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H3647"]["inflt"] is True and f["H3647"]["inflt_trip"] == "H3648 2026-11-03"
    assert f["H3609"]["inflt"] is None
    db.set_pickup("H3647|07Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})  # re-check keeps it
    assert db.recent_finds()[0]["inflt"] is True
    db.score_pickup("H3647|07Nov")
    assert db.picker_stats()["10008"]["inflt_n"] == 1
    db.add_find("H3630|05Nov", "2026-11", {"pairing": "H3630", "start": "05Nov"}, "2026-11-04T04:42:00+00:00", gone="2026-11-04T04:47:00+00:00")
    db.set_pickup("H3630|05Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    db.set_inflt("H3630|05Nov", None, tries=3)          # third failure: unknown for good
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert db.pickups_without_inflt() == [] and f["H3630"]["inflt"] is None


def test_reset_inflt(tmp_path):
    db = Store(str(tmp_path / "r.db"))
    db.add_find("H3647|07Nov", "2026-11", {"pairing": "H3647"}, "2026-11-04T14:24:00+00:00", gone="2026-11-04T14:25:00+00:00")
    db.set_pickup("H3647|07Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    db.set_inflt("H3647|07Nov", False, "", tries=1)
    assert db.pickups_without_inflt() == []
    db.reset_inflt()
    assert [t[0] for t in db.pickups_without_inflt()] == ["H3647|07Nov"]


def test_email_find_scored_approx(tmp_path):
    db = Store(str(tmp_path / "e.db"))
    db.add_find("H3647|07Nov", "2026-11", {"pairing": "H3647", "source": "email"}, "2026-11-04T14:24:00+00:00", gone="2026-11-04T14:25:00+00:00")
    db.set_pickup("H3647|07Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": False})
    assert db.score_pickup("H3647|07Nov") == 30
    f = db.recent_finds()[0]
    assert f["picker_approx"] is True and f["picker_avg_s"] == 30 and f["picker_n"] == 1
    db.add_find("H3609|06Nov", "2026-11", {"pairing": "H3609", "source": "email"}, "2026-11-03T21:25:00+00:00", gone="2026-11-03T21:26:00+00:00")
    db.set_pickup("H3609|06Nov", {"status": "filled", "by": "FO Doe, Pat (10008); RO Roe, Rick (10009)", "ca": "", "known": False})
    assert db.score_pickup("H3609|06Nov") is None  # two candidates: seat unknown, not scored


def test_picker_month_year_counts(tmp_path):
    from datetime import datetime, timedelta, timezone
    db = Store(str(tmp_path / "m.db"))
    db.add_find("H3825|03Nov", "2026-11", {"pairing": "H3825"}, "2026-11-03T22:12:00+00:00", gone="2026-11-03T22:14:17+00:00")
    db.set_pickup("H3825|03Nov", {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
    db.score_pickup("H3825|03Nov")
    db.add_find("H3606|18Oct", "2026-10", {"pairing": "H3606"}, "2026-10-02T19:07:00+00:00", gone="2026-10-02T19:08:00+00:00")
    db.set_pickup("H3606|18Oct", {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
    db.score_pickup("H3606|18Oct")
    now = datetime(2026, 11, 4, 8, 0, tzinfo=timezone(timedelta(hours=-10)))
    st = db.picker_stats(now)["10007"]
    assert st["n"] == 2 and st["month_n"] == 1 and st["year_n"] == 2
    db2 = Store(str(tmp_path / "m.db"))  # reopen: log backfill is idempotent
    assert db2.picker_stats(now)["10007"]["year_n"] == 2


def test_picker_common_layovers(tmp_path):
    from store import Store, lay_of
    assert lay_of({"layover": "-none-", "turn": "PPG"}) == "PPG" and lay_of({"layover": "lax"}) == "LAX" and lay_of({}) == ""
    db = Store(str(tmp_path / "l.db"))
    for i, (k, lay, turn) in enumerate((("H3601|01Nov", "LAX", ""), ("H3602|02Nov", "SEA", ""), ("H3603|03Nov", "LAX", ""), ("H3604|04Nov", "-none-", "PPG"))):
        db.add_find(k, "2026-11", {"pairing": k[:5], "layover": lay, "turn": turn}, f"2026-11-0{i + 1}T10:00:00+00:00", gone=f"2026-11-0{i + 1}T10:01:00+00:00")
        db.set_pickup(k, {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
        db.score_pickup(k)
    st = db.picker_stats()["10007"]
    assert st["lays"] == [["LAX", 2], ["PPG", 1], ["SEA", 1]] and st["last_lay"] == "PPG"
    db2 = Store(str(tmp_path / "l.db"))  # reopen: lay backfilled / kept
    assert db2.picker_stats()["10007"]["lays"][0] == ["LAX", 2]


def test_dwell_vetting(tmp_path):
    """0.7.6 (Ryan): Pickup Speed = FLICA alert time (or first sighting) to the middle of the window between
    the last check that listed the trip and the check that found it gone."""
    from store import Store, dwell
    assert dwell("2026-11-04T16:36:06+00:00", "2026-11-04T16:36:06+00:00", "2026-11-04T16:37:32+00:00") == (43, 43)
    assert dwell("2026-11-04T16:36:06+00:00", "2026-11-04T16:37:20+00:00", "2026-11-04T16:37:32+00:00") == (80, 6)
    assert dwell("2026-11-04T16:36:06+00:00", "2026-11-04T16:37:20+00:00", "2026-11-04T16:37:32+00:00", "2026-11-04T16:35:00+00:00") == (146, 6)
    assert dwell("2026-11-04T16:36:06+00:00", None, None) == (None, None)
    db = Store(str(tmp_path / "d.db"))
    db.add_find("H3676|16Nov", "2026-11", {"pairing": "H3676"}, "2026-11-04T16:36:06+00:00", gone="2026-11-04T16:37:32+00:00")
    db.set_pickup("H3676|16Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    db.db.execute("UPDATE finds SET last_seen='2026-11-04T16:37:20+00:00' WHERE key='H3676|16Nov'")
    assert db.score_pickup("H3676|16Nov") == 80
    assert db.set_alert_at("H3676|16Nov", "2026-11-04T16:35:00+00:00")  # the alert came first: rescored
    f = db.recent_finds()[0]
    assert f["dwell_s"] == 146 and f["dwell_pm_s"] == 6 and db.picker_stats()["10008"]["total_s"] == 146
    assert not db.set_alert_at("H3676|16Nov", "2026-11-04T16:36:00+00:00")  # a later alert does not win

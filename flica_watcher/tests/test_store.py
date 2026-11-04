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
    assert db.score_pickup("H3825|03Nov") == 137
    assert db.score_pickup("H3825|03Nov") is None  # once
    db.add_find("H3606|18Nov", "2026-11", {"pairing": "H3606", "start": "18Nov"}, "2026-11-02T19:07:00+00:00", gone="2026-11-02T19:08:00+00:00")
    db.set_pickup("H3606|18Nov", {"status": "filled", "by": "FO Lane Jr, Chris (10007)", "ca": "", "known": True})
    db.score_pickup("H3606|18Nov")
    st = db.picker_stats()["10007"]
    assert st["n"] == 2 and st["total_s"] == 197
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H3825"]["picker_avg_s"] == 98 and f["H3825"]["picker_n"] == 2
    # unknown seat or email source: not scored
    db.add_find("H3609|06Nov", "2026-11", {"pairing": "H3609", "source": "email"}, "2026-11-03T21:25:00+00:00", gone="2026-11-03T21:26:00+00:00")
    db.set_pickup("H3609|06Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    assert db.score_pickup("H3609|06Nov") is None

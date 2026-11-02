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
    st.record_pot("mobile", {"H3633|26Nov": dict(row, captain="Lau, Sean", x1="X")}, set())
    f = st.recent_finds()[0]
    assert f["captain"] == "Lau, Sean" and f["prem"] is True
    st.set_pickup("H3633|26Nov", {"status": "filled", "by": "FO Roe, Rick", "ca": "Lau, Sean", "known": True})
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

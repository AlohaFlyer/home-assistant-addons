from datetime import date
from pathlib import Path

from pot import fit_tag, parse_schedule

FX = Path(__file__).parent / "fixtures"


def sched():
    return parse_schedule((FX / "mobile_schedule_nov.html").read_text())


def test_parse_schedule_items_and_totals():
    s = sched()
    assert s["month"] == "2026-11" and s["updated"].startswith("Nov 1, 2026 09:54")
    trips = {i["trip"]: (i["start"], i["end"], i["lay"]) for i in s["items"]}
    assert trips["H3815"] == ("2026-11-01", "2026-11-04", "SIN")
    assert trips["H3659"] == ("2026-11-18", "2026-11-19", "SEA")
    assert trips["VAC"] == ("2026-11-22", "2026-11-28", "")
    assert trips["H3607"] == ("2026-11-30", "2026-12-02", "KIX")
    assert s["totals"] == {"block": "92.33", "credit": "121.48", "ytd": "592.22", "days_off": 15}
    assert s["days"][-1] == ["2026-12-02", "", "HNL"]


def test_not_a_schedule():
    assert parse_schedule("<html>Open Time pot</html>") is None


def test_fit_tags():
    s = sched()
    assert fit_tag(date(2026, 11, 26), date(2026, 11, 27), s) == "Conflict VAC"
    assert fit_tag(date(2026, 11, 2), date(2026, 11, 3), s) == "Conflict H3815"
    assert fit_tag(date(2026, 11, 16), date(2026, 11, 17), s) == "Check rest H3629"
    assert fit_tag(date(2026, 11, 20), date(2026, 11, 21), s) == "Check rest H3659"
    assert fit_tag(date(2026, 12, 10), date(2026, 12, 11), s) == ""
    s["items"] = [i for i in s["items"] if i["trip"] not in ("H3629", "H3659")]
    assert fit_tag(date(2026, 11, 16), date(2026, 11, 17), s) == "Fits"
    s["totals"]["days_off"] = 13
    assert fit_tag(date(2026, 11, 16), date(2026, 11, 17), s) == "Days off 11"

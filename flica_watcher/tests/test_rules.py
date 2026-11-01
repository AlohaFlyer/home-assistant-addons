from datetime import datetime, timedelta, timezone

import pytest

import rules as R
from pot import parse_pot

NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)  # 10:00 HST
OLD = (NOW - timedelta(days=8)).isoformat()
NEW = (NOW - timedelta(days=1)).isoformat()


def rule(**kw):
    base = {"id": "sin", "name": "SIN", "mode": "alert", "match": {"layover": ["SIN"]}, "created_at": OLD}
    base.update(kw)
    clean, errs = R.validate([base], NOW)
    assert errs == []
    return clean[0]


@pytest.fixture
def sin_row(fx):
    return parse_pot(fx("mobile_pot_rows_sin.html"))["H3655|12Nov"]


@pytest.fixture
def lax_row(fx):
    return parse_pot(fx("mobile_pot_rows.html"))["H3644|01Nov"]


# ---- the 10 matcher cases from spec section 4
def test_01_sin_present(sin_row):
    assert R.matches(rule(), sin_row, NOW.date()) == (True, "")


def test_02_sin_absent(lax_row):
    assert R.matches(rule(), lax_row, NOW.date()) == (False, "layover")


def test_03_months_next(sin_row):
    assert R.matches(rule(match={"layover": ["SIN"], "months": ["next"]}), sin_row, NOW.date())[0]
    assert not R.matches(rule(match={"months": ["current"]}), sin_row, NOW.date())[0]


def test_04_date_window_edges_inclusive(sin_row):
    r = rule(match={"date_from": "2026-11-12", "date_to": "2026-11-12"})
    assert R.matches(r, sin_row, NOW.date())[0]
    assert R.matches(rule(match={"date_from": "2026-11-13"}), sin_row, NOW.date()) == (False, "before date_from")
    assert R.matches(rule(match={"date_to": "2026-11-11"}), sin_row, NOW.date()) == (False, "after date_to")


def test_05_min_credit_and_max_days(sin_row):
    assert R.matches(rule(match={"min_credit": 24}), sin_row, NOW.date())[0]          # 24.10 pay
    assert not R.matches(rule(match={"min_credit": 24.5}), sin_row, NOW.date())[0]
    assert R.matches(rule(match={"max_days": 4}), sin_row, NOW.date()) == (False, "days")


def test_06_report_window(sin_row):
    assert R.matches(rule(match={"report_after": "09:00", "report_before": "10:00"}), sin_row, NOW.date())[0]
    assert not R.matches(rule(match={"report_after": "10:00"}), sin_row, NOW.date())[0]


def test_07_alert_rule_never_submits(sin_row):
    m = R.evaluate([rule()], sin_row, {"sin": True}, {}, NOW)
    assert len(m) == 1 and m[0]["would_submit"] is False and m[0]["reason"] == "alert rule"


def test_08_auto_add_dry_run_default(sin_row):
    m = R.evaluate([rule(mode="auto_add")], sin_row, {}, {}, NOW)
    assert m[0]["dry_run"] and not m[0]["would_submit"]


def test_09_live_needs_switch_week_and_cap(sin_row):
    young = rule(mode="auto_add", dry_run=False, created_at=NEW)
    assert not R.evaluate([young], sin_row, {"sin": True}, {}, NOW)[0]["would_submit"]
    assert not R.live_allowed(young, NOW)[0]
    old = rule(mode="auto_add", dry_run=False)
    assert R.live_allowed(old, NOW)[0]
    m = R.evaluate([old], sin_row, {"sin": True}, {}, NOW)[0]
    assert m["would_submit"] and "nothing sent" in m["reason"]
    capped = R.evaluate([old], sin_row, {"sin": True}, {"sin": 3}, NOW)[0]
    assert not capped["would_submit"] and capped["reason"].startswith("cap")


def test_10_disabled_and_expired(sin_row):
    assert R.evaluate([rule(enabled=False)], sin_row, {}, {}, NOW) == []
    assert R.evaluate([rule(expires_at="2026-10-31T00:00:00-10:00")], sin_row, {}, {}, NOW) == []


def test_writes_not_implemented():
    assert R.WRITES_IMPLEMENTED is False


def test_validate_rejects_bad_input():
    _, e = R.validate([{"id": "Bad Id"}])
    assert e
    _, e = R.validate([{"id": "a", "mode": "auto_swap"}])
    assert any("swap.give" in x for x in e)
    _, e = R.validate([{"id": "a", "match": {"months": ["soon"], "colour": 1}}])
    assert len(e) == 2
    _, e = R.validate([{"id": "a"}, {"id": "a"}])
    assert any("duplicate" in x for x in e)
    assert R.validate({"id": "a"})[1] == ["rules must be a JSON list"]


def test_validate_defaults_and_example():
    clean, e = R.validate(R.EXAMPLE, NOW)
    assert e == [] and clean[0]["dry_run"] is True and clean[0]["cap_per_day"] == 3
    assert clean[0]["created_at"] == NOW.isoformat()

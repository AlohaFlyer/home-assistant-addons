"""1.8.3 (Ryan, Nov 24, 2026: "pay looks off"): FLICA's month credit for October 2026 was 87:01 while the card counted
47:05 (its SIM, SICK, GDO, SCR days have no row price), so Pay-Gross, Pay-Net and Awarded/Improved were about half of
what the stubs paid. The credit FLICA shows beyond the trips, vacation and PAYP, in a month that holds such codes, is
now priced at the month's rate and shown as 'Other'. Synthetic month and made-up trips."""
import re

from test_release_a_schedule_card import READ_JS, _read, _render


def _with(codes, credit):
    st = _read(prefs=True)
    m = st["sensor.flight_watcher_schedule"]["attributes"]["months"]["2026-11"]
    days = [list(d) for d in m["days"]]
    for i, c in zip((9, 10, 11), codes):
        days[i] = [days[i][0], c, ""]
    m["days"], m["totals"] = days, {"credit": credit}
    return st


def _usd(tot, label):
    g = re.search(label + r"\s*\$([\d,]+)", tot)
    return int(g.group(1).replace(",", "")) if g else None


def test_other_credit_is_priced_and_shown():
    got = _render([("codes", READ_JS, _with(("SIM1", "SIM1", "SICK"), "30:00")),
                   ("none", READ_JS, _with(("", "", ""), "30:00"))])
    c, n = got["codes"]["tot"], got["none"]["tot"]
    assert "Other18:00" in c.replace(" ", "") and "SIM1" in c and "SICK" in c
    assert "Credit30:00" in c.replace(" ", "")  # FLICA's month credit, now counted
    assert "Other" not in n  # no codes: the gap stays unpriced and flagged against FLICA, as before
    g1, g0 = _usd(c, "Pay-Gross"), _usd(n, "Pay-Gross")
    assert g1 and g0 and g1 > g0
    rate = (g1 - g0) / 18
    assert 50 < rate < 400  # 18:00 at the year 3 FO rate

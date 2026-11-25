"""1.8.4 (Hark for Ryan, Nov 25, 2026: his open days in December 2026 are Dec 3 to 11): the add-on option
pot_open_days holds a new open time pot pairing's alert (event/new_pairing, the pushes) unless it starts on an open day
and is home by the last one. Empty (the default) alerts as before; a month no range touches alerts as before; the pot,
the finds and the rules are unchanged. And the December schedule regression (Nov 23: "FW does not appear to be updating
my schedule completely for December"): a December page laid out like Ryan's (trips Dec 6, 9 and 12, VAC Dec 18 to 24)
reads on its own days on both schedule pages. FLICA is never reached; pairings are made up (H39xx), "Doe, Jane"."""
import json
from datetime import date

import yaml

import inflt
import opendays as OD
import pot as P
from test_fw181_pot_month import _check, _new, _w, at
from test_fw182_bid_month_sched import _days, _lkr, _mob
from test_release_a_flica import mk, real_fl  # noqa: F401

DEC_OPEN = ["2026-12-03..2026-12-11"]


def pot_page(rows, cat="HNL 332 FO"):
    """A synthetic mobile open time page: rows (pairing, start 'DDMon', end 'DDMon', days)."""
    trs = "".join(f"<tr><td>{p}</td><td>{s}</td><td>{e}</td><td>6.10</td><td>LAS</td><td></td><td></td>"
                  f"<td>09:00</td><td>15:00</td><td>{n}</td><td></td></tr>" for p, s, e, n in rows)
    return f"<html><body><h3>Open Time Pot {cat}</h3><table>{trs}</table></body></html>"


BASE = [("H3901", "04Dec", "05Dec", 2), ("H3902", "20Dec", "21Dec", 2)]


# ---------------------------------------------------------------- the rule (opendays.py)
def test_parse_merges_ranges_and_reports_bad_items():
    spans, bad = OD.parse(["2026-12-03..2026-12-06", " 2026-12-07 .. 2026-12-11 ", "2026-12-20", "Dec 3",
                           "2026-12-11..2026-12-03", "2026-02-30"])
    assert spans == [(date(2026, 12, 3), date(2026, 12, 11)), (date(2026, 12, 20), date(2026, 12, 20))]
    assert bad == ["Dec 3", "2026-12-11..2026-12-03", "2026-02-30"]
    assert OD.parse([]) == ([], []) and OD.parse(None) == ([], [])
    assert OD.months(OD.parse(["2026-12-30..2027-01-02"])[0]) == {"2026-12", "2027-01"}


def test_verdict_on_ryans_december():
    sp, _ = OD.parse(DEC_OPEN)
    d = lambda n: date(2026, 12, n)  # noqa: E731
    assert OD.verdict(sp, d(3), d(4)) == "" and OD.verdict(sp, d(6), d(8)) == "" and OD.verdict(sp, d(11)) == ""
    assert OD.verdict(sp, d(9), d(11)) == ""  # home on the last open day
    assert OD.verdict(sp, d(2), d(3)) == "starts 2026-12-02, not an open day"
    assert OD.verdict(sp, d(12), d(14)) == "starts 2026-12-12, not an open day"
    assert OD.verdict(sp, d(10), d(12)) == "runs to 2026-12-12, past the last open day 2026-12-11"
    assert OD.verdict(sp, date(2026, 11, 28), d(1)) == ""  # November: no range touches it, alerts as before
    assert OD.verdict(sp, date(2027, 1, 5)) == ""  # January too
    assert OD.verdict([], d(20)) == "" and OD.verdict(sp, None) == ""  # no option, no date: as before


# ---------------------------------------------------------------- the pot read: alerts held, pot unchanged
def test_pot_alerts_only_for_pairings_inside_the_open_days(mk):
    W, fl, pages = _w(mk, at(2026, 11, 25, 9), "Next month", {"003.153": pot_page(BASE)})
    W.row_date = lambda s, today=date(2026, 11, 25): P.row_date(s, today=today)
    W.OPTS["pot_open_days"] = list(DEC_OPEN)
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == []  # December's baseline
    new = [("H3911", "06Dec", "07Dec", 2),   # inside: alerts
           ("H3912", "09Dec", "11Dec", 3),   # home on Dec 11: alerts
           ("H3913", "02Dec", "03Dec", 2),   # starts before the open days: held
           ("H3914", "10Dec", "12Dec", 3),   # runs past Dec 11: held
           ("H3915", "15Dec", "16Dec", 2)]   # after the open days: held
    pages["003.153"] = pot_page(BASE + new)
    assert _check(W, fl, step=1800) == ("ok", ["003.153"])
    assert _new(W) == ["H3911", "H3912"]
    rows = W.MQ.last(f"{W.T}/pot/state")
    assert {r["pairing"] for r in rows["pairings"]} >= {"H3913", "H3914", "H3915"}  # still on the pot


def test_empty_option_and_a_pilots_watcher_alert_as_before(mk):
    for inst, opt in (("", []), ("", None), ("pilot2", DEC_OPEN)):
        W = mk(inst, t=at(2026, 11, 25, 9))
        W.row_date = lambda s, today=date(2026, 11, 25): P.row_date(s, today=today)
        if opt is not None:
            W.OPTS["pot_open_days"] = list(opt)
        ev = {"pairing": "H3913", "start": "02Dec", "end": "03Dec", "days": "2"}
        assert W.pot_alert_hold(ev) == "" and W.pot_alert(dict(ev), "pairing") is True


def test_held_pairing_logs_why_and_a_bad_item_is_logged_once(mk, caplog):
    W = mk("", t=at(2026, 11, 25, 9))
    W.row_date = lambda s, today=date(2026, 11, 25): P.row_date(s, today=today)
    W.OPTS["pot_open_days"] = DEC_OPEN + ["Dec 20"]
    ev = {"pairing": "H3914", "start": "10Dec", "end": "12Dec", "days": "3"}
    with caplog.at_level("INFO"):
        assert W.pot_alert(ev, "pairing") is False
        W.pot_alert(dict(ev), "pairing")
    assert ev["open_days"] == "runs to 2026-12-12, past the last open day 2026-12-11"
    assert not [t for t, _ in W.MQ.msgs if t.endswith("/event/new_pairing")]
    assert "H3914 10Dec: no alert (pot_open_days: runs to 2026-12-12" in caplog.text
    assert caplog.text.count("pot_open_days: ignored Dec 20") == 1


# ---------------------------------------------------------------- the add-on option
def test_config_option_default_empty_and_schema_accepts_the_range():
    import os
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = yaml.safe_load(open(os.path.join(here, "config.yaml"), encoding="utf-8"))
    assert cfg["options"]["pot_open_days"] == []
    pat = cfg["schema"]["pot_open_days"][0]
    assert pat.startswith("match(") and pat.endswith(")")
    rx = re.compile(pat[len("match("):-1])
    assert rx.match("2026-12-03..2026-12-11") and rx.match("2026-12-15") and not rx.match("Dec 3 to 11")
    assert "opendays.py" in open(os.path.join(here, "Dockerfile"), encoding="utf-8").read()


# ---------------------------------------------------------------- the December schedule regression
TRIPS = {"2026-12-06": ("H3961", "LAS", 3), "2026-12-09": ("H3962", "SEA", 2), "2026-12-12": ("H3963", "JFK", 4)}
WANT = [("H3961", "2026-12-06", "2026-12-08"), ("H3962", "2026-12-09", "2026-12-10"),
        ("H3963", "2026-12-12", "2026-12-15"), ("VAC", "2026-12-18", "2026-12-24")]


def _vac(html, mobile):
    for d in _days("2026-12-18", "2026-12-24"):
        if mobile:
            html = html.replace(f"<td>{d[8:]}</td><td>-</td>", f"<td>{d[8:]}</td><td>VAC</td>", 1)
        else:
            html = html.replace(f'"{d[8:]}", "", "", "{d.replace("-", "")}"', f'"{d[8:]}", "VAC", "", '
                                f'"{d.replace("-", "")}"', 1)
    return html


def test_december_reads_on_its_own_days_on_both_schedule_pages():
    rows = _days("2026-11-30", "2026-12-31")  # December's page starts with its carry-in rows
    mob = P.parse_schedule(_vac(_mob("Dec", 2026, rows, TRIPS), True))
    lk = inflt.parse_cm_month(_vac(_lkr("1226", rows, TRIPS), False))
    for sp in (mob, lk):
        assert sp["month"] == "2026-12"
        assert [(i["trip"], i["start"], i["end"]) for i in sp["items"]] == WANT
        assert sp["days"][0][0] == "2026-11-30" and sp["days"][-1][0] == "2026-12-31"
    assert json.dumps(mob["items"]) == json.dumps(lk["items"])

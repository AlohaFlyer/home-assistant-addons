"""1.8.1 (Ryan, Nov 23, 2026: "Always look for the new pot each month. It's a different bcid"; "I'm working on Dec
now"): the open time pot follows the bid month. Each check reads the pot page of the bid month(s) the Pot month select
chooses (This month, Next month, Both), from that month's own BCID: learned (Ryan's two links, then each month whose
page read with its own trips), named by a menu or pot page link, or derived from the latest learned month. A page of
another month's trips is refused. FLICA is never reached: a fake browser answers with synthetic pages (made-up
pairings H39xx, no names)."""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

import pot as P
import roles
from test_release_a_flica import mk, real_fl  # noqa: F401

HST = timezone(timedelta(hours=-10))
BASE = "https://ha2.flica.net"
NOT_OPEN = "<html><body>flica.net - Invalid or unspecified bid period</body></html>"
STUBS = ("schedule_check", "own_trip_times", "publish_working_flight", "versions_check", "uploads_check", "capture",
         "detail_probe", "pot_details", "email_check", "pickup_check", "tradeboard_check", "requests_check",
         "grid_check", "publish_finds", "publish_tickets", "enrich", "swap_scan", "drop_scan", "publish_near_misses")


def at(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=HST).timestamp()


def page(rows=(), links=(), cat="HNL 332 FO"):
    """A synthetic mobile open time page: rows (pairing, start 'DDMon'), links (bcid, text), its category."""
    trs = "".join(f"<tr><td>{p}</td><td>{s}</td><td>{s}</td><td>6.10</td><td>-none-</td><td></td><td></td>"
                  f"<td>09:00</td><td>15:00</td><td>1</td><td></td></tr>" for p, s in rows)
    a = "".join(f'<a href="mobileopentimepot.cgi?BCID={b}&amp;From=MainMenu">{t}</a> ' for b, t in links)
    return f"<html><body><h3>Open Time Pot {cat}</h3>{a}<table>{trs}</table></body></html>"


NOV = [("H3901", "26Nov"), ("H3902", "28Nov")]
DEC = [("H3911", "03Dec"), ("H3912", "12Dec"), ("H3913", "20Dec")]
JAN = [("H3921", "04Jan"), ("H3922", "15Jan")]


def _w(mk, t, mode=None, pages=None):
    W = mk("", t=t)
    for f in STUBS:
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    if mode:
        W.S["pot_month"] = mode
    W.S["pot_urls"] = {}
    pages = {} if pages is None else pages
    fl = real_fl(W, lambda u: pages.get(W.bcid(u), NOT_OPEN) if "opentimepot" in u else "<html><body>x</body></html>")
    return W, fl, pages


def _pot_loads(W, fl):
    return [W.bcid(u) for _, u in fl.loads if "mobileopentimepot" in u]


def _check(W, fl, step=600):
    """One check; the pot pages it fetched (BCIDs, in order)."""
    n = len(_pot_loads(W, fl))
    W.RUN.update(check=True, aborted="", skipped=set())
    try:
        res = W.check(fl)
    finally:
        W.RUN["check"] = False
    W.CLOCK.t += step
    return res, _pot_loads(W, fl)[n:]


def _new(W):
    return [json.loads(p)["pairing"] for t, p in W.MQ.msgs if t == f"{W.T}/event/new_pairing"]


# ---------------------------------------------------------------- D1: the BCID of a month
def test_pot_bcid_follows_the_bid_month_from_the_anchor(mk):
    W = mk("")
    assert W.POT_BCID_ANCHOR == ((2026, 11), "003", 152)
    assert [W.pot_bcid(*ym) for ym in ((2026, 11), (2026, 12), (2027, 1), (2027, 12))] == \
        ["003.152", "003.153", "003.154", "003.165"]
    assert W.pot_bcid(2027, 3, ((2027, 1), "003", 160)) == "003.162"  # from another anchor (a month learned)
    assert W.mobile_pot_url("003.153") == f"{BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    assert "otframe" not in W.mobile_pot_url("003.153") and W.close_in_url("008.153") == W.mobile_pot_url("008.153")
    assert not hasattr(W, "MOBILE_POT")  # 1.8.0's hard-coded November page is gone
    src = open(os.path.join(os.path.dirname(W.__file__), "watcher.py"), encoding="utf-8").read()
    assert "BCID=003.152&From" not in src


def test_a_page_counts_for_a_month_only_with_its_own_trips():
    assert P.pot_month_check(page(DEC), "2026-12")["verdict"] == "ok"
    r = P.pot_month_check(page(NOV), "2026-12")
    assert r["verdict"] == "refused" and r["other"] == "2026-11" and r["dated"] == 2
    assert r["inside"] == 1  # 28Nov: inside the 3 day slack of a bid period's edge
    assert P.pot_month_check(page(), "2026-12")["verdict"] == "empty"  # an empty pot names no month
    assert P.pot_month_check(NOT_OPEN, "2026-12")["verdict"] == "not open"
    # a bid period's edge (November's runs Nov 1 to Dec 1) and one odd row are no refusal
    assert P.pot_month_check(page(NOV + [("H3903", "01Dec")]), "2026-11")["verdict"] == "ok"
    assert P.pot_month_check(page(DEC + [("H3904", "20Nov")]), "2026-12")["verdict"] == "ok"
    assert P.pot_month_check(page([("H3921", "04Jan")]), "2027-01")["verdict"] == "ok"  # the year from the month
    assert P.pot_month_check(page(DEC), "2027-01")["verdict"] == "refused"


# ---------------------------------------------------------------- D2 and D3: the three modes across Nov 30 to Dec 1
def test_this_month_reads_one_page_a_check_and_rolls_to_december_without_alerts(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), pages={"003.152": page(NOV), "003.153": page(DEC)})
    assert W.pot_mode() == "This month"
    assert _check(W, fl) == ("ok", ["003.152"]) and _new(W) == []  # first read: its baseline only
    pages["003.152"] = page(NOV + [("H3905", "29Nov")])
    assert _check(W, fl, step=1800) == ("ok", ["003.152"]) and _new(W) == ["H3905"]
    assert W.local_now().day == 1  # Dec 1, 00:10 HST
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == ["H3905"]  # December's first read: no alert
    assert list(W.S["baseline"]) == ["2026-12"]  # November's baseline dropped as before
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == ["H3905", "H3914"]


def test_next_month_reads_december_now_and_keeps_it_after_dec_1_with_one_page_a_check(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), "Next month", {"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == []
    assert list(W.S["pot_urls"]) == ["2026-12"]
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl, step=1800) == ("ok", ["003.153"]) and _new(W) == ["H3914"]
    # Dec 1: January (derived 003.154) is tried once in place of December's page (its rows of the check before)
    res, got = _check(W, fl)
    assert (res, got) == ("ok", ["003.154"]) and W.pot_status("2027-01") == "not open yet"
    rows = W.MQ.last(f"{W.T}/pot/state")
    assert rows["count"] == 4 and {r["pairing"] for r in rows["pairings"]} >= {"H3911", "H3914"}
    pages["003.153"] = page(DEC + [("H3914", "24Dec"), ("H3915", "27Dec")])
    for _ in range(3):  # December again, one page a check; its baseline carried through the try
        assert _check(W, fl)[1] == ["003.153"]
    assert _new(W) == ["H3914", "H3915"]
    W.CLOCK.t += 86400  # a day later January is tried again, and it opened with its trips: learned, read from now on
    pages["003.154"] = page(JAN)
    assert _check(W, fl)[1] == ["003.154"] and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    assert _new(W) == ["H3914", "H3915"]  # January's first read is its baseline
    assert _check(W, fl)[1] == ["003.154"] and list(W.S["pot_urls"]) == ["2027-01"]
    assert list(W.S["baseline"]) == ["2027-01"]


def test_next_month_falls_back_to_this_month_while_the_next_page_is_refused(mk):
    W, fl, pages = _w(mk, at(2026, 12, 20), "Next month", {"003.153": page(DEC), "003.154": page(DEC)})
    # the first check after a start: no rows of December's on hand yet, so December's page only; the try stays due
    assert _check(W, fl)[1] == ["003.153"] and W.pot_status("2027-01") == "" and W.pot_due("2027-01")
    assert _check(W, fl)[1] == ["003.154"]  # the try, in place of December's read (its rows of the check before)
    assert W.MQ.last(f"{W.T}/pot/state")["count"] == 3  # December's rows stood in
    assert W.pot_status("2027-01") == "refused" and "2027-01" not in W.pot_learned()
    assert "January 2027 open time pot: BCID 003.154 refused (its trips start in December 2026)" in W.S["note"]
    assert list(W.S["pot_urls"]) == ["2026-12"] and _new(W) == []
    for _ in range(3):
        assert _check(W, fl)[1] == ["003.153"]  # this month's page, one a check, until the next try
    a = W.pot_months_attr()
    assert [(x["month"], x["bcid"], x["how"], x["status"], x["read"]) for x in a] == [
        ("2026-12", "003.153", "learned", "ok", True), ("2027-01", "003.154", "not found yet", "refused", False)]


def test_both_reads_this_and_next_once_open(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl, step=1800) == ("ok", ["003.152", "003.153"]) and _new(W) == []
    assert _check(W, fl) == ("ok", ["003.153", "003.154"])  # Dec 1: December, and January's first try
    for _ in range(2):
        assert _check(W, fl)[1] == ["003.153"]  # January not open: tried again tomorrow
    assert _new(W) == []


def test_a_learned_month_keeps_its_bcid_when_a_read_refuses_it(mk):
    W, fl, pages = _w(mk, at(2027, 1, 10), pages={"003.154": page(JAN)})
    assert _check(W, fl)[1] == ["003.154"] and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    pages["003.154"] = page(DEC)  # one page of another month's trips: read again next check, its baseline kept
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "ok"
    assert W.pot_rec("2027-01")["refusals"] == 1 and "refused" not in W.S.get("note", "")
    assert list(W.S["pot_urls"]) == ["2027-01"] and W.S["baseline"]["2027-01"] == ["H3921|04Jan", "H3922|15Jan"]
    pages["003.154"] = page(JAN + [("H3923", "20Jan")])  # a trip that came meanwhile alerts on the next good read
    assert _check(W, fl)[1] == ["003.154"] and _new(W) == ["H3923"] and "refusals" not in W.pot_rec("2027-01")
    pages["003.154"] = page(DEC)  # three refused reads in a row: the month waits for its try (6 h)
    for _ in range(3):
        assert _check(W, fl)[1] == ["003.154"]
    assert W.pot_status("2027-01") == "refused" and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    assert "refused" in W.S["note"]
    assert _check(W, fl)[1] == [] and list(W.S["pot_urls"]) == []  # nothing read until its try (6 h)
    assert "2027-01" in W.S["baseline"]  # kept: the month is still the select's
    W.CLOCK.t += 6 * 3600
    pages["003.154"] = page(JAN + [("H3923", "20Jan"), ("H3924", "25Jan")])
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "ok" and "refused" not in W.S["note"]
    assert _new(W) == ["H3923", "H3924"]  # the trip posted while the month waited alerts (its baseline was kept)


def test_a_month_is_derived_from_the_latest_learned_one(mk):
    """One renumbering by FLICA is learned once: January found on 003.160 (a link), February derives 003.161."""
    W, fl, pages = _w(mk, at(2027, 1, 2), pages={"003.153": page(DEC, links=[("003.160", "Jan")])})
    W.S["pot_month"] = "This month"
    assert W.pot_pick("2027-01") == ("003.154", "derived")
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "not open yet"
    # a page that names January's pot (December's, its link 'Jan'): a candidate, read and checked, then learned
    assert W.pot_link_scan(page(DEC, links=[("003.160", "Jan"), ("008.154", "Close in Opentime")]),
                           W.mobile_pot_url("003.153"), "2026-12") is None
    assert W.S["pot_cands"] == {"2027-01": {"bcid": "003.160", "how": "link", "at": W.S["pot_cands"]["2027-01"]["at"]}}
    pages["003.160"] = page(JAN)
    assert _check(W, fl)[1] == ["003.160"] and W.pot_learned()["2027-01"]["how"] == "menu"
    assert W.pot_derive("2027-02") == "003.161" and W.pot_pick("2027-03") == ("003.162", "derived")


def test_the_close_in_folder_is_never_a_months_pot(mk):
    W, fl, pages = _w(mk, at(2026, 12, 5))
    W.S["close_in"] = {"bcid": "008.153", "verified": True}
    html = page(DEC, links=[("008.153", "Open time"), ("008.154", "Jan"), ("001.154", "Jan"),
                            ("003.154", "Close in Opentime: &lt;16 Hrs to RPT"),
                            ("003.160", "Close in Opentime: &lt;16 Hrs to RPT")])  # not the derived 003.154 either
    W.pot_link_scan(html, W.mobile_pot_url("003.153"), "2026-12")
    assert not W.S.get("pot_cands")
    assert not W.pot_cand("2027-01", "008.153", "menu", "main menu")  # a close-in BCID is never a candidate


# ---------------------------------------------------------------- D1b: the main menu look
class _Frame:
    def __init__(self, links):
        self.url = f"{BASE}/online/leftmenu.cgi"
        self._links = links

    def evaluate(self, js, sec):
        assert "View Opentime Pot" in js and sec == "OPEN TIME"
        return self._links

    def content(self):
        return "<html><body>menu</body></html>"


class _Page:
    def __init__(self, frames, html="<html></html>"):
        self.frames, self._html, self.url = frames, html, f"{BASE}/online/mainmenu.cgi"

    def goto(self, *a, **k):
        pass

    def content(self):
        return self._html

    def close(self):
        pass


def test_a_month_not_found_is_looked_for_on_the_main_menu_at_most_every_6_h(mk):
    W, fl, pages = _w(mk, at(2027, 1, 2), pages={"003.161": page(JAN)})
    W.OPTS["pot_section"] = "OPEN TIME"  # the add-on option's default
    links = [{"i": 0, "section": "OPEN TIME- Add/Swap/Drop requests", "month": "January",
              "href": "javascript:openOT('/full/otframe.cgi?BCID=003.161&ViewOT=1');"},
             {"i": 1, "section": "Close in Opentime: <16 Hrs to RPT", "month": "January", "href": "BCID=008.161"}]
    opened = []
    fl.ctx.new_page = lambda: opened.append(1) or _Page([_Frame(links)])
    fl.save = lambda: None
    gated = []
    real = fl._load
    fl._load = lambda url=None: gated.append(url) or real(url)
    assert _check(W, fl)[1] == ["003.154"] and not opened  # the derivation first: not open
    assert W.pot_look_months() == ["2027-01"]
    assert _check(W, fl)[1] == ["003.161"] and opened == [1]  # the menu names 003.161 (no click): read and checked
    assert W.pot_learned()["2027-01"] == {"bcid": "003.161", "how": "menu", "at": W.pot_learned()["2027-01"]["at"]}
    assert None in gated  # the main menu load went through the gate
    a = W.pot_months_attr()
    assert [(x["month"], x["bcid"], x["how"], x["status"]) for x in a] == [("2027-01", "003.161", "learned", "ok")]
    # a month whose pick is still not open is looked for again only 6 h later
    W2, fl2, _ = _w(mk, at(2027, 1, 2))
    W2.OPTS["pot_section"] = "OPEN TIME"
    opened2 = []
    fl2.ctx.new_page = lambda: opened2.append(1) or _Page([], "<html><body>going to forward</body></html>")
    for _ in range(4):
        _check(W2, fl2, step=1800)
    assert opened2 == [1]
    W2.CLOCK.t += 6 * 3600
    _check(W2, fl2)
    assert opened2 == [1, 1] and W2.S["machine"] != "stopped_unexpected"  # a menu that does not load is no stop


# ---------------------------------------------------------------- 1.8.0 pages carry over, the select, the attribute
def test_the_update_from_1_8_0_carries_the_november_baseline_over(mk):
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV + [("H3906", "30Nov")])})
    W.S["baseline"] = {"mobile": ["H3901|26Nov", "H3902|28Nov"]}
    W.S["fingerprints"] = {"mobile": W.header_fingerprint(page(NOV))}
    W.pot_start()
    assert W.S["pot_plan"] and W.pot_mode() == "This month"
    assert _check(W, fl)[1] == ["003.152"] and _new(W) == ["H3906"]  # the trip that came during the update alerts
    assert sorted(W.S["baseline"]) == ["2026-11"] and "mobile" not in W.S["fingerprints"]


def test_the_select_is_restored_at_start_and_a_change_replans_and_wakes(mk, monkeypatch):
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV), "003.153": page(DEC)})
    ent = {oid: (comp, cfg) for comp, oid, cfg, f in W.entity_defs()}
    comp, cfg = ent["pot_month"]
    assert comp == "select" and cfg["name"] == "Pot month" and cfg["options"] == ["This month", "Next month", "Both"]
    assert cfg["command_topic"] == "flight_watcher/pot_month/set"
    assert cfg["state_topic"] == "flight_watcher/pot_month/state"
    assert cfg["default_entity_id"] == "select.flight_watcher_pot_month"
    assert "pot_month/set" in roles.SUBS and "pot_month/set" not in roles.PORTAL_CMDS
    assert "pot_month/set" in roles.NOT_ON_PORTAL and not roles.entity_on_portal("pot_month", "james")
    assert _check(W, fl)[1] == ["003.152"]
    woke = []
    monkeypatch.setattr(W, "WAKE", types.SimpleNamespace(set=lambda: woke.append(1)))
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/pot_month/set", payload=b"Next month"))
    assert W.S["pot_month"] == "Next month" and W.S["pot_urls"] == {} and woke == [1]
    assert [p for t, p in W.MQ.msgs if t == f"{W.T}/pot_month/state"][-1] == "Next month"
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/pot_month/set", payload=b"Last month"))
    assert W.S["pot_month"] == "Next month" and woke == [1]  # ignored, its state said again
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == []  # December's first read: no alert
    W.save_state(W.S)
    sys.modules.pop("watcher", None)
    import watcher as W2  # the next start reads the same state
    W2.MQ = W.MQ
    W2.pot_start()
    assert W2.pot_mode() == "Next month"
    W2.connect_states(W2.MQ)
    assert [p for t, p in W2.MQ.msgs if t == f"{W2.T}/pot_month/state"][-1] == "Next month"
    sys.modules.pop("watcher", None)


def test_the_state_attribute_says_which_months_are_read(mk):
    W, fl, pages = _w(mk, at(2026, 11, 23), "Next month", {"003.153": page(DEC)})
    _check(W, fl)
    a = json.loads([p for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"][-1])
    assert a["pot_mode"] == "Next month"
    assert a["pot_months"] == [{"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned",
                                "status": "ok", "read": True}]
    assert W.mirror_links()[0] == ("Open time", W.mobile_pot_url("003.153"))  # the mirror follows the page read
    assert W.pot_bcid_now() == "003.153"  # the swap map's pot and its 001.153 / 003.153 pages


def test_the_old_rediscovery_and_hard_coded_page_are_gone():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watcher.py"),
               encoding="utf-8").read()
    assert "rediscovering pot pages to look for the next bid month" not in src
    assert "def discover_pot_urls" not in src and "MOBILE_POT" not in src


# ---------------------------------------------------------------- 1.8.1 review fixes
SEC = "OPEN TIME- Add/Swap/Drop requests"


def _menu(W, fl, links):
    """The main menu fake: each look reads links (a list the test may change); returns the list of looks made."""
    W.OPTS["pot_section"] = "OPEN TIME"
    looks = []
    fl.ctx.new_page = lambda: looks.append(1) or _Page([_Frame(list(links))])
    fl.save = lambda: None
    return looks


def _jan(b, i=0, sec=SEC):
    return {"i": i, "section": sec, "month": "January", "href": f"javascript:openOT('/full/otframe.cgi?BCID={b}');"}


def test_a_menu_bcid_of_another_category_is_never_a_months_pot(mk):
    """flica-1: the menu names January as 001.154, a page of another category (HNL 332 CA) with January's trips: it is
    refused (no learning, the derivation stays on 003), never read again; a menu naming both takes the 003 one."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "001.154": page(JAN, cat="HNL 332 CA")})
    links = [_jan("001.154")]
    looks = _menu(W, fl, links)
    assert _check(W, fl)[1] == ["003.153", "003.154"] and not looks  # January's derived BCID: not open yet
    assert _check(W, fl)[1] == ["003.153", "001.154"] and looks == [1]  # the menu's BCID, read and checked
    assert "2027-01" not in W.pot_learned() and W.pot_derive("2027-02") == "003.155"
    rec = W.pot_rec("2027-01")
    assert rec["status"] == "refused" and rec["why"] == "not an open time page of HNL 332 FO"
    assert "001.154" in rec["refused"] and not (W.S.get("pot_cands") or {}).get("2027-01")
    assert W.pot_pick("2027-01") == ("003.154", "derived")
    assert _check(W, fl)[1] == ["003.153", "003.154"]  # its pick again: still not open, tried again tomorrow
    for _ in range(40):  # 6 h 40 min: one more look names 001.154 again, never read again
        _check(W, fl)
    assert looks == [1, 1] and _pot_loads(W, fl).count("001.154") == 1
    # a menu that names both: the latest learned month's category (003) is taken; it is January's pick, not open at
    # its last read, so it is read on this check (not at tomorrow's try) and learned
    links[:] = [_jan("001.154"), _jan("003.154", 1)]
    W.CLOCK.t += 6 * 3600
    pages["003.154"] = page(JAN)
    assert _check(W, fl)[1] == ["003.153", "003.154"] and looks == [1, 1, 1]
    assert W.pot_learned()["2027-01"]["bcid"] == "003.154" and W.pot_status("2027-01") == "ok"
    # a derived pick on a page of another category is refused too, and the state note says why
    W2, fl2, _ = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": page(JAN, cat="HNL 332 CA")})
    assert _check(W2, fl2)[1] == ["003.153", "003.154"] and W2.pot_status("2027-01") == "refused"
    assert "2027-01" not in W2.pot_learned()
    assert ("January 2027 open time pot: BCID 003.154 refused (not an open time page of HNL 332 FO)"
            in W2.S["note"])


def test_the_menu_prefers_the_learned_category_and_never_takes_the_close_in_folder(mk):
    """T1 (2): menu_pot_bcids itself: a link in the close-in section or naming a known close-in BCID gives nothing;
    of two BCIDs for a month the one with the prefix asked for, else the first."""
    W, fl, pages = _w(mk, at(2026, 12, 5))
    W.S["close_in"] = {"bcid": "008.153", "verified": True}
    links = [_jan("003.170", 0, "Close in Opentime: <16 Hrs to RPT"),
             {"i": 1, "section": SEC, "month": "January", "href": "openOT('008.153'); BCID=003.161"}]
    _menu(W, fl, links)
    assert fl.menu_pot_bcids({"January": "2027-01"}) == {"2027-01": "003.161"}
    links[:] = [_jan("001.154"), _jan("003.154", 1)]
    assert fl.menu_pot_bcids({"January": "2027-01"}) == {"2027-01": "001.154"}
    assert fl.menu_pot_bcids({"January": "2027-01"}, "003") == {"2027-01": "003.154"}


def test_a_menu_that_names_the_pick_of_a_month_not_open_reads_it_then(mk):
    """flica-2 and flica-4: Next month, January not open. When the main menu names its pick (the derived 003.154),
    January is read at the next pot read, not a day later; Next month never reads two pot pages in a check."""
    W, fl, pages = _w(mk, at(2026, 12, 14, 22), "Next month", {"003.153": page(DEC)})
    links = []
    looks = _menu(W, fl, links)
    got = [_check(W, fl)[1] for _ in range(3)]
    assert got == [["003.153"], ["003.154"], ["003.153"]] and looks == [1]  # the try, in place of December's read
    assert W.pot_status("2027-01") == "not open yet"
    for _ in range(12):  # 2 h of checks: December only
        assert _check(W, fl)[1] == ["003.153"]
    links[:] = [_jan("003.154")]  # Dec 15: January's pot opens and the menu names it
    pages["003.154"] = page(JAN)
    W.CLOCK.t = at(2026, 12, 15, 4, 30)
    per = [_check(W, fl)[1] for _ in range(3)]
    assert looks == [1, 1] and ["003.154"] in per[:2] and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    assert W.CLOCK.t < at(2026, 12, 15, 6)  # not at the daily try (Dec 15 22:10)
    assert max(len(x) for x in got + per) == 1 and per[-1] == ["003.154"] and _new(W) == []


def test_this_month_reads_one_page_even_when_it_links_to_the_next_month(mk):
    """flica-3: This month (the default, James's) reads one pot page a check; a link on it to the next month's pot no
    longer adds that month (1.8.0's watch_next_month link)."""
    W, fl, pages = _w(mk, at(2026, 12, 16), pages={"003.153": page(DEC, links=[("003.154", "Jan")]),
                                                   "003.154": page(JAN)})
    W.OPTS["watch_next_month"] = True
    for _ in range(5):
        assert _check(W, fl)[1] == ["003.153"]
    assert W.pot_months_of() == ["2026-12"] and "pot_link_next" not in W.S and not hasattr(W, "pot_link_on")
    assert [x["month"] for x in W.pot_months_attr()] == ["2026-12"]


def test_one_refused_read_keeps_the_baseline_and_both_alerts_the_trip_that_came_meanwhile(mk):
    """alerts-refused-read-drops-baseline, M1 (Both): one odd December page keeps December read at the normal pace."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC)})
    spy = []
    W.swap_scan = lambda rows, read=None, quiet=(): spy.append((set(read), set(quiet)))
    assert _check(W, fl)[1] == ["003.153", "003.154"] and spy[-1] == ({"2026-12", W.CLOSE_IN_KEY}, {"2026-12"})
    pages["003.153"] = page(JAN)  # one page of January's trips
    assert _check(W, fl)[1] == ["003.153"] and W.S["baseline"]["2026-12"]
    assert spy[-1] == ({W.CLOSE_IN_KEY}, set())  # December not read: its swap ideas are kept, none pushed again
    pages["003.153"] = page(DEC + [("H3919", "30Dec")])
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == ["H3919"] and spy[-1][1] == set()


def test_a_first_read_from_another_bcid_sets_its_baseline_only(mk):
    """alerts: the baseline remembers its BCID; a page of another BCID for the month (a new candidate) is a first
    read."""
    W, fl, pages = _w(mk, at(2026, 12, 5), pages={"003.153": page(DEC)})
    assert _check(W, fl)[1] == ["003.153"] and W.S["baseline_bcid"] == {"2026-12": "003.153"}
    W.S["pot_cands"] = {"2026-12": {"bcid": "003.199", "how": "menu", "at": W.now_iso()}}
    pages["003.199"] = page(DEC + [("H3916", "22Dec")])
    assert _check(W, fl)[1] == ["003.199"] and _new(W) == [] and W.pot_learned()["2026-12"]["bcid"] == "003.199"
    pages["003.199"] = page(DEC + [("H3916", "22Dec"), ("H3917", "23Dec")])
    assert _check(W, fl)[1] == ["003.199"] and _new(W) == ["H3917"]


def test_a_candidate_that_is_no_open_time_page_gives_way_to_the_learned_bcid(mk):
    """M2: a menu candidate whose page is not open never replaces the month's learned, proven BCID."""
    W, fl, pages = _w(mk, at(2026, 12, 10), pages={"003.153": page(DEC)})
    assert _check(W, fl)[1] == ["003.153"]
    W.pot_cand("2026-12", "003.199", "menu", "main menu")
    assert W.pot_pick("2026-12") == ("003.199", "menu")
    assert _check(W, fl)[1] == ["003.199"]  # not open
    assert W.pot_pick("2026-12") == ("003.153", "learned") and "003.199" in W.pot_rec("2026-12")["refused"]
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == ["H3914"]  # read again at once, its baseline kept
    W.pot_cand("2026-12", "003.199", "menu", "main menu")  # named again: refused for December
    for _ in range(6):
        assert _check(W, fl)[1] == ["003.153"]


def test_a_refused_link_candidate_is_read_once_and_check_reads_page_links(mk):
    """T1 (3), (9): a pot page read in check() names January's pot (a link): a candidate, read and refused once, never
    read again although every December page still links to it."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC, links=[("003.160", "Jan")]),
                                                  "003.160": page(DEC)})
    assert _check(W, fl)[1] == ["003.153", "003.154"]
    assert W.S["pot_cands"]["2027-01"]["bcid"] == "003.160"  # from the December page check() read
    assert _check(W, fl)[1] == ["003.153", "003.160"] and W.pot_status("2027-01") == ""
    assert "003.160" in W.pot_rec("2027-01")["refused"]
    for _ in range(10):
        _check(W, fl)
    assert _pot_loads(W, fl).count("003.160") == 1 and not (W.S.get("pot_cands") or {}).get("2027-01")


def test_a_main_menu_another_session_took_ends_the_check_killed(mk):
    """T1 (4): the look meets FLICA's 'another session' page: check() returns killed (one FLICA session)."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC)})
    W.OPTS["pot_section"] = "OPEN TIME"
    _check(W, fl)
    fl.ctx.new_page = lambda: _Page([], f"<html><body>{P.KILLED_TXT}</body></html>")
    n = len(fl.loads)
    assert _check(W, fl) == ("killed", []) and len(fl.loads) == n


def test_the_1_8_0_finds_carry_over_and_are_stamped_gone(mk):
    """T1 (5): a November find 1.8.0 kept under 'mobile' belongs to 2026-11 now: it gets gone_at when it leaves."""
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV[:1])})
    rows = P.parse_pot(page(NOV))
    W.DB.record_pot("mobile", rows, set(rows))
    W.S["baseline"] = {"mobile": sorted(rows)}
    W.pot_start()
    assert _check(W, fl)[1] == ["003.152"] and _new(W) == []
    got = dict(W.DB.db.execute("SELECT key, month || ' ' || ifnull(gone_at, '-') FROM finds").fetchall())
    assert got["H3901|26Nov"] == "2026-11 -" and got["H3902|28Nov"].startswith("2026-11 2026-")


def test_a_try_that_reads_keeps_its_baseline_and_an_empty_derived_page_sets_none(mk):
    """T1 (6), (7): Next month's try that reads as January's pot is its baseline, kept into the next check; an empty
    page on a derived BCID (Both) is never baselined, so its first trips later alert nothing."""
    W, fl, pages = _w(mk, at(2026, 12, 20), "Next month", {"003.153": page(DEC), "003.154": page(JAN)})
    assert [_check(W, fl)[1] for _ in range(2)] == [["003.153"], ["003.154"]] and _new(W) == []
    pages["003.154"] = page(JAN + [("H3923", "20Jan")])
    assert _check(W, fl)[1] == ["003.154"] and _new(W) == ["H3923"]
    W2, fl2, pages2 = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": page()})
    assert _check(W2, fl2)[1] == ["003.153", "003.154"] and W2.pot_status("2027-01") == "empty"
    assert "2027-01" not in W2.S["baseline"] and "2027-01" not in W2.S["pot_urls"]
    W2.CLOCK.t += 86400
    pages2["003.154"] = page(JAN)
    assert _check(W2, fl2)[1] == ["003.153", "003.154"] and _new(W2) == []
    assert W2.pot_status("2027-01") == "ok" and W2.S["baseline"]["2027-01"]


def test_a_learned_page_that_is_no_open_time_page_goes_through_the_layout_check(mk):
    """T1 (8): a month's page that read as its pot and now is no open time page: retry, then a stop after 3."""
    W, fl, pages = _w(mk, at(2026, 12, 10), pages={"003.153": page(DEC)})
    assert _check(W, fl)[1] == ["003.153"]
    pages["003.153"] = NOT_OPEN
    assert _check(W, fl) == ("retry", ["003.153"]) and W.S["parse_fail"] == 1 and W.S["pot_urls"] == {}
    assert _check(W, fl) == ("retry", ["003.153"]) and W.S["parse_fail"] == 2
    assert _check(W, fl) == ("stop", ["003.153"]) and W.S["machine"] == "stopped_unexpected"


@pytest.mark.parametrize("key,bad", [
    ("pot_bcids", None), ("pot_bcids", []), ("pot_bcids", {"2026-11": "003.152"}),
    ("pot_bcids", {"2026-11": {"bcid": 5}}), ("pot_months", []), ("pot_months", {"2026-11": "x"}),
    ("pot_months", {"2026-11": {"bcid": "003.152", "status": "ok", "try_at": "soon", "refused": "003.152",
                                "refusals": "2", "look_at": None}}),
    ("pot_cands", {"2026-11": "x"}), ("pot_cands", {"2026-11": {"bcid": None}}), ("pot_cands", 7),
    ("pot_link_next", "x"), ("baseline_bcid", []), ("baseline_bcid", {"2026-11": 3}), ("swap_seen_month", "x"),
    ("pot_months", {"2026-11": {"bcid": "003.152", "status": "refused", "try_at": "soon"}}),
    ("pot_months", {"2026-11": {"bcid": "003.152", "status": "refused", "try_at": 0, "refused": "003.152"}})])
def test_a_state_with_pot_keys_of_the_wrong_type_never_stops_the_watcher(mk, key, bad):
    """state-subkey-type-crash: pot_start and every check drop a pot key of the wrong type (a hand edit)."""
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV)})
    W.S[key] = bad
    W.pot_start()
    assert W.pot_learned()["2026-11"]["bcid"] == "003.152"
    assert _check(W, fl) == ("ok", ["003.152"])
    W.S[key] = bad  # and in a running Watcher, before a check
    assert _check(W, fl) == ("ok", ["003.152"]) and W.pot_months_attr()[0]["status"] == "ok"


def test_a_month_not_planned_after_a_select_change_reads_not_read_yet(mk, monkeypatch):
    """ui-3: right after a select change (or paused), a month whose page read ok is 'not read yet', never 'ok'."""
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV)})
    monkeypatch.setattr(W, "WAKE", types.SimpleNamespace(set=lambda: None))
    _check(W, fl)
    assert [(x["status"], x["read"]) for x in W.pot_months_attr()] == [("ok", True)]
    W.pot_month_cmd(W.MQ, "Next month")
    W.pot_month_cmd(W.MQ, "This month")
    assert [(x["month"], x["how"], x["status"], x["read"]) for x in W.pot_months_attr()] == [
        ("2026-11", "learned", "not read yet", False)]
    _check(W, fl)
    assert [(x["status"], x["read"]) for x in W.pot_months_attr()] == [("ok", True)]


def test_the_category_is_a_whole_phrase_never_a_word_inside_another(mk):
    """R1: an HNL 332 CA page with an SFO layover and 'Requests for open time' is no page of HNL 332 FO; the mobile
    page's real header form '[HNL&nbsp;332 FO]' is."""
    W, fl, pages = _w(mk, at(2026, 12, 5))
    ca = page(JAN, cat="HNL 332 CA").replace("-none-", "SFO", 1).replace("<table>", "<p>Requests for open time</p>"
                                                                           "<table>")
    assert not W.pot_category_ok(ca)
    assert not W.pot_category_ok(page(JAN, cat="FO HNL 332"))
    assert W.pot_category_ok(page(JAN, cat="[HNL&nbsp;332 FO]")) and W.pot_category_ok(page(JAN, cat="hnl 332 fo"))
    W2, fl2, _ = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": ca})
    assert _check(W2, fl2)[1] == ["003.153", "003.154"] and W2.pot_status("2027-01") == "refused"
    assert "2027-01" not in W2.pot_learned()


def test_one_refused_read_keeps_the_months_rows_and_details_cached(mk):
    """R2: one odd page of a month that read ok keeps its pairing details and its rows published (no detail
    re-read at the next good read); after a restart (no rows in memory) the baseline still keeps the details."""
    W, fl, pages = _w(mk, at(2026, 12, 10), pages={"003.153": page(DEC)})
    pubs = []
    W.publish_pot = lambda flat: pubs.append(sum(1 for r in flat if r.get("month") == "2026-12"))
    assert _check(W, fl)[1] == ["003.153"]
    assert _check(W, fl)[1] == ["003.153"]
    keys = sorted(W.S["baseline"]["2026-12"])
    assert len(keys) == 3
    W.S["details"] = {k: {"legs": []} for k in keys}
    pages["003.153"] = page(JAN)  # one page of January's trips
    assert _check(W, fl)[1] == ["003.153"] and W.pot_rec("2026-12")["refusals"] == 1
    assert sorted(W.S["details"]) == keys and pubs[-1] == 3
    W.POT_ROWS.clear()  # a restart: no rows in memory
    assert _check(W, fl)[1] == ["003.153"] and sorted(W.S["details"]) == keys
    pages["003.153"] = page(DEC)
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == [] and len(W.S["details"]) == 3


def test_next_month_reads_one_page_when_both_tries_are_due(mk):
    """R3: Next month, December refused and waiting, January's try due in the same check (after a pause): the next
    month's page now, December's at the next check; never two pot pages in a check."""
    W, fl, pages = _w(mk, at(2026, 12, 20), "Next month", {"003.153": page(DEC)})
    got = [_check(W, fl)[1] for _ in range(2)]
    assert got == [["003.153"], ["003.154"]]  # January not open
    pages["003.153"] = page(NOV)
    for _ in range(3):  # December refused 3 times in a row: on its try time
        got.append(_check(W, fl)[1])
    assert W.pot_status("2026-12") == "refused"
    W.CLOCK.t += 2 * 86400  # a pause: both tries due
    pages["003.153"] = page(DEC)
    for _ in range(4):
        got.append(_check(W, fl)[1])
    assert max(len(x) for x in got) == 1 and got[-4] == ["003.154"] and got[-3] == ["003.153"]


def test_next_month_tries_the_next_month_while_this_months_page_is_empty(mk):
    """next-month starved try: this month's pick is an empty open time page on an unproven BCID; the next month's try
    still takes its place now and then, and January is learned once open."""
    W, fl, pages = _w(mk, at(2027, 1, 2), "Next month", {"003.154": page(), "003.155": page(
        [("H3931", "03Feb"), ("H3932", "10Feb")])})
    W.S["pot_bcids"] = {"2026-12": {"bcid": "003.153", "how": "learned", "at": W.now_iso()}}
    got = [_check(W, fl, step=3600)[1] for _ in range(30)]
    assert "003.155" in sum(got, []) and max(len(x) for x in got) == 1
    assert W.pot_learned()["2027-02"]["bcid"] == "003.155"


def test_a_try_that_read_this_check_shows_as_read(mk):
    """ui-3 recheck: Both, January's pot opens: right after the check that reads it the card says ok, not 'not read
    yet', in the state attribute the check itself publishes."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": page(JAN)})
    assert _check(W, fl)[1] == ["003.153", "003.154"]
    jan = next(x for x in W.pot_months_attr() if x["month"] == "2027-01")
    assert (jan["bcid"], jan["status"], jan["read"]) == ("003.154", "ok", True)
    attrs = [json.loads(p) for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"]
    jan = next(x for x in attrs[-1]["pot_months"] if x["month"] == "2027-01")
    assert (jan["status"], jan["read"]) == ("ok", True)


def test_an_empty_candidate_never_stands_in_for_the_learned_page(mk):
    """recheck 2: Next month, Dec 20, December's learned 003.153 refused 3 times, then an empty menu candidate for
    December while January's try is due: the learned page is read again next check, its rows and details kept."""
    W, fl, pages = _w(mk, at(2026, 12, 20), "Next month", {"003.153": page(DEC)})
    pubs = []
    W.publish_pot = lambda flat: pubs.append(sum(1 for r in flat if r.get("month") == "2026-12"))
    assert [_check(W, fl)[1] for _ in range(2)] == [["003.153"], ["003.154"]]
    keys = sorted(W.S["baseline"]["2026-12"])
    W.S["details"] = {k: {"legs": []} for k in keys}
    pages["003.153"] = page(NOV)
    for _ in range(3):
        _check(W, fl)
    assert W.pot_status("2026-12") == "refused"
    pages["003.153"], pages["003.170"] = page(DEC), page()
    W.CLOCK.t += 86400
    W.pot_cand("2026-12", "003.170", "menu", "main menu")
    got = [_check(W, fl)[1] for _ in range(3)]
    assert got[0] == ["003.170"] and "003.153" in got[1] + got[2] and max(len(x) for x in got) == 1
    assert pubs[-1] == 3 and sorted(W.S["details"]) == keys and _new(W) == []


def test_stand_in_rows_are_never_days_old(mk):
    """recheck 3: Both, then This month for 3 days, then Both: a refused first page of January publishes no old
    January rows."""
    W, fl, pages = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": page(JAN)})
    pubs = []
    W.publish_pot = lambda flat: pubs.append(sum(1 for r in flat if r.get("month") == "2027-01"))
    _check(W, fl)
    assert pubs[-1] == 2
    W.S["pot_month"] = "This month"
    for _ in range(3):
        _check(W, fl, step=86400)
    pages["003.154"] = page(DEC)
    W.S["pot_month"] = "Both"
    _check(W, fl)
    assert pubs[-1] == 0 and _new(W) == []


def test_no_click_once_a_link_named_the_months_bcid(mk):
    """R4 (a): a link with no BCID after one that named January's BCID opens nothing (each click is a FLICA load)."""
    W, fl, pages = _w(mk, at(2026, 12, 5))
    links = [_jan("003.154"), {"i": 1, "section": SEC, "month": "January", "href": ""}]
    _menu(W, fl, links)
    n = len(fl.loads)
    assert fl.menu_pot_bcids({"January": "2027-01"}, "003") == {"2027-01": "003.154"}
    assert len(fl.loads) == n


# ---------------------------------------------------------------- the final gate's findings (Nov 23)
@pytest.mark.parametrize("mode", ["Next month", "Both"])
def test_a_next_month_not_open_at_its_last_try_is_read_at_the_rollover(mk, mode):
    """rollover-next-wait: January not open at the Dec 31 try is tried at the Jan 1 roll-over, not a day later."""
    W, fl, pages = _w(mk, at(2026, 12, 31, 19), mode, {"003.153": page(DEC)})
    while W.CLOCK.t < at(2027, 1, 1, 0, 0):
        _check(W, fl, step=3600)
    pages["003.154"] = page(JAN)
    got = [_check(W, fl, step=3600)[1] for _ in range(7)]
    assert "003.154" in sum(got, []) and max(len(x) for x in got) <= (2 if mode == "Both" else 1)


def test_this_month_refused_before_midnight_is_tried_at_the_rollover(mk):
    """rollover-try-wait: December refused 3 times on Nov 30 as the next month is read again from Dec 1 00:00, and a
    trip posted after its first read alerts."""
    W, fl, pages = _w(mk, at(2026, 11, 30, 22, 0), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    pages["003.153"] = page(NOV)
    for _ in range(3):
        _check(W, fl)
    assert W.pot_status("2026-12") == "refused"
    pages["003.153"] = page(DEC)
    W.CLOCK.t = at(2026, 12, 1, 0, 30)
    got = []
    while W.CLOCK.t < at(2026, 12, 1, 2, 0):
        got += _check(W, fl)[1]
    assert "003.153" in got
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    _check(W, fl)
    assert _new(W) == ["H3914"]


def test_a_first_refusal_before_the_rollover_loses_no_alert(mk):
    """rollover-next-month-wait-blinds-this-month (Both): December odd once on Nov 30 18:00, read from Dec 1 00:05."""
    W, fl, pages = _w(mk, at(2026, 11, 30, 18), "Both", {"003.152": page(NOV), "003.153": page(NOV)})
    _menu(W, fl, [])
    _check(W, fl)
    pages["003.153"] = page(DEC)
    W.CLOCK.t = at(2026, 12, 1, 0, 5)
    for _ in range(6):
        _check(W, fl, step=1800)
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    while W.CLOCK.t < at(2026, 12, 1, 6):
        _check(W, fl, step=1800)
    assert _new(W) == ["H3914"]


def test_one_odd_page_never_bans_a_months_real_bcid_for_good(mk):
    """cand-banned-forever: January renumbered (003.160 on the menu), its first page odd once: read again once its
    wait has passed; a page of another category stays refused for good (test above)."""
    W, fl, pages = _w(mk, at(2027, 1, 2, 8), pages={"003.160": page(DEC)})
    looks = _menu(W, fl, [_jan("003.160")])
    for _ in range(3):
        _check(W, fl, step=3600)
    assert "003.160" in W.pot_rec("2027-01")["refused"]
    pages["003.160"] = page(JAN)
    for _ in range(24):
        _check(W, fl, step=3600)
    assert looks and W.pot_status("2027-01") == "ok" and W.pot_learned()["2027-01"]["bcid"] == "003.160"
    assert _new(W) == []


def test_a_late_december_page_never_counts_as_januarys(mk):
    """month-end slack: on Dec 29 December's pot holds only Dec 29 to 31 trips (inside January's 3-day slack); a BCID
    not learned yet needs most trips in the month proper, so 003.154 is refused and no trip alerts twice."""
    late = [("H3931", "29Dec"), ("H3932", "30Dec"), ("H3933", "31Dec")]
    W, fl, pages = _w(mk, at(2026, 12, 29, 9), "Both", {"003.153": page(late), "003.154": page(late)})
    assert _check(W, fl)[1] == ["003.153", "003.154"]
    pages["003.153"] = pages["003.154"] = page(late + [("H3934", "31Dec")])
    _check(W, fl)
    assert _new(W) == ["H3934"] and "2027-01" not in W.pot_learned()
    W2, fl2, _ = _w(mk, at(2026, 12, 5), "Both", {"003.153": page(DEC), "003.154": page(
        [("H3941", "01Jan"), ("H3942", "02Jan"), ("H3943", "31Dec")])})  # a real January page with a carry-in
    _check(W2, fl2)
    assert W2.pot_learned()["2027-01"]["bcid"] == "003.154"


def test_the_1_8_0_swap_ideas_are_held_through_a_refused_first_read(mk, monkeypatch):
    """update-1-8-0-swap-seen: 1.8.0's pushed swap ideas are held while November's first 1.8.1 page is refused."""
    W = mk("", t=at(2026, 11, 23))
    for f in STUBS:
        if f != "swap_scan":
            setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    monkeypatch.setattr(W.SW, "better", lambda row, mine: (True, 1.0, 0.0, "more soft time"))
    monkeypatch.setattr(W.G, "swap_allowed", lambda *a: (True, []))
    W.far_for = lambda ev, exclude=None: "OK"
    W.swap_test = lambda *a, **k: None
    W.swap_auto = lambda *a, **k: []
    mine = "H9001|20Nov"
    W.S.update(trade_away=[mine], own_trips={mine: {"credit": "10:00", "soft": "1:00"}})
    pages = {}
    fl = real_fl(W, lambda u: pages.get(W.bcid(u), NOT_OPEN) if "opentimepot" in u else "<html><body>x</body></html>")
    W.S["baseline"] = {"mobile": ["H3901|26Nov", "H3902|28Nov"]}
    W.S["fingerprints"] = {"mobile": W.header_fingerprint(page(NOV))}
    W.S["swap_seen"] = sorted(f"{p}>{mine}" for p in ("H3901|26Nov", "H3902|28Nov"))
    W.S["pot_urls"] = {}
    W.pot_start()
    pages["003.152"] = page([("H3801", "12Dec"), ("H3802", "15Dec")])
    _check(W, fl)
    W.CLOCK.t += 6 * 3600
    pages["003.152"] = page(NOV)
    _check(W, fl)
    assert [json.loads(p)["pairing"] for t, p in W.MQ.msgs if t == f"{W.T}/event/swap"] == []


@pytest.mark.parametrize("key,bad", [("baseline", None), ("baseline", []), ("baseline", {"2026-12": 5}),
                                     ("baseline", {"2026-12": [1, 2]}), ("fingerprints", None),
                                     ("fingerprints", {"2026-12": 7})])
def test_a_baseline_of_the_wrong_type_never_crashes_a_check(mk, key, bad):
    """baseline-type-crash: a hand-edited baseline or fingerprints is dropped, never a check error."""
    W, fl, pages = _w(mk, at(2026, 12, 10), pages={"003.153": page(DEC)})
    W.S[key] = bad
    W.pot_start()
    assert _check(W, fl) == ("ok", ["003.153"])
    W.S[key] = bad
    assert _check(W, fl) == ("ok", ["003.153"])


def test_the_state_attribute_follows_two_select_changes(mk, monkeypatch):
    """mode-attr-stale: Both, Next month, Both before a check: the published pot_mode is Both."""
    W, fl, pages = _w(mk, at(2026, 12, 10), "Both", {"003.153": page(DEC)})
    monkeypatch.setattr(W, "WAKE", types.SimpleNamespace(set=lambda: None))
    _check(W, fl)
    W.pot_month_cmd(W.MQ, "Next month")
    W.pot_month_cmd(W.MQ, "Both")
    a = json.loads([p for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"][-1])
    assert a["pot_mode"] == "Both"


def test_a_month_refused_the_third_time_is_not_shown_as_read(mk):
    """attr-read-after-third-refusal."""
    W, fl, pages = _w(mk, at(2026, 12, 10), pages={"003.153": page(DEC)})
    _check(W, fl)
    pages["003.153"] = page(NOV)
    for _ in range(3):
        _check(W, fl)
    a = json.loads([p for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"][-1])["pot_months"]
    assert W.pot_status("2026-12") == "refused" and [(x["status"], x["read"]) for x in a] == [("refused", False)]


# ---------------------------------------------------------------- the second gate's findings (Nov 23)
@pytest.mark.parametrize("mode", ["Both", "Next month"])
def test_a_next_months_refused_bcid_waits_its_whole_try_wait(mk, mode):
    """ban-midpoint: a BCID refused for December on Nov 30 00:50 (a link on November's page names it on every read)
    waits until Dec 1 00:00; no re-read loop toward midnight, December's learned page not re-read in the last hour."""
    W, fl, pages = _w(mk, at(2026, 11, 30, 0, 30), mode,
                      {"003.152": page(NOV, links=[("003.160", "Dec")]), "003.160": page(NOV)})
    got, last_hour = [], []
    while W.CLOCK.t < at(2026, 12, 1, 0, 0):
        late = W.CLOCK.t >= at(2026, 11, 30, 23, 0)
        g = _check(W, fl, step=22 if late else 600)[1]
        got += g
        last_hour += g if late else []
    assert got.count("003.160") == 1 and last_hour.count("003.153") == 0


@pytest.mark.parametrize("mode", ["Both", "Next month"])
def test_a_menu_named_refused_bcid_waits_for_the_next_months_try(mk, mode):
    W, fl, pages = _w(mk, at(2026, 12, 31, 6, 0), mode, {"003.153": page(DEC), "003.160": page(DEC)})
    _menu(W, fl, [_jan("003.160")])
    got = []
    while W.CLOCK.t < at(2026, 12, 31, 23, 59):
        got += _check(W, fl, step=600)[1]
    assert got.count("003.160") == 1


def test_a_page_of_another_category_and_month_stays_refused_for_good(mk):
    """category-refusal-expires: an HNL 332 CA page is refused for good whatever month its trips start in."""
    W, fl, pages = _w(mk, at(2027, 1, 3, 9), pages={"001.154": page(DEC, cat="HNL 332 CA")})
    looks = _menu(W, fl, [_jan("001.154")])
    while W.CLOCK.t < at(2027, 1, 5, 9):
        _check(W, fl, step=1800)
    assert looks and _pot_loads(W, fl).count("001.154") == 1
    ca = page([("H3951", "30Dec"), ("H3952", "31Dec"), ("H3953", "01Jan")], cat="HNL 332 CA")
    W2, fl2, _ = _w(mk, at(2026, 12, 29, 9), "Both", {"003.153": page(DEC), "001.154": ca})
    looks2 = _menu(W2, fl2, [_jan("001.154")])
    while W2.CLOCK.t < at(2027, 1, 2, 12):
        _check(W2, fl2, step=1800)
    assert looks2 and _pot_loads(W2, fl2).count("001.154") == 1


@pytest.mark.parametrize("shape", [5, True, [["x"]], [{"a": 1}], ["H3901|26Nov>H9001|20Nov", 3]])
def test_a_swap_seen_of_the_wrong_type_never_stops_the_watcher(mk, monkeypatch, shape):
    """swap-seen-type-crash: the 1.8.0 update and later checks with a hand-edited swap_seen."""
    W = mk("", t=at(2026, 11, 23))
    for f in STUBS:
        if f != "swap_scan":
            setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    monkeypatch.setattr(W.SW, "better", lambda row, mine: (True, 1.0, 0.0, "more soft time"))
    monkeypatch.setattr(W.G, "swap_allowed", lambda *a: (True, []))
    W.far_for = lambda ev, exclude=None: "OK"
    W.swap_test = lambda *a, **k: None
    W.swap_auto = lambda *a, **k: []
    W.S.update(trade_away=["H9001|20Nov"], own_trips={"H9001|20Nov": {"credit": "10:00", "soft": "1:00"}})
    pages = {"003.152": page(NOV)}
    fl = real_fl(W, lambda u: pages.get(W.bcid(u), NOT_OPEN) if "opentimepot" in u else "<html><body>x</body></html>")
    W.S["baseline"] = {"mobile": ["H3901|26Nov", "H3902|28Nov"]}
    W.S["swap_seen"] = shape
    W.S["pot_urls"] = {}
    W.pot_start()
    for _ in range(3):
        assert _check(W, fl)[0] == "ok"
    assert all(isinstance(k, str) for k in W.S["swap_seen"])


# ---------------------------------------------------------------- the third gate's findings (Nov 23)
def test_an_empty_page_of_another_category_never_holds_the_months_pick(mk):
    """G3-1: the menu names an empty HNL 332 CA pot for January: refused for good, January's own pot is learned."""
    W, fl, pages = _w(mk, at(2027, 1, 1, 0, 5), pages={"001.154": page((), cat="HNL 332 CA")})
    _menu(W, fl, [_jan("001.154")])
    _check(W, fl, step=1800)
    pages["003.154"] = page(JAN)
    while W.CLOCK.t < at(2027, 1, 3, 9):
        _check(W, fl, step=1800)
    loads = _pot_loads(W, fl)
    assert loads.count("001.154") <= 1 and (W.pot_learned().get("2027-01") or {}).get("bcid") == "003.154"


def test_the_links_of_a_page_of_another_category_name_no_candidates(mk):
    """G3-3: a CA page's link to its own February pot never becomes February's candidate (no load of it)."""
    ca = page(DEC, cat="HNL 332 CA", links=[("001.155", "Feb")])
    W, fl, pages = _w(mk, at(2026, 12, 28, 9), "Both", {"003.153": page(DEC), "001.154": ca,
                                                         "001.155": page(DEC, cat="HNL 332 CA")})
    _menu(W, fl, [_jan("001.154")])
    while W.CLOCK.t < at(2027, 1, 3, 9):
        _check(W, fl, step=1800)
    loads = _pot_loads(W, fl)
    assert loads.count("001.154") == 1 and loads.count("001.155") == 0


# ---------------------------------------------------------------- council loop 1 (Nov 23): the bid period, not the calendar
def _periods(W):
    """The pairing files' period bounds, as pdfs.py writes them: November Nov 1 to Dec 1, December Dec 2 to 31."""
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    for m, a, b in (("2026-11", "2026-11-01", "2026-12-01"), ("2026-12", "2026-12-02", "2026-12-31")):
        with open(os.path.join(W.CARD_PAIRINGS, f"pairings_{m}.json"), "w") as f:
            json.dump({"start": a, "end": b, "cols": [], "rows": []}, f)


NOV_D1 = NOV + [("H3905", "01Dec")]  # a Dec 1 trip: November's bid period, in November's pot


def test_dec_1_is_still_novembers_bid_month_for_the_pot(mk):
    """Dec 1 belongs to November's bid period: This month still reads November's pot (its Dec 1 trips alert), and
    December's pot takes over at Dec 2 00:00 HST with a first read (baseline only)."""
    W, fl, pages = _w(mk, at(2026, 11, 30, 23), pages={"003.152": page(NOV_D1), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    W.CLOCK.t = at(2026, 12, 1, 0, 10)
    assert W.this_month_key() == "2026-11" and _check(W, fl)[1] == ["003.152"]
    pages["003.152"] = page(NOV_D1 + [("H3906", "01Dec")])
    assert _check(W, fl)[1] == ["003.152"] and _new(W) == ["H3906"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert W.this_month_key() == "2026-12" and _check(W, fl)[1] == ["003.153"] and _new(W) == ["H3906"]
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == ["H3906", "H3914"]


def test_both_on_dec_1_reads_november_and_december(mk):
    """Both on Dec 1: November's pot (Dec 1 trips) and December's; from Dec 2 December's and January's."""
    W, fl, pages = _w(mk, at(2026, 12, 1, 9), "Both", {"003.152": page(NOV_D1), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    assert [x["month"] for x in W.pot_months_attr()] == ["2026-11", "2026-12"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153", "003.154"] and W.pot_months_of() == ["2026-12", "2027-01"]


def test_a_next_month_refused_on_dec_1_is_tried_at_its_bid_periods_first_day(mk):
    """On Dec 1 (November's bid month) December is still the next month: refused at 10:00, its try waits until its bid
    period's first day (Dec 2 00:00), not 6 h as this month's would."""
    W, fl, pages = _w(mk, at(2026, 12, 1, 10), "Both", {"003.152": page(NOV_D1), "003.153": page(NOV)})
    _periods(W)
    _check(W, fl)
    assert W.pot_status("2026-12") == "refused"
    assert abs(W.pot_rec("2026-12")["try_at"] - at(2026, 12, 2, 0, 0)) < 60
    pages["003.153"] = page(DEC)
    W.CLOCK.t = at(2026, 12, 2, 0, 10)
    assert "003.153" in _check(W, fl)[1]


def test_without_pairing_files_the_calendar_month_still_answers(mk):
    W, fl, pages = _w(mk, at(2026, 12, 1, 9), pages={"003.153": page(DEC)})
    assert W.this_month_key() == "2026-12" and _check(W, fl)[1] == ["003.153"]


# ---------------------------------------------------------------- D4: the clock card in Chromium
WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")
CARD_PAGE = ("<!doctype html><html><head><meta name='viewport' content='width=device-width'><style>"
             ":root{%s}body{margin:0;background:var(--primary-background-color)}</style></head><body>"
             "<script>customElements.define('ha-card', class extends HTMLElement {});window.calls = [];</script>"
             "<script>%s</script></body></html>")
LIGHT = ("--primary-background-color:#fafafa;--card-background-color:#fff;--primary-text-color:#212121;"
         "--secondary-text-color:#555;--divider-color:#ccc")
DARK = ("--primary-background-color:#111;--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
        "--secondary-text-color:#9b9b9b;--divider-color:#444")


def _clock_states(mode="Next month", months=None, dark=False):
    st = lambda s, a=None: {"state": s, "attributes": a or {}, "last_updated": "2026-11-23T21:20:00+00:00"}  # noqa
    months = months if months is not None else [
        {"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned", "status": "ok",
         "read": True}]
    return {"sensor.flight_watcher_state": st("idle", {"note": "", "role": "admin", "pot_mode": mode,
                                                         "pot_months": months}),
            "sensor.flight_watcher_last_check": st("2026-11-23T21:29:30+00:00"),
            "sensor.flight_watcher_next_check": st("2026-11-23T21:33:40+00:00"),
            "switch.flight_watcher_hunt_mode": st("off"), "switch.flight_watcher_pause": st("off"),
            "number.flight_watcher_hunt_check_every": st("40", {"min": 5, "max": 90, "step": 5}),
            "number.flight_watcher_normal_check_every": st("6", {"min": 1, "max": 90, "step": 1}),
            "select.flight_watcher_pot_month": st(mode, {"options": ["This month", "Next month", "Both"]})}


CARD_JS = """([h, dark]) => { const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
  document.body.appendChild(c);
  c.hass = {states: h, themes: {darkMode: dark}, callService: (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot, sel = r.getElementById('pm'), b = sel.getBoundingClientRect();
  return {wide: document.documentElement.scrollWidth, vw: window.innerWidth, h: b.height, w: b.width,
    shown: sel.style.display !== 'none', value: sel.value, opts: [...sel.options].map((o) => o.value),
    label: sel.parentElement.firstChild.textContent.trim(), months: r.getElementById('pmm').textContent,
    mode: r.getElementById('pmt').textContent, aria: sel.getAttribute('aria-label'),
    right: Math.max(...[...r.querySelectorAll('*')].map((x) => x.getBoundingClientRect().right))}; }"""


def _render(src, cases):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    out = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for name, (width, dark, h, keys) in cases.items():
                ctx = b.new_context(viewport={"width": width, "height": 800}, timezone_id="Pacific/Honolulu",
                                    color_scheme="dark" if dark else "light")
                pg = ctx.new_page()
                pg.clock.set_fixed_time("2026-11-23T21:30:00Z")
                pg.set_content(CARD_PAGE % (DARK if dark else LIGHT, src))
                out[name] = pg.evaluate(f"({CARD_JS})", [h, dark])
                if keys:
                    pg.locator("#pm").focus()
                    for k in keys:
                        pg.keyboard.press(k)
                    out[name]["calls"] = pg.evaluate("window.calls")
                    out[name]["focused"] = pg.evaluate(
                        "document.querySelector('flight-watcher-clock-card').shadowRoot.activeElement.id")
                ctx.close()
        finally:
            b.close()
    return out


def test_the_clock_card_pot_select_on_a_phone_light_and_dark():
    import portal as PT
    src = open(os.path.join(WWW, "flight-watcher-clock-card.js"), encoding="utf-8").read()
    two = [{"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned", "status": "ok",
            "read": True},
           {"month": "2027-01", "name": "January 2027", "bcid": "003.154", "how": "derived", "status": "not open yet",
            "read": False}]
    got = _render(src, {"light": (390, False, _clock_states(), ["ArrowDown"]),
                        "dark": (320, True, _clock_states("This month", two), ["ArrowDown"])})
    for k, v in got.items():
        assert v["wide"] <= v["vw"] and v["right"] <= v["vw"] + 0.5, (k, v)  # no horizontal scroll
        assert v["h"] >= 44 and v["w"] >= 44 and v["shown"], (k, v)  # a 44 px phone target
        assert v["opts"] == ["This month", "Next month", "Both"] and v["aria"] == "Pot month" and v["label"] == "Pot"
        assert v["focused"] == "pm"  # reached and worked from the keyboard
    assert got["light"]["value"] == "Next month" and got["light"]["months"] == "December 2026 (003.153)"
    assert got["light"]["calls"] == [["select", "select_option",
                                      {"entity_id": "select.flight_watcher_pot_month", "option": "Both"}]]
    assert got["dark"]["months"] == "December 2026 (003.153) · January 2027 not open yet"
    assert got["dark"]["calls"] == [["select", "select_option",
                                     {"entity_id": "select.flight_watcher_pot_month", "option": "Next month"}]]
    # the portal's copy: no select (no such portal command), the mode and the months as text, read only
    h = _clock_states()
    portal = _render(PT.portal_card(src), {"p": (390, False, h, None)})["p"]
    assert not portal["shown"] and portal["mode"] == "Next month" and portal["months"] == "December 2026 (003.153)"
    assert portal["wide"] <= portal["vw"]
    # ui-3: right after a select change a month whose last read was ok is not planned yet: 'not read yet', never 'ok'
    one = [{"month": "2026-11", "name": "November 2026", "bcid": "003.152", "how": "learned", "status": "ok",
            "read": False}]
    changed = _render(src, {"c": (390, False, _clock_states("This month", one), None)})["c"]
    assert changed["months"] == "November 2026 not read yet" and changed["wide"] <= changed["vw"]

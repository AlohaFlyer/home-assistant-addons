"""1.8.1 (POT-2, LIVE-1, POT-8, P9, LIVE-11, POT-6): alert-email finds and hidden-trip pushes follow the trip's own bid
month. Live on 1.8.0 (Nov 23, 2026) three December trips named in FLICA alert emails got a false CRITICAL hidden push:
each was missing from the one pot read (November's), so it counted as gone, and its seat was still Open on its pairing
page because it sat in December's pot. A find is judged gone, queued for its pickup check, scored or pushed as hidden
only against the pot of its own bid month (bid_period_key of its first day), read OK in this check; it is filed under
the pot month it is live in, else its own bid month; and a find still open when its bid period has ended is closed at
the period's end (no push, no pickup check). FLICA is never reached: a fake browser answers with synthetic pages
(made-up pairings H39xx, made-up names)."""
import json
import re

from test_fw181_pot_month import DEC, NOT_OPEN, NOV, STUBS, _check, _periods, at, page
from test_release_a_flica import mk, real_fl  # noqa: F401

REAL = ("email_check", "pickup_check")
SEAT_OPEN = "<html><body>pairing details {p} check in: 08:00 crew: ca 10009 doe, john fo open</body></html>"
SEAT_FILLED = ("<html><body>pairing details {p} check in: 08:00 crew: ca 10009 doe, john fo 10001 doe, jane"
               "</body></html>")
DONE = ("email_unchanged_fixed", "email_details_fixed", "pickup_backfilled", "pickers_scored", "ids_backfilled")


def _wm(mk, t, mode=None, pages=None, instance=""):
    """test_fw181_pot_month._w with the real email and pickup checks, for the admin (Ryan) or a pilot (instance).
    seats {pairing: page}: its pairing page (default: the FO seat Open)."""
    W = mk(instance, t=t)
    for f in STUBS:
        if f not in REAL:
            setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    W.inflt_check = lambda *a, **k: False
    W.pilot_check = lambda *a, **k: False
    for f in DONE:  # the one-time back-fills of old versions are done
        W.S[f] = True
    if mode:
        W.S["pot_month"] = mode
    W.S["pot_urls"] = {}
    pages = {} if pages is None else pages
    seats = {}

    def answer(u):
        if "opentimepot" in u:
            return pages.get(W.bcid(u), NOT_OPEN)
        m = re.search(r"mobilepairing\.cgi\?PID=(\w+)", u)
        if m:
            return seats.get(m.group(1), SEAT_OPEN).format(p=m.group(1).lower())
        return "<html><body>x</body></html>"
    return W, real_fl(W, answer), pages, seats


def _email(W, pairing, start, at_iso="2026-11-25T10:00:00+00:00"):
    W.S.setdefault("email_queue", []).append(
        {"key": f"{pairing}|{start}", "pairing": pairing, "start": start, "sources": ["test"], "at": at_iso})


def _find(W, key):
    """(month, gone_at) of a find, or None."""
    return W.DB.db.execute("SELECT month, gone_at FROM finds WHERE key=?", (key,)).fetchone()


def _pickup(W, key):
    r = W.DB.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def _hidden(W):
    return [json.loads(p)["key"] for t, p in W.MQ.msgs if t == f"{W.T}/event/hidden"]


def _pairing_loads(fl):
    return [u for _, u in fl.loads if "mobilepairing" in u]


# ---------------------------------------------------------------- POT-2, LIVE-1: an email find of a month not read
def test_this_month_an_email_for_a_december_trip_is_never_judged_gone_nor_pushed_hidden(mk):
    """Nov 25, This month (November's pot only): an alert email names H3911 03Dec, sitting in December's pot. Missing
    from the pot read is no proof it left: no gone_at, no pickup check, no hidden push, no speed; filed under its own
    bid month (2026-12), whose first read later judges it."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25, 0, 30), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    _email(W, "H3911", "03Dec")
    assert _check(W, fl)[1] == ["003.152"]
    assert _find(W, "H3911|03Dec") == ("2026-12", None)
    assert "H3911|03Dec" not in W.S["pickup_pending"]
    assert _hidden(W) == [] and _pairing_loads(fl) == [] and _pickup(W, "H3911|03Dec") == {}
    assert W.S["email_queue"] == []


def test_both_an_email_find_is_judged_against_its_own_months_pot_read_ok_in_this_check(mk):
    """Nov 25, Both (Ryan): an email find in December's pot is live (filed 2026-12, never the first pot_urls key); one
    no longer in December's pot, read OK this check, is gone and its pickup is checked; a real hidden trip still
    pushes. A check whose December page is refused (its last rows stand in) judges no new December email find, and
    November's read never stamps a December find gone."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    _email(W, "H3911", "03Dec")  # in December's pot
    _email(W, "H3916", "06Dec")  # left December's pot before the check: picked up
    _email(W, "H3918", "10Dec")  # not in December's pot, its seat still Open: hidden
    seats["H3916"] = SEAT_FILLED
    _check(W, fl)
    assert _find(W, "H3911|03Dec") == ("2026-12", None)
    assert _find(W, "H3916|06Dec")[0] == "2026-12" and _find(W, "H3916|06Dec")[1]
    assert _pickup(W, "H3916|06Dec")["status"] == "filled"
    assert _find(W, "H3918|10Dec")[1] and _hidden(W) == ["H3918|10Dec"]
    pages["003.153"] = page(NOV)  # December's page refused once: its last good rows stand in, no read
    _email(W, "H3917", "09Dec")  # posted meanwhile: not in the rows standing in
    _check(W, fl)
    assert W.pot_rec("2026-12").get("refusals") == 1
    assert _find(W, "H3917|09Dec") == ("2026-12", None) and "H3917|09Dec" not in W.S["pickup_pending"]
    assert _find(W, "H3911|03Dec") == ("2026-12", None)  # November's read stamps no December find
    assert _hidden(W) == ["H3918|10Dec"]
    pages["003.153"] = page(DEC[1:] + [("H3917", "09Dec")])  # read again: H3911 left December's pot
    _check(W, fl)
    assert _find(W, "H3917|09Dec") == ("2026-12", None)
    assert _find(W, "H3911|03Dec")[1] and "H3911|03Dec" in W.S["pickup_pending"]


def test_this_month_on_dec_1_judges_a_dec_1_trip_against_novembers_pot(mk):
    """Dec 1 is November's bid month: an email for a Dec 1 trip gone from November's pot (read OK) is judged gone;
    one for a Dec 12 trip (December, not read in This month until Dec 2) is not."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 1, 9), pages={"003.152": page(NOV + [("H3905", "01Dec")]),
                                                             "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    _email(W, "H3907", "01Dec")
    _email(W, "H3912", "12Dec")
    seats["H3907"] = SEAT_FILLED
    _check(W, fl)
    assert _find(W, "H3907|01Dec")[0] == "2026-11" and _find(W, "H3907|01Dec")[1]
    assert _pickup(W, "H3907|01Dec")["status"] == "filled"
    assert _find(W, "H3912|12Dec") == ("2026-12", None) and "H3912|12Dec" not in W.S["pickup_pending"]
    assert _hidden(W) == []


def test_both_on_dec_1_files_each_email_find_under_the_pot_month_it_is_live_in(mk):
    W, fl, pages, seats = _wm(mk, at(2026, 12, 1, 9), "Both", {"003.152": page(NOV + [("H3905", "01Dec")]),
                                                                "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    _email(W, "H3905", "01Dec")
    _email(W, "H3911", "03Dec")
    _check(W, fl)
    assert _find(W, "H3905|01Dec") == ("2026-11", None) and _find(W, "H3911|03Dec") == ("2026-12", None)


# ---------------------------------------------------------------- a pickup queued before: no hidden from that check
def test_a_1_8_0_pickup_of_a_december_trip_in_its_pot_ends_in_no_hidden_push(mk):
    """1.8.0 left H3911 03Dec stamped gone (missing from November's pot) with its pickup queued. Under Both, December's
    first read lists it: it is live, so its pickup is dropped with no page load and no hidden push, and the find is
    open again under 2026-12."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    row = {"pairing": "H3911", "start": "03Dec", "dates": "03Dec", "source": "email"}
    W.DB.add_find("H3911|03Dec", "mobile", row, "2026-11-23T10:26:00+00:00", gone="2026-11-23T10:27:00+00:00")
    W.S["pickup_pending"] = {"H3911|03Dec": {"tries": 0, "next": 0}}
    W.S["baseline"] = {"mobile": ["H3901|26Nov", "H3902|28Nov"]}
    W.pot_start()
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    assert _hidden(W) == [] and _pairing_loads(fl) == []
    assert "H3911|03Dec" not in W.S["pickup_pending"]
    assert _find(W, "H3911|03Dec") == ("2026-12", None)


def test_this_month_a_queued_pickup_of_a_month_not_read_ends_in_no_hidden_push(mk):
    """This month on Nov 25 (December not read): a pickup queued for H3911 03Dec (1.8.0's state) reads its page, but
    a seat still Open is no hidden trip when its month's pot was not read: no push, no 'open' verdict."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    row = {"pairing": "H3911", "start": "03Dec", "dates": "03Dec", "source": "email"}
    W.DB.add_find("H3911|03Dec", "2026-11", row, "2026-11-23T10:26:00+00:00", gone="2026-11-23T10:27:00+00:00")
    W.S["pickup_pending"] = {"H3911|03Dec": {"tries": 0, "next": 0}}
    assert _check(W, fl)[1] == ["003.152"]
    assert _hidden(W) == [] and _pickup(W, "H3911|03Dec").get("status") != "open"


def test_james_on_dec_2_a_pickup_queued_on_dec_1_ends_in_no_hidden_push(mk):
    """James, This month: H3906 01Dec leaves November's pot at Dec 1 23:58 (its pickup queued). At Dec 2 00:05 his
    check reads December's pot only: the seat still Open gives no hidden push; the pickup is not left pending."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 1, 23, 30), pages={"003.152": page(NOV), "003.153": page(DEC)},
                              instance="james")
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    pages["003.152"] = page(NOV + [("H3906", "01Dec")])
    W.CLOCK.t = at(2026, 12, 1, 23, 40)
    assert _check(W, fl)[1] == ["003.152"] and _find(W, "H3906|01Dec") == ("2026-11", None)
    pages["003.152"] = page(NOV)
    W.CLOCK.t = at(2026, 12, 1, 23, 58)
    assert _check(W, fl)[1] == ["003.152"] and "H3906|01Dec" in W.S["pickup_pending"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    assert _hidden(W) == [] and "H3906|01Dec" not in W.S["pickup_pending"]


# ---------------------------------------------------------------- POT-6: a month that leaves the watch
def test_james_novembers_finds_still_open_are_closed_at_the_end_of_its_bid_period(mk):
    """James, This month: H3906 01Dec is a find still in November's pot at its last read (Dec 1 23:50). From Dec 2
    November is not read: the find is closed at November's bid period end (Dec 2 00:00 HST), with no push and no
    pickup check."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 30, 23), pages={"003.152": page(NOV), "003.153": page(DEC)},
                              instance="james")
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    pages["003.152"] = page(NOV + [("H3906", "01Dec")])
    assert _check(W, fl)[1] == ["003.152"] and _find(W, "H3906|01Dec") == ("2026-11", None)
    W.CLOCK.t = at(2026, 12, 1, 23, 50)
    assert _check(W, fl)[1] == ["003.152"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    assert _find(W, "H3906|01Dec") == ("2026-11", "2026-12-02T10:00:00+00:00")
    assert "H3906|01Dec" not in W.S["pickup_pending"] and _hidden(W) == [] and _pairing_loads(fl) == []


def test_a_1_8_0_find_left_under_mobile_is_closed_when_1_8_1_first_starts_after_its_period(mk):
    """1.8.1 first starts on Dec 3: no plan reads 1.8.0's page (003.152), so its 'mobile' finds are never carried
    over. Open ones are closed at November's period end; a pickup queued for one is dropped with no load."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 3), "Both", {"003.153": page(DEC)})
    _periods(W)
    row = {"pairing": "H3901", "start": "26Nov", "dates": "26Nov"}
    W.DB.add_find("H3901|26Nov", "mobile", row, "2026-11-20T10:00:00+00:00")
    W.DB.add_find("H3911|03Dec", "mobile", {"pairing": "H3911", "start": "03Dec"}, "2026-11-22T10:00:00+00:00")
    W.S["baseline"] = {"mobile": ["H3901|26Nov"]}
    W.S["pickup_pending"] = {"H3901|26Nov": {"tries": 0, "next": 0, "realert": True}}
    W.pot_start()
    assert _check(W, fl)[1][0] == "003.153"
    assert _find(W, "H3901|26Nov") == ("mobile", "2026-12-02T10:00:00+00:00")
    assert _find(W, "H3911|03Dec") == ("2026-12", None)  # live in December's pot: filed there
    assert "H3901|26Nov" not in W.S["pickup_pending"] and _pairing_loads(fl) == [] and _hidden(W) == []

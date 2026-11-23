"""1.8.1 (POT-2, LIVE-1, POT-8, P9, LIVE-11, POT-6): alert-email finds and hidden-trip pushes follow the trip's own bid
month. Live on 1.8.0 (Nov 23, 2026) three December trips named in FLICA alert emails got a false CRITICAL hidden push:
each was missing from the one pot read (November's), so it counted as gone, and its seat was still Open on its pairing
page because it sat in December's pot. A find is judged gone, queued for its pickup check, scored or pushed as hidden
only against the pot of its own bid month (bid_period_key of its first day), read OK in this check; it is filed under
the pot month it is live in, else its own bid month; and a find still open when its bid period has ended is closed at
the period's end (no push, no pickup check). Review (R1, R2, R3, F1-R2): a pickup queued by a good read of the folder
the trip left (a month's pot, the close-in folder, an email find judged) is judged by that read; any other one waits
for a check that reads its month OK, its stored verdict untouched; an email find of a month not read still has its
pickup checked (a filled seat at once). FLICA is never reached: a fake browser answers with synthetic pages (made-up
pairings H39xx, made-up names)."""
import json
import re
from datetime import datetime, timezone

from test_fw181_pot_month import DEC, NOT_OPEN, NOV, STUBS, _check, _periods, at, page
from test_release_a_flica import mk, real_fl  # noqa: F401

REAL = ("email_check", "pickup_check")
SEAT_OPEN = "<html><body>pairing details {p} check in: 08:00 crew: ca 10009 doe, john fo open</body></html>"
SEAT_FILLED = ("<html><body>pairing details {p} check in: 08:00 crew: ca 10009 doe, john fo 10001 doe, jane"
               "</body></html>")
DONE = ("email_unchanged_fixed", "email_details_fixed", "pickup_backfilled", "pickers_scored", "ids_backfilled")


def _wm(mk, t, mode=None, pages=None, instance="", real=()):
    """test_fw181_pot_month._w with the real email and pickup checks, for the admin (Ryan) or a pilot (instance).
    seats {pairing: page}: its pairing page (default: the FO seat Open). real: more of the Watcher's own functions."""
    W = mk(instance, t=t)
    for f in STUBS:
        if f not in REAL + tuple(real):
            setattr(W, f, lambda *a, **k: None)
    if "close_in_check" not in real:
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


def _tie_clock(W, monkeypatch):
    """The Watcher's and the store's now_iso follow the test clock (gone_at, pickup times, dwell)."""
    import store
    clock = lambda: datetime.fromtimestamp(W.CLOCK.t, timezone.utc).isoformat()  # noqa: E731
    monkeypatch.setattr(store, "now_iso", clock)
    monkeypatch.setattr(W, "now_iso", clock)


def _row(W, key):
    return next(r for r in W.DB.recent_finds(50) if f"{r['pairing']}|{r['dates']}" == key)


# ---------------------------------------------------------------- POT-2, LIVE-1: an email find of a month not read
def test_this_month_an_email_for_a_december_trip_is_never_judged_gone_nor_pushed_hidden(mk):
    """Nov 25, This month (November's pot only): an alert email names H3911 03Dec, sitting in December's pot. Missing
    from the pot read is no proof it left: no gone_at, no hidden push, no speed; filed under its own bid month
    (2026-12), whose first read later judges it. Review R2: its pickup is still checked (a filled seat is recorded at
    once), but its seat still Open gives no verdict: it waits for a check that reads December (no read marked it)."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25, 0, 30), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    _email(W, "H3911", "03Dec")
    assert _check(W, fl)[1] == ["003.152"]
    assert _find(W, "H3911|03Dec") == ("2026-12", None)
    assert "from" not in W.S["pickup_pending"]["H3911|03Dec"]
    assert _hidden(W) == [] and len(_pairing_loads(fl)) == 1 and _pickup(W, "H3911|03Dec") == {}
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
    assert _find(W, "H3917|09Dec") == ("2026-12", None) and "from" not in W.S["pickup_pending"]["H3917|09Dec"]
    assert _find(W, "H3911|03Dec") == ("2026-12", None)  # November's read stamps no December find
    assert _hidden(W) == ["H3918|10Dec"] and _pickup(W, "H3917|09Dec") == {}
    pages["003.153"] = page(DEC[1:] + [("H3917", "09Dec")])  # read again: H3911 left December's pot
    _check(W, fl)
    assert _find(W, "H3917|09Dec") == ("2026-12", None) and "H3917|09Dec" not in W.S["pickup_pending"]  # in its pot
    assert _find(W, "H3911|03Dec")[1] and W.S["pickup_pending"]["H3911|03Dec"]["from"] == "2026-12"


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
    assert _find(W, "H3912|12Dec") == ("2026-12", None) and "from" not in W.S["pickup_pending"]["H3912|12Dec"]
    assert _hidden(W) == [] and _pickup(W, "H3912|12Dec") == {}


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


def test_james_on_dec_2_a_1_8_0_pickup_of_a_dec_1_trip_ends_in_no_hidden_push(mk):
    """James, This month, Dec 2 00:05 (his check reads December only): 1.8.0 left a pickup queued for H3906 01Dec that
    no read of its folder marked (1.8.0 kept none). Its seat still Open is no verdict (November not read this check),
    so its find keeps its record (none written), and the trip has started: it is not left pending."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 2, 0, 5), pages={"003.152": page(NOV), "003.153": page(DEC)},
                              instance="james")
    _periods(W)
    row = {"pairing": "H3906", "start": "01Dec", "dates": "01Dec"}
    W.DB.add_find("H3906|01Dec", "2026-11", row, "2026-12-01T09:40:00+00:00", gone="2026-12-02T09:58:00+00:00")
    W.S["pickup_pending"] = {"H3906|01Dec": {"tries": 0, "next": 0}}
    assert _check(W, fl)[1] == ["003.153"]
    assert len(_pairing_loads(fl)) == 1 and _hidden(W) == [] and _pickup(W, "H3906|01Dec") == {}
    assert "H3906|01Dec" not in W.S["pickup_pending"]


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


# ---------------------------------------------------------------- review R1: a hidden verdict is never thrown away
def test_r1_both_a_hidden_verdict_survives_a_check_whose_months_page_is_refused(mk):
    """Review R1 (a): Both, Nov 25: H3918 10Dec is named in an alert email, gone from December's pot (read OK) with its
    seat Open: hidden, pushed, rechecked hourly. A recheck in a check whose December page is refused once (its last
    rows stand in) keeps the 'open' verdict and its tracking, with no second push."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    _check(W, fl)
    _email(W, "H3918", "10Dec")
    _check(W, fl)
    assert _hidden(W) == ["H3918|10Dec"] and _pickup(W, "H3918|10Dec")["status"] == "open"
    W.S["pickup_pending"]["H3918|10Dec"].update(tries=W.PICKUP_TRIES, next=0)  # its tries done: the hourly recheck
    pages["003.153"] = page(NOV)  # December's page refused once
    n = len(_pairing_loads(fl))
    _check(W, fl)
    assert W.pot_rec("2026-12").get("refusals") == 1 and len(_pairing_loads(fl)) == n + 1
    assert _pickup(W, "H3918|10Dec")["status"] == "open" and "H3918|10Dec" in W.S["pickup_pending"]
    assert _hidden(W) == ["H3918|10Dec"]


def test_r1_next_month_the_daily_january_try_keeps_a_hidden_verdict(mk):
    """Review R1 (b): Next month, Dec 5 (January's pot not open yet): once a day one check is the January try, with
    December's rows of the check before standing in (no December read). A hidden trip's hourly recheck that falls in
    that check keeps its verdict and its tracking."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 5, 8), "Next month", {"003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.153"]
    assert _check(W, fl)[1] == ["003.154"]
    _email(W, "H3918", "10Dec")
    assert _check(W, fl)[1] == ["003.153"]
    assert _hidden(W) == ["H3918|10Dec"] and _pickup(W, "H3918|10Dec")["status"] == "open"
    W.S["pickup_pending"]["H3918|10Dec"].update(tries=W.PICKUP_TRIES, next=0)
    W.CLOCK.t += 86400  # a day later: the January try again
    assert _check(W, fl)[1] == ["003.154"] and W.POT_JUDGE["read"] == set()
    assert _pickup(W, "H3918|10Dec")["status"] == "open" and "H3918|10Dec" in W.S["pickup_pending"]
    assert _hidden(W) == ["H3918|10Dec"]


def test_r1_this_month_a_dec_1_hidden_trip_keeps_its_verdict_at_the_dec_2_roll_over(mk):
    """Review R1 (c): This month: H3906 01Dec leaves November's pot (read OK) on Dec 1 20:00 with its seat Open: hidden,
    pushed. Its recheck at Dec 2 00:05 (November not read any more, the trip started) is judged by November's read:
    the verdict stays 'open' and its tracking ends (the trip started)."""
    W, fl, pages, seats = _wm(mk, at(2026, 12, 1, 19), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    _check(W, fl)
    W.CLOCK.t = at(2026, 12, 1, 19, 30)
    pages["003.152"] = page(NOV + [("H3906", "01Dec")])
    _check(W, fl)
    W.CLOCK.t = at(2026, 12, 1, 20)
    pages["003.152"] = page(NOV)
    _check(W, fl)
    W.CLOCK.t = at(2026, 12, 1, 20, 10)
    _check(W, fl)
    assert _hidden(W) == ["H3906|01Dec"] and _pickup(W, "H3906|01Dec")["status"] == "open"
    W.S["pickup_pending"]["H3906|01Dec"]["next"] = 0
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    assert _pickup(W, "H3906|01Dec")["status"] == "open" and "H3906|01Dec" not in W.S["pickup_pending"]
    assert _hidden(W) == ["H3906|01Dec"]


def test_r1_a_stored_open_verdict_is_never_overwritten_by_a_check_that_does_not_read_its_month(mk):
    """Review R1, F1-R2: 1.8.0 left H3911 03Dec with a pickup 'open' (pushed, its tries done, rechecked hourly) that no
    read of its folder marked. This month on Nov 25 (December not read): its recheck reads the seat Open, which is no
    verdict, so the stored record stands and it stays tracked for a check that reads December; no push."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    row = {"pairing": "H3911", "start": "03Dec", "dates": "03Dec", "source": "email"}
    W.DB.add_find("H3911|03Dec", "2026-11", row, "2026-11-23T10:26:00+00:00", gone="2026-11-23T10:27:00+00:00")
    W.DB.set_pickup("H3911|03Dec", {"status": "open", "by": "", "ca": "", "known": False,
                                    "at": "2026-11-23T10:30:00+00:00"})
    W.S["pickup_pending"] = {"H3911|03Dec": {"tries": W.PICKUP_TRIES + 1, "next": 0, "logged": "open"}}
    assert _check(W, fl)[1] == ["003.152"]
    assert len(_pairing_loads(fl)) == 1 and _hidden(W) == []
    assert _pickup(W, "H3911|03Dec") == {"status": "open", "by": "", "ca": "", "known": False,
                                         "at": "2026-11-23T10:30:00+00:00"}
    assert W.S["pickup_pending"]["H3911|03Dec"]["next"] > W.CLOCK.t - 600 + W.PICKUP_OPEN_S - 300  # an open seat's hour


# ---------------------------------------------------------------- review R2, F1-R1: an email find of a month not read
def test_r2_both_an_email_find_of_a_refused_check_is_judged_at_its_months_next_read(mk):
    """Review R2, F1-R1: Both, Nov 25: December's page is refused one check; an alert email names H3917 09Dec
    meanwhile (stored open; its pickup read, the seat Open: no verdict). December's next good read does not list it
    and its seat is still Open: it is stamped gone and pushed as hidden."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    pages["003.153"] = page(NOV)  # refused once
    _email(W, "H3917", "09Dec")
    _check(W, fl)
    assert _find(W, "H3917|09Dec") == ("2026-12", None) and _hidden(W) == [] and _pickup(W, "H3917|09Dec") == {}
    pages["003.153"] = page(DEC)  # read OK: H3917 not in it
    for _ in range(3):
        _check(W, fl, step=1300)
    assert _find(W, "H3917|09Dec")[1] and _pickup(W, "H3917|09Dec")["status"] == "open"
    assert _hidden(W) == ["H3917|09Dec"]


def test_r2_this_month_a_december_email_find_picked_up_at_once_has_its_pickup_and_a_short_dwell(mk, monkeypatch):
    """Review R2 (probe 5): This month, Nov 25 (December not read): an alert email names H3916 06Dec, whose pairing page
    shows its seat filled. Its pickup is checked at once: picked up, so it left the pot (gone now, a dwell of minutes,
    the picker named); December's first read on Dec 2 changes neither."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25, 12), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    _tie_clock(W, monkeypatch)
    _check(W, fl)
    _email(W, "H3916", "06Dec", at_iso="2026-11-25T22:05:00+00:00")  # Nov 25 12:05 HST
    seats["H3916"] = SEAT_FILLED
    _check(W, fl)
    gone = _find(W, "H3916|06Dec")[1]
    pk = _pickup(W, "H3916|06Dec")
    assert gone and pk["status"] == "filled" and pk["pickers"] == ["10001"]
    assert "H3916|06Dec" not in W.S["pickup_pending"]
    assert _row(W, "H3916|06Dec")["dwell_s"] < 3600 and _hidden(W) == []
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    assert _find(W, "H3916|06Dec") == ("2026-12", gone) and _row(W, "H3916|06Dec")["dwell_s"] < 3600


def test_r2_this_month_an_email_find_picked_up_before_dec_2_has_its_pickup_after_decembers_first_read(mk):
    """Review F1-R1: This month, Nov 25: an alert email names H3912 12Dec, sitting in December's pot (not read): its
    seat Open is no verdict. It is picked up before Dec 2; December's first read does not list it: its pickup is
    recorded (who picked it up), with no hidden push."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25, 0, 30), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152"]
    _email(W, "H3912", "12Dec")
    _check(W, fl)
    assert _find(W, "H3912|12Dec") == ("2026-12", None) and _pickup(W, "H3912|12Dec") == {}
    seats["H3912"] = SEAT_FILLED
    pages["003.153"] = page([x for x in DEC if x[0] != "H3912"])
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    _check(W, fl)
    assert _find(W, "H3912|12Dec")[1] and _pickup(W, "H3912|12Dec")["status"] == "filled"
    assert "H3912|12Dec" not in W.S["pickup_pending"] and _hidden(W) == []


# ---------------------------------------------------------------- review R3, F1-R2: judged by the folder it left
def test_r3_next_month_a_trip_that_leaves_the_close_in_folder_is_judged_by_that_folders_read(mk):
    """Review R3 (a): Next month, Nov 25 (December's pot only, November not read): H3930 26Nov was in the close-in
    folder and leaves it (read OK) with its seat still Open: that folder's read judged it gone, so it is pushed as
    hidden."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Next month", {"003.152": page(NOV), "003.153": page(DEC)},
                              real=("close_in_check",))
    _periods(W)
    W.S["close_in"] = {"bcid": "008.152", "verified": True, "menu_at": W.CLOCK.t, "baseline": ["H3930|26Nov"]}
    row = {"pairing": "H3930", "start": "26Nov", "dates": "26Nov", "src": "C", "folder": "close-in",
           "crew": [["CA", "DOE, JOHN"], ["FO", "OPEN"]]}
    W.DB.add_find("H3930|26Nov", W.CLOSE_IN_KEY, row, "2026-11-25T21:00:00+00:00")
    pages["008.152"] = page([])  # H3930 left the close-in folder
    assert _check(W, fl)[1] == ["003.153", "008.152"]
    assert _find(W, "H3930|26Nov")[1] and "H3930|26Nov" in W.S["pickup_pending"]
    _check(W, fl)
    assert _pickup(W, "H3930|26Nov")["status"] == "open" and _hidden(W) == ["H3930|26Nov"]


def test_r3_without_pairing_files_a_dec_1_trip_that_left_novembers_pot_is_judged_by_that_read(mk):
    """Review R3 (b): This month, Nov 25, no pairing files yet (bid_period_key falls back to the calendar month, so a
    Dec 1 trip reads as December's): H3905 01Dec leaves November's pot (read OK) with its seat Open. November's read
    judged it gone: pushed as hidden."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), pages={"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl)[1] == ["003.152"]
    pages["003.152"] = page(NOV + [("H3905", "01Dec")])
    _check(W, fl)
    assert _find(W, "H3905|01Dec") == ("2026-11", None)
    pages["003.152"] = page(NOV)
    _check(W, fl)
    assert W.find_period("H3905|01Dec") == "2026-12"
    _check(W, fl)
    assert _pickup(W, "H3905|01Dec")["status"] == "open" and _hidden(W) == ["H3905|01Dec"]


def test_f1r2_both_then_this_month_a_trip_judged_gone_by_decembers_read_is_still_pushed_hidden(mk):
    """Review F1-R2: Both: H3913 20Dec leaves December's pot (a good read) with its seat still Open; Ryan sets This
    month before its pickup check. December's own read judged it gone: pushed as hidden, after one pairing page load
    (no tries spent for nothing)."""
    W, fl, pages, seats = _wm(mk, at(2026, 11, 25), "Both", {"003.152": page(NOV), "003.153": page(DEC[:2])})
    _periods(W)
    assert _check(W, fl)[1] == ["003.152", "003.153"]
    pages["003.153"] = page(DEC)
    _check(W, fl)
    assert _find(W, "H3913|20Dec") == ("2026-12", None)
    pages["003.153"] = page(DEC[:2])
    _check(W, fl, step=60)
    assert "H3913|20Dec" in W.S["pickup_pending"]
    W.S["pot_month"] = "This month"
    W.S["pot_urls"] = {}
    for _ in range(2):  # its pickup comes due (PICKUP_FIRST_S) in the second check
        assert _check(W, fl, step=1300)[1] == ["003.152"]
    assert _hidden(W) == ["H3913|20Dec"] and _pickup(W, "H3913|20Dec")["status"] == "open"
    assert len(_pairing_loads(fl)) == 1

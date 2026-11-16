"""1.7.10 (Ryan, Nov 15), the pickup speed cap: when Ryan himself asked for a trip and FLICA denied him because
another pilot picked it up ('CS: H3607:17NOV picked up by DOE, JANE (10001)' on his Open Time Requests list), that
picker asked before Ryan did, so his pickup speed ends no later than Ryan's Requested time (its minute + 59 s), not
at FLICA's decision time and not at the Watcher's later pot read. Every other pickup keeps store.dwell's estimate.
History is recalculated once from the request lists on file; each later read of the list applies it; the cards say
"at most". No FLICA page beyond the lists requests_check already reads. Synthetic pilots only ("Doe, Jane" 10001)."""
import json
import logging

import pytest

import submit as SUB
from store import Store, dwell, req_cap_secs, speed
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw177_pickers import JANE, RICK, _find

KEY = "H3607|17Nov"
FIRST, LAST, GONE = "2026-10-30T22:00:00+00:00", "2026-10-30T22:09:00+00:00", "2026-10-30T22:11:00+00:00"
REQ = "2026-10-30T12:03-10:00"  # Ryan's Requested (HA) 30 OCT 12:03 = 22:03 UTC


# ---------------------------------------------------------------- the request list's text
def test_the_picked_up_by_comment_parses():
    got = SUB.picked_up("cs: h3607:17nov picked up by doe, jane (10001) note: x")
    assert got == {"trip": "H3607", "day": "17NOV", "name": "Doe, Jane", "emp": "10001"}
    assert SUB.picked_up("CS: H3631B:7DEC picked up by O'DOE JR, SEAN P (010004)") == {
        "trip": "H3631B", "day": "07DEC", "name": "O'Doe Jr, Sean P", "emp": "10004"}
    assert SUB.picked_up("cs: rest short on 20nov") is None and SUB.picked_up("") is None
    assert SUB.status_at("Denied 30 OCT 15:10") == ("10/30", "15:10") == SUB.status_at("denied 10/30 15:10")
    assert SUB.requested_at("requested (ha) 30 oct 15:08 status: denied 30 oct 15:10") == ("10/30", "15:08")
    assert SUB.requested_at("swap h3911 time: 11/02 18:41 status: denied") == ("11/02", "18:41")
    assert SUB.requested_at("no time here") is None and SUB.status_at("denied 45 xyz 99:99") is None


def test_the_year_comes_from_the_bid_folders_month():
    assert SUB.req_time("10/30", "15:08", "2026-11") == "2026-10-30T15:08-10:00"
    assert SUB.req_time("12/28", "23:59", "2027-01") == "2026-12-28T23:59-10:00"  # late Dec in January's folder
    assert SUB.req_time("01/02", "08:00", "2026-12") == "2027-01-02T08:00-10:00"  # early Jan in December's folder
    from datetime import datetime, timezone
    assert SUB.req_time("12/31", "09:00", None, datetime(2027, 1, 3, tzinfo=timezone.utc)) == "2026-12-31T09:00-10:00"
    assert SUB.req_time("02/30", "09:00", "2026-03") is None and SUB.req_time("x", "y", "2026-03") is None


LIST = ("open time requests 10/30 12:03 add denied 30 oct 12:05 cs: h3607:17nov picked up by doe, jane (10001) "
        "10/30 14:00 add denied 30 oct 14:02 cs: rest short on 20nov 10/31 09:00 add approved 31 oct 09:05")
IDS = "".join(f'<a href="x?ShowRequest=1&amp;TimeStamp=AAAA{i}:BBBB{i}">v</a>' for i in range(3))


def test_a_denied_row_keeps_who_picked_the_trip_up():
    for html in (None, IDS):  # with FLICA's request ids the row's detail is dropped; what the cap needs is kept
        rows = SUB.parse_request_rows(LIST, html)
        assert [r["status"] for r in rows] == ["Denied", "Denied", "Approved"]
        assert rows[0]["pu"] == {"trip": "H3607", "day": "17NOV", "emp": "10001"} and rows[0]["st_at"] == "10/30 12:05"
        assert "pu" not in rows[1] and "pu" not in rows[2] and rows[2]["st_at"] == "10/31 09:05"
        assert SUB.row_cap(rows[0]) == {"trip": "H3607", "day": "17NOV", "emp": "10001"}
        assert SUB.row_cap(rows[1]) is None and SUB.row_cap(rows[2]) is None
        assert "Doe" not in json.dumps(rows[0]["pu"])  # the picker's name is not kept on the row
    # a row whose comment came from its view page (the reason the 1.3.0 push reads)
    assert SUB.row_cap({"status": "Denied", "reason": "H3607:17NOV picked up by DOE, JANE (10001)"})["emp"] == "10001"
    assert SUB.row_cap({"status": "Approved", "reason": "H3607:17NOV picked up by DOE, JANE (10001)"}) is None


# ---------------------------------------------------------------- the store
def _db(tmp_path, by=f"FO {JANE}", seats="FO", pickers=("10001",), key=KEY):
    db = Store(str(tmp_path / "s.db"))
    _find(db, key, by, GONE, seats, pickup={"pickers": list(pickers)}, first=FIRST)
    db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (LAST, key))
    return db


def _pk(db, key=KEY):
    return json.loads(db.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()[0])


def _log(db):
    return {k: (s, c) for k, s, c in db.db.execute("SELECT key,secs,cap FROM picker_log")}


def test_the_cap_is_the_requests_minute_plus_59_seconds():
    assert dwell(FIRST, LAST, GONE) == (600, 60)  # the middle of the last-listed / found-gone window
    assert req_cap_secs(FIRST, None, REQ) == 239  # 22:00:00 to 22:03:59
    assert speed(FIRST, LAST, GONE, None, REQ) == (239, 0, True)
    assert speed(FIRST, LAST, GONE, None, None) == (600, 60, False)
    assert speed(FIRST, LAST, GONE, None, "2026-10-30T12:30-10:00") == (600, 60, False)  # asked after it was gone
    assert req_cap_secs(FIRST, "2026-10-30T21:58:00+00:00", REQ) == 359  # FLICA's alert is the earlier entry
    assert req_cap_secs(FIRST, None, "2026-10-30T12:00-10:00") == 59 and req_cap_secs(FIRST, None, "2026-10-30T11:59-10:00") == 0
    assert req_cap_secs(FIRST, None, "2026-10-30T09:00-10:00") is None  # hours before: another time in the pot
    assert req_cap_secs(FIRST, None, "nonsense") is None and req_cap_secs(FIRST, None, "") is None


def test_a_scored_pickup_is_capped_and_stays_capped(tmp_path):
    db = _db(tmp_path)
    assert db.score_pickup(KEY) == 600 and _log(db) == {f"{KEY}|10001": (600, 0)}
    assert db.set_req_cap(KEY, REQ, "10001") == "capped"
    pk = _pk(db)
    assert (pk["scored"], pk["capped"], pk["req_caps"]) == (239, True, {"10001": REQ})
    assert _log(db) == {f"{KEY}|10001": (239, 1)}
    st = db.picker_stats()["10001"]
    assert (st["total_s"], st["n"], st["min_s"], st["cap_n"], st["min_cap"]) == (239, 1, 239, 1, True)
    row = db.recent_finds()[0]
    assert (row["dwell_s"], row["dwell_pm_s"], row["dwell_cap"]) == (239, 0, True)
    assert db.pickup_history()[0]["secs"] == 239
    # idempotent, through a rescore of everything and a pickup re-check
    assert db.set_req_cap(KEY, REQ, "10001") == "same"
    db.rescore_all()
    db.set_pickup(KEY, {"status": "filled", "by": f"FO {JANE}", "ca": "", "known": True, "pickers": ["10001"]})
    db.rescore_all()
    assert _pk(db)["scored"] == 239 and _pk(db)["req_caps"] == {"10001": REQ} and _log(db) == {f"{KEY}|10001": (239, 1)}
    # an earlier request of the same pilot lowers it; a later one never raises it
    assert db.set_req_cap(KEY, "2026-10-30T12:01-10:00", "10001") == "capped" and _pk(db)["scored"] == 119
    assert db.set_req_cap(KEY, REQ, "10001") == "same" and _pk(db)["scored"] == 119


def test_a_pickup_scored_after_the_denial_is_capped_too(tmp_path):
    db = _db(tmp_path)
    assert db.set_req_cap(KEY, REQ, "10001") == "kept"  # not scored yet: the cap waits on the pickup
    assert db.score_pickup(KEY) == 239 and _pk(db)["capped"] is True and _log(db) == {f"{KEY}|10001": (239, 1)}


def test_only_the_picker_flica_named_is_capped(tmp_path):
    db = _db(tmp_path, by=f"FO {JANE}; RO {RICK}", seats="FO,RO", pickers=("10001", "10002"))
    db.score_pickup(KEY)
    assert db.set_req_cap(KEY, REQ, "10002") == "capped"
    assert _log(db) == {f"{KEY}|10001": (600, 0), f"{KEY}|10002": (239, 1)}
    st = db.picker_stats()
    assert (st["10001"]["min_cap"], st["10001"]["cap_n"], st["10002"]["min_cap"]) == (False, 0, True)
    assert db.set_req_cap(KEY, REQ, "10009") is None  # not an open-seat picker of this pickup: nothing
    assert db.set_req_cap("H9999|01Dec", REQ, "10001") is None


def test_a_cap_that_does_not_win_leaves_the_estimate(tmp_path):
    db = _db(tmp_path)
    db.score_pickup(KEY)
    assert db.set_req_cap(KEY, "2026-10-30T12:30-10:00", "10001") == "kept"
    assert _pk(db)["scored"] == 600 and "capped" not in _pk(db) and _log(db) == {f"{KEY}|10001": (600, 0)}
    assert db.recent_finds()[0]["dwell_cap"] is False and db.picker_stats()["10001"]["cap_n"] == 0


# ---------------------------------------------------------------- the Watcher
URL = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"


def _watch(W, monkeypatch, tmp_path, body=LIST, ids=IDS):  # noqa: N803
    monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "cap"))
    monkeypatch.setattr(W, "trade_check", lambda: None)
    W.S["pot_urls"] = {"2026-11": URL}
    # the one-time parser-check copies (the list, a view page) were taken long ago: this read loads the list only
    W.S["req_captured"] = {"152": True}
    W.S["req_view_captured"] = {"152": True}
    fetched = []

    class FL:
        def fetch(self, url):
            fetched.append(url)
            if "TB_MyRequests" in url:
                return "<html><body>my requests</body></html>"
            return f"<html><body>{body}{ids}</body></html>"

    def read():
        W.S["req_force"] = True
        W.requests_check(FL())
    return fetched, read


def _seed(W, key=KEY, by=f"FO {JANE}", pickers=("10001",)):  # noqa: N803
    W.DB.add_find(key, "2026-11", {"pairing": key.split("|")[0], "start": "17Nov", "dates": "17Nov-20Nov",
                                   "open_seats": "FO", "layover": "LAX"}, FIRST, gone=GONE)
    W.DB.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (LAST, key))
    W.DB.set_pickup(key, {"status": "filled", "by": by, "ca": "", "known": True, "pickers": list(pickers)})
    W.DB.score_pickup(key)


def test_a_read_of_the_request_list_caps_the_pickup(W, tmp_path, monkeypatch, caplog):  # noqa: F811
    _seed(W)
    _seed(W, "H3608|18Nov", f"FO {RICK}", ("10002",))  # another pickup, no denial: keeps today's estimate
    fetched, read = _watch(W, monkeypatch, tmp_path)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert _pk(W.DB)["scored"] == 239 and _pk(W.DB)["req_caps"] == {"10001": REQ} and _pk(W.DB)["capped"] is True
    assert _pk(W.DB, "H3608|18Nov")["scored"] == 600 and "req_caps" not in _pk(W.DB, "H3608|18Nov")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("speed:")]
    assert lines == ["speed: 1 pickup capped at Ryan's request time, 0 unmatched"]
    for leak in ("10001", "Doe", "doe", "Jane", "jane"):  # counts only: no name, no employee number in the log
        assert leak not in caplog.text, leak
    # no FLICA page beyond the request list and the Tradeboard page it already read; no link followed
    assert len(fetched) == 2 and all("QuickDelete" not in u and "ShowRequest" not in u for u in fetched)
    # the finds export and the pickers publish carry it
    finds = [p for t, p in W.SENT if t == "finds"]
    pickers = [p for t, p in W.SENT if t == "pickers"][-1]["pickers"]
    assert finds and {p["emp"]: (p["min_s"], p["min_cap"], p["cap_n"]) for p in pickers} == {
        "10001": (239, True, 1), "10002": (600, False, 0)}
    # the published request rows carry none of the cap's fields
    sensor = [p for t, p in W.SENT if t == "ot_requests"][-1]
    assert sensor["count"] == 3 and all("pu" not in r and "st_at" not in r for r in sensor["requests"])
    assert W.S["ot_req_rows"]["003.152"][0]["pu"] == {"trip": "H3607", "day": "17NOV", "emp": "10001"}
    # the next read: idempotent, nothing said, nothing more loaded than the same two pages
    n = len(caplog.records)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert not [r for r in caplog.records[n:] if r.getMessage().startswith("speed:")]
    assert len(fetched) == 4 and _pk(W.DB)["scored"] == 239


def test_a_picker_flica_did_not_name_is_not_capped(W, tmp_path, monkeypatch, caplog):  # noqa: F811
    _seed(W, by=f"FO {RICK}", pickers=("10002",))  # the pickup's picker is another pilot than the comment's
    _fetched, read = _watch(W, monkeypatch, tmp_path)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert _pk(W.DB)["scored"] == 600 and "req_caps" not in _pk(W.DB)
    assert "speed: 0 pickups capped at Ryan's request time, 1 unmatched" in caplog.text
    assert "10001" not in caplog.text and "10002" not in caplog.text


def test_history_is_recalculated_once_from_the_lists_on_file(W, tmp_path, monkeypatch, caplog):  # noqa: F811
    """The lists on file: a row kept in the state with its view page's reason (as 1.3.0 stored a pushed denial), and
    the admin's own captured request page; the list read now names no pickup at all."""
    _seed(W)
    _seed(W, "H3609|19Nov", f"FO {RICK}", ("10002",))
    cap = tmp_path / "cap"
    cap.mkdir()
    (cap / "otrequests_152.html").write_text(
        "<html><body>open time requests 10/30 12:04 add denied 30 oct 12:06 cs: h3609:19nov picked up by roe, rick "
        "(10002)" + IDS[:len(IDS) // 3] + "</body></html>")
    fetched, read = _watch(W, monkeypatch, tmp_path, body="open time requests 10/30 12:03 add denied 30 oct 12:05",
                           ids=IDS[:len(IDS) // 3])
    W.S["ot_req_rows"] = {"003.152": [{"key": "ts:AAAA0:BBBB0", "ts": "AAAA0:BBBB0", "date": "10/30", "time": "12:03",
                                       "type": "Add", "status": "Denied", "detail": "", "legs": [], "trips": [],
                                       "reason": "H3607:17NOV picked up by DOE, JANE (10001)"}]}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert _pk(W.DB)["scored"] == 239 and _pk(W.DB, "H3609|19Nov")["scored"] == 299  # 22:00:00 to 22:04:59
    assert "speed: 2 pickups capped at Ryan's request time, 0 unmatched" in caplog.text
    assert W.DB.get("req_cap_v") == W.REQ_CAP_V
    assert W.S["ot_req_rows"]["003.152"][0]["pu"]["emp"] == "10001"  # kept on the row of the same request
    assert len(fetched) == 2


def test_a_pilots_instance_caps_from_its_own_list_only(tmp_path, monkeypatch, caplog):
    """James's Watcher: his own request list caps the pickups in his own database (his own request time), his
    captures stay off (no captured page is read), and the log names nobody."""
    from test_instance import _load
    W = _load(tmp_path, monkeypatch, "james", {"username": "u", "password": "p", "log_level": "info",  # noqa: N806
                                               "category_check": "HNL 332 FO"})
    W.SENT = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: W.SENT.append((t, p)))
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "james.db")))
    monkeypatch.setattr(W, "opt_fits", lambda n: True)
    _seed(W)
    cap = tmp_path / "cap"
    cap.mkdir()
    (cap / "otrequests_152.html").write_text("<html><body>open time requests 10/30 12:00 add denied cs: h3607:17nov "
                                             "picked up by doe, jane (10001)</body></html>")
    assert not W.CAP.admin and W.req_cap_captures() == []
    _fetched, read = _watch(W, monkeypatch, tmp_path)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        read()
    assert _pk(W.DB)["scored"] == 239
    assert "speed: 1 pickup capped at this pilot's own request time, 0 unmatched" in caplog.text
    assert "10001" not in caplog.text and "doe" not in caplog.text.lower()


# ---------------------------------------------------------------- the cards say "at most"
def test_the_finds_and_pickers_cards_mark_a_capped_speed(W, tmp_path):  # noqa: F811
    """In Chromium, on rows the real Store and Watcher make: the capped pickup shows the sign for 'at most' before its
    speed with the reason on hover (and for a screen reader); every other row is as before. FW_1710_SHOTS=<dir> keeps
    the screenshots."""
    import os
    import test_fw177_cards as C
    C._data(W, tmp_path)
    db = W.DB
    assert db.set_req_cap("H9305|23Nov", "2026-11-14T07:00-10:00", "10001") == "capped"  # seen 07:00, gone by 07:02
    finds = db.finds_between(C._at(1, 0), C._at(15, 0))
    W.publish_pickers()
    pickers = [p for t, p in W.SENT if t == "pickers"][-1]["pickers"]
    by = {f["pairing"]: f for f in finds}
    assert (by["H9305"]["dwell_s"], by["H9305"]["dwell_cap"]) == (59, True) and by["H9307"]["dwell_cap"] is False
    shots = os.environ.get("FW_1710_SHOTS", "")
    js = """() => [...FC.shadowRoot.querySelectorAll('tbody tr')].filter((tr) => tr.children.length > 3).map((tr) => {
      const s = tr.querySelector('span[title*="request time"]');
      return [tr.children[2].textContent.trim(), s ? s.textContent : '', s ? s.getAttribute('title') : '',
              s ? s.getAttribute('aria-label') : '', [...tr.children].some((td) => td.textContent.includes('≤'))]; })"""
    with C._browser() as b:
        for width, height in ((390, 844), (1280, 800)):
            pg = C._page(b, width, height, "light", finds, pickers)
            rows = {r[0]: r[1:] for r in pg.evaluate(js)}
            text, title, aria, _ = rows["H9305"]
            assert text.replace("≤", "<=").startswith("<=59s"), text
            assert title.startswith("at most 59s: capped at your request time (FLICA denied your request because this "
                                    "pilot picked it up first)") and aria == title.split(";")[0]
            assert all(not r[3] for k, r in rows.items() if k != "H9305")  # no other row carries the sign
            pg.evaluate("() => { FC.shadowRoot.querySelector('details.key').open = true; }")
            assert "≤ = at most: capped at your own request time" in pg.evaluate(
                "() => FC.shadowRoot.querySelector('details.key').textContent")
            cells = pg.evaluate("""() => [...PC.shadowRoot.querySelectorAll('tbody tr')].map((tr) => [
              tr.querySelector('.nm').textContent, tr.children[8].textContent, tr.children[9].textContent,
              (tr.children[8].querySelector('span[title]') || { title: '' }).title])""")
            jane = next(c for c in cells if c[0] == "Doe, Jane")
            assert jane[1] == "≤59s" and jane[2].startswith("≤") and jane[3] == "at most 59s, capped at your request time"
            assert all("≤" not in c[1] + c[2] for c in cells if c[0] != "Doe, Jane")
            assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth") and pg.errors == []
            if shots:
                os.makedirs(shots, exist_ok=True)
                pg.evaluate("() => { const w = FC.shadowRoot.querySelector('.wrap'); w.scrollLeft = w.scrollWidth; }")
                pg.locator("flight-watcher-finds-card").first.screenshot(path=os.path.join(shots, f"cap_finds_{width}.png"))
                pg.locator("flight-watcher-pickers-card").first.screenshot(path=os.path.join(shots, f"cap_pickers_{width}.png"))
            pg.context.close()

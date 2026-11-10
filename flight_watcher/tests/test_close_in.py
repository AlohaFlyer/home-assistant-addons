"""FW-0034: the close-in open time folder ('Close in Opentime: <16 Hrs to RPT'). Its BCID is taken only from a menu
link whose text names the folder (never guessed), trusted once its open time page reads, and its pot and request list
join the paced reads (GET only, SUB.safe_get + SM.safe_get). Synthetic pages, made-up pairings and names only."""
import json

import pot as P
import submit as SUB
import swapmap as SM

REG = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"

# a menu as plain HTML: sections in bold, a month, then the folder's links (shape made up, names made up)
MENU_HTML = """<html><body>
<b>OPEN TIME- Add/Swap/Drop requests</b><div>November</div>
<a href="/full/mobileopentimepot.cgi?BCID=003.152&amp;From=MainMenu">View Opentime Pot</a>
<a href="/full/mobileotrequest.cgi?BCID=003.152&amp;From=MainMenu">Open Time Requests</a>
<b>Close in Opentime: &lt;16 Hrs to RPT</b><div>November</div>
<a href="/full/mobileopentimepot.cgi?BCID=008.152&amp;From=MainMenu">View Opentime Pot</a>
<b>TradeBoard</b><a href="/online/tb_frame.cgi?BCID=001.152&amp;dp=mr">My Requests</a>
</body></html>"""

# the left menu's JS tree (M.addC / M.addE), the way FLICA builds it inside the menu frame (arguments made up)
MENU_JS = """<html><head><script>
M.addC('OPEN TIME- Add/Swap/Drop requests');
M.addE('November 2026', '');
M.addE('View Opentime Pot', "javascript:openOT('/full/otframe.cgi?BCID=003.152&ViewOT=1');");
M.addC('Close in Opentime: &lt;16 Hrs to RPT');
M.addE('November 2026', '');
M.addE('View Opentime Pot', "javascript:openOT('008.152');");
M.addE('December 2026', '');
M.addE('View Opentime Pot', "javascript:openOT('008.153');");
</script></head><body></body></html>"""


def test_folder_found_under_its_heading_and_regular_folders_never_taken():
    assert P.close_in_folders(MENU_HTML, {"003.152", "001.152"}) == [
        {"bcid": "008.152", "text": "Close in Opentime: <16 Hrs to RPT"}]
    found = P.close_in_folders(MENU_JS, {"003.152"})
    assert [f["bcid"] for f in found] == ["008.152"]  # the first link under the heading only


def test_a_link_naming_the_folder_and_a_folder_option():
    page = ('<a href="/full/mobileopentimepot.cgi?BCID=003.152">Open Time</a>'
            '<a href="/full/mobileopentimepot.cgi?BCID=008.153&amp;From=MainMenu">Close in Opentime: &lt;16 Hrs to RPT</a>')
    assert [f["bcid"] for f in P.close_in_folders(page, {"003.152"})] == ["008.153"]
    sel = ('<select name="BCID"><option value="003.152">OPEN TIME- Add/Swap/Drop requests - November</option>'
           '<option value="008.152">Close in Opentime: &lt;16 Hrs to RPT</option></select>')
    assert [f["bcid"] for f in P.close_in_folders(sel, {"003.152"})] == ["008.152"]


def test_nothing_is_guessed():
    assert P.close_in_folders(MENU_HTML.replace("Close in Opentime: &lt;16 Hrs to RPT", "Reserve"), {"003.152"}) == []
    # the heading is there but the next heading comes before any link
    page = ("<b>Close in Opentime: &lt;16 Hrs to RPT</b><b>Reserve Grid</b>"
            '<a href="/full/x.cgi?BCID=009.152">View</a>')
    assert P.close_in_folders(page) == []
    # a link naming the folder whose BCID is a regular one
    page = '<a href="/full/mobileopentimepot.cgi?BCID=003.152">Close in Opentime</a>'
    assert P.close_in_folders(page, {"003.152"}) == []
    assert P.close_in_folders("") == [] and P.pick_close_in([], {"152"}) is None


def test_pick_the_watched_bid_period():
    found = [{"bcid": "008.153", "text": ""}, {"bcid": "008.152", "text": ""}]
    assert P.pick_close_in(found, {"152", "153"}) == "008.152"
    assert P.pick_close_in(found, {"153"}) == "008.153"
    assert P.pick_close_in(found, set()) == "008.153"


# ---------------------------------------------------------------- the Watcher
def _pot_page(rows=()):
    trs = "".join(f"<tr><td>{p}</td><td>{s}</td><td>{s}</td><td>6.10</td><td>-none-</td><td></td><td></td>"
                  f"<td>09:00</td><td>15:00</td><td>1</td><td></td></tr>" for p, s in rows)
    return (f"<html><body>Nov 2026 Open Time as of: 11/07 09:00 HA [HNL 332 FO] <table>{trs}</table>"
            "[HNL 332 FO]</body></html>")


def _w(tmp_path, monkeypatch, menu=MENU_HTML, frame=""):
    from test_instance import FakeClient, _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info",
                                          "category_check": "HNL 332 FO"})
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "cap"))
    waits = []
    monkeypatch.setattr(W.time, "sleep", waits.append)
    W.S["pot_urls"] = {"mobile": REG}
    pages = {"leftmenu": menu, "008.152": _pot_page(), "mobilepairing": "<html><body>Check In: 08:00</body></html>"}
    fetched, framed = [], []

    class FL:
        def fetch(self, url):
            fetched.append(url)
            return next((v for k, v in pages.items() if k in url), "<html><body>nothing</body></html>")

        def menu_tree(self):
            framed.append(1)
            return frame
    events = lambda t: [json.loads(p) for tp, p, _ in fake.msgs if tp == f"flight_watcher/event/{t}"]  # noqa: E731
    return W, FL(), pages, fetched, framed, waits, events


def test_discovered_verified_then_read_like_the_pot(tmp_path, monkeypatch):
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    rows, kind = W.close_in_check(fl, {"mobile": {}})
    ci = W.S["close_in"]
    assert ci["bcid"] == "008.152" and ci["verified"] and W.S["close_in_bcid"] == "008.152"
    assert rows == {} and kind == "ok" and events("new_pairing") == []  # first read: baseline, no alert
    assert fetched[-1] == "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=008.152&From=MainMenu"
    assert not framed  # the plain left menu named it
    assert all(SUB.safe_get(u) and SM.safe_get(u) for u in fetched)
    assert len(waits) == len(fetched) and all(1.5 <= w <= 3.5 for w in waits)  # every page load paced
    # a new close-in trip pushes like a pot find; one also in the regular pot does not
    pages["008.152"] = _pot_page([("H3627", "07Nov"), ("H3628", "07Nov")])
    reg = {"mobile": {"H3628|07Nov": {"pairing": "H3628", "start": "07Nov"}}}
    rows, _ = W.close_in_check(fl, reg)
    assert list(rows) == ["H3627|07Nov"] and rows["H3627|07Nov"]["src"] == "C"
    ev = events("new_pairing")
    assert [(e["pairing"], e["folder"], e["month"]) for e in ev] == [("H3627", "close-in", "closein")]
    assert "far" in ev[0]
    n = len(fetched)
    W.close_in_check(fl, reg)  # the menu is not read again for a day; details are cached
    assert len(fetched) == n + 1 and len(events("new_pairing")) == 1
    assert len(waits) == len(fetched) and all(1.5 <= w <= 3.5 for w in waits)
    # drafts now carry the close-in BCID
    rec = SUB.compose({"for": "H3600|2026-11-08", "pairing": "H3627", "start": "2026-11-07"}, "003.152", 5,
                      close_in_bcid=W.S["close_in_bcid"])
    assert rec["folder"] == "close-in" and rec["bcid"] == "008.152" and not rec["sendable"]


def test_menu_frame_when_the_left_menu_is_a_skeleton(tmp_path, monkeypatch):
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch, menu="<html><body>menu</body></html>",
                                                      frame=MENU_JS)
    W.close_in_check(fl, {"mobile": {}})
    assert framed and W.S["close_in"]["via"] == "main menu frame" and W.S["close_in_bcid"] == "008.152"


def test_not_named_logs_and_keeps_the_menu_privately(tmp_path, monkeypatch):
    menu = MENU_HTML.replace("Close in Opentime: &lt;16 Hrs to RPT", "Reserve").replace("008.152", "009.152")
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch, menu=menu)
    assert W.close_in_check(fl, {"mobile": {}}) == ({}, "ok")
    assert not W.S.get("close_in_bcid") and (tmp_path / "cap" / "menu_closein.html").exists()
    assert not any("009.152" in u for u in fetched) and not framed  # a real menu: the frame shows the same
    n = len(fetched)
    W.close_in_check(fl, {"mobile": {}})
    assert len(fetched) == n  # next menu read in 6 h


def test_a_bcid_whose_page_is_not_open_time_is_dropped(tmp_path, monkeypatch):
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    pages["008.152"] = "<html><body>Service Temporarily Unavailable</body></html>"
    for _ in range(W.CLOSE_IN_BAD_MAX):
        W.close_in_check(fl, {"mobile": {}})
        assert not W.S.get("close_in_bcid")
    assert "bcid" not in W.S["close_in"] and W.S["close_in"]["rejected"] == ["008.152"]
    assert W.close_in_scan(MENU_HTML, "left menu") is None  # never taken again


def test_scan_of_the_mobile_open_time_page(tmp_path, monkeypatch):
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    page = _pot_page() + '<a href="/full/mobileopentimepot.cgi?BCID=008.152&amp;From=MainMenu">Close in Opentime</a>'
    assert W.close_in_scan(page, "mobile open time page") == "008.152"
    assert not W.S["close_in"].get("verified") and not W.S.get("close_in_bcid")  # a candidate until its page reads


def test_close_in_requests_join_the_decided_push(tmp_path, monkeypatch):
    from test_requests import _flow, _page, _recent
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    pages["text"] = _page("")
    read()  # the feature's first read is done
    W.S["close_in"] = {"bcid": "008.152", "verified": True}
    W.S["close_in_bcid"] = "008.152"
    pages["008.152"] = _page(f"{_recent(W, 40)} add approved h3500 {_recent(W, 1)} swap denied drop h3629 add h3627")
    read()
    ev = events()
    assert [(e["status"], e["bcid"], e.get("folder")) for e in ev] == [("Denied", "008.152", "close-in")]
    assert any(u.endswith("mobileotrequest.cgi?BCID=008.152&From=MainMenu") for u in fetched)
    assert all(SUB.safe_get(u) and SM.safe_get(u) for u in fetched)
    assert (tmp_path / "cap" / "otrequests_closein_152.html").exists()
    assert sensor()[-1]["requests"][-1]["folder"] == "close-in"
    pages["008.152"] = pages["008.152"].replace("add approved h3500", "add approved h3500 "
                                                f"{_recent(W, 0.5)} add approved h3630")
    read()
    assert [e["status"] for e in events()] == ["Denied", "Approved"]  # after its first read, every new decision
    tb = [u for u in fetched if "TB_MyRequests" in u]
    assert tb and all("bcid=001.152" in u for u in tb)  # Tradeboard trades: regular bid periods only


# ---------------------------------------------------------------- review: moves between folders, load, stop pages
def _checks(W, monkeypatch):
    """check() with everything but the pot reads and the close-in read stubbed out."""
    for f in ("schedule_check", "own_trip_times", "versions_check", "uploads_check", "capture", "detail_probe",
              "email_check", "pickup_check", "publish_finds", "tradeboard_check", "requests_check", "grid_check",
              "swap_scan", "drop_scan", "publish_tickets"):
        monkeypatch.setattr(W, f, lambda *a, **k: None)
    monkeypatch.setattr(W, "crew_index_check", lambda fl: "ok")
    for k, v in json.loads(json.dumps(W.DEFAULT_STATE)).items():
        W.S.setdefault(k, v)


def _find(W, k):
    r = W.DB.db.execute("SELECT month, first_seen, gone_at FROM finds WHERE key=?", (k,)).fetchone()
    return dict(zip(("month", "first_seen", "gone_at"), r)) if r else None


def test_a_trip_moving_into_the_close_in_folder_is_the_same_find(tmp_path, monkeypatch):
    """FLICA moves H3627 from the regular pot to the close-in folder (16 h to report): no second new_pairing push, its
    find keeps its first_seen (pickup speed) and stays open, and no pickup check is queued (it would read the seat
    still Open and push 'hidden by scheduling'). Once it leaves the close-in folder, its pickup is checked."""
    import store
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    _checks(W, monkeypatch)
    clock = iter(f"2026-11-07T0{h}:00:00+00:00" for h in range(1, 10))
    monkeypatch.setattr(store, "now_iso", lambda: next(clock))
    pages["003.152"] = _pot_page([("H3628", "07Nov")])
    assert W.check(fl) == "ok"  # both baselines
    pages["003.152"] = _pot_page([("H3628", "07Nov"), ("H3627", "07Nov")])
    assert W.check(fl) == "ok"
    assert [e["pairing"] for e in events("new_pairing")] == ["H3627"]
    first = _find(W, "H3627|07Nov")["first_seen"]
    pages["003.152"] = _pot_page([("H3628", "07Nov")])
    pages["008.152"] = _pot_page([("H3627", "07Nov")])
    assert W.check(fl) == "ok"
    assert [e["pairing"] for e in events("new_pairing")] == ["H3627"]  # moved, not new
    f = _find(W, "H3627|07Nov")
    assert (f["month"], f["first_seen"], f["gone_at"]) == ("closein", first, None)
    assert "H3627|07Nov" not in W.S.get("pickup_pending", {})
    pot = [json.loads(p) for tp, p, _ in W.MQ.msgs if tp == "flight_watcher/pot/state"][-1]["pairings"]
    assert (pot[0]["pairing"], pot[0].get("src"), pot[0].get("folder")) == ("H3627", "C", "close-in")
    assert all("far_why" not in r for r in pot)
    pages["008.152"] = _pot_page([])
    assert W.check(fl) == "ok"  # taken from the close-in folder: now its pickup is checked
    assert "H3627|07Nov" in W.S["pickup_pending"] and _find(W, "H3627|07Nov")["gone_at"]
    assert len(events("new_pairing")) == 1


def test_hunting_reads_the_close_in_page_once_a_minute(tmp_path, monkeypatch):
    """FW-0035 (hunt load stays about 376 FLICA loads an hour): hunting, the close-in page is read at most once every
    CLOSE_IN_READ_S; between reads its last rows are kept on the pot. Check now reads it at once."""
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    now = [1_000_000.0]
    monkeypatch.setattr(W.time, "time", lambda: now[0])
    W.FLAGS["hunt"] = True
    ci_url = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=008.152&From=MainMenu"
    pages["008.152"] = _pot_page([("H3627", "07Nov")])
    rows, _ = W.close_in_check(fl, {"mobile": {}})
    assert list(rows) == ["H3627|07Nov"] and fetched.count(ci_url) == 1
    n = len(fetched)
    now[0] += 30
    rows, kind = W.close_in_check(fl, {"mobile": {}})
    assert list(rows) == ["H3627|07Nov"] and kind == "ok" and len(fetched) == n  # no page load
    rows, _ = W.close_in_check(fl, {"mobile": {"H3627|07Nov": {"pairing": "H3627"}}})
    assert rows == {}  # a regular pot has it now
    now[0] += W.CLOSE_IN_READ_S
    W.close_in_check(fl, {"mobile": {}})
    assert fetched.count(ci_url) == 2
    W.close_in_check(fl, {"mobile": {}}, full=True)
    assert fetched.count(ci_url) == 3
    W.FLAGS["hunt"] = False  # not hunting: every check
    W.close_in_check(fl, {"mobile": {}})
    assert fetched.count(ci_url) == 4
    assert len(waits) >= 4 and all(1.5 <= w <= 3.5 for w in waits)


def test_a_stop_page_on_the_close_in_read_ends_the_pass(tmp_path, monkeypatch):
    """A captcha on the close-in page stops the Watcher, as on the pot; a session taken over elsewhere yields; an
    expired one logs in again. The checks after it in the same pass do not run."""
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    _checks(W, monkeypatch)
    ran = []
    monkeypatch.setattr(W, "tradeboard_check", lambda *a, **k: ran.append(1))
    pages["003.152"] = _pot_page([("H3628", "07Nov")])
    assert W.check(fl) == "ok" and ran == [1]
    pages["008.152"] = "<html><body>Please enter the verification code</body></html>"
    assert W.check(fl) == "stop" and ran == [1]
    assert W.S["machine"] == "stopped_unexpected" and "close-in" in W.S["note"]
    pages["008.152"] = "<html><body>A new session under this account was detected</body></html>"
    assert W.check(fl) == "killed"
    pages["008.152"] = "<html><body>Your session has expired</body></html>"
    assert W.check(fl) == "needs_login" and ran == [1]


def test_a_stop_page_on_the_menu_read_skips_the_close_in_page(tmp_path, monkeypatch):
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch)
    pages["leftmenu"] = "<html><body>A new session under this account was detected</body></html>"
    assert W.close_in_check(fl, {"mobile": {}}) == ({}, "killed")
    assert not any("008.152" in u for u in fetched) and not framed


TRADE_MENU = MENU_HTML.replace("</body>", '<b>Crew Trades</b><div>November</div>'
                               '<a href="/online/crewtrades.cgi?BCID=011.152&amp;token=Ab12">View</a></body>')


def test_menu_reads_name_the_trades_page_without_following_it(tmp_path, monkeypatch):
    """FW-0064: the menu read that looks for the close-in folder also looks for a crew-to-crew trades page. Found, it
    is logged and kept in state (token masked) and the menu is kept privately; it is never fetched. Tradeboard
    entries are not it."""
    W, fl, pages, fetched, framed, waits, events = _w(tmp_path, monkeypatch, menu=TRADE_MENU)
    W.close_in_check(fl, {"mobile": {}})
    tp = W.S["trade_pages"]
    assert tp["found"] == [{"text": "Crew Trades: View", "url": "/online/crewtrades.cgi?BCID=011.152&token=MASKED"}]
    assert tp["via"] == "left menu" and not any("crewtrades" in u for u in fetched)
    kept = (tmp_path / "cap" / "menu_trades.html").read_text()
    assert "Crew Trades" in kept and "Ab12" not in kept
    assert P.trade_pages(MENU_HTML) == [] and P.trade_pages(MENU_JS) == []

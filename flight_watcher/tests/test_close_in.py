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
    rows = W.close_in_check(fl, {"mobile": {}})
    ci = W.S["close_in"]
    assert ci["bcid"] == "008.152" and ci["verified"] and W.S["close_in_bcid"] == "008.152"
    assert rows == {} and events("new_pairing") == []  # first read: baseline, no alert
    assert fetched[-1] == "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=008.152&From=MainMenu"
    assert not framed  # the plain left menu named it
    assert all(SUB.safe_get(u) and SM.safe_get(u) for u in fetched)
    assert len(waits) == len(fetched) and all(1.5 <= w <= 3.5 for w in waits)  # every page load paced
    # a new close-in trip pushes like a pot find; one also in the regular pot does not
    pages["008.152"] = _pot_page([("H3627", "07Nov"), ("H3628", "07Nov")])
    reg = {"mobile": {"H3628|07Nov": {"pairing": "H3628", "start": "07Nov"}}}
    rows = W.close_in_check(fl, reg)
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
    assert W.close_in_check(fl, {"mobile": {}}) == {}
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

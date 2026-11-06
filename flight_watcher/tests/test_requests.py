"""1.2.0: Open Time Requests decisions -> event/request_decided. Synthetic pages only."""
import json

import pytest

import submit as SUB

PAGE_TEXT = ("open time requests 11/02 18:41 swap approved drop h3601 26nov add h3620 28nov "
             "11/05 09:10 swap pending drop h3629 12nov add h3815b 14nov 11/05 09:10 swap denied drop h3612 03dec")


def test_parse_rows_with_trips_and_keys():
    rows = SUB.parse_request_rows(PAGE_TEXT)
    assert [(r["key"], r["status"]) for r in rows] == [
        ("11/02|18:41|Swap|H3601+H3620|1", "Approved"), ("11/05|09:10|Swap|H3629+H3815B|1", "Pending"),
        ("11/05|09:10|Swap|H3612|1", "Denied")]
    assert rows[0]["trips"] == ["H3601", "H3620"] and rows[1]["trips"] == ["H3629", "H3815B"]
    assert "h3612" in rows[2]["detail"]


def test_clearing_one_request_keeps_the_other_keys():
    before = {r["status"]: r["key"] for r in SUB.parse_request_rows(PAGE_TEXT)}
    after = SUB.parse_request_rows(PAGE_TEXT.replace("11/02 18:41 swap approved drop h3601 26nov add h3620 28nov ", ""))
    assert {r["status"]: r["key"] for r in after} == {k: v for k, v in before.items() if k != "Approved"}
    same = SUB.parse_request_rows("11/05 09:10 add denied h3700 11/05 09:10 add denied h3700")
    assert [r["key"] for r in same] == ["11/05|09:10|Add|H3700|1", "11/05|09:10|Add|H3700|2"]


def test_news_once_per_decision():
    rows = SUB.parse_request_rows(PAGE_TEXT)
    assert [r["status"] for r in SUB.request_news({}, rows)] == ["Approved", "Denied"]
    pushed = {SUB.push_key(r): "x" for r in rows if r["status"] in SUB.DECIDED}
    assert SUB.request_news(pushed, rows) == []
    rows2 = SUB.parse_request_rows(PAGE_TEXT.replace("swap pending", "swap approved"))
    assert [r["key"] for r in SUB.request_news(pushed, rows2)] == ["11/05|09:10|Swap|H3629+H3815B|1"]


def test_is_request_page():
    assert SUB.is_request_page("Open Time Requests (none)", [])
    assert not SUB.is_request_page("Service Temporarily Unavailable", [])
    assert not SUB.is_request_page("", [])
    assert SUB.is_request_page("x", SUB.parse_request_rows(PAGE_TEXT))


def test_requests_url_is_safe():
    u = SUB.requests_url("https://ha2.flica.net", "003.152")
    assert u == "https://ha2.flica.net/full/mobileotrequest.cgi?BCID=003.152&From=MainMenu"
    assert SUB.safe_get(u)
    assert not SUB.safe_get(u + "&QuickDelete=1")


def _flow(tmp_path, monkeypatch):
    from test_instance import FakeClient, _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info",
                                          "category_check": "HNL 332 FO"})
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "cap"))
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    W.S["pot_urls"] = {"2026-11": "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"}
    pages, fetched = {}, []

    class FL:
        def fetch(self, url):
            fetched.append(url)
            return pages.get(url.split("BCID=")[1].split("&")[0], pages.get("text"))

    def read(force=True):
        W.S["req_force"] = force
        W.requests_check(FL())
    events = lambda: [json.loads(p) for t, p, _ in fake.msgs if t == "flight_watcher/event/request_decided"]
    sensor = lambda: [json.loads(p) for t, p, _ in fake.msgs if t == "flight_watcher/ot_requests"]
    return W, pages, fetched, read, events, sensor


def _page(body):
    return f"<html><body>open time requests {body}</body></html>"


def _recent(W, hours_ago):
    from datetime import datetime, timedelta
    t = datetime.now(W.HST) - timedelta(hours=hours_ago)
    return t.strftime("%m/%d %H:%M")


def test_requests_check_flow(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    old = _recent(W, 30)
    pages["text"] = _page(f"{old} swap denied drop h3600 add h3601 {_recent(W, 1)} swap pending drop h3629 add h3815b")
    W.requests_check(type("FL", (), {"fetch": lambda self, u: (fetched.append(u), pages["text"])[1]})())
    # first read ever: the 30 h old decision is history (no push); the page is captured privately
    assert events() == [] and (tmp_path / "cap" / "otrequests_152.html").exists()
    assert all("QuickDelete" not in u for u in fetched) and fetched[0].endswith("BCID=003.152&From=MainMenu")
    assert sensor()[-1]["pending"] == 1
    read(force=False)  # inside the pending gap: no fetch
    assert len(fetched) == 1
    pages["text"] = pages["text"].replace("swap pending", "swap approved")
    read()
    ev = events()
    assert len(ev) == 1 and ev[0]["status"] == "Approved" and ev[0]["trips"] == ["H3629", "H3815B"]
    assert sensor()[-1]["pending"] == 0 and sensor()[-1]["count"] == 2
    read()  # same page again: no second push
    assert len(fetched) == 3 and len(events()) == 1


def test_first_read_pushes_a_decision_filed_in_the_last_hours(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    pages["text"] = _page(f"{_recent(W, 2)} swap denied drop h3629 add h3628")
    read()
    assert [e["status"] for e in events()] == ["Denied"]


def test_error_page_and_empty_read_never_repush_or_zero_the_sensor(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    good = _page(f"{_recent(W, 1)} swap approved drop h3629 add h3628 {_recent(W, 1)} add pending h3700")
    pages["text"] = good
    read()
    assert len(events()) == 1 and len(sensor()) == 1
    for bad in ("<html><body>Service Temporarily Unavailable</body></html>", ""):
        pages["text"] = bad
        read()
        assert len(sensor()) == 1  # a failed pass publishes nothing: the sensor keeps 1 pending
    pages["text"] = _page("")  # a list gone empty is believed only on the second read
    read()
    assert len(sensor()) == 1 and W.S["ot_req_rows"]["003.152"]
    pages["text"] = good
    read()
    assert len(events()) == 1  # back again: the decision is not pushed twice
    pages["text"] = _page("")
    read()
    read()
    assert sensor()[-1]["count"] == 0 and len(events()) == 1


def test_new_folder_after_first_read_pushes_its_decisions(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    pages["text"] = _page("")
    read()
    W.S["pot_urls"]["2026-12"] = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    pages["003.153"] = _page(f"{_recent(W, 40)} swap approved drop h3629 add h3628")
    read()
    assert [(e["status"], e["bcid"]) for e in events()] == [("Approved", "003.153")]


def test_pending_in_an_unwatched_folder_does_not_hold_the_fast_poll(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    pages["text"] = _page(f"{_recent(W, 1)} add pending h3700")
    read()
    W.S["pot_urls"] = {"2026-12": "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"}
    pages["text"] = _page("")
    read()
    assert "003.152" not in W.S["ot_req_rows"]
    n = len(fetched)
    W.S["req_checked_at"] = W.time.time() - 300  # past the 2-min pending gap, inside the 15-min idle gap
    read(force=False)
    assert len(fetched) == n


def test_reads_are_paced(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    waits = []
    monkeypatch.setattr(W.time, "sleep", waits.append)
    W.S["pot_urls"]["2026-12"] = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    pages["text"] = _page("")
    read()
    assert len(waits) == 2 and all(1.5 <= w <= 3.5 for w in waits)


def _html(rows):
    """Synthetic list page shaped like FLICA's (made-up ids): each row a ShowRequest link and a QuickDelete link."""
    out = ["<html><body><strong>Nov 2026 OPEN TIME- Add/Swap/Drop requests Requests</strong><table>"
           "<tr><td>Date</td><td>Time</td><td>Request</td><td>Status</td></tr>"]
    for d, t, k, st, ts in rows:
        out.append(f'<tr><td>{d}</td><td>{t}</td><td><a href="/full/mobileotrequest.cgi?ShowRequest=1&TimeStamp={ts}">'
                   f'{k}</a></td><td><a href="/full/mobileotrequest.cgi?TimeStamp={ts}&Type={k}&status={st}'
                   f'&QuickDelete=1">{st}</a></td></tr>')
    out.append("</table>Pending requests are listed by creation date.</body></html>")
    return "".join(out)


def test_rows_keyed_on_flica_id_and_cleared_rows_do_not_renumber():
    from pot import visible_text
    rows = [("10/31", "11:17", "Swap", "Approved", "0000AAAA:00000001"), ("10/31", "11:17", "Swap", "Denied", "0000AAAA:00000002")]
    h = _html(rows)
    got = SUB.parse_request_rows(visible_text(h), h)
    assert [(r["key"], r["status"], r["detail"], r["trips"]) for r in got] == [
        ("ts:0000AAAA:00000001", "Approved", "", []), ("ts:0000AAAA:00000002", "Denied", "", [])]
    assert got[0]["alt"] == "10/31|11:17|Swap||1"
    h2 = _html(rows[1:])
    assert [r["key"] for r in SUB.parse_request_rows(visible_text(h2), h2)] == ["ts:0000AAAA:00000002"]
    pushed = {"10/31|11:17|Swap||2|Denied": "x"}  # pushed by 1.2.1 under the content key: not pushed again
    assert [r["status"] for r in SUB.request_news(pushed, got)] == ["Approved"]


def test_view_url_is_safe_and_view_parsed():
    import swapmap as SM
    u = SUB.request_view_url("https://ha2.flica.net", "003.152", "0000AAAA:00000001")
    assert u == ("https://ha2.flica.net/full/mobileotrequest.cgi?ShowRequest=1&TimeStamp=0000AAAA:00000001"
                 "&BCID=003.152&From=Self&Parent=MainMenu")
    assert SUB.safe_get(u) and SM.safe_get(u)
    v = SUB.parse_request_view("swap request status: approved drop h3629:14nov add h3628:13nov comments none")
    assert v["trips"] == ["H3629", "H3628"] and [x["side"] for x in v["legs"]] == ["drop", "add"]
    assert v["detail"].startswith("swap request status") and SUB.parse_request_view("nothing here")["trips"] == []


def test_decided_request_reads_its_view_page_for_trips(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    rid = "0000BBBB:00000003"
    pages["text"] = _html([(*_recent(W, 1).split(), "Swap", "Pending", rid)])
    read()
    assert events() == [] and any("ShowRequest=1" in u for u in fetched)  # one view page captured once
    assert (tmp_path / "cap" / "otrequest_view_152.html").exists()
    views = []

    class FL:
        def fetch(self, url):
            fetched.append(url)
            if "ShowRequest=1" in url:
                views.append(url)
                return "<html><body>Swap request: drop H3629:14NOV add H3628:13NOV</body></html>"
            return pages["text"].replace("Pending", "Approved")
    W.S["req_force"] = True
    W.requests_check(FL())
    ev = events()
    assert len(ev) == 1 and ev[0]["trips"] == ["H3629", "H3628"] and ev[0]["key"] == f"ts:{rid}"
    assert [x["side"] for x in ev[0]["legs"]] == ["drop", "add"] and "h3628" in ev[0]["detail"]
    assert len(views) == 1 and all("QuickDelete" not in u for u in fetched)
    W.S["req_force"] = True
    W.requests_check(FL())
    assert len(events()) == 1 and len(views) == 1


def test_fallback_to_content_keys_never_repushes(tmp_path, monkeypatch):
    W, pages, fetched, read, events, sensor = _flow(tmp_path, monkeypatch)
    d, t = _recent(W, 1).split()
    pages["text"] = _html([(d, t, "Swap", "Approved", "0000BBBB:00000003")])
    read()
    assert len(events()) == 1
    # a later list where ids and rows no longer pair up (a Pending row without its own link): content keys only
    extra = f"<tr><td>{d}</td><td>{t}</td><td>Add</td><td>Pending</td></tr></table>"
    pages["text"] = pages["text"].replace("</table>", extra, 1)
    read()
    assert len(events()) == 1


def test_view_labels_are_strict():
    from pot import visible_text
    head = "<strong>Nov 2026 OPEN TIME- Add/Swap/Drop requests</strong><p>Request Detail</p><p>Status: Approved</p>"
    v = SUB.parse_request_view(visible_text(head + "<table><tr><td>Trip</td><td>H3620</td><td>28NOV</td></tr></table>"))
    assert v["legs"] == [{"trip": "H3620", "day": "28NOV", "side": ""}]  # the header never labels a trip
    v = SUB.parse_request_view("type: swap from: doe, jane trip h3629 14nov to: h3628 13nov h3629 14nov")
    assert [x["side"] for x in v["legs"]] == ["", ""] and v["trips"] == ["H3629", "H3628"]  # no to/from, once each

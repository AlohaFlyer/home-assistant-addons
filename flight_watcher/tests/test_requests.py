"""1.2.0: Open Time Requests decisions -> event/request_decided. Synthetic pages only."""
import json

import pytest

import submit as SUB

PAGE_TEXT = ("open time requests 11/02 18:41 swap approved drop h3601 26nov add h3620 28nov "
             "11/05 09:10 swap pending drop h3629 12nov add h3815b 14nov 11/05 09:10 swap denied drop h3612 03dec")


def test_parse_rows_with_trips_and_keys():
    rows = SUB.parse_request_rows(PAGE_TEXT)
    assert [(r["key"], r["status"]) for r in rows] == [
        ("11/02|18:41|Swap|1", "Approved"), ("11/05|09:10|Swap|1", "Pending"), ("11/05|09:10|Swap|2", "Denied")]
    assert rows[0]["trips"] == ["H3601", "H3620"] and rows[1]["trips"] == ["H3629", "H3815B"]
    assert "h3612" in rows[2]["detail"]


def test_changes_only_on_decision_and_never_on_first_read():
    rows = SUB.parse_request_rows(PAGE_TEXT)
    assert SUB.request_changes(None, rows) == []
    old = {"11/02|18:41|Swap|1": "Approved", "11/05|09:10|Swap|1": "Pending"}
    got = SUB.request_changes(old, rows)
    assert [(r["key"], r["status"]) for r in got] == [("11/05|09:10|Swap|2", "Denied")]  # new and already decided
    old2 = {r["key"]: r["status"] for r in rows}
    rows2 = SUB.parse_request_rows(PAGE_TEXT.replace("swap pending", "swap approved"))
    assert [(r["key"], r["status"]) for r in SUB.request_changes(old2, rows2)] == [("11/05|09:10|Swap|1", "Approved")]
    assert SUB.request_changes(old2, rows) == []


def test_requests_url_is_safe():
    u = SUB.requests_url("https://ha2.flica.net", "003.152")
    assert u == "https://ha2.flica.net/full/mobileotrequest.cgi?BCID=003.152&From=MainMenu"
    assert SUB.safe_get(u)
    assert not SUB.safe_get(u + "&QuickDelete=1")


def test_requests_check_flow(tmp_path, monkeypatch):
    from test_instance import FakeClient, _load
    W = _load(tmp_path, monkeypatch, "", {"username": "u", "password": "p", "log_level": "info",
                                          "category_check": "HNL 332 FO"})
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "cap"))
    W.S["pot_urls"] = {"2026-11": "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"}
    pages = {"text": "<html><body>open time requests 11/05 09:10 swap pending drop h3629 add h3815b</body></html>"}
    fetched = []

    class FL:
        def fetch(self, url):
            fetched.append(url)
            return pages["text"]
    events = lambda: [json.loads(p) for t, p, _ in fake.msgs if t == "flight_watcher/event/request_decided"]
    W.requests_check(FL())  # first read: baseline, no push, page captured privately
    assert events() == [] and (tmp_path / "cap" / "otrequests_152.html").exists()
    assert all("QuickDelete" not in u for u in fetched) and fetched[0].endswith("BCID=003.152&From=MainMenu")
    W.requests_check(FL())  # inside the pending gap: no fetch
    assert len(fetched) == 1
    W.S["req_checked_at"] = 0
    pages["text"] = pages["text"].replace("swap pending", "swap approved")
    W.requests_check(FL())
    ev = events()
    assert len(ev) == 1 and ev[0]["status"] == "Approved" and ev[0]["trips"] == ["H3629", "H3815B"]
    st = json.loads([p for t, p, _ in fake.msgs if t == "flight_watcher/ot_requests"][-1])
    assert st["pending"] == 0 and st["count"] == 1
    W.S["req_force"] = True  # a yield sets this: read again at once, same state, no second push
    W.requests_check(FL())
    assert len(fetched) == 3 and len(events()) == 1

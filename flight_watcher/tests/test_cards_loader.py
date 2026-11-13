"""1.7.2: the card loader picks up a card a release added while a page stays open (Ryan, Nov 12, Sydney: the phone
app's Working Flight page said "Configuration error" because its page predated the 1.7.1 layover card), and tries a
card whose import failed again. Runs the real LOADER_JS in Chromium against a fake /local/."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cards  # noqa: E402

from test_cards import _chromium  # noqa: E402


def _card(tag):
    return f"customElements.define({json.dumps(tag)}, class extends HTMLElement {{}});"


def test_loader_text_rechecks_on_return_and_on_a_timer():
    js = cards.LOADER_JS
    assert cards.MANIFEST in js and "no-store" in js
    assert "visibilitychange" in js and "setInterval(load, 300000)" in js
    assert "done.delete(f)" in js and "&r=" in js  # a failed import is tried again under a new URL


def test_loader_imports_a_card_added_later_and_retries_a_failed_one():
    pw = pytest.importorskip("playwright.sync_api")
    state = {"cards": ["flight-watcher-a-card.js"], "c_ok": False}
    hits = []

    def route(r):
        u = r.request.url
        path = u.split("http://fw.test", 1)[1]
        hits.append(path)
        if path == "/":
            return r.fulfill(status=200, content_type="text/html",
                             body='<!doctype html><script type="module" src="/local/%s"></script>' % cards.LOADER)
        if path == "/local/" + cards.LOADER:
            return r.fulfill(status=200, content_type="text/javascript", body=cards.LOADER_JS)
        if path == "/local/" + cards.MANIFEST:
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"version": "9.9.9", "cards": state["cards"]}))
        if path.startswith("/local/flight-watcher-a-card.js"):
            return r.fulfill(status=200, content_type="text/javascript", body=_card("flight-watcher-a-card"))
        if path.startswith("/local/flight-watcher-b-card.js"):
            return r.fulfill(status=200, content_type="text/javascript", body=_card("flight-watcher-b-card"))
        if path.startswith("/local/flight-watcher-c-card.js"):
            if not state["c_ok"]:
                return r.fulfill(status=404, content_type="text/plain", body="not found")
            return r.fulfill(status=200, content_type="text/javascript", body=_card("flight-watcher-c-card"))
        return r.fulfill(status=404, body="")

    defined = "(t) => !!customElements.get(t)"
    back = "() => document.dispatchEvent(new Event('visibilitychange'))"
    with pw.sync_playwright() as p:
        b = _chromium(p)
        if b is None:
            pytest.skip("no Chromium")
        try:
            pg = b.new_page()
            pg.route("http://fw.test/**", route)
            pg.goto("http://fw.test/")
            pg.wait_for_function(defined, arg="flight-watcher-a-card", timeout=5000)
            assert not pg.evaluate(defined, "flight-watcher-b-card")
            # a release adds two cards; one of them fails to load the first time
            state["cards"] = ["flight-watcher-a-card.js", "flight-watcher-b-card.js", "flight-watcher-c-card.js"]
            pg.evaluate(back)
            pg.wait_for_function(defined, arg="flight-watcher-b-card", timeout=5000)
            pg.wait_for_timeout(300)
            assert not pg.evaluate(defined, "flight-watcher-c-card")
            state["c_ok"] = True
            pg.evaluate(back)
            pg.wait_for_function(defined, arg="flight-watcher-c-card", timeout=5000)
        finally:
            b.close()
    a = [h for h in hits if h.startswith("/local/flight-watcher-a-card.js")]
    c = [h for h in hits if h.startswith("/local/flight-watcher-c-card.js")]
    assert a == ["/local/flight-watcher-a-card.js?v=9.9.9"]  # a card already imported is not imported again
    assert c == ["/local/flight-watcher-c-card.js?v=9.9.9", "/local/flight-watcher-c-card.js?v=9.9.9&r=2"]

"""1.8.0: the FLICA mirror (ingress page flica). FLICA allows one session per login and the Watcher owns it, so the
mirror shows FLICA's mobile pages through the Watcher's own session: the ingress thread asks, the main loop loads
(through the gate) while it waits between checks. Read only: only the pot, pairing and own schedule pages, never a
request link, forms disabled, FLICA's scripts removed. Synthetic pages only; FLICA is never reached."""
import threading

import pytest

import mirror as MR
from test_release_a_flica import mk, real_fl  # noqa: F401

F = "https://ha2.flica.net"
POT = F + "/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
PAIR = F + "/full/mobilepairing.cgi?PID=H3676&DATE=20261126&FROM=MobileOpentimePot&CurrentPage=1"

POT_HTML = """<html><head><meta http-equiv="refresh" content="5"><title>FLICA.Net - Mobile Opentime</title>
<link rel="stylesheet" href="/styles/mobileheader.css" /><script src="/public/jserror.js"></script></head>
<body onload="go()"><a href="javascript:history.back()" class="sabreHeaderBackIcon">Back</a>
<a href="/online/mainmenu.cgi?&Junk=1">Menu</a> Open Time
<table><tr><td><a href="/full/mobilepairing.cgi?PID=H3676&DATE=20261126&FROM=MobileOpentimePot&CurrentPage=1">H3676</a>
</td><td>26NOV</td></tr></table>
<a href="/full/mobileotrequest.cgi?BCID=003.152&CreateRequest=1&From=MainMenu">Requests</a>
<a href="javascript:doSomething()">JS</a><a href="https://example.com/help">Help</a>
<form action="/full/mobileotrequest.cgi" method="post"><input name="PID" value="H3676"><input type="submit" value="Add">
</form><script>alert(1)</script><img src="/images/logo.gif" onerror="x()"></body></html>"""


# ------------------------------------------------------------------ pure: which pages the mirror loads
@pytest.mark.parametrize("url,kind", [
    (POT, "pot"),
    (PAIR, "pairing"),
    (F + "/full/mobileschedule.cgi?BlockDate=1126&From=MainMenu", "schedule"),
    (F + "/full/mobileopentimepot.cgi?CurrentPage=1&From=Self&XDisp=1", "pot"),
])
def test_read_pages_are_loaded(url, kind):
    assert MR.page_kind(url) == kind


@pytest.mark.parametrize("url", [
    F + "/full/mobileotrequest.cgi?BCID=003.152&CreateRequest=1&From=MainMenu",  # requests
    F + "/full/mobileschedule.cgi?BCID=001.152&Priority=1&From=MobileOTDrop",  # the drop flow's schedule
    F + "/full/mobileschedule.cgi?BCID=001.152&From=MobileOTSwap&BlockDate=1126",  # the swap flow
    F + "/full/mobilepairing.cgi?PID=H3676&Add=1",
    F + "/full/mobileopentimepot.cgi?BCID=003.152&Submit=Yes",
    F + "/online/mainmenu.cgi",  # behind reCAPTCHA
    F + "/online/tb_frame.cgi?BCID=001.152&dp=mr",  # Tradeboard (requests live there)
    F + "/full/scheduledetail.cgi",  # FLICA answers it with a reCAPTCHA page
    F + "/full/mobileschedule.cgi?From=MainMenu",  # no BlockDate
    "http://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152",  # not https
    "https://evil.example/full/mobileopentimepot.cgi?BCID=003.152",
    "https://user@ha2.flica.net/full/mobileopentimepot.cgi",
    "https://ha2.flica.net:8443/full/mobileopentimepot.cgi",
    "",
])
def test_anything_else_is_never_loaded(url):
    assert MR.page_kind(url) == ""


@pytest.mark.parametrize("u,ok", [
    ("/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu", True),
    ("//evil.example/full/mobileopentimepot.cgi", False),
    ("https://evil.example/x", False),
    ("/full/mobileopentimepot.cgi?BCID=003.152 x", False),
    ("/full/mobileotrequest.cgi?CreateRequest=1", False),
    ("\\\\evil", False),
    ("/" + "a" * 500, False),
])
def test_mirror_u_maps_only_to_flica_read_pages(u, ok):
    assert bool(MR.flica_url(u)) is ok
    if ok:
        assert MR.flica_url(u).startswith(F + "/full/")


def test_rewrite_keeps_reads_in_the_mirror_and_drops_everything_else():
    body, head, title = MR.rewrite(POT_HTML, POT)
    assert title == "FLICA.Net - Mobile Opentime"
    assert "<script" not in body.lower() and "alert(" not in body and "onload" not in body and "onerror" not in body
    assert "refresh" not in body.lower()
    # the pairing link stays in the mirror
    assert MR.mirror_href(PAIR) in body.replace("&amp;", "&")
    # the request link and the main menu are plain text, never a link to FLICA (that would kick the Watcher)
    assert "mobileotrequest" not in body and "mainmenu" not in body and "doSomething" not in body
    assert "Requests" in body and "Menu" in body
    assert 'href="javascript:history.back()"' in body
    assert 'href="https://example.com/help"' in body and "noopener" in body
    # the form is disabled and posts nowhere
    assert 'action="#"' in body and body.count('disabled="disabled"') == 2
    # stylesheets and pictures load from FLICA by their full address
    assert 'href="https://ha2.flica.net/styles/mobileheader.css"' in head
    assert 'src="https://ha2.flica.net/images/logo.gif"' in body


def test_page_has_a_bar_and_a_visible_only_refresh_timer():
    out = MR.page("<p>x</p>", "", "T", [("Open time", POT), ("Pair", PAIR)], POT, 1_800_000_000, version="1.8.0")
    assert "flica?u=%2Ffull%2Fmobileopentimepot.cgi%3FBCID%3D003.152%26From%3DMainMenu" in out
    assert "class='on'" in out and "visibilityState" in out and "location.reload" in out
    assert "localStorage" in out and "try {" in out


# ------------------------------------------------------------------ through the Watcher: one session, the gate
def _ask(W, u):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", W.mirror_get(u)))
    t.start()
    for _ in range(400):
        if W.MIRROR["q"] or not t.is_alive():
            break
        threading.Event().wait(0.005)
    W.mirror_serve()
    t.join(5)
    return out["r"]


def _live(W, fl):
    W.set_machine("idle", "")
    W.S["last_login_ok"] = "2026-11-23T00:00:00+00:00"
    W.S["pot_urls"] = {"mobile": POT}
    W.MIRROR.update(fl=fl, thread=threading.current_thread(), q=[], cache={}, held={})


def test_a_page_is_loaded_once_through_the_watchers_session_and_kept(mk):
    W = mk()
    fl = real_fl(W, lambda url: POT_HTML)
    _live(W, fl)
    code, html = _ask(W, "")
    assert code == 200 and "H3676" in html and [u for _, u in fl.loads] == [POT]
    code, html = W.mirror_get("")  # a copy under a minute old: no second FLICA load
    assert code == 200 and len(fl.loads) == 1
    W.CLOCK.t += 120
    _ask(W, "")
    assert len(fl.loads) == 2


def test_the_watchers_own_pot_read_feeds_the_mirror(mk):
    W = mk()
    fl = real_fl(W, lambda url: POT_HTML)
    _live(W, fl)
    fl.fetch(POT)
    n = len(fl.loads)
    code, html = W.mirror_get("")
    assert code == 200 and "H3676" in html and len(fl.loads) == n


@pytest.mark.parametrize("setup,word", [
    (lambda W: W.FLAGS.update(pause=True), "paused"),
    (lambda W: (W.set_machine("yielded", ""), W.S.update(yield_until=W.CLOCK.t + 600)), "stepped aside"),
    (lambda W: W.set_machine("stopped_login_failed", ""), "not signed in"),
])
def test_no_load_while_the_watcher_is_paused_yielded_or_stopped(mk, setup, word):
    W = mk()
    fl = real_fl(W, lambda url: POT_HTML)
    _live(W, fl)
    setup(W)
    try:
        code, html = W.mirror_get("")
        assert code == 200 and word in html and fl.loads == []
    finally:
        W.FLAGS["pause"] = False


def test_a_captcha_is_never_answered_and_holds_that_page(mk):
    W = mk()
    fl = real_fl(W, lambda url: '<html><body><div class="g-recaptcha"></div><script src="https://www.google.com/'
                                'recaptcha/api.js"></script></body></html>')
    _live(W, fl)
    code, html = _ask(W, "")
    assert "CAPTCHA" in html and len(fl.loads) == 1
    W.CLOCK.t += 120
    code, html = _ask(W, "")
    assert "CAPTCHA" in html and len(fl.loads) == 1  # held: not loaded again


def test_an_ended_session_wakes_the_loop_and_the_mirror_never_logs_in(mk):
    W = mk()
    fl = real_fl(W, lambda url: '<html><body><form><input type="password" name="pw"></form></body></html>')
    _live(W, fl)
    W.WAKE.clear()
    code, html = _ask(W, "")
    assert "session ended" in html and W.WAKE.is_set() and len(fl.loads) == 1


def test_a_refused_page_is_never_loaded(mk):
    W = mk()
    fl = real_fl(W, lambda url: POT_HTML)
    _live(W, fl)
    code, html = W.mirror_get("/full/mobileotrequest.cgi?BCID=003.152&CreateRequest=1&From=MainMenu")
    assert code == 403 and "read only" in html and fl.loads == [] and W.MIRROR["q"] == []


def test_only_the_main_thread_loads(mk):
    W = mk()
    fl = real_fl(W, lambda url: POT_HTML)
    _live(W, fl)
    W.MIRROR["q"].append({"url": POT, "ev": threading.Event(), "res": None, "at": W.CLOCK.t})
    t = threading.Thread(target=W.mirror_serve)
    t.start()
    t.join(5)
    assert fl.loads == [] and len(W.MIRROR["q"]) == 1


def test_mirror_links_name_the_pots_and_the_schedule(mk):
    W = mk()
    _live(W, real_fl(W, lambda url: ""))
    links = W.mirror_links()
    assert links[0] == ("Open time", POT)
    assert any(lbl == "My schedule" and MR.page_kind(u) == "schedule" for lbl, u in links)


def test_ingress_route_serves_the_mirror_only_from_ingress():
    import http.client
    import web

    class Log:
        def info(self, *a):
            pass

    seen = []
    srv = web.serve(0, "1.8.0", lambda: [], lambda d: [], None, Log(),
                    mirror_get=lambda u: (seen.append(u), (200, "<p>mirror ok</p>"))[1])
    try:
        port = srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/flica?u=%2Ffull%2Fmobileopentimepot.cgi%3FBCID%3D003.152")
        r = c.getresponse()
        body = r.read().decode()
        assert r.status == 200 and "mirror ok" in body and r.getheader("Cache-Control") == "no-store"
        assert seen == ["/full/mobileopentimepot.cgi?BCID=003.152"]
    finally:
        srv.shutdown()

"""1.0.1: the Web UI Settings form (credentials). Synthetic values only."""
import web


def test_form_never_shows_a_password():
    st = {"username": "doej", "my_name": "Doe", "ctweb_username": "12345", "has_password": True,
          "has_ctweb_password": False}
    f = web._settings_form(st)
    assert "value='doej'" in f and "value='Doe'" in f and "value='12345'" in f
    assert f.count("type='password'") == 2 and "set</b>" in f and "not set</b>" in f
    assert "action='settings'" in f


def test_form_escapes_values():
    f = web._settings_form({"username": "a'><script>"})
    assert "<script>" not in f and "&#x27;" in f


def test_parse_keeps_only_filled_known_fields():
    d = web.parse_settings("username=+doej+&password=&ctweb_username=&ctweb_password=s3cr%26t&my_name=Doe&bogus=x")
    assert d == {"username": "doej", "ctweb_password": "s3cr&t", "my_name": "Doe"}
    assert web.parse_settings("password=&username=") == {}


def test_settings_post_end_to_end():
    """POST /settings on a live server: the callback gets the filled fields; the reply never echoes a password."""
    import logging
    import socket
    import urllib.request

    class Store:
        def recent_finds(self, n):
            return []

        def recent_matches(self, n):
            return []

    saved = []
    state = {"username": "doej", "has_password": False}
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    cleared = []
    srv = web.serve(port, "9.9.9", lambda: [], lambda d: [], Store(), logging.getLogger("t"),
                    get_settings=lambda: state, save_settings=lambda d: saved.append(d) or True,
                    clear_settings=lambda: cleared.append(1) or True)
    try:
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert page.index('id="settings"') < page.index('id="pdfs"') and "value='doej'" in page
        body = b"username=doej&password=Secr3t-pw&ctweb_username=&ctweb_password=&my_name="
        reply = urllib.request.urlopen(f"http://127.0.0.1:{port}/settings", data=body).read().decode()
        assert saved == [{"username": "doej", "password": "Secr3t-pw"}]
        assert "Saved." in reply and "Secr3t-pw" not in reply
        reply = urllib.request.urlopen(f"http://127.0.0.1:{port}/settings", data=b"username=&password=").read().decode()
        assert "every field was blank" in reply and len(saved) == 1
        reply = urllib.request.urlopen(f"http://127.0.0.1:{port}/settings", data=b"clear=1").read().decode()
        assert "Saved values cleared" in reply and cleared == [1] and len(saved) == 1
    finally:
        srv.shutdown()


def test_portal_key_shown_only_when_a_pilot_has_a_portal():
    """1.6.0 (FW-0061): the Web UI shows the portal signing key's public half for HOM's fw_signing_key option; with no
    portal the page is exactly as in 1.5.0."""
    import logging
    import socket
    import urllib.request

    class Store:
        def recent_finds(self, n):
            return []

        def recent_matches(self, n):
            return []

    assert web.portal_section("") == ""
    key = "ed25519:" + "Ab_-" * 10 + "xyz"
    s = web.portal_section(key)
    assert key in s and "fw_signing_key" in s and "Pilot portal" in s
    assert "&lt;b&gt;" in web.portal_section("<b>")
    pages = {}
    for k in ("", key):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        srv = web.serve(port, "9.9.9", lambda: [], lambda d: [], Store(), logging.getLogger("t"), portal_key=k)
        try:
            pages[k] = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        finally:
            srv.shutdown()
    assert "Pilot portal" not in pages[""] and "ed25519:" not in pages[""]
    assert pages[key].replace(web.portal_section(key), "") == pages[""]  # the only difference

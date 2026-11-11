"""FW-0071 (Ryan): paste a screenshot into a new ticket in Chrome on a Mac, and on iOS. In a real Chromium: a paste event
carrying a PNG File in a DataTransfer, dispatched on a field inside the card's shadow root (not composed, so the 1.7.0
document listener never heard it), on the form itself and on the paste box, adds the picture through the same shrink
and photo limit as Add photos; a composed paste heard by both the shadow root and the document adds it once; a picture
dropped on the form is added; the Paste photo button reads a stubbed navigator.clipboard.read, and a refusal or an
empty clipboard says so. The portal copy (FW_PORTAL) does the same with no blob: URL. Made-up data only; screenshots
of the open form at 390 px and 1100 px, light and dark, go to the pytest tmp folder."""
import json
import os

import pytest

import portal
from test_cards import _chromium

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(HERE, "www", "flight-watcher-tickets-card.js"), encoding="utf-8").read()

DARK = ("--primary-color:#03a9f4;--secondary-text-color:#9b9b9b;--divider-color:rgba(255,255,255,.12);"
        "--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;background:#111;color:#e1e1e1")
LIGHT = ("--primary-color:#03a9f4;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);"
         "--card-background-color:#fff;--primary-text-color:#212121;background:#f4f4f4;color:#212121")


def _page(src, theme=LIGHT, clip=""):
    """The card on a page with a stub hass (no photos limit: 10 on HA, 3 in the portal). clip: script run first (a
    navigator.clipboard stub)."""
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<style>body{{margin:0;padding:8px 16px;font-family:Roboto,sans-serif;{theme}}}</style></head><body><script>"
            "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML ="
            " '<style>:host{display:block;background:var(--card-background-color);border-radius:12px;padding:0}</style><slot></slot>'; } });"
            "window.calls = []; window.blobUrls = 0; const _cou = URL.createObjectURL.bind(URL);"
            "URL.createObjectURL = (b) => { window.blobUrls++; return _cou(b); };" + clip + "</script><script>" + src + "</script><script>"
            "const c = document.createElement('flight-watcher-tickets-card'); c.setConfig({}); document.body.appendChild(c);"
            "c.hass = {states: {'sensor.flight_watcher_tickets': {last_updated: 'a', attributes: {tickets: []}},"
            " 'sensor.flight_watcher_state': {attributes: {version: '9.9.9'}}}, callService: async (d, s, data) => { window.calls.push([d, s, data]); }};"
            "window.png = (w, h) => new Promise((res) => { const cv = document.createElement('canvas'); cv.width = w; cv.height = h;"
            " const g = cv.getContext('2d'); g.fillStyle = '#c62828'; g.fillRect(0, 0, w / 2, h / 2); g.fillStyle = '#1976d2'; g.fillRect(w / 2, h / 2, w / 2, h / 2);"
            " cv.toBlob(res, 'image/png'); });"
            "window.dt = async () => { const d = new DataTransfer(); d.items.add(new File([await window.png(1600, 1000)], 'Screenshot.png', {type: 'image/png'})); return d; };"
            "window.root = () => document.querySelector('flight-watcher-tickets-card').shadowRoot;"
            "window.nph = () => window.root().querySelectorAll('.ph img').length;"
            "</script></body></html>")


CLIP_OK = ("Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {read: async () => {"
           " window.reads = (window.reads || 0) + 1; const b = await window.png(800, 600);"
           " return [{types: ['text/plain'], getType: async () => new Blob(['x'])}, {types: ['image/png'], getType: async () => b}]; }}});")
CLIP_DENY = ("Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {read: async () => {"
             " throw new DOMException('denied', 'NotAllowedError'); }}});")
CLIP_TEXT = ("Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {read: async () =>"
             " [{types: ['text/plain'], getType: async () => new Blob(['hello'], {type: 'text/plain'})}]}});")


def _open(pg):
    card = pg.locator("flight-watcher-tickets-card")
    card.locator("[data-new]").click()
    return card


def _paste_into(pg, sel, composed=False):
    """Dispatch a paste with a PNG File on sel (inside the shadow root); returns defaultPrevented."""
    return pg.evaluate("""async ([sel, composed]) => {
        const el = sel === 'document' ? document.body : window.root().querySelector(sel);
        const ev = new ClipboardEvent('paste', {clipboardData: await window.dt(), bubbles: true, cancelable: true, composed});
        el.dispatchEvent(ev); return ev.defaultPrevented; }""", [sel, composed])


def _wait_n(pg, n):
    pg.wait_for_function(f"window.nph() === {n} && !window.root().querySelector('[data-count]').textContent.startsWith('Preparing')")


@pytest.fixture()
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            yield b
        finally:
            b.close()


@pytest.mark.parametrize("portal_copy", [False, True], ids=["ha", "portal"])
def test_paste_in_a_field_the_form_or_the_paste_box_adds_the_picture(browser, portal_copy, tmp_path):
    src = portal.portal_card(SRC) if portal_copy else SRC
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(src))
    card = _open(pg)
    assert card.locator("[data-pastebox]").count() == 1 and card.locator("[data-pastebox]").get_attribute("contenteditable") == "true"
    # title, the text boxes, the form itself and the paste box: each paste is inside the shadow root, not composed
    cap = 3 if portal_copy else 10  # the portal takes 3: the 4th and 5th say so and add nothing
    for i, sel in enumerate(['[data-f="title"]', '[data-f="narrative"]', '[data-f="steps"]', "[data-newform]", "[data-pastebox]"], 1):
        assert _paste_into(pg, sel) is True, sel
        _wait_n(pg, min(i, cap))
    n = pg.evaluate("window.nph()")
    assert n == (3 if portal_copy else 5)
    srcs = pg.evaluate("Array.from(window.root().querySelectorAll('.ph img')).map((i) => i.src.slice(0, 23))")
    assert set(srcs) == {"data:image/jpeg;base64,"}
    if portal_copy:
        assert pg.evaluate("window.blobUrls") == 0  # the portal's CSP has no blob:
        assert "Already 3 photos" in card.locator(".photos .warn").inner_text()
    # the paste box kept nothing
    assert pg.evaluate("window.root().querySelector('[data-pastebox]').innerHTML") == ""
    # the photos go with the ticket, one message per photo (HA) or in chunks (portal)
    card.locator('[data-f="title"]').fill("Grid blank")
    card.locator('[data-f="narrative"]').fill("Nothing shows.")
    card.locator("[data-send]").click()
    pg.wait_for_function("window.calls.some((c) => c[2].topic.endsWith('ticket/image'))")
    first = json.loads(pg.evaluate("window.calls[0][2].payload"))
    assert first["images"] == n
    pg.close()


def test_a_composed_paste_is_taken_once_and_a_closed_form_takes_none(browser):
    pg = browser.new_page(viewport={"width": 1100, "height": 900})
    pg.set_content(_page(SRC))
    # no form open: nothing added, the paste is left alone
    assert _paste_into(pg, "document", composed=True) is False
    card = _open(pg)
    assert _paste_into(pg, '[data-f="title"]', composed=True) is True  # the shadow root and the document both hear it
    _wait_n(pg, 1)
    pg.wait_for_timeout(300)
    assert pg.evaluate("window.nph()") == 1
    assert _paste_into(pg, "document", composed=True) is True  # nothing focused (the 1.7.0 path) still works
    _wait_n(pg, 2)
    # a text-only paste in the paste box: kept out of the box, and a plain why
    prevented = pg.evaluate("""() => { const d = new DataTransfer(); d.setData('text/plain', 'hello');
        const ev = new ClipboardEvent('paste', {clipboardData: d, bubbles: true, cancelable: true});
        window.root().querySelector('[data-pastebox]').dispatchEvent(ev); return ev.defaultPrevented; }""")
    assert prevented is True and "No picture on the clipboard" in card.locator(".photos .warn").inner_text()
    # text pasted into the title is not touched
    prevented = pg.evaluate("""() => { const d = new DataTransfer(); d.setData('text/plain', 'hello');
        const ev = new ClipboardEvent('paste', {clipboardData: d, bubbles: true, cancelable: true});
        window.root().querySelector('[data-f="title"]').dispatchEvent(ev); return ev.defaultPrevented; }""")
    assert prevented is False
    pg.close()


def test_a_picture_dropped_on_the_form_is_added(browser):
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(SRC))
    card = _open(pg)
    r = pg.evaluate("""async () => { const d = await window.dt();
        const over = new DragEvent('dragover', {dataTransfer: d, bubbles: true, cancelable: true, composed: true});
        window.root().querySelector('[data-f="narrative"]').dispatchEvent(over);
        const drop = new DragEvent('drop', {dataTransfer: d, bubbles: true, cancelable: true, composed: true});
        window.root().querySelector('[data-f="narrative"]').dispatchEvent(drop); return [over.defaultPrevented, drop.defaultPrevented]; }""")
    assert r == [True, True]
    _wait_n(pg, 1)
    r = pg.evaluate("""() => { const d = new DataTransfer(); d.items.add(new File(['%PDF-1.4'], 'a.pdf', {type: 'application/pdf'}));
        const drop = new DragEvent('drop', {dataTransfer: d, bubbles: true, cancelable: true});
        window.root().querySelector('[data-newform]').dispatchEvent(drop); return drop.defaultPrevented; }""")
    assert r is True and "Only pictures" in card.locator(".photos .warn").inner_text()
    assert pg.evaluate("window.nph()") == 1
    pg.close()


@pytest.mark.parametrize("portal_copy", [False, True], ids=["ha", "portal"])
def test_paste_photo_button_reads_the_clipboard(browser, portal_copy):
    src = portal.portal_card(SRC) if portal_copy else SRC
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(src, clip=CLIP_OK))
    card = _open(pg)
    btn = card.locator("[data-pastebtn]")
    assert btn.count() == 1 and "Paste photo" in btn.inner_text()
    btn.click()
    _wait_n(pg, 1)
    assert pg.evaluate("window.reads") == 1
    assert pg.evaluate("window.root().querySelector('.ph img').src.startsWith('data:image/jpeg;base64,')")
    if portal_copy:
        assert pg.evaluate("window.blobUrls") == 0
    pg.close()


def test_paste_photo_button_says_why_when_refused_or_empty_and_hides_without_the_api(browser):
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(SRC, clip=CLIP_DENY))
    card = _open(pg)
    card.locator("[data-pastebtn]").click()
    pg.wait_for_function("window.root().querySelector('.photos .warn')")
    assert "did not let the card read the clipboard" in card.locator(".photos .warn").inner_text()
    assert pg.evaluate("window.nph()") == 0
    pg.close()
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(SRC, clip=CLIP_TEXT))
    card = _open(pg)
    card.locator("[data-pastebtn]").click()
    pg.wait_for_function("window.root().querySelector('.photos .warn')")
    assert "No picture on the clipboard" in card.locator(".photos .warn").inner_text()
    pg.close()
    # no async Clipboard API (plain http, an old browser): no button, the paste box and Cmd+V still work
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.set_content(_page(SRC, clip="Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined});"))
    card = _open(pg)
    assert card.locator("[data-pastebtn]").count() == 0 and card.locator("[data-pastebox]").count() == 1
    pg.close()


def test_real_keyboard_paste_into_the_paste_box(browser):
    """A real Ctrl+V (Chromium on Linux; Cmd+V on a Mac) with a PNG on the system clipboard, focus in the paste box:
    one photo, and the box stays empty (its default would insert the picture)."""
    ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"], viewport={"width": 390, "height": 900})
    pg = ctx.new_page()
    pg.route("http://localhost/fw0071", lambda r: r.fulfill(body=_page(SRC), content_type="text/html"))
    pg.goto("http://localhost/fw0071")  # a secure context, so the clipboard can be written
    wrote = pg.evaluate("async () => { try { await navigator.clipboard.write([new ClipboardItem({'image/png': await window.png(900, 500)})]); return true; } catch (e) { return String(e); } }")
    if wrote is not True:
        ctx.close()
        pytest.skip(f"clipboard not writable here: {wrote}")
    card = _open(pg)
    card.locator("[data-pastebox]").click()
    pg.keyboard.press("ControlOrMeta+V")
    _wait_n(pg, 1)
    assert pg.evaluate("window.root().querySelector('[data-pastebox]').innerHTML") == ""
    ctx.close()


@pytest.mark.parametrize("width", [390, 1100])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_render_open_form_with_paste_box(browser, tmp_path, width, theme):
    pg = browser.new_page(viewport={"width": width, "height": 1000})
    pg.set_content(_page(SRC, theme=LIGHT if theme == "light" else DARK, clip=CLIP_OK))
    card = _open(pg)
    _paste_into(pg, '[data-f="title"]')
    _wait_n(pg, 1)
    box = card.locator("[data-pastebox]").bounding_box()
    assert box and box["width"] <= width - 32 + 1 and box["height"] <= 64
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    # the photo buttons stay inside the page at both widths (they wrap at 390 px) and are 44 px tall taps (UX review
    # r3: Paste photo was 27 px); the remove x on a thumbnail keeps its small round shape
    for sel in ("[data-add]", "[data-pastebtn]", "[data-clear]"):
        bb = card.locator(sel).bounding_box()
        assert bb and bb["height"] >= 44 and bb["x"] + bb["width"] <= width, sel
    rm = card.locator("[data-rm]").first.bounding_box()
    assert rm["height"] == rm["width"] == 24
    shots = [str(tmp_path)] + ([os.environ["FW_171_SHOTS"]] if os.environ.get("FW_171_SHOTS") else [])
    for d in shots:
        pg.screenshot(path=os.path.join(d, f"fw0071_tickets_{width}_{theme}.png"), full_page=True)
    # the hint promises only what works everywhere: Safari and the HA app paste only into a box (UX review r3)
    hint = card.locator("[data-photos] [data-count]")
    pg.evaluate("window.root().querySelector('[data-clear]').click()")
    assert "in any box of this form, or in the paste box below" in hint.inner_text() and "anywhere" not in hint.inner_text()
    pg.close()

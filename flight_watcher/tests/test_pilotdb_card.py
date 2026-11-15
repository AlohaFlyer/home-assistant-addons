"""1.7.8 (spec 10.3 and 12): the Pilots card (www/flight-watcher-pilotdb-card.js) in Chromium at 390 x 844 and
1280 x 800, light and dark, on a real pilot database (the Watcher's own api/pilotdb callbacks answer the card's ingress
requests) seeded from the synthetic contact list: browse (status line, search, filter chips, results by Sen #), the
record (every field with its source and date, the other sources, call / text / mail links), a hand edit that stays
and is logged, Use upload value, the notes field saved compare-and-set (a newer save shows beside the draft: Take
theirs, Save mine over theirs), its versions with Restore, the dated log (add, Only me, take back, hide, restore), the
picker's pickup history with the count per layover station, the AI note shown read only when one is there, the held
rows; follow mode under the pilot lookup card (never pilot/set); anyone else sees one read-only line. Every value is
text: hostile notes and names never become markup or links. 1.7.9: the card joins a pilot's portal bundle (B16).
The pilot card's _esc escapes the single quote. FW_178_SHOTS=<dir> keeps the screenshots (device scale 2). Synthetic
data only ("Doe, Jane" 10001, 808-555-01xx, example.com)."""
import json
import os
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

import cards
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw171_cards import HARNESS_JS, PORTAL_CSS
from test_pilot_grid_look import _browser
from test_pilotdb_watcher import P  # noqa: F401  (the seeded pilot database fixture)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(HERE, "www", "flight-watcher-pilotdb-card.js")
SHOTS = os.environ.get("FW_178_SHOTS", "")
ORIGIN = "https://ha.test"
API = "/api/hassio_ingress/Tok3nAbc/api/pilotdb"
HOSTILE = "<img src=x onerror=alert(1)> 'single' \"double\" `tick` javascript:alert(2) </div><b>bold</b>"
ADMIN_JS = """
window.ws = [];
window.admin = { user: { id: "u1", name: "Admin", is_admin: true, is_owner: true },
  callWS: async (m) => { window.ws.push(m.endpoint);
    if (m.endpoint.endsWith("/info")) return { ingress_url: "/api/hassio_ingress/Tok3nAbc/", state: "started", ingress: true };
    if (m.endpoint === "/ingress/session") return { session: "S".repeat(32) };
    return {}; } };
"""


def _pickups():
    rows = []
    for i, (lay, day, secs) in enumerate((("LAX", 2, 75), ("SEA", 5, 40), ("LAX", 9, 300), ("", 12, 20)), 1):
        rows.append({"key": f"H36{i:02d}|{day + 3:02d}Nov", "emp": "10001", "name": "Doe, Jane", "pos": "FO",
                     "at": f"2026-11-{day:02d}T18:00:00+00:00", "pairing": f"H36{i:02d}", "start": f"2026-11-{day + 3:02d}",
                     "days": 3 if lay else 1, "lay": lay, "turn": not lay, "credit": "15:30" if lay else "6:10",
                     "report": "08:00", "dow": "Thu", "secs": secs, "approx": False, "inflt": i == 3})
    return rows


@pytest.fixture
def seeded(P):  # noqa: F811
    db = P.pilotdb_start()
    jane = db.find("10001")
    db.sync_pickups(_pickups())
    db.save_notes(jane, "Commutes from Maui.\nGood on reserve.", "000000000000")
    db.add_entry(jane, "Flew with her in Oct: great CRM.", rid="seed-0001")
    db.add_entry(jane, HOSTILE, rid="seed-0002")
    rec = db.record(jane)
    db.set_field(jane, "doh", "2001-05-02", rec["rev"], why="the PDF list has the 2nd")
    with db.lock:  # the AI note is HOM's (1.7.9): a test row only, to show it read only
        db.db.execute("INSERT INTO ai_notes(pid,text,model,basis,at) VALUES(?,?,?,?,?)",
                      (jane, "Picks up LAX layovers fast, mostly on Mondays.", "consultant-test", "stats", "2026-11-15T19:00:00+00:00"))
    roe = db.new_record("10066", f"Roe, Rich {HOSTILE[:40]}".replace("\"", "'"))
    return P, db, jane, roe


def _states(P, emp="", name=""):
    lu = "2026-11-15T19:00:00+00:00"
    return {"sensor.flight_watcher_pilotdb": {"state": "5", "last_updated": lu, "last_changed": lu, "attributes": P.pilotdb_sensor()},
            "sensor.flight_watcher_pilot_schedule": {"state": emp, "last_updated": lu, "last_changed": lu,
                                                     "attributes": {"emp": emp, "name": name, "status": "ok" if emp else ""}}}


def _page(b, P, width, height, scheme, hits):
    built = cards.build("9.9.9", [])
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
            + ADMIN_JS + "</script><script type='module'>" + built["flight-watcher-pilotdb-card.js"] + "</script></body></html>")

    def serve(route):
        req, url = route.request, route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        if urlsplit(url).path == API:
            hits.append((req.method, dict(req.headers), url))
            if req.method == "GET":
                code, body = P.pilotdb_get({k: v[-1] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()})
            else:
                assert req.headers.get("content-type", "").startswith("application/json")
                assert req.headers.get("x-fw-card") == "pilotdb"
                code, body = P.pilotdb_post(json.loads(req.post_data))
            return route.fulfill(status=code, content_type="application/json", headers={"Cache-Control": "no-store"},
                                 body=json.dumps(body))
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("dialog", lambda d: d.accept())
    pg.goto(ORIGIN + "/")
    pg.wait_for_function("!!customElements.get('flight-watcher-pilotdb-card')")
    return pg


def _shot(pg, name, sel="flight-watcher-pilotdb-card"):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pre = os.environ.get("FW_178_SHOT_PREFIX", "")  # e.g. final_ for the release's screenshots
    pg.locator(sel).first.screenshot(path=os.path.join(SHOTS, f"{pre}{name}.png"))


def _click(pg, text, scope="[data-rec]"):
    """Click the first button in the card (under scope) whose text is `text`."""
    ok = pg.evaluate("""([t, scope]) => { const root = C.shadowRoot; const box = scope ? root.querySelector(scope) : root;
      const b = [...(box || root).querySelectorAll('button')].find((x) => x.textContent.trim() === t && !x.disabled);
      if (!b) return false; b.click(); return true; }""", [text, scope])
    assert ok, text


def _txt(pg, sel="[data-rec]"):
    return pg.evaluate("(s) => { const e = C.shadowRoot.querySelector(s); return e ? e.textContent : ''; }", sel)


def _open_jane(pg):
    pg.wait_for_function("C.shadowRoot && C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 4")
    pg.evaluate("() => [...C.shadowRoot.querySelectorAll('button.nm')].find((b) => b.textContent === 'Doe, Jane A').click()")
    pg.wait_for_function("!!C.shadowRoot.querySelector('[data-rec]')")


def test_the_card_source_follows_the_rendering_rule():
    s = open(CARD, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    # no markup is ever parsed from a string: no innerHTML at all (the style block goes in as textContent)
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser", "createContextualFragment",
                "eval(", "new Function"):
        assert bad not in code, bad
    # never a Home Assistant service call (a note would land in HA's recorder) and never the pilot lookup
    assert "callService" not in code and "mqtt" not in code and "pilot/set" not in code
    # the only links: tel:, sms:, mailto:, through the href property after the checks
    assert re.findall(r"\.href\s*=", code) == [".href ="] and "a.href = `${kind}:${v}`" in code
    assert 'fwPdbLink("tel"' in code and 'fwPdbLink("sms"' in code and 'fwPdbLink("mailto"' in code
    assert "setAttribute(k" in code and "href" not in re.search(r"/\^\(title\|[^/]+/", code).group(0)
    # every write: JSON with the card's header, to the ingress API
    assert '"Content-Type": "application/json", "X-FW-Card": "pilotdb"' in code
    assert "const FW_PORTAL = false;" in s and chr(0x2014) not in s


def test_the_card_ships_and_joins_a_pilots_portal_bundle(W):  # noqa: F811
    """1.7.9 (B16, contract 1 revision 4): the Pilots card left PORTAL_CARDS_OUT, so a pilot's portal bundle carries his
    copy with FW_PORTAL on (it stayed off every portal in 1.7.8)."""
    built = cards.build("9.9.9", ["james"])
    assert "flight-watcher-pilotdb-card.js" in built and "flight-watcher-pilotdb-card-james.js" in built
    cp = built["flight-watcher-pilotdb-card-james.js"]
    assert 'customElements.define("flight-watcher-pilotdb-card-james"' in cp and "Ryan" not in cp and "ryan" not in cp.lower()
    assert 'FW_PDB_PREFIX = "flight_watcher_james"' in cp  # a pilot's copy is never the admin's (the read-only line)
    assert "pilotdb-card" not in W.PORTAL_CARDS_OUT
    W.INSTANCE = "james"
    try:
        W.EXPORT["cards"] = None
        pc = W.portal_cards()
        assert "const FW_PORTAL = true;" in pc["flight-watcher-pilotdb-card-james.js"]
        assert any("pilot-card" in f for f in pc) and not any("uploads-card-james" in f and "pilot-uploads" not in f
                                                              for f in pc)
    finally:
        W.INSTANCE = ""
        W.EXPORT["cards"] = None


def test_the_pilot_card_esc_escapes_the_single_quote(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    src = open(os.path.join(HERE, "www", "flight-watcher-pilot-card.js"), encoding="utf-8").read()
    m = re.search(r"  _esc\(s\) \{ (.+?) \}\n", src)
    f = tmp_path / "e.js"
    f.write_text("const esc = (s) => { " + m.group(1) + " };\nconsole.log(esc(`<a href='x' title=\"y\">&</a>`));")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30).stdout.strip()
    assert out == "&lt;a href=&#39;x&#39; title=&quot;y&quot;&gt;&amp;&lt;/a&gt;"


def test_browse_and_the_record_on_a_phone_and_a_desktop(seeded):
    P, db, jane, roe = seeded
    with _browser() as b:
        for width, height in ((390, 844), (1280, 800)):
            for scheme in ("light", "dark"):
                hits = []
                pg = _page(b, P, width, height, scheme, hits)
                pg.evaluate("(st) => { window.C = mount('flight-watcher-pilotdb-card', {title: 'Pilots'}, st, window.admin); }", _states(P))
                pg.wait_for_function("C.shadowRoot && C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 5")
                status = _txt(pg, "[data-status]")
                assert "5 pilots" in status and "with notes" in status and "held for you" in status
                assert "Sources: contact list 2026-11-14 (5 rows)." in status and "4 pickups by 1 picker" in status
                names = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('button.nm')].map((b) => b.textContent)")
                assert names[0] == "Roe, Rick Jr" and "Doe, Jane A" in names  # by Sen #
                pg.wait_for_function("C.shadowRoot.textContent.includes('Held for you (1)')")
                _shot(pg, f"pilotdb_browse_{width}_{scheme}")
                # the search (debounced) and a filter chip
                pg.evaluate("() => { const q = C.shadowRoot.querySelector('input[type=search]'); q.value = 'doe'; q.dispatchEvent(new Event('input')); }")
                pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length === 1")
                pg.evaluate("() => { const q = C.shadowRoot.querySelector('input[type=search]'); q.value = ''; q.dispatchEvent(new Event('input')); }")
                pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 5")
                _click(pg, "Notes", None)
                pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length === 1")
                _click(pg, "All", None)
                _open_jane(pg)
                t = _txt(pg)
                # every field with its source and date; the hand edit with its reason and the upload value it drifts from
                assert "contacts 2026-11-14" in t and "edited by ryan" in t and "Why: the PDF list has the 2nd" in t
                assert "contacts 2026-11-14 says 2001-05-01" in t and "Use upload value" in t and "Keep my edit" in t
                assert "Retires" in t and "2041-03" in t and "SLOA" in t
                hrefs = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-rec] a')].map((a) => a.getAttribute('href'))")
                assert hrefs == ["tel:+18085550101", "sms:+18085550101", "mailto:jane.doe@example.com"]
                # notes, its log (newest first, hostile text as text), pickups per station, the AI note
                assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=notes]').value") == "Commutes from Maui.\nGood on reserve."
                assert HOSTILE in t and pg.evaluate("() => C.shadowRoot.querySelectorAll('img, b').length") == 0
                stations = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('.stn span')].map((s) => s.textContent)")
                assert stations == ["LAX 2", "SEA 1"]
                assert "4 pickups" in t and "3 with a layover, 1 turn" in t and "reports at 08:00" in t and "1 while in flight" in t and "LAX (2)" in t
                assert "AI note" in t and "Picks up LAX layovers fast" in t and "Read only; not a human note." in t
                assert pg.evaluate("() => !!C.shadowRoot.querySelector('.tag.ai')")
                _shot(pg, f"pilotdb_record_{width}_{scheme}")
                fit = pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
                assert fit, "no page scroll sideways"
                con = pg.evaluate("() => fwContrast(C)")
                assert con["fails"] == [], con["fails"][:5]
                # requests: every GET and POST to the app's ingress API only, with the card's header
                assert hits and all(h[1].get("x-fw-card") == "pilotdb" for h in hits)
                assert pg.evaluate("() => window.calls.length") == 0  # no Home Assistant service call
                assert pg.errors == []
                pg.context.close()


def test_edit_notes_log_and_the_conflict_view(seeded):
    P, db, jane, roe = seeded
    with _browser() as b:
        hits = []
        pg = _page(b, P, 1280, 800, "light", hits)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-pilotdb-card', {}, st, window.admin); }", _states(P))
        _open_jane(pg)
        # a hand edit of the status, with a reason: it stays and is logged
        pg.evaluate("() => C.shadowRoot.querySelector('button[aria-label=\"Edit Status\"]').click()")
        pg.evaluate("""() => { const i = C.shadowRoot.querySelector('input[data-k=edit-status]'); i.value = 'A'; i.dispatchEvent(new Event('input'));
          const w = C.shadowRoot.querySelector('input[data-k=why-status]'); w.value = 'back from leave Nov 1'; w.dispatchEvent(new Event('input')); }""")
        _click(pg, "Save")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Status saved. It stays shown through later uploads.')")
        f = db.record(jane)["fields"]["status"]
        assert (f["value"], f["source"], f["why"]) == ("A", "hand", "back from leave Nov 1")
        assert [x["how"] for x in db.record(jane)["field_log"] if x["field"] == "status"][0] == "hand"
        # a bad value names the field, the draft stays
        pg.evaluate("() => C.shadowRoot.querySelector('button[aria-label=\"Edit Sen #\"]').click()")
        pg.evaluate("() => { const i = C.shadowRoot.querySelector('input[data-k=edit-sen]'); i.value = 'abc'; i.dispatchEvent(new Event('input')); }")
        _click(pg, "Save")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Sen # must be 1 to 5 digits.')")
        assert pg.evaluate("() => C.shadowRoot.querySelector('input[data-k=edit-sen]').value") == "abc"
        _click(pg, "Cancel")
        # Use upload value: back to the uploads
        pg.evaluate("""() => { const f = [...C.shadowRoot.querySelectorAll('.fl')].find((x) => x.querySelector('.fk').textContent === 'DOH');
          [...f.querySelectorAll('button')].find((b) => b.textContent === 'Use upload value').click(); }""")
        pg.wait_for_function("C.shadowRoot.textContent.includes('DOH: back to the uploads.')")
        assert db.record(jane)["fields"]["doh"] == dict(db.record(jane)["fields"]["doh"], value="2001-05-01", hand=False)
        # the notes field, compare-and-set: Ryan types, another save lands first
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]'); t.value = 'My draft about her.'; t.dispatchEvent(new Event('input')); }")
        cur = db.record(jane)["notes"]
        db.save_notes(jane, "Saved elsewhere first.", cur["rev"], by="ryan")
        _click(pg, "Save notes")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Not saved: changed by ryan')")
        t = _txt(pg)
        assert "Theirs (saved)" in t and "Saved elsewhere first." in t and "Yours (not saved)" in t and "My draft about her." in t
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=notes]').value") == "My draft about her."
        assert db.record(jane)["notes"]["text"] == "Saved elsewhere first."  # nothing overwritten blind
        _shot(pg, "pilotdb_notes_conflict_1280_light")
        _click(pg, "Save mine over theirs")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Notes saved.')")
        assert db.record(jane)["notes"]["text"] == "My draft about her."
        # its versions: Restore one (a new save on the current base)
        pg.evaluate("() => { const d = [...C.shadowRoot.querySelectorAll('summary')].find((s) => s.textContent.startsWith('Earlier versions')); d.click(); }")
        pg.evaluate("""() => { const e = [...C.shadowRoot.querySelectorAll('[data-rec] details .ent')].find((x) => x.textContent.includes('Saved elsewhere first.'));
          [...e.querySelectorAll('button')].find((b) => b.textContent === 'Restore').click(); }""")
        pg.wait_for_function("C.shadowRoot.querySelector('textarea[data-k=notes]').value === 'Saved elsewhere first.'")
        assert db.record(jane)["notes"]["text"] == "Saved elsewhere first."
        # the log: add with Only me, take back, hide and restore
        pg.evaluate("""() => { const t = C.shadowRoot.querySelector('textarea[data-k=entry]'); t.value = 'Only for me: ask about the 777.'; t.dispatchEvent(new Event('input'));
          const c = C.shadowRoot.querySelector('input[data-k=only]'); c.checked = true; c.dispatchEvent(new Event('change')); }""")
        _click(pg, "Add")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Only for me: ask about the 777.')")
        e = next(x for x in db.record(jane)["entries"] if x["text"] == "Only for me: ask about the 777.")  # review: by text
        assert (e["text"], e["shared"], e["by"]) == ("Only for me: ask about the 777.", False, "ryan")
        assert db.record(jane)["entries"][0]["eid"] == e["eid"]  # and newest first (entries in one second keep their order)
        assert "only me" in pg.evaluate("(eid) => C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent", e["eid"])
        pg.evaluate("(eid) => [...C.shadowRoot.querySelector(`[data-eid=${eid}]`).querySelectorAll('button')].find((b) => b.textContent === 'Take back').click()", e["eid"])
        pg.wait_for_function("(eid) => C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('taken back by ryan')", arg=e["eid"])
        assert next(x for x in db.record(jane)["entries"] if x["eid"] == e["eid"])["gone"] == "retracted"
        hostile = next(x for x in db.record(jane)["entries"] if x["text"] == HOSTILE)
        pg.evaluate("(eid) => [...C.shadowRoot.querySelector(`[data-eid=${eid}]`).querySelectorAll('button')].find((b) => b.textContent === 'Hide').click()", hostile["eid"])
        pg.wait_for_function("(eid) => C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('hidden by ryan')", arg=hostile["eid"])
        pg.evaluate("(eid) => [...C.shadowRoot.querySelector(`[data-eid=${eid}]`).querySelectorAll('button')].find((b) => b.textContent === 'Restore').click()", hostile["eid"])
        pg.wait_for_function("(eid) => !C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('hidden by ryan')", arg=hostile["eid"])
        # the held row: attach the unmatched contact to a record through the small search
        pg.evaluate("() => [...C.shadowRoot.querySelectorAll('button')].find((b) => b.textContent === 'Attach to a record').click()")
        pg.evaluate("() => { const i = [...C.shadowRoot.querySelectorAll('input[type=search]')].pop(); i.value = 'poe'; i.dispatchEvent(new Event('input')); }")
        pg.wait_for_function("[...C.shadowRoot.querySelectorAll('button')].some((b) => b.textContent === 'Pick')")
        pg.evaluate("() => [...C.shadowRoot.querySelectorAll('button')].find((b) => b.textContent === 'Pick').click()")
        pg.wait_for_function("!C.shadowRoot.textContent.includes('Held for you (')")
        assert db.conflicts() == []
        pages = [u for m, _h, u in hits if m == "POST"]
        assert pages and all(urlsplit(u).path == API for u in pages)
        assert pg.evaluate("() => window.calls.length") == 0
        assert pg.errors == []
        pg.context.close()


def test_follow_mode_under_the_pilot_card_and_anyone_else(seeded):
    P, db, jane, roe = seeded
    with _browser() as b:
        for width, height in ((390, 844), (1280, 800)):
            for scheme in ("light", "dark"):
                hits = []
                pg = _page(b, P, width, height, scheme, hits)
                pg.evaluate("(st) => { window.C = mount('flight-watcher-pilotdb-card', {follow: true}, st, window.admin); }", _states(P))
                pg.wait_for_function("C.shadowRoot.textContent.includes('Look a pilot up above')")
                assert not any(m == "GET" and "emp=" in u for m, _h, u in hits)
                pg.evaluate("(st) => { C.hass = mkHass(st, window.admin); }", _states(P, "10001", "Doe, Jane"))
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-rec]')")
                t = _txt(pg)
                assert "Doe, Jane A" in t and "Sen 812 · Emp 10001" in t and "Commutes from Maui." in pg.evaluate(
                    "() => C.shadowRoot.querySelector('textarea[data-k=notes]').value")
                assert "Flew with her in Oct: great CRM." in t and "LAX 2" in t and "AI note" in t
                assert "Merge, renumber or delete" not in t  # browse only
                _shot(pg, f"pilotdb_follow_{width}_{scheme}")
                assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
                assert pg.evaluate("() => fwContrast(C)")["fails"] == []
                # a pilot who is not in the database: say so, and offer a record
                pg.evaluate("(st) => { C.hass = mkHass(st, window.admin); }", _states(P, "10099", "Doe, Nobody"))
                pg.wait_for_function("C.shadowRoot.textContent.includes('Not in the pilot database.')")
                assert "Add a record for him" in _txt(pg, ".c")
                gets = [u for m, _h, u in hits if m == "GET" and "emp=" in u]
                assert any("emp=10001" in u for u in gets) and any("emp=10099" in u for u in gets)
                assert pg.evaluate("() => window.calls.length") == 0  # never pilot/set (no service call at all)
                assert pg.errors == []
                pg.context.close()
        # anyone else (not an admin, or a pilot's copy): one read-only line, no request
        hits = []
        pg = _page(b, P, 390, 844, "light", hits)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-pilotdb-card', {}, st); }", _states(P, "10001", "Doe, Jane"))
        pg.wait_for_timeout(1500)
        assert _txt(pg, ".c") == "Pilot databaseThe pilot database is on Ryan's dashboard, for a Home Assistant admin."
        assert hits == [] and pg.evaluate("() => window.ws.length") == 0
        _shot(pg, "pilotdb_not_admin_390_light")
        assert pg.errors == []
        pg.context.close()

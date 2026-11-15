"""1.7.9 (contract 1 revision 4, spec 11.5), as of 1.7.10 (Ryan's decisions of Nov 15: "The pilot database should be
shared with James 100%"): the Pilots card on a shared pilot's portal.

The portal's copy of www/flight-watcher-pilotdb-card.js (cards.pilot_copy, then portal.portal_card: FW_PORTAL on) in
Chromium at 390, 820 and 1280 px, light and dark, on the real pieces behind it: Ryan's database (pilotdb.PilotDB), the
admin's files (pdbshare.write_files), the pilot's read side (pdbshare.View: his file), his Watcher's checks
(pdbshare.pilot_check), the inbox and the admin's drain. The card reads the pilot's own synthesized sensor and his
own file, never the ingress API. It is a full browse and search of every pilot, as Ryan's card: the pilot looked up
and every pilot of the list, each with every field, call, text and mail links, the notes field saved compare-and-set
(a stale save shows both texts), the log (add, take back his own; no "Only me"), the pickup history and field edits;
every value is text; a command carries no author, name or employee number; fields are 16 px and controls 44 px, with
no sideways scroll. Ryan's own card has the Share switch per portal pilot and the AI notes switch, both on by
default and his to turn off.
FW_179_SHOTS=<dir> keeps the screenshots. Synthetic pilots only ("Doe, Jane", 10001, 808-555-01xx, example.com)."""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

import cards
import pdbshare as PS
import pilotdb as PDBM
import portal as PT
import roles
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw171_cards import HARNESS_JS, PORTAL_CSS
from test_pilot_grid_look import _browser
from test_pilotdb_card import ADMIN_JS, API, HOSTILE
from test_pilotdb_store import CONTACTS, LIST
from test_pilotdb_watcher import P  # noqa: F401  (the seeded pilot database fixture)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("FW_179_SHOTS", "")
ORIGIN = "https://portal.test"
TAG = "flight-watcher-pilotdb-card-james"
SENSOR = "sensor.flight_watcher_james_pilotdb"
FILE_PATH = "/local/flight-watcher/james/pilotdb_" + "0" * 32 + ".json"
T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
SIZES = ((390, 844), (820, 1180), (1280, 800))


class Side:
    """Both Watchers without a Watcher: Ryan's database and files, and the pilot's view, checks and answers."""

    def __init__(self, tmp_path):
        self.root = str(tmp_path / "share" / "flight_watcher" / "pilotdb")
        self.db = PDBM.PilotDB(str(tmp_path / "pilotdb.sqlite"), clock=lambda: T0)
        self.db.merge_list(LIST)
        self.db.merge_contacts(CONTACTS)
        self.view = PS.View("james", self.root)
        self.emp, self.name = "", ""
        self.local, self.pending = [], []
        self.jane, self.roe = self.db.find("10001"), self.db.find("10002")

    def share(self, on=True):
        self.db.set_share("james", on)
        self.files()

    def files(self):
        PS.write_files(self.db, ["james"], self.root)
        self.view.refresh()

    def shown(self):
        return self.view.shown(self.emp, self.name) if self.view.state == "on" else None

    def states(self):
        v = self.view
        answers = v.answers + [a for a in self.local if a["rid"] not in {x["rid"] for x in v.answers}]
        attrs = {"friendly_name": "Pilot database", "rev": v.rev, "file_key": "0" * 32, "count": v.count,
                 "updated": v.updated, "shown": self.shown(), "answers": answers, "pending": list(self.pending),
                 "limits": v.limits or PT.pilotdb_limits()}
        assert set(attrs) == set(PT.PILOTDB_STATE_KEYS["attributes"])
        at = v.updated or None
        return {SENSOR: {"state": v.state, "attributes": attrs, "last_changed": at, "last_updated": at}}

    def command(self, topic, payload):
        """What the pilot's Watcher and then the admin's drain do with one published command."""
        m = re.fullmatch(r"flight_watcher_james/pilotdb/(note|edit)", topic)
        assert m, topic
        inner, why = PS.pilot_check(self.view, None, m.group(1), payload, len(self.pending))
        if why:
            self.local.append({"rid": inner["rid"], "ok": False, "why": why, "at": "2026-11-15T20:00:00+00:00"})
            return
        PS.inbox_put("james", m.group(1), inner, self.root)
        PS.drain(self.db, ["james"], self.root)
        self.files()


@pytest.fixture
def side(tmp_path):
    s = Side(tmp_path)
    yield s
    s.db.close()


def _card():
    built = cards.build("9.9.9", ["james"])
    return PT.portal_card(built[TAG + ".js"])


def _page(b, side, width, height, scheme, fetched):
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="America/New_York", has_touch=width < 1000)
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
            + "</script><script type='module'>" + _card() + "</script></body></html>")

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        fetched.append(url)
        if urlsplit(url).path == FILE_PATH and side.view.state == "on":
            return route.fulfill(status=200, content_type="application/json", body=side.view.text)
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("dialog", lambda d: d.accept())
    pg.goto(ORIGIN + "/")
    pg.wait_for_function(f"!!customElements.get('{TAG}')")
    return pg


def _mount(pg, side):
    pg.evaluate("([tag, st]) => { window.C = mount(tag, {follow: true}, st); }", [TAG, side.states()])


def _push(pg, side):
    pg.evaluate("(st) => { C.hass = mkHass(st); }", side.states())


def _pump(pg, side, done=0):
    """Hands every command the card published since `done` to the Watchers, then gives the card the new state."""
    calls = pg.evaluate("() => window.calls")
    for d, s, data in calls[done:]:
        assert (d, s) == ("mqtt", "publish") and set(data) == {"topic", "payload"}
        side.command(data["topic"], data["payload"])
    _push(pg, side)
    return len(calls)


def _shot(pg, name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pg.locator(TAG).first.screenshot(path=os.path.join(SHOTS, f"{name}.png"))


def _txt(pg, sel=".c"):
    return pg.evaluate("(s) => { const e = C.shadowRoot.querySelector(s); return e ? e.textContent : ''; }", sel)


def _click(pg, text, scope=None):
    ok = pg.evaluate("""([t, scope]) => { const root = C.shadowRoot; const box = scope ? root.querySelector(scope) : root;
      const b = [...(box || root).querySelectorAll('button')].find((x) => x.textContent.trim() === t && !x.disabled);
      if (!b) return false; b.click(); return true; }""", [text, scope])
    assert ok, text


def _type(pg, key, value):
    pg.evaluate("""([k, v]) => { const e = [...C.shadowRoot.querySelectorAll('[data-k]')].find((x) => x.dataset.k === k);
      e.value = v; e.dispatchEvent(new Event('input')); }""", [key, value])


def _sizes(pg):
    """(the smallest field font size, the lowest control height) of what is on screen in the card."""
    return pg.evaluate("""() => { const root = C.shadowRoot, vis = (e) => e.getClientRects().length > 0;
      const fields = [...root.querySelectorAll('input:not([type=checkbox]), textarea, select')].filter(vis);
      const ctl = [...root.querySelectorAll('button, a.ct, summary, input:not([type=checkbox])')].filter(vis);
      return [Math.min(...fields.map((e) => parseFloat(getComputedStyle(e).fontSize))),
              Math.min(...ctl.map((e) => e.getBoundingClientRect().height))]; }""")


def _seed(side):
    db = side.db
    db.save_notes(side.jane, "Commutes from Maui.\nGood on reserve.", PDBM.ZERO_REV)
    db.add_entry(side.jane, "Flew with her in Oct: great CRM.", rid="seed-0001")
    db.add_entry(side.jane, HOSTILE, rid="seed-0002")
    db.add_entry(side.jane, "ONCE-ONLY-ME", shared=False, rid="seed-0003")  # 1.7.9's "Only me": shared since 1.7.10
    db.add_entry(side.roe, "Good with the new hires.", rid="seed-0004")


# ---------------------------------------------------------------- the source
def test_the_portal_copy_publishes_only_the_two_commands_and_parses_no_markup(W):  # noqa: F811
    src = open(os.path.join(HERE, "www", "flight-watcher-pilotdb-card.js"), encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser", "eval(", "new Function"):
        assert bad not in code, bad
    # one service call in the whole card: _pub, which refuses outside a portal
    assert code.count("callService") == 1 and "pilot/set" not in code
    pub = re.search(r"  _pub\(sub, obj\) \{.*?\n  \}\n", code, re.S).group(0)
    assert 'if (!FW_PORTAL) return Promise.reject' in pub and 'callService("mqtt", "publish"' in pub
    assert re.findall(r'_pub\("([a-z_/]+)"', code) == ["pilotdb/note", "pilotdb/edit"]
    cp = _card()
    assert "const FW_PORTAL = true;" in cp and "/local/flight-watcher/james/pilotdb_" in cp
    assert PT.card_subs(cp, "flight_watcher_james") == {"pilotdb/note", "pilotdb/edit"}
    assert all(roles.portal_sub(s) for s in ("pilotdb/note", "pilotdb/edit"))
    assert "ryan" not in cp.lower() and chr(0x2014) not in src
    # the ops and keys the card sends are the contract's
    for op in roles.PILOTDB_NOTE_OPS + roles.PILOTDB_EDIT_OPS:
        assert f'op: "{op}"' in code, op
    assert "pilotdb-card" not in W.PORTAL_CARDS_OUT
    layout = json.load(open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8"))
    pilot_tab = [c["type"] for t in layout["tabs"] if t["id"] == "pilot" for c in t["cards"]]
    assert pilot_tab.index("custom:flight-watcher-pilotdb-card-{name}") == pilot_tab.index("custom:flight-watcher-pilot-card-{name}") + 1


# ---------------------------------------------------------------- what he sees
def test_not_shared_shows_one_line_and_asks_for_nothing(side):
    side.share(on=False)  # Ryan turned this pilot's share off
    with _browser() as b:
        fetched = []
        pg = _page(b, side, 390, 844, "light", fetched)
        _mount(pg, side)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Not shared')")
        assert _txt(pg) == "Pilot databaseNot shared: the admin has turned his pilot database off for you."
        assert fetched == [] and pg.evaluate("() => window.calls.length") == 0 and pg.errors == []
        _shot(pg, "portal_off_390_light")
        pg.context.close()


def _picks(side):
    side.db.sync_pickups([{"key": f"H36{i:02d}|13Nov", "emp": "10001", "name": "Doe, Jane", "pos": "FO",
                           "at": f"2026-11-{10 + i:02d}T03:10:00+00:00", "secs": 90 + i, "approx": False,
                           "lay": "SYD" if i else "", "pairing": f"H36{i:02d}", "start": "2026-11-20",
                           "days": 3 if i else 1, "turn": not i, "credit": "14:05", "report": "07:10", "dow": "Fri",
                           "inflt": False} for i in range(3)])


LIST_NAMES = "() => [...C.shadowRoot.querySelectorAll('[data-plist] button.nm')].map((x) => x.textContent)"


def test_every_pilot_browse_search_and_record_at_three_widths(side):
    _seed(side)
    _picks(side)
    db = side.db
    db.set_field(side.roe, "phones", [{"label": "mobile", "number": "808-555-0102"}], db.record(side.roe)["rev"])
    db.set_field(side.jane, "domicile", "HNL", db.record(side.jane)["rev"])
    side.share()
    with _browser() as b:
        for width, height in SIZES:
            for scheme in ("light", "dark"):
                fetched = []
                side.emp, side.name = "", ""
                pg = _page(b, side, width, height, scheme, fetched)
                _mount(pg, side)
                pg.wait_for_function("C.shadowRoot.textContent.includes('All pilots (2)')")
                t = _txt(pg)
                assert "Look a pilot up above to see his record here, or find him in the list below." in t
                assert ("The pilot database you share with the admin: every pilot, every field. Notes are read by the "
                        "admin and his assistant; write them as notes, not requests.") in t
                assert pg.evaluate(LIST_NAMES) == ["Roe, Rick", "Doe, Jane A."]  # every pilot, by Sen #
                lt = _txt(pg, "[data-plist]")
                assert "Sen 812 · Emp 10001 · SLOA" in lt and "Emp 10002" in lt and "3 pickups" in lt
                assert "555" not in lt and "example.com" not in lt  # phones and emails are on the record, not the list
                assert pg.evaluate("() => C.shadowRoot.querySelectorAll('[data-plist] a').length") == 0
                # the search, as on Ryan's card: name words, an employee number, s<Sen #>, "quoted" notes and log text
                for q, want in (("roe", ["Roe, Rick"]), ("doe ja", ["Doe, Jane A."]), ("10001", ["Doe, Jane A."]),
                                ("1000", ["Roe, Rick", "Doe, Jane A."]), ("s812", ["Doe, Jane A."]), ("s81", []),
                                ('"reserve"', ["Doe, Jane A."]), ('"new hires"', ["Roe, Rick"]), ("zzz", []), ("", ["Roe, Rick", "Doe, Jane A."])):
                    _type(pg, "pq", q)
                    assert pg.evaluate(LIST_NAMES) == want, q
                assert pg.evaluate("() => C.shadowRoot.querySelector('[data-pcount]').textContent") == "2 pilots, by Sen #."
                # the filter chips
                chips = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] .chip')].map((x) => [x.textContent, x.getAttribute('aria-pressed')])")
                assert chips == [["All", "true"], ["Notes", "false"], ["Edited", "false"], ["Pickups", "false"], ["Gone", "false"]]
                for chip, want in (("Pickups", ["Doe, Jane A."]), ("Edited", ["Roe, Rick", "Doe, Jane A."]), ("Gone", []),
                                   ("Notes", ["Roe, Rick", "Doe, Jane A."]), ("All", ["Roe, Rick", "Doe, Jane A."])):
                    _click(pg, chip, "[data-plist]")
                    assert pg.evaluate(LIST_NAMES) == want, chip
                font, height_min = _sizes(pg)
                assert font >= 16 and height_min >= 44, (width, font, height_min)
                _shot(pg, f"portal_browse_{width}_{scheme}")
                # a pilot who is not in the database
                side.emp, side.name = "10099", "Doe, Nobody"
                _push(pg, side)
                pg.wait_for_function("C.shadowRoot.textContent.includes(\"Not in the admin's pilot database.\")")
                # the pilot looked up: every field, the links, notes, the log and the pickups
                side.emp, side.name = "10001", "Doe, Jane"
                _push(pg, side)
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-rec]')")
                t = _txt(pg, "[data-pshown]")
                assert "Doe, Jane A." in t
                assert "Sen 812 · Emp 10001 · DOH 2001-05-01 · Status SLOA · Retires 2041-03 · Base HNL" in t
                hrefs = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-pshown] a')].map((a) => a.getAttribute('href'))")
                assert "tel:+18085550101" in hrefs and "mailto:jane.doe@example.com" in hrefs
                assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-notes]').value") == "Commutes from Maui.\nGood on reserve."
                # the whole log, the entry 1.7.9 kept as "Only me" too; every value is text
                assert "Flew with her in Oct: great CRM." in t and HOSTILE in t and "ONCE-ONLY-ME" in t
                assert pg.evaluate("() => C.shadowRoot.querySelectorAll('img, b, script').length") == 0
                assert "Saved by ryan 2026-11-15 10:00 HST" in t  # HST whatever zone the phone is in
                assert "Pickups" in t and "3 pickups · 2 with a layover, 1 turn" in t and "SYD 2" in t
                # Ryan's side only: no history, hide, purge, merge or delete; and no "Only me" anywhere
                for s in ("History", "Hide", "Purge", "Merge", "Delete", "Only me", "Earlier versions", "sources disagree"):
                    assert s not in _txt(pg), s
                # any other pilot from the list, with no lookup: the same record, his links too
                pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] button.nm')].find((x) => x.textContent === 'Roe, Rick').click()")
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-psel] [data-rec]')")
                st = _txt(pg, "[data-psel]")
                assert "Roe, Rick" in st and "Good with the new hires." in st and "Sen 13 · Emp 10002" in st
                sel = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-psel] a')].map((a) => a.getAttribute('href'))")
                assert sel == ["tel:+18085550102", "sms:+18085550102"]
                allh = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('a')].map((a) => a.getAttribute('href'))")
                assert all(re.match(r"^(tel|sms|mailto):", h) for h in allh)
                pg.evaluate("() => { for (const d of C.shadowRoot.querySelectorAll('details')) d.open = true; }")
                labels = "(box) => [...C.shadowRoot.querySelectorAll(box + ' .fk')].map((x) => x.textContent)"
                want = ["Name", "Sen #", "DOH", "Status", "Retires", "Seat", "Equipment", "Phones", "Emails", "Union ID", "Base"]
                assert pg.evaluate(labels, "[data-pshown]") == want and pg.evaluate(labels, "[data-psel]") == want
                font, height_min = _sizes(pg)
                assert font >= 16 and height_min >= 44, (width, font, height_min)
                _shot(pg, f"portal_record_{width}_{scheme}")
                assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), "no page scroll sideways"
                inner = pg.evaluate("""() => [...C.shadowRoot.querySelectorAll('*')].filter((e) => e.getClientRects().length
                  && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible').map((e) => e.className)""")
                assert inner == [], inner  # and nothing inside the card scrolls sideways either
                con = pg.evaluate("() => fwContrast(C)")
                assert con["fails"] == [], con["fails"][:5]
                # only his own file was fetched, by its rev; nothing was published; never the ingress API
                assert fetched and all(urlsplit(u).path == FILE_PATH and urlsplit(u).query == f"r={side.view.rev}" for u in fetched)
                assert pg.evaluate("() => window.calls.length") == 0 and pg.errors == []
                pg.context.close()


def test_a_file_of_1300_pilots_draws_fifty_at_a_time_and_searches_at_once(side):
    """The size Ryan's database has (about 1228 live records): the list draws 50 rows and "Show 50 more", a search
    narrows it, and nothing scrolls sideways at any width."""
    def last(i):  # letters only, as names are: Doeaaa, Doeaab, ...
        return "Doe" + "".join(chr(97 + (i // 26 ** k) % 26) for k in (2, 1, 0))
    recs = [{"pid": "p%010x" % i, "emp": str(20000 + i), "name": f"{last(i)}, Jane", "sen": str(i + 1), "doh": "2001-05-01",
             "status": "A", "retire": "2041-03", "seat": "FO", "equip": "A330", "base": "HNL", "union_id": "",
             "phones": [{"label": "mobile", "number": "808-555-0101", "tel": "+18085550101"}],
             "emails": ["jane.doe@example.com"], "gone": False, "edited": [], "rev": 1, "entries": [], "entries_total": 0}
            for i in range(1300)]
    doc = {"v": 1, "generated": "2026-11-15T20:00:00+00:00", "as_of": {"list": "2026-11-01", "contacts": "", "award": ""},
           "count": len(recs), "records": recs, "answers": [], "limits": PT.pilotdb_limits()}
    os.makedirs(os.path.join(side.root, "portal"), exist_ok=True)
    open(PS.export_path("james", side.root), "w", encoding="utf-8").write(json.dumps(doc, separators=(",", ":")))
    side.view.refresh()
    assert side.view.state == "on" and side.view.count == 1300 and len(side.view.names) == 1300
    with _browser() as b:
        for width, height in SIZES:
            pg = _page(b, side, width, height, "light", [])
            _mount(pg, side)
            pg.wait_for_function("C.shadowRoot.textContent.includes('All pilots (1300)')")
            assert len(pg.evaluate(LIST_NAMES)) == 50
            assert "The first 50 of 1300 are shown." in _txt(pg, "[data-plist]")
            _click(pg, "Show 50 more", "[data-plist]")
            assert len(pg.evaluate(LIST_NAMES)) == 100
            _type(pg, "pq", last(777).lower())
            assert pg.evaluate(LIST_NAMES) == [f"{last(777)}, Jane"]
            _type(pg, "pq", "21299")
            assert pg.evaluate(LIST_NAMES) == [f"{last(1299)}, Jane"]
            _type(pg, "pq", "s1300")
            assert pg.evaluate(LIST_NAMES) == [f"{last(1299)}, Jane"]
            _click(pg, f"{last(1299)}, Jane", "[data-plist]")
            pg.wait_for_function("!!C.shadowRoot.querySelector('[data-psel] [data-rec]')")
            assert "Sen 1300 · Emp 21299" in _txt(pg, "[data-psel]")
            assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
            font, height_min = _sizes(pg)
            assert font >= 16 and height_min >= 44, (width, font, height_min)
            _shot(pg, f"portal_1300_{width}_light")
            assert pg.errors == []
            pg.context.close()


# ---------------------------------------------------------------- what he writes
def test_notes_log_and_field_edits_travel_as_commands_and_come_back_as_answers(side):
    _seed(side)
    side.share()
    db, jane = side.db, side.jane
    side.emp, side.name = "10001", "Doe, Jane"
    with _browser() as b:
        pg = _page(b, side, 390, 844, "light", [])
        _mount(pg, side)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-rec]') && C.shadowRoot.textContent.includes('Flew with her')")
        # a log entry: the draft stays until the Watcher's answer is in
        _type(pg, "shown-entry", "Flew the SYD trip together.")
        _click(pg, "Add", "[data-pshown]")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Sent. Waiting for the Watcher...')")
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-entry]').value") == "Flew the SYD trip together."
        topic, payload = pg.evaluate("() => [window.calls[0][2].topic, window.calls[0][2].payload]")
        body = json.loads(payload)
        assert topic == "flight_watcher_james/pilotdb/note"
        assert set(body) == {"op", "pid", "text", "rid"} and body["op"] == "add" and body["pid"] == jane
        assert re.fullmatch(r"[A-Za-z0-9_-]{16}", body["rid"])
        n = _pump(pg, side)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Added.')")
        pg.wait_for_function("[...C.shadowRoot.querySelectorAll('[data-pshown] .ent')].some((e) => e.textContent.includes('Flew the SYD trip together.') && e.textContent.includes('yours'))")
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-entry]').value") == ""
        e = next(x for x in db.record(jane)["entries"] if x["text"] == "Flew the SYD trip together.")
        assert e["by"] == "james" and e["shared"] is True  # the author is the instance, never a payload key
        # take back his own entry (Ryan's entries have no button)
        assert pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-pshown] .ent button')].map((x) => x.textContent)") == ["Take back"]
        _click(pg, "Take back", "[data-pshown]")
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Taken back.')")
        assert next(x for x in db.record(jane)["entries"] if x["eid"] == e["eid"])["gone"] == "retracted"
        # the notes field, compare-and-set on the version read
        _type(pg, "shown-notes", "Commutes from Maui.\nGood on reserve.\nLikes the early SYD.")
        _click(pg, "Save notes", "[data-pshown]")
        body = json.loads(pg.evaluate("() => window.calls[window.calls.length - 1][2].payload"))
        assert set(body) == {"op", "pid", "base", "text", "rid"} and body["op"] == "field" and re.fullmatch(r"[0-9a-f]{12}", body["base"])
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Notes saved.')")
        cur = db.record(jane)["notes"]
        assert cur["text"].endswith("Likes the early SYD.") and cur["by"] == "james"
        pg.wait_for_function("C.shadowRoot.textContent.includes('Saved by james')")
        # a stale save: Ryan saved meanwhile, the card has not seen it. Nothing is overwritten, both texts show
        _type(pg, "shown-notes", "My draft about her.")
        db.save_notes(jane, "Ryan saved this first.", cur["rev"], by="ryan")
        _click(pg, "Save notes", "[data-pshown]")
        n = _pump(pg, side, n)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-conflict]') && C.shadowRoot.querySelector('[data-conflict]').textContent.includes('Ryan saved this first.')")
        t = _txt(pg, "[data-conflict]")
        assert "Not saved: changed by ryan at 10:00 HST; your text is still in the box." in t
        assert "Theirs (saved)" in t and "Yours (not saved)" in t and "My draft about her." in t
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-notes]').value") == "My draft about her."
        assert db.record(jane)["notes"]["text"] == "Ryan saved this first."
        _shot(pg, "portal_notes_conflict_390_light")
        _click(pg, "Save mine over theirs", "[data-pshown]")
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Notes saved.')")
        assert db.record(jane)["notes"]["text"] == "My draft about her."
        assert [v["text"] for v in db.record(jane)["notes_hist"]][0] == "Ryan saved this first."  # every version kept
        # a field edit, with a reason; then a value the database refuses (the answer never repeats it)
        pg.evaluate("() => { for (const d of C.shadowRoot.querySelectorAll('[data-pshown] details')) d.open = true; }")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-pshown] button[aria-label=\"Edit Seat\"]').click()")
        _type(pg, "shown-edit-seat", "FO")
        _type(pg, "shown-why-seat", "from the award")
        _click(pg, "Save", "[data-pshown]")
        body = json.loads(pg.evaluate("() => window.calls[window.calls.length - 1][2].payload"))
        assert pg.evaluate("() => window.calls[window.calls.length - 1][2].topic") == "flight_watcher_james/pilotdb/edit"
        assert set(body) == {"op", "pid", "field", "value", "rev", "why", "rid"} and (body["op"], body["field"], body["value"]) == ("set", "seat", "FO")
        assert isinstance(body["rev"], int) and body["rev"] >= 1
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Seat saved.')")
        f = db.record(jane)["fields"]["seat"]
        assert (f["value"], f["hand"], f["by"], f["why"]) == ("FO", True, "james", "from the award")
        pg.wait_for_function("[...C.shadowRoot.querySelectorAll('[data-pshown] .fl')].find((x) => x.querySelector('.fk').textContent === 'Seat').textContent.includes('edited')")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-pshown] button[aria-label=\"Edit DOH\"]').click()")
        _type(pg, "shown-edit-doh", "May 1st 2001")
        _click(pg, "Save", "[data-pshown]")
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Not saved: that value is not valid for doh.')")
        assert pg.evaluate("() => C.shadowRoot.querySelector('input[data-k=shown-edit-doh]').value") == "May 1st 2001"
        assert db.record(jane)["fields"]["doh"]["value"] == "2001-05-01"
        _click(pg, "Cancel", "[data-pshown]")
        # the phones of the pilot looked up: one a line, sent as the JSON text of a list
        pg.evaluate("() => C.shadowRoot.querySelector('[data-pshown] button[aria-label=\"Edit Phones\"]').click()")
        _type(pg, "shown-edit-phones", "mobile 808-555-0111\nhome 808-555-0112")
        _click(pg, "Save", "[data-pshown]")
        body = json.loads(pg.evaluate("() => window.calls[window.calls.length - 1][2].payload"))
        assert json.loads(body["value"]) == [{"label": "mobile", "number": "808-555-0111"}, {"label": "home", "number": "808-555-0112"}]
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Phones saved.')")
        pg.wait_for_function("[...C.shadowRoot.querySelectorAll('[data-pshown] a')].some((a) => a.getAttribute('href') === 'sms:+18085550111')")
        # Use upload value: the uploads' value is back
        pg.evaluate("""() => { const f = [...C.shadowRoot.querySelectorAll('[data-pshown] .fl')].find((x) => x.querySelector('.fk').textContent === 'Seat');
          [...f.querySelectorAll('button')].find((x) => x.textContent === 'Use upload value').click(); }""")
        body = json.loads(pg.evaluate("() => window.calls[window.calls.length - 1][2].payload"))
        assert set(body) == {"op", "pid", "field", "rev", "rid"} and body["op"] == "unset"
        n = _pump(pg, side, n)
        pg.wait_for_function("C.shadowRoot.textContent.includes(\"Seat: back to the uploads' value.\")")
        assert db.record(jane)["fields"]["seat"]["hand"] is False
        # no command ever named an author, a name or an employee number, and each passed the contract's shape
        for d, s, data in pg.evaluate("() => window.calls"):
            body = json.loads(data["payload"])
            assert not set(body) & {"by", "emp", "name", "author"}, body
            PT.check_shape(data["topic"].split("/", 1)[1], data["payload"])
        assert pg.errors == []
        pg.context.close()


def test_a_command_the_portal_does_not_send_keeps_the_draft_and_says_so(side):
    _seed(side)
    side.share()
    side.emp, side.name = "10002", "Roe, Rick"
    with _browser() as b:
        pg = _page(b, side, 390, 844, "dark", [])
        pg.evaluate("""([tag, st]) => { const c = document.createElement(tag); c.setConfig({follow: true});
          c.hass = { ...mkHass(st), callService: async () => { throw new Error("Too many commands. Wait a minute."); } };
          document.querySelector(".view").appendChild(c); window.C = c; }""", [TAG, side.states()])
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-rec]')")
        _type(pg, "shown-entry", "A note that does not leave.")
        _click(pg, "Add", "[data-pshown]")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Not sent: Too many commands. Wait a minute. Your text is still in the box.')")
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-entry]').value") == "A note that does not leave."
        # too long, or empty: said on the card, nothing sent
        _type(pg, "shown-entry", "x" * 2001)
        _click(pg, "Add", "[data-pshown]")
        pg.wait_for_function("C.shadowRoot.textContent.includes('A note is at most 2000 characters.')")
        assert pg.errors == []
        pg.context.close()


# ---------------------------------------------------------------- Ryan's own card: the two switches
def test_ryans_card_has_both_switches_on_by_default_and_his_to_turn_off(P):  # noqa: F811
    P.OPTS["pilots"] = [{"name": "james", "portal": True}, {"name": "pilot3"}]
    db = P.pilotdb_start()
    jane = db.find("10001")
    with db.lock:
        db.db.execute("INSERT INTO ai_notes(pid,text,model,basis,at) VALUES(?,?,?,?,?)",
                      (jane, "Picks up LAX layovers fast, mostly on Mondays.", "consultant-test", "stats", "2026-11-15T19:00:00+00:00"))
    lu = "2026-11-15T19:00:00+00:00"
    states = {"sensor.flight_watcher_pilotdb": {"state": "5", "last_updated": lu, "last_changed": lu, "attributes": P.pilotdb_sensor()}}
    built = cards.build("9.9.9", [])
    posts = []
    ep = PS.export_path("james", P.PILOTDB_SHARE)
    with _browser() as b:
        for width, height, scheme in ((390, 844, "light"), (1280, 800, "dark")):
            P.pilotdb_post({"op": "share", "pilot": "james", "on": True})  # each run starts as a fresh install is: on
            P.pilotdb_post({"op": "ai", "on": True})
            ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme)
            html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
                    + ADMIN_JS + "</script><script type='module'>" + built["flight-watcher-pilotdb-card.js"] + "</script></body></html>")

            def serve(route):
                req, url = route.request, route.request.url
                if url == "https://ha.test/":
                    return route.fulfill(status=200, content_type="text/html", body=html)
                if urlsplit(url).path == API:
                    if req.method == "GET":
                        from urllib.parse import parse_qs
                        code, body = P.pilotdb_get({k: v[-1] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()})
                    else:
                        posts.append(json.loads(req.post_data))
                        code, body = P.pilotdb_post(posts[-1])
                    return route.fulfill(status=code, content_type="application/json", body=json.dumps(body))
                return route.fulfill(status=404, body="")
            ctx.route("https://ha.test/**", serve)
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("dialog", lambda d: d.accept())
            pg.goto("https://ha.test/")
            pg.wait_for_function("!!customElements.get('flight-watcher-pilotdb-card')")
            pg.evaluate("(st) => { window.C = mount('flight-watcher-pilotdb-card', {title: 'Pilots'}, st, window.admin); }", states)
            pg.wait_for_function("!!C.shadowRoot.querySelector('[data-share-pilot=james]')")
            t = _txt(pg, "[data-share]")
            assert "Share with james" in t and "On: he sees and searches every pilot, as you do." in t
            assert "On for every pilot with a portal unless you turn it off here." in t and "shared 100%" in t
            assert "pilot3" not in t and "Only me" not in _txt(pg)  # no portal, no switch; the option is gone
            assert pg.evaluate("() => [C.shadowRoot.querySelector('[data-k=share-james]').checked, C.shadowRoot.querySelector('[data-k=ai-on]').checked]") == [True, True]
            assert P.pilotdb_status()["shared_with"] == ["james"] and os.path.exists(ep)
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.locator("flight-watcher-pilotdb-card").first.screenshot(path=os.path.join(SHOTS, f"admin_sharing_{width}_{scheme}.png"))
            # his OFF switch: the file is deleted at once, and it stays off
            n0 = len(posts)
            pg.evaluate("() => C.shadowRoot.querySelector('[data-k=share-james]').click()")
            pg.wait_for_function("C.shadowRoot.querySelector('[data-share]').textContent.includes('Off: you turned it off.')")
            assert posts[n0:] == [{"op": "share", "pilot": "james", "on": False}]
            assert P.pilotdb_status()["shared_with"] == [] and not os.path.exists(ep)
            pg.evaluate("() => C.shadowRoot.querySelector('[data-k=ai-on]').click()")
            pg.wait_for_function("C.shadowRoot.querySelector('[data-ai]').textContent.includes('Off: HOM')")
            assert posts[-1] == {"op": "ai", "on": False} and P.pilotdb_status()["ai"]["on"] is False
            # the AI note on the record: read only, labeled AI, with its model
            pg.evaluate("() => [...C.shadowRoot.querySelectorAll('button.nm')].find((x) => x.textContent === 'Doe, Jane A').click()")
            pg.wait_for_function("!!C.shadowRoot.querySelector('[data-rec]') && C.shadowRoot.querySelector('[data-rec]').textContent.includes('AI note')")
            rt = _txt(pg, "[data-rec]")
            assert "Written by consultant-test" in rt and "Read only; not a human note." in rt and "Picks up LAX layovers fast" in rt
            assert pg.evaluate("() => !!C.shadowRoot.querySelector('[data-rec] .tag.ai')")
            assert pg.evaluate("() => fwContrast(C)")["fails"] == []
            assert pg.evaluate("() => window.calls.length") == 0 and errors == []
            # and on again
            pg.evaluate("() => C.shadowRoot.querySelector('[data-k=share-james]').click()")
            pg.wait_for_function("C.shadowRoot.querySelector('[data-share]').textContent.includes('On: he sees and searches every pilot')")
            assert posts[-1] == {"op": "share", "pilot": "james", "on": True} and os.path.exists(ep)
            ctx.close()



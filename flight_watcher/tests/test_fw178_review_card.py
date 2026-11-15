"""1.7.8 review fixes, the Pilots card in Chromium (each test failed on the builders' commit 65ac158): a late record
read never overwrites a newer save; a long drift line wraps on a phone; on a phone the fields are 16 px and every
button 44 px, each pickup is one wrapped line and the results' flags sit under the name (the flags column is named);
the focus stays where Ryan acted after a write; every message goes to one live region that is never redrawn; a rev bump
while Ryan types leaves the box alone; Restore of a version with a draft in the box asks and then shows it; "Use upload
value" only when an upload has one. Synthetic data only ("Doe, Jane" 10001, 808-555-01xx, example.com)."""
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pilotdb_card import _browser, _click, _open_jane, _page, _pickups, _shot, _states, seeded  # noqa: F401
from test_pilotdb_watcher import P  # noqa: F401

OPEN_ALL = "() => { for (const d of C.shadowRoot.querySelectorAll('details')) d.open = true; }"
ACTIVE = """() => { const a = C.shadowRoot.activeElement; return a ? (a.dataset.k || a.tagName) : document.activeElement.tagName; }"""


def _mount(pg, P, follow=False):  # noqa: F811
    cfg = "{follow: true}" if follow else "{title: 'Pilots'}"
    pg.evaluate(f"(st) => {{ window.C = mount('flight-watcher-pilotdb-card', {cfg}, st, window.admin); }}", _states(P))


def _jane_two_phones(db, jane):
    db.merge_contacts({"uploaded_at": "2026-11-15T08:00:00-10:00", "pilots": [
        {"emp": "10001", "name": "Doe, Jane", "name_full": "Doe, Jane A",
         "phones": [{"label": "mobile", "number": "808-555-0101"}, {"label": "home", "number": "808-555-0111"}],
         "emails": ["jane.alexandra.doe.longer.address@example.com"],
         "hal": {"emp": "10001", "sen": "812", "sen_month": "2026-07", "doh": "2001-05-01", "status": "SLOA",
                 "retire": "2041-03"}}]}, "ryan")
    rec = db.record(jane)
    rec = db.set_field(jane, "phones", [{"label": "mobile", "number": "808-555-0101"}], rec["rev"], why="home line gone")
    db.set_field(jane, "emails", ["jane.doe@example.com"], rec["rev"], why="her short one")
    rec = db.record(jane)
    assert rec["fields"]["phones"]["drift"] and rec["fields"]["emails"]["drift"]


def test_a_late_record_read_never_overwrites_a_newer_save(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 390, 844, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        pg.evaluate("""() => { const f = window.fetch; window.fetch = async (u, o) => { const r = await f(u, o);
          if (window.SLOW && String(u).includes('?pid=')) await new Promise((ok) => setTimeout(ok, 1500)); return r; }; }""")
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]'); t.value = 'My draft about her.'; t.dispatchEvent(new Event('input')); }")
        db.save_notes(jane, "Saved elsewhere first.", db.record(jane)["notes"]["rev"], by="ryan")
        pg.evaluate("() => { window.SLOW = true; }")
        _click(pg, "Save notes")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Not saved: changed by ryan')")
        _click(pg, "Save mine over theirs")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Notes saved.')")
        pg.wait_for_timeout(2500)  # the record read sent with the 409 answers now
        saved = db.record(jane)["notes"]
        later = pg.evaluate("() => ({box: C.shadowRoot.querySelector('textarea[data-k=notes]').value, rev: C._rec.notes.rev})")
        assert saved["text"] == "My draft about her." and later == {"box": saved["text"], "rev": saved["rev"]}
        assert pg.errors == []
        pg.context.close()


def test_a_long_drift_line_wraps_on_a_phone(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    _jane_two_phones(db, jane)
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _page(b, P, 390, 844, scheme, [])
            _mount(pg, P)
            _open_jane(pg)
            drift = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('.tag.w')].map((t) => t.textContent).filter((t) => t.includes(' says '))")
            assert any("home 808-555-0111" in t for t in drift) and any("longer.address" in t for t in drift)
            _shot(pg, f"pilotdb_drift_390_{scheme}")
            pg.evaluate(OPEN_ALL)
            fit = pg.evaluate("() => ({sw: document.documentElement.scrollWidth, iw: innerWidth})")
            assert fit["sw"] <= fit["iw"], fit
            assert pg.evaluate("() => fwContrast(C)")["fails"] == []
            pg.context.close()


def test_phone_fields_are_16px_and_every_button_44px(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 390, 844, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        pg.evaluate("() => C.shadowRoot.querySelector('button[aria-label=\"Edit Status\"]').click()")
        pg.evaluate(OPEN_ALL)
        out = pg.evaluate("""() => ({
          fields: [...C.shadowRoot.querySelectorAll('input:not([type=checkbox]), textarea')].map((e) => getComputedStyle(e).fontSize),
          small: [...C.shadowRoot.querySelectorAll('button, summary, a.ct, label.ck')].filter((x) => { const r = x.getBoundingClientRect(); return r.height && r.height < 43.5; })
            .map((x) => [x.tagName, x.textContent.slice(0, 20), Math.round(x.getBoundingClientRect().height)]) })""")
        assert len(out["fields"]) >= 10 and set(out["fields"]) == {"16px"}, out["fields"]
        assert out["small"] == [], out["small"]
        pg.context.close()
        # a desktop keeps the compact sizes
        pg = _page(b, P, 1280, 800, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        assert pg.evaluate("() => getComputedStyle(C.shadowRoot.querySelector('textarea[data-k=notes]')).fontSize") == "14px"
        pg.context.close()


def test_each_pickup_is_one_wrapped_line_on_a_phone(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 390, 844, "dark", [])
        _mount(pg, P)
        _open_jane(pg)
        out = pg.evaluate("""() => { const l = C.shadowRoot.querySelector('ol.pkl'), t = C.shadowRoot.querySelector('table.pk');
          const box = l.getBoundingClientRect(), card = C.getBoundingClientRect();
          return {list: getComputedStyle(l).display, table: t.getBoundingClientRect().width, lines: [...l.querySelectorAll('li')].map((x) => x.textContent),
                  inside: box.right <= card.right + 1}; }""")
        assert out["list"] == "block" and out["table"] == 0 and out["inside"], out
        # every column's value is on the line: #, the time and weekday, pairing, start, days, layover with its running
        # count (or turn), credit, report, speed, in flight
        line = next(x for x in out["lines"] if "H3603" in x)
        for part in ("#3", "H3603", "starts 2026-11-12 Thu", "3-day", "LAX (2)", "credit 15:30", "report 08:00",
                     "picked up in 5m 00s", "in flight"):
            assert part in line, (part, line)
        assert any("turn" in x for x in out["lines"])
        pg.evaluate("() => C.shadowRoot.querySelector('ol.pkl').scrollIntoView()")
        _shot(pg, "pilotdb_pickups_390_dark")
        pg.context.close()
        pg = _page(b, P, 1280, 800, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        assert pg.evaluate("() => getComputedStyle(C.shadowRoot.querySelector('ol.pkl')).display") == "none"
        assert pg.evaluate("() => C.shadowRoot.querySelectorAll('table.pk th').length") == 10
        pg.context.close()


def test_the_results_flags_show_on_a_phone_and_the_column_is_named(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 390, 844, "light", [])
        _mount(pg, P)
        pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 5")
        vis = pg.evaluate("""() => { const w = C.shadowRoot.querySelector('.wrap').getBoundingClientRect();
          return [...C.shadowRoot.querySelectorAll('tbody tr.pick .tag')].filter((t) => t.getBoundingClientRect().width)
            .map((t) => [t.textContent, t.getBoundingClientRect().right <= w.right + 1]); }""")
        assert vis and all(v for _t, v in vis), vis
        assert pg.evaluate("() => { const w = C.shadowRoot.querySelector('.wrap'); return w.scrollWidth <= w.clientWidth + 1; }")
        th = pg.evaluate("() => [...C.shadowRoot.querySelectorAll('table.rt thead th')].map((x) => x.textContent)")
        assert th[-1] == "Flags"
        _shot(pg, "pilotdb_results_flags_390_light")
        q = pg.evaluate("() => { const q = C.shadowRoot.querySelector('input[type=search]'); const c = document.createElement('canvas').getContext('2d'); "
                        "const s = getComputedStyle(q); c.font = `${s.fontSize} ${s.fontFamily}`; return {fits: c.measureText(q.placeholder).width <= q.clientWidth - 16, ph: q.placeholder}; }")
        assert q["fits"], q
        pg.context.close()
        pg = _page(b, P, 1280, 800, "light", [])
        _mount(pg, P)
        pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 5")
        assert pg.evaluate("() => C.shadowRoot.querySelector('input[type=search]').placeholder") == \
            'Name, employee #, s812 for a Sen #, "text" in notes'
        pg.context.close()


def test_the_focus_stays_where_ryan_acted(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 1280, 800, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        # a field: Edit, type, Save with the keyboard: the focus comes back to its Edit button
        pg.evaluate("() => C.shadowRoot.querySelector('button[aria-label=\"Edit Status\"]').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_function("!!C.shadowRoot.querySelector('input[data-k=edit-status]')")
        assert pg.evaluate(ACTIVE) == "edit-status"
        pg.keyboard.press("Control+A")
        pg.keyboard.type("A")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=f-status-save]').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Status saved.')")
        assert pg.evaluate(ACTIVE) == "f-status-edit"
        # Cancel: back to Edit
        pg.keyboard.press("Enter")
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-k=f-status-cancel]')")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=f-status-cancel]').focus()")
        pg.keyboard.press("Enter")
        assert pg.evaluate(ACTIVE) == "f-status-edit"
        # Add to the log: the focus stays on Add
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=entry]'); t.value = 'Keyboard entry.'; t.dispatchEvent(new Event('input')); }")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=entry-add]').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Keyboard entry.')")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Added.')")
        assert pg.evaluate(ACTIVE) == "entry-add"
        # Hide it: the focus goes to its Restore; Restore: back to Hide; Take back: its entry
        eid = next(e["eid"] for e in db.record(jane)["entries"] if e["text"] == "Keyboard entry.")
        pg.evaluate("(k) => C.shadowRoot.querySelector(`[data-k=${k}]`).focus()", f"ent-{eid}-hide")
        pg.keyboard.press("Enter")
        pg.wait_for_function("(eid) => C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('hidden by ryan')", arg=eid)
        assert pg.evaluate(ACTIVE) == f"ent-{eid}-restore"
        pg.keyboard.press("Enter")
        pg.wait_for_function("(eid) => !C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('hidden by ryan')", arg=eid)
        assert pg.evaluate(ACTIVE) == f"ent-{eid}-hide"
        pg.evaluate("(k) => C.shadowRoot.querySelector(`[data-k=${k}]`).focus()", f"ent-{eid}-retract")
        pg.keyboard.press("Enter")
        pg.wait_for_function("(eid) => C.shadowRoot.querySelector(`[data-eid=${eid}]`).textContent.includes('taken back by ryan')", arg=eid)
        assert pg.evaluate(ACTIVE) == f"ent-{eid}"
        # Save notes: the focus stays on it, and the next Tab goes on from there (never back to the top)
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]'); t.value = 'Keyboard notes.'; t.dispatchEvent(new Event('input')); }")
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=notes-save]').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Notes saved.')")
        assert pg.evaluate(ACTIVE) == "notes-save"
        pg.keyboard.press("Tab")
        assert pg.evaluate(ACTIVE) != "close"
        # Close: back to her row in the results
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=close]').focus()")
        pg.keyboard.press("Enter")
        assert pg.evaluate(ACTIVE) == f"nm-{jane}"
        assert pg.errors == []
        pg.context.close()


def test_every_message_goes_to_one_live_region_that_is_never_redrawn(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 1280, 800, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        pg.evaluate("() => { window.LIVE = C.shadowRoot.querySelector('[data-live]'); }")
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=entry]'); t.value = 'Live region check.'; t.dispatchEvent(new Event('input')); }")
        _click(pg, "Add")
        pg.wait_for_function("window.LIVE.textContent === 'Added.'")
        out = pg.evaluate("""() => ({same: C.shadowRoot.querySelector('[data-live]') === window.LIVE && window.LIVE.isConnected,
          role: window.LIVE.getAttribute('role'), polite: window.LIVE.getAttribute('aria-live'),
          inRecord: !!C.shadowRoot.querySelector('[data-rec] [role=status], [data-rec] [aria-live]'),
          shown: C.shadowRoot.querySelector('[data-msg=log]').textContent})""")
        assert out == {"same": True, "role": "status", "polite": "polite", "inRecord": False, "shown": "Added."}
        pg.context.close()


def test_a_rev_bump_while_typing_leaves_the_notes_box_alone(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    with _browser() as b:
        pg = _page(b, P, 390, 844, "light", [])
        _mount(pg, P)
        _open_jane(pg)
        pg.evaluate("""() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]'); window.T0 = t; t.focus();
          t.style.height = '260px'; t.value = 'Line\\n'.repeat(40) + 'typing...'; t.dispatchEvent(new Event('input')); }""")
        rows = [{"key": "H3699|20Nov", "emp": "10001", "name": "Doe, Jane", "pos": "FO", "at": "2026-11-15T01:00:00+00:00",
                 "pairing": "H3699", "start": "2026-11-20", "days": 1, "lay": "", "turn": True, "credit": "6:00",
                 "report": "07:00", "dow": "Fri", "secs": 30, "approx": False, "inflt": None}]
        before = db.rev
        db.sync_pickups(_pickups() + rows)  # a picker scores a pickup: the database's rev moves, the sensor follows
        assert db.rev > before
        st = _states(P)
        st["sensor.flight_watcher_pilotdb"]["last_updated"] = "2026-11-15T19:05:00+00:00"
        pg.evaluate("(st) => { C.hass = mkHass(st, window.admin); }", st)
        pg.wait_for_function("!!C._pendingRec")
        out = pg.evaluate("""() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]');
          return {same: t === window.T0, height: t.style.height, focused: C.shadowRoot.activeElement === t, draft: t.value.endsWith('typing...')}; }""")
        assert out == {"same": True, "height": "260px", "focused": True, "draft": True}
        # the focus leaves the box: the record is drawn again (her new pickup shows), the draft and the height kept
        pg.evaluate("() => C.shadowRoot.querySelector('[data-k=notes-save]').focus()")
        pg.wait_for_function("C.shadowRoot.textContent.includes('5 pickups')")
        out = pg.evaluate("""() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]');
          return {height: t.style.height, draft: t.value.endsWith('typing...'), focus: C.shadowRoot.activeElement.dataset.k}; }""")
        assert out == {"height": "260px", "draft": True, "focus": "notes-save"}
        pg.context.close()


def test_restore_a_version_with_a_draft_asks_then_shows_it(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    db.save_notes(jane, "Version two.", db.record(jane)["notes"]["rev"])
    with _browser() as b:
        pg = _page(b, P, 820, 1180, "light", [])
        asked = []
        pg.on("dialog", lambda d: asked.append(d.message))
        _mount(pg, P)
        _open_jane(pg)
        pg.evaluate("() => { const t = C.shadowRoot.querySelector('textarea[data-k=notes]'); t.value = 'Half a thought'; t.dispatchEvent(new Event('input')); }")
        pg.evaluate(OPEN_ALL)
        pg.evaluate("""() => { const e = [...C.shadowRoot.querySelectorAll('[data-rec] details .ent')].find((x) => x.textContent.includes('Commutes from Maui.'));
          [...e.querySelectorAll('button')].find((b) => b.textContent === 'Restore').click(); }""")
        pg.wait_for_function("C.shadowRoot.textContent.includes('That version is the notes again')")
        saved = db.record(jane)["notes"]["text"]
        assert saved == "Commutes from Maui.\nGood on reserve."
        assert asked == ["Restore this version? Your unsaved text in the Notes box is replaced by it."]
        assert pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=notes]').value") == saved
        _shot(pg, "pilotdb_restore_version_820_light")
        pg.context.close()


def test_use_upload_value_only_when_an_upload_has_one(seeded):  # noqa: F811
    P, db, jane, roe = seeded
    db.set_field(roe, "seat", "FO", db.record(roe)["rev"], why="flies FO")
    with _browser() as b:
        pg = _page(b, P, 390, 844, "light", [])
        asked = []
        pg.on("dialog", lambda d: asked.append(d.message))
        _mount(pg, P)
        pg.wait_for_function("C.shadowRoot.querySelectorAll('tbody tr.pick').length >= 5")
        pg.evaluate("(pid) => C._open(pid, true)", roe)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-rec]')")
        btns = pg.evaluate("""() => Object.fromEntries([...C.shadowRoot.querySelectorAll('.fl')].map((f) => [f.querySelector('.fk').textContent,
          [...f.querySelectorAll('button')].map((b) => b.textContent)]))""")
        assert btns["Name"] == ["Edit"] and btns["Seat"] == ["Edit", "Remove my edit"]
        _shot(pg, "pilotdb_hand_only_390_light")
        _click(pg, "Remove my edit")
        pg.wait_for_function("C.shadowRoot.textContent.includes('Seat: your edit is removed.')")
        assert asked == ["Remove your edit of Seat? No upload has a value for it, so it is left empty."]
        assert db.record(roe)["fields"]["seat"]["value"] == "" and db.record(roe)["fields"]["name"]["value"]
        # Jane's DOH has an upload value: Use upload value as before
        pg.evaluate("(pid) => C._open(pid, true)", jane)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Doe, Jane A')")
        doh = pg.evaluate("""() => [...[...C.shadowRoot.querySelectorAll('.fl')].find((f) => f.querySelector('.fk').textContent === 'DOH')
          .querySelectorAll('button')].map((b) => b.textContent)""")
        assert doh == ["Edit", "Use upload value", "Keep my edit"]
        pg.context.close()

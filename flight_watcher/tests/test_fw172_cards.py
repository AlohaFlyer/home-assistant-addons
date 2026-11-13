"""1.7.2 cards, in Chromium (Playwright) on the portal's page and theme (test_fw171_cards' harness): the pilot's uploads
card (FW-0066, contract 1 revision 3) at 390 px light and dark, its upload in upload/pdf parts that pass the contract's
shape; the admin's uploads card with the pilots' uploads and Approve / Remove / Reject; the admin's recall paste that
asks before it replaces a day on file (F#78); the pilot lookup that sends the pilot/set shape only (F#49). Made-up
data and names only."""
import base64
import hashlib
import json
import os

import pytest

import portal as PT
from test_fw171_cards import P, _browser, _card, _page, _pilot, _s

SHOTS = os.environ.get("FW_172_SHOTS", "")  # a folder: the renders are saved there as PNGs


def _shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


def _view(pending=True):
    return {"friendly_name": "Pilot uploads", "busy": False, "receiving": None,
            "months": [{"month": "2026-11", "name": "November 2026",
                        "pairings": {"on_file": True, "by": "the admin", "pending": False},
                        "award": {"on_file": True, "by": "you", "pending": False}},
                       {"month": "2026-12", "name": "December 2026",
                        "pairings": {"on_file": True, "by": "the admin", "pending": pending},
                        "award": {"on_file": False, "by": "", "pending": False}},
                       {"month": "2027-01", "name": "January 2027",
                        "pairings": {"on_file": False, "by": "", "pending": False},
                        "award": {"on_file": False, "by": "", "pending": False}}],
            "mine": [{"id": "uDemo0000000000001", "kind": "pairings", "month": "2026-12", "state": "pending",
                      "size": 2100000, "at": "2026-11-10T09:00:00-10:00", "decided_at": None}],
            "answers": [{"uid": "uDemo0000000000001", "ok": True, "state": "pending", "at": "2026-11-10T19:00:00Z",
                         "message": "Held for the admin: a December 2026 pairings package is on file already. Yours "
                                    "is used only if the admin approves it."}],
            "limits": {"file_bytes": 4194304, "per_day": 4, "used_today": 1, "left_today": 3, "chunk_chars": 60000,
                       "chunk_parts": 94, "stale_s": 120, "kinds": ["pairings", "award"]}}


def _states(view=None):
    return {f"sensor.{P}_pilot_uploads": _s("1", view or _view())}


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_pilot_uploads_card_at_390_px(scheme):
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390, scheme=scheme)
        got = pg.evaluate("""(st) => { const c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st);
          const r = c.shadowRoot; return {text: r.textContent.replace(/\\s+/g, ' '), fit: fwFits(c), con: fwContrast(c),
            months: [...r.querySelectorAll('[data-month] option')].map((o) => o.textContent),
            picked: r.querySelector('[data-month]').value,
            kinds: [...r.querySelectorAll('[data-kind] option')].map((o) => o.value),
            btn: r.querySelector('[data-up]').getBoundingClientRect().height,
            font: getComputedStyle(r.querySelector('[data-kind]')).fontSize}; }""", _states())
        _shot(pg, f"pilot_uploads_390_{scheme}")
    assert got["fit"]["right"] <= 390 and got["fit"]["page"] <= 390 and got["fit"]["inner"] <= 0
    assert got["con"]["fails"] == [], got["con"]["fails"]
    assert got["months"] == ["November 2026", "December 2026", "January 2027"] and got["picked"] == "2026-12"
    assert got["kinds"] == ["pairings", "award"]  # never the seniority list or the contact list
    t = got["text"]
    assert "Pairings package: on file from the admin; your copy waits for the admin" in t
    assert "Award: on file from you" in t and "Award: not on file yet" in t
    assert "Up to 4 MB a file and 4 uploads a day (3 left today)" in t and "Held for the admin" not in t  # no send yet
    assert "never the seniority list or the contact list" in t and "Ryan" not in t
    assert got["btn"] >= 44 and got["font"] == "16px"  # a phone: 44 px buttons, 16 px fields (no iOS zoom)


def _pdf(n):
    body = b"%PDF-1.4\n" + bytes((i * 37) % 251 for i in range(n)) + b"\n%%EOF\n"
    return body


def test_pilot_uploads_card_sends_parts_the_contract_takes():
    raw = _pdf(50000)  # two parts of base64
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        pg.evaluate("""(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""", _states())
        inp = pg.evaluate_handle("() => c.shadowRoot.querySelector('[data-pdf]')")
        inp.as_element().set_input_files(files=[{"name": "dec.pdf", "mimeType": "application/pdf", "buffer": raw}])
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => window.calls.length >= 2", timeout=15000)
        pg.wait_for_function("() => /Checking|checking/.test(c.shadowRoot.textContent)", timeout=5000)
        calls = pg.evaluate("() => window.calls")
        text = pg.evaluate("() => c.shadowRoot.textContent")
    assert [c[:2] for c in calls] == [["mqtt", "publish"]] * 2
    parts = []
    for c in calls:
        assert c[2]["topic"] == f"{P}/upload/pdf"
        d = PT.check_shape("upload/pdf", c[2]["payload"])  # the spool's and HOM's own check
        assert len(json.dumps({"sub": "upload/pdf", "payload": c[2]["payload"]}).encode()) < PT.CAPS["cmd"]
        parts.append(d)
    assert [d["part"] for d in parts] == [1, 2] and {d["parts"] for d in parts} == {2}
    assert {(d["kind"], d["month"], d["size"], d["sha"], d["uid"]) for d in parts} == {
        ("pairings", "2026-12", len(raw), hashlib.sha256(raw).hexdigest(), parts[0]["uid"])}
    assert base64.b64decode("".join(d["data"] for d in parts)) == raw
    assert "Sending the December 2026 pairings package" in text


def test_pilot_uploads_card_refuses_before_sending():
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        out = {}
        for name, raw in (("gif", b"GIF89a not a pdf"), ("big", b"%PDF-1.4\n" + b"0" * (4 * 1024 * 1024))):
            pg.evaluate("""(st) => { document.querySelector('.view').innerHTML = '';
              window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); window.calls = []; }""", _states())
            inp = pg.evaluate_handle("() => c.shadowRoot.querySelector('[data-pdf]')")
            inp.as_element().set_input_files(files=[{"name": f"{name}.pdf", "mimeType": "application/pdf",
                                                     "buffer": raw}])
            pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
            pg.wait_for_function("() => c.shadowRoot.querySelector('[data-msg]').textContent.length > 0")
            out[name] = pg.evaluate("() => [c.shadowRoot.querySelector('[data-msg]').textContent, window.calls.length]")
    assert out["gif"] == ["That file is not a PDF.", 0]
    assert out["big"][0].startswith("That file is 4.2 MB: up to 4 MB") and out["big"][1] == 0


# ---------------------------------------------------------------- the admin's uploads card
def _uploads_sensor():
    return {"files": [{"name": "2026-12_pairings.pdf", "kind": "pairings", "month": "2026-12", "day": "",
                       "size": 1795960, "uploaded_at": "2026-11-07T01:34:00-10:00", "has_text": True}],
            "seniority": None, "contacts": None, "version": "1.7.2", "wanted": [],
            "pilot_uploads": [
                {"id": "uDemo0000000000001", "who": "pilot2", "kind": "pairings", "month": "2026-12",
                 "state": "pending", "at": "2026-11-10T09:00:00-10:00", "size": 2100000, "decided_at": "",
                 "sha": "0123456789ab", "restores": False},
                {"id": "uDemo0000000000002", "who": "pilot2", "kind": "award", "month": "2026-12", "state": "live",
                 "at": "2026-11-10T08:00:00-10:00", "size": 900000, "decided_at": "", "sha": "ba9876543210",
                 "restores": False},
                {"id": "uDemo0000000000003", "who": "pilot2", "kind": "award", "month": "2026-11",
                 "state": "rejected", "at": "2026-11-01T08:00:00-10:00", "size": 800000,
                 "decided_at": "2026-11-01T09:00:00-10:00", "sha": "aaaaaaaaaaaa", "restores": False}]}


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_admins_uploads_card_lists_pilot_uploads_with_their_buttons(scheme):
    st = {"sensor.flight_watcher_uploads": _s("1", _uploads_sensor()),
          "sensor.flight_watcher_upload_status": _s("done", {})}
    with _browser() as b:
        pg = _page(b, [_card("uploads-card", pilot=False)], width=390, scheme=scheme)
        got = pg.evaluate("""(st) => { window.c = mount('flight-watcher-uploads-card', {}, st);
          const r = c.shadowRoot, sec = r.querySelector('[data-pilot]');
          return {text: sec.textContent.replace(/\\s+/g, ' '), fit: fwFits(c), con: fwContrast(c),
            btns: [...sec.querySelectorAll('button[data-act]')].map((x) => [x.dataset.act, x.dataset.id])}; }""", st)
        _shot(pg, f"admin_uploads_pilot_section_390_{scheme}")
        asked = pg.evaluate("""async () => { window.asked = []; window.confirm = (t) => { asked.push(t); return false; };
          c.shadowRoot.querySelector('button[data-act="approve"]').click(); await new Promise((ok) => setTimeout(ok, 50));
          const none = window.calls.length;
          window.confirm = (t) => { asked.push(t); return true; };
          c.shadowRoot.querySelector('button[data-act="remove"]').click(); await new Promise((ok) => setTimeout(ok, 50));
          return {none, asked, calls: window.calls}; }""")
    assert got["fit"]["right"] <= 390 and got["fit"]["page"] <= 390 and got["con"]["fails"] == [], got["con"]["fails"]
    assert got["btns"] == [["approve", "uDemo0000000000001"], ["reject", "uDemo0000000000001"],
                           ["remove", "uDemo0000000000002"]]  # nothing to do on a rejected one
    t = got["text"]
    assert "Pilot uploads" in t and "Pairings package Dec 2026 from pilot2: waiting for you" in t
    assert "Award Dec 2026 from pilot2: in use (nothing was on file)" in t and "rejected" in t
    assert asked["none"] == 0  # Cancel sends nothing
    assert asked["asked"][0].startswith("Use pilot2's Pairings package Dec 2026 instead of the one on file?")
    assert asked["asked"][1].startswith("Remove pilot2's Award Dec 2026?")
    (dom, svc, data), = asked["calls"]
    assert (dom, svc, data["topic"]) == ("mqtt", "publish", "flight_watcher/upload/decide")
    assert json.loads(data["payload"]) == {"id": "uDemo0000000000002", "action": "remove"}


def test_a_pilots_copy_of_the_admins_uploads_card_has_no_pilot_section():
    st = _pilot({"sensor.flight_watcher_uploads": _s("1", {k: v for k, v in _uploads_sensor().items()
                                                             if k != "pilot_uploads"})})
    with _browser() as b:
        pg = _page(b, [_card("uploads-card")], width=390)
        html = pg.evaluate("""(st) => mount('flight-watcher-uploads-card-pilot2', {}, st)
          .shadowRoot.querySelector('[data-pilot]').innerHTML""", st)
    assert html == ""


# ---------------------------------------------------------------- the admin's recall paste (F#78)
def test_the_admins_recall_paste_names_the_dates_on_file_first():
    st = {"sensor.flight_watcher_recall_o75": _s("0", {"days": [{"date": "2026-11-03", "file": "ok", "verdicts": []},
                                                                {"date": "2026-11-04", "file": "blank", "verdicts": []}],
                                                       "me": {"sen": 500, "seat": "FO"}, "open": 0, "alert": 0}),
          "sensor.flight_watcher_state": _s("idle", {"role": "admin"})}
    paste = json.dumps([{"date": "2026-11-04", "rows": []}, {"date": "2026-11-05", "rows": []},
                        {"date": "2026-11-03", "rows": []}])
    with _browser() as b:
        pg = _page(b, [_card("recall-card", pilot=False)], width=390)
        got = pg.evaluate("""async ([st, paste]) => { const c = mount('flight-watcher-recall-card', {}, st);
          const r = c.shadowRoot, go = () => { r.querySelector('[data-paste]').value = paste; r.querySelector('[data-paste-go]').click(); };
          const asked = []; window.confirm = (t) => { asked.push(t); return false; };
          go(); const cancel = [r.querySelector('[data-paste-go]').textContent, window.calls.length];
          window.confirm = (t) => { asked.push(t); return true; };
          go(); const sent = window.calls.length;
          r.querySelector('[data-paste]').value = JSON.stringify({date: '2026-11-06', rows: []});
          r.querySelector('[data-paste-go]').click();
          return {asked, cancel, sent, calls: window.calls.map((x) => x[2])}; }""", [st, paste])
    assert got["asked"] == ["Replace the recall lists already on file for Tue Nov 3, Wed Nov 4? The pasted list takes "
                            "their place."] * 2  # the new day alone (Nov 6) asks nothing
    assert got["cancel"] == ["Not sent", 0] and got["sent"] == 1 and len(got["calls"]) == 2
    assert all(c["topic"] == "flight_watcher/recall/set" for c in got["calls"])
    assert json.loads(got["calls"][1]["payload"])["date"] == "2026-11-06"


def test_a_pilots_recall_card_has_no_paste():
    st = _pilot({"sensor.flight_watcher_recall_o75": _s("0", {"days": [], "me": {}, "open": 0, "alert": 0}),
                 "sensor.flight_watcher_state": _s("idle", {"role": "pilot"})})
    with _browser() as b:
        pg = _page(b, [_card("recall-card")], width=390)
        n = pg.evaluate("""(st) => mount('flight-watcher-recall-card-pilot2', {}, st)
          .shadowRoot.querySelectorAll('[data-paste]').length""", st)
    assert n == 0


# ---------------------------------------------------------------- the pilot lookup's shape (F#49)
def test_the_pilot_lookup_sends_the_pilot_set_shape_only():
    st = {"sensor.flight_watcher_pilot_schedule": _s("", {})}
    sends = [{"emp": "10001", "name": "Doe, Jane " + "x" * 80, "extra": 1},
             {"q": "Doe\nJane"}, {"emp": "123456789"}, {"pick": "0123456789ab", "name": "Doe, Jane"},
             {"q": "  "}, {"emp": "١٢٣"}]
    with _browser() as b:
        pg = _page(b, [_card("pilot-card", pilot=False)], width=390)
        calls = pg.evaluate("""async ([st, sends]) => { mount('flight-watcher-pilot-card', {entity: 'sensor.flight_watcher_pilot_schedule'}, st);
          for (const d of sends) { window.dispatchEvent(new CustomEvent('flight-watcher-pilot', {detail: d}));
            await new Promise((ok) => setTimeout(ok, 20)); }
          return window.calls.map((x) => x[2]); }""", [st, sends])
    got = [json.loads(c["payload"]) for c in calls]
    assert all(c["topic"] == "flight_watcher/pilot/set" for c in calls)
    assert got == [{"emp": "10001", "name": ("Doe, Jane " + "x" * 80)[:60]}, {"q": "Doe Jane"},
                   {"pick": "0123456789ab", "name": "Doe, Jane"}]
    for c in calls:
        PT.check_shape("pilot/set", c["payload"])

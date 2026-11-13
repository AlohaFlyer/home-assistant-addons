"""1.7.2: the fixes from the adversarial reviews of contract 1 revision 3 (authorization and privacy, untrusted input,
and the third pass). Each test fails without its fix:
- a pilot's upload id is never the record's id: the Watcher mints it, a reused uid is refused, Approve installs only
  the bytes that were checked (A1, B2);
- Remove after an Approve gives the file that comes back its Remove again (B3, C1);
- the package parsers take linear time on a crafted text, and the text is bounded before any parser sees it (B1);
- an award whose last line is cut off is "not read", never an IndexError that stops every later award (B4);
- the extractor runs as nobody when the Watcher runs as root, and its output is never followed through a link (A2);
- schedule_unread counts its 6 h from the last held tick and goes at most once in 24 h (C2, C3);
- an upload dropped for no part, or cut off by a restart, gets an answer (C5);
- a removed award is no longer a looked-up pilot's .001 (C6);
- the rollback notes say how to keep a CrewTrac refusal on a rollback to 1.7.1 (C4).
Made-up PDFs, texts, names ("Doe") and numbers only."""
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime

import pytest

import pdfs as PDF
import pilotpdf as PP
import pilotver as PV
import roles
import web
from pdfmake import LEGS, award_lines, make_pdf, package_lines
from test_crew_index import W  # noqa: F401  (the watcher fixture of the FW-0069 tests)
from test_fw172_uploads import AWARD, EMP, PKG, PKG_NEW, Msg, _answer, _chunks, _send, inst  # noqa: F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
HST = PP.HST
LIM = roles.PILOT_UPLOAD_LIMITS


def _rv(tmp_path, t=None):
    t = t or [1.8e9]
    rv = PP.Review(str(tmp_path / "uploads"), str(tmp_path / "review"), now=lambda: t[0])
    os.makedirs(rv.uploads, exist_ok=True)
    return rv, t


def _txt(tmp_path, body="text"):
    p = tmp_path / f"t{time.monotonic_ns()}.txt"
    p.write_text(body)
    return str(p)


def _on_file(rv, name):
    return open(rv.live(name)[0], "rb").read()


# ---------------------------------------------------------------- A1 / B2: the pilot's uid is never the record's id
def test_a_reused_uid_is_refused_and_the_record_id_is_the_watchers_own(tmp_path):
    rv, t = _rv(tmp_path)
    rv.record_admin("pairings", "2026-12", "0" * 64, 1)
    open(rv.live("2026-12_pairings")[0], "wb").write(b"%PDF-admin")
    open(rv.live("2026-12_pairings")[1], "w").write("admin")
    u = "uSameId0000000001"
    held = rv.store("pilot2", "pairings", "2026-12", b"%PDF-dec", _txt(tmp_path), u, {"pairings": 110})
    assert held["state"] == "pending" and held["uid"] == u and held["id"] != u
    assert re.fullmatch(roles.UPLOAD_ID_PATTERN, held["id"])
    assert os.path.exists(rv.q(held["id"])[0]) and not os.path.exists(rv.q(u)[0])
    # review scenario A: the same uid for January's award would have overwritten the held December copy
    t[0] += 60
    with pytest.raises(PP.Refused, match="used before"):
        rv.store("pilot2", "award", "2027-01", b"%PDF-jan-award", _txt(tmp_path), u, {"items": 2})
    assert open(rv.q(held["id"])[0], "rb").read() == b"%PDF-dec"
    ok, _, rec = rv.decide(held["id"], "approve")
    assert ok and _on_file(rv, "2026-12_pairings") == b"%PDF-dec"
    assert hashlib.sha256(_on_file(rv, "2026-12_pairings")).hexdigest() == rec["sha256"]
    # scenario B: a held upload's uid again while nothing is on file for another kind: refused, not live unannounced
    t[0] += 60
    with pytest.raises(PP.Refused, match="used before"):
        rv.store("pilot2", "award", "2026-12", b"%PDF-dec-award", _txt(tmp_path), u, {"items": 2})
    assert not os.path.exists(rv.live("2026-12_award")[0])
    # two uploads, two uids: two ids
    a = rv.store("pilot2", "award", "2026-12", b"%PDF-dec-award", _txt(tmp_path), "uOther00000000001", {})
    assert a["state"] == "live" and a["id"] not in (held["id"], "uOther00000000001")


def test_approve_installs_only_the_bytes_that_were_checked(tmp_path):
    rv, t = _rv(tmp_path)
    first = rv.store("pilot2", "pairings", "2026-12", b"%PDF-first", _txt(tmp_path), "uFirst00000000001", {})
    held = rv.store("pilot2", "pairings", "2026-12", b"%PDF-second", _txt(tmp_path), "uSecond0000000001", {})
    assert (first["state"], held["state"]) == ("live", "pending")
    open(rv.q(held["id"])[0], "wb").write(b"%PDF-other bytes")  # anything that changed the held copy
    ok, msg, rec = rv.decide(held["id"], "approve")
    assert not ok and "not the file that was checked" in msg and rec["state"] == "rejected"
    assert _on_file(rv, "2026-12_pairings") == b"%PDF-first" and not os.path.exists(rv.q(held["id"])[0])


def test_the_pilots_two_uploads_with_one_uid_through_the_watcher(inst):
    """End to end: December's package used at once, then January's award with the same uid: refused, so Ryan's push
    names every file in use and each can be removed."""
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2026-12", uid="uReuse00000000001"))
    assert _answer(W, "uReuse00000000001")["state"] == "live"
    jan = make_pdf(award_lines("January 2027", emp=EMP))
    W._PUP["refused"].clear()
    _send(W, _chunks(jan, "award", "2027-01", uid="uReuse00000000001"))
    a = _answer(W, "uReuse00000000001")
    assert a["state"] == "error" and "used before" in a["message"]
    assert not os.path.exists(os.path.join(inst.up, "2027-01_award.pdf"))
    _send(W, _chunks(jan, "award", "2027-01", uid="uFresh00000000001"))
    assert _answer(W, "uFresh00000000001")["state"] == "live"
    A = inst("")
    sent = A.pilot_upload_announce()
    assert sorted(e["file"] for e in sent) == ["2026-12_pairings.pdf", "2027-01_award.pdf"]
    assert len({e["id"] for e in sent}) == 2 and not {e["id"] for e in sent} & {"uReuse00000000001",
                                                                                 "uFresh00000000001"}
    for e in sent:
        A.upload_decide_cmd(json.dumps({"id": e["id"], "action": "remove"}))
    assert not [n for n in os.listdir(inst.up) if n.endswith(".pdf")]


# ---------------------------------------------------------------- B3 / C1: Remove after Approve
def test_remove_after_approve_gives_the_file_back_its_remove(tmp_path):
    rv, t = _rv(tmp_path)
    L = rv.store("pilot2", "pairings", "2026-12", b"%PDF-L", _txt(tmp_path), "uLLLLLLLLLLLLLLL1", {})
    t[0] += 60
    P = rv.store("pilot2", "pairings", "2026-12", b"%PDF-P", _txt(tmp_path), "uPPPPPPPPPPPPPPP1", {})
    t[0] += 60
    assert rv.decide(P["id"], "approve")[0]
    t[0] += 60
    ok, msg, _ = rv.decide(P["id"], "remove")
    assert ok and "is back" in msg and _on_file(rv, "2026-12_pairings") == b"%PDF-L"
    states = {r["id"]: r["state"] for r in rv.records()}
    assert states[L["id"]] == "live" and states[P["id"]] == "removed"  # the file in use is L's again
    assert rv.load()["files"]["2026-12_pairings"]["id"] == L["id"]
    t[0] += 60
    ok, msg, _ = rv.decide(L["id"], "remove")
    assert ok and "nothing is on file" in msg and not os.path.exists(rv.live("2026-12_pairings")[0])


def test_remove_walks_back_a_chain_of_approves(tmp_path):
    rv, t = _rv(tmp_path)
    ids = []
    for n, body in enumerate((b"%PDF-1", b"%PDF-2", b"%PDF-3")):
        t[0] += 60
        r = rv.store("pilot2", "pairings", "2026-12", body, _txt(tmp_path), f"uChain{n}0000000000", {})
        ids.append(r["id"])
        if n:
            assert rv.decide(r["id"], "approve")[0]
    for k, back in ((2, b"%PDF-2"), (1, b"%PDF-1")):
        t[0] += 60
        assert rv.decide(ids[k], "remove")[0] and _on_file(rv, "2026-12_pairings") == back
    assert {r["id"]: r["state"] for r in rv.records()}[ids[0]] == "live"
    assert rv.decide(ids[0], "remove")[0] and not os.path.exists(rv.live("2026-12_pairings")[0])


def test_a_restored_file_that_is_not_its_record_keeps_no_pilots_name(tmp_path):
    rv, t = _rv(tmp_path)
    L = rv.store("pilot2", "pairings", "2026-12", b"%PDF-L", _txt(tmp_path), "uLLLLLLLLLLLLLLL1", {})
    P = rv.store("pilot2", "pairings", "2026-12", b"%PDF-P", _txt(tmp_path), "uPPPPPPPPPPPPPPP1", {})
    assert rv.decide(P["id"], "approve")[0]
    kept = os.path.join(rv.rdir, next(r for r in rv.records() if r["id"] == P["id"])["prev"] + ".pdf")
    open(kept, "wb").write(b"%PDF-changed in rollback")
    assert rv.decide(P["id"], "remove")[0]
    f = rv.load()["files"]["2026-12_pairings"]
    assert f["how"] == "restored" and f["id"] == "" and {r["id"]: r["state"] for r in rv.records()}[L["id"]] == \
        "replaced"


# ---------------------------------------------------------------- B1: linear parsers, bounded text
def _crafted(pre=0, feeds=0, cal=0):
    """A made-up December package: the title, then 'January 1' and feeds form feeds (empty pages), pre lines before the
    first header with no rule, cal long blank lines inside the first A332 HNL block."""
    pl = package_lines()
    head = pl[:1] + (["January 1" + "\f" * feeds] if feeds else []) + pl[1:2]  # before the period line, as reviewed
    body = pl[3:]
    if cal:
        body = body[:2] + [" " * (PP.LINE_CHARS - 1) + "x"] * cal + body[2:]
    return "\n".join(head + ["filler line"] * pre + body) + "\n"


@pytest.mark.parametrize("kw", [{"feeds": 400}, {"pre": 30000}, {"cal": 150}])
def test_the_package_parsers_take_linear_time_on_a_crafted_text(kw):
    text = _crafted(**kw)
    PP.text_shape(text)  # within the bounds: the parsers must be quick on it, not refuse it
    t = time.perf_counter()
    assert PP.check_pairings(text, "2026-12") == {"pairings": 110, "a332": 3}
    pj = PDF.package_json(text, "x")
    det = PDF.package_details(text)
    took = time.perf_counter() - t
    assert pj["month"] == "2026-12" and len(pj["rows"]) == 3 and "H9000" in det
    assert took < 1.0, f"{kw}: {took:.1f} s"


def test_the_linear_day_cells_and_period_match_the_old_patterns():
    rnd = random.Random(1772)
    cells = [" ", " ", "1", "2", "-", "x", "\t", "\f", " ", "٣"]
    for _ in range(50000):
        ln = "".join(rnd.choice(cells) for _ in range(rnd.randint(0, 30)))
        m = PDF.CAL_RE.search(ln)
        assert PDF._cal_tail(ln) == (m.group(1) if m else None), repr(ln)
    old = re.compile(r"(" + "|".join(PDF.MONTHS) + r")\s+(\d{1,2})\s*\W+\s*(?:" + "|".join(PDF.MONTHS) +
                     r")\s+\d{1,2}\s*\(\d{2} Days\)", re.I)
    bits = [" ", "-", "\u2014", "\f", "x", "1", "2", "December ", "January ", "(30 Days)", "(", ")"]
    for _ in range(20000):
        s = "".join(rnd.choice(bits) for _ in range(rnd.randint(0, 14)))
        o, n = old.search(s), PDF.PERIOD_RE.search(s)
        assert (o and (o.span(), o.groups())) == (n and (n.span(), n.groups())), repr(s)
    assert PDF.period_start("December 2 \u2014December 31 (30 Days)", "2026-12").isoformat() == "2026-12-02"
    assert PDF.period_start("December 31 -January 30 (31 Days)", "2027-01").isoformat() == "2026-12-31"


def test_text_beyond_any_real_package_or_award_is_refused_before_a_parser():
    with pytest.raises(PP.Refused, match="over 1000 characters"):
        PP.text_shape("December 2026 Pairing Package\n" + " 12" * 20000 + "\n")  # the review's 20000-token line
    with pytest.raises(PP.Refused, match="lines of text"):
        PP.text_shape("x\n" * (PP.TEXT_LINES + 1))
    with pytest.raises(PP.Refused, match="far more text"):
        PP.text_shape(("y" * 999 + "\n") * (PP.TEXT_CHARS // 1000 + 1))
    PP.text_shape("\n".join(package_lines()))  # a whole made-up package passes
    assert PP.TEXT_LINES == 60000 and PP.LINE_CHARS == 1000


def test_extract_refuses_a_long_line_before_any_parser(tmp_path):
    w = str(tmp_path / "w")
    with pytest.raises(PP.Refused, match="over 1000 characters"):
        PP.extract(b"%PDF", w, cmd=("sh", "-c", 'printf "January 1%01200d\\n" 0 > "$2"', "sh"))
    assert os.listdir(w) == []


# ---------------------------------------------------------------- B4: an award's last line cut off
def test_an_award_line_cut_off_is_not_read_and_every_later_award_still_is(inst):
    cut = "\n".join(award_lines(emp=EMP) + ["00002 / 5678"]) + "\n"
    assert PP.check_award(cut, "2026-12", EMP) == {"items": 2}  # the pilot's own line is whole
    with pytest.raises(ValueError, match="cut off"):
        PDF.parse_award(cut, "5678", {}, "2026-12")
    A = inst("")
    A.S["own_emp"] = "5678"
    up = inst.up
    for month, title in (("2026-12", "December 2026"), ("2027-01", "January 2027")):
        open(os.path.join(up, f"{month}_pairings.txt"), "w").write(
            "\n".join(package_lines(title).copy()) + "\n")
    open(os.path.join(up, "2026-12_award.txt"), "w").write(cut)
    open(os.path.join(up, "2027-01_award.txt"), "w").write("\n".join(award_lines("January 2027", emp="5678")) + "\n")
    A.uploads_check()
    done = A.S.get("uploads_done") or {}
    assert "2026-12_award.txt" in done and "2027-01_award.txt" in done  # marked done: not retried every pass
    vers = A.DB.get("sched_versions:2027-01") or []
    assert vers and vers[0]["award"]  # the later award is read


# ---------------------------------------------------------------- A2: the extractor's user
@pytest.mark.skipif(os.geteuid() != 0, reason="the drop happens only when the Watcher runs as root (the add-on does)")
def test_the_extractor_runs_as_nobody_with_no_groups(tmp_path):
    text, d = PP.extract(b"%PDF-1.4 made up %%EOF", str(tmp_path / "w"),
                         cmd=("sh", "-c", 'id -u > "$2"; id -G >> "$2"; id -g >> "$2"', "sh"))
    assert text.split() == [str(PP.EXTRACT_UID)] * 3
    st = os.stat(os.path.join(d, "out.txt"))
    assert st.st_uid == 0 and os.listdir(d) == ["out.txt"]  # the text stored is the Watcher's own new file
    assert "os.setuid(u)" in PP.LIMIT_SHIM and "os.setgroups([])" in PP.LIMIT_SHIM


def test_the_extractors_output_is_never_read_through_a_link(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("December 2026 Pairing Package\n")
    os.chmod(secret, 0o644)
    with pytest.raises(PP.Refused, match="no text"):
        PP.extract(b"%PDF", str(tmp_path / "w"), cmd=("sh", "-c", f'ln -s {secret} "$2"', "sh"))
    with pytest.raises(PP.Refused, match="no text"):
        PP.extract(b"%PDF", str(tmp_path / "w"), cmd=("sh", "-c", 'mkfifo "$2"', "sh"))


def test_a_real_pdf_still_reads_through_the_dropped_extractor(tmp_path):
    text, d = PP.extract(PKG, str(tmp_path / "w"))
    assert "December 2026 Pairing Package" in text and PP.check_pairings(text, "2026-12")["pairings"] == 110
    assert open(os.path.join(d, "out.txt"), encoding="utf-8").read() == text


# ---------------------------------------------------------------- C2 / C3: schedule_unread
@pytest.fixture
def unread(portal_pilot, monkeypatch):
    W2, _ = portal_pilot("pilot2")
    assert W2.portal_start(threads=False)
    return W2


def _hst(*a):
    return datetime(*a, tzinfo=HST).timestamp()


def test_schedule_unread_waits_6_h_after_a_pause_or_a_stop_ends(unread, monkeypatch):
    W2 = unread
    t = _hst(2026, 11, 12, 10, 0)
    monkeypatch.setattr(W2, "PROC_START", t - 30 * 3600)
    W2.S["sched_read_at"] = datetime.fromtimestamp(t - 26 * 3600, HST).isoformat()
    W2.S["machine"] = "paused"
    assert W2.schedule_unread_tick(t - 60) is None
    W2.S["machine"] = "idle"  # Pause off: the first read is still on its way
    assert W2.schedule_unread_tick(t) is None
    assert W2.schedule_unread_tick(t + 5 * 3600) is None
    rec = W2.schedule_unread_tick(t + 6 * 3600)
    assert rec and rec["data"]["hours"] == 32  # the hours since the last good read
    W2.S["machine"] = "stopped_login_failed"
    assert W2.schedule_unread_tick(t + 40 * 3600) is None
    W2.S["machine"] = "hunting"  # Re-arm
    assert W2.schedule_unread_tick(t + 40 * 3600 + 60) is None


def test_schedule_unread_goes_at_most_once_in_24_h_not_again_at_midnight(unread, monkeypatch):
    W2 = unread
    t = _hst(2026, 11, 12, 16, 0)
    monkeypatch.setattr(W2, "PROC_START", t - 10 * 3600)
    W2.S["machine"] = "hunting"
    W2.S["sched_read_at"] = datetime.fromtimestamp(t - 8 * 3600, HST).isoformat()
    assert W2.schedule_unread_tick(t)
    assert W2.schedule_unread_tick(_hst(2026, 11, 13, 0, 1)) is None  # a new HST day, 8 h later: not yet
    assert W2.schedule_unread_tick(t + 86400 - 60) is None
    nxt = W2.schedule_unread_tick(t + 86400)
    assert nxt and nxt["data"]["hours"] == 32
    assert W2.DB.get(W2.SCHED_UNREAD_DONE) == {"day": "2026-11-13", "at": t + 86400}


# ---------------------------------------------------------------- C5: an upload with no answer
def test_an_upload_dropped_for_no_part_gets_an_answer(inst, monkeypatch):
    W2 = inst("pilot2")
    clock = [1000.0]
    monkeypatch.setattr(W2.PDF_ASM, "now", lambda: clock[0])
    ch = _chunks(PKG, "pairings", "2026-12", uid="uLost000000000001")
    assert len(ch) >= 2
    _send(W2, ch[:-1])  # the last part lost on the way (HOM said ok, the Watcher's spool refused it)
    assert _answer(W2, "uLost000000000001")["state"] == "receiving"
    assert W2.pilot_upload_stale() == []
    clock[0] += LIM["stale_s"] + 1
    assert W2.pilot_upload_stale() == ["uLost000000000001"]
    a = _answer(W2, "uLost000000000001")
    assert a["state"] == "error" and not a["ok"] and "no part came for 120 s" in a["message"]
    assert W2.pilot_upload_stale() == []  # once
    _send(W2, ch[-1:])  # the lost part after all: nothing more (the card shows the first answer)
    assert _answer(W2, "uLost000000000001")["state"] == "error"
    assert "pilot_upload_stale()" in open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read().split(
        "def upload_janitor", 1)[1].split("def ", 1)[0]  # the janitor's sweep runs it


def test_answers_left_open_by_a_restart_are_settled_at_start(inst):
    W2 = inst("pilot2")
    _send(W2, _chunks(PKG, "pairings", "2026-12", uid="uDone000000000001"))
    W2.pilot_upload_answer("uDone000000000001", True, "checking", "All parts in: checking the file.")
    W2.pilot_upload_answer("uCut0000000000001", True, "receiving", "Receiving part 3 of 9.")
    W3 = inst("pilot2")  # the next start (portal_start settles them)
    assert _answer(W3, "uCut0000000000001")["state"] == "error" and "restarted" in _answer(W3, "uCut0000000000001")[
        "message"]
    assert _answer(W3, "uDone000000000001")["state"] == "live"  # its check had finished: what it gave


def test_the_uploads_card_stops_waiting_when_no_answer_comes():
    from test_fw171_cards import P, _browser, _card, _page, _s
    from test_fw172_cards import _view

    def states(answers):
        return {f"sensor.{P}_pilot_uploads": _s("0", {**_view(pending=False), "mine": [], "answers": answers})}
    raw = b"%PDF-1.4\n" + b"x" * 1000 + b"\n%%EOF\n"
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390, clock=True)
        pg.evaluate("(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }", states([]))
        inp = pg.evaluate_handle("() => c.shadowRoot.querySelector('[data-pdf]')")
        inp.as_element().set_input_files(files=[{"name": "dec.pdf", "mimeType": "application/pdf", "buffer": raw}])
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => window.calls.length === 1 && c._send && c._send.lastAt")
        uid = pg.evaluate("() => c._send.uid")
        pg.evaluate("(st) => { c.hass = mkHass(st); }", states([{"uid": uid, "ok": True, "state": "checking",
                                                                "message": "All parts in: checking the file.",
                                                                "at": "2026-11-10T19:00:00Z"}]))
        assert pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').disabled")
        pg.clock.run_for(170000)
        assert pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').disabled")  # still within the wait
        pg.clock.run_for(20000)
        msg = pg.evaluate("() => c.shadowRoot.querySelector('[data-msg]').textContent")
        assert msg.startswith("No answer from your Watcher") and not pg.evaluate(
            "() => c.shadowRoot.querySelector('[data-up]').disabled")
        # a final answer that comes later still wins
        pg.evaluate("(st) => { c.hass = mkHass(st); }", states([{"uid": uid, "ok": True, "state": "live",
                                                                "message": "Stored: in use now.",
                                                                "at": "2026-11-10T19:05:00Z"}]))
        assert pg.evaluate("() => c.shadowRoot.querySelector('[data-msg]').textContent") == "Stored: in use now."


# ---------------------------------------------------------------- C6: a removed award and the looked-up pilots
def test_clear_award_renumbers_a_looked_up_pilots_versions():
    class DB(dict):
        def get(self, k, d=None):
            return super().get(k, d)

        def put(self, k, v):
            self[k] = v
    db = DB()
    items = [{"trip": "H9000", "start": "2026-12-03", "end": "2026-12-04", "lay": "LAX"}]
    PV._save(db, "10001", "2026-12", PV.renumber("2026-12", [
        {"source": "award", "items": items, "days": [], "at": "a"},
        {"source": "lookup", "items": [], "days": [], "at": "b"}]), now_iso="x")
    assert PV.clear_award(db, "10001", "2026-12")
    assert [(v["ver"], v["source"]) for v in PV.versions_of(db, "10001", "2026-12")] == [("12.001", "lookup")]
    assert not PV.clear_award(db, "10001", "2026-12") and not PV.clear_award(db, "x", "2026-12")


def test_a_removed_award_is_no_longer_a_looked_up_pilots_001(W, tmp_path, monkeypatch):  # noqa: F811
    from test_crew_index import _file, _row
    from test_pilotver_watcher import Fl, _lookup
    from test_pdfs import AWARD as AW_TEXT, PKG as PKG_TEXT
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "seniority_refresh", lambda: None)
    _lookup(W, Fl())
    W.DB.put("pkg_details:2026-11", PDF.package_details(PKG_TEXT))
    (up / "2026-11_award.txt").write_text(AW_TEXT.replace("00999 / 1234", "00999 / 10001"))
    W.uploads_check()
    assert PV.versions_of(W.DB, "10001", "2026-11")[0]["source"] == "award"
    rv = W.review()
    with rv.lock():
        d = rv.load()
        rv._bump(d, "2026-11_award")
        rv._save(d)
    os.unlink(up / "2026-11_award.txt")  # removed with nothing to restore
    assert W.upload_gens_check() == ["2026-11_award"]
    assert [(v["ver"], v["source"]) for v in PV.versions_of(W.DB, "10001", "2026-11")] == [("11.001", "lookup")]


# ---------------------------------------------------------------- C4: the rollback notes
def test_the_rollback_notes_keep_a_crewtrac_refusal_on_1_7_1():
    for path in (os.path.join(HERE, "CHANGELOG.md"), os.path.join(ROOT, "HANDOFF.md")):
        text = " ".join(open(path, encoding="utf-8").read().split())
        assert "restore /data from the backup taken before the update" in text, path
        assert "blank the CrewTrac password" in text, path

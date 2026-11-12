"""1.7.2 (FW-0066, Ryan Nov 11; contract 1 revision 3): a pilot uploads the month's pairings package or award from his
portal (upload/pdf). His Watcher puts the chunks together and checks the whole file (pilotpdf.py: size, sha256, %PDF
and %%EOF, pdftotext in a child process under limits, that month's package or award with his own line) before
anything is stored; nothing on file -> used at once and the admin is pushed (Remove); a file on file -> held in the
quarantine folder, which no instance reads and nothing serves, until the admin approves it (Approve / Reject).
Made-up PDFs (tests/pdfmake.py) and made-up names and numbers only."""
import base64
import hashlib
import json
import logging
import math
import os
import stat
import sys
import textwrap
from datetime import datetime

import pytest

import pilotpdf as PP
import portal as PT
import roles
import web
from pdfmake import award_lines, make_pdf, package_lines

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
NOW = datetime(2026, 11, 12, 10, 0)  # HST, as local_now() gives it
LIM = roles.PILOT_UPLOAD_LIMITS
EMP = "1234"  # made up


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode() if isinstance(payload, str) else payload


def _chunks(raw, kind, month, uid="uDemo0000000000001"):
    b = base64.b64encode(raw).decode("ascii")
    n = math.ceil(len(b) / LIM["chunk_chars"])
    sha = hashlib.sha256(raw).hexdigest()
    return [json.dumps({"uid": uid, "kind": kind, "month": month, "size": len(raw), "sha": sha, "part": p, "parts": n,
                        "data": b[(p - 1) * LIM["chunk_chars"]:p * LIM["chunk_chars"]]}) for p in range(1, n + 1)]


def _send(W, payloads):
    for p in payloads:
        W.on_message(None, None, Msg(f"{W.T}/upload/pdf", p))


def _answer(W, uid="uDemo0000000000001"):
    a = W._pup_read().get("answers") or []
    return next((x for x in a if x["uid"] == uid), None)


PKG = make_pdf(package_lines())  # December 2026: 110 pairings, 3 of them A332 HNL (H9000 to H9002)
PKG_NEW = make_pdf(package_lines(n=120, a332=5))  # a revised copy: 5 A332 ones (H9003, H9004 new)
AWARD = make_pdf(award_lines())


@pytest.fixture
def inst(portal_pilot, tmp_path, monkeypatch):
    """load(name) -> a Watcher ('pilot2' with his portal on, '' the admin) reading the one shared uploads folder under
    tmp_path, at NOW, its background work run in place."""
    up = tmp_path / "share" / "flight_watcher" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))

    def load(name="pilot2"):
        W, _ = portal_pilot(name, portal=bool(name))
        monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
        monkeypatch.setattr(W, "UPLOADS", str(up))
        monkeypatch.setattr(W, "local_now", lambda: NOW)
        monkeypatch.setattr(W, "_bg", lambda fn, *a: fn(*a))
        if name:
            W.S["own_emp"] = EMP
            assert W.portal_start(threads=False)
        return W
    load.up = str(up)
    load.review = str(up.parent / "upload_review")
    return load


# ---------------------------------------------------------------- pilotpdf: the chunks
def test_limits_fit_the_command_cap_and_a_4_mb_file():
    assert PP.parts_for(LIM["file_bytes"]) == LIM["chunk_parts"] == 94
    assert LIM["kinds"] == ["pairings", "award"] and LIM["per_day"] == 4 and LIM["stale_s"] == 120
    big = {"uid": "u" * 40, "kind": "pairings", "month": "2026-12", "size": LIM["file_bytes"], "sha": "a" * 64,
           "part": 94, "parts": 94, "data": "A" * LIM["chunk_chars"]}
    cmd = {"fwp": 1, "id": "0" * 16, "pilot": "james", "ts": 1763600000000, "sub": "upload/pdf",
           "payload": json.dumps(big), "session": "0" * 16}
    assert len(json.dumps(cmd).encode()) < PT.CAPS["cmd"]  # one chunk under the 64 KB command cap
    assert PP.months_allowed(NOW.replace(tzinfo=PP.HST)) == ["2026-11", "2026-12", "2027-01"]
    assert PP.month_refusal("2027-02", NOW.replace(tzinfo=PP.HST)) and not PP.month_refusal("2027-01", NOW.replace(tzinfo=PP.HST))


def _d(p):
    return PT.check_shape("upload/pdf", p)


def test_assembler_one_at_a_time_in_order_and_whole():
    raw = os.urandom(150000)
    t = [1000.0]
    a = PP.Assembler(now=lambda: t[0])
    ch = _chunks(raw, "pairings", "2026-12")
    assert len(ch) == 4
    assert a.add(_d(ch[0])) is None and a.add(_d(ch[0])) is None  # the same chunk again counts once
    with pytest.raises(PP.Refused, match="another upload"):
        a.add(_d(_chunks(raw, "award", "2026-12", uid="uOther00000000001")[0]))
    with pytest.raises(PP.Refused, match="out of order"):
        a.add(_d(ch[2]))
    assert not a.busy()  # the upload it belonged to was dropped
    assert a.add(_d(ch[0])) is None and a.add(_d(ch[1])) is None and a.add(_d(ch[2])) is None
    meta, got = a.add(_d(ch[3]))
    assert got == raw and meta["parts"] == 4 and not a.busy()
    assert a.add(_d(ch[3])) is None  # the last chunk resent: already handed on
    # stale: no chunk within stale_s drops it
    a.add(_d(ch[0]))
    t[0] += LIM["stale_s"] + 1
    assert not a.busy()
    with pytest.raises(PP.Refused, match="out of order"):
        a.add(_d(ch[1]))
    # parts that do not fit the size, a changed sha, a size over the cap
    bad = json.loads(ch[0])
    with pytest.raises(PP.Refused, match="parts do not fit"):
        a.add(_d(json.dumps({**bad, "parts": 5})))
    a2 = PP.Assembler()
    one = _chunks(b"%PDF-1.4 x %%EOF", "pairings", "2026-12")[0]
    with pytest.raises(PP.Refused, match="checksum"):
        a2.add(_d(json.dumps({**json.loads(one), "sha": "0" * 64})))


def test_pdf_shape_magic_and_trailer():
    with pytest.raises(PP.Refused, match="not a PDF"):
        PP.pdf_shape(b"GIF89a" + b"%%EOF")
    with pytest.raises(PP.Refused, match="not complete"):
        PP.pdf_shape(b"%PDF-1.4\n" + b"x" * 5000)
    with pytest.raises(PP.Refused, match="not complete"):
        PP.pdf_shape(b"%PDF-1.4\n%%EOF\n" + b"x" * 2000)  # the trailer must be in the last 1024 bytes
    PP.pdf_shape(PKG)


# ---------------------------------------------------------------- pilotpdf: the extractor's child process
CHILD = textwrap.dedent("""
    import os, resource, sys, time
    mode, out = sys.argv[1], sys.argv[-1]
    if mode == "limits":
        open(out, "w").write(repr({k: resource.getrlimit(getattr(resource, k)) for k in
                                   ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_CORE")})
                             + "|" + repr(sorted(os.environ)) + "|" + repr(sys.stdin.read()))
    elif mode == "sleep":
        time.sleep(30)
    elif mode == "spin":
        while True:
            pass
    elif mode == "fail":
        sys.exit(3)
    elif mode == "empty":
        open(out, "w").write("   ")
    elif mode == "big":  # Python ignores SIGXFSZ, so the write fails (pdftotext, in C, is killed by it)
        with open(out, "w") as f:
            f.write("x" * 4096)
""")


@pytest.fixture
def child(tmp_path):
    p = tmp_path / "child.py"
    p.write_text(CHILD)
    return lambda mode: (sys.executable, str(p), mode)


def test_extract_runs_in_a_child_under_limits(tmp_path, child):
    text, d = PP.extract(b"%PDF-1.4 made up %%EOF", str(tmp_path / "w"), cmd=child("limits"))
    lim, env, stdin = text.split("|")
    lim = eval(lim)  # noqa: S307 (our own child's repr)
    assert lim["RLIMIT_AS"] == (LIM["extract_mem_mb"] * 1024 * 1024,) * 2  # the extractor itself runs under them
    assert lim["RLIMIT_CPU"] == (LIM["extract_cpu_s"], LIM["extract_cpu_s"] + 1)
    assert lim["RLIMIT_FSIZE"] == (PP.TEXT_MAX, PP.TEXT_MAX) and lim["RLIMIT_CORE"] == (0, 0)
    assert set(eval(env)) <= {"PATH", "LANG", "LC_CTYPE"} and eval(stdin) == ""  # noqa: S307
    src = open(os.path.join(HERE, "pilotpdf.py"), encoding="utf-8").read()
    assert "preexec_fn=" not in src  # 1.7.2: no preexec_fn in the Watcher's many-threaded process
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700 and stat.S_IMODE(os.stat(os.path.join(d, "in.pdf")).st_mode) == 0o600


def test_extract_refuses_a_slow_a_spinning_a_failed_or_an_empty_read(tmp_path, child):
    w = str(tmp_path / "w")
    with pytest.raises(PP.Refused, match="took over 1 s"):
        PP.extract(b"%PDF", w, timeout=1, cmd=child("sleep"))
    with pytest.raises(PP.Refused, match="could not be read"):  # SIGXCPU at the CPU limit, long before the timeout
        PP.extract(b"%PDF", w, timeout=60, cmd=child("spin"), limits=PP.child_limits(cpu_s=1))
    with pytest.raises(PP.Refused, match="could not be read"):
        PP.extract(b"%PDF", w, cmd=child("fail"))
    with pytest.raises(PP.Refused, match="no text"):
        PP.extract(b"%PDF", w, cmd=child("empty"))
    with pytest.raises(PP.Refused, match="could not be read"):  # a write past the file size limit
        PP.extract(b"%PDF", w, cmd=child("big"), limits=PP.child_limits(fsize=1024))
    with pytest.raises(PP.Refused, match="could not be read"):  # SIGXFSZ is back to its default: a C writer is killed
        PP.extract(b"%PDF", w, cmd=("sh", "-c", 'head -c 4096 /dev/zero > "$2"', "sh"),
                   limits=PP.child_limits(fsize=1024))
    assert os.listdir(w) == []  # nothing left behind


def test_the_extractor_is_the_admins_pdftotext_with_a_30_s_timeout():
    assert PP.EXTRACTOR == ("pdftotext", "-layout") and LIM["extract_timeout_s"] == 30
    src = open(os.path.join(HERE, "web.py"), encoding="utf-8").read()
    assert '["pdftotext", "-layout", tmp, tmp[:-4] + ".txt"]' in src


# ---------------------------------------------------------------- pilotpdf: the parsers
def _text(raw, tmp_path):
    t, _ = PP.extract(raw, str(tmp_path / "x"))
    return t


def test_a_pairings_package_must_be_that_months_whole_a332_package(tmp_path):
    t = _text(PKG, tmp_path)
    assert PP.check_pairings(t, "2026-12") == {"pairings": 110, "a332": 3}
    with pytest.raises(PP.Refused, match="December 2026 pairing package, not January 2027"):
        PP.check_pairings(t, "2027-01")
    with pytest.raises(PP.Refused, match="only 99 pairings"):
        PP.check_pairings(_text(make_pdf(package_lines(n=99)), tmp_path), "2026-12")
    with pytest.raises(PP.Refused, match="no A332 HNL"):
        PP.check_pairings(_text(make_pdf(package_lines(a332=0)), tmp_path), "2026-12")
    with pytest.raises(PP.Refused, match="does not read as a pairing package"):
        PP.check_pairings(_text(make_pdf(award_lines()), tmp_path), "2026-12")


def test_an_award_must_be_that_months_with_the_pilots_own_line(tmp_path):
    t = _text(AWARD, tmp_path)
    assert PP.award_month(t) == "2026-12" and PP.check_award(t, "2026-12", EMP) == {"items": 2}
    with pytest.raises(PP.Refused, match="December 2026 award, not January 2027"):
        PP.check_award(t, "2027-01", EMP)
    with pytest.raises(PP.Refused, match="your line is not in this award"):
        PP.check_award(t, "2026-12", "5678")
    with pytest.raises(PP.Refused, match="employee number yet"):
        PP.check_award(t, "2026-12", "")
    with pytest.raises(PP.Refused, match="not read as a PBS award"):
        PP.check_award(_text(PKG, tmp_path), "2026-12", EMP)


# ---------------------------------------------------------------- the pilot's Watcher, end to end
def test_nothing_on_file_the_pilots_upload_is_used_at_once_and_the_admin_pushed(inst, caplog):
    W = inst("pilot2")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        _send(W, _chunks(PKG, "pairings", "2026-12"))
    a = _answer(W)
    assert a["ok"] and a["state"] == "live" and "in use" in a["message"]
    pdf, txt = os.path.join(inst.up, "2026-12_pairings.pdf"), os.path.join(inst.up, "2026-12_pairings.txt")
    assert open(pdf, "rb").read() == PKG and "December 2026 Pairing Package" in open(txt).read()
    rec = PP.Review(inst.up, inst.review).records()[-1]
    assert (rec["who"], rec["state"], rec["sha256"], rec["size"]) == ("pilot2", "live", hashlib.sha256(PKG).hexdigest(),
                                                                     len(PKG))
    assert rec["at"].startswith("20") and rec["at"].endswith("-10:00")  # when, in HST
    assert PP.Review(inst.up, inst.review).load()["files"]["2026-12_pairings"]["who"] == "pilot2"
    for d in (inst.review, os.path.join(inst.review, "quarantine"), os.path.join(inst.review, "rollback")):
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert "Pairing Package" not in caplog.text and "H9000" not in caplog.text  # counts only, never content
    # both instances read it as today
    W.uploads_check()
    assert W.DB.get("pkg_details:2026-12") and "H9000" in W.DB.get("pkg_details:2026-12")
    assert json.load(open(os.path.join(W.CARD_PAIRINGS, "pairings_2026-12.json")))["month"] == "2026-12"
    view = W.pilot_uploads_state()[f"sensor.{W.T}_pilot_uploads"]["attributes"]
    dec = next(m for m in view["months"] if m["month"] == "2026-12")
    assert dec["pairings"] == {"on_file": True, "by": "you", "pending": False} and dec["award"]["on_file"] is False
    assert view["limits"]["left_today"] == 3 and view["mine"][0]["state"] == "live"
    assert "sha256" not in json.dumps(view) and "ryan" not in json.dumps(view).lower()
    # the admin's Watcher pushes it once (event/pilot_upload), never again
    A = inst("")
    sent = A.pilot_upload_announce()
    assert len(sent) == 1 and sent[0]["state"] == "live" and sent[0]["who"] == "pilot2"
    assert sent[0]["title"] == "Pilot2 uploaded the December 2026 pairings package"
    assert "Remove" in sent[0]["message"] and sent[0]["file"] == "2026-12_pairings.pdf"
    assert [t for t, *_ in A.MQ.raw.msgs if t == "flight_watcher/event/pilot_upload"] == ["flight_watcher/event/pilot_upload"]
    assert A.pilot_upload_announce() == []  # once
    # a pilot's Watcher never pushes anyone (no event/pilot_upload on his prefix)
    assert W.pilot_upload_announce() == [] and not [t for t, *_ in W.MQ.raw.msgs if "pilot_upload" in t]


def test_remove_leaves_nothing_on_file_and_both_instances_read_again(inst):
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2026-12"))
    W.uploads_check()
    assert W.DB.get("pkg_details:2026-12")
    A = inst("")
    A.uploads_check()
    assert A.DB.get("pkg_details:2026-12")
    uid = PP.Review(inst.up, inst.review).records()[-1]["id"]
    A.on_message(None, None, Msg("flight_watcher/upload/decide", json.dumps({"id": uid, "action": "remove"})))
    assert not os.path.exists(os.path.join(inst.up, "2026-12_pairings.pdf"))
    assert not os.path.exists(os.path.join(A.CARD_PAIRINGS, "pairings_2026-12.json"))
    assert PP.Review(inst.up, inst.review).records()[-1]["state"] == "removed"
    assert "2026-12_pairings" not in PP.Review(inst.up, inst.review).load()["files"]
    A.uploads_check()
    assert not A.DB.get("pkg_details:2026-12") and A.pkg_details_for("2026-12") == {}
    # the pilot's instance follows the change too, whatever its state (the uploads janitor's minute)
    W2 = inst("pilot2")
    assert W2.upload_gens_pending()
    W2.uploads_check()
    assert not W2.DB.get("pkg_details:2026-12") and not W2.upload_gens_pending()
    v = W2.pilot_uploads_state()[f"sensor.{W2.T}_pilot_uploads"]["attributes"]
    assert v["mine"][0]["state"] == "removed" and not next(m for m in v["months"] if m["month"] == "2026-12")[
        "pairings"]["on_file"]


def _quarantined_text(inst):
    q = os.path.join(inst.review, "quarantine")
    return {n: open(os.path.join(q, n), "rb").read() for n in os.listdir(q)}


def test_a_file_on_file_holds_the_pilots_copy_where_nothing_reads_or_serves_it(inst):
    """Ryan: a file already on file -> the pilot's copy goes to a quarantine folder that no instance reads and nothing
    serves, until he approves it. H9003 and H9004 are only in the pilot's copy."""
    A = inst("")
    r = web.save_upload({"kind": "pairings", "month": "2026-12"}, PKG, logging.getLogger("t"))
    assert r["ok"]
    A.uploads_check()
    W = inst("pilot2")
    _send(W, _chunks(PKG_NEW, "pairings", "2026-12"))
    a = _answer(W)
    assert a["state"] == "pending" and "approves" in a["message"]
    assert open(os.path.join(inst.up, "2026-12_pairings.pdf"), "rb").read() == PKG  # the file on file stays
    q = _quarantined_text(inst)
    assert sorted(n.rsplit(".", 1)[1] for n in q) == ["pdf", "txt"] and PKG_NEW in q.values()
    for n in q:
        assert stat.S_IMODE(os.stat(os.path.join(inst.review, "quarantine", n)).st_mode) == 0o600
    # never read: neither instance parses it into pairing details, the pairing file, the bid calendar or the vans
    for X in (W, A):
        X.uploads_check()
        det = X.DB.get("pkg_details:2026-12") or {}
        assert "H9000" in det and "H9003" not in det and "H9004" not in det
        assert "H9003" not in json.dumps(X.pkg_details_for("2026-12"))
        assert "H9003" not in open(os.path.join(X.CARD_PAIRINGS, "pairings_2026-12.json")).read()
        X.bidcal_package("2026-12")
    # never served: not on the uploads list (sensor and Web UI), not in the pilot's portal export
    lst = web.uploads_json("1.7.2", review=True)
    assert [f["name"] for f in lst["files"]] == ["2026-12_pairings.pdf"]
    assert all("quarantine" not in json.dumps(lst["files"]) for _ in [0])
    W.portal_export_once(full=True)
    out = os.path.join(W.PORTAL_DIR, "out")
    blob = b"".join(open(os.path.join(dp, f), "rb").read() for dp, _, fs in os.walk(out) for f in fs)
    assert b"H9003" not in blob and b"H9004" not in blob
    assert not [p for p, *_ in W.portal_file_sources() if inst.review in p]
    # the admin is pushed with Approve / Reject, and his card lists it
    sent = A.pilot_upload_announce()
    assert [e["state"] for e in sent] == ["pending"] and "Approve" in sent[0]["message"]
    assert lst["pilot_uploads"][0]["state"] == "pending" and lst["pilot_uploads"][0]["who"] == "pilot2"
    # Approve swaps it in (the old file kept for rollback): only now is it read
    A.upload_decide_cmd(json.dumps({"id": sent[0]["id"], "action": "approve"}))
    assert open(os.path.join(inst.up, "2026-12_pairings.pdf"), "rb").read() == PKG_NEW
    rb = os.listdir(os.path.join(inst.review, "rollback"))
    assert sorted(n.rsplit(".", 1)[1] for n in rb) == ["pdf", "txt"]
    assert _quarantined_text(inst) == {}
    for X in (A, inst("pilot2")):
        X.uploads_check()
        assert "H9003" in (X.DB.get("pkg_details:2026-12") or {})
    # Remove after an approve brings the file it replaced back
    A.upload_decide_cmd(json.dumps({"id": sent[0]["id"], "action": "remove"}))
    assert open(os.path.join(inst.up, "2026-12_pairings.pdf"), "rb").read() == PKG
    A.uploads_check()
    assert "H9003" not in (A.DB.get("pkg_details:2026-12") or {}) and "H9000" in A.DB.get("pkg_details:2026-12")


def test_reject_deletes_the_held_copy_and_the_file_on_file_stays(inst):
    A = inst("")
    web.save_upload({"kind": "pairings", "month": "2026-12"}, PKG, logging.getLogger("t"))
    W = inst("pilot2")
    _send(W, _chunks(PKG_NEW, "pairings", "2026-12"))
    uid = PP.Review(inst.up, inst.review).records()[-1]["id"]
    A.on_message(None, None, Msg("flight_watcher/upload/decide", json.dumps({"id": uid, "action": "reject"})))
    assert _quarantined_text(inst) == {} and open(os.path.join(inst.up, "2026-12_pairings.pdf"), "rb").read() == PKG
    recs = PP.Review(inst.up, inst.review).records()
    assert recs[-1]["state"] == "rejected" and recs[-1]["decided_by"] == "ryan"
    # a decision twice changes nothing; approve after reject neither
    ok, msg, _ = PP.Review(inst.up, inst.review).decide(uid, "approve")
    assert not ok and "not waiting" in msg


def test_the_same_file_again_is_not_stored_twice(inst):
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2026-12"))
    _send(W, _chunks(PKG, "pairings", "2026-12", uid="uDemo0000000000002"))
    assert _answer(W, "uDemo0000000000002")["state"] == "same" and _quarantined_text(inst) == {}


def test_an_award_needs_his_own_line_and_becomes_version_001_until_removed(inst):
    W = inst("pilot2")
    W.S["own_emp"] = "5678"
    _send(W, _chunks(AWARD, "award", "2026-12"))
    assert _answer(W)["state"] == "error" and "your line is not in this award" in _answer(W)["message"]
    assert not os.path.exists(os.path.join(inst.up, "2026-12_award.pdf"))
    W.S["own_emp"] = EMP
    _send(W, _chunks(PKG, "pairings", "2026-12", uid="uDemo0000000000003"))
    _send(W, _chunks(AWARD, "award", "2026-12", uid="uDemo0000000000004"))
    assert _answer(W, "uDemo0000000000004")["state"] == "live"
    W.uploads_check()
    vers = W.DB.get("sched_versions:2026-12")
    assert vers and vers[0]["award"] and vers[0]["ver"] == "12.001"
    A = inst("")
    A.upload_decide_cmd(json.dumps({"id": "uDemo0000000000004", "action": "remove"}))
    W2 = inst("pilot2")
    W2.uploads_check()
    assert not [v for v in W2.DB.get("sched_versions:2026-12") or [] if v.get("award")]


def test_the_pilots_limits_month_kind_and_a_day(inst, monkeypatch):
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2027-02"))
    assert _answer(W)["state"] == "error" and "pick November 2026, December 2026 or January 2027" in _answer(W)["message"]
    for kind in ("seniority", "contacts"):  # never the seniority list or the contact list (other pilots' phones)
        _send(W, [p.replace('"kind": "pairings"', f'"kind": "{kind}"') for p in _chunks(PKG, "pairings", "2026-12",
                                                                                      uid=f"u{kind}000000000000")])
        assert _answer(W, f"u{kind}000000000000") is None
    assert not os.listdir(inst.up)
    big = b"%PDF-1.4\n" + b"0" * (LIM["file_bytes"] + 1)
    W.on_message(None, None, Msg(f"{W.T}/upload/pdf", _chunks(big, "pairings", "2026-12", uid="uBig0000000000001")[0]))
    assert _answer(W, "uBig0000000000001") is None  # the shape check refuses the size before anything
    # a fifth upload in 24 h is refused at its first chunk (refused or not, four were put together)
    for i in range(4):
        _send(W, _chunks(b"%PDF-1.4 not a package %%EOF", "pairings", "2026-12", uid=f"uDay{i}000000000000"))
        assert _answer(W, f"uDay{i}000000000000")["state"] == "error"
    _send(W, _chunks(PKG, "pairings", "2026-12", uid="uDay4000000000000"))
    a = _answer(W, "uDay4000000000000")
    assert a["state"] == "error" and "4 uploads in the last 24 h" in a["message"]
    assert W.pilot_uploads_state()[f"sensor.{W.T}_pilot_uploads"]["attributes"]["limits"]["left_today"] == 0


def test_upload_commands_belong_to_a_portal_pilot_and_decisions_to_the_admin(inst, caplog):
    W = inst("pilot2")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.on_message(None, None, Msg(f"{W.T}/upload/decide", json.dumps({"id": "uDemo0000000000001",
                                                                         "action": "approve"})))
    assert "upload/decide refused: not for a pilot instance" in caplog.text
    A = inst("")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        A.on_message(None, None, Msg("flight_watcher/upload/pdf", _chunks(PKG, "pairings", "2026-12")[0]))
        A.upload_decide_cmd(json.dumps({"id": "x", "action": "approve"}))
        A.upload_decide_cmd(json.dumps({"id": "uDemo0000000000001", "action": "delete"}))
    assert "upload/pdf refused: the portal is off on this instance" in caplog.text
    assert caplog.text.count("upload decision refused") == 2
    assert not os.path.exists(inst.review) or not os.listdir(os.path.join(inst.review, "quarantine"))


def test_the_admins_own_upload_is_its_provenance_and_replaces_a_pilots(inst):
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2026-12"))
    inst("")
    assert web.save_upload({"kind": "pairings", "month": "2026-12"}, PKG_NEW, logging.getLogger("t"))["ok"]
    rv = PP.Review(inst.up, inst.review)
    f = rv.load()["files"]["2026-12_pairings"]
    assert f["who"] == "ryan" and f["how"] == "admin" and f["sha256"] == hashlib.sha256(PKG_NEW).hexdigest()
    assert rv.records()[-1]["state"] == "replaced"
    ok, msg, _ = rv.decide("uDemo0000000000001", "remove")
    assert not ok and "not the file in use" in msg  # the admin's file is never removed by a pilot's record


# ---------------------------------------------------------------- the HA automation for Ryan's push
def _auto():
    import yaml
    autos = yaml.safe_load(open(os.path.join(ROOT, "ha", "automations_flight_watcher.yaml"), encoding="utf-8"))
    return next(a for a in autos if a["alias"] == "Flight Watcher pilot upload")


def test_ryans_push_and_its_buttons():
    pytest.importorskip("yaml")
    a = _auto()
    trig = {t["id"]: t for t in a["triggers"]}
    assert trig["up"]["topic"] == "flight_watcher/event/pilot_upload" and trig["act"]["event_type"] == \
        "mobile_app_notification_action"
    text = json.dumps(a)
    assert "flight_watcher_" not in text.replace("flight_watcher_upload_", "")  # never a pilot's prefix
    acts = json.dumps(a["actions"])
    assert acts.count("time-sensitive") == 4 and "critical" not in acts
    pushes = []

    def walk(o):
        if isinstance(o, dict):
            if str(o.get("action", "")).startswith("notify."):
                pushes.append((o["action"], [b["action"].split("|")[0] for b in o["data"]["data"]["actions"]]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(a["actions"])
    assert sorted(set(t for t, _ in pushes)) == ["notify.mobile_app_ryans_iphone", "notify.mobile_app_ryans_iphone_16"]
    assert sorted({tuple(b) for _, b in pushes}) == [("FLIGHT_WATCHER_UPLOAD_APPROVE", "FLIGHT_WATCHER_UPLOAD_REJECT"),
                                                     ("FLIGHT_WATCHER_UPLOAD_REMOVE",)]
    act = a["actions"][0]["choose"][1]["sequence"][0]
    assert act["action"] == "mqtt.publish" and act["data"]["topic"] == "flight_watcher/upload/decide"
    # the payload template gives exactly what upload_decide_cmd takes
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment()
    env.filters["tojson"] = lambda v: json.dumps(v)
    for btn, want in (("FLIGHT_WATCHER_UPLOAD_APPROVE", "approve"), ("FLIGHT_WATCHER_UPLOAD_REJECT", "reject"),
                      ("FLIGHT_WATCHER_UPLOAD_REMOVE", "remove")):
        trigger = {"event": {"data": {"action": f"{btn}|uDemo0000000000001"}}}
        out = json.loads(env.from_string(act["data"]["payload"]).render(trigger=trigger))
        assert out == {"id": "uDemo0000000000001", "action": want}


def test_the_push_isolation_guard_counts_the_new_handler():
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ha", "check_push_isolation.py")], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "22 automations (5 neutral, 17 ryan), 3 notification-action handler(s), 0 offender(s)" in r.stdout


def test_a_held_award_never_becomes_the_awarded_line(inst):
    W = inst("pilot2")
    _send(W, _chunks(PKG, "pairings", "2026-12", uid="uDemo0000000000005"))  # nothing on file: in use
    inst("")
    assert web.save_upload({"kind": "award", "month": "2026-12"}, AWARD, logging.getLogger("t"))["ok"]
    other = make_pdf([ln.replace("H9000", "H9001") for ln in award_lines()])
    W = inst("pilot2")
    _send(W, _chunks(other, "award", "2026-12", uid="uDemo0000000000006"))
    assert _answer(W, "uDemo0000000000006")["state"] == "pending"
    W.uploads_check()
    (aw,) = [v for v in W.DB.get("sched_versions:2026-12") if v.get("award")]
    assert [i["trip"] for i in aw["items"] if i["trip"] != "VAC"] == ["H9000"]  # the file on file, never the held one
    assert "H9001" not in json.dumps(W.DB.get("sched_versions:2026-12"))

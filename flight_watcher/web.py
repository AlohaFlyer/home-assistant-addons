"""Ingress page: settings (credentials), monthly PDFs and the pilot seniority list, rules editor, recent finds,
recent matches. HA handles auth (the ingress panel is for HA admins); only the Supervisor ingress proxy (172.30.32.2)
may connect. Passwords are never shown or logged.

1.4.5 (Ryan, Nov 6): JSON endpoints beside the page, same ingress-only access, for the dashboard uploads card
(www/flight-watcher-uploads-card.js, admin only): GET api/uploads (what is on file) and POST api/upload (the page's
own multipart form, the same checks and limits; the page and the card share one save path). An award upload is also
read for dates of hire (seniority.award_parse) and merged into seniority.json (award_seniority).

1.4.8 (FW-0066, Ryan Nov 7: any user can see and upload, and pilot contact lists): kind 'contacts' (a PDF, CSV or XLSX
pilot contact list) is read into /share/flight_watcher/contacts.json (mode 600; contacts.py) and its source kept mode
600; save_upload is also the save path of an upload sent in chunks over MQTT by a user who is not an admin
(chunks.py, watcher.upload_chunk), and every save runs under one lock shared by the pilot instances (save_lock)."""
import contextlib
import fcntl
import html
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import contacts as CT
import crewidx as CI
import seniority as SEN

INGRESS_IP = "172.30.32.2"
UPLOAD_DIR = "/share/flight_watcher/uploads"
PAIRINGS_DIR = "/homeassistant/www/flight-watcher"  # watcher.CARD_PAIRINGS: the pairing files the crew index reads
UPLOAD_MAX = 25_000_000  # the app's own hard cap on a request body (and on a file sent in chunks over MQTT)
CONTACTS_FILE = "/share/flight_watcher/contacts.json"  # FW-0066: the parsed pilot contact list (mode 600, not /config/www)
# FW-0066: every save (the Web UI, the card's ingress path, a chunked upload on either pilot instance) runs under this
# lock; both instances run in this one container, so /tmp is theirs alone.
LOCK_PATH = "/tmp/flight-watcher-uploads.lock"
_SAVE_LOCK = threading.Lock()
KINDS = ("award", "pairings", "seniority", "contacts")
CONTACTS_RE = re.compile(r"contacts_(\d{4}-\d{2}-\d{2})\.(pdf|csv|xlsx)")
# 1.4.5 review fix: what reaches the app through ingress. The Supervisor's ingress proxy reads a POST body whole
# (supervisor/api/ingress.py, no ingress_stream in config.yaml) and its aiohttp app refuses a body over 16 MiB
# (supervisor/api/__init__.py, MAX_CLIENT_SIZE = 1024**2 * 16) with HTTP 413, before the app sees it. api/uploads
# advertises this, less 64 KiB for the multipart form around the PDF, so the card refuses a larger file before
# sending it. Not ingress_stream: the body would then come chunked, with no Content-Length for this server to read.
INGRESS_MAX = 16 * 1024 * 1024 - 64 * 1024
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Flight Watcher rules</title>
<style>
body{{font:14px system-ui,sans-serif;margin:16px;max-width:1000px;background:#fafafa;color:#222}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#ddd}}textarea,td,th{{border-color:#444}}
textarea{{background:#1b1b1b;color:#ddd}}}}
textarea{{width:100%;height:340px;font:13px ui-monospace,monospace;box-sizing:border-box}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #ccc;padding:4px 6px;text-align:left}}
.err{{color:#c62828}}.ok{{color:#2e7d32}}.note{{opacity:.75}}button{{padding:6px 14px}}
nav a{{margin-right:14px}}.set label{{display:block;margin:6px 0}}.set input{{width:260px;max-width:100%;padding:4px}}
.set .k{{display:inline-block;width:150px}}
</style></head><body>
<h2>Flight Watcher {version}</h2>
<nav><a href="#settings">Settings</a><a href="#pdfs">Monthly PDFs</a><a href="#rules">Rules</a><a href="#finds">Recent finds</a></nav>
<h3 id="settings">Settings</h3>
{settings_msg}{settings}
<h3 id="pdfs">Monthly PDFs</h3>
<p class="note">0.9.0 (Ryan): upload the month's award (your line as awarded) and the pilot pairings package. They are
kept in /share/flight_watcher/uploads (never committed) with a text copy, and parsed for the month's starting
schedule and the tag-on ideas. 1.4.2 (FW-0062): the pilot seniority list (any month; the Month box is not used for
it) gives each pilot's date of hire, so a pilot's month rebuilt from crew lists shows a pay line for every pilot
instance. Give its list date if the PDF does not print one. Home Assistant's app proxy takes a PDF of up to
{max_mb} MB.</p>
<form method="post" action="upload" enctype="multipart/form-data">
Month <input type="month" name="month" value="{month}"> &nbsp;
<select name="kind"><option value="award">Monthly award</option><option value="pairings">Pairings package</option><option value="seniority">Pilot seniority list</option><option value="contacts">Pilot contact list</option></select> &nbsp;
<label>List date <input type="date" name="list_date" title="Seniority list only, optional"></label> &nbsp;
<input type="file" name="pdf" accept="application/pdf,.pdf,.csv,.xlsx,text/csv" required> &nbsp;<button type="submit">Upload</button></form>
<p class="note">1.4.8 (FW-0066): a pilot contact list (PDF, CSV or XLSX: employee number, name, phones, emails) is kept
as /share/flight_watcher/contacts.json (readable by this app only); the pilot card shows a call, text and mail link
for the pilot looked up.</p>
{uploads}{seniority}
<h3 id="rules">Rules</h3>
<p class="note">FLICA is read only: rules alert and log what they <i>would</i> submit, and nothing is ever sent to
FLICA. Every rule starts in dry run; its live switch (switch.flight_watcher_rule_&lt;id&gt;_live) cannot turn on until the rule is 7 days old.</p>
{msg}
<form method="post" action="rules"><textarea name="rules" spellcheck="false">{rules}</textarea>
<p><button type="submit">Save rules</button></p></form>
<details><summary>Schema</summary><pre>{schema}</pre></details>
<h3 id="finds">Recent finds</h3>{finds}
<h3>Recent rule matches</h3>{matches}
</body></html>"""
SCHEMA_HELP = """[{
  "id": "sin_hunt",                 a-z 0-9 _, max 32
  "name": "SIN layover",
  "enabled": true,
  "mode": "alert",                  alert | auto_add | auto_swap
  "dry_run": true,                  true forces dry run whatever the live switch says
  "match": {
    "layover": ["SIN"],             any of these stations in the layover column
    "months": ["current", "next"],  or "YYYY-MM"
    "date_from": "2026-11-01", "date_to": "2026-12-31",   trip start date window
    "min_credit": 10.5,             hours
    "max_days": 4,
    "report_after": "06:00", "report_before": "14:00",
    "pairing_prefix": "H36"
  },
  "swap": {"give": "H3601"},        auto_swap only
  "cap_per_day": 3,
  "notify": "critical",             critical | normal
  "expires_at": "2026-12-31T23:59:00-10:00"
}]"""


def _table(rows, cols):
    if not rows:
        return "<p class='note'>None yet.</p>"
    h = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '') if r.get(c) is not None else ''))}</td>"
                                 for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"


def _month_default():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=10)).strftime("%Y-%m")


def _uploads_table():
    files = sorted(uploads_list(), key=lambda f: f["name"])
    if not files:
        return "<p class='note'>Nothing uploaded yet.</p>"
    rows = [{"file": f["name"], "size": f"{f['size'] // 1024} KB", "text copy": "yes" if f["has_text"] else "no"}
            for f in files]
    return _table(rows, ["file", "size", "text copy"])


def _hst_now():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=-10)))


def seniority_file():
    """FW-0062: the parsed seniority list, shared by every pilot instance (the Web UI runs on the default one)."""
    return os.path.join(UPLOAD_DIR, "seniority.json")


def seniority_read(txt_path, uploaded_at, list_date=""):
    """Parse a seniority list text copy (pdftotext -layout): seniority.parse's dict (rows, rejects, ...). The century
    of a two-digit year comes from the list date, else the upload's year."""
    ref = int(list_date[:4]) if list_date else int(uploaded_at[:4])
    return SEN.parse(open(txt_path, encoding="utf-8", errors="replace").read(), ref)


SEN_LIST = "seniority_list.json"    # 1.4.5: the dedicated list, kept while an award's dates of hire are on top
SEN_AWARD = "seniority_award.json"  # 1.4.5: the newest award's dates of hire (25 pilot rows or more)
HST = timezone(timedelta(hours=-10))


def hst_iso(ts):
    """A file time as HST ISO ('2026-11-06T09:30:00-10:00')."""
    return datetime.fromtimestamp(ts, HST).isoformat(timespec="seconds")


def _load_json(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _dump(path, d):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, path)


def seniority_sources(out=None):
    """1.4.5: (list, award) that seniority.json (`out`, seniority_file() unless given) was built from. Under a list on
    top it is the list itself (a 1.4.4 file, with no 'source', is a list); under an award the list is in
    seniority_list.json. The award is seniority_award.json. (None, None) when there is no seniority.json: the Watcher
    then starts over from the text copies (seniority_refresh)."""
    out = out or seniority_file()
    view = _load_json(out)
    if not view:
        return None, None
    d = os.path.dirname(out)
    if str(view.get("source") or "list") == "list":
        lst = {k: v for k, v in view.items() if k not in SEN.VIEW_ONLY}
        lst["source"] = "list"
    else:
        lst = _load_json(os.path.join(d, SEN_LIST))
    return lst, seniority_award(out)


def seniority_award(out=None):
    """1.4.5: the newest award's dates of hire (seniority_award.json beside `out`), or None."""
    return _load_json(os.path.join(os.path.dirname(out or seniority_file()), SEN_AWARD))


def seniority_rebuild(lst, aw, out=None):
    """1.4.5: write seniority.json = seniority.combine(list, award) (atomic). Under an award on top the list is kept
    as seniority_list.json; with the list on top seniority.json is the list, and a leftover seniority_list.json goes.
    Returns what seniority.json now holds (None when there is neither)."""
    out = out or seniority_file()
    keep = os.path.join(os.path.dirname(out), SEN_LIST)
    view = SEN.combine(lst, aw)
    if view and lst and view.get("source") != "list":
        _dump(keep, dict({k: v for k, v in lst.items() if k not in SEN.VIEW_ONLY}, source="list"))
    elif os.path.exists(keep):
        os.remove(keep)
    if view:
        view["parser"] = SEN.PARSER
        _dump(out, view)
    return view


def seniority_store(parsed, pdf_name, uploaded_at, list_date="", out=None):
    """Store a dedicated seniority list parse with pilot rows (SEN.to_json, source 'list') and rebuild seniority.json
    (`out`, seniority_file() unless given) with the award on file: the list is on top unless that award is later
    (seniority.combine). Returns the list's dict."""
    d = SEN.to_json(parsed, pdf_name, uploaded_at, list_date)
    d["source"] = "list"
    _lst, aw = seniority_sources(out)
    seniority_rebuild(d, aw, out)
    return d


def seniority_write(txt_path, pdf_name, uploaded_at, list_date="", out=None):
    """Parse a seniority list text copy and write seniority.json (seniority_read + seniority_store). Returns the
    written dict, or None when no pilot row was read (the file on hand is kept). Nothing personal is logged."""
    parsed = seniority_read(txt_path, uploaded_at, list_date)
    return seniority_store(parsed, pdf_name, uploaded_at, list_date, out) if parsed["rows"] else None


def award_seniority(txt_path, month, pdf_name, uploaded_at, out=None):
    """1.4.5 (Ryan, Nov 6: the monthly award packet lists every pilot's date of hire): read an award's text copy for
    dates of hire (SEN.award_parse) and merge them into seniority.json. Rules:
      * fewer than SEN.AWARD_MIN pilot rows: nothing changes ('too-few'), so an award with no dates of hire never
        overwrites a good list;
      * an older award month than the award on file: nothing changes ('older-award');
      * else the award is kept as seniority_award.json (source 'award YYYY-MM') and seniority.json is rebuilt: the
        award goes on top when its bid period (or a list date printed in it) is later than the dedicated list's date
        ('on-top', the list's other pilots carried under it), else the list stays in use ('list-newer').
    Returns {rows, reader, rejects, month, decision, on_file?, view?} (counts only; nothing personal)."""
    out = out or seniority_file()
    parsed = SEN.award_parse(open(txt_path, encoding="utf-8", errors="replace").read(), int(month[:4]))
    info = {"rows": len(parsed["rows"]), "reader": parsed["reader"], "rejects": len(parsed["rejects"]), "month": month}
    if info["rows"] < SEN.AWARD_MIN:
        return dict(info, decision="too-few")
    lst, aw_on = seniority_sources(out)
    if aw_on and str(aw_on.get("award_month") or "") > month:
        return dict(info, decision="older-award", on_file=aw_on["award_month"])
    aw = SEN.to_json(parsed, pdf_name, uploaded_at)
    aw.update(source=f"award {month}", award_month=month, reader=parsed["reader"])
    _dump(os.path.join(os.path.dirname(out), SEN_AWARD), aw)
    view = seniority_rebuild(lst, aw, out)
    return dict(info, decision="on-top" if view.get("source") == aw["source"] else "list-newer", view=seniority_summary(view))


def award_note(info):
    """The upload result's sentence about an award's dates of hire (plain text, counts only)."""
    n, d = info.get("rows", 0), info.get("decision")
    if d == "too-few":
        return (f"No dates of hire read from it ({n} pilot rows; {SEN.AWARD_MIN} needed), so the seniority data on "
                "file is unchanged.")
    if d == "older-award":
        return f"Dates of hire: {n} pilots read, but the {info.get('on_file')} award on file is newer and stays in use."
    v = info.get("view") or {}
    if d == "list-newer":
        return (f"Dates of hire: {n} pilots read from its {info.get('reader')}; the seniority list on file "
                f"({v.get('as_of') or 'no date'}) is newer and stays in use.")
    more = f" ({v['carried']} more kept from the seniority list of {(v.get('base') or {}).get('as_of')})" if v.get("carried") else ""
    return f"Dates of hire: {n} pilots read from its {info.get('reader')}; {v.get('pilots', n)} pilots on file now{more}."


def seniority_summary(view):
    """What api/uploads and the upload result say about seniority.json (counts and dates only, no pilot)."""
    if not view:
        return None
    base = view.get("base") or {}
    return {"pilots": view.get("count", 0), "list_date": view.get("list_date") or "",
            "uploaded_at": view.get("uploaded_at") or "", "source": view.get("source") or "list",
            "file": view.get("file") or "", "as_of": SEN.as_of(view), "newest_doh": view.get("newest_doh") or "",
            "rejects": view.get("rejects", 0), "carried": view.get("carried", 0),
            "base": {"source": base.get("source"), "as_of": base.get("as_of"), "file": base.get("file")} if base else None}


def _seniority_line(d):
    if d.get("list_date"):
        when = f"list date {d['list_date']}"
    elif str(d.get("source") or "list").startswith("award"):
        when = f"as of {SEN.as_of(d)} (the award's bid period)"
    else:
        when = "no list date in the file"
    return (f"{d.get('count', 0)} pilots read, {when}, newest date of hire on it {d.get('newest_doh') or '?'}"
            f" ({d.get('rejects', 0)} lines not read)")


def _view_note(view):
    """A list upload under a later award: say the award's dates of hire stay on top."""
    if not view or str(view.get("source") or "list") == "list":
        return ""
    return (f" The {view['source']} on file is later ({SEN.as_of(view)}), so its dates of hire stay on top of this "
            f"list ({view.get('count', 0)} pilots in all).")


def _seniority_status():
    d = _load_json(seniority_file())
    if d is None:
        return "<p class='note'>No pilot seniority list on file: the pay line under a rebuilt month needs one.</p>"
    src = str(d.get("source") or "list")
    head = "Seniority list on file" if src == "list" else f"Dates of hire on file from the {src[6:]} award"
    more = f", {d['carried']} more kept from the seniority list of {(d.get('base') or {}).get('as_of')}" if d.get("carried") else ""
    return (f"<p class='note'>{html.escape(head)}: {html.escape(_seniority_line(d))}{html.escape(more)}; uploaded "
            f"{html.escape(str(d.get('uploaded_at') or '')[:16].replace('T', ' '))} HST "
            f"({html.escape(str(d.get('file') or ''))}). Every pilot instance reads it.</p>")


def _form(ctype, body):
    """(fields, file bytes or None) from a multipart/form-data body (the file in the part named pdf, or file)."""
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    fields, data = {}, None
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name in ("pdf", "file"):
            data = part.get_payload(decode=True)
        elif name:
            fields[name] = (part.get_payload(decode=True) or b"").decode(errors="replace").strip()
    return fields, data


def _why_no_text(e):
    """Why pdftotext gave no text copy, short and without the file's path."""
    if isinstance(e, subprocess.CalledProcessError):
        return f"pdftotext exit {e.returncode}: damaged or password-protected PDF?"
    if isinstance(e, subprocess.TimeoutExpired):
        return "pdftotext took over 2 minutes"
    return str(e)[:120]


@contextlib.contextmanager
def save_lock():
    """FW-0066: one save at a time, across threads (the Web UI, the MQTT thread's worker) and across the pilot
    instances' processes (an flock on LOCK_PATH)."""
    with _SAVE_LOCK:
        fd = None
        try:
            fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            fd = None  # no lock file (a read-only /tmp): the thread lock still holds within this process
        try:
            yield
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def save_upload(fields, data, log):
    """The one save path of the Web UI page, the dashboard card's ingress path and (1.4.8) an upload sent in chunks
    over MQTT: {ok, message (plain text), file?, seniority?, contacts?}. Stores one PDF as
    <YYYY-MM>_<award|pairings>.pdf plus a pdftotext -layout copy; a PDF that gives no text copy is refused and the
    month's file on file is kept. An award's text is also read for dates of hire (award_seniority; it never fails the
    upload). FW-0062: kind 'seniority' (no month) goes to _save_seniority: kept as seniority_<YYYY-MM-DD, HST upload
    day>.pdf and read into seniority.json only when it gives pilot rows. FW-0066: kind 'contacts' goes to
    _save_contacts."""
    month, kind = fields.get("month", ""), fields.get("kind", "")
    if kind not in KINDS or (kind in ("award", "pairings") and not re.fullmatch(r"\d{4}-\d{2}", month)):
        return {"ok": False, "message": "Pick a month and a kind."}
    if kind == "contacts":
        if CT.sniff(data) is None:
            return {"ok": False, "message": "That file is not a PDF, CSV or XLSX contact list."}
    elif not data or not data.startswith(b"%PDF"):
        return {"ok": False, "message": "That file is not a PDF."}
    with save_lock():
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        if kind == "contacts":
            return _save_contacts(data, log)
        if kind == "seniority":
            return _save_seniority(data, fields, log)
        return _save_monthly(data, month, kind, log)


def _save_monthly(data, month, kind, log):
    """An award or a pairings package (save_upload, under save_lock)."""
    path, kb = os.path.join(UPLOAD_DIR, f"{month}_{kind}.pdf"), len(data) // 1024
    tmp, txt = path[:-4] + ".new.pdf", path[:-4] + ".txt"
    # 1.4.5 review fix: staged like a seniority list (_save_seniority). The PDF is written and read under
    # <month>_<kind>.new.pdf / .new.txt and only a file that gives a text copy replaces the one on file, so a PDF
    # pdftotext cannot read (truncated, encrypted) never replaces a good one nor leaves the old text copy beside it.
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            subprocess.run(["pdftotext", "-layout", tmp, tmp[:-4] + ".txt"], check=True, timeout=120)
        except Exception as e:
            what = "award" if kind == "award" else "pairings package"
            kept = f"the {month} {what} on file is kept" if os.path.exists(path) else "nothing was saved"
            log.info("upload: %s %s (%d KB) gave no text copy; not kept", month, kind, kb)
            return {"ok": False, "message": f"Not kept: {os.path.basename(path)} ({kb} KB) gave no text copy "
                                            f"({_why_no_text(e)}), so the Watcher cannot read it; {kept}."}
        os.replace(tmp, path)
        os.replace(tmp[:-4] + ".txt", txt)
    finally:
        for f in (tmp, tmp[:-4] + ".txt"):
            try:
                os.remove(f)
            except OSError:
                pass
    log.info("upload: %s %s saved (%d KB)", month, kind, kb)
    out = {"ok": True, "message": f"Saved {os.path.basename(path)} ({kb} KB).", "file": os.path.basename(path)}
    if kind == "award":
        try:
            info = award_seniority(txt, month, os.path.basename(path), _hst_now().isoformat(timespec="seconds"))
            log.info("upload: %s award dates of hire: %d pilot rows (%s, %d lines not read), %s", month, info["rows"],
                     info["reader"], info["rejects"], info["decision"])
            out["seniority"] = {k: info[k] for k in ("rows", "reader", "decision", "view") if k in info}
            out["message"] += " " + award_note(info)
        except Exception as e:
            log.info("upload: %s award dates of hire not read: %s", month, e)
            out["message"] += f" Dates of hire not read ({str(e)[:120]})."
    return out


def upload_result(ctype, body, log):
    """A multipart upload body -> save_upload's dict; never raises."""
    try:
        return save_upload(*_form(ctype, body), log)
    except Exception as e:
        return {"ok": False, "message": f"Upload failed: {e}"}


def _save_upload(ctype, body, log, after=None):
    """The Web UI page's upload: save_upload's result as one HTML line."""
    r = upload_result(ctype, body, log)
    if after:
        after(r)
    return f"<p class='{'ok' if r['ok'] else 'err'}'>{html.escape(r['message'])}</p>"


def _save_seniority(data, fields, log):
    """FW-0062: a seniority list upload. It goes to a temporary name (seniority_<day>.new.pdf / .txt) and is read
    there; only a file that gives pilot rows is renamed to seniority_<YYYY-MM-DD, HST upload day>.pdf / .txt and
    written to seniority.json. A refused file (no text copy, no pilot rows) is deleted, so the list on file keeps its
    PDF and text copy (seniority_refresh re-reads that text after a parser change), even when the refused upload is
    on the same day. Returns save_upload's dict."""
    now = _hst_now()
    name = f"seniority_{now.strftime('%Y-%m-%d')}"
    final, tmp = os.path.join(UPLOAD_DIR, name + ".pdf"), os.path.join(UPLOAD_DIR, name + ".new.pdf")
    kb = len(data) // 1024
    kept = "the list on file is kept."
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            subprocess.run(["pdftotext", "-layout", tmp, tmp[:-4] + ".txt"], check=True, timeout=120)
        except Exception as e:
            log.info("upload: seniority list (%d KB) gave no text copy; not kept", kb)
            return {"ok": False, "message": f"Not kept: {name}.pdf ({kb} KB) gave no text copy ({_why_no_text(e)}), so "
                                            f"the list cannot be read; {kept}"}
        given = fields.get("list_date", "")
        given = given if re.fullmatch(r"\d{4}-\d{2}-\d{2}", given) else ""
        at = now.isoformat(timespec="seconds")
        parsed = seniority_read(tmp[:-4] + ".txt", at, given)
        if not parsed["rows"]:
            why = {r for r, _ in parsed.get("rejects") or []}
            log.info("upload: seniority list (%d KB) read no pilot rows (%d lines not read); not kept", kb,
                     len(parsed.get("rejects") or []))
            if "header-order" in why:
                return {"ok": False, "message": f"Not kept: {name}.pdf ({kb} KB). No pilot rows were read: its header "
                        "puts the columns in an order this version does not read (it needs EMP # before ALPA #, and "
                        f"DOH as the first date column); {kept}"}
            return {"ok": False, "message": f"Not kept: {name}.pdf ({kb} KB). No pilot rows were found in it (is it "
                                            f"the pilot seniority list?); {kept}"}
        os.replace(tmp, final)
        os.replace(tmp[:-4] + ".txt", final[:-4] + ".txt")
        d = seniority_store(parsed, name + ".pdf", at, given)
    finally:
        for f in (tmp, tmp[:-4] + ".txt"):
            try:
                os.remove(f)
            except OSError:
                pass
    log.info("upload: seniority list read, %d pilots, %d lines not read; saved (%d KB)", d["count"], d["rejects"], kb)
    view = _load_json(seniority_file())
    return {"ok": True, "message": f"Saved {name}.pdf ({kb} KB). {_seniority_line(d)}.{_view_note(view)}",
            "file": name + ".pdf", "seniority": {"view": seniority_summary(view)}}


def _private(path):
    """FW-0066: a contact list's files are readable by this app only."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _save_contacts(data, log):
    """FW-0066: a pilot contact list (PDF, CSV or XLSX; the type is read from the bytes). It is written mode 600
    under contacts_<HST day>.new.<ext> and read there (a PDF from its pdftotext copy); only a list that gives pilot
    contacts (a phone or an email with a name or employee number) replaces the one on file: it becomes
    contacts_<YYYY-MM-DD>.<ext> (any older contact list file goes) and CONTACTS_FILE is rewritten (mode 600). A refused
    file is deleted. The result and the log carry counts only, never a name, number or address."""
    ext = CT.sniff(data)
    if ext is None:
        return {"ok": False, "message": "That file is not a PDF, CSV or XLSX contact list."}
    now = _hst_now()
    name = f"contacts_{now.strftime('%Y-%m-%d')}"
    final, tmp = os.path.join(UPLOAD_DIR, f"{name}.{ext}"), os.path.join(UPLOAD_DIR, f"{name}.new.{ext}")
    ttxt = tmp.rsplit(".", 1)[0] + ".txt"
    kb, kept = len(data) // 1024, "the contact list on file is kept."
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        text = None
        if ext == "pdf":
            try:
                subprocess.run(["pdftotext", "-layout", tmp, ttxt], check=True, timeout=120)
                _private(ttxt)
                text = open(ttxt, encoding="utf-8", errors="replace").read()
            except Exception as e:
                log.info("upload: contact list (%d KB) gave no text copy; not kept", kb)
                return {"ok": False, "message": f"Not kept: {name}.pdf ({kb} KB) gave no text copy ({_why_no_text(e)}), "
                                                f"so the list cannot be read; {kept}"}
        try:
            parsed = CT.parse(data, ext, text)
        except Exception as e:
            log.info("upload: contact list (%d KB, %s) not read: %s", kb, ext, type(e).__name__)
            return {"ok": False, "message": f"Not kept: {name}.{ext} ({kb} KB) could not be read ({type(e).__name__}); "
                                            f"{kept}"}
        if not parsed["entries"]:
            log.info("upload: contact list (%d KB, %s) gave no pilot contacts (%d lines); not kept", kb, ext,
                     parsed["lines"])
            return {"ok": False, "message": f"Not kept: {name}.{ext} ({kb} KB). No pilot contacts were found in it "
                                            "(each pilot needs a name or employee number with a phone or an email); "
                                            f"{kept}"}
        for old in os.listdir(UPLOAD_DIR):
            if CONTACTS_RE.fullmatch(old) or re.fullmatch(r"contacts_\d{4}-\d{2}-\d{2}\.txt", old):
                try:
                    os.remove(os.path.join(UPLOAD_DIR, old))
                except OSError:
                    pass
        os.replace(tmp, final)
        if text is not None:
            os.replace(ttxt, final.rsplit(".", 1)[0] + ".txt")
        d = CT.build(parsed, os.path.basename(final), now.isoformat(timespec="seconds"))
        CT.store(CONTACTS_FILE, d)
    finally:
        for f in (tmp, ttxt):
            try:
                os.remove(f)
            except OSError:
                pass
    log.info("upload: pilot contact list read, %d pilots (%d with a phone, %d with an email, %d lines not read, "
             "%d with neither); saved (%d KB)", d["count"], d["with_phone"], d["with_email"], d["rejects"],
             d["skipped"], kb)
    more = f" {d['rejects']} lines with a phone or email but no pilot were not read." if d["rejects"] else ""
    return {"ok": True, "message": f"Saved {os.path.basename(final)} ({kb} KB). Pilot contacts: {d['count']} "
                                   f"pilot{'' if d['count'] == 1 else 's'}, "
                                   f"{d['with_phone']} with a phone, {d['with_email']} with an email.{more}",
            "file": os.path.basename(final), "contacts": CT.summary(d)}


def uploads_list():
    """1.4.5, api/uploads: the files on file, newest first: {name, kind (award | pairings | seniority | contacts |
    other), month (YYYY-MM; '' for a seniority or contact list), day (a seniority or contact list's HST upload day),
    size (bytes), uploaded_at (the file time, HST ISO), has_text (the Watcher can read it: a pdftotext copy beside a
    PDF; a CSV or XLSX contact list is read as it is)}. File names and sizes only: never a file's content."""
    try:
        names = sorted(f for f in os.listdir(UPLOAD_DIR) if ".new." not in f and
                       (f.endswith(".pdf") or CONTACTS_RE.fullmatch(f)))
    except OSError:
        return []
    out = []
    for f in names:
        try:
            st = os.stat(os.path.join(UPLOAD_DIR, f))
        except OSError:
            continue
        m = re.fullmatch(r"(\d{4}-\d{2})_(award|pairings)\.pdf", f)
        n = re.fullmatch(r"seniority_(\d{4}-\d{2}-\d{2})\.pdf", f)
        c = CONTACTS_RE.fullmatch(f)
        kind = m.group(2) if m else "seniority" if n else "contacts" if c else "other"
        text = (c and c.group(2) != "pdf") or os.path.exists(os.path.join(UPLOAD_DIR, f.rsplit(".", 1)[0] + ".txt"))
        out.append({"name": f, "kind": kind, "month": m.group(1) if m else "",
                    "day": n.group(1) if n else c.group(1) if c else "", "size": st.st_size,
                    "uploaded_at": hst_iso(st.st_mtime), "has_text": bool(text)})
    out.sort(key=lambda x: x["uploaded_at"], reverse=True)
    return out


def _month_shift(ym, k):
    y, m = divmod(int(ym[:4]) * 12 + int(ym[5:7]) - 1 + k, 12)
    return f"{y}-{m + 1:02d}"


def uploads_wanted(today=None, pdir=None, files=None):
    """FW-0057 (1.4.7 verify): the pairings packages the crew index still needs, so the card can ask for them: this
    bid month's and the previous one's (a trip another pilot started in the previous bid period and runs into this
    one is on no other file: until that package is on file it reaches the crew index only from pilot lookups), each
    while its pairing file (PAIRINGS_DIR/pairings_<YYYY-MM>.json) is missing and no upload of it is on file, back to
    the bid month of crewidx.CREW_FROM. `today` is an HST date (now by default), `files` uploads_list(). Oldest first:
    [{kind: 'pairings', month, why}]. Reads local files only; nothing goes to FLICA."""
    today = today or _hst_now().date()
    cur, floor = f"{today:%Y-%m}", f"{CI.CREW_FROM:%Y-%m}"
    have = {f.get("month") for f in (uploads_list() if files is None else files) if f.get("kind") == "pairings"}
    out = []
    for month in (_month_shift(cur, -1), cur):
        if month < floor or month in have or os.path.exists(os.path.join(pdir or PAIRINGS_DIR, f"pairings_{month}.json")):
            continue
        out.append({"kind": "pairings", "month": month, "why": "previous" if month < cur else "current"})
    return out


def uploads_json(version):
    """api/uploads (and, 1.4.8, sensor.<prefix>_uploads): {files, seniority (seniority_summary of seniority.json, or
    None), contacts (contacts.summary of contacts.json: counts and its file name only, or None), version, max_bytes
    (the largest file that gets through Home Assistant's ingress proxy, INGRESS_MAX), mqtt_max_bytes (the largest file
    sent in chunks over MQTT, UPLOAD_MAX), wanted (uploads_wanted: the pairings packages the crew index still
    needs)}."""
    files = uploads_list()
    return {"files": files, "seniority": seniority_summary(_load_json(seniority_file())),
            "contacts": CT.summary(CT.load(CONTACTS_FILE)), "version": version,
            "max_bytes": min(UPLOAD_MAX, INGRESS_MAX), "mqtt_max_bytes": UPLOAD_MAX, "wanted": uploads_wanted(files=files)}


SETTINGS_FIELDS = (  # (key, label, secret)
    ("username", "FLICA username", False), ("password", "FLICA password", True),
    ("ctweb_username", "CrewTrac username", False), ("ctweb_password", "CrewTrac password", True),
    ("my_name", "Last name", False))


def _settings_form(state):
    """The credentials form. Usernames and the name are shown; a password only as set / not set."""
    state = state or {}
    rows = []
    for k, label, secret in SETTINGS_FIELDS:
        if secret:
            has = state.get("has_" + k if k != "password" else "has_password")
            cur = "<b class='ok'>set</b>" if has else "<b class='err'>not set</b>"
            rows.append(f"<label><span class='k'>{label}</span> <input type='password' name='{k}' "
                        f"autocomplete='new-password' placeholder='leave blank to keep'> {cur}</label>")
        else:
            v = html.escape(str(state.get(k) or ""))
            rows.append(f"<label><span class='k'>{label}</span> <input type='text' name='{k}' value='{v}' "
                        f"autocomplete='off' spellcheck='false'></label>")
    return ("<p class='note'>Saved on this Home Assistant only (/data/creds.json, readable by this app alone), never "
            "in git. A blank field keeps what is saved. Saving restarts the Watcher; with a new FLICA username or "
            "password it logs in within a minute, unless FLICA asked for a CAPTCHA/MFA (then press Re-arm after "
            "dealing with FLICA yourself).</p>"
            "<form class='set' method='post' action='settings'>" + "".join(rows) +
            "<p><button type='submit'>Save settings</button></p></form>"
            "<form method='post' action='settings'><input type='hidden' name='clear' value='1'>"
            "<p class='note'>Saved values win over the Configuration tab. To go back to it: "
            "<button type='submit'>Clear saved values</button></p></form>")


def parse_settings(body):
    """Form body -> {key: value} for the non-blank settings fields (values stripped)."""
    q = parse_qs(body, keep_blank_values=True)
    out = {}
    for k, _label, _secret in SETTINGS_FIELDS:
        v = (q.get(k) or [""])[0].strip()
        if v:
            out[k] = v
    return out


def serve(port, version, get_rules, save_rules, store, log, get_settings=None, save_settings=None,
          clear_settings=None, on_saved=None):
    """The ingress page and its JSON endpoints. on_saved (1.4.8) runs after an upload is saved (the Watcher then
    publishes sensor.<prefix>_uploads); its failure never fails the upload."""
    def saved(r):
        if r.get("ok") and on_saved:
            try:
                on_saved()
            except Exception as e:  # noqa: BLE001
                log.info("upload: after-save hook failed: %s", type(e).__name__)
        return r

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _guard(self):
            if self.client_address[0] not in (INGRESS_IP, "127.0.0.1"):
                self.send_error(403)
                return False
            return True

        def _page(self, msg="", draft=None, settings_msg=""):
            body = PAGE.format(
                version=html.escape(version), msg=msg, month=_month_default(), uploads=_uploads_table(),
                max_mb=f"{INGRESS_MAX / 1048576:.1f}",
                seniority=_seniority_status(),
                settings_msg=settings_msg,
                settings=_settings_form(get_settings() if get_settings else {}) if save_settings else
                "<p class='note'>Not available on this instance.</p>",
                rules=html.escape(draft if draft is not None else json.dumps(get_rules(), indent=2)),
                schema=html.escape(SCHEMA_HELP),
                finds=_table(store.recent_finds(50), ["seen", "pairing", "dates", "days", "layover",
                                                      "report", "credit", "gone"]),
                matches=_table(store.recent_matches(50), ["at", "rule_id", "pairing", "dry_run",
                                                          "would_submit", "reason"]))
            b = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _json(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _api(self):
            """1.4.5: 'uploads' / 'upload' for a path under api/ (as the ingress proxy passes it on), '' for an
            unknown one under api/, None for the page's own paths."""
            p = urlsplit(self.path).path.rstrip("/")
            m = re.search(r"(?:^|/)api(?:/([a-z]*))?$", p)
            return (m.group(1) or "") if m else None

        def do_GET(self):
            if not self._guard():
                return
            api = self._api()
            if api == "uploads":
                return self._json(200, uploads_json(version))
            if api is not None:
                return self._json(404, {"ok": False, "message": "Not found."})
            self._page()

        def do_POST(self):
            if not self._guard():
                return
            n = int(self.headers.get("Content-Length", 0) or 0)
            api = self._api()
            if api is not None:  # 1.4.5: the dashboard uploads card
                if api != "upload":
                    return self._json(404, {"ok": False, "message": "Not found."})
                ctype = self.headers.get("Content-Type", "")
                if not ctype.lower().startswith("multipart/form-data"):
                    return self._json(400, {"ok": False, "message": "Send the PDF as a multipart form."})
                if n > UPLOAD_MAX:
                    return self._json(413, {"ok": False, "message": f"File too large ({UPLOAD_MAX // 1_000_000} MB max)."})
                if n <= 0:
                    return self._json(400, {"ok": False, "message": "No file received."})
                r = saved(upload_result(ctype, self.rfile.read(n), log))
                return self._json(200 if r["ok"] else 400, r)
            if self.path.rstrip("/").endswith("upload"):
                if n > UPLOAD_MAX:
                    return self._page("<p class='err'>File too large (25 MB max).</p>")
                return self._page(_save_upload(self.headers.get("Content-Type", ""), self.rfile.read(n), log, saved))
            if n > 200_000:
                self.send_error(413)
                return
            if self.path.rstrip("/").endswith("settings"):
                if not save_settings:
                    self.send_error(404)
                    return
                body = self.rfile.read(n).decode()
                if parse_qs(body).get("clear") == ["1"]:
                    if clear_settings and clear_settings():
                        return self._page(settings_msg="<p class='ok'>Saved values cleared: the Configuration tab "
                                          "applies again. The Watcher restarts in a few seconds.</p>")
                    return self._page(settings_msg="<p class='note'>Nothing saved here to clear.</p>")
                d = parse_settings(body)
                if not d:
                    return self._page(settings_msg="<p class='note'>Nothing to save: every field was blank.</p>")
                if save_settings(d):
                    return self._page(settings_msg="<p class='ok'>Saved. The Watcher restarts in a few seconds and "
                                      "logs in with the new details; reload this page in a minute.</p>")
                return self._page(settings_msg="<p class='note'>Nothing changed: those values were already saved.</p>")
            raw = parse_qs(self.rfile.read(n).decode()).get("rules", [""])[0]
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                return self._page(f"<p class='err'>Not valid JSON: {html.escape(str(e))}</p>", raw)
            errs = save_rules(data)
            if errs:
                msg = "<p class='err'>Not saved:<br>" + "<br>".join(html.escape(e) for e in errs) + "</p>"
                return self._page(msg, raw)
            log.info("rules saved from ingress page (%d rules)", len(get_rules()))
            self._page("<p class='ok'>Saved. Rules take effect on the next check.</p>")

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="ingress").start()
    return srv

"""1.8.0: the FLICA mirror (Ryan, Nov 23, 2026: "click on Open Time and have it refresh so I never get logged out").

FLICA allows one session per login and the Watcher owns it, so a second app that logs in on its own would kick the
Watcher (and the Watcher's next login would kick it). The mirror shows FLICA's own mobile pages to Ryan through the
Watcher's session instead: the ingress page `flica?u=<path>` asks the Watcher to load the page (through the same
FLICA gate as every other read, or from a copy the Watcher loaded under a minute ago), rewrites its links so a tap
stays in the mirror, and adds a bar with a refresh timer that only runs while the page is on screen.

Read only, like everything else in this app: only the pages below are ever loaded (GET), any link or query that
names a request, add, drop, swap, trade, bid or delete is never loaded, every form is shown disabled, and FLICA's
scripts are removed. No CAPTCHA is ever answered: a CAPTCHA page is shown as a note, never loaded again by the
mirror until the Watcher's own reads are fine. Pure functions here; watcher.py does the loading."""
import html as H
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

from bs4 import BeautifulSoup

FLICA = "https://ha2.flica.net"
HOST = "ha2.flica.net"
HST = timezone(timedelta(hours=-10))
# path (lower case) -> kind. Only FLICA's mobile read pages: the open time pot, a pairing's detail, the pilot's own
# schedule. Never mobileotrequest.cgi (requests), the Tradeboard, the main menu (it sits behind reCAPTCHA) or the
# desktop schedule page (FLICA answers it with a reCAPTCHA page).
PAGES = {"/full/mobileopentimepot.cgi": "pot", "/full/mobilepairing.cgi": "pairing",
         "/full/mobileschedule.cgi": "schedule"}
# a query key or value naming any of these is never loaded (read only: FLICA's request links are plain GETs)
BAD_WORDS = ("request", "submit", "delete", "drop", "swap", "add", "trade", "bid", "confirm", "award", "remove",
             "cancel", "priority", "quick", "action", "pickup", "giveaway", "propose")
MAX_U = 400
REFRESH_CHOICES = (60, 120, 300, 0)  # seconds; 0 = off
REFRESH_DEFAULT = 120
FRESH_S = 60  # a copy younger than this is shown without a new FLICA load


def page_kind(url):
    """'pot', 'pairing' or 'schedule' for a FLICA URL the mirror may load, else ''."""
    try:
        s = urlsplit(url or "")
    except ValueError:
        return ""
    if s.scheme != "https" or (s.hostname or "").lower() != HOST or s.port not in (None, 443) or s.username \
            or s.password:
        return ""
    kind = PAGES.get(s.path.lower(), "")
    if not kind:
        return ""
    for k, v in parse_qsl(s.query, keep_blank_values=True):
        kl, vl = k.lower(), v.lower()
        if any(w in kl for w in BAD_WORDS):
            return ""
        # FROM=MobileOpentimePot names where a pairing link came from; "From=MobileOTDrop/Swap" starts a request
        if any(w in vl for w in BAD_WORDS):
            return ""
    if kind == "schedule" and not any(k.lower() == "blockdate" for k, _ in parse_qsl(s.query)):
        return ""  # the mobile schedule without a BlockDate is the request flow's schedule (MobileOTDrop)
    return kind


def flica_url(u):
    """The FLICA URL for a mirror `u` (a FLICA path and query, as the mirror's own links carry it), or '' when it is
    not one the mirror loads."""
    u = (u or "").strip()
    if not u or len(u) > MAX_U or not u.startswith("/") or u.startswith("//") or "\\" in u \
            or any(ord(c) < 33 or ord(c) > 126 for c in u):
        return ""
    url = FLICA + u.split("#")[0]
    return url if page_kind(url) else ""


def mirror_href(url):
    """The mirror link (relative to the ingress page) for a FLICA URL the mirror loads, else ''."""
    if not page_kind(url):
        return ""
    s = urlsplit(url)
    return "flica?u=" + quote(s.path + ("?" + s.query if s.query else ""), safe="")


def _abs(page_url, ref):
    try:
        return urljoin(page_url, ref or "")
    except ValueError:
        return ""


def rewrite(page_html, page_url):
    """FLICA's page made safe to show in the mirror: no scripts or event handlers, links to pages the mirror loads
    point back into the mirror, other FLICA links are shown as plain text (opening FLICA itself would log in a second
    session and kick the Watcher), stylesheets and pictures load from FLICA by their full address, forms are disabled.
    Returns (the body's inner HTML, the head's stylesheet links, the page title)."""
    soup = BeautifulSoup(page_html or "", "html.parser")
    for t in soup.find_all(["script", "noscript", "iframe", "frame", "frameset", "object", "embed", "base"]):
        t.decompose()
    for t in soup.find_all("meta"):
        t.decompose()  # FLICA's refresh, charset and viewport tags: the mirror's page sets its own
    for t in soup.find_all(True):
        for a in list(t.attrs):
            if a.lower().startswith("on") or a.lower() in ("formaction", "srcdoc", "ping", "target"):
                del t.attrs[a]
    for a in soup.find_all("a"):
        ref = (a.get("href") or "").strip()
        if ref.replace(" ", "").lower() == "javascript:history.back()":
            a["href"] = "javascript:history.back()"
            continue
        url = _abs(page_url, ref) if ref and not ref.lower().startswith(("javascript:", "data:", "vbscript:")) else ""
        m = mirror_href(url) if url else ""
        if m:
            a["href"] = m
            continue
        s = urlsplit(url) if url else None
        if s and s.scheme in ("http", "https") and (s.hostname or "").lower() not in (HOST, "flica.net") \
                and not (s.hostname or "").lower().endswith(".flica.net"):
            a["href"] = url
            a["target"] = "_blank"
            a["rel"] = "noopener noreferrer"
            continue
        del a["href"]
        a["class"] = (a.get("class") or []) + ["fw-off"]
        a["title"] = "Not shown in the mirror (read only)"
    for t in soup.find_all(["img", "link", "input", "source"]):
        for att in ("src", "href", "srcset"):
            if t.get(att):
                v = _abs(page_url, t[att]) if att != "srcset" else ""
                if att == "srcset" or not v.startswith(FLICA + "/"):
                    del t[att]
                else:
                    t[att] = v
    for t in soup.find_all("link"):
        if "stylesheet" not in [r.lower() for r in (t.get("rel") or [])] or not t.get("href"):
            t.decompose()
    for f in soup.find_all("form"):
        f["action"] = "#"
        f["onsubmit"] = "return false"
        for el in f.find_all(["input", "button", "select", "textarea"]):
            el["disabled"] = "disabled"
    head = "".join(str(t) for t in soup.find_all("link"))
    for t in soup.find_all("link"):
        t.decompose()
    body = soup.body
    if body is not None:
        inner = "".join(str(c) for c in body.contents)
    else:
        for t in soup.find_all(["html", "head", "title"]):
            t.unwrap() if t.name != "title" else t.decompose()
        inner = str(soup)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return inner, head, title


def hst(ts):
    return datetime.fromtimestamp(float(ts or 0), HST).strftime("%H:%M:%S")


def nav(links, current):
    """The bar's page buttons: [(label, FLICA URL)]; the current one is marked."""
    out = []
    for label, url in links:
        m = mirror_href(url)
        if not m:
            continue
        cls = " class='on'" if url == current else ""
        out.append(f"<a{cls} href='{H.escape(m, quote=True)}'>{H.escape(label)}</a>")
    return "".join(out)


STYLE = """
html,body{margin:0;background:#fff;color:#111;font:15px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}
#fwbar{position:sticky;top:0;z-index:9;background:#0b3d6b;color:#fff;padding:6px 8px;display:flex;flex-wrap:wrap;
 gap:6px;align-items:center;font-size:14px}
#fwbar a{color:#fff;text-decoration:none;padding:5px 9px;border-radius:6px;background:rgba(255,255,255,.14)}
#fwbar a.on{background:#fff;color:#0b3d6b;font-weight:600}
#fwbar .sp{flex:1}
#fwbar select{font-size:13px}
#fwstat{background:#eef3f8;color:#234;padding:4px 8px;font-size:12px}
#fwnote{background:#fff4d6;color:#5a3d00;padding:8px;font-size:14px;border-bottom:1px solid #e6c766}
#fwpage{padding:0 4px 24px}
.fw-off{color:inherit;text-decoration:none;cursor:default}
"""

SCRIPT = """
(function(){
  var loaded = Date.now(), every = %(default)d, sel = document.getElementById('fwevery');
  try { var v = localStorage.getItem('fw_mirror_every'); if (v !== null && sel.querySelector('option[value="'+v+'"]')) every = +v; } catch (e) {}
  sel.value = String(every);
  sel.onchange = function(){ every = +sel.value; try { localStorage.setItem('fw_mirror_every', sel.value); } catch (e) {} tick(); };
  var cd = document.getElementById('fwcd');
  function tick(){
    if (!every) { cd.textContent = 'auto refresh off'; return; }
    var left = Math.max(0, Math.round((loaded + every * 1000 - Date.now()) / 1000));
    if (document.visibilityState !== 'visible') { cd.textContent = 'paused while hidden'; return; }
    cd.textContent = 'refresh in ' + left + ' s';
    if (left <= 0) { cd.textContent = 'refreshing'; loaded = Date.now() + 600000; location.reload(); }
  }
  setInterval(tick, 1000);
  document.addEventListener('visibilitychange', tick);
  tick();
})();
"""


def page(body_html, head_html, title, links, current, fetched_at, note="", age_s=None, version=""):
    """The mirror's whole page: bar, status line, an optional note, FLICA's page."""
    opts = "".join(f"<option value='{s}'>{('every ' + str(s // 60) + ' min') if s else 'off'}</option>"
                   for s in REFRESH_CHOICES)
    age = ""
    if fetched_at:
        age = f"FLICA copy from {hst(fetched_at)} HST"
        if age_s is not None and age_s >= 5:
            age += f" ({int(age_s)} s old)"
    stat = (f"<div id='fwstat'>{H.escape(age or 'No copy yet')} &middot; <span id='fwcd'></span>"
            f"{(' &middot; Flight Watcher ' + H.escape(version)) if version else ''}</div>")
    note_html = f"<div id='fwnote'>{note}</div>" if note else ""
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='apple-mobile-web-app-capable' content='yes'>"
            f"<title>{H.escape(title or 'FLICA')}</title>{head_html}<style>{STYLE}</style></head><body>"
            f"<div id='fwbar'>{nav(links, current)}<span class='sp'></span>"
            f"<a href='{H.escape(mirror_href(current) or 'flica', quote=True)}'>Refresh</a>"
            f"<select id='fwevery' aria-label='Auto refresh'>{opts}</select></div>{stat}{note_html}"
            f"<div id='fwpage'>{body_html}</div>"
            f"<script>{SCRIPT % {'default': REFRESH_DEFAULT}}</script></body></html>")


NOTES = {
    "paused": "Flight Watcher is paused, so the mirror is showing its last copy. Turn Pause off to see FLICA live.",
    "yielded": "You are signed in to FLICA somewhere else, so Flight Watcher stepped aside{until}. The mirror shows "
               "its last copy until then.",
    "stopped": "Flight Watcher is not signed in to FLICA right now ({state}). The mirror shows its last copy.",
    "busy": "FLICA is busy with Flight Watcher's own check. This is the last copy; it refreshes on the next timer.",
    "captcha": "FLICA answered this page with a CAPTCHA. Flight Watcher never answers one, so this page is held "
               "for now; the other pages still work.",
    "expired": "FLICA's session ended. Flight Watcher signs in again on its next check (a minute or two).",
    "killed": "FLICA ended this session because the same login was used somewhere else. Flight Watcher steps aside "
              "for 30 min, then signs in again.",
    "blocked": "FLICA showed a sign-in block or a security check. Flight Watcher stops on it and tells you.",
    "error": "FLICA did not answer ({why}). This is the last copy.",
    "none": "No copy of this page yet. It loads when Flight Watcher is signed in.",
    "refused": "That page is not shown in the mirror (read only: requests, adds, drops and swaps stay in FLICA).",
}


def note(kind, **kw):
    return H.escape(NOTES.get(kind, "").format(**{k: v or "" for k, v in kw.items()}))

"""Read-only map of FLICA's open time add / drop / swap request pages (0.4.10, for t1243).
Pure helpers, no I/O. The Watcher GETs only URLs that pass `safe_get`, saves the HTML to the
private captures folder (/share, never the repo) and Claude reads the forms from there to build
the live swap. Nothing here can submit: a request in FLICA is a POST or a GET carrying filled
Add/Drop lists, and both are refused."""
import re
from urllib.parse import urljoin, urlparse, parse_qs

HOST = "ha2.flica.net"
FOLLOW = re.compile(r"open\s*time|opentime|\bOT\b|request|trade|swap|drop|pickup|add", re.I)
UNSAFE_WORDS = re.compile(r"submit|process|confirm|delete|cancel|award|save|logout|signout|sign out", re.I)
LIST_PARAMS = ("addlist", "droplist", "swaplist", "aotsitemlist", "aotsvaluelist", "splitdetail",
               "secsplitdetail", "cansplitlist", "seccansplitlist")


def safe_get(url):
    """True only for a same-host http(s) URL whose query fills no request list and names no action."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or u.netloc.lower() != HOST:
        return False
    if UNSAFE_WORDS.search(u.path) or UNSAFE_WORDS.search(u.query):
        return False
    q = {k.lower(): v for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    return not any(any(x.strip() for x in q.get(p, [])) for p in LIST_PARAMS)


def links(html, base):
    """[(text, absolute url)] for <a href> and frame/iframe src, javascript: links dropped."""
    out = []
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if not href.lower().startswith("javascript"):
            out.append((text[:60], urljoin(base, href)))
    for m in re.finditer(r"<i?frame\b[^>]*src=[\"']([^\"']+)[\"']", html, re.I):
        out.append(("frame", urljoin(base, m.group(1))))
    return out


def forms(html):
    """[{'method','action','inputs':[(type,name,value)]}] for every form, for the swap mapping."""
    out = []
    for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", html, re.I | re.S):
        attrs, body = m.group(1), m.group(2)
        meth = (re.search(r"method=[\"']?(\w+)", attrs, re.I) or [None, "get"])[1].lower()
        act = (re.search(r"action=[\"']([^\"']*)", attrs, re.I) or [None, ""])[1]
        ins = []
        for tag in re.finditer(r"<(input|select|textarea)\b([^>]*)>", body, re.I):
            a = tag.group(2)
            name = re.search(r"name=[\"']([^\"']+)", a, re.I)
            if not name:
                continue
            typ = re.search(r"type=[\"']?(\w+)", a, re.I)
            val = re.search(r"value=[\"']([^\"']*)", a, re.I)
            ins.append((typ.group(1).lower() if typ else tag.group(1).lower(), name.group(1),
                        val.group(1)[:80] if val else ""))
        out.append({"method": meth, "action": act, "inputs": ins})
    return out

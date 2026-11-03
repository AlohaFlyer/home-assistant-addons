"""Reserve Grid (0.4.13, Ryan): per-day NET RESERVES with FLICA's own color. Pure, no I/O.

Green = a drop, or a swap that moves Ryan off that day, can be approved. Red or black = only an
add (pickup) is possible on that day. FLICA renders the color as a class buffer-color-green /
-red / -black on the NET RESERVES cell; the page is built from reserveGridService.cgi (JSON)."""
import re
from datetime import date

MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
ROW_RE = re.compile(r"<tr[^>]*fang-ng-repeat-end[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r'<td[^>]*class="([^"]*)"[^>]*>.*?ng-bind-template="([^"]*)"', re.S)
COLOR_RE = re.compile(r"buffer-color-(green|red|black)")


def _iso(ddmon, year):
    m = re.match(r"(\d{2})([A-Z]{3})", ddmon.strip().upper())
    if not m or m.group(2) not in MON:
        return None
    return date(year, MON[m.group(2)], int(m.group(1))).isoformat()


def parse_grid_html(html, year):
    """{iso_date: {'net': int, 'color': 'green'|'red'|'black', 'avail': int, 'open': int}} from the
    rendered page. Dates roll into the next year when the month goes backwards (Dec -> Jan)."""
    out, last_m = {}, 0
    for row in ROW_RE.findall(html):
        cells = CELL_RE.findall(row)
        if len(cells) < 4:
            continue
        d = _iso(cells[0][1], year)
        if not d:
            continue
        if int(d[5:7]) < last_m:
            year += 1
            d = _iso(cells[0][1], year)
        last_m = int(d[5:7])
        try:
            avail, open_, net = int(cells[1][1]), int(cells[2][1]), int(cells[3][1])
        except ValueError:
            continue
        c = COLOR_RE.search(cells[3][0])
        out[d] = {"net": net, "color": c.group(1) if c else "black", "avail": avail, "open": open_}
    return out


def _find_rows(data):
    """reserveGridService.cgi (seen 2026-11-03): {"success","total","root":{"BidPeriod","headings",
    "data":[{"date":"01NOV","avl":"14","odp":"0","net":"14","statusColor":{"net":"black"}}, ...]}}.
    Falls back to the first list of dicts found anywhere two levels deep."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    root = data.get("root")
    if isinstance(root, dict) and isinstance(root.get("data"), list):
        return root["data"]
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
        if isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, list) and vv and isinstance(vv[0], dict):
                    return vv
    return None


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def parse_grid_json(data, year):
    """{iso_date: {'net','color','avail','open'}} from reserveGridService JSON. Color comes from
    statusColor.net (FLICA's own green/red/black); a row without one counts as black. Dates roll
    into the next year when the month goes backwards (Dec -> Jan)."""
    rows = _find_rows(data)
    if not rows:
        return {}
    out, last_m = {}, 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        keys = {k.lower(): k for k in r}
        dk = keys.get("date") or next((keys[k] for k in keys if "date" in k or k in ("day", "dt")), None)
        nk = keys.get("net") or next((keys[k] for k in keys if "net" in k), None)
        if not dk or not nk:
            continue
        raw = str(r[dk]).strip()
        if re.match(r"\d{2}[A-Za-z]{3}", raw):
            d = _iso(raw, year)
            if d and int(d[5:7]) < last_m:
                year += 1
                d = _iso(raw, year)
        else:
            d = raw[:10]
        if not d:
            continue
        last_m = int(d[5:7]) if re.match(r"\d{4}-\d{2}", d) else last_m
        net = _int(r[nk], None)
        if net is None:
            continue
        sc = r.get("statusColor")
        color = str((sc or {}).get("net", "") if isinstance(sc, dict) else sc or "").lower()
        if not color:
            ck = next((keys[k] for k in keys if "color" in k or "colour" in k), None)
            color = str(r.get(ck, "")).lower() if ck else ""
        color = next((c for c in ("green", "red", "black") if c in color), "black")
        out[d] = {"net": net, "color": color,
                  "avail": _int(r.get(keys.get("avl") or keys.get("avail", ""), 0)),
                  "open": _int(r.get(keys.get("odp") or keys.get("open", ""), 0))}
    return out


def days_moved_off(mine_days, new_days):
    """Days Ryan's marked trip covers that the candidate does not: these must all be green."""
    return sorted(set(mine_days) - set(new_days))


def swap_allowed(grid, mine_days, new_days):
    """(ok, blocking_days): a swap is allowed when the candidate shares a day with the marked trip
    and every day moved off is green on the grid. Days without a grid entry count as not green."""
    if not set(mine_days) & set(new_days):
        return False, ["no shared day"]
    bad = [d for d in days_moved_off(mine_days, new_days) if (grid.get(d) or {}).get("color") != "green"]
    return (not bad), bad

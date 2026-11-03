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


def parse_grid_json(data, year):
    """Best effort on reserveGridService JSON: any list of row objects with a date and a net value.
    Field names are not known yet (captured on first read); returns {} when nothing fits."""
    rows = None
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                rows = v
                break
    elif isinstance(data, list):
        rows = data
    if not rows:
        return {}
    out = {}
    for r in rows:
        keys = {k.lower(): k for k in r}
        dk = next((keys[k] for k in keys if "date" in k or k in ("day", "dt")), None)
        nk = next((keys[k] for k in keys if "net" in k), None)
        ck = next((keys[k] for k in keys if "color" in k or "colour" in k), None)
        if not dk or not nk:
            continue
        d = _iso(str(r[dk]), year) if re.match(r"\d{2}[A-Za-z]{3}", str(r[dk])) else str(r[dk])[:10]
        try:
            net = int(r[nk])
        except (TypeError, ValueError):
            continue
        color = str(r.get(ck, "")).lower() if ck else ""
        color = next((c for c in ("green", "red", "black") if c in color), "")
        out[d] = {"net": net, "color": color or "black"}
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

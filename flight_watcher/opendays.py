"""1.8.4: the open days filter for the open time pot's new pairing alerts (Ryan, Nov 25, 2026: his open days in
December 2026 are Dec 3 to 11).

The add-on option `pot_open_days` is a list of date ranges, each "YYYY-MM-DD..YYYY-MM-DD" (both days included) or a
single day "YYYY-MM-DD". Empty (the default) keeps every alert as before. A range governs only the calendar months it
touches: a new pot pairing that starts in such a month alerts only when it starts on an open day and comes home by the
last day of that open stretch (ranges that touch or overlap are one stretch). A pairing that starts in a month no
range touches alerts as before, so a month nobody set up is never silenced. Pure functions, no FLICA, no I/O."""
import re
from datetime import date, timedelta

ITEM_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*(?:\.\.\s*(\d{4}-\d{2}-\d{2})\s*)?$")


def parse(items):
    """(stretches, bad): stretches is a sorted list of (first, last) dates with touching or overlapping ranges merged;
    bad lists the items that do not parse (a reversed range, a day that does not exist, any other text)."""
    spans, bad = [], []
    for it in items or []:
        m = ITEM_RE.match(str(it or ""))
        try:
            a = date.fromisoformat(m.group(1)) if m else None
            b = date.fromisoformat(m.group(2) or m.group(1)) if m else None
        except ValueError:
            a = b = None
        if a is None or b < a:
            bad.append(str(it))
            continue
        spans.append((a, b))
    spans.sort()
    out = []
    for a, b in spans:
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out, bad


def months(stretches):
    """The calendar months ('YYYY-MM') the stretches touch."""
    out = set()
    for a, b in stretches:
        d = a.replace(day=1)
        while d <= b:
            out.add(f"{d.year}-{d.month:02d}")
            d = (d + timedelta(days=32)).replace(day=1)
    return out


def verdict(stretches, start, end=None):
    """'' when the pairing (start, end: dates) may alert; else why it is held: 'starts <day>, not an open day' or
    'runs to <day>, past the last open day <day>'. No stretches, no start, or a start in a month no stretch touches:
    ''."""
    if not stretches or not start:
        return ""
    if f"{start.year}-{start.month:02d}" not in months(stretches):
        return ""
    end = end or start
    for a, b in stretches:
        if a <= start <= b:
            return "" if end <= b else f"runs to {end.isoformat()}, past the last open day {b.isoformat()}"
    return f"starts {start.isoformat()}, not an open day"

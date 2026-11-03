"""Swap ideas (0.4.9, Ryan): trips Ryan marked 'would trade' vs open time and Tradeboard pickups.
Pure, no I/O. Never submits anything: WRITES_IMPLEMENTED stays False until Ryan has confirmed a
dry run and the FLICA swap form is mapped (read only).

Better (Ryan, Nov 2 2026): more soft time (credit minus block) is what he wants, e.g. a 3-day LAS or
SMF at 15:00 credit. A candidate is better when its soft time beats the marked trip by MIN_SOFT_GAIN,
or its credit beats it by MIN_CREDIT_GAIN without losing soft time. Swapping a 2-day for a 3-day
that runs over a day off is fine; days he does not want to work are blocked on the calendar and
those candidates are dropped before this is called.
"""
from pot import hours

MIN_SOFT_GAIN = 0.5    # hours
MIN_CREDIT_GAIN = 1.0  # hours


def _fmt(h):
    m = round(abs(h) * 60)
    return f"{'+' if h >= 0 else '-'}{m // 60}:{m % 60:02d}"


def better(cand, mine):
    """(is_better, soft_gain_h, credit_gain_h, reason). cand/mine carry 'credit' and 'soft'
    (H:MM). Unknown credit on either side is never better."""
    cc, mc = hours(cand.get("credit")), hours(mine.get("credit"))
    if cc is None or mc is None:
        return False, 0.0, 0.0, "credit unknown"
    cs, ms = hours(cand.get("soft")) or 0.0, hours(mine.get("soft")) or 0.0
    ds, dc = cs - ms, cc - mc
    if ds >= MIN_SOFT_GAIN:
        return True, ds, dc, f"soft {_fmt(ds)}, credit {_fmt(dc)}"
    if dc >= MIN_CREDIT_GAIN and ds >= 0:
        return True, ds, dc, f"credit {_fmt(dc)}, soft {_fmt(ds)}"
    return False, ds, dc, f"soft {_fmt(ds)}, credit {_fmt(dc)}"


def fmt_gain(h):
    return _fmt(h)

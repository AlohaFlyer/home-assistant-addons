"""1.8.2 (transition audit T5 / LIVE-3, T9): the December award's carry-in and the Improved pay headline.

FLICA's December award prints the trip carried in from November left of the Dec 2 column, in its C/IN column, with a
'MonDD' marker (its first day) under the pilot's number. The parser put every pairing on the nearest day column, so the
carry-in became a Dec 2 trip priced from December's same-numbered pairing, and the first December trip, printed a few
characters right of the Dec 2 header, was dated Dec 2 though its release prints under the day it ends (it starts Dec 3).
The awarded line is version 12.001, so December's Awarded and Improved Pay-Gross were wrong and 12.002 showed fake
drops. The stored 12.001 is read again from its text copy after the update (no FLICA load); every other version stays.
Review (G4A-1, R3): a token is still on 1.8.1's nearest column unless its release time shows that column wrong, so a
line 1.8.1 read right (November's included) reads the same. Review (G4A-2): a first-day trip squeezed left of the first
header, with no marker, whose release prints where this period's pairing releases, is no carry-in.

T9: the Improved pay gross sensor's state was the latest month priced with no month label; it is now the bid month in
progress (Dec 1 is still November's), named in its month attribute.

All award text is synthetic in the award's fixed-width layout (column positions only): made-up pilots ("Doe, Jane"
99999, "Roe, Rick" 10001), made-up pairings H39xx, made-up days, credits, times and pay figures. FLICA is never
reached."""
import copy
import json
import os
import tempfile
from datetime import date, datetime, timedelta

import pytest

import pay as PAY
import pdfs as PDF
import pilotver as PV
import versions as VER
from pot import schedule_items
from store import Store
from test_fw181_pot_month import _periods, at
from test_release_a_flica import mk  # noqa: F401

# December's day columns (Dec 2 to 31) as the award prints them; 'C/IN' sits on the weekday line at column 17
HPOS = [25, 34, 44, 54, 64, 74, 84, 93, 102, 112, 122, 131, 141, 151, 160, 170, 180, 190, 199, 209, 219, 228,
        238, 248, 257, 267, 277, 286, 296, 306]


def col(day):
    """The header column of a December day (Dec 2 is the first)."""
    return HPOS[day - 2]


def _put(cells, width=320):
    s = [" "] * width
    for p, txt in cells:
        s[p:p + len(txt)] = list(txt)
    return "".join(s).rstrip()


def _block(sen, emp, name, cells, cr="052:20", off=16):
    """One pilot's five lines and a blank: number and report times, name with the carry-in marker and release times,
    credits, ids (after Days Off), seats. cells: [(col, report, release, credit, id, seat)], '' for none."""
    return [_put([(0, f"{sen} / {emp}")] + [(c[0], c[1]) for c in cells if c[1]]),
            _put([(0, name)] + [(c[0], c[2]) for c in cells if c[2]]),
            _put([(0, f"Cr:{cr}")] + [(c[0], c[3]) for c in cells if c[3]]),
            _put([(0, f"Days Off: {off}")] + [(c[0], c[4]) for c in cells if c[4]]),
            _put([(c[0], c[5]) for c in cells if c[5]]), ""]


# Doe (99999): the carry-in H3911 Nov 29 to Dec 2 (its Dec 2 release printed after its 'Nov29' marker), H3942 squeezed
# 3 characters right of the Dec 2 header (its release under Dec 5: Dec 3 to 5), H3944 Dec 13, H3946 Dec 20, VA Dec 26.
DOE = [(16, "09:15", "Nov29 14:05", "006:20", "H3911", "FO"), (28, "19:30", "", "013:40", "H3942", "FO"),
       (col(5), "", "14:55", "", "", ""),
       (col(13), "06:50", "", "011:15", "H3944", "RO"), (col(15), "", "17:05", "", "", ""),
       (col(20), "05:55", "", "009:05", "H3946", "FO"), (col(21), "", "12:10", "", "", ""),
       (col(26), "", "", "012:00", "VA", "")]
# Roe (10001): the carry-in H3912 Dec 1 to 2 ('Dec1': Dec 1 is November's bid period) and H3948 Dec 7 to 9
ROE = [(16, "10:40", "Dec1 19:10", "005:10", "H3912", "FO"), (col(7), "08:10", "", "012:30", "H3948", "FO"),
       (col(9), "", "15:45", "", "", "")]
HDR = _put([(p, str(d)) for p, d in zip(HPOS, range(2, 32))])


def award_text(blocks=((("00123", "99999", "DOE"), DOE), (("00456", "10001", "ROE"), ROE))):
    wd = ("Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue")
    dow = _put([(17, "C/IN")] + [(p, wd[k % 7]) for k, p in enumerate(HPOS)])
    out = ["                                      A332FO PBS BIDLINE AWARD",
           "                                       DECEMBER 2026 BID PERIOD",
           "                                         Posted November 12, 2026", dow, HDR, ""]
    for (sen, emp, name), cells in blocks:
        out += _block(sen, emp, name, cells)
    return "\n".join(out) + "\n"


def _duties(*spec):
    return [{"d": d, "dep": dep, "arr": arr, "stn": stn, "blk": blk} for d, dep, arr, stn, blk in spec]


def _det(report, block, credit, rel, lay, *duties):
    return {"report": report, "block": block, "credit": credit, "rel_days": rel, "lay": lay,
            "route": f"HNL-{lay}-HNL", "duties": _duties(*duties)}


# December's package: the same pairing numbers fly other trips there (H3911 is a BOS trip, 19:40 credit)
DEC_DET = {"H3911": _det("16:20", "17:30", "19:40", 2, "BOS", (0, 1040, 1660, "BOS", 620), (2, 3720, 4150, "HNL", 430)),
           "H3912": _det("07:45", "09:20", "11:05", 1, "SJC", (0, 525, 805, "SJC", 280), (1, 1900, 2180, "HNL", 280)),
           "H3942": _det("19:30", "11:20", "13:40", 2, "SEA", (0, 1230, 1560, "SEA", 330), (2, 3410, 3760, "HNL", 350)),
           "H3944": _det("06:50", "10:10", "11:15", 2, "PDX", (0, 470, 790, "PDX", 320), (2, 3600, 3890, "HNL", 290)),
           "H3946": _det("05:55", "08:30", "09:05", 1, "OAK", (0, 415, 670, "OAK", 255), (1, 1900, 2155, "HNL", 255)),
           "H3948": _det("08:10", "10:40", "12:30", 2, "SAN", (0, 550, 880, "SAN", 330), (2, 3500, 3810, "HNL", 310))}
# November's package: the carry-ins as FLICA flies them (H3911 a 4-day PPG trip, 16:30; H3912 a 2-day LAS trip)
NOV_DET = {"H3911": _det("09:15", "11:25", "16:30", 3, "PPG", (0, 615, 935, "PPG", 320), (3, 4785, 5150, "HNL", 365)),
           "H3912": _det("10:40", "10:35", "13:15", 1, "LAS", (0, 700, 1040, "LAS", 340), (1, 2280, 2575, "HNL", 295))}


def _items(aw):
    return [(i["trip"], i["start"], i["end"], i["lay"]) for i in aw["items"]]


def _starts(aw):
    return [(i["trip"], i["start"]) for i in aw["items"]]


def _one(cells, det=None, prev=None):
    """Doe's line with only these cells, read as December's award."""
    return PDF.parse_award(award_text(((("00123", "99999", "DOE"), cells),)), "99999",
                           DEC_DET if det is None else det, "2026-12", "2026-12-02", prev)


# ---------------------------------------------------------------- T5 / LIVE-3: the parser
def test_december_carry_in_is_dated_from_its_marker_and_the_squeezed_trip_from_its_release():
    """The carry-in is Nov 29 to Dec 2 (its 'Nov29' marker), never a Dec 2 trip; the first H3942 is Dec 3 (its column
    span, its release under Dec 5); the trips on their columns and the vacation are as before."""
    aw = PDF.parse_award(award_text(), "99999", DEC_DET, "2026-12", "2026-12-02")
    assert [(t, s, e) for t, s, e, _ in _items(aw)] == [
        ("H3911", "2026-11-29", "2026-12-02"), ("H3942", "2026-12-03", "2026-12-05"),
        ("H3944", "2026-12-13", "2026-12-15"), ("H3946", "2026-12-20", "2026-12-21"),
        ("VAC", "2026-12-26", "2026-12-28")]
    assert "H3911|2026-12-02" not in aw["trips"] and "H3942|2026-12-02" not in aw["trips"]
    carry = aw["trips"]["H3911|2026-11-29"]
    assert carry.get("credit") != "19:40" and carry.get("report") != "16:20"  # never December's same-numbered trip
    assert carry["seat"] == "FO" and carry["period_credit"] == "6:20"  # the Cr row's share: December's part
    assert aw["days"][0] == ["2026-12-02", "", "HNL"]  # the carry-in's last day, no trip starts on Dec 2
    assert aw["days"][1] == ["2026-12-03", "H3942", "SEA"] and aw["totals"]["credit"] == "52:20"


def test_carry_in_details_come_from_the_previous_bid_periods_package():
    """With November's package on file, the carry-in takes November's trip (PPG, 16:30, report 09:15, its duties): the
    whole trip, as every trip record holds it, which the card splits by bid period (PWA 4.A) as it splits FLICA's own
    record of the same trip. December's H3911 (BOS, 19:40) is never used."""
    aw = PDF.parse_award(award_text(), "99999", DEC_DET, "2026-12", "2026-12-02", NOV_DET)
    assert _items(aw)[0] == ("H3911", "2026-11-29", "2026-12-02", "PPG")
    assert aw["trips"]["H3911|2026-11-29"] == {"blk": "11:25", "credit": "16:30", "seat": "FO", "report": "09:15",
                                               "duties": NOV_DET["H3911"]["duties"], "period_credit": "6:20"}
    assert aw["trips"]["H3942|2026-12-03"]["credit"] == "13:40"
    roe = PDF.parse_award(award_text(), "10001", DEC_DET, "2026-12", "2026-12-02", NOV_DET)
    assert _items(roe) == [("H3912", "2026-12-01", "2026-12-02", "LAS"), ("H3948", "2026-12-07", "2026-12-09", "SAN")]
    assert (roe["trips"]["H3912|2026-12-01"]["credit"], roe["trips"]["H3912|2026-12-01"]["period_credit"]) == (
        "13:15", "5:10")


def test_carry_in_left_of_the_first_column_without_a_marker_and_the_year_turn():
    """A token left of the first day column is a carry-in even with no marker: its release day less the previous
    package's rel_days. A January award (Dec 31 to Jan 30) dates a 'Dec29' marker in December of the year before."""
    no_mark = award_text().replace("Nov29 14:05", "      14:05")
    aw = PDF.parse_award(no_mark, "99999", DEC_DET, "2026-12", "2026-12-02", NOV_DET)
    assert _items(aw)[0] == ("H3911", "2026-11-29", "2026-12-02", "PPG")
    jan = [str(d) for d in [31] + list(range(1, 30))]
    text = award_text().replace(HDR, _put([(p, d) for p, d in zip(HPOS, jan)])).replace("Nov29", "Dec29")
    aw = PDF.parse_award(text, "99999", {}, "2027-01", "2026-12-31", {"H3911": dict(NOV_DET["H3911"], rel_days=2)})
    assert _items(aw)[0] == ("H3911", "2026-12-29", "2026-12-31", "PPG")


# ---------------------------------------------------------------- review G4A-1 / R3: 1.8.1's column unless the release
def test_without_a_release_a_squeezed_token_keeps_the_nearest_column():
    """No release time to cross-check: the token keeps 1.8.1's nearest column, so a token squeezed right of the Dec 2
    header reads Dec 2 as 1.8.1 read it, and the rest of the line is as before. Only its release printed under the
    next column's day plus rel_days moves it (the first test)."""
    text = award_text()
    for t in ("14:55", "17:05", "12:10"):
        text = text.replace(t, "     ")
    aw = PDF.parse_award(text, "99999", DEC_DET, "2026-12", "2026-12-02")
    assert _starts(aw)[:4] == [("H3911", "2026-11-29"), ("H3942", "2026-12-02"), ("H3944", "2026-12-13"),
                               ("H3946", "2026-12-20")]


def test_a_token_right_of_its_header_keeps_its_day_unless_its_release_moves_it():
    """A token printed 1 to 4 characters off its own header (either side) is that header's day, as 1.8.1 read it,
    when no release is on the line, when its own release is, when the trip is not in the package, and for VA (no
    release at all). It moves to the next day only when it sits right of its header, no release prints under its
    day plus rel_days and one prints under the next day's (it is the next day's trip, squeezed left)."""
    for o in range(-4, 5):
        p = col(13) + o
        none = [(p, "06:50", "", "011:15", "H3944", "FO")]
        own = none + [(col(15), "", "17:05", "", "", "")]
        nxt = none + [(col(16), "", "17:05", "", "", "")]
        assert _starts(_one(none)) == [("H3944", "2026-12-13")], o
        assert _starts(_one(own)) == [("H3944", "2026-12-13")], o
        assert _starts(_one(nxt)) == [("H3944", "2026-12-14" if o > 0 else "2026-12-13")], o
        lost = [(p, "06:50", "", "011:15", "H3999", "FO"), (col(15), "", "17:05", "", "", "")]
        assert _starts(_one(lost)) == [("H3999", "2026-12-13")], o  # not in the package (rel_days 0)
        va = _one([(col(26) + o, "", "", "012:00", "VA", "")])
        assert _items(va) == [("VAC", "2026-12-26", "2026-12-28", "")], o
    one = {"H3944": DEC_DET["H3944"], "H3949": {"rel_days": 0, "credit": "6:00", "lay": ""}}
    one_day = _one([(col(13) + 1, "07:00", "", "006:00", "H3949", "FO"), (col(13) + 3, "", "13:00", "", "", "")],
                   det=one)
    assert _starts(one_day) == [("H3949", "2026-12-13")]  # a one-day trip, its release the same day
    # a trip not in the package (rel_days unknown) never moves on a release, and a trip whose own release is not on
    # the line never takes the next trip's (a one-day trip's release printed just left of its token)
    lost = _one([(col(13) + 2, "06:50", "", "011:15", "H3999", "FO"), (col(14), "", "17:05", "", "", "")])
    assert _starts(lost) == [("H3999", "2026-12-13")]
    steal = _one([(col(13) + 2, "06:50", "", "011:15", "H3944", "FO"), (col(16) - 1, "", "13:00", "", "", ""),
                  (col(16) + 1, "07:00", "", "006:00", "H3949", "FO")], det=one)
    assert _starts(steal) == [("H3944", "2026-12-13"), ("H3949", "2026-12-16")]


# ---------------------------------------------------------------- review G4A-2: a first-day trip squeezed left
def test_a_first_day_trip_squeezed_left_of_the_first_header_is_no_carry_in():
    """No marker and a token left of the Dec 2 header, nearer the C/IN label: when its release prints where this
    period's same-numbered pairing releases (Dec 2 plus its rel_days), or the previous period's package does not have
    it, it is this period's first-day trip with this period's details, not a carry-in dated Dec 1. A carry-in without a
    marker (in the previous package, its release on Dec 2) stays one; with no previous package on file it reads as
    1.8.1 read it until that package comes (the award is read again then)."""
    cells = [(20, "19:30", "", "013:40", "H3942", "FO"), (col(4), "", "14:55", "", "", "")]
    aw = _one(cells, prev=NOV_DET)
    assert _items(aw) == [("H3942", "2026-12-02", "2026-12-04", "SEA")]
    assert aw["trips"]["H3942|2026-12-02"]["credit"] == "13:40" and "period_credit" not in aw["trips"][
        "H3942|2026-12-02"]
    both = _one([(20, "16:20", "", "019:40", "H3911", "FO"), (col(4), "", "21:25", "", "", "")], prev=NOV_DET)
    assert _items(both) == [("H3911", "2026-12-02", "2026-12-04", "BOS")]  # in both packages: December's, by release
    assert both["trips"]["H3911|2026-12-02"]["credit"] == "19:40"
    no_rel = _one(cells[:1], prev=NOV_DET)  # no release on the line: this period's pairing only, no previous one
    assert _items(no_rel) == [("H3942", "2026-12-02", "2026-12-04", "SEA")]
    carry = _one([(20, "09:15", "      14:05", "006:20", "H3911", "FO")], prev=NOV_DET)
    assert _items(carry) == [("H3911", "2026-11-29", "2026-12-02", "PPG")]
    assert _items(_one(cells)) == [("H3942", "2026-12-02", "2026-12-04", "SEA")]  # no previous package on file
    assert _starts(_one([(20, "09:15", "      14:05", "006:20", "H3911", "FO")])) == [("H3911", "2026-12-02")]


# ---------------------------------------------------------------- T5 / LIVE-3: the stored 12.001 read again
def _setup(W, nov=True):
    _periods(W)  # November Nov 1 to Dec 1, December Dec 2 to 31
    os.makedirs(W.UPLOADS, exist_ok=True)
    path = os.path.join(W.UPLOADS, "2026-12_award.txt")
    with open(path, "w") as f:
        f.write(award_text())
    W.S["own_emp"] = "99999"
    if nov:
        W.DB.put("pkg_details:2026-11", NOV_DET)
    W.DB.put("pkg_details:2026-12", DEC_DET)
    mt = f"{os.path.getmtime(path):.0f}"
    for k in ("2026-11_pairings.txt", "2026-12_pairings.txt"):  # the packages were read before (no text copy here)
        W.S.setdefault("uploads_done", {})[k] = "x"
    W.S["uploads_done"]["2026-12_award.txt"] = mt  # 1.8.1 stored the award's mark as its file time only
    W.S.setdefault("pilotver_awards", {})["2026-12_award.txt"] = mt
    return mt


def _dec_days(marks):
    return [[f"2026-12-{d:02d}", *marks.get(d, ("", ""))] for d in range(2, 32)]


def _trip_1_8_1(pid, start, seat):
    dt = DEC_DET[pid]
    end = (date.fromisoformat(start) + timedelta(days=dt["rel_days"])).isoformat()
    return {"trip": pid, "start": start, "end": end, "lay": dt["lay"]}, {
        "blk": dt["block"], "credit": dt["credit"], "seat": seat, "report": dt["report"],
        "duties": copy.deepcopy(dt["duties"])}


def _old_award(full=True):
    """12.001 exactly as 1.8.1's parser (c868152 pdfs.parse_award) read Doe's line (full) or its first two pairings and
    release (the card's line): the carry-in on Dec 2 as December's H3911 (BOS, 19:40, its duties), H3942 on Dec 2 too,
    the days as its day loop made them (the later trip's code on Dec 2). Checked against that parser when written."""
    rows = [("H3911", "2026-12-02", "FO"), ("H3942", "2026-12-02", "FO")]
    marks = {2: ("H3942", "SEA"), 3: ("", "-"), 4: ("", "HNL")}
    if full:
        rows += [("H3944", "2026-12-13", "RO"), ("H3946", "2026-12-20", "FO")]
        marks.update({13: ("H3944", "PDX"), 14: ("", "-"), 15: ("", "HNL"), 20: ("H3946", "OAK"), 21: ("", "HNL"),
                      26: ("VAC", ""), 27: ("VAC", ""), 28: ("VAC", "")})
    items, trips = [], {}
    for pid, start, seat in rows:
        it, tr = _trip_1_8_1(pid, start, seat)
        items.append(it)
        trips[f"{pid}|{start}"] = tr
    if full:
        items.append({"trip": "VAC", "start": "2026-12-26", "end": "2026-12-28", "lay": ""})
    return {"items": items, "days": _dec_days(marks), "totals": {"credit": "52:20", "days_off": 16},
            "updated": "Award posted November 12, 2026", "trips": trips}


def _flica_ver(items, extra=()):
    return {"items": items + list(extra), "days": [[f"2026-12-{d:02d}", "", ""] for d in range(1, 32)],
            "totals": {"credit": "58:05"}, "updated": "Nov 22, 2026", "trips": {}}


FL_ITEMS = [{"trip": "H3911", "start": "2026-11-29", "end": "2026-12-02", "lay": "PPG"},
            {"trip": "H3942", "start": "2026-12-03", "end": "2026-12-05", "lay": "SEA"},
            {"trip": "H3944", "start": "2026-12-13", "end": "2026-12-15", "lay": "PDX"},
            {"trip": "H3946", "start": "2026-12-20", "end": "2026-12-21", "lay": "OAK"},
            {"trip": "VAC", "start": "2026-12-26", "end": "2026-12-28", "lay": ""}]
TRADE_LINE = "traded H3970 2026-12-30 (Tradeboard, approved Nov 23)"  # a line trades.py writes, no recompute gives


def _imp(W):
    return W.MQ.last(f"{W.T}/improved_pay")


def test_the_stored_december_award_is_read_again_and_every_other_version_stays(mk):
    """After the update the stored 12.001 (1.8.1's parse) is read again from its text copy: the carry-in Nov 29 from
    November's package, H3942 Dec 3; 12.002 (FLICA) no longer shows the fake drops and adds; 12.003 (with a line no
    recompute gives) and November's versions are as stored; December's stale Improved pay is dropped for the card to
    price again, and the sensor says so; a looked-up pilot's award (.001) is read again too. A second pass changes
    nothing. No FLICA load (no browser at all)."""
    W = mk("", t=at(2026, 11, 24, 9))
    mt = _setup(W)
    W.DB.put("sched_versions:2026-11", [{"ver": "11.001", "n": 1, "award": True, "items": [], "days": [],
                                          "changes": ["awarded line (PBS bid run)"], "at": "2026-10-12T00:00:00Z"}])
    nov_before = W.DB.get("sched_versions:2026-11")
    VER.set_award(W.DB, "2026-12", _old_award(), "2026-11-12T20:00:00+00:00")
    VER.update(W.DB, {"2026-12": _flica_ver(FL_ITEMS)}, {}, "2026-11-22T02:37:00+00:00")
    VER.update(W.DB, {"2026-12": _flica_ver(FL_ITEMS, [{"trip": "H3970", "start": "2026-12-30", "end": "2026-12-31",
                                                         "lay": "SFO"}])}, {}, "2026-11-23T10:53:00+00:00")
    vs = W.DB.get("sched_versions:2026-12")
    vs[2]["changes"] = [TRADE_LINE]  # 1.8.2 review (R2): the stored changes stay, never compared again
    W.DB.put("sched_versions:2026-12", vs)
    before = W.DB.get("sched_versions:2026-12")
    assert "dropped H3911 2026-12-02" in before[1]["changes"]  # what 1.8.1 shows on 12.002
    W.DB.put("improved_pay", {"2026-11": {"month": "2026-11", "awarded": 30000.0, "current": 31000.0,
                                          "improved": 1000.0},
                              "2026-12": {"month": "2026-12", "awarded": 30000.0, "current": 26000.0,
                                          "improved": -4000.0}})
    W.publish_improved()
    assert _imp(W)["ytd"] == -3000.0
    # a looked-up pilot with a December version and 1.8.1's award (.001) from the same text
    PV.register(W.DB, "10001", "Roe, Rick", "2026-11-20T00:00:00+00:00")
    PV.capture_lookup(W.DB, "10001", "Roe, Rick", {"month": "2026-12", "updated": "Nov 20, 2026", "items": [
        {"trip": "H3948", "start": "2026-12-07", "end": "2026-12-09", "lay": "SAN"}], "days": [], "totals": {}},
        "2026-11-20T00:00:00+00:00", ("2026-12-01", "2026-12-31"))
    old = {"items": [{"trip": "H3912", "start": "2026-12-02", "end": "2026-12-03", "lay": "SJC"}], "days": [],
           "updated": "Award posted Nov 12, 2026"}
    PV.set_award(W.DB, "10001", "2026-12", old, "2026-11-20T00:00:00+00:00", ("2026-12-01", "2026-12-31"), "2026-12-01")

    W.uploads_check()

    vers = W.DB.get("sched_versions:2026-12")
    assert [v["ver"] for v in vers] == ["12.001", "12.002", "12.003"]
    assert _starts(vers[0])[:2] == [("H3911", "2026-11-29"), ("H3942", "2026-12-03")]
    assert vers[0]["trips"]["H3911|2026-11-29"]["credit"] == "16:30" and "H3911|2026-12-02" not in vers[0]["trips"]
    assert vers[0]["at"] == before[0]["at"]  # the awarded line keeps its place in time
    assert not [c for c in vers[1]["changes"] if c.startswith(("dropped", "added"))]  # no fake drops or adds
    assert vers[2] == before[2] and vers[2]["changes"] == [TRADE_LINE]  # every later version as stored
    assert {k: v for k, v in vers[1].items() if k != "changes"} == {
        k: v for k, v in before[1].items() if k != "changes"}
    assert W.DB.get("sched_versions:2026-11") == nov_before
    imp = W.DB.get("improved_pay")
    assert "2026-12" not in imp and imp["2026-11"]["improved"] == 1000.0  # the card prices December again
    p = _imp(W)  # 1.8.2 review (R2): the sensor (the bar and YTD Ryan sees) drops December's stale row at once
    assert [r["month"] for r in p["months"]] == ["2026-11"] and p["ytd"] == 1000.0
    assert (p["month"], p["improved"]) == ("2026-11", 1000.0)
    roe = PV.versions_of(W.DB, "10001", "2026-12")
    assert roe[0]["source"] == "award" and (roe[0]["items"][0]["trip"], roe[0]["items"][0]["start"]) == (
        "H3912", "2026-12-01")
    assert W.S["uploads_done"]["2026-12_award.txt"].startswith(mt + "|")  # the parser's version is in the mark now

    def snap():  # a second pass: nothing is read again
        return json.dumps(W.DB.get("sched_versions:2026-12")), json.dumps(PV.versions_of(W.DB, "10001", "2026-12"))
    s1 = snap()
    W.uploads_check()
    assert snap() == s1


def test_the_award_is_read_again_when_the_month_befores_package_comes(mk):
    """1.8.2 review (R2): read before November's package was on file, the carry-in has its dates but no details. When
    the package comes, the next look at the uploads reads the same award again (its mark names the package) and the
    carry-in takes November's trip; the line keeps its time and the version after it is compared again."""
    W = mk("", t=at(2026, 11, 24, 9))
    mt = _setup(W, nov=False)
    W.uploads_check()
    vers = W.DB.get("sched_versions:2026-12")
    at0 = vers[0]["at"]
    assert _items(vers[0])[0] == ("H3911", "2026-11-29", "2026-12-02", "")
    assert "credit" not in vers[0]["trips"]["H3911|2026-11-29"]
    assert W.S["uploads_done"]["2026-12_award.txt"] == f"{mt}|a{PDF.AWARD_PARSER}"
    VER.update(W.DB, {"2026-12": _flica_ver(FL_ITEMS)}, {}, "2026-11-25T02:37:00+00:00")
    W.DB.put("pkg_details:2026-11", NOV_DET)  # November's package read now
    W.uploads_check()
    vers = W.DB.get("sched_versions:2026-12")
    assert [v["ver"] for v in vers] == ["12.001", "12.002"] and vers[0]["at"] == at0
    assert _items(vers[0])[0] == ("H3911", "2026-11-29", "2026-12-02", "PPG")
    assert vers[0]["trips"]["H3911|2026-11-29"]["credit"] == "16:30"
    assert W.S["uploads_done"]["2026-12_award.txt"] == f"{mt}|a{PDF.AWARD_PARSER}|c"


def test_an_award_read_again_unchanged_leaves_every_version_as_stored(mk):
    """A month whose award reads the same with the new parser (no carry-in, nothing squeezed) is not stored again:
    its versions, their times and changes stay byte for byte, and its Improved pay stays."""
    W = mk("", t=at(2026, 11, 24, 9))
    _setup(W)
    aw = PDF.parse_award(award_text(), "99999", DEC_DET, "2026-12", "2026-12-02", NOV_DET)
    VER.set_award(W.DB, "2026-12", aw, "2026-11-12T20:00:00+00:00")
    one = [{"trip": "H3942", "start": "2026-12-03", "end": "2026-12-05", "lay": "SEA"}]
    VER.update(W.DB, {"2026-12": _flica_ver(one)}, {}, "2026-11-22T02:37:00+00:00")
    W.DB.put("improved_pay", {"2026-12": {"month": "2026-12", "awarded": 1.0, "current": 2.0, "improved": 1.0}})
    before = json.dumps(W.DB.get("sched_versions:2026-12"))
    W.uploads_check()
    assert json.dumps(W.DB.get("sched_versions:2026-12")) == before
    assert W.DB.get("improved_pay")["2026-12"]["improved"] == 1.0


# ---------------------------------------------------------------- T9: the Improved pay headline
def test_improved_pay_headline_is_the_bid_month_in_progress_and_says_which(mk):
    """The state is the bid month in progress, named in its month attribute (Dec 1 is still November's); the months,
    ytd and the cards' attributes are as before. A month not priced yet headlines the latest month before it."""
    W = mk("", t=at(2026, 11, 24, 9))
    _periods(W)
    W.DB.put("improved_pay", {
        "2026-11": {"month": "2026-11", "awarded": 30000.0, "current": 31000.0, "improved": 1000.0},
        "2026-12": {"month": "2026-12", "awarded": 31000.0, "current": 30500.0, "improved": -500.0}})
    for t, want in ((at(2026, 11, 24, 9), ("2026-11", 1000.0)), (at(2026, 11, 30, 23), ("2026-11", 1000.0)),
                    (at(2026, 12, 1, 12), ("2026-11", 1000.0)), (at(2026, 12, 2, 0, 5), ("2026-12", -500.0))):
        W.CLOCK.t = t
        W._THIS_MONTH.update(day=None)
        W.publish_improved()
        p = _imp(W)
        assert (p["month"], p["improved"]) == want, t
        assert [r["month"] for r in p["months"]] == ["2026-11", "2026-12"] and p["ytd"] == 500.0
    W.DB.put("improved_pay", {"2026-11": {"month": "2026-11", "improved": 1000.0}})
    W.publish_improved()  # Dec 2: December not priced yet
    assert (_imp(W)["month"], _imp(W)["improved"]) == ("2026-11", 1000.0)


def test_improved_pay_headline_follows_the_bid_month_change_without_a_card_report(mk):
    """The janitor's tick republishes the headline when the bid month changes (Dec 2 00:00 HST), not before."""
    W = mk("", t=at(2026, 12, 1, 23, 50))
    _periods(W)
    W.DB.put("improved_pay", {"2026-11": {"month": "2026-11", "improved": 1000.0},
                              "2026-12": {"month": "2026-12", "improved": -500.0}})
    W.publish_improved()
    n = len(W.MQ.msgs)
    W.improved_tick()
    assert len(W.MQ.msgs) == n  # same bid month: nothing sent
    W.CLOCK.t = at(2026, 12, 2, 0, 1)
    W._THIS_MONTH.update(day=None)
    W.improved_tick()
    assert (_imp(W)["month"], _imp(W)["improved"]) == ("2026-12", -500.0)


def test_the_upload_janitor_moves_the_headline_at_the_bid_month_change(mk, monkeypatch):
    """1.8.2 review (R2): the uploads janitor's minute pass is what runs improved_tick: one pass after Dec 2 00:00 HST
    republishes the headline as December's, with no card report and no FLICA load."""
    W = mk("", t=at(2026, 12, 1, 23, 50))
    _periods(W)
    W.DB.put("improved_pay", {"2026-11": {"month": "2026-11", "improved": 1000.0},
                              "2026-12": {"month": "2026-12", "improved": -500.0}})
    W.publish_improved()
    assert _imp(W)["month"] == "2026-11"
    W.CLOCK.t = at(2026, 12, 2, 0, 1)
    W._THIS_MONTH.update(day=None)

    class Stop(BaseException):
        pass

    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) > 1:
            raise Stop()
    monkeypatch.setattr(W.time, "sleep", sleep)
    monkeypatch.setattr(W, "UPLOADS_PUB_S", W.UPLOAD_SWEEP_S)  # the minute pass on the first sweep
    monkeypatch.setattr(W, "assembler", lambda: type("A", (), {"sweep": lambda self: []})())
    with pytest.raises(Stop):
        W.upload_janitor()
    assert (_imp(W)["month"], _imp(W)["improved"]) == ("2026-12", -500.0)


# ---------------------------------------------------------------- T5 / LIVE-3: the card prices the line read again
def _card_pkgs():
    from test_crew_index import COLS
    from test_fw1711_totals import _leg

    def row(pid, report, dep, rel, rel_days, fdm, route, credit, tafb, days, block):
        return [pid, report, dep, rel, rel_days, fdm, route, credit, tafb, days, block, "CA01FO01"]
    nov_det = {"H3911": {"eq": "332", "crew": "CA01FO01", "rept": "09:15", "tot": {"block": "11h25", "credit": "16h30"},
                         "duties": [{"legs": [_leg("1", "9081", "HNL", "PPG", "10:15", "15:35", "5h20", "5h20")],
                                     "tblk": "5h20", "tcrd": "10h10", "stn": "PPG"},
                                    {"legs": [_leg("4", "9082", "PPG", "HNL", "07:45", "13:50", "6h05", "6h20")],
                                     "tblk": "6h05", "tcrd": "6h20", "stn": "HNL"}]}}

    def pk(m, a, b, rows, det):
        return {"month": m, "source": "synthetic", "start": a, "end": b, "cols": COLS, "rows": rows, "dv": 2,
                "detail": det}
    nov = [row("H3911", "09:15", "10:15", "14:05", 3, 615, "HNL-PPG-HNL", "16h30", "76h50", "29", "11:25")]
    dec = [row("H3911", "16:20", "17:20", "23:55", 2, 1040, "HNL-BOS-HNL", "19h40", "55h35", "2 16", "17:30"),
           row("H3942", "19:30", "20:30", "14:55", 2, 1230, "HNL-SEA-HNL", "13h40", "43h15", "3", "11:20")]
    return {"2026-11": pk("2026-11", "2026-11-01", "2026-12-01", nov, nov_det),
            "2026-12": pk("2026-12", "2026-12-02", "2026-12-31", dec, {})}


CARD_JS = """(h) => new Promise((res) => {
  const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({}); document.body.appendChild(c);
  const cs = (d, s, x) => (window.sent = window.sent || []).push(x);
  c.hass = {states: h, callService: cs};
  setTimeout(() => { c.hass = {states: h, callService: cs}; setTimeout(() => {
    res((window.sent || []).filter((x) => (x.topic || '').endsWith('improved/set')).map((x) => JSON.parse(x.payload)));
  }, 700); }, 400); })"""


def test_the_card_prices_decembers_line_read_again_with_no_phantom_trip():
    """Chromium: Ryan's schedule card prices December's awarded line (12.001) and FLICA's (12.002), the same trips.
    Read by 1.8.1 the award dated the carry-in Dec 2 as December's H3911 and H3942 Dec 2, so the awarded line held a
    phantom December trip and Improved-Pay-Gross read hours negative; read again, the carry-in is the same PPG trip on
    both lines (its December part by TCRD, PWA 4.A) and a line FLICA still holds as awarded improves by nothing."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    from test_release_a_schedule_card import _src, _states

    def month(first, last, marks, credit):
        a, b = datetime.fromisoformat(first), datetime.fromisoformat(last)
        days = [[(a + timedelta(days=k)).date().isoformat(), "", ""] for k in range((b - a).days + 1)]
        for d in days:
            d[1:] = list(marks.get(d[0], ("", "")))
        return {"items": schedule_items(days), "days": days, "totals": {"credit": credit, "days_off": 16},
                "updated": "Nov 22, 2026"}
    marks = {"2026-11-29": ("H3911", "PPG"), "2026-11-30": ("", "-"), "2026-12-01": ("", "-"),
             "2026-12-02": ("", "HNL"), "2026-12-03": ("H3942", "SEA"), "2026-12-04": ("", "-"),
             "2026-12-05": ("", "HNL")}
    nov = month("2026-11-01", "2026-12-01", marks, "47:10")
    dec = month("2026-11-29", "2026-12-31", marks, "20:00")
    own = {"H3911|2026-11-29": {"blk": "11:25", "credit": "16:30", "seat": "FO", "report": "09:15",
                                "duties": copy.deepcopy(NOV_DET["H3911"]["duties"])},
           "H3942|2026-12-03": {"blk": "11:20", "credit": "13:40", "seat": "FO", "report": "19:30",
                                "duties": copy.deepcopy(DEC_DET["H3942"]["duties"])}}
    text = award_text(((("00123", "99999", "DOE"), DOE[:3]),))
    new = PDF.parse_award(text, "99999", DEC_DET, "2026-12", "2026-12-02", NOV_DET)
    old = _old_award(full=False)  # 1.8.2 review (R4): as 1.8.1 stored it, December's details and duties included

    def states(aw):
        db = Store(os.path.join(tempfile.mkdtemp(), "v.db"))
        VER.set_award(db, "2026-12", aw, "2026-11-12T20:00:00+00:00")
        VER.update(db, {"2026-12": dec}, own, "2026-11-22T02:37:00+00:00")
        st = _states({"2026-11": nov, "2026-12": dec}, VER.published(db, ["2026-12"]), {"ok": True, "why": ""},
                     "Nov 22, 2026")
        st["sensor.flight_watcher_schedule"]["attributes"]["periods"] = {
            "2026-11": {"start": "2026-11-01", "end": "2026-12-01", "src": "package"},
            "2026-12": {"start": "2026-12-02", "end": "2026-12-31", "src": "package"}}
        st["input_number.flight_watcher_month_offset"]["state"] = "1"
        st["sensor.flight_watcher_state"]["attributes"]["doh"] = "2017-04-11"
        for k, val in (("federal_tax_pct", "22.0"), ("state_tax_pct", "0.0"), ("longevity_year", "9.0")):
            st[f"input_number.flight_watcher_{k}"] = {"state": val, "last_updated": "a", "attributes": {}}
        st["sensor.flight_watcher_own_trip_times"] = {"state": "2", "last_updated": "a",
                                                      "attributes": {"count": 2, "trips": own}}
        return st
    stub = ("window.fetch = async (u) => { const m = /pairings_(\\d{4}-\\d{2})\\.json/.exec(String(u)); const P = "
            + json.dumps(_card_pkgs()) + "; return m && P[m[1]] ? {ok: true, json: async () => P[m[1]]} : "
            "{ok: false, json: async () => null}; };")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            + stub + "</script><script>" + _src() + "</script></body></html>")
    got = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for name, aw in (("read_again", new), ("by_1_8_1", old)):
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.clock.set_fixed_time("2026-11-24T19:00:00Z")  # Nov 24 09:00 HST
                pg.set_content(page)
                got[name] = [x for x in pg.evaluate(CARD_JS, states(aw)) if x["month"] == "2026-12"]
                pg.close()
        finally:
            b.close()
    rate = PAY.rate_for(9, "2026-12-02")
    fixed, bad = got["read_again"][-1], got["by_1_8_1"][-1]
    assert abs(fixed["current"] - fixed["awarded"]) < 0.02, got  # the same line: no improvement, no loss
    assert fixed["current"] > (6 + 20 / 60 + 13 + 40 / 60) * rate - 1  # the carry-in's 6:20 and H3942's 13:40 at least
    # 1.8.1's line (review R4: as 1.8.1 stored it): the phantom December H3911 (19:40) on the awarded line where the
    # carry-in's December part (6:20) is, so Awarded is above Current and Improved reads 13:20 negative
    assert bad["awarded"] > bad["current"], got
    assert abs(bad["awarded"] - bad["current"] - (19 + 40 / 60 - 6 - 20 / 60) * rate) < 0.1 * rate, got

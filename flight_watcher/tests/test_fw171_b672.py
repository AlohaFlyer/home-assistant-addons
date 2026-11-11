"""1.7.1, FW-0042 part 2 (Ryan's rule, relayed by Hark on the HOM bus Nov 9): the 90 h monthly credit cap was Hark's
error, not Ryan's rule (the PWA does not cap voluntary adds), so smart.json's cap_credit is read and ignored. In its
place: the pilot's block hours in the 672 consecutive hours ending at the pickup's last release (flown + scheduled +
the pickup, block not credit), against the company's 98 h buffer in that rolling window (FAR 117.23(b)(1)'s own limit
is 100 h): 'Fits 672 (H:MM)' at or under 98:00, 'Over 98/672 (H:MM)' above, '672 ? (...)' when a needed block is not
on file. A find over 98/672 is shown and tagged, never hidden or quieted. Synthetic only: made-up pairings, dates in
2030, made-up airports and names."""
import json
import os
import re
from datetime import date

import far as F
import recall as RC
import smart as SM
from test_smart import RAW, _w

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def D(mo, d):
    return date(2030, mo, d)


def _month(mk, items):
    y, m = int(mk[:4]), int(mk[5:])
    first, nxt = date(y, m, 1), date(y + m // 12, m % 12 + 1, 1)
    days = [[date.fromordinal(first.toordinal() + k).isoformat(), "", ""] for k in range((nxt - first).days)]
    return {"month": mk, "days": days, "totals": {"credit": "80:00"}, "items": items}


def line(trips, have=("2030-02", "2030-03", "2030-04")):
    """(schedule months, own_trips) from [(pairing, start, end, check-in, last block-in, block)]: each trip on its
    start month's page (a trip across a month end is listed there), its times and block as own_trip_times() keeps
    them from its pairing page (block None: the page was never read, no own_trips entry)."""
    sched = {mk: _month(mk, []) for mk in have}
    own = {}
    for p, a, b, rep, arr, blk in trips:
        if a[:7] in sched:
            sched[a[:7]]["items"].append({"trip": p, "start": a, "end": b, "lay": "AAA"})
        if blk is not None:
            own[f"{p}|{a}"] = {"report": rep, "last_arr": arr, "blk": blk, "credit": blk, "duties": []}
    return sched, own


# 90:00 of block in the 672 h ending Mar 29 18:15 (Mar 1 18:15 to Mar 29 18:15); one trip before it, one after
LINE90 = [("H9000", "2030-02-20", "2030-02-23", "08:00", "16:00", "30:00"),
          ("H9001", "2030-03-02", "2030-03-05", "08:00", "16:00", "30:00"),
          ("H9002", "2030-03-09", "2030-03-12", "08:00", "16:00", "30:00"),
          ("H9003", "2030-03-16", "2030-03-19", "08:00", "16:00", "30:00"),
          ("H9005", "2030-04-05", "2030-04-08", "08:00", "16:00", "30:00")]


def b672(day, blk, trips, have=("2030-02", "2030-03", "2030-04"), today=D(3, 1), duties=None):
    """block_672 of a one-day pickup on `day` (check-in 06:00, block-in 18:00, release 18:15) against the line, as
    the Watcher's far_trips() builds both."""
    sched, own = line(trips, have)
    new = RC.pickup_trip("H9101", day, day, "06:00", "18:00", SM.hours(blk) if blk else None, duties or [])
    return SM.block_672(new, RC.line_records(sched, own, day, day, today))


# ---------------------------------------------------------------- the 98:00 line
def test_97_59_and_98_00_fit_98_01_is_over():
    """90:00 flown and scheduled in the window plus the pickup's block: 97:59 and exactly 98:00 fit, 98:01 is over.
    The trip before the window (Feb 20-23) and the one after the pickup (Apr 5-8) do not count."""
    assert SM.BUFFER_672_H == 98 and F.FT_672 == 100  # the company's buffer is its own constant, apart from FAR's
    assert b672(D(3, 29), "7:59", LINE90) == {"tag": "Fits 672 (97:59)", "b672": "97:59", "b672_ok": True}
    assert b672(D(3, 29), "8:00", LINE90) == {"tag": "Fits 672 (98:00)", "b672": "98:00", "b672_ok": True}
    assert b672(D(3, 29), "8:01", LINE90) == {"tag": "Over 98/672 (98:01)", "b672": "98:01", "b672_ok": False}
    assert b672(D(3, 29), "2:00", LINE90)["tag"] == "Fits 672 (92:00)"
    # block, never credit: the pickup's credit plays no part (the row's credit is not even passed in)
    assert b672(D(3, 29), "8:01", [t[:5] + ("30:00",) for t in LINE90])["b672"] == "98:01"
    # one day later the window starts Mar 2 18:15: H9001 (Mar 2 08:00 to Mar 5 16:00) straddles its start
    assert b672(D(3, 30), "1:00", LINE90)["tag"] == "Fits 672 (91:00)"  # counted whole: the most it can be


def test_the_tag_goes_where_over_cap_was():
    """month_rule puts the tag among its parts after the months' own (where 'Over cap' was) and before the rest; a
    Fits is a note ('OK, Fits ...'), an Over or an unknown is not OK. A reserve month carries it too (FAR 117.23(b)
    is not a line rule), and a month with no type has no rule to put it in (the row's b672 fields still say it)."""
    cfg = SM.normalize(dict(RAW, month_types={"2030-03": "line", "2030-04": "reserve"}, vac=[], min_days_off=10))
    sched, _ = line(LINE90)
    mr = lambda a, b, t, far="OK", fit="Fits": SM.month_rule(a, b, "9:00", fit, far, sched, cfg, b672=t)
    assert mr(D(3, 29), D(3, 29), "Fits 672 (97:59)") == "OK, Fits 672 (97:59)"
    assert mr(D(3, 29), D(3, 29), "Over 98/672 (98:01)") == "Over 98/672 (98:01)"
    assert mr(D(3, 29), D(3, 29), "672 ? (block not read)") == "672 ? (block not read)"
    assert mr(D(3, 29), D(3, 29), "Over 98/672 (98:01)", far="OK (CBA rest 10:30)") == \
        "Over 98/672 (98:01), Rest 10:30"
    assert mr(D(3, 29), D(3, 29), "Fits 672 (97:59)", far="OK (CBA rest 10:30)") == "Fits 672 (97:59), Rest 10:30"
    assert mr(D(3, 4), D(3, 4), "Fits 672 (97:59)", fit="Conflict H9001") == "Conflict H9001, Fits 672 (97:59)"
    assert mr(D(4, 20), D(4, 20), "Fits 672 (60:00)") == "Not SCR, Fits 672 (60:00)"  # reserve: not an SCR day
    assert mr(D(3, 29), D(3, 29), "") == "OK"  # no tag given: as before
    nontype = SM.normalize(dict(RAW, month_types={}, vac=[]))
    assert SM.month_rule(D(3, 29), D(3, 29), "9:00", "Fits", "OK", sched, nontype, b672="Fits 672 (97:59)") == ""


# ---------------------------------------------------------------- across a month end
def test_a_window_that_crosses_a_month_end():
    """A pickup Apr 3 (April's bid month): its window, Mar 6 18:15 to Apr 3 18:15, takes March's trips Mar 9-12,
    Mar 16-19 and Mar 23-25 off the March page, and Mar 30 to Apr 1 (20:00, across the month end, listed on March's
    page); not Mar 2-5 (block-in Mar 5 16:00, before the window) nor Apr 6-8 (after the pickup). 90:00 + the
    pickup's block."""
    trips = [("H9001", "2030-03-02", "2030-03-05", "08:00", "16:00", "30:00"),
             ("H9002", "2030-03-09", "2030-03-12", "08:00", "16:00", "30:00"),
             ("H9003", "2030-03-16", "2030-03-19", "08:00", "16:00", "30:00"),
             ("H9005", "2030-03-23", "2030-03-25", "08:00", "16:00", "10:00"),
             ("H9004", "2030-03-30", "2030-04-01", "08:00", "16:00", "20:00"),
             ("H9006", "2030-04-06", "2030-04-08", "08:00", "16:00", "30:00")]
    assert b672(D(4, 3), "2:00", trips, today=D(3, 25))["tag"] == "Fits 672 (92:00)"
    assert b672(D(4, 3), "7:59", trips, today=D(3, 25))["tag"] == "Fits 672 (97:59)"
    assert b672(D(4, 3), "8:00", trips, today=D(3, 25))["tag"] == "Fits 672 (98:00)"
    assert b672(D(4, 3), "8:01", trips, today=D(3, 25)) == {"tag": "Over 98/672 (98:01)", "b672": "98:01",
                                                            "b672_ok": False}
    # without the trip across the month end the window holds 70:00 (it is what puts this pickup at 98)
    assert b672(D(4, 3), "8:01", [t for t in trips if t[0] != "H9004"], today=D(3, 25))["tag"] == \
        "Fits 672 (78:01)"
    # March's page not on file (only April's): those days of the window are unknown, never read as no trips
    assert b672(D(4, 3), "1:00", trips, have=("2030-04",), today=D(3, 25)) == \
        {"tag": "672 ? (line not on file)", "b672": "", "b672_ok": ""}
    # a pickup across the month end itself (Mar 31 to Apr 1 would overlap H9004; Apr 1 to 2 against a line without it)
    sched, own = line([t for t in trips if t[0] != "H9004"])
    new = RC.pickup_trip("H9102", D(4, 1), D(4, 2), "08:00", "16:00", 17.0, [])
    assert SM.block_672(new, RC.line_records(sched, own, D(4, 1), D(4, 2), D(3, 25)))["tag"] == "Fits 672 (87:00)"


# ---------------------------------------------------------------- unknown blocks
def test_a_pickup_whose_block_is_unknown_is_never_guessed():
    unk = {"tag": "672 ? (block not read)", "b672": "", "b672_ok": ""}
    assert b672(D(3, 29), None, LINE90) == unk  # no block on the row and no duty periods
    # the duty periods give it when the row has none (the pairing page's legs, the package's)
    duties = [{"d": 0, "dep": 420, "arr": 1080, "stn": "HNL", "blk": 420}]
    assert b672(D(3, 29), None, LINE90, duties=duties)["tag"] == "Fits 672 (97:00)"
    # one of the pilot's own trips in the window never read (no times, no block): unknown too
    assert b672(D(3, 29), "1:00", [t if t[0] != "H9002" else t[:5] + (None,) for t in LINE90]) == unk
    # ... but the blocks on file already over 98:00 are over whatever the unknown adds
    over = LINE90 + [("H9004", "2030-03-23", "2030-03-24", "08:00", "16:00", "9:00")]
    assert b672(D(3, 29), None, over) == {"tag": "Over 98/672 (99:00)", "b672": "99:00", "b672_ok": False}
    # the pickup's own report or release not known: the window cannot be placed
    assert SM.block_672(None, None) == {"tag": "672 ? (times not read)", "b672": "", "b672_ok": ""}


def test_a_trip_across_the_window_start_counts_at_most_its_overlap():
    """H9000 Feb 28 08:00 to Mar 2 16:00 (20:00 block) straddles the window's start (Mar 1 18:15): how much of it flew
    inside is not on file. A Fits counts it up to its overlap (the most it can be), so it holds whatever the split;
    when the split decides it, the tag gives the range instead of a guess."""
    trips = [("H9000", "2030-02-28", "2030-03-02", "08:00", "16:00", "20:00")] + LINE90[2:4] + [
        ("H9004", "2030-03-23", "2030-03-24", "08:00", "16:00", "10:00")]
    assert b672(D(3, 29), "2:00", trips)["tag"] == "Fits 672 (92:00)"
    assert b672(D(3, 29), "8:00", trips)["tag"] == "Fits 672 (98:00)"
    assert b672(D(3, 29), "8:01", trips) == {"tag": "672 ? (78:01 to 98:01)", "b672": "", "b672_ok": ""}
    more = trips[:-1] + [("H9004", "2030-03-23", "2030-03-24", "08:00", "16:00", "30:01")]
    assert b672(D(3, 29), "8:00", more)["tag"] == "Over 98/672 (98:01)"  # over on the known blocks alone
    sched, own = line(trips)
    new = RC.pickup_trip("H9101", D(3, 29), D(3, 29), "06:00", "18:00", 8.0, [])
    r = F.flight_time_to_release(new, RC.line_records(sched, own, D(3, 29), D(3, 29), D(3, 1)))
    assert (r["known"], r["worst"], r["edge"], r["unknown_block"], r["unknown_line"]) == \
        (78.0, 98.0, ["H9000 Feb 28"], [], [])


# ---------------------------------------------------------------- the Watcher
ROW = {"pairing": "H9101", "start": "29Mar", "end": "29Mar", "days": "1", "credit": "99:00", "depart": "07:00",
       "arrive": "18:00", "dates": "29Mar", "report": "06:00", "blk": "7:59"}


def _wl(tmp_path, monkeypatch, smart=None):
    W, sent = _w(tmp_path, monkeypatch, smart=smart or dict(RAW, cap_credit="90:00", vac=[]))
    W.S["schedule"], W.S["own_trips"] = line(LINE90)
    logged = []

    class Log:
        def info(self, msg, *a):
            logged.append(msg % a if a else msg)

        def __getattr__(self, name):  # warning, debug...: not what this test counts
            return lambda *a, **k: None
    monkeypatch.setattr(W, "log", Log())
    return W, sent, logged


def test_an_old_smart_json_with_cap_credit_is_ignored_and_logged_once(tmp_path, monkeypatch):
    """Pako's smart.json still has cap_credit (90:00): a 99:00 credit pickup in a line month whose credit is 80:00
    on file never reads 'Over cap' or 'Cap ?'; the key is logged once, not on every row or pass."""
    W, _, logged = _wl(tmp_path, monkeypatch)
    for credit in ("99:00", "9:00", "x", ""):
        row = dict(ROW, credit=credit)
        row["far"] = W.far_for(row)
        W.smart_fields(row)
        assert "cap" not in row["month_rule"].lower() and row["month_rule"] == "OK, Fits 672 (97:59)", row
    said = [m for m in logged if "cap_credit" in m]
    assert len(said) == 1 and said[0].startswith("smart.json cap_credit ignored: no monthly credit cap")
    # a changed file is read again and says it again, once
    (tmp_path / "smart.json").write_text(json.dumps(dict(RAW, cap_credit="95:00", vac=[], rate=101.0)))
    for _ in range(3):
        W.smart_fields(dict(ROW))
    assert len([m for m in logged if "cap_credit" in m]) == 2


def test_each_find_carries_the_tag_and_its_own_fields(tmp_path, monkeypatch):
    """The row (pot, Tradeboard, close-in, finds, event/new_pairing) carries b672 and b672_ok next to month_rule; the
    pot and Tradeboard sensor rows do not (SENSOR_DROP, the 12 KB cap); the finds DB and month files keep them."""
    W, sent, _ = _wl(tmp_path, monkeypatch)
    rows = {}
    for blk in ("7:59", "8:00", "8:01", ""):
        r = dict(ROW, blk=blk)
        r["far"] = W.far_for(r)
        W.smart_fields(r)
        rows[blk] = r
    assert [(rows[b]["b672"], rows[b]["b672_ok"], rows[b]["month_rule"]) for b in ("7:59", "8:00", "8:01", "")] == [
        ("97:59", True, "OK, Fits 672 (97:59)"), ("98:00", True, "OK, Fits 672 (98:00)"),
        ("98:01", False, "Over 98/672 (98:01)"), ("", "", "672 ? (block not read)")]
    assert {"b672", "b672_ok"} <= set(W.SMART_FIELDS) and not {"b672", "b672_ok"} & set(W.sensor_row(rows["8:01"]))
    W.publish_pot([dict(rows["8:01"], month="2030-03")])
    s = [p for t, p in sent if t == "pot/state"][-1]["pairings"][0]
    assert "b672" not in s and "b672_ok" not in s
    W.DB.add_find("H9101|29Mar", "2030-03", rows["8:01"], "2030-03-02T19:00:00+00:00")
    f = next(x for x in W.DB.recent_finds() if x["pairing"] == "H9101")
    assert (f["b672"], f["b672_ok"], f["month_rule"]) == ("98:01", False, "Over 98/672 (98:01)")
    # without smart.json nothing changes: blank, as every smart field
    os.remove(tmp_path / "smart.json")
    r = dict(ROW)
    W.smart_fields(r)
    assert (r["b672"], r["b672_ok"], r["month_rule"]) == ("", "", "")


def test_the_pickups_report_or_release_not_read(tmp_path, monkeypatch):
    W, _, _ = _wl(tmp_path, monkeypatch)
    r = dict(ROW, report="", depart="", arrive="")
    r["far"] = W.far_for(r)
    W.smart_fields(r)
    assert (r["far"], r["b672"], r["b672_ok"]) == ("?", "", "") and r["month_rule"] == "672 ? (times not read)"


def test_nothing_quiets_or_hides_a_find_over_98_672(tmp_path, monkeypatch):
    """'Over cap' was never read to quiet, rank or hide a find, and neither is the 672 tag: the HA automations
    (ha/) read no month_rule or b672 (their conditions are VAC, blocked days, fit and far), no card ranks or filters
    on them (the finds card shows month_rule on hover only), there is no value score, and the portal's push priority
    reads fit and far alone. An Over 98/672 find still goes out on event/new_pairing and into the finds DB."""
    import portal
    ha = open(os.path.join(os.path.dirname(HERE), "ha", "automations_flight_watcher.yaml"), encoding="utf-8").read()
    assert not any(w in ha for w in ("month_rule", "b672", "Over cap", "cap_credit", "672 ?"))
    for name in os.listdir(os.path.join(HERE, "www")):
        if name.endswith(".js"):
            src = open(os.path.join(HERE, "www", name), encoding="utf-8").read()
            assert "b672" not in src and "Over cap" not in src, name
            assert all("Month: ${f.month_rule}" in x for x in src.splitlines() if "month_rule" in x), name
    # the Watcher reads month_rule and b672 nowhere but where smart_fields sets them: no filter, rank or quiet rule
    wsrc = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    assert not re.search(r'get\("(month_rule|b672|b672_ok)"|\["(month_rule|b672|b672_ok)"\]\s*(==|!=|in\b)|'
                         r'"(Over cap|Over 98|Fits 672)', wsrc)
    over = {"pairing": "H9101", "dates": "29Mar", "fit": "Fits", "far": "OK", "month_rule": "Over 98/672 (98:01)",
            "b672": "98:01", "b672_ok": False}
    assert portal.event_priority("new_pairing", over) == portal.event_priority("new_pairing", dict(
        over, month_rule="OK, Fits 672 (97:59)", b672="97:59", b672_ok=True)) == 5
    title, body = portal.event_text("new_pairing", portal.event_data("new_pairing", over))
    assert "Month Over 98/672 (98:01)" in body
    # the Watcher's new pairing push: the enriched row goes out whatever the tag says
    W, sent, _ = _wl(tmp_path, monkeypatch)
    ev = dict(ROW, blk="8:01")
    page = "<html><body>Check In: 06:00 Blk : 0801 Pay : 0900 Crew: CA 10001 DOE, JANE FO OPEN</body></html>"

    class Fl:
        def fetch(self, url):
            return page
    W.enrich(Fl(), ev)
    assert (ev["b672"], ev["b672_ok"]) == ("98:01", False) and ev["month_rule"] == "Over 98/672 (98:01)"


def test_docs_say_the_cap_is_gone():
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    entry = log.split("\n## 1.7.1\n", 1)[1].split("\n## 1.7.0\n", 1)[0]
    assert "VAC, credit cap" not in readme and "no monthly credit cap" in readme
    assert "Over 98/672" in readme and "98:00" in readme
    assert "cap_credit" in entry and "Fits 672" in entry and "Over 98/672" in entry
    smart_src = open(os.path.join(HERE, "smart.py"), encoding="utf-8").read()
    assert '"Over cap"' not in smart_src and '"Cap ?"' not in smart_src


def test_a_block_longer_than_its_span_with_a_trip_across_the_window_start():
    """A block on file longer than its own span (H9006: 10:00 in an 8 h day, a page's slip) counts in full in the
    most it can be, next to a trip across the window's start (H9000, up to its overlap): 20:00 + 60:00 + 10:00 + the
    pickup. Before the fix the slip counted only up to its span there, and an 8:01 pickup read 'Fits 672 (96:01)'
    when the most it can be is 98:01."""
    trips = [("H9000", "2030-02-28", "2030-03-02", "08:00", "16:00", "20:00")] + LINE90[2:4] + [
        ("H9006", "2030-03-23", "2030-03-23", "08:00", "16:00", "10:00")]
    assert b672(D(3, 29), "8:00", trips) == {"tag": "Fits 672 (98:00)", "b672": "98:00", "b672_ok": True}
    assert b672(D(3, 29), "8:01", trips) == {"tag": "672 ? (78:01 to 98:01)", "b672": "", "b672_ok": ""}
    sched, own = line(trips)
    new = RC.pickup_trip("H9101", D(3, 29), D(3, 29), "06:00", "18:00", 8.0, [])
    r = F.flight_time_to_release(new, RC.line_records(sched, own, D(3, 29), D(3, 29), D(3, 1)))
    assert (r["known"], r["worst"], r["edge"]) == (78.0, 98.0, ["H9000 Feb 28"])
    # the slip alone, no edge trip: known (its block in full) is the most it can be
    assert b672(D(3, 29), "8:01", LINE90[2:4] + trips[-1:])["tag"] == "Fits 672 (78:01)"


def test_a_find_stored_before_1_7_1_no_longer_reads_over_cap(tmp_path):
    """Only a find still in the pot is screened again; one that left it before 1.7.1 keeps the month_rule it was
    stored with ('Over cap' on 17 of November's line-month finds on Pako). The finds DB rows, and with them the month
    files and the finds card's hover, drop the cap's parts; nothing left reads '' (the 672 h check never ran on that
    find), not OK. Rows from 1.7.1 on are untouched."""
    from store import Store
    st = Store(str(tmp_path / "w.db"))
    old = {"Over cap": "", "Cap ?": "", "Conflict H9001, Over cap": "Conflict H9001",
           "Days off 9, Cap ?, Rest 10:30": "Days off 9, Rest 10:30", "VAC, Over cap, No sched": "VAC, No sched",
           "OK": "OK", "": "", "OK, Fits 672 (97:59)": "OK, Fits 672 (97:59)",
           "Over 98/672 (98:01), Rest 10:30": "Over 98/672 (98:01), Rest 10:30"}
    for i, rule in enumerate(old):
        row = {"pairing": f"H92{i:02d}", "dates": "12Mar", "days": "1", "credit": "9:00", "month_rule": rule}
        st.add_find(f"H92{i:02d}|12Mar", "2030-03", row, f"2030-03-02T19:{i:02d}:00+00:00")
    st.record_pot("2030-03", {}, set())  # every one of them has left the pot: never screened again
    for rows in (st.recent_finds(50), st.finds_between("2030-03-01T10:00:00+00:00", "2030-04-01T10:00:00+00:00")):
        got = {r["pairing"]: r["month_rule"] for r in rows}
        assert got == {f"H92{i:02d}": want for i, want in enumerate(old.values())}
        assert not any("cap" in r["month_rule"].lower() for r in rows)
    assert json.loads(st.db.execute("SELECT row FROM finds WHERE key='H9200|12Mar'").fetchone()[0])["month_rule"] \
        == "Over cap"  # the stored row itself is not rewritten

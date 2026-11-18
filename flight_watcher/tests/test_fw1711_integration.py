"""1.7.11 integration review fixes: what broke with the four reviewed branches together (FW-0075, FW-0076 / FW-0078,
FW-0079 / FW-0080, the log masks) or on the first start after the update from 1.7.10. Synthetic pilots, pairings and
numbers only (Roe, Rick 10999; Doe, Jane; H96xx), no FLICA load, nothing on Pako.

- I1: a pairing FLICA rebuilt (FW-0068, H9635B) splits by bid period (FW-0080) with its base id's package duties when
  that package lists the base id on the trip's first day: pilot_price, the carry, the rebuilt month (pilot_pay_line),
  pkg_detail_for / payp_tcrd. Never the base's duties for a trip on another day.
- S1 / S2 / I2 / S4: the one-time PAYP repair (repair_payp_splits) on stored 1.7.10 versions written by VER.update (no
  'end' on a stored record): a continuation keeps its share (its end from the version's own PAYP item), the records
  on file are priced first, every repaired version's fingerprint is made again and its PAYP change lines say the bid
  period, so the first 1.7.11 start makes no schedule version and sends no event/schedule_version.
- S3: a PAYP whose removed trip still flies in part (H9640A) splits only the duties on the PAYP's own days.
- I3: a month tap while Schedule Lookup reads are paused gets the paused line naming that month.
- P2: the pilot month HA kept from 1.7.10 is priced again by bid period at the first start (no FLICA load).
- P3: on a phone the split's reason is on screen (the note under the grid, the pairing sheet), not only in a title.
- I4 / I5: the contract doc's pick list limit is LOOKUP_MAX; HANDOFF's 1.7.11 entry names every item and revision 6."""
import copy
import json
import os
import re
import shutil
import subprocess

import pytest

import cards
import versions as VER
from test_crew_index import ROE, W, _sen  # noqa: F401
from test_fw1711_totals import DETAIL, H9640, _pkg, _row, _setup

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)


# ---------------------------------------------------------------- I1: a rebuilt pairing id splits by bid period
def _rebuilt(pid="H9635B", st="2026-12-01", end="2026-12-03"):
    return {"trip": pid, "start": st, "end": end, "lay": "LAX", "credit": "15:00", "blk": "11:15", "seat": "FO", "n": 2}


def test_a_rebuilt_pairing_splits_by_its_base_ids_duties(W, tmp_path, monkeypatch):  # noqa: F811
    """H9635B Dec 1 to 3 (FLICA's rebuilt copy of the package's H9635, no pairing page legs): December holds only its
    Dec 3 duty, 6:39 / 5:52, and November the rest, 8:21 / 5:23, as H9635 itself; before, December had 0:00 and
    November the whole 15:00 / 11:15 under a "no duty times on file" title."""
    _setup(W, tmp_path, monkeypatch)
    for pid in ("H9635", "H9635B"):
        dec, info = W.pilot_price([_rebuilt(pid)], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
        nov, _ = W.pilot_price([_rebuilt(pid)], "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 12)
        assert (dec["trips"], dec["credit"], dec["block"]) == (1, "6:39", "5:52"), pid
        assert (nov["credit"], nov["block"]) == ("8:21", "5:23"), pid
        sp = info[f"{pid}|2026-12-01"]["split"]
        assert (sp["placed"], sp["none"], sp["est"], sp["out_credit"], sp["other"]) == (True, False, False, "8:21", "2026-11"), pid
    # the TCRD of the base id's package detail (pkg_detail_for, payp_tcrd) for the rebuilt id on that day only
    assert [d.get("tcrd") for d in W.pkg_detail_for("2026-11", "H9635B", "2026-12-01")["duties"]] == ["5h23", "6h39"]
    assert W.pkg_detail_for("2026-11", "H9635B") is None and W.pkg_detail_for("2026-11", "H9635B", "2026-11-20") is None
    assert W.payp_tcrd("H9635B|2026-12-01", {}, lambda iso: "2026-11") == ["5h23", "6h39"]


def test_a_rebuilt_pairing_on_another_day_never_takes_the_base_ids_duties(W, tmp_path, monkeypatch):  # noqa: F811
    """H9640A Dec 2 to 3 is a part of H9640 (Nov 30 to Dec 3): the base's duties placed from Dec 2 would be Dec 2, 4
    and 5, so it gets none (the whole trip in the bid period of its first day, as before)."""
    _setup(W, tmp_path, monkeypatch)
    dec, info = W.pilot_price([{**_rebuilt("H9640A", "2026-12-02", "2026-12-03"), "credit": "8:30", "blk": "8:30"}],
                              "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    assert (dec["credit"], dec["block"]) == ("8:30", "8:30") and "split" not in info["H9640A|2026-12-02"]
    assert W.pkg_base("2026-11", "H9640A", "2026-12-02") == "H9640A" and W.pkg_base("2026-11", "H9640A", "2026-11-30") == "H9640"


def test_the_rebuilt_month_and_the_carry_split_a_rebuilt_id(W, tmp_path, monkeypatch):  # noqa: F811
    """The month rebuilt from crew lists (pilot_pay_line) has no legs: H9635B Dec 1 to 3 counted whole in November
    before. And a crew index trip from before FLICA's grid (H9640B Nov 30 to Dec 3) carried into December counts its
    December part."""
    _setup(W, tmp_path, monkeypatch)
    trips = [{"pairing": "H9635B", "start": "2026-12-01", "end": "2026-12-03", "seat": "FO", "credit": "15:00", "blk": "11:15", "n": 2}]
    dec = W.pilot_pay_line(copy.deepcopy(trips), "10999", "Roe, Rick", "2026-12-02", "2026-12-31", "2026-12")
    nov = W.pilot_pay_line(copy.deepcopy(trips), "10999", "Roe, Rick", "2026-11-01", "2026-12-01", "2026-11")
    assert (dec["credit"], dec["block"], nov["credit"], nov["block"]) == ("6:39", "5:52", "8:21", "5:23")
    days = [[f"2026-12-{d:02d}", "", "-" if d <= 3 else ""] for d in range(1, 32)]
    recon = [{"pairing": "H9640B", "start": "2026-11-30", "end": "2026-12-03", "seat": "FO", "credit": "18:00", "blk": "14:00", "n": 2}]
    line, info = W.pilot_price([], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", recon, 12, None, days)
    assert [c["pairing"] for c in line.get("carry") or []] == ["H9640B"] and (line["credit"], line["block"]) == ("8:30", "8:30")


# ---------------------------------------------------------------- S1 / S2 / I2 / S4: the first start after 1.7.10
H9640_OWN = {"blk": "14:00", "credit": "18:00", "soft": "4:00", "seat": "FO", "report": "20:40", "last_arr": "11:00",
             "duties": [dict(d) for d in H9640]}


def _page(first, last, marks, credit="0:00", block="0:00"):
    from datetime import date, timedelta

    from pot import schedule_items
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    at = {d: (t, lay) for d, t, lay in marks}
    days = [[(a + timedelta(days=k)).isoformat(), *at.get((a + timedelta(days=k)).isoformat(), ("", ""))] for k in range((b - a).days + 1)]
    return {"items": schedule_items(days), "days": days, "totals": {"days_off": 12, "block": block, "credit": credit}, "updated": "Nov 17, 2026"}


def _pages(nov_marks, dec_marks):
    return {"2026-11": _page("2026-11-01", "2026-12-01", nov_marks, "9:30"), "2026-12": _page("2026-12-01", "2026-12-31", dec_marks, "8:30")}


def _old_world(W, own, months, steps):  # noqa: N803
    """Stored versions as 1.7.10 wrote them: VER.update over each step's pages and own trips (trips_of, no 'end'),
    with the 1.7.10 PAYP records as own trips (the calendar month's split and its continuation's share)."""
    for i, (mk_pages, recs) in enumerate(steps):
        W.S["schedule"] = mk_pages
        VER.update(W.DB, mk_pages, recs, f"2026-11-1{i}T0{i}:00:00+00:00")
    W.S["schedule"] = months
    W.S["own_trips"] = own
    W.S.pop("payp_fix_v", None)


def _h9640_world(W, tmp_path, monkeypatch):  # noqa: N803
    """H9640 Nov 30 to Dec 3 (duties Nov 30, Dec 2, Dec 3; TCRD 5:30 / 5:00 / 3:30; credit 18:00) removed for a PAYP:
    November's page lists PAYP Nov 30 to Dec 1, December's (from Dec 1) PAYP Dec 1 to 3. 1.7.10 kept PAYP|2026-11-30
    split by the calendar month (7:04 / 10:56) and its continuation PAYP|2026-12-01 at 10:56."""
    _setup(W, tmp_path, monkeypatch)
    W.TEST_CLOCK["t"] = W.TEST_CLOCK["t"].replace(month=11, day=17)
    trip = _pages([("2026-11-30", "H9640", "SEA"), ("2026-12-01", "", "SEA")],
                  [("2026-12-01", "", "SEA"), ("2026-12-02", "", "LAX"), ("2026-12-03", "", "HNL")])
    trip["2026-12"]["items"] = [{"trip": "H9640", "start": "2026-11-30", "end": "2026-12-03", "lay": "SEA"}]
    payp = _pages([("2026-11-30", "PAYP", "-"), ("2026-12-01", "PAYP", "-")],
                  [("2026-12-01", "PAYP", "-"), ("2026-12-02", "PAYP", "-"), ("2026-12-03", "PAYP", "-")])
    nov_rec = {"credit": "18:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "end": "2026-12-01",
               "src": "own trips", "seat": "FO", "split": {"2026-11": "7:04", "2026-12": "10:56"}}
    cont = {"credit": "10:56", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "end": "2026-12-03",
            "src": "own trips", "seat": "FO", "of": "PAYP|2026-11-30"}
    own = {"PAYP|2026-11-30": nov_rec, "PAYP|2026-12-01": cont}
    _old_world(W, copy.deepcopy(own), payp, [(trip, {"H9640|2026-11-30": H9640_OWN}), (payp, own)])
    return own


def _start_and_check(W):  # noqa: N803
    """main()'s start (versions_check(force_pub=True)) and then check()'s bookkeeping (own_trip_times' payp_refresh and
    prune, then versions_check), with no FLICA load."""
    W.SENT.clear()
    W.versions_check(force_pub=True)
    own = W.S["own_trips"]
    keep = W.payp_refresh(own)
    for k in [k for k in own if k not in keep]:
        own.pop(k)
    W.versions_check()
    return [p for t, p in W.SENT if t == "event/schedule_version"]


def test_the_first_start_keeps_the_continuations_share_and_makes_no_version(W, tmp_path, monkeypatch):  # noqa: F811
    """S1: the stored continuation (no 'end': VER.update never writes it) took only its first day, Dec 1, November's,
    found no share and was dropped from 12.002. S2 / I2: the repair left each version's fingerprint as it was, and
    payp_refresh then moved the record on file to 8:30, so the first check made 12.003 ("keeps ... 8:30") and sent
    event/schedule_version with nothing changed on FLICA."""
    _h9640_world(W, tmp_path, monkeypatch)
    before = {mk: [v["ver"] for v in W.DB.get(f"sched_versions:{mk}")] for mk in ("2026-11", "2026-12")}
    assert before == {"2026-11": ["11.001", "11.002"], "2026-12": ["12.001", "12.002"]}
    assert "end" not in W.DB.get("sched_versions:2026-12")[-1]["trips"]["PAYP|2026-12-01"]  # as 1.7.10 stored it
    events = _start_and_check(W)
    assert events == [] and {mk: [v["ver"] for v in W.DB.get(f"sched_versions:{mk}")] for mk in before} == before
    n2 = W.DB.get("sched_versions:2026-11")[-1]["trips"]["PAYP|2026-11-30"]
    d2 = W.DB.get("sched_versions:2026-12")[-1]["trips"]["PAYP|2026-12-01"]
    assert n2["split"] == {"2026-11": "9:30", "2026-12": "8:30"} and d2["credit"] == "8:30" and "end" not in d2
    assert W.S["own_trips"]["PAYP|2026-12-01"]["credit"] == "8:30"
    for mk in before:  # S2: each repaired version's fingerprint is its trips' again
        for v in W.DB.get(f"sched_versions:{mk}"):
            assert v["fp"] == VER.fingerprint(v, v["trips"]), v["ver"]


def test_the_repaired_versions_change_lines_say_the_bid_period(W, tmp_path, monkeypatch):  # noqa: F811
    """S4: 11.002's line kept 1.7.10's "by month (PWA 4.A) 2026-11 7:04, 2026-12 10:56" and 12.002's "10:56 ... this
    month's share" beside records that now hold 9:30 / 8:30 and 8:30."""
    _h9640_world(W, tmp_path, monkeypatch)
    for v in W.DB.get("sched_versions:2026-11")[1:] + W.DB.get("sched_versions:2026-12")[1:]:  # the wording 1.7.10 wrote
        v["changes"] = [c.replace("by bid period", "by month").replace("this bid period's share", "this month's share") for c in v["changes"]]
    W.repair_payp_splits()
    n = [c for c in W.DB.get("sched_versions:2026-11")[-1]["changes"] if c.startswith("PAYP")]
    d = [c for c in W.DB.get("sched_versions:2026-12")[-1]["changes"] if c.startswith("PAYP")]
    assert n == ["PAYP 2026-11-30 keeps H9640 2026-11-30's credit 18:00 (pay protected; by bid period (PWA 4.A) 2026-11 9:30, 2026-12 8:30)"], n
    assert d == ["PAYP 2026-12-01 keeps H9640 2026-11-30's credit 8:30 (pay protected; this bid period's share (PWA 4.A))"], d
    assert not any("by month" in c or "this month's share" in c for v in W.DB.get("sched_versions:2026-11") for c in v["changes"])


def test_a_continuation_with_no_share_is_dropped_on_file_and_in_the_versions_alike(W, tmp_path, monkeypatch):  # noqa: F811
    """H9103 Nov 29 to Dec 1: every duty departs on a November day (Dec 1 is November's), so 1.7.10's continuation
    PAYP|2026-12-01 (6:19, the calendar share) goes from own trips and from the stored versions at the same start:
    no version at the first start, none at the first check."""
    _setup(W, tmp_path, monkeypatch)
    W.TEST_CLOCK["t"] = W.TEST_CLOCK["t"].replace(month=11, day=17)
    du = [{"d": 0, "dep": 1380, "arr": 1722, "stn": "SEA", "blk": 342}, {"d": 1, "dep": 2415, "arr": 2720, "stn": "SFO", "blk": 305},
          {"d": 2, "dep": 3900, "arr": 4250, "stn": "HNL", "blk": 350}]
    trip_rec = {"credit": "18:00", "blk": "16:37", "seat": "FO", "report": "22:00", "last_arr": "10:50", "duties": du}
    trip = _pages([("2026-11-29", "H9103", "SEA"), ("2026-11-30", "", "SFO"), ("2026-12-01", "", "HNL")], [("2026-12-01", "", "HNL")])
    trip["2026-12"]["items"] = [{"trip": "H9103", "start": "2026-11-29", "end": "2026-12-01", "lay": "SEA"}]
    payp = _pages([("2026-11-29", "PAYP", "-"), ("2026-11-30", "PAYP", "-"), ("2026-12-01", "PAYP", "-")], [("2026-12-01", "PAYP", "-")])
    own = {"PAYP|2026-11-29": {"credit": "18:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9103|2026-11-29",
                               "end": "2026-12-01", "src": "own trips", "seat": "FO", "split": {"2026-11": "11:41", "2026-12": "6:19"}},
           "PAYP|2026-12-01": {"credit": "6:19", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9103|2026-11-29",
                               "end": "2026-12-01", "src": "own trips", "seat": "FO", "of": "PAYP|2026-11-29"}}
    _old_world(W, copy.deepcopy(own), payp, [(trip, {"H9103|2026-11-29": trip_rec}), (payp, own)])
    assert _start_and_check(W) == []
    assert [v["ver"] for v in W.DB.get("sched_versions:2026-12")] == ["12.001", "12.002"]
    assert "PAYP|2026-12-01" not in W.DB.get("sched_versions:2026-12")[-1]["trips"] and "PAYP|2026-12-01" not in W.S["own_trips"]
    assert "split" not in W.S["own_trips"]["PAYP|2026-11-29"]


def test_a_stored_continuation_with_no_readable_span_is_kept():
    """S1: a stored continuation whose version lists no PAYP item at its start (its span cannot be read) is left as
    it is, never dropped."""
    orig = {"credit": "18:00", "payp": True, "protected": "H9640|2026-11-30", "split": {"2026-11": "9:30", "2026-12": "8:30"}}
    cont = {"credit": "10:56", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "of": "PAYP|2026-11-30"}
    vers = {"2026-11": [{"items": [{"trip": "PAYP", "start": "2026-11-30", "end": "2026-12-01"}], "trips": {"PAYP|2026-11-30": dict(orig)}}],
            "2026-12": [{"items": [], "trips": {"PAYP|2026-12-01": dict(cont)}}]}
    VER.resplit_versions(vers, {}, lambda iso: "2026-11" if iso <= "2026-12-01" else iso[:7])
    assert vers["2026-12"][0]["trips"]["PAYP|2026-12-01"] == cont
    vers["2026-12"][0]["items"] = [{"trip": "PAYP", "start": "2026-12-01", "end": "2026-12-03"}]
    VER.resplit_versions(vers, {}, lambda iso: "2026-11" if iso <= "2026-12-01" else iso[:7])
    assert vers["2026-12"][0]["trips"]["PAYP|2026-12-01"]["credit"] == "8:30"


# ---------------------------------------------------------------- S3: a PAYP whose trip still flies in part
def _bp(iso):
    return "2026-11" if str(iso)[:10] == "2026-12-01" else str(iso)[:7]


def test_a_payp_whose_trip_still_flies_in_part_pays_in_the_bid_period_of_its_days():
    """H9640 Nov 30 to Dec 3 removed, H9640A Dec 2 to 3 (8:30) flies its Dec 2 and Dec 3 duties, the PAYP is Nov 30 to
    Dec 1 (November's days): its 9:30 (18:00 less 8:30) pays in November. 1.7.11 split it with every duty's TCRD:
    November 1:00, December 8:30 (December's part already paid by H9640A)."""
    tc = ["5h30", "5h00", "3h30"]
    items = [{"trip": "PAYP", "start": "2026-11-30", "end": "2026-12-01"}, {"trip": "H9640A", "start": "2026-12-02", "end": "2026-12-03"}]
    own = {"H9640|2026-11-30": copy.deepcopy(H9640_OWN), "H9640A|2026-12-02": {"credit": "8:30", "blk": "8:30", "seat": "FO"}}
    from pot import PAIRING_RE
    got = VER.payp_entries(items, own, lambda mk: [], PAIRING_RE.match, _bp, lambda k, r: tc if k.startswith("H9640|") else None)
    assert got["PAYP|2026-11-30"]["credit"] == "9:30" and "split" not in got["PAYP|2026-11-30"], got
    # the PAYP over Nov 30 to Dec 2 while H9640A flies the Dec 3 duty (3:30): the Dec 2 duty's TCRD (5:00) goes to
    # December, never the Dec 3 one's too (1.7.11: November 6:00, December 8:30)
    items2 = [{"trip": "PAYP", "start": "2026-11-30", "end": "2026-12-02"}, {"trip": "H9640A", "start": "2026-12-03", "end": "2026-12-03"}]
    own2 = {"H9640|2026-11-30": copy.deepcopy(H9640_OWN), "H9640A|2026-12-03": {"credit": "3:30", "blk": "3:30", "seat": "FO"}}
    got2 = VER.payp_entries(items2, own2, lambda mk: [], PAIRING_RE.match, _bp, lambda k, r: tc if k.startswith("H9640|") else None)
    assert got2["PAYP|2026-11-30"]["credit"] == "14:30" and got2["PAYP|2026-11-30"]["split"] == {"2026-11": "9:30", "2026-12": "5:00"}
    # the one-time repair of a stored record of that shape: left unsplit, never 1:00 / 8:30
    rec = {"credit": "9:30", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "end": "2026-12-01",
           "split": {"2026-11": "3:39", "2026-12": "5:51"}}
    out = VER.payp_resplit("PAYP|2026-11-30", rec, lambda p: H9640_OWN, _bp, lambda k, r: tc)
    assert "split" not in out and out["credit"] == "9:30"
    vers = {"2026-11": [{"items": [{"trip": "PAYP", "start": "2026-11-30", "end": "2026-12-01"}],
                         "trips": {"PAYP|2026-11-30": {k: v for k, v in rec.items() if k != "end"}}}]}
    assert VER.resplit_versions(vers, {"H9640|2026-11-30": H9640_OWN}, _bp, lambda k, r: tc) == ["2026-11"]
    assert "split" not in vers["2026-11"][0]["trips"]["PAYP|2026-11-30"]


# ---------------------------------------------------------------- I3: a month tap while lookups are paused
def test_a_month_tap_while_lookups_are_paused_says_so_with_its_month(W, monkeypatch):  # noqa: F811
    """The first paused line was keyed by the employee number alone, so a tap of a month for the pilot already shown
    stayed 'loading' for hours (the card's queued-month path never ran)."""
    monkeypatch.setattr(W.BRK, "allow", lambda kind: kind != "lookup")
    monkeypatch.setattr(W.BRK, "until", lambda kind: W.time.time() + 3 * 3600)
    monkeypatch.setattr(W, "pilot_cached", lambda emp, month="": None)
    W.TEST_CLOCK["t"] = W.TEST_CLOCK["t"].replace(month=11, day=17)

    def ask(**d):
        W.SENT.clear()
        W.pilot_cmd(json.dumps({"emp": "10999", "name": "Roe, Rick", **d}))
        W.pilot_check(None)
        W.pilot_check(None)  # the next loop says nothing again
        return [(p["status"], p.get("asked_month")) for t, p in W.SENT if t == "pilot_schedule"]
    first = ask()
    assert first[0] == ("loading", None) and first[1][0].startswith("Schedule Lookup reads are paused") and len(first) == 2
    tap = ask(month="2026-12")
    assert tap[0] == ("loading", "2026-12") and tap[1][0].startswith("Schedule Lookup reads are paused") and tap[1][1] == "2026-12"
    assert len(tap) == 2
    again = ask(month="2026-12")  # the same month tapped again: the line again, once
    assert len(again) == 2 and again[1][1] == "2026-12"


# ---------------------------------------------------------------- I4 / I5: the docs
def test_the_contract_doc_names_the_pick_lists_limit():
    doc = open(os.path.join(FW, "PORTAL_CONTRACT.md"), encoding="utf-8").read()
    n = int(re.search(r"^LOOKUP_MAX = (\d+)", open(os.path.join(FW, "watcher.py"), encoding="utf-8").read(), re.M).group(1))
    found = [int(x) for x in re.findall(r"at most (\d+) (?:matches|entries)", doc)]
    assert found and set(found) == {n}, found
    assert "section 5.3's limits" not in doc  # 5.3 is pref/set, not the lookup


def test_handoff_names_every_1_7_11_item_and_its_contract_revision():
    text = open(os.path.join(FW, "..", "HANDOFF.md"), encoding="utf-8").read()
    rel = text[text.index("## Recent releases"):]
    entry = rel[rel.index("1.7.11"):rel.index("1.7.5")]
    for k in ("FW-0075", "FW-0076", "FW-0078", "FW-0079", "FW-0080", "log mask", "revision 6", "HOM 1.9.2"):
        assert k in entry, k
    assert "no contract change" not in entry and chr(0x2014) not in text


# ---------------------------------------------------------------- P2: the pilot month 1.7.10 left in HA
DEC_TWO = [{"trip": "H9635", "start": "2026-12-01", "end": "2026-12-03", "lay": "LAX", "credit": "15:00", "blk": "11:15", "seat": "FO", "n": 2},
           {"trip": "H9656", "start": "2026-12-05", "end": "2026-12-07", "lay": "SEA", "credit": "15:00", "blk": "11:15", "seat": "FO", "n": 2}]


def _old_attrs(rec):
    """What 1.7.10's pub_pilot left retained for that read: calendar month totals (30:00 / 22:30), no period, no split."""
    items = [dict(it, seat_src="pairing page", gross=1000.0) for it in rec["items"]]
    return {**rec, "status": "ok", "items": items, "friendly_name": "Pilot schedule", "icon": "mdi:account-clock",
            "items_pay": {"trips": 2, "credit": "30:00", "block": "22:30", "soft": "7:30", "gross": 2000.0, "doh_known": True},
            "reconstructed": [], "reconstructed_month": "2026-12", "versions": {}, "versions_file_key": "x", "versions_rev": 1}


@pytest.mark.parametrize("cached", [True, False])
def test_the_first_start_prices_the_pilot_month_an_older_release_left(W, tmp_path, monkeypatch, cached):  # noqa: F811
    """The retained 1.7.10 reply (Credit 30:00 against FLICA's 21:39, in red) was drawn by the 1.7.11 card under the
    bid period's title until the next lookup; at the start it is priced again: 21:39 / 17:07, December's part of H9635."""
    _setup(W, tmp_path, monkeypatch)
    rec = {"emp": "10999", "name": "Roe, Rick", "month": "2026-12", "updated": "Nov 17, 2026 03:16:30", "bd": "1226",
           "fetched": "2026-11-17T16:00:00+00:00", "fetched_ts": W.time.time() - 7 * 3600,
           "days": [[f"2026-12-{d:02d}", *({1: ["H9635", "LAX"], 5: ["H9656", "SEA"]}.get(d, ["", ""]))] for d in range(1, 32)],
           "items": copy.deepcopy(DEC_TWO), "totals": {"block": "17:07", "credit": "21:39", "days_off": 20}}
    if cached:
        W.DB.put("pilot_sched:10999", rec)
    calls = []
    monkeypatch.setattr(W, "ha_state_full", lambda eid: (calls.append(eid), (200, {"state": "10999", "attributes": _old_attrs(rec)}))[1])
    W.SENT.clear()
    assert W.pilot_shown_reprice() is True and calls == ["sensor.flight_watcher_pilot_schedule"]
    p = [x for t, x in W.SENT if t == "pilot_schedule"][-1]
    ip = p["items_pay"]
    assert (ip["credit"], ip["block"], ip["period"]["from"], ip["period"]["to"]) == ("21:39", "17:07", "2026-12-02", "2026-12-31")
    h = next(it for it in p["items"] if it["trip"] == "H9635")
    assert (h["split"]["credit"], h["split"]["blk"], h["split"]["other"]) == ("6:39", "5:52", "2026-11")
    assert p["status"] == ("cached" if cached else "ok") and "friendly_name" not in p
    # priced by bid period already (this release's reply), or no pilot shown: nothing
    W.SENT.clear()
    monkeypatch.setattr(W, "ha_state_full", lambda eid: (200, {"state": "10999", "attributes": p}))
    assert W.pilot_shown_reprice() is False and not W.SENT
    monkeypatch.setattr(W, "ha_state_full", lambda eid: (404, None))
    assert W.pilot_shown_reprice() is False and not W.SENT


# ---------------------------------------------------------------- P3: the split on a phone (Chromium)
def test_a_phone_shows_why_a_row_is_split(W, tmp_path, monkeypatch):  # noqa: F811
    """At 390 px the Dec 1 row's purple 5:52 / 6:39 said nothing on screen: the reason was only in the cells' title (a
    tap shows none) and the sheet a tap on H9635 opens showed the whole trip's 11:15 / 15:00. Now a note under the
    totals says which part pays in November, and the sheet carries the split's reason."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    from test_fw1711_totals import _pilot_attrs
    attrs = _pilot_attrs(W, tmp_path, monkeypatch)
    f = tmp_path / "attrs.json"
    f.write_text(json.dumps(attrs))
    card = tmp_path / "pc.js"
    card.write_text(cards.build("9.9.9", [])["flight-watcher-pilot-card.js"])
    out = subprocess.run(["node", os.path.join(HERE, "fw1711_totals_render.js"), str(card), str(f), "", "390"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    for v in ("390_light", "390_dark"):
        m = r[v]
        assert "Purple Block and Credit: only the part flown in this bid period (PWA 4.A" in m["bodyText"], (v, m["bodyText"][-600:])
        assert "H9635 Dec 1: 5:23 block, 8:21 credit pay in the November bid period" in m["bodyText"], v
        assert "5:23 block, 8:21 credit flown before Dec 2 pay in the November bid period (PWA 4.A)" in m["sheetText"], (v, m["sheetText"])
        assert m["doc"] <= m["win"], (v, m["doc"])  # still no sideways scroll

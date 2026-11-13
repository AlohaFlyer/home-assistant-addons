"""1.7.2 (Ryan, Nov 13): "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?"
2023 PWA Definitions item 57: a Flight Grouping removed from the schedule, the pilot retains its Pay and Credit. PWA
4.R.1: a trip added on PAYP days pays on top. The v11.028 -> v11.029 shape: trip H3620 Nov 12-14 (credit 15:00)
replaced by PAYP Nov 12-14, FLICA's month credit 131:15 both times, block 94:42 -> 82:23. Synthetic month, made-up
trips (H9001, H9002, H3999 are not real pairings here), no crew names; the card rendered in Chromium at 390 px."""
import json
import logging
import re
import sys
from datetime import datetime

import pytest

import versions as VER
from pot import PAIRING_RE, schedule_items
from store import Store

RATE = 259.04  # PWA 3.D.6 A330 PAX FO, year 5, from 2026-03-02 (the card's own table)
NET = 1 - (22 + 7) / 100


def _days(marks):
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    for iso, act, lay in marks:
        days[int(iso[8:]) - 1] = [iso, act, lay]
    return days


BASE = [("2026-11-03", "H9001", "SFO"), ("2026-11-04", "", "HNL"),
        ("2026-11-20", "H9002", "LAX"), ("2026-11-21", "", "-"), ("2026-11-22", "", "HNL")]
LAS = [("2026-11-12", "H3620", "LAS"), ("2026-11-13", "", "-"), ("2026-11-14", "", "HNL")]
PAYP3 = [("2026-11-12", "PAYP", "-"), ("2026-11-13", "PAYP", "-"), ("2026-11-14", "PAYP", "-")]
# PWA 4.R.1: a trip added on a PAYP day (FLICA shows the trip that day, the PAYP on the others)
ADDED = [("2026-11-12", "PAYP", "-"), ("2026-11-13", "H3999", "-"), ("2026-11-14", "PAYP", "-")]

OWN = {"H9001|2026-11-03": {"blk": "40:00", "credit": "50:00", "soft": "10:00", "seat": "FO", "report": "08:00",
                            "last_arr": "18:00"},
       "H3620|2026-11-12": {"blk": "12:19", "credit": "15:00", "soft": "2:41", "seat": "FO", "report": "22:45",
                            "last_arr": "11:37"},
       "H9002|2026-11-20": {"blk": "42:23", "credit": "66:15", "soft": "23:52", "seat": "FO", "report": "09:00",
                            "last_arr": "06:00"}}
H3999 = {"blk": "5:10", "credit": "6:00", "soft": "0:50", "seat": "FO", "report": "07:00", "last_arr": "15:00"}


def _sched(marks, credit, block, days_off=15):
    days = _days(BASE + marks)
    return {"items": schedule_items(days), "days": days, "totals": {"days_off": days_off, "block": block,
                                                                     "credit": credit}, "updated": "Nov 12, 2026"}


V28 = _sched(LAS, "131:15", "94:42", 13)
V29 = _sched(PAYP3, "131:15", "82:23")


def _ver(n, sched, trips):
    return {"ver": f"11.{n:03d}", "n": n, "at": f"2026-11-1{n % 10}T01:00:00+00:00", "updated": sched["updated"],
            "items": sched["items"], "days": sched["days"], "totals": sched["totals"],
            "trips": {k: {f: v for f, v in t.items() if f in VER.TRIP_FIELDS} for k, t in trips.items()},
            "changes": ["synthetic"]}


def _own29():
    return {k: v for k, v in OWN.items() if k != "H3620|2026-11-12"}


# ---------------------------------------------------------------- versions.payp_entries (pure)
def test_v11029_shape_payp_keeps_the_removed_trips_credit_from_own_trips():
    assert [i for i in V29["items"] if i["trip"] == "PAYP"] == [
        {"trip": "PAYP", "start": "2026-11-12", "end": "2026-11-14", "lay": ""}]
    got = VER.payp_entries(V29["items"], dict(OWN), lambda mk: [], PAIRING_RE.match)
    assert got == {"PAYP|2026-11-12": {"credit": "15:00", "blk": "0:00", "soft": "0:00", "payp": True,
                                       "protected": "H3620|2026-11-12", "end": "2026-11-14", "src": "own trips",
                                       "seat": "FO"}}


def test_the_removed_trip_from_the_versions_when_own_trips_lost_it():
    """Pako on Nov 13: H3620's own record was pruned with v11.029; v11.028 still holds its credit."""
    vers = [_ver(28, V28, OWN), _ver(29, V29, _own29())]
    got = VER.payp_entries(V29["items"], _own29(), lambda mk: vers if mk == "2026-11" else [], PAIRING_RE.match)
    assert got["PAYP|2026-11-12"]["credit"] == "15:00" and got["PAYP|2026-11-12"]["src"] == "v11.028"
    assert got["PAYP|2026-11-12"]["protected"] == "H3620|2026-11-12"
    # the version before the PAYP only: an older one without the trip gives nothing, never a guess
    gone = _ver(28, V28, _own29())  # H3620 on the line but no credit read for it
    assert VER.payp_entries(V29["items"], _own29(), lambda mk: [_ver(27, V28, OWN), gone, vers[1]],
                            PAIRING_RE.match) == {}


def test_no_removed_trip_on_file_gives_no_record():
    assert VER.payp_entries(V29["items"], _own29(), lambda mk: [], PAIRING_RE.match) == {}
    assert VER.payp_entries(V28["items"], dict(OWN), lambda mk: [], PAIRING_RE.match) == {}  # no PAYP: nothing


def test_the_record_stays_while_the_payp_is_on_the_schedule_and_a_trip_added_and_dropped_changes_nothing():
    rec = VER.payp_entries(V29["items"], dict(OWN), lambda mk: [], PAIRING_RE.match)
    own = {**_own29(), **rec}
    assert VER.payp_entries(V29["items"], own, lambda mk: [], PAIRING_RE.match) == rec  # the removed trip is gone
    # PWA 4.R.1: H3999 added over the PAYP days, then dropped (its record not pruned yet): the PAYP keeps 15:00
    own["H3999|2026-11-13"] = dict(H3999)
    assert VER.payp_entries(V29["items"], own, lambda mk: [], PAIRING_RE.match) == rec


def test_one_payp_over_two_removed_trips_sums_their_credits():
    days = _days(BASE + [("2026-11-12", "PAYP", "-"), ("2026-11-13", "PAYP", "-"), ("2026-11-14", "PAYP", "-"),
                         ("2026-11-15", "PAYP", "-"), ("2026-11-16", "PAYP", "-")])
    own = {**OWN, "H3621|2026-11-15": {"blk": "8:00", "credit": "10:30", "seat": "FO"}}
    got = VER.payp_entries(schedule_items(days), own, lambda mk: [], PAIRING_RE.match)
    assert got["PAYP|2026-11-12"]["credit"] == "25:30"
    assert got["PAYP|2026-11-12"]["protected"] == "H3620|2026-11-12,H3621|2026-11-15"


def test_a_removed_trip_counts_for_one_payp_only():
    """PWA 4.R.1 split: a trip added on Nov 13 leaves PAYP Nov 12 and PAYP Nov 14; H3620 is kept once, on Nov 12."""
    sched = _sched(ADDED, "137:15", "87:33")
    items = sched["items"]
    assert [(i["trip"], i["start"], i["end"]) for i in items if i["trip"] in ("PAYP", "H3999")] == [
        ("PAYP", "2026-11-12", "2026-11-12"), ("H3999", "2026-11-13", "2026-11-13"), ("PAYP", "2026-11-14", "2026-11-14")]
    vers = [_ver(28, V28, OWN), _ver(29, V29, _own29())]
    first = VER.payp_entries(V29["items"], dict(OWN), lambda mk: vers, PAIRING_RE.match)
    own = {**_own29(), **first, "H3999|2026-11-13": dict(H3999)}
    got = VER.payp_entries(items, own, lambda mk: vers, PAIRING_RE.match)
    assert list(got) == ["PAYP|2026-11-12"] and got["PAYP|2026-11-12"]["credit"] == "15:00"
    assert got["PAYP|2026-11-12"]["end"] == "2026-11-12"  # its days changed: credit kept, new end
    # both new at once, from the versions: the first PAYP takes it, the second gets none
    got = VER.payp_entries(items, {**_own29(), "H3999|2026-11-13": dict(H3999)}, lambda mk: vers, PAIRING_RE.match)
    assert list(got) == ["PAYP|2026-11-12"] and got["PAYP|2026-11-12"]["src"] == "v11.028"


def test_a_payp_whose_start_moves_takes_its_trips_and_credit_along():
    rec = VER.payp_entries(V29["items"], dict(OWN), lambda mk: [], PAIRING_RE.match)
    days = _days(BASE + [("2026-11-10", "PAYP", "-"), ("2026-11-11", "PAYP", "-")] + PAYP3)
    own = {**_own29(), **rec, "H3610|2026-11-10": {"blk": "6:00", "credit": "7:00", "seat": "FO",
                                                   "duties": [{"dep": 600, "arr": 1500, "blk": 360}]}}
    got = VER.payp_entries(schedule_items(days), own, lambda mk: [], PAIRING_RE.match)
    assert list(got) == ["PAYP|2026-11-10"]
    assert got["PAYP|2026-11-10"]["credit"] == "22:00" and got["PAYP|2026-11-10"]["end"] == "2026-11-14"
    assert set(got["PAYP|2026-11-10"]["protected"].split(",")) == {"H3620|2026-11-12", "H3610|2026-11-10"}


def test_versions_store_the_payp_credit_and_name_it(tmp_path):
    db = Store(str(tmp_path / "v.db"))
    assert VER.update(db, {"2026-11": V28}, OWN, "t28") == [("2026-11", "11.001")]
    own = {**_own29(), **VER.payp_entries(V29["items"], dict(OWN), lambda mk: [], PAIRING_RE.match)}
    assert VER.update(db, {"2026-11": V29}, own, "t29") == [("2026-11", "11.002")]
    v = db.get("sched_versions:2026-11")[-1]
    assert v["trips"]["PAYP|2026-11-12"] == {"blk": "0:00", "credit": "15:00", "soft": "0:00", "seat": "FO",
                                             "payp": True, "protected": "H3620|2026-11-12"}
    assert "added PAYP 2026-11-12" in v["changes"] and "dropped H3620 2026-11-12" in v["changes"]
    assert "PAYP 2026-11-12 keeps H3620 2026-11-12's credit 15:00 (pay protected)" in v["changes"]
    # a version stored before 1.7.2 (no PAYP record) gets one new version once the record is on file
    db2 = Store(str(tmp_path / "v2.db"))
    VER.update(db2, {"2026-11": V29}, _own29(), "old")
    assert VER.update(db2, {"2026-11": V29}, own, "new") == [("2026-11", "11.002")]
    assert db2.get("sched_versions:2026-11")[-1]["changes"] == [
        "PAYP 2026-11-12 keeps H3620 2026-11-12's credit 15:00 (pay protected)"]


# ---------------------------------------------------------------- the Watcher (every instance)
class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


class NoFLICA:
    def fetch(self, url):
        raise AssertionError(f"no FLICA load expected: {url}")


@pytest.fixture(params=["", "pilot2"])
def W(request, tmp_path, monkeypatch):
    instance = request.param
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p", "my_name": "Doe"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "local_now", lambda: datetime(2026, 11, 11, 12, 0))  # before the trips: no re-reads
    watcher.FAKE = FakeClient()
    monkeypatch.setattr(watcher, "MQ", watcher.FAKE)
    monkeypatch.setattr(watcher, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    watcher.S.clear()
    return watcher


def _cached(t):  # an own trip as read since 1.4.9 (nothing left to read on it)
    return {**t, "duties": [], "crew": [], "legs": [], "read_at": "2026-11-11T11:00:00", "final": False}


def _sensor(W):
    return [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"{W.T}/own_trips"][-1]["trips"]


def test_watcher_keeps_payp_across_refreshes_stores_it_in_versions_and_prunes_it_with_the_payp(W):
    W.S["schedule"] = {"2026-11": json.loads(json.dumps(V28))}
    W.S["own_trips"] = {k: _cached(v) for k, v in OWN.items()}
    W.own_trip_times(NoFLICA())
    W.versions_check()
    assert not any(k.startswith("PAYP|") for k in W.S["own_trips"])
    # v11.029: the trip is cancelled and FLICA shows PAYP
    W.S["schedule"] = {"2026-11": json.loads(json.dumps(V29))}
    W.own_trip_times(NoFLICA())
    rec = W.S["own_trips"]["PAYP|2026-11-12"]
    assert (rec["credit"], rec["blk"], rec["payp"], rec["protected"]) == ("15:00", "0:00", True, "H3620|2026-11-12")
    assert "H3620|2026-11-12" not in W.S["own_trips"]  # the removed trip itself is pruned
    assert _sensor(W)["PAYP|2026-11-12"]["credit"] == "15:00"  # on the own_trips sensor for the card
    W.versions_check()
    v = W.DB.get("sched_versions:2026-11")[-1]
    assert v["trips"]["PAYP|2026-11-12"]["credit"] == "15:00" and v["trips"]["PAYP|2026-11-12"]["payp"] is True
    # later refreshes keep it although the removed trip is gone
    for _ in range(2):
        W.own_trip_times(NoFLICA())
        assert W.S["own_trips"]["PAYP|2026-11-12"] == rec
    # the PAYP leaves the schedule (a reassignment over those days): its record goes with it
    W.S["schedule"] = {"2026-11": _sched([("2026-11-12", "H3630", "LIH"), ("2026-11-13", "", "HNL")],
                                         "126:15", "92:23")}
    W.S["own_trips"]["H3630|2026-11-12"] = _cached({"blk": "10:00", "credit": "10:00"})
    W.own_trip_times(NoFLICA())
    assert "PAYP|2026-11-12" not in W.S["own_trips"] and "PAYP|2026-11-12" not in _sensor(W)


def test_watcher_finds_the_removed_trip_in_the_versions_after_a_restart(W):
    """The Pako case: v11.028 and v11.029 stored, H3620's own record already pruned, no PAYP record yet."""
    W.DB.put("sched_versions:2026-11", [_ver(28, V28, OWN), _ver(29, V29, _own29())])
    W.S["schedule"] = {"2026-11": json.loads(json.dumps(V29))}
    W.S["own_trips"] = {k: _cached(v) for k, v in _own29().items()}
    W.own_trip_times(NoFLICA())
    rec = W.S["own_trips"]["PAYP|2026-11-12"]
    assert rec["credit"] == "15:00" and rec["src"] == "v11.028" and rec["protected"] == "H3620|2026-11-12"
    assert W.load_state()["own_trips"]["PAYP|2026-11-12"] == rec  # saved, with no pairing page read


def test_watcher_payp_step_never_stops_the_trip_reads(W, monkeypatch, caplog):
    W.S["schedule"] = {"2026-11": json.loads(json.dumps(V29))}
    W.S["own_trips"] = {**{k: _cached(v) for k, v in _own29().items()},
                        "PAYP|2026-11-12": {"credit": "15:00", "blk": "0:00", "soft": "0:00", "payp": True,
                                            "protected": "H3620|2026-11-12", "end": "2026-11-14", "src": "own trips"}}

    def boom(*a, **k):
        raise ValueError("synthetic")
    monkeypatch.setattr(W.VER, "payp_entries", boom)
    caplog.set_level(logging.INFO, logger="flight_watcher")
    W.own_trip_times(NoFLICA())
    assert "pay protection skipped" in caplog.text
    assert W.S["own_trips"]["PAYP|2026-11-12"]["credit"] == "15:00"  # what is on file stays


# ---------------------------------------------------------------- the schedule card (Chromium, 390 px)
JS = """async (h) => { window.calls = []; const c = document.createElement('flight-watcher-schedule-card');
  c.setConfig({}); document.body.appendChild(c);
  c.hass = {states: h, callService: async (d, s, data) => window.calls.push([d, s, data])};
  await new Promise((ok) => setTimeout(ok, 300));
  const r = c.shadowRoot, q = (s) => r.querySelector(s);
  const row = (d) => { const tr = r.querySelector(`tr[data-d="${d}"]`); return tr ? [...tr.children].map((td) => td.textContent.trim()) : null; };
  const cell = (d, i) => { const tr = r.querySelector(`tr[data-d="${d}"]`); return tr ? tr.children[i] : null; };
  const pp = r.querySelector('tr[data-d="2026-11-12"] .payp');
  const cr = cell('2026-11-12', 5);
  const rect = cr ? cr.getBoundingClientRect() : null;
  const imp = window.calls.filter((x) => (x[2].topic || '').endsWith('improved/set')).map((x) => JSON.parse(x[2].payload));
  const out = {tot: ((q('.tot') || {}).textContent || '').replace(/\\s+/g, ' ').trim(), bad: !!r.querySelector('.tot .bad'),
    r12: row('2026-11-12'), r13: row('2026-11-13'), r14: row('2026-11-14'), ppTitle: pp ? pp.title : null,
    crTitle: cr ? cr.title : '', crRight: rect ? rect.right : null, crW: rect ? rect.width : 0,
    payInfo: (r.querySelector('tr[data-d="2026-11-12"] .pay') || {dataset: {}}).dataset.info || '',
    vbar: ((q('.vbar') || {}).textContent || '').replace(/\\s+/g, ' ').trim(), imp: imp[imp.length - 1] || null,
    wide: document.documentElement.scrollWidth, marks: r.querySelectorAll('tr[data-d="2026-11-12"] .trb, tr[data-d="2026-11-12"] .drb').length};
  const prev = r.querySelector('.vb[data-v="prev"]');
  if (prev) { prev.click(); await new Promise((ok) => setTimeout(ok, 20));
    out.prev = ((r.querySelector('.vbar') || {}).textContent || '').replace(/\\s+/g, ' ').trim();
    out.prevTot = ((r.querySelector('.tot') || {}).textContent || '').replace(/\\s+/g, ' ').trim(); }
  c.remove(); return out; }"""


def _card_states(sched, own, versions=None):
    from test_release_a_schedule_card import _states
    st = _states({"2026-11": json.loads(json.dumps(sched))}, versions or {}, {"ok": True, "why": ""}, "Nov 12, 2026")
    st["sensor.flight_watcher_state"]["attributes"]["doh"] = "2022-01-15"
    for k, v in (("federal_tax_pct", "22.0"), ("state_tax_pct", "7.0"), ("longevity_year", "5.0")):
        st[f"input_number.flight_watcher_{k}"] = {"state": v, "last_updated": "a", "attributes": {}}
    st["sensor.flight_watcher_own_trip_times"] = {"state": str(len(own)), "last_updated": "a",
                                                  "attributes": {"count": len(own), "trips": own}}
    return st


def _render(cases, src=None):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    from test_release_a_schedule_card import _src
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.fetch = async () => ({ok: false, json: async () => null});</script><script>"
            + (src or _src()) + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-13T02:00:00Z")  # Nov 12 16:00 HST
            pg.set_content(page)
            return {name: pg.evaluate(JS, st) for name, st in cases.items()}
        finally:
            b.close()


def _usd(v):
    return "$" + f"{round(v):,}"


def _rec():
    return VER.payp_entries(V29["items"], dict(OWN), lambda mk: [], PAIRING_RE.match)


CASES = {
    "v28": _card_states(V28, OWN),
    "v29": _card_states(V29, {**_own29(), **_rec()}),
    "v29old": _card_states(V29, _own29()),  # no PAYP record (a version or a Watcher from before 1.7.2)
    "added": _card_states(_sched(ADDED, "137:15", "87:33"), {**_own29(), **_rec(), "H3999|2026-11-13": dict(H3999)}),
    "versions": _card_states(V29, _own29(), {"2026-11": {"count": 2, "current": "11.029", "awarded": "11.028",
                                                         "versions": [_ver(28, V28, OWN), _ver(29, V29, _own29())]}}),
    "browse": _card_states(V29, {**_own29(), **_rec()}, {"2026-11": {"count": 3, "current": "11.030", "awarded": "11.028",
                                                                     "versions": [_ver(28, V28, OWN), _ver(29, V29, _own29()),
                                                                                  _ver(30, V29, {**_own29(), **_rec()})]}}),
}


@pytest.fixture(scope="module")
def card():
    return _render(CASES)


def _pay(tot):
    return (re.search(r"Pay-Gross (\$[\d,]+)", tot).group(1), re.search(r"Pay-Net (\$[\d,]+)", tot).group(1))


def test_card_v11029_with_the_record_matches_flica_and_the_v11028_pay(card):
    a, b = card["v28"], card["v29"]
    gross28 = 131.25 * RATE
    assert "Credit 131:15 ✓" in a["tot"] and not a["bad"], a["tot"]
    assert _pay(a["tot"]) == (_usd(gross28), _usd(gross28 * NET))
    assert "Credit 131:15 ✓" in b["tot"] and not b["bad"], b["tot"]  # FLICA's 131:15: no red
    assert _pay(b["tot"]) == _pay(a["tot"])  # Pay-Gross and Pay-Net as before the cancellation
    assert "PAYP 15:00" in b["tot"] and "estimate" not in b["tot"]
    # the PAYP row: its credit on the start day, no block, no soft, pay at the rate; the next days carry none
    assert b["r12"][2] == "PAYP" and b["r12"][4] == "" and b["r12"][5] == "15:00" and b["r12"][6] == ""
    assert b["r12"][7] == _usd(15 * RATE) and b["r12"][8] == _usd(15 * RATE * NET)
    assert b["r13"][2] == "PAYP" and b["r13"][5] == "" and b["r13"][7] == "" and b["r14"][5] == ""
    assert b["ppTitle"].startswith("Pay protected: H3620 Nov 12 (PWA Definitions 57; 4.R.1 if you add a trip on these "
                                   "days)")
    assert b["crTitle"] == b["ppTitle"] and "Pay protected: H3620 Nov 12" in b["payInfo"]
    assert b["marks"] == 0  # no trade or drop mark on a PAYP


def test_card_block_and_block_avail_never_count_the_payp(card):
    a, b, o = card["v28"], card["v29"], card["v29old"]
    assert "Block 94:42 ✓" in a["tot"] and "Block Avail 3:18" in a["tot"]
    for x in (b, o):  # with the record or with the estimate: H3620's 12:19 is out of the block, nothing added
        assert "Block 82:23 ✓" in x["tot"] and "Block Avail 15:37" in x["tot"] and "Soft 33:52" in x["tot"], x["tot"]


def test_card_estimates_a_payp_with_no_record_from_flicas_month_credit(card):
    o = card["v29old"]
    assert "Credit 131:15 ✓" in o["tot"] and not o["bad"], o["tot"]  # still checked against FLICA
    assert "PAYP 15:00 estimate" in o["tot"]
    assert o["r12"][5] == "15:00 est" and o["r12"][7] == _usd(15 * RATE)
    assert "Pay protected: the removed trip is not on file (PWA Definitions 57" in o["ppTitle"]
    assert "is an estimate: FLICA's month credit 131:15 less everything else counted" in o["ppTitle"]
    assert _pay(o["tot"]) == _pay(card["v28"]["tot"])


def test_card_a_trip_added_on_payp_days_counts_on_top(card):
    x = card["added"]
    assert "Credit 137:15 ✓" in x["tot"] and not x["bad"], x["tot"]  # 131:15 + H3999's 6:00 (PWA 4.R.1)
    assert _pay(x["tot"]) == (_usd(137.25 * RATE), _usd(137.25 * RATE * NET))
    assert x["r12"][5] == "15:00" and x["r13"][2].startswith("H3999") and x["r13"][5] == "6:00"
    assert x["r14"][2] == "PAYP" and x["r14"][5] == ""  # the second PAYP has no record and FLICA leaves it none
    assert "Block 87:33 ✓" in x["tot"]  # only H3999's block joins: 82:23 + 5:10


def test_card_versions_count_the_payp_in_awarded_improved_and_a_viewed_version(card):
    v = card["versions"]  # stored versions from before 1.7.2, no record anywhere: the estimate
    assert v["imp"] and v["imp"]["awarded"] == v["imp"]["current"] == round(131.25 * RATE, 2)
    assert "Improved-Pay-Gross +$0" in v["vbar"], v["vbar"]
    w = card["browse"]  # v11.029 (no record stored) viewed while v11.030 holds it
    assert w["imp"]["awarded"] == w["imp"]["current"]
    assert f"Pay-Gross {_usd(131.25 * RATE)}" in w["prev"] and "v11.029" in w["prev"], w["prev"]
    assert "Credit 131:15 ✓" in w["prevTot"]


def test_card_renders_the_payp_credit_at_390_px(card):
    b = card["v29"]
    assert b["wide"] <= 390  # no page wider than the phone
    assert b["crW"] > 0 and b["crRight"] <= 390  # the Credit cell of the PAYP row is on screen

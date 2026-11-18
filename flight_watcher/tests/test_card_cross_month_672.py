"""1.7.11 (Ryan, Nov 17: "are they gonna say I am over block on Dec 02?"): a trip across a month end is on both
months' schedules (FLICA lists Nov 30 on the December page too). The schedule card counted it once per month, so its
block went into FAR-100/672 and Room twice (H3607: 101:17 on Dec 2 against a real 83:42). It is one trip and counts
once, in both months' views. Chromium, synthetic data only: made-up pairing X9607."""
import pytest

from test_pairing_panel_card import TAG, _browser, _page, _q
from test_fw171_cards import _card

NOW = "2026-11-20T20:00:00Z"
TRIP = {"trip": "X9607", "start": "2026-11-30", "end": "2026-12-02", "lay": "KIX"}
OWN = {"X9607|2026-11-30": {"report": "12:45", "last_arr": "09:20", "blk": "17:35", "credit": "17:35", "seat": "FO",
                            "crew": [], "duties": [
                                {"d": 0, "dep": 825, "arr": 1425, "stn": "KIX", "blk": 600},
                                {"d": 2, "dep": 2985, "arr": 3440, "stn": "HNL", "blk": 455}]}}


def _days(mk, n):
    lay = {"2026-11-30": ("X9607", "KIX"), "2026-12-01": ("", "-"), "2026-12-02": ("", "HNL")}
    return [[f"{mk}-{d:02d}", *lay.get(f"{mk}-{d:02d}", ("", ""))] for d in range(1, n + 1)]


def _states(offset):
    s = lambda st, a=None: {"state": st, "attributes": a or {}, "last_updated": NOW, "last_changed": NOW}  # noqa: E731
    months = {"2026-11": {"items": [TRIP], "days": _days("2026-11", 30), "totals": {"block": "10:00", "credit": "10:00"}},
              "2026-12": {"items": [dict(TRIP)], "days": _days("2026-12", 31), "totals": {"block": "7:35", "credit": "7:35"}}}
    return {"sensor.flight_watcher_schedule": s("ok", {"updated": "Nov 20, 2026", "months": months}),
            "sensor.flight_watcher_own_trip_times": s("1", {"count": 1, "trips": OWN}),
            "input_number.flight_watcher_month_offset": s(str(offset)),
            "sensor.flight_watcher_state": s("watching", {"role": "admin", "doh": "2012-03-04"})}


@pytest.mark.parametrize("offset,day,want", [(0, "2026-11-30", "10:00"), (1, "2026-12-02", "17:35"),
                                             (1, "2026-12-05", "17:35")])
def test_a_trip_across_a_month_end_counts_once_in_100_672(offset, day, want):
    with _browser() as b:
        pg = _page(b, _card("schedule-card", pilot=False), 1280, 900, pkg=None)
        pg.clock.set_fixed_time(NOW)
        pg.evaluate("([tag, st]) => { window.C = mount(tag, {}, st, {user: {id: 'o', name: 'O', is_admin: true, "
                    "is_owner: true}}); }", [TAG, _states(offset)])
        pg.wait_for_function(f"C.shadowRoot && C.shadowRoot.querySelector('tr[data-d=\"{day}\"]')")
        cell = _q(pg, f"return q('tr[data-d=\"{day}\"]').cells[11].textContent.replace('~', '').trim();")
        assert cell == want  # each leg once (Nov 30: the first leg so far), never twice

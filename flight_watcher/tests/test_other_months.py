"""0.8.5: October / December via Tools > Schedule Lookup for Ryan's own number (synthetic pages only)."""
import json
import os
import sys

import pytest


@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    W.S.clear()
    return W


def _page(bd, months, rows):
    opts = "".join(f'<option value="{b}" {"selected" if b == bd else ""}> M' for b in months)
    tasks = "".join(f'TAry[TAry.length]=new Task(1, "SU", "{dd}", "{code}", "{lay}", "{ymd}", 1, 0, \'{code}\');' for dd, code, lay, ymd in rows)
    return (f'<html><script>function pair(pr){{}} {tasks}</script><select name="BlockDates">{opts}</select>'
            ' DOE, PAT (Emp# 10008) Schedule Last Updated: Nov 4, 2026 13:52:55 HA'
            '<table><tr><td>Block &nbsp;</td><td>80.10</td></tr><tr><td>Days Off</td><td>14</td></tr></table></html>')


class FakeFl:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def fetch(self, url):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        return "<html>nothing</html>"


def test_note_own(W):
    assert W.note_own("flica.net - tradeboard trade requests - november doe, pat 10008 - hnl 332 fo display options") == "10008"
    assert W.S["own_name"] == "Doe, Pat" and W.S["sched_prev_at"] == 0
    assert W.note_own("no header here") == "10008"


def test_other_months_read_and_cached(W):
    W.S["own_emp"] = "10008"
    months = ("1026", "1126")
    pages = {"bd=1126": _page("1126", months, [("01", "H3647", "PHX", "20261101")]),
             "bd=1026": _page("1026", months, [("03", "H3610", "LAX", "20261003"), ("20", "VAC", "", "20261020")])}
    fl = FakeFl(pages)
    assert W.other_months_check(fl, "2026-11") is True
    oct_ = W.S["schedule"]["2026-10"]
    assert oct_["month"] == "2026-10" and [i["trip"] for i in oct_["items"]] == ["H3610", "VAC"]
    assert oct_["totals"] == {"block": "80:10", "days_off": 14} and oct_["src"] == "lookup"
    assert "2026-11" not in W.S["schedule"]  # the current month is the schedule check's job
    n = len(fl.urls)
    # 1.6.2 review: the month list is kept 6 h (S lookup_months) and October is cached: no load at all
    assert W.other_months_check(fl, "2026-11") is True and len(fl.urls) == n
    # December appears in the list once published (the next current-month lookup page, or 6 h on, brings the list)
    months3 = ("1026", "1126", "1226")
    pages["bd=1126"] = _page("1126", months3, [("01", "H3647", "PHX", "20261101")])
    pages["bd=1226"] = _page("1226", months3, [("05", "H3700", "SYD", "20261205")])
    W.S["lookup_months"]["at"] -= 6 * 3600 + 1
    assert W.other_months_check(fl, "2026-11") is True
    assert [i["trip"] for i in W.S["schedule"]["2026-12"]["items"]] == ["H3700"]


def test_other_months_without_number_or_list(W):
    assert W.other_months_check(FakeFl({}), "2026-11") is False
    W.S["own_emp"] = "10008"
    assert W.other_months_check(FakeFl({"cmschedules": "<html>application error</html>"}), "2026-11") is False

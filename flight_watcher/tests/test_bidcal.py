"""1.7.1 (FW-0070, Ryan): bid calendar alerts. bidcal.parse reads a pairing package's Bid Calendar from its two-column
cover page, bidcal.schedule makes the cycle's alerts (the package's dates, else the usual ones), and the Watcher sends
each once on <prefix>/event/bid_calendar from the uploads janitor, whatever its state, keeps the sensor
<prefix>_bid_calendar and never repeats one after a restart. Only Ryan's prefix has the HA push. Synthetic cover pages that copy the layout
of the real packages (two columns, the date and its label first, table text after them), made-up table text."""
import copy
import importlib.util
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta

import pytest

import bidcal as BC
import roles

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
HST = BC.HST
RIGHT = 66  # where the right column (the reserve and credit tables) starts on the real pages


def _ln(left="", right=""):
    return (left.ljust(RIGHT) + right).rstrip() if right else left


# the December 2026 layout: awards' "1700HST on" next to the note, open time's date three lines under its label
DEC = "\n".join([
    _ln(" " * 70 + "December 2026 Pairing Package"),
    _ln(" " * 69 + "December 2 to December 31 (30 Days)"),
    _ln(" " * 57 + "For general PBS questions, ask the PBS office."),
    _ln("", "Reserve Construction        RSV Period   A321 (R1)   A332 (R3)"),
    _ln("                    Bid Calendar"),
    _ln("", "                                               R1A        R3A"),
    _ln("", "Synthetic reserve text for the test, not a real rule.   0400-1600"),
    _ln("November 4               Pairing Package Published", "periods will follow the made-up ratio of groupings"),
    _ln("", "2-day reserve periods will not exceed the percentage shown"),
    _ln("November 7                     Practice Run #1", "occur on the pilot's Reserve Run at least as shown"),
    _ln("November 10                    Practice Run #2", "                              LATE (C)"),
    _ln("", "groupings will not exceed the percentage in the column."),
    "",
    _ln("November 11                 CA & FO Bids Close", "              LCR        LCR"),
    _ln("", "      1-Day     2-Days     3-Days     4+ Days   LONG CALL"),
    _ln(" 0800HST             (Flica closed during award processing)", "0001-2400  0001-2400"),
    _ln("", "A321           49%        51%"),
    _ln(" no later than           All Monthly Awards Posted", "        Freight Allocation of Flying"),
    _ln("1700HST on         *Note: Flica will reopen when the Bid", "A332    48%   51%   1%"),
    _ln("November 15              Run Award is published*", "        Min Credit/  Normal  Max Credit"),
    _ln("", "HNL"),
    _ln(" no later than", "B789"),
    _ln("                   Freight Flight Groupings Modified with"),
    _ln("1700HST on"),
    _ln("                      Deadheads to/from Gateway City", "SEA     A33YFO   75   80   90"),
    _ln("November 18"),
    _ln("", "B789     FREIGHT   Min 64"),
    _ln("1200HST on            Flica Open Time Window Opens"),
    _ln("", "VACATION"),
    _ln("", "Threshold"),
    _ln("November 22                    for December", "B717    62%    38%    75   ABOVE   ABOVE"),
    "",
    _ln("       ALV               Min Credit / MMG", "Initial Min Credit   Average Line Value"),
]) + "\f" + "\n".join([  # page 2: a pairing page, never read for the calendar
    "November 30                    Practice Run #1",
    "H9001  Doe, Jane  synthetic pairing text",
])

# the October 2026 layout, moved to a January 2027 package: dates in December 2026, the awards' "1700HST on" with
# table text after it, Practice Run #1 on the 8th (not the usual 7th)
JAN = "\n".join([
    _ln(" " * 75 + "January 2027 Pairing Package"),
    _ln("                    Bid Calendar", "Reserve Construction"),
    _ln("December 4              Pairing Package Published", "periods will follow the made-up ratio"),
    _ln("December 8                    Practice Run #1", "occur on the Reserve Run at least as shown"),
    _ln("December 10                   Practice Run #2", "ings will not exceed the percentage shown"),
    _ln("December 11                CA & FO Bids Close", "      LONG CALL"),
    _ln("  0800HST            (Flica closed during award processing)"),
    _ln("", "A321          62%       38%"),
    _ln("  no later than         All Monthly Awards Posted"),
    _ln(" 1700HST on", "A332          50%       48%      2%"),
    _ln("                   *Note: Flica will reopen when the Bid", "Min Credit/  Normal"),
    _ln("December 15            Run Award is published*", "Min Thresh   Threshold"),
    _ln("  no later than", "B789"),
    _ln(" 1700HST on        Freight Flight Groupings Modified with"),
    _ln("                      Deadheads to/from Gateway City", "SEA"),
    _ln("December 18", "                       90%     10%"),
    _ln(" 1200HST on           Flica Open Time Window Opens", "FREIGHT   Threshold   SAME AS"),
    _ln("December 22                    for January", "B717    64%    36%   VACATION   75"),
])


# ---------------------------------------------------------------- parse
def test_parse_reads_the_left_column_of_the_two_column_cover_page():
    assert BC.parse(DEC) == {
        "bid_month": "2026-12", "published": "2026-11-04", "practice": ["2026-11-07", "2026-11-10"],
        "close": {"date": "2026-11-11", "time": "08:00"}, "awards_by": {"date": "2026-11-15", "time": "17:00"},
        "open_time_opens": {"date": "2026-11-22", "time": "12:00"}}


def test_parse_a_january_package_dates_its_calendar_in_december_of_the_year_before():
    assert BC.parse(JAN, "2027-01") == {
        "bid_month": "2027-01", "published": "2026-12-04", "practice": ["2026-12-08", "2026-12-10"],
        "close": {"date": "2026-12-11", "time": "08:00"}, "awards_by": {"date": "2026-12-15", "time": "17:00"},
        "open_time_opens": {"date": "2026-12-22", "time": "12:00"}}


def test_parse_reads_page_one_only_and_never_the_right_column():
    # the page 2 line naming Practice Run #1 on Nov 30 is not read: page 1's Nov 7 stays
    assert BC.parse(DEC)["practice"][0] == "2026-11-07"
    # a date and label that sit in the right column (a table cell) are never the calendar's
    lines = DEC.split("\f")[0].splitlines()
    lines = [ln for ln in lines if "Practice Run #2" not in ln]
    lines.append(_ln("", "November 30      Practice Run #2"))
    assert BC.parse("\n".join(lines))["practice"] == ["2026-11-07", None]


def test_parse_says_none_for_what_it_does_not_find():
    nothing = BC.parse("")
    assert nothing == {"bid_month": None, "published": None, "practice": [None, None], "close": None,
                       "awards_by": None, "open_time_opens": None}
    no_head = "\n".join(ln for ln in DEC.split("\f")[0].splitlines() if "Pairing Package" not in ln
                        or "Published" in ln)
    assert BC.parse(no_head) == nothing  # no heading and no month given: no date can get its year
    got = BC.parse(no_head, "2026-12")  # the upload's name gives the month
    assert got["published"] == "2026-11-04" and got["close"] == {"date": "2026-11-11", "time": "08:00"}
    no_time = DEC.replace(" 0800HST ", "         ")
    assert BC.parse(no_time)["close"] == {"date": "2026-11-11", "time": None}


# ---------------------------------------------------------------- schedule
def _by_kind(alerts):
    return {a["kind"]: a for a in alerts}


def test_schedule_without_a_package_uses_the_usual_days_and_says_so():
    a = _by_kind(BC.schedule("2026-12"))
    assert tuple(a) == BC.KINDS == ("publish_eve", "practice_eve_1", "practice_eve_2", "close_24h", "close_eve")
    assert {k: (v["fire_at"], v["deadline"]) for k, v in a.items()} == {
        "publish_eve": ("2026-11-03T08:00:00-10:00", "2026-11-04T00:00:00-10:00"),
        "practice_eve_1": ("2026-11-06T20:00:00-10:00", "2026-11-07T00:00:00-10:00"),
        "practice_eve_2": ("2026-11-09T20:00:00-10:00", "2026-11-10T00:00:00-10:00"),
        "close_24h": ("2026-11-10T08:00:00-10:00", "2026-11-10T20:00:00-10:00"),
        "close_eve": ("2026-11-10T20:00:00-10:00", "2026-11-11T08:00:00-10:00")}
    assert {v["source"] for v in a.values()} == {"default"}
    assert a["publish_eve"]["key"] == "2026-12_publish_eve"
    assert a["publish_eve"]["message"] == ("The December pairing package publishes tomorrow, Wed Nov 4. Adjust your "
                                           "vacation if needed.")
    assert a["practice_eve_1"]["title"] == "PBS Practice Run #1 tomorrow"
    assert a["practice_eve_1"]["message"].startswith(
        "Practice Run #1 for December is tomorrow, Sat Nov 7. Have your PBS bid in by tonight.")
    assert a["close_24h"]["title"] == "Bids close in 24 h"
    assert a["close_24h"]["message"].startswith(
        "December bids close in 24 h: Wed Nov 11 08:00 HST. FLICA closes during award processing.")
    assert a["close_eve"]["title"] == "Bids close tomorrow 08:00 HST"
    assert "Finish your PBS bid tonight." in a["close_eve"]["message"]
    # a usual date says so; the publish alert never (no package can be on file before it publishes)
    assert all("Usual date" in v["message"] for k, v in a.items() if k != "publish_eve")
    assert "Usual date" not in a["publish_eve"]["message"]


def test_schedule_takes_the_dates_of_the_cycles_own_package():
    a = _by_kind(BC.schedule("2027-01", BC.parse(JAN)))
    assert a["practice_eve_1"]["fire_at"] == "2026-12-07T20:00:00-10:00"  # Practice Run #1 on Dec 8, not the 7th
    assert "Tue Dec 8" in a["practice_eve_1"]["message"] and "Usual date" not in a["practice_eve_1"]["message"]
    assert {v["source"] for v in a.values() if v["kind"] != "publish_eve"} == {"package"}
    c = BC.cycle_dates("2027-01", BC.parse(JAN))
    assert c["source"] == "package" and c["awards_by"] == {"date": "2026-12-15", "time": "17:00"}
    # another month's package is not this cycle's: the usual dates stay
    assert BC.cycle_dates("2026-12", BC.parse(JAN))["source"] == "default"
    assert _by_kind(BC.schedule("2026-12", BC.parse(JAN)))["practice_eve_1"]["fire_at"] == "2026-11-06T20:00:00-10:00"
    # a misread date far from the cycle never moves an alert: that one date keeps its default
    bad = dict(BC.parse(JAN), practice=["2026-03-08", "2026-12-10"])
    c = BC.cycle_dates("2027-01", bad)
    assert c["practice"] == ["2026-12-07", "2026-12-10"] and c["sources"]["practice_1"] == "default"


def test_the_publish_alert_time_is_one_constant(monkeypatch):
    # Ryan, Nov 11 (FW-0070): 08:00 HST the day before the publish date (the 3rd by default), not 20:00
    assert BC.PUBLISH_ALERT == (1, "08:00")
    monkeypatch.setattr(BC, "PUBLISH_ALERT", (0, "08:00"))  # Ryan's answer could be the morning of the 4th
    a = _by_kind(BC.schedule("2026-12"))["publish_eve"]
    assert (a["fire_at"], a["deadline"]) == ("2026-11-04T08:00:00-10:00", "2026-11-05T00:00:00-10:00")
    assert a["title"] == "December pairing package today"
    monkeypatch.setattr(BC, "PUBLISH_ALERT", (2, "20:00"))
    a = _by_kind(BC.schedule("2026-12"))["publish_eve"]
    assert a["fire_at"] == "2026-11-02T20:00:00-10:00" and "publishes in 2 days, Wed Nov 4" in a["message"]


def _t(d, hm):
    return datetime(2026, 11, d, int(hm[:2]), int(hm[3:]), tzinfo=HST)


def test_due_sends_late_until_the_deadline_then_drops():
    alerts = BC.schedule("2026-12")
    send, drop = BC.due(alerts, {}, _t(10, "10:00"))  # off since before Nov 3: back at 10:00 on the 10th
    assert [a["kind"] for a in send] == ["close_24h"]
    assert [a["kind"] for a in drop] == ["publish_eve", "practice_eve_1", "practice_eve_2"]
    title, msg = BC.render(send[0], _t(10, "10:00"))
    assert title == "Bids close in 22 h" and msg.startswith("December bids close in 22 h: Wed Nov 11 08:00 HST.")
    send, drop = BC.due(alerts, {}, _t(11, "07:00"))  # close_eve still useful, worded for the morning itself
    assert [a["kind"] for a in send] == ["close_eve"] and "close_24h" in [a["kind"] for a in drop]
    title, msg = BC.render(send[0], _t(11, "07:00"))
    assert title == "Bids close today 08:00 HST" and "Finish your PBS bid now." in msg
    send, drop = BC.due(alerts, {}, _t(11, "08:00"))
    assert send == [] and len(drop) == 5
    assert BC.due(alerts, {a["key"]: {} for a in alerts}, _t(11, "08:00")) == ([], [])
    assert BC.due(alerts, {}, _t(3, "07:59")) == ([], [])  # nothing before its time


def test_the_publish_alert_goes_at_0800_the_day_before_and_holds_until_the_publish_day():
    """FW-0070, Ryan's Nov 11 answer: the 'pairing package publishes tomorrow, adjust your vacation' alert fires at
    08:00 HST the day before the publish date (Nov 3 for the usual 4th), not at 20:00; one sent late (the app was off
    that morning) still goes out until the publish day starts."""
    alerts = BC.schedule("2026-12")
    assert BC.due(alerts, {}, _t(3, "07:59")) == ([], [])
    send, drop = BC.due(alerts, {}, _t(3, "08:00"))
    assert [a["kind"] for a in send] == ["publish_eve"] and drop == []
    assert send[0]["fire_at"] == "2026-11-03T08:00:00-10:00"
    assert BC.render(send[0], _t(3, "08:00")) == (
        "December pairing package tomorrow",
        "The December pairing package publishes tomorrow, Wed Nov 4. Adjust your vacation if needed.")
    send, _ = BC.due(alerts, {}, _t(3, "21:00"))  # late, still the day before: sent, worded the same
    assert [a["kind"] for a in send] == ["publish_eve"]
    send, drop = BC.due(alerts, {}, _t(4, "00:00"))  # the publish day has started: dropped
    assert send == [] and [a["kind"] for a in drop] == ["publish_eve"]
    # the package's own publish date moves it with it: published Dec 4 on January's cover page, so 08:00 Dec 3
    a = _by_kind(BC.schedule("2027-01", BC.parse(JAN)))["publish_eve"]
    assert a["fire_at"] == BC._at(date.fromisoformat(BC.parse(JAN)["published"]) - timedelta(days=1),
                                  "08:00").isoformat()


def test_cycles_are_next_month_and_the_one_after():
    assert BC.cycles(_t(11, "10:00")) == ["2026-12", "2027-01"]
    assert BC.cycles(datetime(2026, 12, 31, 23, 59, tzinfo=HST)) == ["2027-01", "2027-02"]
    assert BC.cycles(datetime(2026, 12, 1, 9, 59, tzinfo=BC.timezone.utc)) == ["2026-12", "2027-01"]  # Nov 30 HST


def test_no_em_dash_in_the_module_or_its_words():
    assert chr(0x2014) not in open(os.path.join(HERE, "bidcal.py"), encoding="utf-8").read()
    for bm, p in (("2026-12", None), ("2027-01", BC.parse(JAN))):
        for a in BC.schedule(bm, p):
            assert chr(0x2014) not in a["title"] + a["message"]


# ---------------------------------------------------------------- the Watcher
class FakeClient:
    def __init__(self, up=True):
        self.msgs, self.up = [], up

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass

    def is_connected(self):
        return self.up


def _load(tmp_path, monkeypatch, instance="", fake=None):
    data = tmp_path / ("data_" + (instance or "default"))
    data.mkdir(exist_ok=True)
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "log_level": "info",
                                                   "category_check": "HNL 332 FO"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(uploads))
    fake = fake or FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    return W, fake, uploads


@pytest.fixture(autouse=True)
def _unload():
    yield
    sys.modules.pop("watcher", None)


def _events(fake, prefix="flight_watcher"):
    return [(json.loads(p), r) for t, p, r in fake.msgs if t == f"{prefix}/event/bid_calendar"]


def _sensor(fake, prefix="flight_watcher"):
    got = [(json.loads(p), r) for t, p, r in fake.msgs if t == f"{prefix}/bid_calendar"]
    return got[-1] if got else (None, None)


def test_each_alert_goes_once_and_a_restart_never_repeats_one(tmp_path, monkeypatch, caplog):
    W, fake, _ = _load(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        sent = W.bidcal_tick(_t(6, "20:00"))
    assert [a["kind"] for a in sent] == ["practice_eve_1"]
    (ev, retain), = _events(fake)
    assert retain is False
    assert ev == {"kind": "bid_calendar", "key": "2026-12_practice_eve_1", "bid_month": "2026-12",
                  "title": "PBS Practice Run #1 tomorrow", "message": ev["message"],
                  "at_hst": "2026-11-06T20:00:00-10:00", "event_hst": "2026-11-07T00:00:00-10:00", "source": "default"}
    assert ev["message"].startswith("Practice Run #1 for December is tomorrow, Sat Nov 7.")
    # the publish alert of Nov 3 was missed (the app was off): dropped with a log line, never sent
    assert "2026-12_publish_eve not sent" in caplog.text
    assert W.DB.get(W.BIDCAL_DONE)["2026-12_publish_eve"]["how"] == "dropped"
    assert W.bidcal_tick(_t(6, "20:01")) == [] and len(_events(fake)) == 1
    # a restart (the module again, the same /data): nothing repeats, the next one still comes
    W, fake, _ = _load(tmp_path, monkeypatch)
    assert W.bidcal_tick(_t(6, "21:00")) == [] and _events(fake) == []
    assert [a["kind"] for a in W.bidcal_tick(_t(9, "20:00"))] == ["practice_eve_2"]
    assert [e["key"] for e, _ in _events(fake)] == ["2026-12_practice_eve_2"]


def test_a_due_alert_waits_while_mqtt_is_down(tmp_path, monkeypatch):
    W, fake, _ = _load(tmp_path, monkeypatch, fake=FakeClient(up=False))
    assert W.bidcal_tick(_t(10, "08:00")) == [] and _events(fake) == []
    assert "2026-12_close_24h" not in (W.DB.get(W.BIDCAL_DONE) or {})
    fake.up = True
    sent = W.bidcal_tick(_t(10, "08:30"))  # back: sent late, still before its deadline
    assert [a["kind"] for a in sent] == ["close_24h"]
    assert _events(fake)[0][0]["title"] == "Bids close in 24 h"  # 23.5 h left reads 24 h


def test_the_cycles_package_dates_are_used_when_it_is_on_file(tmp_path, monkeypatch):
    W, fake, uploads = _load(tmp_path, monkeypatch)
    jan = BC.parse(JAN)
    (uploads / "2027-01_pairings.txt").write_text(JAN, encoding="utf-8")
    sent = W.bidcal_tick(datetime(2026, 12, 7, 20, 0, tzinfo=HST))
    assert [a["key"] for a in sent] == ["2027-01_practice_eve_1"]
    ev = _events(fake)[0][0]
    assert ev["source"] == "package" and "Tue Dec 8" in ev["message"]
    s, retain = _sensor(fake)
    assert retain is True and s["bid_month"] == "2027-01" and s["source"] == "package"
    assert s["practice"] == jan["practice"] and s["open_time_opens"] == jan["open_time_opens"]
    assert s["next_at"] == "2026-12-09T20:00:00-10:00" and s["next"]["key"] == "2027-01_practice_eve_2"
    # a package for another month under this name is not used
    (uploads / "2027-02_pairings.txt").write_text(JAN, encoding="utf-8")
    assert W.bidcal_package("2027-02") is None


def test_the_sensor_shows_the_next_alert_and_its_cycle(tmp_path, monkeypatch):
    W, fake, _ = _load(tmp_path, monkeypatch)
    W.bidcal_tick(_t(11, "10:00"))  # December's cycle is over (all dropped): January's is next
    s, retain = _sensor(fake)
    assert retain is True
    assert s["next_at"] == "2026-12-03T08:00:00-10:00" and s["bid_month"] == "2027-01" and s["source"] == "default"
    assert s["next"]["at_hst"] == "Thu Dec 3 08:00 HST" and s["next"]["title"] == "January pairing package tomorrow"
    assert s["close"] == {"date": "2026-12-11", "time": "08:00"} and s["practice"] == ["2026-12-07", "2026-12-10"]
    assert [a["status"] for a in s["alerts"]] == ["pending"] * 5
    n = len(fake.msgs)
    W.bidcal_tick(_t(11, "10:01"))
    assert len(fake.msgs) == n  # unchanged: not published again
    cfg = next(c for comp, oid, c, f in W.entity_defs() if oid == "bid_calendar")
    assert cfg["default_entity_id"] == "sensor.flight_watcher_bid_calendar" and cfg["device_class"] == "timestamp"
    assert cfg["state_topic"] == cfg["json_attributes_topic"] == "flight_watcher/bid_calendar"
    assert cfg["value_template"] == "{{ value_json.next_at }}"
    assert len(json.dumps(s, separators=(",", ":"))) < 4000


def test_a_pilot_makes_the_same_alerts_on_his_own_prefix(tmp_path, monkeypatch):
    W, fake, _ = _load(tmp_path, monkeypatch, "pilot2")
    assert roles.event_allowed("bid_calendar", "pilot2") and "bid_calendar" not in roles.PORTAL_EVENTS
    W.bidcal_tick(_t(6, "20:00"))
    assert [e["key"] for e, _ in _events(fake, "flight_watcher_pilot2")] == ["2026-12_practice_eve_1"]
    assert not [t for t, _, _ in fake.msgs if t.startswith("flight_watcher/")]  # never on the admin's prefix
    cfg = next(c for comp, oid, c, f in W.entity_defs() if oid == "bid_calendar")
    assert cfg["default_entity_id"] == "sensor.flight_watcher_pilot2_bid_calendar"


class _Stop(BaseException):
    pass


def test_the_uploads_janitor_checks_every_minute_whatever_else_fails(tmp_path, monkeypatch):
    W, fake, _ = _load(tmp_path, monkeypatch)
    ticks, sleeps = [], []

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) > 12:
            raise _Stop()
    monkeypatch.setattr(W.time, "sleep", sleep)
    monkeypatch.setattr(W, "assembler", lambda: type("A", (), {"sweep": lambda self: []})())  # no staging folder
    monkeypatch.setattr(W, "bidcal_tick", lambda: ticks.append(1))

    def broken():
        raise OSError("uploads folder gone")
    monkeypatch.setattr(W, "publish_uploads", broken)
    with pytest.raises(_Stop):
        W.upload_janitor()
    assert len(ticks) == 2  # 120 s: one a minute, though the uploads list fails each time
    monkeypatch.setattr(W, "bidcal_tick", lambda: (_ for _ in ()).throw(ValueError("x")))
    listed = []
    monkeypatch.setattr(W, "publish_uploads", lambda: listed.append(1))
    sleeps.clear()
    with pytest.raises(_Stop):
        W.upload_janitor()
    assert len(listed) == 2  # and a bid calendar error never stops the uploads list


def test_the_dockerfile_copies_every_module_the_watcher_imports():
    src = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    mods = set(re.findall(r"^import (\w+)", src, re.M)) | set(re.findall(r"^from (\w+) import", src, re.M))
    local = {m for m in mods if os.path.exists(os.path.join(HERE, m + ".py"))}
    copy_line = next(ln for ln in open(os.path.join(HERE, "Dockerfile"), encoding="utf-8").read().splitlines()
                     if ln.startswith("COPY run.py"))
    assert "bidcal" in local and {m + ".py" for m in local} <= set(copy_line.split())


# ---------------------------------------------------------------- the HA push (Ryan's phones only)
_spec = importlib.util.spec_from_file_location("check_push_isolation_bidcal", os.path.join(ROOT, "ha",
                                                                                          "check_push_isolation.py"))
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)
SNAPSHOT = os.path.join(ROOT, "ha", "automations_flight_watcher.yaml")


def _targets(auto):
    return [s["action"] for s in auto["actions"][1]["parallel"]]


def test_the_ha_push_is_ryans_critical_alert_like_the_charter_one():
    autos = G.load(SNAPSHOT)
    bid = next(a for a in autos if a["alias"] == "Flight Watcher bid calendar")
    charter = next(a for a in autos if a["alias"] == "Flight Watcher charter")
    assert bid["triggers"] == [{"topic": "flight_watcher/event/bid_calendar", "trigger": "mqtt"}]
    assert sorted(_targets(bid)) == sorted(_targets(charter))
    for b, c in zip(bid["actions"][1]["parallel"], charter["actions"][1]["parallel"]):
        assert b["data"]["data"]["push"] == c["data"]["data"]["push"]  # interruption-level critical, its sound
        assert b["data"]["title"] == "{{ p.title }}" and b["data"]["message"] == "{{ p.message }}"
        assert b["continue_on_error"] is True
    assert bid["actions"][0] == {"variables": {"p": "{{ trigger.payload_json }}"}}
    # no automation pushes a pilot's bid calendar topic
    text = open(SNAPSHOT, encoding="utf-8").read()
    assert re.findall(r"flight_watcher\w*/event/bid_calendar", text) == ["flight_watcher/event/bid_calendar"]
    assert G.check(autos)[0] == []


def test_the_guard_refuses_the_bid_calendar_push_from_a_pilots_prefix():
    autos = G.load(SNAPSHOT)
    bad = copy.deepcopy(autos)
    next(a for a in bad if a["alias"] == "Flight Watcher bid calendar")["triggers"][0]["topic"] = \
        "flight_watcher_james/event/bid_calendar"
    offenders, _ = G.check(bad)
    assert any(name == "Flight Watcher bid calendar" and "pushes Ryan" in why for name, why in offenders), offenders

"""1.7.2, contract 1 revision 3 (the council's plan of Nov 11 and Ryan's decisions), besides the pilot uploads
(test_fw172_uploads.py): the bid_calendar and schedule_unread portal events (his Alerts list and ntfy), the pilot/set
shape on the spool and in the Watcher, recall/set refused from the portal, the fit alone in the new pairing text, the
manifest's revision, and the CrewTrac refusal block keyed with an HMAC of the instance's own. Synthetic data only."""
import hashlib
import json
import logging
import os
import stat
import time
from datetime import datetime, timedelta, timezone

import pytest

import bidcal as BC
import charter as CH
import ntfy as NT
import portal as PT
import roles

HST = timezone(timedelta(hours=-10))
FIX = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "portal_contract_v1.json"),
                     encoding="utf-8"))


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


def _events(W, kind):
    return [e for e in W.EXPORT["events_list"] if e["kind"] == kind]


# ---------------------------------------------------------------- bid_calendar on the pilot's portal
def test_a_pilots_bid_calendar_alert_is_a_portal_event_with_the_admins_words(portal_pilot):
    at = datetime(2026, 11, 6, 20, 0, tzinfo=HST)  # the night before Practice Run #1 (December's bid month)
    A, _ = portal_pilot("", portal=False)
    sent = A.bidcal_tick(at)
    assert [a["kind"] for a in sent] == ["practice_eve_1"]
    admin = json.loads(next(p for t, p, *_ in A.MQ.raw.msgs if t == "flight_watcher/event/bid_calendar"))
    assert not A.EXPORT["on"] and not A.EXPORT["events_list"]  # the admin has no portal
    W, _ = portal_pilot("pilot2")
    assert W.portal_start(threads=False)
    W.bidcal_tick(at)
    mine = json.loads(next(p for t, p, *_ in W.MQ.raw.msgs if t == "flight_watcher_pilot2/event/bid_calendar"))
    assert set(mine) == set(admin) and {k: mine[k] for k in mine if k != "at_hst"} == {
        k: admin[k] for k in admin if k != "at_hst"}  # the same keys and words on both instances
    (ev,) = _events(W, "bid_calendar")
    assert (ev["title"], ev["body"]) == (admin["title"], admin["message"])
    assert ev["title"] == "PBS Practice Run #1 tomorrow" and ev["view"] == "watcher" and ev["priority"] == 4
    assert set(ev["data"]) == set(roles.EVENT_KIND_FIELDS["bid_calendar"])
    assert ev["data"]["alert"] == "practice_eve_1" and "title" not in ev["data"] and "message" not in ev["data"]
    # ntfy says the same with a token or without (dates and what to do only)
    assert NT.plain_text(ev) == (ev["title"], ev["body"])
    # the same alert again (a replay) keeps its id; the date moved (a package uploaded late) is a new id
    assert PT.event_record("bid_calendar", mine, 1, "t")["id"] == ev["id"]
    assert PT.event_record("bid_calendar", {**mine, "event_hst": "2026-11-08T00:00:00-10:00"}, 2, "t")["id"] != ev["id"]


def test_bid_calendar_text_comes_only_from_well_shaped_fields():
    a = BC.schedule("2026-12")[3]  # close_24h
    at = datetime.fromisoformat(a["fire_at"])
    d = {"bid_month": "2026-12", "alert": a["kind"], "event_hst": a["event"], "at_hst": a["fire_at"],
         "source": a["source"], "cycle_source": a["cycle_source"]}
    assert BC.alert_text(d) == BC.render(a, at)
    for bad in ({**d, "alert": "free text"}, {**d, "bid_month": "Doe, Jane"}, {**d, "event_hst": "soon"},
                {**d, "at_hst": "2026-11-10T08:00:00"}):  # a naive time too
        assert BC.alert_text(bad) is None
    assert PT.event_text("bid_calendar", {"alert": "x"}) == ("Bid calendar", "See the bid calendar dates in your "
                                                                             "pairing package.")
    # another kind's payload never brings the bid calendar's own fields along
    assert "alert" not in PT.event_data("new_pairing", {"pairing": "H9001", "alert": "publish_eve", "source": "x"})


# ---------------------------------------------------------------- schedule_unread
@pytest.fixture
def unread(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    assert W.portal_start(threads=False)
    now = time.time()
    monkeypatch.setattr(W, "PROC_START", now - 10 * 3600)
    W.S["machine"] = "hunting"
    return W, now


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def test_schedule_unread_after_6_h_once_a_day(unread):
    W, now = unread
    W.S["sched_read_at"] = _iso(now - 5 * 3600)
    assert W.schedule_unread_tick(now) is None  # 5 h: not yet
    W.S["sched_read_at"] = _iso(now - 7 * 3600 - 60)
    W.S["sched_fail"] = 2
    rec = W.schedule_unread_tick(now)
    assert rec["kind"] == "schedule_unread" and rec["view"] == "schedule" and rec["data"] == {"state": "failing",
                                                                                            "hours": 7}
    assert rec["title"] == "Schedule not read for 7 h" and "keeps trying" in rec["body"]
    assert W.schedule_unread_tick(now + 3600) is None  # at most once an HST day
    assert NT.plain_text(rec) == ("Schedule not read for 7 h", "Open the Schedule tab of your Flight Watcher portal "
                                                               "to see why.")
    nxt = W.schedule_unread_tick(now + 86400)
    assert nxt and nxt["data"]["hours"] == 31 and nxt["id"] != rec["id"]
    assert len(_events(W, "schedule_unread")) == 2


def test_schedule_unread_since_the_start_when_no_read_came_and_never_when_paused_or_waiting_for_logins(unread,
                                                                                                         monkeypatch):
    W, now = unread
    monkeypatch.setattr(W, "PROC_START", now - 3 * 3600)
    W.S["sched_read_at"] = _iso(now - 48 * 3600 - 60)  # the app was off: counted from this start
    assert W.schedule_unread_tick(now) is None
    monkeypatch.setattr(W, "PROC_START", now - 6 * 3600 - 1)
    for st in ("paused", "needs_settings", "stopped_login_failed"):
        W.S["machine"] = st
        assert W.schedule_unread_tick(now) is None, st
    W.S["machine"] = "yielded"  # a yield is waiting (his own FLICA login elsewhere): it counts
    assert W.schedule_unread_tick(now) is None  # review: 6 h from the last tick that saw him held, not from the read
    rec = W.schedule_unread_tick(now + 6 * 3600 + 60)
    assert rec["data"] == {"state": "waiting", "hours": 54} and "waiting" in rec["body"]  # since the last good read


def test_schedule_unread_is_never_made_from_a_publish(unread):
    W, _ = unread
    W.MQ.publish("flight_watcher_pilot2/event/schedule_unread", json.dumps({"state": "x", "hours": 1}))
    assert not _events(W, "schedule_unread")
    assert "schedule_unread" in roles.OWN_EVENTS and "schedule_unread" not in roles.PORTAL_EVENTS


def test_schedule_unread_never_on_the_admin(portal_pilot):
    A, _ = portal_pilot("", portal=False)
    A.S["sched_read_at"] = _iso(time.time() - 30 * 3600)
    assert A.schedule_unread_tick(time.time() + 86400) is None and not A.DB.get(A.SCHED_UNREAD_DONE)


# ---------------------------------------------------------------- the pilot/set shape
def test_pilot_set_samples_through_the_watchers_own_check(portal_pilot, caplog):
    W, _ = portal_pilot("pilot2")
    seen = []
    W.pub_pilot = lambda d: seen.append(d)
    acc = [s for s in FIX["samples"]["commands"]["accepted"] if s["cmd"]["sub"] == "pilot/set"]
    ref = [s for s in FIX["samples"]["commands"]["refused"] if s["cmd"]["sub"] == "pilot/set"]
    assert len(acc) >= 7 and len(ref) >= 20
    for s in ref:
        with caplog.at_level(logging.INFO, logger="flight_watcher"):
            W.on_message(None, None, Msg("flight_watcher_pilot2/pilot/set", s["cmd"]["payload"]))
    assert caplog.text.count("pilot lookup refused") == len(ref) and not seen and not W.S.get("pilot_req")
    for word in ("Doe", "Jane", "12345678", "example.invalid", "enaJ"):  # the log never carries the text
        assert word not in caplog.text, word
    W.on_message(None, None, Msg("flight_watcher_pilot2/pilot/set", json.dumps({"q": "10001"})))
    assert W.S["pilot_req"]["emp"] == "10001"
    assert PT.check_shape("pilot/set", json.dumps({"emp": "10001", "name": "Doe, Jane"}))


def test_the_admins_lookup_has_the_same_shape(portal_pilot, caplog):
    A, _ = portal_pilot("", portal=False)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        A.on_message(None, None, Msg("flight_watcher/pilot/set", json.dumps({"q": "x" * 61})))
    assert "pilot lookup refused: pilot/set: q is not text of 1 to 60 characters" in caplog.text


# ---------------------------------------------------------------- recall/set off the portal
def test_recall_set_is_refused_from_the_portal_but_the_admins_forward_still_comes(portal_pilot, tmp_path):
    W, _ = portal_pilot("pilot2")
    assert W.portal_start(threads=False)
    assert "recall/set" not in roles.PORTAL_CMDS and "recall/set" in roles.PORTAL_REFUSED
    assert "recall/set" not in W.portal_mqtt_subs()
    sp = PT.Spool("demo", now=lambda: 1763600000.5)
    s = next(x for x in FIX["samples"]["commands"]["refused"] if x["cmd"]["sub"] == "recall/set")
    p = tmp_path / s["name"]
    p.write_text(json.dumps(s["cmd"]))
    with pytest.raises(PT.PortalError, match="sub not allowed: recall/set"):
        sp.take(str(p))
    # the pilot's Watcher still takes the list the admin's Watcher forwards on MQTT (1.7.1, F#75)
    assert ("recall/set", 0) in roles.subscriptions("pilot2", portal=True)
    W.on_message(None, None, Msg("flight_watcher_pilot2/recall/set", json.dumps({"date": "2026-11-03", "rows": []})))
    assert "2026-11-03" in (W.DB.get("recall_days") or {})


def test_the_manifest_names_its_revision(portal_pilot):
    W, _ = portal_pilot("pilot2")
    assert W.portal_start(threads=False)
    W.portal_export_once(full=True)
    key = PT.load_key(W.PORTAL_KEY_FILE, create=False)
    env = json.load(open(os.path.join(W.PORTAL_DIR, "out", "manifest.json"), encoding="utf-8"))
    m = json.loads(PT.verify(PT.public_id(key), env, "manifest", "pilot2"))
    assert m["contract"] == 1 and m["revision"] == 3 and "upload/pdf" in m["mqtt_subs"]


def test_the_new_pairing_sample_says_the_fit_alone():
    ev = json.loads(FIX["samples"]["envelopes"][2]["envelope"]["payload"])["events"][0]
    assert ev["kind"] == "new_pairing" and "Fit Fits" not in ev["body"] and ". Fits. FAR 117 OK" in ev["body"]


# ---------------------------------------------------------------- the CrewTrac refusal block, HMAC-keyed
USER, BAD = "10001", "pw-synthetic-wrong"


@pytest.fixture
def admin(portal_pilot):
    def load():
        A, _ = portal_pilot("", portal=False)
        A.OPTS["ctweb_username"], A.OPTS["ctweb_password"] = USER, BAD
        return A
    return load


def test_the_block_key_is_a_private_random_32_bytes_and_never_a_bare_sha256(admin, caplog):
    A = admin()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        ct = A.crewtrac_state()
    st = os.stat(A.CT_KEY_FILE)
    key = open(A.CT_KEY_FILE, "rb").read()
    assert len(key) == 32 and stat.S_IMODE(st.st_mode) == 0o600
    assert ct["creds"] == CH.creds_hash(USER, BAD, key) != CH.legacy_hash(USER, BAD)
    assert key.hex() not in caplog.text and BAD not in caplog.text
    # the key never leaves the data folder: no out/ file, no MQTT message carries it
    assert all(key.hex() not in str(p) for _, p, *_ in A.MQ.raw.msgs)
    A2 = admin()  # a restart: the same key, the same record
    assert A2.crewtrac_hash(USER, BAD) == ct["creds"]


def test_the_1_7_1_records_are_rekeyed_once(admin):
    A = admin()
    old = CH.legacy_hash(USER, BAD)
    A.DB.put("crewtrac", {"state": "refused", "creds": old, "block": old, "at": "2026-11-10T08:05:00-10:00"})
    A.DB.put("crewtrac_refused", {old: "2026-11-10T08:05:00-10:00", "f" * 64: "2026-10-01T00:00:00-10:00"})
    assert not os.path.exists(A.CT_KEY_FILE) and A.DB.get(A.CT_HMAC_V) is None
    ct = A.crewtrac_state()
    h = A.crewtrac_hash(USER, BAD)
    assert ct["block"] == h == ct["creds"] and A.crewtrac_stopped(ct)  # still blocked: the same details
    assert A.DB.get("crewtrac_refused") == {h: "2026-11-10T08:05:00-10:00"}  # a bare sha256 is never kept
    assert A.DB.get(A.CT_HMAC_V) == 1 and not A.DB.get(A.CT_KEY_LOST)


def test_a_lost_key_with_a_refusal_on_record_blocks_until_a_new_save(admin):
    A = admin()
    A.crewtrac_state()
    ct = A.DB.get("crewtrac")
    A.crewtrac_failed(dict(ct), CH.REFUSED)
    assert A.crewtrac_stopped(A.DB.get("crewtrac"))
    os.unlink(A.CT_KEY_FILE)  # a restored or wiped data folder
    A2 = admin()
    A2.OPTS["ctweb_password"] = BAD + "2"  # even other details: the old record cannot be matched any more
    ct2 = A2.crewtrac_state()
    assert A2.DB.get(A2.CT_KEY_LOST) and A2.crewtrac_stopped(ct2) and A2.charter_wait() is None
    assert "Save your CrewTrac details again in Settings" in A2.DB.get("charter_status")
    assert A2.DB.get("crewtrac_refused") == {}
    # the next save in Settings lifts it
    A2.load_opts = lambda: dict(A2.OPTS)
    assert A2.crewtrac_resaved() is True
    assert not A2.DB.get(A2.CT_KEY_LOST) and not A2.crewtrac_stopped(A2.crewtrac_state())


def test_a_lost_key_with_no_refusal_on_record_blocks_nothing(admin):
    A = admin()
    A.crewtrac_state()
    os.unlink(A.CT_KEY_FILE)
    A2 = admin()
    assert not A2.crewtrac_stopped(A2.crewtrac_state()) and not A2.DB.get(A2.CT_KEY_LOST)

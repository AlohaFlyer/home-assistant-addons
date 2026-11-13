"""1.7.3: a pilot's log lines mask a crew name in every form the Watcher logs it (after a quote, as the detail probe's
%r writes it; 'Last, First'; a surname of two words; 'First Last') and its employee number in parentheses (3 to 7
digits); times, dates, pairing ids, flight numbers, years and credit values stay. The detail probe on a pilot logs only
whether a captain was parsed. The admin's log is as before. Synthetic names only ("Doe, Jane")."""
import json
import logging
import sys

import pytest

import captures as CAPS
import inflt as IF


@pytest.mark.parametrize("text,leaks", [
    ("Doe, Jane (1234)", ("Doe", "Jane", "1234")),
    ("Doe Jr, Jane (14157)", ("Doe", "Jr", "Jane", "14157")),
    ("captain='Doe, Jane (6598)'", ("Doe", "Jane", "6598")),
    ("captain='Doe Jr, Jane (14157)'", ("Doe", "Jr", "Jane", "14157")),
    ('captain="Doe, Jane (6598)"', ("Doe", "Jane", "6598")),
    ("captain='Jane Doe (6598)'", ("Doe", "Jane", "6598")),
    ("captain='DOE, JANE (123)'", ("DOE", "JANE", "123")),
    ("Jane Doe (6598)", ("Doe", "Jane", "6598")),
    ("captain='Day, Pat (6598)'", ("Day", "Pat", "6598")),  # a surname that is also a page word
])
def test_a_crew_name_and_its_number_are_masked(text, leaks):
    out = CAPS.mask(text, [])
    for leak in leaks:
        assert leak not in out, (text, out, leak)


def test_the_live_detail_probe_line_is_masked():
    line = "detail probe H3607: captain='Doe, Jane (6598)' blk=17:35 credit=17:35 soft=0:00"
    assert CAPS.mask(line, []) == "detail probe H3607: captain='xxx, xxxx (####)' blk=17:35 credit=17:35 soft=0:00"
    line2 = "detail probe H3631B: captain='Doe Jr, Jane (14157)' blk=17:35 credit=17:35 soft=0:00"
    assert CAPS.mask(line2, []) == ("detail probe H3631B: captain='xxx xx, xxxx (#####)' blk=17:35 credit=17:35 "
                                    "soft=0:00")


@pytest.mark.parametrize("line", [
    "detail probe H3607: captain='' blk=17:35 credit=17:35 soft=0:00",
    "pairing H3607 H3631B on 2026-11-13 (11/13/26, 13NOV) blk 17:35 credit 17:35 soft 0:00 pay 5:30 (2026)",
    "flight HA 51 dep 09:05 arr 17:35 TAFB 72:15 credit 10.5 month 2026-11 year 2026 (Nov 13, 2026)",
    "crew index run done: 12 pages (ok), 3 trips (123 rows) in 1.5 s",
])
def test_times_dates_pairings_flights_and_credits_stay(line):
    assert CAPS.mask(line, []) == line


@pytest.fixture
def load(tmp_path, monkeypatch):
    def _load(instance="pilot2"):
        data = tmp_path / ("data_" + (instance or "admin"))
        data.mkdir(exist_ok=True)
        (data / "options.json").write_text(json.dumps({"username": "doej2", "password": "pw-synthetic",
                                                       "log_level": "info", "category_check": "HNL 332 FO"}))
        if instance:
            (data / "creds.json").write_text(json.dumps({"username": "doej2", "password": "pw-synthetic"}))
        monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
        for k in ("FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL"):
            monkeypatch.delenv(k, raising=False)
        if instance:
            monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
            monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
        else:
            monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
            monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
        sys.modules.pop("watcher", None)
        import watcher as W
        monkeypatch.setattr(W.CAP, "root", str(tmp_path / "share"))
        monkeypatch.setattr(W, "DETAIL_PROBE", {"done": False})

        def enrich(fl, row):
            row.update(captain="Doe, Jane (6598)", blk="17:35", credit="17:35", soft="0:00")
        monkeypatch.setattr(W, "enrich", enrich)
        W.S.clear()
        return W
    yield _load
    sys.modules.pop("watcher", None)
    IF.WRITE = None


POT = {"H3607:13NOV": {"pairing": "H3607", "date": "2026-11-13"}}


def test_a_pilots_detail_probe_names_no_captain(load, caplog):
    W = load("pilot2")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.detail_probe(None, POT)
        W.log.info("detail probe %s: captain=%r blk=%s", "H3607", "Doe Jr, Jane (14157)", "17:35")  # the mask too
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in ("Doe", "Jane", "Jr", "6598", "14157"):
        assert leak not in text, (leak, text)
    assert "detail probe H3607: captain=parsed blk=17:35 credit=17:35 soft=0:00" in text


def test_the_admins_detail_probe_is_as_before(load, caplog):
    W = load("")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.detail_probe(None, POT)
    assert "detail probe H3607: captain='Doe, Jane (6598)' blk=17:35 credit=17:35 soft=0:00" in caplog.text

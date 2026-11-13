"""1.7.3: a pilot's log lines mask a crew name in every form the Watcher logs it (after a quote, as the detail probe's
%r writes it; 'Last, First'; a surname of two words; 'First Last') and its employee number in parentheses (3 to 7
digits); times, dates, pairing ids, flight numbers, years and credit values stay. The detail probe on a pilot logs only
whether a captain was parsed. The admin's log is as before. Synthetic names only ("Doe, Jane")."""
import json
import logging
import sys
import time

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


def test_mask_takes_linear_time_on_a_long_run_of_capitalized_words():
    """1.7.3 review: a long run of capitalized words with no '(digits)' after it (a page's text node) costs linear
    time, not quadratic (NAME_EMP_RE's run is bounded)."""
    for text in ("Doe Jane " * 4000, "Doe, Jane " * 4000, "CA Day Jr, Pat " * 3000):
        t = time.perf_counter()
        CAPS.mask(text, [])
        assert time.perf_counter() - t < 2.0, text[:20]


@pytest.mark.parametrize("text,want", [
    # 1.7.3 review: a surname (or first or middle name) that is also a page word is masked in a 'Last, First' name;
    # a seat code first stays
    ("captain='Day Jr, Pat (6598)'", "captain='xxx xx, xxx (####)'"),
    ("pickup H3607:13NOV: FO Doe, Jane (6598) (CA Block Jr, Pat (10007))",
     "pickup H3607:13NOV: FO xxx, xxxx (####) (CA xxxxx xx, xxx (#####))"),
    ("captain='Day, Pat'", "captain='xxx, xxx'"),
    ("pickup H3607:13NOV: FO Day, Pat (CA ?)", "pickup H3607:13NOV: FO xxx, xxx (CA ?)"),
    ("captain='Doe, Jane May (6598)'", "captain='xxx, xxxx xxx (####)'"),
    ("picker FO Day, Pat (10003); RO Block, Jan: 12 in open time",
     "picker FO xxx, xxx (#####); RO xxxxx, xxx: 12 in open time"),
    ("captain='Day, May (6598)'", "captain='xxx, xxx (####)'"),  # page words only, but a comma and a number
    ("CA De La Cruz Jr, Maria Ann (6598)", "CA xx xx xxxx xx, xxxxx xxx (####)"),
    ("CA DOE, JANE FO OPEN", "CA xxx, xxxx FO OPEN"),
    # 1.7.3 review: letters outside ASCII (Latin-1, Latin Extended, the okina) are name letters too
    ("captain='Pe\u00f1a, Jos\u00e9 (6598)'", "captain='xxxx, xxxx (####)'"),
    ("captain='Ka\u02bbaihue, Keoni (6598)'", "captain='xxxxxxxx, xxxxx (####)'"),
    ("pickup H3607:13NOV: FO \u014cta, K\u0113hau (CA ?)", "pickup H3607:13NOV: FO xxx, xxxxx (CA ?)"),
    ("Jos\u00e9 Pe\u00f1a (6598)", "xxxx xxxx (####)"),
])
def test_page_word_and_non_ascii_names_are_masked(text, want):
    assert CAPS.mask(text, []) == want


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


def test_a_pilots_pickup_lines_name_no_crew(load, caplog):
    """1.7.3 review: the pilot's pickup and picker lines ('Last, First' with page-word surnames, a name outside
    ASCII) are masked by PilotLogMask."""
    W = load("pilot2")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.log.info("pickup %s: %s (CA %s)", "H3607:13NOV", "FO Day, Pat (6598)", "Block Jr, Pat (10007)")
        W.log.info("picker %s: %s in open time", "FO Pe\u00f1a, Jos\u00e9 (6598)", 12)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in ("Day", "Pat", "Block", "Jr", "6598", "10007", "Pe\u00f1a", "Jos\u00e9", "\u00f1", "\u00e9"):
        assert leak not in text, (leak, text)
    assert "pickup H3607:13NOV: FO xxx, xxx (####) (CA xxxxx xx, xxx (#####))" in text
    assert "picker FO xxxx, xxxx (####): 12 in open time" in text

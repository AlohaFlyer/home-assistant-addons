from datetime import date

import pytest

from pot import bcid, classify, header_fingerprint, hhmm, hours, is_pot_page, parse_pot, pot_links, row_date


@pytest.mark.parametrize("name,kind", [
    ("mobile_pot_rows.html", "ok"),       # captcha only in <script>: not a block
    ("mobile_pot_empty.html", "ok"),
    ("mainmenu.html", "ok"),
    ("killed.html", "killed"),
    ("expired.html", "expired"),
    ("blocked.html", "blocked"),
])
def test_classify(fx, name, kind):
    assert classify(fx(name)) == kind


def test_is_pot_page(fx):
    assert is_pot_page(fx("mobile_pot_rows.html"))
    assert is_pot_page(fx("mobile_pot_empty.html"))
    assert not is_pot_page(fx("killed.html"))


def test_parse_rows_mobile_columns(fx):
    pot = parse_pot(fx("mobile_pot_rows.html"))
    assert set(pot) == {"H3644|01Nov", "H3601|26Nov", "H3649|26Nov"}
    r = pot["H3644|01Nov"]
    # v0.1.9 put LAX in report and 2 in layover; these are the corrected fields the push uses
    assert (r["dates"], r["days"], r["layover"], r["report"], r["credit"], r["blk"]) == \
        ("01Nov-02Nov", "2", "LAX", "11.27", "11:04", "08:10")


def test_parse_empty(fx):
    assert parse_pot(fx("mobile_pot_empty.html")) == {}


def test_baseline_keys_unchanged_from_v01(fx):
    # v0.1.x key was pairing|cells[1]; keeping it means the stored baseline carries over, no false alerts
    assert "H3649|26Nov" in parse_pot(fx("mobile_pot_rows.html"))


def test_fingerprint_stable_and_detects_layout_change(fx):
    a = header_fingerprint(fx("mobile_pot_rows.html"))
    assert a and a == header_fingerprint(fx("mobile_pot_rows_sin.html"))
    assert a == header_fingerprint(fx("mobile_pot_header_time_changed.html"))
    assert a != header_fingerprint(fx("mobile_pot_new_layout.html"))
    assert header_fingerprint(fx("mobile_pot_empty.html")) is None


def test_next_month_links(fx):
    url = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
    links = pot_links(fx("mobile_pot_rows.html"), url)
    assert [bcid(l["url"]) for l in links] == ["003.152", "003.153"]
    assert links[1]["url"].startswith("https://ha2.flica.net/full/mobileopentimepot.cgi")


def test_helpers():
    t = date(2026, 10, 31)
    assert row_date("01Nov", t) == date(2026, 11, 1)
    assert row_date("05Jan", t) == date(2027, 1, 5)
    assert row_date("20Oct", t) == date(2026, 10, 20)
    assert row_date("xx", t) is None
    assert round(hours("11:04"), 3) == 11.067 and hours("") is None
    assert hhmm("11.27") == "11:27" and hhmm("0945") == "09:45" and hhmm("-none-") is None


def test_next_bid_period_only():
    from pot import bcid_after
    assert bcid_after("003.153", "003.152") and not bcid_after("003.151", "003.152")
    assert bcid_after("003.160", "003.152") and not bcid_after("003.152", "003.152")

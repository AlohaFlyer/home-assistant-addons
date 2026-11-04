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
    # Crd/Dy column is pay; 08:10/11:04 are first departure and last arrival (confirmed Nov 1, 2026)
    assert (r["dates"], r["days"], r["layover"], r["credit"], r["depart"], r["arrive"]) == \
        ("01Nov-02Nov", "2", "LAX", "11:27", "08:10", "11:04")


DETAIL = ("flica.net - mobile pairing pairing details h3619:01nov nov 1 - nov 17 check in: 12:10 dy flt "
          "dps-ars dep arr blk su 876 hnl-las 1310 2054 0544 layover hotel (702)555-0177 (1106) "
          "mo 807 las-hnl 0930 1404 0634 blk : 1218 tafb : 2609 pay : 1218 crew: ca 10007 lane jr, "
          "chris fo open")


def test_parse_detail_real_text():
    from pot import parse_detail, soft_time
    d = parse_detail(f"<p>{DETAIL}</p>")
    assert d.pop("duties")[0]["stn"] == "LAS" and d == {"captain": "Lane Jr, Chris (10007)", "report": "12:10", "blk": "12:18",
                 "credit": "12:18", "tafb": "26:09", "days": "2", "open_seats": "FO", "crew": [["CA", "Lane Jr, Chris"], ["FO", "OPEN"]],
                 "last_arr": "14:04", "route": "HNL-LAS-HNL", "turn": "LAS"}
    assert soft_time(d["credit"], d["blk"]) == "0:00"
    assert parse_detail("<p>crew: ca open fo open</p>")["captain"] == "OPEN"


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


def _nested(rows):
    head = "<tr><td>[HNL 332 FO]</td><td></td><td><a href='#'>Display Options</a></td></tr>"
    hdr = "<tr><td><b>Pair</b></td><td><b>Start</b></td><td><b>End</b></td><td><b>Crd</b>/<b>Dy</b></td><td><b>Layover</b></td><td><b>Prem</b></td></tr>"
    body = "".join(
        f"<tr><td colspan='6'><hr></td></tr><tr><td colspan='6'><table><tr><td>{p}</td><td>{s}</td><td>{e}</td>"
        f"<td>{c}</td><td>{l}</td><td></td></tr></table></td></tr>" for p, s, e, c, l in rows)
    return f"<html><body><table>{head}</table><table>{hdr}{body}</table></body></html>"


def test_fingerprint_ignores_which_pairing_is_first():
    a = header_fingerprint(_nested([("H3606", "01Nov", "03Nov", "21.00", "JFK"), ("H3619", "01Nov", "02Nov", "12.18", "LAS")]))
    b = header_fingerprint(_nested([("H3619", "01Nov", "02Nov", "12.18", "LAS")]))
    c = header_fingerprint(_nested([("H3601", "26Nov", "27Nov", "11.20", "-none-")]))
    assert a and a == b == c


def _unclosed(rows):
    """Shape of the real mobile pot (Nov 1 2026): each pairing's first <tr> is never closed,
    so html.parser nests every later row inside the first pairing row."""
    hdr = ("<tr><td><b>Pair</b></td><td><b>Start</b></td><td><b>End</b></td><td><b>Crd</b>/<b>Dy</b></td>"
           "<td><b>Layover</b></td><td><b>Prem</b></td></tr><tr><td colspan='6'><hr></td></tr>")
    body = "".join(
        f"<tr><td><a href='#'>{p}</a></td><td>{s}</td><td>{e}</td><td>{c}</td><td>{l}</td><td> </td>"
        f"<tr><td>&nbsp;</td><td>16:30</td><td>05:55</td><td>2</td><td>&nbsp;</td></tr>"
        f"<tr><td colspan='6'><hr/></td></tr>" for p, s, e, c, l in rows)
    return f"<html><body><table>{hdr}{body}</table></body></html>"


def test_fingerprint_ignores_pot_size_with_unclosed_rows():
    # Counting nested cells made the hash change with the pot and parked the watcher 9 times.
    two = _unclosed([("H3601", "26Nov", "27Nov", "11.20", "-none-"), ("H3633", "26Nov", "27Nov", "11.56", "LAX")])
    one = _unclosed([("H3633", "26Nov", "27Nov", "11.56", "LAX")])
    three = _unclosed([("H3655", "12Nov", "15Nov", "24.10", "SIN")] +
                      [("H3601", "26Nov", "27Nov", "11.20", "-none-"), ("H3633", "26Nov", "27Nov", "11.56", "LAX")])
    assert header_fingerprint(two) == header_fingerprint(one) == header_fingerprint(three) is not None


def test_layout_still_parses(fx):
    from pot import layout_still_parses
    assert layout_still_parses(_unclosed([("H3601", "26Nov", "27Nov", "11.20", "-none-")]))
    assert layout_still_parses(fx("mobile_pot_rows.html"))
    assert not layout_still_parses(fx("mobile_pot_empty.html"))
    assert not layout_still_parses(fx("killed.html"))


TURN = ("FLICA.Net - Mobile Pairing Pairing Details H3601:26NOV Nov 2 - Nov 30 Check In: 15:30 Dy Flt "
        "Dps-Ars Dep Arr Blk Th 865 HNL-PPG 1630 2115 0545 Th 866 PPG-HNL 2320 0555 0535 Blk : 1120 "
        "TAFB : 1455 Pay : 1120 Crew: CA 10001 SMITH JR, JOHN CA 10002 DOE, JANE FO Open")


def test_parse_detail_turn_station():
    from pot import parse_detail
    d = parse_detail(f"<p>{TURN}</p>")
    assert d["turn"] == "PPG" and d["route"] == "HNL-PPG-HNL" and d["last_arr"] == "05:55"
    multi = parse_detail("<p>Dy Flt Dps-Ars Th 865 HNL-PPG 1630 2115 Th 13 PPG-PPT 2320 0100 Fr 14 PPT-HNL 0300 0800</p>")
    assert multi["turn"] == "PPG/PPT" and multi["route"] == "HNL-PPG-PPT-HNL"


def test_parse_crew_and_pickup():
    from pot import parse_crew, pickup_result
    crew = parse_crew(TURN)
    assert crew == [("CA", "Smith Jr, John"), ("CA", "Doe, Jane"), ("FO", "OPEN")]
    assert pickup_result(crew, ["FO"]) == ("open", "")
    taken = parse_crew("Crew: CA 10001 SMITH JR, JOHN FO 10003 ROE, RICK RO Open")
    assert pickup_result(taken, ["FO"]) == ("filled", "FO Roe, Rick")
    assert pickup_result(taken, ["RO"]) == ("open", "")
    assert pickup_result(taken, []) == ("filled", "FO Roe, Rick")
    assert pickup_result(parse_crew("no crew here"), ["FO"]) == ("unknown", "")


def test_prem_flag():
    from store import is_prem
    assert is_prem({"x1": "X"}) and is_prem({"x1": " x "}) and not is_prem({"x1": "", "prem": ""})


def test_pickup_diff_finds_the_newcomer():
    from pot import parse_crew, pickup_diff
    # open seat shown as "FO Open" while in the pot
    before = parse_crew("Crew: CA 10001 SMITH JR, JOHN FO Open")
    after = parse_crew("Crew: CA 10001 SMITH JR, JOHN FO 10003 ROE, RICK")
    assert pickup_diff(before, after) == ("filled", "FO Roe, Rick", True)
    # open seat not listed at all while in the pot (H3631 style): RO newcomer
    before = parse_crew("Crew: CA 10001 SMITH JR, JOHN FO 10004 DOE, JANE")
    after = parse_crew("Crew: CA 10001 SMITH JR, JOHN FO 10004 DOE, JANE RO 10005 POE, PAT")
    assert pickup_diff(before, after) == ("filled", "RO Poe, Pat", True)
    # still open after leaving the pot -> suspected hidden
    assert pickup_diff(parse_crew("Crew: CA 1 A, B FO Open"), parse_crew("Crew: CA 1 A, B FO Open"))[0] == "open"
    # same crew, nobody new
    assert pickup_diff(before, before) == ("unchanged", "", True)
    # no roster from before: fall back, not known
    assert pickup_diff(None, after) == ("filled", "FO Doe, Jane; RO Poe, Pat", False)


def test_parse_alert_email():
    from pot import parse_alert_email
    text = ("Alert Notification - 3 match(es) for alert request 'Nov 13-20 Max'\r\n3 alert matched pairings "
            "'Nov 13-20 Max': H3627:18NOV from 'OPEN TIME- Add/Swap/Drop requests - November', H3627:18NOV from "
            "'Close in Opentime: &lt;16 Hrs to RPT - November', H3655:12NOV from 'Fly Me Preferencing - November'")
    got = parse_alert_email(text)
    assert [g["key"] for g in got] == ["H3627|18Nov", "H3655|12Nov"]
    assert got[0]["sources"] == ["OPEN TIME- Add/Swap/Drop requests - November",
                                 "Close in Opentime: &lt;16 Hrs to RPT - November"]
    assert parse_alert_email("test ding") == []


def test_detail_days_and_pay_id():
    from pot import parse_detail
    d = parse_detail("<p>Check In: 20:37 Dy Flt Dps-Ars Su 804 HNL-LAX 2137 0500 0523 Tu 933 LAX-OGG 0830 1222 "
                     "0552 Tu 1135 OGG-HNL 1326 1410 0044 Blk : 1115 TAFB : 4133 Pay : 1500 Pay : 1000000001</p>")
    assert d["credit"] == "15:00" and d["days"] == "3" and d["blk"] == "11:15"


def test_crew_ids_and_with_ids():
    from pot import crew_ids, with_ids, parse_detail
    txt = "Crew: CA 10001 SMITH JR, JOHN FO 10003 ROE, RICK RO Open"
    assert crew_ids(txt) == {"Smith Jr, John": "10001", "Roe, Rick": "10003"}
    assert with_ids("FO Roe, Rick; RO Poe, Pat", crew_ids(txt)) == "FO Roe, Rick (10003); RO Poe, Pat"
    assert with_ids("", {}) == ""
    d = parse_detail("<html><body>Pairing H9999:01NOV Check In: 07:00 " + txt + "</body></html>")
    assert d["captain"] == "Smith Jr, John (10001)"


def test_parse_duties_turn_and_layover():
    from pot import parse_duties
    # PPG turn (PPG is UTC-11): one duty, back next day; printed times are local
    t = "dy flt dps-ars dep arr blk th 865 hnl-ppg 1630 2115 0545 th 866 ppg-hnl 2320 0555 0535 blk : 1120"
    d = parse_duties(t)
    assert len(d) == 1 and d[0]["d"] == 0 and d[0]["dep"] == 16 * 60 + 30 and d[0]["arr"] == 1440 + 5 * 60 + 55 and d[0]["stn"] == "HNL"
    assert d[0]["blk"] == 5 * 60 + 45 + 5 * 60 + 35
    # SIN (UTC+8, 18 h ahead of HST): out Su 1130 HST, 10:50 block, lands Mo 16:20 SIN; back Tu 23:10 SIN
    t = "su 450 hnl-sin 1130 1620 1050 tu 451 sin-hnl 2310 1300 1050"
    d = parse_duties(t)
    assert len(d) == 2 and d[0]["stn"] == "SIN" and d[0]["arr"] == 1440 - 1440 + 22 * 60 + 20
    free = d[1]["dep"] - d[0]["arr"]
    assert free == (2 * 1440 + 23 * 60 + 10 - 18 * 60) - (22 * 60 + 20)  # 30 h 50 min on the layover
    assert free >= 30 * 60


def test_legs_cm_schedule_and_inflight():
    from pot import parse_legs, parse_cm_schedule, inflight_at
    txt = "check in: 11:40 dy flt dps-ars dep arr blk tu 816 hnl-san 1249 1946 0457 we 815 san-hnl 0805 1219 0614 blk : 1111"
    legs = parse_legs(txt)
    assert [(l["dep"], l["arr"], l["to"]) for l in legs] == [(769, 1066, "SAN"), (1805, 2179, "HNL")]
    sched = parse_cm_schedule("pair('H3647','20261101',0) pair('H3648','20261103',0) pair('H3647','20261101',0)")
    assert sched == [{"trip": "H3647", "start": "2026-11-01"}, {"trip": "H3648", "start": "2026-11-03"}]
    # 04:25 HST Nov 4 = layover hotel, before block-out at 06:05 HST: not in flight
    assert inflight_at(legs, "2026-11-03", "2026-11-04T14:25:00+00:00") is False
    # 07:00 HST Nov 4 = airborne SAN-HNL
    assert inflight_at(legs, "2026-11-03", "2026-11-04T17:00:00+00:00") is True
    # 22:00 HST Nov 3 = on the ground in SAN after block-in
    assert inflight_at(legs, "2026-11-03", "2026-11-04T08:00:00+00:00") is False
    assert inflight_at(legs, "bad", "2026-11-04T17:00:00+00:00") is None

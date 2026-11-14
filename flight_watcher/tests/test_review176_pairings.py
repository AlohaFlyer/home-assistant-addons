"""1.7.6 review fixes, the pairings package side (synthetic packages only: made-up pairings, flights and hotels).
- The pairing file is served at a fixed URL with no login and copied to every pilot's portal: it keeps routes and
  times, never the crew hotels or their van times (those reach the pilot's own trips through his own trip times).
- A pilot's upload is untrusted: the detail has a whole-file budget, so a crafted package cannot push the month's
  pairing file past the portal's file cap (rows and all would be skipped).
- The detail is built only from the blocks the pairing file keeps (base HNL, A330 legs), the first one per id."""
import json
import os

import pdfs
import portal as PT
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pairing_detail import package

RULE = "=" * 120


def test_public_pairing_file_has_no_hotel_or_van():
    text = package()
    j = pdfs.package_json(text, "t")
    raw = json.dumps(j)
    assert "EXAMPLE LAKE HOTEL" not in raw and "EXAMPLE BAY INN" not in raw and "EXAMPLE PIER HOTEL" not in raw
    for d in j["detail"].values():
        for du in d["duties"]:
            assert "hotel" not in du and "van" not in du
            assert du["legs"] and "stn" in du and "layo" in du  # routes and times stay
    assert j["detail"]["H9101"]["duties"][0]["layo"] == "10h18"
    # the full detail and the hotels stay available to the Watcher (DB), never to the public file
    assert pdfs.package_legs(text)["H9101"]["duties"][0]["hotel"] == "EXAMPLE LAKE HOTEL"
    assert pdfs.package_hotels(text) == {"H9101": [["SEA", "EXAMPLE LAKE HOTEL", "16:15"], ["SFO", "EXAMPLE BAY INN", ""]],
                                         "H9102": [["LAX", "EXAMPLE PIER HOTEL", "16:30"]]}


def test_uploads_keep_hotels_in_the_db_and_own_trips_carry_them(W, tmp_path, monkeypatch):  # noqa: F811
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    (up / "2026-11_pairings.txt").write_text(package())
    W.uploads_check()
    out = json.load(open(os.path.join(W.CARD_PAIRINGS, "pairings_2026-11.json")))
    assert "HOTEL" not in json.dumps(out) and "H9101" in out["detail"]
    assert W.DB.get("pkg_hotels:2026-11")["H9101"][0] == ["SEA", "EXAMPLE LAKE HOTEL", "16:15"]
    W.S["own_trips"] = {"H9101|2026-11-12": {"report": "22:00", "credit": "16:00"}, "H9999|2026-11-20": {"report": "08:00"}}
    W.publish_own_trips()
    trips = [p for t, p in W.SENT if t == "own_trips"][-1]["trips"]
    assert trips["H9101|2026-11-12"]["hotels"] == [["SEA", "EXAMPLE LAKE HOTEL", "16:15"], ["SFO", "EXAMPLE BAY INN", ""]]
    assert "hotels" not in trips["H9999|2026-11-20"]  # not in the package: as it was
    assert "hotels" not in W.S["own_trips"]["H9101|2026-11-12"]  # the stored record stays as FLICA gave it


def _crafted(n, month="December 2026", period="December 2 \u2014December 31 (30 Days)"):
    """n A332 HNL pairings at the detail caps (30 legs, 12 duties, 80-character hotel lines): a crafted upload."""
    lines = [" " * 49 + f"{month} Pairing Package", " " * 49 + period, RULE]
    for i in range(n):
        lines += [f"H{i:04d}                                  BASE REPT:     22:00L/08:00GMT", "BASE : HNL         CA01FO01RO01SO01"]
        leg = 0
        for d in range(12):
            k_n = 3 if d < 6 else 2
            for k in range(k_n):
                a, b = ("HNL", "SEA") if leg % 2 == 0 else ("SEA", "HNL")
                tail = "        5h42   5h42   6h57   10h18" if k == k_n - 1 and d < 11 else ""
                lines.append(f"{d + 1}          9{leg:03d}      {a} - {b} 23:00/09:00 06:42/14:42 5h42            5:42    1:00   332{tail}")
                leg += 1
            lines.append("D-END: 06:57L/14:57GMT")
            if d < 11:
                lines += ["X" * 80 + "   VAN 16:15", "                                         REPT: 17:15L/01:15GMT"]
        lines += ["      TOTALS BLOCK 99h00     FDP 99h00    DHD 0h00     LDGS: 30    CREDIT 99h00    T.A.F.B. 99h00", RULE]
    return "\n".join(lines) + "\n"


def test_crafted_package_stays_under_the_portal_file_cap(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    pj = pdfs.package_json(_crafted(2000), "t")
    assert len(pj["rows"]) == 2000  # every row stays, as in 1.7.5
    assert pj["dcut"] == 2000 - len(pj["detail"]) > 0 and len(pj["detail"]) <= pdfs.DETAIL_MAX_PAIRINGS
    W._write_pairings(os.path.join(W.CARD_PAIRINGS, "pairings_2026-12.json"), pj)
    size = os.path.getsize(os.path.join(W.CARD_PAIRINGS, "pairings_2026-12.json"))
    assert size < pdfs.DETAIL_FILE_MAX + 600_000 < PT.CAPS["file"]
    W.local_now = lambda: __import__("datetime").datetime(2026, 11, 14, 12, 0)
    W.portal_export_once(full=True)
    assert "pairings_2026-12.json" in os.listdir(os.path.join(W.PORTAL_DIR, "out", "files"))


def test_an_ordinary_package_keeps_all_its_detail():
    pj = pdfs.package_json(_crafted(150), "t")
    assert len(pj["detail"]) == 150 and "dcut" not in pj


def test_another_fleets_block_with_the_same_id_never_replaces_the_a330_detail():
    text = package().replace("H9103                                  BASE REPT:", "H9101                                  BASE REPT:")
    j = pdfs.package_json(text, "t")
    d = j["detail"]["H9101"]
    assert d["eq"] == "332"
    assert [(leg[3], leg[4]) for du in d["duties"] for leg in du["legs"]] == [
        ("HNL", "SEA"), ("SEA", "LAX"), ("LAX", "SFO"), ("SFO", "HNL")]
    assert pdfs.package_legs(text)["H9101"]["eq"] == "332"
    # a second A330 block with the same id (H9102 renamed): the first one wins
    twice = package().replace("H9102                                  BASE REPT:", "H9101                                  BASE REPT:")
    assert pdfs.package_legs(twice)["H9101"]["duties"][0]["stn"] == "SEA"
    assert pdfs.package_json(twice, "t")["detail"]["H9101"]["duties"][0]["stn"] == "SEA"

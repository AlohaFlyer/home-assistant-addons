"""1.7.8 (pilot database, spec 8.1; Ryan, Nov 14: "the seniority PDF wins on Sen#, DOH, status"): seniority.to_json
keeps each pilot's mandatory retirement month (the older list's DOR column, Mon-yy, as `retire` YYYY-MM; a yy below 70
reads as 20yy, 14 CFR 121.383(d)) and the union list's Remarks status code (`status`, only a code in the STATUS LEGEND),
so the pilot database reads both from seniority.json. seniority.PARSER 4, so the list on file is read again once.
seniority.json stays mode 600. Made-up pilots only."""
import seniority as SEN
from test_seniority_hal import hal_text


def test_parser_4():
    assert SEN.PARSER == 4


def test_retire_from_dor(fx):
    d = SEN.to_json(SEN.parse(fx("seniority_synthetic.txt"), 2026), "s.pdf", "2026-11-06T09:00:00-10:00")
    jane = d["pilots"]["901"]
    assert jane["retire"] == "2028-05" and "status" not in jane  # 'May-28'; the older list has no status column
    assert d["pilots"]["9002"]["retire"] == "2029-06"
    assert all(len(v["retire"]) == 7 for v in d["pilots"].values() if "retire" in v)


def test_dor_century():
    assert SEN.dor_month("May-28") == "2028-05" and SEN.dor_month("Jan-69") == "2069-01"
    assert SEN.dor_month("Jan-70") == "1970-01" and SEN.dor_month("Foo-28") == "" and SEN.dor_month("") == ""


def test_status_kept_per_pilot_only_from_the_legend():
    d = SEN.to_json(SEN.parse(hal_text()), "seniority_2026-11-14.pdf", "2026-11-14T09:00:00-10:00")
    codes = {v.get("status") for v in d["pilots"].values()}
    assert codes <= SEN.HAL_STATUS and "A" in codes
    assert all("retire" not in v for v in d["pilots"].values())  # the union list prints no DOR
    assert sum(d["statuses"].values()) == sum(1 for v in d["pilots"].values() if v.get("status"))
    p = SEN.parse(hal_text())
    p["rows"][0]["status"] = "ZZZ"  # a code the legend does not have: counted, not kept on the pilot
    d = SEN.to_json(p, "s.pdf", "2026-11-14T09:00:00-10:00")
    assert d["statuses"].get("ZZZ") == 1 and all(v.get("status") != "ZZZ" for v in d["pilots"].values())

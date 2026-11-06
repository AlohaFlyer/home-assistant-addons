from datetime import datetime

import submit as S


def test_swap_form_matches_mapped_page():
    f = S.swap_form("003.152", "H3629", "2026-11-14", "H3633", "2026-11-26")
    assert f["DropList"] == "H3629:20261114"
    assert f["AddList"] == "H3633:20261126-F"
    assert f["BCID"] == "003.152" and f["Priority"] == "1" and f["SubmitBid"] == "1"
    assert f["QuickSwap"] == "0" and f["Convert"] == "0" and f["SplitDetail"] == "Split"
    assert set(f) == {"BCID", "Priority", "DropList", "AddList", "SubmitBid", "CanSplitList", "SplitDetail",
                      "SecCanSplitList", "SecSplitDetail", "AOT", "LimoData", "QuickSwap", "Convert", "ABI", "Submit"}


def test_compose_pot_and_close_in():
    idea = {"for": "H3629|2026-11-14", "pairing": "H3633", "start": "2026-11-26"}
    r = S.compose(idea, "003.152", hours_to_report=40)
    assert r["folder"] == "pot" and r["form"]["AddList"].endswith("-F") and not r["sendable"]
    r = S.compose(idea, "003.152", hours_to_report=5)
    assert r["folder"] == "close-in" and r["form"] is None and "close-in" in r["why"]
    r = S.compose(idea, "003.152", hours_to_report=5, close_in_bcid="008.024", seat="R")
    assert r["form"]["BCID"] == "008.024" and r["form"]["AddList"] == "H3633:20261126-R"
    assert S.WRITES_IMPLEMENTED is False


def test_safe_get_blocks_delete_links():
    assert not S.safe_get("/full/mobileotrequest.cgi?TimeStamp=01DD6BD9:D81E615B&Type=Swap&status=Denied&QuickDelete=1")
    assert S.safe_get("/full/mobileotrequest.cgi?ShowRequest=1&TimeStamp=01DD6BD9:D81E615B")
    assert S.safe_get("/full/mobileotrequest.cgi?BCID=003.152&From=MainMenu")


def test_parse_requests():
    txt = "Date Time Request Status 10/31 11:17 Swap Approved 10/31 11:17 Swap Denied 11/01 05:53 Add Approved"
    rows = S.parse_requests(txt)
    assert [r["status"] for r in rows] == ["Approved", "Denied", "Approved"]
    assert rows[0] == {"date": "10/31", "time": "11:17", "type": "Swap", "status": "Approved"}


def test_hours_until():
    now = datetime(2026, 11, 3, 20, 0)
    assert S.hours_until("2026-11-04T08:00", now) == 12
    assert S.folder_for(S.hours_until("2026-11-04T08:00", now)) == "close-in"
    assert S.hours_until("bad", now) is None and S.folder_for(None) == "pot"


def test_compose_drop_is_a_draft():
    r = S.compose_drop("H3629|2026-11-14", "003.152", hours_to_report=200)
    assert r["form"]["DropList"] == "H3629:20261114" and r["form"]["AddList"] == "" and not r["sendable"]
    assert "not mapped" in r["why"]
    r = S.compose_drop("H3629|2026-11-14", "003.152", hours_to_report=3)
    assert r["folder"] == "close-in" and r["form"] is None


def test_test_is_the_only_mode_and_drafts_are_labelled():
    """FW-0028: FLICA stays read-only for good; Confirm and Live are gone and every request is a draft."""
    assert S.MODES == ("Test",) and S.DEFAULT_MODE == "Test" and S.WRITES_IMPLEMENTED is False
    assert not hasattr(S, "LIVE_PER_DAY")
    idea = {"for": "H3629|2026-11-14", "pairing": "H3633", "start": "2026-11-26"}
    for r in (S.compose(idea, "003.152", hours_to_report=40), S.compose(idea, None, hours_to_report=40),
              S.compose_drop("H3629|2026-11-14", "003.152", hours_to_report=200), S.compose_drop("H3629|2026-11-14", None)):
        assert r["draft"] == "draft only, never sent" and r["why"].startswith("draft only, never sent")
        assert r["sendable"] is False

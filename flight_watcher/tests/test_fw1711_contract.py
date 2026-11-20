"""1.7.11, contract 1 revision 6 (Ryan's yes of Nov 17, 2026, FW-0076: "This month and next month buttons on the pilot
lookup, on both instances. Needs portal contract revision 6, so a HOM 1.9.2 release goes first."): pilot/set takes an
optional key, month (YYYY-MM, roles.MONTH_PATTERN). The command is revision 1's; the KEY is revision 6's
(commands.key_since_revision, the way revision 5 marked a value in commands.value_since_revision), so HOM 1.9.2 takes a
pilot/set with month only for a Watcher whose manifest names revision 6, and HOM 1.9.1's pinned shape refuses the key.
The Watcher takes only this HST month or the next (its own rule, not the shape). FW-0078's pick list (emp and base on
each entry of the pilot sensor) passes the portal masks as they are: no mask changed. Synthetic data only."""
import json

import pytest

import portal as PT
import roles


def _fx():
    return PT.contract()


def test_revision_6_marks_the_month_key_of_pilot_set():
    assert roles.CONTRACT == 1 and roles.CONTRACT_REVISION == 6
    assert roles.KEY_SINCE == {"pilot/set": {"month": 6}}
    assert "pilot/set" not in roles.COMMAND_SINCE  # the command itself is revision 1's
    assert roles.VALUE_SINCE == {"upload/pdf": {"kind": {"contacts": 5}}}  # revision 5's value, unchanged
    sh = roles.SHAPE_CMDS["pilot/set"]
    assert sh["keys"] == ["emp", "q", "name", "pick", "month"] and sh["required"] == []
    assert sh["any_of"] == ["emp", "q", "pick"]  # a month alone names no pilot
    assert sh["fields"]["month"] == {"type": "text", "min": 7, "max": 7, "pattern": r"^[0-9]{4}-(0[1-9]|1[0-2])$"}
    # every other shape, the allowlists and every limit are as in revision 5
    assert set(roles.SHAPE_CMDS) == {"pilot/set", "upload/pdf", "pilotdb/note", "pilotdb/edit"}
    assert "month" in roles.SHAPE_CMDS["upload/pdf"]["keys"]  # its own month, revision 3's
    assert roles.PORTAL_CMDS.count("pilot/set") == 1 and "pilot/set" not in roles.PORTAL_REFUSED


def test_the_fixture_says_revision_6_and_what_hom_checks():
    fx = _fx()
    cm = fx["commands"]
    assert fx["revision"] == 6
    assert cm["key_since_revision"] == {"pilot/set": {"month": 6}}
    assert cm["value_since_revision"] == {"upload/pdf": {"kind": {"contacts": 5}}}
    assert cm["shapes"]["pilot/set"] == json.loads(json.dumps(roles.SHAPE_CMDS["pilot/set"]))
    r6 = fx["revisions"]["6"]
    assert r6.startswith("Flight Watcher 1.7.11, HOM 1.9.2")
    for w in ("month", "key_since_revision", "HOM 1.9.1", "month is not allowed", "this HST month or the next",
              "emp", "base", "masks"):
        assert w in r6, w
    assert set(fx["revisions"]) == {"1", "2", "3", "4", "5", "6"} and fx["revisions"]["5"].startswith(
        "Flight Watcher 1.7.10, HOM 1.9.1")
    man = json.loads(next(e["envelope"] for e in fx["samples"]["envelopes"] if e["file"] == "manifest.json")["payload"])
    assert man["revision"] == 6 and "pilot/set" in man["mqtt_subs"]
    # no mask changed (FW-0078's emp and base pass them)
    assert fx["masks"]["zero"] == ["file_key", "versions_file_key"] and fx["masks"]["drop"] == ["contact"]


def test_the_month_samples_go_through_the_shape_on_both_sides():
    fx = _fx()
    acc = [s for s in fx["samples"]["commands"]["accepted"] if s["cmd"]["sub"] == "pilot/set"]
    ref = [s for s in fx["samples"]["commands"]["refused"] if s["cmd"]["sub"] == "pilot/set"]
    months = [json.loads(s["cmd"]["payload"]).get("month") for s in acc]
    assert {"2026-11", "2026-12"} <= set(months)
    # the shape takes any well formed month; the Watcher's own rule (this HST month or the next) refuses the rest
    assert "2030-01" in months
    for s in acc:
        assert isinstance(PT.check_shape("pilot/set", s["cmd"]["payload"]), dict), s
    whys = {s["why"] for s in ref}
    for w in ("pilot/set month alone", "pilot/set month 13", "pilot/set month without its zero",
              "pilot/set month in words", "pilot/set month a number", "pilot/set month null",
              "pilot/set month with a trailing newline", "pilot/set month with a day"):
        assert w in whys, w
    for s in ref:
        with pytest.raises(PT.PortalError):
            PT.check_shape("pilot/set", s["cmd"]["payload"])
    # the pick list's number is never a pick
    assert "pilot/set pick an employee number" in whys


def test_the_contract_doc_names_revision_6():
    import os
    doc = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PORTAL_CONTRACT.md"),
               encoding="utf-8").read()
    assert "| contract 1 rev 6 (`fwp` 1) | 1.7.11 | 1.9.2, live FIRST |" in doc
    for w in ("revision 6", "key_since_revision", "With HOM 1.9.1 still live", "month is not allowed",
              "this HST month or the next", "Revision 6's rollout", "the month choice needs a portal update"):
        assert w in doc, w
    assert chr(0x2014) not in doc

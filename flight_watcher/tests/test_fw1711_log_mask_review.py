"""1.7.11 review: the log masks catch again every form 1.7.10 masked, and the sweep reads every fixed log text.

Each case below was masked by 1.7.10 (or is the same leak in a nearby form) and passed the first 1.7.11 build:
- L1: a phone's last group after a 6 or 7 digit number, when a date follows (PHONE_RE's 20-character window);
- L2, F4: a dotted country or area code ('+44.207 946 0958', 'Nov 17.808 555 0101', '+49 30.123 4567') read as a
  schedule version;
- L3: a 3 or 4 digit employee number beside a name, after 'pilot', or after a quoted 'emp' key, next to a date;
- L4: an employee number joined to a date by '. ', ' - ' or ' -';
- L5: a name before a number followed by '#' ('DOE JANE 10001#12');
- L7: a phone after ' -' that follows a month;
- L8, F2: a phone with more digits glued on through '(' or ')' before a trailing dot or hyphen;
- F1: the words of an employee number's label ('employee number #####') read as a crew name;
- F3: texts sent through portal_once, the gate's _say and a helper that returns the text, never swept;
- F6: a long count before a full stop ('size 10485760.') read as a phone.
Synthetic names and numbers only ("Doe, Jane", 10001, 6593, 808-555-01xx, +44 20 7946 0958)."""
import re

import pytest

import captures as CAPS
from test_fw1711_log_mask_text import Module, modules, opaque_calls, sweep, OPAQUE


def pilot(t):
    """A pilot's line quoted through page_log, then his log filter (PilotLogMask): mask twice."""
    return CAPS.mask(CAPS.mask(t, ()), ())


def admin_page(t):
    """The admin's page text through page_log (mask_crew page=True), then his log filter (AdminLogMask)."""
    return CAPS.mask_crew(CAPS.mask_crew(t, page=True))


BOTH = (("pilot", pilot), ("admin page", admin_page))


# --------------------------------------------------------------------------------------------- L1: the window's tail
@pytest.mark.parametrize("line", [
    "Doe, Jane 123456 (808) 555 0101 2026-11-17", "123456 - 808 555 0101 2026-11-17",
    "Doe, Jane 10001  (808) 555 0101 2026-11-17", "1234567 (808) 555 0101 2026-11-17",
    "123456 (808) 555 0101", "Doe, Jane 123456 (808) 555 0101 12.002",
])
def test_l1_a_phones_last_group_is_masked_when_the_window_split_it(line):
    for who, fn in BOTH:
        out = fn(line)
        assert not re.search(r"808|555|0101", out), (who, line, out)
        for keep in ("2026-11-17", "12.002"):
            assert (keep in out) == (keep in line), (who, line, out)
    assert CAPS._phones("123456 (808) 555 0101 2026-11-17") == "###### (###) ### #### 2026-11-17"


# ------------------------------------------------------------------------- L2, F4: a dotted country or area code
@pytest.mark.parametrize("line", [
    "+44.207 946 0958", "contact +1.808 555 0101", "Nov 17.808 555 0101", "call 1.808 555 0101", "12.808 555 0101",
    "tel +44.207 946 0958 ok", "+49 30.123 4567", "tel +43 1.234 5678", "808 12.345 0101", "+44 20.794 6095",
    "call +49 30.123 4567 now", "+33 1.234 56789", "call 808 12.345 0101.",
])
def test_l2_f4_a_dotted_group_of_a_phone_is_no_schedule_version(line):
    for who, fn in BOTH:
        out = fn(line)
        assert not re.search(r"\d", out), (who, line, out)
    assert CAPS.NOT_PHONE_RE.search("+44.207 946 0958") is None
    assert CAPS.NOT_PHONE_RE.search("+1.808 555 0101") is None


@pytest.mark.parametrize("line", [
    "schedule version 12.002 (2026-11)", "versions 12.002 12.003 12.004", "schedule version 12.002 (10001)",
    "pilot lookup: schedule version 11.003, 11.004 (2026-11, from the FLICA schedule)", "+3 12.002",
])
def test_l2_f4_a_schedule_version_with_no_phone_around_it_stays(line):
    for who, fn in BOTH:
        out = fn(line)
        for v in re.findall(r"\d{1,2}\.\d{3}", line):
            assert v in out, (who, line, out)


# ---------------------------------------------------------------- L3: a 3 or 4 digit employee number next to a date
@pytest.mark.parametrize("line, num", [
    ("Doe, Jane 6593 2026-11-17", "6593"), ("DOE, JANE 999 (12.002)", "999"), ("pilot 6593 2026-11-17", "6593"),
    ("pilot 6593 2026-11-17 on reserve", "6593"), ("'emp': 6593 2026-11-17", "6593"),
    ("Doe, Jane 6593 (2026-11-17)", "6593"), ("DOE JANE 6593 (2026-11)", "6593"), ("Doe, Jane 6593 12.002", "6593"),
    ("2026-11-17 6593 Doe, Jane", "6593"), ('{"emp": 6593, "day": "2026-11-17"}', "6593"),
    ("pilot 6593 12.002", "6593"),
])
def test_l3_a_short_employee_number_beside_a_name_or_a_date_is_masked(line, num):
    for who, fn in BOTH:
        out = fn(line)
        assert num not in out, (who, line, out)
        for leak in ("Doe", "DOE", "Jane", "JANE"):
            assert leak not in out, (who, line, out)
        for keep in ("2026-11-17", "2026-11", "12.002"):
            assert (keep in out) == (keep in line), (who, line, out)
    assert CAPS.mask("Doe, Jane 6593 2026-11-17", ()) == "xxx, xxxx #### 2026-11-17"
    assert CAPS.mask("DOE, JANE 999 (12.002)", ()) == "xxx, xxxx ### (12.002)"
    assert CAPS.mask_crew("pilot 6593 2026-11-17") == "pilot #### 2026-11-17"


@pytest.mark.parametrize("line", [
    "pilot 3 2026-11", "pilot lookup: 12 pilots read 2026-11-17", "reserve grid 2026-11: 14 days, 120 credit",
    "pilot H3681 2026-11 (12.002)", "crew index: H3681 2026-11-17 flew as FO (read)",
])
def test_l3_a_count_beside_a_date_stays(line):
    for who, fn in BOTH:
        assert fn(line) == line, who


# ------------------------------------------------------------------- L4: '. ', ' - ' or ' -' between number and date
@pytest.mark.parametrize("line", [
    "Doe, Jane 10001. 2026-11-17", "2026-11-17 -10001", "2026-11-17 - 10001", "10001 - 2026-11-17",
    "10001. 2026-11-17", "2026-11-17. 10001", "DOE JANE 10001. 2026-11-17", "doe, jane 10001. 2026-11-17",
    "trade 10001 - 2026-11-17", "12.002 - 10001", "2026-11-17 10001.",
])
def test_l4_an_employee_number_joined_to_a_date_by_a_dot_or_a_dash_is_masked(line):
    for who, fn in BOTH:
        out = fn(line)
        assert "10001" not in out, (who, line, out)
        for keep in ("2026-11-17", "12.002"):
            assert (keep in out) == (keep in line), (who, line, out)


# ----------------------------------------------------------------------------- L5: a number followed by '#'
@pytest.mark.parametrize("line, page, out", [
    ("trade: DOE JANE 10001#12", False, "trade: xxx xxxx ######12"),
    ("Captain: DOE JOHN 10001#12", False, "Captain: xxx xxxx ######12"),
    ("JANE DOE 10001#12 808-555-0101", True, "xxxx xxx ######## ###-###-####"),
    ("trade: DOE JANE 10001 2026-11-17", True, "trade: xxx xxxx ##### 2026-11-17"),
    ("Captain: DOE JOHN 10001 2026-11-17", True, "Captain: xxx xxxx ##### 2026-11-17"),
])
def test_l5_a_name_before_a_number_followed_by_a_hash_is_masked(line, page, out):
    assert CAPS.mask_crew(line, page=page) == out


# ------------------------------------------------------------------------------------- L7: a phone after ' -'
@pytest.mark.parametrize("line", ["on 2026-11 -808 555 0101", "on 2026-11-17 -808 555 0101",
                                  "12.002 .808 555 0101", "on 2026-11 -808-555-0101"])
def test_l7_a_phone_after_a_dash_that_follows_a_month_is_masked(line):
    for who, fn in BOTH:
        out = fn(line)
        assert not re.search(r"808|555|0101", out), (who, line, out)
        assert ("2026-11" in out) == ("2026-11" in line) and ("12.002" in out) == ("12.002" in line), (who, out)


# ----------------------------------------------- L8, F2: a phone with digits glued on through a bracket, at the end
@pytest.mark.parametrize("line", [
    "call 8085550101)(20261117.", "1-808-555-0101(10001.", "+18085550101)10001.", "+1.808.555.0101(10001-",
    "call 1-808-555-0101(10001. now", "8085550101)(2026111.", "8085550101(20261117.", "8085550101)20261117.",
    "8085550101)(20261117-", "call 808-555-0101(1234567) now",
])
def test_l8_f2_a_phone_with_a_number_glued_on_is_masked(line):
    for who, fn in BOTH:
        out = fn(line)
        assert not re.search(r"808|555|0101", out), (who, line, out)
    assert CAPS._phones("call 8085550101)(20261117.") == "call ##########)(20261117."


# --------------------------------------------------------- F1: the words of an employee number's label are no name
@pytest.mark.parametrize("line, out", [
    ("ca: employee number 10001", "ca: employee number #####"),
    ("FO: EMPLOYEE NUMBER 10001", "FO: EMPLOYEE NUMBER #####"),
    ("FO: EMP NO 10001", "FO: EMP NO #####"), ("Captain: employee id 10001", "Captain: employee id #####"),
    ("fo: emp 10001", "fo: emp #####"), ("RO: emp no. 10001", "RO: emp no. #####"),
    ("SCHEDULE FOR EMPLOYEE NUMBER 10001", "SCHEDULE FOR EMPLOYEE NUMBER #####"),
    ("PILOT EMPLOYEE NUMBER 10001", "PILOT EMPLOYEE NUMBER #####"),
    ("Captain: lookup pilot 10001: read", "Captain: lookup pilot #####: read"),
])
def test_f1_an_employee_number_label_stays_readable(line, out):
    assert CAPS.mask_crew(line) == out
    assert CAPS.mask_crew(line, page=True) == out
    assert CAPS.mask_crew(line + " 2026-11-17", page=True) == out + " 2026-11-17"


# -------------------------------------------------------- F6: a long count before a full stop is no phone number
@pytest.mark.parametrize("line", ["size 10485760.", "epoch 1763400000- next", "lon 157.92245.", "count 1234567.",
                                  "ts 1763400000.", "size 10485760. Then"])
def test_f6_a_long_count_before_a_full_stop_stays(line):
    assert CAPS._phones(line) == line
    for who, fn in BOTH:
        assert fn(line) == line, who


@pytest.mark.parametrize("line, out", [
    ("call 808-555-0101.", "call ###-###-####."), ("call (808) 555-0101.", "call (###) ###-####."),
    ("call +44 20 7946 0958.", "call +## ## #### ####."), ("call 555-0101.", "call ###-####."),
    ("call 808 555 0101- then", "call ### ### ####- then"), ("call 1-808-555-0101.", "call #-###-###-####."),
])
def test_f6_a_phone_before_a_full_stop_is_still_masked(line, out):
    assert CAPS._phones(line) == out


# ------------------------------------------------------------------- F3: every fixed log text reaches the sweep
def test_f3_the_sweep_reads_texts_sent_through_portal_once():
    mod = Module("watcher.py", 'def portal_once(key, msg, *a):\n    log.info(msg, *a)\n\n'
                               'portal_once("k", "SWAP DRAFT (%s): give %s", a, b)\n'
                               'log.info("SWAP DRAFT (%s): give %s", a, b)\n')
    assert sorted({line for _n, line, _w, _t, _o in sweep([mod])}) == [4, 5]


def test_f3_the_sweep_reads_texts_sent_through_the_gates_say():
    mod = Module("gate.py", "class Gate:\n    def _say(self, msg, *a):\n        if self.log:\n"
                            "            self.log.info(msg, *a)\n\n    def busy(self, why):\n"
                            '        self._say("SWAP DRAFT (%s) gate", why)\n')
    assert sorted({line for _n, line, _w, _t, _o in sweep([mod])}) == [7]


def test_f3_the_sweep_reads_a_helpers_returned_text():
    mod = Module("watcher.py", 'def _m(src, r):\n    if r:\n        return f"SWAP DRAFT {src} merged"\n'
                               '    return f"pilot db: {src} not applied"\n\n\nlog.info(_m("list", r))\n')
    got = sweep([mod])
    assert sorted({line for _n, line, _w, _t, _o in got}) == [7], got
    assert any("SWAP DRAFT list merged" in text for _n, _l, _w, text, _o in got), got
    mod = Module("watcher.py", 'def _m(src):\n    return f"pilot db: {src} not applied"\n\n\nlog.info(_m("list"))\n')
    assert not sweep([mod]) and not opaque_calls([mod])


def test_f3_a_log_text_the_sweep_cannot_read_fails_unless_allowed():
    mod = Module("watcher.py", "def f(line):\n    log.info(line)\n")
    assert opaque_calls([mod]) == [("watcher.py", 2, "f")]
    assert {(f, fn) for f, _l, fn in opaque_calls(modules())} <= set(OPAQUE)


# ------------------------------------- each phone form beside each neighbour, compared with 1.7.10 (the review's sweep)
@pytest.mark.parametrize("line", [
    "10001  1 808 555 0101", "123456 1 808 555 0101", "10001 808 555 0101 12.002", "x 10001-+44.207 946 0958-10001",
    "+49 30.123 4567 10001", "LAS (808) 555 0101 2026-11-17", "(808) 555-0101 - 123456-", "123456. 808-555-0101.",
    "808.555.0101. 123456.", "+1 808 555 0101-123456.", "2026-11 808-5550101.", "2026-11 8085550101.",
    "x 2026-11-(808) 555-0101-2026-11", "808 555 0101  10001(10001.", "10001 1 808 555 0101(10001.",
    "808-555-0101: 2026-11", "+1 808 555 0101: crew desk", "+44 20 7946 0958: 2026-11",
])
def test_a_phone_beside_another_number_or_a_date_is_masked(line):
    for who, fn in BOTH:
        out = fn(line)
        assert not re.search(r"808|555|0101|7946|0958|946|44\.207|30\.123|4567", out), (who, line, out)
        for keep in ("2026-11", "12.002"):
            assert (keep in out) == (keep in line), (who, line, out)


PHONE_FORMS = ("(808) 555-0101", "808-555-0101", "808.555.0101", "+1 808 555 0101", "8085550101", "808 555 0101",
               "1-808-555-0101", "+18085550101", "+1.808.555.0101", "+44 20 7946 0958", "+44.207 946 0958")
NEIGHBOURS = ("2026-11", "2026-11-17", "12.002", "10001", "123456", "6593", "H3681", "Doe, Jane")


@pytest.mark.parametrize("phone", PHONE_FORMS)
def test_every_phone_form_beside_every_neighbour_is_masked(phone):
    """No digit of the phone is left, whatever stands beside it (before, after, both) and however they are joined;
    the dates and versions beside it stay."""
    for tok in NEIGHBOURS:
        for sep in (" ", " (", ") ", "  ", ". ", " - ", ": ", ", "):
            for end in ("", ".", " now", " 2026-11-17", " 12.002", ": crew"):
                for line in (f"{tok}{sep}{phone}{end}", f"{phone}{sep}{tok}{end}",
                             f"x {tok}{sep}{phone}{sep}{tok}{end}"):
                    at = line.find(phone)
                    for who, fn in BOTH:
                        out = fn(line)
                        assert not re.search(r"\d", out[at:at + len(phone)]), (who, line, out)
                        for keep in ("2026-11-17", "12.002"):
                            assert out.count(keep) == line.count(keep), (who, line, out)


@pytest.mark.parametrize("line", ["2026-11-17 13:05", "H3681 13:05:00.", "12:30: ok", "count 1234567: x",
                                  "2026-11-17 10001: x", "1 2 3: x", "seq 1001 1002 1003 1004", "pairings 3681 3605"])
def test_a_time_or_a_count_before_a_colon_stays(line):
    assert CAPS._phones(line) == line


# --------------------------------------------- a line masked twice (page_log, then the log filter) keeps its date
@pytest.mark.parametrize("line, out", [
    ("emp# 10001 2026-11-17", "emp# ##### 2026-11-17"), ("'emp': 6593 2026-11-17", "'emp': #### 2026-11-17"),
    ("emp: 6593 12.002", "emp: #### 12.002"), ("(emp# 10001) schedule 2026-11-17", "(emp# #####) schedule 2026-11-17"),
])
def test_a_labeled_number_masked_twice_keeps_the_date_after_it(line, out):
    for who, fn in BOTH:
        assert fn(line) == out, who
    assert CAPS.mask_crew("emp ## 10001") == "emp ## #####" and CAPS.mask("emp ## 10001", ()) == "emp ## #####"


def test_the_phone_rule_takes_linear_time_on_long_lines():
    import time
    for text in ("1 " * 20000, "808 555 0101 " * 3000, "123456. " * 5000, "2026-11-17 10001 " * 2500,
                 "(808) 555-0101. " * 2500, "#" * 40000, "1.2 " * 10000):
        t = time.perf_counter()
        CAPS._phones(text)
        CAPS.mask_crew(text, page=True)
        assert time.perf_counter() - t < 3.0, text[:20]

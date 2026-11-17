"""Who writes FLICA and CrewTrac page captures, and where (1.6.2, Release A item 8). Plain Python, no app imports but
roles.

The admin (the default instance) keeps his captures exactly as before: his own pages, as read, in
/share/flight_watcher/captures (the folder the caller passes). A pilot instance takes none by default: no page is
written and no page is loaded only to be saved. Debug captures of a pilot are on only while the file
/share/flight_watcher/<pilot>/captures_on exists and is under 24 h old (the admin creates it by hand when a pilot's
page needs checking; deleting it, or 24 h passing, turns them off). Then:
- session tokens, crew names (crewidx.crew_mask style: the letters of a name become 'x'), employee numbers and the
  pilot's own logins and name are masked, in the page and in the file name; 1.6.2 review: by the page's structure
  too: runs of capitalized words that are no page words ('JANE DOE'), every person argument of a Tradeboard row and
  every JS string literal that is no known token, e-mail addresses and phone numbers;
- files go only to /share/flight_watcher/<pilot>/captures: the pilot name must match roles.NAME_RE and not be reserved,
  the path is resolved and must stay inside that folder, no symlink is followed, the folder is 0700 and each file 0600;
- files there older than 7 days are deleted (checked at most once an hour, also while captures are off).
Nothing of a pilot ever lands in the admin's folder.
"""
import os
import re
import stat
import time

import roles as ROLES

ROOT = "/share/flight_watcher"
FLAG = "captures_on"
FLAG_MAX_S = 24 * 3600
FLAG_AHEAD_S = 300  # a flag dated more than 5 min ahead (a wrong clock, a planted time) does not count
KEEP_S = 7 * 86400
PRUNE_EVERY_S = 3600
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")  # one capture file name (the admin's may add one subfolder)

# masking (a pilot's captures only)
TOKEN_RE = re.compile(r"(?i)\b(token|sid|session(?:id)?|jsessionid|csrf[a-z_]*|auth[a-z_]*|key|ticket)=([^&\"'\s<>;]+)")
HIDDEN_RE = re.compile(r"(?i)(<input\b[^>]*\btype\s*=\s*[\"']?hidden[\"']?[^>]*\bvalue\s*=\s*[\"']?)([^\"'>\s]*)")
HIDDEN_RE2 = re.compile(r"(?i)(<input\b[^>]*\bvalue\s*=\s*[\"']?)([^\"'>\s]*)([\"']?[^>]*\btype\s*=\s*[\"']?hidden)")
# 1.7.11 review: a quoted key too ('emp': 6593, "emp": "6593": a JSON-like sample); one or two '#' but not a run of
# three or more (a number masked already), so a line masked twice (page_log, then the pilot's log filter) keeps the
# date after it ('emp# ##### 2026-11-17')
EMP_KEY_RE = re.compile(r"(?i)\b(emp(?:loyee)?\s*(?:id|no\.?|num(?:ber)?|#(?!#))?['\"]?\s*(?:[=:]|#{1,2}(?!#))+"
                        r"\s*['\"]?)(\d{3,7})")
# 1.7.3 (F#55's live run, Nov 14): the pilot lookup's lines start 'pilot <employee number>:' or 'pilot <number> (<name>)',
# and EMP_RE takes only 5 to 7 digits: the number there is masked whatever its length (3 to 7), a count is not; review:
# the pickup check's 'picker <employee number> ...' too
# 1.7.11 review: and 'pilot <n>' right before a date or a schedule version ('pilot 6593 2026-11-17'), which the phone
# rule took with the number before 1.7.11
_DATE_OR_VERSION = r"(?:20\d{2}-(?:0[1-9]|1[0-2])|\d{1,2}\.\d{3}(?!\d))"
_BESIDE = r"\d{3,7}(?![.\-]\d)[\s().-]{1,4}" + _DATE_OR_VERSION
PILOT_EMP_RE = re.compile(r"(?i)\b(pilot\s+(?=\d{3,7}\s*[:(]|" + _BESIDE + r")|picker\s+)(\d{3,7})\b")
SEAT_EMP_RE = re.compile(r"(?i)(?<![\w'.,-])(CA|FO|RO|FA|SO|F/O)(\s+)(\d{3,7})\b")
EMP_RE = re.compile(r"(?<![\d.:/\-])\d{5,7}(?![\d.:/\-])")
# 1.7.3 review: a name's letters outside ASCII too ('Pe\u00f1a, Jos\u00e9', 'Ka\u02bbaihue', '\u014cta'): Latin-1 and
# Latin Extended letters, the okina and combining accents
NAME_UP = r"A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u024f"
NAME_LOW = r"A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u02bb\u0300-\u036f'\-"
# 'DOE, JANE' / 'Doe Jr, Jane A' / 'DOE, CKP JANE': a capitalized last name, a comma, a capitalized first name.
# 1.7.3: a name right after a quote is a name too (a log line's %r: captain='Doe, Jane'), so the lookbehind takes
# only a word character, not a quote
COMMA_NAME_RE = re.compile(rf"(?<!\w)(\u02bb?[{NAME_UP}][{NAME_LOW}]+(?:\s+\u02bb?[{NAME_UP}][{NAME_LOW}]+)?)\s*,\s*"
                           rf"((?:CKP\s+)?\u02bb?[{NAME_UP}][{NAME_LOW}]+(?:\s+[{NAME_UP}]\.?(?![\w]))?)")
# the words after a seat code and a (masked) employee number, up to the next seat code: 'CA ##### DOE JANE FO open'
CREW_NAME_RE = re.compile(r"(?i)(?<![\w'.,-])((?:CA|FO|RO|FA|SO|F/O)\s+#{3,7}\s+)(.+?)(?=\s+(?:CA|FO|RO|FA|SO|F/O)\s+"
                          r"(?:#|open\b)|\s*$)")
TAG_RE = re.compile(r"(<[^>]*>)")
# 1.6.2 review: by the page's structure, not only the 'Last, First' pattern (the Tradeboard writes 'FIRST LAST' and
# JS string literals "JANE","DOE", with e-mail addresses and phone numbers)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w.:/-])(?:\+?\d[\d\s().-]{5,18}\d)(?![\w.:/-])")
# 1.7.11: a phone may end a sentence or a clause ('call 808-555-1234.', '808-555-1234- ...'; review: '808-555-1234:
# crew desk'): a dot, a colon or a hyphen right after it ends it when no word, digit or dot follows ('13:05' stays).
# Review: read by a rule of its own that takes only a phone's shape (END_SHAPE_RE: a '+' number, three groups or more,
# nnn-nnnn, or a North American number: '8085551234.', '808-5551234.'), so a count, an epoch or a decimal before a
# full stop stays ('size 10485760.', 'ts 1763400000.', 'lon 157.92245.'); and PHONE_RE keeps its 1.7.10 end, so a
# match never runs past a phone into digits glued on through a bracket ('8085551234)(20261117.')
PHONE_END_RE = re.compile(r"(?<![\w.:/-])(?:\+?\d[\d\s().-]{5,18}\d)(?=[.:\-](?![\w.:/\-]))")
END_SHAPE_RE = re.compile(r"\+\d[\d\s().-]*|\d+(?:[\s().-]+\d+){2,}|\d{3}[.-]\d{4}"
                          r"|(?:1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?[2-9]\d{2}[\s.-]?\d{4}")
END_NEXT_RE = re.compile(r"[\w.:/\-]")  # what may not follow the dot, colon or hyphen after a phone (PHONE_END_RE)
DATE_DIGITS_RE = re.compile(r"^20\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d{6})?$")  # YYYYMMDD[HHMMSS]
SCRIPT_OPEN_RE = re.compile(r"(?i)^<script\b")
SCRIPT_CLOSE_RE = re.compile(r"(?i)^</script\b")
JS_STR_RE = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")
A_CALL_RE = re.compile(r"new\s+A\s*\(")
A_PERSON_ARGS = range(9, 15)  # tradeboard.parse_js: flica, email, phone, first, last, comments
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
UI_WORDS = {w.lower() for w in (
    "Trade", "Drop", "Pickup", "Trip", "Trips", "Propose", "Offer", "Add", "Favorites", "Open", "Time", "Opentime",
    "Pot", "Schedule", "Schedules", "Details", "Detail", "Request", "Requests", "Approved", "Denied", "Pending",
    "Processing", "Cancel", "Hide", "Main", "Menu", "Report", "Check", "In", "Out", "Block", "Credit", "Days", "Day",
    "Off", "Layover", "Total", "Totals", "Crew", "Date", "Pairing", "Pairings", "Status", "Type", "Tradeboard", "All",
    "My", "Display", "Options", "Phone", "Email", "Comments", "Comment", "Sign", "Home", "Help", "Next", "Previous",
    "Prev", "Bid", "Period", "Name", "Seat", "Position", "Base", "Equipment", "Updated", "Last", "First", "Flight",
    "Dep", "Arr", "Depart", "Arrive", "Duty", "Rest", "Pay", "TAFB", "Legal", "Hotel", "Notes", "Note", "Submit",
    "Close", "Back", "View", "Print", "Legend", "Reserve", "Grid", "Line", "Award", "Lookup", "Tools", "Crewmember",
    "Flica", "FLICA", "Mobile", "Version", "Yes", "No", "None", "Total", "Hours", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Su", "Mo", "Tu",
    "We", "Th", "Fr", "Sa", "HA", "HST", "CA", "FO", "RO", "FA", "SO", "HNL", "OPEN", "Open", "A330", "A332", "B787",
    "Would", "Like", "To", "The", "And", "For", "With", "By", "Of", "On", "At", "Posted", "Pick", "Up", "Please",
    "Recent", "Updates", "Session", "Expired", "Login", "Password", "User", "Welcome", "Emp", "Employee",
    "ID") + MONTHS}
NAME_WORD = rf"(?:\u02bb?[{NAME_UP}][{NAME_LOW}]+|[{NAME_UP}]\.?)"  # 1.7.3 review: outside ASCII too
NAME_RUN_RE = re.compile(rf"(?<!\w)({NAME_WORD}(?:(?:\s*,\s*|\s+){NAME_WORD})+)(?![\w'])")  # 1.7.3: after a quote too
# 1.7.3: a name with its employee number in parentheses ('Doe, Jane (6593)'; 3 to 7 digits, EMP_RE takes only 5 to 7).
# 1.7.3 review: up to 8 words, so a long run of capitalized words with no number after it costs linear time
NAME_EMP_RE = re.compile(rf"(?<!\w)({NAME_WORD}(?:(?:\s*,\s*|\s+){NAME_WORD}){{0,7}})(\s*\(\s*)(\d{{3,7}})(\s*\))")
SEAT_CODES = {"CA", "FO", "RO", "FA", "SO"}
KNOWN_LIT_RE = re.compile(
    r"^(?:|[\s_,.;:/()&#%-]*|&nbsp;|true|false|null|[A-Z]\d{4}[A-Z]?(?::\d{2}[A-Z]{3})?|\d{1,2}[A-Z]{3}(?:\d{2,4})?"
    r"|\d{1,4}(?:[.:]\d{1,2})*|\d{1,2}:\d{2}(?::\d{2})?|20\d{6}(?:\d{6})?|[A-Z]{2,4}"
    r"|(?:" + "|".join(MONTHS) + r")\s+\d{1,2},\s+\d{4}(?:\s+\d{2}:\d{2}:\d{2}\s+HA)?|[A-Za-z]+(?:/[A-Za-z]+)?)$")


def _x(s):
    """crewidx.crew_mask style: every letter becomes 'x', digits '#', the rest (spaces, commas) stays. 1.7.3 review:
    letters outside ASCII too (the okina, a combining accent)."""
    return re.sub(r"\d", "#", re.sub(r"[^\W\d_]|[\u0300-\u036f]", "x", s))


def _comma_words(words):
    """1.7.3 review: in a run split by re.split (words at even indexes), the words of a 'Last, First' name, page
    words too ('Day Jr, Pat', 'Block, Pat', 'Doe, Jane May'): the one or two words before each comma (COMMA_NAME_RE's
    surname; a seat code first stays: 'CA Doe, Jane') and every word after it up to the next comma or seat code."""
    out = set()
    for c in range(1, len(words), 2):
        if "," not in words[c]:
            continue
        out.add(c - 1)
        if c >= 3 and "," not in words[c - 2] and words[c - 3] not in SEAT_CODES:
            out.add(c - 3)
        j = c + 1
        out.add(j)
        while j + 2 < len(words) and "," not in words[j + 1] and words[j + 2] not in SEAT_CODES:
            j += 2
            out.add(j)
    return out


def _name_runs(t):
    """Two or more capitalized words in a row ('JANE DOE', 'Doe Jane A', 'DE LA CRUZ, MARIA'): each word that is no
    known page word (UI_WORDS, months, seats) is masked."""
    def one(m):
        words = re.split(r"(\s*,\s*|\s+)", m.group(1))
        name = _comma_words(words)  # 1.7.3 review: a 'Last, First' name's page words too ('Day, Pat', 'RO Block, Jan')
        if not name and all(w.lower() in UI_WORDS for w in words[::2]):
            return m.group(1)
        return "".join(w if (i % 2 or (w.lower() in UI_WORDS and i not in name)) else _x(w)
                       for i, w in enumerate(words))
    return NAME_RUN_RE.sub(one, t)


def _name_emps(t):
    """1.7.3: a name followed by its employee number in parentheses ('Doe, Jane (6593)', 'DOE J (10001)') is a crew
    name: the number becomes '#', every word that is no page word is masked and so are the page words of a 'Last,
    First' name (_comma_words: 'Day Jr, Pat'); page words before it (a seat code) stay, and words that are all page
    words with no comma ('Version (1720)') are no name."""
    def one(m):
        words = re.split(r"(\s*,\s*|\s+)", m.group(1))
        name = _comma_words(words)
        if not name and all(w.lower() in UI_WORDS for w in words[::2]):
            return m.group(0)
        out = [w if i % 2 or (w.lower() in UI_WORDS and i not in name) else _x(w) for i, w in enumerate(words)]
        return "".join(out) + m.group(2) + "#" * len(m.group(3)) + m.group(4)
    return NAME_EMP_RE.sub(one, t)


# 1.7.11 (Ryan, Nov 17: "Fix the masking text too"): an ISO month or date (2026-11, 2026-11-17) and a schedule version
# (one or two digits, a dot, three digits: 12.002) are never a phone number or part of one. Before, PHONE_RE took
# 'schedule version 12.002 (2026-11)' for one 11-digit number and the pilot's log said '##.### (####-##)'. Now a match
# is masked only when its digits outside them still make a phone number by the rules below, and only those digits
# are masked; and the text between them is read again on its own (a phone longer than what PHONE_RE could take after
# a version: '12.002 (+1 808 555 1234)'). So a phone right after a date ('2026-11-17 808-555-1234') or in brackets
# after a version is still masked. Review: a '+' right before one makes it a country code ('+44.207 946 0958')
NOT_PHONE_RE = re.compile(r"((?<![\d.+])(?<!\d-)(?:20\d{2}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?"
                          r"|\d{1,2}\.\d{3})(?!\d|[.\-]\d))")
VERSION_RE = re.compile(r"\d{1,2}\.\d{3}")
# review: a version-shaped group that is a phone's own digits, masked with it as before 1.7.11: in a number that starts
# with '+', with digits after it or right after the country code ('+49 30.123 4567'; not '+18085551234 12.002'), with
# digits on both sides of it and 7 or more around it ('808 12.345 0101'), or as the area code of a 3-3-4 number ('Nov
# 17.808 555 1234', 'call 1.808 555 1234')
V_AREA_RE = re.compile(r"\d{1,2}\.\d{3}[\s().-]+\d{3}[\s.-]?\d{4}")
# a 5 to 7 digit number (an employee number's shape) right beside one of them, which the phone rule took with it
# before: masked still ('2026-11-17 10001', '10001 (2026-11-17)'); review: joined by a dot or a dash too, as PHONE_RE
# took it ('10001. 2026-11-17', '2026-11-17 - 10001', '2026-11-17 -10001', '2026-11-17 10001.')
NUM_BEFORE_RE = re.compile(r"(?<![\w.:/])(?<![\w.:/\-]-)(\d{5,7})([\s().-]{1,4})$")
NUM_AFTER_RE = re.compile(r"^([\s().-]{1,4})(\d{5,7})(?![\w:/])(?![.\-][\w.:/\-])")
# review: a phone's group that a rule's 20-character window left out ('123456 (808) 555 1234 2026-11-17' gave
# '123456 (808) 555' and '1234 2026-11-17'): 3 or 4 digits right after or right before a phone's digits, only a
# phone's separators between them (two groups at most after it, three before it: a phone has no more)
TAIL_RE = re.compile(r"(?<=\d)[\s().-]{1,3}(\d{3,4})(?![\w/])(?![.:]\d)")
# review: a phone of the usual shapes inside a longer match that is no phone as a whole ('10001 808 555 1234',
# '10001 1 808 555 1234 10001'): ADMIN_PHONE_RE's shapes, read with the match's dates and versions blanked
INNER_PHONE_RE = re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\d])")
HEAD_RE = re.compile(r"(?<![\w.:/])(?<![\w.:/\-]-)(\d{3,4}|1)[\s().-]{1,3}(?=\d)")  # '1': a country code
# a phone written with spaces only: an international one ('+1 808 555 1234', '+44 20 7946 0958') or the 3-3-4 shape
# ('808 555 1234', '1 808 555 1234')
SPACED_PHONE_RE = re.compile(r"\+\d[\d\s]*|(?:1\s+)?\d{3}\s+\d{3}\s+\d{4}")


def _is_phone(s):
    """One PHONE_RE match (its dates and versions taken out) is a phone number: 7 to 15 digits, no YYYYMMDD[HHMMSS],
    no time, and not numbers in a row ('1 2 3 4 5 6 7') unless written as a phone."""
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7 or len(digits) > 15 or DATE_DIGITS_RE.match(digits):
        return False
    s = s.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", s):
        return False
    return not (" " in s and not re.search(r"[()\-.]|\d{7}", s) and not SPACED_PHONE_RE.fullmatch(s))


def _is_phone_end(s):
    """Review: a match before a trailing dot, colon or hyphen (PHONE_END_RE) is a phone only in a phone's shape."""
    return _is_phone(s) and bool(END_SHAPE_RE.fullmatch(s.strip()))


def _own_versions(s, parts, plus=False):
    """Review: the indexes (in parts, NOT_PHONE_RE.split(s)) of the version-shaped groups that are the phone's own
    digits (V_AREA_RE's comment; plus: a '+' right before s, which PHONE_RE leaves out after a '-'). A date never
    is."""
    digits = [len(re.sub(r"\D", "", p)) if i % 2 == 0 else 0 for i, p in enumerate(parts)]
    own = set()
    for i in range(1, len(parts), 2):
        if not VERSION_RE.fullmatch(parts[i]):
            continue
        before, after = sum(digits[:i]), sum(digits[i + 1:])
        intl = (plus or s.startswith("+")) and (after or before <= 3)  # in it, or right after its country code
        if intl or (before and after and before + after >= 7) or V_AREA_RE.fullmatch("".join(parts[i:]).rstrip()):
            own.add(i)
    return own


def _mask_phone(s, ok, plus=False):
    """s (one match) with a phone's digits as '#', or None when ok finds no phone in it. Its dates and versions stay,
    unless a version is the phone's own (_own_versions)."""
    parts = NOT_PHONE_RE.split(s)
    own = _own_versions(s, parts, plus)
    with_own = "".join(p for i, p in enumerate(parts) if i % 2 == 0 or i in own)
    # a phone with its own versions, or one without them ('+49 30.123 4567 10001': 16 digits with the number after it)
    if ok(with_own) or (own and ok("".join(parts[::2]))):
        return "".join(re.sub(r"\d", "#", p) if i % 2 == 0 or i in own else p for i, p in enumerate(parts))
    return None


def _plus(m):
    """A '+' right before the match (PHONE_RE takes none after a '-': '10001-+44.207 946 0958')."""
    return m.start() > 0 and m.string[m.start() - 1] == "+"


def _phone_sub(m):
    """One PHONE_RE match, its phone's digits as '#' (unchanged when it holds none)."""
    s = m.group(0)
    out = _mask_phone(s, _is_phone, _plus(m))
    if out is not None:
        return out
    parts = NOT_PHONE_RE.split(s)
    blank = "".join(" " * len(p) if i % 2 else p for i, p in enumerate(parts))
    inner = [x.span() for x in INNER_PHONE_RE.finditer(blank)]
    if inner:  # review: a phone of the usual shape inside it
        return "".join("#" if c.isdigit() and any(a <= k < b for a, b in inner) else c for k, c in enumerate(s))
    rest = "".join(parts[::2])
    cut = max((w.start() for w in re.finditer(r"[\s()]", s)), default=-1)
    if len(re.sub(r"\D", "", rest)) > 15 and cut > 0:
        # more digits than one phone holds: a phone and the number after it ('1-808-555-1234 10001'), each read on
        # its own (split at the last space; review: or bracket, '808-555-1234(1234567)')
        return PHONE_RE.sub(_phone_sub, s[:cut]) + PHONE_RE.sub(_phone_sub, s[cut:])
    return s


def _scan(t, rx, one):
    """rx over t, each match given to one(m) -> (masked text, its end) or None. Review: where a match holds no phone,
    the next one may start inside it ('10001  1 808 555 1234', '123456. 808-555-1234.': the run from the first number
    is too long for one phone or no phone's shape, the one from the next number is a phone)."""
    out, pos, i = [], 0, 0
    while True:
        m = rx.search(t, i)
        if not m:
            break
        r = one(m)
        if r is None or r[0] == t[m.start():r[1]]:
            i = m.start() + 1
            continue
        out += [t[pos:m.start()], r[0]]
        pos = i = r[1]
    return "".join(out) + t[pos:]


def _one_end(m):
    """One PHONE_END_RE match; where it holds no phone, a shorter one from the same start that also ends before a dot,
    a colon or a hyphen may ('808.555.1234. 123456.')."""
    t = m.string
    for e in range(m.end(), m.start() + 6, -1):
        if e == m.end() or (t[e] in ".:-" and t[e - 1].isdigit() and not END_NEXT_RE.match(t, e + 1)):
            r = _mask_phone(t[m.start():e], _is_phone_end, _plus(m))
            if r is not None:
                return r, e
    return None


def _phone_pass(t):
    """t read once by both phone rules: PHONE_RE, then PHONE_END_RE on what is left (a phone before a trailing dot,
    colon or hyphen). PHONE_RE first, so a phone that ends with a space is read from its first digit ('(808) 555-1234
    - 123456.'); a phone's group a window leaves out ('+1 808 555 1234- ...') is masked by _phones (TAIL_RE,
    HEAD_RE)."""
    return _scan(_scan(t, PHONE_RE, lambda m: (_phone_sub(m), m.end())), PHONE_END_RE, _one_end)


def _phones(t):
    """Phone numbers in t, their digits as '#'. Dates and versions stay (NOT_PHONE_RE); the length never changes.
    Review: a digit another rule masked already ('#') is read as a digit, so a phone that rule took a part of is still
    a phone ('LAS (###) 555 1234': _name_emps took 'LAS (808)' for a name and its number); only digits are masked."""
    orig, t = str(t), str(t).replace("#", "0")
    hit = [a != b for a, b in zip(t, _phone_pass(t))]  # a phone's digits
    near = [False] * len(t)  # a 5 to 7 digit number beside a date or a version
    parts = NOT_PHONE_RE.split(t)
    pos = 0
    for i, p in enumerate(parts if len(parts) > 1 else ()):
        if i % 2 == 0:  # the text between them, each piece on its own
            # review: a dot or a dash right after a date or a version is no part of the phone after it ('2026-11
            # -808 555 1234'): read as a space, so PHONE_RE's lookbehind takes the phone's first digit
            lead = len(re.match(r"[\s().-]*", p).group(0)) if i else 0
            q = _phone_pass(re.sub(r"[.-]", " ", p[:lead]) + p[lead:])
            for k, (x, y) in enumerate(zip(p, q)):
                hit[pos + k] = hit[pos + k] or (x.isdigit() and y == "#")
            m = NUM_BEFORE_RE.search(p) if i + 1 < len(parts) else None
            n = NUM_AFTER_RE.match(p) if i else None
            for k in [k for x in (m and m.span(1), n and n.span(2)) if x for k in range(*x)]:
                near[pos + k] = True
        pos += len(p)
    tokens = [m.span() for m in NOT_PHONE_RE.finditer(t)]  # a date's or a version's digits are never a phone's group
    for n in range(3):  # review: a phone's group a window left out, after it (two) or before it (three: '1 808 555')
        grow = [m.span(1) for m in TAIL_RE.finditer(t) if hit[m.start() - 1]] if n < 2 else []
        grow += [m.span(1) for m in HEAD_RE.finditer(t) if hit[m.end()]]
        for a, b in [g for g in grow if not any(x < g[1] and g[0] < y for x, y in tokens)]:
            for k in range(a, b):
                hit[k] = True
    return "".join("#" if c.isdigit() and (hit[i] or near[i]) else c for i, c in enumerate(orig))


# 1.7.11 review: a bare number right beside a masked name ('xxx, xxxx 6593', 'xxx xxxx 999 (12.002)', '6593 xxx,
# xxxx') is that pilot's employee number (3 to 7 digits, as NAME_EMP_RE takes): a pilot's mask, after the names (the
# phone rule took it before 1.7.11 when a date or a version was beside it). Two to eight masked words, so a long run
# of them with no number costs linear time
_X_RUN = r"x+(?:(?:[ '.\-]{1,3}|\s*,\s*)x+){1,7}"
X_RUN_NUM_RE = re.compile(r"((?<![\w'])" + _X_RUN + r"[\s,:;(]{1,4})(\d{3,7})(?![\w:/])(?![.\-][\w.:/\-])")
NUM_X_RUN_RE = re.compile(r"(?<![\w.:/])(?<![\w.:/\-]-)(\d{3,7})([\s,:;)]{1,4}" + _X_RUN + r")(?![\w])")


def _mask_text(t):
    t = _name_emps(t)  # 1.7.3: a name and its employee number in parentheses, before the 5 to 7 digit numbers go
    t = SEAT_EMP_RE.sub(lambda m: m.group(1) + m.group(2) + "#" * len(m.group(3)), t)
    t = EMP_RE.sub(lambda m: "#" * len(m.group(0)), t)
    t = CREW_NAME_RE.sub(lambda m: m.group(1) + (m.group(2) if m.group(2).lower() == "open" else _x(m.group(2))), t)
    t = _name_runs(t)  # before the comma pattern, so a run like 'DE LA CRUZ, MARIA' is masked whole
    t = COMMA_NAME_RE.sub(lambda m: _x(m.group(0)), t)
    t = X_RUN_NUM_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), t)
    return NUM_X_RUN_RE.sub(lambda m: "#" * len(m.group(1)) + m.group(2), t)


def _lit(tok, force=False):
    """One JS string literal (with its quotes), masked unless it is a known token (pairing, date, time, number,
    station or seat code, a UI word, true / false)."""
    q, body = tok[0], tok[1:-1]
    if not force and KNOWN_LIT_RE.match(body) and (len(body) > 4 or body.lower() in UI_WORDS
                                                   or not re.fullmatch(r"[A-Za-z]+", body) or body.isupper()):
        if not re.fullmatch(r"[A-Z][a-z]+", body) or body.lower() in UI_WORDS:
            return tok
    return q + _x(body) + q


def _mask_js(code):
    """A script's string literals: every argument about a person of a Tradeboard row (new A(...): flica, e-mail,
    phone, first, last, comments) masked whatever it holds; any other literal unless it is a known token."""
    out, i = [], 0
    for m in A_CALL_RE.finditer(code):
        if m.start() < i:
            continue
        out.append(JS_STR_RE.sub(lambda x: _lit(x.group(0)), code[i:m.end()]))
        j, arg, q = m.end(), 0, None
        start = j
        while j < len(code):
            ch = code[j]
            if q:
                if ch == "\\":
                    j += 1
                elif ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
            elif ch in ",)":
                piece = code[start:j]
                out.append(JS_STR_RE.sub(lambda x: _lit(x.group(0), force=arg in A_PERSON_ARGS), piece) + ch)
                arg += 1
                start = j + 1
                if ch == ")":
                    break
            j += 1
        i = j + 1 if j < len(code) else len(code)
        if j >= len(code):
            out.append(JS_STR_RE.sub(lambda x: _lit(x.group(0)), code[start:]))
    out.append(JS_STR_RE.sub(lambda x: _lit(x.group(0)), code[i:]))
    return "".join(out)


# 1.7.9 (Ryan, Nov 15): a labeled employee number in FLICA page text quoted in a log line ("(emp# n) schedule last
# updated", "Emp#n", "EmployeeID=n", "employee id: n"), whatever its length; the label stays, the digits become '#'
# 1.7.9 review: close variants too. The label is 'emp' or 'employee' at a word start, or 'EmployeeID' anywhere
# ('strEmployeeID=', 'CrewEmployeeID='), with or without id / no / num / number; between it and the digits any run of
# spaces, dots, '_', '#', ':', '=', '-', a no-break space, '&nbsp;' or '%3D', or nothing ('Employee Number 10001',
# 'EmpNo 10001', 'empid 10001', 'Emp. # 10001', 'employee_id=10001'); the number may hold hyphens ('0-10001'). Also
# the capture file's own name (cmschedule_<n>.html, in an error text) and a number in brackets beside a 'Last, First'
# name ('(10001) Doe, Jane', 'Doe, Jane (10001)').
# 1.7.11 review: a quote too ('emp': 6593, "emp": "6593"); one or two '#' but not a run of three or more (a number
# masked already), so a line masked twice (page_log, then the admin's log filter) keeps the date after it ('emp: ####
# 2026-11-17')
_EMP_SEP = r"(?:[\s._:=\-\xa0'\"]|#{1,2}(?!#)|&nbsp;|%3D)*"
EMP_QUOTE_RE = re.compile(r"(?i)((?:\bemp(?:loyee)?|employee[\s._-]*id)[\s._-]*(?:id|no|num(?:ber)?)?" + _EMP_SEP
                          + r"|cmschedule_)(\d(?:[\d-]*\d)?)")
_NAME = r"[a-z][a-z'.\-]+,\s*[a-z][a-z'.\-]*"  # any case: visible_text lowercases a page
EMP_NAME_RE = re.compile(r"(?i)(\(\s*)(\d{4,7})(\s*\)\s*" + _NAME + r")|(" + _NAME + r"\s*\(\s*)(\d{4,7})(\s*\))")


def mask_emp(text):
    """Page text for a log line with no employee number (the admin's log too): every labeled number masked. Names,
    times, pairings and flights stay (a pilot's line is masked in full by mask)."""
    s = EMP_QUOTE_RE.sub(lambda m: m.group(1) + re.sub(r"\d", "#", m.group(2)), str(text or ""))
    return EMP_NAME_RE.sub(lambda m: (m.group(1) + "#" * len(m.group(2)) + m.group(3)) if m.group(2) else
                           (m.group(4) + "#" * len(m.group(5)) + m.group(6)), s)


# 1.7.10 (Ryan, Nov 15): the admin's own log carries no crew name and no employee number either. mask_crew is the
# admin's line mask (watcher.AdminLogMask, and page text quoted through watcher.page_log): narrower than mask() (a
# pilot's), which would also blank ordinary words; it takes what a crew list, a pickup line or a lookup line holds.
# review (round 2): a last name of up to four words ('de la cruz', 'van der doe jr'), a second given name where a
# number in brackets ends the name ('doe-smith, mary ann (10001)'), a 3-digit number in brackets (submit.PICKED_RE
# takes 3 to 7), and the small words a page puts before a name ('with doe, jane') are no part of it
_LW = (r"(?!(?:ca|fo|ro|fa|so|by|up|ckp|open|picked|pilot|picker|capt|captain|with|for|and|the|from)\b)"
       r"[a-z\u00c0-\u024f\u02bb][a-z\u00c0-\u024f\u02bb'.\-]*")
_LOW_LAST = r"(?<![\w'])" + _LW + r"(?:\s+" + _LW + r"){0,3}\s*,\s*"
_LOW_NAME = _LOW_LAST + _LW + r"(?:\s+[a-z]\b\.?)?"
_LOW_NAME2 = _LOW_LAST + _LW + r"(?:\s+" + _LW + r"){0,2}"
NAME_HASH_RE = re.compile(r"(?i)(" + _LOW_NAME2 + r")(\s*\(\s*)([#\d]{3,7})(\s*\))")
HASH_NAME_RE = re.compile(r"(?i)(\(\s*)([#\d]{3,7})(\s*\)\s*)(" + _LOW_NAME + r")")
# a capitalized 'Last, First' with up to four last-name words and a second given name ('De La Cruz, John', 'Doe-Smith,
# Mary Ann'): the admin's line mask only (COMMA_NAME_RE stays the pilot mask's)
_CAPW = rf"\u02bb?[{NAME_UP}][{NAME_LOW}]+"
COMMA_NAME_WIDE_RE = re.compile(rf"(?<!\w)((?:{_CAPW}\s+){{0,3}}{_CAPW}\s*,\s*(?:CKP\s+)?{_CAPW}"
                                rf"(?:\s+[{NAME_UP}]\.?(?![\w]))?)(\s+{_CAPW})?")
# names with no comma: a seat label, one to four words and the number ('Captain: DOE JOHN 99999', 'f/o: doe jane
# 10001'), and capital words right before a number ('trade: DOE JANE 10001'). 1.7.11: mask_crew lets them read the
# digits the phone rule masked (in page text, a number right beside a date is masked first), and only those: a number
# another rule masked ('employee number #####') has no name before it
SEAT_WORDS_NUM_RE = re.compile(r"(?i)(?<![\w'.,-])((?:CA|FO|RO|F/O|capt(?:ain)?)\s*[:=]\s*)((?:[a-z\u00c0-\u024f\u02bb]"
                               r"[a-z\u00c0-\u024f\u02bb'.\-]*\s+){1,4})(\d{3,7})(?![\d:./-])")
CAPS_NUM_RE = re.compile(rf"(?<![\w'])((?:[{NAME_UP}][{NAME_UP}'\-]+\s+){{2,4}})(\d{{4,7}})(?![\d:./-])")
QUOTED_NUM_RE = re.compile(r"(\b\w*(?:Error|Exception)\(\s*['\"])(\d{3,7})(['\"]\s*\))")  # KeyError('10001')
ADMIN_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")  # bounded: linear on a long token
ADMIN_PHONE_RE = re.compile(r"(?<![\w.:/-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w:/-])")
# review (speed cap view pages): crew scheduling's real comment is first name first with no comma, and visible_text
# lowercases it ('picked up by john q. doe jr (10001)'): every word after 'picked up by' (eight at most, each split
# from the next by spaces or a comma; a label such as 'note:' ends them) is masked whatever its case, and so is the
# number after them, in brackets or not, whole or cut short by the line's length ('(100')
_PW = r"(?![^\W\d_]{1,30}:)[^\W\d_](?:[^\W\d_]|['\u2019.\-]){0,30}"
PICKED_BY_RE = re.compile(r"(?i)(picked\s{1,8}up\s{1,8}by\s{1,8})(" + _PW + r"(?:(?:\s{0,8},\s{0,8}|\s{1,8})" + _PW
                          + r"){0,7})?(\s{0,8},?\s{0,8}\(?\s{0,8})([\d#]{1,7})?")
SEAT_NAME_RE = re.compile(r"(?i)(?<![\w'.,-])((?:CA|FO|RO|F/O|capt(?:ain)?)\s*[:=]?\s+)(" + _LOW_NAME + r")")
CREW_LINE_RE = re.compile(r"(?is)(\bcrew\s*:\s*)(.{0,400})")
LOOKUP_EMP_RE = re.compile(r"(?i)\b(pilot\s+|picker\s+)(\d{3,7})\b(?=\s*[:(]|\s+(?:on|still|is|was)\b|(?![.\-]\d)"
                           r"[\s().-]{1,4}" + _DATE_OR_VERSION + r")")  # 1.7.11 review: 'pilot 6593 2026-11-17'
# 1.7.11 review: 3 to 7 digits (NAME_EMP_RE's; 'xxx, xxxx 999 (12.002)'), and before a full stop ('xxx, xxxx 10001.')
X_NAME_NUM_RE = re.compile(r"((?<![\w'])x+(?:[ '.\-]x+)*,\s*x+(?:[ '.\-]x+)*[\s,:;(]+)(\d{3,7})(?![\d:/])"
                           r"(?![.\-][\w.:/\-])")
NUM_X_NAME_RE = re.compile(r"(?<![\d:./-])(\d{3,7})([\s,:;)]+x+(?:[ '.\-]x+)*,\s*x+)(?![\w])")
MONTH_WORDS = {"january", "february", "march", "april", "june", "july", "august", "september", "october", "november",
               "december"}


def _crew_line(m):
    """A crew line's words (crewidx.crew_mask's rule): seat codes, 'open' and 'ckp' stay; a number becomes '#', any
    other word 'x' (commas and brackets stay)."""
    toks = m.group(2).split(" ")
    out = []
    for i, t in enumerate(toks):
        low = t.lower()
        nxt = toks[i + 1].lower() if i + 1 < len(toks) else ""
        if low in ("open", "ckp", ""):
            out.append(t)
        elif re.fullmatch(r"[a-z]{2}|[a-z]/[a-z]", low) and (nxt[:1].isdigit() or nxt[:1] == "#" or nxt == "open"):
            out.append(t)
        elif re.fullmatch(r"\(?[\d#]{3,7}\)?[,;]?", t):
            out.append(re.sub(r"\d", "#", t))
        elif re.search(r"\d", t):
            out.append(t)  # a time, a date, a pairing: not a name
        else:
            out.append(_x(t))
    return m.group(1) + " ".join(out)


def _comma_name(m):
    words = [w.lower() for w in re.split(r"[\s,]+", m.group(0)) if w]
    if all(w in UI_WORDS or w in MONTH_WORDS for w in words):
        return m.group(0)  # 'Friday, November', 'Open, Pending': page words, no name
    return _x(m.group(0))


def _comma_wide(m):
    """A capitalized 'Last, First' (COMMA_NAME_WIDE_RE): masked unless every word is a page word; the word after it
    is a second given name ('Mary Ann') unless it is a page word ('Doe, Jane Schedule')."""
    words = [w.lower() for w in re.split(r"[\s,]+", m.group(1)) if w]
    if all(w in UI_WORDS or w in MONTH_WORDS for w in words):
        return m.group(0)
    tail = m.group(2) or ""
    return _x(m.group(1)) + (tail if tail.strip().lower() in UI_WORDS | MONTH_WORDS else _x(tail))


def _name_num(name, pre, num, post, m):
    words = [w.lower() for w in re.split(r"[\s,]+", name) if w]
    if all(w in UI_WORDS or w in MONTH_WORDS for w in words):
        return m.group(0)
    return None


def _caps_num(m):
    words = m.group(1).split()
    if all(w.lower() in UI_WORDS or w.lower() in MONTH_WORDS for w in words):
        return m.group(0)
    return "".join(w if not w.strip() or w.lower() in UI_WORDS else _x(w)
                   for w in re.split(r"(\s+)", m.group(1))) + "#" * len(m.group(2))


LOW_NAME_RE = re.compile(r"(?i)" + _LOW_NAME)
LONG_RUN_RE = re.compile(r"(?:[^\W\d_]|['.\-]){80,}")


def mask_crew(text, page=False):
    """A log line (or page text for one) with no crew name and no employee number, for the admin's log: a labeled
    number (mask_emp), the number of a 'pilot <n>:' / 'picker <n>' line, a name with its number in brackets, a seat
    and its number, the names of a crew line ('crew: ca 99999 doe, john fo 10001 doe, jane' -> 'crew: ca ##### xxx,
    xxxx fo ##### xxx, xxxx'), a 'picked up by' or seat-labeled name, and a capitalized 'Last, First'. Seats,
    pairings, dates, times, flights and counts stay, so a line still says which seat or pairing it is about.
    page=True (text quoted from a FLICA page, which visible_text lowercases): a 'last, first' in any letter case
    too, page words apart ('monday, november'). Review (round 2): also an e-mail address, a phone-shaped number
    (any 7 to 15 digit phone in page text), a seat-labeled or all-capitals name with no comma before its number
    ('Captain: DOE JOHN 99999'), and the number an error text quotes (KeyError('10001'))."""
    # review (round 2): a run of 80 or more letters (hyphens, dots and apostrophes too) is no word (and no name): said by its length, so one very long
    # token never costs the name patterns seconds
    s = LONG_RUN_RE.sub(lambda m: f"({len(m.group(0))} letters)", str(text or ""))
    s = _name_emps(s)
    s = mask_emp(s)
    s = LOOKUP_EMP_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), s)
    s = SEAT_EMP_RE.sub(lambda m: m.group(1) + m.group(2) + "#" * len(m.group(3)), s)
    s = CREW_LINE_RE.sub(_crew_line, s)
    s = CREW_NAME_RE.sub(lambda m: m.group(1) + (m.group(2) if m.group(2).lower() == "open" else _x(m.group(2))), s)
    if "@" in s:  # review (round 2): an e-mail address, a phone-shaped number
        s = ADMIN_EMAIL_RE.sub(lambda m: _x(m.group(0)), s)
    before = s
    s = _phones(s) if page else ADMIN_PHONE_RE.sub(lambda m: re.sub(r"\d", "#", m.group(0)), s)
    phone = [a != b for a, b in zip(before, s)]  # the digits the phone rule masked (the length never changes)
    s = QUOTED_NUM_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)) + m.group(3), s)
    s = NAME_HASH_RE.sub(lambda m: _name_num(m.group(1), 0, 0, 0, m) or (
        _x(m.group(1)) + m.group(2) + "#" * len(m.group(3)) + m.group(4)), s)
    s = HASH_NAME_RE.sub(lambda m: _name_num(m.group(4), 0, 0, 0, m) or (
        m.group(1) + "#" * len(m.group(2)) + m.group(3) + _x(m.group(4))), s)
    # 1.7.11 review: the two name rules before a number read the digits the phone rule masked as digits ('trade: DOE
    # JANE 10001 2026-11-17' in page text), and a number another rule masked as no number ('employee number #####')
    s = "".join(b if p else c for b, c, p in zip(before, s, phone))
    s = SEAT_WORDS_NUM_RE.sub(lambda m: m.group(1) + _x(m.group(2)) + "#" * len(m.group(3)), s)
    s = CAPS_NUM_RE.sub(_caps_num, s)
    s = "".join("#" if p else c for c, p in zip(s, phone))
    s = PICKED_BY_RE.sub(lambda m: m.group(1) + _x(m.group(2) or "") + m.group(3) + "#" * len(m.group(4) or ""), s)
    s = SEAT_NAME_RE.sub(lambda m: m.group(1) + _x(m.group(2)), s)
    s = COMMA_NAME_WIDE_RE.sub(_comma_wide, s)
    if page:  # quoted page text (visible_text lowercases it): any 'last, first' there, whatever its case
        s = LOW_NAME_RE.sub(_comma_name, s)
    # a bare number right beside a masked name ('xxx, xxxx 10001', '10001 xxx, xxxx') is that pilot's
    s = X_NAME_NUM_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), s)
    return NUM_X_NAME_RE.sub(lambda m: "#" * len(m.group(1)) + m.group(2), s)


def mask(text, extra=()):
    """A page as a pilot's capture may hold it: session tokens and hidden form values MASKED, employee numbers '#',
    crew names and every string in extra (the pilot's own logins, name and employee number) masked."""
    s = str(text or "")
    for v in sorted({x for x in extra if isinstance(x, str) and len(x.strip()) >= 3}, key=len, reverse=True):
        s = re.sub(re.escape(v.strip()), "MASKED", s, flags=re.I)
    s = TOKEN_RE.sub(lambda m: f"{m.group(1)}=MASKED", s)
    s = HIDDEN_RE.sub(lambda m: m.group(1) + "MASKED", s)
    s = HIDDEN_RE2.sub(lambda m: m.group(1) + "MASKED" + m.group(3), s)
    s = EMP_KEY_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), s)
    s = PILOT_EMP_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), s)
    s = EMAIL_RE.sub(lambda m: _x(m.group(0)), s)  # 1.6.2 review: e-mail addresses and phone numbers
    s = _phones(s)
    parts = TAG_RE.split(s)
    script = False
    for i, p in enumerate(parts):
        if not p:
            continue
        if p.startswith("<"):
            script = bool(SCRIPT_OPEN_RE.match(p)) or (script and not SCRIPT_CLOSE_RE.match(p))
            parts[i] = EMP_RE.sub(lambda m: "#" * len(m.group(0)), COMMA_NAME_RE.sub(lambda m: _x(m.group(0)), p))
        elif script or A_CALL_RE.search(p):
            parts[i] = EMP_RE.sub(lambda m: "#" * len(m.group(0)), _mask_js(p))
        else:
            parts[i] = _mask_text(p)
    return "".join(parts)


class Captures:
    """One instance's capture policy. secrets: a callable giving the strings a pilot's captures must never hold (his
    FLICA and CrewTrac user names, passwords, name and employee number); log: a callable taking one line."""

    def __init__(self, instance, root=ROOT, log=None, secrets=None, now=time.time):
        self.instance = instance or ""
        self.root = root
        self.log = log or (lambda m: None)
        self.secrets = secrets or (lambda: ())
        self.now = now
        self._said = None
        self._pruned = 0.0

    @property
    def admin(self):
        return ROLES.role(self.instance) == ROLES.ADMIN

    def _base(self):
        """/share/flight_watcher/<pilot> for a pilot whose name passes, else None."""
        if self.admin or ROLES.name_refusal(self.instance):
            return None
        return os.path.join(self.root, self.instance)

    def folder(self, admin_dir=None):
        """Where this instance's captures go: the admin's folder as given (default <root>/captures), a pilot's
        <root>/<pilot>/captures, or None (a pilot name that does not pass)."""
        if self.admin:
            return admin_dir or os.path.join(self.root, "captures")
        b = self._base()
        return os.path.join(b, "captures") if b else None

    def on(self):
        """True while this instance may write captures: always on the admin; on a pilot only while its captures_on
        file exists, is a plain file (no symlink) and is under 24 h old. Logs each change once. A pilot's old files
        are pruned here too (at most once an hour)."""
        if self.admin:
            return True
        b = self._base()
        if not b:
            return False
        self.prune()
        flag, ok = os.path.join(b, FLAG), False
        try:
            st = os.lstat(flag)
            age = self.now() - st.st_mtime
            ok = stat.S_ISREG(st.st_mode) and -FLAG_AHEAD_S <= age < FLAG_MAX_S
        except OSError:
            pass
        if ok != self._said:
            self._said = ok
            self.log(f"page captures {'on' if ok else 'off'} for this pilot" + (
                " (masked, own folder, deleted after 7 days; ends 24 h after captures_on was made)" if ok else ""))
        return ok

    def _pilot_dir(self):
        """The pilot's captures folder, made 0700 when missing; None when it is not a plain folder inside
        <root>/<pilot> (a symlink anywhere, a file in its place)."""
        b = self._base()
        if not b:
            return None
        d = os.path.join(b, "captures")
        try:
            os.makedirs(b, exist_ok=True)
            if not os.path.lexists(d):
                os.mkdir(d, 0o700)
            st = os.lstat(d)
            if not stat.S_ISDIR(st.st_mode):
                return None
            real_b = os.path.realpath(b)
            if os.path.realpath(d) != os.path.join(real_b, "captures") or os.path.islink(b):
                return None
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(d, 0o700)
            return d
        except OSError:
            return None

    def write(self, name, data, admin_dir=None, extra=()):
        """Save one capture; the path written, or None (captures off, a name that does not pass, an error). The
        admin's goes to admin_dir exactly as before (makedirs, plain write, no masking). A pilot's is masked, named
        safely, kept inside its folder, 0600, never through a symlink."""
        if isinstance(data, (dict, list)):
            import json
            data = json.dumps(data, indent=1)
        data = "" if data is None else str(data)
        if self.admin:
            d = admin_dir or os.path.join(self.root, "captures")
            path = os.path.join(d, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(data)
            return path
        if not self.on():
            return None
        extra = [x for x in list(self.secrets() or ()) + list(extra or ()) if isinstance(x, str)]
        safe = re.sub(r"\d{5,7}", lambda m: "N" * len(m.group(0)), mask(name.replace("/", "_"), extra))
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe)  # an employee number in a name is NNNNN
        if not NAME_OK.fullmatch(safe) or ".." in safe:
            return None
        d = self._pilot_dir()
        if not d:
            self.log("page capture not written: the pilot's captures folder is not a plain folder")
            return None
        path = os.path.join(d, safe)
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(d):
            return None
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(mask(data, extra))
        return path

    def _own_dir(self):
        """1.6.2 review: <root>/<pilot>/captures when it, and <root>/<pilot> itself, are plain folders (no symlink
        anywhere: a linked pilot folder pointing at the admin's would have had his files deleted) and it resolves to
        exactly that path; else None. Nothing is made."""
        b = self._base()
        if not b:
            return None
        d = os.path.join(b, "captures")
        try:
            for p in (b, d):
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                    return None
            if os.path.realpath(d) != os.path.join(os.path.realpath(self.root), self.instance, "captures"):
                return None
        except OSError:
            return None
        return d

    def cleanup_pilot(self):
        """1.6.2 review, once per pilot (the caller keeps the flag): 1.6.1 saved an unmasked login screenshot
        (<root>/<pilot>/last_login.png); it is deleted, the captures folder made 0700 and pruned. Returns how many
        files went (the log says only that count)."""
        b = self._base()
        if not b:
            return 0
        n = 0
        shot = os.path.join(b, "last_login.png")
        try:
            st_b = os.lstat(b)
            st = os.lstat(shot)
            if not stat.S_ISLNK(st_b.st_mode) and stat.S_ISREG(st.st_mode):
                os.remove(shot)
                n += 1
        except OSError:
            pass
        d = self._own_dir()
        if d:
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
        return n + self.prune(force=True)

    def prune(self, force=False):
        """A pilot's capture files older than 7 days are deleted (plain files only, never through a symlink). At most
        once an hour unless force. Returns how many went."""
        b = self._base()
        if not b or (not force and self.now() - self._pruned < PRUNE_EVERY_S):
            return 0
        self._pruned = self.now()
        d, n = self._own_dir(), 0
        if not d:
            return 0
        try:
            for f in os.listdir(d):
                p = os.path.join(d, f)
                st = os.lstat(p)
                if stat.S_ISREG(st.st_mode) and self.now() - st.st_mtime > KEEP_S:
                    os.remove(p)
                    n += 1
        except OSError:
            pass
        if n:
            self.log(f"page captures: {n} older than 7 days deleted")
        return n


# 1.6.2 review: what 1.6.1's pilot code wrote into the admin's folder (/share/flight_watcher/captures) and 1.6.2 no
# longer writes there; the admin's own copies of the last two kinds come back with his next scans.
OLD_PILOT_NAMES = (re.compile(r"^leftmenu\.html$"), re.compile(r"^scheduledetail_[A-Za-z0-9_]*\.html$"),
                   re.compile(r"^cmschedules_prompt\.html$"), re.compile(r"^ctweb_[A-Za-z0-9_.-]*\.html$"),
                   re.compile(r"^cmschedule_[A-Za-z0-9_]*\.html$"))


def cleanup_admin(folder):
    """1.6.2 review, once on the admin (the caller keeps the flag): the files of OLD_PILOT_NAMES in his captures folder
    (plain files only, never through a symlink) are deleted. Returns how many."""
    n = 0
    try:
        st = os.lstat(folder)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            return 0
        for f in os.listdir(folder):
            if not any(r.match(f) for r in OLD_PILOT_NAMES):
                continue
            p = os.path.join(folder, f)
            if stat.S_ISREG(os.lstat(p).st_mode):
                os.remove(p)
                n += 1
    except OSError:
        pass
    return n

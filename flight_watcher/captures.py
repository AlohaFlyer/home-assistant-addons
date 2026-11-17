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
EMP_KEY_RE = re.compile(r"(?i)\b(emp(?:loyee)?\s*(?:id|no\.?|num(?:ber)?|#)?\s*[=:#]+\s*)(\d{3,7})")
# 1.7.3 (F#55's live run, Nov 14): the pilot lookup's lines start 'pilot <employee number>:' or 'pilot <number> (<name>)',
# and EMP_RE takes only 5 to 7 digits: the number there is masked whatever its length (3 to 7), a count is not; review:
# the pickup check's 'picker <employee number> ...' too
PILOT_EMP_RE = re.compile(r"(?i)\b(pilot\s+(?=\d{3,7}\s*[:(])|picker\s+)(\d{3,7})\b")
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
# an address starts only where a run of address characters starts (the lookbehind), so a long run with no '@'
# ('x' * 200000) is tried once, not from each of its characters (quadratic: minutes); EMAIL_RE itself is tried only
# right where the last masked address ended, which is where its next match could start mid-run ('a@b.c+d@e.f')
EMAIL_START_RE = re.compile(r"(?<![\w.+-])" + EMAIL_RE.pattern)
PHONE_RE = re.compile(r"(?<![\w.:/-])(?:\+?\d[\d\s().-]{5,18}\d)(?![\w.:/-])")
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


def _emails(t):
    """Every e-mail address masked (_x), the very spans EMAIL_RE.sub masks, in linear time; only when there is an '@'."""
    if "@" not in t:
        return t
    out, pos = [], 0
    while True:
        m = (pos and EMAIL_RE.match(t, pos)) or EMAIL_START_RE.search(t, pos)
        if not m:
            out.append(t[pos:])
            return "".join(out)
        out += [t[pos:m.start()], _x(m.group(0))]
        pos = m.end()


def _phones(t):
    def one(m):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 7 or len(digits) > 15 or DATE_DIGITS_RE.match(digits):
            return m.group(0)
        if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", m.group(0).strip()):
            return m.group(0)
        if " " in m.group(0).strip() and not re.search(r"[()\-.]|\d{7}", m.group(0)):
            return m.group(0)  # numbers in a row ('1 2 3 4 5 6 7'), not one phone number
        return re.sub(r"\d", "#", m.group(0))
    return PHONE_RE.sub(one, t)


def _mask_text(t):
    t = _name_emps(t)  # 1.7.3: a name and its employee number in parentheses, before the 5 to 7 digit numbers go
    t = SEAT_EMP_RE.sub(lambda m: m.group(1) + m.group(2) + "#" * len(m.group(3)), t)
    t = EMP_RE.sub(lambda m: "#" * len(m.group(0)), t)
    t = CREW_NAME_RE.sub(lambda m: m.group(1) + (m.group(2) if m.group(2).lower() == "open" else _x(m.group(2))), t)
    t = _name_runs(t)  # before the comma pattern, so a run like 'DE LA CRUZ, MARIA' is masked whole
    return COMMA_NAME_RE.sub(lambda m: _x(m.group(0)), t)


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
_EMP_SEP = r"(?:[\s._#:=\-\xa0]|&nbsp;|%3D)*"
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
# 10001'), and capital words right before a number ('trade: DOE JANE 10001')
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
LOOKUP_EMP_RE = re.compile(r"(?i)\b(pilot\s+|picker\s+)(\d{3,7})\b(?=\s*[:(]|\s+(?:on|still|is|was)\b)")
X_NAME_NUM_RE = re.compile(r"((?<![\w'])x+(?:[ '.\-]x+)*,\s*x+(?:[ '.\-]x+)*[\s,:;(]+)(\d{4,7})(?![\d:./-])")
NUM_X_NAME_RE = re.compile(r"(?<![\d:./-])(\d{4,7})([\s,:;)]+x+(?:[ '.\-]x+)*,\s*x+)(?![\w])")
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
    s = _phones(s) if page else ADMIN_PHONE_RE.sub(lambda m: re.sub(r"\d", "#", m.group(0)), s)
    s = QUOTED_NUM_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)) + m.group(3), s)
    s = NAME_HASH_RE.sub(lambda m: _name_num(m.group(1), 0, 0, 0, m) or (
        _x(m.group(1)) + m.group(2) + "#" * len(m.group(3)) + m.group(4)), s)
    s = HASH_NAME_RE.sub(lambda m: _name_num(m.group(4), 0, 0, 0, m) or (
        m.group(1) + "#" * len(m.group(2)) + m.group(3) + _x(m.group(4))), s)
    s = SEAT_WORDS_NUM_RE.sub(lambda m: m.group(1) + _x(m.group(2)) + "#" * len(m.group(3)), s)
    s = CAPS_NUM_RE.sub(_caps_num, s)
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
    s = _emails(s)  # 1.6.2 review: e-mail addresses and phone numbers
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

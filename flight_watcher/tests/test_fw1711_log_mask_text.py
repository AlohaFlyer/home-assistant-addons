"""1.7.11 (Ryan, Nov 17: "Fix the masking text too"): the log masks blank no fixed text, no date, no schedule version.

Seen live on 1.7.10: Ryan's log (watcher.AdminLogMask, captures.mask_crew) said "no monthly credit cap (xxxx, xxx 9:
..." (smart.IGNORED's own text read as a 'Last, First'), and James's log (watcher.PilotLogMask, captures.mask) said
"schedule version ##.### (####-##)" (captures._phones took '12.002 (2026-11' for one 11-digit phone number).

- The sweep: every log.info / warning / error (and debug / exception / critical) text in flight_watcher/*.py, and the
  texts a module hands to the Watcher's log (captures, ntfy, pdbshare, smart), is put together with neutral samples
  in its holes (a pairing, a month, a schedule version, a count, a station, an exception name; the strings the code
  names, such as 'sealed' / 'not sealed' or smart.IGNORED's texts, as they are) and run through both masks: no fixed
  character may change, a hole that holds no capitalized word may not change either, and no line is a phone number
  to the phone rules. The admin's mask gets the station too (a capitalized value, 'LAS'): a fixed text must not put
  'Word, ' or ', Word' beside a value, or a value and a word read as 'Last, First'. A pilot's mask takes any two
  capitalized words in a row for a name by design (1.6.2: pages write 'FIRST LAST'), so there the samples hold no
  capitalized word but an exception's name. A text that is meant to carry a masked value goes in ALLOW with its
  reason.
- _phones: an ISO month or date and a schedule version are never a phone number or part of one; real phone numbers
  stay masked in every form, right after a date and in brackets after a version too.
- The name masks are as strong as before: 'Doe, Jane', 'DOE, JANE (10001)', 'picked up by JOHN DOE (10001)' and an
  employee number next to a date are masked on both instances.
Synthetic names and numbers only ("Doe, Jane", 10001, 808-555-01xx)."""
import ast
import itertools
import logging
import os
import re

import pytest

import captures as CAPS
from test_fw173_log_mask import load  # noqa: F401  (a Watcher as the admin or as a pilot)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVELS = {"info", "warning", "error", "debug", "exception", "critical"}
# the modules whose own log callable is the Watcher's log.info (watcher.py: Captures(log=log.info), Ntfy(log=...),
# PS.drain(log=log.info), SMART.load(warn=log.info)); run.py, cards.py, migrate.py and portal.py print their own lines
INDIRECT = {"captures.py": {"self.log"}, "ntfy.py": {"self.log"}, "pdbshare.py": {"say"}, "smart.py": {"warn"}}
FMT_RE = re.compile(r"%(\([^)]*\))?[-#0 +]*(\d+|\*)?(\.\d+)?([sdirfgxXeEc%])")
# a pairing, a schedule version, a month, a count, a station; in this order the rotation puts a version before a month
# ('schedule version 12.002 (2026-11)', as live)
SAMPLES = ("H3681", "12.002", "2026-11", 3, "LAS")
PILOT_SAMPLES = SAMPLES[:4]
CAPITALIZED = {"LAS", "ValueError"}  # capitalized samples: beside a capitalized word they make a name's shape
NUMERIC_CALLS = {"int", "len", "round", "sum", "min", "max", "abs", "float"}
# (file, a piece of the fixed text): texts meant to carry a masked value, each with its reason. None today: every
# fixed text that was blanked is reworded instead
ALLOW = {}


def _dotted(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return _dotted(n.value) + "." + n.attr
    return ""


class Module:
    """One source file: its log calls and its module-level text constants (NAME = "..." / NAME = {k: "..."})."""

    def __init__(self, name, src=None):
        self.name = name
        self.tree = ast.parse(src if src is not None else open(os.path.join(HERE, name), encoding="utf-8").read())
        self.consts = {}
        for n in self.tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                try:
                    v = ast.literal_eval(n.value)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(v, str):
                    self.consts[n.targets[0].id] = [v]
                elif isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
                    self.consts[n.targets[0].id] = list(v.values())

    def calls(self):
        for n in ast.walk(self.tree):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = _dotted(n.func)
            if isinstance(n.func, ast.Attribute) and n.func.attr in LEVELS and _dotted(n.func.value) in ("log",
                                                                                                          "self.log"):
                yield n.lineno, n.args[0], n.args[1:]
            elif f in INDIRECT.get(self.name, ()):
                yield n.lineno, n.args[0], None

    def values(self, node):
        """A hole's fixed texts when the code names them (a string, either string of an 'a if c else b', a module
        text constant or one of a module dict's texts), else None (a sample fills it)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
            return [str(node.value)]
        if isinstance(node, ast.IfExp):
            a, b = self.values(node.body), self.values(node.orelse)
            return a + b if a is not None and b is not None else None
        if isinstance(node, ast.Name) and node.id in self.consts:
            return self.consts[node.id]
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in self.consts:
            return self.consts[node.value.id]
        if isinstance(node, ast.JoinedStr):  # an f-string handed in whole: its text, a count in each of its holes
            return ["".join(v.value if isinstance(v, ast.Constant) else (self.values(v.value) or ["3"])[0]
                            for v in node.values)]
        return None

    def sample(self, node):
        """The sample kind a hole takes: 'num' (a count), 'exc' (an exception's name) or None (the rotation)."""
        if isinstance(node, ast.Call) and _dotted(node.func) in NUMERIC_CALLS:
            return "num"
        if isinstance(node, ast.BinOp) and not isinstance(node.op, (ast.Add, ast.Mod)):
            return "num"
        if isinstance(node, ast.Attribute) and node.attr == "__name__":
            return "exc"
        return None

    def template(self, node, args):
        """The text as pieces: ('c', fixed text) and ('h', conversion, format spec, fixed values or None, kind).
        A list of templates (an 'a if c else b' text gives two)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if args is None:
                return [[("c", node.value)]]
            out, pos, k = [], 0, 0
            for m in FMT_RE.finditer(node.value):
                out.append(("c", node.value[pos:m.start()]))
                if m.group(4) == "%":
                    out.append(("c", "%"))
                else:
                    a = args[k] if k < len(args) else None
                    k += 1
                    kind = "num" if m.group(4) in "dixXfgeE" else (self.sample(a) if a is not None else None)
                    spec = ("%" + (m.group(3) or "") + m.group(4)) if m.group(4) in "fgeE" else ""
                    out.append(("h", m.group(4), spec, self.values(a) if a is not None and kind != "num" else None,
                                kind))
                pos = m.end()
            out.append(("c", node.value[pos:]))
            return [out]
        if isinstance(node, ast.JoinedStr):
            outs = [[]]
            for v in node.values:
                if isinstance(v, ast.Constant):
                    outs = [o + [("c", v.value)] for o in outs]
                else:
                    spec = "".join(x.value for x in (v.format_spec.values if v.format_spec else ())
                                   if isinstance(x, ast.Constant))
                    kind = "num" if spec else self.sample(v.value)
                    outs = [o + [("h", "r" if v.conversion == ord("r") else "s", spec and "{:" + spec + "}",
                                  self.values(v.value), kind)] for o in outs]
            return outs
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return [a + b for a in self.template(node.left, args) for b in self.template(node.right, args)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            right = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            return self.template(node.left, list(right))
        if isinstance(node, ast.IfExp):
            return self.template(node.body, args) + self.template(node.orelse, args)
        if isinstance(node, ast.Call) and _dotted(node.func).endswith("scrub") and node.args:
            return self.template(node.args[0], args)
        return [[("h", "s", "", None, None)]]


def _fill(conv, spec, v):
    if spec.startswith("{:"):
        for n in (3, 3.0):
            try:
                return spec.format(n)
            except (ValueError, TypeError):
                pass
    if spec:
        return spec % 3.0
    return repr(v) if conv == "r" else str(v)


def renderings(tpl, samples=SAMPLES):
    """Each way to fill tpl: every rotation of samples over its free holes, times each fixed value of its named holes
    (at most 16 combinations). Yields (text, flags, held): flags[i] is True for a fixed character, held[i] the
    sample that put a hole's character there."""
    named = [p[3] for p in tpl if p[0] == "h" and p[3] is not None]
    combos = list(itertools.islice(itertools.product(*named), 16)) if named else [()]
    for shift in range(len(samples)):
        for combo in combos:
            text, flags, held, free, nv = [], [], [], 0, 0
            for p in tpl:
                if p[0] == "c":
                    s, f, h = p[1], True, None
                elif p[3] is not None:
                    s, f, h = _fill(p[1], "", combo[nv]), True, None
                    nv += 1
                else:
                    v = (3 if p[4] == "num" else "ValueError" if p[4] == "exc"
                         else samples[(free + shift) % len(samples)])
                    free += 1
                    s, f, h = _fill(p[1], p[2], v), False, str(v)
                text.append(s)
                flags.extend([f] * len(s))
                held.extend([h] * len(s))
            yield "".join(text), flags, held


def _admin(t):
    return CAPS.mask_crew(t)


def _pilot(t):
    return CAPS.mask(t, ())


def modules():
    return [Module(n) for n in sorted(os.listdir(HERE)) if n.endswith(".py")]


def sweep(mods):
    """Every (file, line, mask, text, masked) where a mask changes a fixed character or a hole that holds no
    capitalized word, or where the phone rules take a part of the line."""
    bad = []
    for mod in mods:
        for line, node, args in mod.calls():
            for tpl in mod.template(node, args):
                fixed = "".join(p[1] for p in tpl if p[0] == "c")
                if any(f == mod.name and piece in fixed for f, piece in ALLOW):
                    continue
                for who, fn, samples in (("admin", _admin, SAMPLES), ("pilot", _pilot, PILOT_SAMPLES)):
                    for text, flags, held in renderings(tpl, samples):
                        if CAPS._phones(text) != text or CAPS.ADMIN_PHONE_RE.search(text):
                            bad.append((mod.name, line, "phone", text, CAPS._phones(text)))
                        out = fn(text)
                        if out != text and (len(out) != len(text) or any(
                                a != b and (f or h not in CAPITALIZED) for a, b, f, h in zip(text, out, flags, held))):
                            bad.append((mod.name, line, who, text, out))
    return bad


def _report(bad):
    seen, lines = set(), []
    for name, line, who, text, out in bad:
        if (name, line, who) not in seen:
            seen.add((name, line, who))
            lines.append(f"{name}:{line} [{who}]\n  {text}\n  {out}")
    return lines


def test_no_fixed_log_text_is_blanked_by_either_mask():
    mods = modules()
    assert sum(1 for m in mods for _c in m.calls()) > 500  # the sweep reads every log call
    assert all(any(True for _c in m.calls()) for m in mods if m.name in INDIRECT)  # and the modules' own callables
    lines = _report(sweep(mods))
    assert not lines, "\n".join(lines)


def test_the_sweep_finds_the_lines_of_1_7_10():
    """The sweep fails on each kind of line 1.7.10 blanked: its cap_credit text on the admin's mask, a pilot's
    'SWAP DRAFT' and 'Flight Watcher', and 'KB, <Word>'; the live version line it renders as it was logged."""
    old = Module("smart.py", 'IGNORED = {"cap_credit": "no monthly credit cap (Ryan, Nov 9: the PWA does not cap '
                             'voluntary adds)"}\n\n\ndef load(warn, k):\n    warn(f"smart.json {k} ignored: '
                             '{IGNORED[k]}")\n')
    got = sweep([old])
    assert any(who == "admin" and "(xxxx, xxx 9:" in out for _n, _l, who, _t, out in got), got
    old = Module("watcher.py", 'log.info("SWAP DRAFT (%s): give %s", a, b)\n'
                               'log.warning("pilot db: the file is from a newer Flight Watcher")\n'
                               'log.info("upload %s (%d KB, %s)", a, n, "Sealed" if x else "not sealed")\n'
                               'log.info("contact list (%d KB, %s) not read", kb, ext)\n'
                               'log.info("MQTT %s refused", sub)\n')
    assert sorted({(line, who) for _n, line, who, _t, _o in sweep([old])}) == [
        (1, "pilot"), (2, "pilot"), (3, "admin"), (3, "pilot"), (4, "admin")]  # 'MQTT LAS': a pilot's by design
    now = Module("watcher.py", 'log.info("schedule version %s (%s)", v, mk)\n')
    texts = [t for _l, node, args in now.calls() for tpl in now.template(node, args) for t, _f, _h in renderings(tpl)]
    assert "schedule version 12.002 (2026-11)" in texts and not sweep([now])


# ------------------------------------------------------------------------------------ C: the live lines, made up values
def test_live_line_1_the_cap_credit_text_reads_whole_on_the_admin_and_a_pilot():
    import smart
    text = f"smart.json cap_credit ignored: {smart.IGNORED['cap_credit']}"
    assert "Ryan's rule of Nov 9" in text and "Ryan, Nov" not in text
    assert _admin(text) == text and _pilot(text) == text


def test_live_line_2_a_schedule_version_and_its_month_stay_on_a_pilot():
    for line in ("schedule version 12.002 (2026-11)", "schedule version 3.017 (2026-12)",
                 "schedule version 12.002 (2026-11) imported from the recorder",
                 "pilot lookup: schedule version 11.003, 11.004 (2026-11, from the FLICA schedule)",
                 "crew index: H3681 2026-11-17 flew as FO (read)"):
        assert _pilot(line) == line and _admin(line) == line and CAPS.mask_crew(line, page=True) == line


@pytest.mark.parametrize("line", [
    "Swap draft (DRAFT): give H3681 take H3605 folder 003.152 bcid 003.152 form ok",
    "Drop ready (DRAFT): H3681|2026-11-17, grid green on 17, 18; form ok",
    "pilot db: the file is from a newer release of this app; it is left as it is (roll forward to use it)",
    "trade seen on the schedule (2026-11-17): Trade H3681 for H3605 LAS; Pay-Gross +$120.00",
    "pilot lookup: schedule version 11.003 (2026-11, from the FLICA schedule)",
    "alert email: H3681|17Nov entered the pot at 2026-11-17T08:00:00-10:00 (pickup speed rescored)",
    "contact list read again (parser 3): 12 pilots, 4 with HAL notes, 0 notes segments not read",
    "upload: contact list (CSV, 3 KB) not read: ValueError",
    "upload: contact list (XLSX, 3 KB) gave no pilot contacts (40 lines); not kept",
])
def test_the_reworded_texts_read_whole_on_both_instances(line):
    """Each text 1.7.11 rewords, with made-up values (a capitalized one where the code can hand one in)."""
    assert _admin(line) == line and _pilot(line) == line and CAPS.mask_crew(line, page=True) == line


def test_the_live_lines_through_the_watchers_log_filters(load, caplog):  # noqa: F811
    for instance in (None, "pilot2"):
        W = load(instance)
        with caplog.at_level(logging.INFO, logger="flight_watcher"):
            caplog.clear()
            W.log.info("schedule version %s (%s)", "12.002", "2026-11")
            W.log.info("smart.json %s ignored: %s", "cap_credit", __import__("smart").IGNORED["cap_credit"])
            W.log.info("a page line: %s", "Doe, Jane (10001) 2026-11-17 808-555-0101")
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "schedule version 12.002 (2026-11)" in text, (instance, text)
        assert "Ryan's rule of Nov 9: the PWA does not cap voluntary adds" in text, (instance, text)
        for leak in ("Doe", "Jane", "10001", "555-0101"):
            assert leak not in text, (instance, leak, text)


# ------------------------------------------------------------------------------------------------- B: _phones
PHONES = ("(808) 555-0101", "808-555-0101", "808.555.0101", "+1 808 555 0101", "8085550101", "808 555 0101",
          "1-808-555-0101", "+18085550101", "+1 (808) 555-0101")


@pytest.mark.parametrize("phone", PHONES)
def test_a_real_phone_number_stays_masked_in_every_form(phone):
    for fn in (_pilot, lambda t: CAPS.mask_crew(t, page=True)):
        for line in (f"call {phone} now", f"2026-11-17 {phone}", f"schedule version 12.002 ({phone})",
                     f"{phone} 2026-11", f"12.002 {phone}"):
            out = fn(line)
            assert not re.search(r"555|0101", out), (line, out)
            assert ("2026-11" in out) == ("2026-11" in line) and ("12.002" in out) == ("12.002" in line), (line, out)


@pytest.mark.parametrize("line, out", [
    ("2026-11-17 808-555-0101", "2026-11-17 ###-###-####"),
    ("schedule version 12.002 (808-555-0101)", "schedule version 12.002 (###-###-####)"),
    ("schedule version 12.002 (+1 808 555 0101)", "schedule version 12.002 (+# ### ### ####)"),
    ("schedule version 12.002 (2026-11)", "schedule version 12.002 (2026-11)"),
    ("versions 12.002 12.003 12.004", "versions 12.002 12.003 12.004"),
    ("2026-11-01 2026-11-30", "2026-11-01 2026-11-30"),
    ("1 2 3 4 5 6 7", "1 2 3 4 5 6 7"),  # numbers in a row, not one phone
    ("20261117", "20261117"),  # YYYYMMDD, as before
    ("pairing 2026-11-1234", "pairing ####-##-####"),  # '-1234' after it: no month, read as before
    # a phone at the end of a sentence or a clause, and a phone with a number after it: masked (before 1.7.11 the dot,
    # the hyphen or the 16 digits together let it through, unless a date after it happened to make the count right)
    ("call 808-555-0101.", "call ###-###-####."), ("call 808-555-0101. Then", "call ###-###-####. Then"),
    ("+1 808 555 0101- 2026-11-17", "+# ### ### ####- 2026-11-17"),
    ("call 1-808-555-0101 10001 now", "call #-###-###-#### 10001 now"),  # 10001: EMP_RE's (a pilot's mask)
    ("v1.2.3.4567", "v1.2.3.4567"), ("H3681 13:05:00.", "H3681 13:05:00."),
])
def test_phones_dates_and_versions(line, out):
    assert CAPS._phones(line) == out
    assert CAPS._phones(out) == out


def test_a_version_shaped_piece_of_a_dotted_phone_is_no_version():
    """'808.555.0101' and '1.808.555.0101' hold no 'n.nnn' or 'nn.nnn' with nothing digit-like around it."""
    assert CAPS.NOT_PHONE_RE.search("808.555.0101") is None
    assert CAPS.NOT_PHONE_RE.search("1.808.555.0101") is None
    assert CAPS.NOT_PHONE_RE.search("+1 808 555 0101") is None
    assert [m.group(0) for m in CAPS.NOT_PHONE_RE.finditer("12.002 (2026-11) 2026-11-17 3.017.")] == [
        "12.002", "2026-11", "2026-11-17", "3.017"]


# ------------------------------------------------------------------------- C: the name masks are as strong as before
# 'trade: DOE JANE 10001' and 'Captain: DOE JOHN 10001' next to a date: in the admin's page text the date's
# neighbour was masked first (as a phone before 1.7.11, as a number beside a date now), so the name rules that need
# its digits missed the name; they take a masked number too now
NAMED = ("Doe, Jane", "DOE, JANE (10001)", "picked up by JOHN DOE (10001)", "Doe Jr, Jane (10001)",
         "captain='Doe, Jane (10001)'", "CA 10001 DOE, JANE FO open", "trade: DOE JANE 10001",
         "Captain: DOE JOHN 10001")


@pytest.mark.parametrize("line", NAMED)
def test_a_crew_name_is_masked_on_both_instances(line):
    for who, fn in (("admin", _admin), ("admin page", lambda t: CAPS.mask_crew(t, page=True)), ("pilot", _pilot)):
        for text, keep in ((f"2026-11-17 {line} on H3681 (12.002)", ("2026-11-17 ", " on H3681 (12.002)")),
                           (f"{line} 2026-11-17", (" 2026-11-17",)), (f"{line} 12.002", (" 12.002",)), (line, ())):
            out = fn(text)
            for leak in ("Doe", "DOE", "Jane", "JANE", "John", "JOHN", "10001"):
                assert leak not in out, (who, text, out)
            for k in keep:
                assert k in out, (who, text, out)


@pytest.mark.parametrize("line", [
    "2026-11-17 emp# 10001", "pilot 10001: 2026-11-17 read", "2026-11-17 (Doe, Jane 10001)",
    "2026-11 CA 10001", "12.002 EmployeeID=10001", "10001 Doe, Jane 2026-11-17",
])
def test_an_employee_number_next_to_a_date_stays_masked_on_both_instances(line):
    for fn in (_admin, lambda t: CAPS.mask_crew(t, page=True), _pilot):
        out = fn(line)
        assert "10001" not in out, (line, out)


@pytest.mark.parametrize("line, out", [
    ("2026-11-17 10001", "2026-11-17 #####"), ("10001 2026-11-17", "##### 2026-11-17"),
    ("10001 (2026-11-17)", "##### (2026-11-17)"), ("12.002 10001", "12.002 #####"),
])
def test_a_bare_number_beside_a_date_or_version_is_masked_as_before(line, out):
    """The phone rule took it with the date before 1.7.11: the pilot's mask (EMP_RE) and the admin's page text mask it
    still; the date or the version stays."""
    assert _pilot(line) == out
    assert CAPS.mask_crew(line, page=True) == out

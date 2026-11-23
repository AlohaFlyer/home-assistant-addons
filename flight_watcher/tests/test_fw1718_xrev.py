"""1.7.18 cross-item review fixes (Nov 18), each against the earlier item it corrects. Synthetic data only: made-up
pairings (H9xxx), made-up airports' timetables, no names; no FLICA, nothing on Pako.

1. Item 3 (1.7.12, the Data age stamp): on a wide schedule header the month arrows, the title and Now slid left as the
   stamp's text grew past its 14em minimum ("2 h 10 min, very stale" by 11 px, "over 1 h 5 min, Watcher offline" by
   59 px) and back on the whole hour. The stamp is one fixed box now (21em), so nothing beside it moves.
2. Item B (1.7.18, the lock switch) with item 3: on a phone the header took three lines (the switch alone, the month,
   the stamp alone, 86 px). The stamp now sits on the switch's line, at its right (a long text wraps inside that
   box), so the header is two lines (70 px) and the month's line never moves.
3. Item 8 (1.7.17): the pot_table macro's Commutable chip and the pot table's Key line had no "Pending on Pako" section
   and the snapshot had no Key line. Both are in ha/README.md now (the macro text in git, rendered here with Jinja2),
   and the one snapshot carries the Key line with its sha pinned. Applied on Pako 2026-11-18 (the section is an
   "Applied on Pako" one now, with how the call was placed and the check's result).
4. Item 6 (1.7.15): the pay figures on every marked idea (about 120 bytes each) made the 12 KB cap keep 19 marked ideas
   where 1.7.11 kept 24. Over the cap, the marked ideas now give up their pay figures from the end before any is
   left out, so "ideas" keeps what 1.7.11 kept (the head ones keep their figures while they fit).
5. Item 6 (1.7.15): pub()'s backstop never saw an automatic idea on event/swap_test (the draft record had no auto key).
   The record carries the idea's auto flag now."""
import hashlib
import json
import os
import re

import pytest

from test_fw1712_data_age import ROOT, _sched
from test_fw171_cards import _browser, _card, _page as _portal_page
from test_fw1715_auto_swap import _hm, _load, _pubs, _row, _sensor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = "flight-watcher-schedule-card"

# ---------------------------------------------------------------- 1 and 2: the schedule header and its stamp
# (last check, its last_changed) -> the stamp's text at the harness's clock (Nov 10 11:30 UTC), normal checks every 6 min
LASTS = [
    (("2026-11-10T11:27:00+00:00", None), "Data age 3 min"),
    (("2026-11-10T09:30:00+00:00", None), "Data age 2 h, very stale"),
    (("2026-11-10T09:29:00+00:00", None), "Data age 2 h 1 min, very stale"),
    (("2026-11-10T09:20:00+00:00", None), "Data age 2 h 10 min, very stale"),
    (("2026-11-09T11:31:00+00:00", None), "Data age 23 h 59 min, very stale"),
    (("2026-10-30T12:30:00+00:00", None), "Data age 10 d 23 h, very stale"),
    (("unavailable", "2026-11-10T10:25:00+00:00"), "Data age over 1 h 5 min, Watcher offline"),
    (("unavailable", "2026-11-09T11:31:00+00:00"), "Data age over 23 h 59 min, Watcher offline"),
    (("unavailable", "2026-10-30T12:30:00+00:00"), "Data age over 10 d 23 h, Watcher offline"),
    (("unknown", None), "Data age unknown"),
]

HEAD_JS = """([tag, st]) => { const c = mount(tag, {}, st); const r = c.shadowRoot;
  return new Promise((ok) => setTimeout(() => {
    const q = (s) => r.querySelector(s), B = (e) => { const b = e.getBoundingClientRect();
      return {l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height}; };
    const ag = q('.hd2 .ag[data-age]'), hd = q('.hd2'), rg = document.createRange();
    rg.selectNodeContents(ag);
    const lines = [...rg.getClientRects()].map((x) => Math.round(x.top)), tx = rg.getBoundingClientRect();
    ok({text: ag.textContent, ag: B(ag), lock: B(q('.hd2 .lock')), hd: B(hd), prev: B(q('.hd2 .nav[data-nav="-1"]')),
        next: B(q('.hd2 .nav[data-nav="1"]')), h3: B(q('.hd2 h3')), now: B(q('.hd2 .nav.now')),
        textRight: tx.right, lines: new Set(lines).size, clip: [ag.scrollWidth - ag.clientWidth, ag.scrollHeight - ag.clientHeight],
        hdOver: hd.scrollWidth - hd.clientWidth, page: document.documentElement.scrollWidth,
        dark: c.hasAttribute('dark'), rf: q('.hd2 .rfb') ? B(q('.hd2 .rfb')) : null}); }, 80)); }"""


def _right(g):
    """1.8.2: where the stamp's box ends: the header's right, or (Home Assistant's copy) the refresh button's left,
    the button then at the header's right (in the portal's copy there is no button)."""
    if g["rf"] is None:
        return g["hd"]["r"]
    assert abs(g["rf"]["r"] - g["hd"]["r"]) <= 1 and g["rf"]["t"] <= g["ag"]["b"], g["rf"]
    assert 0 <= g["rf"]["l"] - g["ag"]["r"] <= 12, (g["rf"], g["ag"])  # next to Data age
    return g["ag"]["r"]


def _head(width, pilot, scheme):
    """The header at each stamp text of LASTS on one page (the HA copy or the portal's pilot2 copy)."""
    tag = SC + ("-pilot2" if pilot else "")
    out = []
    with _browser() as b:
        pg = _portal_page(b, [_card("schedule-card", pilot=pilot)], width=width, scheme=scheme)
        for (last, lc), text in LASTS:
            g = pg.evaluate(HEAD_JS, [tag, _sched(last=last, pilot=pilot, **({"lc": lc} if lc else {}))])
            assert g["text"] == text, (width, pilot, g["text"])
            out.append(g)
            pg.evaluate("() => { document.querySelector('.view').innerHTML = ''; }")
        pg.context.close()
    return out


def _spot(g):
    """Where the month controls are: the arrows, the title and Now (left and top, to the pixel) and the header's height."""
    return tuple(round(g[k][x]) for k in ("prev", "h3", "next", "now") for x in ("l", "t")) + (round(g["hd"]["h"]),)


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [761, 820, 1024, 1280])  # 1.8.2: one row from 761 px (the refresh button's room)
def test_a_wide_header_keeps_the_month_controls_put_at_every_stamp_text(width, scheme):
    """Item 3 (1.7.12): one row, the stamp at its right in one fixed box, so the arrows, the month and Now sit at the
    same pixels whether the stamp reads 3 min, 2 h, 2 h 10 min very stale or over 23 h 59 min Watcher offline."""
    for pilot in (False, True):
        got = _head(width, pilot, scheme)
        assert len({_spot(g) for g in got}) == 1, (width, pilot, [(g["text"], _spot(g)) for g in got])
        assert len({(round(g["ag"]["l"]), round(g["ag"]["w"])) for g in got}) == 1, (width, pilot)  # one box
        for g in got:
            where = (width, pilot, scheme, g["text"])
            assert g["dark"] == (scheme == "dark"), where
            assert g["clip"][0] <= 0 and g["clip"][1] <= 0 and g["hdOver"] <= 0 and g["page"] <= width, where
            assert g["lines"] == 1, where  # every text on one line in this font: nothing cut, nothing hidden
            assert g["ag"]["l"] >= g["now"]["r"] and abs(g["ag"]["r"] - _right(g)) <= 1, where  # right of Now
            assert abs(g["textRight"] - g["ag"]["r"]) <= 1.5, where  # the text sits at the box's right
            assert abs((g["lock"]["t"] + g["lock"]["b"]) / 2 - (g["h3"]["t"] + g["h3"]["b"]) / 2) < 12, where  # one row
            assert round(g["hd"]["h"]) == 44, where


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [360, 390, 430, 701, 760])  # 1.8.2: and 701 to 760 px (no room for one row)
def test_a_phone_header_is_two_lines_with_the_stamp_beside_the_switch(width, scheme):
    """Item B (1.7.18) with item 3 (1.7.12): line 1 the Lock switch with the stamp at its right, line 2 the arrows,
    the month and Now. A long stamp text wraps inside its box under the switch's 44 px, so neither line moves."""
    for pilot in (False, True):
        got = _head(width, pilot, scheme)
        assert len({_spot(g) for g in got}) == 1, (width, pilot, [(g["text"], _spot(g)) for g in got])
        for g in got:
            where = (width, pilot, scheme, g["text"])
            lk, ag, hd = g["lock"], g["ag"], g["hd"]
            assert ag["t"] >= lk["t"] - 0.5 and ag["b"] <= lk["b"] + 0.5, where  # on the switch's line
            assert ag["l"] >= lk["r"] and abs(ag["r"] - _right(g)) <= 1 and abs(g["textRight"] - ag["r"]) <= 1.5, where
            assert g["prev"]["t"] >= lk["b"] and g["now"]["t"] >= lk["b"], where  # the month's line under it
            mids = [(g[k]["t"] + g[k]["b"]) / 2 for k in ("prev", "h3", "next", "now")]
            assert max(mids) - min(mids) < 12, where  # the arrows, the month and Now together
            assert hd["h"] <= 72 and g["lines"] <= 3, where  # two lines (it was 86 px, three)
            assert g["clip"][0] <= 0 and g["clip"][1] <= 0 and g["hdOver"] <= 0 and g["page"] <= width, where


def test_the_stamp_box_and_the_phone_order_are_in_every_copy():
    """The HA copy, a second pilot's dashboard copy and the portal's pilot2 copy carry the same header rules."""
    import cards
    import portal as PT
    built = cards.build("9.9.9", ["pilot2"])
    for src in (built[f"{SC}.js"], built[f"{SC}-pilot2.js"], PT.portal_card(built[f"{SC}-pilot2.js"])):
        assert ".hd2 .ag{margin-left:auto;text-align:right;white-space:normal;min-width:0;flex:0 0 21em}" in src
        assert "@media (max-width:700px){.hd2 .ag{order:1;flex:1 1 0}.hd2 .sp{order:2}.hd2 .nav,.hd2 h3{order:3}}" in src
        assert "min-width:14em" not in src


# ---------------------------------------------------------------- 3: 1.7.17's Pako edits in git (applied 2026-11-18)
SNAP = os.path.join(ROOT, "ha", "dashboard_flight_watcher.json")
KEY_LINE = ("- **Commutable KOA**: you can commute from that airport both ways: 2 scheduled nonstops arriving HNL before "
            "report (PWA 26.QQ.2) and 1 nonstop home leaving at least your home gap after release (home_gap_min in your "
            "smart.json, 60 min unless set), same day (release 30 min after block-in when clearing customs, PWA 2.19.b), "
            "from your smart.json timetables. No chip = not commutable, or not known")
HEAD_1717 = "## Applied on Pako 2026-11-18 about 08:18 HST (1.7.17): Commutable chip in the pot table\n"
HEAD_1715 = "## Applied on Pako 2026-11-18 about 08:04 HST (1.7.15)"


def _pot_md(text):
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "markdown" and "pot_table" in (x.get("content") or ""):
                out.append(x["content"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(json.loads(text))
    return out


def _section(readme, head):
    i = readme.index(head)
    return readme[i:readme.index("\n## ", i + len(head))]


def test_the_1717_pot_table_edits_are_applied_on_pako_with_the_key_line_in_the_snapshot():
    text = open(SNAP, encoding="utf-8").read()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"  # the Refresh format
    (md,) = _pot_md(text)
    key = md[md.index("<details><summary><b>Key</b></summary>"):]
    lines = key.split("\n")
    i = lines.index("- **CBA rest**: legal, but under the 11 h company minimum")
    assert lines[i + 1] == KEY_LINE and md.count("Commutable") == 1  # right after CBA rest, once
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    readme = open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read()
    sec = _section(readme, HEAD_1717)
    at = [readme.index(h) for h in (HEAD_1715, HEAD_1717, "## Applied on Pako 2026-11-13")]
    assert at == sorted(at)  # after the 1.7.15 section, before the older applied ones (release order)
    assert "Pending on Pako" not in readme  # applied on Pako 2026-11-18: no pending section is left
    # Pako reads the snapshot's sha (every edit applied); the 1.7.15 one (6678f813...) is the snapshot without the Key
    # line
    assert sha in sec and "6678f813" in sec and "be03a0a4" not in sec
    flat = " ".join(sec.split())
    for part in ("`pot_table`", "flight_watcher.jinja", "{{ comm_chip(p) }}", "homeassistant.reload_custom_templates",
                 "Ryan's yes", "Undo", "1.7.17 go-live", "PWA 26.QQ.2", "PWA 2.19.b"):
        assert part in flat, part
    # how the call was placed on Pako (pot_table prints Fits and FAR in one loop over extra.cols): gated to the FAR
    # column, so it prints once per row; the reload at 08:19 HST and the check's output are recorded
    for part in ("extra.cols", "{% if k == 'far' %}{{ comm_chip(p) }}{% endif %}", "08:19 HST",
                 "it rendered exactly that", "2 of the 3 pot rows", "remove the whole"):
        assert part in flat, part
    assert KEY_LINE in sec.split("\n")  # the line added, as the snapshot has it
    # the 1.7.15 section names the snapshot with the first three edits alone, and the snapshot's sha (Pako's now)
    s15 = _section(readme, HEAD_1715)
    assert "6678f813ccdc4a6e2e1ab8837ccddffbd3de6f0c1de874a5cd8a1c48ea9a5cc5" in s15 and sha in s15
    assert chr(0x2014) not in readme and chr(0x2014) not in text


def _blocks(sec, lang):
    return re.findall(r"```" + lang + r"\n(.*?)\n```", sec, re.S)


def test_the_comm_chip_macro_in_the_readme_renders_as_it_says():
    """The macro and its check, as the README gives them, in a sandbox with Home Assistant's match test."""
    jinja2 = pytest.importorskip("jinja2")
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    sec = _section(open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read(), HEAD_1717)
    macro, call, check = _blocks(sec, "jinja")
    assert macro.startswith("{%- macro comm_chip(p) -%}") and macro.endswith("{%- endmacro -%}")
    assert call == "{{ comm_chip(p) }}"
    env = ImmutableSandboxedEnvironment(loader=jinja2.DictLoader({"flight_watcher.jinja": macro}))
    env.tests["match"] = lambda v, pat: bool(re.match(pat, str(v)))  # as Home Assistant registers it
    want = re.search(r"It must give `([^`]+)`", sec).group(1)
    assert env.from_string(check).render() == want
    assert want == "[ **Commutable KOA LAS**][ **Commutable KOA**][][][ **Commutable LAS**][ **Commutable KOA LAS**][]"
    # a pot_table row cell with the call on the Fits / FAR text's line: words in bold, nothing for a row without cm
    row = env.from_string("{%- from 'flight_watcher.jinja' import comm_chip -%}| {{ p.fit }} {{ p.far }}{{ comm_chip(p) }} |")
    assert row.render(p={"fit": "Fits", "far": "OK", "cm": ["KOA", "LAS"]}) == "| Fits OK **Commutable KOA LAS** |"
    assert row.render(p={"fit": "Fits", "far": "OK"}) == "| Fits OK |"
    # as placed on Pako (2026-11-18): Fits and FAR are printed by one loop over the columns, the call gated to the FAR
    # column at the end of the cell, so it prints once per row, in the FAR cell, and a row without cm is unchanged
    gated = re.search(r"`(\{% if k == 'far' %\}\{\{ comm_chip\(p\) \}\}\{% endif %\})`", sec).group(1)
    assert call in gated
    cells = env.from_string("{%- from 'flight_watcher.jinja' import comm_chip -%}|{% for k in cols %} {{ p[k] }}"
                            + gated + " |{% endfor %}")
    assert cells.render(p={"fit": "Fits", "far": "OK", "cm": ["KOA", "LAS"]}, cols=["fit", "far"]) == \
        "| Fits | OK **Commutable KOA LAS** |"
    assert cells.render(p={"fit": "Fits", "far": "OK"}, cols=["fit", "far"]) == "| Fits | OK |"


def test_the_dashboard_pot_key_matches_the_pot_cards_key():
    """The HA Key line says what the pot card's Key says (1.7.17 review: the home gap, never a fixed 60)."""
    card = open(os.path.join(HERE, "www", "flight-watcher-pot-card.js"), encoding="utf-8").read()
    m = re.search(r"<li><b>Commutable</b> and an airport = (.*?)\.</li>", card)
    assert m and m.group(1) in KEY_LINE.replace("- **Commutable KOA**: ", "")


# ---------------------------------------------------------------- 4: the marked ideas' pay figures and the 12 KB cap
NEW_KEYS = ("pay", "pay_days", "ppd", "for_pay", "for_days", "for_ppd", "ppd_gain", "auto")
MARKED = {f"H90{n:02d}|2026-11-{18 + 2 * n:02d}": f"2026-11-{19 + 2 * n:02d}" for n in range(5)}  # 2 days each
UNMARKED = {"H9010|2026-11-28": "2026-11-29"}  # 5:00 a day: the pot trips on its days pay more, automatic ideas
URL = "https://ha2.flica.net/full/mobilepairing.cgi?PID={}&DATE={}&FROM=MobileOpentimePot&CurrentPage=1"


def _busy(W):
    """A busy month of marks: 5 marked trips and 1 not marked, 6 better pot trips on each one's days (more soft time,
    more credit), each priced at the year 5 rate."""
    own = {**MARKED, **UNMARKED}
    W.S["schedule"]["2026-11"]["items"] = [{"trip": k.split("|")[0], "start": k.split("|")[1], "end": e, "lay": "LAX"}
                                           for k, e in own.items()]
    W.S["own_trips"] = {k: {"credit": "10:00", "blk": "8:00", "soft": "2:00", "seat": "FO"} for k in own}
    W.S["trade_away"] = list(MARKED)
    rows, n = [], 0
    for k, end in own.items():
        start = k.split("|")[1]
        for j in range(6):
            soft = 2.5 + 0.12 * n
            pid = f"H93{n:02d}"
            rows.append(_row(pid, start, end, _hm(12 + 0.5 * j), _hm(12 + 0.5 * j - soft),
                             detail_url=URL.format(pid, start.replace("-", ""))))
            n += 1
    return rows


def _shape_1711(idea):
    return {k: v for k, v in idea.items() if k not in NEW_KEYS}


def _kept_1711(W, marked, marks):
    """How many marked ideas 1.7.11 listed for the same ideas: its payload ({count, ideas[:30], marked}, its idea
    without the 1.7.15 keys) through the same cap."""
    old = {"count": len(marked), "ideas": [_shape_1711(i) for i in marked[:30]], "marked": marks}
    return len(W.cap_attrs("swap/state", old)["ideas"])


def test_a_busy_month_keeps_as_many_marked_ideas_as_1711(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "")
    rows = _busy(W)
    monkeypatch.setattr(W, "ATTR_MAX", 10 ** 7)  # every idea, uncut: what the scan finds
    W.swap_scan(rows)
    full = _sensor(W)
    marked = full["ideas"]
    assert len(marked) == 30 and full["count"] - full["auto_count"] > 30 and full["auto_count"] >= 6
    assert all(isinstance(i["ppd_gain"], float) and i["auto"] is False for i in marked)  # priced, marked
    monkeypatch.setattr(W, "ATTR_MAX", 12000)
    W.FAKE.msgs.clear()
    W.swap_scan(rows)
    s = _sensor(W)
    base = _kept_1711(W, marked, list(MARKED))
    assert base == 24  # 1.7.11 in this month (2307cce gives the same: 24 listed, 6 left out)
    assert W.attr_size(s) <= 12000 and s["auto_ideas"] == [] and s["auto_more"] == s["auto_count"] == full["auto_count"]
    assert len(s["ideas"]) >= base and s["trimmed"] == 30 - len(s["ideas"])  # it was 19, 11 left out
    assert [i["pairing"] for i in s["ideas"]] == [i["pairing"] for i in marked[:len(s["ideas"])]]  # 1.7.11's order
    # the figures stay on the first ones while they fit; the rest are 1.7.11's ideas exactly
    priced = [i for i in s["ideas"] if "ppd_gain" in i]
    assert priced and s["ideas"][:len(priced)] == marked[:len(priced)] and len(priced) < len(s["ideas"])
    assert s["ideas"][len(priced):] == [_shape_1711(i) for i in marked[len(priced):len(s["ideas"])]]
    # every reader shows "-" for a bare idea's pay, never a wrong figure: the cards read them only as numbers
    assert not any(k in i for i in s["ideas"][len(priced):] for k in NEW_KEYS)


@pytest.mark.parametrize("extra", [0, 40, 80, 120, 160, 200, 240, 280, 320, 360, 400, 440])
def test_the_cap_never_lists_fewer_marked_ideas_than_1711_less_one(tmp_path, monkeypatch, extra):
    """Across idea sizes (a longer layover text each step): never fewer than 1.7.11 kept but for the one the six new
    counts (under 100 bytes) can cost; and never fewer figures than fit."""
    W = _load(tmp_path, monkeypatch, "")
    rows = [dict(r, layover="L" * (3 + extra // 4)) for r in _busy(W)]
    monkeypatch.setattr(W, "ATTR_MAX", 10 ** 7)
    W.swap_scan(rows)
    marked = _sensor(W)["ideas"]
    monkeypatch.setattr(W, "ATTR_MAX", 12000)
    W.FAKE.msgs.clear()
    W.swap_scan(rows)
    s = _sensor(W)
    base = _kept_1711(W, marked, list(MARKED))
    extra_b = W.attr_size({k: s[k] for k in ("auto_ideas", "auto_count", "auto_shown", "auto_more", "auto_max", "priced")})
    assert extra_b < 100
    assert base - 1 <= len(s["ideas"]) and W.attr_size(s) <= 12000, (base, len(s["ideas"]))
    n = sum(1 for i in s["ideas"] if "ppd_gain" in i)
    if n < len(s["ideas"]):  # one more idea with its figures would not fit
        more = [marked[j] if j <= n else i for j, i in enumerate(s["ideas"])]
        assert W.attr_size(dict(s, ideas=more)) > 12000


def test_a_month_that_fits_keeps_every_figure(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "")
    rows = _busy(W)
    W.S["trade_away"] = list(MARKED)[:1]
    W.swap_scan(rows[:4] + rows[-4:])  # 8 ideas for the marked trip, 4 automatic ones
    s = _sensor(W)
    assert "trimmed" not in s and len(s["ideas"]) == 8 and len(s["auto_ideas"]) == 4 and W.attr_size(s) <= W.ATTR_MAX
    assert all(i["auto"] is False and isinstance(i["ppd_gain"], float) for i in s["ideas"])


# ---------------------------------------------------------------- 5: pub()'s backstop on event/swap_test
class _GuardBypassed(dict):
    """An automatic idea whose first auto read (swap_test's own return) says False: a later edit that lost that return."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reads = 0

    def get(self, k, d=None):
        if k == "auto":
            self.reads += 1
            if self.reads == 1:
                return False
        return super().get(k, d)


def test_a_draft_carries_the_ideas_auto_flag_and_the_backstop_holds_on_event_swap_test(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "")
    marked = {"for": "H9001|2026-11-20", "for_trip": "H9001", "pairing": "H9101", "start": "20Nov", "key": "k1",
              "report": "", "auto": False}
    W.swap_test(dict(marked))
    (draft,) = _pubs(W, "event/swap_test")
    assert draft["auto"] is False and draft["give"] == "H9001 2026-11-20" and draft["sent"] is False
    assert W.S["swap_tests"][-1]["auto"] is False
    W.FAKE.msgs.clear()
    W.swap_test(dict(marked, auto=True, key="k2"))  # swap_test's own guard: no draft at all
    assert W.FAKE.msgs == [] and len(W.S["swap_tests"]) == 1
    sly = _GuardBypassed(marked, auto=True, key="k3")
    W.swap_test(sly)
    assert sly.reads >= 2  # the guard was passed, the record asked again
    assert _pubs(W, "event/swap_test") == []  # pub() refused it: the record said auto
    W.pub("event/swap_test", {"auto": True, "take": "H9102 21Nov"}, retain=False)
    W.pub("event/swap", dict(marked, auto=True), retain=False)
    assert _pubs(W, "event/swap_test") == [] and _pubs(W, "event/swap") == []
    W.pub("event/swap_test", dict(draft), retain=False)  # a marked trip's draft still goes out
    assert len(_pubs(W, "event/swap_test")) == 1


def test_docs_say_what_each_fix_corrects():
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    top = log.split("\n## 1.7.17\n", 1)[0]
    sec = top[top.index("### Cross-item review fixes"):]
    # the CHANGELOG names the README section as 1.7.18 wrote it (it became an "Applied on Pako" one on 2026-11-18)
    for part in ("1.7.12", "item 3", "item B", "1.7.17", "item 8", "1.7.15", "item 6", "event/swap_test", "21em",
                 "Pending on Pako (1.7.17)", "e322dc0e", "tests/test_fw1718_xrev.py"):
        assert part in sec, part
    for f in ("CHANGELOG.md", "README.md", "watcher.py", "www/flight-watcher-schedule-card.js", "tests/test_fw1718_xrev.py"):
        assert chr(0x2014) not in open(os.path.join(HERE, f), encoding="utf-8").read(), f

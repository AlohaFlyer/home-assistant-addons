"""1.7.8 polish: the pickers table fits a Mac and an iPad card without a sideways scroll (Avg Pickup Speed was cut off
at 1280), and the admin's pilot lookup placeholder is short enough for an iPhone. Synthetic data only."""
from test_fw171_cards import _browser, _card, _page, _s

LONG = [{"name": f"Berrios-Montgomery{i}, Maximiliano", "emp": f"1{i:04d}", "pos": "FO" if i % 2 else "RO", "n": 6,
         "month_n": 6, "year_n": 6, "inflt_n": 1, "lays": [["SEA", 2], ["PHX", 2], ["KIX", 1], ["PPG", 1]],
         "last_lay": "SEA", "min_s": 3600 * 23 + 120, "avg_s": 3600 * 23 + 1260} for i in range(8)]

FIT_JS = """async ([tag, ent, st, w]) => { const c = mount(tag, {entity: ent, open: true}, st); c.style.display = 'block';
  c.style.width = w + 'px'; await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const r = c.shadowRoot, wrap = r.querySelector('.wrap'), ths = [...r.querySelectorAll('th')].filter((e) => e.checkVisibility());
  return {heads: ths.map((t) => t.querySelector('.lg').checkVisibility() ? t.querySelector('.lg').textContent : t.querySelector('.sh').textContent),
          scroll: wrap.scrollWidth - wrap.clientWidth,
          avgRight: ths[ths.length - 1].getBoundingClientRect().right, wrapRight: wrap.getBoundingClientRect().right}; }"""

FULL = ["Pilot", "Emp", "Pos", "Ttl Pickups", "Month Pickups", "Year Pickups", "InFlt Pickups", "Common Layover",
        "Fastest Pickup Speed", "Avg Pickup Speed"]


def test_the_pickers_table_fits_a_mac_and_an_ipad_card():
    st = {"sensor.flight_watcher_pickers": _s("8", {"pickers": LONG})}
    args = ["flight-watcher-pickers-card", "sensor.flight_watcher_pickers", st]
    got = {}
    with _browser() as b:
        for vw, cw in ((1280, 990), (1100, 900), (820, 748), (700, 560), (390, 358)):
            got[cw] = _page(b, [_card("pickers-card", pilot=False)], width=vw).evaluate(FIT_JS, args + [cw])
    for cw in (990, 900, 748):  # Mac and iPad: every column, Avg on screen, no sideways scroll
        assert got[cw]["heads"] == FULL, cw
        assert got[cw]["scroll"] <= 0 and got[cw]["avgRight"] <= got[cw]["wrapRight"] + 1, (cw, got[cw])
    for cw in (560, 358):  # a phone (or an iPad in split view): Pilot, Pos, Best, Avg
        assert got[cw]["heads"] == ["Pilot", "Pos", "Best", "Avg"], cw
        assert got[cw]["scroll"] <= 0, (cw, got[cw])


def test_the_admin_lookup_placeholder_fits_an_iphone_box():
    st = {"sensor.flight_watcher_state": _s("ok", {"role": "admin"})}
    js = """(st) => { const c = mount('flight-watcher-pilot-search-card', {}, st); const i = c.shadowRoot.querySelector('input');
      const cv = document.createElement('canvas').getContext('2d'); cv.font = getComputedStyle(i).font;
      const cs = getComputedStyle(i), room = i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return {ph: i.placeholder, need: cv.measureText(i.placeholder).width, room}; }"""
    with _browser() as b:
        got = _page(b, [_card("pilot-search-card", pilot=False)], width=390).evaluate(js, st)
    assert got["ph"] == "Last name, first name or emp #"
    assert got["need"] <= got["room"], got  # the whole hint shows in the box on an iPhone

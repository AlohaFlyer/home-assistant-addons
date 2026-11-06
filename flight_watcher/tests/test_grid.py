from grid import days_moved_off, parse_grid_html, parse_grid_json, swap_allowed

ROW = ('<tr fang-ng-repeat-end="x"><td class="ng-scope"><span ng-bind-template="{d}">{d}</span></td>'
       '<td class="ng-scope"><span ng-bind-template="{a}">{a}</span></td>'
       '<td class="ng-scope buffer-color-black"><span ng-bind-template="0">0</span></td>'
       '<td class="ng-scope buffer-color-{c}"><span ng-bind-template="{a}">{a}</span></td></tr>')


def html(rows):
    return "<table>" + "".join(ROW.format(d=d, a=a, c=c) for d, a, c in rows) + "</table>"


def test_parse_grid_html_colors_and_year_roll():
    g = parse_grid_html(html([("30DEC", 12, "green"), ("31DEC", 9, "red"), ("01JAN", 14, "black")]), 2026)
    assert g["2026-12-30"] == {"net": 12, "color": "green", "avail": 12, "open": 0}
    assert g["2026-12-31"]["color"] == "red" and g["2027-01-01"]["color"] == "black"


def test_swap_rules():
    g = parse_grid_html(html([("06NOV", 19, "green"), ("07NOV", 18, "green"), ("08NOV", 10, "red")]), 2026)
    mine = ["2026-11-06", "2026-11-07"]
    assert swap_allowed(g, mine, ["2026-11-07", "2026-11-08", "2026-11-09"]) == (True, [])  # moves later
    assert swap_allowed(g, ["2026-11-07", "2026-11-08"], ["2026-11-06", "2026-11-07"]) == (False, ["2026-11-08"])
    assert swap_allowed(g, mine, ["2026-11-10"]) == (False, ["no shared day"])
    assert days_moved_off(mine, ["2026-11-07"]) == ["2026-11-06"]


def test_parse_grid_json_best_effort():
    data = {"rows": [{"date": "02NOV", "netReserves": 10, "netColor": "RED"}, {"date": "03NOV", "netReserves": 16, "netColor": "green"}]}
    g = parse_grid_json(data, 2026)
    assert g["2026-11-02"]["net"] == 10 and g["2026-11-02"]["color"] == "red" and g["2026-11-03"]["color"] == "green"
    assert parse_grid_json({"x": 1}, 2026) == {}


def test_parse_grid_json_real_shape():
    import grid as G
    data = {"success": True, "total": 3, "root": {"BidPeriod": "November 2026", "data": [
        {"date": "01NOV", "avl": "14", "odp": "0", "net": "14", "statusColor": {"net": "black"}},
        {"date": "02NOV", "avl": "10", "odp": "0", "net": "10", "statusColor": {"net": "red"}},
        {"date": "26NOV", "avl": "17", "odp": "2", "net": "15", "statusColor": {"net": "red"}},
        {"date": "01DEC", "avl": "16", "odp": "0", "net": "16", "statusColor": {"net": "green"}},
    ]}}
    g = G.parse_grid_json(data, 2026)
    assert g["2026-11-02"] == {"net": 10, "color": "red", "avail": 10, "open": 0}
    assert g["2026-11-26"]["open"] == 2 and g["2026-11-26"]["color"] == "red"
    assert g["2026-12-01"]["color"] == "green"


def test_parse_grid_json_year_rollover():
    import grid as G
    data = {"root": {"data": [
        {"date": "31DEC", "avl": "9", "odp": "0", "net": "9", "statusColor": {"net": "green"}},
        {"date": "01JAN", "avl": "9", "odp": "0", "net": "9"},
    ]}}
    g = G.parse_grid_json(data, 2026)
    assert "2027-01-01" in g and g["2027-01-01"]["color"] == "black"


def test_drop_allowed():
    from grid import drop_allowed
    g = {"2026-11-14": {"color": "green"}, "2026-11-15": {"color": "green"}, "2026-11-16": {"color": "red"}}
    assert drop_allowed(g, ["2026-11-14", "2026-11-15"]) == (True, [])
    assert drop_allowed(g, ["2026-11-14", "2026-11-16"]) == (False, ["2026-11-16"])
    assert drop_allowed(g, ["2026-11-14", "2026-11-17"]) == (False, ["2026-11-17"])  # no grid entry = not green

from datetime import date
from tradeboard import parse_pickups, other_requests_url

HTML = """<table>
<tr><td>Trade<br><a>Add to Favorites</a></td><td><a>H3612:10NOV</a> HNL 332 FO</td><td>2</td>
<td>15:05 16:05 21:59</td><td>12:17 12:17</td><td>LAS</td><td>Would like to trade</td>
<td>TUCKER RODEFFER Oct 25, 2026 07:30:44 HA</td><td><a>Propose Trade</a></td></tr>
<tr><td>Drop<br><a>Add to Favorites</a></td><td><a>H3607:25NOV</a> HNL 332 FO</td><td>3</td>
<td>12:45 13:45 09:20</td><td>17:35 17:35</td><td>KIX</td><td></td>
<td>BRANDON KEKONA Oct 31, 2026 12:09:41 HA</td><td><a>Pickup Trip</a> Phone : 8084439210</td></tr>
<tr><td>Pickup</td><td>PICKUP HNL 332 FO</td><td>1</td><td></td><td></td><td></td>
<td>pick up SAN</td><td>DANIEL COTTER Oct 22, 2026 12:16:33 HA</td><td><a>Offer a Trip</a></td></tr>
</table>"""


def test_pickup_only():
    p = parse_pickups(HTML, today=date(2026, 10, 31))
    assert list(p) == ["H3607|25Nov|BRANDON KEKONA"]
    r = p["H3607|25Nov|BRANDON KEKONA"]
    assert r["layover"] == "KIX" and r["days"] == "3"
    assert r["depart"] == "13:45" and r["arrive"] == "09:20"
    assert r["credit"] == "17:35" and r["blk"] == "17:35" and r["soft"] == "0:00"
    assert r["end"] == "27Nov" and r["poster"] == "Brandon Kekona"


def test_frame_link():
    h = '<frameset><frame name="TB_body" src="tb_myrequests.cgi?BCID=001.152"></frameset><a href="tb_otherrequests.cgi?BCID=001.152&x=1">All</a>'
    assert other_requests_url(h, "https://ha2.flica.net/online/tb_frame.cgi?BCID=001.152&dp=mr").endswith("tb_otherrequests.cgi?BCID=001.152&x=1")


JS = '''<script> var D='Drop' var X='Trade/Drop' var T='Trade' var G='Pickup' var S='&nbsp;'
r[0]=new A(29517234,0,1,249736,T,"H3606","Nov 4, 2026","04NOV","20261104","true","x@y.com",S,"CRISTINA","MARTI","Trade%20for",false,"Oct 29, 2026 08:57:06 HA",S,0,1,"14:45","3","21:00","21:00","JFK","15:45","14:55","HNL","332","FO","(18573)","LDD",  "","","",1,"_",1,"",0,0,"20261029085706","","AT","",0,0)
r[1]=new A(29600001,0,1,302095,D,"H3607","Nov 25, 2026","25NOV","20261125","true",S,"8084439210","BRANDON","KEKONA","",false,"Oct 31, 2026 12:09:41 HA",S,0,1,"12:45","3","17:35","17:35","KIX","13:45","09:20","HNL","332","FO","(23732)","LDD%3D(x)","","","",1,"_",1,"",0,0,"20261031120941","","AT","",0,0)
</script>'''


def test_js_drop():
    p = parse_pickups(JS, today=date(2026, 10, 31))
    assert list(p) == ["H3607|25Nov|29600001"]
    r = p["H3607|25Nov|29600001"]
    assert (r["days"], r["layover"], r["depart"], r["arrive"], r["credit"], r["blk"]) == ("3", "KIX", "13:45", "09:20", "17:35", "17:35")
    assert r["end"] == "27Nov" and r["poster"] == "Brandon Kekona" and r["post_type"] == "Drop"

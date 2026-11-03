from swapmap import forms, links, safe_get


def test_safe_get_refuses_requests_and_other_hosts():
    ok = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&AddList=&DropList="
    assert safe_get(ok)
    assert not safe_get("https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&AddList=H3610%3A18NOV")
    assert not safe_get("https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&DropList=H3628")
    assert not safe_get("https://ha2.flica.net/online/otrequest.cgi?Action=Submit")
    assert not safe_get("https://ha2.flica.net/online/logout.cgi")
    assert not safe_get("https://example.com/x.cgi")


def test_links_and_forms():
    html = ('<a href="/online/a.cgi?x=1">Open Time Requests</a><a href="javascript:void(0)">x</a>'
            '<frame src="leftmenu.cgi"><form method="post" action="/full/req.cgi">'
            '<input type="hidden" name="AddList" value=""><input type="submit" name="Go" value="Submit"></form>')
    ls = links(html, "https://ha2.flica.net/online/mainmenu.cgi")
    assert ("Open Time Requests", "https://ha2.flica.net/online/a.cgi?x=1") in ls
    assert ("frame", "https://ha2.flica.net/online/leftmenu.cgi") in ls and len(ls) == 2
    f = forms(html)[0]
    assert f["method"] == "post" and f["action"] == "/full/req.cgi"
    assert ("hidden", "AddList", "") in f["inputs"] and ("submit", "Go", "Submit") in f["inputs"]

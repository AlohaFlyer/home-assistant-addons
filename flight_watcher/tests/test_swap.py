from swap import better


def test_more_soft_is_better():
    ok, ds, dc, why = better({"credit": "15:00", "soft": "3:45"}, {"credit": "11:27", "soft": "0:00"})
    assert ok and round(ds, 2) == 3.75 and why.startswith("soft +3:45")


def test_more_credit_without_losing_soft():
    assert better({"credit": "12:50", "soft": "0:00"}, {"credit": "11:27", "soft": "0:00"})[0]
    assert not better({"credit": "12:50", "soft": "0:00"}, {"credit": "11:27", "soft": "0:30"})[0]


def test_small_gain_or_unknown_is_not_better():
    assert not better({"credit": "11:40", "soft": "0:10"}, {"credit": "11:27", "soft": "0:00"})[0]
    assert not better({"credit": "", "soft": "3:00"}, {"credit": "11:27", "soft": "0:00"})[0]

"""Paychecks on the schedule card (Ryan, Nov 19, 2026): the next month's 7th and 22nd checks (PWA 2.A.56) and, on the
admin's card with sensor.flight_watcher_pay_model on file, the per-check engine (Pub 15-T withholding, Social Security,
Medicare, 401(k) to the 402(g) and 415(c) limits, the employer's 415(c) excess paid as cash). Synthetic numbers only."""
import json
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js")
SRC = open(CARD, encoding="utf-8").read()


def _engine():
    a = SRC.index("const fwgR2 = ")
    r = SRC.index("toChk: fwgR2(", a)
    b = SRC.index("\n};\n", r) + 4
    return SRC[a:b]


def test_source_has_the_engine_the_check_group_and_the_flat_fallback():
    assert "const fwgCheck = (g, ytd, P0)" in SRC
    assert 'S["sensor.flight_watcher_pay_model"]' in SRC and "admin ?" in SRC
    assert 'tgrp("tchk"' in SRC and "+ chkGrp +" in SRC
    assert ".tot .tchk{" in SRC
    assert chr(0x2014) not in SRC[SRC.index("const fwgR2 = "):]


def _run(js):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(["node", "-e", _engine() + js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


P = {"tables": {"single": [[0, 0, 0.10]]}, "w4": "single", "ss_base": 10000, "addl_med_at": 200000,
     "cap_402g": 24500, "cap_415c": 1000, "k401_pct": 0, "er_pct": 0, "allot": 300}


def test_a_plain_check_withholds_by_table_and_fica():
    r = _run("const P=%s; const y={year:2026,ss_wages:0,med_wages:0,c415:0,ee401:0};"
             "console.log(JSON.stringify(fwgCheck({date:'2026-12-07',gross:1000,eligible:1000,erBase:0},y,P)));"
             % json.dumps(P))
    assert r["fed"] == 100 and r["ss"] == 62 and r["med"] == 14.5
    assert r["net"] == 823.5 and r["toChk"] == 523.5


def test_415c_full_pays_the_employer_share_as_cash_and_social_security_stops_at_the_base():
    q = dict(P, k401_pct=0.10, er_pct=0.20)
    r = _run("const P=%s; const y={year:2026,ss_wages:9950,med_wages:0,c415:900,ee401:0};"
             "const c=fwgCheck({date:'2026-12-22',gross:1000,eligible:1000,erBase:1000},y,P);"
             "console.log(JSON.stringify({c, y}));" % json.dumps(q))
    c, y = r["c"], r["y"]
    assert c["def"] == 100 and c["erCash"] == 200 and c["gross"] == 1200
    assert c["ss"] == 3.1 and y["ss_wages"] == 10000 and y["c415"] == 1000


def test_a_new_year_resets_the_limits():
    q = dict(P, k401_pct=0.10, c415_start=0)
    r = _run("const P=%s; const y={year:2026,ss_wages:10000,med_wages:0,c415:1000,ee401:500};"
             "const c=fwgCheck({date:'2027-01-07',gross:1000,eligible:1000,erBase:0},y,P);"
             "console.log(JSON.stringify({c, y}));" % json.dumps(q))
    assert r["y"]["year"] == 2027 and r["c"]["def"] == 100 and r["c"]["ss"] == 62 and r["c"]["fed"] == 90


def test_1_8_3_a_later_tax_year_uses_its_own_limits():
    # 1.8.3 (Ryan, Nov 24): the model's figures hold for its tax_year; 2027 checks use 2027's SS base and 402(g)
    q = dict(P, tax_year=2026, ss_base=184500, cap_402g=24500, cap_415c=72000, k401_pct=0.10)
    r = _run("const P=%s; const y={year:2027,ss_wages:184000,med_wages:0,c415:0,ee401:25000};"
             "const c=fwgCheck({date:'2027-11-07',gross:1000,eligible:1000,erBase:0},y,P);"
             "console.log(JSON.stringify({c, y}));" % json.dumps(q))
    # 2026's figures would give no deferral (402(g) 24,500 used) and Social Security on 500 only (base 184,500);
    # 2027's give def 100 (25,500 less 25,000 leaves room) and Social Security on all 1,000 (base 192,300)
    assert r["c"]["def"] == 100 and r["c"]["ss"] == 62


def test_1_8_3_the_tax_year_of_the_model_keeps_its_own_figures():
    q = dict(P, tax_year=2026, ss_base=10000)
    r = _run("const P=%s; const y={year:2026,ss_wages:9950,med_wages:0,c415:0,ee401:0};"
             "console.log(JSON.stringify(fwgCheck({date:'2026-12-07',gross:1000,eligible:1000,erBase:0},y,P)));" % json.dumps(q))
    assert r["ss"] == 3.1


def test_1_8_3_other_credit_is_priced_in_the_totals_and_versions():
    # October 2026: SIM, SICK, GDO, SCR credit in FLICA's month credit (87:01) and none of it priced (card 47:05)
    assert "const codesIn = (mm) =>" in SRC
    assert "sum.oth = xh" in SRC and "crAll = sum.cr + sum.vac + (sum.oth || 0)" in SRC
    assert "codesIn(mm).length) g += Math.max(0, fcr - other - ph - cut) * RATE" in SRC
    assert '["Other", sum.oth ?' in SRC

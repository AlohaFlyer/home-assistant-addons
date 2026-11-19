"""FW-0072 (Ryan, Nov 19, 2026): a pilot's tax rates from his pay stub, read in his browser and never kept, and the
2026 state income tax picker on the schedule card's Pay settings. The PDFs here are built by the test from synthetic
numbers (plain, RC4 and AES-128 Standard security, a password-protected one); no real pay stub is in the repo."""
import hashlib
import json
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js")
SRC = open(CARD, encoding="utf-8").read()


def _reader():
    a = SRC.index("const fwpMd5 = ")
    b = SRC.index("const PAIRINGS_URL = ")
    return SRC[a:b]


# builds a one-page PDF of the pay advice's rows; enc: None, "rc4" or "aes"; upw: the open password
BUILD = r"""
const zlib = require("zlib"), nc = require("crypto");
const PAD = Buffer.from("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A", "hex");
const md5 = (b) => nc.createHash("md5").update(b).digest();
const rc4 = (k, d) => Buffer.from(fwpRc4(Uint8Array.from(k), Uint8Array.from(d)));
const padpw = (p) => Buffer.concat([Buffer.from(p, "latin1"), PAD]).subarray(0, 32);
function build(rows, enc, upw) {
  const esc = (t) => t.replace(/[\\()]/g, (c) => "\\" + c);
  let c = "BT\n/F1 9 Tf\n";
  rows.forEach((cells, i) => cells.forEach(([x, t]) => {
    const y = 760 - i * 12;
    if (t === "YTD") c += `/F2 9 Tf 1 0 0 1 ${x} ${y} Tm <001900140004> Tj /F1 9 Tf\n`;
    else if (t.startsWith("[")) c += `1 0 0 1 ${x} ${y} Tm [${JSON.parse(t).map((p) => typeof p === "number" ? p : "(" + esc(p) + ")").join(" ")}] TJ\n`;
    else c += `1 0 0 1 ${x} ${y} Tm (${esc(t)}) Tj\n`;
  }));
  c += "ET\n";
  const cmap = "/CIDInit /ProcSet findresource begin 12 dict begin begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange 1 beginbfrange <0001> <001A> <0041> endbfrange endcmap end end";
  const id0 = Buffer.from("0123456789abcdef0123456789abcdef", "hex");
  const objs = {}, streams = {};
  objs[2] = "<< /Type /Catalog /Pages 4 0 R >>";
  objs[4] = "<< /Type /Pages /Kids [ 7 0 R ] /Count 1 >>";
  objs[5] = "<< /ProcSet [ /PDF /Text ] /Font << /F1 9 0 R /F2 13 0 R >> >>";
  objs[7] = "<< /Type /Page /Parent 4 0 R /Resources 5 0 R /Contents 8 0 R /MediaBox [0 0 612 792] >>";
  objs[9] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>";
  objs[13] = "<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode 17 0 R >>";
  streams[8] = zlib.deflateSync(Buffer.from(c, "latin1"));
  streams[17] = zlib.deflateSync(Buffer.from(cmap, "latin1"));
  let encDict = null, key = null;
  if (enc) {
    const P = -1340, p4 = Buffer.alloc(4); p4.writeInt32LE(P);
    let ok = md5(padpw("owner-pw")); for (let i = 0; i < 50; i++) ok = md5(ok);
    let O = rc4(ok, padpw(upw || "")); for (let i = 1; i < 20; i++) O = rc4(ok.map((b) => b ^ i), O);
    let h = md5(Buffer.concat([padpw(upw || ""), O, p4, id0])); for (let i = 0; i < 50; i++) h = md5(h.subarray(0, 16));
    key = h.subarray(0, 16);
    let U = rc4(key, md5(Buffer.concat([PAD, id0]))); for (let i = 1; i < 20; i++) U = rc4(key.map((b) => b ^ i), U);
    U = Buffer.concat([U, Buffer.alloc(16)]);
    encDict = `<< /Filter /Standard /O <${O.toString("hex")}> /U <${U.toString("hex")}> /P ${P} /R ${enc === "aes" ? 4 : 3} /V ${enc === "aes" ? 4 : 2} /Length 128` +
      (enc === "aes" ? " /CF << /StdCF << /Length 16 /AuthEvent /DocOpen /CFM /AESV2 >> >> /StrF /StdCF /StmF /StdCF" : "") + " >>";
    for (const n of Object.keys(streams)) {
      const ok2 = md5(Buffer.concat([key, Buffer.from([n & 255, (n >> 8) & 255, (n >> 16) & 255, 0, 0]), enc === "aes" ? Buffer.from("sAlT") : Buffer.alloc(0)])).subarray(0, 16);
      if (enc === "aes") { const iv = nc.randomBytes(16), ci = nc.createCipheriv("aes-128-cbc", ok2, iv); streams[n] = Buffer.concat([iv, ci.update(streams[n]), ci.final()]); }
      else streams[n] = rc4(ok2, streams[n]);
    }
    objs[1] = encDict;
  }
  const parts = [Buffer.from("%PDF-1.6\r\n", "latin1")];
  for (const n of Object.keys({ ...objs, ...streams }).map(Number).sort((a, b) => a - b)) {
    if (streams[n] !== undefined) parts.push(Buffer.from(`${n} 0 obj\r\n<< /Filter /FlateDecode /Length ${streams[n].length} >>\r\nstream\r\n`, "latin1"), streams[n], Buffer.from("\r\nendstream\r\nendobj\r\n", "latin1"));
    else parts.push(Buffer.from(`${n} 0 obj\r\n${objs[n]}\r\nendobj\r\n`, "latin1"));
  }
  parts.push(Buffer.from(`trailer\r\n<< /Size 20 /Root 2 0 R${enc ? " /Encrypt 1 0 R" : ""} /ID [<${id0.toString("hex")}><${id0.toString("hex")}>] >>\r\n%%EOF\r\n`, "latin1"));
  return Buffer.concat(parts);
}
"""

ROWS = [
    [[40, "Example Air"], [300, "Advice Date:"], [380, "01/07/2027"]],
    [[40, "Description"], [300, "Current"], [380, "YTD"]],
    [[40, "Flight Pay ($)"], [150, "8,000.00"], [220, "100,000.00"], [300, "Fed Withholding"], [400, "1,200.00"], [480, "15,000.00"]],
    [[40, "Meal Pay"], [150, "0.00"], [220, "0.00"], [300, "Fed MED/EE"], [400, "116.00"], [480, "1,450.00"]],
    [[300, '["Fed OAS", "DI/EE"]'], [400, "496.00"], [480, "6,200.00"]],
    [[300, "Fed Addl Med"], [400, "0.00"], [480, "0.00"]],
    [[300, "ZZ Withholding"], [400, "240.00"], [480, "3,000.00"]],
    [[40, "TOTAL GROSS"], [150, "FED TAXABLE GROSS"], [260, "TOTAL TAXES"], [360, "TOTAL DEDUCTIONS"], [480, "NET PAY"]],
    [[40, "Current"], [150, "8,000.00"], [220, "7,500.00"], [300, "2,052.00"], [400, "640.00"], [480, "5,308.00"]],
    [[40, "YTD"], [150, "100,000.00"], [220, "93,000.00"], [300, "25,650.00"], [400, "8,000.00"], [480, "66,350.00"]],
]


def _run(js):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(["node", "-e", _reader() + BUILD + js], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _read(rows, enc=None, upw=""):
    return _run("(async () => { let r; try { r = await fwpReadStub(build(%s, %s, %s)); } catch (e) {"
                " r = { error: e instanceof FwpError ? e.message : 'crash: ' + e.stack }; } console.log(JSON.stringify(r)); })();"
                % (json.dumps(rows), json.dumps(enc), json.dumps(upw)))


def test_md5_matches_the_standard():
    cases = ["", "abc", "a" * 55, "a" * 56, "a" * 64, "x" * 1000]
    r = _run("console.log(JSON.stringify(%s.map((s) => Buffer.from(fwpMd5(new TextEncoder().encode(s))).toString('hex'))));"
             % json.dumps(cases))
    assert r == [hashlib.md5(c.encode()).hexdigest() for c in cases]


@pytest.mark.parametrize("enc", [None, "rc4", "aes"])
def test_rates_from_a_pay_advice_year_to_date(enc):
    r = _read(ROWS, enc)
    # federal = (15,000 + 1,450 + 6,200 + 0) / 100,000; state = 25,650 taxes less those; deductions = 8,000
    assert r == {"federal": 22.65, "state": 3.0, "deductions": 8.0}


def test_a_stub_with_an_open_password_is_refused():
    assert _read(ROWS, "aes", "secret") == {"error": "needs a password to open"}


def test_totals_that_do_not_add_up_are_refused():
    bad = [row[:] for row in ROWS]
    bad[-1] = [[40, "YTD"], [150, "100,000.00"], [220, "93,000.00"], [300, "25,650.00"], [400, "8,000.00"], [480, "60,000.00"]]
    assert _read(bad) == {"error": "its totals don't add up as read"}


def test_some_other_pdf_is_refused():
    assert _read([[[40, "Quarterly newsletter"]]]) == {"error": "not a pay advice this can read"}
    assert _run("(async () => { try { await fwpReadStub(new TextEncoder().encode('hello').buffer); } catch (e) {"
                " console.log(JSON.stringify(e.message)); } })();") == "not a PDF"


def test_state_table_has_every_state_and_dc_and_figures_a_bracketed_rate():
    r = _run("console.log(JSON.stringify({n: Object.keys(FWP_STATES).length, nv: fwpStateTax('NV', 'single', 200000),"
             " co: fwpStateTax('CO', 'single', 116100), ca: fwpStateTax('CA', 'single', 240000),"
             " none: fwpStateTax('CA', 'married', 0), step: [fwpStep(7.6, 0.25, 0, 15), fwpStep(27.88, 0.5, 0, 45)]}));")
    assert r["n"] == 51
    assert r["nv"]["pct"] == 0
    assert r["co"]["pct"] == 3.79  # 4.4% of (116,100 - 16,100) / 116,100
    assert r["ca"]["pct"] == 7.6 and r["ca"]["low"] == 1 and r["ca"]["top"] == 13.3
    assert r["none"]["pct"] is None and r["none"]["top"] == 13.3
    assert r["step"] == [7.5, 28]


def test_card_says_the_stub_is_not_kept_and_keeps_it_off_the_admin_card():
    assert ("Your pay stub is read once on this device to set your tax rates, then discarded. Only the resulting rates "
            "are saved to your settings: federal, state and deductions, as percentages.") in SRC
    assert '${admin ? "" : this._payPickHtml()}' in SRC
    assert "Tax Foundation, State Individual Income Tax Rates and Brackets, 2026" in SRC
    w = SRC[SRC.index("  _payWire() {"):SRC.index("  getCardSize()")]
    # the reader's result goes to the two rate helpers and this device's deductions percent, nothing else
    assert 'stub.value = ""' in w and "fetch(" not in w and "XMLHttpRequest" not in w and "console." not in w
    rd = _reader()
    assert "fetch(" not in rd and "console." not in rd and "localStorage" not in rd
    assert chr(0x2014) not in rd and chr(0x2014) not in w

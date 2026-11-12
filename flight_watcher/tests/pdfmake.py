"""1.7.2 (FW-0066): made-up PDFs for the upload tests, written by hand (no PDF library): lines of text in Courier, a
fixed-width font, so pdftotext -layout gives the lines back with their spacing. Synthetic content only."""
import base64


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines, per_page=70, size=7):
    """A PDF of the text lines (ASCII), per_page lines a page, Courier at size points."""
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[""]]
    objs = []  # (number, body)
    n_pages = len(pages)
    font = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>"))
    lead = size + 2
    for i, pg in enumerate(pages):
        body = f"BT /F1 {size} Tf {lead} TL 18 {lead * per_page + 20} Td " + " ".join(f"({_esc(x)}) Tj T*" for x in pg) + " ET"
        objs.append((3 + 2 * i, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {int(size * 0.6 * 140) + 40} "
                                f"{lead * per_page + 40}] /Resources << /Font << /F1 {font} 0 R >> >> "
                                f"/Contents {4 + 2 * i} 0 R >>"))
        objs.append((4 + 2 * i, f"<< /Length {len(body.encode('latin-1'))} >>\nstream\n{body}\nendstream"))
    objs.append((font, "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"))
    out = b"%PDF-1.4\n"
    offs = {}
    for num, body in sorted(objs):
        offs[num] = len(out)
        out += f"{num} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    total = max(offs) + 1
    out += f"xref\n0 {total}\n0000000000 65535 f \n".encode()
    for num in range(1, total):
        out += f"{offs[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


LEGS = [
    "1          900       HNL - LAX 12:30/22:30 20:30/04:30 5h00            5:00           332        5h00   5h00   8h00   24h00",
    "D-END: 20:45L/04:45GMT",
    "2          901       LAX - HNL 21:45/05:45 00:45/10:45 6h00            6:00           332        6h00   6h00   7h00",
    "D-END: 01:00L/11:00GMT",
    "      TOTALS BLOCK 11h00     FDP 15h00    DHD 0h00     LDGS: 2    CREDIT 12h00    T.A.F.B. 39h00",
]


def package_lines(month_title="December 2026", n=110, a332=3):
    """A made-up pairing package: its title, a bid period line and n pairings (a332 of them A332 HNL ones, the rest
    717 interisland ones based in HNL, which the A332 parser leaves out)."""
    out = [" " * 40 + f"{month_title} Pairing Package", " " * 40 + "December 2 -December 31 (30 Days)", "=" * 100]
    for i in range(n):
        pid = f"H{9000 + i}"
        out += [f"{pid}                                  BASE REPT:     10:00L/20:00GMT", "BASE : HNL         CA01FO01"]
        if i < a332:
            out += LEGS
        else:
            out += ["1          100       HNL - OGG 11:00/21:00 11:45/21:45 0h45            0:45           717        0h45",
                    "D-END: 12:00L/22:00GMT",
                    "      TOTALS BLOCK 0h45     FDP 1h30    DHD 0h00     LDGS: 1    CREDIT 1h00    T.A.F.B. 2h00"]
        out.append("=" * 100)
    return out


def award_lines(month_title="December 2026", emp="1234"):
    """A made-up PBS award holding one line for employee emp (no real name or number)."""
    return [
        " " * 40 + f"{month_title} ALV",
        " " * 36 + "A332FO PBS BIDLINE AWARD",
        " " * 39 + "Posted November 18, 2026",
        "                 C/IN   Wed      Thu      Fri",
        "                        2        3        4        5        6        7        8        9        10       11",
        "",
        "                                 LAX",
        f"00999 / {emp}                     10:00",
        "DOE                                       01:00",
        "Cr:022:00                        012:00                     010:00",
        "Days Off: 25                     H9000                      VA",
        "                                 FO",
    ]


def b64(raw):
    return base64.b64encode(raw).decode("ascii")

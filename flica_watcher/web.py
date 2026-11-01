"""Ingress page: rules editor, recent finds, recent matches. HA handles auth; only the
Supervisor ingress proxy (172.30.32.2) may connect."""
import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

INGRESS_IP = "172.30.32.2"
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FLICA Watcher rules</title>
<style>
body{{font:14px system-ui,sans-serif;margin:16px;max-width:1000px;background:#fafafa;color:#222}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#ddd}}textarea,td,th{{border-color:#444}}
textarea{{background:#1b1b1b;color:#ddd}}}}
textarea{{width:100%;height:340px;font:13px ui-monospace,monospace;box-sizing:border-box}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #ccc;padding:4px 6px;text-align:left}}
.err{{color:#c62828}}.ok{{color:#2e7d32}}.note{{opacity:.75}}button{{padding:6px 14px}}
</style></head><body>
<h2>FLICA Watcher {version} rules</h2>
<p class="note">Read only until v0.3: rules alert and log what they <i>would</i> submit. Every rule starts
in dry run; its live switch (switch.flica_rule_&lt;id&gt;_live) cannot turn on until the rule is 7 days old.</p>
{msg}
<form method="post" action="rules"><textarea name="rules" spellcheck="false">{rules}</textarea>
<p><button type="submit">Save rules</button></p></form>
<details><summary>Schema</summary><pre>{schema}</pre></details>
<h3>Recent finds</h3>{finds}
<h3>Recent rule matches</h3>{matches}
</body></html>"""
SCHEMA_HELP = """[{
  "id": "sin_hunt",                 a-z 0-9 _, max 32
  "name": "SIN layover",
  "enabled": true,
  "mode": "alert",                  alert | auto_add | auto_swap
  "dry_run": true,                  true forces dry run whatever the live switch says
  "match": {
    "layover": ["SIN"],             any of these stations in the layover column
    "months": ["current", "next"],  or "YYYY-MM"
    "date_from": "2026-11-01", "date_to": "2026-12-31",   trip start date window
    "min_credit": 10.5,             hours
    "max_days": 4,
    "report_after": "06:00", "report_before": "14:00",
    "pairing_prefix": "H36"
  },
  "swap": {"give": "H3601"},        auto_swap only
  "cap_per_day": 3,
  "notify": "critical",             critical | normal
  "expires_at": "2026-12-31T23:59:00-10:00"
}]"""


def _table(rows, cols):
    if not rows:
        return "<p class='note'>None yet.</p>"
    h = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '') if r.get(c) is not None else ''))}</td>"
                                 for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"


def serve(port, version, get_rules, save_rules, store, log):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _guard(self):
            if self.client_address[0] not in (INGRESS_IP, "127.0.0.1"):
                self.send_error(403)
                return False
            return True

        def _page(self, msg="", draft=None):
            body = PAGE.format(
                version=html.escape(version), msg=msg,
                rules=html.escape(draft if draft is not None else json.dumps(get_rules(), indent=2)),
                schema=html.escape(SCHEMA_HELP),
                finds=_table(store.recent_finds(50), ["seen", "pairing", "dates", "days", "layover",
                                                      "report", "credit", "gone"]),
                matches=_table(store.recent_matches(50), ["at", "rule_id", "pairing", "dry_run",
                                                          "would_submit", "reason"]))
            b = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self._guard():
                self._page()

        def do_POST(self):
            if not self._guard():
                return
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > 200_000:
                self.send_error(413)
                return
            raw = parse_qs(self.rfile.read(n).decode()).get("rules", [""])[0]
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                return self._page(f"<p class='err'>Not valid JSON: {html.escape(str(e))}</p>", raw)
            errs = save_rules(data)
            if errs:
                msg = "<p class='err'>Not saved:<br>" + "<br>".join(html.escape(e) for e in errs) + "</p>"
                return self._page(msg, raw)
            log.info("rules saved from ingress page (%d rules)", len(get_rules()))
            self._page("<p class='ok'>Saved. Rules take effect on the next check.</p>")

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="ingress").start()
    return srv

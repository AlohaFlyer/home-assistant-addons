# ha/: Pako HI Home Assistant snapshots (Flight Watcher)

Copies of the Flight Watcher pieces that live in Home Assistant on Pako HI rather than in the app, kept here for
review and history (FW-0036). Nothing in this folder is loaded by Home Assistant or by the app, and the app store
ignores it (no `config.yaml`).

**Snapshot refreshed 2026-11-06 about 13:50 HST** (Settings tab: "Settings" heading relabeled "Credentials" on both
dashboards; Ryan's gets a "Monthly PDFs" heading and the 1.4.5 upload card above Tickets, Ryan only). Both dashboards
were checked against Pako by sha256 of the redacted text; the automations are unchanged since the 09:30 HST refresh and
the wx package since 2026-11-05.

**Automations refreshed 2026-11-06 about 16:45 HST** (1.4.6): "Flight Watcher recall miss alert" now sends a MISSED row
as a critical push titled "RECALL ALERT: missed ..." (sound `default`, `critical: 1`, `volume: 1`; anything else
time-sensitive), and the new "Flight Watcher Hark CCR alert" (`flight_watcher/event/recall_hark_alert`, time-sensitive,
Ryan's phones only) is live. Both were applied through the Home Assistant connector, and the 19 automations here match
Pako by sha256 of the redacted text.

| File | Live copy on Pako |
|:--|:--|
| `automations_flight_watcher.yaml` | `/config/automations.yaml`: the 18 automations whose alias starts with "Flight Watcher" (or that mention `flight_watcher`), in file order |
| `dashboard_flight_watcher.json` | `/config/.storage/lovelace.flight_watcher` (dashboard `flight-watcher`) |
| `dashboard_flight_watcher_james.json` | `/config/.storage/lovelace.flight_watcher_james` (dashboard `flight-watcher-james`) |
| `packages/flight_watcher_wx.yaml` | `/config/packages/flight_watcher_wx.yaml` |
| `check_push_isolation.py` | the push-isolation guard (below) |
| `sounds/flight-watcher-buzzer.wav` | `/config/www/flight-watcher-buzzer.wav` (`/local/`), the FW-0054 new-pairing buzzer; `sounds/make_buzzer.py` regenerates it byte for byte |

## Rules

- These are snapshots. The live copies are changed through the Home Assistant connector (automation and dashboard
  tools) or the HA UI, never by hand-editing `.storage`. Refresh the snapshot in the same PR as any related change.
- Redacted before commit: webhook ids (`'<redacted>'`, quoted or not on Pako), email addresses (`<redacted-email>`), Google Drive / Docs
  URLs (`<redacted-drive-url>`), any token, password or API key (`'<redacted>'`), phone numbers
  (`<redacted-phone>`). No crew names or employee numbers (none were present).
- Kept on purpose (opaque, not secrets): automation ids, the IMAP integration's config entry id, and one HA user id
  (Ryan's) in the `visibility` conditions of the three paycheck cards on the Details view.

## Refresh

1. Read Pako only: the Pako HI Shell connector (`read_file`, or `bash` printing to stdout) or the HA connector's
   get-automation and get-dashboard tools. Never write on Pako to take a snapshot.
2. Automations: every top-level item of `/config/automations.yaml` whose alias starts with "Flight Watcher" or whose
   text mentions `flight_watcher` / `flight-watcher`. Keep Home Assistant's text as it is, apply the redactions,
   keep the 3-line header comment.
3. Dashboards: load the `.storage` JSON, redact its strings, write `json.dumps(obj, indent=2, ensure_ascii=False)`
   plus a newline. Add `dashboard_flight_watcher_<name>.json` for each second pilot's dashboard.
4. Package: copy and redact.
5. Verify: sha256 of the redacted text on Pako equals the file here; grep the diff for `@`, `drive.google`,
   `docs.google`, `webhook_id`, `token`, `password`; then run the guard and the tests:

       python3 ha/check_push_isolation.py
       cd flight_watcher && python -m pytest -q

## Push-isolation guard

`python3 ha/check_push_isolation.py [file] [--no-yaml]` checks the automations snapshot (FW-0038: each pilot's
Watcher pushes only that pilot's phones). Exit 0 with a one-line summary when clean, 1 with one `OFFENDER` line per
problem, 2 when the file cannot be read. It uses PyYAML when installed, else a small built-in reader
(`--no-yaml` forces it).

- Ryan's notify targets: `notify.mobile_app_ryans_iphone_16`, `notify.mobile_app_ryans_iphone`,
  `notify.mobile_app_ryan_macbook`. Every other target counts as not Ryan's.
- Triggered by `flight_watcher_james/...` or a `*.flight_watcher_james_*` entity: never a Ryan target.
- Triggered only by `flight_watcher/...` or Ryan's `*.flight_watcher_*` entities: Ryan targets only, or none.
  Neutral triggers (time, webhook, IMAP) that push must push one pilot and read only that pilot's data.
- `<prefix>/event/ticket_fixed` pushing Ryan: needs a condition on `reporter == 'ryan'`.
- `mobile_app_notification_action` handlers filter on their own pilot's action prefixes only (Ryan `RECALL_`,
  `FLIGHT_WATCHER_`; James `JRECALL_`, `FLIGHT_WATCHER_JAMES_`), and pushes carry only the receiving pilot's.

Tests: `flight_watcher/tests/test_push_isolation.py` (the real snapshot passes; synthetic crossings fail).

- The Windy iframe coordinates in both dashboard snapshots are redacted (`lat=<redacted>`, `lon=<redacted>`): town-level home location stays out of git. The live dashboards keep them.

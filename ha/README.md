# ha/: Pako HI Home Assistant snapshots (Flight Watcher)

Copies of the Flight Watcher pieces that live in Home Assistant on Pako HI rather than in the app, kept here for
review and history (FW-0036). Nothing in this folder is loaded by Home Assistant or by the app, and the app store
ignores it (no `config.yaml`).

## Pending on Pako (1.7.1, FW-0070): "Flight Watcher bid calendar"

`automations_flight_watcher.yaml` ends with a new automation, **Flight Watcher bid calendar** (id `1794426120070`),
that is not on Pako yet (Pako has the 19 Flight Watcher automations above it, read 2026-11-11). Apply it through the HA
connector once 1.7.1 is live: a [DESTRUCTIVE] yes from Ryan. Triggered by `flight_watcher/event/bid_calendar` only
(never `flight_watcher_<pilot>/...`), it sends the payload's `title` and `message` as a critical push (sound `default`,
`critical: 1`, `volume: 1.0`, tag `flight_watcher_bid_calendar_<key>`) to `notify.mobile_app_ryans_iphone` and
`notify.mobile_app_ryans_iphone_16`, exactly like "Flight Watcher charter". HA appends a new automation at the end of
`/config/automations.yaml`, so the snapshot keeps file order; after applying, check by sha256 of the redacted text as
in Refresh below, then drop this section. Until then the snapshot is one automation ahead of Pako (20 here, 19 there).
Undo: delete the automation (its id above). The guard passes with it (`python3 ha/check_push_isolation.py`: 20
automations, 0 offenders).

## Pending on Pako (1.7.1, FW-0072): "Flight Watcher van time" and the layover card

Two edits, each applied through the HA connector once 1.7.1 is live (the card file and the two sensors must exist
first), each a [DESTRUCTIVE] yes from Ryan; then check by sha256 of the redacted text as in Refresh below and drop
this section.

1. `automations_flight_watcher.yaml` ends with **Flight Watcher van time** (id `1794426120072`), after the bid
   calendar one: triggered by `flight_watcher/event/van` only (never a pilot's prefix), it sends the payload's
   `title` ("Van SYD 19:40 AEDT") and `message` ("Van in 30 min: 19:40 AEDT (22:40 HST), <place>") as a critical push
   (sound `default`, `critical: 1`, `volume: 1.0`, tag `flight_watcher_van_<minutes>`) to
   `notify.mobile_app_ryans_iphone` and `notify.mobile_app_ryans_iphone_16`, exactly like "Flight Watcher charter".
   With the bid calendar one the snapshot is two automations ahead of Pako (21 here). Undo: delete it (its id above).
   The guard passes with it (`python3 ha/check_push_isolation.py`: 21 automations, 0 offenders).
2. `dashboard_flight_watcher.json`, view `flight` (Working Flight): its one section's two cards (the markdown card
   and the grid holding the "Ready to update?" button) become one card,
   `{"grid_options": {"columns": "full"}, "type": "custom:flight-watcher-layover-card", "update_url": <the button's
   tap_action url_path, Hark's project page, redacted here>}`. Through the connector:
   `ha_config_set_dashboard(url_path="flight-watcher", python_transform=...)` with
   `v = next(v for v in config["views"] if v.get("path") == "flight");
   u = v["sections"][0]["cards"][1]["cards"][0]["tap_action"]["url_path"];
   v["sections"] = [{"type": "grid", "cards": [{"type": "custom:flight-watcher-layover-card",
   "grid_options": {"columns": "full"}, "update_url": u}]}]`. Undo: the connector's edits backup of the dashboard (or
   put the two cards back from git history). Pako's dashboard had 5 views when read on 2026-11-11 (no Aviation Wx
   view; this snapshot still lists it): refresh the snapshot from Pako after applying.

**Applied on Pako 2026-11-10 (James's HA page retired):** James uses the pilot portal (FW-0061) and his HA user is
gone, so the `flight-watcher-james` dashboard and his seven HA helpers (`input_number.flight_watcher_james_*` federal
and state tax, longevity year, month offset; `input_text.flight_watcher_james_*` ER trips, picker search;
`input_boolean.flight_watcher_james_show_vac_trips`) were deleted through the HA connector, and "Flight Watcher
dashboard month reset" now resets Ryan's month offset only. The portal never read those helpers (its prefs are the
Watcher's own `/data/james/prefs.json`). `dashboard_flight_watcher_james.json` is removed from this folder; the
sections below that mention it are history. Undo: restore the edits backups (dashboard, automation, seven helpers)
with `ha_manage_backup(scope="edits", action="restore")`.

**Snapshot refreshed 2026-11-06 about 13:50 HST** (Settings tab: "Settings" heading relabeled "Credentials" on both
dashboards; Ryan's gets a "Monthly PDFs" heading and the 1.4.5 upload card above Tickets, Ryan only). Both dashboards
were checked against Pako by sha256 of the redacted text; the automations are unchanged since the 09:30 HST refresh and
the wx package since 2026-11-05.

**Automations refreshed 2026-11-06 about 16:45 HST** (1.4.6): "Flight Watcher recall miss alert" now sends a MISSED row
as a critical push titled "RECALL ALERT: missed ..." (sound `default`, `critical: 1`, `volume: 1`; anything else
time-sensitive), and the new "Flight Watcher Hark CCR alert" (`flight_watcher/event/recall_hark_alert`, time-sensitive,
Ryan's phones only) is live. Both were applied through the Home Assistant connector, and the 19 automations here match
Pako by sha256 of the redacted text.

**Applied on Pako 2026-11-06 about 20:30 HST (1.4.7, FW-0064):** "Flight Watcher request decided" (id `1793941354206`)
says "Seen on your FLICA schedule ... (a crew-to-crew trade)" for a `sched:` key instead of "Filed ...". The 19
automations here match Pako by sha256 of the redacted text.

## Applied on Pako 2026-11-08 (1.4.9, FW-0067): Working Flight views

A **Working Flight** view (path `flight`, icon `mdi:airplane-takeoff`) sits at index 2 of both dashboards (Watcher, Aviation
Wx, Working Flight, Details, Recall/O75, Settings), one markdown card each:

- `flight-watcher` (Ryan): reads `sensor.hark_working_flight` (Hark writes it over HA REST every 30 min: live status, gates,
  tail, MEL, NOTAM, GIN, release link) when it covers the same pairing as `sensor.flight_watcher_working_flight`, else the
  Watcher's sensor (1.4.9, from Ryan's own FLICA pairings, retained over MQTT, so it survives an HA restart while Hark's REST
  state does not). A **Ready to update?** button opens Ryan's Hark project (redacted here) to send "ready".
- `flight-watcher-james`: reads only `sensor.flight_watcher_james_working_flight` (his own schedule); no Hark data and no
  button. The view's `visible` list is James's and Ryan's, like his other views.

Both templates use `.get()` on the attributes, so a missing field never logs a template warning. Applied through the HA
connector (JSON patch at `/views/2`, with a `test` on the Details path first); HA stores the inserted view with sorted keys.
Undo: remove `/views/2` from each dashboard.

## Applied on Pako 2026-11-07 about 13:35 HST (1.4.8, FW-0066)

Edits 1 and 2 below were applied through the HA connector once 1.4.8 was live (`flight-watcher` 13:34,
`flight-watcher-james` 13:38 HST). Both dashboard snapshots here match Pako by sha256 of the redacted text. Undo: give
the two cards of edit 1 back the `user` visibility condition and rename the heading "Monthly PDFs"; delete the two
cards edit 2 inserted. Item 3 is still open. Items 4 and 5 were applied on Pako 2026-11-07 about 15:15 HST
(Ryan's yes): `configuration.yaml` backed up to `configuration.yaml.bak-20261107-fw0066`, both edits made, config
check valid, HA restarted.

Who the card reaches (read on Pako 2026-11-07): `flight-watcher` is `require_admin: true`, so only HA admins open it;
all five views of `flight-watcher-james` (Settings included) are `visible` to James's and Ryan's user ids only. So
after edits 1 and 2 the uploads card serves Ryan, the other HA admins and James, not every HA user: the non-admin
household users (four, a guest login among them) can open `flight-watcher-james` but see none of its views.

1. `flight-watcher` (Ryan's, `lovelace.flight_watcher`), view `settings`, section 0: the heading card "Monthly PDFs"
   (icon `mdi:file-upload-outline`) is renamed **"Monthly files"** and loses its `visibility` (the `user` condition
   naming Ryan's user id); the `custom:flight-watcher-uploads-card` right after it loses the same `visibility`. The
   divider (`markdown` "---"), the Tickets heading and the tickets card keep theirs. (The dashboard itself stays
   `require_admin: true`, so on it the card meets admins only.)
2. `flight-watcher-james` (`lovelace.flight_watcher_james`), view `settings`, section 0: after
   `custom:flight-watcher-settings-card-james` (Credentials) and before the divider, insert
   `{"type": "heading", "heading": "Monthly files", "icon": "mdi:file-upload-outline"}` and
   `{"type": "custom:flight-watcher-uploads-card-james", "grid_options": {"columns": "full"}}`, with no visibility
   condition (James is not an admin: his card reads `sensor.flight_watcher_james_uploads` and sends chunks to
   `flight_watcher_james/upload/chunk`). The view's own `visible` list (James, Ryan) stays as it is.
3. Open question for Ryan, not applied (still open): should the other household users upload too? That
   means adding their user ids to the `visible` list of the `flight-watcher-james` Settings view (they would then also
   see James's Credentials card there, which shows his FLICA username), or a separate view or dashboard for the
   uploads card alone. A separate [DESTRUCTIVE] edit; recommended: leave as is.
4. Applied 2026-11-07 (`/config/configuration.yaml`, then an HA restart): `recorder: exclude: entities:` add
   `sensor.flight_watcher_pilot_schedule` and `sensor.flight_watcher_james_pilot_schedule`. A pilot lookup's payload
   carries the looked-up pilot's contact (not retained in MQTT since the review fix), and a small payload (a "loading"
   or "no data" reply) is under the recorder's 16 KB attribute limit, so without this each lookup's contact stays in
   `home-assistant_v2.db` for `purge_keep_days` (3 on Pako). Nothing reads these sensors' history.
5. Applied 2026-11-07 (`/config/configuration.yaml`, then an HA restart): each chunk is a `call_service` event of about 256 KiB,
   and the recorder logs "Event data for call_service exceed maximum size of 32768 bytes" at WARNING for every one
   (about 10 for a 1.7 MB award, about 130 for 25 MB) and stores `{}` for it. Recommended: under the existing
   `logger:` add
   `filters: {homeassistant.components.recorder.db_schema: ["Event data for call_service exceed maximum size"]}`,
   which only silences that line. (`recorder: exclude: event_types: [call_service]` also stops the warnings and the
   one small last chunk being stored, but drops every service call from history and from the logbook's "triggered
   by" context.)

| File | Live copy on Pako |
|:--|:--|
| `automations_flight_watcher.yaml` | `/config/automations.yaml`: the automations whose alias starts with "Flight Watcher" (or that mention `flight_watcher`), in file order (19 on Pako; 20 here with the pending bid calendar one, above) |
| `dashboard_flight_watcher.json` | `/config/.storage/lovelace.flight_watcher` (dashboard `flight-watcher`) |
| `packages/flight_watcher_wx.yaml` | `/config/packages/flight_watcher_wx.yaml` |
| `check_push_isolation.py` | the push-isolation guard (below) |
| `pilots.json` | none: who the guard knows (admin `ryan`, pilots `["james"]`), their notify targets and action prefixes (1.5.0) |
| `sounds/flight-watcher-buzzer.wav` | `/config/www/flight-watcher-buzzer.wav` (`/local/`), the FW-0054 new-pairing buzzer; `sounds/make_buzzer.py` regenerates it byte for byte |

## Rules

- These are snapshots. The live copies are changed through the Home Assistant connector (automation and dashboard
  tools) or the HA UI, never by hand-editing `.storage`. Refresh the snapshot in the same PR as any related change.
- Redacted before commit: webhook ids (`'<redacted>'`, quoted or not on Pako), email addresses (`<redacted-email>`), Google Drive / Docs
  URLs (`<redacted-drive-url>`), Hark project links (`<redacted-hark-url>`), the Windy map's lat/lon (`<redacted>`), any token,
  password or API key (`'<redacted>'`), phone numbers (`<redacted-phone>`). No crew names or employee numbers.
- HA user ids and the IMAP config entry id are placeholders since the Nov 7 history cleanup: Ryan's user id is
  `00000000000000000000000000000001`, James's `00000000000000000000000000000002`, the config entry id 26 zeros. The
  sha256 check applies the same mapping to Pako's text. Never copy these files over Pako without putting the real ids back.
- Kept on purpose (opaque, not secrets): automation ids.

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

`python3 ha/check_push_isolation.py [file] [--no-yaml] [--pilots=pilots.json]` checks the automations snapshot
(FW-0038: each pilot's Watcher pushes only that pilot's phones). Exit 0 with a one-line summary when clean, 1 with one
`OFFENDER` line per problem, 2 with one line naming the file when the automations file, the pilots file or
`flight_watcher/roles.py` cannot be read (the guard reads them when it runs, not at import, so `--pilots=<file>` works
while the default `ha/pilots.json` is broken). It uses PyYAML when installed, else a small built-in reader
(`--no-yaml` forces it).

- 1.5.0 (FW-0063): the pilots come from `ha/pilots.json` (admin `ryan`, pilots `["james"]`, each one's notify
  targets and action prefixes); add a pilot there when it joins the app's `pilots` option, no code change. An id is
  a pilot's when it starts with `flight_watcher_<name>` (the longest known name wins: `jane_doe` before `jane`),
  Ryan's when its first word is one of the app's reserved words (`flight_watcher/roles.py` `RESERVED`), and an
  unknown pilot's otherwise, which is an offender.
- Ryan's notify targets: `notify.mobile_app_ryans_iphone_16`, `notify.mobile_app_ryans_iphone`,
  `notify.mobile_app_ryan_macbook`. A target `pilots.json` gives a pilot is that pilot's. A notify target it gives to
  nobody is an offender (1.5.0, fail closed: with several pilots the guard cannot tell whose phone it is), so list
  each pilot's targets there before an automation pushes them.
- Triggered by `flight_watcher_james/...` or a `*.flight_watcher_james_*` entity: never a Ryan target, nor another
  pilot's; when it pushes, its conditions and actions read only James's topics and entities (1.5.0: reading Ryan's
  or another pilot's schedule into James's push is an offender).
- Triggered only by `flight_watcher/...` or Ryan's `*.flight_watcher_*` entities: Ryan targets only, or none; when it
  pushes, it reads no pilot's topics or entities (1.5.0).
  Neutral triggers (time, webhook, IMAP) that push must push one pilot and read only that pilot's data (an automation
  that reads several pilots' data and pushes is an offender).
- Pilot names in `pilots.json` follow the app's rule (`roles.NAME_RE`: 1 to 32 lowercase letters and digits, single
  underscores between words); any other name is exit 2.
- `<prefix>/event/ticket_fixed` pushing Ryan: needs a condition on `reporter == 'ryan'`.
- `mobile_app_notification_action` handlers filter on their own pilot's action prefixes only (Ryan `RECALL_`,
  `FLIGHT_WATCHER_`; James `JRECALL_`, `FLIGHT_WATCHER_JAMES_`), and pushes carry only the receiving pilot's.

Tests: `flight_watcher/tests/test_push_isolation.py` (the real snapshot passes; synthetic crossings fail).

- The Windy iframe coordinates in both dashboard snapshots are redacted (`lat=<redacted>`, `lon=<redacted>`): town-level home location stays out of git. The live dashboards keep them.

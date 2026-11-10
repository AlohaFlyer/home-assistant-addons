# HANDOFF: Flight Watcher (refreshed 2026-11-10, release 1.6.0 live; 1.6.1 stage 0 and 1.6.2 Release A built on branch fw-1.6.2, not deployed)

State: app **1.6.0** on Pako HI (1.4.7 Nov 7, 1.4.8 FW-0066 uploads and contacts Nov 7, 1.4.9 FW-0067 working flight
per pilot Nov 8, 1.4.10 FW-0068 crew index finds FLICA-rebuilt pairings like H3631B Nov 9, 1.4.11 FW-0069 schedule versions
for looked-up pilots on the pilot card Nov 9 (`pilotver.py`, list file `pilotver_<key>.json`), 1.4.12 the probe reads
every rebuilt copy until all pilot seats are named Nov 9, 1.4.13 FW-0042 comm / month rule / value from
`/share/flight_watcher/smart.json` Nov 9, 1.5.0 FW-0063 pilots list and roles (`roles.py`, `ha/pilots.json`) Nov 9; each instance publishes `sensor.<prefix>_working_flight`, read by the Working Flight view on each
dashboard, see `ha/README.md`). **1.6.0** (FW-0061, the Flight Watcher half of the pilot portal: `portal.py`,
`ntfy.py`, `portal_layout.json`, `PORTAL_CONTRACT.md`) is live with `portal: true` for James, and Ryan's instance is
unchanged by it. **1.6.2** (Release A, branch `fw-1.6.2` on top of 1.6.1, not pushed or deployed; CHANGELOG 1.6.2):
the host-wide FLICA gate (`gate.py`; pilot 100 loads an hour, host 480, the admin's 376 kept; hunt 5 to 90 s and normal 1 to 90 min on every instance per Ryan's Nov 10 instruction, a pilot's short hunt spread over his budget, his portal's normal up to 20 min until the Release C contract revision), read-path
breakers, the schedule read in at most 2 loads, the awarded line on the card, pilot captures off (`captures.py`),
topic-only ntfy with guardrails, Recall/O75 seniority from the award, the minimal pilot name lookup, pref flags, and the
portal's pot, working flight, CrewTrac and requests cards with HST times and portal wording. The reviewers' findings on it are fixed in the same branch (CHANGELOG 1.6.2, Release A review fixes: FLICA refusal block and 10 min login floor on a pilot, his check floor (5 s since Ryan's Nov 10 ranges), the gate's abort and the pot's share, CAPTCHA stops, 2 loads per schedule read, masked pilot logs, the card fixes). The git history was cleaned on Nov 7 (`ha/` files carry placeholder user ids). Slug `43b22650_flight_watcher`,
two instances: Ryan (`flight_watcher`, `/data`) and
James (`pilots` entry `james`, role pilot, `flight_watcher_james`, `/data/james`). James uses the pilot portal
(homeofficemanager.app/fw, FW-0061), not Home Assistant: his HA user was retired on Nov 10 and his HA dashboard
(`flight-watcher-james`) and HA helpers were deleted the same day (backups in the HA connector's edits store); his
portal prefs live in `/data/james/prefs.json`. The work list is the tickets folder, not this file:
`/share/flight_watcher/tickets/FW-nnnn/ticket.json` (card at the bottom of the Settings tab, Ryan only).

## How the work runs

- **Tickets:** "process all bugs" = read every new / reopened ticket, fix, release, mark `fixed` with the version
  via `flight_watcher/ticket/act` (that sends `event/ticket_fixed`, a quiet push to the reporter). "Confirm your
  completed fixes" = Claude verifies each fixed ticket itself (tests, app log, entity states, deployed files) and
  closes it with a note; only steps that need Ryan's phone, password or a [DESTRUCTIVE] yes stay open.
  Claude files its own follow-ups straight into the folder (same lock and counter) so they do not push Ryan.
- **Releases:** CLAUDE.md > Release procedure. Ryan pre-approved (2026-11-06) merging and updating releases of
  fixed tickets, `second_pilot: james`, and the Pako / GitHub leftover cleanup listed in FW-0032 / FW-0033.
- **Pako config** (automations, dashboards, wx package) is changed through the HA connector, then the redacted
  snapshot under `ha/` is refreshed in the same PR and checked by sha256 (`ha/README.md`). Run
  `python3 ha/check_push_isolation.py` after any push change: James's pushes never reach Ryan's devices and the
  reverse.
- **Pushes:** Ryan's iPhone 16 and "Ryan's iPhone" (Apple Watch mirrors), MacBook for H3628 only. The device table
  is the Phone alerts card on the Details tab. New pairing he can take = critical with the buzzer
  (`/local/flight-watcher-buzzer.wav`, `ha/sounds/`).

## Open items (ticket numbers)

1. **Ryan, on his iPhones:** allow Critical Alerts for Home Assistant; import the buzzer (FW-0054) and Fanfare
   (H3628 alert) sounds in the HA app (Settings > Companion App > Notifications > Sounds > Import); Watch app >
   Notifications > Home Assistant > Mirror iPhone alerts.
2. **James (FW-0037 / FW-0038):** once his Samsung registers in the HA app, add his Android push automations
   (`JRECALL_` / `FLIGHT_WATCHER_JAMES_` action prefixes, alarm-stream channel for critical) and run the isolation
   guard. Welcome note with the Samsung steps is a Gmail **draft only**; nobody contacts James until Ryan says so.
3. **Release 1.4.7, each a [DESTRUCTIVE] yes from Ryan:** merge the PR and update the add-on (then verify
   `sensor.flight_watcher_state` version and the app log); apply the request-decided automation change through the HA
   connector (`ha/README.md`, "Pending on Pako"); close-in folder while hunting is read at most every 5 min (about +12 FLICA loads an hour on top of FW-0035's
   ~376; every check when not hunting); Ryan may ask for once a minute (+60 an hour).
4. **[DESTRUCTIVE] decision, Ryan (the repo is public):** the real crew names and employee numbers 1.4.7 removed from
   the tree are still in git history on `main` and on pushed `claude/*` branches. Options: `git filter-repo
   --replace-text` (old values to made-up ones) over `main` and those branches, force-push, and ask GitHub Support to
   purge cached views and PR refs; or delete the stale branches. Until then, merge 1.4.7 promptly so `main`'s tree is
   clean. The FLICA alerts mailbox address (CHANGELOG 0.4.1, redacted in the tree in 1.4.7) is in that history too.
5. **After 1.4.7 is live:** FW-0057, trips other pilots started in October that run into November are indexed only
   from pilot lookups (each reads the pilot's October once) until October's pairings package is uploaded; keep it open
   until checked on Pako. FW-0064, the crew-to-crew trades page: watch the app log for "crew-to-crew trades page named"
   (menu reads, never followed) and check that page by hand before the Watcher reads it. FW-0034 / FW-0064 risk: at
   every login the main menu never builds its left menu frame in the Watcher's browser (it stays on FLICA's forward
   page with its reCAPTCHA, never bypassed), so the menu tree both rely on may never be read; check the log for
   "close-in folder not on the menu yet" and `captures/menu_closein.html`, then Ryan decides how the close-in BCID is
   found (nothing is guessed).
6. **Features:** FW-0042 smart push is built in 1.4.13 (`smart.py`: `comm`, `value`, `month_rule` in the DB, the
   finds files, `last_new` and `event/new_pairing`, not on the finds, pot or Tradeboard sensors; not deployed yet).
   It needs `/share/flight_watcher/smart.json` on Pako (Hark's tables, never in git; blank fields without it) and a
   separate HA step to use the fields in the new-pairing push (CHANGELOG 1.4.13). Comm or Value in the pot_table
   macro needs a Watcher release that puts the fields back on `pot/state` (12 KB cap) as well as the macro edit.
   Hark to confirm the overnight-release cut-off (a release from midnight to 05:00 has no same-day home;
   `home_day_start` in smart.json moves it). FW-0044 FLICA DROP review page mapped read only.
7. **Ryan-owned:** FW-0021 paycheck check Dec 22 (PWA 2.A.56, 3.D, 4.C.3, 4.O.1, 6.J); FW-0040 upload the December
   award and January pairings PDFs when posted; FW-0057 upload the October 2026 pairings package (the uploads card
   on the Settings tab asks for it from 1.4.7); FW-0033 delete the merged `claude/*` branches in the GitHub UI
   (this session can push only its own branch).
8. **Waiting on Hark:** FW-0020 (Nov 3 recall list blank), FW-0030 (HPA 2026-27 school calendar partial).
9. **FW-0061 pilot portal (live Nov 10):** FW 1.6.0 and HOM 1.6.0 are deployed and the options are set. James got
   his invite and guide from Ryan, and his Watcher left `needs_settings` (state `hunting` on Nov 10). Open: Ryan's
   ntfy plan choice, then the first ntfy push to James. Close FW-0061 once that push is seen.

## Decided (do not reopen)

- FLICA read only, forever: no submit, drop, swap, add or bid; the swap "mode" is a read-only sensor (FW-0028).
- Hunt load stays about 376 FLICA loads an hour (FW-0035).
- Hark's daily A330 charter scan is retired; the Watcher's own charter watch pushes a new charter (FW-0043, FW-0050).
- Crew assignments are public information (Ryan confirmed with ALPA and the company).
- Recall/O75 CCRs are filed on hal.alpa.org only after Ryan approves the narrative ("file CCR <date> <pairing>").

## Recent releases

1.1.x Settings card (sealed), 1.2.x request-decided push with Pay-Gross, 1.3.0 FW-0002 to FW-0009,
1.4.0 FW-0010 to FW-0029 batch, FW-0047 to FW-0049, FW-0053; 1.4.1 to 1.4.6 trade requests, pay line (FW-0062),
uploads, Recall/O75 (see `flight_watcher/CHANGELOG.md`).

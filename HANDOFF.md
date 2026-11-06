# HANDOFF: Flight Watcher (refreshed 2026-11-06, release 1.4.0)

State: app **1.4.0** on Pako HI (slug `43b22650_flight_watcher`), two instances: Ryan (`flight_watcher`, `/data`) and
James (`second_pilot: james`, `flight_watcher_james`, `/data/james`). James's HA user exists; his Watcher waits for
his FLICA and CrewTrac logins on his own Settings tab. The work list is the tickets folder, not this file:
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
3. **Crew index (FW-0056 to FW-0059):** trips not in the bid package, the previous bid period, names split on seat
   codes, a pilot on two overlapping trips.
4. **Sensor size (FW-0060):** tickets (about 39 KB) and schedule versions (about 16 KB) exceed the recorder limit.
5. **Features:** FW-0034 close-in open time folder (read only), FW-0039 FAR 117.23(c) cumulative FDP, FW-0042 smart
   push (commute, month-type rules), FW-0044 FLICA DROP review page mapped read only.
6. **Ryan-owned:** FW-0021 paycheck check Dec 22 (PWA 2.A.56, 3.D, 4.C.3, 4.O.1, 6.J); FW-0040 upload the December
   award and January pairings PDFs when posted; FW-0033 delete the merged `claude/*` branches in the GitHub UI
   (this session can push only its own branch).
7. **Waiting on Hark:** FW-0020 (Nov 3 recall list blank), FW-0030 (HPA 2026-27 school calendar partial).

## Decided (do not reopen)

- FLICA read only, forever: no submit, drop, swap, add or bid; the swap "mode" is a read-only sensor (FW-0028).
- Hunt load stays about 376 FLICA loads an hour (FW-0035).
- Hark's daily A330 charter scan is retired; the Watcher's own charter watch pushes a new charter (FW-0043, FW-0050).
- Crew assignments are public information (Ryan confirmed with ALPA and the company).
- Recall/O75 CCRs are filed on hal.alpa.org only after Ryan approves the narrative ("file CCR <date> <pairing>").

## Recent releases

1.1.x Settings card (sealed), 1.2.x request-decided push with Pay-Gross, 1.3.0 FW-0002 to FW-0009,
1.4.0 FW-0010 to FW-0029 batch, FW-0047 to FW-0049, FW-0053 (see `flight_watcher/CHANGELOG.md`).

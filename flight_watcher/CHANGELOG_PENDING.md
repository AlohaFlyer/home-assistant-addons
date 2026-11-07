# Pending changelog lines (1.4.7 review fixes; the integrator folds these into CHANGELOG.md)

- FW-0034 / FW-0035 (hunt load): hunting, the close-in folder's page is read at most once a minute
  (`CLOSE_IN_READ_S` = 60; every check when not hunting, and on Check now); between reads its last rows stay on the
  pot. That is up to about 60 more FLICA loads an hour while hunting, on top of the ~376 Ryan accepted (FW-0035),
  instead of 100 to 190; Ryan's OK is needed before release.
- FW-0034 (folder move): a trip FLICA moves from the regular pot to the close-in folder is the same find: no second
  `event/new_pairing`, its `first_seen` (pickup speed) is kept, its find now belongs to the close-in folder
  (`Store.move_finds`), and no pickup check is queued while it is open there (no false "hidden by scheduling").
- FW-0034 (stop pages): a captcha, a session taken over elsewhere or an expired session on the close-in page or its
  menu read ends the pass as on the pot (stop, yield 30 min, log in again); after such a menu read the close-in page
  is not loaded.
- FW-0034 (guards): `enrich()` and `pickup_check()` pairing page GETs now pass `SUB.safe_get` and `SM.safe_get`.
- FW-0039: the FAR column rounds an over-limit total up, so it never reads as the limit (60:30 h of FDP is
  `FDP 61h/168h`; 102:30 h of flight time `FT 103h/672h`), and shows the worst failing window, not the first in time.
  `far_why` stays off the pot and Tradeboard sensors (the DB, the finds files and `event/new_pairing` keep it).
- FW-0056: a pilot lookup shows the later of a trip's stored end and the index's (a schedule end that grew);
  `crewidx.instances` keeps the schedule trips when no pairing file exists yet; a test covers an end that grows and
  never shrinks (`note_sched_trips`).
- FW-0057: when the previous bid month has no pairing package on file, a pilot lookup also reads that pilot's previous
  month once (Schedule Lookup, GET only, both guards, paced; one extra load per pilot and month) and notes the trips
  that run into this month for the crew index. Trips other pilots started in October are covered only for pilots
  looked up (and Ryan's own months) until October's pairings package is uploaded: keep FW-0057 open until checked on
  Pako.
- FW-0059: overlap flags come only from trips in the index (a trip gone from it clears its flag, never "kept"); a
  forced re-read whose fetch fails stays queued until a page comes back.
- FW-0060: the tickets card keeps the file's whole title when the sensor's 80-character cut starts it (titles over
  80 characters show whole, and Edit starts from the whole title).
- FW-0062: no change in this pass; list FW-0062 with the tickets 1.4.7 closes (PR title or description).
- FW-0064 (trades page): every menu read (close-in folder search, schedule menu) looks for an entry naming
  crew-to-crew trades (`pot.trade_pages`, Tradeboard left out). Found, it is logged once with its link (session token
  masked), kept in state (`trade_pages`) and the menu kept privately as `captures/menu_trades.html`; it is never
  fetched. The "find the page" half of FW-0064 stays open until a live menu read names it and the page is checked.
- FW-0064 (pending requests): a Pending or Processing open time request read with its FLICA id has its view page read
  once (both guards, paced; at most 3 new a read) for its legs, so a swap approved on the schedule is pushed once as
  that request, not first as a crew-to-crew trade with no request on file.
- Test data: the `note_own` docstring's sample page header in `watcher.py` is made up now (it held a real employee
  number). The old values remain in git history: rewriting it is a [DESTRUCTIVE] decision for Ryan (HANDOFF.md item 4).
- Trip end (was labeled FW-0065; no such ticket is filed on Pako, whose counter reads 64, so the next ticket filed
  there takes that number): relabeled "trip end fix (no ticket filed)" in CHANGELOG 1.4.7, README, HANDOFF, code and
  tests; `versions.repair_ends` marks a repaired version `repaired: "trip-end-1.4.7"` (`versions.REPAIR_TAG`). Not yet
  on Pako (it runs 1.4.6), so no stored version carries the old marker. Do not list FW-0065 among the tickets 1.4.7
  closes; if Ryan wants it tracked, file it through the ticket flow first.
- Test data (tradeboard): the JS fixture in `tests/test_tradeboard.py` had three real FLICA values left (r[0]'s request
  id, and the crew id of r[0] and r[1]); they are made up now (29600000, 100001, 100002). A sweep of every 6 to 9
  digit number in tests, cards and code against Pako's captures and crew index finds no other match. The old values
  remain in git history (HANDOFF.md item 4, a [DESTRUCTIVE] decision for Ryan).

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
- Trip end fix (no ticket filed): its old label named a ticket number Pako never filed; it now reads "trip end fix (no
  ticket filed)" in CHANGELOG 1.4.7, README, HANDOFF, code and tests, and `versions.repair_ends` marks a repaired
  version `repaired: "trip-end-1.4.7"` (`versions.REPAIR_TAG`). Not yet on Pako (it runs 1.4.6), so no stored version
  carries the old marker.
- Test data (tradeboard): the JS fixture in `tests/test_tradeboard.py` had three real FLICA values left (r[0]'s request
  id, and the crew id of r[0] and r[1]); they are made up now (29600000, 100001, 100002). A sweep of every 6 to 9
  digit number in tests, cards and code against Pako's captures and crew index finds no other match. The old values
  remain in git history (HANDOFF.md item 4, a [DESTRUCTIVE] decision for Ryan).
- FW-0057 (1.4.7 verify): the uploads card asks for the pairings packages the crew index still needs ("Wanted: the Oct
  2026 pairings package", with why): this bid month's and the previous one's, while neither its pairing file nor an
  upload of it is on file, back to the crew index's first bid month (api/uploads `wanted`, `web.uploads_wanted`).
  Pako has no `pairings_2026-10.json`, so the card now asks Ryan for October's package; once it is read, trips other
  pilots started in October that run into November are indexed from it, not only from pilot lookups.
- FW-0034 / FW-0064 (1.4.7 verify, menu capture): the schedule's left menu read keeps the plain left menu page when the
  main menu's frame gives nothing (`menu_tree()` returns '' when FLICA's forward page does not move on), so that page
  is still scanned for the close-in folder and a trades page and its private capture is no longer an empty file
  (Pako's `captures/leftmenu.html` of Nov 4 is 0 bytes).
- Docs: the 0.4.1 changelog entry no longer names the FLICA alerts mailbox (`<redacted-email>`, as the `ha/` snapshot
  writes it); a test keeps email addresses out of the changelogs, READMEs, HANDOFF, CLAUDE.md and the `ha/` snapshot.

## Integrator notes (not for CHANGELOG.md)

- Fixed in 1.4.7 per the verify pass: FW-0034 (code and tests; finding its BCID live is unproven, see below), FW-0039,
  FW-0056, FW-0058, FW-0059, FW-0060, FW-0062. Do not list FW-0065 (Pako's ticket counter reads 64; the trip end fix
  has no ticket; if Ryan wants it tracked, file it through the ticket flow first).
- Keep open: FW-0057 until October's pairings package is uploaded (the uploads card now asks) and the crew index is
  checked on Pako; FW-0064 until a live menu read names the crew-to-crew trades page and it is checked by hand, and
  the `ha/automations_flight_watcher.yaml` request-decided change is applied on Pako (a [DESTRUCTIVE] yes). FW-0034
  stays unconfirmed until its BCID is found live.
- FW-0034 / FW-0064 live risk: on Pako (app log, Nov 6 07:25, 12:32 and 14:59 HST, at each login) the main menu
  never builds its left menu frame in the Watcher's browser ("main menu: no leftmenu frame", frames: the forward page
  and FLICA's reCAPTCHA frames). The Watcher never bypasses a reCAPTCHA, so `menu_tree()` gives nothing there, and the
  plain left menu GET is a skeleton (0.8.4). The close-in folder and a trades page can then be found only on a page
  that names them (the mobile open time page names neither today). After 1.4.7 is live, check the log for "close-in
  folder not on the menu yet" and the private `captures/menu_closein.html`; if no page names the folder, Ryan decides
  how its BCID is found (nothing is guessed).
- Ryan's OK on the hunting close-in read load (about +60 FLICA loads an hour on top of FW-0035's ~376) is still needed
  before release.
- The alerts mailbox address and the earlier real values stay in git history: rewriting it is HANDOFF item 4 (a
  [DESTRUCTIVE] decision for Ryan).

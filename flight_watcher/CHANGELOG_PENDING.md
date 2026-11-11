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

## 1.7.1, watcher core (branch fw171-core; the integrator folds these into CHANGELOG.md under 1.7.1)

- LIVE-1 (seen in the live log Nov 11 on a pilot instance): his open time hunt paced to his whole 100 loads an hour
  left the reads that may be left out one first come, first served pool (opt_cap), so his own trips, the pickups and
  their in-flight lookups took every load that came free and the Tradeboard, the reserve grid, the pot details and
  the trade requests were "left out of this check: FLICA budget kept for the open time pot" for hours. Each of those
  four now has its own share of the hour on a pilot (`opt_shares`: one whole read an hour; the Tradeboard 2 loads a
  bid number, the grid 2 a pot page, the requests 1 a folder and 1 a bid number, the pot details 2), the rest of his
  optional loads stay a pool (`OPT_POOL_H` 4 at least), and the pace keeps room for both (`opt_hour`: 12 as before
  with one bid month, so a 5 s hunt stays about 44 s apart; 18 with two, about 96 s instead of 89 s; about 2 min with
  the close-in folder). A Tradeboard, grid or request read starts only when all its loads fit (`opt_fits`: its share
  or the pool, and his budget and the host's cap with `GATE_KEEP` free); one that does not fit tries again at the next
  check without moving its timer, and says so in the log at most every 30 min. A grid cross-check left out keeps the
  JSON just read. The hard caps are the gate's, unchanged (a pilot's 100 an hour, the host's 480); the admin has no
  budget, no shares and keeps his ~376 an hour (FW-0035). Tests: `test_pilot_secondary_share.py` (the real check()
  for 3 h at the floor with a greedy optional read: each of the four reads in every hour, the pot on every check, no
  rolling hour over 100), pacing tests in `test_freq_ranges.py` and `test_release_a_review.py` moved to the new
  numbers (their fake request list and pairing pages are now pages the parsers know: those reads run now).
- F#15: a pilot instance writes an empty rules.json (the SIN example rule only on the admin, as before). Once per
  pilot (DB `example_rule_checked`), a rule that is exactly the seeded example (every field but created_at) is
  removed from his rules.json, logged, and its live switch taken down; an edited one stays. Tests: `test_fw171_core.py`.
- F#12, F#92, F#149: a Check now (Scan FLICA now) the Watcher would ignore (paused, stopped, waiting for settings,
  stepped aside, in a re-login back-off, under 10 s since the last check, or held by the FLICA budget) answers the
  portal ok false with the reason in plain words and is not republished (`check_now_refusal`, `press_answer` in the
  spool); a press from Home Assistant logs the same words. Re-arm says what it does by state (`rearm_answer`): idle or
  hunting with no check for the clock card's 'Stuck' limit (10 min hunting, 2.5 times the normal interval and at least
  30 min otherwise) and none running, it runs a full check now (what 'Stuck. Press Re-arm.' asks for); idle or hunting
  and checking, paused, waiting for settings, a check running, or the budget holding the next check: ok false with
  why; stopped: the login as before; stepped aside: accepted, and the login waits for the step-aside's end (another
  command waking the loop no longer cuts it short; only a stop wakes the loop for Re-arm, as documented in 1.6.2).
  Tests: `test_fw171_core.py`, the wake test in `test_release_a_flica.py` (a Check now while paused is ignored).
- F#7, F#110: the export's full sweep (every 300 s) writes state.json even when nothing changed: the same payload in a
  new envelope, so its seq (the write time) moves at least every 5 min in every state, needs_settings included. No new
  field (contract 1 as it is). Test: `test_portal_export.py`.
- F#75: the admin forwards each recall list it takes to every pilot's Watcher itself (`recall_forward`:
  `<prefix>/recall/set`, qos 1, never its 'me'; the pilots by run.py's own rules on the add-on options). A day that
  comes again unchanged keeps the time it first came in (the card's 'received') and is no new list, so the second
  copy (Ryan's HA automation still forwards too) changes nothing. Once this is live, the second mqtt.publish of the
  HA automation "Flight Watcher recall list in (Hark webhook)" can be dropped (a [DESTRUCTIVE] HA change for Ryan,
  then the `ha/` snapshot refreshed). Tests: `test_fw171_core.py`.
- F#102: a pilot who saved only his CrewTrac details gets the charter watch while his FLICA watch waits for its login
  (`start_charter_watch` before the needs_settings wait: CrewTrac is its own site and login), so Scan CrewTrac now
  has a reader. Test: `test_fw171_core.py`.
- F#155: a sealed settings message `{"ctweb_off": true}` (the card's Remove CrewTrac login; sealed only, like
  `ntfy_off`; the portal relays the sealed message as it is, no contract change) removes ctweb_username and
  ctweb_password from his creds.json, resets the CrewTrac record and restarts the instance like any save ("saved:
  CrewTrac login removed"; "nothing new: no CrewTrac login is saved" when there is none). Test: `test_fw171_core.py`.
- F#77: no Watcher-side cause found: a Recall/O75 Refresh from the portal is taken (ok) and answered with a new
  `checked` time on `sensor.<prefix>_recall_o75` (test in `test_fw171_core.py`); the stuck note is the card's (a late
  answer never clears it).

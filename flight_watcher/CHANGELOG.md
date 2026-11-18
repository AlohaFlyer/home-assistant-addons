# Changelog

## 1.7.18

Two card changes Ryan asked for on Nov 17, 2026 (screenshots of Settings > Monthly files and of the schedule card on a
Samsung phone). Cards only: no Watcher, sensor, contract or FLICA change.

### The On file list folds

Ryan, Nov 17: "collapse the on file list". The uploads card (Settings, heading "Monthly files") listed every file kept,
one row each, above Pilot uploads, Dates of hire and Pilot contacts.
- The file rows fold under their heading, folded by default. The heading is a button (44 px high, aria-expanded,
  aria-controls, a chevron that turns down when open) that says "On file (6)" and, while folded, one line on what is
  there: "6 files, newest Award Dec 2026, uploaded Nov 14" (the newest upload, its HST day, and "1 not read" in red when
  a file has no text copy). A tap, Enter or Space opens or folds it; the focus stays on the heading.
- Open or folded is kept per browser (localStorage `flight_watcher_onfile_open`; a pilot's copy keeps its own,
  `flight_watcher_<name>_onfile_open`). Blocked storage (a private window) folds it at first and still opens it.
  Refresh, and every sensor update, leave it as it is; the count and the line follow the new list. More than 6 files
  still fold the rest under "n older" inside.
- The Wanted line (a pairings package the crew index needs), "Nothing uploaded yet", an error, and the sections after
  the list stay in view: Pilot uploads (its Approve and Reject), Dates of hire and Pilot contacts are sections of their
  own (their own headings), not rows of the list. The Refresh button is 44 px high too.
- While there is nothing to fold (the list loading, an error, "Nothing uploaded yet.") the heading is plain text: no
  button, no aria-expanded, no aria-controls pointing at a list that is not there, no arrow, and a tap does nothing.
  The button comes back, open or folded as kept, once there is a list (review AB-1).
- The count in the heading and in the folded line is the Watcher's (the sensor's `count`), not the rows the sensor
  carries: the Watcher cuts the uploads sensor's list at its 12000 byte cap, the oldest files first, and kept the full
  number beside it. A card that reads the sensor (a user who is not an admin, a pilot's copy) said "On file (83)" for
  102 files; it now says "On file (102)" and the open list ends with "19 older files not listed here (more than the
  sensor can carry)." A count that is not a whole number above the rows listed is not used (review AB-2).
- The portal has no copy of this card (the admin's uploads card stays off the portal; a pilot uploads with the pilot
  uploads card, unchanged). A second pilot's dashboard copy (`flight-watcher-uploads-card-<name>`) folds the same.

### The version lock is a switch

Ryan, Nov 17: "The lock does not display well on James' samsung... its not obvious when it is locked or unlocked...
Can we try a toggle Show the lock icon, and then an on/off toggle where locked is on". The lock at the top left of the
schedule card was an emoji (each phone draws its own) whose only change was the shackle.
- Now: a lock icon drawn as an inline SVG (shut, or the shackle lifted when unlocked; the same on every phone), the
  word Lock, a switch track with its knob, and the word On (locked) or Off. On = locked, the default. On: a filled blue
  track with the knob at the right and On in bold; Off: an outlined grey track with the knob at the left and Off. The
  state never rests on colour alone (the knob's side and the word), and the track, knob and edge keep 3:1 against the
  card in light and dark (WCAG 1.4.11); the text keeps AA.
- One button (role switch, aria-checked, named "Lock schedule marks", 44 px), with a 3 px focus ring; a tap, Enter or
  Space flips it and the redraw keeps the focus on it. The title is the same ("Locked: ... cannot be changed by a tap.
  Tap to unlock." / "Unlocked: taps change .... Tap to lock."), and so are the taps it freezes and the storage
  (localStorage `flight_watcher_lock`, "0" = Off, anything else or nothing = On; a pilot's copy its own key).
- A refused tap says "Settings are locked: turn the Lock switch at the top left Off to change availability, trade or
  drop marks." The Key's Day row says how the switch works.
- On a phone (700 px or less) the switch has the header's first line to itself, so the month's arrows, title and Now
  stay together on the next line (at 360 and 390 px the wider switch would otherwise split them); the Data age stamp
  (1.7.12) follows Now, on a line of its own at 360 and 390 px. A wide card keeps one line, as before. Hover shading only with a mouse (no grey box left after a tap on a phone).
- The pilot card has no lock; every copy of the schedule card (a second pilot's, the portal's) gets the switch.

### Tests

`tests/test_fw1718_ui.py` (Chromium, synthetic files and pairings, "pilot2"): A folded by default with the count and the
line, opens and is remembered (another copy, a reload), Enter and Space with the focus kept, Refresh on the admin's
card (ingress) and a user's (sensor) keeps it, the empty and error states in view, a pilot's copy under its own key,
blocked storage, 390 px light and dark (no sideways scroll, AA text), the heading plain text while loading, on an error
and with nothing on file (no button, aria-expanded, dangling aria-controls or arrow, Chromium's accessibility tree
included) and a button again once a list comes, and the Watcher's count over a cut sensor list (a synthetic sensor, and
120 synthetic files through watcher.cap_attrs). B: the switch reflects and toggles the lock
(aria-checked, the knob's side, On / Off, the SVG, no emoji in any card), the title, the refused tap and the trade tap,
Space and Enter with the focus ring, the stored value as before (and blocked storage), the Key, the portal's pilot2
copy, and renders at 390 px and on an Android-like phone (360 x 780 at 3x), light and dark: on its own first line, the
arrows, month and Now together, 44 px, AA text, 3:1 for the track, knob and edge. README: the On file fold and the
lock switch.

## 1.7.17

### Commutable flag on pot trips

Ryan, Nov 17: "Tag pot trips whose report and release times line up with my commutes from KOA and LAS." He chose the
existing commute check and its smart.json timetables (no new windows). No FLICA page load, no contract change.

- **The Watcher**: each row of `sensor.<prefix>_pot_count` and `sensor.<prefix>_tradeboard_pickups` carries `cm`, the
  airports the commute check passed both ways, in smart.json's order (`["KOA", "LAS"]`; `smart.comm_tag`): two scheduled
  nonstops arriving HNL before report (PWA 26.QQ.2) and one home at least smart.json's `home_gap_min` after release (60
  min unless set), same day. A last leg from outside the US releases 30 min after block-in, not 15 (PWA 2.19.b); one
  whose origin is not on file is judged both ways, so an airport that makes it only without customs is never tagged.
  There is no `cm` key at all when no airport passes, when one is only unknown, or when smart.json is missing or has no
  timetables: never a guess.
- The full commute object (`comm`, `comm_why`) stays off both sensors as before (`SENSOR_DROP`); a row with no tag is
  byte for byte the row it was. The DB, the finds month files, `last_new` and `event/new_pairing` are unchanged.
- The Tradeboard's tag is judged again at each publish from the timetables on hand (a post's details are read once), so
  a smart.json edit reaches it as it reaches the pot every check. So are the close-in folder's rows between its reads
  (hunting, at most every 5 min) and after a failed read: an edit or removal of smart.json reaches their tag with no
  page load, and a tag is never kept without timetables. Each instance reads its own smart.json
  (`/share/flight_watcher/smart.json`; a second pilot's `/share/flight_watcher/<name>/smart.json`).
- **Size**: about 19 bytes on a row commutable from two airports. The pot sensor stays at or under its 12 KB cap
  (`cap_attrs` still cuts rows from the end). With every row tagged, the busiest synthetic pot keeps 18 rows where it
  kept 19, and a lighter one keeps 34 where it kept 36.
- **The pot card** (`flight-watcher-pot-card.js`: the portal's pot, and the admin's copy): a chip "Commutable KOA LAS"
  beside Fits and FAR. It is in words, not color alone, and green like Fits (the F#119 colors, WCAG AA in light and
  dark); hover shows the rule. Only three-letter codes are drawn. The Key gets a Commutable line when a row has the
  chip; it gives the home flight as your smart.json home gap (`home_gap_min`, 60 min unless set), never a fixed 60. The
  stale-pot banner's style no longer reaches the FAR chip "OK (CBA rest ...)": every chip on a row is one chip high
  again (before, that chip's margin stretched Fits and the new chip beside it, text at the top).
- **The HA Watcher view**: its pot table is the `pot_table` Jinja macro on Pako (not in git). The macro edit and the
  dashboard Key line are in the release notes; they need Ryan's OK at the release step (custom templates reload).
- **James's portal**: gets the tag with no contract change. state.json masks only `contact` and the www file keys, so
  the new attribute passes through as signed. The contract fixture is unchanged (sha256 `a066d935...ed2ec9`), and his
  copy of the pot card reads the same attribute. He sees chips only when his own smart.json has timetables; without one
  his card is unchanged.
- Tests: `tests/test_fw1717_comm_tag.py` (made-up KOA and LAS timetables, made-up pairings). It covers both ways, one
  way only (not tagged), no timetables (no tag), and the customs release from a US station, from abroad and with the
  origin not on file. It also covers smart.json's `domestic` list, the Tradeboard tag judged fresh, each instance's own
  file, a worst-case pot under the cap, the portal pass-through and fixture hash, and the chip at 390 px on the portal
  (light and dark, contrast checked) and on Home Assistant's themes. Review: the close-in rows judged again between
  reads and after failed ones, the Key's home gap (45 and 90 min gaps), and the chip heights beside a CBA rest chip.
  `tests/test_smart.py`'s sensor test now expects the tag as the one difference.

## 1.7.16

### When to hunt: pickup speed by layover, weekday and time of day

Ryan, Nov 17: "Using the pot log ("Pickup Speed" exists, so build on it), show median time to pickup by layover city and
by day of week/time of day, so I know when to run Hunt."
- From the pickups the FO / RO pickers card already counts (`picker_log`; no new source), each pickup once (a trip
  with both seats open is one pot entry and one dwell: once, at its faster picker's speed, which is the same for both
  unless one has a request cap), the median time to pickup, the count and the fastest by layover (the first station
  of the trip's layover, else of its turn, as Common Layover; split as rules.py splits a layover, so a pot-seen
  multi-stop turn "PPG/PPT" and the "PPG" the Watcher files its email-caught copy under are one station, and
  "SYD/MEL" is SYD), by the HST weekday and by the HST time of day (00-06, 06-12, 12-18, 18-24) the trip entered the
  pot. The entry is `dwell()`'s, the earlier of the first sighting and FLICA's alert, kept on the pickup's
  `picker_log` row (new column `entry`) when it is scored or rescored, so a trip back in the pot, or a find later
  cleared or deleted, never moves it to another weekday or band. A row logged before 1.7.16 gets it once at start
  from its find, else from its pickup time less its speed (late by half the gone window, more for a capped speed).
  Stored times are UTC; the weekday and band are read in HST (-10 h all year), so 05:00 UTC Wednesday is Tuesday
  19:00, 18-24.
- A speed capped at Ryan's request time (1.7.10) counts at its cap; a group with one has its median read "at most"
  (an upper bound), and its fastest too when the fastest is the capped one (≤, the reason on hover).
- The median of an even count is the mean of the two middle speeds, to the nearest second. Each table runs by
  median (a tie: more pickups first), the groups of 5 or more pickups first; a group of fewer is grey, "too few to
  trust", and never the tip.
- The tip names the fastest HST day and time of day together (a slot) of 5 or more pickups: "Trips go fastest when
  they enter the pot Tue 18-24 HST: median 4 min (n 12).", when that slot is no slower than the fastest day and the
  fastest time of day of 5 or more; never the slot where the fastest day and the fastest time of day cross, which can
  be slow or nearly empty. Else it gives that day and that time of day as two separate facts ("Fastest day: Mon
  (median 50 s, n 5). Fastest time of day: 06-12 HST (median 30 s, n 7). No day and time pair has 5 pickups yet.",
  the last sentence only when no slot has 5); from one table when only it has a group of 5; none when neither has.
- The FO / RO pickers card has a When to hunt section at its top, under the header and outside the pickers list, so
  the tip shows while the list is collapsed (the dashboard and the pilot portal mount the card collapsed): the tip,
  then the three small tables (Layover, Day (HST), Time (HST): Median, Fastest, n), collapsed by default when they run
  past 12 rows and kept as the viewer left them across updates, however they were opened or closed (a tap, the
  keyboard, find in page). An update changes the tip and tables in place, so a focused summary keeps its focus; an
  empty table says so ("No layover on file yet."); a slot in the tip ("Tue 18-24 HST") never splits across two lines.
  390 px with no sideways scroll, WCAG AA in light and dark; three side by side on a wide card.
- Published as `speed` on `sensor.<prefix>_pickers` (`{n, min_n, city, dow, band, tip, more}`, each group `[label, n,
  median_s, fastest_s, capped_n, fastest_capped]`): aggregates only, no name, employee number or pairing; at most
  2500 bytes (`store.SPEED_ATTR_MAX`), the layovers with the fewest pickups left out first and counted in `more` ("12
  more layovers with fewer pickups not shown."). The busiest case measured: 7.5 KB for the whole pickers sensor,
  under its 8 KB bar and HA's 16 KB recorder limit. The pickers list file is unchanged.
- Each instance computes its own from its own store (Ryan's and every pilot's); nothing crosses instances. A pilot's
  portal shows the section from the pickers sensor it already gets in state.json: no new export, contract 1 revision
  6 unchanged.
- No FLICA load. `Store.speed_stats()` is recomputed only after picker_log changes (a pickup scored or rescored, the
  log rebuilt, backfilled or trimmed), not on every check's publish.
- Tests: `tests/test_fw1716_speed.py` (synthetic pairings H96xx, made-up stations, "Doe, Jane"): median with odd and
  even counts, capped speeds, HST bands across midnight and the date line from UTC stored times, the HST weekday, the
  under-5 rule, the tip in each form, the size bound, the store counting what the pickers card counts (both seats
  open), the alert and request cap moving the entry and speed, a find gone or back in the pot, the recompute only on a
  change, no FLICA load, a pilot's instance on its own, the contract unchanged, and the card in Chromium at 390 px
  light and dark and 1280 px (screenshots `item7_390_light.png`, `item7_390_dark.png`, `item7_1280_light.png`,
  `item7_390_short.png`). Review fixes, `tests/test_fw1716_review.py`: the tip's slot (the fastest of 5 or more, not
  where the fastest day and band cross; two separate facts when none has 5 or it is slower), a both-seats trip once
  (count, trust bar and median weight, and at the cap when one picker is capped), one station per layover across
  sources, the entry kept through a trip back in the pot, a cleared pickup and a deleted find (a capped one too), a
  row logged before 1.7.16 filled once at start, the section shown on a collapsed card (the dashboard's and portal's
  config), an open without a click and the summary's focus kept through updates, an empty table, and the tip's slot
  on one line at 360 to 414 px (screenshots `item7_review_collapsed_390_light.png`, `..._dark.png`,
  `item7_review_nolay_390_light.png`, `..._dark.png`).

## 1.7.15

### Automatic swap ideas ranked by pay per day

Ryan, Nov 17 (item 6, his yes): "Fill Swap ideas without a manual tap: rank my trips against open pot trips by pay per
day. Keep legality and VAC/blocked rules." Both instances; no FLICA page load, nothing sent to FLICA, no contract change
(revision 6 and its fixture stay; section 4.3's wording follows, below).

- **Every trip, no tap.** Each check, every own pairing that has not started yet (it starts after today, HST) and is not
  marked "would trade" is compared with every open pot trip (open time and the close-in folder; a Tradeboard post is
  not the pot) of the same bid period that it could swap for (a FLICA swap stays inside one BCID): the pot's own bid
  month when its key names one (`2026-11`, or the desktop menu's `November`), else the bid period of its first day
  (`bid_period_fn`, the 1.7.11 rule); his trip's is the pairing files' bounds, else the first schedule page on file
  that lists it (a Dec 1 trip listed on November's and December's pages is November's: FLICA's next page starts on
  the bid period before's last day), else `bid_period_fn`. Marked trips work as
  before: the soft time or credit rule (`swap.better`), their pushes, their drafts and the auto swap dry run.
- **Ranked by pay per day**: (pot trip Pay-Gross / its days) minus (own trip Pay-Gross / its days). Each trip is priced
  the way the swap pushes price one (`price_moves`, `pay.trip_gross`): credit x the PWA 3.D.6 rate `pay_settings()`
  gives for the longevity year, plus the PWA 4.O.1 override for the seat flown (RO $4.00 a block hour; FO $3.00 on a
  3-pilot crew) and the Extended Range +15% where on (the per-trip ER list too). Credit and block come from his own trip
  record (his seat and roster) and from the pot row, else from the pairings package of the bid period that holds the
  trip's first day (1.7.11, PWA 4.A: a Dec 1 trip of November's period is in November's package), then the calendar
  month's. A pot trip is priced in the RO seat when RO is its only open seat (the row's `open_seats`), else in the FO
  seat, as `price_moves` falls back; its crew is its own roster (the row's `crew`, open seats included), else the
  package's crew line, as his trip's is his roster. His trip's layover for the ER rule is the package's route, else
  its schedule item's (a SIN trip no package or roster covers keeps its +15%). No rate is invented: with no rate on
  file (no date of hire, no longevity year) there are no automatic ideas and the sensor says `priced: false`.
  `pay_settings()` is read again at most every 5 min for this (`SWAP_PAY_TTL_S`).
- **Each idea shows** both pay-per-day figures and both trips' totals: `pay`, `pay_days`, `ppd` (the pot trip),
  `for_pay`, `for_days`, `for_ppd` (his trip) and `ppd_gain`; an idea for a marked trip carries them too (None when the
  rate or the credit is not known). An automatic idea is listed only when it pays more a day.
- **The same legality, nothing looser**: not his own pairing number; FAR 117 with his trip removed (`far_for` with
  `exclude`) reading a plain OK, so the 11 h domicile rest (PWA 10.E.1.a) holds; no VAC or blocked day; the grid rule
  (`grid.swap_allowed`: it shares a day with his trip and every day moved off is green). A marked trip's grid-red idea
  is listed and waits, as before; an automatic idea is listed only when the grid is green now.
- **Never a push**: each idea has `auto` (true for an automatic idea, false for a marked trip's). Automatic ideas are
  never published on `event/swap` (the topic the "Flight Watcher swap idea" automation listens to; it reads no sensor,
  so it needs no condition and is unchanged), never on `event/swap_test`, never a draft (`swap_test`), never the auto
  swap dry run, never in `swap_seen`. `pub()` refuses an idea with `auto` true on either topic (a backstop, one log
  line), so a pilot's portal alert and ntfy never get one either. `ha/check_push_isolation.py` passes unchanged.
- **Bounded, and `ideas` keeps its meaning**: on `sensor.<prefix>_swap_ideas`, `ideas` lists the marked trips' ideas
  only, exactly as 1.7.11 did (at most 30, in their soft time and credit order, `gain_h`, the order they push in); the
  best 10 automatic ones (`SWAP_AUTO_MAX`) are in their own attribute, `auto_ideas`, the best pay per day first. So
  every reader of `ideas` (the old Swap ideas card still on Pako until the dashboard edit, the schedule card's swap
  tags) shows what 1.7.11 showed and never an automatic idea unlabeled. New attributes: `auto_ideas`, `auto_count`
  (all automatic ideas), `auto_shown` (those listed), `auto_more` (those not listed), `auto_max` (10) and `priced`.
  The 12 KB attribute cap drops automatic ideas from the end first, then trims `ideas` from the end, the least soft
  time first, as in 1.7.11 (the best soft-time idea, the first push, stays listed). The state (`count`) is every idea
  found, marked and automatic.
- **Dashboard** (`ha/dashboard_flight_watcher.json`, Watcher view, Swap ideas): the table shows the automatic ideas
  ("*auto*" beside the trip given up) and two new columns, Pay ("$2,029 (1 day) vs $3,886 (3 days)") and Per day
  ("+$734 a day: $2,029 vs $1,295"); "N more automatic ideas not shown (the best K by pay per day are)" under it, K the
  number listed (the size cap can list fewer than 10, or none: "no room left next to your marked trips' ideas"); with
  no idea, "No better-paying swap
  in the open pot right now" (or, with no rate, how to set one) and the mark hint. The key explains auto and pay per
  day. **The snapshot is ahead of Pako by this edit and the earlier pending ones** (1.7.12's Details tile, 1.7.14's
  near misses card; `ha/README.md`: "Pending on Pako (1.7.15): automatic swap ideas on the Swap ideas table", one
  section a release in release order; the snapshot, every pending edit, sha256 `6678f813...`, which Pako reads once
  all three are applied; Pako's `be03a0a4...` stays named; `tests/test_fw171_r2.py` pins both). Applying it is a step
  of the 1.7.15 go-live: right after the update is verified, Claude applies the card's `content` through the HA
  connector (after the 1.7.12 and 1.7.14 edits), checks the sha256 and drops that section. Until then the old card shows the marked trips'
  ideas exactly as 1.7.11 did, and no automatic idea.
- **Pot card** (the portal's Watcher tab): `ideas` then `auto_ideas`, the same columns and "auto" chip, the "N more"
  line (the number listed), the new empty text;
  "-" for an idea with no pay figure (an older Watcher). Folds into labeled lines at 390 px; WCAG AA light and dark.
- The schedule card is unchanged: its Ideas column is a separate system, and its swap tags (up to 2 a trip) read
  `ideas`, so they show the marked trips' ideas as in 1.7.11 and no automatic one.
- **Portal contract** (`PORTAL_CONTRACT.md` 4.3 and the `roles.PORTAL_EVENTS` comment): the `swap` alert's opt-in now
  reads "no mark, no alert", and 4.3 says 1.7.15 keeps revision 6 (the fixture is unchanged): the swap ideas sensor
  also lists automatic ideas in `auto_ideas`, which never alert (never `event/swap`, so never a `swap` event or an
  ntfy push). Wording only: no constant, fixture or HOM change.
- Tests: `tests/test_fw1715_auto_swap.py` (synthetic pairings, both instances): the ranking and the figures, the
  pricing (seat, crew, package, ER list, the bid period's package), marked vs automatic, each legality rule rejecting
  (VAC, blocked, FAR conflict, rest, the CBA 11 h, FAR unknown, a red or missing grid day, another bid period, less pay
  a day, no rate, his own pairing, a started trip, a Tradeboard post), the real FAR screen with the trip removed, no
  push and no draft for automatic ideas (MQTT, the portal and ntfy), the push automation, the size bound and the cap,
  no FLICA load, each instance on its own prefix, the dashboard table (Jinja) and the pot card (Chromium); from the
  review: marked ideas in their 1.7.11 order with the cap trimming the least soft time first, `ideas` holding no
  automatic idea, the RO seat, the pot row's roster, his trip's schedule layover (ER), the pot's and his page's bid
  period with no pairing files, the "N more" wording on both cards, the contract wording.
  `tests/test_fw171_cards.py`: the pot card's swap table test follows the new columns and empty text;
  `tests/test_fw171_r2.py`: the dashboard snapshot sha and the pending note; `tests/test_doh_settings.py` and
  `tests/test_van_settings.py`: the contract doc's sha256 pin follows the 4.3 wording (the fixture's is unchanged).

## 1.7.14

### Near misses in the open time pot

Ryan, Nov 17: "In the open time pot, for each trip hidden by a VAC or blocked day, show what I'd have to drop or swap to
fly it, plus the pay difference."
- Each check, right after the pot sensor, the Watcher lists every pot trip (the open time pot and the close-in folder)
  hidden today because it touches a VAC day, a blocked day or one of the pilot's own trips (`near_misses`,
  `near_blockers`). A PAYP day is free for a pickup (PWA 4.R.1), never in the way; a pot row that is one of his own
  trips (its open seat) is left out.
- What stands in the way: "VAC Nov 21 to 22" (the VAC days the trip touches, a run of days each), "blocked Nov 14",
  "overlaps your H3620 Nov 25 to 27". What to change to fly it: "give up VAC Nov 21 to 22", "unblock Nov 14", "drop or
  swap H3620". A trip hidden for more than one reason lists each.
- An own trip that only shares a day with the pickup is kept, nothing given up, when `far_screen` with it in the line
  is a plain OK: "same day as your H2000 Nov 10 to 11, legal to fly both" (home in the morning, the pot turn that
  evening; its duty does not overlap and every rest and limit holds), or when the pickup is known not legal for
  another reason exactly as with it dropped ("no conflict with it"). A "?" keeps it in the way.
- The pay difference: the trip's Pay-Gross less what is given up, and the credit hours ("+$518", "+2:00"). Every trip
  is priced by `pay.trip_gross` (the schedule card's tripFull, as `price_moves` prices a trade): credit x the PWA 3.D.6
  rate for the longevity year in Pay settings (`pay_settings`, PWA 3.B.1), the PWA 4.O.1 override (RO $4.00 per block
  hour when only the RO seat is open, FO $3.00 on a 3-pilot crew) and the Extended Range +15% where on. Pilots are
  counted the same way on the pickup and on a dropped trip: CA, FO, RO and SO, never a flight attendant (`_near_crew_n`,
  as `crewidx.pilot_seats`). Credit, block and crew not on the row or record come from the pairings package of the
  trip's own bid period (`bid_period_key`, 1.7.11: Dec 1 is November's). A VAC day given up is 4:00 of pay and credit
  (PWA 6.J.1.c, `pay.VAC_H`, the schedule card's VAC_H x RATE); a dropped own trip its own Pay-Gross and credit (his own
  trip record, else the newest version of the schedule month that holds it, else the pairings package: `_move_rec`); a
  blocked day or a kept trip nothing. No longevity year or DOH: the hours only, and the sensor says why. Any credit not
  on file: no amount (never a wrong one).
- FAR 117 with the conflict removed: `far_screen` (the check `far_for` and the swap ideas use) with the overlapping own
  trips given up left out (`recall.line_records` now takes several keys); VAC and blocked days are no duty. "legal"
  only on a plain OK, as `swap_scan` (FAR 117.25(e), 117.25(b), 117.23(b)(1), 117.23(c) and the PWA 10.E.1.a 11 h home
  rest); else the reason with its trip and rule in the text, not a tooltip ("not legal: rest 6:15 before (H1019 Nov
  19), under 10 h (FAR 117.25(e))", "not legal: CBA rest 10:30, under the 11 h home rest (PWA 10.E.1.a)"). A time not
  on file, or "OK (CBA rest 10:50?)" (the home rest short only if a release was 30 min after block-in for customs, PWA
  2.19.b), reads "not known yet: ...", never legal and never not legal.
- Information only: from the pot rows, schedule, own trip records, blocked days, pairings package file and Pay settings
  already on hand. No FLICA page load, no event, nothing added, dropped, swapped or requested.
- New sensor `sensor.<prefix>_near_misses` (MQTT discovery, core: the admin and every pilot instance each compute
  their own; topic `<prefix>/near/state`): `count`, `misses` (legal first, then not known, then not legal; the best pay
  difference first; the first 20, `NEAR_ROWS`), `kinds`, `rate`, `year`, `pay_note`; `cap_attrs` trims `misses` from
  the end under the 12 KB `ATTR_MAX`. The pot sensor is unchanged.
- Not on a pilot's portal yet: `roles.ENTITY_OFF_PORTAL` keeps the sensor out of his state.json (a new exported state
  is a portal contract change, PORTAL_CONTRACT.md 4.2, left for a later revision), and the card is in
  `PORTAL_CARDS_OUT`. Contract 1 revision 6, its fixture, PORTAL_CONTRACT.md (sha256 `e4f559e0...`, unchanged) and
  James's portal are exactly as in 1.7.11; he sees near misses after a later contract revision. `near` joins
  `roles.RESERVED` (no pilot may be named near or near_x).
- New card `www/flight-watcher-near-card.js` (`custom:flight-watcher-near-card`), deployed with the others: the list
  folded by default with its count, staying open across updates once opened; each miss with what is in the way, what
  to change (with the credit and pay each change gives up, "nothing lost" for a blocked day or a kept trip), the pay
  difference in green or red and the FAR 117 chip; a key with the PWA and FAR references. The card is built once: an
  update changes only the count, the list and the rate, so "How this is figured" stays open and the keyboard focus
  stays put. While the sensor is unavailable or unknown (the Watcher offline or restarting: HA drops its attributes)
  or not published yet, the count reads "?", never 0, and the folded header says why. 390 px with no sideways scroll,
  44 px targets, WCAG AA in light and dark.
- Ryan's Watcher view: `ha/dashboard_flight_watcher.json` has the card under the pot table, before Swap ideas.
  **Pending on Pako**: Claude applies that one card through the HA connector after the release, with Ryan's yes
  (ha/README.md: the snapshot matched Pako's `be03a0a4...` until the pending edits, 1.7.12's Details tile and this
  card, and is ahead of it by those two, `e95ce9d3...`; Pako reads that once both are applied).
- Tests: `tests/test_fw1714_near.py` (synthetic pairings): each conflict type, the pay math with the PWA rules (VAC
  4:00 a day, the RO override, a dropped trip's credit, a blocked day at nothing, no rate, an unknown credit), legal,
  not legal (FAR rest with its trip and rule, the 11 h home rest) and not known (a time not on file, a customs-only
  short rest), a trip hidden for two reasons, several excluded trips, a same-day trip kept (legal to fly both; not the
  problem), two own trips with one kept, a Dec 1 trip priced from November's package and schedule versions, pilots
  counted without flight attendants on both sides, the order, no FLICA load, the sensor's size bound, both instances
  and the unchanged portal export, the dashboard snapshot and its README wording, and the card in Chromium at 390 px
  light and dark (unavailable, unknown and no sensor; the key staying open with its focus across an update).
  `tests/test_sensor_size.py`'s busy month publishes the near misses too (60 rows, each hidden by a week of VAC, the
  blocked days and own trips), for the admin and a pilot, under the 12 KB bar.

## 1.7.13

### FAR 117 columns with units and headroom

Ryan, Nov 17: "Give FAR-30/7, FAR-100/672 and Room real headers with units, and show headroom against each limit (e.g.
"100h/672h: 10:57 left"). Explain the Room column in the Key." The Schedule card only (far.py, the pot and finds cards
unchanged); the windows Room to 100h tries are the next section's.
- Headers `30h in 7d`, `100h in 672h` and `Room to 100h` (one line each at 390 px; above 700 px the last two take two
  lines and the FAR cells pad 4 px a side, so the grid is within about 15 px of 1.7.11's width and a laptop-sized card
  fits it again); each title names its rule: FAR 117.25(b) (30 consecutive hours free from all duty in the 168 h before
  a report) and FAR 117.23(b)(1) (at most 100 flight hours in any 672 consecutive hours).
- `100h in 672h` is what is left in the 672 h ending 24:00 that day (`10:57 left`; its title `100h/672h: 10:57 left.
  89:03 block flown or scheduled in the 672 h (28 days) ending 24:00 ...`); the block is rounded to the minute once,
  so a cell and its title always add up to 100:00. `Room to 100h` is what is left in the busiest 672 h window that
  holds any part of the day, back and forward (the next section). Both read red `0:00 left` at the limit and red
  `1:20 over` past it, so the word says it, never the colour alone; `~` in front when a window reaches past the
  schedule on file (`~10:57 left`) or holds a trip with no times on file.
- `30h in 7d` words today's states with units: `✓ 36h 11/05` (a report at that day's first duty start, 00:01 on a day
  off, is covered: the longest break off duty in the 168 h before it, whole hours, and the day it ended; a later report
  that day may not be, so its title gives 'covers reports until'), red `need 30h off`, `?` (the 168 h reach before the
  schedule on file), `–` (mid-trip).
- The Key has a row for each column: units, the rule (FAR 117.25(b); FAR 117.23(b)(1), 100 flight hours in any 672
  consecutive hours), what Room to 100h counts that 100h in 672h does not (trips later on the line, the windows it
  tries), and that a trip whose times are not read yet adds no block (`~`) and, with no report and release on file,
  counts as time off in 30h in 7d. The cells stay on one line (no taller rows).
- Tests: `tests/test_fw1713_far_columns.py` (synthetic months, made-up trips H91xx, H93xx, H95xx, H98xx; Chromium at
  390 px, light and dark, and a 936 px box for the pilot's and Ryan's copies): headers and titles, the 100h in 672h and
  Room to 100h cells positive, zero, over and approximate, a cell and its title adding up to 100:00 (half-minute legs),
  Room over on a window ending mid-day where far.py says NO, the 30h in 7d states and which report the tick covers, red
  only with its word, the Key text, the grid's width, far.py's limits unchanged.
  `FW_1713_SHOTS=<folder>` saves the screenshots (390 px and 1024 px). 1.7.11's cross-month test
  (`tests/test_card_cross_month_672.py`) reads the 100h in 672h cell as headroom (`82:25 left` on Dec 2) and the
  trip's block, counted once (17:35), in its title.

### Room to 100h tries every 672 h window, like far.py; unknown trip times marked

Ryan, Nov 18: "fix all of these things" (the FAR 117 gaps item 4's review left open). The Schedule card only; far.py,
recall.py and the pot and finds cards are unchanged here (far.py changes in the review fixes below).
- **Room to 100h finds far.py's windows** (F1): it was 100:00 minus the busiest 672 h window ending 24:00 HST, and a
  window ending mid-day can hold more (on a synthetic line Room read `9:00 left` where far.legality finds 101:00 in the
  672 h from Nov 1 10:45 to Nov 29 10:45, over FAR 117.23(b)(1)). Room is now 100:00 minus the busiest 672 h window
  that holds any part of the day, back and forward: the windows starting at a duty's start or ending at its block-in
  (far._cum's, where the busiest one always is), a duty's block counting when the whole duty is in the window, on the
  spans far.py reads (recall._trip: a duty from the trip's report, or 1:00 before departure from HNL and 1:15 elsewhere,
  PWA 2.19.b, to its block-in), and the windows ending 24:00 HST counted leg by leg as before, so Room never shows more
  room than 100h in 672h. On the same line Room reads over exactly where far.py finds a 672 h window over 100:00 that
  holds the day, or where a window ending 24:00 is over leg by leg (a leg across its edge counted in part), which
  far.py reads `?` (may pass), never OK. The 100h in 672h cell stays the 672 h ending 24:00 that day. Room's title
  names the window's end (`101:00 flown or scheduled in the 672 h ending 10:45 2026-11-29`; a tie keeps the window
  ending 24:00); the "windows ending 24:00 only" caveat is gone from the header, title, Key and README. A window holds
  the day when it holds part of it (far._cum's rule for a pickup), so Room's `~` (a window past the schedule on file)
  reaches a day further each way. Where a trip's duty blocks add up to more than FLICA's trip Block, Room counts the
  duty blocks as far.py does; 100h in 672h still scales them to the trip Block.
- **A trip with no times on file is marked** (F3): it adds 0:00 block, so a 100h in 672h or Room to 100h cell whose
  window holds an own trip with no times (no Block and no duties, a `{}` record, or none) reads with `~` (not known in
  full) and its title names the trip (`~ = not known in full: no block times on file yet for H9205 11/05 (counted
  0:00)`). The Key says so for both cells; 30h in 7d still counts such a trip as time off without a report and release.
- **Ryan's line** (live data, names stripped, not in git): Room on every day of November and December equals far.py's
  busiest window holding that day. Nov 29 reads `6:42 left` (was `10:03 left`: the 672 h from 04:00 Nov 1 hold 93:18),
  Dec 1 `10:03 left` (was `10:04`), Dec 6 `~10:04 left` (was `~16:35`), Dec 7 `~16:35 left` (was `~18:34`), Dec 4 gains
  its `~`; Dec 2's 100h in 672h is unchanged (`16:18 left`, 83:42); every cell is positive.
- **F4**: item 4's queued finding (a trip from the month before taking its release from a later HNL day of the viewed
  month) was fixed in 1.7.11 (`tests/test_card_cross_month_review.py`); a render on this release confirms it (X9620 Nov
  20 to 22 keeps its Nov 22 release in the December view, and Dec 10 shows only X9612's own release).
- Tests: `tests/test_fw1713_room_windows.py` (Chromium, synthetic lines, made-up trips H91xx, H92xx, H96xx): Room over
  on the mid-day window; day by day against far._cum on the same line (a widebody-shaped line with red-eyes, out-station
  duty starts, a trip across Nov 30 and a duty with no block; the mid-day line; item 4's lines at 101:20, at exactly
  100:00 (`0:00 left`, far.py OK) and with duty blocks over the trip Block): over exactly when far.py is, Room's block
  the larger of far.py's busiest window and the windows ending 24:00; `~` and the trip's name for a `{}` record, no
  record and no Block; the Key and header. Each fails on the code before. `tests/test_fw1713_far_columns.py` moves
  to the new cells (Room over on Nov 29 of the 101:20 line, `~` a day further, Room counting duty blocks as far.py).

### FAR review fixes

Two adversarial checks of the FAR fixes above (460 random synthetic lines, 28,060 day comparisons with far.py) found
four gaps. Each is fixed with a test that fails on the code before (`tests/test_fw1713_room_windows.py`).
- **Exactly 100:00 is legal in far.py** (R1): far._cum added blocks as float hours, and about a quarter of block sets
  that add up to exactly 6000 min float to 100.00000000000001 h, so a pickup that brings a 672 h window to exactly
  100:00 read NO `flight time 100:00 h in 672 h, over 100 h` (`FT 100h/672h` in the pot, Tradeboard and finds FAR
  column and the Recall/O75 miss check) while the card read `0:00 left`. FAR 117.23(b)(1) allows 100 h. _cum now
  compares whole minutes (every time on file is one), for the FDP limits too (FAR 117.23(c)(1): five FDPs adding up to
  exactly 60:00 in 168 h read over); one minute more is over. The 1.7.13 claim "at exactly 100:00 (`0:00 left`,
  far.py OK)" now holds for any blocks, not only the `zero` line's.
- **100h in 672h counts a trip with a duty block missing** (R2): its legs held only the duties with a block, so a
  window holding H9201 (Block 20:00, its second duty with no block) counted 10:00 where far.py counts the trip's 20:00
  (recall._trip puts the Block on one span from report to last block-in): `6:00 left` (94:00) against 104:00, no `~`,
  while Room read `4:00 over`. The rest of the trip's Block now counts on the duties without a block (departure to
  arrival, shared by their length; on far.py's span when their times do not read), so a window holding the whole trip
  counts its Block as far.py does. With no trip Block the duties with a block count and the cell reads `~` (`no block
  time on file yet for a duty of H9205 11/05 (counted the duties with a block)`). The Key says both.
- **A no-duty trip's block ends at its last block-in** (R3): 100h in 672h spread it to the release (15 min later,
  PWA 2.19.b), so the 672 h ending 24:00 after a 23:50 block-in held 99:59 of a 100:02 line (`0:01 left`, Room `0:02
  over`). It now ends at the block-in, as far.py's span does.
- **far._cum tries the open edges too** (R4): it tried only windows built on span edges, so for a pairing with no
  flight time of its own (the tests' day probe) the busiest worst window, ending just after 00:00 that day as a span of
  the line leaves it, was never tried: on a line where Room read `5:00 over` on Dec 25 (105:00 in the 672 h ending
  24:00, a leg across its start) far.py read OK `at most 95:00`. _cum now also tries the window ending 1 s after the
  start of the pairing's first span and the one starting 1 s before the end of its last (its report and release when
  it has none): `?` (95:00 known, up to 129:00), as a real 1:00 pickup that day read. "Room over leg by leg, far.py `?`,
  never OK" now holds for the probe, and the test checks it on every day. On 12,000 random synthetic pickups against
  300 random lines only 15 of 21,789 FAR 117.23 checks changed: 2 NO at exactly 60:00 FDP now OK (R1), 13 NO now `?`
  (`over ... even without the pairing: the line on file looks incomplete`), each on a synthetic line already over the
  limit by itself next to the pickup, which a line on file cannot be.
- A rerun of the checks on the fixed code (450 random lines, seeds 11, 22, 33, Nov and Dec, 27,450 days): Room never
  reads left where far.py finds a window over 100:00, never over where far.py reads OK, and its block is never below
  far.py's busiest sure window. The 100h in 672h cell lies between far.py's sure and worst count of the same 672 h
  ending 24:00 on every day, except windows holding a trip whose duty blocks add up to more than its Block (the cell
  scales them to the Block, 1.7.11, as before). 30h in 7d is identical to 1.7.11's on every day.
- Tests: synthetic lines H91xx (exactly 100:00, a float sum over 100 h), H92xx (a duty with no block), H93xx (a 23:50
  block-in), H94xx (Oct to Jan, the probe's edge window), two H9205 records whose second duty has no block (with and
  without the trip Block) and five FDPs (H95xx) at exactly 60:00 in 168 h; on every test line the 100h in 672h cell
  between far.py's sure and worst count of its window, day by day (half100 left out: it scales duty blocks by design),
  and far.py `?` wherever Room is over and far.py's sure count is not.

## 1.7.12

### One data age stamp in place of the two clocks

Ryan, Nov 17 (approved): "Replace the two clocks ("updated" and "Last check") with one "data age" stamp. Turn it amber
past 1x the normal interval and red past 2x." No FLICA page load, no new entity, no contract change.

- **The stamp**: "Data age 12 min", the time since the Watcher's last good read (`sensor.<prefix>_last_check`, which a
  check sets only when it succeeds): seconds under a minute, then minutes, hours and minutes, days and hours. Amber
  with the word "stale" past 1x the check interval (`number.<prefix>_normal_check_every`, minutes; while hunting, the
  switch on or the state `hunting`, `number.<prefix>_hunt_check_every`, seconds), red with "very stale" past 2x, plain
  otherwise. The word goes with the colour, so the colour is never the only cue (colour-blind users, screen readers).
  A last check time that is unknown, missing or not a time reads "Data age unknown" with no colour (unavailable: see
  the review below); an interval that is unknown or 0 leaves the age shown with no colour. Amber `#8a5300` and red `#c62828` on a light card,
  `#ffb74d` and `#ef9a9a` on a dark one (Home Assistant's dark mode, the portal's from the device), WCAG AA on both.
  The code is one block (`// ---- shared data age ...`) the clock and schedule cards carry byte for byte (the cards load
  one file each, so a shared file would change the portal's card bundle); `tests/test_fw1712_data_age.py` keeps the
  copies equal.
- **Clock card**: "Last HH:MM:SS HST (N ago)" gives way to the stamp; "Next" stays. The last good read's HST time is
  in its hover text with the thresholds ("Last good read 01:27:00 HST. Stale past 10 min 48 s, very stale past 21 min
  36 s: ...", the review below). It ticks with the card's 1 s redraw. The Stuck state, its Re-arm and its card colour
  are as before (with the interval known, Stuck reads red on the stamp too: very stale comes no later than its limit).
- **Clock card, `mode: age`**: the stamp alone (no controls), for the Details view.
- **Schedule card**: the header's "updated ..." gives way to the same stamp. FLICA's own schedule time (the schedule
  sensor's `updated`) is only in the stamp's hover text, "FLICA updated Nov 9, 2026 09:54:34. Data age: ...". The
  stamp ticks each second by itself (that one span; the card still redraws only when its entities change), and stops
  off the page.
- **Details view** (`ha/dashboard_flight_watcher.json`): the "Last check" tile becomes
  `{"grid_options": {"columns": 6}, "mode": "age", "type": "custom:flight-watcher-clock-card"}` in its place. Pending
  on Pako (`ha/README.md`): applied through the HA connector right after 1.7.12 is live, with Ryan's yes.
- **A pilot's portal**: his clock and schedule cards (the same files, his entity ids) show the same stamp, from the
  entities the portal already exports (state, last check, the two intervals, hunt mode). Nothing new is exported; the
  portal's tabs and card bundle are as they were.
- The pot card's "Pot last read ..." note (after 15 min) is unchanged.
- Tests: `tests/test_fw1712_data_age.py` (synthetic states): the age text and both thresholds in normal and hunt mode
  (1x and 2x exactly are not past them), unknown or missing values (no colour, "Data age unknown"), the clock card and
  the schedule header in Chromium at 390 px light and dark (the portal's theme and Home Assistant's) with WCAG AA, the
  ticks without a reload or a redraw, the Details view snapshot and its sha256. The clock card's HST check and the
  award line's check read the stamp's hover text now.

### Review fixes (the meaning of "1x" waits for Ryan's yes)

The review ran the first build against the Watcher's real timing and found a healthy Watcher reading amber "stale" on
about half of its normal cycles and nearly every hunt cycle, and a pilot held by his FLICA budget reading red "very
stale" most of the time beside "Slowed.". `gap()` (watcher.py) waits the interval x 0.7 to 1.3 (`JITTER`), the wait
starts when a check ends, and the next check takes time too (a crew index chunk: about 2 min in normal mode, 20 s
hunting), so the bare interval is shorter than one healthy cycle. **This changes what "1x" means in Ryan's rule: it is
built and tested, and needs his yes before it ships** (say no and the stamp goes back to the bare interval).

- **Thresholds** (the shared block): 1x and 2x of the Watcher's longest cycle between two good reads: the interval x
  1.3 plus room for the check (`FW_AGE_ROOM_S`: 3 min normal, 45 s hunting, which also covers a few seconds of a phone
  clock running fast). Normal 6 min: stale past 10 min 48 s, very stale past 21 min 36 s; hunt 40 s: 1 min 37 s and 3
  min 14 s; hunt 5 s: 52 s and 1 min 44 s. On a pilot whose budget holds his checks apart (the state note's "at least
  N s apart"), that pace is the interval. Very stale comes no later than the Watcher's own Stuck limit
  (`stuck_after_s`), so "Stuck." always has a red stamp. The hover text says which cycle it used.
- **Counted from later when the Watcher's wait started later**: after a change of hunt or of the interval in use (the
  entity's `last_changed` after the read: the wait starts over, and a next check planned before the change still
  counts, so Hunt pressed with a 3 min old read no longer turns red at once), and from the next check while the FLICA
  budget or host limit holds it (the gate's note).
- **Watcher offline**: a last check that is `unavailable` (the app is down; every entity has its availability topic)
  reads red "Data age over 12 min, Watcher offline" (from the entity's `last_changed`, "unknown" under a minute), not
  the grey "Data age unknown" of a Watcher that never read.
- **Hover text**: the last good read in HST carries its day when it is not today's ("Last good read Nov 9 23:30:00
  HST."), and the schedule card's has it too. A tap, Enter or Space on the clock card's stamp (both modes) opens it in
  a box ("tap to close"), as the schedule card already did for its titles: phones have no hover.
- **Layout**: the stamp keeps one weight (600) at every level and a 14em minimum width (the clock card's Next 17em).
  On a phone the clock card's stamp starts its own line and Next the one after it, so the card's height and its
  buttons no longer jump 22 px as the age ticks; the schedule header's stamp sits at its right (its own line on a
  phone), so the month arrows and Now stay put at every width. Only a longer state text ("Watcher offline") may move
  them, once.
- **Details tile** (`mode: age`): a 56 px tile like the ones beside it (`getGridOptions`: 6 columns, 1 row), "Data age"
  over its value, never wrapped (an ellipsis); a mode change on the same card element (HA's card editor) builds the
  card again instead of throwing every second or freezing.
- Tests (`tests/test_fw1712_data_age.py`): healthy cycles of jitter and check time (normal 1, 6 and 10 min, hunt 5 and
  40 s, a held pilot) show no colour; the held pace, the gate, a mode change, a phone 8 s fast, the Stuck limit, the
  offline Watcher, the day in the hover text, the tap box, the clock card's height from 360 to 1024 px, the header's
  month controls from 390 to 1280 px, the 56 px tile at 166 and 183 px and the mode change, in Chromium light and
  dark.

## 1.7.11

Ryan's ticket run of Nov 17, 2026. FW-0075 is Ryan's; FW-0076 and FW-0078 are James's, built on Ryan's yes naming
both; FW-0079 and FW-0080 are follow-ups filed under Ryan from FW-0076 by james (its screenshot) ("Fix the crew column and totals too",
scope "Everywhere"); the log masks on Ryan's "Fix the masking text too". **Contract 1 revision 6: HOM 1.9.2 goes
live first.**

### Own trip times are never blanked by a pairing page with no times; a trip across a month end counts once

Ryan, Nov 17: "an own trip's times must never be blanked by a pairing page with no times. Keep times already read when a
page has none, and re-read an empty record hourly." Before, `own_trip_times` wrote an empty record over the times read
before whenever FLICA's pairing page came back with no report or arrival time, and an empty record was never read
again (save on a full Check now), so the FAR column, the pay line and the working flight lost that trip.

The cause (Ryan, Nov 17): the schedule card's Block read 91:04 against FLICA's 103:18. H3620 Nov 15 (block 12:21) had
lost its times: at 16:48 HST, while the FLICA session was going, its in-progress re-read got a page with no times (the
same page stopped pairing reads as "not a pairing page"), and the Watcher replaced the good record with an empty one.
An empty record counted as cached, so it was never read again and the block stayed out of the month. No new kind of
FLICA page, no change to budgets, pacing or the one-session rule; read only as before.
- A page with no times keeps the times already read; one log line says so ("no times on the pairing page; the times
  read before are kept"). A trip with no times read yet stays an empty record, as before.
- A page that stops pairing reads (the Flica client's breaker judged that very page: not a pairing page) is no read at
  all: the times on file and `own_empty_at` stay exactly as they were, a trip never read gets no empty record, and the
  trips after it in the same check are kept (never pruned) and load nothing ("the page stopped pairing reads; the
  times on file are kept (read again in an hour)"). Review: that trip waits an hour (`S["own_stop_at"]`,
  `OWN_EMPTY_RETRY_S`), a trip never read and a Check now too. Before, it was due again at every reopen, and as this
  read runs first in a check its page was the first pairing load each time and stopped the path again (30 min
  doubling to 6 h), so the pot details, pickups and crew index never got a pairing page to close the breaker with. Now
  the first load at the reopen is another reader's (a good page closes the breaker), and the trip's own page is tried
  again an hour after its last try. A read of the trip clears it; a trip leaving the schedule takes it along.
- Review: when the page says FLICA's session is gone (another login took it, "new session under this account was
  detected"; it expired; reads are blocked), no more own trip pages load on it in that check (before: up to 2 more, 11
  on Check now); every trip stays on file and the sensor goes out, and the check meets the same page on the pot and
  yields as before. A load a pilot's budget leaves out (the gate's skip) no longer drops the trips read before it in
  the same check: they are saved, gone trips are pruned and the own trips sensor goes out, then the read is logged as
  left out as before (both older than 1.7.11).
- `S["own_empty_at"]` holds, per trip, when its page last had no times. Such a trip is read again at most once an hour
  (`OWN_EMPTY_RETRY_S`), whether it has times from before or none, inside the per-check limit (`OWN_PER_CHECK`, 3) and
  the 1.5 to 3.5 s pacing. A read with times clears it; a trip leaving the schedule takes it along. The only new FLICA
  load: one pairing page per empty trip per hour, as Ryan asked.
- Schedule card, FAR-100/672 and Room (Ryan, Nov 17: "are they gonna say I am over block on Dec 02?"): a trip
  across a month end (H3607 Nov 30 to Dec 2) is on both months' schedules, and the card counted it once per month, so
  its block went in twice: 101:17 on Dec 2 and Room -7:31, against a real 83:42 (highest window Nov 30 to Dec 14:
  89:56). It now enters the card's trip list once (same rule as recall.line_records), in both months' views. FLICA
  gives a trip in progress no code day on a later page, so both pages list it at its own start (or the later page
  not at all): one trip and start is one trip.
- Checked for the same double count wherever two months' schedule items are joined (a synthetic trip across a month
  end, old code and new): the card's own trip list was the only one that counted it twice. The card's Block, Credit
  and Pay totals, its carried-in trips and prices (keyed by trip and start), FAR-30/7 and Legal next, the Watcher's
  FAR column and 98/672 tag (recall.line_records), the Recall/O75 lines (recall.held_at) and the working flight
  (working.py) count it once. Review, three more joins fixed in the card (all older than 1.7.11):
  - Swap ideas: the trip a swap replaces is skipped by its trip and start. Its copy on the other month's page
    (December's Schedule Lookup rows start in late November) made every day of it busy, so a trip across a month end
    never got a swap idea (no Ideas button).
  - A trip not in the viewed month's package is released on a day of its own (after its start, up to its end). In the
    December view every November trip took the first HNL day on December's page (Dec 2, H3607's return), which moved
    its release, the FAR-30/7 mid-trip days, the trip box, Legal next and the rest a pick-up idea needs (PWA
    10.E.1.a): a legal Dec 3 pick-up 22:25 after H3607 read 12:45 after a November trip, or was not offered.
  - The Open column's clash test, the layover cell and the in-progress mark read every month's items (each trip and
    start once). From Dec 1 December is read on the mobile page, which starts at Dec 1 and gives H3607 no code day, so
    an open-time pairing on Dec 1 to 2 showed as fitting while the Watcher's schedule_fit says Conflict H3607.
- Month totals of a trip across a month end (Ryan, Nov 17: December Credit 73:00 / Block 36:21 against FLICA 80:35 /
  43:56 on 1.7.10): FLICA's December page starts on Nov 30 when a trip runs in (H3607), and its Dec 2 leg (7:35) is
  December's (PWA 4.A). FW-0080 above already counts each duty in the bid period it departs in, so December's Credit,
  Block, Soft and Pay include it and November keeps its own part; a test keeps it so (Ryan's 1.7.12 patch, folded in).
- Tests: `tests/test_own_trip_blank.py` (synthetic pairings, both instances): times kept, hourly re-read, the
  pre-1.7.11 empty record read once then hourly, an in-progress trip with kept times not re-read every check, the
  per-check limit, pruning, no load for a trip with times, and a page that stops pairing reads (times and
  `own_empty_at` unchanged, the later trip not pruned, no further load, no empty record for a trip never read);
  review, on the real Flica.fetch path (a fake browser context): a trip whose page stopped pairing reads waits an
  hour and a good pot detail at the reopen closes the breaker, a killed or expired page loads nothing more, and a
  load the budget leaves out still publishes the trips read before it;
  `tests/test_card_cross_month_672.py` (Chromium, made-up pairing X9607: Nov 30, Dec 2 and Dec 5 in both months'
  views, December's page starting on Nov 30, and each month's Block and Credit matching its FLICA totals); `tests/test_card_cross_month_review.py` (Chromium, made-up pairings: swap ideas for X9607 with its copy on
  December's page, a November trip's release, FAR-30/7, trip box, Legal next and pick-up rest in the December view,
  and the Open clash and layover cell on December's mobile page).

### FW-0075: move the van time in 5 minute steps

Ryan's ticket (Nov 17, page Watcher): "I need to have a plus and a - kind of below the numbers for the van time because
in some cases the company adjust the van time a little tiny bit to accommodate local things that are happening and so
in this case my [van time] says 5:25 am and I would want to be able to switch the van time in five minute increments
so I could set it for 510 for example". The admin's instance only; no FLICA page load, no contract change.

- **The layover card**: under the big van time, "-5 min" and "+5 min" (44 px taps; aria-labels "Van 5 minutes earlier"
  and "Van 5 minutes later"). They show only when `sensor.flight_watcher_layover_van` says `adjustable` (the Watcher
  placed the van the card shows): never for Hark's van the Watcher did not place, never in a portal's copy of the card
  (it now has the `FW_PORTAL` flag; it is on no portal). A press publishes `flight_watcher/van/adjust/set`
  `{"van": <van_id>, "minutes": <the move>}`: the absolute move from the van as read (the Watcher's current move plus
  or minus 5), so a repeated press or a retry never moves it twice. One move at a time: while one is saving, the
  buttons are `aria-disabled` and a tap on them does nothing, so only the answer to that command ends the wait. A
  button at an end of the range (-120 and +120 min) is `aria-disabled` the same way (never `disabled`, so the
  keyboard focus stays on it); when "Back to" goes with its answer, the focus moves to "-5 min". "Saving..." until the
  sensor says the new move; "Not saved, try again" after 10 s without it, after a publish error, or when the van
  itself changed meanwhile. A screen reader hears "Saving", "Van moved to 05:10", "Van back to 05:25" or "Not saved,
  try again" from one visually hidden `role="status"` element that every render keeps. Moved, the big time, its HST, the
  countdown and the alert times are the moved van's; under the buttons "You moved it -15 min (the package says
  05:25)" ("Hark says" for Hark's van; its weekday when the move crossed midnight) and "Back to 05:25" (minutes 0).
  When the package's van wins, "Hark says ..." still shows only when Hark says another time than the package did.
  Every value is escaped; light and dark; 390 px with no sideways scroll.
- **`layover.py`**: `adjusted(info, minutes)` moves the van's instant by a whole multiple of 5 in `ADJUST_RANGE`
  (-120 to +120), then reads its local time, date, weekday and zone letters again on the station's zone (daylight
  time right: 03:10 AEDT less 15 min is 01:55 AEST; midnight right: 00:05 less 10 is 23:55 the day before) and its
  HST time and date; a moved van has `adjust_min`, `orig_local` and `orig_date`. `van_id(info)` is the van before any
  move (the pairing's base id and the van instant as read, UTC). `adjust_ok` is the check: an int (never a bool, a
  float or text), a multiple of 5, in the range. The sensor gets `adjustable`, `van_id`, `adjust_min` (0 when not
  moved) and, moved, `orig_local` and `orig_date`, with a van on the admin's instance; nothing new without one.
- **The Watcher**: `S["van_adjust"]` `{van_id: minutes}` (kept across a restart; at most 8, the newest, the van in
  hand's always). The command is refused with one log line and nothing changed (the van sensor still goes again, so
  the card stops waiting) when the payload is not a JSON object of at most 512 bytes, the minutes are not a whole
  multiple of 5 from -120 to 120 (NaN, 1e999, "5", 5.0 and true are not; nothing in it can end paho's thread), there
  is no van in hand, or the van is not the van in hand's; a pilot's instance refuses it (roles: `admin_pushes`; it is
  in `roles.NOT_ON_PORTAL`, so a portal's spool refuses it like the van settings). 0 removes the move. One log line a
  change, no crew names: "van: moved -15 min by Ryan: H3681 LAS 2026-11-18 05:10 PST (the package says 05:25)". The
  sensor says the moved van at once. `van_tick` applies the move right after `van_source`, under the van lock, so the
  keys, the alerts, the sensor and the van a setting applies to are the moved van's: a moved van is a new van time
  (a new key) and follows the 1.7.1 and 1.7.2 rules (a late start sends the latest alert still due, worded with the
  minutes left; nothing after the van). A moved van's alerts wait 30 s (`VAN_ADJUST_SETTLE_S`) from the first sweep
  that saw the last move, so the 5 minute steps passed through on the way to the time Ryan wants (05:25 to 05:10 in
  three taps, a 10 s sweep between them) send no push and leave no key; only the time he chose gets its alert. Moving it back to the van as read never sends one of that van's alerts again
  (`van_keep` keeps its keys while it is moved). When the van itself changes (a new package, Hark's text, another
  pairing) the move no longer applies: one log line ("van: the -15 min move no longer applies: the van time
  changed"), and it stays in the state only within the 8. The move applied is kept in the state too
  (`S["van_moved"]`), so a van that changed while the app was down (an update, a restart) still gets that one line.
  A sweep that cannot read Hark's sensor drops nothing, and a move taken then does not log that sweep's reason again.

### The pilot lookup: up to 12 matches with seat, base and employee number (FW-0078); this month or next (FW-0076)

Both tickets are James's (reporter james); Ryan said yes on Nov 17 naming both, and only what he approved was built.
**Contract 1 revision 6: HOM 1.9.2 goes live first.** Synthetic data in every test.

- **Up to 12 matches** (FW-0078, Ryan: "show up to 12 matches as Last, First, seat, base and employee #"). A name
  lookup lists up to 12 pilots (5 before; the most pilots sharing one last name in the shared pilot file is 10). More
  than 12 is still no list ("More than 12 pilots match ... Type more of the last name, or Last, First, or the employee
  number."). Both instances.
- **Each entry reads "Doe, Jane · FO · HNL · #10001"**: the name, the seat as before (with the Sen # for two entries
  that would read the same), the base and the employee number. The base is the pilot database record's (its domicile,
  from the award's category), else the award's seniority line's or the seniority list's, else it is left out. The
  entries wrap on a 390 px phone and are 44 px tall; names are escaped.
- **The pick is still the opaque pick id.** On a pilot's instance an entry is picked by its pick id, never by the
  number it shows (the card sends no number for it). Ryan's card picks by the number, as before.
- **This month and next** (FW-0076, Ryan: "This month and next month buttons on the pilot lookup, on both instances.
  One FLICA load per tap, inside the budget."). On a pilot's month the pilot card shows two buttons under the heading,
  this HST month and the next ("Nov 2026", "Dec 2026"). The month shown is pressed and not tappable; the other reads
  that month for the same pilot, "Loading Nov 2026..." while it waits. Before, a lookup always showed FLICA's default
  month, which after the award is the next bid month (December on Nov 17).
- **One page per tap.** With a month the Watcher reads only that month's Schedule Lookup page (`bd=MMYY`), then the
  pairing pages as before, paced 1.5 to 3.5 s, inside the pilot's FLICA budget and the host gate like every lookup.
  The 6 h cache is per month (a month the default lookup already read is served from it); FW-0057's previous month
  follows the month read. Only this HST month or the next is taken; any other is refused with one log line and a
  status line on the card. A lookup with no month (a name, a pick, a #pilot= link) is exactly as before.
- **The same pilot.** Ryan's card sends the employee number; a pilot's card sends the field that found the pilot it
  shows (his pick, the number of a #pilot= link, or the number he typed), which his Watcher publishes as the pilot
  sensor's `ask`; the pick of the pilot shown stays usable for his month buttons after the pick list's 30 min. The
  card's 2 s guard covers a month tap.
- **Contract 1 revision 6.** `pilot/set` takes one more key, `month` (YYYY-MM); `commands.key_since_revision`
  (`{"pilot/set": {"month": 6}}`) marks the key the way revision 5 marked a value. HOM 1.9.2 takes a `pilot/set` with
  `month` only from a revision 6 export and goes live first. With HOM 1.9.1 still live a month tap is refused by its
  pinned shape ("pilot/set: month is not allowed") and the card says "The month choice needs a portal update (Nov 2026
  was not read)."; nothing else changes for James. No mask changed: the pick list's `emp` and `base` pass the portal's
  masks (only `contact` is dropped and the file keys zeroed). The fixture is regenerated: sha256
  `a066d935367dfc736383bb4a6b1fa71d114fee26defcb2de8479695759ed2ec9`.
- **Rollback to 1.7.10** (Flight Watcher first; HOM 1.9.2 can stay, it takes revision 5): safe. 1.7.10 refuses a
  `pilot/set` with `month` by its own shape check (one log line, nothing read), its card has no month buttons and its
  pick list is back to 5 entries of name and seat. The per-month cache rows (`pilot_sched:<emp>:<YYYY-MM>`) are ignored.
- **Review fixes** (synthetic data in every test; no contract change, the fixture is unchanged):
  - A month tap answers from the newer read of its month on hand, the month's own or the lookup's with no month
    (fetched_ts), so it never reads FLICA again, or shows an older read, while a newer one of its month is cached;
    a month's versions are priced from that same read. A lookup with no month uses its own read, as before.
  - The pick list's base is never another pilot's: on Ryan's instance a pilot database hit shows its own record's
    domicile, a crew directory hit the directory's only when that row names the same last name; a seniority list
    record on a shared number ('also') never takes the first record's seat or base.
  - A month tap whose page cannot be read (or whose read fails) rebuilds the month asked for from the crew lists and
    names it ("Dec 2026: not readable ..."), never this month's rebuild.
  - On the portal the note "The month choice needs a portal update (Nov 2026 was not read)." now shows: HOM's shell
    swaps in a fresh pilot card before the refusal arrives, so the card keeps the note on its class (for the sensor
    and the pilot it names) and every pilot card on the page draws it. A refused tap can be sent again at once.
  - A month tap the Watcher keeps for later (yielded, paused) reads "Loading Nov 2026..." with that month pressed and
    both buttons waiting; a lookup still unanswered after its wait frees the buttons again ("Still waiting after N
    min for Nov 2026: ..."); a pilot shown under a number the shape refuses (8 digits or more) gets no buttons.
  - The pressed month is white on #01579b (7.6:1, the layover pill's), not the theme's primary pair (white on Home
    Assistant's #03a9f4 is 2.63:1, on #009ac7 3.26:1).
  - The card test pins its clock inside the page (it read the real clock and would have failed from Dec 1 HST).

### FW-0080: totals by bid period, everywhere (PWA 4.A)

Ryan, Nov 17: "Fix the crew column and totals too", scope "Everywhere". Seen in a pilot's screenshot (FW-0076, a
report only): another pilot's December showed Credit 15:00 and Block 11:15 in red beside FLICA's 6:39 and 5:52.

- **Why.** The Watcher and the cards totalled a month by the calendar month; FLICA totals the bid period (December
  2026 runs Dec 2 to Dec 31, November Nov 1 to Dec 1, its package days read "D1"). A trip Dec 1 to 3 (duty 1 Dec 1,
  duty 2 Dec 3) counted whole in December; FLICA's December holds only duty 2. 1.7.7 had chosen the calendar month on
  purpose; the bid period replaces it everywhere.
- **The rule** (`pay.split_by_period` / `pay.period_share`; the schedule card's `fwSplit`, the same rule, tested side
  by side): each duty counts in the bid period that holds its HST departure date (its `dep` minutes, never a weekday
  field). Its credit is its TCRD from the pairings package detail (paired by index with the package's duties, only
  when both list as many); the bid period of the trip's first day keeps the rest of the trip credit (rig, minimums), so
  the parts add up to the trip: November 8:21 / 5:23 and December 6:39 / 5:52 for the 15:00 / 11:15 trip. With no
  TCRD on file: the block share, marked an estimate. With no duty times: the whole trip pays in the bid period of its
  first day.
- **The bid period** comes from the pairings package (`start` / `end`), else the calendar month as before, and the totals'
  title says which. Ryan's schedule card and the PAYP split also take the schedule pages on file before the calendar
  month (the schedule sensor's new `periods`, `bid_bounds`, `bid_period_fn`); another pilot's month and the rebuilt
  month have no schedule-page fallback (their `period.src` is `package` or `calendar`).
- **Another pilot's month** (`pilot_price`): no `start[:7] == month` guard; a trip counts in a bid period when its part
  there is not zero, so a trip from the bid period before counts its own part. A crew index trip that starts before
  FLICA's grid and flies on into the bid period counts its part too (`carry`, only while FLICA's grid shows its days
  free with a layover cell). VAC and PAYP days and the pay line's dates are the bid period's. The line carries
  `period` ({from, to, src}); each split trip's `split` names its part here, the part in the other bid period
  (`out_credit`, `out_blk`), `side`, `other`, `edge`, `est`, `none`.
- **The rebuilt month** (`pilot_pay_line`) and **the versions** (`pilotver_<key>.json`, its `pay` with `period` and
  `carry`) count the same way.
- **Ryan's own month** (the schedule card): rows, totals, the carried-in trips (named under the totals), the PAYP
  estimate's checks and the versions' Awarded / Improved-Pay-Gross (`price`) all by bid period. A trip whose own times
  are not read yet places the package detail's duties (each duty's first leg, made HST with the Watcher's time zones)
  and takes its credit from its own bid period's package. The month's Improved-Pay-Gross goes to the Watcher once every
  package a price asked for is in (one report a load, priced with the TCRD, never the block share first; F#32).
- **A PAYP's kept credit** splits by bid period with the removed trip's TCRD (`versions.payp_entries` with
  `bid_period_fn`, `payp_tcrd`). Listed again on the next page (December's page starts on Dec 1, November's bid
  period's last day), its continuation record carries the share of the bid period of its days, Dec 2 on (the card
  also reads that share off the November record when December's page has none yet). A record kept from 1.7.10 (the
  calendar month's split, or none) is split again from the removed trip's duties in own trips or the versions (only
  its split changes), and the PAYP records in the stored versions once (`repair_payp_splits`, `payp_fix_v`). The
  versions' change line says "by bid period".
- **Another pilot's pairing page legs** make duty periods as Ryan's own trips and the package's do (a gap of 8 h or
  more starts a new one), so a duty whose legs cross HST midnight counts on its first leg's date whichever source
  prices the trip.
- **Cards.** A split trip's Block and Credit show its part in this bid period, purple (`--fw-split`, WCAG AA light and
  dark), titled for example "5:23 block, 8:21 credit flown before Dec 2 pay in the November bid period (PWA 4.A)". With
  no duty times on file the title says where the trip starts and that the whole trip pays in that bid period. Only a
  pairing is marked split (a reserve or other code on a grid day outside the bid period stays plain). The totals' title
  says "flown in the bid period". A totals line that matches FLICA shows its check mark, no red.
- Tests: `tests/test_fw1711_totals.py` (the Dec 1 to 3 shape both ways, the block share fallback, a VAC day on Dec 1 in
  November, a carried trip, the versions file, the rebuilt month, the PAYP split, the card's split against the
  Watcher's, Ryan's schedule card in Chromium) and `tests/test_fw1711_review.py` (the PAYP listed again on December's
  page, 1.7.10 records and versions split again, the legs' duty periods, the card's package duties, plain codes, the
  no-times title, one Improved-Pay-Gross report). The tests that pinned the calendar month (`tests/test_review176_pay.py`
  and the two month-boundary PAYP tests in `tests/test_payp.py`) now pin the bid period, each saying why.

### FW-0079: the pilot card's crew on a phone

Seen in the same screenshot (FW-0076, a report only): at 390 px with crews about 41 characters long the grid was about
606 px wide in a 368 px frame, clipped with no scrollbar a phone shows.

- On a phone (700 px or less) the pilot card hides the Crew column and lists the crew under the grid, one line a
  pairing ("H9601 Dec 1: CA Doe, Jane · FO Roe, Rick"), each pilot a no-wrap span, the looked-up pilot's call, text
  and mail links kept; the header cells are 3 px padded there. Down to 360 px the grid fits: the Credit, Soft and
  Pay-Gross cells (the columns with no twin in the shared look) are 1 to 2 px padded, Pay-Gross heads two lines, and a
  one-day turn's report and release may share its Layover cell on two lines when the grid needs it. A wider card keeps
  the Crew column while the grid fits it; one whose grid does not (a tablet in portrait, a long crew) lists the crew
  too, measured on the card's own width after each draw and resize. Everything is escaped as before. The shared grid
  block is untouched; the day, date, trip, layover and block cells keep the schedule card's look and every other row
  its height.
- Tests: Chromium (node Playwright, `tests/fw1711_pilot_render.js`) at 390 px light and dark (the grid fits its box,
  the list names every crew, a name with markup stays text) and 1024 px (the Crew column shows, the list is hidden);
  `tests/test_fw1711_review.py` at 360, 375 and 390 px with and without one-day turns, and at 820 px (the list).
  `test_pilot_grid_look` and `test_pilot_contact_card` now measure the phone's crew list instead of the hidden column.

### Log masks: fixed text is no longer blanked

Ryan, Nov 17: "Fix the masking text too." Two lines seen live on 1.7.10, and every other fixed log text checked the
same way. The name, employee number, e-mail and phone masks are as strong as before or stronger: a review compared
each phone form beside each kind of neighbour (a date, a version, an employee number, a pairing, a name) and each
way of joining them with 1.7.10, and no form that 1.7.10 masked passes now. Synthetic data in every test.

- **Ryan's log, the cap_credit line.** smart.json's ignored `cap_credit` text said "(Ryan, Nov 9: the PWA does not
  cap voluntary adds)", and the admin's log mask (`captures.mask_crew`, the 'Last, First' rule) read "Ryan, Nov" as
  a crew name: the log said "(xxxx, xxx 9: ...". The text now says "(Ryan's rule of Nov 9: the PWA does not cap
  voluntary adds)", which neither mask touches. The name rule is unchanged.
- **James's log, schedule versions and months.** The phone rule (`captures._phones`, used by a pilot's log mask and
  for FLICA page text in Ryan's log) took "12.002 (2026-11" for one 11-digit phone number, so a pilot's log said
  "schedule version ##.### (####-##)". Now an ISO month or date (2026-11, 2026-11-17) and a schedule version (one or
  two digits, a dot, three digits: 12.002) are never a phone number or part of one, with three exceptions where the
  dotted group is the phone's own: a number that starts with "+" ("+44.207 946 0958", "+49 30.123 4567"), a group
  with 7 or more digits around it on both sides ("808 12.345 0101"), and an area code before a 3-3-4 number ("Nov
  17.808 555 0101"). The text between dates and versions is read by the phone rules on its own (a dot or a dash
  right after a date reads as a space there: "2026-11 -808 555 0101"), so a phone right after a date or in brackets
  after a version is still masked.
- **A number beside a date or a version** that the phone rule used to take with it is masked still: a 5 to 7 digit
  number joined by spaces, brackets, a dot or a dash ("2026-11-17 10001", "10001. 2026-11-17", "2026-11-17 -10001");
  a 3 or 4 digit employee number after "pilot" ("pilot 6593 2026-11-17"), after a quoted "emp" key ("'emp': 6593")
  or beside a masked name (a pilot's mask: "Doe, Jane 6593 2026-11-17", "DOE JANE 6593 (2026-11)", "6593 Doe,
  Jane"; the admin's: "DOE, JANE 999 (12.002)"). Counts beside a date stay ("pilot 3 2026-11", "12 pilots read
  2026-11-17").
- **Phones the phone rule let through before** are masked now in a pilot's log and in quoted page text:
  - written with spaces only: an international number ("+1 808 555 0101", "+44 20 7946 0958") and the 3-3-4 shape
    ("808 555 0101"). Before, those passed as "numbers in a row". Numbers in a row ("1 2 3 4 5 6 7") still pass;
  - at the end of a sentence or a clause ("call 808-555-0101.", "808-555-0101- ...", "808-555-0101: crew desk"),
    read by a rule of its own that takes only a phone's shape (a "+" number, three groups or more, nnn-nnnn, or a
    North American number), so a count, an epoch or a decimal before a full stop stays ("size 10485760.", "ts
    1763400000.", "lon 157.92245.") and a time before a colon stays ("12:30: ok");
  - beside another number ("1-808-555-0101 10001", "10001 808 555 0101", "808-555-0101(1234567)"), and a phone's
    group that the rule's 20-character window left out ("123456 (808) 555 0101 2026-11-17" left "0101"), read
    again from the next number or grown by the group beside it;
  - a phone another rule took a part of ("LAS (808) 555 0101": the name rule took "LAS (808)").
- **A name beside a masked number.** In quoted page text a number right beside a date is masked first, so the two
  name rules that wait for its digits ("trade: DOE JANE 10001", "Captain: DOE JOHN 10001") missed the name when a
  date followed it (this was so before too, through the phone rule). They read the digits the phone rule masked now,
  and only those: an employee number's label stays readable ("employee number #####", "FO: EMP NO #####"), and a
  number followed by "#" is read as before ("trade: DOE JANE 10001#12").
- **A line masked twice** (page_log, then the log filter) keeps the date after a labeled number ("emp# #####
  2026-11-17", before "emp# ##### ####-##-##"): the label rules take one or two "#" but not a masked number.
- **Fixed texts reworded** so neither mask blanks them (the sweep below found each one; no mask was made weaker):
  - `Swap draft (...)` (was `SWAP DRAFT`) and `Drop ready (...)` (was `DROP READY`): a pilot's mask took the two
    capital words for a name.
  - `pilot db: the file is from a newer release of this app` (was `... a newer Flight Watcher`): "Watcher" is no page
    word.
  - `alert email: ... (pickup speed rescored)` (was `Pickup Speed`).
  - `contact list read again (parser n): ... with HAL notes, n notes segments not read` (was `HAL Notes`).
  - `upload: contact list (<ext>, n KB) ...` (was `(n KB, <ext>)`: "KB, CSV" read as 'Last, First').
  - `trade seen on the schedule (...): <detail>; Pay-Gross ...` (was `<detail>, Pay-Gross`: a detail ending in a
    capitalized word read as 'Last, First').
  - `pilot lookup: schedule version ... (<month>, from the FLICA schedule)` (was `(<month>, FLICA schedule)`).
- **Guard tests** (`tests/test_fw1711_log_mask_text.py`, `tests/test_fw1711_log_mask_review.py`): the sweep reads
  every log text in flight_watcher/*.py (log.info, warning, error, debug, exception, critical; the texts captures,
  ntfy, pdbshare and smart hand to the Watcher's log; the texts sent through `portal_once` and the gate's `_say`; and
  the texts a module helper returns, such as the pilot database's merge line), fills its holes with neutral samples
  (a pairing, a schedule version, a month, a count, an exception's name, and on the admin's mask a station; the
  strings the code names, such as smart's ignored texts, as they are) and fails when either mask changes a fixed
  character, a hole that holds no capitalized word, or finds a phone number in the line. A log call whose text the
  sweep cannot read fails unless it is listed with its reason (today only the two wrappers' own bodies). Its allow
  list (texts meant to carry a masked value) is empty. Each phone form beside each neighbour is checked on both
  instances, and the phone rule stays linear on long lines.
- Not changed: cards, the database, exports, FLICA reads and budgets, the portal, pushes.

### Integration review fixes

What broke with the four branches together, or on the first start after the update from 1.7.10. Synthetic data in
every test (`tests/test_fw1711_integration.py`); no contract change, the fixture is unchanged (sha256
`a066d935367dfc736383bb4a6b1fa71d114fee26defcb2de8479695759ed2ec9`); no FLICA load.

- **A rebuilt pairing splits by bid period** (FW-0068 with FW-0080). FLICA's rebuilt copy of a package pairing
  (H9635B) found no duties, so another pilot's December gave it 0:00 and November the whole 15:00 / 11:15 under "no
  duty times on file". Another pilot's month, its carried trips and the rebuilt month now use the base id's package
  duties and TCRD (`pkg_det`, `pkg_detail_for` with the trip's first day, `payp_tcrd`), only when that bid period's
  pairing file lists the base id on the trip's first day (`pkg_base`, the pilot card's rule): never for a trip on
  another day, such as a part of it (H9640A).
- **The first start after 1.7.10 makes no schedule version** (`repair_payp_splits`). A stored version's records have no
  `end`, so the repair took a continuation PAYP (PAYP|12-01) for Dec 1 alone, November's day, and dropped it; its
  span now comes from the version's own PAYP item, and a continuation whose span cannot be read is kept. The records
  on file are priced first (`payp_refresh`; a record of a PAYP on the schedule that it no longer keeps leaves own
  trips, as `own_trip_times` prunes it), and each repaired version's fingerprint is made again, so neither the start's
  `versions_check` nor the first check's makes a version or sends `event/schedule_version` when FLICA changed nothing.
- **The repaired versions' change lines** say what the records now hold, in the bid period's words (their PAYP lines
  written again from `versions.diff`; "by month ... 7:04, 10:56" became "by bid period ... 9:30, 8:30").
- **A PAYP whose trip still flies in part** (H9640A flies the Dec 2 and Dec 3 duties of H9640, the PAYP is Nov 30 to
  Dec 1): its kept credit (18:00 less 8:30) splits only the duties departing on the PAYP's own days, so November gets
  its 9:30 (PWA 4.A, PWA Definitions 57); before, November 1:00 and December 8:30, which H9640A already pays. The
  one-time repair does the same, with the PAYP's days from the version's item.
- **A month tap while Schedule Lookup reads are paused** says so with its month ("Loading Nov 2026... Schedule Lookup
  reads are paused until ..."): the paused line was said once a pilot, so a tap for the pilot already shown stayed
  "loading" for hours. It is said once a request now, for the pilot and the month.
- **The pilot month an older release left in HA** (the retained `pilot_schedule`, which the portal exports as it is)
  is priced again by bid period at the start, when its pay lines carry no `period` (`pilot_shown_reprice`: from its
  stored read, served as cached, else from the sensor's own fields), so James never sees 1.7.10's calendar-month
  totals in red under the bid period's title until his next lookup.
- **On a phone the split explains itself**: a line under the totals ("Purple Block and Credit: only the part flown in
  this bid period (PWA 4.A ...). H9635 Dec 1: 5:23 block, 8:21 credit pay in the November bid period.") and the split's
  reason in the pairing sheet (and the wide card's panel) a tap opens. Touch never shows a title.
- **Docs**: `PORTAL_CONTRACT.md` section 5.7 said the name lookup gives at most 5 matches (12 since FW-0078, and it
  pointed at section 5.3, which is pref/set; the doc's own sha256 pin in `tests/test_doh_settings.py` and
  `tests/test_van_settings.py` moves with it, the fixture's does not); HANDOFF's release list called 1.7.11 FW-0075
  alone with no contract change (it is revision 6, HOM 1.9.2 first, with every item above).
- **A test that read the wall clock** (`test_a_new_denial_pushed_with_its_view_page_is_not_read_twice`) failed about
  once a run in 60 (at :59.x the request cap is 599 s, not 600); its clock is pinned to three seconds of a minute now.
- **Not fixed here, needs a contract change:** the month buttons are this HST month and the next, as contract 1
  revision 6 words them in the pinned fixture. On a bid period's day after its calendar month ends (Dec 1, 2026 is
  November's) the bid period being flown cannot be picked; offering it changes the rule the fixture states.

## 1.7.10

Ryan's decisions of Nov 15 about the pilot database: "The pilot database should be shared with James 100%; we work on
a shared system; we do have our own schedules and pay rates though." They replace the 1.7.9 limits named below. No
new command, no new FLICA page load; the FLICA budgets, pacing, one-session rule and every FLICA read limit are
exactly as they were, and schedules and pay rates stay each pilot's own. Synthetic data in every test.

Ryan's decision of Nov 16 is in here too: a portal pilot uploads the contacts list into the shared database. That
one adds a kind to a command, so the release is **contract 1 revision 5 and HOM 1.9.1 goes live first** (its own
section below).

### Part one: the pilot database shared 100%, on by default; AI notes on; a pilot's uploads merge into it

- **Shared 100%.** Before (1.7.9): a shared pilot's file held only the pilots with a shared note, with no employee
  number, phone or email; the pilot he looked up came as a brief, with that one pilot's phones and emails. Now his
  file holds EVERY live record (about 1228 on Pako) with every field: employee number, name, Sen #, DOH, status,
  retirement, seat, equipment, base, union id, phones and emails; the notes field; the whole dated log; each picker's
  pickup history (the summary of all his pickups and the newest 100 rows); and the AI note.
- **No "Only me".** The option is gone from both cards. Every entry 1.7.9 kept as only-me becomes a shared one at the
  first start (and at every later open, so a restored older copy follows). Ryan: "Share those too."
- **On by default.** Sharing is on for every pilot with a portal (James now, anyone Ryan adds later) with no tap. The
  "Share with <pilot>" switch on Ryan's card stays as his OFF switch and the way back on.
- **AI notes on by default** (decision 3). Ryan's AI switch turns them off and on. HOM's consultant cost cap and the
  anonymous-statistics rule are unchanged. A stored note goes into a pilot's file only when it still passes Flight
  Watcher's own text rules (`refuse_re`, the model name's pattern).
- **Ryan's choices are kept out of the database** (decision 2): `/data/pilotdb_switches.json` (0600, the Watcher's
  own file beside its state; `pilotdb.Switches`). Only a tap of Ryan's writes it. What I chose for the 1.7.9 "a copy
  put back turns both switches off" fix: it is removed, because the switches are no longer in the copy. A daily copy
  put back now changes neither switch: what Ryan switched off stays off, what is on by default stays on. The share
  rows and the AI flag a 1.7.9 database still holds are not read any more. If the switches file is there and cannot
  be read, everything is off (it fails closed) and the card says so until Ryan taps a switch.
- **A pilot's uploads merge into the one database** (decision 4). An award James uploads on his portal (through
  `upload/pdf`, its checks and its quarantine, as before) and a contact or seniority list his instance saves are
  merged like Ryan's own, with James recorded as the author of every value and record they make. Before, a row of a
  pilot's contact list that matched no record made none and was held for Ryan. Ryan's hand edits still stay on top
  of every upload, and every earlier value is in the record's history for him to put back. This settles the question
  left open in 1.7.8 (refusing those kinds on a pilot's instance): they are accepted and merged.
- **The portal card** (`flight-watcher-pilotdb-card.js`, portal mode): a full browse and search of every pilot, as
  Ryan's card. "All pilots (N)": a search (name words, an employee number, s812 for a Sen #, "quoted" text in the
  notes and the log), filter chips (All, Notes, Edited, Pickups, Gone), the list by Sen #, 50 rows at a time. Any
  record, looked up or tapped, opens with every field, Call / Text / Mail links, the notes, the log, the pickups, the
  AI note read only, and field edits as before. 16 px fields, 44 px controls, no sideways scroll at 390, 820 and
  1280 px, light and dark.
- **Removed, because 100% sharing makes it dead:** `roster.json` (a roster 1.7.9 left under `/data/pilotdb_roster` or
  the share folder is deleted), the brief of the looked-up pilot in the sensor (`shown` now only says which record
  of the file he is: `{emp, pid}`), `pdbshare.ai_note_of`, the "look the pilot up first" answer, and the 20 briefs an
  hour cap. The name lookup's pick list reads the names and seats of the pilot's own file instead of the roster.
- **Size.** The file is capped: over 4 MiB (`export_bytes`, unchanged) it carries 20 log entries and 20 pickup rows a
  record and says `full` (new notes are refused, as in 1.7.9); it never passes 7 MiB (`pilotdb.EXPORT_HARD`), under
  the 8 MiB a signed file may be. Measured on a synthetic database of 1300 pilots: 0.64 MiB with two phones and an
  email each; 1.06 MiB with 60 pickers of 25 pickups and their AI notes (about what Pako holds); 3.20 MiB with a
  300 character notes field and three log entries on every pilot, 150 pickers of 30 pickups and 150 AI notes.

### A portal pilot uploads the contacts list (Ryan, Nov 16): contract 1 REVISION 5, HOM 1.9.1 first

Ryan: "His uploads should update the shared database too", and the contacts list upload on James's portal "Now, in
1.7.10". No FLICA page load is behind any of it; every FLICA budget, the pacing and the one-session rule are as they
were. Synthetic rows in every test ("Doe, Jane", 10001, 808-555-0101, an example.com address).

- **What a pilot does.** The pilot uploads card on his portal's Settings tab offers "Contacts list (CSV)" beside the
  pairings package and the award, only while the pilot database is shared with him. He picks the airline contacts
  list's CSV export (first row "First Name, Middle Name, Last Name, Suffix, Company, Job Title, Mobile Phone, Email,
  Employee ID, Notes"; at most 1 MiB). The card checks the header before it sends anything.
- **How it travels.** The same `upload/pdf` parts with `kind` `contacts`. His Watcher puts them together and checks
  the whole file (`pdbshare.contacts_check`: size, sha256, text only, the header row, the row and cell bounds, then the parser Ryan's own
  contact list upload goes through, `contacts.parse` of the 1.4.8 uploads path), keeps nothing of it, and drops it
  into his pilot inbox under `/share/flight_watcher/pilotdb/inbox/<name>/` (0600), like `pilotdb/edit`. Ryan's
  Watcher, the single writer, takes the author from the inbox folder's name (never from the payload), runs every
  check again and merges it (`pilotdb.pilot_contacts`); the answer comes back to the pilot's card with counts only
  ("Contacts merged: 4 rows read, 2 pilots added, 2 updated, 0 held for Ryan"). Limits: one list of a pilot waiting
  at a time, 4 merged for a pilot in 24 h, and his 4 uploads a day count it too. The log has counts only.
- **What the merge does (the choice, exactly): it only adds and updates** (`pilotdb.merge_contacts`, additive; the
  default for every author but ryan, so a list a pilot's instance saves the old way follows the same rule):
  - a row is matched like a row of Ryan's own list; a row that fits no record makes one with the pilot as its
    author; a row the matcher cannot place is held for Ryan;
  - a value it gives (name, Sen #, DOH, status, retirement month, union id) is written with the pilot as its author,
    and the value before it stays in the record's history for Ryan to put back; a value already there is left as it
    is, its author and date too;
  - an empty cell drops nothing;
  - phones and emails are added AFTER the ones on file (4 phones and 3 emails at most, so a full list is left
    alone); a pilot's list never replaces or removes a phone or an email, whoever set it (the value they are added
    to keeps its own author; the history names the pilot for the addition: review fixes below);
  - a pilot the list does not hold loses nothing; nobody is marked gone or back; no record is deleted;
  - Ryan's hand edits stay on top;
  - the date and row count Ryan's next list is measured by do not move, so his list is never "older" or "partial"
    because of a pilot's. Ryan's own next list still says what it lists, and no longer removes a value only a
    pilot's list gave from a record his list does not hold.
- **The contract is revision 5** (`roles.CONTRACT_REVISION`, the manifest, `PORTAL_CONTRACT.md` 5.6.1, the fixture).
  One command shape changed: `upload/pdf`'s `kind` takes `contacts` (`commands.value_since_revision`: the value is
  revision 5's; the command stays revision 3's). New in the fixture: `commands.pilot_contacts_limits`,
  `commands.pilot_contacts_checks`, `commands.value_since_revision`, five `commands.pilotdb_answers`,
  `pilotdb.inbox.contacts_max_bytes` and `contacts_body`, `revisions.5`, one accepted sample (a made-up list) and
  three refused ones. The fixture is regenerated (again by the review fixes below): sha256
  `4e7812d603f97a6e46ff00fc8b6cf6f3dc32708db1539f15010566e6095a192b` (`tests/test_portal_contract.py`
  `CONTRACT_SHA256`); HOM 1.9.1 pins those bytes (the first build of this section was `051676bbdf48...`).
- **The order: HOM 1.9.1 FIRST, then Flight Watcher 1.7.10.** HOM 1.9.1 takes revisions 3, 4 and 5. If Flight
  Watcher 1.7.10 is live while HOM 1.9.0 still runs, James's portal is NOT broken: HOM 1.9.0 reads a manifest's
  revision only to refuse a command newer than the Watcher speaks, so everything it served it still serves; only the
  new choice is refused, by HOM 1.9.0's own pinned shape, at the first part ("the portal does not take a contacts
  list yet (it needs its next update). Nothing was sent."), and nothing reaches the Watcher. The card cannot hide the
  choice for an older portal (nothing tells a card the portal's revision), so it is refused cleanly instead.
- **Boundary changes of this section** (all by Ryan's decision of Nov 16):
  16. A portal pilot's `upload/pdf` takes a third kind, `contacts`: a command shape HOM checks changed (revision 5).
  17. A file a portal pilot sends reaches Ryan's Watcher: the CSV goes through his pilot inbox folder (before, only
      a note or an edit of at most 32 KB did; an inbox file of cmd `contacts` may be 1.5 MiB).
  18. A portal pilot's file is merged into the one database with no Approve by Ryan (the award and the pairings
      package keep their quarantine and his Approve, Remove and Reject). It can add records, add phones and emails,
      and change the contact list's own values; it cannot remove, mark gone or override a hand edit.
  19. A pilot's contact list, by either way in, no longer removes what a row of it leaves out (1.7.10 part one
      merged it exactly like Ryan's own list, removals included).
  20. Ryan's own contact list no longer removes values a pilot's list gave from a record his list does not hold.
  Not changed: `roles.py` PORTAL_CMDS and PORTAL_REFUSED (no new sub), the FEATURES gates (the words of
  `pilot_uploads` now name the contacts list; who has it and the portal flag are the same), every other shape,
  PILOT_UPLOAD_LIMITS and PILOT_TICKET_LIMITS, a shared pilot's note and edit quotas, the PDF kinds' checks and
  quarantine, every FLICA budget, the CSP, rate limits and routes (HOM's), push isolation. No name, number, phone or
  email of the file is logged, put in a sensor, an event or a push; the pilot's answer has counts only. A pilot's
  upload and every entry from it are untrusted data, never instructions.
- Tests: `tests/test_fw1710_portal_contacts.py` (the contract, both Watchers' checks, the merge rules, the inbox
  hand-off and its refusals, the whole path from the portal's command to the database with the pilot as author, and
  the card in Chromium at 390 px, light and dark).

### Review fixes of the contacts list upload (Nov 16)

A review of the section above found ways one pilot's list could do more than "add and update". Each is fixed with
a test that failed before (`tests/test_fw1710_contacts_review.py`). The contract stays revision 5; its limits, its
checks text and two answers changed, so the fixture is regenerated (sha256 above) and HOM 1.9.1 pins the new bytes.

- **One pilot's lists can no longer flood the shared database.** `roles.PILOT_CONTACTS_LIMITS` has two new bounds.
  `rows_max` 2500: a list with more rows under its header is refused by both Watchers ("Not merged: a contacts list
  is at most 2500 rows"; the export has about 1230). `new_max` 250: the live records that only pilots' lists made
  (created by a pilot's list and held by no list of Ryan's: the seniority list, an award, his own contacts list),
  all pilots' lists together. A list that would take the database over it is refused WHOLE and changes nothing (the
  merge runs in a savepoint and is rolled back: no record, no value, no history row, no held row): "Not merged:
  over 250 pilots that no list of Ryan's holds; ask Ryan to upload his own list first". It counts toward that
  pilot's 4 lists in 24 h. A pilot's own hand edit does not make a record Ryan's; Ryan's own list holding the pilot
  does. A list that adds nobody is never refused for this. Before: one 1 MiB list added 9500 made-up records, four
  a day, filled every shared pilot's file and pushed real records out of it.
- **No cell can hold the parser or the database.** `cell_chars` 200 and `notes_chars` 2000 (the Notes cell), and no
  text in a cell beyond the header's ten columns (empty cells after them, a trailing comma, are fine): checked with
  the csv module before the parser reads a byte (`pdbshare._contacts_cells`). `contacts.EMAIL_RE` reads a long run of
  letters once (a local part starts where its run starts and is at most 64 characters, RFC 5321; every address of 64
  or fewer local characters is found exactly as before, in Ryan's own uploads too). Ryan's Watcher now checks a
  waiting list BEFORE it takes the pilot database's lock (`pdbshare.contacts_precheck`, `watcher.pilotdb_share_pass`);
  only the merge runs inside it. Before: a well-formed list with seven 130000 letter email cells held the lock about
  100 s; now the largest crafted list is checked in well under a second.
- **A held row of a pilot's list that Ryan answers is applied the way the list is** (`pilotdb.resolve`: additive when
  the row's ref is a pilot's list). Attach, Same pilot, New and Different add its phones and emails after the ones on
  file and drop nothing. Before, Attach replaced Ryan's list's phone and dropped the email and the retirement month.
- **Whose value it is (the rule, exactly).** When a pilot's list adds a phone or an email to ones on file, the value
  on file keeps its own author, ref and date (Ryan's numbers stay Ryan's list's) and the record's history names the
  pilot as the author of the addition, with the value before and after. A phones or emails value the database did
  not have is the pilot's own (his name, ref `pilot contacts <day>`). So Ryan's next list treats the phones exactly
  as it treats the email: for a pilot it lists it writes what it lists (a pilot's added number goes; as before), and
  for a pilot it no longer holds it removes the values his lists gave, the added number with them (logged, so Ryan
  can put it back); a value only a pilot's list gave stays. The partial list answer "gone" now follows the same rule
  (it removed pilot-given values too). Before: the whole phones value turned into the pilot's (Ryan's number read as
  his) and then outlived Ryan's next list while the email on the same record did not.
- **Still the chosen rule, now said plainly:** a row's HAL values (name, Sen #, DOH, status, retirement month, union
  id) are WRITTEN over the contact list's value with the pilot as the author, also over a value Ryan's own contact
  list gave; the value before is in the history. So one pilot's list can change the shown retirement month and union
  id of any pilot with no hand edit (Sen #, DOH, status and the name are shown from the seniority list where it has
  them). A value a pilot's list wrote carries his ref, so Ryan's next list that no longer holds that pilot leaves
  it. There is no one-step undo of a merged list: Ryan restores a value from the record's history, field by field.
- **The same file Ryan's own upload reads.** A pilot's list is decoded as the 1.4.8 parser decodes Ryan's: UTF-8 (a
  BOM allowed), else Windows-1252 (`limits.encodings`). Bytes Windows-1252 does not have (81, 8D, 8F, 90, 9D hex) and
  control characters are refused as before. Before, one accented name in a Windows-1252 export refused the whole
  list for a pilot while Ryan's upload of the same file was read. HOM 1.9.1's chunk check must take the same two
  encodings (it sees parts, so: no NUL or other control byte but tab, CR and LF; the header row in the first part).
- **The card.** A refusal the portal gives in its own words is shown in those words ("Not sent: that file is not the
  contacts list (CSV) export. Nothing was merged."), cut to one plain line; "the portal does not take a contacts list
  yet (it needs its next update)" is said only for an older portal's own refusal ("kind is not one of ..."). Before,
  every refusal of the live HOM 1.9.1 read as a missing update. The fields and the button are 16 px text and 44 px
  high at every width (they were 14 px and 32 px from 700 px up). The title is "Uploads" while the contacts list is
  offered, the cap reads "1 MB", and a merged answer is shown once, under "Your contacts list".
- **Boundary changes of these fixes** (they narrow what a pilot's list can do, and none widens it):
  21. `roles.PILOT_CONTACTS_LIMITS` gains `encodings`, `rows_max`, `cell_chars`, `notes_chars` and `new_max`, and
      `PILOTDB_ANSWERS` two refusals (rows, new pilots). The fixture's `commands.pilot_contacts_limits`,
      `pilot_contacts_checks` and `pilotdb_answers` follow; HOM re-pins the fixture.
  22. A pilot's contacts list may be Windows-1252 text as well as UTF-8 (the one widening: the encodings of Ryan's
      own upload path).
  23. A pilot's list can make at most 250 standing records of its own, all pilots together; over that it is refused
      whole.
  24. Ryan's next contact list removes a number a pilot's list added to his value when his list no longer holds that
      pilot (boundary change 20 now covers only a value a pilot's list alone gave).
  25. The answer to a held row of a pilot's list never removes or replaces a value.
  Not changed: PORTAL_CMDS, PORTAL_REFUSED, FEATURES, every shape, PILOT_UPLOAD_LIMITS, PILOT_TICKET_LIMITS, the note
  and edit quotas, the FLICA budgets, the inbox folder and its modes, the author from the folder's name, the log
  (counts only), push isolation.
- Left open for Ryan: a one-step "undo this pilot's list" (by its merge row) is not built.

### The contract (part one, Nov 15): contract 1 revision 4 until the section above
- Decided from HOM 1.9.0's run-time code (commit 7bf6d25): the file and the state are relayed as signed and no key of
  either is read (`fwportal/exchange.mjs` `load` and `fileText`; `fwportal/server.mjs` imports no pilotdb key table);
  the one size check is `capFor`, `caps.file` of HOM's own pinned fixture, 8388608 bytes for every file kind
  (`fwportal/contract.mjs` `capFor`, `fwportal/exchange.mjs` `verifyEnvelope`). No command, shape, limit, quota, cap,
  file kind, event kind or upload kind changed. So 1.7.10 works with the live HOM 1.9.0 at once and either order is
  safe. HOM only re-pins the fixture (its copy, its sha256, its tests, its docs): no version bump, no deploy.
- The fixture was regenerated for part one: sha256 `86c2d8f905eff7509cb8ef85cf3f8a7adf7e611556ab395a017e6fd460311fbf` (revision 4's bytes; revision 5's are in the section above). Its words about the file changed (`pilotdb.share`, `pilotdb.file`,
  `pilotdb.state`, `pilotdb.uploads`, `pilotdb.ai.switch`, `pilotdb.ai.portal`, `commands.pilotdb_rules`,
  `revisions.4`, `masks.contact_only_in`), the record keys grew (`emp`, `base`, `phones`, `emails`, `pickups`), the
  `shown` keys shrank to `emp`, `pid`, `none`, the samples follow, and `commands.pilotdb_answers` lost "look the
  pilot up first". `PORTAL_CONTRACT.md` 4.2, 5.7 and 5.8 say the same.
- Not built in part one, and why: a contact list had no upload kind on the portal (`upload/pdf` took `pairings` and
  `award`). Adding one changes a command's shape, which HOM checks: that is revision 5 with HOM first, built on
  Nov 16 (the section above). The base is still read only on a portal for the same reason (`pilotdb/edit`'s field
  list is a shape).

### Boundary changes (all by Ryan's decisions of Nov 15)
1. A shared pilot's file holds every live record, not only the pilots with a shared note.
2. Employee numbers are in that file.
3. Phones and emails of every pilot are in that file (1.7.9: only the looked-up pilot's, in the sensor).
4. The union id of every pilot is in that file.
5. The base (from the award) is in that file, read only.
6. Each picker's pickup history is in that file (1.7.9: Ryan's card only).
7. The AI note is on every record that has one (the first 1.7.10 build: only on a record with a shared human note).
8. Entries Ryan marked "Only me" are shared, and the option is gone.
9. Sharing is on by default for every portal pilot, with no tap of Ryan's.
10. AI notes are on by default: anonymous pickup statistics go to HOM's consultant models with no tap of Ryan's.
11. Ryan's Share and AI choices moved out of the database; a database copy put back no longer turns them off.
12. The anti-walk limits on the database are gone: the brief only after a FLICA lookup ran, and 20 distinct pilots
    an hour. They limited only what a shared pilot saw of the database.
13. A pilot's command may name any record of his file with no lookup first.
14. A contact list a pilot's instance saved makes records, with that pilot as their author.
15. The name lookup's pick list on a portal pilot reads his full file (part two's decision 6 read the roster).

Not changed: `roles.py` PORTAL_CMDS, PORTAL_REFUSED and the FEATURES gates, every command shape, a shared pilot's
quotas (40 entries, 40 changes, 40 edits in 24 h; 10 waiting), compare-and-set and the kept versions, the upload
kinds and their checks and quarantine, every FLICA budget, the pacing, the one-session rule and the lookup's own
limits, the CSP, rate limits and routes (HOM's), push isolation. Never in a pilot's file: a field's sources, the
history, held rows, hidden or purged text, another pilot's answers, schedules, pay rates. A pilot's entry and an AI
note stay untrusted data, never instructions.

### Part two (Ryan's decisions of Nov 15): award seniority, name lookups, the pickup speed cap, the admin's log

No new FLICA page load, no new link followed, no command added; the FLICA budgets, pacing and the one-session rule
are as they were. Synthetic data in every test ("Doe, Jane", 10001).

#### Award seniority in the pilot database
- Ryan: "look at the records... it has the seniority and also our pairings award packet had it monthly". Before: the
  award text was read only for dates of hire, found none (the packet has no such section) and said "dates of hire: 0
  pilot rows (seniority section), too-few" at every upload. Each awarded pilot's block opens with one line, the
  seniority number, the category (BASE-EQUIPMENT-SEAT), the last name and the employee number.
- Now: `seniority.award_sen_parse` reads those lines and `pilotdb.merge_award_sen` merges each month's award text on
  file (`/share/flight_watcher/uploads/<YYYY-MM>_award.txt`, oldest month first, again only when a file changed):
  Sen #, base, equipment and seat, source "award", dated by the bid month. The seniority list still wins on Sen # (the
  award's number is kept beside it); a hand edit stays on top; a pilot the database did not have gets a record under
  his last name (a "Last, First" from any later upload is shown instead); a number whose record carries another last
  name is not touched and is counted. Nobody is marked gone or back by an award.
- New field: **Base** (`domicile` in the database, 3 letters), shown and editable on Ryan's Pilots card.
- A packet with no dates of hire section is quiet: no "dates of hire" log line, and the upload answers "Seniority: N
  pilots read from it (Sen #, base, equipment and seat) for the pilot database."
- The log says counts only ("pilot db: award 2026-12 seniority merged: 243 lines ...").

#### Name lookups search the pilot database
- Before: a portal pilot's "Look up a pilot's month" searched only the award's pilot lines and the seniority list, so a
  surname that is in the database answered "No pilot named ... on the award or seniority list on file".
- Now: a whole last name or "Last, First" also finds every pilot of the pilot database. Ryan's lookup searches his
  database beside the crew the Watcher has seen; a portal pilot's searches the award's seniority lines (the award text
  every instance has) and, unless Ryan turned his share off, the records of his own pilotdb file (part one). The FLICA
  lookup then runs exactly as before (pick list of name and seat, never a number; budgets unchanged).
- **Boundary change (Ryan's decision 6):** the pilot database on a portal pilot's Watcher (his own file, every
  record) is read for the names and seats of the name lookup's pick list. The lookup's
  own limits stay: letters only, the whole last name (a start from 5 letters), at most 5 matches, 20 name lookups an
  hour; a number two records share is left out; with sharing off nothing of the database is searched.

#### Pickup speed: capped at Ryan's request time
- Ryan's rule: when he himself asked for a trip and FLICA denied him "picked up by" another pilot, that pilot asked
  before he did. Before: the picker's speed ran to the middle of the window between the Watcher's last pot read that
  listed the trip and the read that found it gone, which can be minutes after Ryan's own request.
- Now: that picker's speed is at most Ryan's Requested time minus the trip's entry (the request's minute plus 59 s,
  since the list prints minutes), when that is lower than the estimate. Every other pickup keeps the estimate. The cap
  is kept on the find (`req_caps`, one for each picker; see the round 2 fixes), so every rescore and re-check keeps it; only the picker FLICA
  named is capped (it must be one of the pickup's open-seat pickers, else nothing changes and it is counted
  unmatched); a request filed more than 10 minutes before the trip entered the pot is not used.
- History: once, after the first good read of the request lists, every pickup with a matching denied row on file is
  recalculated (the request lists in the Watcher's state and Ryan's own captured request pages); the log says counts
  only ("speed: N pickups capped at Ryan's request time, M unmatched"). Going forward each read of the list applies it.
- The finds card and the FO / RO pickers card show the sign for "at most" before a capped speed, with "capped at your
  request time" on hover and for a screen reader; each card's Key says so. The picker's history in the pilot database
  takes the capped seconds.
- A portal pilot's Watcher does the same from his own request list for the pickups in his own database (his own
  request time); it reads no captured page, and nothing crosses instances.
- The year of a request comes from its bid folder's month (a late December request in January's folder is last year's).
- **Where the comment really is (Nov 16, checked against the real pages):** the Open Time Requests list has only
  "10/29 19:22 Add Denied" on a row (that time is the Requested time), no comment and no decision time, so as first
  built the cap never fired. Crew scheduling's comment is on each request's read-only view page. Now each Denied add
  or swap on the list with no reason on file is read there once (`watcher.req_cap_views`, the same read-only view
  page a pending request already used; both `safe_get` guards, 1.5 to 3.5 s apart, never the QuickDelete link beside
  it, nothing submitted). At most 2 new view pages for each bid folder on each read of the list (every 15 minutes;
  every 2 while a request is pending), so a history of 15 denials is read over about 8 list reads with no burst; a
  page that cannot be read is tried 3 times in all. A new denial is read within the next reads (one that is pushed
  is read once for its push and not again). A drop, a trade or an approved request is never read for this.
- **FLICA budget:** each view page is one FLICA load, counted by the gate like the list's own (pace, host cap, a
  pilot's hourly budget). On a pilot's Watcher a view page is loaded only when one more load fits his budget and the
  request reads' share (`opt_fits`); otherwise it waits for a later read and no try is used. None is loaded while the
  request reads are stopped (their breaker) or the Watcher is paused.
- **Both name orders:** the real comment is first name first with no comma ("CS: H3677:13NOV picked up by JOHN DOE
  (10001)", made-up values; the first build read only "DOE, JANE"). Both read now: one or more given names, a middle
  initial, a suffix (JR, III), hyphens, apostrophes, any letter case. "CS: Added pairing (H3630:14NOV) not in
  opentime pot" and every other comment is no pickup and caps nothing; a comment about the trip a swap gives up caps
  nothing either.
- What is kept for each denial: the pairing, its day and the picker's employee number, by folder and FLICA request id
  (`req_cap_views` in the Watcher's state, forgotten when the request leaves the list). The picker's name is never
  kept. The cap uses the row's own Requested time from the list (year from the bid folder's month).
- Log, counts only: "speed: 2 denied request view pages read, 3 left to read" and "speed: N pickups capped at Ryan's
  request time, M unmatched" (the second whenever a speed or the unmatched count changed). No name, no employee number.
- A portal pilot's Watcher reads his own denials' view pages the same way, inside his budget, with his captures off.
- Tests: `test_fw1710_speed_cap.py` (the real list and view page layouts with made-up values; each new test failed
  before the change).
- **Review fixes (view page reads):**
  - Log: the line of a view page's first capture and the line of a pushed decision no longer quote crew scheduling's
    comment (it reads "cs: (41 chars)"; the private capture holds the page), and the log mask (`captures.mask_crew`)
    now knows the real comment: every word after "picked up by" and the number after them are masked, first name
    first, lower case, whole or cut short by the line's length. Before, a new bid month's first view page capture
    printed the picker's name and employee number in Ryan's log.
  - Budget order: a pass reads the denials' view pages last, after the request lists and the Tradeboard's My Requests
    pages. Read inside the folder loop they took the load kept for My Requests, so a pilot at his budget's pace with
    15 denials had no trade decision read for hours. On such a pilot the history now uses only what is left (about
    one view page in four hours in the simulation), so his history takes days; Ryan's own Watcher has no hourly
    budget and reads 2 a folder a read as before.
  - What counts as read: a view page is final only when it is the request's own page (a trip read on it,
    `submit.is_view_page`); a "please wait" page or any other page is a failed try (3 in all). Each kept record
    carries the parser's version (`REQ_CAP_VIEW_V`): after a parser fix that raises it, every "no pickup" verdict and
    every given-up page is read once more, and a reason on file is kept.
  - The "picked up by" pattern: name words are split by a real separator, 31 characters a word at most, and read only
    in the 200 characters after "picked up by". A long run of letters with no number after it took 43 s at 60
    letters (hours beyond) inside the check thread; it now takes no time.
  - The trip a swap gives up: one rule (`submit.gives_up`, used by `row_cap` and `view_cap`) for the denial's push,
    the history read and a captured view page. Before, only the history read left it uncapped. Whether such a
    comment should cap is still Ryan's to confirm; until then it caps nothing on any path.
  - Tests: `test_fw1710_speed_cap_review.py`.

#### No crew names or employee numbers in Ryan's log
- Before: the admin's log named the captain ("detail probe H3601: captain='...(...)'"), quoted a pairing page's crew
  list ("detail text H3601: ... crew: ca ..."), started each Schedule Lookup line with the employee number ("pilot
  <emp>: ...EmployeeID=<emp>..."), named a pickup's pickers and quoted the request list's "picked up by".
- Now: those lines name the seat or the pairing ("detail probe H3601: captain=parsed", "pilot lookup: schedule
  requested", "pickup H3607|13Nov: filled (FO; CA named)", "picker of H3607|13Nov (FO): 120 in open time", "crew
  index: a pilot on two overlapping trips (...)"), page text is quoted through `page_log` (names and numbers masked),
  and a filter on the admin's logger (`captures.mask_crew`) is the net under every other line. A pilot's log keeps its
  stricter mask. Cards, the database and the exports are unchanged.

### Review fixes, round 2 (Nov 15)

- **Ryan's log, the Tradeboard lines** (decision 8): "NEW tradeboard pickup" names the pairing and its dates, never the
  poster or his comments; the Tradeboard probe and the "no trip rows" line say counts only (the page stays in the
  capture on /share, never the log). The admin's line mask (`captures.mask_crew`) also takes an e-mail address, a
  phone-shaped number (any 7 to 15 digit phone in quoted page text), a last name of up to four words ("De La Cruz,
  John"), a second given name ("Doe-Smith, Mary Ann"), a 3-digit number in brackets after a name, a seat-labeled or
  all-capitals name with no comma before its number ("Captain: DOE JOHN 99999") and the number an error text quotes
  (`KeyError('10001')`). A run of 80 or more letters is said by its length, so one very long token never costs the
  mask seconds.
- **Every log line that quotes FLICA page text goes through `page_log`**: the block hints line, the two own
  schedule lines, the schedule totals line, the close-in folder's two lines, the trade decision line and the Schedule
  Lookup prompt page line (a lowercased "last, first" there was not masked). A test reads `watcher.py` and fails on
  any log call that quotes page text without it.
- **A share Ryan switched off stays off when /data loses its switches file** (decision 2). Every OFF is also kept in
  `/share/flight_watcher/pilotdb/switches_off.json` (0600, the Watcher's own folder, outside /data and outside the
  database). A pilot, or the AI notes, is off when either file says off, so an older /data put back by a Home
  Assistant restore never shares again by itself. A mirror that cannot be read fails closed.
  **Boundary change:** one new private file on /share that holds pilot instance names and two true / false values,
  nothing else.
- **A tap on an unreadable switches file writes a good one**: the defaults are on again (a pilot Ryan adds later is
  shared, decision 2), every pilot configured now and the AI notes are written as off except the one tapped, and the
  running Watcher changes only after both files were written (a failed write leaves it as it was).
- **Pickup speed cap, each picker's own**: the cap is kept per picker (`pickup.req_caps`, employee number to request
  time; the first build's `req_cap_at` / `req_cap_emp` is still read). On a both-seats pickup the finds card shows
  the cap only when the picker it shows is the capped one; two denials naming the two pickers both stay, and a second
  pass writes and rescores nothing ("same"); when a re-check names another picker the old picker's cap goes and the
  pickup is rescored.
- **The award's dates of hire no longer erase the seat its seniority lines wrote** (`merge_award` leaves the award's
  seat when it has none of its own).
- **Name lookups agree on who is gone**: `name_hits` (Ryan's lookup) and `name_rows` (a portal pilot's directory) both
  leave out a pilot marked gone, and a pilot a seniority list dropped who is on the award of that list's month or a
  later one is back (logged "back", as a list's own). Two pick-list rows with one name and one seat (award-only
  namesakes) show their Sen # ("FO Sen 72"), from the pilot's own pilotdb file; never an employee number.
- **Portal Pilots card**: the search field, its hint, the chips and the count line are built once and only the count's
  text and the rows are redrawn, so a composing keyboard (Android Gboard, any IME) types "zedb" and not
  "zzezedzedbzedb", and the count is one lasting live region a screen reader announces. A last name typed without its
  apostrophe, hyphen, space or okina is found ("obrien", "delacruz", "mcdonaldsmith", "stjohn"), as the name lookup
  does; text with no letter or digit is no query. The Mail link is 44 px wide.
- **The file's size ladder has no cliff**: past the hard size the pickup rows go and the notes fields, AI notes and
  log entries are kept newest first, across all pilots, for as long as they fit (before: every text left the file at
  once). The card's banner counts the older log entries the file left out. No new key: the contract and its fixture
  are unchanged.
- Tests: `test_fw1710_review2.py` (each failed before its fix); `test_fw1710_speed_cap.py`, `test_pilotdb_export.py`
  and `test_pilotdb_share_admin.py` updated to the per-picker cap, the gradual ladder and the repaired switches file.
- Left open for Ryan (see HANDOFF.md): the CLAUDE.md hard-rule line for decision 9, the contact list upload on a
  pilot's portal page (contract revision 5, HOM first), gzip and ETag for the file route (a later HOM release), and
  checking the speed cap on the real pages after the update (the denials' view pages; see the speed cap section).

### After the update: what Ryan does
Each step is [DESTRUCTIVE] and needs its own yes; an earlier yes never covers a later one.
1. Flight Watcher 1.7.10: merge its PR, store reload, update. It works with the live HOM 1.9.0. **The update itself
   turns sharing on for James and turns the AI notes on** (both by Ryan's decisions of Nov 15): his yes to the
   update is the yes to both. Nothing else needs a tap.
2. HOM's re-pin PR (tests and docs only): merge. No deploy. It can go before or after step 1.
3. To turn either off: Pilots card, Sharing. Claude never taps either switch.
4. No dashboard edit on Pako, and nothing for James to do: his portal takes the card from the add-on.

## 1.7.9

Release order: HOM 1.9.0 first, then this add-on, each step with Ryan's own yes (see "After the update" at the end of
this section). Two parts: Ryan's two in-flight follow-ups of Nov 15, and sharing Ryan's pilot database with James (the
pilot database spec's steps 2 to 4, with HOM 1.9.0): contract 1 revision 4, with the swap idea alert (F#107) and the
clock card's Re-arm confirm (F#92). Ryan's decisions (Nov 14, HST): phones and emails on James's portal for the pilot he looks up only; James
browses the pilots with shared notes plus the pilots he looks up (the 1.6.2 anti-walk limits stay); James edits the
notes field, adds to the log and edits every record field ("he can be trusted and edit all"), each with
compare-and-set, the earlier versions kept (the newest 50 notes versions per author, every field edit) and Ryan's
restore; the AI note comes from HOM's consultant models, from
anonymous statistics only. Nothing is shared until Ryan taps his Share switch himself. Synthetic data in every test;
FLICA is read only and nothing here loads a FLICA page.

### Ryan's two follow-ups (Nov 15; `store.py`, `inflt.py`, `captures.py`, the finds card)
- **Both named pilots get an in-flight lookup when the open-seat picker is not known.** Before: a pickup the pot
  showed no open seat for, naming two pilots ("FO Doe, Jane (10001); RO Roe, John (10002)"), had no picker, so 1.7.7
  dropped its verdict (`inflt_skip`) and 1.7.8 re-checked nobody. Now each pilot it names is looked up for himself
  (`store.named_of`), his own verdict kept by employee number (`inflt_named`, the shape of `inflt_no`). They are queued
  once (`inflt_named_v`, `queue_inflt_named`), the oldest too, listed first like the 1.7.8 re-check, within
  `INFLT_PER_CHECK` and the existing pacing. FLICA read only (GET only). Nobody is made the picker: the pickup's own
  verdict, its pickers and the pickers' in-flight counts do not change.
- The finds export carries each named pilot's verdict (`inflt_named`, only while the picker is not known) and the finds
  card shows one line a pilot by his seat ("FO no", "RO" with the airplane and the flight), marked "picker not known",
  his name on hover. No blue link changes: only a known picker is a link. The Key says so.
- **No in-flight log line carries an employee number.** Before: the verdict line named the pilot by seat order (1.7.8),
  but the schedule lookup line quoted FLICA's page text, which prints the number ("... november (emp# n) schedule
  last updated ..."). Now `captures.mask_emp` masks every labeled number ("emp# n", "Emp#n", "EmployeeID=n",
  "employee id: n": the label stays, the digits become #) in the shared helper that quotes FLICA page text
  (`watcher.page_log`) and in the in-flight lines, the admin's log included. The verdict line names "picker 2" as
  1.7.8 does, or "named pilot 2 (picker not known)".
- Everything else is as 1.7.8 decided.

### Sharing the pilot database (the backend; `pdbshare.py`, `pilotdb.py`, `watcher.py`)
- **Off by default.** One Share switch per portal pilot on Ryan's own card (`POST api/pilotdb` op `share` `{pilot, on}`,
  the admin's ingress API only; Claude never sends it). While it is off nothing of the database leaves Ryan's Watcher:
  no file, no roster, the pilot's sensor says `off` and every command is answered "Not saved: Ryan has not shared the
  pilot database with you". Turning it off deletes the pilot's file at once.
- **The pilot's file** (`/share/flight_watcher/pilotdb/portal/<pilot>.json`, 0600, written 2 s after the database last
  changed and at once after one of his commands): only the pilots with a notes field or a shared log entry, each with
  name, Sen #, DOH, status, retirement, seat, equipment, gone, the edited marker, the record's revision, the notes field
  and the newest 50 entries (his own marked; a taken back entry without its text; hidden and only-me entries not at
  all), and his own last 20 answers. The builder is a whitelist, pinned by a key scan and a byte scan: no employee
  number, phone, email, union id, source, history, conflict, pickup or AI note. Over 4 MB the entries drop to 20 a
  record; still over, his new notes are refused ("the shared notes file is full").
- **The roster** (`/data/pilotdb_roster/roster.json`, 0600, in the add-on's own data folder, only while a share is on;
  see "Review fixes"): every live record's brief by employee number, for a
  shared pilot's Watcher to show the one pilot his pilot card shows. It carries the phones and emails (see B23 below);
  it is never exported, never in a sensor and never logged.
- **James's Watcher** (a pilot with a portal; feature `pilotdb`) never opens the database. It signs his file into
  `out/files/pilotdb.json` unchanged (exported before the state that names its rev), synthesizes
  `sensor.<prefix>_pilotdb` in state.json only (never an HA entity or an MQTT topic: state `on`, `off` or `waiting`,
  `rev`, `count`, the `shown` brief of the pilot looked up, `answers`, `pending`, `limits`) and takes two
  new commands, `pilotdb/note` and `pilotdb/edit`. It checks each (the shape; shared or not; the record must be in his
  file or be the pilot shown, so a command is no oracle for which pilots exist; a take back only of his own entry; at
  most 10 waiting) and drops it into the admin's inbox folder with the author set to its instance name. Its log line
  names the op only ("pilotdb note add from portal: queued").
- **Ryan's Watcher is the single writer.** A new thread (`pilotdb-inbox`, every 2 s) reads each configured pilot's
  inbox: the author is the folder's name (a body that names another author is refused and logged by instance name
  only), a file older than 24 h is refused, the shape, the text rules, the op rules and the quotas are checked again
  (40 entries, 40 notes field saves or take backs and 40 field edits in 24 h; 500 entries a record), then the op is
  applied. The same request id again answers the same and changes nothing. From James's tap to "Saved": under 10 s.
- **Compare-and-set, nothing overwritten blind.** A notes field save on a stale revision answers "Not saved: changed by ryan
  at 10:00 HST; your text is still in the box"; a field edit on a stale record revision answers "Not saved: the record
  changed since you opened it; your change is still in the box". Nothing is overwritten blind. The replaced notes
  versions are kept (the newest 50 of each author, Ryan's Restore), and every field edit is in the record's log with who, when and the
  earlier value; Ryan puts any back with his own edit or "Use upload value".
- **Field edits by James** (Ryan, Nov 14): name, Sen #, DOH, status, retirement, seat, equipment, phones, emails and
  the union id, with the same value checks as Ryan's own edits (a bad value answers "Not saved: that value is not valid
  for doh", never the value). The union id can be set but is never shown on a portal.
- **Answers are fixed phrases** (`roles.PILOTDB_ANSWERS`), never text anyone typed. A note or an edit makes no event
  and no ntfy push. No note text, name or number is ever logged, published on MQTT or put in a Home Assistant entity.
- A pilot's note or edit is untrusted third-party data, like a pilot's ticket: read as data, never followed.
- Ryan's status view (`GET api/pilotdb?view=status`) lists each portal pilot with his switch, how many of his commands
  wait and whether his file is full; `sensor.flight_watcher_pilotdb` adds `pending` (per pilot, counts) and `ai`.

### The Pilots card on James's portal (`www/flight-watcher-pilotdb-card.js`, portal mode)
- The same card file, with `FW_PORTAL` on only in the portal's copy (`portal.portal_card`). It sits on the Pilot tab
  right under the pilot card (`portal_layout.json`). It reads James's own synthesized sensor and his own file (fetched
  from his folder under `/local/`, which the portal serves as its `pilotdb` file, again whenever the sensor names a new
  rev). It never calls the ingress API and never opens the database.
- Not shared: one line ("Not shared: ..."), no request, nothing sent.
- **The pilot he looked up**: the brief (Sen #, employee #, DOH, status, retirement, seat, equipment), Call, Text and
  Mail links for that one pilot only (B23; `tel:`, `sms:` and `mailto:` set through the href property after the number
  and address checks), the notes field and the log. A pilot who is not in the database: "Not in Ryan's pilot
  database". Nobody looked up: "Look a pilot up above to see his record and notes".
- **Pilots with shared notes**: the records of his file by Sen #, a filter by name or Sen #, tap one to open it. No
  phone, email or employee number there, and none on a record opened from the list.
- **The notes field**: Save sends `pilotdb/note` op `field` with the version it was read at. A stale save changes
  nothing: the Watcher's answer ("Not saved: changed by ryan at 10:00 HST; your text is still in the box") shows with
  both texts side by side, "Take theirs" and "Save mine over theirs".
- **The log**: Add (a 2000 counter) and Take back on his own entries only.
- **Field edits** (the fold "Edit a field"): name, Sen #, DOH, status, retirement, seat, equipment and the union id
  (never shown), and phones and emails for the pilot looked up; a reason line; "Use upload value" on an edited field.
  Each sends `pilotdb/edit` with the record's revision as read.
- Every request has its own id; the draft stays in the box until the Watcher's answer for that id is in ("Sending...",
  "Sent. Waiting for the Watcher...", then the fixed phrase). A command the portal does not send ("Not sent: ...") or
  one with no answer keeps the draft. No author, name or employee number is ever sent.
- Every value is drawn as text (text nodes), no markup is parsed from a string, text is never turned into a link.
  Fields are 16 px and every control at least 44 px tall at every width. Not on the portal: the history, pickups, the
  AI note, only-me and hidden entries, the notes versions, hide, purge, merge, renumber and delete.
- The card's one `mqtt.publish` call (`_pub`) refuses on Home Assistant (`FW_PORTAL` off), so Ryan's notes still never
  reach Home Assistant's recorder.

### Ryan's card: the two switches and the AI note
- Browse mode has a **Sharing** section: one "Share with <pilot>" switch per pilot with a portal (off; a confirm says
  what he will see and edit; while on it says how many of his changes wait and whether his file is full; off deletes
  his file at once) and the **AI notes** switch (off; a confirm; "Remove the AI notes" once it is off). Both post to
  the ingress API as before; only Ryan's taps send them.
- A record's AI note shows read only, labeled AI, with its model and time ("Read only; not a human note").
- The "Only me" hint says what it does now: it keeps an entry off a shared pilot's portal.

### The looked-up pilot's phones and emails (B23)
- Ryan's answer to Q1 reverses FW-0066 plan Q6 for one case: the synthesized `sensor.<prefix>_pilotdb` carries
  `shown.contact` (phones and emails) for the one pilot James's pilot card shows, from Ryan's database, only while Ryan
  shares it. Never a list, never in the file, never the roster on the portal.
- `portal.MASK_DROP` itself is unchanged: `contact` is still removed from every state read from Home Assistant. The
  fixture's `masks.contact_only_in` names the one exception. The price: `roster.json`, a file between the two Watcher
  processes (0600, root), holds the phones and emails the contact list already holds on the same share.

### The swap idea alert (F#107)
- A new swap idea is a portal alert: the Watcher's own `event/swap` joins `roles.PORTAL_EVENTS` as kind `swap`, view
  `watcher` (the pot card lists the ideas), priority 3, in the Alerts list and on ntfy once a topic is saved. The pilot
  opts in by marking a trip "would trade" (`trade/set`): no mark, no idea, no alert; an idea alerts once.
- Its data holds the pickup (pairing, dates, days, layover, credit), the trip he would give up (`for_trip`,
  `for_date`), `soft_gain`, `credit_gain` and `src`; never the idea's reason text, a URL or the draft of a request.
  "Swap idea: H9002 20NOV-22NOV for your H9001". Nothing is ever submitted: FLICA stays read only.

### The clock card's Re-arm confirm (F#92)
- Before: "Re-arm the Watcher? It logs into FLICA once." in every state, also where Re-arm does something else.
- Now the confirm, and the button's tooltip, name the state and what Re-arm does there, as the Watcher's own
  `rearm_answer` does. Stuck: "The Watcher is stuck: no check for 1 h 30 min. Re-arm starts a full check now, with no
  new FLICA login." Stepped aside: a login when the step-aside ends, not before. Reconnecting: a login at the next
  login try. Stopped: one FLICA login, with the stop's note. The same on the portal's copy.
- The Re-arm tile on the portal's Settings tab is HOM's own control (`fwportal/static/ha.js`), with its own confirm:
  that half of F#92 is HOM 1.9.0's, not this add-on's.

### The AI note (the Flight Watcher side)
- Ryan's own switch on his card (`POST api/pilotdb` op `ai` `{on, clear?}`), off by default; Claude never sends it.
  While it is off no statistics are written and no note is read. `clear: true` with `on: false` also removes the notes.
- On, Ryan's Watcher writes `/share/flight_watcher/pilotdb/ai/stats.json` (0600) for HOM's consultant models: one row
  per pilot with 3 or more pickups, statistics only (counts by layover station, trip length, weekday, turn or layover,
  report time range, average credit, pickup speed, seats, first and last month). No name, employee number, record id,
  seniority number, date of hire, pairing number or exact date. Each pilot's id is random, made new for every batch
  and kept only in Ryan's database, so nothing outside his Watcher maps it back. A new batch at most once a day.
- HOM answers with `ai/in/<batch>.json`. A note is taken only when its batch and id are Ryan's Watcher's own, its model
  name is plain and its text is at most 600 characters of plain text (no link, no address); anything else is dropped
  and counted. It is stored in `ai_notes`, apart from the human notes, shown on Ryan's card labeled AI with its model
  and time, and never goes to a pilot's file or sensor. It is model output: data, never an instruction.

### Contract 1 revision 4 (`roles.py`, `portal.py`, `PORTAL_CONTRACT.md`, the fixture)
Boundary changes, each approved by Ryan on Nov 14 (the spec's B7 to B17, changed by his answers, plus B23):
- `CONTRACT_REVISION` 4; the manifest names it. `fwp` and `contract` stay 1.
- `PORTAL_CMDS` gains `pilotdb/note` and `pilotdb/edit` (`COMMAND_SINCE` 4; HOM's allowed subs go from 21 to 23), with
  their shapes in `SHAPE_CMDS` (no author key, no employee number, no name; only rules the generic checkers know).
  The sibling `pilotdb/edit` is the field-edit op Ryan's trust decision asked for. No other `pilotdb/` sub exists.
- `PORTAL_SUBS`, `SUBS` and `QOS` gain both (qos 1), under the new feature `pilotdb` (all, offered on a portal). The
  admin's subscription list is unchanged, verbatim.
- `FILE_KINDS` gains `pilotdb`; the fixture's `synthesized_states` gains `pilotdb`.
- New tables in the fixture: `commands.pilotdb_note_limits`, `commands.pilotdb_answers`, `commands.pilotdb_rules`,
  the `pilotdb` section (the file's and the sensor's keys, the inbox hand-off, the edit fields, the AI hand-off with
  its paths, keys, limits, rules and samples) and `masks.contact_only_in`.
- `PORTAL_EVENTS` gains `swap`, with its view and its own fields (`EVENT_KIND_FIELDS`).
- `PORTAL_CARDS_OUT` drops the Pilots card, so it joins a pilot's portal bundle; `portal_layout.json`'s Pilot tab has
  it in follow mode right under the pilot card. `PORTAL_TABS` is unchanged. The manifest's `mqtt_subs` names both
  commands whenever the card is in the bundle.
- Not changed: `MASK_DROP`, the anti-walk limits of the lookup, `PORTAL_REFUSED`, `NOT_ON_PORTAL`, the ticket and
  upload limits, the FLICA budgets, push isolation, `pub_pilot` and the pilot schedule sensor.
- The fixture `tests/fixtures/portal_contract_v1.json` is regenerated as revision 4 (new samples numbered from 700:
  11 accepted and 38 refused pilotdb commands, 4 refused `pilotdb/` subs, the file URL forms, the manifest, the state,
  the file and the swap event). HOM 1.9.0 pins the same bytes.

### Tests
- New: `test_fw179_inflt_named.py` (follow-ups), `test_pilotdb_export.py`, `test_pilotdb_portal.py`,
  `test_pilotdb_share_admin.py` (the backend, end to end), `test_fw179_pilotdb_portal_card.py` (the portal's copy of
  the card in Chromium at 390, 820 and 1280 px, light and dark, on the real database, files, checks and drain: what
  he sees, every command's keys against the contract's shape, the stale notes view, sizes, contrast; Ryan's two
  switches) and `test_fw179_clock_rearm.py` (F#92). Synthetic pilots only ("Doe, Jane", 10001).

### Review fixes (before release; `tests/test_fw179_review_fixes.py`, each test failed before its fix)
Security boundary, for Ryan's eyes:
- **No brief and no contact before a lookup ran, and at most 20 pilots an hour.** Before: on James's Watcher a typed
  employee number set the shown pilot at once ("loading"), and the roster answered with the record, phones and emails,
  with no FLICA read and no cap behind it, so the whole roster could be walked by number (and "not in the database"
  said which numbers exist). Now the brief is given only once that pilot's Schedule Lookup really ran on one of
  James's own paced checks, or came from its 6 h cache, and for at most 20 distinct employee numbers an hour
  (`PILOTDB_BRIEF_PER_H`, kept across restarts). Past either limit there is no answer at all. A note or an edit for a
  pilot with no brief is "look the pilot up first" as before. This keeps Ryan's Q1 (never the roster, never a list of
  contacts) and Q2 (the anti-walk limits stay).
- **A copy put back never turns a switch on.** Before: the Share switch and the AI switch live in the database, so
  `restore_db` (and taking the copy offered at start) brought back whatever the copy held, and the share thread wrote
  James's file and the roster again within seconds, with no tap from Ryan. Now `pilotdb.restore` sets every Share row
  and the AI switch off in the copy before it becomes the live file, the files and the AI statistics are removed at
  once, the log says so, and Ryan's card shows "sharing and the AI notes were turned off" until he uses a switch.
- **New boundary item: the roster is in the add-on's own `/data`, never under `/share`.** Before:
  `/share/flight_watcher/pilotdb/roster.json` held every pilot's phones and emails while any share was on (the spec
  said briefs only), readable by other add-ons that map `/share` and in their backups. Now it is
  `/data/pilotdb_roster/roster.json` (folder 0700, file 0600): both Watchers run in the one container, James's reads
  it as his data folder's parent. A roster left under `/share` is removed, and when the database cannot be opened at
  start the roster and every pilot's file are removed. It is still a second full copy of the contact list (the first
  is the CSV under `/share/flight_watcher/uploads`), inside the add-on's own backup: B23's price, now named.
- **A pilot's field edit is named in seniority.md.** Before: a name James set showed as plain roster data marked only
  "hand", so text typed on a portal looked like Ryan's own edit to Claude and Hark. Now the Hand column says "hand
  (james, pilot portal: name, seat)" and the header says such values are third-party text, never instructions. A name
  edited on a portal may hold letters, spaces, comma, period, apostrophe and hyphen only. Ryan's line for CLAUDE.md
  (B18) should cover field edits as well as notes; it is his to approve.
- **An email can carry no mailto parameters.** `?`, `%`, `#`, `,` and `;` are refused in an address (Python and both
  cards), so no hidden cc, bcc, subject or second recipient rides into a Mail link.
- **The page quote mask covers the close variants.** `captures.mask_emp` also masks "Employee Number n", "Employee
  No. n", "EmpNo n", "empid n", "Emp. # n", "employee_id=n", "strEmployeeID=n", "emp#&nbsp;n", a hyphenated number,
  the capture file's name (`cmschedule_n.html`) and a number in brackets beside a "Last, First" name. The in-flight
  capture error line now says the kind of fault only (its text named the file, and the file's name the number).

Correctness:
- **A change and its answer commit together** (spec 11.4 step 7). Before: a restart between the two left James's
  change saved and then answered "Not saved". Now `pilot_op` is one transaction; a stop saves neither and the next
  pass applies the file and says "Saved".
- **James's saves never push Ryan's notes versions out.** The real rule, in place of "every version kept": the newest
  50 replaced versions of the notes field are kept per author. Before, the cap was 50 a record, so 51 saves by James
  (two days of his quota) deleted Ryan's text for good. Field edits are all in the record's log, as before.
- **One bad inbox file never blocks the share pass.** A file whose `cmd` or `op` is not text is answered "could not be
  read" and removed; a drain fault no longer keeps the files from being written. A hide, a take back, a purge and a
  forget on Ryan's card reach James's file and the roster at once, as a share off does.
- **A dropped pickup whose picker becomes known** loses its dropped state and tries, so the picker gets his own normal
  lookup, and its "listed first" mark goes.
- **AI statistics HOM takes.** Before: an empty report time or credit (an older picker's find no longer on file), a
  pickup slower than 11.5 days or an odd station text made HOM leave the pilot out for good, silently. Now empty
  values are null, seconds are capped at 999999 and only station codes are listed; the contract has such a sample
  (`pilotdb.ai.sample_stats_sparse`). Ryan's card says how many pilots of the last batch got no note.
- **The same AI note again changes nothing**, and an AI note never moves a record's revision, so an edit James or
  Ryan has open is not refused as stale.
- **The same swap idea twice is one alert** (F#107): it takes the place of its earlier alert in the list.
- **The Re-arm confirm says what the Watcher does** (F#92): no login saved ("Re-arm does nothing: enter your FLICA
  login on the Settings tab"), the app not answering, details FLICA refused ("Re-arm makes no login ...: save new
  FLICA details"), and any state that is not stopped. "Stopped" is said only of a stopped Watcher.
- Portal card: the Seat and Status hints no longer offer a blank the card refuses ("to undo an edit, Use upload
  value"), and a line a save left ("Seat saved.") goes when the share goes off.
- The contract fixture is regenerated (still revision 4): the anti-walk rule of `shown`, the email and name rules,
  `pilotdb.ai.stats_values` and `pilotdb.ai.sample_stats_sparse`. HOM 1.9.0 pins the new bytes.
- Not changed, for Ryan to decide: the standing in-flight rule looks up every numbered name of a pickup with no known
  picker (also a lone name that is no candidate for the open seat). The dark filled-button contrast on the portal
  (3.02:1) is the HOM shell's color pair, fixed in HOM 1.9.0.

### After the update: what Ryan does
Each step is [DESTRUCTIVE] and needs its own yes; an earlier yes never covers a later one.
1. HOM 1.9.0 first: merge its PR, then Hark's deploy on the Pako NUC. James's portal keeps working on 1.7.8.
2. Flight Watcher 1.7.9: merge, store reload, update. Nothing is shared yet: both switches are off.
3. Open the Pilots card on the Settings tab, section Sharing, and tap **Share with james**. Only Ryan taps it.
4. Optional: tap **AI notes** to let HOM's consultant models write a note per pilot with 3 or more pickups.
5. Tell James when ready (his first note needs his passkey). Claude never contacts James.
6. No dashboard edit is needed on Pako: the Pilots card is already on Ryan's dashboard, and James's portal takes its
   layout from the add-on.

## 1.7.8

Ryan's pilot database (Ryan, Nov 14: "should we have an editable pilot database that has these data points. and even a
notes field we can edit and append to"), the pilot database spec's step 1: on Ryan's own instance only, the portal
contract unchanged at revision 3, HOM untouched, nothing shared with a pilot (sharing with James is 1.7.9 with HOM
1.9.0); the schema is ready for it. Plus the in-flight re-check (Ryan, Nov 15: "Re-check them"). Synthetic data in every
test; FLICA is read only and nothing in the pilot database loads a FLICA page.

### The database (`pilotdb.py`, the admin's Watcher only: `one_writer`)
- `/data/pilotdb.sqlite`, mode 600, in HA's pre-update app backup; schema `user_version` 1 (a file from a newer
  Flight Watcher is never opened). One record per pilot, keyed by employee number plus last name (two pilots on one
  number are two records) with an opaque `pid`.
- Each field (name, Sen #, DOH, status, retirement month, seat, equipment, phones, emails, union id) keeps every source's
  value with its date and reference: the seniority list, the award's dates of hire, the contact list and Ryan's hand
  edits. The seniority PDF wins on Sen #, DOH and status (Ryan, Nov 14); the contact list's age 65 month comes first
  for retirement (14 CFR 121.383(d)). Sources that differ are flagged (`disagree`).
- A hand edit stays shown through every later upload; an upload that brings another value flags `drift` ("Use upload
  value" or "Keep my edit"). Every change is in the field log (old, new, who, when, why). Edits are compare-and-set on
  the record's revision: a stale one is refused with the fresh record, never written blind.
- The notes field (one per record, at most 4000 characters): every save compare-and-set on the version it was read at,
  the newest 50 versions kept, Restore any. The dated log (at most 2000 characters an entry, 500 a record): add (a
  repeated request id adds nothing), Only me, take back your own, hide, restore, purge, delete the whole record (typed
  DELETE). A take back, a purge or a delete scrubs the file; a purge or a delete also replaces the daily copies and
  deletes the files set aside beside it (before a restore, or failed its check).
- Uploads merge on their own when a source file changes (checked at start and once a minute, at once after an upload):
  a pilot missing from a newer list is marked gone (his last values kept, marked stale) and back when he returns.
  Nothing is moved or merged automatically: a renumbered pilot, another pilot on a known number, an ambiguous row, an
  unmatched contact and a list with fewer than 90% of the last one's pilots are held for Ryan, each with its answers.
- Seeded on the first start from the kept contact list on the share (`contacts_<date>.csv`, its Notes "HAL Emp# n |
  Sen# n (Mon YYYY) | DOH D-Mon-YY | Status X | Age 65 retirement Mon YYYY") and `seniority.json`. `contacts.hal_notes`
  reads the Notes ("Age-65" as Pako's file has it, and "Age 65"); the raw Notes are never kept; contacts parser 2 reads
  the kept source again once. A contact row with a HAL Emp# makes a record (there is no `seniority.json` on Pako yet);
  one a pilot's instance uploaded is held for Ryan instead.
- Each picker's record carries his full pickup history from the pickers data 1.7.7 rebuilt, linked by employee number:
  each pickup with its running count overall and at its layover station, trip length, turn or layover, credit, report
  time, weekday and pickup speed.
- `seniority.md` (same path, mode 600) is written from the database, 30 s after the last change, at once after a merge
  and each HST day. Daily copies at 02:47 HST in `/data/pilotdb_backup` and `/share/flight_watcher/pilotdb/backup`
  (folders 0700, files 0600, 7 kept). At start: a file that fails its integrity check is set aside and the newest good
  copy offered; a share copy newer than the live file (an older /data restored) is offered, never written over.
- The AI note has its table (`ai_notes`: written later by HOM's consultant models from anonymous stats, labeled AI,
  kept apart from the human notes); nothing writes it in 1.7.8. The share, answers and act_log tables wait for 1.7.9.
- `seniority.to_json` keeps each pilot's status code and the DOR as `retire` (parser 4: the list on file is read again).
- Every log line carries counts and op names only, never a name, a number or a note.

### Ryan's side: the ingress API, the sensor and the Pilots card
- `GET` and `POST api/pilotdb` on the app's Web UI (B4; admin only, the ingress IP guard): search (name words, an
  employee number, `s` and a Sen #, "quoted" text in the notes; filters; 50 rows a page, no phones or emails in a row),
  the whole record, the pilot the pilot card shows, the held rows, the status and copies. A POST is one op as a JSON
  object: it needs `Content-Type: application/json` and the header `X-FW-Card: pilotdb` (a plain cross-site form can
  send neither), at most 64 KB, known keys only; the author is always `ryan`. Ops: set, unset, keep, field,
  restore_field, add, retract, hide, restore, purge, forget, resolve, move, merge, new, restore_db (typed RESTORE). A
  stale write answers 409 (the fresh record, or the notes text there now); an error names the field and never echoes a
  value or a note; every answer is `Cache-Control: no-store`. There is no share op (B6: 1.7.9).
- `sensor.flight_watcher_pilotdb` (B5, admin only): the live record count, with counts, source dates, the seniority.md
  and copy times, the revision and the database state (ok, newer_db, error, restore_offered, off). No name, number or
  text, under 2 KB; the card reads it again when its revision moves.
- The Pilots card (`flight-watcher-pilotdb-card.js`): browse on the Settings tab (search, filter chips, the record with
  every field's source and date, edit, the notes with the conflict view and versions, the log, the pickups with the
  count per layover station, the AI note read only when there is one, the history, merge, renumber, delete; the held
  rows; a new record; the daily copies and Restore), and follow mode under the pilot lookup card (the looked-up
  pilot's record and notes; it never publishes `pilot/set`). Admin mode only; anyone else sees one read-only line.
  Every value goes in as text (no markup is ever parsed); the only links are tel:, sms: and mailto: after the pilot
  card's checks. The card is kept off every portal (B3, `PORTAL_CARDS_OUT`).
- The pilot card's `_esc` also escapes the single quote.
- roles (B1, B2): `one_writer` names the pilot database; RESERVED gains `pilotdb`; `ENTITY_FEATURE` maps the new sensor
  to `one_writer`. No portal list, contract fixture, FLICA budget or push changes.
- On Pako, after the update and with Ryan's yes: the Settings view gets the card above the tickets
  (`type: custom:flight-watcher-pilotdb-card`) and the watcher view gets it in follow mode right under the pilot card
  (`follow: true`), then the `ha/` snapshot in git (HANDOFF.md).

### In-flight re-check (Ryan, Nov 15: "Re-check them")
- The verdicts 1.7.7 dropped as made for another pilot (`inflt_skip`) are looked up once more, for the picker; the
  second picker of a both-seats pickup gets his own lookup (`inflt_no`, by employee number). All within the paced
  in-flight budget (`INFLT_PER_CHECK`), read only.

### Choices that differ from the spec text
- Sen # and status take the list first rather than the newest source (Ryan: "the seniority PDF wins").
- Contact rows with a HAL Emp# create records (the seed would make none otherwise); seat also accepts RO (the relief
  officer); bookkeeping writes (signatures, md and copy times) do not move the revision the card follows.
- `FLIGHT_WATCHER_PILOTDB=0` keeps the database closed (the test suite's default); run.py never sets it.

### Review fixes (each with a test that failed first: `tests/test_fw178_review.py`, `tests/test_fw178_review_card.py`)
- One pilot listed twice in one upload (a second phone card on the contact list, an `also` that repeats him) is one
  row: the first row's values, each missing field filled from the others, phones and emails joined (counted `dup`). It
  made a second record before, which broke the unique key and rolled back the whole merge, so a duplicated contact
  stopped the seed, `seniority.md`, the copies, the pickups and the sensor every minute. The same number and last name
  with another first initial is held for Ryan (`ambiguous`). Each row runs in its own SAVEPOINT (one refused row is
  counted bad and rolls back alone), and each source merges in its own try in `pilotdb_tick`: a failed merge logs
  "pilot db: <source> not merged: <error type>" once per file and is tried again next pass while the rest runs.
- The 90% guard measures each list against the last whole list's count, which a partial list no longer moves: a second
  partial list (the other half of the roster) no longer marks the first half gone. The same for the contact list.
- A record's identity (last name, first initial) comes from the uploads' own name (list, award, contacts), a hand name
  only when no upload has one, and a row matches on any DOH the record holds: a hand edit of the name or the DOH only
  decides what is shown, and the pilot's later rows keep updating it (drift) instead of being held as `other_pilot`.
  Unsetting a name no upload has is refused.
- Ryan's answer to a held row is remembered with the record it put the row on: a contact row he attached goes to that
  record again on every later list (it was skipped and the record lost its contacts values), an ignored one stays
  ignored. A record that answer named is gone (deleted): the row is asked again.
- A purge or a delete also deletes the files set aside beside the database (`pilotdb.sqlite.before-restore-<time>`
  from a restore, `pilotdb.sqlite.bad-<time>` from a failed check); otherwise they roll off after 7 days with the
  nightly copies. The card's Daily copies lists them (`view=status` `aside`).
- An answered held row keeps only its employee number and the record it went to (`conflicts.pid`); a delete also
  removes the open rows about that pilot, so no contact's phones, emails or name outlive the record in the file or the
  fresh copies.
- A contact or seniority list keeps its uploader (`uploaded_by`, save_upload's `who`; kept through a re-read) and is
  merged as his (`vals.by`, `merges.by`, "uploaded by" in seniority.md). A contact list a pilot's instance saved makes
  no record: such a row is held for Ryan (`contact_unmatched`, Attach or Ignore); rows that match a record update it.
  Refusing the contacts and seniority kinds on a pilot's instance altogether is a boundary change left for Ryan's yes.
- A record Ryan merged into another keeps its pickups through the next pass (`_link_pickups` follows `merged_into`).
- A turn's station is no layover station: the pickup history keeps it as `station`, counts it apart (`turn_stations`)
  and never in the stations or the running count per station; seniority.md says "Layover stations: LAX 2; turns: OGG 1".
- The notes rev hashes the rev it replaces too (`sha256(pid|base|text|by|at)`), so a rev never comes back (X, Y, X in
  one second gave the first save's rev).
- Log entries made in one second stay newest first (`ORDER BY at DESC, rowid DESC`), in the card and seniority.md.
- In-flight re-check: the pickups the once-only reset touched (`inflt_recheck`) are listed first whatever their age
  (most were older than the newest 50 and were never looked up), only a pickup with a known picker is reset (any other
  keeps its dropped state), and the log says how many are queued. The in-flight log names the picker by seat
  ("picker 2 IN FLIGHT ..."), and the schedule lookup and capture lines no longer carry an employee number.
- The Pilots card:
  - a record read that answers after a newer read or a write is dropped (a sequence guard, as the search has): after
    "Save mine over theirs" the card no longer goes back to the older notes;
  - on a phone (700 px or less) every field is 16 px (no iOS zoom) and every button, chip, link and fold 44 px; a drift
    line wraps; each pickup is one wrapped line (the table needed a hidden sideways swipe); the results' flags sit under
    the name and the flags column is named "Flags" for a screen reader; the search placeholder is short enough to read;
  - after Save, Cancel, Add, Hide, Restore, Take back, a held row's answer and Close the focus stays where Ryan acted
    (the Edit button, the entry, the next held row, the pilot's row in the results), never the top of the page;
  - every message also goes to one live region that is never redrawn (the sections' lines are plain text and stay
    through a redraw);
  - a record read that lands while Ryan types in it waits until the focus leaves the field (the box, its caret and its
    height stay; an iPhone kept losing the keyboard); a notes box made taller stays that tall;
  - Restore of a version with a draft in the box asks first, then shows the restored text;
  - "Use upload value" shows only when an upload has a value; otherwise "Remove my edit" behind a confirm (never for
    the name).

### Pickers table and the pilot lookup (tests: `tests/test_fw178_polish.py`)
- Pickers card: Avg Pickup Speed was cut off behind a sideways scroll at Mac width (1280). The headers' words now wrap
  (the cells do not), and on a card 900 px wide or less (an iPad) the name and layover cells wrap and the cells are
  tighter, so all ten columns fit a Mac or iPad card. The phone layout (Pilot, Pos, Best, Avg) starts at a 700 px card
  (was 500), so an iPad in split view or a phone on its side gets it. Checked on the live list (72 pickers) at card
  widths 990, 900, 748, 560 and 358: no sideways scroll at any of them.
- Pilot lookup card: the admin's placeholder is "Last name, first name or emp #" (was "Anybody's schedule: last name,
  first name or employee #"), so the whole hint shows in the box on an iPhone. The box got its own full row on the
  Watcher view on Nov 14 (`ha/README.md`).

## 1.7.7

The pairing detail panel, one look for every month, other pilots' pay and seniority.md (Ryan, Nov 14), then Ryan's
Nov 14 follow-ups: only the picker is a link, the flight of an in-flight pickup, the bid calendar's 5th and the DOH on
a pilot's portal. Built on 1.7.6.1 and 1.7.6 (t1301); with tests that failed first. No new FLICA page loads, no portal
contract change, no change to the `roles.py` lists.

### Pairing detail panel (Ryan: "click on a pairing and have the actual pairing pop open below the schedule")
- A tap (or Enter) on a pairing on the schedule card opens its detail like FLICA's pairing printout: the header (the
  days it operates, base report, base and equipment), each leg (day, date, DH, flight, from-to, local departure and
  arrival as printed, block, ground), each duty's TBLK, TDHD, TCRD, duty and FDP (from report to the last flight's
  block-in, FAR 117.3; a deadhead after it is duty, not FDP), D-END, the next report, the layover and the totals (trip
  rig as printed, else credit less the legs' credit) and the crew. Below the grid on a wide card (the trip's rows
  tinted); a bottom sheet on a phone (a modal dialog about 60% high; the backdrop, the close button, Esc or a swipe
  down closes it). "Would trade" is the arrow mark alone; the lock still guards trade, drop and blocked days.
- The pairings package parse keeps each A330 HNL pairing's legs, duties, layovers and totals in the card's pairing
  file (`detail`, parser `dv` 2; the text copies on file are read again once); the file is written whole (a temporary
  file, then moved). Hotel names and van times stay out of that public file (`/local/` with no login, copied to every
  portal): they are kept in the DB (`pkg_hotels`) and Ryan's own panel shows his hotel from his trip times. A detail
  budget (1.5 MB or 600 pairings, `dcut`) keeps a crafted upload under the portal's file cap; lines, legs and duties
  are capped (a pilot's upload is untrusted). A pairing the package does not list that day shows FLICA's duties and
  says why.

### One look for every month (Ryan: "exactly the same style including this latest detail panel")
- Another pilot's month FLICA showed, its older versions and a month reconstructed from crew lists are drawn with the
  schedule card's own grid block (carried byte for byte, `tests/test_sched_grid_shared.py`): day colours and holidays,
  the bold blue pairing, the layover box with R and Rel, row heights, the totals line, VAC and PAYP days, the trip
  status mark, a trip carried in from the month before, light and dark, and the same pairing detail. Ryan's own card
  is unchanged.

### Other pilots' pay (Ryan: "calculate their pay by looking at their date of hire and seniority")
- A month FLICA showed for another pilot, and each of its versions, is priced like the rebuilt month: each pairing at
  the seat he flies on its crew line (Captain PWA 3.C.4, FO and RO PWA 3.D.6) for his longevity year from the date of
  hire on the seniority list (PWA 3.B.1; `rate_steps` names a step inside the month), with the PWA 4.O.1 overrides.
  The month is the schedule card's: trips that start in the calendar month, each its PWA 4.A share (a segment pays on
  the date it originates), vacation days at 4:00 a day (PWA 6.J.1.c) and a PAYP (PWA Definitions 57) at FLICA's month
  credit less the rest (an estimate). Each trip's package is its own bid period's; a pilot on another fleet is not
  priced at the A330 rates. No FLICA page is loaded for it.

### seniority.md (Ryan: "keep that in an MD card for reference")
- Each time `seniority.json` is written the Watcher writes `/share/flight_watcher/seniority.md` (the list date, then
  Seniority #, Name, Emp, DOH, Seat, Equip and the pay year today, PWA 3.B.1): private, mode 600, written whole, beside
  the uploads folder (never in the Web UI's list, `www` or a portal export), and rewritten once a day (HST).

### Picked up by: only the picker is a link (Ryan: "the other person who was already on the pairing should be black")
- The finds card links only the open-seat picker (blue); a pilot already on the pairing is plain text. The pickup check
  stores the picker's employee number (`pickers`: the newcomer in a seat that was Open, or that FLICA had left out and
  appeared; a newcomer in a seat that was not open is a crew swap); an older find is read from its `open_seats` and the
  seat before each name, and an ambiguous one links nobody rather than the wrong pilot.
- Bug fixed: `store.picker_of` read a two-name "by" ("FO A (n1); RO B (n2)") as the first name with the last number, so
  the FO / RO pickers table showed merged rows ("A (n1); RO B" under n2) and the in-flight check looked up B. The table
  and its log now count the open-seat picker(s), each once per pickup (both when both seats were open), and the
  in-flight check looks up the first one, one lookup a pickup as before. The first start rebuilds the pickers table
  from the stored pickups once (`pickers_rebuild_v`; a pickup whose trip is back in the pot keeps its count). An
  in-flight verdict made before 1.7.7 for a pilot who was not the picker is dropped and not checked again (no FLICA
  load; the card's "-" says why on hover); one made for a picker stays his.
- A find whose pot detail read had no crew line is read without a roster: of two names, nobody is the picker (linked,
  scored or looked up), never both.

### InFlt names the flight (Ryan: "i.e AS808/06NOV and date")
- An in-flight pickup shows the airplane and `AS808/06NOV`: the leg the picker was airborne on (a deadhead counts) and
  its departure date local at its origin; hover: "picked up while airborne on AS808 HNL-LAS, departed 06NOV 23:00 local
  (pairing H3648 Nov 3)", with "(DH, deadhead)" for a deadhead. The check keeps the leg from the pairing page it
  already reads (`inflt_leg`), no extra page. A trip whose first leg leaves after midnight of its start day (or from a
  station whose local date is a day ahead) has its legs on that day, not 24 hours early.
- An in-flight pickup from before 1.7.7 gets its leg from the pairings package, with no FLICA load, at start and after
  a package upload, only when the package lists the picker's pairing on that start date and one of its legs holds the
  pickup time; else the airplane stays alone and the hover says "flight not on file".

### Bid calendar (Ryan: "pairings post on the 5th of the month and close on the 11th monthly")
- The usual publish day is the 5th (it was the 4th), so the "adjust your vacation" alert goes at 08:00 HST on the 4th;
  the close stays the 11th 08:00 HST. A package's printed Bid Calendar still wins.

### DOH on a pilot's portal (Ryan: "james and I are on a high level of trust. he can be trusted")
- A pilot instance's pay lines carry the looked-up pilot's date of hire, the list's dates and `year_to` again, as
  1.7.5's rebuilt-month line (`pay_line`) sent them, plus the new `rate_steps`; `items_pay` (new in this release)
  carries the same. The first build of this release had left them out. Every other review fix stays.

Tests: `tests/test_pairing_detail.py`, `tests/test_pairing_panel_card.py`, `tests/test_pilot_grid_look.py`,
`tests/test_sched_grid_shared.py`, `tests/test_pilot_price.py`, `tests/test_seniority_md.py`,
`tests/test_review176_{pairings,pay,cards}.py`, `tests/test_fw177_{pickers,inflt,cards}.py`, `tests/test_bidcal.py`
(synthetic only).

## 1.7.6.1

The union's seniority list (Ryan, Nov 14: "what format does it need? make the settings page work with this format. it is
what the union provides"). Built with tests that failed first, then two adversarial reviews; every reproduced finding is
fixed.

### The Settings page reads the Pilot's System Seniority List
- Before: an upload of the company's "Pilot's System Seniority List" PDF (Sen #, Name, Employee #, DOH as 17-Sep-85,
  Remarks) was refused: "No pilot rows were found in it". The reader knew only the older SEN / EMP / DOH list.
- Now both lists are read; the header line picks the reader. On the July 1, 2026 list every row is read (seniority
  numbers with no gaps, 0 lines not read). The leading "*" (a changed seniority number) is ignored; "Jr." names, two-word
  last names, apostrophes and hyphens read as printed; columns that drift page to page are fine. The pilots-removed
  section, the status legend, page titles, "Page n of m" and the footnote are never read as pilots.
- The list date comes from the printed "Effective July 1, 2026" when none is typed; a typed date still wins, and the
  upload message says so when the two differ.
- Two-digit hire years take their century from the printed list date (then the typed one, then the upload year), and a
  date of hire 60 or more years before the list is refused as a misread (age 65 retirement, 14 CFR 121.383(d)). The
  first build would have put a 2026 hire in 1926 under a mistyped list date.
- A row with another mark ("**", a dagger, "12*") is read; a dated row that cannot be read counts as a line not read, and
  each missing seniority number is noted as a gap. A union header in another column order is refused with the union
  list's own rule (Sen #, Name, Employee #, DOH, Remarks).
- The status codes (A, SLOA, MLOA, EXEC, LOA, ALPA, FUR, MRET, PESL) are counted, never stored per pilot. The seniority PDF,
  its text copy and the three seniority JSON files are now mode 600, like the contact list.
- The name lookup compares last names without Jr / Sr / II and takes a curly apostrophe. Pilots with a 2-letter last
  name are still found by employee number only (the 3-letter minimum stays, 1.6.2).
- PARSER 3: a list already on file is read again at start. The older list and the award's dates of hire read exactly as
  in 1.7.6. The uploads card's help line names both lists.

### Ryan
- Upload the seniority PDF again on the Settings tab (Monthly files, What = Pilot seniority list): the refused one was
  not kept.

## 1.7.6

Session lost on the open time page (HOM t1301; Ryan approved shipping Nov 8).

- Before: at 15:02 HST on Nov 8 FLICA answered the open time page with "application error initializesessiondata()
  failed". That page counted as a pot layout miss ("retry"), so the Watcher cleared its pot links, added one to the
  layout count and slept a full check gap with state idle and Session OK on; the pot went stale until Check now.
- Now: that page on the open time read ends the pass as an expired session (`needs_login`): one login attempt on the
  usual backoff, pot links and the layout count kept. Any other unknown page is still a layout miss.
- Schedule Lookup is unchanged: a hidden lookup prints the same error on a live session (FW-0069), so the text is not
  added to `pot.EXPIRED_HINTS`.
- Test: `test_session_lost_page_on_the_pot_logs_in_again` (tests/test_close_in.py).

## 1.7.5

"Pause wins" (Ryan, Nov 14): Pause cancels a FLICA login still waiting to run. Built with tests that failed first, then
three adversarial reviews; every reproduced finding is fixed.

### Pause cancels a waiting login
- Before (since 1.6.2): on a pilot, a FLICA login asked for by Re-arm, or by the one more try after re-saving the same
  FLICA details (1.7.4), can wait up to 10 min for the login floor; Pause turned on during that wait did not stop it.
- Now: turning Pause on (or Pause found on at start) cancels it (`pause_cancels_login`): the Re-arm and a save's
  pending try are dropped, one log line, and a stopped Watcher's note says the login was cancelled by Pause: press
  Re-arm after turning Pause off. A Re-arm while paused answers ok false ("nothing to re-arm while paused: turn Pause
  off, then press Re-arm"); the clock card hides Re-arm while Pause is on. A save made while paused lifts FLICA's
  refusal block but queues no try. The admin's Re-arm follows the same rule.
- The races the reviews found are closed: Pause in the last instant before the login (`rearm_claim`, a last look in
  `try_login` before FLICA is reached), Pause on and off in the first seconds of a start, a portal poll that holds a
  Pause change and a Re-arm or Check now (answered against the poll's own Pause value), the floor-wait note written
  only while the Re-arm is still pending.
- A login waiting in the FLICA gate (a pilot's 100 an hour, the host cap, the pacing) now gives up when Pause comes on
  (`RUN["login"]`, `gate_abort`), with no refusal block and the login time put back; a Re-arm's login gets the cancel
  note, a back-off or step-aside login is left to the loop, which parks for Pause (older than 1.7.5).
- The 10 min login floor now counts from when FLICA is reached (the login page past the gate, and again after the
  credentials are submitted), not from before a gate wait: a gate-delayed login could be followed by a back-off login
  a minute later (older than 1.7.5).

### Not changed
- Un-pause during a step-aside for the owner's own FLICA login ends the step-aside as before: the Paused card says
  "Turn Pause off when you have signed out of FLICA" (a change made during review was backed out).
- Known edge (Ryan's call if wanted): Pause turned on after the login page has passed the gate does not give up the
  credentials' submit; it waits only when the pilot's hourly FLICA budget is used up.

Tests: `tests/test_fw175_pause_wins.py`, `tests/test_fw175_review.py`, `tests/test_fw175_review2.py`,
`tests/test_fw175_review3.py` (synthetic only).

## 1.7.4

A pilot's FLICA refusal record keyed with an HMAC of his own instance key (Ryan, Nov 13: the backlog item "the FLICA
refusal block on a pilot as an HMAC like CrewTrac's"). Built with tests that failed first, then three adversarial
reviews (security and migration, login flows, then a fresh pair on the rework); every reproduced finding is fixed.

### The block's record
- Before: a pilot's FLICA refusal block (`S["flica_refused"]`: FLICA refused these details, no login with them until
  others are saved, CHANGELOG 1.6.2) held a bare sha256 of his FLICA user name and password: anyone reading his state
  could test password guesses against it offline.
- Now: an HMAC-SHA256 with a random 32-byte key of that instance (`<data>/flica_hmac.key`, mode 0600, read with
  O_NOFOLLOW, made atomically on first need, a lock against two makers, never logged, exported, published or
  captured), as CrewTrac's since 1.7.2. The admin never makes a key and has no block.
- The first 1.7.4 start of a pilot re-keys a 1.7.3 record of the details in use (the block holds, same time) and drops
  any other; one log line gives the counts. The old bare sha256 is then scrubbed from the database files too
  (`Store.scrub`: checkpoint, VACUUM, TRUNCATE checkpoint; retried at each start until it completes): a checkpoint alone
  left copies in free pages.

### The block never lifts on a doubt
- A key gone, unreadable or replaced, or a state copy put back onto a remade key, with a refusal on record: no stored
  record can be matched, so the pilot stays blocked while stopped_login_failed until FLICA details are saved again in
  Settings (`flica_key_lost`); the note, the restart note and Re-arm's answer say so. A read error on the key file
  (EIO, EMFILE, EACCES) keeps the key and the block (only a missing file, a link, a socket, a non-regular file or a
  wrong size count as no key).
- The same FLICA details saved together with another change (my name, CrewTrac) now give the one more try too: the
  block holds until the restart that save makes, then the try runs once, through Re-arm's path and the 10 min login
  floor, announced as the save's try; a login cut short by a restart counts for the floor.
- A restart of a refused pilot says the refusal note, never "press Re-arm" (refused then).

### CrewTrac (the admin's charter scan too)
- The CrewTrac key now has a lock (two callers make one key), its key-lost verdict is saved before a new key is
  written, a read error keeps the key, and while it cannot be read the Charters sensor says "CrewTrac scans held: the
  CrewTrac block key could not be read (next try in 1 min)" instead of the last good status. A CrewTrac save during a
  read error still lifts a lost-key block.

### Not changed (Ryan's call)
- Pause turned on while a Re-arm (or the save's try) waits for its login floor does not stop that login (so since
  1.6.2). Whether an explicit Re-arm or save beats Pause is Ryan's decision.

### Rollback to 1.7.3 (read first)
- 1.7.3 compares a bare sha256, so it never matches a 1.7.4 record and ignores `flica_key_lost`: a pilot stopped by a
  FLICA refusal is no longer blocked there, and his next Re-arm makes one more FLICA login with details FLICA refused.
  Before a rollback, restore /data from the backup taken before the 1.7.4 update; without it, check whether the pilot
  is stopped_login_failed with a FLICA refusal note and make sure nobody presses Re-arm for him until his details are
  right. Blanking the password in Settings does not work (blank values are ignored). Going forward to 1.7.4 again
  re-keys anything 1.7.3 wrote.

Tests: `tests/test_fw174_flica_hmac.py`, `tests/test_fw174_review.py`, `tests/test_fw174_review2.py` (synthetic
details only).

## 1.7.3

Fixes for three low bugs the post-deploy check of 1.7.2 found live on Nov 13 (all older than 1.7.2). Each was
reproduced with a synthetic test that failed first, then reviewed adversarially; the review findings are fixed too.

### Crew index probes no longer stop every pairing read
- Seen live 7 times (Nov 12 to 13): a crew index run probed the lettered copies of a trip (FW-0068: H3646A to D,
  H3604A to D). A copy that does not exist answers with a page that names the id but has no report, crew or credit
  (or FLICA's application error page). The Watcher judged each one a failed pairing read; the third in a row stopped
  every pairing read for 30 min ("FLICA pairing read stopped for 30 min ...: not a pairing page"), which also
  blocked Ryan's detail reads, pickups and own trip times, and outlived a restart. The trip was never recorded, so
  every run (about 4 a day) probed it again until VARIANT_MAX_AGE_D.
- While crew_variants reads a lettered copy (`PROBE["miss_ok"]`), a no-such-trip page or FLICA's error page is a miss
  and leaves the breaker alone. A page nothing knows, a CAPTCHA or a load error still counts, and every detail or
  queue read is judged as before (a real error page there still trips the breaker).
- A probe cut short (a stopped path, the budget, a fetch error) is a try (`crew_variant_tries`, letters done and
  failed kept); the next run reads on from the letters not read yet, and a trip is recorded (parked) once every
  letter had a try (VARIANT_MAX_TRIES 3), so it is never probed every run. Tests: `tests/test_crew_variants.py`.

### A pilot's log masks crew names and employee numbers in every form
- Seen live: the second pilot's "detail probe" line kept the captain's name and his 4-digit employee number readable
  (the name came right after a quote; the number mask took only 5 to 7 digits); older lines kept a two-word surname's
  first word. Only the admin and Claude read the add-on log, but PilotLogMask promises other pilots' names and
  numbers are masked on every pilot line.
- `captures.py`: a name after a quote is masked; a name followed by its employee number in parentheses (3 to 7
  digits) is masked whole, page-word surnames, middle names and letters outside ASCII (accents, the okina) too; the
  name run is bounded so the mask stays linear on long text. Times, dates, pairing ids, flight numbers, years and
  credits stay. `watcher.detail_probe` on a pilot now says only whether a captain was parsed; the admin's line is as
  before. Tests: `tests/test_fw173_log_mask.py` (synthetic names only).
- F#55's live run (Nov 14, Ryan's yes: one lookup on the second pilot's session, by name, then the pick) worked end to
  end (name lookup on the award files, the pick, the employee-number Schedule Lookup, the result on his portal), with
  FLICA answering its application error page as it does for every November lookup that day. It showed more of the
  same leak on a pilot's lines, now fixed and reviewed adversarially:
  - the lookup's lines start "pilot <employee number>:" and the pickup check's "picker <employee number>"; a 4-digit
    number stayed readable (`PILOT_EMP_RE`: masked after "pilot" before ":" or " (", and after "picker", 3 to 7
    digits; "100 loads an hour" stays);
  - a failed lookup page's text (lowercased by visible_text, so the name masks missed "doe, jane (emp# 1234)") was
    logged as it was: a pilot now logs page text only through `page_log` (only while his captures are on, masked),
    in the lookup and in the pickup check (`inflt.PAGE_LOG`); the admin's lines are as before;
  - the Pilot card's status for FLICA's error page is one plain line ("not readable: FLICA application error, try
    again later", which the card since 1.6.2 turns into its friendly line), any other page one short line with no
    control or bidi character (`pilot_unreadable_status`).

### The state note drops a pause when it ends
- Seen live: `sensor.flight_watcher_state` kept "FLICA pairing read paused until 05:52 HST" at 06:25, until the next
  good pairing read (up to Ryan's 90 min check).
- `health_note_tick()` runs every loop tick (60 s), after each gate wait chunk and before each FLICA load: when the
  breakers' part of the note changed, the note is applied again (published only on a change; a stop, pause or yield
  note is never replaced). No FLICA load. Tests: `tests/test_fw173_breaker_note.py`.

## 1.7.2

Portal contract 1 revision 3 (the council's plan of Nov 11 and Ryan's decisions the same day), from the audit of the
live portal and FW-0066 (Ryan: "either I or James can upload them; the pairings and awards are the same doc for each
of us"). On top of 1.7.1 (live). A contract change: HOM 1.8.2 (takes
revision 2 and 3 exports and commands) ships first, then this release; each with Ryan's yes, a backup and a 30 min
live watch; rollback Flight Watcher first (see "Rollback to 1.7.1" below). The fixture `tests/fixtures/portal_contract_v1.json` is regenerated (its new
sha256 is pinned in `tests/test_portal_contract.py`; HOM's `fwportal/contract/v1.json` must be the same bytes) and
`PORTAL_CONTRACT.md` says revision 3. Revision 2's crewtrac_refused pilot event is not in it: since 1.7.1 a pilot's
Watcher makes no CrewTrac login at all.

### Contract 1 revision 3 (`roles.py`, `portal.py`, `ntfy.py`, `bidcal.py`)

- `bid_calendar` on the pilot's portal (FW-0070 for the pilot): 1.7.1 computes the bid calendar alerts on every
  instance and only Ryan's prefix had a push. Each alert is now a portal event of the pilot's (his Alerts list and
  ntfy) with the admin's push words, built from the alert's own fields only (`bidcal.alert_text`: bid_month, alert,
  event_hst, at_hst, source, cycle_source; `roles.EVENT_KIND_FIELDS`, carried for that kind only), view watcher,
  priority 4. The `event/bid_calendar` payload gains `alert` and `cycle_source` on every instance (the same keys on
  both; the admin's automation reads title, message and key as before), and its `at_hst` is the time the words are
  from.
- `schedule_unread`, the Watcher's own event (never from an MQTT topic): after 6 h without a good FLICA schedule read
  (since the last good read, or since this start when none came after it), at most once an HST day, not while paused,
  waiting for the FLICA login or stopped; data only `state` (failing or waiting) and `hours`, view schedule, ntfy
  "Schedule not read for 7 h".
- `pilot/set` shape (F#49, `roles.SHAPE_CMDS`, `portal.check_shape`, the ticket commands' generic rules): keys only
  emp, q, name and pick; emp 1 to 7 ASCII digits; q 1 to 60 and name 0 to 60 code points of one line; pick 12 hex.
  The spool, HOM and the Watcher (every instance, `pilot_cmd`) refuse anything else; the Watcher's log line never
  carries the text. The pilot lookup card sends only that shape (a long name is cut to 60, a line break is a space).
- `recall/set` leaves `PORTAL_CMDS` (F#78) and is named in `PORTAL_REFUSED`, with `layover/note` and the new
  `upload/decide`: a pilot's recall lists come only from the admin's forward (1.7.1). The admin's own paste on his
  dashboard asks first when it would replace a day on file, naming those dates ("Replace the recall lists already on
  file for Tue Nov 3, Wed Nov 4?"); Cancel sends nothing.
- The fit alone in the new pairing text (F#161): "... Credit 15:20. Fits. FAR 117 OK", not "Fit Fits".
- The manifest names its `revision` (3); HOM refuses a revision 3 command to a Watcher whose manifest names none or 2
  (`commands.since_revision`), with a plain message. The fixture also carries `commands.shapes`,
  `commands.pilot_upload_limits`, `commands.pilot_upload_checks`, `commands.removed_in_revision`,
  `events.kind_fields`, `events.bid_calendar_alerts`, `synthesized_states` and `revisions`, and refused samples for
  every shape rule.

### A pilot's pairings package and award uploads (FW-0066, Ryan's decision)

- New portal command `upload/pdf` (feature `pilot_uploads`, taken only on a pilot whose portal is on, at qos 1): one
  chunk of the month's pairings package or award PDF (never the seniority list or the contact list), each under the
  64 KB command cap (60000 base64 characters, at most 94 parts for 4 MB). The pilot uploads card (new, the portal's
  Settings tab, 390 px light and dark) reads the file with FileReader, takes its sha256 with WebCrypto and sends one
  part every 2.5 s; it shows what is on file for this month and the next two (from you, the admin or another pilot:
  never a name), his uploads and the Watcher's answers, from `sensor.<prefix>_pilot_uploads`, which the Watcher
  synthesizes in his portal's state.json (never a Home Assistant entity).
- `pilotpdf.py` on the pilot's Watcher, before anything is stored: one upload at a time, chunks in order, 120 s
  without a chunk drops it, the month this HST month or one of the next two, 4 uploads a day, 4 MB, the whole base64
  to its size and sha256, `%PDF-` and `%%EOF`, then `pdftotext -layout` (the admin's extractor) in a child process
  with a 30 s timeout and memory (512 MB), CPU (30 s), file size and core limits set in the child (setrlimit), then
  the existing parsers: that month's pairing package (its title, at least 100 pairings over every base and fleet, at
  least one A332 HNL one; the real November and December packages hold 257 and 225 pairings, 84 of them A332 HNL) or
  that month's award holding his own line. A refusal says why in plain words; an upload refused stays refused (its
  later chunks are ignored).
- Nothing on file for that month and kind: used at once, both instances read it as an upload of the admin's. A file
  on file: the pilot's copy goes to `/share/flight_watcher/upload_review/quarantine/` (0700, files 0600), which no
  instance reads and nothing serves (not the uploads list, not the portal export, not the Web UI) until Ryan approves
  it; the same file again is not stored. Provenance per file (who, when, sha256) in
  `upload_review/provenance.json`, the admin's own uploads included (`web.save_upload`, `Review.record_admin`).
- Ryan's push: his Watcher publishes `flight_watcher/event/pilot_upload` once per upload (feature `upload_review`,
  the admin only) and the new HA automation "Flight Watcher pilot upload" (`ha/automations_flight_watcher.yaml`, not
  on Pako yet) pushes his two iPhones, time-sensitive, naming the file and the pilot: Remove for one used at once,
  Approve and Reject for one held. A button publishes `{id, action}` to `flight_watcher/upload/decide`, the
  admin-only command his Watcher takes (also from the new "Pilot uploads" part of his Settings uploads card, which
  asks first). Approve swaps the held copy in and keeps the old file in `upload_review/rollback/`; Remove takes a
  pilot's file off (the file it replaced comes back when there was one, else nothing is on file; the pairing file
  goes too); Reject deletes the held copy. Each change bumps the file's generation, which every instance follows
  within a minute whatever its state (`upload_gens_check`: a removed package's details and a removed award's version
  .001 are forgotten, `versions.clear_award`; a swapped file is read again). The push guard passes and counts the new
  handler (23 automations with the Nov 12 ask-Hark one, 3 notification-action handlers, 0 offenders).

### CrewTrac refusal block keyed with an HMAC (the council's change)

- The admin's stored CrewTrac retry block (1.6.1, a bare sha256 of the user ID and password) is HMAC-SHA256 with a
  random 32-byte key of the instance's own (`<data>/crewtrac_hmac.key`, 0600; never exported, logged or sent). The
  first 1.7.2 start re-keys the record of the details in use and drops a bare sha256 of any other. A key found gone
  later with a refusal on record keeps CrewTrac blocked until the next save in Settings ("CrewTrac is not tried: its
  refusal record could not be checked ..."); with no refusal on record nothing is blocked.

### Review fixes (three adversarial reviews of revision 3)

- A pilot's upload id is never a record's id: `Review.store` mints the id (24 hex) that names the quarantined copy,
  Ryan's push and his Approve / Remove / Reject, keeps the pilot's own `uid` beside it for his card, and refuses a uid
  already on record. Before, a uid sent again by a crafted client overwrote a held copy (Ryan's Approve of December's
  package put another file in use) or put a file in use with no push and no Remove. Approve also installs only bytes
  whose sha256 is the record's.
- Remove after an Approve: the pilot's file that comes back is in use again (`live` or `approved`, not `replaced`), so
  Ryan can Remove it in turn; a file back from rollback that is not its record's is "restored" with no pilot's name.
- The package parsers take linear time on a pilot's text: the bid period pattern (`pdfs.PERIOD_RE`, the same text as
  before) no longer takes cubic time ("January 1" then 1200 empty pages took 28 s in the check and 86 s in each
  instance's uploads check, the Watcher frozen meanwhile), the calendar cells are read in one pass (`pdfs._cal_tail`,
  what `CAL_RE` found), and the lines before a header are appended, not copied. A pilot's text is bounded before any
  parser sees it (`pilotpdf.text_shape`: at most 60000 lines of at most 1000 characters, 8 million characters in all;
  the real files on file are 11,600 to 20,100 lines of at most 676 characters).
- An award whose last line is the start of a pilot's line (the next four lines cut off) is "not read" for him
  (`ValueError`), not an `IndexError` that stopped every later award's read on each instance.
- The extractor runs as nobody (65534, no groups) when the Watcher runs as root (it does in the add-on), in a folder of
  its own, and its text is copied to a new file of the Watcher's (never read through a link, a FIFO or another user's
  file) before that folder goes.
- schedule_unread counts its 6 h from the last tick that saw the pilot paused, stopped or waiting for his login (his
  Pause off or Re-arm gets its first read in first) and goes at most once in 24 h (not again at 00:00 HST).
- An upload the pilot's Watcher drops for no part in 120 s, or one a restart cut off, gets an error answer (or, when
  its check had finished, the answer it gave), and the uploads card stops waiting 3 min after its last part.
- A removed award is no longer a looked-up pilot's version .001 either (`pilotver.clear_award`).

### The card loader picks up new cards on an open page (Ryan, Nov 12, in Sydney)

- Ryan's phone showed "Configuration error" on the Working Flight page. The layover card's code and his data were
  fine (it renders in Chromium with his live sensors): the phone app kept a page open from before 1.7.1, and the
  loader imports the card list only once per page, so the card the dashboard asked for was never imported.
- `cards.py` LOADER_JS now reads `flight-watcher-cards.json` again whenever the page comes back to the screen and
  every 5 min, imports a card not imported yet, and tries a card whose import failed again (under `&r=<n>`, since a
  browser keeps a failed module). A card already imported is never imported twice (`tests/test_cards_loader.py`
  runs the real loader in Chromium against a fake `/local/`).
- The phones hold the old loader up to 31 days (HA's `/local/` cache), so after this release is live the one
  dashboard resource becomes `/local/flight-watcher-loader.js?v=1.7.2` (`ha/README.md`). Until then a full reload
  of the app (pull down) fixes such a page. The Working Flight view also has the built-in markdown card and the
  "Ready to update?" button back above the layover card (applied on Pako Nov 12), so it reads with no custom card.
- James's portal is not affected: it loads its card bundle on every page load, and its Watcher tab uses the
  working-flight card, which renders with his live export (checked Nov 12).

### "Ready to update" asks Hark by itself (Ryan, Nov 12)

- Ryan: "When I click ready to update I want you to trigger hark without my help. Get the info and bring it back
  automatically." On Pako (HA config, not the app): the Working Flight button runs a new automation, "Flight Watcher
  ready to update (ask Hark)", that waits up to 30 min for Hark's release, MEL and NOTAM write and pushes Ryan
  either way; Hark watches the automation's `last_triggered` (bus ASK, Nov 12). Details in `ha/README.md`.
- `roles.RESERVED` gains "ready", so the push guard reads `automation.flight_watcher_ready_to_update_ask_hark` as
  the admin's (a pilot can no longer be named "ready").

### Van alert settings (Ryan, Nov 12)

- Ryan: "I like the layover card. Can you add a tick box to turn on the van time alerts and also add van time alert
  settings in the form of sliders in the settings tab?" Ryan's Watcher only (roles `admin_pushes`, like the alerts).
- The Watcher keeps `S["van"]`: `on`, `first` and `second` (minutes before the van; defaults on, 30 and 10, 1.7.1's
  alerts), saved with the state so a restart keeps them. New admin-only MQTT commands: `flight_watcher/van/alerts/set`
  ON or OFF (on, off, true, false too), `flight_watcher/van/first_min/set` 5 to 120 and
  `flight_watcher/van/second_min/set` 0 to 60 (0 is no second alert), a whole number of minutes, clamped; 'abc',
  'inf' or 'nan' is ignored like the frequency sliders. Retained states `flight_watcher/van/alerts/state`,
  `.../first_min/state` and `.../second_min/state` at connect and after each command; one log line a change.
- New entities (Ryan's only; a pilot's Watcher empties their configs): `switch.flight_watcher_van_alerts` "Van time
  alerts", `number.flight_watcher_van_alert_first` "First van alert" (5 to 120 min, step 5, slider) and
  `number.flight_watcher_van_alert_second` "Second van alert (0 is off)" (0 to 60 min, step 5, slider).
- The alerts follow the settings: the lead times are the distinct values above 0 of first and second, largest first
  (`layover.offsets_of`; `due`, `event` and `sensor` take them, `OFFSETS` stays the default). Off sends nothing; the
  van sensor still shows the van.
- Safety: a setting changes only the van in hand when it is made (the last van the Watcher placed), never a van it
  learns later. `layover.settle` says what happens to each lead time that became active (alerts switched on, or a
  slider moved to a new value), and the Watcher writes its skips into the DB at once (one log line each):
  - its mark is ahead: it goes at its mark;
  - its mark has passed and another alert for that van is still ahead or one has gone (or the van has passed): skipped,
    `why` `set_after_mark`, never sent late on top of them;
  - its mark has passed and nothing has gone or is ahead: the latest such one goes at the next sweep, worded with the
    minutes left (the late-start rule), so a setting never leaves the van in hand with no alert (raising both alerts
    past their marks at 35 min before used to silence the van);
  - its slider's alert has already gone for that van: skipped, `why` `slot_sent`. One alert a slider a van: moving the
    first slider after its alert went sends no other for that van (it used to send one for each move). The same value
    on both sliders is one alert, the first's, so splitting them again still sends the second. A sent key names its
    slider (`slot`); a key from 1.7.1 names none and counts for none.

  A van Hark moves or writes after a setting is a new key and follows the 1.7.1 rules (a late-learned van sends its
  latest alert still due; tying the setting's time to every later van could leave a moved van with no alert at all).
  Before the Watcher's first look at the van after a start (one sweep, 10 s) there is no van in hand, so a setting then
  changes nothing already decided and a van follows the 1.7.1 late-start rule (an alert late, never none). The
  late-start rule after a restart is exactly 1.7.1's (`why` `late_start`); its log line now says the mark passed with
  no alert (the app or MQTT was down, or the van time came later), not that the app was not running. The DB key keeps
  its form (pairing, van instant, minutes), so an alert sent once is never sent again, whatever the tick box or the
  sliders do after it, and nothing goes after the van time. The kept keys stay bounded: the newest 40, and always
  every key of the van in hand (at most one a lead time), so a run of slider moves can never push out an alert already
  sent and send it again (`van_keep`).
- `sensor.flight_watcher_layover_van` gains `alerts_on` and `offsets` (even without a van), and its alerts list is the
  current lead times (status `off` while off; a skipped one with its `why`; switched on only after the van, skipped,
  not missed). A setting republishes it at once. The
  `event/van` payload gains `offsets`; the push automation is unchanged (title, message, minutes).
- Layover card: under the van time, a "Van alerts" tick box (checked from the sensor's `alerts_on`, else the switch;
  when neither says, as while the Watcher is unavailable, "Not known yet" and not tappable, never shown as on); a tap
  publishes `flight_watcher/van/alerts/set` ON or OFF, shows "Saving..." until the sensor says the new state (the line
  under the van lists no alert times while saving off), and puts the box back with a short message on a publish error
  or no answer in 30 s (also when the card was off the page meanwhile); the message goes once the Watcher's state
  changes. The box keeps the keyboard focus through a tap and its answer (`aria-disabled` while waiting, not
  `disabled`). Under it "30 and 10 min before" ("Off" when off) and "Change in Settings" (the Settings tab, in the
  app). 44 px taps, a box white on a fixed dark blue when ticked, AA contrast in light and dark, no sideways scroll at
  390 px.
- Settings tab: a "Van time alerts" heading and tiles for the switch and the two sliders (`numeric-input` slider
  feature). These entities exist from 1.7.2, so the dashboard edit is applied on Pako after this release is live
  (`ha/README.md`, Pending); the snapshot is one edit ahead of Pako until then.
- `roles.py`: the three set topics in `SUBS` (admin_pushes) and `NOT_ON_PORTAL` (a portal never sends them; the spool
  refuses them), the three entities in `ENTITY_FEATURE`, and "van" in `RESERVED` (a pilot can no longer be named
  "van"; the push guard reads `*.flight_watcher_van_*` as Ryan's). The portal contract fixture and
  `PORTAL_CONTRACT.md` are byte for byte unchanged (revision 3).
- Tests: `tests/test_van_settings.py` (commands, clamps, restart, discovery by role, custom lead times, off, switched
  on or moved after a mark, a van moved or learned after a setting, lead times raised past their marks, one alert a
  slider a van, switched on after the van, MQTT down over both marks, toggles and sliders back and forth, the restart
  rule, bounded keys, roles and the contract, the card at 390 px with the Watcher unavailable, away from the page and
  by keyboard, the Settings tiles).

### The GIN code on its own line (Ryan, Nov 12)

- "Gin code should be on its own line so it doesn't get cut off." The layover card shows Hark's GIN as the label and
  place ("GIN arr: HNL gate C5 (Non-Mauka)") with the code under it on one unbroken line (`_gin`,
  tests/test_layover_card.py). The same change is live on Pako in the Working Flight view's markdown card.

### Pay protection (PAYP) counts its credit (Ryan, Nov 13)

- Ryan: "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?" In v11.029
  H3620 Nov 12 to 14 (credit 15:00) became PAYP Nov 12 to 14; FLICA's month credit stayed 131:15 (block 94:42 to
  82:23), but the schedule card showed Credit 116:15 beside a red "FLICA 131:15", and Pay-Gross and Pay-Net fell by
  the 15:00. 2023 PWA Definitions item 57: "PAY PROTECT/PAY PROTECTION (PAYP): A Flight Grouping that has been
  removed from a pilot's schedule, however the pilot shall retain the Pay and Credit for such Flight Grouping." PWA
  4.R.1: "Should a pilot elect to Add a Flight Grouping on a PAYP day(s), the pay shall be: a. Pay and Credit of the
  PAYP Day, and b. Pay and Credit of the added Flight Grouping". (NQ pay protection, PWA 4.Q, is not this case.)
- Why it dropped: the card adds up each trip's credit from `sensor.flight_watcher_own_trip_times`, which held only
  pairings read from their FLICA pairing pages. PAYP is a code with no pairing page, so it counted 0:00 and $0.
- The Watcher (`payp_refresh`, `versions.payp_entries`; every instance for its own schedule, no FLICA load): each
  PAYP item on the schedule gets an own trips record `PAYP|<start>` with the removed trip's credit, block and soft
  0:00, `payp`, `protected` (the removed trip's key), its seat, the PAYP's end and where the credit came from. The
  removed trip is the own trips record no longer on the schedule that starts on one of the PAYP's days (looked at
  before those records are pruned), else the pairings that start on those days in the newest stored version before
  the PAYP; else there is no record (a credit is never guessed here). One PAYP over parts of two removed trips sums
  both credits, each in full; a removed trip counts for one PAYP only. The record stays while the PAYP item is on the
  schedule (the removed trip being gone, or a trip added on the PAYP days and dropped again, changes nothing) and is
  pruned with it. On Pako H3620's own record was already pruned, so the first check after the update takes its 15:00
  from v11.028 (checked read only on Pako's versions file: H3681, home on Nov 12, stays out).
- Versions: the record is stored in each new version's trips like any trip (`TRIP_FIELDS` gains `payp`,
  `protected`, `split` and `of`), so the version browser, Awarded-Pay-Gross and Improved-Pay-Gross count it. Its first version says so
  ("PAYP 2026-11-12 keeps H3620 2026-11-12's credit 15:00 (pay protected)"); on Pako that is one new version (11.030)
  right after the update, the same line as 11.029 with the credit kept.
- The schedule card: a PAYP's credit counts in Credit, Pay-Gross and Pay-Net on its first day, at the hourly rate,
  with no block and no soft; the PAYP label and the Credit cell say "Pay protected: H3620 Nov 12 (PWA Definitions 57;
  4.R.1 if you add a trip on these days)"; a PAYP has no trade or drop mark; the totals show "PAYP 15:00". No IRO or
  Extended Range override is added by itself (PWA 4.O.1 pays them per block hour or for the seat flown, and a PAYP
  flies none); the RO+15% tap in the Pay-Gross box still turns one on. With no record (v11.029 as stored on Pako, or a
  Watcher before 1.7.2) the card estimates the credit: FLICA's month credit less everything else it counted, only when
  that is above zero and the month has a PAYP, split by days over the PAYP items without a record, marked "est" on the
  row, "estimate" in the totals and "est" beside Credit (no check mark: it equals FLICA's by construction). A trip
  added on PAYP days counts in full on top (PWA 4.R.1). The Block total, Block Avail (98 h), the FAR columns and the
  98/672 checks never count a PAYP (not flown).
- Fix pass (two reviews of the change, each finding reproduced with a synthetic test first):
  - A trip that only comes home on the PAYP's first day (H3681 Nov 9 to 12 on Pako, beside PAYP Nov 12 to 14) joined
    the record when it left the schedule in the same read (35:55 instead of 15:00). A removed trip now counts only
    when it starts on one of the PAYP's days, in both the own trips and the versions paths.
  - A partial cancellation counted the flown part twice: H3620 Nov 12 to 14 becoming H3620A Nov 12 to 13 (7:30) plus
    PAYP Nov 14 kept the full 15:00 on top (Credit 138:45 against FLICA 131:15). Now there is no record for it (the
    card's estimate, 7:30); when FLICA puts a lettered pairing over the removed trip's days and the PAYP starts first,
    the record holds what is left of the credit once that pairing is read, and none before.
  - PWA 4.R.1: a trip added over every PAYP day (FLICA shows it, no PAYP) pruned the record and the 15:00 was lost
    again (Credit 134:15 against FLICA 149:15). The record now stays while a pairing other than the removed one starts
    on its days; the card counts it in the totals only when FLICA's month credit holds it, so a reassignment that ends
    the protection (FLICA 126:15) counts nothing.
  - A PAYP over the month boundary (like H3607 Nov 30 to Dec 2 on Pako, duty blocks 600 and 455 minutes) kept all
    17:35 in November and December estimated 7:35 more. The record now carries `split` (PWA 4.A, the card's own block
    share: November 10:00, December 7:35), the card counts each month's share, and the PAYP December's page lists
    again gets a record of its own for its share (`of`). Every day of a PAYP names its record, the next month's too.
  - With no record on file, a trip added on PAYP days and then dropped became the protected trip (6:00). A trip a
    stored version shows taken on days already PAYP is never the protected trip now.
  - FLICA showing the days empty one read before PAYP lost the trip (no record). The versions path now looks past
    such a read when the days went empty at most a day before the PAYP showed; a PAYP that grows also takes the trip
    removed on its new days from the versions.
  - The estimate took credit that is not the PAYP's (an unread trip, SIM or SICK days, last month's trip running into
    this one: "PAYP 45:00 est" for 15:00, and the red Credit check turned into a check mark). The card now estimates,
    and counts a PAYP kept under an added trip, only when it counts everything else in the month; otherwise the totals
    say "PAYP credit unknown" and the red check stays. With no FLICA total it says so too (it counted 0:00 silently).
  - FW-0064: H3620 cancelled to PAYP and H3999 added the same HST day was pushed as "Trade, Approved, Pay-Gross
    -$2,331". A trip whose first day is now PAYP is marked explained ("pay protected"), also when the PAYP shows a read
    after the drop, so it is never priced as given away.
  - Left as it was: the removed trip's IRO override and Extended Range +15% (PWA 4.O.1) are not added to the PAYP's
    pay (whether Definitions 57's "Pay" includes them is Ryan's call against the contract text); `protected` changing
    alone makes no new version (cosmetic).
- Open time over PAYP days (Ryan: "make way for the fact that I can also pick up a trip over the top of PAYP for
  additional pay"; PWA 4.R.1). On Pako H3607 Nov 13 to 15 and H3839 Nov 13 to 14 over PAYP Nov 12 to 14 were tagged
  "Conflict PAYP" and their FAR column said "may overlap PAYP Nov 12: PAYP Nov 12 times not on file". A PAYP day is
  now free for a pickup: the fit tag (`pot.fit_tag`, `FREE_ITEMS`), the month rules (`smart.month_rule`,
  `FREE_CODES`, whatever smart.json `off_codes` lists) and the FAR line (`recall.line_records`) leave the PAYP out,
  since its trip is not flown. FLICA counts PAYP days in Days Off (Pako: 13 before, 15 with the PAYP), so a pickup on
  them uses days off as on any day (10.G, `min_days_off`). A trip already added on a PAYP day still holds that day
  (a Conflict), and a trip either side still needs its rest ("Check rest"). The Recall / Over 75 miss check is
  unchanged: it still counts a PAYP as possible duty (POSSIBLE, never MISSED). Tests: `tests/test_payp_pickup.py`.
- Limits: a trip from last month running into this month is still not counted in this month's totals (as before
  1.7.2); a reserve month still asks for SCR on every pickup day (a PAYP day there reads "Not SCR").
- Tests: `tests/test_payp.py` (synthetic v11.028 to v11.029: Credit 131:15 with the FLICA check passing, Pay-Gross
  and Pay-Net as in v11.028, the estimate, PWA 4.R.1, block and Block Avail, the Watcher on both instances across
  refreshes and pruning, the versions, the card at 390 px; the fix pass adds the month boundary, the partial
  cancellation, the trip added over every PAYP day, the adjacent trip, the read before the PAYP, the estimate guard
  and the trade push).

### Rollback to 1.7.1

- 1.7.1 cannot read 1.7.2's HMAC-keyed CrewTrac records: it takes them for other details and lifts a refusal block, so
  it would make one more CrewTrac login with details CrewTrac refused. Before a rollback, restore /data from the backup
  taken before the update, or, when CrewTrac refused the details in use while on 1.7.2, blank the CrewTrac password in
  Settings first (then save the right password on 1.7.1).
- 1.7.1 ignores `S["van"]` (its alerts are always on, 30 and 10) and leaves the van setting entities without a
  Watcher behind them; the Settings tiles show them unavailable until they are removed (`ha/README.md`).

### Also

- The admin's uploads card keeps WCAG AA contrast on a dark card (its green "read" was 3.1:1).
- `Dockerfile` copies `pilotpdf.py`.

## 1.7.1.1

Hotfix on 1.7.1: pay protection (PAYP) keeps the removed trip's exact Pay and Credit (Ryan, Nov 13: "My LAS trip today
was cancelled and PAYP pay protected. Why did your pay calculations drop?", "Fix it now", then "I want it to keep the
exact cancelled trip credit. Also make way for the fact that I can also pick up a trip over the top of PAYP for
additional pay."). The same change is in 1.7.2 (PR 107).

- Ryan: "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?" In v11.029
  H3620 Nov 12 to 14 (credit 15:00) became PAYP Nov 12 to 14; FLICA's month credit stayed 131:15 (block 94:42 to
  82:23), but the schedule card showed Credit 116:15 beside a red "FLICA 131:15", and Pay-Gross and Pay-Net fell by
  the 15:00. 2023 PWA Definitions item 57: "PAY PROTECT/PAY PROTECTION (PAYP): A Flight Grouping that has been
  removed from a pilot's schedule, however the pilot shall retain the Pay and Credit for such Flight Grouping." PWA
  4.R.1: "Should a pilot elect to Add a Flight Grouping on a PAYP day(s), the pay shall be: a. Pay and Credit of the
  PAYP Day, and b. Pay and Credit of the added Flight Grouping". (NQ pay protection, PWA 4.Q, is not this case.)
- Why it dropped: the card adds up each trip's credit from `sensor.flight_watcher_own_trip_times`, which held only
  pairings read from their FLICA pairing pages. PAYP is a code with no pairing page, so it counted 0:00 and $0.
- The Watcher (`payp_refresh`, `versions.payp_entries`; every instance for its own schedule, no FLICA load): each
  PAYP item on the schedule gets an own trips record `PAYP|<start>` with the removed trip's credit, block and soft
  0:00, `payp`, `protected` (the removed trip's key), its seat, the PAYP's end and where the credit came from. The
  removed trip is the own trips record no longer on the schedule that starts on one of the PAYP's days (looked at
  before those records are pruned), else the pairings that start on those days in the newest stored version before
  the PAYP; else there is no record (a credit is never guessed here). One PAYP over parts of two removed trips sums
  both credits, each in full; a removed trip counts for one PAYP only. The record stays while the PAYP item is on the
  schedule (the removed trip being gone, or a trip added on the PAYP days and dropped again, changes nothing) and is
  pruned with it. On Pako H3620's own record was already pruned, so the first check after the update takes its 15:00
  from v11.028 (checked read only on Pako's versions file: H3681, home on Nov 12, stays out).
- Versions: the record is stored in each new version's trips like any trip (`TRIP_FIELDS` gains `payp`,
  `protected`, `split` and `of`), so the version browser, Awarded-Pay-Gross and Improved-Pay-Gross count it. Its first version says so
  ("PAYP 2026-11-12 keeps H3620 2026-11-12's credit 15:00 (pay protected)"); on Pako that is one new version (11.030)
  right after the update, the same line as 11.029 with the credit kept.
- The schedule card: a PAYP's credit counts in Credit, Pay-Gross and Pay-Net on its first day, at the hourly rate,
  with no block and no soft; the PAYP label and the Credit cell say "Pay protected: H3620 Nov 12 (PWA Definitions 57;
  4.R.1 if you add a trip on these days)"; a PAYP has no trade or drop mark; the totals show "PAYP 15:00". No IRO or
  Extended Range override is added by itself (PWA 4.O.1 pays them per block hour or for the seat flown, and a PAYP
  flies none); the RO+15% tap in the Pay-Gross box still turns one on. With no record (v11.029 as stored on Pako, or a
  Watcher before 1.7.1.1) the card estimates the credit: FLICA's month credit less everything else it counted, only when
  that is above zero and the month has a PAYP, split by days over the PAYP items without a record, marked "est" on the
  row, "estimate" in the totals and "est" beside Credit (no check mark: it equals FLICA's by construction). A trip
  added on PAYP days counts in full on top (PWA 4.R.1). The Block total, Block Avail (98 h), the FAR columns and the
  98/672 checks never count a PAYP (not flown).
- Fix pass (two reviews of the change, each finding reproduced with a synthetic test first):
  - A trip that only comes home on the PAYP's first day (H3681 Nov 9 to 12 on Pako, beside PAYP Nov 12 to 14) joined
    the record when it left the schedule in the same read (35:55 instead of 15:00). A removed trip now counts only
    when it starts on one of the PAYP's days, in both the own trips and the versions paths.
  - A partial cancellation counted the flown part twice: H3620 Nov 12 to 14 becoming H3620A Nov 12 to 13 (7:30) plus
    PAYP Nov 14 kept the full 15:00 on top (Credit 138:45 against FLICA 131:15). Now there is no record for it (the
    card's estimate, 7:30); when FLICA puts a lettered pairing over the removed trip's days and the PAYP starts first,
    the record holds what is left of the credit once that pairing is read, and none before.
  - PWA 4.R.1: a trip added over every PAYP day (FLICA shows it, no PAYP) pruned the record and the 15:00 was lost
    again (Credit 134:15 against FLICA 149:15). The record now stays while a pairing other than the removed one starts
    on its days; the card counts it in the totals only when FLICA's month credit holds it, so a reassignment that ends
    the protection (FLICA 126:15) counts nothing.
  - A PAYP over the month boundary (like H3607 Nov 30 to Dec 2 on Pako, duty blocks 600 and 455 minutes) kept all
    17:35 in November and December estimated 7:35 more. The record now carries `split` (PWA 4.A, the card's own block
    share: November 10:00, December 7:35), the card counts each month's share, and the PAYP December's page lists
    again gets a record of its own for its share (`of`). Every day of a PAYP names its record, the next month's too.
  - With no record on file, a trip added on PAYP days and then dropped became the protected trip (6:00). A trip a
    stored version shows taken on days already PAYP is never the protected trip now.
  - FLICA showing the days empty one read before PAYP lost the trip (no record). The versions path now looks past
    such a read when the days went empty at most a day before the PAYP showed; a PAYP that grows also takes the trip
    removed on its new days from the versions.
  - The estimate took credit that is not the PAYP's (an unread trip, SIM or SICK days, last month's trip running into
    this one: "PAYP 45:00 est" for 15:00, and the red Credit check turned into a check mark). The card now estimates,
    and counts a PAYP kept under an added trip, only when it counts everything else in the month; otherwise the totals
    say "PAYP credit unknown" and the red check stays. With no FLICA total it says so too (it counted 0:00 silently).
  - FW-0064: H3620 cancelled to PAYP and H3999 added the same HST day was pushed as "Trade, Approved, Pay-Gross
    -$2,331". A trip whose first day is now PAYP is marked explained ("pay protected"), also when the PAYP shows a read
    after the drop, so it is never priced as given away.
  - Left as it was: the removed trip's IRO override and Extended Range +15% (PWA 4.O.1) are not added to the PAYP's
    pay (whether Definitions 57's "Pay" includes them is Ryan's call against the contract text); `protected` changing
    alone makes no new version (cosmetic).
- Limits: a trip from last month running into this month is still not counted in this month's totals (as before); the open time fit marks still treat PAYP days as taken.
- Tests: `tests/test_payp.py` (synthetic v11.028 to v11.029: Credit 131:15 with the FLICA check passing, Pay-Gross
  and Pay-Net as in v11.028, the estimate, PWA 4.R.1, block and Block Avail, the Watcher on both instances across
  refreshes and pruning, the versions, the card at 390 px; the fix pass adds the month boundary, the partial
  cancellation, the trip added over every PAYP day, the adjacent trip, the read before the PAYP, the estimate guard
  and the trade push).

## 1.7.1

Fixes after 1.7.0 went live (the live log of Nov 11 on the second pilot's instance, LIVE-1, and the review findings
F#n), Ryan's decisions of Nov 11, and his tickets FW-0042 part 2 (no monthly credit cap; the 98 h block in 672 h
check), FW-0070 (bid calendar alerts), FW-0071 (paste a screenshot into a ticket) and FW-0072 (the layover page, van
alerts and layover notes; the van time from the pairings package first). Built, not deployed: branch
claude/quirky-thompson-p94wms merges fw171-core, fw171-cards and fw171-bidcal, the review fixes, then fw171-r2 (Ryan's
Nov 11 decisions), fw171-cap (FW-0042 part 2) and fw171-r3 (FW-0071, FW-0072), with each side's fixes kept where they
met.

No portal contract change: `roles.py` PORTAL_CMDS, PORTAL_REFUSED, PORTAL_EVENTS, FEATURES, PILOT_TICKET_LIMITS and
the FLICA budgets, `tests/fixtures/portal_contract_v1.json` and `PORTAL_CONTRACT.md` are as in 1.7.0, and no command
changes shape. What the portal sees that is new is all allowed by contract 1: the layout gains the recall card in alert
mode (a bundled type) and the export a core entity (`sensor.<prefix>_bid_calendar`); the fetches sensor gains two plain
attributes; a pilot reads one retained topic under the admin's prefix (the shared charters) and the admin each
pilot's retained availability (neither is a command topic, so neither is in `roles.SUBS`); an ignored press (Check
now, Re-arm, Scan CrewTrac now) answers ok false with the reason in the result's existing {id, ok, why}; and the new
admin-only command `layover/note` is refused on a portal as "anything else" (`roles.NOT_ON_PORTAL`, the fixture's
bytes unchanged). So no HOM release is needed first.

### The Watcher

- LIVE-1: a pilot's open time hunt paced to his whole 100 loads an hour left the reads that may be left out in one
  first come, first served pool (opt_cap), so his own trips, the pickups and their in-flight lookups took every load
  that came free and the Tradeboard, the reserve grid, the pot details and the trade requests were "left out of this
  check: FLICA budget kept for the open time pot" for hours. Each of those four now has its own share of the hour on a
  pilot (`opt_shares`: one whole read an hour; the Tradeboard 2 loads a bid number, the grid 2 a pot page, the
  requests 1 a folder and 1 a bid number, the pot details 2); the rest of his optional loads stay a pool (`OPT_POOL_H`,
  4 at least), and the pace keeps room for both (`opt_hour`: 12 as before with one bid month, so a 5 s hunt stays
  about 44 s apart; 18 with two, about 96 s instead of 89 s; about 2 min with the close-in folder). A Tradeboard, grid
  or request read starts only when all its loads fit (`opt_fits`: its share or the pool, and his budget and the
  host's cap with `GATE_KEEP` free); one that does not fit tries again at the next check without moving its timer and
  says so in the log at most every 30 min. A grid cross-check left out keeps the JSON just read. The hard caps are the
  gate's, unchanged (a pilot's 100 an hour, the host's 480); the admin has no budget, no shares and keeps his ~376 an
  hour (FW-0035).
- F#15: a pilot instance writes an empty rules.json (the SIN example rule only on the admin, as before; a pilot's
  portal has no rules view, so he could neither see nor turn it off). Once per pilot (DB `example_rule_checked`), a
  rule that is exactly the seeded example (every field but created_at) is removed from his rules.json, logged, and
  its live switch taken down; an edited one stays, and so does the same rule written again later.
- F#12: a Check now (Scan FLICA now) the Watcher would ignore (paused, stopped, waiting for settings, stepped aside,
  in a re-login back-off, under 10 s since the last check, or held by the FLICA budget or the host's cap) answers the
  portal ok false with the reason in plain words and is not republished (`check_now_refusal`, `press_answer` in the
  spool; the result keeps its {id, ok, why} shape). A press from Home Assistant logs the same words and changes
  nothing.
- F#149: Re-arm does what the clock card's "Stuck. Press Re-arm." asks for (`rearm_answer`): idle or hunting with no
  check for the card's own limit (10 min hunting, otherwise 2.5 times the normal interval and at least 30 min), no
  check running and no budget hold, it runs a full check now ("a full check starts now"). Idle or hunting and checking
  normally, paused, waiting for settings, a check running or the budget holding the next check: ok false with why.
- F#92: in a stop, a step-aside or a back-off Re-arm keeps its login path, and only a stop wakes the loop for it, as
  1.6.2 documents. Its result's why says what happens ("logs in when the step-aside for your own FLICA login ends,
  HH:MM HST"; a back-off "at the next login try"; details FLICA refused, ok false: "save new ones on Settings"). New in
  the main loop: while stepped aside, a Re-arm waits for the step-aside's end, so another command waking the loop no
  longer cuts the 30 min short (in 1.7.0 it did).
- What the pilot reads of these answers: HOM 1.8 shows the why of a refused command ("Not applied: Re-arm. The Watcher
  said: ..."), but for a taken one only "Sent: the Watcher took Re-arm.", so the why of a Re-arm that acts ("a full
  check starts now", "logs in when the step-aside ... ends") reaches him once HOM shows a taken result's why too. That
  is a HOM change, not a contract change: results already carry {id, ok, why}.
- F#7, F#110: the export's full sweep (every 300 s) writes state.json even when nothing changed: the same payload in
  a new signed envelope (atomic, about 44 KB), so its seq moves at least every 5 min in every state, needs_settings
  included, and the portal can tell a Watcher that is up from one that stopped. No new field. Passes that are not
  full still skip unchanged text.
- F#75: the admin forwards each recall list it takes to every pilot's Watcher itself (`recall_forward`:
  `<prefix>/recall/set`, qos 1, not retained, never its 'me'; the pilots by run.py's own rules on the add-on options).
  A pilot forwards nothing. A day that comes again unchanged keeps the time it first came in (the card's "received")
  and is no new list, and drafts are keyed by row, so the second copy (Ryan's HA automation still forwards too)
  changes and pushes nothing; a changed list is news again.
- F#102: a pilot who saved only his CrewTrac details gets the charter watch while his FLICA watch waits for its login
  (`start_charter_watch`, before the needs_settings wait: CrewTrac is its own site and login), so his Scan CrewTrac now
  has a reader. (Superseded the same release by F#22 below: a pilot's charters status still goes out before that wait,
  but his Watcher no longer scans.)
- The recall history replay (Ryan's yes, Nov 11): the admin's Watcher held recall lists from Oct 30 that a pilot's
  Watcher never got (James's started Nov 10). Once per pilot (DB `recall_replay_done`, keyed by his prefix, so a pilot
  added later gets his own), from the uploads janitor's minute on the admin only, 2 min after its start
  (`RECALL_REPLAY_DELAY_S`, the pilots' Watchers have subscribed by then) and while MQTT is up, the admin sends every
  recall day it stores through F#75's `recall_forward` (date, file, rows and the time it first came in; never its
  `me`, verdicts or CCR drafts), each marked `"replay": true`, to that pilot's `<prefix>/recall/set`; one log line
  (`recall_replay_tick`). The pilot (`recall_cmd`) takes a replayed day only when he holds no list for that date (a day
  he holds is never touched, so a replay twice changes nothing), keeps the admin's received time and the mark, judges
  it against his own line and shows it on his Recall/O75 tab with its CCR draft, but raises no alert or push for it:
  no `event/recall_miss` now or on any later evaluation, and the RECALL ALERT count (sensor `alert`, the alert bar)
  leaves replayed days out. One log line ("recall history from the admin: N days taken, M already held"). The mark
  means nothing on the admin (its lists come from Hark) and is never forwarded live.
  Review fix: every Watcher's MQTT session is clean and the replay is not retained, so one published while the
  pilot's Watcher was down (a Settings save restarts it, a crash, a broker reconnect) was dropped by the broker with
  no error and still marked done for good. The admin now subscribes to each pilot's own availability,
  `<prefix>/status` (retained: "online" from his connect, "offline" from the broker's will when his connection ends),
  outside `roles.subscriptions` (no command; the role lists and the portal contract are unchanged; `pilot_status_subs`,
  `pilot_status_in`, the payload only compared with "online"). It sends a pilot's replay only once his Watcher has read
  online for 30 s (`RECALL_REPLAY_SETTLE_S`; his subscriptions follow his "online") and marks it done only once he
  stayed online 2 min after the send (`RECALL_REPLAY_CONFIRM_S`); if he went offline or restarted in that time, it goes
  again when he is back (a replay twice changes nothing on him). The admin's own reconnect starts the counts again.
  Log lines: "waits until its Watcher is online" (once a pilot), "sent to ...", "restarted after the send; sending it
  again", and "replayed once to ..." when done.
- F#22, shared charters (Ryan, Nov 11): a pilot's Watcher runs no CrewTrac scan and makes no CrewTrac login at all
  (`charter_scan`, `_charter_scan`, `charter_press`, `crewtrac_lift` do nothing on a pilot; `start_charter_watch`
  publishes his status and starts no charter thread). The admin, after each scan that read CrewTrac and once at start,
  publishes the flight list its Charters card shows, retained, qos 1, on `flight_watcher/charters/shared`
  (`charters_share`: {v, at, items}, each flight's key, date, flight, route, scheduled, eqpt, tail, why, first_seen
  and gone; never CrewTrac's other columns, the admin's CrewTrac login state or status, his own schedule or fit), only
  while the add-on runs a pilot and after a first scan. Every pilot subscribes to it (under the admin's prefix, which
  his portal can never publish on) and publishes `sensor.<prefix>_charters` from it (`charters_shared_in`, the payload
  read as data: a JSON object, each flight cut to those fields, at most 200): `source` "admin", `last_scan` the admin's
  scan time, `status` "from the admin's scan at HH:MM HST" (the date too when not today), `crewtrac.state`
  "not_used". A flight new to him (not gone, not seen, nor found by his own scans before 1.7.1) still fires his
  `event/charter` once, his portal's charter alert; the first list on an instance that never had one is taken
  quietly. A Scan CrewTrac now on a pilot does nothing (logged); from his portal it answers ok false: "ignored:
  charters come from the admin's CrewTrac scan; this Watcher does not log in to CrewTrac" (`press_answer`). What
  else a pilot's CrewTrac login was for: nothing (it is read only by the charter watch), so a saved one stays unused
  and harmless; Remove CrewTrac login (F#155) still clears it, and saving the same one again no longer says
  "CrewTrac gets one more try".
- F#10, health line: `sensor.<prefix>_flica_fetches` (exported to a pilot's portal already) gains `hour` (this
  Watcher's FLICA loads in the hour up to `at`, the host gate's own count) and `budget` (100 on a pilot, null on the
  admin): plain numbers of his own instance (`fetches_payload`). On a pilot the uploads janitor's minute sends it again
  when that count changed (loads age out of the hour while nothing loads; `fetches_tick`), never when it is the same.
- FW-0042 part 2 (Ryan's rule, relayed by Hark on the HOM bus Nov 9; branch fw171-cap): no monthly credit cap. The
  90 h cap was Hark's error, not Ryan's rule (the PWA does not cap voluntary adds): a `cap_credit` still in smart.json
  (Pako's has one) is read and ignored, logged once per change of the file, and no find reads `Over cap` or `Cap ?`
  any more (in 1.7.0 every line-month find did). In its place Ryan's rolling block check: the pilot's block (flight)
  time, never credit, in the 672 h ending at the pickup's last release, flown + scheduled + the pickup
  (`smart.block_672` on the FAR column's own trips, `watcher.far_trips`, summed by `far.flight_time_to_release` with
  the FAR 117.23(b)(1) machinery, whose window sum `_cum` now shares), against the company's 98 h buffer
  (`smart.BUFFER_672_H`, one constant apart from FAR's 100 h, `far.FT_672`): `Fits 672 (97:59)` at or under 98:00,
  `Over 98/672 (98:01)` above it, `672 ? (block not read)`, `(line not on file)` or `(times not read)` when a needed
  block, a day of the line or the pickup's own times are not on file (never guessed; blocks on file already over 98:00
  stay Over), and `672 ? (78:01 to 98:01)` when only a trip across the window's start decides it (a Fits counts that
  trip's block up to its overlap). The tag sits in `month_rule` where `Over cap` was, for a line or a reserve month
  (a Fits alone reads `OK, Fits 672 (97:59)`; `RULE_MAX` 80 keeps the rest part), and on the row as `b672` ('97:59')
  and `b672_ok` (true, false, '' unknown) in the finds DB and month files, `last_new` and `event/new_pairing`, not on
  the pot, Tradeboard or finds sensors (`SENSOR_DROP`). Only the window ending at the pickup's release is held to
  98 h; FAR's 100 h in every 672 h window stays the FAR column's. Nothing quiets, ranks or hides a find on
  `month_rule`: the HA automations (in git, and on Pako as read Nov 11) read VAC, blocked days, fit and far only (the
  new-pairing push's message text shows the tag, below under Home Assistant), the finds card shows `month_rule` on
  hover only, there is no value score, and the portal's priority reads fit and far. A quiet rule built on the 1.4.13
  template must not count `Fits 672` or `Over 98/672` as a fail (Ryan decides).
  Tests: `tests/test_fw171_b672.py`; `test_smart.py`'s cap tests now check the cap is gone.
- FW-0042 part 2 review: a find stored before 1.7.1 that has left the pot (never screened again) drops `Over cap`
  and `Cap ?` from its `month_rule` in the finds DB rows, month files and card hover (`store.find_month_rule`;
  blank when nothing else is left, as the 672 h check never ran on it; Pako had 17 in November's file), and the
  672 h most-it-can-be counts a block on file longer than its own span (a page's slip) in full next to a trip
  across the window's start, which had read `Fits` up to that slip's excess too low
  (`far.flight_time_to_release`; the FAR column's `_cum` is unchanged).
- Review: Tradeboard on a pilot: a detail load his FLICA budget left out (GateSkip) ended the whole Tradeboard read
  before its baseline was saved, so a new post already pushed on event/new_pairing was pushed again by the next read
  (his portal and ntfy), the next bid month was not read and the board was not published. With 1.7.1's Tradeboard
  share this was the usual path at the hunt floor. Now a detail left out only screens that post from its list (fit,
  vacation, FAR, the smart fields: `screen_row`) and is not cached, so a later read reads it; the read saves its
  baseline, reads every bid month and publishes. A detail load waits while it would leave no room for the frames and
  lists of the bid months still to read; a new post joins the baseline as soon as it is pushed (a read that ends
  later, Pause, never pushes it again); and its details are cached from the push, so a new post costs one detail load,
  not two (the admin's too). One log line a check says the details were left out.
- Review: F#155: Remove CrewTrac login also drops the login from a pilot's options in memory, which hold creds.json's
  values from the start: the state published with "saved: CrewTrac login removed" still showed the old user ID,
  "CrewTrac password: set" and the Remove button, and the charter watch could use the login until the restart. The
  admin's options (the add-on's own) stay.
- Review: Scan CrewTrac now from the portal: a press that starts no scan (one running, no CrewTrac details or ones
  CrewTrac refused, the login form came back last time, or the last pressed scan under 30 min ago) answers ok false
  with the reason ("ignored: the last pressed scan was under 30 min ago") and is not republished, like Check now
  (`charter_press_refusal` in `press_answer`; the result keeps its {id, ok, why} shape). A press from Home Assistant
  is unchanged. Merged with F#22: a pilot's Watcher never scans, so his portal's press always answers "ignored:
  charters come from the admin's CrewTrac scan; this Watcher does not log in to CrewTrac" (a CrewTrac login saved or
  not); these reasons are what the admin's `press_answer` gives.
- FAR column, 672 h flight time (the same gap the FW-0042 part 2 review found in `far.flight_time_to_release`):
  `far._cum`'s most-it-can-be counted a block on file longer than its own span (a page's slip, H9006's 10:00 in an
  8 h day) only up to its span, so next to a trip across the window's start a 10:01 pickup read "flight time at most
  98:01 of 100 h" (OK) when the most it can be is 100:01, which is "may pass 100 h" (?). `far._in_window` now counts a
  block surely in the window in full in the worst too, so the worst is never under the sure sum; the rest still count
  up to their overlap. Only such a slip changes a result (a block no longer than its span counted in full already);
  FDP and every other check are unchanged, and `flight_time_to_release` uses the same bound (FAR 117.23(b)(1)).

### The cards

- F#155: Remove CrewTrac login on the settings card. While a pilot's CrewTrac login is saved the card shows "Remove
  CrewTrac login" and, after a confirm, sends the sealed `{"ctweb_off": true}` on `settings/set` (sealed only, like
  Turn off phone alerts: on a page without the Watcher's key it sends nothing and says why; never offered on the
  admin's own instance, whose logins may be the add-on's options). The Watcher (`settings_cmd`) takes it sealed only:
  it removes ctweb_username and ctweb_password from his creds.json, resets the CrewTrac record, ignores CrewTrac fields
  sent with it and restarts like any save ("saved: CrewTrac login removed", in green; "nothing new: no CrewTrac login
  is saved" when there is none, shown as "No change: no CrewTrac login is saved"). His FLICA login stays.
- F#77: a Recall/O75 Refresh answer that comes after the recall card's 15 s note clears "No answer from the Watcher
  yet" (the card keeps the old checked time and clears the note when checked or last_updated moves). The Watcher side
  was right already: a Refresh from the portal is taken and answered with a new `checked` time.
- F#66: the pilot portal's Watcher tab starts with the recall card in alert mode (`portal_layout.json`), the RECALL
  ALERT bar of the admin's main view. It takes no room while no MISSED recall has an open CCR draft, and its "Review
  and file CCR on Recall/O75" button opens the Recall/O75 tab (`/flight-watcher-<name>/recall`, which the portal maps).
- F#107: swap ideas on the pot card (the portal's Watcher tab), from `sensor.<prefix>_swap_ideas` and
  `sensor.<prefix>_would_trade`, with the columns of the admin's table (Give up, For, Dates, Layover, Days, Credit,
  Soft, Gain, Src, Grid) and its key in portal wording; under 560 px each idea folds into labeled lines. An alert for a
  new idea is not in this release: it needs a portal event, which is a contract change.
- F#4: the clock card keeps an interval the pilot picks until the Watcher's state shows it (or 20 s, or the portal
  settles the command without it), instead of jumping back on the next 1 s tick; its focus guard looks in the card's
  shadow root. With the portal's pending marks (`hass.fwPending`) Check now, Hunt, Pause and Re-arm read "Sending..."
  and take no second tap, and an interval waits for its command.
- F#32: the schedule card reports a month's Improved-Pay-Gross (`improved/set`) only once the pairings package is in or
  known to be missing (a 404 now redraws too), so no load sends a first, too low figure.
- F#43: the pilot lookup is a form (Go is its submit): a phone keyboard's Go or Search key asks after the keyboard
  commits what it was composing; `enterkeyhint="search"`, autocomplete off, 16 px text (no iOS zoom), the 2 s
  same-name guard kept. On a pilot's card the placeholder is "Last name or employee #", with a line above ("Look up a
  pilot's month (asks FLICA)") and one under it saying what a name finds. The admin's card keeps its placeholder.
- F#52: the pickers card's box is labeled "Filter this list (it does not ask FLICA)". On a card 500 px wide or less (a
  container query; the desktop table is unchanged) it shows Pilot, Pos, Best and Avg, with the employee number, the
  pickup counts and the layovers on a small line under the name: the speeds show at 390 px with no sideways scroll.
- F#93: each secret field on the settings card has a Show / Hide button and `autocomplete="off"` (no "new-password");
  a password goes exactly as typed whether shown or not, and the fields empty and hide again after a send. The
  Watcher's "nothing new" reads "No change: ..." in the text color, not as a green save.
- F#96: a pilot's card copy says "the admin" ("The admin" at a sentence's start) where the admin's name was, so the
  comments in the source a pilot can view stay whole (`cards.scrub_names`).
- Recall history replay: the recall card leaves a replayed day (`replay`) out of the RECALL ALERT bar (alert mode
  and tab), marks it "list ok, history" and says on it: "From the admin's recall history (a list your Watcher did not
  get when it came in): checked against your line, with no alert or push."
- F#22: the charters card on a pilot (`source` "admin") says "From the admin's CrewTrac scan at Nov 10 14:05 HST." (or
  that it waits for one), has no Scan CrewTrac now button, and says his Watcher never logs in to CrewTrac; the admin's
  card is as before. Review fix: the admin shares only after a scan that read CrewTrac, so when its scans stop (its
  CrewTrac login refused or removed) the pilot's list stayed as it was with no warning. Over 13 h after the admin's
  scan (two 6 h scans and their jitter missed) the status turns to a warning: "The admin's last CrewTrac scan was Nov
  9 12:00 HST, over 13 h ago. Charters added or cancelled since then are not shown until it scans again." The card's
  signature carries that state, so the same sensor turns it on as time passes. A flight gone from the schedule is
  struck through at full color (it was faded to 60 %, under AA contrast). The settings card, when the Watcher says it
  makes no CrewTrac login (`crewtrac.state` "not_used"), has no CrewTrac fields and says "Not needed: your charters
  come from the admin's CrewTrac scan, and your Watcher never logs in to CrewTrac."; a CrewTrac login still saved
  keeps its Remove CrewTrac login button. The portal's Watcher tab help says the same instead of the Scan CrewTrac now
  line (`portal_layout.json`).
- F#10: the settings card's last line is the Watcher's health, "Watcher 1.7.1: hunting. FLICA pages in the last hour:
  37 of 100." (version and state from `sensor.<prefix>_state`, the count and budget from the fetches sensor; a count
  older than 2 min says when it was counted, one over an hour old reads 0), on the portal's Settings tab and Ryan's.
- The tickets card's page list on Ryan's dashboard offers Working Flight instead of Aviation Wx (he removed that view).
- F#119: status text on the clock, settings, schedule, pot and recall cards uses the cards' own color variables, a
  lighter tone on dark cards (Home Assistant's dark mode, `hass.themes.darkMode`, which the portal sets from the
  device; the phone's own setting only when that is not given (review r4: a profile forced to Light on a phone in dark
  mode had the light-on-dark reds at 2.01:1); the schedule card's old dark overrides never applied), so text keeps WCAG
  AA contrast (4.5:1) on the portal's light and dark cards. Also for AA: the Hunt
  button and the CHECK chip a darker orange behind white, the NO chip darker gray, the reserve grid tint a little
  lighter on light cards, a trip marked "would trade" in the text color on its orange mark, the faint marks in the
  secondary text color, the settings notes in the secondary text color instead of a fade, the pickers' sorted header
  in the text color. These show on Ryan's HA dashboard as well; his light-theme status colors are unchanged except
  warn text (#8a5300). The portal's own primary buttons in dark mode (white on #3a9be0, 3.02:1) are HOM's palette.
- Review: The cards on a phone (700 px or less): every field and select of the settings, pickers, clock, schedule (Pay
  settings) and recall cards is 16 px, so iOS Safari no longer zooms into a tapped field and leaves the page wider
  than the screen (the pilot lookup has been 16 px since F#43). Desktop sizes are unchanged. Review r4: the tickets
  card's fields (13 px since 1.7.0) and its paste box (12 px) too.
- Review r4, the cards on Home Assistant's own light theme (2026.11, primary #009ac7; F#119 was checked on the portal's
  palette): a SHOULD HAVE BEEN YOU row's reasons (3.98:1) and the recall card's month arrows (3.26:1), the clock
  card's Last, Next and interval labels in the red Stuck state (4.07:1, 3.89:1) and its Check now (3.26:1) are the
  primary text color; the recall card's buttons are 44 px tall on a phone (27 px). The pot card's fold-outs (Swap
  ideas key, Key) are 44 px taps (32 px), and a folded swap idea's Grid line reads "red 11-21", not "grid red 11-21".
- Review r4, privacy (F#96): a pilot's card copy names the admin in no letter case (the tickets card's Claude prompt
  kept "reporter is not ryan", in the portal bundle) and says "the admin's Home Assistant" for his house's ("Pako HI").

### Bid calendar alerts (FW-0070, Ryan)

- `bidcal.py` (new; the Dockerfile copies it). `bidcal.parse` reads a pairing package's Bid Calendar from page 1 of
  its text copy (the left column of the two-column cover page, so the reserve and credit tables after a date never
  count): Pairing Package Published, Practice Run #1 and #2, CA & FO Bids Close with its 0800HST, All Monthly Awards
  Posted (no later than 1700HST on) and Flica Open Time Window Opens (1200HST on), dated from the page's "<Month>
  <YYYY> Pairing Package" heading (a January package's dates are December of the year before); anything not found is
  None. Read right on the October, November and December 2026 packages on Pako (read only).
- `bidcal.schedule` makes each cycle's alerts, all HST: 08:00 the day before the package publishes ("adjust your
  vacation if needed"; `PUBLISH_ALERT = (1, "08:00")`, one constant: the packages publish on the 4th, so this is the
  morning of the 3rd, Ryan's answer of Nov 11; built first as 20:00 that evening), 20:00 the night before each
  practice run, 24 h before the close and 20:00 the night before it.
  The cycle for bid month M+1 runs in month M; without that month's package (it cannot be on file before it
  publishes) the usual days apply: published the 4th, practice runs the 7th and the 10th, close the 11th 08:00. A date
  the package gives replaces its default; a date outside the 62 days before the bid month is never used. Each alert
  says which (`source` package or default; a usual date also says so in its text).
- The Watcher (`bidcal_tick`): the uploads janitor checks once a minute, first and on its own (an uploads error never
  skips it), whatever the state (paused, stepped aside, hunting, waiting for settings); no FLICA load, and page 1 of
  the shared package is read only when its file changes. Each due alert goes once on `<prefix>/event/bid_calendar`
  (not retained: kind, key, bid_month, title, message, at_hst, event_hst, source); the sent and dropped keys are in
  the DB (`bid_calendar_done`) before the publish, so a restart never repeats one. A due alert waits while MQTT is
  down; one late (the app was off) is still sent, worded from the time it goes out ("Bids close in 22 h"), until its
  words stop being true (the publish alert and the evening ones until their day starts, the 24 h one until the
  night-before one, that one until the close), else it is dropped with a log line.
- `sensor.<prefix>_bid_calendar` (new, core, every instance; a timestamp sensor, retained on `<prefix>/bid_calendar`):
  the next alert's time (HST), and as attributes that alert, its cycle's dates (awards and open time from a package),
  source and sources, and each of the cycle's alerts with its status (pending, sent, dropped). Published when it
  changes. "bid" joins `roles.RESERVED` (a pilot name may not start with it) and `bid_calendar` `roles.EVENTS` (core).
- Phone push, Ryan only: the new HA automation "Flight Watcher bid calendar" (`ha/automations_flight_watcher.yaml`,
  pending on Pako: `ha/README.md`), triggered by `flight_watcher/event/bid_calendar` only, a critical push to Ryan's
  two iPhones exactly like "Flight Watcher charter", title and message from the payload. The push guard passes.
- A pilot's Watcher makes the same alerts on its own prefix, which no automation reads; they are not portal events
  (that is a contract change, not in this release). His `sensor.<prefix>_bid_calendar` is in his portal's state.json
  like any core entity (PORTAL_CONTRACT.md 4.1 and 4.2: a new entity needs no HOM release).
- Review: an alert's record keeps the event it was for (`bid_calendar_done`: how, at, event; `bidcal.is_done`).
  A date the package moves after its usual-date alert went out (a package uploaded late, as December's was on Nov 7;
  October's Practice Run #1 was on the 8th, not the 7th) is alerted once more at its own time under the same key (the
  phone's push of the same tag replaces the wrong one), and the sensor shows it pending until then, not sent. An
  unchanged date is never sent twice. The same for a close the package moves (its 24 h and night-before alerts).
- Review: a usual date in a package that is on file but does not show that date says "Usual date: not found in
  the pairing package." instead of "the pairing package is not uploaded yet" (each alert carries its cycle's source,
  `cycle_source`).
- Review: `sensor.<prefix>_bid_calendar` is not published (nor kept as sent) while MQTT is down, and a
  reconnect sends it again at the next minute, so a broker restart across an alert's deadline no longer leaves the
  sensor on the dropped alert's past time, pending.

### Paste a screenshot into a ticket (FW-0071, Ryan)

- Ryan could not paste a screenshot into a new ticket in Chrome on his Mac, nor on iOS, though the form said "paste a
  screenshot (Cmd+V)". The 1.7.0 card listened for the paste on the document only. A real Cmd+V in a field does reach
  it in Chromium here (the paste event is composed), but nothing else does: a paste event a page or a wrapper makes is
  not composed and stops at the card's shadow root, Safari and the Home Assistant app fire no paste unless a text
  field has focus, and in a plain text box iOS does not reliably offer Paste for a picture. So the paste depended on
  the cursor being in a text box, in Chrome (not reproduced on a Mac here: Chromium on Linux takes a real Ctrl+V in a
  field or on the page). The card now hears it in every way: its shadow root listens too
  (title, text boxes, the form itself, which takes focus when its background is clicked), a paste box (an editable
  area that keeps nothing: click it and press Cmd+V; on iPhone or iPad touch and hold it, then Paste, which iOS offers
  there for a picture), a picture dropped on the form (the Mac's screenshot preview; the browser no longer opens it in
  place of the dashboard), and a Paste photo button that reads the clipboard with `navigator.clipboard.read()` inside
  the tap (Safari asks then; a refusal or a clipboard with no picture says so in plain words; no button where the API
  is missing, such as plain http). Each paste is taken once (the shadow root and the document both hear a composed
  one). Every way goes through the same shrink, checks and photo limit as Add photos; in the portal copy that is
  FileReader into a data: URL, never a blob: URL, so its CSP is unchanged.
- Review r3: the hint says "Cmd+V in any box of this form, or in the paste box below" (it said "anywhere in this
  form", which Safari and the Home Assistant app do not do), and Add photos, Paste photo and Remove all are 44 px tall
  taps (Paste photo was 27 px; the round remove x on a thumbnail keeps its size).

### The layover page, van alerts and layover notes (FW-0072, Ryan)

- `www/flight-watcher-layover-card.js` (new, shipped by `cards.py` like the others; the admin's dashboard only: not in
  the portal's layout and not bundled for it, `PORTAL_CARDS_OUT`) replaces the Working Flight view's markdown card
  and its "Ready to update?" tile, the biggest thing on screen. At the top the flight, route and leg, and at the top
  right the van time in headline size (44 px) with the station's zone abbreviation, the HST time and a countdown that
  moves on its own ("in 2 h 10 min", orange from 30 min, red from 10); with no van the report time takes its place.
  Report, departure and arrival below, the van's place and its alerts' status, then a small "Update with Hark" chip
  (card option `update_url`) with FlightAware, Sig Wx and the release. On a layover: the hotel (address to its map,
  phone as a tel: link, Hark's notes), weather, open now, eat, things to do with Hark's photos as small lazy
  thumbnails (https only, alt text), transport. Release, MEL, NOTAM and GIN fold away under one status line. It reads
  Hark's sensor when it covers the Watcher's pairing (the markdown card's rule), else the Watcher's working flight,
  and Hark's only on the admin's instance (its state sensor's role).
- Van alerts (`layover.py`, new; the Dockerfile copies it; where the van time comes from: the last item below): the
  admin's Watcher reads `sensor.hark_working_flight` through the Supervisor API (at most once a minute), puts its van
  on the layover station's clock (`working.ZONES`, daylight time included) and sends `flight_watcher/event/van` 30 and
  10 min before it, once per pairing, van time and offset (DB `van_alerts_done`, written before the publish, so a
  restart never repeats one). A new van time arms both again; after a late start only the latest alert still before
  the van goes, worded with the minutes really left; at or after the van time nothing. The uploads janitor runs it
  every 10 s on its own, whatever the state (paused, stepped aside, hunting, waiting for settings), no FLICA load; a
  due alert waits while MQTT is down. A station with no zone, a van with no date and 24 h time, or a local time a
  daylight time change skips is no alert and one log line, never a guess (a time that happens twice is the first of
  the two: early, not late). BFI, IND, LAN and LNK (in Ryan's pairing and finds files on Pako, no zone before) join
  `working.ZONES`. `sensor.flight_watcher_layover_van` (new, admin only, a timestamp sensor): the van's instant, its
  abbreviation, HST and each alert's status for the card.
- HA automation "Flight Watcher van time" (`ha/automations_flight_watcher.yaml`, pending on Pako: `ha/README.md`):
  triggered by `flight_watcher/event/van` only, a critical push to Ryan's two iPhones exactly like "Flight Watcher
  charter": "Van in 30 min: 19:40 AEDT (22:40 HST), <place>". The push guard passes.
- Layover notes: "My notes for <CITY>" on the card (the layover station; any 3-letter code can be typed) sends
  `flight_watcher/layover/note` {city, text, rid}; the admin's Watcher stores it in
  `/share/flight_watcher/layovers/<CITY>.json` (folder 0700, files 0600; plain text, at most 1000 characters and 200
  notes a city; never in git, never in a portal export) and answers on `sensor.flight_watcher_layover_notes` (new,
  admin only: by city the guide and the newest notes, the current station first, within 12000 bytes). A note is
  deleted after a second tap. "Tidy with AI" files a feature ticket "Tidy the <CITY> layover notes" through the
  existing ticket path (reporter ryan); Claude writes `<CITY>.guide.md` in the ticket flow (HANDOFF.md, "Layover
  notes"), which the card shows above the notes, its markdown escaped first (headings, lists, bold, italics, https
  links; nothing else becomes markup). The Watcher never logs a note's text.
- Roles: `layover/note` (feature `one_writer`) and the event `van` (`admin_pushes`) are the admin's; the two sensors
  are admin only (`ENTITY_FEATURE`); "layover" and "layovers" join `RESERVED` (a pilot named "layovers" would share
  the notes folder). A portal refuses `layover/note` as "anything else" (`roles.NOT_ON_PORTAL`): PORTAL_CMDS,
  PORTAL_REFUSED, FEATURES and the fixture are unchanged.
- Dashboard (`ha/dashboard_flight_watcher.json`, pending on Pako: `ha/README.md`): the `flight` view's two cards become
  the one layover card, its `update_url` the button's Hark link (redacted here).
- Review r3, van alerts: a date-first van with AM or PM, seconds or a zone after its time ("2026-11-12 7:40 PM",
  "2026-11-12T08:40:00Z") was read as the station's 24 h time, so the 30 min push could go 12 h early and the real van
  get none; it is now no alert and one log line. So is a van whose weekday is not its date's ("12:05 AM (00:05) Fri
  2026-11-12", a Thursday: both alerts about 24 h early), in each of the three forms ("Thu", "Thurs", "Thursday"
  match; a word that is no weekday is ignored). Hark's state ("van 2026-11-12 19:40") stands in only when the van text
  has no date at all, so it never re-reads the same doubtful date. The card reads the van with the same three patterns
  as the Watcher (it had no 12 h one, so a van Hark wrote that way got its alerts but no van on the card), falls back
  to the Watcher's own reading of it, and shows Hark's van text with "no van alert" when neither can place it.
- Review r3, layover notes: the folder is under /share, which the HOM app maps too, so it is opened without following
  a link and every file in it is read only when it is a plain file (never through a symlink, never waiting on a FIFO,
  size capped; `portal.read_plain`'s rules): a guide linked to `/data/options.json` no longer becomes the guide on the
  sensor, and a FIFO guide no longer hangs the janitor (van alerts) and the MQTT thread. A folder that is a symlink is
  refused, never chmod'ed or written through; notes are written with `*at` calls on the folder's fd. A notes file that
  is there but cannot be read (a hand edit that broke its JSON, `[]`) is no longer taken as empty and overwritten by
  the next note: the note is refused ("the SYD notes file could not be read: nothing changed"), the sensor leaves that
  city out (`unreadable`, named on the card) and still publishes the others (`[]` made it fail for every city). A lone
  surrogate in a note (`"\ud83d"` from a hand-made MQTT message) is stripped like a control character, and any error
  in a note command still answers, so the card never waits on "Saving..." for good. The janitor and the MQTT thread
  publish the notes sensor one at a time (a lock), so a payload built before a note was written is never the last one
  sent.
- Review r3, privacy: the card shows Hark's data only while `sensor.<prefix>_state` says role admin (it showed it
  unless the role was "pilot", so a pilot's copy with its state sensor missing or restarting showed Ryan's trip), and
  `sensor.flight_watcher_layover_van` keeps only what the card reads from it (not Hark's van text, the hotel, the zone
  name or the HST date; the push event still names the hotel and place). HANDOFF's "Tidy the <CITY> layover notes"
  steps are for a ticket reported by ryan only: the same title from a pilot is a third party's report.
- Review r3, the card on Home Assistant's own theme (2026.11: primary #009ac7, warning #ffa600, error #db4437): the
  countdown, "in 25 min" in orange (1.96:1), "in 8 min" in red (4.29:1), the release warning (1.96:1), the chips and
  links (3.26:1) and the armed Delete? (4.29:1) were under WCAG AA. Text on the card is now the theme's primary text
  color (links keep their underline), the urgent countdown and the armed delete are white on a fixed dark orange or
  red (AA in light and dark), and a refusal is a white on red line. Every button, input, fold-out and block link is
  44 px tall (the delete x 44 by 44; a chip stays 34 px to the eye with a 44 px tap area). A note's date is its HST
  date (its time is UTC: an evening note showed the next day) and the guide's tidied time says HST. With only the
  Watcher's working flight (no Hark), the release line is a plain line, not a fold-out with nothing in it.
- The van time's source (Ryan, Nov 11: "remember van times are published in the pairings pack monthly and can be
  updated from time to time"): the van alerts and the layover card now take the van, in this order: (a) the pairings
  package's VAN for that pairing's layover, (b) Hark's sensor for the same pairing, (c) nothing (no alert; the card
  says the van time is not known and why). (a) `layover.package_vans` reads the text copy every upload makes
  (`uploads/<YYYY-MM>_pairings.txt`): inside each pairing, after a duty that ends away from base, the hotel line
  ("<HOTEL>   <phone>   VAN HH:MM", calendar cells may follow), the next duty's report and its first leg; per pairing
  and layover it keeps the station, that leg's flight and local departure, the report, the VAN and the hotel's name
  (never the phone number). `layover.package_van` finds Ryan's layover in it (the pairing, else a FLICA-rebuilt
  copy's base id; the station; the next leg's flight and departure where known; only a package whose bid period holds
  the trip's first day) and puts the VAN on the station's clock on the day of that report (the day before for a
  report before midnight or a van before it). VAN 00:00 means none given, and so does a VAN more than 3 h before the
  report or after it: on Pako every hotel line of the October to December 2026 packages reads 00:00 except four
  "HOTEL TBA" charter lines reading 00:30 next to 21:10, 21:15, 23:45 and 05:48 reports, a ride time rather than a
  pickup, so today every van still comes from Hark. The Watcher (`van_source`, `van_packages`) re-reads a package only
  when its file changes (an upload or a revised package replaces it, so a revision's VAN is used from the next 10 s
  sweep; one log line a read) and finds the layover from Ryan's own schedule (`working.layover_leg`: his next leg out
  of a station he has landed at), else from Hark's layover. Hark's van is used only for the pairing on his schedule
  (Hark still on another trip is no van). A different VAN is a new van time, so it re-arms both alerts; the same VAN
  again re-arms nothing. `sensor.flight_watcher_layover_van` gains `source` (package or hark), and its `why` names
  Hark's reason and then the package's ("Hark's working flight is not in Home Assistant; the pairings package gives
  no van time for H3681 SYD (VAN 00:00)"). The card shows "from the pairings package" or "from Hark" under the van
  time, and on a layover with no van "Van time not known: not in the pairings package and not from Hark, so no van
  alert comes." with that reason.
- Review r4, van alerts: an alert's key is the pairing's base id, the van instant and the offset (`layover.key`). The
  Watcher takes FLICA's rebuilt H3681B on Ryan's schedule and Hark's H3681 as the same trip, and the leg's spelling
  changed when the layover leg came from the other one (Ryan's legs no longer read, or read between the 30 and 10 min
  marks), so the same van could push twice. After an MQTT (re)connect the van and notes sensors go again at the next
  sweep (`forget_layover_sigs`): one published while the broker was down was dropped (QoS 0) yet counted as sent, so a
  van Hark revised or a note added during a Mosquitto restart did not reach the card until it changed again.
- Review r4, the layover card: H3681B and H3681 are the same trip on the card too (`_same`: Hark's sensor, the
  package's van and the Watcher's van reading; it showed REPORT and "Van time not known ... so no van alert comes"
  and hid Hark's hotel while the alerts went), and it never says no van alert comes while the van sensor has a van. A
  long link or word wraps (a bare URL in the guide, Hark's lists or status widened a 390 px page to 775 px). When the
  package's van wins and Hark says another time, "Hark says 19:40" shows under the source. Report and Departs carry
  HST (Hark's from the Watcher's sensor on the same trip, station and local time; the Watcher's own "local" is the
  station's zone the van sensor read, "20:25 AEDT, 23:25 HST"). The note and City fields are 16 px on a phone, the
  source line no longer pushes the route onto two lines at 390 px, and the Layover pill is white on a fixed dark blue
  (7.4:1; Home Assistant's default blue was 3.26:1).

### Home Assistant (snapshots under `ha/`, pending on Pako: `ha/README.md`)

- FW-0042, show only: "Flight Watcher new pairing" (`ha/automations_flight_watcher.yaml`) ends its message with the
  commute result and the value from the event payload, each left out when blank: "Commute: KOA/ITO" (and "
  (<comm_why>)" when that is 60 characters or less) and "Value: 4617". Its trigger, conditions, targets, sound and
  title are unchanged: nothing is silenced and no one else is pushed. Pending on Pako (`ha/README.md`): Claude applies
  it through the HA connector with Ryan's [DESTRUCTIVE] yes. The push guard passes (21 automations with the bid
  calendar and van ones, 0 offenders).
- Ryan removed the Aviation Wx view (`wx`) from his dashboard `flight-watcher` on Nov 11.
  `ha/dashboard_flight_watcher.json` was refreshed from Pako (read only, redacted as `ha/README.md` says) and matched
  it by sha256 of the redacted text (3a5c1dbf...); the wx package, its sensors and helpers stay. CLAUDE.md's views
  list follows. With FW-0072's pending layover card on the `flight` view the snapshot is one edit ahead of Pako (its
  own sha256 78a4d55b..., both in `ha/README.md`).
- FW-0042 part 2, show only: "Flight Watcher new pairing" also ends its message with the find's 98 h in 672 h tag,
  after Commute and Value: the tag in its `month_rule` ("Fits 672 (97:59)", "Over 98/672 (98:01)", "672 ? (block not
  read)"), else one made from `b672` and `b672_ok` when `month_rule` has none (no month type set), left out when
  blank or unknown. It is text only: its trigger, conditions, targets, sound and title are unchanged, nothing is
  silenced, ranked or hidden on it, and no one else is pushed. Pending on Pako with the Commute and Value lines (one
  edit, after 1.7.1 is live: `ha/README.md`).
- "Flight Watcher van time" (FW-0072, pending on Pako) says in its description that the van comes from the pairings
  package's VAN when it gives one, else Hark's working flight; the push itself is unchanged. The temporary "Flight
  Watcher van time (temporary, FW-0072)" automation Claude made for tonight's Sydney van (Ryan's yes, Nov 11) is not
  part of this release: Claude deletes it after that van.

### Tests

- `tests/test_fw171_review.py` (the review fixes: a pilot's Tradeboard at the hunt floor with one load of the pool
  left, two new posts pushed once each across two reads; two bid months with none left, both read; the admin's one
  detail load per new post; a pilot's portal Scan CrewTrac now refused with F#22's reason, a login saved or not, and
  the admin's refusal reasons on `press_answer` itself). `tests/test_bidcal.py` (a date the
  package moves after its usual alert, in bidcal and in the Watcher across a restart; the usual-date words; the
  sensor while MQTT is down and after a reconnect). `test_fw171_core.py` and `test_fw171_crewtrac_remove.py` load the
  options after creds.json is written, as a start does; `test_fw171_cards.py` checks every field at 390 px for 16 px;
  the accepted portal samples test gives the demo pilot a CrewTrac login, and his press is still refused (F#22).
- `tests/test_tickets_paste.py` (FW-0071, Chromium, the HA and the portal copy): a PNG pasted (a DataTransfer in a
  paste event, not composed) into the title, a text box, the form and the paste box adds it through the same path,
  three at most in the portal and no blob: URL there; a composed paste counts once; a drop on the form; Paste photo
  with a stubbed `navigator.clipboard.read` (a picture, a refusal, text only, no API); a real Ctrl+V into the paste
  box; screenshots at 390 and 1100 px, light and dark. Each fails on the 1.7.0 card.
- `tests/test_layover.py` (FW-0072: van parsing, a DST zone (AEDT) and DST-free ones, the year and month edge, the
  skipped and repeated hours, unknown zones, due once, a late start, re-arm; the Watcher once across a restart, paused
  or stepped aside, MQTT down, one log line, a pilot never reads or sends, the janitor every sweep; notes 0600 in
  0700, refusals, plain text, the sensor cap, the portal never gets the card or the sensors; the HA push and the
  guard) and `tests/test_layover_card.py` (the card in Chromium: the van at the top right in headline size at 390 px,
  the countdown, the chip, the layover lists and links, the folded release, the fallbacks, the escaped guide, add,
  tidy and delete, screenshots at 390 and 1100 px, light and dark). Review r3: date-first vans with AM, PM or a zone,
  contradicting weekdays, the probe's 12 h early push, the van sensor's keys, a damaged notes file, a lone surrogate
  and any error answering, two threads publishing, a symlinked guide, notes file and folder and a FIFO guide; on the
  card WCAG AA from the rendered colors on Home Assistant 2026.11's theme at 130, 25 and 8 min with the armed delete
  and a refusal, 44 px taps at 390 px, HST note dates, a 12 h van and one only the Watcher read, a van neither can
  place, the card's van reading equal to `layover.parse_van` on 19 texts, a damaged file named, no state sensor; the
  tickets card's 44 px photo buttons and hint. Each fails on the r3 build before these fixes. `test_roles.py`,
  `test_instance.py`, `test_portal_contract.py` and `test_portal_spool.py` take the new sub, sensors and
  `NOT_ON_PORTAL`.
- `tests/test_pilot_secondary_share.py` (LIVE-1: the real check() for 3 h at the 5 s floor on a pilot with one and two
  bid months and a greedy optional read: each of the four reads in every hour, the pot on every check, no rolling hour
  over 100, checks at least the pace apart; the admin has no shares). The pacing tests in `test_freq_ranges.py` and
  `test_release_a_review.py` follow the new numbers (their fake request list and pairing pages are now pages the
  parsers know: those reads run now).
- `tests/test_fw171_core.py` (F#15, F#12, F#149, F#92 with the real main() woken every minute in a step-aside, F#75,
  F#102 with the real main() up to the settings wait, F#155, F#77); `test_portal_export.py` (F#7: a non-full pass
  writes nothing new, a full sweep the same payload with a later seq); the wake test in `test_release_a_flica.py` (a
  Check now while paused is ignored).
- `tests/test_fw171_cards.py` renders every changed card as the portal serves it (the pilot's copy, the portal's theme
  variables and ha-card) in Chromium at 390 and 1100 px, light and dark, computes the contrast of every visible text
  node from its rendered colors, and checks each card fix above; the pilot lookup's node test follows the form.
- `tests/test_fw171_crewtrac_remove.py` (F#155 across both halves): the card on the real Watcher's settings state and
  key, its sealed message into the real `settings_cmd`, and the Watcher's answer back on the card; without the key the
  card sends nothing and the Watcher ignores a plain `ctweb_off`.
- `tests/test_fw171_r2.py` (Ryan's Nov 11 decisions): the admin replays its recall history once to each pilot (the
  delay, the body: date, file, rows, the first time and the mark, never `me` or verdicts; once, and a pilot added
  later gets his own; a pilot replays nothing; review fix: sent only while the pilot's Watcher reads online, done only
  once it stayed online after the send, sent again after a restart in that time, the admin's reconnect counting again,
  a status payload read only as the exact word "online" and from this add-on's pilots only, a pilot reading none); the
  admin's real replay body into a pilot: older days taken, judged, drafted and shown with the admin's time, the held
  day untouched, no `event/recall_miss`, the alert count his own, a replay twice changes nothing, a later live list
  alerts for its own miss only; the admin ignores the mark and never forwards it; the recall card leaves a replayed
  day out of the bar; the admin shares only the card's flight fields, retained on its own prefix (none of its login,
  status, line or fit), after a scan and at start; a pilot's sensor from the shared list (source, time, not_used), the
  first list quiet, a new flight alerting once, malformed or extra data dropped, his own old scans counting as seen; a
  pilot makes no CrewTrac login (no thread, scan, press or retry; his subscriptions his own plus the shared list, the
  admin never reads it); a portal Scan CrewTrac now answers ok false with the reason; the charters card (review fix:
  the warning once the admin's scan is over 13 h old, in light and dark, and as time passes on the same sensor; the
  admin's own card never) and the settings card (no CrewTrac fields, Remove kept, the health line) in Chromium at 390
  px light and dark with AA contrast; the fetches sensor's `hour` and `budget` and the janitor's resend; the
  new-pairing message rendered with Jinja (the fields shown, blanks left out, a long why kept off) and its conditions
  and targets unchanged; the dashboard snapshot without the weather view at the sha `ha/README.md` records.
  `test_crewtrac_stop.py` runs its refusal, back-off and press rules on the admin's Settings-saved CrewTrac login
  (they ran on a pilot) and adds that a pilot never logs in; `test_doh_settings.py`, `test_fw171_core.py` (F#102),
  `test_portal_spool.py` (the accepted samples: Scan CrewTrac now answered ok false), `test_roles.py` (a pilot's
  subscriptions), `test_release_a_cards.py` (the help text) and `test_release_c_card.py` (the page list) follow.
- `tests/test_bidcal.py` (parse on synthetic cover pages in the real layout, schedule, the publish alert at 08:00 the
  day before (late until the publish day, the package's date moving it), late and dropped alerts, once per key across
  a restart, MQTT down, the package's dates, the sensor, a pilot's prefix, the janitor, the
  Dockerfile, the HA push and the guard); the entity lists in `test_instance.py` and `test_portal_export.py` and the
  busy-month sensor sizes take the new sensor. `test_release_c_tickets.py` checks the version 1.7.1.
- `tests/test_van_package.py` (the van time's source, a synthetic package with a made-up hotel and phone number):
  the parser keeps each layover and never the phone number; 00:00 is no van time; the van on the station's clock
  before the report (and across midnight), found by station and flight or departure, not in another period's package,
  a rebuilt copy's base id; a VAN that is no pickup before the report (00:30 by a 21:10 report, as on Pako) is none;
  `working.layover_leg` from Ryan's own legs; in the Watcher a non-zero VAN wins over Hark's (alerts at 19:25, not
  19:40, Hark's place words kept, source package), a revised package with another VAN re-arms both alerts and the same
  one again re-arms nothing, 00:00 or a ride time falls through to Hark, no van from either is no alert with both
  reasons, Hark for another pairing is not used, Hark's layover finds the package van without Ryan's legs, a misnamed
  package is not used. `test_layover_card.py`: "from the pairings package" and "from Hark" on the card, and "Van time
  not known" with the reason (none at home). `test_layover.py`'s van sensor keys gain `source`.
- `tests/test_fw171_r4.py` (review r4, the Watcher): one key for H3681B and H3681, the reviewer's probe (Ryan's legs
  gone after the 30 min alert, or read between the marks) sends each alert once; a van and a note changed while the
  broker drops what is published reach the sensors after the reconnect, then only on a change; a pilot's copies name
  neither the admin (any case) nor his Home Assistant. `tests/test_fw171_r4_cards.py` (the cards in Chromium): the
  rebuilt pairing on the layover card, no "no van alert" with a van, a bare URL at 390 px, "Hark says", 16 px fields,
  the one-line route, the pill on Home Assistant's blue (light and dark), HST on Report and Departs and the zone for
  "local", the pot card's 44 px fold-outs and Grid cell, the five cards' dark colors from `hass.themes.darkMode` (and
  the device's without it), the recall and clock cards at AA on Home Assistant's light theme with 44 px taps. Each
  fails before its fix (the 1100 px field size, unchanged, excepted). `test_tickets_paste.py` (16 px on a phone) and
  `test_fw171_cards.py` (the name scrub in any case, the Grid cell) follow.
- `tests/test_fw171_r2.py`: the new-pairing message with the 672 tag (from `month_rule`, from `b672` / `b672_ok`, the
  unknowns, other parts never taken for it). `test_fw171_b672.py`: the FAR column's 672 h worst counts a slipped
  block in full (fails before the fix: 98:01 "OK"), and is never under the sure sum in any window tried; its guard
  that nothing quiets on the tag now checks every automation's triggers, conditions and other variables (the
  new-pairing message text is the only reader).

## 1.7.0

Release C: tickets on the pilot portal (contract 1 revision 2; the Flight Watcher half, HOM 1.8.0 ships the same
fixture first). Council requirements of 2026-11-10 and the verified tickets design (D1 to D9, P1 to P15, TK-01 to
TK-15). Built, not deployed. Ryan's instance and his HA tickets card work as before (the one visible change there: the
Claude Code prompt now ends "except a pilot's ticket: leave it fixed for its reporter to verify", P1).

- Contract 1 revision 2 (`roles.py`, `portal.py`, `PORTAL_CONTRACT.md`, `tests/fixtures/portal_contract_v1.json`,
  same name; fwp and contract stay 1): the five ticket subs are allowed on a portal (21 allowed subs; refused stays
  email/alert, crew_scan/press, upload/chunk, drop/set, auto_swap/set, swap_map/press, hunt/state, pause/state), with
  their shapes as data (`roles.TICKET_CMDS`, read as `roles.TICKET_RULES`: keys a subset of keys plus required,
  lengths in code points, patterns as full matches, whole numbers, enums, le pairs, nonempty_when) that the spool
  checks with `portal.check_ticket` and HOM with one generic checkTicket; the fixture carries them with accepted and
  refused samples (worker actions, a note with no text, an inline photo, a reporter key, images 2.5 or true, a title
  one code point over 200 with an astral character, a data URL or a trailing newline in a chunk, the HA card's whole
  photo, an array payload). `revision: 2`, `commands.pilot_ticket_actions` (verify, reopen, note),
  `commands.pilot_ticket_limits`, the `tickets` file kind and tab, the `ticket_fixed` event (OWN_EVENTS) with fields
  `ticket` and `version`, and `samples.file_urls_refused` (the admin's tickets list, another pilot's folder).
  PORTAL_CONTRACT.md also drops two sentences 1.6.2 left behind: ntfy with a topic only is described (section 6) and
  the prefs come from prefs.json only (5.3: no seed from the HA helpers).
- Authority in the Watcher (`tickets.py`): with a pilot's name as allowed_reporter, `act` takes only verify, reopen
  and note (a note needs text), and another reporter's ticket answers "<id> not found" for act, edit and delete, the
  same as a missing id (no id probing; TK-08, TK-14). `fixed_moves` lists every move into fixed of one reporter's
  tickets (a fix later closed counts, a version correction or a note does not); `count_recent`, `open_count` and
  `quota_refusal` feed the quotas; `store_photo` stores checked bytes with a pilot's limits.
- Quotas, a pilot only (`roles.PILOT_TICKET_LIMITS`): 10 new tickets in 24 h (deleted ones count), 25 open, 3 photos a
  ticket (images capped, photo numbers 1 to 3, no inline photo), 1.5 MB of stored photos a ticket, one photo upload in
  flight. The admin has none.
- Photos (`photos.py`, new; Dockerfile copies it and installs Pillow 11.0.0): a pilot's ticket/image comes in the
  portal's chunk form {cid, i, n, part, parts, data} (at most 8 chunks of 60,000 base64 characters, each command under
  the 64 KB cap; its shape is checked again in the handler whatever sent it) or a dashboard card's whole form. The
  Assembler keeps one photo in flight: chunks in order, the same chunk twice counts once, out of order drops the
  photo, another ticket's photo while one is coming is refused, the same ticket's next photo replaces an unfinished
  one, 120 s without a chunk drops it; a photo the ticket cannot take is refused at its first chunk. The whole photo
  is decoded strictly (alphabet, padding at the end), must be a JPEG or PNG by its magic bytes and within the size
  cap, and is re-encoded by Pillow (no EXIF, GPS, comments or trailing bytes; at most 2048 px a side) before it is
  stored. Without Pillow a pilot's photo is refused. The admin's photos are stored as sent, as before.
- Answers: a pilot's `sensor.<prefix>_tickets` carries `answers` (the last 10, newest first: {ref, id, action, i, ok,
  error, at} for new, image, act, edit and delete, ref the card's cid or rid; TK-11) and `limits`; `last` keeps its
  FW-0049 meaning. The admin's sensor is unchanged (no answers, no limits).
- Fixed alert (D5, TK-04): on a portal pilot, `ticket_fixed_watch` (inside `publish_tickets`) turns each new move into
  fixed of his own tickets into one portal event per pass, `ticket_fixed` {ticket, version}: "Ticket FW-0071 fixed in
  1.7.0" (or "3 tickets fixed: ..."), view tickets, priority 2, white_check_mark, never a title or any ticket text; it
  goes to events.json and to ntfy (a topic-only push: the ids and the version, `ntfy.plain_text`). The moves already
  there at the first run (or after its file is lost) are seeded without an alert in `<data>/tickets_fixed_seen.json`
  {seeded, keys} (0600, written even when empty). A pilot can no longer mark a ticket fixed, so his instance never
  sends `event/ticket_fixed` itself.
- `publish_tickets` runs one caller at a time (`TICKETS_LOCK`) and, on a pilot, also from the uploads janitor every
  60 s, so his list and his alert follow the folder while he is paused, yielded or waiting for settings (TK-09; a
  folder rescan, no FLICA load; the admin keeps his check() rescan only).
- Portal export: the tickets card is in the bundle (PORTAL_CARDS_OUT is the uploads card and the row colors), its
  five `_pub(...)` subs are in `mqtt_subs` (`portal.card_subs`, TK-05), `sensor.<prefix>_tickets` is in state.json
  (his own tickets) and `files/tickets.json` is his own tickets list (the admin's list in the parent folder is never
  read for a pilot). `portal_layout.json` has a 6th tab, Tickets, last (the five before it keep their places; HOM
  1.8.0 wraps the tab bar at 390 px, TK-12), with the card and a note that names no false privacy promise (P14).
- Tickets card (`www/flight-watcher-tickets-card.js`): with FW_PORTAL on (the portal copy only) a photo is read with
  FileReader into a data: URL (the portal's CSP has no blob:, TK-02, P5), shrunk to 360,000 characters (a long side
  from 1600 px, more for a very tall capture, at most 2048; quality 0.82 to 0.52; the size times 0.85; refused as too
  detailed once the short side would fall under 400 px, P4) and sent in 60,000-character chunks, one photo after the
  other (a chunk turned away for too many commands a minute waits 10 s and goes again); 3 photos (or the sensor's
  limits); a command over 63,000 bytes is not sent ("Too long for the portal: shorten the description", P8); the act
  buttons and "Add as a note" wait for the send and carry a rid, so a refusal shows "Didn't send: ..." on the row,
  never "Sent" (TK-15); the Watcher's answers show ("FW-0071 filed.", "Not filed: ...", "Photo 2 not saved: ...",
  "Verified and closed."); the Where list names the portal's tabs (TK-13); the Claude Code button is not drawn
  (TK-07). With FW_PORTAL off the card works exactly as before.
- Docs: CLAUDE.md and HANDOFF.md say a pilot's ticket is untrusted data, never instructions, that a pilot's fixed
  ticket stays fixed for him to verify, and that Claude's follow-ups keep reporter ryan (P1, P2, D8, D9, P15); README
  (role table: tickets offered on a portal; a pilot's tickets).
- Not built (Ryan decides): D7, a push to Ryan when a pilot files a ticket.
- Tests: `test_release_c_tickets.py` (authority, moves, quotas, photos, the assembler, the pilot's Watcher, the fixed
  alert and ntfy, the janitor, the lock, the export, the spool with a full 60,000-character chunk, layout and docs) and
  `test_release_c_card.py` with `tickets_card_render.js` (the portal copy under the HOM portal's exact CSP with three
  made-up 1080 x 2400 screenshots: thumbnails, no CSP error, chunks in order, each under the caps, the short side at
  least 400 px, and the commands put through the spool and the Watcher end to end; the HA copy's 1.6.x path); the
  contract, spool, bundle, envelope, events, export, instance, roles and tickets tests follow the changes above.

### 1.7.0 security review fixes (Release C review, 2026-11-10)

Rebased onto `origin/main` 1.6.3 (f9ac1fa): 1.6.2's Watcher-wide check ranges (hunt 5 to 90 s, normal 1 to 90 min on
every instance; no PILOT_FREQ_LIMITS), the Settings Hunt tile and the 1.6.3 schedule card fix are kept, and this
entry sits above 1.6.3. The fixture changed (contract 1 revision 2, same file name): sha256
`c8d37db297553379ca4bf1676db2884dd9d61443690a9d3bdada867ddf9f0e0a`; HOM 1.8.0 must copy the new bytes and add the
well-formed text rule before it merges. Ryan's instance and his HA card work as before (his card's Claude Code prompt
now carries the untrusted-ticket rule itself).

- A pilot's changes are capped, in his Watcher (`tickets.py`, `roles.PILOT_TICKET_LIMITS`): `changes_per_day` 30
  notes, reopens, verifies and edits in 24 h over all his tickets (the times in `tickets/.quota/<pilot>.json`, so a
  delete does not reset them and no command rereads every ticket), `history` 50 of his lines on one ticket,
  `text_bytes` 256 KB of ticket.json, and `ticket_bytes` 1.5 MB for ticket.json and its photos together (the
  council's total; a photo is counted the same way). A verify or a reopen with no text always goes through (each
  follows a fix by whoever works the ticket). Refusals answer "ticket limit reached: ..." on his sensor. Before, one
  portal session could grow one ticket.json by about 108 MB an hour with notes or 322 MB an hour with edits on /share,
  each write under the folder lock both instances take. The admin has no caps. ticket.json is written as UTF-8
  (ensure_ascii off, read back as UTF-8), so an astral character costs 4 bytes, not a 12-byte escape.
  `count_recent` reads newest first and stops a day back, so a ticket/new no longer parses every ticket.json ever
  written (deleted ones included).
- Ticket text, whoever sends it (`tickets.py`; portal and fixture): text that is not well-formed Unicode is refused
  ("text is not valid Unicode": a lone surrogate passed both checkers, and Home Assistant's orjson refuses one, so a
  single pilot ticket froze the admin's tickets sensor and card); a one-line field (title, page, version) keeps no
  control character, line or paragraph separator or bidi control and no run of spaces; a text field (narrative,
  steps, expected, a note) keeps only line breaks and tabs. The contract says the same: every text field has a pattern
  (`roles.TICKET_LINE_PATTERN`, `TICKET_TEXT_PATTERN`, BMP escapes that Python and an unflagged JavaScript RegExp read
  alike) and a new rule in `ticket_rules` (well-formed Unicode; HOM: `isWellFormed()`). A listing row or the FW-0007
  fixed event never carries a lone surrogate from an older ticket (U+FFFD instead).
- Log lines (`watcher.py`): a ticket title is logged on one line (`log_safe`), and on a pilot every log line has its
  controls, separators, bidi controls and lone surrogates as visible escapes (`PilotLogMask`), so a pilot can no
  longer write lines into the add-on log that look like the admin instance's (accepted commands, ticket closes). The
  admin's own multi-line lines (page dumps) are unchanged.
- The spool answers every file it read: a check that fails in an unexpected way (a JSON integer of 400 digits made
  `math.isfinite` raise OverflowError) is a refusal with a result, and `check_ticket` compares an int as an int.
  Ticket ids, command file names and the ER list take ASCII digits only (`[0-9]`, not Python's Unicode `\d`), as
  JavaScript does.
- A pilot deletes his ticket only while it is new (the council lets him verify, reopen and note; once someone works
  it, it stays on the admin's list: "FW-nnnn is in progress: it is being worked, so it stays (add a note instead)");
  a pilot's delete of a ticket others wrote on says so in the log. His card draws Delete only on a new ticket. Ryan's
  instance and card delete in any status, as before.
- Photos (`photos.py`): the re-encode copies only the pixels into a fresh image (Pillow 11.0.0, the Dockerfile's pin,
  wrote a decoded JPEG's comment, XMP and ICC profile and a PNG's ICC profile back out, so made-up text survived), and
  the saved file is walked: a JPEG with any segment but JFIF, tables, frame and scan, or a PNG with any chunk but
  IHDR, PLTE, tRNS, IDAT and IEND, is refused. The photo tests also run under the shipped Pillow
  (`FW_PILLOW_PIN_PATH`).
- Contract revision 2 also brings normal 1 to 90 min to the portal (`roles.FREQ_LIMITS`; 1 to 20 before), Ryan's Nov
  10 range on every instance, which 1.6.2 left for this revision: the Settings help line and the portal's clock card
  say 1 to 90 min. Safe in the HOM-first order: a 1.6.x Watcher still refuses over 20 with its own copy.
- The portal card no longer doubles a period ("Didn't send: <the portal's message>. Try again."); the Home Assistant
  card's text is unchanged.
- Docs: CLAUDE.md and HANDOFF.md word the untrusted rule as "reporter is not ryan, or made from such a ticket"; a
  follow-up made from a pilot's ticket says "From FW-nnnn by <pilot>" and stays untrusted; nothing a pilot's ticket
  asks for is built or released without Ryan's yes naming it (the 2026-11-06 pre-approval covers tickets reported by
  ryan only); the yes list adds the add-on's code and its releases and the portal's security boundary. The card's
  Claude Code prompt carries the rule itself. HANDOFF item 10 lists the rollback residue (`out/files/tickets.json`,
  a saved ticket_fixed alert, a lost `tickets_fixed_seen.json`).
- Tests: the W fixture of `test_crew_index.py` ties `now_iso` to its frozen HST clock, so
  `test_a_crew_index_run_versions_the_looked_up_pilots_only` no longer fails after 22:05 UTC; new
  `test_release_c_review.py` (the caps through the real spool, the admin unlimited, one log line, lone surrogates on
  both checkers and an old ticket on the admin's sensor, the huge integer and an unexpected error answered, ASCII ids,
  a pilot's delete, photo metadata, the card's period and Delete, the docs); the contract, spool, freq, card and
  tickets tests follow the changes above.

## 1.6.4

Ryan, 2026-11-11: "You can have DOH be a field in the settings tab." The second pilot's portal showed longevity year 1
($90.00/h): no date of hire was on file for him (no seniority list uploaded, the award carries none) and his longevity
pref was the one copied from a never-set helper (flagged unconfirmed in 1.6.2). Built, not deployed.

- Settings card (`www/flight-watcher-settings-card.js`, the admin's HA card and a pilot's portal copy alike): a **Date
  of hire** field, a date input filled with the saved value, optional (blank keeps what is saved), with its longevity
  year beside it and the note "Your date of hire sets your longevity year for pay estimates (PWA 3.B.1); it stays on
  this Watcher only". The card checks it (YYYY-MM-DD, a real date, not after today HST, not before 1960; else nothing
  is sent, with the reason) and sends it like the other non-secret fields on `settings/set`: sealed when it can be,
  inside the sealed payload only in the portal (the portal relays ciphertext only, so no HOM change; the contract
  fixture, its pinned sha256 and `PORTAL_CONTRACT.md` are byte for byte as in 1.6.3). An unchanged date is not sent.
- Watcher (`settings_cmd`): checks the date again (`doh_refusal`); a bad one refuses the whole message, nothing saved,
  with the reason in the result line ("refused: date of hire: it is in the future; nothing was saved"; the value is
  never logged). A good one goes to the instance's own `<data>/cards.json` `doh` (`doh_save`: every other key kept,
  atomic, mode 0600), which `pilot_doh()` reads, so `sensor.<prefix>_state` attribute `doh` carries it;
  `sensor.<prefix>_settings` shows it too (attribute `doh`, on the admin's sensor as well). A date of hire alone
  restarts nothing: "saved: date of hire (no restart needed)" and the new state attributes go out at once (a portal
  pilot's export picks both up on its next pass). With a login change it is saved too and the restart is the login's.
- Longevity follows the DOH (PWA 3.B.1, 3.D.2; the PWA 3.D.6 table caps at 12): on the schedule card, the pot card's
  Value and the Watcher's pay figures (`pay_settings`: the Pay-Gross of decided requests and of trades seen on the
  schedule), a longevity year still flagged unconfirmed yields to the DOH's year; one the pilot chose himself (Pay
  settings, or Keep these) still wins. The rate line shows "DOH YYYY-MM-DD = year N", and the "Set your tax and
  longevity" banner and Keep these leave longevity out once a DOH is saved. The admin's figures are unchanged (his
  longevity helper when set, else his DOH from `/data/cards.json`; his helper is never flagged): his schedule and pot
  cards render byte for byte as in 1.6.3 across helper, DOH and tax combinations.
- Review fixes: (1) the Settings card's status beside the date says which year pay uses: "longevity year N" only when
  the date decides it, else "year N from this date; pay uses year M, set in Pay settings" (the admin's helper, or a
  year the pilot chose or kept, wins as on the schedule card). (2) A date of hire saved together with the same FLICA or
  CrewTrac details again still lifts their refusal block for one more try, as those details alone do ("saved: date of
  hire (no restart needed); FLICA gets one more login try with these details"); before, the date-only path returned
  first and the block stayed on with no word. (3) The portal copy no longer says the date "stays on this Watcher
  only": it is sealed on the way in but shown back on his page from the exported state, so the field note and the
  header say the portal can read that one (the admin's HA card keeps the 1.6.4 wording).
- Tests: `tests/test_doh_settings.py` (the field and what it sends, sealed only in the portal, in Chromium and Node;
  the Watcher's check, cards.json kept, no restart for a date alone, the longevity year from the DOH over an
  unconfirmed pref, a chosen year still winning, the admin's figures, the contract files unchanged). The admin's
  settings sensor key pin (`tests/test_portal_export.py`) gains `doh`. `tests/test_pilotver_watcher.py`: one test
  stamped its versions on the real clock and failed from 22:05 UTC on 2026-11-10 on; it now uses the fixture's clock.

## 1.6.3

- Schedule card: a trip whose own times are not read yet takes its credit from the pairings package, which writes it
  as "15h00". The card read only "15:00", so such a trip counted 0:00 and $0 in its row and in the month's Credit and
  Pay-Gross (seen live on the second pilot's first schedule read: Credit 0:00 and Pay-Gross $0 beside FLICA's
  150:28). The package credit is now read in either form. Both instances (the admin's card too, for a new trip).
  Test: `tests/test_schedule_card_package_credit.py` (fails without the fix).

## 1.6.2

Release A, group 1 (FLICA load and the schedule read; watcher.py core). Ryan's decisions of 2026-11-10: his own budget
stays about 376 FLICA loads an hour (FW-0035), the host cap is 480 an hour, a pilot's budget 100 an hour. His later
instruction the same day replaced a pilot's fastest hunt of 120 s: "The hunt floor should be 5 sec to 90 sec. And
normal should be 1 min to 90 min", on every instance (see "Check frequency ranges" at the end of this entry). Built,
not deployed.

- FLICA gate (`gate.py`, new; Dockerfile copies it): every Watcher in the container loads FLICA through one lock file,
  `/data/flica_gate.lock` (the admin's data folder, the parent of each pilot's; `FLIGHT_WATCHER_GATE` overrides). Each
  load (`Flica.fetch`, `render`, `menu_tree`, the login page and its submit, the pot discovery and each pot link it
  opens) waits until this Watcher's previous load is uniform(1.5, 3.5) s old, the host's previous load (any Watcher)
  1.5 s old, the host made fewer than 480 loads in the last hour and, on a pilot, he made fewer than 100 (a token comes
  back an hour after its load). A load is never skipped: it waits. A check starts only once 3 loads fit (the loop
  sleeps meanwhile, Pause and Check now still read), and a budget wait shows in the state note ("FLICA budget: 100 page
  loads in the last hour; the next one waits until 10:42 HST"). The lock is held only to read and write the small file,
  taken with a bounded non-blocking loop (about 10 s); when it cannot be had the load is paced by this Watcher alone
  (logged at most every 10 min). A Watcher that dies releases its lock; a broken file reads as empty and log times in
  the future are dropped. Every load is on the file's rolling-hour log (time, instance) and on the fetch counter.
  The per-site 1.0 to 2.0 s pauses (schedule tries, the lookup prompt) are 1.5 to 3.5 s now; the pot read after a
  schedule read (about 0 s before) is paced like every other load.
- Check frequency: hunt 5 to 90 s and normal 1 to 90 min on every instance (the 120 s pilot floor of the first build
  is gone; see "Check frequency ranges" below).
- Breakers (every instance): each FLICA read path (`gate.read_path`: schedule, schedule_detail, lookup, pairing,
  requests, tradeboard, menu, grid, other) stops for 6 h on a CAPTCHA or interstitial page, at once for 30 min on a page
  its parser does not know (the request list), and for 30 min after 3 failed reads in a row; each stop after the first
  with no good read between doubles, up to 6 h. A stopped path loads nothing (`Flica` refuses before the load); one
  log line, and the state note while idle or hunting ("FLICA requests read paused until 16:05 HST: a CAPTCHA page
  (never answered)"). Kept in the state, so a restart keeps a stop. The open time pot, the login and the pot discovery
  have no breaker: the pot watch keeps its own stop rules. Read paths in a check are guarded, so a stopped path ends
  only its read; while pairing pages are stopped no empty pot detail is cached, no pickup or in-flight try is used up and
  the crew index waits; a pilot lookup waits with a status line.
- `pot.classify` has a new kind, `captcha`: a reCAPTCHA challenge (grecaptcha.getResponse, the g-recaptcha box, "not a
  robot") or the api.js page that says it is going to forward (FLICA's scheduledetail forward page). It was "ok"
  before (only visible text was checked). The api.js script alone (the main menu and every pot page load it) stays "ok".
- Schedule read (`schedule_check`): at most 2 loads a read, pages already in use only: the shape of the URL that last
  worked (`S['sched_shape']`: the bid period number as {n}, filled from the month, 152 = November 2026, so a learned
  BCID=001.152 reads BCID=001.153 in December; an older literal `sched_url_ok` is turned into its shape once), else
  Tools > Schedule Lookup for the pilot's own number and the current month (`IF.CM_SCHED_MONTH`, `IF.parse_cm_month`,
  both safe_get guards, the page kept for other_months_check), else the mobile schedule's BlockDate page.
  scheduledetail.cgi and the BCID guesses are gone from the read, from the daily probe (removed) and from the previous
  month's read (`desktop_schedule` removed with its test). A page for another month than the current one is refused
  (the month rollover bug, both instances). The 1.6.1 back-off stays (10 min, 30 min); from the 3rd failed read in a row
  the breaker stops the read 30 min, then 60, 120... up to 6 h (`test_schedule_backoff` follows it). A month read on
  Schedule Lookup each time records trades seen between two reads, as the mobile page does.
- `sensor.<prefix>_schedule` is published after a failed read too, with the months on file and a new attribute
  `read_status` {ok, why, at, at_hst, next_try, next_hst, tries}: the reason in words (no URL, no employee number).
  The Schedule card shows "FLICA schedule not read: <reason> at HH:MM HST; next try HH:MM HST", and, while no FLICA
  month is read but the award file's line is on file, draws that line labeled "Awarded line from the award file.
  FLICA schedule not read yet." (no versions bar or Improved-Pay-Gross from it; "updated" shows only with a time).
- Schedule versions: a month whose first version is the PBS award (last month to two ahead) is published even with no
  FLICA read of it (`versions_months`): James's 11.001 was stored but never shown. The admin's months are unchanged.
- Commands: on a pilot only Check now (its 10 s gap), a hunt or pause switch that changes and Re-arm while stopped wake
  the loop into a FLICA check; a pilot lookup, a frequency change, Scan CrewTrac now or any other portal command no
  longer does (every one did). The admin keeps his wakes, except Scan CrewTrac now (no FLICA read) and a switch set to
  the value it has.
- Portal export: list files first, then the manifest when the file set changed, then state.json, so a state that names a
  new rev never points at a file not written yet.
- Tests: `test_flica_gate.py`, `test_release_a_flica.py`, `test_release_a_schedule_card.py`; `test_schedule_backoff`,
  `test_watcher_state`, `test_trades`, `test_requests`, `test_portal_spool` follow the changes above.

Release A, group 2 (a pilot's data paths). Ryan's decision of 2026-11-10: ntfy topic-only is allowed, with the
guardrails below. Built, not deployed.

- Page captures per instance (`captures.py`, new; Dockerfile copies it). The admin's are unchanged: his own pages, as
  read, in /share/flight_watcher/captures. A pilot takes none by default, and loads no FLICA page only to save it (the
  6-hourly pot capture's extra pages, the request view probe, the Schedule Lookup prompt probe), and never writes into
  the admin's folder (CrewTrac `ctweb_*`, `cmschedules_prompt` and inflt's `cmschedule_<emp>` used to land there:
  `IF.CAPTURE_DIR` and every capture site go through `cap_write`; inflt has a `WRITE` hook). Debug captures of a pilot
  run only while `/share/flight_watcher/<pilot>/captures_on` exists and is under 24 h old (the admin creates it by hand;
  one log line when they turn on or off): then session tokens, hidden form values, crew names (crewidx.crew_mask style),
  employee numbers and the pilot's own logins and name are masked in the page and the file name; the files go only to
  `/share/flight_watcher/<pilot>/captures` (the name checked with `roles.NAME_RE` and the reserved words, the path
  resolved and kept inside, no symlink followed, the folder 0700, each file 0600); files there older than 7 days are
  deleted (checked at most hourly, also while captures are off). A pilot's login screenshot (`last_login.png`) is
  never taken (a picture cannot be masked).
- ntfy topic-only (`ntfy.py`): the access token is optional. A topic must be at least 24 characters with both letters
  and digits (`ntfy.topic_refusal`); an unusable topic or token refuses the whole sealed save with the reason ("refused:
  ntfy topic: ...; nothing was saved"), never the value. A topic-only push carries only the kind, the pairing number,
  the date and the fit (`ntfy.plain_text`): no crew name, employee number, URL (no Click header), report time, rule id
  or ticket text. With a token the 1.6.0 push is unchanged. The manifest says `ntfy` true with a usable topic alone; a
  topic saved before 1.6.2 that is too easy to guess keeps ntfy off and the Settings card says so
  (`ntfy_topic_ok`, a boolean; the topic itself is never logged, never in settings/state, MQTT or state.json). Settings
  card: before a first topic it explains that anyone who learns the topic can read the alerts on ntfy.sh for about 12 h
  and asks for a tick; Generate (Rotate once one is saved) makes a 32-character random topic with
  `crypto.getRandomValues` (no modulo bias), shown once to subscribe to in the ntfy app and cleared after Save; a typed
  topic under the rule is refused on the card too; Turn off phone alerts forgets the topic and token (sealed
  `ntfy_off`). PORTAL_CONTRACT.md is unchanged (its section 6 still names the token; contract 1 needs no HOM change).
- Recall/O75 (PWA 22.G.2): the pilot's seniority number comes from the PBS award of the month (or the newest before it)
  by his own employee number, else the shared seniority list; a typed number wins (`recall_me`, `sen_source` on the
  sensor: typed, award YYYY-MM, seniority list). recall/act `me.sen` takes only an int 1..99999 (null forgets the typed
  one), `seat` only FO or CA; a list forwarded to a pilot never sets his `me`. No CCR draft and no recall_miss alert is
  made while his seniority or his line for the row's days is not on file: the row is CHECK with `missing` (seniority or
  line) and says so, and the card shows what is missing at the top. A draft not yet approved follows its row (rebuilt on
  each check: a number or a line that came in later is in it). The narrative never prints None, says "an FO", and a
  CHECK draft starts with what to check first. Card: the Hark hint only where Hark files (not on a pilot); day rows say
  "Flight Ops did not post a list for this day." or "The posted list was empty."; "came in ... HST"; the seniority box
  sends only a whole number 1 to 99999 (or blank), no seat, and is not redrawn while typed in.
- Pilot name lookup on a pilot instance: names only from the award and seniority files every instance already receives
  (`name_directory`; never the admin's crew index or contact list, nor his own crew directory); at least 3 letters of
  the last name, letters only (no wildcard), at most 5 matches with name and seat; each match carries an opaque pick id
  (`{"pick": id}` runs it) and the employee number shows only once a pilot is chosen; `#10001` is an employee number. A
  lookup while his Watcher is paused, yielded, in back-off, waiting for settings or stopped says it waits. No crew index
  coverage on a pilot (`reconstructed_coverage_pct` null: the "Crew index ... 0% of trips read" line is gone). Pilot
  card: the header names the pilot asked for (never the sensor's previous one), a reply with no month shows its status
  line with its time (HST), the loading line says when the Watcher reads it and, 2 minutes past that, gives the reason.
  The admin's lookup is unchanged.
- Prefs: a portal pilot's HA helpers (`input_*.flight_watcher_<pilot>_*`, James's were deleted) are never read: not by
  the pay line (`tax_pct`, `pay_settings`: a pref not set is the code default) and not at the start (the 1.6.0 seed from
  the helpers is gone; PORTAL_CONTRACT.md 5.3's seed sentence is left as is). Once (`prefs.json` checked), values that
  seed copied from never-set helpers (at their minimum: federal 0 %, state 0 %, longevity year 1, stamped at the seed)
  are flagged `unconfirmed`: kept, and the Schedule card says "Set your tax and longevity in Pay settings", opens Pay
  settings and offers Keep these; a pref/set clears the flag.
- Tests: `test_release_a_captures.py`, `test_release_a_ntfy.py`, `test_release_a_recall.py` (with
  `release_a_recall_render.js`), `test_release_a_lookup.py` (with `release_a_pilot_render.js`),
  `test_release_a_prefs_card.py`; `test_ntfy` (a 30-character test topic), `test_prefs` and `test_portal_export` (no
  seed from the helpers), `test_crewtrac_stop` (per-instance capture folder) follow the changes above.

Release A, group 3 (cards and layout, shipped by the Watcher). Built, not deployed.

- Portal layout (`portal_layout.json`, the same 5 tabs, contract unchanged): the Watcher tab has the working flight,
  the open time pot and Tradeboard pickups and the CrewTrac charters card; the Schedule tab has the FLICA requests,
  where the Request decided alert opens. Four new cards ship like the others (`www/`, copied per pilot by `cards.py`,
  bundled for the portal): `flight-watcher-pot-card.js` (a port of the HA pot_table macro: pot rows and Tradeboard
  pickups marked T, with credit, soft time, report, captain, Fits ("needs your schedule" while the schedule is not
  read), FAR 117 (117.25(e), 117.25(b), 117.23(b)(1), 117.23(c); CBA rest, PWA 10.E.1.a) and Value = credit x the PWA
  3.D.6 rate for the longevity year in Pay settings (flagged while that year is not confirmed); rows on VAC or blocked
  days behind Show VAC/blocked, kept on the device; "Pot last read ... HST" when the pot is over 15 min old),
  `flight-watcher-working-card.js` (the Working Flight view without Hark's parts; "your FLICA schedule has not been
  read" instead of No trip; only https links), `flight-watcher-charters-card.js` (the CrewTrac status in words from
  the 1.6.1 crewtrac state: refused, outage, not set up, OK; the flights found; last scan HST; Scan CrewTrac now inside
  it, off while CrewTrac's refusal stands or no details are saved) and `flight-watcher-requests-card.js` (open time
  requests and trades as FLICA lists them: status, type, trips, date and time HST, newest first; read only).
- Wording on a portal copy: the clock card (new `FW_PORTAL` flag) says "Watcher not answering ... ask the Flight
  Watcher admin" instead of the Settings > Apps step and gives needs_settings its own line (Settings tab, no Re-arm);
  the settings card says "Encrypted in your browser; only your Watcher can read it ... Saving restarts your Watcher" and
  shows the CrewTrac status under the fields (red while refused); the finds card's Key leaves out the alert email and
  smart.json lines in the portal; the improved card no longer says "app 0.9.0"; the school calendar (HPA) is read and
  named on the admin's schedule card only. Help text: Scan FLICA now is a full check, the yield grows past 30 min (up
  to 4 h), Scan CrewTrac now is one CrewTrac login and stops after a refusal. A pilot's notes name nobody and give no
  MQTT topic or HA step ("back in 30 min", "enter your FLICA username and password on the Settings tab", "paused: the
  Pause switch is on"); the admin's yield note is unchanged. sealed.py: "reload this page and save again". Alert
  texts match their pages: a recall verdict in the Recall card's words (CHECK, SHOULD HAVE BEEN YOU), "Your alert rule
  matched ..." without the internal rule id and with the layover, and a failed FLICA login points at the Settings save.
  The new pairing text ("Fit Fits") is pinned by the contract sample and stays.
- HST and touch: the clock card's Last and Next are HST (Pacific/Honolulu, labeled) on any phone; its buttons and
  selects are at least 44 px tall on a phone; its interval selects offer only what the number entity allows and, in
  the portal, what contract 1 passes (hunt 5 to 90 s, normal 1 to 20 min); an off-list value goes in its sorted place.
  The pilot card's "read" time is HST.
- Finds: this month's and last month's finds files are written even when empty, so the finds card (and the portal
  export, finds:<month>) never fetches a month file that does not exist.
- Schedule card: its redraw signature includes each state, not only last_updated, so the month arrows work where the
  month helper's last_updated does not move (the portal's local helper).
- Tests: `test_release_a_cards.py` (layout, texts, notes, finds files, and Chromium renders at 390 px of the four new
  cards, the clock card in Tokyo and Los Angeles time, the schedule card's month arrows, the portal settings and finds
  cards and the pilot card); `test_portal_bundle`, `test_portal_events` and `test_wwwfiles` follow the changes above.
  A mutation check (34 mutations, one per change) killed every one.

Release A review fixes (the reviewers' findings on the committed Release A). Built, not deployed.

- Account safety, FLICA login: a refused FLICA login (the form came back, no load error) is kept as a hash of the
  details (S `flica_refused`, never the values); while stopped_login_failed holds those same details, Re-arm logs in no
  more and says "FLICA refused these login details at HH:MM HST; save new ones on the Settings tab". New details saved
  in Settings lift the block (and the login floor); the same ones saved again give one more try, as CrewTrac's block
  (1.6.1). On a pilot, FLICA logins are at least 10 min apart (`LOGIN_MIN_GAP_S`) whatever asks (Re-arm, a re-login
  back-off, the end of a yield): the wait shows in the note. A pilot's un-pause checks with the session he has and logs
  in only if that check finds it gone. The admin's Re-arm and un-pause are unchanged.
- A pilot's checks start at least his fastest hunt apart whatever wakes the loop (`PILOT_CHECK_FLOOR_S`, 5 s since
  Ryan's ranges; 120 s in the first build): a hunt change, an un-pause or Check now inside that time wakes it at the
  floor instead (`WAKE_DUE`, one wake); Pause on still wakes at once (it loads nothing). His Check now gap is the
  admin's 10 s (a press or a check start inside it counts too). His wait between checks is never under 5 s or 1 min,
  nor under his budget's pace (below). The admin's jitter is unchanged.
- The gate gives up a waiting load when Pause goes on or the Watcher stops during a check (`GateAbort`): the check ends
  with nothing more loaded. On a pilot the reads that may be left out (Tradeboard, reserve grid, request lists, crew
  index, his own trips, pot details, pickups) skip a load that would wait for his budget (`GateSkip`, `GATE_KEEP` 4
  free) and never take the pot's share of the hour (`opt_cap`: 100 less the pot's pages times his checks an hour, his
  schedule and one check's start); the main loop starts a check only once the loads it needs fit (`check_tokens`), so a
  hunting check never waits inside the gate. A pilot's lookup still waits for his budget. Simulated 3 h of hunting at
  90 s: about 83 loads an hour, about 68 of them the pot, no wait inside a check.
- A CAPTCHA page on the main menu (with no mobile pot to read), on the mobile pot, the open time pot or the close-in
  folder stops the Watcher ("FLICA showed a CAPTCHA page on the main menu (never answered); press Re-arm after you have
  opened FLICA yourself"): no new login is used to get past it (it was taken for an expired session, up to 6 logins).
  The admin's menu CAPTCHA with a mobile pot that reads still falls back to it, as before.
- Schedule read: the mobile shape that worked is kept apart (S `sched_shape_mobile`) and tried second, so one hiccup that
  let Schedule Lookup answer never loses the admin's BCID page. One read loads at most 2 pages in all: the follow-on
  reads (FLICA's totals, the other months, last month) use what the current month left, the rest waits for the next due
  read (stored totals are kept meanwhile); the Schedule Lookup month list is kept 6 h (S `lookup_months`). A listed
  month that fails waits 1 h, 2, 4, at most 6 h (S `sched_other_fail`), and a failing other-months pass is counted on
  the lookup path once per read unless another lookup page of that read was a schedule; a pass that missed a month waits
  like the mobile one (S `sched_prev_at`).
- Breakers: Tradeboard, pairing and reserve grid pages are judged by what their parsers know (`page_verdict`): a page
  none knows (FLICA's "Service Temporarily Unavailable") stops the path for 30 min; the asked pairing's own page with
  nothing readable is a failed read (3 in a row stop); a good page closes the breaker. The request list still publishes
  while the Tradeboard path is stopped.
- Captures and logs: a pilot's captures are masked by the page's structure too: runs of capitalized words that are no
  page words ("JANE DOE", "Jane Doe", "DE LA CRUZ, MARIA"), every person argument of a Tradeboard row (flica, e-mail,
  phone, first, last, comments) and any JS string literal that is no known token, e-mail addresses, 7 to 15 digit phone
  numbers, and 3 to 7 digits after Emp; the Tradeboard posters and trade employee numbers join the masked strings. On a
  pilot every log line is masked the same way (`PilotLogMask`), and the raw page dumps (after login, mobile pot probe,
  detail probe, schedule not parsed, Tradeboard, reserve grid JSON) only go in while his captures are on (else their
  size). Once at start (DB `caps_cleanup_v`): the admin deletes what 1.6.1's pilot code wrote into his captures folder
  (leftmenu, scheduledetail_*, cmschedules_prompt, ctweb_*, cmschedule_*; his own come back with his next scans); each
  pilot deletes his unmasked last_login.png, makes his captures folder 0700 and prunes it; only a count is logged.
  `prune()` never follows a symlinked pilot folder.
- Pilot name lookup: a last name matches whole; its start only from 5 letters on (3-letter prefixes listed the roster);
  at most 20 name queries an hour (a status line says when the next may run); even one match is a pick list, so an
  employee number is used and shown only after the pick. The search placeholder on a pilot: "Last name (3+ letters),
  Last, First, or employee #".
- Cards and layout: a frequency the Watcher clamps says so in its portal result ("set to 90 min, the slowest this
  Watcher allows"; since Ryan's ranges nothing contract 1 passes is clamped); no State, Last check or Next check rows
  under the clock card. The clock card shows
  the gate's and breakers' note while idle or hunting and, during a budget wait, "Waiting for the FLICA budget until
  HH:MM HST" instead of "Stuck. Press Re-arm". Settings: a save's result is said again for 10 min after the restart it
  causes ("saved: ... (Watcher restarted with them)", S `settings_last`); the card shows "Restarting with your
  settings..." meanwhile and keeps its message across a rebuild. Schedule card: with no longevity year and no real DOH
  no rate is used (the placeholder DOH gave year 12): the banner asks for it, the pay figures and Improved-Pay-Gross wait
  for it; a pilot's unset taxes are named in the banner too; the RO+15% toggle inside the Pay-Gross box can be tapped;
  the award-only view labels its totals check "award", not "FLICA". Pilot card: a lookup seen on a fresh page open is
  timed from the sensor's own time and promises no past next-check time. Working flight: "On H3681: its legs are not
  read yet." on a trip whose legs are not read, and "From your FLICA schedule" only once a month is on file. Charters:
  "Not scanned yet." before a scan, never "No unusual A330 flying found". Recall/O75: rows before the first schedule
  version on file say the line as held that day is not on file (versions start <date>), not "until the Watcher has
  read it" (`missing_line_old`, `versions_from`); the month arrows are 44 px buttons; the raw JSON paste tool is the
  admin's only. Help: Scan FLICA now reads the schedule too unless a schedule read is backing off.
- Tests: `test_release_a_review.py` (new: the main loop with a fake browser for Re-arm, un-pause and toggles, the
  gate's abort and skip, a 3 h pilot simulation, CAPTCHA stops, the schedule shape and 2-load cap, the judged
  breakers), and new cases in `test_release_a_captures.py`, `test_release_a_lookup.py`, `test_release_a_cards.py`,
  `test_release_a_ntfy.py`, `test_release_a_schedule_card.py` and `test_release_a_recall.py`; `test_release_a_flica`,
  `test_other_months`, `test_watcher_state` and `test_cards` follow the changes above. Each new case fails on the
  committed Release A.

Check frequency ranges (Ryan 2026-11-10: "The hunt floor should be 5 sec to 90 sec. And normal should be 1 min to 90
min"; it replaces the pilot's 120 s floor of the first build, on the admin and on every pilot). Built, not deployed.

- Ranges: hunt 5 to 90 s and normal 1 to 90 min on every instance (`roles.WATCHER_FREQ_LIMITS`, `roles.freq_limits`;
  `roles.PILOT_FREQ_LIMITS` is gone): the number entities (`number.<prefix>_hunt_check_every`, `_normal_check_every`),
  the clamp of `freq/*/set`, the clamp of a stored value when it is read, and the check timing floors (5 s, 1 min). The
  admin's normal now goes to 90 min (20 before); his hunt range, jitter and budget are unchanged. The pilot's start-up
  move of a stored hunt to 120 s (`freq_migrate`) is removed: a stored 40 s stays 40 s. A pilot's Check now gap is the
  admin's 10 s.
- Portal contract 1 is byte-identical (`tests/fixtures/portal_contract_v1.json`, its sha256, `PORTAL_CONTRACT.md`):
  `roles.FREQ_LIMITS` stays normal 1 to 20 min and hunt 5 to 90 s, what a portal's `freq/*/set` must be within. So a
  pilot whose portal is on advertises normal up to 20 min on his number entity (`roles.entity_freq_limits`) and the
  clock card's portal copy offers up to 20 (`FC_PORTAL_MAX`), while his Watcher's own clamp already takes 1 to 90: the
  contract revision in Release C is the only step left. The admin's entity says 1 to 90 now.
- The safety limits stay: a pilot's 100 FLICA loads an hour, the host's 480 an hour and 1.5 s gap (`gate.py`), the
  breakers. A pilot's hunt faster than his budget keeps up for an hour is spread over the hour (`budget_pace_s`: his
  pot pages a check into 100 less the schedule read, one check's start, 12 loads an hour for the reads that may be
  left out, `PACE_OPT_H`, and, hunting, the close-in folder's reads, `close_in_h`; about 89 s with 2 pot pages and
  105 s once the close-in folder is known, jittered up to 30 % above), instead of spending the budget in minutes and
  then waiting most of the hour blind. Hunting reads the close-in folder at most every 5 min (FW-0035), so the pace
  charges it as about 12 loads an hour, not a page of every check (counted per check it held every hunt to 133 s,
  slower than the 120 s floor this replaces); in normal mode every check reads it, so it is a page of each check.
  `opt_cap` counts a held hunt at that pace, and leaves the optional reads (a new find's pot details among them)
  `PACE_OPT_H` an hour at it. The state note and the
  clock card say so plainly: "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget, at
  least 89 s apart" (`held_note`; "Checking every 1 min ..." in normal mode; "(next at HH:MM HST)" while a load waits
  for the budget); the clock card labels it "Slowed." with the next check's time, never "Stuck". Simulated 2 h of a
  5 s pilot hunt in the real main loop: about 85 loads in the busiest hour, about 34 checks an hour, both pot pages every
  check, never more than 2.5 min between pot reads, no budget wait. With the close-in folder known: about 29 checks an
  hour (it was 23), the folder at most every 5 min, about 84 loads in the busiest hour.
- `gate.py` keeps each load's time in full in its file (it was rounded to 1 ms, so a token could come back, or the
  host gap end, up to 0.5 ms early: 101 loads in 3599.9995 s). The limits themselves are unchanged.
- Clock card options: hunt 5, 10, 15, 20, 30, 45, 60, 90 s; normal 1, 2, 3, 5, 6, 10, 15, 20, 30, 45, 60, 90 min, within
  the entity's min and max (an entity without them: 5 to 90 s, 1 to 90 min).
- `portal_layout.json`: the Settings tab has the "Hunt: check every" tile again (it was dropped only because 120 s could
  not be sent) and a line: hunt 5 to 90 s, normal 1 to 20 min (longer normal intervals come to the portal in a later
  update), and the Watcher keeps a pilot within 100 FLICA page loads an hour, which keeps up about one check every
  1.5 min (a little longer once the close-in folder is found), so a shorter hunt or normal interval runs at that pace.
  The Watcher tab's help has no 2 min floor any more, says the same of the budget (a 5 s and a 60 s hunt check about
  as often) and that each Scan FLICA now press uses a few of the 100 loads, so pressing it over and over can leave the
  Watcher waiting up to an hour for the budget.
- `freq()` falls back to config.yaml's defaults (6 min, 40 s) when an option is missing, so a frequency command never
  raises.
- Tests: `test_freq_ranges.py` (new: the admin's and a pilot's ranges, the clamp at 5 and 90 s and 1 and 90 min, the
  timing floors and the pace, a portal pilot's entity at normal 20 max, a stored 40 s through a real start, the budget
  holding a 5 s hunt to at most 100 loads an hour and spreading it, the held note, the close-in folder in the pace and
  a 5 s hunt with it known through the real main loop); `test_flica_gate` (101 loads never inside one hour, the host
  gap to the microsecond); `test_release_a_flica`, `test_release_a_review` (the worst rolling hour is now at most
  100, not 101), `test_release_a_cards` (a held hunt in the clock card, the Settings tab and its new help wording) and
  `test_portal_spool` follow the new ranges.

## 1.6.1

Stage 0: stop retrying a login CrewTrac refused, and stop reading FLICA's schedule page every loop when it cannot be
read. Built, not deployed.

- CrewTrac login (`charter.py` `Scanner.login`): three outcomes. `ok`; `refused` when the page says so (e.g. "Invalid
  User ID or Password", or a locked account); `outage` for anything else (no login form, an unexpected page, a network
  error, a timeout). The log lines keep their shape; no typed value is logged.
- Refused: a block keyed to the sha256 of the CrewTrac user name and password in use (never the values) in the DB
  (`crewtrac`). While it matches, nothing logs in: not the 6 h timer, not Scan CrewTrac now (it only republishes the
  status). Saving other CrewTrac details (Settings for a pilot, the app Configuration tab for the admin) lifts it,
  because the hash no longer matches. Before, a failed login left `charter_scan_at` unset and the thread tried again
  every 30 s to 10 min, so a wrong password was sent to CrewTrac over and over.
- Outage: the next try waits 30 min, then 60, 120, 240, then 6 h at most; a scan that works resets it. A scan that
  fails after the login (an error, the session dropped mid-scan) counts as an outage.
- Scan CrewTrac now: at most one scan every 30 min (the first press after new details excepted); a press inside the
  gap, or while a scan runs, only republishes the status and never queues a second scan.
- `sensor.<prefix>_charters`: the status in plain words ("CrewTrac refused your user ID or password at 08:05 HST. No
  more tries until you save new CrewTrac details in Settings.", "in the app Configuration tab" for the admin; "Enter
  your CrewTrac user ID and password in Settings." when none are saved; the outage text names the next try), and a new
  attribute `crewtrac` {state ok | refused | outage | not_configured ('' until the first try with new details), at,
  next_try}, times in HST. A working login scans exactly as before (same rows, status `ok: ...`, events, log lines).
- Passwords are no longer trimmed: `settings_cmd` (plain and sealed), `creds.json` as loaded, the Web UI form and the
  Settings card keep a password exactly as typed (a space may be part of it); user names and the last name are still
  trimmed, the ntfy topic and token are still checked and kept trimmed.
- Schedule read (`schedule_check`): no schedule stored no longer forces a read on every loop. After a read where no
  page was accepted the next one is due in 10 min, then 30, then every 30 min (`SCHED_GAP_S`); a read that works
  resets it (`S` keeps `sched_fail` and `sched_next_at`). Nothing is fetched inside the gap; only this start's first
  forced read (the first pass, or a Check now) skips it. One log line per failed read sums up its tries (it was one
  line per try, up to 4 every 40 s). The URL candidates and the pacing are unchanged.
- Review fixes (before release):
  - A refusal wording counts only when it is new in CrewTrac's answer: help text already on the login page ("three
    incorrect password attempts lock your account") never blocks details that work. More wordings are known
    ("Incorrect User ID or Password", "... and/or password", "the user name or password you entered is incorrect",
    "login failed", "too many failed attempts"), also inside a script alert().
  - The login form coming back with no refusal message is an outage marked unconfirmed: Scan CrewTrac now is held
    and the timer tries once more after 30 min; the login form back again is a refusal. So a refusal in words not on
    the list costs two tries at most, and one hiccup never blocks working details. Status: "CrewTrac did not let the
    login through at 08:05 HST. One more try at 08:35 HST; if that fails the same way, no more tries until you save
    new CrewTrac details in Settings."
  - Refused hashes are also kept apart (DB `crewtrac_refused`, the newest 20): details cleared or swapped and later
    back (a restored file, or blanked and put back in the Configuration tab) stay blocked. Saving CrewTrac details in
    Settings (even the same ones, for example after CrewTrac unlocked the account) lifts the block for one more try;
    refused again, it is back. A save with no CrewTrac field lifts nothing.
  - An error after the rows are read (merge, DB, events, publish) is a failed scan with the outage back-off, not a
    new full scan 30 s later; the charter thread logs any error a turn lets out and goes on a minute later.
  - The admin's status says "in Settings" when CrewTrac details saved in Settings (creds.json) are in use, since those
    win over the Configuration tab.
  - Schedule: a read that works after failed tries logs one line naming them ("schedule read: <url> worked after 1
    failed: ..."), so the preferred URL starting to fail still shows.
- Tests: `test_crewtrac_stop.py`, `test_schedule_backoff.py`; the spool's descriptor count now collects garbage first
  (an earlier test's closed SQLite files are no leak).

## 1.6.0

- FW-0061 (the Flight Watcher half of James's portal): a pilot entry in the option `pilots` may say `portal: true`
  (new schema field), plus the optional `fw_portal_origin` (only `https://<host>.<tailnet>.ts.net`, else ignored with
  a log line). Everything below is dark until an entry says so; with none, nothing of it runs and the admin (Ryan's
  instance) keeps the 1.5.0 subscriptions, entities, settings sensor and log lines exactly (tests pin them).
- Launcher: before any child starts, for the portal pilots only, `/share/fw_portal/<name>/` with `out/`,
  `out/blobs/`, `out/files/` (root:2061 0750) and `in/` (2061:2061 0700), modes re-applied every start, a symlinked
  folder refused (that pilot gets no portal); `/share/flight_watcher` becomes 0700; the Ed25519 signing key
  `/data/portal_ed25519.pem` (0600, made when missing, a corrupt one moved to `.bad`; never under `/share`) and the log
  line `portal signing key ed25519:...`, also shown on the Web UI for HOM's `fw_signing_key` option.
- New `portal.py`: signed envelopes (`fwp1` bytes, base64url Ed25519 signature, seq strictly increasing and kept in
  `/data/<name>/portal_seq.json`), atomic `out/` writes (0640), size caps, the `in/` spool checks and the event
  formatter. New `roles.py` contract tables: `PORTAL_CMDS`, `PORTAL_REFUSED`, `PORTAL_EVENTS`, `MACHINE_EVENTS`,
  `EVENT_FIELDS`, `PREF_KEYS`, `LOCAL_HELPERS`, `FILE_KINDS`. The interface is `PORTAL_CONTRACT.md` and
  `tests/fixtures/portal_contract_v1.json`, generated from those tables and pinned by sha256 (HOM keeps the same file).
- A portal pilot's Watcher exports, from a thread started before it waits for its first logins: `state.json` (its
  own entities only, read back from HA one GET each, 2 s after a change and all every 5 min; file keys zeroed,
  `contact` removed, HA's `context` never copied), `events.json` (the last 100 of new pairing, rule match, recall
  miss (PWA 22.G.2), request decided, schedule changed, charter, hidden, needs settings and stopped: whitelisted
  fields only, so no crew names, employee numbers, URLs, `comm_why`, `value` or pay), `results.json`, its list files
  (finds months, versions, pickers, recall, pilot versions, school calendar and the shared pairings packages; never
  tickets) and `manifest.json` with the card bundle (its own card copies as content-addressed blobs, the layout in the
  new `portal_layout.json`, the services and the subs the cards publish).
- The spool (every second) accepts only the allowlisted subs from `in/` (plain files owned by uid 2061, at most 64 KB
  and 300 s old, unseen ids, 30 a minute, `settings/set` sealed only) and republishes each on the pilot's own MQTT
  topic; every refusal is logged and answered in `results.json`. Uploads, tickets, drop marks, auto swap, the crew
  index and alert emails are never reachable from a portal.
- Prefs: new subscription `pref/set` on a portal pilot only; `/data/<name>/prefs.json` (0600) holds the federal and
  state tax %, longevity year (PWA 3.B.1, 3.D.6) and ER trips (PWA 4.O.1.b), seeded once from the HA helpers; the
  pilot's pay line reads it before the helpers. The admin never reads a `prefs.json`. `pref` joins `roles.RESERVED`.
- ntfy (new `ntfy.py`): a portal pilot may save an ntfy topic and access token on its Settings card (sealed only; the
  card shows the fields only when `sensor.<prefix>_settings` says `ntfy`, never on Ryan's card, and never sends them
  on the plain-http fallback). Pushes go to the constant `https://ntfy.sh/<topic>` with the event's name-free title
  and body, priority 5 for a new pairing that fits and is FAR 117 legal, a tap target only with `fw_portal_origin`,
  dedupe, at most 30 an hour, 3 tries; the token and topic are never logged. The admin never posts.
- Review fixes (before release): a folder in `in/` is refused without leaving a file descriptor open or stopping the
  poll (it stalled every later command and leaked one fd a second); an empty one is removed, one that is not empty is
  refused once and then skipped. One bad entry never ends a poll. `freq/*/set` from the portal must be a finite number
  in the slider's range (`roles.FREQ_LIMITS`; `inf` was OverflowError inside on_message, which ends paho's network
  thread), the freq handler refuses it too, and paho's callback (`on_message_safe`) logs a handler's error by type
  instead of re-raising it, on every instance. A `pref/set` with a 400-digit number, or JSON nested too deep, is a
  refusal, not an uncaught error. The list file export reads plain files only (no symlink, FIFO or device; bounded
  read) from folders that are not symlinks, so nothing planted in HA's config folder can make it copy a file of this
  container or stall. The prefs seed waits for Home Assistant (retried on each 5-minute sweep) instead of being used
  up empty, and keeps a `pref/set` that came first. A card blob is kept 1 h after the manifest stops naming it (it was
  timed from the file's age, so an update deleted the old cards at once). urllib3's debug request line no longer
  writes the ntfy topic into the log. `PORTAL_CONTRACT.md` now says state.json and files/ are the pilot's own
  dashboard data (crew names, employee numbers, `value`, `comm_why` stay there; events.json and ntfy never carry
  them). The contract fixture gains the freq limits and two refused freq samples (new sha256).
- Review fixes, round 2: an event's dedupe id now covers its own time (`seen`, `at`, `updated`, `since`), so a pot
  pairing that is picked up and dropped back, or a rule that matches again, is pushed and listed again (a replay of
  one publish still dedupes). Dotfiles in `in/` never count toward a poll's 200-entry cap (200 abandoned portal temp
  files stopped the spool for good, silently); one older than 5 minutes is removed (logged once). The prefs seed takes
  a never-set ER list (`input_text` reading `unknown` for good) as empty instead of retrying every sweep forever. A
  state HA had no answer for (a 404 right after a start or in an HA restart, or no answer with nothing cached) is read
  again after 15 s, doubling up to the 5-minute sweep, so the settings sensor and its key are back within seconds.
  The portal's copy of the Settings card (`FW_PORTAL` on, `portal.portal_card`; the cards under `/local/` and Ryan's
  card are unchanged) sends a login sealed or not at all: with no key loaded yet or no WebCrypto, Save is disabled and
  sends nothing. Turning a portal off is fail-closed: at each start the launcher empties `out/` and `in/` of a pilot
  folder whose portal is no longer on (`portal.retire`; never follows a link; nothing at all without
  `/share/fw_portal`).
- No FLICA page loads are added; FLICA stays read only.

## 1.5.0

- FW-0063 (pilots and roles): new `roles.py` holds one table, `FEATURES`, of what each Watcher may do; README.md
  carries the same table ("Pilots and roles"). The default instance (Ryan's, prefix `flight_watcher`) is the only
  admin; every other instance is a pilot. The role comes from the instance, never from an option. Ryan's instance
  keeps exactly the 1.4.12 MQTT subscriptions, entities, cards and pushes (tests pin both lists).
- New option `pilots` (a list of `name`, at most 3 besides the admin), read by the launcher; while it is empty,
  `second_pilot` is read as before (at read time: the options are never rewritten, so James's setup needs no change).
  A name that is invalid, repeats, starts with one of the admin's id, topic or folder words (`roles.RESERVED`: `state`,
  `settings`, `ticket`, `hunt` ...) or would mix with another pilot's ids is left out with a log line. A third pilot
  gets its prefix, data folder, entities and card copies with no code change.
- A pilot's Watcher no longer subscribes to `email/alert`, `auto_swap/set`, `swap_map/press` or `drop/set` (nor
  `crew_scan/press`, as before), refuses a stray message on one with one log line, and empties the retained discovery
  config of Would drop, Auto swap (dry run) and Map swap pages (read only), so HA removes those three entities from
  James's device; none is on his dashboard. Its drop scan, `event/drop_ready`, swap page mapping and alert email check
  never run, and a stored auto swap is turned off at start. The crew index, Hark CCR requests (and now the CCR reply
  poll, idle on a pilot) and the one-writer duties read the role instead of the instance name.
- `sensor.<prefix>_state` gains `role` (`admin` or `pilot`) and `features`. The schedule card draws the drop mark only
  when its Watcher's role is `admin` AND the HA user is the owner: on Ryan's card it shows to the HA owner only, as in
  1.4.12 (FW-0048; another HA admin login sees no drop mark), and a pilot's copy never shows it, even to Ryan.
- Push isolation guard: `ha/pilots.json` (new) lists the admin, the pilots, their notify targets and action prefixes;
  `ha/check_push_isolation.py` reads it (`--pilots=` for another file), reads an id of a pilot it does not know as an
  offender instead of Ryan's, matches pilot names with underscores (longest name first), and checks each pilot's
  targets and action prefixes. It fails closed: a notify target `pilots.json` gives to nobody is an offender, as is a
  neutral-trigger automation that reads several pilots and pushes, or a push to an unlisted target carrying any
  pilot's action. The snapshot still reports 0 offenders.
- Review fixes: an automation one pilot's Watcher triggers that pushes may read only that pilot's topics and entities
  (a James trigger putting Jane's or Ryan's schedule into James's push is an offender), and a Ryan-triggered push no
  pilot's. The guard reads `ha/pilots.json` and `roles.py` when it runs, not at import, so a broken file is exit 2
  with one line naming it (it was a traceback with exit 1, the offenders code). Pilot names are words of lowercase
  letters and digits joined by single underscores (`roles.NAME_RE`, also the `pilots` schema, `cards.py` and the
  guard): `jane_` or `a__b` gave ids such as `sensor.flight_watcher_jane__state`, which Home Assistant does not keep.
  A test pins the exact subscribe calls `on_connect` makes for the admin (the 1.4.12 list) and for a pilot.
- No FLICA page loads are added or changed; FLICA stays read only.

## 1.4.13

- FW-0042 (roadmap items 2 and 3, Hark's rules of Nov 1, Ryan's go-ahead Nov 8): smart push fields. Every row that
  carries `fit` and `far` (pot, Tradeboard, close-in, the finds history and the `event/new_pairing` payload) now also
  carries `comm`, `comm_why`, `value` and `month_rule`. New module `smart.py` (pure functions and a loader cached by
  the file's contents, so a same-size rewrite inside one file time tick is still seen; it never raises). No new
  FLICA page loads: the fields are built from what the Watcher already reads.
- `comm`, Hark's commute check per home airport: IN = at least two scheduled nonstops (any airline) from that airport
  the same day as the report, scheduled to arrive HNL before the report time (arrival = departure + the route's
  longest block; PWA 26.QQ.2, the two-flight rule; an overnight report before the first arrival is No); HOME = at
  least one scheduled nonstop HNL to that airport departing 60+ min after the release (block-in + 15 min, PWA 2.19.b),
  the same day. An overnight release has no same-day home (the mirror of the overnight report): one whose 60 min runs
  past midnight, or one after midnight and before 05:00 (`home_day_start` in `smart.json` moves that; Hark to
  confirm whether a 04:00 to 05:00 release counts). When the last leg comes from outside the US (its origin, from the
  route or the pairings package; `domestic` in `smart.json` adds US stations), HOME uses the PWA 2.19.b customs
  release, block-in + 30 min, and `comm_why` says `(customs, PWA 2.19.b)`. When the origin is not on file, HOME is
  judged at both releases, far.py's sure / worst rule (a No needs the sure case to fail): an airport that makes it
  with customs counts, one that misses it without customs fails, and one that makes it only without customs is
  unknown (`home 21:00 only if no customs`, and `comm_why` gives the customs time). An airport counts only with both.
  The value is the airports that count joined with `/` (both, one), `No` when every airport surely fails, or `''`
  when none counts but one is unknown (the finds card shows `?`); `comm_why` gives the report, the release and each
  airport's count and first flight home.
  Report and release come from the best on file: the pairing page's check-in and the pot row's final arrival, else
  the duty periods (pairing page, details cache or the bid period's pairings package), else 1:00 before the pot
  row's first departure; `''` when either is unknown.
- `month_rule`, the type of each bid month the trip touches (a trip across a bid period's end is judged in both,
  each by its own type). A bid month is the bid period, not the calendar month (November 2026 runs Nov 1 to Dec 1,
  December Dec 2 to 31): each day goes to its bid month by the pairing files' period bounds (the ones the crew index
  and the cards use), else by the schedule pages on file (a page lists a day outside its bid period only for a
  carried trip, so a page that lists a day with no pairing on it owns it), else the calendar month; that bid month's
  type, schedule, days off and cap judge the day. `line` (adds only on days off, from the fit tag's Conflict and the
  schedule's own days; a day off code the fit tag names, `Conflict GDO` or `OFF` or one in `off_codes`, is a day
  off, not a Conflict; the 11 h minimum rest, PWA 10.E.1.a, from the FAR column's CBA rest note; at least
  `min_days_off` days off after the add over that bid period, from FLICA's own Days Off total (which counts VAC days
  as off) less the days off the add uses, a recount of the bid period's days without it; the month's credit plus the
  trip's, split by its days across a bid period's end, at most `cap_credit`) or `reserve` (pickups over SCR days
  only). VAC days are never pickup days, also in a month with no type yet (`VAC` alone). `OK`, or what fails joined
  with `, ` (`VAC`, `Conflict H3659`, `Days off 11`, `Over cap`, `Rest 10:30`, `Not SCR`). The unknowns are never
  `OK` and never a fail: `No sched` (a month the trip touches is not on file), `Rest ?` (the rest next to a trip is
  not on file yet), `Rest 10:50?` (short only if the neighbour clears customs, PWA 2.19.b) and `Cap ?` (the month's
  credit or the trip's is not on file, or the split across a month end decides it). Not checked: reserve's 48 h in
  the pot, R-14 and no-GDO conditions.
- `value`: the trip's credit times the hourly rate, whole dollars.
- Privacy (the repo is public): the home airports, the nonstop tables, the month types, VAC dates, the rate and the
  break-even live only in `smart.json` on the pilot's share (`/share/flight_watcher/smart.json`; a second pilot's
  `/share/flight_watcher/<name>/smart.json`, like his captures), format `v: 1`. No defaults ship: without the file
  every new field is `''`, the pot and Tradeboard sensors carry exactly what they did, and a malformed file is logged
  once and treated as none. Tests use made-up airports and times.
- Sensors: the four fields stay off the pot and Tradeboard sensors (like `far_why`), which publish exactly what they
  did in 1.4.12, so a busy month keeps as many rows under the 12 KB cap. The DB, the finds month files, `last_new` and
  `event/new_pairing` carry all four; the finds, pot and Tradeboard sensors carry none of them (the finds sensor
  keeps its short rows). Showing Comm or Value in the pot_table macro needs two things: a Watcher release that takes
  the fields out of `SENSOR_DROP` for `pot/state` (minding the 12 KB cap), and the HA macro edit.
- Finds card: Comm and Value columns after Credit (blank when the field is `''`, so finds from before 1.4.13 and an
  install without `smart.json` show nothing new); Comm is green when an airport works and red on No, and its hover
  gives `comm_why` and the month rule.
- Push (a separate HA step, not in this release; no automation or `ha/*.yaml` changed): `event/new_pairing` carries
  `comm`, `comm_why`, `value` and `month_rule` next to `fit` and `far`. The new-pairing automation can add them to the
  message (`Comm {{ trigger.payload_json.comm }} | ${{ trigger.payload_json.value }} | {{
  trigger.payload_json.month_rule }}`, each with `| default('')`) and lower a trip to a quiet push only on a real
  fail: `comm == 'No'`, or a `month_rule` part that is not an unknown (`VAC`, `Conflict`, `Days off`, `Over cap`,
  `Rest h:mm`, `Not SCR`). Everything else keeps the critical buzzer: a blank `comm`, and the `month_rule` parts
  `''`, `OK`, `No sched` and any with a `?` (`Rest ?`, `Rest 10:50?`, `Cap ?`), as the automation's "'?' still
  pushes" rule does. In a template: `{% set p = trigger.payload_json %}{% set mr = (p.month_rule |
  default('')).split(', ') | reject('in', ['', 'OK', 'No sched']) | reject('search', '[?]') | list %}` and quiet when
  `p.comm | default('') == 'No' or mr`. A combined `VAC, No sched` still goes quiet. Blank fields mean no
  `smart.json`, a time not on file, or a commute that only a customs release decides (the last leg's origin not on
  file): treat them as unknown, never as a pass or a fail.

## 1.4.12

- FW-0068 follow-up (Nov 9, live check of 1.4.10): the probe found H3631 Nov 6 flown as H3631B, but that copy's crew
  line names the captain only, so pilot 10031 (an FO on the trip, per CrewTrac) still had nothing on Nov 6-8. FLICA
  can split a rebuilt trip's crew over two lettered copies, and the probe stopped at the first copy with crew. Now
  the letters are read on until the copies found name as many pilots as the package trip has pilot seats (its crew
  line after departure, OPEN seats counted); every copy that names a pilot is indexed. A copy that leaves seats
  unnamed is logged with its crew line masked (`crewidx.crew_mask`: seat codes, OPEN, CKP and employee numbers kept,
  every word of a name shown as x), so a seat layout the crew line parser does not know shows up in the log without a
  name. Probe records gain `v: 2` and list every copy found (`found: "H3631B,H3631C"`); a record from 1.4.10 / 1.4.11
  whose copies leave seats unnamed is probed once more (the copy indexed already is not read again; at most 3 more
  page loads per trip, once, GET only, paced 1.5 to 3.5 s). New in `crewidx.py`: `pilot_seats`, `named_pilots`,
  `crew_mask`.

## 1.4.11

- FW-0069 (Ryan, Nov 9: "When we look at pilots' schedules, can we make it like when I view mine, where we give
  schedules a version and we can cycle through them as you capture them? MM.01 style?"): the pilot card keeps
  schedule versions for every pilot Ryan looks up, numbered like his own (11.001, 11.002, ... per bid month). New
  module `pilotver.py`; nothing in it reads FLICA (no new page loads), and Ryan's own versions (`versions.py`) are
  unchanged.
- What makes a version: only the pilot's pairings, each one its id and start date (H3631B Nov 6). Seat, crew, end
  date, block and credit, reserve and VAC days, FLICA's totals and the source do not, so the same trips seen two ways
  never make two versions. Captures: a readable Schedule Lookup (source "FLICA schedule"); a lookup FLICA hides, from
  the crew index's rebuild ("rebuilt"); and after every crew index run, a rebuild for each pilot Ryan looked up, for
  each bid month the index holds from the current one on (Ryan's instance only, like the crew index). A rebuild
  covers only the trips the index read, so it keeps every trip of the latest version that the index does not
  contradict (a crew read of that trip taken after the version whose crew line does not hold the pilot), and it does
  not add a trip whose read is older than the latest version.
- Version .001 is the awarded line when the bid month's award text is on file (uploads, `pdfs.parse_award` for that
  pilot's employee number); the first capture is then .002 only when its trips differ. An award uploaded later goes
  in as .001 and the rest are renumbered, as for Ryan's own versions. Each version keeps its trips, its days (FLICA's,
  the award's, or built the way the card draws a rebuilt month), FLICA's totals for a lookup, and the changes from
  the one before ("added H3631B Nov 6-8 LAX", "removed H3631 Nov 6").
- Kept in the DB: pilots Ryan looked up (`pilot_versions_index`, the 60 most recent; an older one goes with his
  versions), up to 4 bid months a pilot, and per month the first version plus the latest 24. The versions of the
  pilot on the card go to `www/flight-watcher/pilotver_<key>.json` (keyed and swept like the other list files;
  James's copy reads its own folder), and `sensor.flight_watcher_pilot_schedule` gains `versions_file_key`,
  `versions_rev` and `versions` (count, current and awarded version per month).
- Pilot card: a versions bar under the header, as on the schedule card: older and newer arrows, the version, the
  house back to the current one, "N versions (current)" or "viewing <capture time HST> (FLICA schedule | rebuilt |
  awarded line)", and "Changes in v11.003". The current version is the card as before; an older one draws its own
  days and trips in the same grid with its own totals, and says that block and credit per trip, crew and pay shown
  are the live ones. The choice is kept per pilot and month while the page is open.

## 1.4.10

- FW-0068 (Ryan, Nov 8: a pilot card's schedule rebuilt from pairing crew lines missed an LAX trip Nov 6-8): FLICA
  rebuilds a package pairing it changes under the same id plus a letter (H3631 becomes H3631A, H3631B, ...; Ryan's
  H3815B and pot finds such as H3676A are the same thing) and the crew moves to it. The package trip's page then names
  no pilot (seats OPEN), and the new id was in no package, on no schedule the Watcher could read (that pilot's FLICA
  schedule shows an application error) and never in the pot, so the crew index never read it. Now each chunk of a
  crew index run first probes up to 2 package trips (`VARIANT_PER_CHECK`) for the copy the crew flew: a trip whose id
  has no letter, that departed no more than 35 days ago (`VARIANT_MAX_AGE_D`), whose last read was taken after
  departure (the final crew) and names no pilot, in a bid period whose award is out, and that was not probed before;
  most recently departed first. The probe reads the same pairing page URL with the ids H3631A to H3631D
  (`crewidx.VARIANT_LETTERS`), GET only, each URL through both read-only guards, 1.5 to 3.5 s before every read; the
  reads count in the run's 300 pages and the chunk's 50 (8 while hunting). An id already in the index is not read
  (one whose read names a pilot is the copy). A page that names that id on that date (`crewidx.page_names`, from the
  header `pairing details h3631b:06nov`; an error page or another date's trip is skipped) with a pilot on its crew line
  is the trip flown: it is noted with the schedule trips (src `variant`; end, route and report from its page), its
  crew read is stored, and from then on it shows on the pilot card and in the month Markdown like any other trip.
  The letters after it are not read. The package trip keeps its own read.
- Each probe is recorded in the DB (`crew_variants`: the trip, when, and the id found or none) once every letter was
  tried or one was found, so a trip is probed once (at most 4 FLICA loads, once, per departed trip whose crew line
  names no pilot); a fetch error leaves it for a later run (not again in the same run). A captcha, a session taken
  over or an expired session on a probe page ends the run as on any crew index read; pause and re-arm stop the probe
  and the run goes on later. Records older than 65 days are dropped. Ryan's instance only, like the rest of the crew
  index. The log names pairing ids and dates only (`crew index: H3631 2026-11-06 flew as H3631B (read)`).
- `sensor.flight_watcher_crew_index` gains `from_variants` (rebuilt copies in the index; `from_schedules` still counts
  the trips from schedules). New in `crewidx.py`: `variant_ids`, `page_names`, `variant_candidates` and
  `extra_instance` (the schedule trip builder `instances()` already used, now keeping src `variant`).

## 1.4.9

- FW-0067 (Ryan, Nov 8: "When other users use Flight Watcher the new Working Flight view should point to their
  schedule"): every Watcher instance publishes `sensor.<prefix>_working_flight` (Ryan: `sensor.flight_watcher_working_flight`;
  James: `sensor.flight_watcher_james_working_flight`) from that pilot's own FLICA schedule, so each pilot's Working
  Flight view can read his own line. Hark's `sensor.hark_working_flight` (Ryan only: release, MEL, NOTAMs, gate codes,
  live status) is unchanged. New module `working.py` (pure, no FLICA): all legs of the pilot's own trips on HST time
  in departure order; the working leg is the first whose block-in + 2 h is after now (it stays on a leg until 2 h
  after block-in, then rolls to the next; on a turn shorter than 2 h it rolls when the next leg blocks out). State
  `HA865 HNL-PPG` (or `No trip`); attributes pairing, leg (`2 of 2`), flight, date (the departure day FLICA printed,
  the date at the origin), origin, dest, dep_sched / arr_sched (`16:30 local, 16:30 HST`), block, report (the trip's
  first duty: FLICA's check in, `15:30 HST`; a later duty after a layover of 8 h or more: 1:15 before departure out
  of domicile, 1:00 in domicile, PWA 2.19.b, as local and HST; a later leg in the same duty: its duty's report), status (`Scheduled`, `Enroute per schedule`,
  `Arrived per schedule`), status_as_of, next (`HA866 PPG-HNL 2026-11-27 23:20 local`, else the next pairing as
  `H3681 SYD 2026-11-09`), flightaware_url, sigwx_url, source `schedule`, release_updated false, updated, updated_by
  `Flight Watcher`. With no leg ahead: `No trip` with source, next (the next pairing whose legs are not read yet),
  updated, updated_by. A trip whose legs are not read yet is skipped for the working leg but can be next; while such a
  trip has not ended and comes before the first read leg's trip (the pilot is on it or flies it first), the sensor
  says `No trip` with that trip next instead of showing a later trip's leg.
- HST times follow each station's own clock, daylight time included (SYD, MEL and AKL from October to April, the US
  mainland and ANC from March to November): each leg is rebuilt from the day and times FLICA printed at the station's
  zone (`working.ZONES`, one for every station in `pot.TZ`), the arrival at the printed time nearest departure +
  block, so departure + block is the arrival and status, the 2 h roll and a later duty's report are on time. A
  station in no table: the leg hangs on its known end (known origin: arrival = departure + block; known destination:
  departure = arrival - block); with neither end known only the printed local times show. The image installs
  `tzdata` (2025.2) so the zones do not depend on the base image. `pot.parse_legs` and the FAR 117 duty periods keep
  their standard offsets, unchanged.
- Published retained on `<prefix>/working_flight` at start, after the own trip times on each check, and every minute
  while the Watcher waits (also when yielded, paused or parked), only when something besides the time stamps changed,
  and at least every 30 min. A failure is logged and never stops the check loop.
- `pot.parse_legs` gives each leg its flight number (`flt`) and origin (`frm`) too (new `LEG_FLT_RE`; `LEG_FULL_RE`
  and every other key unchanged). The own trip times keep each trip's legs in the state (a trip cached without them
  that ended no earlier than yesterday is read again, at most 3 a check, read only; an ended trip keeps its cached
  times and is not read for legs); `sensor.<prefix>_own_trip_times` leaves the legs out (with them a busy line passes
  the 12 KB cap and loses trips the schedule card shows). Every own trip read now waits 1.5 to 3.5 s before it (the
  first too, after the schedule read) and the last one before the pot read that follows.

## 1.4.8

- FW-0066 (Ryan, Nov 7: "Make sure that any user can see and upload pairings and awards and seniority lists and pilot
  contact lists"): the uploads card works for every Home Assistant user who can open a Flight Watcher dashboard's
  Settings view, admin or not (on Pako: the HA admins, since Ryan's dashboard is admin-only, and James, since James's
  views are visible to James and Ryan only; another household user would need adding to that view's `visible`
  list). It picks its path from the signed-in user: an admin keeps the ingress fast path (`api/uploads`, `api/upload`); anyone
  else (Home Assistant grants an app ingress session to admins only) reads what is on file from the new
  `sensor.<prefix>_uploads` and sends the file in chunks with the `mqtt.publish` service (any signed-in user may call
  it) to `<prefix>/upload/chunk` (qos 1, never retained): an upload id, index, total, size, the file's sha256, kind,
  bid period or list date and about 256 KiB of base64 per chunk (`chunks.CHUNK_MAX` = 192 KiB raw). Where the browser
  has WebCrypto (an https address) the file is sealed first, as the Credentials card seals a login: AES-256-GCM with a
  random key wrapped by this Watcher's RSA-OAEP key, the upload's fields bound as GCM additional data, so Home
  Assistant's recorder (it stores every service call's data under 32 KB; Pako keeps 3 days) and the MQTT broker hold
  ciphertext only. On a plain http address the file goes as it is, except a pilot contact list, which is refused
  there (by the card and by the Watcher). The Watcher (`chunks.Assembler`) stages the chunks in a private folder
  (`/share/flight_watcher/uploads/.staging/<prefix>/<id>/`, mode 700, files 600), ignores a repeated chunk, takes
  them in any order, drops an upload with no chunk for 2 minutes (and any later chunk of it), refuses one over the
  25 MB cap or with the wrong file type for its kind (PDF; CSV or XLSX too for a contact list), opens the seal, checks
  size and sha256, then saves it with the ingress upload's own `web.save_upload`. Progress and the result go to
  `<prefix>/upload/status` (not retained; `sensor.<prefix>_upload_status`, with the last 5 results so a card that
  missed an update still finds its own). Every save (the Web UI, ingress, chunks on either instance) runs under one
  lock (`web.save_lock`).
- FW-0066 (shared files): the award, the pairings package and the seniority list are base-wide, so every pilot instance
  now reads the one shared folder `/share/flight_watcher/uploads` (`watcher.UPLOADS`; a second pilot's instance read
  `/share/flight_watcher/<name>/uploads` before, which nothing wrote to). James's instance takes his own awarded line
  from the shared award; either instance may save a chunked upload there. `sensor.<prefix>_uploads` is re-listed when a
  file is saved and every minute (the other instance or the Web UI may have saved one).
- FW-0066 (pilot contact list): new upload kind `contacts` (PDF, CSV or XLSX; the type is read from the bytes, never
  the name). `contacts.py` reads each pilot's employee number, name ("Last, First"), phones (US numbers; a fax is left
  out; cell, home or work from the column or a label) and emails where present: a CSV or XLSX by its header row
  (EMP / EMPLOYEE # / FILE #, NAME or LAST and FIRST, PHONE / CELL / MOBILE / HOME / WORK, EMAIL), a PDF (its
  pdftotext copy) or a header-less sheet line by line, a wrapped line joining the pilot above it. The XLSX reader is
  the standard library's (no new dependency); a workbook with a DTD or one that unpacks past 60 MB is refused. Only
  pilots with a phone or an email are kept, in `/share/flight_watcher/contacts.json` (mode 600, outside `/config/www`,
  never in git); the uploaded file is kept mode 600 as `contacts_<YYYY-MM-DD>.<ext>` and replaces the previous list's
  file. A pilot lookup adds that one pilot's entry (`contact`: name, phones, emails) to
  `sensor.<prefix>_pilot_schedule`; a name only the contact list knows is looked up by its employee number. The pilot
  card shows Call, Text (not to a home or work number) and Mail links beside the name, and small ones beside the
  pilot's own name in the crew lists. No other sensor attribute, status message or log line carries a name, number or
  address from the list: the upload result, the uploads sensor and the log carry counts only.
- Uploads card (`www/flight-watcher-uploads-card.js`): a fourth kind, "Pilot contact list" (no bid period, the file
  picker takes .pdf, .csv, .xlsx); the contact list's counts under "On file"; the progress line reads "Sending ...:
  part i of n, N %" (read out at each 10 % step), then the Watcher's own progress. The James copy publishes to `flight_watcher_james/upload/chunk`
  and reads `sensor.flight_watcher_james_*`; an admin's copy still reaches the one app's ingress. The Web UI's
  Monthly PDFs form takes the contact list too.
- FW-0066 review fixes: an XLSX contact list reads only its first 256 columns (a 500-byte workbook with a cell at
  `ZZZZZZZ1` asked for about 67 GB) and streams its sheet and string table (each refused over 10 MB unpacked); a
  lookup by employee number never takes another numbered entry by name; "Employee Name" is a name column; a
  "City, ST 12345" address line is no pilot and its ZIP no employee number; a two-word last name or a suffix ("Doe
  Jr") is kept. The pilot schedule's retained MQTT copy carries no contact (the copy with it follows, not retained).
  The upload janitor starts with MQTT, so James's instance sweeps stalled uploads while it waits for settings. An
  ended upload's id is ignored for the seal's hour (it was 20 minutes), and a completed sealed upload's id is kept in
  the instance's `/data/upload_done.json` across a restart (no replays). The upload status also carries `phase`
  (Home Assistant drops an attribute named `state`); the card reads it, restarts its 2.5-minute wait on each status
  of its upload, resends a part lost with the connection for up to 90 s and says so plainly instead of
  "[object Object]", re-reads the sensor on Refresh for a user who is not an admin, sends an admin's file over
  15.9 MB in parts instead of refusing it, and shows "part i of n, p %". The crew-list contact links are 24 px tap
  targets and match the pilot's FLICA spelling too.
- Dashboards (`ha/` snapshots, the intended state; applied on Pako after this release): Ryan's Settings view heading
  "Monthly PDFs" becomes "Monthly files" and it and the uploads card lose their Ryan-only visibility condition;
  James's Settings view gets the same heading and `custom:flight-watcher-uploads-card-james` under Credentials.

## 1.4.7

- FW-0062 (Ryan, Nov 7): a looked-up pilot's rebuilt month now has Block and Layover on every trip when the bid period
  has no pairing package details (no package upload on file): block comes from the pairing file's block column
  ('12h19'), the layover from its route (stations past HNL, only for a trip that lays over: more than one day and TAFB
  longer than its first duty, so a red-eye turn has none). The pay line's Block total and the PWA 4.O.1 RO $4.00 and
  3-pilot FO $3.00 per block hour overrides are priced again; package details still win where they exist
  (`crewidx.pilot_trips`, new `crewidx.route_lay`; `crewidx.instances` keeps block, tafb, first_duty_min).
- FW-0034 (close-in folder, read only): the close-in open time folder ("Close in Opentime: <16 Hrs to RPT") is read,
  GET only. Its BCID is taken only from a menu link whose text names the folder (or the first link under a heading
  that does), never guessed: from the open time pages read every check, the pot discovery menu (desktop and mobile),
  the schedule menu read, and a paced left menu read every 6 h while it is unknown (once a day once known; the main
  menu frame when the left menu is only its skeleton). The BCID is used only after its open time page reads as HNL 332
  FO, and dropped after 3 bad reads. Once trusted: its pot is read every check (both safe_get guards, paced 1.5 to 3.5
  s), its trips are listed first on the pot (src `C`, folder `close-in`, FAR column, finds) and a new one fires
  `event/new_pairing`; its Open Time Requests list joins the request-decided push (folder `close-in`; its first read
  pushes only decisions from the last 6 h); swap and drop drafts under 16 h to report carry its BCID. A menu that does
  not name the folder is kept privately as `captures/menu_closein.html` (session token masked). Until a live menu read
  names the folder it stays unknown (no saved page on Pako shows it).
- FW-0039 (FAR column): pot, Tradeboard and finds rows get their FAR column from the same checks as the Recall miss
  check (`far.screen()` on `far.legality()`), per duty period of Ryan's trips and of the pickup (duty times from its
  FLICA pairing page, else the bid period's package): FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h,
  117.23(b)(1) 100 h flight time in 672 h and, new on these rows, 117.23(c)(1) FDP 60 h in 168 h and 117.23(c)(2) FDP
  190 h in 672 h (column words `FDP 65h/168h`, `FDP 191h/672h`). Anything not on file (a neighbour trip's times, days
  no schedule month covers, training and reserve days, a customs release that could cut the 10 h rest) reads `?`,
  never OK, so some pickups that read OK before (next to training or reserve days) now read `?`. Each row carries
  `far_why` citing the rule. The PWA 10.E.1.a 11 h domicile rest stays the `OK (CBA rest 10:30)` note (`10:50?` when
  only a 30 min customs release, PWA 2.19.b, can make it short). The old `far_check` is gone.
- FW-0056 (crew index, trips the package does not list): the crew index also reads every trip on a schedule the
  Watcher reads (Ryan's own months, a pilot lookup's month, a picker's month), kept in the DB as `crew_sched_trips`
  (dropped 62 days after the trip ends), so trips built or renumbered later (H38xx, a trade's H3815B) get their crew
  in pilot lookups and the Markdown. A trip with no package row takes its end, route and report from its pairing page;
  a later schedule end replaces a shorter one stored (the trip end repair). Every crew index page load now goes through
  `SUB.safe_get` and `SM.safe_get`; pacing is unchanged.
- FW-0057 (previous bid period): the crew index keeps a trip that starts before its first day (Oct 31) and runs into
  it; October's trips come from Ryan's October schedule when there is no October package, each in its own bid period
  (`crewidx.period_for()`: Oct 31 is October's, Dec 1 November's). A pilot lookup's rebuilt grid and its coverage
  count a trip that starts before the grid and runs into it.
- FW-0058 (seat codes inside names): a seat code (CA, FO, RO, FA, SO) on a crew line counts only in FLICA's seat
  position, standing alone and followed by the employee number or Open, so a name such as "Lee, So Young" (made up)
  stays whole. Crew lines stored before the fix that look cut are read once more at the first start
  (`crew_split_repair()`; a failed re-read keeps the stored line).
- FW-0059 (one pilot on two overlapping trips): two trips overlap when they share two or more days, start the same day
  or end the same day; trips that only touch (a morning release, a night report the same day) count only when the
  package times put the report before the release. A new overlap is flagged and both trips are read again first (at
  most 10 a check outside a run); the flag clears when the re-read shows the pilot on one, and when he is still on
  both the newer read is kept and the other is marked "older read" (Markdown Pairing cell, `overlap` / `overlap_with`
  on pilot lookup trips, one line on the pilot card).
- FW-0060 (sensor attributes too large): every Flight Watcher sensor stays under 12 KB of attributes (HA's recorder
  keeps no history past 16 KB). The ticket log, the schedule versions, the pickers and the recall days are written to
  `<name>_<key>.json` in the pilot's own `www/flight-watcher/` folder (second pilot: `www/flight-watcher/<name>/`;
  same random key as the finds files, published only as the sensor's `file_key`, with `rev` so an open card fetches
  again). The sensors keep counts and a short list (tickets: counts, `last` and the newest 30 open tickets without
  their text; versions: each month's count and awarded / current version; pickers: the count and the fastest 20;
  recall: the newest days that fit, `days_total`, the open and alert counts over every day). Every other sensor list
  is held at 12000 bytes by `cap_attrs()` (oldest or least useful items out, `trimmed` says how many). The tickets,
  schedule, pickers and recall cards read the files and show the sensor's short list until a file arrives. List files
  under an old key are deleted at start.
- FW-0064 (trade approved, no push): a crew-to-crew Trade is pushed as `event/request_decided`, type Trade, status
  Approved, when the schedule shows trips dropped and added on the same HST day (FLICA's "Schedule Updated" time) that
  no decided request explains (the request reads log each decision) and that is not a pairing renamed with a suffix
  letter, once a later read shows no new change and the trips taken have their credit (at most 2 h). A Pending or
  Processing request whose every trip shows on the schedule is pushed at once under its own key. Pay-Gross from pay.py
  (seat and credit from Ryan's trip records, PWA 4.O.1 overrides, PWA 3.D.6 rate); each is pushed once, also across
  restarts (`trades.py`). The request-decided automation says "Seen on your FLICA schedule MM/DD HH:MM HST; no request
  on file (a crew-to-crew trade)" for these (`ha/automations_flight_watcher.yaml`, to apply on Pako). Not pushed: a
  trade whose drops and adds fall on different HST days, months first read through Schedule Lookup.
- Trip end cut short (no ticket filed): a trip that comes home the day the next activity starts (H3681 SYD Nov 9
  to 12, then H3620 on Nov 12) kept only its first day from version 11.009 on: FLICA shows only the new trip's row that day, so
  there was no HNL layover cell to end it. `pot.schedule_items()` (now also the Schedule Lookup builder in
  `inflt.parse_cm_month`) ends a trip still away on the day the next activity starts. Stored versions and the schedule
  on file are repaired once at start (`versions.repair_ends`, fingerprints remade so the fix makes no new version; the
  PBS award is left alone), and a later end change shows in a version's change list. Recall legality spans and pay see
  the whole trip again.
- Test data: real crew names, employee numbers and a phone number copied from FLICA pages into `tests/test_store.py`,
  `tests/test_tradeboard.py`, a `tradeboard.py` docstring, a `watcher.py` docstring and one CHANGELOG line were
  replaced with made-up ones (the old values remain in git history).
- FW-0035 kept: while hunting the close-in page is read at most every 5 min (about 12 FLICA loads an hour), every
  check otherwise.

## 1.4.6

- Recall / Over 75 judged on the line held that day (Ryan, Nov 6): each recall list day is checked against the
  schedule version Ryan held then (`sched_versions:<month>`), never today's schedule, so a later trade neither turns
  an old row into a miss nor clears a real one. The line at 00:00 HST is checked and again each version seen during
  the day; when they disagree the row is POSSIBLE (the award time is not on the list). Per month around the day: the
  newest version seen by then; for a month not on file yet, the trips that had already started (from a later
  version); a later month with no version by then counts as not awarded yet (its first 8 days after the list day stay
  unknown); the PBS award alone counts only for a month the Watcher kept versions for from its first day. New `recall.held_at`, `helds_on`, `judge`; the row's why names the version (`your line as held at Nov 10
  00:00 HST (version 11.004)`).
- Full legality before MISSED (`far.legality`, audit of recall.py against FAR 117 and the PWA): FAR 117.25(e) 10 h
  rest and PWA 10.E.1.a 11 h domicile rest on both sides; FAR 117.25(b) 30 h free from duty in the 168 h before every
  FDP the pairing touches (its own and the next week's); FAR 117.23(b)(1) 100 h flight time in 672 h; FAR 117.23(c)(1)
  60 h and (c)(2) 190 h FDP in 168 / 672 h (new: not checked before); per duty period, with PWA 2.19.b duty times
  (1:00 before departure in domicile, 1:15 out of domicile, 15 min after block-in, 30 with customs). Every check runs
  on what is surely known (a NO needs that to fail) and on the worst case of every guess (an OK needs that to pass);
  between the two it is unknown and the row is POSSIBLE. Missing data (days of the line not on file for that day, a
  trip's times or block) can only make a check unknown: POSSIBLE, never MISSED. Over 75 with a trip or vacation in the
  way now says Over 75 is for days off (22.G.2.d) instead of citing the Recall removal steps. Every rule is cited in
  `refs` and in the why.
- RECALL ALERT bar: a red bar at the top of the Recall/O75 tab card and as the alert card on the main view (was "RED
  ALERT"), one line per MISSED row with an open CCR draft: date, Recall / Over 75, pairing, who it went to, the draft's
  status; the main view keeps its button to the tab, a line on the tab opens that day. `alert` on
  `sensor.flight_watcher_recall_o75` now counts exactly those rows (a POSSIBLE row confirmed by Ryan stays on the tab).
- Recall/O75 days fold: a day is closed by default when every row is NO MISS, the list is blank or not posted; a day
  with a MISSED or POSSIBLE row is open. What Ryan opens or closes is remembered in the browser (localStorage
  `flight_watcher_recall_fold`; works without it).
- Pushes: a MISSED row is a critical push (iOS interruption-level critical, sound default, critical 1, volume 1),
  titled "RECALL ALERT: missed Recall H3601"; anything else stays time-sensitive (only MISSED rows push, as before).
  `ha/automations_flight_watcher.yaml` has the new "recall miss alert" (to apply on Pako after the release). A
  POSSIBLE row that turns MISSED on a later list post pushes once (`missed_sent`); Refresh still never pushes.
- CCR by Hark: after Ryan approves the narrative, the row shows **Have Hark file this CCR** (the copy-and-open
  hal.alpa.org button stays as the manual way). It sends `recall/act {id, action: file_request}`; the Watcher refuses
  unless the narrative is approved (status approved, or blocked / cancelled after an approval) and the row is still
  MISSED or POSSIBLE, and on a second pilot's instance; a superseded draft never files. Then it writes
  `/share/flight_watcher/ccr_requests/<rid>.json` (`ccr.py`: `{v: 1, rid, id, pilot, date, pairing, kind, seat,
  narrative as approved, approved_at, requested_at}`, temp file and rename, no symlinks, at most 64 KB), sets the
  draft to `filing` and fires `event/recall_file_requested` (not retained). Once a minute, with no FLICA traffic, it
  reads the HOM app's answers: `<rid>.done.json` sets `filed` with the CCR number, `filed_at` and who filed it
  (`event/recall_ccr_filed`); `<rid>.status.json` sets `blocked` or `cancelled` with the reason; `<rid>.task.json`
  shows the HOM task. Answers older than the request, other names, symlinks, files over 64 KB and anything off the
  contract are refused; their text is trimmed and shown escaped. The card shows "Sent to Hark <time> HST, waiting for
  the CCR number", "Filed: CCR <n> by Hark <time>" or the blocked reason. New sensor attribute `hark_files` (true on
  Ryan's instance only).
- Review fixes (Nov 7), each with a test:
  - A row awarded to Ryan's own seniority number is NO ("awarded to you"): the version showing his own trip can come
    in after the list day.
  - A pairing whose length is unknown (no days or end on the row, no package) is POSSIBLE ("pairing length unknown"),
    never squeezed to one day.
  - Each row reads its own bid period's package (`pkg_details_for(row month)`); pairing ids repeat across months and the
    old merged dict let whichever month came last win. A period with no package gives POSSIBLE.
  - The line held at a time also uses each version's FLICA "Schedule Updated" stamp (HST): a version stored after a
    read outage whose stamp is at or before that time is the line then, and its month is not "not awarded yet".
    Change times during the list day come from the stamp too.
  - The held line reaches LOOK + 7 days back (a trip from the month before that runs into the 672 h window counts for
    FAR 117.23(b)(1) and (c)(2)); days not on file are unknown from there, and 7 days into the next month (a trip that
    starts on an unknown day may still be running).
  - Upgrade from 1.4.5: an open draft counts as already pushed only if its stored verdict was MISSED, so a 1.4.5
    POSSIBLE row that is MISSED now gets its critical push once.
  - Over 75 eligibility (PWA 22.G.2.d, Reserve Run pilots only) is answered per month on the tab
    (`me.o75_months {YYYY-MM: true | false}`, `recall/act {me: {o75_months}}`; the old single flag, which defaulted to
    eligible, is dropped). Not set: an Over 75 row that would be MISSED is POSSIBLE.
  - Hark requests: HOM makes one task per rid, ever, so no second request goes out under a rid HOM made a task of
    (a request HOM rejected without a task can still be sent again). The date in a rid must be a real date. Withdraw
    from Hark, Not a miss and Mark filed work while Hark has the draft (sent, blocked, cancelled): with no HOM task yet
    the Watcher removes its own `<rid>.json` first; with a task they need `hom_cleared` ("I completed HOM task <id> as
    skipped" on the card), because nothing reaches HOM from the Watcher. An edit approved while Hark's task is blocked
    or cancelled keeps that status. Refusals show on the card (`hark_note`).
  - A blocked or cancelled draft goes back to `filing` when HOM removes its status file and the task is still there
    (the task is open again). Drafts keep being read after Ryan withdraws, dismisses or marks them filed: a CCR number
    from Hark other than his, a task HOM made after the request was taken back, or a draft superseded while Hark had it
    fires `event/recall_hark_alert` (new, not retained) once and shows on the card. `ha/automations_flight_watcher.yaml`
    has the new "Flight Watcher Hark CCR alert" (time-sensitive, Ryan's phones; to apply on Pako after the release).
  - Card: Have Hark file this CCR is off while the box differs from the approved narrative ("Re-approve first: the box
    differs from what you approved") and sends the box text, which the Watcher checks; the approve button says
    Approve narrative when nothing changed. Wherever Hark may still file a draft a red line names the HOM task, and
    Withdraw from Hark, Not a miss and Mark filed wait for the "completed as skipped" tick. The Over 75 checkbox is a
    per-month choice (not set, on reserve, not on reserve).

## 1.4.5

- Tickets card (Ryan, Nov 6): **Process Tickets in Claude Code** now copies the prompt ("Process all Flight Watcher tickets on Pako HI: fix every new or reopened one, release it, mark it fixed, then confirm and close your completed fixes.") to the clipboard for Ryan to paste into his own Claude Code window, instead of opening a new session. It says "Copied. Paste it in Claude Code." under the button; if the browser blocks copying, the prompt shows selected to copy by hand. Card option `claude_code_prompt` replaces the text.
- Uploads on the dashboard (Ryan, Nov 6: "give me a place to upload the award and the pairings monthly"): a new
  card, `custom:flight-watcher-uploads-card`, for the Settings tab under Credentials and above Tickets. Pick Monthly
  award, Pairings package or Pilot seniority list, the bid period (next month, HST, by default; the seniority list
  takes an optional List date instead) and the PDF; the card shows the upload's progress and the app's answer, what
  is on file (what, bid period, size, upload time HST, read or not) and the dates of hire on file. Home Assistant
  admin only: anyone else sees "Uploads are for the Home Assistant admin." and the card makes no call. It reaches
  the app the way Home Assistant's own app panels do (Supervisor ingress address and session over the WebSocket
  `supervisor/api`, the `ingress_session` cookie, re-validated every 5 min while open). Shipped and loaded like the
  other cards (a second pilot's copy too, still admin only, still talking to the one app). Fits a 390 px phone.
- Web UI: JSON endpoints beside the page for the card, with the same ingress-only access: `GET api/uploads` (the PDFs
  on file and a seniority summary: counts and dates, no pilot) and `POST api/upload` (the page's own multipart form
  and checks; one save path for both). The Web UI page works as before.
- Dates of hire from the award (Ryan: the monthly award packet lists every pilot's date of hire): an uploaded award
  is read for dates of hire too, from a seniority section in the seniority list's layout or from the pilot lines with
  a labeled DOH. With 25 pilot rows or more it is merged into `seniority.json` (source `award YYYY-MM`): the later of
  the award's bid period and the seniority list's date is on top (a tie goes to the list), an award on top keeps the
  list's other pilots, and an award with fewer rows or an older award month never replaces what is on file. An award
  uploaded before 1.4.5 is read once at the first start. The upload's answer and the Web UI say where the dates of
  hire came from; counts only in the log. Built on made-up text (the real packet was not available): the first real
  upload's counts are to be checked.
- Pilot card: a pay line without a date of hire now says to upload the seniority list or the month's award on the
  Settings tab, and names the award when the dates of hire on file came from one (`list_source` on the pay line).
- Settings card relabeled for the Credentials heading: its button reads "Save credentials".
- Review fixes (1.4.5):
  - An award or pairings package that gives no text copy (damaged or password-protected PDF) is refused ("Not kept")
    instead of replacing the month's good PDF while its old text copy stayed beside it (the card then said "read" for
    a file never read). It is read under `<YYYY-MM>_<kind>.new.pdf` and deleted, as a refused seniority list is.
  - The card and `api/uploads` give the real size limit, 15.9 MB: the Supervisor's ingress proxy refuses a request
    over 16 MiB (HTTP 413) after it has all arrived, so a larger PDF is refused in the card before it is sent. The
    Web UI page says so too; the app's 25 MB check stays as the hard cap.
  - An award already on file is now read for dates of hire at the first 1.4.5 start also when a 1.4.4 seniority list
    is on file (the current list no longer ends the check before the award), once per file and parser.
  - An award on top keeps both pilots of a shared employee number: when the award lists only one of them, the other
    keeps the list's record and date of hire (PWA 3.B.1 longevity) instead of being found as the other pilot.
  - The card's progress and result lines are live regions (WCAG 4.1.3), so a screen reader announces the outcome.

## 1.4.4

- FW-0062 (Ryan, Nov 6): a pilot's month "Reconstructed from pairing crew lists" on the pilot card ends with a pay line in the schedule card's totals style: Trips, Credit, Block, Soft, Pay-Gross, Pay-Net (est. at your tax %) and Days Off, then "Year N (DOH YYYY-MM-DD) · $rate/cr h CA (PWA 3.C.4) · $rate/cr h FO (PWA 3.D.6)". Each trip is priced for the seat on its crew line, on its own date, for the longevity year from the pilot's date of hire (PWA 3.B.1, capped at 12): a Captain at the PWA 3.C.4 Captain rate plus $5.00 per block hour on a crew of 3 or more and never the 15% (PWA 4.O.1.a/b, "under all circumstances"), an FO or RO at the PWA 3.D.6 FO rate with the same RO $4.00, FO $3.00 and Extended Range +15% rules as your own schedule. Trips without a credit are listed and left out (Pay-Gross then says "k of m trips"); a trip without its block is named when its override is missing. Days Off are bid period days with no trip on the crew lists (reserve and training are not on them). Pay-Net follows your federal and state tax settings live. Without a date of hire the line shows hours and days and says to upload the seniority list. The numbers come from the Watcher (`pay_line` on `sensor.<prefix>_pilot_schedule`, `gross` on each priced trip), which picks the grid's trips the way the card does (newest read wins; a test runs both).
- FW-0062: the Web UI takes a new upload kind, "Pilot seniority list" (no month; an optional List date box). It is saved as `/share/flight_watcher/uploads/seniority_<YYYY-MM-DD>.pdf` with its text copy and read at once into `seniority.json` (employee number, seniority number, name, seat, equipment, date of hire), shared by every pilot instance; the page shows how many pilots were read, the list date and the newest date of hire on it. The new `seniority.py` reads the list by the shape of its values, not by column position (columns shift page to page and crowded values run together), keeps one row per seniority number, checks the repeats in the other sections, and breaks a shared employee number by last name. Tests use a made-up list.
- `pay.py`: the PWA 3.C.4 Captain table beside the PWA 3.D.6 FO table, `rate_for(year, iso, seat="FO")` (an RO is paid the FO rate), and `trip_gross(..., ca_rules=True)` for the Captain's PWA 4.O.1 override. The FO numbers and every existing caller are unchanged.
- Blank Block / Layover on rebuilt trips: package details are now looked up in each trip's own bid period (the grid's first row, Oct 31, is a trip from October's package, and the same id can be another trip in another month), by the exact id and then the id without its trailing letter. A second pilot's instance reads the package text and the seniority list from the shared uploads folder (`/share/flight_watcher/uploads`), so its rebuilt trips get them too.
- Review fixes (FW-0062):
  - Longevity year turns over on the DOH anniversary (PWA 3.B.1 from the date of employment; PWA 3.D.2 "completed one (1) year"), in `pay.doh_year` and your schedule card's `dohYear()` alike. The old 365.25-day count priced a trip that starts on the anniversary one year low when the span held fewer leap days (worst for a first-to-second-year FO: $90.00 instead of $203.93/h). A test runs both against the same dates.
  - The seniority list reader can no longer hang the Watcher: its row pattern fails a malformed line in linear time (it took seconds to hours per line with wide gaps), lines over 400 characters are not tried, and the Watcher stores a file's signature before re-reading it, so a slow or bad file is not read again at every start.
  - A refused seniority upload (no pilot rows, columns in another order, no text copy) is read under a temporary name and deleted, so it never overwrites the list on file's PDF or text copy, on the same day or later. After a parser change the Watcher re-reads the text copy of the file seniority.json names (keeping its upload time and typed list date), not the newest file.
  - A header whose columns are in another order (DOR before DOH, ALPA # before EMP #) is no longer misread: its rows are not read ("header-order") and the page says why. A DOH after the list date is not read ("future-doh") instead of being priced at Year 1.
  - A pilot row whose DOH wrapped onto the next line is joined and read; a numbered line with no date that cannot be joined counts in "lines not read". Parser version 2.

## 1.4.3

- Trade requests (Ryan, Nov 6): a crew-to-crew Trade never shows on the Open Time Requests list; it lives on the Tradeboard's My Requests page (TB_MyRequests.cgi, the page tb_frame.cgi?...&dp=mr loads). The Watcher now reads that page too (read only, a plain list GET through both URL guards, paced 1.5 to 3.5 s; its Cancel / Hide form is never submitted), lists each trade on `sensor.flight_watcher_ot_requests`, reads every 2 min while one is Processing or Pending, and pushes once when one is Approved or Denied (`event/request_decided`, type Trade, with Pay-Gross: the trips before 'With' are given, the trips after 'For' are taken). Its first read is kept privately in /share/flight_watcher/captures for parser checks.

## 1.4.2

- Request list (Ryan's Nov 6 Trade was not read): when the Open Time Requests page holds a request the parser does not recognise, or mentions a trade or Processing, the Watcher logs how many requests the page has against the rows it read and keeps a private copy of the latest such page in /share/flight_watcher/captures (never in git), so the row's wording can be added.

## 1.4.1

- Trade requests (Ryan, Nov 6): a crew-to-crew Trade on the Open Time Requests list ('Trade H3604:13NOV and H3659:18NOV With Emp #: ... For H3620:12NOV and H3620:15NOV') is now read like a swap: listed, polled every 2 min while it reads Processing (as well as Pending), and pushed once when Approved or Denied, with Pay-Gross. The trips before 'With' are given, the trips after 'For' are taken, and the same pairing taken on two days counts twice (the view page's legs were kept once per trip number).
- Pay-Gross (Ryan, Nov 6): a taken trip is priced in the seat FLICA's view page marks, (F) / (R) / (C), so an RO seat gets the PWA 4.O.1 $4.00 per block hour override (it was always priced FO, $3.00 on a 3-pilot crew). The H3604 RO swap's push was about $17 low.

## 1.4.0

- FW-0010 / FW-0026 (Ryan): the month finds files get a random key in their name (`finds_<YYYY-MM>_<key>.json`, key kept in /data/www_key and published only behind HA's login as the `file_key` attribute), so crew names and employee numbers no longer sit at a guessable /local/ address; the pilot's DOH moves out of the card files into `/data/cards.json` and reaches the schedule card as the `doh` attribute of `sensor.flight_watcher_state`. `sensor.flight_watcher_finds` keeps the last 30 finds as short rows under 12 KB, so the recorder stops dropping it; the files are written before the sensor and the card keeps its history while the Watcher is offline.
- FW-0012 (Ryan): Recall/O75 retires a CCR draft once its row is no longer a miss (PWA 22.G.2).
- FW-0013 (Ryan): the in-flight lookup rejects FLICA's no-schedule error page instead of storing "not in flight".
- FW-0014 / FW-0015 (Ryan): bid period month math for the pairings and award PDFs: a bid period that starts in the prior month is dated right, and December (starts Dec 2) parses.
- FW-0016 / FW-0017 (Ryan): the crew index waits for the award before reading a new bid period, an awarded period is never treated as held, no retries after departure, and FLICA's CKP check-pilot tag stays out of first names.
- FW-0019 (Ryan): the current month schedule shows FLICA's Block and Credit totals.
- FW-0024 (Ryan): the Pause switch and Would drop sensor publish their states on connect, so they no longer read unknown after a start.
- FW-0025 (Ryan): the pilot card adds one listener (one lookup per tap); a re-asked pilot draws the reply it already has.
- FW-0028 (Ryan): the Test / Confirm / Live swap mode select is retired (removed from discovery) and replaced by a read-only `sensor.flight_watcher_swap_mode`; nothing can submit to FLICA.
- FW-0029 (Ryan): stale "writes ship in v0.3" and pre-rename text removed from the UI and READMEs.
- FW-0047 (Ryan): Improved-Pay has a Net tick box to show Pay-Net instead of Pay-Gross.
- FW-0048 (Ryan): the auto drop mark on the schedule card shows only for the HA owner (never for a second pilot); the auto swap badge on Ryan's dashboard is Ryan-only.
- FW-0049 (Ryan): tickets can be edited while new or reopened, and deleted at any status (`<prefix>/ticket/edit`, `<prefix>/ticket/delete`; the folder moves to `tickets/.deleted/`, nothing is destroyed, the number is never reused). The fixed chip says "v" only before an app version number.
- FW-0031: HANDOFF.md refreshed for 1.0.0 to 1.4.0 (how tickets and releases run, open items by ticket, decisions).
- Tickets card (Ryan, Nov 6): a "Process Tickets in Claude Code" button at the far right of Submit a ticket opens Claude Code on a new session with this repo picked and the prompt filled in (`claude.ai/code/new?q=...&repo=AlohaFlyer/home-assistant-addons`; the Claude app takes the link on iPhone and Mac; nothing is sent until you tap send). On a phone it wraps under, right-aligned. Card option `claude_code_url` overrides the link.
- Recall/O75 (Ryan, Nov 6): a Refresh button re-judges every recall list on file against your current line now (recall/act {refresh}: no push, no FLICA read) and shows when it last checked (HST) and when Hark's last list came in (new `checked` and `received` attributes on `sensor.<prefix>_recall_o75`). If the Watcher does not answer in 15 s the card says so.
- FW-0053 (Ryan, Mac): Cmd+V pastes a copied screenshot into an open New ticket form as a photo (same 10-photo cap and checks); text still pastes into a field as usual.
- FW-0052 / FW-0055 (Ryan, Pako config): the tickets card moved to the bottom of the Settings tab under a divider and shows to Ryan only (on James's dashboard too); the new-ticket and ticket-fixed pushes open the Settings tab.
- FW-0054 (Ryan, Pako config): a new pairing he can take (the push already skips VAC, blocked, conflicting and FAR 117 failing trips) now buzzes: `flight-watcher-buzzer.wav` (ha/sounds, served at /local/) as the critical sound. iOS plays the default sound until the file is imported in the Home Assistant app.
- Request view (FW-0002 follow-up): FLICA's "Swap <given> For <taken>" sets the Pay-Gross sides, and crew scheduling's CS comment becomes the denial reason in the push.
- Review fixes: a ticket edit the Watcher refused or never answered keeps its text (Copy, or Add as a note); a ticket deleted while its edit form is open no longer freezes the tickets card; the push-isolation guard counts an MQTT trigger whose first topic level is a wildcard (`+/...`, `#`) as every pilot's.
- ha/ (FW-0036): a redacted snapshot of Pako's Flight Watcher automations, both dashboards and the aviation weather package, plus `ha/check_push_isolation.py` (and a test) that fails if any of James's pushes could reach Ryan's devices or the reverse.

## 1.3.0

- FW-0002 (Ryan): rebuilt schedules (a pilot whose FLICA schedule page is not readable, reconstructed from pairing crew lists) now use the same day-by-day grid as a readable schedule: weekday, day, Trip with its leg count and the pilot's seat, the Layover box across the trip's days, Block, Credit, Soft and Crew, over the whole bid period (its first and last day too). Layover, block and credit come from the month's pairing package when it is uploaded, else credit from the pairing file; blanks stay blank. Two trips read for the same days (a trade between reads) show the newer one in the grid and list the other under it, untotaled. Under a readable schedule the rebuilt grid folds away.
- FW-0003 (Ryan): a bug report or feature request takes up to 10 photos (Photo Library, Take Photo or Choose Files). The ticket goes first on `<prefix>/ticket/new` (with a client id and the photo count), then each photo on its own `<prefix>/ticket/image` message, so no message is larger than before; the Watcher caps 10 per ticket, keeps the size and JPEG/PNG checks per photo, ignores photos for an unknown ticket, and stores screenshot.jpg, screenshot_2.jpg ... with an `images` list (`image` stays the first). The card shows the count, lets you remove one, and says which photos did not go through.
- FW-0005 (Ryan): the finds card ("Recently added to the pot") shows only today's finds (HST day) and folds the rest of the month under one line ("41 earlier this month"), remembered per browser; it moves on at midnight HST without waiting for a new find. A month picked in the picker opens in full.
- FW-0006 (Ryan): one "Submit a ticket" button and one form with a Bug / Feature request choice (steps and expected only for a bug); typed text and photos survive switching.
- FW-0007 (Ryan): when a ticket is marked fixed the Watcher sends `<prefix>/event/ticket_fixed` {id, kind, title, reporter, version} once; HA pushes the reporter a quiet note (no sound) to check it.
- FW-0008 / FW-0009 (Ryan, iPhone): the version bar keeps Awarded-Pay-Gross and Improved-Pay-Gross together on their own line, and the totals keep Pay-Gross and Pay-Net together on one line; no label is split from its value. Footer warnings (FLICA mismatch, Block Avail at 0 or below, Need 30 h off within 48 h) show red again, and Days Off is escaped.
- FW-0004 (Ryan): the schedule card no longer paints days inside a 30 h+ break (FAR 117.25(b)) teal; the FAR-30/7 column (check mark and date) says the same. A thin teal edge left of the day stays as the marker, and weekend blue and holiday yellow now show on those days too.

## 1.2.2

- Request push, checked on the real FLICA page (19 requests): the list names no trips, so a decided request's trips (and the Pay-Gross of an Approved one) now come from its own read-only view page (its ShowRequest link, GET only, both safe_get guards; never the QuickDelete link beside it), read once per decision, paced. Each request is keyed on FLICA's own request id (the link's TimeStamp), so clearing one never renumbers another; decisions 1.2.1 already pushed are not pushed again. The push no longer shows the page footer as its detail. The first view page is saved privately to /share/flight_watcher/captures for parser checks. Pay-Gross sides (review): an Add or Drop request's type decides its side, a swap's sides come from the trips Ryan held when he filed (page words only when no schedule version is on file and they name both sides), and the view page's labels are strict (drop / give up / add / pick up / take, right before the trip; a header such as 'Add/Swap/Drop requests' or a 'From:' line never labels one), so a layout surprise gives no amount rather than a wrong one. A decision is remembered under both its id and its content key, so a read that falls back to content keys never pushes it again.

## 1.2.1

- Pay-Gross in the request push (Ryan): an Approved request carries `pay` {delta, delta_text, parts [{trip, start, side drop|add, gross, credit}], rate, year}: + for a pickup, - for a drop, the net for a swap. New `pay.py` is the schedule card's tripFull() in Python (credit x PWA 3.D.6 FO rate by longevity year, the package credit carrying the PWA 4.C.3 5:00 minimum; PWA 4.O.1 IRO $4.00 RO / $3.00 FO per block hour and Extended Range +15%); a test runs the card's JavaScript beside it. A trip given is priced from Ryan's own trip record (FLICA credit, block, seat), a trip taken from the month's pairing package (FO). Which trip was given: the page's own words, else the request type, else (swap) the trip on the schedule version in force when he filed. Longevity year and ER list from the HA helpers (new `homeassistant_api: true`), else the DOH in /data/cards.json. No amount when a trip cannot be priced.

## 1.2.0

- Request decisions pushed (Ryan): the Watcher reads FLICA's Open Time Requests list (`/full/mobileotrequest.cgi?BCID=<pot folder>&From=MainMenu`, GET only, both safe_get guards; the per-row Approved / Denied links delete a request on a GET and are never followed) every 15 min, every 2 min while a request is Pending, and first thing after a yield to Ryan's own FLICA login (when he files them). A swap, add or drop request that turns Approved or Denied, or first shows up already decided, fires `<prefix>/event/request_decided` once {key, date, time, type, status, trips, detail, bcid, url}. Each decision is pushed once ever (kept in state 60 days after it leaves the list), so an error page or a cleared request never brings a second push; a request is keyed on its own content (date, time, type, trips), not its place on the page. The feature's very first read pushes only decisions filed in the last 6 hours; a bid folder that opens later is read in full. A page that is not the request list (maintenance, error, interstitial) is not a read, a list gone empty must read so twice, and a failed pass leaves the sensor as it was. Reads are paced 1.5 to 3.5 s apart. Not covered yet: requests filed in the close-in folder (its BCID is not known). `sensor.<prefix>_ot_requests` = pending count, attributes = the last 20 requests. The first read of each folder saves a private copy to /share/flight_watcher/captures for parser checks. HA automation "Flight Watcher request decided" pushes it to Ryan's iPhones.

## 1.1.2

- Tickets card (Ryan): completed tickets (fixed or closed) fold away under "N completed" (noting how many still wait for your verify); open ones stay in the log. The header reads "N open · N completed". The fold remembers whether you opened it.

## 1.1.1

- FW-0001 (Ryan, iPhone): the finds card ("Recently added to the pot") cut its table off after the Trip column on a phone, because the month picker took a column of its own beside the table. The picker now sits in the card's top-right corner and the table gets the full width (it scrolls sideways on a phone). Times are built from parts, so iOS Safari no longer shows "Nov 5 at 12:23" (wider rows); midnight shows 00:xx.
- The stopped note for missing credentials points to the dashboard Settings tab.

## 1.1.0

- Settings card on the dashboard (Ryan, for a pilot without Home Assistant admin access): `custom:flight-watcher-settings-card` edits the FLICA and CrewTrac usernames and passwords and the last name right on the dashboard. The form is sealed in the browser (AES-256-GCM, its key wrapped with RSA-OAEP SHA-256) with the Watcher's own public key and sent with mqtt.publish to `<prefix>/settings/set` as `{"enc": ...}`, so Home Assistant's history database, logs and the MQTT broker only ever hold ciphertext. Each instance keeps its key pair in /data/settings_key.pem (mode 600) and publishes the public half (`pubkey`, `kid`) and the last result (`result`: saved / nothing new / refused) on `sensor.<prefix>_settings`. A sealed message older than an hour, tampered with, or sealed for another key is refused. A second pilot's card copy writes to his own Watcher. On a plain http address (no browser crypto) the card sends the fields unencrypted instead (Ryan: trusted users only). New dependency: cryptography 43.0.3.

## 1.0.1

- Settings tab (Ryan): the Web UI (Settings > Apps > Flight Watcher > Open Web UI) opens on a Settings form for the FLICA username and password, the CrewTrac username and password and the last name. Saved to /data/creds.json (created mode 600), which wins over the Configuration tab; a blank field keeps what is saved; passwords are only shown as set / not set and never logged. Saving restarts the Watcher; a new FLICA username or password clears only a no-credentials or rejected-login stop (no Re-arm needed). A CAPTCHA/MFA stop or any other park still waits for Re-arm, whatever is saved. "Clear saved values" forgets creds.json so the Configuration tab applies again. Any restart (a save, an app restart) now keeps a running 30-min yield to your own FLICA login and a re-login back-off instead of loading FLICA at once. The stopped note points there.

## 1.0.0

- Renamed FLICA Watcher to Flight Watcher everywhere (Ryan). New app: folder `flight_watcher/`, slug `flight_watcher` (Supervisor `43b22650_flight_watcher`). MQTT prefix `flight_watcher` (second pilot `flight_watcher_<name>`), device `flight_watcher`, entities `*.flight_watcher_*` (rule switches `switch.flight_watcher_rule_<id>_live` for every instance), folders `/share/flight_watcher/` and `/homeassistant/www/flight-watcher/` (`/local/flight-watcher/`), cards `flight-watcher-<x>-card.js` with elements `custom:flight-watcher-<x>-card`, helpers `input_*.flight_watcher_*`, localStorage keys `flight_watcher_*`, card event `flight-watcher-pilot` (per pilot in a second pilot's copies, which also open their own `/flight-watcher-<name>/recall`), env vars `FLIGHT_WATCHER_*`, logger `flight_watcher`. Names of FLICA itself (the website, `sensor.flight_watcher_flica_fetches`) and FW- ticket numbers are unchanged. Entries below keep the names of their time.
- Migration (`migrate.py`, first start): imports the old app's /data from `/share/flight_watcher/import/data` (exported by flica_watcher 0.10.4; never options, FLICA cookies or creds.json, so credentials are entered again), moves `/share/flica_watcher/*` and `/homeassistant/www/flica/*` across, and the DOH falls back to the old `flica-schedule-card.js`. The import is staged in /data/.import.tmp and redone if cut short; a /data started fresh before the export arrived is replaced by it on the next start (.fresh); the old app re-exports (SQLite backup API, WAL included) on every start until .imported exists.
- Entity ids keep their old name-based suffixes (`ENTITY_SUFFIX`: `sensor.flight_watcher_recall_o75`, `would_drop`, `re_arm`, ...) so the cards, automations and the renamed history line up; the unique_ids and topics keep the short oids. A second pilot's cards register in the card picker under their own types, "(<name>)" in the name.

## 0.10.3

- Entity ids (Ryan): Home Assistant now ignores `object_id` in MQTT discovery, so new entities were named from the device (`sensor.flight_watcher_*`). Discovery also sends `default_entity_id` (`<component>.<prefix>_<id>`, rule switches `switch.flica_rule_<id>_live`), so new entities come up as `*.flica_watcher_*` again and a second pilot's as `*.flica_watcher_<name>_*`. `object_id` stays for older HA. Existing entities keep their registry ids.

## 0.10.2

- Dashboard cards ship with the app (Ryan): every `flica-*.js` card is now in git (`flica_watcher/www/`) and the add-on copies it to HA's `www` folder (`/local/`) on each start, writing only files that changed. A second pilot's copies (`flica-*-<name>.js`, formerly made by hand with `/config/www/make_pilot_cards.py`, now `cards.pilot_copy`) are written too when `second_pilot` is set. One dashboard resource, `/local/flight-watcher-loader.js`, reads `flight-watcher-cards.json` (card list and app version, fetched with cache `no-store`) and imports each card with `?v=<app version>`, so a card change reaches every browser with the app update and no resource needs a manual `?v=` bump. The schedule card's date of hire is personal data and stays out of git: it is kept in `/data/cards.json` `{"doh": "YYYY-MM-DD"}`, taken once from the card already on disk.

## 0.10.1

- Crew index (Ryan): Ryan's instance rebuilds any HNL A330 pilot's month from the crew lines on the pairing pages. Trip instances come from the card's pairing files (www/flica/pairings_<YYYY-MM>.json, on or after Oct 31 2026; a day number past the month's end, or a late number ahead of a smaller one, is last month's, `D<n>` next month's; trip end = start + rel_days). Runs at the first check after 00:00, 06:00, 12:00 and 18:00 HST and on the new button "Update schedules" (`flica_watcher/crew_scan/press`): at most 300 pages per run, read 50 per check between pot checks, 1.5 to 3.5 s apart, GET only; order: never read (soonest first), failed over a day ago, departing within 72 h and read over 6 h ago, departed but read before departure (once), then the oldest-read future trips; a departed trip read after departure is never read again. A killed, expired or captcha page ends the run. Results in SQLite (crew_idx, crew_emp), `sensor.flica_watcher_crew_index` (coverage %, `flica_watcher/crew_index`) and one Markdown file per month in /share/flica_watcher/crew_index/<YYYY-MM>.md (a section per pilot, Date | Pairing | Seat | Route | Days).
- Pilot lookup: every `flica_watcher/pilot_schedule` publish carries `reconstructed` (that pilot's trips in the shown month from the crew index: pairing, start, end, seat, route, checked_at), `reconstructed_coverage_pct` and `reconstructed_month`, also when FLICA's schedule page is hidden or errors.
- Tickets (Ryan): bug reports and feature requests on `<prefix>/ticket/new` {kind bug|feature, title, narrative, steps?, expected?, page?, version?, image? (JPEG or PNG data URL, 2 MB max)}, numbered FW-0001 on across both pilots and kept in /share/flica_watcher/tickets/FW-nnnn/ (ticket.json, screenshot.jpg or .png). `<prefix>/ticket/act` {id, action triage|progress|fixed|verify|reopen|close|note, text?, version?} moves the status (new, triaged, in_progress, fixed, closed, reopened) with a history line. `sensor.<prefix>_tickets` (open count; `<prefix>/tickets` lists all tickets on Ryan's instance, a second pilot's own only), `<prefix>/event/ticket_new` on each new one, `<prefix>/event/ticket_error` when one is refused.

## 0.10.0

- Renamed Flight Watcher (Ryan): app, device and Web UI names; entity ids unchanged.
- Second pilot (Ryan, for James): the add-on runs one `watcher.py` per pilot from a launcher (`run.py`). Option `second_pilot` (lowercase letters, digits, underscores, e.g. `james`) starts a second Watcher beside Ryan's with its own data folder (/data/<name>), its own MQTT prefix (`flica_watcher_<name>/...`), its own HA device "Flight Watcher (<Name>)" and entities `sensor.flica_watcher_<name>_schedule`, `switch.flica_watcher_<name>_hunt_mode` and so on (rule switches `switch.flica_watcher_<name>_rule_<id>_live`). Ryan's instance, topics, entity ids and the ingress Web UI are unchanged.
- Credentials over MQTT: `flica_watcher_<name>/settings/set` {username, password, ctweb_username, ctweb_password, my_name} (any subset, blanks ignored) are kept in /data/<name>/creds.json (mode 600, never in the add-on options) and the Watcher restarts itself to use them; `.../settings/state` and `sensor.flica_watcher_<name>_settings` say who is configured (has_password, never the password). Without credentials the instance waits in state `needs_settings` instead of parking. Ryan's instance takes the same topic (creds.json overlays the add-on options).
- Per pilot files: finds_<YYYY-MM>.json go to www/flica/<name>/, captures and uploads to /share/flica_watcher/<name>/; pairings_<YYYY-MM>.json stay shared. The launcher restarts a Watcher that exits (10 s, 60 s after a crash within 30 s of starting) and passes SIGTERM on to both.

## 0.9.4
- Finds history (Ryan): finds are kept 24 months (prune) and written one file per HST month, www/flica/finds_<YYYY-MM>.json, for the finds card's month picker (this month and last month on every check, all 24 once per start).

## 0.9.3
- Recall / O75: a trip or vacation in the way of the pairing is not a miss (it would have needed a removal under 22.G.2.f/g, and a junior volunteer clean under 22.G.2.e goes first), so the row is NO with the reason; only eligible days junior to you are MISSED.

## 0.9.2
- Recall / Over 75 miss check (Ryan): Hark posts the daily HNL recall list (Alaska Flight Ops SharePoint) to an HA webhook that lands on `flica_watcher/recall/set`; `recall.py` judges every Recall / Over 75 award against Ryan's line per PWA 22.G.2.d-g, 22.E, 4.M, 4.N, 10.E.1.a and FAR 117 (MISSED / POSSIBLE / NO with the reason) and publishes `sensor.flica_watcher_recall_o75`; a miss fires `flica_watcher/event/recall_miss` once, and approving the CCR narrative on the dashboard (`recall/act`) fires `flica_watcher/event/recall_approved`. The app files nothing.

## 0.9.1
- Monthly PDFs parsed (Ryan): the pairings package becomes the schedule card's pairing file (www/flica/pairings_<YYYY-MM>.json, A332 HNL, checked 83 of 83 against the hand-built November file, plus the H3665 charter it lacked) with each pairing's block and HST duty times; the PBS award becomes the month's version .001 (Ryan's row only), renumbering later versions. December's bid period (Dec 2 to 31) and its 33L equipment code are handled. The app now maps HA's config folder to write the pairing file.

## 0.9.0
- Schedule versions (Ryan): every change FLICA shows to a month (trips added / dropped / swapped, day codes, any trip's block, credit, seat or times, FLICA's Block / Credit) is saved as a numbered version, MM.NNN (11.001 = first on file). Published on `sensor.flica_watcher_schedule_versions` (awarded version plus the latest 24 per month) and `flica_watcher/event/schedule_version`. November's Nov 2 to 4 versions are rebuilt from HA's recorder (11.001 H3628, 11.002 H3601, 11.003 H3620). FLICA's days_off is ignored (it differs between FLICA's own pages).
- Improved pay: the schedule card prices the awarded and current versions with today's pay settings and reports them on `flica_watcher/improved/set`; kept per month and published as `sensor.flica_watcher_improved_pay` for the Details bar chart.
- PDF upload (Ryan): the Web UI takes the monthly award and the pairings package PDFs (kept in /share/flica_watcher/uploads with a pdftotext copy; poppler-utils added). Parsers follow once real PDFs are on file.

## 0.8.7
- FLICA fetch counter (Ryan): every page the Watcher loads from FLICA is counted and published as `sensor.flica_watcher_flica_fetches` (total_increasing), for hourly / daily / monthly utility meters on the dashboard.
- Schedule lookup accepts Ryan's own page (no Emp# on it).

## 0.8.6
- Schedule codes read from Schedule Lookup are URL-decoded (October showed O%2FK for O/K).

## 0.8.5
- October and December (Ryan): Tools > Schedule Lookup for Ryan's own employee number lists every month FLICA holds (1026, 1126, 1226 once published); each month other than the current one is read with bd=MMYY (GET only) and stored beside it, so the FAR 30 in 7 / 100 in 672 columns can look back and forward. The employee number is taken from the Tradeboard page header; the Schedules-menu route stays as the fallback.

## 0.8.4
- October: FLICA only builds the Schedules menu tree inside the real menu frame (a plain GET returns the 8 KB skeleton), so the Watcher loads the main menu in a tab and reads the frame (read only, no clicks) to find the tokened October link.
- Pilot lookup: the Schedule Lookup prompt page is saved once to the private share folder, to see whether FLICA offers a name search for pilots not yet in the crew directory.

## 0.8.3
- October: the Schedules-menu link is matched with the query parameters in any order (any month's link carries the same session token), the menu page is saved (token masked) for checking, and the previous-month read re-runs at start and every 30 min until October is in.

## 0.8.2
- Look anybody up (Ryan): `flica_watcher/pilot/set` accepts {"q": "last, first | first last | employee number"}. The Watcher keeps a crew directory (crew_dir) of every CA / FO / RO with a number it has seen on pairing pages (pot details, pilot schedules) plus the pickers and captains already recorded; one match reads that pilot, several are offered to pick from, none asks for the employee number.
- Pickers (Ryan): `min_s` = the pilot's fastest pickup, for a Fastest Pickup Speed column.

## 0.8.1
- Pilot schedule: tries both Schedule Lookup URL shapes (GO=1, then bd=MMYY) and logs what a non-schedule page said, as the InFlt reader already did.

## 0.8.0
- Pilot schedule (Ryan): tap a pilot's name on the FO / RO pickers list or in Recently added and the Watcher reads that pilot's current month from Tools > Schedule Lookup plus each pairing's page (read only, up to 8 pairings, cached 6 h) and publishes `sensor.flica_watcher_pilot_schedule` (days, items with block / credit / soft / legs / crew, totals); the dashboard draws it in the schedule-card calendar shape under Recently added. MQTT `flica_watcher/pilot/set` {"emp"}.

## 0.7.6
- Pickup Speed vetted (Ryan): a trip enters the pot at FLICA's alert time when that is earlier than the Watcher's first sighting (alert emails naming a known find now record it), and it is picked up somewhere between the last check that still listed it and the check that found it gone, so the speed is the middle of that window with a plus/minus of half the window (`dwell_s`, `dwell_pm_s` on each find). Every scored pickup is recomputed once on start; the pickers' Avg Pickup Speed follows. Checked against the log: alert emails wake a check within a second, so first sightings already matched the alert times to the second.
- Pickers (Ryan): each scored pickup logs its layover (or turn station); `sensor.flica_watcher_pickers` rows carry `lays` ([station, count], most picked first, ties by most recent) and `last_lay` for the dashboard's Common Layover column. Existing pickups are back-filled from the finds on start.

## 0.7.5
- Fix: `charter_regular` adds stations to the built-in regular list instead of replacing it (an option saved before 0.7.4 re-flagged every HNL-PPT leg); listed flights that no longer qualify are dropped on the next scan.

## 0.7.4
- Charter watch scans from the 1st of the current month (Ryan: past charters stay visible, e.g. the SIN run) to 30 days ahead; entries are kept through the following month.
- Charter watch works against the real CrewTrac page: rows live in a second table (REPORTINFO) under a separate header table, so rows are matched by shape; same-station A330 legs (HNL-HNL test or maintenance flights) are not flagged.

## 0.7.3
- Charter watch debug: the CrewTrac login page, login response and first report page are saved to the private share folder and summarised in the log (field names only, never values); a report served as the not-logged-in page counts as a dropped session.

## 0.7.2
- Fix: CrewTrac login was judged refused because the menu page says "Change Password"; logged in now means Sign Out present and no password input.

## 0.7.1
- Fix: the first charter scan runs at start (0.7.0 waited 6 h before the first one).
- October (Ryan): the previous-month read now also follows FLICA's own Schedules menu (leftmenu.cgi) to the desktop schedule page for that month (tokened link, GET only); the page is saved privately so the parser can be written against it.

## 0.7.0
- Charter watch (Ryan): every 6 h, in its own thread and its own session, the Watcher logs into CrewTrac Web (ctweb.hawaiianair.com, options `ctweb_username` = employee number and `ctweb_password`) and reads Options > Scheduled Service for HNL departures and HNL arrivals over the next 30 days, one date per query (GET only). A330 rows (Eqpt 332/333) with a 99xx flight number or an end outside `charter_regular` (editable station list) are kept on `sensor.flica_watcher_charters` (items with date, flight, route, scheduled, eqpt, tail, why, first_seen, gone) and each new one fires `flica_watcher/event/charter` once. Button "Scan CrewTrac charters now". No credentials = sensor says not configured, nothing else changes.
- Own trips (Ryan): a trip in progress is re-read every 6 h and a finished trip once more the day after it ends, so Block / Credit show the actual (final) times; own_trips carry `read_at` and `final`. A trip that has started loses its "would trade" / "would drop" mark (it cannot be traded or dropped any more).

## 0.6.0
- Drop watch (Ryan), Test mode: mark a trip "would drop" on the schedule card (down arrow next to the trade arrows, MQTT flica_watcher/drop/set). Each check the Watcher checks NET RESERVES on every day of the trip; the first time all are green it pushes event/drop_ready (HA automation "FLICA watcher drop ready") and composes a draft drop request (sensor.flica_watcher_would_drop: keys, ready, tests). Nothing is filed; a red day re-arms the push. The DROP review page is not mapped yet, so the draft form is a guess modelled on the mapped SWAP form.

## 0.5.6
- Email-caught and unknown-seat pickups with a single FO/RO name are scored from the FLICA alert time (flagged approximate); existing ones rescored once. New picker_log table (400-day keep) gives per-picker month and year pickup counts (pickers sensor: month_n, year_n).

## 0.5.3
- In-flight lookup moved to inflt.py. The Schedule Lookup page is accepted only when it carries pairing links (a forwarding or prompt page counts as a failed try and its text is logged, three times at most); the month URL shape (bd=MMYY) is tried as well. 0.5.2 marked pickups "no trip that day" on such pages; those verdicts are re-checked once.

## 0.5.2
- InFlt (Ryan): for every filled pickup with a known picker, the Watcher reads that pilot's month on Tools > Schedule Lookup (cmschedules.cgi, read only), the legs of the pairing covering the pickup day, and marks the pickup in flight when the trip left the pot between a leg's block-out and block-in. Layover rest and ground time do not count; no trip that day = not in flight. Three lookups per check; saved pickups are back-filled the same way. Finds carry `inflt` / `inflt_trip`; pickers carry `inflt_n` (dashboard columns InFlt and InFlt Pickups).

## 0.5.1
- Fix: submit.py was missing from the Dockerfile copy list, so 0.5.0 failed to start (ModuleNotFoundError). watcher.py is unchanged (its VERSION attribute still reads 0.5.0).

## 0.5.0
- Swap mode select (Test / Confirm / Live), Test only in this version: for every new swap idea the Watcher composes the exact FLICA swap request it would file (one POST to mobileotswap.cgi, mapped read only with Ryan on 2026-11-03), logs it and keeps the last 20 on sensor.flica_watcher_swap_test_requests. Nothing is sent; Confirm and Live are refused until the send path exists and Ryan turns it on.
- Close-in rule: a swap whose trip reports inside 16 h is composed for the Close-in folder and is never sendable until that folder's BCID is read.
- The Watcher never fetches a request-list link carrying QuickDelete (those delete a request on GET).
- Schedule read: the other URL shapes are probed once a day instead of on every read (3 GETs saved per read).

## 0.4.21
- Alert emails (Ryan): a pairing the Watcher already knows that FLICA alerts on again gets its pairing page re-read, so the pickup record shows who holds it now.
- Schedule read: two more mobile URL shapes (BlockDate=MMYY, and no BCID) tried first; the desktop scheduledetail page is kept last since this session gets a reCAPTCHA page there (never bypassed).

## 0.4.20
- Schedule read tries the desktop schedule page first (`scheduledetail.cgi?BlockDate=MMYY`, the Schedules > month link, no token needed): it carries FLICA's Block / Credit / YTD / Days Off and every leg, for this month and last month. Its HTML is saved once to /share/flica_watcher/captures for parser work.

## 0.4.19
- Duty periods carry their block (`blk`, minutes) so the schedule card can put each duty's pay in the month its segments originate (PWA 4.A) and add vacation days at the PWA 6.J value. Cached trips are re-read once.
- Schedule read prefers the mobile view that carries FLICA's Block / Credit / YTD totals (tries the pot's BCID prefix 003 too; the OT drop view has no totals), so the card can check its month totals against FLICA.

## 0.4.18
- Picker speed (Ryan): a `pickers` table per FO/RO employee number records how long each trip they took sat in open time (first seen to gone). Scored once per find when the seat was known and the find was seen in the pot (email-caught finds have no dwell). Finds carry `picker_avg_s` and `picker_n`; the dashboard shows the average right of Picked up by, bold under 1 min. sensor.flica_watcher_pickers lists every picker (name, employee number, position, n, average), fastest first.

## 0.4.17
- Own trips carry `crew` (position, name, employee number) so the schedule card can show the roster on hover.
- Previous month schedule: tries the MainMenu URL shapes with the lower bid-period number (the OT drop view only offers open months); logs the candidates once an hour until one parses.
- Employee numbers back-filled once (Ryan): finds whose pickup or captain was recorded before 0.4.11 get one read-only pairing page read (3 per check) to add the numbers.

## 0.4.16
- Previous month schedule (Ryan): read once a day from the mobile schedule page with the bid-period number one lower (Oct = 001.151), kept in sensor.flica_watcher_schedule with the current and next month, so the card's FAR 117 windows (30 in 7, 100 in 672) that reach back into last month have data. Own trip times are read for those trips too (cached).

## 0.4.15
- Own trip times carry `duties` (Ryan): duty periods from the pairing page legs (day offset, first departure, last arrival, station, local times; a gap of 8 h+ at a station is a layover). The schedule card uses them so a 30 in 7 (FAR 117.25(b)) earned on a long layover counts, and for FAR-30/7 and FAR-100/672 columns. Cached trips are re-read once.
- Own trips carry `seat` (RO / FO / CA) from the pairing page crew list, matched on the new `my_name` option (a surname). The card shows the RO override add-on only on trips where Ryan is listed as RO.

## 0.4.14
- Reserve grid: parse reserveGridService.cgi JSON by its real shape (root.data[], statusColor.net, avl/odp), so the grid updates every 5 min from JSON instead of waiting on the 30 min page render. Rendered page stays the fallback.

## 0.4.13
- Reserve Grid (Ryan): each check reads NET RESERVES per day with FLICA's color (green = drop or swap off that day can be approved; red/black = add only) from reserveGridService.cgi, cross-checked against the rendered page every 30 min. sensor.flica_watcher_reserve_grid carries days {date: {net, color}}.
- Swap ideas apply the grid rule: the candidate must share a day with the marked trip (it may move earlier or later), and every day moved off must be green. Blocked ideas stay in the sensor with the red days named; they push the moment the grid turns green.

## 0.4.12
- Map swap pages also renders the Reserve Grid (a JS page) read only and saves its HTML and API calls, so the grid reader can be built from the real page.

## 0.4.11
- Employee numbers (Ryan): the pairing page lists crew as "FO 10001 Name", so the pickup text and the captain now carry the number, e.g. "FO Doe, Jane (12345)". Rosters still compare by name, so old finds keep working; the number appears on each find's next pickup check.

## 0.4.10
- "Map swap pages (read only)" button (diagnostic): on the next check the Watcher walks from the main menu, the pot, the OT drop view and the Tradeboard to the open time request pages, GETs each page that passes swapmap.safe_get (no POST, no filled Add/Drop list, no action words), and saves the HTML and a form summary to /share/flica_watcher/captures/swapmap (private, never committed). Groundwork for live swap; nothing is submitted.

## 0.4.9
- Swap ideas (Ryan): tap a trip on the schedule card to mark it "would trade" (`flica_watcher/trade/set`, sensor.flica_watcher_would_trade). Every check, open time and Tradeboard pickups are compared with each marked trip (swap.py): better = soft time up by 0:30+, or credit up by 1:00+ without losing soft time. A candidate must still be legal with the marked trip removed (FAR screen plain OK, so 11 h domicile rest; no VAC, no blocked day, no clash with his other trips). Ideas are on sensor.flica_watcher_swap_ideas and each new one is pushed once (`flica_watcher/event/swap`).
- Auto swap switch, DRY RUN ONLY: with it on, the push also says exactly what a live swap would submit (cap 1 a day). Nothing is ever submitted to FLICA; live swapping needs Ryan to confirm a dry run first and the FLICA swap form mapped read only.
- Own trip times now keep credit and soft time (re-read once).

## 0.4.8
- Fix: FLICA shows a changed pairing with a letter suffix (H3815B). It was not recognised as a trip, so it ended on its first day: days off, Fits, FAR and the own trip times were wrong around it. Pairing IDs now allow one trailing letter.

## 0.4.7
- Own trip times for the schedule card (Ryan): report and block-in of each of Ryan's trips (already read for the FAR screen) are published on `flica_watcher/own_trips` (sensor.flica_watcher_own_trip_times). The card shows report and release times and suggests tag-on pairings from the monthly pairing package.
- Fix: the version reported in the state sensor was stuck at 0.4.4.

## 0.4.6
- Tradeboard pickups in the pot list (Ryan): every Tradeboard post with "Pickup Trip" is read once (pairing page: captain, times, crew) and published on `flica_watcher/tradeboard/state` (sensor.flica_watcher_tradeboard) with the same fit, VAC, blocked-day and FAR screen as open time rows, plus `src: T`. The dashboard merges them into "Open time pot / Tradeboard Pickups" with an O/T column. New posts still push as before (same VAC/blocked rules).

## 0.4.5
- Fix (Ryan): blocking today did not stick after 14:00 HST. The container runs UTC, so "today" was already tomorrow and today was pruned as a past day. Today, month rollover and the pot month pick now use Honolulu time.

## 0.4.4
- Blocked days (Ryan): tap a day on the dashboard schedule card to block it (no pickups wanted: a trip you won't trade, VAC you can't swap, a day you don't want to work). The card publishes `flica_watcher/blocked/set` {"date"}; the app keeps the list (sensor.flica_watcher_blocked_days, past days drop off) and flags every pot, tradeboard and alert row that touches one as `blocked`. The dashboard hides those rows with VAC ones, and the new-pairing and hidden-trip pushes skip them, unless "Show VAC/blocked" is on.

## 0.4.3
- Fix: some pairing pages carry a second "Pay : 1000000001" (an id), which became a 158:39 credit. Only H:MM-sized values count now, and the first Pay is the credit.
- Pairing detail gives the trip length (`days`) from the leg day codes, so email finds show Days.
- Email finds refresh credit, days, block and TAFB from the page on their pickup check; existing ones are re-read once.
- Hidden trips push (Ryan): the first time a trip that left the pot still shows an open FO/RO seat, the Watcher publishes `flica_watcher/event/hidden`; HA automation "FLICA watcher hidden trip" sends a time-sensitive push.

## 0.4.2
- Fix: an email find that had already left the pot took its crew roster after the pickup, so the diff read "left pot, same crew". Those finds now skip the roster and list the FO/RO names (not bold, seat unknown). Finds 0.4.1 marked that way are re-checked once.

## 0.4.1
- Missed trips from FLICA alert emails (Ryan): Home Assistant forwards each email that lands in the FLICA alerts Gmail inbox (<redacted-email>, IMAP) to `flica_watcher/email/alert` (automation "FLICA alert email to Watcher"). Pairings it names that the pot watch never recorded (they came and went between checks) are added to finds with `source: email`. Each gets one read-only detail GET (CA, times, crew roster). One already out of the pot is stamped gone and its pickup is tracked like any other find. The email also wakes the Watcher for an immediate check.

## 0.4.0
- Who picked it up, by seat (Ryan): every pot pairing now keeps its crew roster (`crew`) while it is in the pot. When it leaves, the roster is compared with the pairing page: the FO or RO who is new is the pickup (`known`, shown bold with the seat). This works whether FLICA showed the open seat as "FO Open" or did not list it at all. Status `unchanged` = left the pot with the same FO/RO crew. Pairings cached before 0.4.0 are re-read once to get their roster.
- Dashboard adds a "Picked up" time column: when the trip left the pot (within one check interval).

## 0.3.9
- Check now is a full refresh (Ryan): besides the pot it re-reads the schedule, Ryan's own trip times, every pot pairing's detail (CA, times, open seat), pending pickups and the Tradeboard, at most 12 detail pages per kind, still 1.5-3.5 s apart.
- Finds still in the pot keep their stored row current every check (CA, details, fit, Prem), so the Recently added table never shows a stale or blank CA. The finds sensor is published every check.

## 0.3.8
- FAR column (`far` on every pot and tradeboard row, new far.py): FAR 117 screen against Ryan's own trips. It checks 10 h rest before and after (release = last block-in + 15 min), 30 h free in every affected 168 h, and 100 h flight time in 672 h. It notes the company 11 h rest when FAR passes. Shows OK, the problem (e.g. "Rest 9:45 before"), Conflict, or ? when times are missing. Cumulative FDP (60 h/168 h, 190 h/672 h) is not checked yet.
- Ryan's own trip times (check-in, final arrival, block) are read once from each of his pairing pages (read only, at most 3 per check, cached).
- `vac` on every row: the trip touches one of Ryan's VAC days (the dashboard hides these by default).
- Pickups record whether the open seat was known (`pickup_known`), so the dashboard bolds the name of whoever took it.

## 0.3.7
- Pickup tracking (Ryan, Nov 1 2026): when a find leaves the pot, the Watcher GETs its pairing page (read only) and records who now holds the FO/RO seat that was open, plus the CA. A seat that still shows Open on the pairing page while the trip is not in the open time pot is stored as status `open` (suspected hidden by scheduling; the dashboard row turns light red) and rechecked every 20 min for 2 h, then hourly until it is filled or the trip starts. Gone finds from before 0.3.7 are back-filled once.
- The pairing detail now records which seats were open (`open_seats`). Finds carry `prem` (FLICA's Prem column X), `captain` and `picked_by`.

## 0.3.6
- Every pot row and alert carries `turn` (where the trip lands away from HNL, e.g. PPG, or PPG/PPT for several stops) and `route` (HNL-PPG-HNL), read from the pairing detail page already being fetched. The dashboard and push show a no-layover turn as **PPG** instead of "none" (Ryan, Nov 1 2026).

## 0.3.5
- Fixes the false "pot table layout changed" parks (9 on Nov 1, 2026, about 4.5 h blind). Root cause: FLICA never closes a pairing's <tr>, so every later row nests inside the first and the column count in the hash grew with the pot. The hash now counts only the row's own cells. Stored hashes are cleared once (fingerprint v2).
- Self re-arm: if the hash still changes but every pot row still parses (pairing, start date, credit), the new layout is accepted and logged instead of parking. Only a page that no longer parses parks.
- Fit is "No sched" instead of blank when no schedule month covers the dates, so blank never reads as fits.
- The "starting" note clears after the first good check.
- HA side (not in this repo): stale push now waits 30 min or 2.5x the normal interval and goes to both phones with a Re-arm button; the clock card shows BLIND in red past that limit.

## 0.3.4
- Slider ranges per Ryan: hunt 5-90 s (was 15-300), normal 1-20 min (was 1-60). Stored values outside the new range are clamped. Each wait is still randomized +-30 % around the setting.

## 0.3.3
- Every pot row now carries captain, check-in (report), block, TAFB, soft time and fit, not only new-pairing alerts. Detail pages are read once per pairing (cached until it leaves the pot), at most 8 per check, 1.5-3.5 s apart. Fit is re-tagged every check. (Claude, owner from 0.3.3; see FLICA_Watcher_Shared_Context.md.)

## 0.3.2
- Days off computed from the schedule when the page shows no totals (VAC counts as off, as FLICA does). Rest flag only next to a real pairing, not vacation.

## 0.3.1
- Schedule page: try the bid-period BCIDs (001-004 + Priority=1, then the read-only OTDrop view) and remember the one that works.

## 0.3.0
- Reads Ryan's own month schedule (mobileschedule.cgi, GET only) every 30 min into sensor.flica_watcher_schedule; fires flica_watcher/event/schedule_changed when trips change.
- Every new pot/tradeboard alert carries fit: Fits, Conflict <trip>, Check rest <trip>, or Days off <n> (12/13 rule, 10.G).

## 0.2.9
- Pot layout guard no longer trips when the first pot pairing changes (wrapper rows and rows naming a pairing are skipped when hashing the header). It parked the watcher 4 times on Nov 1, 2026.

## 0.2.8
- Tradeboard rows are read from the page's JS data (r[i]=new A(...)); Drop and Trade/Drop posts (the ones with a Pickup Trip button) alert.

## 0.2.6
- Tradeboard: never baseline a page with no trip rows (logs its raw HTML once to find where rows load).

## 0.2.5
- Tradeboard watch (read only): every check (at most every 2 min) reads Tradeboard All Requests for each watched bid month; a new post whose response method is "Pickup Trip" is published on `flica_watcher/event/new_pairing` with `source: tradeboard` (days, depart, arrive, blk, credit=TPay, soft, poster, captain from the detail page). First read is a silent baseline. Failures never stop the pot watch.

## 0.2.4
- Fix: mobile pot Crd/Dy column is pay (credit); the two times are first departure and last arrival, not block and credit (confirmed against the H3619 detail page). Block, check-in, TAFB and captain come from the detail page; `soft` = pay minus block. Rules fall back to first departure for report windows when check-in is unknown.

## 0.2.3
- New pairing pushes carry `captain`, `soft` (credit minus block) and `detail_url`, read with one GET of the pairing's mobile detail page (read only). Logs one detail page's text per start so the captain parser can be checked.

## 0.2.2
- `button.flica_watcher_check_now`: runs a pot check right away (ignored within 10 s of the last check, and while paused or stopped).
- Frequency sliders `number.flica_watcher_normal_minutes` (1-60 min) and `number.flica_watcher_hunt_seconds` (15-300 s); each gap is randomized +-30 % around the setting. Defaults keep the old midpoints (6 min, 40 s).

## 0.2.1
- New `sensor.flica_watcher_next_check` (timestamp): when the next pot check is due; unknown while paused or stopped.
- Read-only page capture every 6 h to /share/flica_watcher/captures (pot page, its links, one pairing detail, any schedule link) so soft time, captain, fits and FAR parsers (t1222) are built from real HTML.

## 0.2.0
- Rules engine (rules.json, Ingress editor page, per-rule live switch with dry-run week gate, cap per day). Read only: no FLICA writes exist.
- Finds history in SQLite; retained `flica_watcher/finds`; new sensors finds, rules_active, last_match.
- State moved from state.json to SQLite (imported once, file renamed `.imported`).
- Pot header fingerprint parks on a table layout change.
- Exponential re-login backoff (1-30 min) replaces the "lost within 15 min" park.
- Next bid month watched once its mobile pot link appears.
- pot_count gets state_class measurement; device shows sw_version; state sensor carries a `note` attribute.
- Fix: mobile pot columns were read in desktop order, so pushes showed the layover as report and the days as layover.

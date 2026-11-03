# Changelog

## 0.4.14
- Reserve grid: parse reserveGridService.cgi JSON by its real shape (root.data[], statusColor.net, avl/odp), so the grid updates every 5 min from JSON instead of waiting on the 30 min page render. Rendered page stays the fallback.

## 0.4.13
- Reserve Grid (Ryan): each check reads NET RESERVES per day with FLICA's color (green = drop or swap off that day can be approved; red/black = add only) from reserveGridService.cgi, cross-checked against the rendered page every 30 min. sensor.flica_watcher_reserve_grid carries days {date: {net, color}}.
- Swap ideas apply the grid rule: the candidate must share a day with the marked trip (it may move earlier or later), and every day moved off must be green. Blocked ideas stay in the sensor with the red days named; they push the moment the grid turns green.

## 0.4.12
- Map swap pages also renders the Reserve Grid (a JS page) read only and saves its HTML and API calls, so the grid reader can be built from the real page.

## 0.4.11
- Employee numbers (Ryan): the pairing page lists crew as "FO 14103 Name", so the pickup text and the captain now carry the number, e.g. "FO Faagau, Justin (12345)". Rosters still compare by name, so old finds keep working; the number appears on each find's next pickup check.

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
- Fix: some pairing pages carry a second "Pay : 1583974803" (an id), which became a 158:39 credit. Only H:MM-sized values count now, and the first Pay is the credit.
- Pairing detail gives the trip length (`days`) from the leg day codes, so email finds show Days.
- Email finds refresh credit, days, block and TAFB from the page on their pickup check; existing ones are re-read once.
- Hidden trips push (Ryan): the first time a trip that left the pot still shows an open FO/RO seat, the Watcher publishes `flica_watcher/event/hidden`; HA automation "FLICA watcher hidden trip" sends a time-sensitive push.

## 0.4.2
- Fix: an email find that had already left the pot took its crew roster after the pickup, so the diff read "left pot, same crew". Those finds now skip the roster and list the FO/RO names (not bold, seat unknown). Finds 0.4.1 marked that way are re-checked once.

## 0.4.1
- Missed trips from FLICA alert emails (Ryan): Home Assistant forwards each email that lands in ha.flica.alerts@gmail.com (IMAP) to `flica_watcher/email/alert` (automation "FLICA alert email to Watcher"). Pairings it names that the pot watch never recorded (they came and went between checks) are added to finds with `source: email`. Each gets one read-only detail GET (CA, times, crew roster). One already out of the pot is stamped gone and its pickup is tracked like any other find. The email also wakes the Watcher for an immediate check.

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

# Changelog

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

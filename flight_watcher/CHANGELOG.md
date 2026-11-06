# Changelog

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

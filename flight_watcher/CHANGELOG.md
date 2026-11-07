# Changelog

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
- Fix: some pairing pages carry a second "Pay : 1583974803" (an id), which became a 158:39 credit. Only H:MM-sized values count now, and the first Pay is the credit.
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

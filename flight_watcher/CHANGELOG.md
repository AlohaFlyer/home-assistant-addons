# Changelog

## 1.7.2

Portal contract 1 revision 3 (the council's plan of Nov 11 and Ryan's decisions the same day), from the audit of the
live portal and FW-0066 (Ryan: "either I or James can upload them; the pairings and awards are the same doc for each
of us"). Built on branch fw-1.7.2 on top of 1.7.1 (live), not pushed or deployed. A contract change: HOM 1.8.2 (takes
revision 2 and 3 exports and commands) ships first, then this release; each with Ryan's yes, a backup and a 30 min
live watch; rollback Flight Watcher first. The fixture `tests/fixtures/portal_contract_v1.json` is regenerated (its new
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
  handler (22 automations, 3 notification-action handlers, 0 offenders).

### CrewTrac refusal block keyed with an HMAC (the council's change)

- The admin's stored CrewTrac retry block (1.6.1, a bare sha256 of the user ID and password) is HMAC-SHA256 with a
  random 32-byte key of the instance's own (`<data>/crewtrac_hmac.key`, 0600; never exported, logged or sent). The
  first 1.7.2 start re-keys the record of the details in use and drops a bare sha256 of any other. A key found gone
  later with a refusal on record keeps CrewTrac blocked until the next save in Settings ("CrewTrac is not tried: its
  refusal record could not be checked ..."); with no refusal on record nothing is blocked.

### Also

- The admin's uploads card keeps WCAG AA contrast on a dark card (its green "read" was 3.1:1).
- `Dockerfile` copies `pilotpdf.py`.

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
  line names the captain only, so pilot 19852 (an FO on the trip, per CrewTrac) still had nothing on Nov 6-8. FLICA
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

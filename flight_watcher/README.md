# Flight Watcher

Keeps one FLICA session alive on the Pako HI NUC, reads the HNL/332/FO open time pot and the pilot's own pages, and
publishes what it finds to Home Assistant over MQTT.

**FLICA is read only.** Nothing in this app submits, drops, swaps, adds or bids. It logs in and reads pages, paced
1.5 to 3.5 s apart, and stops at a CAPTCHA or MFA prompt. Rules and the swap tools only say what they *would* do.

## What it does

- Pot watch: reloads the open time pot at random gaps (idle 2 to 10 min, hunt 20 to 60 s with
  `switch.flight_watcher_hunt_mode`), for the current bid month and the next one once FLICA shows it. A new pairing
  fires `flight_watcher/event/new_pairing` and lands on the finds card.
- One session: FLICA allows one login. When you log in elsewhere the Watcher steps aside for 30 min (doubling on
  repeat). A failed login, a layout change or anything unexpected parks it until Re-arm.
- Schedule: your line, numbered schedule versions (MM.NNN), FAR 117 columns, pay from the PWA tables, pairing
  details, and the monthly award and pairings PDFs uploaded on the dashboard (or the Web UI).
- Request decisions: reads FLICA's Open Time Requests list and the Tradeboard's My Requests page (crew-to-crew
  trades), and pushes each Approved or Denied request once, with Pay-Gross.
- Recall / Over 75: checks each award against your line (PWA 22.G.2) and flags a possible miss.
- Crew index and pilot lookup, charter watch (CrewTrac, read only), tickets (below).
- A second pilot: option `second_pilot` runs a second Watcher with its own data, MQTT prefix
  (`flight_watcher_<name>`), entities and card copies.

## Settings

Enter the FLICA and CrewTrac logins and your last name on the dashboard **Settings card** (Credentials, on the
Settings tab; sealed in the browser, so HA's history and the MQTT broker only hold ciphertext). The Web UI Settings
form and the app's Configuration tab work too; a saved value wins over the Configuration tab. Credentials never go in
git.

## Uploads on the dashboard (1.4.5)

The monthly award, the pilot pairings package and the pilot seniority list are uploaded from the dashboard: Settings
tab, the **uploads card** (`custom:flight-watcher-uploads-card`) under Credentials and above Tickets. It is for the
Home Assistant admin only: anyone else sees "Uploads are for the Home Assistant admin." and the card makes no call.

- Pick what (Monthly award, Pairings package, Pilot seniority list), the bid period (it starts on next month, HST;
  the seniority list has no bid period and takes an optional List date instead) and the PDF, then Upload. The line
  under the button shows the progress and the app's answer (for an award, how many dates of hire it read).
- "On file" lists every PDF kept (what, bid period, size, upload time HST, and whether its text was read), then the
  dates of hire on file: how many pilots, from the seniority list or from which award, its date, and how many more
  were kept from the list under a later award.
- How it reaches the app: the same way Home Assistant's own app panels do. It asks the Supervisor (WebSocket
  `supervisor/api`) for the app's ingress address (`/addons/<slug>/info`, card option `slug`, default
  `43b22650_flight_watcher`) and an ingress session (`/ingress/session`), sets it as the `ingress_session` cookie
  (path `/api/hassio_ingress/`), re-validates it every 5 minutes while the card is open (`/ingress/validate_session`),
  then calls the Web UI's JSON endpoints: `GET api/uploads` and `POST api/upload` (the same form and checks as the
  Web UI page). Only the Supervisor's ingress proxy may connect to them, like the page.
- Size: a PDF of up to 15.9 MB. The Supervisor's ingress proxy refuses a request over 16 MiB (HTTP 413) only after
  all of it has arrived, so the card refuses a larger PDF before sending it (`max_bytes` in `api/uploads`, 16 MiB
  less 64 KiB for the form). The app's own 25 MB check stays as the hard cap.
- The progress line and the result line are live regions (the result a polite status), so a screen reader
  announces the upload's progress and whether the PDF was saved or refused.

## Web UI and rules

The Web UI (sidebar "Flight Watcher Rules", an HA Ingress panel for HA admins) has Settings, Monthly PDFs, Rules and
Recent finds.

- Monthly PDFs: pick a month and a kind, then the PDF (the dashboard uploads card above does the same). Uploads go to
  `/share/flight_watcher/uploads` (never in git) with a `pdftotext -layout` text copy. The award and the pairings
  package are per month (`<YYYY-MM>_award.pdf`, `<YYYY-MM>_pairings.pdf`). A PDF that gives no text copy (damaged or
  password-protected) is refused: it is read under `<YYYY-MM>_<kind>.new.pdf` and deleted, so the month's PDF and
  text copy on file stay as they were.
- **Dates of hire from the award** (1.4.5, Ryan: the monthly award packet lists every pilot's date of hire): an
  uploaded award is also read for dates of hire, either from a seniority section in the seniority list's layout or
  from the pilot lines (`SSSSS / EMP`) with the date labeled DOH, HIRE DATE or DATE OF HIRE (an unlabeled date is
  never taken). With 25 pilot rows or more it is kept as `seniority_award.json` and merged into `seniority.json`:
  the award's bid period (or a list date printed in it) against the seniority list's date (typed, printed, else its
  upload day). The later one is on top and a tie goes to the list. An award on top keeps the list's other pilots
  under it (`seniority_list.json`), per pilot: when two pilots share an employee number on the list and the award
  lists only one, the other keeps the list's record and date of hire. A newer list stands alone. An award with
  fewer rows, or an older award month than the one on file, changes nothing, so it never overwrites a good list. An
  award already on file when 1.4.5 starts is read once at the start, also beside a seniority list uploaded on 1.4.4.
  The log has counts only.
- **Pilot seniority list** (FW-0062): kind "Pilot seniority list" needs no month (the Month box is ignored). It is
  saved as `seniority_<YYYY-MM-DD>.pdf` (the HST upload day) and read at once into
  `/share/flight_watcher/uploads/seniority.json`: each pilot's seniority number, name, seat, equipment and date of
  hire, keyed on the employee number. The page then says how many pilots were read, the list date (typed in the
  List date box, else found in the cover text, else "no list date in the file") and the newest date of hire on the
  list. A PDF with no pilot rows (or with its columns in another order: the reader needs EMP # before ALPA # and DOH
  as the first date column) is refused and deleted; the list on file keeps its PDF, text copy and seniority.json,
  even when the refused upload is on the same day. Lines the reader skips are counted as "lines not read" (a row
  whose DOH wrapped onto the next line is joined and read; a DOH after the list date is not read). The log has
  counts only. Every pilot instance (Ryan's and a second pilot's) reads the same file. Upload a newer list when new
  hires are missing.
- Pay line under a rebuilt month: when the pilot card shows a month "Reconstructed from pairing crew lists", the
  Watcher adds `pay_line` to `sensor.<prefix>_pilot_schedule`: Trips, Credit, Block, Soft, Pay-Gross, Pay-Net and Days
  Off over the trips the grid draws, each trip priced for the seat on its crew line (Captain PWA 3.C.4, FO and RO PWA
  3.D.6) for the longevity year from the date of hire on the seniority list (PWA 3.B.1; a new year on each DOH
  anniversary, PWA 3.D.2; capped at 12), with the PWA
  4.O.1 overrides (Captain $5.00 per block hour on a crew of 3 or more, RO $4.00, FO $3.00 on a 3-pilot crew) and the
  Extended Range +15% as on your own schedule. Pay-Net is an estimate at your own federal and state tax settings. Days
  Off counts bid period days with no trip on the crew lists (reserve and training are not on crew lists). No date of
  hire on file: hours and days only, and the card says to upload the list.
- Rules live in `/data/rules.json` and are edited there (the schema is on the page). They are checked against each
  new pairing; a match publishes `flight_watcher/event/rule_match` and `sensor.flight_watcher_last_match`.
- Every rule starts in dry run, and `switch.flight_watcher_rule_<id>_live` stays off until the rule is 7 days old.
  Even live, a rule only logs `would_submit`: nothing is sent to FLICA.
- History is kept in SQLite (`/data/watcher.db`). The last 30 finds (short rows, under 12 KB for the recorder) are on
  `sensor.flight_watcher_finds`. The finds card reads the full month files `finds_<YYYY-MM>_<key>.json`, whose random key
  is kept in `/data/www_key` and published only behind HA's login (`file_key` attribute), so nothing personal sits
  at a guessable `/local/` address.
- The pilot's date of hire stays in `/data/cards.json` and reaches the schedule card as the `doh` attribute of
  `sensor.flight_watcher_state`; the card files carry a placeholder only.

## Dashboard cards and pushes

The cards ship with the app (`www/`) and are copied to `/config/www/` on each start; the dashboard loads them
through `/local/flight-watcher-loader.js`. Phone pushes are HA automations on Pako that listen to the Watcher's
events (`<prefix>/event/...`: new_pairing, request_decided, recall_miss, ticket_fixed and others).

## Tickets (FW-nnnn)

The tickets card (`custom:flight-watcher-tickets-card`, bottom of the Settings tab under a divider, shown to Ryan only:
FW-0052, FW-0055) has one **Submit a ticket** button: one form, Bug or Feature request chosen at its top (Bug first;
steps and expected only for a bug), up to 10 photos (library, camera, files, or a screenshot pasted with Cmd+V, FW-0053).
At its far right, **Process Tickets in Claude Code** copies the ticket prompt to the clipboard, to paste into Claude Code. Tickets
live in `/share/flight_watcher/tickets/FW-nnnn/`, shared by both pilots. MQTT, `<prefix>` = `flight_watcher` (a
second pilot: `flight_watcher_<name>`):

- `<prefix>/ticket/new` {kind bug|feature, title, narrative, steps?, expected?, page?, version?, cid?, images?},
  then one `<prefix>/ticket/image` {cid, i, n, image} per photo.
- `<prefix>/ticket/act` {id, action triage|progress|fixed|verify|reopen|close|note, text?, version?}. A second
  pilot's instance acts on its own tickets only.
- `<prefix>/ticket/edit` {id, rid?, title?, narrative?, steps?, expected?, page?} (FW-0049): only while the ticket
  is new or reopened, and only the fields sent change; the history line keeps the old text. The card's Edit button
  shows only then.
- `<prefix>/ticket/delete` {id, rid?} (FW-0049): any status, the completed list too. The card asks first. The
  folder moves to `tickets/.deleted/<id>-<time>` (nothing is destroyed) and leaves every list; its number is not
  used again. Ryan's instance edits or deletes any ticket, a second pilot's instance only his own.
- `<prefix>/tickets` (retained, `sensor.<prefix>_tickets`): the list (Ryan's instance: all; a second pilot: his own).
  A new or reopened ticket is listed `editable` with its whole text. `last` {rid, id, action, ok, error, at} is the
  answer to the last edit or delete, so the card can say saved, deleted or why not.
- Events (not retained): `<prefix>/event/ticket_new` {id, kind, title, reporter}; `<prefix>/event/ticket_error`
  {error, at}; **`<prefix>/event/ticket_fixed` {id, kind, title, reporter, version}** (FW-0007) when a `fixed`
  action moves a ticket to fixed, once per move (a repeated `fixed` that only corrects the version sends nothing;
  fixed again after a reopen sends it again). It goes out on the prefix of the instance that took the action
  (normally `flight_watcher/ticket/act`), so `reporter` (`ryan`, or the second pilot's name) says who to tell.

The HA automation for `event/ticket_fixed` lives on Pako, not here: push it to the reporter's phone as a quiet,
non-critical message (no sound, e.g. iOS `push: {interruption-level: passive}`), opening the Settings tab so they
can check it is what they expected, then verify or reopen it on the card.

## Tests

`pip install pytest beautifulsoup4 && pytest tests` from this folder. Every fixture is synthetic, with made-up
names; real FLICA or CrewTrac pages never go in git (see tests/fixtures/README.md).

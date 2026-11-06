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
  details, and the monthly award and pairings PDFs uploaded on the Web UI.
- Request decisions: reads FLICA's Open Time Requests list and pushes each Approved or Denied request once.
- Recall / Over 75: checks each award against your line (PWA 22.G.2) and flags a possible miss.
- Crew index and pilot lookup, charter watch (CrewTrac, read only), tickets (below).
- A second pilot: option `second_pilot` runs a second Watcher with its own data, MQTT prefix
  (`flight_watcher_<name>`), entities and card copies.

## Settings

Enter the FLICA and CrewTrac logins and your last name on the dashboard **Settings card** (sealed in the browser,
so HA's history and the MQTT broker only hold ciphertext). The Web UI Settings form and the app's Configuration tab
work too; a saved value wins over the Configuration tab. Credentials never go in git.

## Web UI and rules

The Web UI (sidebar "Flight Watcher Rules") has Settings, Monthly PDFs, Rules and Recent finds.

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
steps and expected only for a bug), up to 10 photos (library, camera, files, or a screenshot pasted with Cmd+V, FW-0053). Tickets
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

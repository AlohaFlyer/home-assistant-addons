# Flight Watcher

Keeps one FLICA session alive on the Pako HI NUC, reloads the HNL/332/FO open time pot at random gaps, and publishes any new pairing to Home Assistant over MQTT. **Read only:** nothing in this add-on submits anything to FLICA.

- Idle gap 2-10 min, hunt gap 20-60 s (switch.flight_watcher_hunt_mode).
- One login attempt per expiry; a failed login or anything unexpected parks it until Re-arm.
- Repeated session loss backs off 1, 2, 4, 8, 16, 30 min before each single login attempt, then parks.
- Yields when the account is used elsewhere (FLICA allows one session), comes back after 30 min, doubling on repeat.
- Pot table header fingerprint: a layout change parks the watcher instead of parsing garbage; Re-arm accepts the new layout.
- Watches the current bid month and the next one once its pot link appears (rechecked every 6 h). Option `watch_next_month`.
- Credentials only in the add-on Configuration tab.

## v0.2: rules and finds

- Rules live in `/data/rules.json`, edited on the add-on's web page (Open Web UI / sidebar "FLICA Rules"). Schema is shown on the page. First start creates one example rule: SIN layover, this month or next, alert only.
- Rules are checked against each **new** pairing (not the baseline). A match publishes `flight_watcher/event/rule_match` and `sensor.flight_watcher_last_match`.
- Every rule is dry run. `switch.flight_watcher_rule_<id>_live` refuses to turn on until the rule is 7 days old. Even live, v0.2 only logs `would_submit`; writes arrive in v0.3 behind a global kill switch.
- History in SQLite `/data/watcher.db` (finds, matches, submissions, state; 90 days). The last 30 finds (short rows, kept under 12 KB for HA's 16 KB recorder limit) are retained on `flight_watcher/finds` (`sensor.flight_watcher_finds`, list in the `finds` attribute); the finds card reads the full rows from the month files `www/flight-watcher/finds_<YYYY-MM>_<key>.json`, where `<key>` is a random key kept in `/data/www_key` and published only in the sensor's `file_key` attribute (HA serves `www` with no login, so these files never get a guessable name). The files are written before the sensor is published, and the sensor's `rev` attribute changes with every change to this month's or last month's file, so an open card fetches it again (an InFlt verdict, for one). The card keeps the last key per browser, so it still shows the history while the Watcher is offline.
- The pilot's date of hire stays in `/data/cards.json`; the Watcher publishes it as the `doh` attribute of `sensor.flight_watcher_state` for the schedule card. The card files under `www` carry a placeholder only.

## Tickets (FW-nnnn)

The tickets card (`custom:flight-watcher-tickets-card`, Details tab) has one **Submit a ticket** button: one form,
Bug or Feature request chosen at its top (Bug first; steps and expected only for a bug), up to 10 photos. Tickets
live in `/share/flight_watcher/tickets/FW-nnnn/`, shared by both pilots. MQTT, `<prefix>` = `flight_watcher` (a
second pilot: `flight_watcher_<name>`):

- `<prefix>/ticket/new` {kind bug|feature, title, narrative, steps?, expected?, page?, version?, cid?, images?},
  then one `<prefix>/ticket/image` {cid, i, n, image} per photo.
- `<prefix>/ticket/act` {id, action triage|progress|fixed|verify|reopen|close|note, text?, version?}. A second
  pilot's instance acts on its own tickets only.
- `<prefix>/tickets` (retained, `sensor.<prefix>_tickets`): the list (Ryan's instance: all; a second pilot: his own).
- Events (not retained): `<prefix>/event/ticket_new` {id, kind, title, reporter}; `<prefix>/event/ticket_error`
  {error, at}; **`<prefix>/event/ticket_fixed` {id, kind, title, reporter, version}** (FW-0007) when a `fixed`
  action moves a ticket to fixed, once per move (a repeated `fixed` that only corrects the version sends nothing;
  fixed again after a reopen sends it again). It goes out on the prefix of the instance that took the action
  (normally `flight_watcher/ticket/act`), so `reporter` (`ryan`, or the second pilot's name) says who to tell.

The HA automation for `event/ticket_fixed` lives on Pako, not here: push it to the reporter's phone as a quiet,
non-critical message (no sound, e.g. iOS `push: {interruption-level: passive}`), opening the Details tab so they
can check it is what they expected, then verify or reopen it on the card.

## Tests

`pip install pytest beautifulsoup4 && pytest tests` from this folder. Fixtures are synthesized (see tests/fixtures/README.md); replace with real captures when convenient.

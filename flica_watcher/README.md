# FLICA Watcher

Keeps one FLICA session alive on the Pako HI NUC, reloads the HNL/332/FO open time pot at random gaps, and publishes any new pairing to Home Assistant over MQTT. **Read only:** nothing in this add-on submits anything to FLICA.

- Idle gap 2-10 min, hunt gap 20-60 s (switch.flica_watcher_hunt_mode).
- One login attempt per expiry; a failed login or anything unexpected parks it until Re-arm.
- Repeated session loss backs off 1, 2, 4, 8, 16, 30 min before each single login attempt, then parks.
- Yields when the account is used elsewhere (FLICA allows one session), comes back after 30 min, doubling on repeat.
- Pot table header fingerprint: a layout change parks the watcher instead of parsing garbage; Re-arm accepts the new layout.
- Watches the current bid month and the next one once its pot link appears (rechecked every 6 h). Option `watch_next_month`.
- Credentials only in the add-on Configuration tab.

## v0.2: rules and finds

- Rules live in `/data/rules.json`, edited on the add-on's web page (Open Web UI / sidebar "FLICA Rules"). Schema is shown on the page. First start creates one example rule: SIN layover, this month or next, alert only.
- Rules are checked against each **new** pairing (not the baseline). A match publishes `flica_watcher/event/rule_match` and `sensor.flica_watcher_last_match`.
- Every rule is dry run. `switch.flica_rule_<id>_live` refuses to turn on until the rule is 7 days old. Even live, v0.2 only logs `would_submit`; writes arrive in v0.3 behind a global kill switch.
- History in SQLite `/data/watcher.db` (finds, matches, submissions, state; 90 days). The last 50 finds are retained on `flica_watcher/finds` (`sensor.flica_watcher_finds`, list in the `finds` attribute).

## Tests

`pip install pytest beautifulsoup4 && pytest tests` from this folder. Fixtures are synthesized (see tests/fixtures/README.md); replace with real captures when convenient.

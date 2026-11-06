# CLAUDE.md: Flight Watcher (folder flica_watcher)

Owner: Ryan Pettit, A330 FO, Hawaiian Airlines (Alaska), HNL based. This repo holds his Home Assistant add-ons;
the one under active development is **Flight Watcher** (`flica_watcher/`, slug `43b22650_flica_watcher` on the
Pako HI Home Assistant). Read `HANDOFF.md` next: it lists everything open.

## How Ryan wants you to work
- First line of every reply: `Running: <true running model> · Needs: <Tn> <tier model> · Laptop: safe to close | keep awake`.
  Last line: `STATUS: 100% DONE` or `STATUS: NOT DONE`, after a checklist of each done-criterion (done / blocked + why + owner).
- No em dashes. No preamble, no closing summaries. Under ~200 words unless the task needs more.
- Questions: one at a time, tappable options, recommended option first and marked "(recommended)".
- Multi-step work: state done-criteria and steps briefly, then run straight through. No approval gate.
- **[DESTRUCTIVE]** ops need one explicit yes each time: merging a PR, updating/restarting the add-on, deleting
  anything, changing the add-on Configuration options. Never assume an earlier yes covers a new one.
- Never send messages on any channel (email, chat, SMS). Drafts only. Exception: Hark's chat on hark.com.
  Never contact James Luksan until Ryan approves (he will when James's setup is fully built).
- Give PWA references wherever a rule comes from the contract (2023 PWA; the parsed copy is the Cowork project doc
  `claude/2023_PWA.md`). FAR 117 references for legality. Everything FLICA-related is HST.

## Hard rules for this code
- **FLICA is read-only.** Never submit, drop, swap, add or bid. Never bypass a CAPTCHA/MFA. One FLICA session per
  login (the Watcher yields 30 min when Ryan logs in elsewhere). Keep page loads paced (1.5 to 3.5 s apart).
- **No secrets or personal data in git:** no credentials (they live in the add-on Configuration tab, or
  `/data/<name>/creds.json` for a second pilot), no HA tokens, no webhook ids, no real crew names, no captured
  FLICA/CrewTrac pages. Tests use synthetic data with made-up names ("Doe, Jane").
- Never print or repeat passwords seen in add-on options.

## Architecture
- `run.py` launcher starts `watcher.py` once per pilot. Ryan = default instance (MQTT prefix `flica_watcher`,
  `/data`). Option `second_pilot: james` adds an instance with prefix `flica_watcher_james`, `/data/james`,
  creds over MQTT `<prefix>/settings/set`.
- `watcher.py`: main loop, MQTT discovery (entities `*.flica_watcher_*`), pot / schedule / tradeboard / pairing
  detail reads via Playwright `fl.fetch`. Modules: `pot.py` (parsers), `far.py` (FAR 117), `recall.py`
  (Recall/O75 miss check, PWA 22.G.2), `versions.py` (schedule versions MM.NNN), `pdfs.py` (award and pairings
  PDFs), `crewidx.py` (crew index), `tickets.py` (FW-nnnn tickets), `store.py` (SQLite), `web.py` (ingress UI).
- Shared files on Pako: `/homeassistant/www/flica/pairings_<YYYY-MM>.json`, `finds_<YYYY-MM>.json`
  (`/www/flica/<name>/` for a second pilot), `/share/flica_watcher/` (uploads, crew_index/*.md, tickets/).
- Dashboard cards currently live ONLY on Pako `/config/www/flica-*.js` (not in git yet, see HANDOFF item 1).
  `/config/www/make_pilot_cards.py james` generates James's copies (`flica-*-james.js`).
- Dashboard `flica-watcher` (title "Flight Watcher"), views: watcher, wx, details, recall.

## Release procedure
1. Branch, change, `cd flica_watcher && python -m pytest -q` (all must pass), bump `version` in `config.yaml`
   and `VERSION` in `watcher.py`, add a CHANGELOG entry.
2. Push branch, open PR. Ask Ryan for a yes ([DESTRUCTIVE]) before merging.
3. After merge: Home Assistant > the app store reload (`check_updates`) then update the app (second yes if not
   already given for this release). Verify `sensor.flica_watcher_state` attribute `version` and the app log.
4. New MQTT discovery entities come up as `*.flica_watcher_*` (0.10.3 sends `default_entity_id`). Any created as
   `*.flight_watcher_*` before 0.10.3 need a one-time rename in the entity registry.

## Reaching Home Assistant
- Pako HI Home Assistant: Nabu Casa URL (in Ryan's connectors), MCP connector "Home Assistant - Pako HI" and the
  "Pako HI Shell" connector (file read/write, bash on the HA host). Long shell calls drop: run patches in the
  background. Sprucebrook NV is a different house: never touch it for this project.

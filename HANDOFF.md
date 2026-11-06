# HANDOFF: Flight Watcher, moved from Cowork to Claude Code (2026-11-05)

State at hand-off: app **0.10.1** running on Pako HI (Ryan's instance only). Crew index first pass in progress.
Work top to bottom; tick items off here in the same PR that finishes them.

## Open items

0. ~~**Rename to Flight Watcher on Pako (1.0.0).**~~ Done 2026-11-06: backup `1c4b12af` first; 65 entity ids, 14
   automations (aliases, topics, tags, deep links; the Hark webhook id kept), 7 helpers, 3 utility meters,
   `custom_templates/flight_watcher.jinja`, `packages/flight_watcher_wx.yaml` renamed with history kept; old retained
   discovery cleared; app `43b22650_flight_watcher` installed (imported /data: 47 finds, crew index, rules, DOH;
   /share and /www/flica moved); dashboard `flight-watcher` recreated, old one deleted; old app uninstalled, old
   cards removed, `.bak` copies and pre-rename files in `/share/flight_watcher/archive/`. **Ryan:** enter FLICA and
   CrewTrac credentials in the app's Web UI > Settings (1.0.1; or the Configuration tab) (the Watcher waits until then); `second_pilot` too when
   James is ready.
1. ~~**Cards into git, self-deploying.**~~ Done (0.10.2, live 0.10.3 on 2026-11-06): cards in `flight_watcher/www/`,
   deployed by `cards.py` on start; the only resource is `/local/flight-watcher-loader.js` (the 10 per-card
   resources were deleted). Ryan's DOH lives in `/data/cards.json` on Pako, never in git. Item 4's "register
   resources for the -james copies" is covered by the loader. Old `/config/www/make_pilot_cards.py` and the
   hand-made `-james` copies on Pako are superseded (the add-on regenerates them when `second_pilot` is set).
2. **Pako-side config into git (snapshots):** the automations below and the `flight-watcher` dashboard JSON, saved
   under `ha/` for review and history (write back via the HA connector, never by hand-editing .storage):
   "FLICA alert to phone", "FLICA recall list in (Hark webhook)", "FLICA recall miss alert",
   "Flight Watcher new ticket", the new-pairing / charter / watcher-health automations, `packages/flica_wx.yaml`.
   Strip the webhook id before committing.
3. **Entity id bug:** fixed in 0.10.3 (discovery sends `default_entity_id`, keeps `object_id`). After the update,
   any entity created as `*.flight_watcher_*` before the fix still needs a one-time rename in the entity registry.
4. **James Kane's instance** (HNL A330 FO, HA username `jameskane`; email on file in Ryan's memory; do NOT
   contact him until Ryan approves):
   - Ryan sets option `second_pilot: james` in the app Configuration (Claude does not edit options that hold
     Ryan's passwords) and creates James's HA user himself (Settings > People, non-admin; Claude does not
     create accounts; may generate a temporary password for Ryan to type).
   - Then (the loader already loads `flight-watcher-*-card-james.js`): helpers `input_number.flight_watcher_james_*`
     (federal_tax_pct, state_tax_pct, longevity_year, month_offset) and `input_text.flight_watcher_james_er_trips`,
     copying ranges from Ryan's; dashboard `flight-watcher-james` (same views, James's cards); a **Settings
     tab** card that publishes `flight_watcher_james/settings/set` (FLICA user/password, CrewTrac user/password,
     last name) and `flight_watcher_james/recall/act {me:{sen, seat}}`; forward the recall webhook to
     `flight_watcher_james/recall/set` too; push automations to his Companion app notify target; set Ryan's
     other dashboards `require_admin` so James sees only his.
   - His pay: FO table PWA 3.D by his longevity year (he sets it); his DOH is not on file.
5. **Crew index checks** (0.10.1): confirm the first full pass (about 1,336 trip instances, 300 pages per run at
   00/06/12/18 HST, 8 per check while hunting), `/share/flight_watcher/crew_index/<YYYY-MM>.md` written, and the
   pilot card's "Reconstructed" table. Unverified on real pages: crew-name trimming, the day-number to date
   mapping, and a suspected `pdfs.py` bug for a bid period starting on the 31st (D prefixes on every day).
   Ryan confirmed with ALPA and the company that crew assignments are public information.
6. **Tickets workflow:** buttons and log are on Details. "work tickets" = read `/share/flight_watcher/tickets/*`,
   mirror each to a GitHub issue here (label bug / feature, link FW id), diagnose, batch fixes into a release,
   mark `fixed` with the version via `flight_watcher/ticket/act`. Reporter verifies.
7. **Paycheck check:** paydays the 7th (estimate) and 22nd (true-up), PWA 2.A.56. Ryan taps "Get paycheck
   (Hark)"; Hark saves `YYYYMMDD_pay-advice_HAL.pdf` (+ earnings detail) to Drive "Claude - Pay stubs" via Alaska
   PeopleSoft (aagpeople.com) with a PingID one-time code. First real check Dec 22: compare line by line with the
   schedule card (credit x rate PWA 3.D, 5:00 min per day 4.C.3, IRO / ER overrides 4.O.1, vacation 4:00 per day
   6.J). Open question: SIN H3815B pays both the RO $4.00/blk h override and ER 15% today; settle against the stub.
8. **Hunt-mode load:** about 376 FLICA page loads an hour while hunting. Ryan to pick a cap.
9. **Recall/O75:** live. Hark posts each day's HNL recall list to the HA webhook automation. Red rows = missed
   (eligible, junior pilot got it); push + red alert only for those. Filing a CCR on hal.alpa.org needs a
   browser session (Cowork with Chrome, or Hark), only after Ryan approves the narrative and says
   "file CCR <date> <pairing>". Claude Code on the web cannot do this step.
10. **Housekeeping:** Hark's shared Google Doc "Flight Watcher Shared Context" gets a Log line for each release;
    homeofficemanager.app task register items t1275 (hunt load), t1276 (paycheck), t1277 (James), t1278 (Hark
    paycheck procedure, done) to update.

## Done this period (for context)
0.9.2 Recall/O75 tab, 0.9.3 trip/vacation is not a miss, 0.9.4 finds kept 24 months + month picker card,
0.10.0 second-pilot engine + Flight Watcher name, 0.10.1 crew index + tickets. Card-only: schedule card version
bar aligned, changes list under Pay settings, Credit left of Block, recall card FO/CA boxes, pilot card error
text and reconstructed table, finds card, tickets card, Update schedules button.

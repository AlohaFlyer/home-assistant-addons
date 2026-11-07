# Pending changelog lines (for the integrator; merged into CHANGELOG.md with the next version)

- FW-0060: every Flight Watcher sensor stays under 12 KB of attributes (HA's recorder keeps no history past 16 KB).
  The ticket log, the schedule versions, the pickers and the recall days now go to `<name>_<key>.json` in the pilot's
  own `www/flight-watcher/` folder (same random key as the finds files, published only in the sensor's `file_key`,
  with `rev` so an open card refetches); the tickets, schedule, pickers and recall cards read those files (second
  pilot: `www/flight-watcher/<name>/`). The sensors keep counts and a short list (tickets: the newest 30 open, no
  text; versions: each month's count and awarded / current version; pickers: the fastest 20; recall: the newest
  days that fit). Every other sensor list is held at 12000 bytes by `cap_attrs()` (oldest or least useful items out,
  `trimmed` says how many). New test `tests/test_sensor_size.py` publishes a busy month through every publisher.
- FW-0064: a crew-to-crew Trade (or any request the Watcher cannot see on a list) is pushed as
  `event/request_decided`, status Approved, type Trade, when the schedule shows trips dropped and added the same HST
  day (FLICA's "Schedule Updated" stamps) that no decided request explains, once a later read is quiet and the trips
  taken have their credit; a Pending / Processing request whose every leg shows on the schedule is pushed at once
  under its own key. Pay-Gross from pay.py (seat from Ryan's trip records, PWA 4.O.1 overrides, PWA 3.D.6 rate);
  pushed once, kept across restarts (`trades.py`, `tests/test_trades.py`). The request-decided automation says
  "Seen on your FLICA schedule" instead of "Filed" for these (ha/ snapshot; apply on Pako).
- FW-0065: a trip that comes home the day the next activity starts (H3681 SYD Nov 9 to 12, then H3620 on Nov 12) kept
  only its first day from version 11.009 on: FLICA shows only the new trip's row that day, so there was no HNL
  layover cell to end on. The item builder (`pot.schedule_items`, now also used for Schedule Lookup months) ends a
  trip still away on the day the next activity starts; stored versions and the schedule on file are repaired once
  (`versions.repair_ends`, fingerprints remade so no spurious version), and a later end change shows in a version's
  changes. Test `tests/test_trip_end.py`.

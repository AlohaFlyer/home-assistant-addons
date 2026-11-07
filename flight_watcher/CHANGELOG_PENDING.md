# Pending changelog lines (the integrator folds these into the next release)

- FW-0056: the crew index now reads every trip on a schedule the Watcher reads (Ryan's own months, a pilot lookup's month, a picker's month), not only the trips the month's pairing package lists, so trips built or renumbered later (H38xx, a trade's H3815B) get their crew in pilot lookups and the Markdown. Read only, paced like every crew index read; a trip with no package row takes its end, route and report from its pairing page.
- FW-0057: the crew index keeps a trip that starts before the index's first day and runs into it, and October's trips come from Ryan's October schedule when there is no October package, each in its own bid period; a pilot lookup's rebuilt grid (and its coverage) counts a trip that starts before the grid and runs into it.
- FW-0058: a seat code (CA, FO, RO, FA, SO) on a crew line counts only in FLICA's seat position, standing alone and followed by the employee number or Open, so a name such as "Lee, So Young" (made up) stays whole. Crew lines stored before the fix that were cut this way are read once more at the first start (a failed re-read keeps the stored line).
- FW-0059: a pilot the crew index shows on two overlapping trips (a trade between reads) is flagged: both trips are read again first (paced, ten a check outside a run), the flag clears when the re-read shows the pilot on one, and when the pilot is still on both the newer read is kept and the other is marked as the older read (Markdown Pairing cell, pilot lookup overlap fields, the pilot card's overlap line). Trips that only touch (a morning release, a night report the same day) are not flagged.
- Test data: real crew names, employee numbers and a phone number that had been copied from FLICA pages into tests/test_store.py, tests/test_tradeboard.py, a tradeboard.py docstring, a watcher.py docstring and one CHANGELOG line were replaced with made-up ones (the old values remain in git history).
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

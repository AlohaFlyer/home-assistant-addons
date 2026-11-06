# FLICA fixtures

SYNTHESIZED, not captured. Built 31 Oct 2026 from the rows v0.1.9 published on
`sensor.flight_watcher_pot_count` (H3644, H3601, H3649) and the cell order those rows imply. They hold no crew
names or employee numbers; a test that needs a name uses a made-up one ("Doe, Jane"). The header row text, the
next-month link (BCID=003.153) and the killed/expired/blocked wording are assumptions.

Real FLICA or CrewTrac pages never go in git. To check a parser against the real thing, compare it with the
private copy the Watcher saves under /share/flight_watcher/captures on Pako, on the host only. If the real page
shows a wrong assumption, change the synthetic fixture to the real layout, keeping made-up names and numbers, and
re-run `pytest`.

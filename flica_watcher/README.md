# Old Flight Watcher (hand-off)

Retired. The app was renamed to Flight Watcher (folder `flight_watcher/`, slug `flight_watcher`), which Supervisor
installs as a new app with an empty /data. This last release (0.10.4) of the old slug `flica_watcher` only copies
its /data to `/share/flight_watcher/import/data` for Flight Watcher 1.0.0 to import, and then waits. It does not log
in to FLICA. Uninstall it once Flight Watcher runs with the imported data; this folder is then removed from git.

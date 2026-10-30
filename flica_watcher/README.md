# FLICA Watcher

Keeps one FLICA session alive on the Pako HI NUC, reloads the HNL/332/FO open time pot at random gaps, and publishes any new pairing to Home Assistant over MQTT.

- Idle gap 2-10 min, hunt gap 20-60 s (switch.flica_watcher_hunt_mode).
- One login attempt per expiry; a failed login or anything unexpected parks it until Re-arm.
- Yields when the account is used elsewhere (FLICA allows one session), comes back after 30 min, doubling on repeat.
- Credentials only in the add-on Configuration tab.

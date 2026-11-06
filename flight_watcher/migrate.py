"""One-time move from the old FLICA Watcher app (slug flica_watcher) to Flight Watcher (1.0.0).

Supervisor gives a new slug a new, empty /data, so the old app's last release (flica_watcher 0.10.4) copies its
/data to /share/flight_watcher/import/data and writes READY there. run.py calls run() before the watchers start:
- /data: when it has no watcher.db yet and the import is READY, every file is copied in (never options.json,
  which is this app's own Configuration; credentials, FLICA cookies and a second pilot's creds.json are never
  exported, so they are entered again). The import folder is then deleted and /share/flight_watcher/.imported
  written, which also tells the old app not to export again.
- /share/flica_watcher/* moves to /share/flight_watcher/ (captures, crew_index, tickets, uploads, versions seed, a
  second pilot's folder) and /homeassistant/www/flica/* to /homeassistant/www/flight-watcher/ (pairings, finds,
  school year). An entry already at the destination is left alone. The old folder is removed once empty.
Never raises: a failure is logged and the watchers start anyway.
"""
import json
import os
import shutil
import time

DATA = "/data"
SHARE_OLD, SHARE_NEW = "/share/flica_watcher", "/share/flight_watcher"
WWW_OLD, WWW_NEW = "/homeassistant/www/flica", "/homeassistant/www/flight-watcher"
NEVER = {"options.json"}


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [migrate]", msg, flush=True)


def import_data(data=DATA, share=SHARE_NEW):
    """Copy the old app's exported /data in. Returns the copied relative paths ([] when nothing to do)."""
    src = os.path.join(share, "import", "data")
    if not os.path.exists(os.path.join(src, "READY")):
        return []
    if os.path.exists(os.path.join(data, "watcher.db")):
        log("import skipped: /data already has watcher.db (delete the import folder by hand if it is stale)")
        return []
    done = []
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        os.makedirs(os.path.join(data, rel_root), exist_ok=True)
        for f in files:
            rel = os.path.normpath(os.path.join(rel_root, f))
            if f in NEVER or rel == "READY":
                continue
            dst = os.path.join(data, rel)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(root, f), dst)
                done.append(rel)
    with open(os.path.join(share, ".imported"), "w") as fh:
        json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": len(done)}, fh)
    shutil.rmtree(os.path.join(share, "import"), ignore_errors=True)
    log(f"imported {len(done)} file(s) from the old app's /data")
    return done


def move_tree(old, new):
    """Move every entry of old into new unless new already has it; remove old when it ends up empty."""
    if not os.path.isdir(old):
        return []
    os.makedirs(new, exist_ok=True)
    moved = []
    for name in sorted(os.listdir(old)):
        src, dst = os.path.join(old, name), os.path.join(new, name)
        if os.path.exists(dst):
            continue
        shutil.move(src, dst)
        moved.append(name)
    try:
        os.rmdir(old)
    except OSError:
        pass
    if moved:
        log(f"moved {len(moved)} entr(y/ies) {old} -> {new}")
    return moved


def run(data=DATA, share_old=SHARE_OLD, share_new=SHARE_NEW, www_old=WWW_OLD, www_new=WWW_NEW):
    for step in (lambda: import_data(data, share_new), lambda: move_tree(share_old, share_new),
                 lambda: move_tree(www_old, www_new) if os.path.isdir(os.path.dirname(www_new)) else []):
        try:
            step()
        except Exception as e:  # noqa: BLE001
            log(f"migration step failed: {e}")

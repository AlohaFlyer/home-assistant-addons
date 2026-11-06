"""One-time move from the old FLICA Watcher app (slug flica_watcher) to Flight Watcher (1.0.0).

Supervisor gives a new slug a new, empty /data, so the old app's last release (flica_watcher 0.10.4) copies its
/data to /share/flight_watcher/import/data and writes READY there. run.py calls run() before the watchers start:
- /data: when the import is READY and /data has not been migrated (empty, marked .fresh, or an import cut short),
  every file is copied in, staged (see import_data; never options.json, which is this app's own Configuration;
  credentials, FLICA cookies and a second pilot's creds.json are never exported, so they are entered again). The
  import folder is then deleted and /share/flight_watcher/.imported written, which also tells the old app not to
  export again.
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
    """Copy the old app's exported /data in. Returns the imported relative paths ([] when nothing to do).

    Staged: files are copied to /data/.import.tmp first, then each is moved into place with os.replace; /data/.migrated
    is written last. An import cut short (reboot, full disk) is simply redone on the next start, because the export
    stays READY until .migrated exists. A /data the watcher started fresh (marked .fresh by note_fresh(), so no import
    had happened) may be overwritten by an export that turns up later."""
    src = os.path.join(share, "import", "data")
    if os.path.exists(os.path.join(data, ".migrated")) or not os.path.exists(os.path.join(src, "READY")):
        return []
    stage = os.path.join(data, ".import.tmp")
    if os.path.exists(os.path.join(data, "watcher.db")) and not (os.path.exists(os.path.join(data, ".fresh"))
                                                                 or os.path.exists(stage)):
        log("import skipped: /data already holds this app's own data")
        return []
    shutil.rmtree(stage, ignore_errors=True)
    rels = []
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        os.makedirs(os.path.join(stage, rel_root), exist_ok=True)
        for f in files:
            rel = os.path.normpath(os.path.join(rel_root, f))
            if f in NEVER or rel == "READY":
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(stage, rel))
            rels.append(rel)
    for rel in rels:
        dst = os.path.join(data, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        for side in ("-wal", "-shm"):  # a fresh DB's own journal must not be replayed onto the imported one
            if os.path.exists(dst + side) and not os.path.exists(os.path.join(stage, rel + side)):
                os.remove(dst + side)
        os.replace(os.path.join(stage, rel), dst)
    shutil.rmtree(stage, ignore_errors=True)
    with open(os.path.join(data, ".migrated"), "w") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    if os.path.exists(os.path.join(data, ".fresh")):
        os.remove(os.path.join(data, ".fresh"))
    with open(os.path.join(share, ".imported"), "w") as fh:
        json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": len(rels)}, fh)
    shutil.rmtree(os.path.join(share, "import"), ignore_errors=True)
    log(f"imported {len(rels)} file(s) from the old app's /data")
    return rels


def note_fresh(data=DATA):
    """Before the watchers start: a /data with no watcher.db and no import is marked .fresh, so an export that
    arrives later (old app updated after this one started) can still be imported over it."""
    if not os.path.exists(os.path.join(data, "watcher.db")) and not os.path.exists(os.path.join(data, ".migrated")):
        open(os.path.join(data, ".fresh"), "w").close()
        log("no data to import yet: starting fresh; an export from the old app will still be imported on a restart")


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
    for step in (lambda: import_data(data, share_new), lambda: note_fresh(data), lambda: move_tree(share_old, share_new),
                 lambda: move_tree(www_old, www_new) if os.path.isdir(os.path.dirname(www_new)) else []):
        try:
            step()
        except Exception as e:  # noqa: BLE001
            log(f"migration step failed: {e}")

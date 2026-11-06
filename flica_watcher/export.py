"""Old FLICA Watcher app, final release 0.10.4: hand the data to the new Flight Watcher app, then wait.

Copies /data to /share/flight_watcher/import/data (then writes READY) so Flight Watcher 1.0.0 can import it on
its first start. Never copied: options.json (the Configuration, credentials included), storage_state.json (FLICA
cookies) and any creds.json (a second pilot's credentials); those are entered again in the new app. Nothing here
logs in to FLICA, so the new app can hold the one FLICA session. Exports again on every start until the new app has
imported (/share/flight_watcher/.imported). Uninstall this app once Flight Watcher runs with the imported data.
"""
import os
import shutil
import sqlite3
import time

DATA = "/data"
SHARE = "/share/flight_watcher"
SKIP = {"options.json", "storage_state.json", "creds.json"}
SIDE = ("-wal", "-shm", "-journal")  # SQLite side files: the .db is copied whole with the backup API instead


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [hand-off]", msg, flush=True)


def export(data=DATA, share=SHARE):
    if os.path.exists(os.path.join(share, ".imported")):
        log("Flight Watcher already imported the data; nothing to do. Uninstall this app.")
        return 0
    # Exported afresh on every start until Flight Watcher has imported, so a restored backup's newer data wins.
    dst, tmp = os.path.join(share, "import", "data"), os.path.join(share, "import", "data.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for root, dirs, files in os.walk(data):
        rel_root = os.path.relpath(root, data)
        os.makedirs(os.path.join(tmp, rel_root), exist_ok=True)
        for f in files:
            if f in SKIP or f.endswith(".tmp") or f.endswith(SIDE):
                continue
            src, out = os.path.join(root, f), os.path.join(tmp, rel_root, f)
            if f.endswith(".db"):  # one consistent file, WAL included
                a, b = sqlite3.connect(src), sqlite3.connect(out)
                try:
                    a.backup(b)
                finally:
                    b.close()
                    a.close()
            else:
                shutil.copy2(src, out)
            n += 1
    shutil.rmtree(dst, ignore_errors=True)
    os.replace(tmp, dst)
    open(os.path.join(dst, "READY"), "w").write(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    log(f"exported {n} file(s) to {dst}")
    return n


if __name__ == "__main__":
    try:
        export()
    except Exception as e:  # noqa: BLE001
        log(f"export failed: {e}")
    log("retired: waiting (uninstall when Flight Watcher has imported the data)")
    while True:
        time.sleep(3600)

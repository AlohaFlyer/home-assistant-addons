"""FLICA Watcher launcher (0.10.0; cards deployed since 0.10.2): one watcher.py per pilot from the same add-on.

The default instance is Ryan's and runs exactly as before (add-on options, /data, flica_watcher/... topics,
the ingress Web UI). When the option `second_pilot` names another pilot (lowercase letters, digits and
underscores), a second watcher.py runs beside it with its own data folder (/data/<name>), its own MQTT
prefix (flica_watcher_<name>) and its own credentials (sent to flica_watcher_<name>/settings/set, kept
in /data/<name>/creds.json). Either child that exits is started again: after 10 s, or 60 s when it died
within 30 s of starting (a crash loop). SIGTERM / SIGINT go to both children; the launcher exits when
they have stopped.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

OPTIONS = "/data/options.json"
WATCHER = "/app/watcher.py"
NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
RESTART_S = 10
CRASH_WINDOW_S = 30
CRASH_RESTART_S = 60
STOP_GRACE_S = 25


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [run]", msg, flush=True)


def second_pilot_name(opts):
    """The validated `second_pilot` option, or '' (blank, missing or not [a-z0-9_])."""
    v = str((opts or {}).get("second_pilot") or "").strip().lower()
    if not v:
        return ""
    if not NAME_RE.match(v):
        log(f"second_pilot {v!r} ignored: use lowercase letters, digits and underscores only")
        return ""
    return v


def child_specs(opts, data="/data"):
    """[{name, env}] for every watcher.py to run: the default instance, then the second pilot's."""
    specs = [{"name": "", "env": {}}]
    name = second_pilot_name(opts)
    if name:
        specs.append({"name": name, "env": {
            "FLICA_DATA": f"{data}/{name}",
            "FLICA_PREFIX": f"flica_watcher_{name}",
            "FLICA_INSTANCE": name,
            "FLICA_OPTIONS": f"{data}/options.json",
            "FLICA_WEB": "0",
        }})
    return specs


def read_options(path=None):
    try:
        d = json.load(open(path or OPTIONS))
        return d if isinstance(d, dict) else {}
    except Exception as e:
        log(f"options unreadable ({e}); running the default instance only")
        return {}


def start(spec):
    if spec["env"].get("FLICA_DATA"):
        os.makedirs(spec["env"]["FLICA_DATA"], exist_ok=True)
    env = {**os.environ, **spec["env"]}
    p = subprocess.Popen([sys.executable, "-u", WATCHER], env=env)
    log(f"started watcher {spec['name'] or 'default'} (pid {p.pid})")
    return {"p": p, "started": time.time(), "restart_at": None}


def app_version(path=WATCHER):
    """VERSION from watcher.py without importing it (the import starts a watcher's globals)."""
    try:
        m = re.search(r'^VERSION = "([^"]+)"', open(path, encoding="utf-8").read(), re.M)
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


def main():
    opts = read_options()
    specs = child_specs(opts)
    import cards  # 0.10.2: the dashboard cards ship with the app
    cards.deploy(app_version(), [s["name"] for s in specs if s["name"]])
    procs = {}
    stopping = {"on": False}

    def on_signal(signum, frame):
        if not stopping["on"]:
            log(f"signal {signum}: stopping children")
        stopping["on"] = True
        for r in procs.values():
            if r["p"].poll() is None:
                try:
                    r["p"].send_signal(signal.SIGTERM)
                except OSError:
                    pass

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    for spec in specs:
        procs[spec["name"]] = start(spec)
    stop_at = None
    while True:
        alive = [r for r in procs.values() if r["p"].poll() is None]
        if stopping["on"]:
            if not alive:
                log("children stopped")
                return 0
            stop_at = stop_at or time.time()
            if time.time() - stop_at > STOP_GRACE_S:
                for r in alive:
                    try:
                        r["p"].kill()
                    except OSError:
                        pass
            time.sleep(0.5)
            continue
        for spec in specs:
            r = procs[spec["name"]]
            rc = r["p"].poll()
            if rc is None:
                continue
            if r["restart_at"] is None:
                ran = time.time() - r["started"]
                wait = CRASH_RESTART_S if ran < CRASH_WINDOW_S else RESTART_S
                log(f"watcher {spec['name'] or 'default'} exited with {rc} after {ran:.0f} s; restart in {wait} s")
                r["restart_at"] = time.time() + wait
            elif time.time() >= r["restart_at"]:
                procs[spec["name"]] = start(spec)
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())

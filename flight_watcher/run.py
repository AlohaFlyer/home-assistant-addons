"""Flight Watcher launcher (0.10.0; cards deployed since 0.10.2): one watcher.py per pilot from the same add-on.

The default instance is Ryan's and runs exactly as before (add-on options, /data, flight_watcher/... topics,
the ingress Web UI). When the option `second_pilot` names another pilot (lowercase letters and digits, single
underscores between words), a second watcher.py runs beside it with its own data folder (/data/<name>), its own MQTT
prefix (flight_watcher_<name>) and its own credentials (sent to flight_watcher_<name>/settings/set, kept
in /data/<name>/creds.json). Either child that exits is started again: after 10 s, or 60 s when it died
within 30 s of starting (a crash loop). SIGTERM / SIGINT go to both children; the launcher exits when
they have stopped.

1.5.0 (FW-0063): option `pilots` [{name}] names every pilot (at most roles.MAX_PILOTS besides the default instance,
which is the admin); each runs exactly like the second pilot above. While `pilots` is empty the older `second_pilot`
is read instead (at read time: the options are never rewritten). A name that does not match roles.NAME_RE, starts with
one of the admin's reserved words (roles.RESERVED), repeats or mixes with another pilot's ids is left out with a log
line, and so is any pilot past the cap.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

import roles

OPTIONS = "/data/options.json"
WATCHER = "/app/watcher.py"
NAME_RE = roles.NAME_RE
RESTART_S = 10
CRASH_WINDOW_S = 30
CRASH_RESTART_S = 60
STOP_GRACE_S = 25


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [run]", msg, flush=True)


def second_pilot_name(opts):
    """The validated `second_pilot` option, or '' (blank, missing or not roles.NAME_RE)."""
    v = str((opts or {}).get("second_pilot") or "").strip().lower()
    if not v:
        return ""
    if not NAME_RE.match(v):
        log(f"second_pilot {v!r} ignored: use 1 to 32 lowercase letters, digits and single underscores between words")
        return ""
    return v


def pilot_names(opts):
    """1.5.0 (FW-0063): the pilots to run besides the admin, in option order: `pilots` [{name}] when it lists any,
    else `second_pilot`. Invalid, reserved, repeated and mixing names are left out (logged), then the cap applies."""
    opts = opts or {}
    raw = opts.get("pilots")
    if isinstance(raw, list) and raw:
        names = [str((p.get("name") if isinstance(p, dict) else p) or "").strip().lower() for p in raw]
        old = second_pilot_name(opts)
        if old and old not in names:
            log(f"second_pilot {old!r} ignored: the pilots option is set")
    else:
        names = [n for n in (second_pilot_name(opts),) if n]
    out = []
    for n in names:
        why = roles.name_refusal(n, out)
        if why:
            log(f"pilot {n!r} left out: {why}")
        elif len(out) >= roles.MAX_PILOTS:
            log(f"pilot {n!r} left out: at most {roles.MAX_PILOTS} pilots besides the admin")
        else:
            out.append(n)
    return out


def child_specs(opts, data="/data"):
    """[{name, env}] for every watcher.py to run: the default instance (the admin), then each pilot's."""
    specs = [{"name": "", "env": {}}]
    for name in pilot_names(opts):
        specs.append({"name": name, "env": {
            "FLIGHT_WATCHER_DATA": f"{data}/{name}",
            "FLIGHT_WATCHER_PREFIX": f"flight_watcher_{name}",
            "FLIGHT_WATCHER_INSTANCE": name,
            "FLIGHT_WATCHER_OPTIONS": f"{data}/options.json",
            "FLIGHT_WATCHER_WEB": "0",
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
    if spec["env"].get("FLIGHT_WATCHER_DATA"):
        os.makedirs(spec["env"]["FLIGHT_WATCHER_DATA"], exist_ok=True)
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
    import migrate  # 1.0.0: the one-time move from the old FLICA Watcher app (slug flica_watcher)
    migrate.run()
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

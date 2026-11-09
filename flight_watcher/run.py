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

1.6.0 (FW-0061): a pilot entry with `portal: true` gets a pilot portal (served by the HOM app). Only then, before any
child starts, the launcher makes /share/fw_portal/<name>/ with its out/ and in/ folders and their modes (portal.prepare;
a symlinked folder is refused and that pilot gets no portal), sets /share/flight_watcher to 0700, makes the Ed25519
signing key /data/portal_ed25519.pem (never under /share) and logs its public half (`portal signing key
ed25519:...`, the value HOM pins in fw_signing_key). That pilot's watcher.py gets FLIGHT_WATCHER_PORTAL=1, its folder
and the key path; the default instance gets the public key for the Web UI. Option `fw_portal_origin` (only
https://<host>.<tailnet>.ts.net, else ignored) is the ntfy Click origin. With no portal entry nothing of this runs: no
folder, no key, no log line. Turning a portal off is fail-closed: at each start a pilot folder left under
/share/fw_portal whose portal is not on (or was refused) this start has its out/ and in/ emptied (portal.retire).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

import portal
import roles

OPTIONS = "/data/options.json"
WATCHER = "/app/watcher.py"
NAME_RE = roles.NAME_RE
RESTART_S = 10
CRASH_WINDOW_S = 30
CRASH_RESTART_S = 60
STOP_GRACE_S = 25
PORTAL_ROOT = portal.ROOT  # 1.6.0 (FW-0061)
SHARE_FW = "/share/flight_watcher"


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


def pilot_entries(opts):
    """1.6.0 (FW-0061): [(name, portal)] of the pilots to run besides the admin, in option order: `pilots`
    [{name, portal}] when it lists any, else `second_pilot` (no portal). Invalid, reserved, repeated and mixing names
    are left out (logged), then the cap applies. portal is True only for an entry whose `portal` is exactly true."""
    opts = opts or {}
    raw = opts.get("pilots")
    if isinstance(raw, list) and raw:
        entries = [(str((p.get("name") if isinstance(p, dict) else p) or "").strip().lower(),
                    isinstance(p, dict) and p.get("portal") is True) for p in raw]
        old = second_pilot_name(opts)
        if old and old not in [n for n, _ in entries]:
            log(f"second_pilot {old!r} ignored: the pilots option is set")
    else:
        entries = [(n, False) for n in (second_pilot_name(opts),) if n]
    out = []
    for n, want in entries:
        why = roles.name_refusal(n, [x for x, _ in out])
        if why:
            log(f"pilot {n!r} left out: {why}")
        elif len(out) >= roles.MAX_PILOTS:
            log(f"pilot {n!r} left out: at most {roles.MAX_PILOTS} pilots besides the admin")
        else:
            out.append((n, want))
    return out


def pilot_names(opts):
    """1.5.0 (FW-0063): the pilots to run besides the admin (pilot_entries' names)."""
    return [n for n, _ in pilot_entries(opts)]


def portal_origin(opts):
    """1.6.0: the option fw_portal_origin when it is https://<host>.<tailnet>.ts.net, else '' (a set value that is not
    one is logged as ignored). Used only as the ntfy Click link; never read from /share."""
    v = str((opts or {}).get("fw_portal_origin") or "").strip()
    if v and not portal.origin_ok(v):
        log("fw_portal_origin ignored: use https://<host>.<tailnet>.ts.net")
        return ""
    return v


def child_specs(opts, data="/data", portal_ready=None, entries=None, origin=None, pub=""):
    """[{name, env}] for every watcher.py to run: the default instance (the admin), then each pilot's. 1.6.0: a pilot
    whose entry has portal: true and whose folders are ready (portal_ready; None: every such entry) also gets
    FLIGHT_WATCHER_PORTAL=1, its folder, the key path and the origin; pub (the signing key's public half) goes to the
    default instance for the Web UI."""
    entries = pilot_entries(opts) if entries is None else entries
    specs = [{"name": "", "env": {"FLIGHT_WATCHER_PORTAL_PUB": pub} if pub else {}}]
    for name, want in entries:
        env = {
            "FLIGHT_WATCHER_DATA": f"{data}/{name}",
            "FLIGHT_WATCHER_PREFIX": f"flight_watcher_{name}",
            "FLIGHT_WATCHER_INSTANCE": name,
            "FLIGHT_WATCHER_OPTIONS": f"{data}/options.json",
            "FLIGHT_WATCHER_WEB": "0",
        }
        if want and (portal_ready is None or name in portal_ready):
            env.update({"FLIGHT_WATCHER_PORTAL": "1", "FLIGHT_WATCHER_PORTAL_DIR": f"{PORTAL_ROOT}/{name}",
                        "FLIGHT_WATCHER_PORTAL_KEY": f"{data}/portal_ed25519.pem"})
            o = portal_origin(opts) if origin is None else origin
            if o:
                env["FLIGHT_WATCHER_PORTAL_ORIGIN"] = o
        specs.append({"name": name, "env": env})
    return specs


def setup_portal(names, data="/data", root=PORTAL_ROOT, share_fw=SHARE_FW, euid=None, chown=None):
    """1.6.0 (FW-0061): for the pilots whose entry has portal: true (names), before any child starts: the signing key
    (/data/portal_ed25519.pem, 0600, made when missing; its public half logged) and the folders of contract 3.1
    (portal.prepare). Then, on every start, portal off is fail-closed: a pilot folder left under root whose portal is
    not ready this start (its entry no longer has portal: true, or the key or its folders were refused) has its out/
    and in/ emptied (portal.retire). With no portal entry and no root there is nothing at all: no key, no folder, no
    line. Returns (the names whose portal is ready, the public key id)."""
    if not names:
        portal.retire(root, [], log=log)
        return [], ""
    try:
        key = portal.load_key(os.path.join(data, "portal_ed25519.pem"), log=log)
    except Exception as e:  # noqa: BLE001
        log(f"portal signing key unavailable ({type(e).__name__}): no pilot portal this start")
        portal.retire(root, [], log=log)
        return [], ""
    pub = portal.public_id(key)
    log(f"portal signing key {pub}")
    ready = portal.prepare(root, names, share_fw, euid=euid, chown=chown, log=log)
    portal.retire(root, ready, log=log)
    return ready, pub


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
    entries = pilot_entries(opts)
    origin = portal_origin(opts)
    import migrate  # 1.0.0: the one-time move from the old FLICA Watcher app (slug flica_watcher)
    migrate.run()
    import cards  # 0.10.2: the dashboard cards ship with the app
    cards.deploy(app_version(), [n for n, _ in entries])
    ready, pub = setup_portal([n for n, want in entries if want])  # 1.6.0: key and folders before any child
    specs = child_specs(opts, portal_ready=ready, entries=entries, origin=origin, pub=pub)
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

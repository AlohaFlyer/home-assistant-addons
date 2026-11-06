"""Flight Watcher dashboard cards: deployed by the add-on on every start (0.10.2).

The cards live in git under www/ (copied to /app/www in the image). run.py calls deploy() once before the
watchers start:
- every www/flight-watcher-*.js goes to /homeassistant/www/ (HA's /local/), written only when its content changed;
- the pilot's date of hire (DOH) lives in /data/cards.json {"doh": "YYYY-MM-DD"}: personal data, never in git and
  (FW-0010) never in a deployed card, since HA serves /local/ with no login. The Watcher publishes it in
  sensor.<prefix>_state (attribute doh) and the schedule card reads it there; every card file carries the placeholder.
  On the first deploy a DOH an older version wrote into the card on disk is moved to /data/cards.json (load_doh)
  before that card is replaced;
- a second pilot (option second_pilot) gets a copy of every card (flight-watcher-*-<name>.js, from pilot_copy(), formerly
  /config/www/make_pilot_cards.py) reading that pilot's entities, topics, helpers and finds files;
- flight-watcher-cards.json lists the cards and the app version, and flight-watcher-loader.js (the one dashboard
  resource, /local/flight-watcher-loader.js) reads that list with cache "no-store" and imports each card with
  ?v=<version>, so a card change ships with an app update and no resource needs a manual ?v= bump.
"""
import glob
import json
import os
import re

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
DST = "/homeassistant/www"
SETTINGS = "/data/cards.json"
LOADER = "flight-watcher-loader.js"
MANIFEST = "flight-watcher-cards.json"
DOH_RE = re.compile(r'DOH = "(\d{4}-\d{2}-\d{2})"')
PLACEHOLDER_DOH = "2000-01-01"
NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
CARD_RE = re.compile(r"flight-watcher-[a-z]+(-[a-z]+)*-card|flight-watcher-row-colors")

LOADER_JS = """// Flight Watcher card loader, written by the add-on (cards.py). The only dashboard resource the cards need:
// it reads the card list and app version fresh on every page load and imports each card with ?v=<version>.
(async () => {
  try {
    const r = await fetch("/local/%s", { cache: "no-store" });
    const m = await r.json();
    for (const f of m.cards || []) {
      import(`/local/${f}?v=${encodeURIComponent(m.version)}`).catch((e) => console.error("Flight Watcher card", f, e));
    }
  } catch (e) {
    console.error("Flight Watcher loader", e);
  }
})();
""" % MANIFEST


def log(msg):
    import time
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [cards]", msg, flush=True)


def sources(src=SRC):
    """{basename: text} for every card in the image (originals only, never a pilot copy)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(src, "flight-watcher-*.js"))):
        base = os.path.basename(p)[:-3]
        if CARD_RE.fullmatch(base):
            out[base] = open(p, encoding="utf-8").read()
    return out


def set_doh(s, doh):
    return DOH_RE.sub(f'DOH = "{doh}"', s, count=1)


def pilot_copy(s, name):
    """A second pilot's copy of one card. The blanket flight_watcher -> flight_watcher_<name> also moves the
    helpers (input_*.flight_watcher_*) and the localStorage keys ("flight_watcher_..."); the hyphenated names
    (/local/flight-watcher/, the dashboard /flight-watcher/, elements flight-watcher-*) are handled one by one."""
    s = s.replace("flight_watcher", f"flight_watcher_{name}")
    s = s.replace("/local/flight-watcher/finds_", f"/local/flight-watcher/{name}/finds_")
    s = s.replace("/local/flight-watcher/school_", f"/local/flight-watcher/{name}/school_")
    s = s.replace('"/flight-watcher/recall"', f'"/flight-watcher-{name}/recall"')
    s = s.replace('"flight-watcher-pilot"', f'"flight-watcher-pilot-{name}"')
    s = re.sub(r'customElements\.define\("(flight-watcher-[a-z-]+)"', rf'customElements.define("\1-{name}"', s)
    s = re.sub(r'customElements\.get\("(flight-watcher-[a-z-]+)"\)', rf'customElements.get("\1-{name}")', s)
    s = re.sub(r'(customCards\.push\(\{ type: ")(flight-watcher-[a-z-]+)", name: "([^"]*)"',
               rf'\1\2-{name}", name: "\3 ({name})"', s)
    s = set_doh(s, PLACEHOLDER_DOH)  # FW-0010: the source holds the placeholder already; kept as a guard
    s = s.replace("Ryan", "")
    return s


def load_doh(settings=SETTINGS, dst=DST):
    """The pilot's DOH from settings; on first use migrate it from the deployed schedule card and save it."""
    try:
        d = json.load(open(settings))
        if isinstance(d, dict) and DOH_RE.fullmatch(f'DOH = "{d.get("doh", "")}"'):
            return d["doh"]
    except (OSError, ValueError):
        pass
    m = None
    for card in ("flight-watcher-schedule-card.js", "flica-schedule-card.js"):  # 1.0.0: the pre-rename name too
        try:
            m = DOH_RE.search(open(os.path.join(dst, card), encoding="utf-8").read())
        except OSError:
            continue
        if m and m.group(1) != PLACEHOLDER_DOH:
            break
    if m and m.group(1) != PLACEHOLDER_DOH:
        try:
            with open(settings, "w") as f:
                json.dump({"doh": m.group(1)}, f)
            log("DOH migrated from the deployed schedule card to " + settings)
        except OSError as e:
            log(f"DOH not saved ({e})")
        return m.group(1)
    return None


def _write(path, text):
    """Write only when different (atomic). True when written."""
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def build(version, pilots=(), src=SRC):
    """{filename: text} of everything to deploy, without touching disk. FW-0010: no DOH goes into any card (the
    schedule card reads it from sensor.<prefix>_state); set_doh() puts the placeholder back if a source lost it."""
    files, cards = {}, []
    srcs = sources(src)
    for base, s in srcs.items():
        files[f"{base}.js"] = set_doh(s, PLACEHOLDER_DOH)
        cards.append(f"{base}.js")
    for name in pilots:
        if not NAME_RE.match(name or ""):
            continue
        for base, s in srcs.items():
            files[f"{base}-{name}.js"] = pilot_copy(s, name)
            cards.append(f"{base}-{name}.js")
    files[MANIFEST] = json.dumps({"version": version, "cards": cards}, indent=1) + "\n"
    files[LOADER] = LOADER_JS
    return files


def deploy(version, pilots=(), src=SRC, dst=DST, settings=SETTINGS):
    """Copy the cards to HA's www folder. Never raises: a failure is logged and the watchers start anyway."""
    try:
        if not os.path.isdir(dst):
            log(f"{dst} not mapped; cards not deployed")
            return []
        if not load_doh(settings, dst):  # before the cards are written: moves a DOH an older deploy left in a card
            log(f"no DOH on file: set {settings} {{\"doh\": \"YYYY-MM-DD\"}}; the schedule card asks for the longevity year")
        written = [n for n, t in build(version, pilots, src).items() if _write(os.path.join(dst, n), t)]
        log(f"cards {version}: {len(written)} file(s) updated" + (f" ({', '.join(written)})" if written else ""))
        return written
    except Exception as e:  # noqa: BLE001
        log(f"card deploy failed: {e}")
        return []


if __name__ == "__main__":  # manual run inside the container: python3 /app/cards.py [version] [pilot ...]
    import sys
    deploy(sys.argv[1] if len(sys.argv) > 1 else "dev", sys.argv[2:])

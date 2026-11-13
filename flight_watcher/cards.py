"""Flight Watcher dashboard cards: deployed by the add-on on every start (0.10.2).

The cards live in git under www/ (copied to /app/www in the image). run.py calls deploy() once before the
watchers start:
- every www/flight-watcher-*.js goes to /homeassistant/www/ (HA's /local/), written only when its content changed;
- the pilot's date of hire (DOH) lives in /data/cards.json {"doh": "YYYY-MM-DD"}: personal data, never in git and
  (FW-0010) never in a deployed card, since HA serves /local/ with no login. The Watcher publishes it in
  sensor.<prefix>_state (attribute doh) and the schedule card reads it there; every card file carries the placeholder.
  On the first deploy a DOH an older version wrote into the card on disk is moved to /data/cards.json (load_doh)
  before that card is replaced;
- each pilot (option pilots, or second_pilot) gets a copy of every card (flight-watcher-*-<name>.js, from pilot_copy(), formerly
  /config/www/make_pilot_cards.py) reading that pilot's entities, topics, helpers and finds files;
- flight-watcher-cards.json lists the cards and the app version, and flight-watcher-loader.js (the one dashboard
  resource, /local/flight-watcher-loader.js) reads that list with cache "no-store" and imports each card with
  ?v=<version>, so a card change ships with an app update and no resource needs a manual ?v= bump.
"""
import glob
import json
import os
import re

import roles

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
DST = "/homeassistant/www"
SETTINGS = "/data/cards.json"
LOADER = "flight-watcher-loader.js"
MANIFEST = "flight-watcher-cards.json"
DOH_RE = re.compile(r'DOH = "(\d{4}-\d{2}-\d{2})"')
PLACEHOLDER_DOH = "2000-01-01"
NAME_RE = roles.NAME_RE  # 1.5.0: the pilot name rule (single underscores between words)
CARD_RE = re.compile(r"flight-watcher-[a-z]+(-[a-z]+)*-card|flight-watcher-row-colors")

LOADER_JS = """// Flight Watcher card loader, written by the add-on (cards.py). The only dashboard resource the cards need:
// it reads the card list and app version fresh on every page load and imports each card with ?v=<version>.
// 1.7.2 (Ryan, Nov 12, Sydney: the Working Flight page said "Configuration error"): the phone app keeps one page open
// for days, so a card a release adds (the 1.7.1 layover card) was never imported while the dashboard already asked
// for it. The list is read again whenever the page comes back to the screen and every 5 min; a card not imported yet
// is imported then, and one whose import failed is tried again (a new URL, since a browser keeps a failed module).
(async () => {
  const done = new Set();
  const tries = {};
  let busy = false;
  const load = async () => {
    if (busy) return;
    busy = true;
    try {
      const r = await fetch("/local/%s", { cache: "no-store" });
      const m = await r.json();
      for (const f of m.cards || []) {
        if (done.has(f)) continue;
        done.add(f);
        const n = (tries[f] = (tries[f] || 0) + 1);
        const q = `?v=${encodeURIComponent(m.version)}${n > 1 ? `&r=${n}` : ""}`;
        import(`/local/${f}${q}`).catch((e) => { done.delete(f); console.error("Flight Watcher card", f, e); });
      }
    } catch (e) {
      console.error("Flight Watcher loader", e);
    } finally {
      busy = false;
    }
  };
  await load();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
  setInterval(load, 300000);
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
    # the pilot's own files under www/flight-watcher/<name>/: finds months, the school calendar and (FW-0060) the
    # tickets, versions, pickers and recall list files, and (FW-0069) the pilot card's pilotver list file; the
    # pairings package stays shared
    s = re.sub(r"/local/flight-watcher/(finds|school|tickets|versions|pickers|recall|pilotver)_",
               rf"/local/flight-watcher/{name}/\1_", s)
    s = s.replace('"/flight-watcher/recall"', f'"/flight-watcher-{name}/recall"')
    s = s.replace('"flight-watcher-pilot"', f'"flight-watcher-pilot-{name}"')
    s = re.sub(r'customElements\.define\("(flight-watcher-[a-z-]+)"', rf'customElements.define("\1-{name}"', s)
    s = re.sub(r'customElements\.get\("(flight-watcher-[a-z-]+)"\)', rf'customElements.get("\1-{name}")', s)
    s = re.sub(r'(customCards\.push\(\{ type: ")(flight-watcher-[a-z-]+)", name: "([^"]*)"',
               rf'\1\2-{name}", name: "\3 ({name})"', s)
    s = set_doh(s, PLACEHOLDER_DOH)  # FW-0010: the source holds the placeholder already; kept as a guard
    return scrub_names(s)


# 1.7.1 (F#96): the admin's name never reaches a pilot's copy. Deleting it left broken comments in the source a pilot
# can view ("(1.4.5,  Nov 6: labeled ...", "'s card never shows them."), so it becomes a neutral word instead,
# capitalized where it starts a sentence or a comment. Review r4: in any letter case (the tickets card's Claude prompt
# says "reporter is not ryan", the stored reporter id), and the name of his house's Home Assistant ("Pako HI") too.
_START = r"(^|[.!?]\s+|//\s*|/\*\s*)"
_NAMES = ((re.compile(r"\bryan\b", re.I), "the admin"),
          (re.compile(r"\bpako(?: hi)?\b", re.I), "the admin's Home Assistant"))


def scrub_names(s):
    """The admin's first name and his Home Assistant's name, in a pilot's card copy, whole words in any case, as "the
    admin" and "the admin's Home Assistant" (capitalized at a sentence's or a comment's start)."""
    for rx, word in _NAMES:
        s = re.sub(_START + rx.pattern, lambda m, w=word: m.group(1) + w[0].upper() + w[1:], s, flags=re.M | re.I)
        s = rx.sub(word, s)
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

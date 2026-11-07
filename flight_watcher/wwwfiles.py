"""FW-0010: no crew names or employee numbers at a guessable path under Home Assistant's www folder.

HA serves /config/www as /local/ with NO login (also through the Nabu Casa URL), so a file there is public to anyone
who knows its name; HA does not list folders (a GET on /local/flight-watcher/ is 403). The finds month files carry
pickers' and captains' names and employee numbers, so each instance names them finds_<YYYY-MM>_<key>.json, where
<key> is a random 128-bit hex key made once and kept in that instance's /data (mode 0600). The key is published only
in an attribute of sensor.<prefix>_finds (reading HA states needs a login), where the finds card picks it up. It is
never logged: scrub() takes it out of any error text first.

FW-0060 (1.4.7): the long lists that used to ride in sensor attributes (tickets about 39 KB, schedule versions about
33 KB, pickers and the recall days growing past HA's 16 KB recorder limit) go to <name>_<key>.json in the same folder
under the same key (LIST_NAMES), and the sensor carries a short form plus file_key and rev (a hash of the file) so
the card fetches the file again when it changes. They are cleaned like the finds files: in an instance's own folder
every list file not under its current key goes.

The other files the Watcher writes under www hold no names: pairings_<YYYY-MM>.json (the company's pairing package:
times, routes, crew complement codes such as CA01FO01) and the cards. The cards carry no date of hire either: the
pilot's DOH stays in /data/cards.json and goes out in sensor.<prefix>_state (cards.py). school_<YYYY-YY>.json is a
school calendar put there by hand. The crew index and tickets live in /share, which HA does not serve.
Pure file logic; no network, no MQTT."""
import os
import re
import secrets

KEY_RE = re.compile(r"[0-9a-f]{32}")
# every finds month file the Watcher has ever written: finds_<YYYY-MM>.json before FW-0010, finds_<YYYY-MM>_<key>.json
# since, plus the .tmp of an atomic write cut short. Nothing else in the folder matches.
FINDS_RE = re.compile(r"finds_(\d{4}-\d{2})(?:_([0-9a-f]{32}))?\.json(?:\.tmp)?")


LIST_NAMES = ("tickets", "versions", "pickers", "recall")  # FW-0060
LIST_RE = re.compile(r"(%s)_([0-9a-f]{32})\.json(?:\.tmp)?" % "|".join(LIST_NAMES))


def load_key(path):
    """This instance's key from path; made (secrets, 128 bits) and saved 0600 on first use or when unreadable."""
    try:
        k = open(path, encoding="ascii").read().strip()
        if KEY_RE.fullmatch(k):
            return k
    except (OSError, ValueError):
        pass
    k = secrets.token_hex(16)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(k + "\n")
    os.replace(tmp, path)
    return k


def finds_name(month, key):
    """finds_<YYYY-MM>_<key>.json: the month file name the finds card fetches."""
    return f"finds_{month}_{key}.json"


def list_name(name, key):
    """<name>_<key>.json (FW-0060): a list file a card fetches, name one of LIST_NAMES."""
    return f"{name}_{key}.json"


def stale(name, key, own):
    """True for a finds file to delete. In the instance's own folder: every finds file but its own current names
    (the old predictable names, files under a key from a reset /data, .tmp leftovers). In any other folder (a second
    pilot's, the pre-1.0.0 www/flica): only the predictable names, since that pilot's own instance keeps its keyed
    files. FW-0060: a list file (LIST_RE) the same way; it never had a predictable name, so only the own folder."""
    lm = LIST_RE.fullmatch(name)
    if lm:
        return own and name != list_name(lm.group(1), key)
    m = FINDS_RE.fullmatch(name)
    if not m:
        return False
    if own:
        return name != finds_name(m.group(1), key)
    return m.group(2) is None


def cleanup(own_dir, key, other_dirs=()):
    """Delete the stale finds files (see stale()) from own_dir and the predictable ones from other_dirs. Returns how
    many went. A folder that is missing or unreadable is skipped; a file another instance removed first is fine."""
    n = 0
    for d, own in [(own_dir, True)] + [(x, False) for x in other_dirs if x != own_dir]:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if stale(name, key, own):
                try:
                    os.remove(os.path.join(d, name))
                    n += 1
                except FileNotFoundError:
                    pass
    return n


def subdirs(root):
    """Immediate subfolders of root (a second pilot's www folder is one), [] when root is missing."""
    try:
        return [os.path.join(root, x) for x in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, x))]
    except OSError:
        return []


def scrub(text, key):
    """text with the key taken out, for a log line (an OSError names the file it failed on)."""
    s = str(text)
    return s.replace(key, "<key>") if key else s

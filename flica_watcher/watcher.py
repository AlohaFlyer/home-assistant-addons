"""FLICA Watcher: one kept-alive FLICA session, open time pot diff, HA over MQTT.

Login rule: never two login attempts in a row without a success in between.
A failed login, or anything unexpected, parks the watcher until re-armed from HA.
v0.2 is READ ONLY: rules match and log; nothing is ever submitted to FLICA.
"""
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import requests
from playwright.sync_api import sync_playwright

import rules as R
import web
from pot import BLOCK_HINTS, detail_url, parse_detail, soft_time, bcid, bcid_after, bcid_key, classify, header_fingerprint, is_pot_page, parse_pot, pot_links, visible_text
from store import Store

VERSION = "0.2.3"
BASE = "https://ha2.flica.net"
DATA = "/data"
STATE_FILE = f"{DATA}/state.json"
DB_FILE = f"{DATA}/watcher.db"
RULES_FILE = f"{DATA}/rules.json"
COOKIES = f"{DATA}/storage_state.json"
OPTS = json.load(open(f"{DATA}/options.json"))

logging.basicConfig(
    level=getattr(logging, OPTS.get("log_level", "info").upper()),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("flica")

MOBILE_POT = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
BACKOFF_MIN = [1, 2, 4, 8, 16, 30]  # minutes before each re-login on repeated needs_login; then park
HST = timezone(timedelta(hours=-10))

T = "flica_watcher"
AVAIL = f"{T}/status"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- state
DEFAULT_STATE = {"baseline": {}, "machine": "idle", "pot_urls": {}, "kills": [], "last_login_ok": None,
                 "fingerprints": {}, "relogin_streak": 0}
DB = Store(DB_FILE, legacy_json=STATE_FILE, default_state=DEFAULT_STATE)


def load_state():
    s = DB.load_state()
    for k, v in DEFAULT_STATE.items():
        s.setdefault(k, json.loads(json.dumps(v)))
    return s


def save_state(s):
    DB.save_state(s)


S = load_state()
WAKE = threading.Event()
FLAGS = {"hunt": False, "pause": False, "rearm": False}
# Check frequency from the dashboard sliders (number entities); persisted in state.
# Each gap is randomized +-30 % around the setting so the checks never look machine-regular.
FREQ_LIMITS = {"normal_min": (1, 60), "hunt_s": (15, 300)}
JITTER = 0.3
CHECK_NOW_MIN_GAP_S = 10
RULES = {"list": [], "published": set()}
RULE_LOCK = threading.Lock()


# ---------------------------------------------------------------- rules file
def load_rules():
    if not os.path.exists(RULES_FILE):
        clean, _ = R.validate(R.EXAMPLE)
        write_rules(clean)
        log.info("rules.json created with the example SIN alert rule (alert only, dry run)")
        return clean
    try:
        clean, errs = R.validate(json.load(open(RULES_FILE)))
    except Exception as e:
        clean, errs = [], [f"rules.json unreadable: {e}"]
    if errs:
        log.warning("rules.json has errors, running with NO rules until fixed: %s", errs)
    return clean


def write_rules(lst):
    tmp = RULES_FILE + ".tmp"
    json.dump(lst, open(tmp, "w"), indent=2)
    os.replace(tmp, RULES_FILE)


def save_rules_from_page(data):
    clean, errs = R.validate(data)
    if errs:
        return errs
    with RULE_LOCK:
        write_rules(clean)
        RULES["list"] = clean
    if MQ:
        publish_rules(MQ)
    return []


# ---------------------------------------------------------------- mqtt
def mqtt_creds():
    tok = os.environ.get("SUPERVISOR_TOKEN")
    r = requests.get("http://supervisor/services/mqtt",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]


def on_message(c, u, msg):
    p = msg.payload.decode().strip().upper()
    if msg.topic == f"{T}/hunt/set":
        FLAGS["hunt"] = p == "ON"
        c.publish(f"{T}/hunt/state", "ON" if FLAGS["hunt"] else "OFF", retain=True)
        log.info("hunt mode %s", FLAGS["hunt"])
    elif msg.topic == f"{T}/pause/set":
        FLAGS["pause"] = p == "ON"
        c.publish(f"{T}/pause/state", "ON" if FLAGS["pause"] else "OFF", retain=True)
        log.info("pause %s", FLAGS["pause"])
    elif msg.topic == f"{T}/rearm/press":
        FLAGS["rearm"] = True
        log.info("re-arm pressed")
    elif msg.topic in (f"{T}/hunt/state", f"{T}/pause/state"):
        key = "hunt" if "hunt" in msg.topic else "pause"
        FLAGS[key] = p == "ON"
        return
    elif msg.topic == f"{T}/check_now/press":
        # Waking the loop runs a check right away (only when idle or hunting; paused/stopped ignore it).
        if time.time() - S.get("last_check_ts", 0) < CHECK_NOW_MIN_GAP_S:
            log.info("check now ignored: last check under %d s ago", CHECK_NOW_MIN_GAP_S)
            return
        log.info("check now pressed")
    elif msg.topic in (f"{T}/freq/normal_min/set", f"{T}/freq/hunt_s/set"):
        key = msg.topic.split("/")[2]
        lo, hi = FREQ_LIMITS[key]
        try:
            v = int(round(float(p)))
        except ValueError:
            return
        S.setdefault("freq", {})[key] = max(lo, min(hi, v))
        save_state(S)
        c.publish(f"{T}/freq/{key}/state", str(S["freq"][key]), retain=True)
        log.info("frequency %s = %s", key, S["freq"][key])
    elif msg.topic.startswith(f"{T}/rule/") and msg.topic.endswith("/live/set"):
        rule_live_cmd(c, msg.topic.split("/")[2], p == "ON")
        return
    WAKE.set()


def rule_live_cmd(c, rid, want):
    with RULE_LOCK:
        rule = next((r for r in RULES["list"] if r["id"] == rid), None)
    if rule is None:
        return
    if want:
        ok, why = R.live_allowed(rule)
        if not ok:
            log.info("rule %s live refused: %s", rid, why)
            c.publish(f"{T}/rule/{rid}/live/state", "OFF", retain=True)
            c.publish(f"{T}/event/rule_refused", json.dumps({"rule_id": rid, "reason": why, "at": now_iso()}))
            return
    DB.set_live(rid, want)
    c.publish(f"{T}/rule/{rid}/live/state", "ON" if want else "OFF", retain=True)
    log.info("rule %s live=%s", rid, want)


DEV = {"identifiers": ["flica_watcher"], "name": "FLICA Watcher", "manufacturer": "Pako HI",
       "sw_version": VERSION}


def publish_rules(c):
    """One live switch per rule via MQTT discovery; removes switches of deleted rules."""
    with RULE_LOCK:
        lst = list(RULES["list"])
    flags = DB.live_flags()
    ids = {r["id"] for r in lst}
    for rid in RULES["published"] - ids:
        c.publish(f"homeassistant/switch/flica_watcher/rule_{rid}_live/config", "", retain=True)
        c.publish(f"{T}/rule/{rid}/live/state", "", retain=True)
        DB.drop_live(rid)
    for r in lst:
        cfg = {"availability_topic": AVAIL, "device": DEV, "name": f"Rule {r['name']} live",
               "unique_id": f"flica_rule_{r['id']}_live", "object_id": f"flica_rule_{r['id']}_live",
               "command_topic": f"{T}/rule/{r['id']}/live/set", "state_topic": f"{T}/rule/{r['id']}/live/state",
               "icon": "mdi:rocket-launch", "entity_category": "config"}
        c.publish(f"homeassistant/switch/flica_watcher/rule_{r['id']}_live/config", json.dumps(cfg), retain=True)
        live = flags.get(r["id"], False) and R.live_allowed(r)[0]
        c.publish(f"{T}/rule/{r['id']}/live/state", "ON" if live else "OFF", retain=True)
    RULES["published"] = ids
    active = [r for r in lst if r["enabled"]]
    c.publish(f"{T}/rules/state", json.dumps({
        "count": len(active),
        "rules": [{"id": r["id"], "name": r["name"], "mode": r["mode"], "live": flags.get(r["id"], False),
                   "created_at": r["created_at"]} for r in lst]}), retain=True)


def publish_finds():
    pub("finds", {"count": len(f := DB.recent_finds(50)), "finds": f})


def discovery(c):
    dev = DEV
    base = {"availability_topic": AVAIL, "device": dev}
    ents = [
        ("sensor", "state", {"name": "State", "state_topic": f"{T}/state", "icon": "mdi:airplane-search",
                             "json_attributes_topic": f"{T}/state_attr"}),
        ("sensor", "last_check", {"name": "Last check", "state_topic": f"{T}/last_check",
                                  "device_class": "timestamp"}),
        ("sensor", "next_check", {"name": "Next check", "state_topic": f"{T}/next_check",
                                  "device_class": "timestamp", "icon": "mdi:timer-sand"}),
        ("sensor", "pot_count", {"name": "Pot count", "state_topic": f"{T}/pot/state",
                                 "value_template": "{{ value_json.count }}", "state_class": "measurement",
                                 "unit_of_measurement": "pairings",
                                 "json_attributes_topic": f"{T}/pot/state", "icon": "mdi:format-list-bulleted"}),
        ("sensor", "finds", {"name": "Finds", "state_topic": f"{T}/finds",
                             "value_template": "{{ value_json.count }}",
                             "json_attributes_topic": f"{T}/finds", "icon": "mdi:history"}),
        ("sensor", "rules_active", {"name": "Rules active", "state_topic": f"{T}/rules/state",
                                    "value_template": "{{ value_json.count }}",
                                    "json_attributes_topic": f"{T}/rules/state", "icon": "mdi:filter-cog"}),
        ("sensor", "last_match", {"name": "Last match", "state_topic": f"{T}/last_match",
                                  "value_template": "{{ value_json.rule_id }}: {{ value_json.row.pairing }}",
                                  "json_attributes_topic": f"{T}/last_match", "icon": "mdi:bullseye-arrow"}),
        ("sensor", "last_new", {"name": "Last new pairing", "state_topic": f"{T}/last_new",
                                "value_template": "{{ value_json.pairing }}",
                                "json_attributes_topic": f"{T}/last_new", "icon": "mdi:new-box"}),
        ("binary_sensor", "session_ok", {"name": "Session OK", "state_topic": f"{T}/session",
                                         "device_class": "connectivity"}),
        ("switch", "hunt_mode", {"name": "Hunt mode", "command_topic": f"{T}/hunt/set",
                                 "state_topic": f"{T}/hunt/state", "icon": "mdi:target"}),
        ("switch", "pause", {"name": "Pause", "command_topic": f"{T}/pause/set",
                             "state_topic": f"{T}/pause/state", "icon": "mdi:pause-circle"}),
        ("button", "rearm", {"name": "Re-arm", "command_topic": f"{T}/rearm/press", "icon": "mdi:restart"}),
        ("button", "check_now", {"name": "Check now", "command_topic": f"{T}/check_now/press",
                                 "icon": "mdi:refresh"}),
        ("number", "normal_minutes", {"name": "Normal check every", "command_topic": f"{T}/freq/normal_min/set",
                                      "state_topic": f"{T}/freq/normal_min/state", "min": 1, "max": 60,
                                      "step": 1, "mode": "slider", "unit_of_measurement": "min",
                                      "icon": "mdi:timer-outline"}),
        ("number", "hunt_seconds", {"name": "Hunt check every", "command_topic": f"{T}/freq/hunt_s/set",
                                    "state_topic": f"{T}/freq/hunt_s/state", "min": 15, "max": 300,
                                    "step": 5, "mode": "slider", "unit_of_measurement": "s",
                                    "icon": "mdi:timer-alert-outline"}),
    ]
    for comp, oid, cfg in ents:
        cfg = {**base, **cfg, "unique_id": f"flica_watcher_{oid}", "object_id": f"flica_watcher_{oid}"}
        c.publish(f"homeassistant/{comp}/flica_watcher/{oid}/config", json.dumps(cfg), retain=True)


def mqtt_start():
    m = mqtt_creds()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="flica_watcher")
    c.username_pw_set(m["username"], m["password"])
    c.will_set(AVAIL, "offline", retain=True)
    c.on_message = on_message

    def on_connect(cl, u, f, rc, p=None):
        cl.publish(AVAIL, "online", retain=True)
        discovery(cl)
        for t in ("hunt/set", "pause/set", "rearm/press", "hunt/state", "pause/state", "rule/+/live/set",
                  "check_now/press", "freq/normal_min/set", "freq/hunt_s/set"):
            cl.subscribe(f"{T}/{t}")
        fq = freq()
        cl.publish(f"{T}/freq/normal_min/state", str(fq["normal_min"]), retain=True)
        cl.publish(f"{T}/freq/hunt_s/state", str(fq["hunt_s"]), retain=True)
        publish_rules(cl)

    c.on_connect = on_connect
    c.connect(m["host"], int(m["port"]))
    c.loop_start()
    return c


MQ = None


def pub(topic, payload, retain=True):
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    MQ.publish(f"{T}/{topic}", payload, retain=retain)


def set_machine(state, note=""):
    if S.get("machine") != state:
        log.info("state %s -> %s %s", S.get("machine"), state, note)
    if S.get("machine") != state or not S.get("since"):
        S["since"] = now_iso()
    S["machine"] = state
    S["note"] = note
    save_state(S)
    pub("state", state)
    pub("state_attr", {"note": note, "version": VERSION, "since": S["since"]})


# ---------------------------------------------------------------- browser
class Flica:
    def __init__(self, pw):
        self.browser = pw.chromium.launch(headless=True)
        self.ctx = None
        self.new_context()

    def new_context(self, fresh=False):
        if self.ctx:
            self.ctx.close()
        kw = {"storage_state": COOKIES} if (os.path.exists(COOKIES) and not fresh) else {}
        self.ctx = self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"), **kw)

    def save(self):
        self.ctx.storage_state(path=COOKIES)

    def login(self):
        """Exactly one attempt. Returns 'ok', 'failed' or 'blocked'."""
        log.info("login attempt")
        S["last_login_attempt"] = now_iso()
        save_state(S)
        self.new_context(fresh=True)  # old cookies can skip the login form and break the login
        page = self.ctx.new_page()
        try:
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
            pw_in = page.locator("input[type=password]").first
            pw_in.wait_for(timeout=20000)
            inputs = page.evaluate("""() => [...document.querySelectorAll('input')].map((e, i) => {
                e.setAttribute('data-fwi', String(i));
                const r = e.getBoundingClientRect();
                return {i, type: (e.type || '').toLowerCase(), name: e.name || '', id: e.id || '',
                        vis: r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'};
            })""")
            log.info("login form inputs: %s", [(x["type"], x["name"], x["id"], x["vis"]) for x in inputs])
            pw_idx = next(x["i"] for x in inputs if x["type"] == "password" and x["vis"])
            skip = {"hidden", "password", "submit", "button", "checkbox", "radio", "image", "reset"}
            cands = [x for x in inputs if x["i"] < pw_idx and x["vis"] and x["type"] not in skip]
            if not cands:
                log.warning("no username field found before the password field")
                return "failed"
            user_in = page.locator(f"input[data-fwi='{cands[-1]['i']}']")
            pw_in = page.locator(f"input[data-fwi='{pw_idx}']")
            user_in.fill(OPTS["username"])
            pw_in.fill(OPTS["password"])
            pw_in.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=45000)
            time.sleep(4)
            html = page.content()
            for fr in page.frames:
                try:
                    html += fr.content()
                except Exception:
                    pass
            low = html.lower()
            try:
                os.makedirs("/share/flica_watcher", exist_ok=True)
                page.screenshot(path="/share/flica_watcher/last_login.png", full_page=True)
                vis = page.inner_text("body")[:600].replace("\n", " | ")
                log.info("after login url=%s text=%s", page.url.split("?")[0], vis)
            except Exception as e:
                log.info("diag capture failed: %s", e)
            if "forward to the main menu" in low or "/online/mainmenu.cgi" in page.url:
                time.sleep(5)
                html = page.content()
                for fr in page.frames:
                    try:
                        html += fr.content()
                    except Exception:
                        pass
                low = html.lower()
            text = visible_text(html)
            on_menu = "/online/mainmenu.cgi" in page.url or "/full/" in page.url
            no_pw = page.locator("input[type=password]:visible").count() == 0
            # The main menu's "Recent Updates" bulletin can mention captcha/MFA in its news
            # text, so reaching the menu with no password box is a successful login.
            if on_menu and no_pw:
                self.save()
                S["last_login_ok"] = now_iso()
                save_state(S)
                return "ok"
            hits = [h for h in BLOCK_HINTS if h in text]
            if hits:
                i = text.find(hits[0])
                log.warning("block hints matched (visible text): %s near: %s", hits, text[max(0, i - 120):i + 120])
                return "blocked"
            if "sign out" in low and no_pw:
                self.save()
                S["last_login_ok"] = now_iso()
                save_state(S)
                return "ok"
            return "failed"
        except Exception as e:
            log.warning("login error: %s", e)
            return "failed"
        finally:
            page.close()

    def discover_pot_urls(self):
        """Walk the main menu once, open each 'View Opentime Pot' under the configured
        section for the current and next month, and remember the content frame URL."""
        page = self.ctx.new_page()
        found = {}
        try:
            page.goto(BASE + "/online/mainmenu.cgi", wait_until="domcontentloaded", timeout=45000)
            menu = None
            for _ in range(10):  # mainmenu.cgi first shows a "forwarding to the Main Menu" page
                time.sleep(2)
                menu = next((f for f in page.frames if "leftmenu" in f.url.lower()), None)
                if menu:
                    break
            kind = classify(page.content())
            if not menu:
                log.warning("main menu: no leftmenu frame (classify=%s) url=%s frames=%s", kind,
                            page.url.split("?")[0], [f.url.split("?")[0] for f in page.frames])
                if kind in ("killed", "expired"):
                    return None
                # Headless main menu can stall on a reCAPTCHA forward; the mobile pot page is
                # frameless and works with the same session cookie (Ryan's Distill used it).
                html = self.fetch(MOBILE_POT)
                mk = classify(html)
                txt = visible_text(html)
                log.info("mobile pot probe: classify=%s len=%d text=%s", mk, len(html), txt[:1500])
                rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
                log.info("mobile pot rows=%d sample=%s", len(rows), [r[:400] for r in rows[:4]])
                if mk in ("killed", "expired"):
                    return None
                if "open time" in txt or "opentime" in txt:
                    # key "mobile" kept for the first page so the v0.1.x baseline carries over
                    urls = {"mobile": MOBILE_POT}
                    if OPTS.get("watch_next_month", True):
                        links = pot_links(html, MOBILE_POT)
                        log.info("mobile pot links to other bid months: %s", links)
                        mine = bcid(MOBILE_POT)
                        later = sorted((l for l in links if bcid(l["url"]) and bcid_after(bcid(l["url"]), mine)),
                                       key=lambda l: bcid_key(bcid(l["url"])))
                        if later:  # the nearest later bid period only, never an earlier month
                            urls[f"mobile_{bcid(later[0]['url'])}"] = later[0]["url"]
                        if len(urls) < 2:
                            log.info("no next-month pot link on the mobile page yet (opens with the bid month)")
                    return urls
                return None
            links = menu.evaluate(
                """(sec) => {
                  const months = %s; let section = '', month = '', out = [], i = 0;
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                  let n; const re = new RegExp(sec, 'i');
                  while ((n = walker.nextNode())) {
                    if (n.children.length === 0 || n.tagName === 'A') {
                      const t = (n.innerText || '').trim();
                      const m = months.find(x => t.startsWith(x));
                      const bold = parseInt(getComputedStyle(n).fontWeight || '400') >= 600;
                      if (n.tagName !== 'A' && bold && !m && t) section = re.test(t) ? t : '';
                      if (m) month = m;
                      if (n.tagName === 'A' && /View Opentime Pot/i.test(t)) {
                        n.setAttribute('data-fw', String(i)); out.push({i, section, month}); i++;
                      }
                    }
                  }
                  return out;
                }""" % json.dumps(MONTHS),
                OPTS["pot_section"],
            )
            now = datetime.now()
            want = {MONTHS[now.month - 1], MONTHS[now.month % 12]}
            for l in links:
                if not l["section"] or l["month"] not in want or l["month"] in found:
                    continue
                with self.ctx.expect_page(timeout=20000) as pinfo:
                    menu.locator(f"a[data-fw='{l['i']}']").click()
                pot = pinfo.value
                pot.wait_for_load_state("domcontentloaded")
                time.sleep(3)
                alltxt = ""
                for fr in pot.frames:
                    try:
                        alltxt += fr.inner_text("body")
                    except Exception:
                        pass
                cat = OPTS["category_check"].split()
                if cat and not all(c in alltxt for c in cat):
                    log.warning("pot page for %s is not category %s, skipped", l["month"], OPTS["category_check"])
                    pot.close()
                    continue
                for fr in pot.frames:
                    try:
                        if "Opentime Pot" in fr.content() and fr.url.startswith("http"):
                            found[l["month"]] = fr.url
                    except Exception:
                        pass
                pot.close()
            self.save()
            return found
        finally:
            page.close()

    def fetch(self, url):
        r = self.ctx.request.get(url, timeout=45000)
        return r.text()


# ---------------------------------------------------------------- main loop
def freq():
    """Current settings. Defaults are the midpoints of the add-on options (6 min normal, 40 s hunt)."""
    f = dict(S.get("freq") or {})
    f.setdefault("normal_min", max(1, round((OPTS["idle_min_s"] + OPTS["idle_max_s"]) / 2 / 60)))
    f.setdefault("hunt_s", max(15, round((OPTS["hunt_min_s"] + OPTS["hunt_max_s"]) / 2)))
    return f


def gap():
    fq = freq()
    mid = fq["hunt_s"] if FLAGS["hunt"] else fq["normal_min"] * 60
    return random.uniform(mid * (1 - JITTER), mid * (1 + JITTER))


def sleep(sec):
    WAKE.clear()
    WAKE.wait(sec)



def sleep_announced(sec):
    """Sleep, publishing when the next pot check is due (sensor.flica_watcher_next_check)."""
    pub("next_check", datetime.fromtimestamp(time.time() + sec, timezone.utc).isoformat())
    sleep(sec)


def no_next_check():
    pub("next_check", "None")  # HA shows unknown: no check scheduled (paused/stopped)


def try_login(fl, reason):
    """Single attempt. Parks the watcher on anything but success."""
    res = fl.login()
    if res == "ok":
        S["pot_urls"] = {}
        pub("session", "ON")
        set_machine("hunting" if FLAGS["hunt"] else "idle", f"logged in ({reason})")
        return True
    pub("session", "OFF")
    if res == "blocked":
        set_machine("stopped_unexpected", "FLICA asked for captcha/MFA/password change during login")
    else:
        set_machine("stopped_login_failed", f"one login attempt failed ({reason})")
    return False


def hst_midnight_utc():
    d = datetime.now(HST).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat()


def run_rules(month, key, row):
    with RULE_LOCK:
        lst = list(RULES["list"])
    if not lst:
        return
    hits = R.evaluate(lst, row, DB.live_flags(), DB.would_submits_since(hst_midnight_utc()))
    for m in hits:
        DB.add_match(m, f"{month}|{key}")
        log.info("rule match %s %s would_submit=%s (%s)", m["rule_id"], row.get("pairing"),
                 m["would_submit"], m["reason"])
        pub("event/rule_match", m, retain=False)
        pub("last_match", m)


DETAIL_PROBE = {"done": False}


def enrich(fl, ev):
    """One read-only GET of the pairing's mobile detail page: captain name, block, credit,
    soft time (credit minus block). Never clicks or submits. Failure leaves the row as is."""
    try:
        url = detail_url(ev)
        if url:
            page = fl.fetch(url)
            if classify(page) == "ok":
                d = parse_detail(page)
                if not DETAIL_PROBE["done"]:
                    DETAIL_PROBE["done"] = True
                    log.info("detail text %s: %s", ev.get("pairing"), visible_text(page)[:2500])
                ev.update({k: v for k, v in d.items() if k == "captain" or not ev.get(k)})
                ev["detail_url"] = url
    except Exception as e:
        log.info("detail skipped for %s: %s", ev.get("pairing"), e)
    ev.setdefault("captain", "")
    st = soft_time(ev.get("credit"), ev.get("blk"))
    ev["soft"] = st or ""


def detail_probe(fl, pot):
    """Once per start: log one detail page's text so the captain/total parsers can be checked."""
    if DETAIL_PROBE["done"] or not pot:
        return
    row = dict(next(iter(pot.values())))
    enrich(fl, row)
    log.info("detail probe %s: captain=%r blk=%s credit=%s soft=%s", row.get("pairing"),
             row.get("captain"), row.get("blk"), row.get("credit"), row.get("soft"))


CAPTURE_DIR = "/share/flica_watcher/captures"


def capture(fl, month, html):
    """Read-only discovery for t1222 (soft time, captain, fits, FAR): every 6 h save the pot page,
    its links, one pairing detail page and any schedule page this session can already open, so
    the parsers get built from real HTML. Same session, GET only; never clicks or submits."""
    if time.time() - S.get("captured_at", 0) < 6 * 3600:
        return
    S["captured_at"] = time.time()
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        open(f"{CAPTURE_DIR}/pot_{month}.html", "w").write(html)
        url = S["pot_urls"][month]
        links = [{"text": a.get_text(" ", strip=True)[:60], "href": urljoin(url, a["href"])}
                 for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)]
        json.dump(links, open(f"{CAPTURE_DIR}/links_{month}.json", "w"), indent=1)
        picks = [l for l in links if re.match(r"^[A-Z]\d{4}", l["text"])][:1]
        picks += [l for l in links if re.search(r"sched|my trips|calendar", l["text"], re.I)][:1]
        for l in picks:
            if not l["href"].startswith(BASE):
                continue
            page = fl.fetch(l["href"])
            if classify(page) != "ok":
                log.info("capture: %s gave %s, skipped", l["text"], classify(page))
                continue
            name = re.sub(r"[^A-Za-z0-9]+", "_", l["text"])[:30] or "page"
            open(f"{CAPTURE_DIR}/{name}.html", "w").write(page)
        log.info("capture saved to %s: %d links, extra pages %s", CAPTURE_DIR, len(links),
                 [l["text"] for l in picks])
    except Exception as e:
        log.info("capture skipped: %s", e)


def check(fl):
    """One pass. Returns next action hint."""
    if not S.get("pot_urls"):
        urls = fl.discover_pot_urls()
        if urls is None:
            return "needs_login"
        if not urls:
            set_machine("stopped_unexpected", f"no 'View Opentime Pot' found under '{OPTS['pot_section']}'")
            return "stop"
        S["pot_urls"] = urls
        S["discovered_at"] = time.time()
        save_state(S)
        log.info("pot pages: %s", list(urls))
    pot_all = {}
    new_any = False
    for month, url in list(S["pot_urls"].items()):
        html = fl.fetch(url)
        kind = classify(html)
        if kind == "killed":
            return "killed"
        if kind == "blocked":
            set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page")
            return "stop"
        if kind == "expired":
            return "needs_login"
        if not is_pot_page(html, mobile=month.startswith("mobile")):
            S["pot_urls"] = {}
            S["parse_fail"] = S.get("parse_fail", 0) + 1
            save_state(S)
            if S["parse_fail"] >= 3:
                set_machine("stopped_unexpected", "open time page no longer recognised (3 in a row)")
                return "stop"
            return "retry"
        S["parse_fail"] = 0
        fp = header_fingerprint(html)
        if fp:
            old = S["fingerprints"].get(month)
            if old is None:
                S["fingerprints"][month] = fp
                log.info("pot header fingerprint %s: %s", month, fp)
            elif old != fp:
                set_machine("stopped_unexpected",
                            f"pot table layout changed on {month} ({old} -> {fp}); not parsing it. "
                            "Check the page, then Re-arm to accept the new layout")
                S["fingerprint_pending"] = {month: fp}
                save_state(S)
                return "stop"
        pot = parse_pot(html)
        pot_all[month] = pot
        capture(fl, month, html)
        detail_probe(fl, pot)
        base = S["baseline"].get(month)
        new_keys = set()
        if base is None:
            log.info("baseline %s: %d pairings (no alert)", month, len(pot))
        else:
            new_keys = {k for k in pot if k not in base}
            for k in sorted(new_keys):
                ev = {**pot[k], "month": month, "seen": now_iso()}
                enrich(fl, ev)
                log.info("NEW pairing %s", ev)
                pub("event/new_pairing", ev, retain=False)
                pub("last_new", ev)
                run_rules(month, k, pot[k])
        DB.record_pot(month, pot, new_keys)
        new_any = new_any or bool(new_keys)
        S["baseline"][month] = sorted(pot.keys())
    # drop months no longer published
    S["baseline"] = {m: v for m, v in S["baseline"].items() if m in S["pot_urls"]}
    S["relogin_streak"] = 0
    save_state(S)
    if new_any or not S.get("finds_published"):
        publish_finds()
        S["finds_published"] = True
    flat = [dict(v, month=m) for m, p in pot_all.items() for v in p.values()]
    pub("pot/state", {"count": len(flat), "pairings": flat[:60]})
    pub("last_check", now_iso())
    S["last_check_ts"] = time.time()
    pub("session", "ON")
    return "ok"


def main():
    global MQ
    MQ = mqtt_start()
    time.sleep(2)
    if not OPTS.get("username") or not OPTS.get("password"):
        set_machine("stopped_unexpected", "set username and password in the add-on Configuration tab")
    elif S.get("machine", "").startswith("stopped"):
        set_machine(S["machine"], S.get("note", "") + " (still stopped after restart, press Re-arm)")
    else:
        set_machine("idle", "starting")
    RULES["list"] = load_rules()
    publish_rules(MQ)
    publish_finds()
    web.serve(int(os.environ.get("INGRESS_PORT", "8099")), VERSION, lambda: RULES["list"],
              save_rules_from_page, DB, log)
    last_month_check = None
    with sync_playwright() as pw:
        fl = Flica(pw)
        while True:
            st = S.get("machine", "idle")
            if FLAGS["rearm"]:
                FLAGS["rearm"] = False
                if st.startswith("stopped") or st in ("yielded", "backoff"):
                    S["kills"] = []
                    S["pot_urls"] = {}
                    S["parse_fail"] = 0
                    S["relogin_streak"] = 0
                    if S.pop("fingerprint_pending", None):
                        S["fingerprints"] = {}  # Re-arm after a layout park accepts the new layout
                        log.info("re-arm: pot header fingerprints cleared, re-learned on next check")
                    try_login(fl, "re-arm")
                    continue
            if st.startswith("stopped"):
                no_next_check()
                sleep(3600)
                continue
            if FLAGS["pause"]:
                if st != "paused":
                    set_machine("paused", "paused from HA")
                no_next_check()
                sleep(3600)
                continue
            if st == "paused":
                if not try_login(fl, "un-pause"):
                    continue
                st = S["machine"]
            if st == "yielded":
                wait_until = S.get("yield_until", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                if not try_login(fl, "after yield cooldown"):
                    continue
            if st == "backoff":
                wait_until = S.get("relogin_at", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                try_login(fl, f"backoff step {S.get('relogin_streak', 0)}")
                continue
            # next bid month: its pot link appears mid-month, so rediscover every 6 h until found
            if (OPTS.get("watch_next_month", True) and 0 < len(S.get("pot_urls") or {}) < 2
                    and time.time() - S.get("discovered_at", 0) > 6 * 3600):
                log.info("rediscovering pot pages to look for the next bid month")
                S["pot_urls"] = {}
            if time.time() - S.get("pruned_at", 0) > 86400:
                DB.prune()
                S["pruned_at"] = time.time()
            # month rollover: rediscover once per new calendar month
            mk = datetime.now().strftime("%Y-%m")
            if last_month_check and last_month_check != mk:
                S["pot_urls"] = {}
            last_month_check = mk
            try:
                res = check(fl)
            except Exception as e:
                log.warning("check error: %s", e)
                S["net_fail"] = S.get("net_fail", 0) + 1
                if S["net_fail"] >= 3:
                    set_machine("stopped_unexpected", f"3 check errors in a row: {e}")
                sleep_announced(gap())
                continue
            S["net_fail"] = 0
            if res == "needs_login":
                pub("session", "OFF")
                streak = S.get("relogin_streak", 0)
                if streak >= len(BACKOFF_MIN):
                    set_machine("stopped_unexpected",
                                f"session lost {streak} times in a row with no good check between; parked")
                    continue
                wait = BACKOFF_MIN[streak]
                S["relogin_streak"] = streak + 1
                S["relogin_at"] = time.time() + wait * 60
                set_machine("backoff", f"session expired, one login attempt in {wait} min "
                                       f"(step {streak + 1}/{len(BACKOFF_MIN)})")
                continue
            if res == "killed":
                pub("session", "OFF")
                now = time.time()
                S["kills"] = [k for k in S.get("kills", []) if now - k < 86400] + [now]
                recent = [k for k in S["kills"] if now - k < 6 * 3600]
                mult = 2 ** max(0, len(recent) - 1)
                cool = min(OPTS["yield_cooldown_min"] * 60 * mult, 4 * 3600)
                S["yield_until"] = now + cool
                set_machine("yielded", f"Ryan logged in elsewhere, back in {int(cool / 60)} min")
                continue
            if res == "stop":
                pub("session", "OFF")
                continue
            if res == "ok":
                want = "hunting" if FLAGS["hunt"] else "idle"
                if S["machine"] != want:
                    set_machine(want)
            sleep_announced(gap())


if __name__ == "__main__":
    main()

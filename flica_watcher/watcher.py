"""FLICA Watcher: one kept-alive FLICA session, open time pot diff, HA over MQTT.

Login rule: never two login attempts in a row without a success in between.
A failed login, or anything unexpected, parks the watcher until re-armed from HA.
"""
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://ha2.flica.net"
DATA = "/data"
STATE_FILE = f"{DATA}/state.json"
COOKIES = f"{DATA}/storage_state.json"
OPTS = json.load(open(f"{DATA}/options.json"))

logging.basicConfig(
    level=getattr(logging, OPTS.get("log_level", "info").upper()),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("flica")

KILLED_TXT = "new session under this account was detected"
EXPIRED_HINTS = ("session has expired", "session expired", "please log in", "please sign in")
BLOCK_HINTS = ("captcha", "verification code", "one-time", "one time pass", "change your password",
               "password has expired", "account is locked", "account locked")
PAIRING_RE = re.compile(r"^[A-Z]\d{4}$")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

T = "flica_watcher"
AVAIL = f"{T}/status"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- state
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {"baseline": {}, "machine": "idle", "pot_urls": {}, "kills": [],
                "last_login_ok": None}


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    json.dump(s, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE_FILE)


S = load_state()
WAKE = threading.Event()
FLAGS = {"hunt": False, "pause": False, "rearm": False}


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
    WAKE.set()


def discovery(c):
    dev = {"identifiers": ["flica_watcher"], "name": "FLICA Watcher", "manufacturer": "Pako HI"}
    base = {"availability_topic": AVAIL, "device": dev}
    ents = [
        ("sensor", "state", {"name": "State", "state_topic": f"{T}/state", "icon": "mdi:airplane-search"}),
        ("sensor", "last_check", {"name": "Last check", "state_topic": f"{T}/last_check",
                                  "device_class": "timestamp"}),
        ("sensor", "pot_count", {"name": "Pot count", "state_topic": f"{T}/pot/state",
                                 "value_template": "{{ value_json.count }}",
                                 "json_attributes_topic": f"{T}/pot/state", "icon": "mdi:format-list-bulleted"}),
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
        for t in ("hunt/set", "pause/set", "rearm/press", "hunt/state", "pause/state"):
            cl.subscribe(f"{T}/{t}")

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
    S["machine"] = state
    S["note"] = note
    save_state(S)
    pub("state", state)


# ---------------------------------------------------------------- page classification
def visible_text(html):
    """Text a person would read: drops scripts/styles so words like 'captcha' in
    page code (FLICA's main menu loads a captcha script) don't count as a block."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "template"]):
            t.decompose()
        return soup.get_text(" ", strip=True).lower()
    except Exception:
        return html.lower()


def classify(html):
    low = html.lower()
    if KILLED_TXT in low:
        return "killed"
    if any(h in visible_text(html) for h in BLOCK_HINTS):
        return "blocked"
    if 'type="password"' in low or "type=password" in low or any(h in low for h in EXPIRED_HINTS):
        return "expired"
    return "ok"


# ---------------------------------------------------------------- browser
class Flica:
    def __init__(self, pw):
        self.browser = pw.chromium.launch(headless=True)
        self.ctx = None
        self.new_context()

    def new_context(self):
        if self.ctx:
            self.ctx.close()
        kw = {"storage_state": COOKIES} if os.path.exists(COOKIES) else {}
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
        self.new_context()
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
            hits = [h for h in BLOCK_HINTS if h in text]
            if hits:
                log.warning("block hints matched (visible text): %s", hits)
                return "blocked"
            on_menu = "/online/mainmenu.cgi" in page.url or "/full/" in page.url
            no_pw = page.locator("input[type=password]:visible").count() == 0
            if ("sign out" in low or on_menu) and no_pw:
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
            time.sleep(3)
            if classify(page.content()) != "ok":
                return None
            menu = next((f for f in page.frames if "leftmenu" in f.url), None)
            if not menu:
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


def parse_pot(html):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) >= 10 and PAIRING_RE.match(cells[0]):
            key = f"{cells[0]}|{cells[1]}"
            out[key] = {"pairing": cells[0], "dates": cells[1], "bid_pos": cells[2], "days": cells[3],
                        "report": cells[4], "depart": cells[5], "arrive": cells[6], "blk": cells[7],
                        "credit": cells[8], "layover": cells[9],
                        "prem": cells[10] if len(cells) > 10 else ""}
    return out


# ---------------------------------------------------------------- main loop
def gap():
    lo, hi = ((OPTS["hunt_min_s"], OPTS["hunt_max_s"]) if FLAGS["hunt"]
              else (OPTS["idle_min_s"], OPTS["idle_max_s"]))
    return random.uniform(lo, max(lo, hi))


def sleep(sec):
    WAKE.clear()
    WAKE.wait(sec)


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
        save_state(S)
        log.info("pot pages: %s", list(urls))
    pot_all = {}
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
        if "Opentime Pot" not in html:
            S["pot_urls"] = {}
            save_state(S)
            S["parse_fail"] = S.get("parse_fail", 0) + 1
            if S["parse_fail"] >= 3:
                set_machine("stopped_unexpected", "open time page no longer recognised (3 in a row)")
                return "stop"
            return "retry"
        S["parse_fail"] = 0
        pot = parse_pot(html)
        pot_all[month] = pot
        base = S["baseline"].get(month)
        if base is None:
            log.info("baseline %s: %d pairings (no alert)", month, len(pot))
        else:
            for k, v in pot.items():
                if k not in base:
                    ev = {**v, "month": month, "seen": now_iso()}
                    log.info("NEW pairing %s", ev)
                    pub("event/new_pairing", ev, retain=False)
                    pub("last_new", ev)
        S["baseline"][month] = sorted(pot.keys())
    # drop months no longer published
    S["baseline"] = {m: v for m, v in S["baseline"].items() if m in S["pot_urls"]}
    save_state(S)
    flat = [dict(v, month=m) for m, p in pot_all.items() for v in p.values()]
    pub("pot/state", {"count": len(flat), "pairings": flat[:60]})
    pub("last_check", now_iso())
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
    last_month_check = None
    with sync_playwright() as pw:
        fl = Flica(pw)
        while True:
            st = S.get("machine", "idle")
            if FLAGS["rearm"]:
                FLAGS["rearm"] = False
                if st.startswith("stopped") or st == "yielded":
                    S["kills"] = []
                    S["pot_urls"] = {}
                    S["parse_fail"] = 0
                    try_login(fl, "re-arm")
                    continue
            if st.startswith("stopped"):
                sleep(3600)
                continue
            if FLAGS["pause"]:
                if st != "paused":
                    set_machine("paused", "paused from HA")
                sleep(3600)
                continue
            if st == "paused":
                if not try_login(fl, "un-pause"):
                    continue
                st = S["machine"]
            if st == "yielded":
                wait_until = S.get("yield_until", 0)
                if time.time() < wait_until:
                    sleep(wait_until - time.time())
                    continue
                if not try_login(fl, "after yield cooldown"):
                    continue
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
                sleep(gap())
                continue
            S["net_fail"] = 0
            if res == "needs_login":
                pub("session", "OFF")
                last_ok = S.get("last_login_ok")
                if last_ok and (datetime.now(timezone.utc) - datetime.fromisoformat(last_ok)).total_seconds() < 900:
                    set_machine("stopped_unexpected", "session lost within 15 min of a login; not retrying")
                    continue
                log.info("session expired")
                try_login(fl, "session expired")
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
            sleep(gap())


if __name__ == "__main__":
    main()

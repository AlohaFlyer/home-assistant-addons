#!/usr/bin/env python3
"""Push-isolation guard for the Flight Watcher automations snapshot (FW-0036, FW-0038).

Usage: python3 ha/check_push_isolation.py [automations.yaml] [--no-yaml]

Reads ha/automations_flight_watcher.yaml (or the file given) and fails (exit 1, one line per offender) when an
automation can push one pilot's Flight Watcher events to the other pilot's phone:

  1. Triggered by a second pilot's topic (flight_watcher_james/...) or entity (*.flight_watcher_james_*):
     never calls a Ryan notify target.
  2. Triggered only by Ryan's topics (flight_watcher/...) or entities (*.flight_watcher_*): calls Ryan notify
     targets only, or none. Pilot-neutral triggers (time, webhook, IMAP, notification actions) do not count.
     An automation with only neutral triggers that pushes must push one pilot only, and must not read the
     other pilot's topics or entities.
  3. Triggered by <prefix>/event/ticket_fixed and notifying Ryan: a condition on reporter == 'ryan'.
  4. mobile_app_notification_action handlers: filter on an action name (event_data.action, or startswith / ==
     on trigger.event.data.action in a condition) that uses only their own pilot's prefixes and cannot match
     the other pilot's (Ryan: RECALL_, FLIGHT_WATCHER_; James: JRECALL_, FLIGHT_WATCHER_JAMES_).
  5. Actionable pushes carry only the receiving pilot's action prefixes (URI buttons excepted).

Exit 0 with a one-line summary when clean, 2 when the file cannot be read. Plain Python 3: uses PyYAML when it is
installed, else a small built-in reader for the block YAML Home Assistant writes.
"""
import os
import re
import sys

RYAN = "ryan"
RYAN_TARGETS = frozenset({
    "notify.mobile_app_ryans_iphone_16",
    "notify.mobile_app_ryans_iphone",
    "notify.mobile_app_ryan_macbook",
})
SECOND_PILOTS = ("james",)  # MQTT prefix flight_watcher_<name>, entities *.flight_watcher_<name>_*
ACTION_PREFIXES = {
    RYAN: ("RECALL_", "FLIGHT_WATCHER_"),
    "james": ("JRECALL_", "FLIGHT_WATCHER_JAMES_"),
}
NEUTRAL_ACTIONS = frozenset({"URI"})  # iOS link buttons: open a URL, fire no handler
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "automations_flight_watcher.yaml")

_TOPIC = re.compile(r"(?<![\w/])flight_watcher(?:_([a-z0-9]+))?/[\w/+#-]*")
_ENTITY = re.compile(r"\b[a-z_]+\.flight_watcher_(\w+)")
_FILTER_START = re.compile(
    r"event\.data\.action(?:\s*\|\s*default\([^)]*\))?\s*\)?\s*\.startswith\(\s*['\"]([^'\"]+)['\"]")
_FILTER_EQ = re.compile(
    r"event\.data\.action(?:\s*\|\s*default\([^)]*\))?\s*\)?\s*==\s*['\"]([^'\"]+)['\"]")
_REPORTER_RYAN = re.compile(r"reporter[^=!<>]*==\s*['\"]ryan['\"]")
_DQ_ESC = re.compile(r"\\(U[0-9A-Fa-f]{8}|u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2}|.)")
_DQ_MAP = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "\\": "\\", "/": "/", " ": " "}


def _dq_char(m):
    e = m.group(1)
    return chr(int(e[1:], 16)) if len(e) > 1 else _DQ_MAP.get(e, e)


# ---------------------------------------------------------------- loading

def _mini_yaml(text):
    """Small reader for block YAML as Home Assistant writes it: mappings, sequences, plain / quoted / block
    scalars, one-line flow lists. Enough for this guard, not a general YAML parser."""
    lines = text.split("\n")
    pos = [0]
    key_re = re.compile(r"^([A-Za-z0-9_][\w.-]*|'[^']*'|\"[^\"]*\")\s*:(?:\s+|$)(.*)$")

    def indent(ln):
        return len(ln) - len(ln.lstrip(" "))

    def peek():
        while pos[0] < len(lines):
            s = lines[pos[0]].strip()
            if s and not s.startswith("#") and s != "---":
                return indent(lines[pos[0]]), s
            pos[0] += 1
        return None

    def plain(v):
        v = re.sub(r"\s+#.*$", "", v).strip()
        if v in ("true", "True", "false", "False"):
            return v.lower() == "true"
        if v in ("", "~", "null"):
            return None
        if re.fullmatch(r"-?\d+", v):
            return int(v)
        if re.fullmatch(r"-?\d+\.\d*", v):
            return float(v)
        if v.startswith("[") and v.endswith("]"):
            return [scalar_inline(x.strip()) for x in v[1:-1].split(",") if x.strip()]
        if v == "{}":
            return {}
        return v

    def scalar_inline(v):
        if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"":
            return v[1:-1].replace("''", "'") if v[0] == "'" else v[1:-1]
        return plain(v)

    def fold(parts):
        out = ""
        for p in parts:
            if p == "":
                out += "\n"
            else:
                out += (" " if out and not out.endswith("\n") else "") + p
        return out

    def scalar(first, parent):
        """first: text after 'key:' or '- '; the cursor is on the next line."""
        q = first[:1]
        if q in ("'", '"'):
            parts, buf = [], first[1:]
            while True:
                if q == "'":
                    body = buf.replace("''", "\0")
                    end = body.find("'")
                else:
                    body = buf
                    m = re.search(r'(?<!\\)(?:\\\\)*"', body)
                    end = m.end() - 1 if m else -1
                if end >= 0:
                    parts.append(body[:end].strip() if parts else body[:end])
                    break
                parts.append(body.strip() if parts else body.rstrip())
                if pos[0] >= len(lines):
                    raise ValueError("unterminated quoted scalar")
                buf = lines[pos[0]]
                pos[0] += 1
            s = fold(parts)
            if q == "'":
                return s.replace("\0", "'")
            return _DQ_ESC.sub(_dq_char, s)
        if first[:1] in ("|", ">"):
            body = []
            while pos[0] < len(lines) and (not lines[pos[0]].strip() or indent(lines[pos[0]]) > parent):
                body.append(lines[pos[0]])
                pos[0] += 1
            while body and not body[-1].strip():
                body.pop()
            cut = min((indent(b) for b in body if b.strip()), default=0)
            body = [b[cut:] for b in body]
            if first[0] == "|":
                return "\n".join(body)
            out = body[0] if body else ""
            for prev, b in zip(body, body[1:]):  # folded: more-indented lines keep their line breaks
                out += "\n" + b if (not b or not prev or b[0] == " " or prev[0] == " ") else " " + b
            return out
        parts = [first]
        while pos[0] < len(lines) and (not lines[pos[0]].strip() or indent(lines[pos[0]]) > parent):
            if not lines[pos[0]].strip() and (pos[0] + 1 >= len(lines) or indent(lines[pos[0] + 1]) <= parent):
                break
            parts.append(lines[pos[0]].strip())
            pos[0] += 1
        return plain(fold(parts)) if len(parts) > 1 else plain(first)

    def node(ind):
        p = peek()
        if p is None:
            return None
        return seq(ind) if p[1] == "-" or p[1].startswith("- ") else mapping(ind)

    def seq(ind):
        items = []
        while True:
            p = peek()
            if p is None or p[0] != ind or not (p[1] == "-" or p[1].startswith("- ")):
                return items
            rest = p[1][1:].strip()
            if not rest:
                pos[0] += 1
                n = peek()
                items.append(node(n[0]) if n and n[0] > ind else None)
            elif key_re.match(rest) or rest == "-" or rest.startswith("- "):
                lines[pos[0]] = " " * (ind + 2) + rest  # "- key: v" opens a mapping two columns in
                items.append(node(ind + 2))
            else:
                pos[0] += 1
                items.append(scalar(rest, ind))

    def mapping(ind):
        d = {}
        while True:
            p = peek()
            if p is None or p[0] != ind or p[1] == "-" or p[1].startswith("- "):
                return d
            m = key_re.match(p[1])
            if not m:
                raise ValueError(f"line {pos[0] + 1}: cannot read {p[1][:40]!r}")
            key, rest = scalar_inline(m.group(1)), m.group(2).strip()
            pos[0] += 1
            if rest:
                d[key] = scalar(rest, ind)
                continue
            n = peek()
            if n and (n[0] > ind or (n[0] == ind and (n[1] == "-" or n[1].startswith("- ")))):
                d[key] = node(n[0])
            else:
                d[key] = None

    p = peek()
    return node(p[0]) if p else None


def load(path, use_yaml=True):
    text = open(path, encoding="utf-8").read()
    if use_yaml:
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            return yaml.safe_load(text) or []
    return _mini_yaml(text) or []


# ---------------------------------------------------------------- analysis

def _strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif o is not None:
        yield str(o)


def _pilots_in(o):
    """Pilots whose Flight Watcher topics or entities appear anywhere in o."""
    found = set()
    for s in _strings(o):
        for m in _TOPIC.finditer(s):
            found.add(m.group(1) or RYAN)
        for m in _ENTITY.finditer(s):
            rest = m.group(1)
            found.add(next((p for p in SECOND_PILOTS if rest == p or rest.startswith(p + "_")), RYAN))
    return found


def _wild_pilots(t):
    """Review fix (1.4.0): an MQTT trigger whose first topic level is a wildcard ('+/event/new_pairing', '#')
    matches every pilot's Watcher, so it counts as triggered by all of them."""
    if not isinstance(t, dict) or t.get("trigger", t.get("platform")) != "mqtt":
        return set()
    topics = t.get("topic")
    for topic in (topics if isinstance(topics, list) else [topics]):
        if str(topic or "").split("/", 1)[0] in ("+", "#"):
            return {RYAN, *SECOND_PILOTS}
    return set()


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _pushes(o, out):
    """(target, action ids) for each notify call anywhere under o."""
    if isinstance(o, dict):
        svc = o.get("action", o.get("service"))
        if isinstance(svc, str) and svc.startswith("notify."):
            data = o.get("data") or {}
            targets = [svc]
            if svc in ("notify.send_message",):
                targets = _as_list((o.get("target") or {}).get("entity_id")) or [svc]
            inner = data.get("data") if isinstance(data, dict) else None
            ids = []
            if isinstance(inner, dict):
                ids = [a.get("action") for a in _as_list(inner.get("actions")) if isinstance(a, dict)]
            for t in targets:
                out.append((str(t), [str(i) for i in ids if i]))
        for v in o.values():
            _pushes(v, out)
    elif isinstance(o, list):
        for v in o:
            _pushes(v, out)
    return out


def _trigger_type(t):
    return t.get("trigger", t.get("platform")) if isinstance(t, dict) else None


def _is_handler(t):
    return _trigger_type(t) == "event" and t.get("event_type") == "mobile_app_notification_action"


def _action_name(i):
    return i.split("|", 1)[0].split("{", 1)[0]


def _filter_ok(f, exact, pilot):
    own = ACTION_PREFIXES.get(pilot, ())
    others = [p for q, ps in ACTION_PREFIXES.items() if q != pilot for p in ps]
    if not any(f.startswith(p) for p in own):
        return False
    if any(f.startswith(p) for p in others):
        return False
    return exact or not any(p.startswith(f) for p in others)


def check_one(a):
    """Offence strings for one automation (empty when it is clean), plus its pilot label."""
    name = a.get("alias") or a.get("id") or "(no alias)"
    triggers = _as_list(a.get("triggers", a.get("trigger")))
    conditions = _as_list(a.get("conditions", a.get("condition")))
    actions = _as_list(a.get("actions", a.get("action")))
    bad = []

    trig_pilots = set()
    for t in triggers:
        if not _is_handler(t):
            trig_pilots |= _pilots_in(t) | _wild_pilots(t)
    pushes = _pushes(actions, [])
    targets = {t for t, _ in pushes}
    ryan_t = {t for t in targets if t in RYAN_TARGETS}
    other_t = targets - ryan_t
    templated = {t for t in targets if "{" in t}
    if templated:
        bad.append(f"notify target is a template, cannot be checked: {sorted(templated)}")

    seconds = trig_pilots - {RYAN}
    if seconds and ryan_t:
        bad.append(f"triggered by {sorted(seconds)} but pushes Ryan: {sorted(ryan_t)}")
    if seconds and RYAN in trig_pilots and other_t:
        bad.append(f"triggered by both Ryan and {sorted(seconds)} and pushes: split it, one automation per pilot")
    if trig_pilots == {RYAN} and other_t:
        bad.append(f"triggered by Ryan's Watcher but pushes non-Ryan targets: {sorted(other_t)}")
    if not trig_pilots and targets:
        body = _pilots_in([conditions, actions])
        if ryan_t and other_t:
            bad.append(f"neutral trigger pushes both Ryan and others: {sorted(targets)}")
        elif ryan_t and body - {RYAN}:
            bad.append(f"pushes Ryan but reads {sorted(body - {RYAN})}'s topics or entities")
        elif other_t and RYAN in body:
            bad.append(f"pushes {sorted(other_t)} but reads Ryan's topics or entities")
    pilot = "+".join(sorted(trig_pilots)) if trig_pilots else "neutral"

    for t in triggers:
        topic = str(t.get("topic", "")) if isinstance(t, dict) else ""
        if topic.endswith("/event/ticket_fixed") and ryan_t:
            if not any(_REPORTER_RYAN.search(s) for s in _strings(conditions)):
                bad.append("ticket_fixed pushes Ryan without a condition on reporter == 'ryan'")

    handlers = [t for t in triggers if _is_handler(t)]
    if handlers:
        acts = _pilots_in(actions) | (trig_pilots if trig_pilots else set())
        if len(acts) != 1:
            bad.append(f"notification-action handler acts for {sorted(acts) or 'no pilot'}: one pilot only")
        hp = next(iter(acts)) if len(acts) == 1 else None
        cond_text = list(_strings(conditions))
        for t in handlers:
            filters = []
            exact = (t.get("event_data") or {}).get("action")
            if exact:
                filters.append((str(exact), True))
            for s in cond_text:
                filters += [(m.group(1), False) for m in _FILTER_START.finditer(s)]
                filters += [(m.group(1), True) for m in _FILTER_EQ.finditer(s)]
            if not filters:
                bad.append("notification-action handler matches every action: filter on its own pilot's prefix")
            for f, ex in filters:
                if hp and not _filter_ok(f, ex, hp):
                    bad.append(f"handler for {hp} matches {f!r}{'' if ex else '*'}, not only "
                               f"{hp}'s prefixes {list(ACTION_PREFIXES.get(hp, ()))}")

    for target, ids in pushes:
        tp = RYAN if target in RYAN_TARGETS else None
        for i in ids:
            n = _action_name(i)
            if n in NEUTRAL_ACTIONS:
                continue
            if tp == RYAN and not _filter_ok(n, True, RYAN):
                bad.append(f"push to {target} carries action {n!r}, not one of Ryan's prefixes")
            if tp is None and _filter_ok(n, True, RYAN):
                bad.append(f"push to {target} carries Ryan's action {n!r}")
    return name, pilot, len(handlers) > 0, bad


def check(automations):
    """(offenders [(alias, reason)], summary line)."""
    if not isinstance(automations, list):
        raise ValueError("expected a YAML list of automations")
    offenders, counts, handlers = [], {}, 0
    for a in automations:
        if not isinstance(a, dict):
            continue
        name, pilot, is_handler, bad = check_one(a)
        counts[pilot] = counts.get(pilot, 0) + 1
        handlers += is_handler
        offenders += [(name, b) for b in bad]
    split = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    n = len([a for a in automations if isinstance(a, dict)])
    summary = (f"push isolation {'OK' if not offenders else 'FAILED'}: {n} automations ({split}), "
               f"{handlers} notification-action handler(s), {len(offenders)} offender(s)")
    return offenders, summary


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    path = args[0] if args else DEFAULT_PATH
    try:
        autos = load(path, use_yaml="--no-yaml" not in argv)
        offenders, summary = check(autos)
    except (OSError, ValueError) as e:
        print(f"push isolation: cannot read {path}: {e}")
        return 2
    for name, why in offenders:
        print(f"OFFENDER {name}: {why}")
    print(summary)
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

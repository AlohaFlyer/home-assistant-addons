"""Rules: schema validation and matching. Pure, no I/O.

v0.2 is read only. `would_submit` reports what a live auto_add / auto_swap rule WOULD do once
v0.3 ships; nothing in this add-on can submit to FLICA (WRITES_IMPLEMENTED is False).
"""
import re
from datetime import date, datetime, timedelta, timezone

from pot import hhmm, hours, row_date

WRITES_IMPLEMENTED = False
MODES = ("alert", "auto_add", "auto_swap")
NOTIFY = ("critical", "normal")
DRY_RUN_DAYS = 7
ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")
MATCH_KEYS = {"layover", "months", "date_from", "date_to", "min_credit", "max_days",
              "report_after", "report_before", "pairing_prefix"}
RULE_KEYS = {"id", "name", "enabled", "mode", "dry_run", "match", "swap", "cap_per_day", "notify",
             "expires_at", "created_at"}

EXAMPLE = [{
    "id": "sin_hunt", "name": "SIN layover, this month or next", "enabled": True, "mode": "alert",
    "dry_run": True, "match": {"layover": ["SIN"], "months": ["current", "next"]},
    "cap_per_day": 3, "notify": "critical",
}]


def _iso_date(v):
    return date.fromisoformat(v) if isinstance(v, str) else None


def _iso_dt(v):
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate(rules, now=None):
    """Return (clean_rules, errors). Fills defaults; stamps created_at on new rules."""
    now = now or datetime.now(timezone.utc)
    errs, out, ids = [], [], set()
    if not isinstance(rules, list):
        return [], ["rules must be a JSON list"]
    for i, r in enumerate(rules):
        where = f"rule {i + 1}"
        if not isinstance(r, dict):
            errs.append(f"{where}: must be an object")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            errs.append(f"{where}: id must be 1-32 chars of a-z 0-9 _")
            continue
        where = f"rule {rid}"
        if rid in ids:
            errs.append(f"{where}: duplicate id")
            continue
        ids.add(rid)
        extra = set(r) - RULE_KEYS
        if extra:
            errs.append(f"{where}: unknown keys {sorted(extra)}")
        c = {"id": rid, "name": str(r.get("name") or rid), "enabled": bool(r.get("enabled", True)),
             "mode": r.get("mode", "alert"), "dry_run": r.get("dry_run", True),
             "match": r.get("match") or {}, "swap": r.get("swap"),
             "cap_per_day": r.get("cap_per_day", 3), "notify": r.get("notify", "critical"),
             "expires_at": r.get("expires_at"), "created_at": r.get("created_at") or now.isoformat()}
        if c["mode"] not in MODES:
            errs.append(f"{where}: mode must be one of {MODES}")
        if not isinstance(c["dry_run"], bool):
            errs.append(f"{where}: dry_run must be true or false")
        if c["notify"] not in NOTIFY:
            errs.append(f"{where}: notify must be one of {NOTIFY}")
        if not isinstance(c["cap_per_day"], int) or not 0 <= c["cap_per_day"] <= 10:
            errs.append(f"{where}: cap_per_day must be an integer 0-10")
        if c["mode"] == "auto_swap" and not (isinstance(c["swap"], dict) and c["swap"].get("give")):
            errs.append(f"{where}: auto_swap needs swap.give (a pairing id or a date window)")
        m = c["match"]
        if not isinstance(m, dict):
            errs.append(f"{where}: match must be an object")
            m = c["match"] = {}
        bad = set(m) - MATCH_KEYS
        if bad:
            errs.append(f"{where}: unknown match keys {sorted(bad)}")
        for k in ("layover", "months"):
            if k in m and not (isinstance(m[k], list) and all(isinstance(x, str) for x in m[k])):
                errs.append(f"{where}: match.{k} must be a list of strings")
        for x in m.get("months", []) if isinstance(m.get("months"), list) else []:
            if x not in ("current", "next") and not re.match(r"^\d{4}-\d{2}$", x):
                errs.append(f"{where}: match.months entries are current, next or YYYY-MM")
        for k in ("date_from", "date_to"):
            if k in m:
                try:
                    if _iso_date(m[k]) is None:
                        raise ValueError
                except (ValueError, TypeError):
                    errs.append(f"{where}: match.{k} must be YYYY-MM-DD")
        for k in ("report_after", "report_before"):
            if k in m and hhmm(str(m[k])) is None:
                errs.append(f"{where}: match.{k} must be HH:MM")
        if "min_credit" in m and not isinstance(m["min_credit"], (int, float)):
            errs.append(f"{where}: match.min_credit must be hours as a number")
        if "max_days" in m and not isinstance(m["max_days"], int):
            errs.append(f"{where}: match.max_days must be an integer")
        if c["expires_at"]:
            try:
                _iso_dt(c["expires_at"])
            except (ValueError, AttributeError):
                errs.append(f"{where}: expires_at must be ISO date-time")
        try:
            _iso_dt(c["created_at"])
        except (ValueError, AttributeError):
            errs.append(f"{where}: created_at must be ISO date-time")
        out.append(c)
    return (out if not errs else []), errs


def _month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def matches(rule, row, today=None):
    """(True, '') or (False, reason). Every condition present must hold."""
    today = today or date.today()
    m = rule.get("match") or {}
    start = row_date(row.get("start") or (row.get("dates") or "").split("-")[0], today)
    if m.get("layover"):
        lay = {x.strip().upper() for x in re.split(r"[\s,/]+", row.get("layover") or "") if x.strip()}
        if not lay & {x.upper() for x in m["layover"]}:
            return False, "layover"
    if m.get("pairing_prefix") and not (row.get("pairing") or "").startswith(m["pairing_prefix"]):
        return False, "pairing_prefix"
    if m.get("months"):
        if not start:
            return False, "no date"
        want = set()
        nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        for x in m["months"]:
            want.add(_month_key(today) if x == "current" else _month_key(nxt) if x == "next" else x)
        if _month_key(start) not in want:
            return False, "month"
    if m.get("date_from") or m.get("date_to"):
        if not start:
            return False, "no date"
        if m.get("date_from") and start < _iso_date(m["date_from"]):
            return False, "before date_from"
        if m.get("date_to") and start > _iso_date(m["date_to"]):
            return False, "after date_to"
    if "min_credit" in m:
        cr = hours(row.get("credit"))
        if cr is None or cr < m["min_credit"]:
            return False, "credit"
    if "max_days" in m:
        try:
            if int(row.get("days")) > m["max_days"]:
                return False, "days"
        except (TypeError, ValueError):
            return False, "days unknown"
    if m.get("report_after") or m.get("report_before"):
        rpt = hhmm(row.get("report"))
        if not rpt:
            return False, "report unknown"
        if m.get("report_after") and rpt < hhmm(str(m["report_after"])):
            return False, "report before report_after"
        if m.get("report_before") and rpt > hhmm(str(m["report_before"])):
            return False, "report after report_before"
    return True, ""


def evaluate(rules, row, live, submits_today, now=None):
    """Match one new row against all rules.

    live: {rule_id: bool} from the per-rule HA switch. submits_today: {rule_id: int}.
    Returns a list of match dicts (one per matching rule)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for r in rules:
        if not r["enabled"]:
            continue
        if r.get("expires_at") and now >= _iso_dt(r["expires_at"]):
            continue
        ok, _ = matches(r, row, now.date())
        if not ok:
            continue
        age = now - _iso_dt(r["created_at"])
        dry = r["dry_run"] or not live.get(r["id"], False) or age < timedelta(days=DRY_RUN_DAYS)
        reason = ""
        if r["mode"] == "alert":
            would = False
            reason = "alert rule"
        elif dry:
            would = False
            reason = "dry run" + (f" (rule is {age.days} d old, live after {DRY_RUN_DAYS})"
                                  if age < timedelta(days=DRY_RUN_DAYS) else "")
        elif submits_today.get(r["id"], 0) >= r["cap_per_day"]:
            would = False
            reason = f"cap {r['cap_per_day']}/day reached"
        else:
            would = True
            reason = "live" + ("" if WRITES_IMPLEMENTED else " (writes ship in v0.3; nothing sent)")
        out.append({"rule_id": r["id"], "rule": r["name"], "mode": r["mode"], "dry_run": dry,
                    "would_submit": would, "reason": reason, "notify": r["notify"],
                    "row": row, "at": now.isoformat()})
    return out


def live_allowed(rule, now=None):
    """Can the live switch be turned on yet? (dry-run week gate)"""
    now = now or datetime.now(timezone.utc)
    age = now - _iso_dt(rule["created_at"])
    if age < timedelta(days=DRY_RUN_DAYS):
        left = timedelta(days=DRY_RUN_DAYS) - age
        return False, f"dry-run week: {left.days} d {left.seconds // 3600} h left"
    if rule["mode"] == "alert":
        return False, "alert rules have nothing to make live"
    return True, ""

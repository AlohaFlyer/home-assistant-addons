"""FW-0029: the user-facing text matches 1.3.x (read-only FLICA, Settings card, tickets, pushes): no promise of FLICA
writes in a later version, no pre-rename names, no request for real FLICA captures, no em dashes."""
import os
import re

import pytest

import rules as R
import web

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
FILES = [os.path.join(HERE, f) for f in ("web.py", "rules.py", "watcher.py", "README.md", "tests/fixtures/README.md",
                                        "PORTAL_CONTRACT.md", "portal.py", "ntfy.py", "roles.py")] + \
        [os.path.join(ROOT, f) for f in ("README.md", "repository.yaml", "repository.json")]
STALE = ("v0.3", "until v0.", "v0.2 is", "v0.2 only", "v0.2:", "FLICA Rules", "writes ship", "writes arrive",
         "real capture", "replace with real", "Replace each file", "flica_watcher", "FLICA Watcher")


@pytest.mark.parametrize("path", FILES, ids=lambda p: os.path.relpath(p, ROOT))
def test_no_stale_text(path):
    s = open(path, encoding="utf-8").read()
    for old in STALE:
        assert old not in s, old
    if not path.endswith(".py"):
        assert chr(0x2014) not in s  # no em dashes in the docs


def test_rule_reason_and_rules_page_say_read_only():
    assert R.WRITES_IMPLEMENTED is False
    assert "FLICA is read only" in web.PAGE and "nothing is ever sent to" in web.PAGE


def test_repository_names_every_app():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for name in ("Flight Watcher", "AI Agent Manager - HI", "AI Agent Manager - NV", "flight_watcher/README.md"):
        assert name in readme, name
    assert "Flight Watcher" in open(os.path.join(ROOT, "repository.yaml"), encoding="utf-8").read()


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
DOCS = [os.path.join(HERE, f) for f in ("CHANGELOG.md", "CHANGELOG_PENDING.md", "README.md")] + \
       [os.path.join(ROOT, f) for f in ("README.md", "HANDOFF.md", "CLAUDE.md", "ha/README.md", "ha/automations_flight_watcher.yaml")]


@pytest.mark.parametrize("path", [p for p in DOCS if os.path.exists(p)], ids=lambda p: os.path.relpath(p, ROOT))
def test_no_email_address_in_the_docs(path):
    """1.4.7 verify: no mailbox in git (the 0.4.1 changelog entry named the FLICA alerts inbox, which anyone could then
    mail into the Watcher's alert path); the ha/ snapshot already writes <redacted-email>."""
    assert EMAIL.findall(open(path, encoding="utf-8").read()) == []

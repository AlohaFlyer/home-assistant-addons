"""FW-0029: the user-facing text matches 1.3.x (read-only FLICA, Settings card, tickets, pushes): no promise of FLICA
writes in a later version, no pre-rename names, no request for real FLICA captures, no em dashes."""
import os

import pytest

import rules as R
import web

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
FILES = [os.path.join(HERE, f) for f in ("web.py", "rules.py", "watcher.py", "README.md", "tests/fixtures/README.md")] + \
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

"""0.10.2: dashboard cards deployed by the add-on (cards.py). Synthetic dates only."""
import json
import os

import cards
import run


def test_repo_cards_hold_no_real_doh():
    for name, s in cards.sources().items():
        for m in cards.DOH_RE.finditer(s):
            assert m.group(1) == cards.PLACEHOLDER_DOH, name


def test_build_lists_every_card_and_pilot_copy():
    f = cards.build("9.9.9", "1999-02-03", ["pilot2"])
    m = json.loads(f[cards.MANIFEST])
    assert m["version"] == "9.9.9"
    assert "flight-watcher-schedule-card.js" in m["cards"] and "flight-watcher-schedule-card-pilot2.js" in m["cards"]
    assert set(m["cards"]) | {cards.MANIFEST, cards.LOADER} == set(f)
    assert 'DOH = "1999-02-03"' in f["flight-watcher-schedule-card.js"]
    p = f["flight-watcher-schedule-card-pilot2.js"]
    assert f'DOH = "{cards.PLACEHOLDER_DOH}"' in p and "1999-02-03" not in p
    assert 'customElements.define("flight-watcher-schedule-card-pilot2"' in p
    assert "sensor.flight_watcher_pilot2_" in p and "Ryan" not in p
    assert cards.MANIFEST in f[cards.LOADER] and "no-store" in f[cards.LOADER]


def test_pilot_copy_moves_every_per_pilot_name():
    f = cards.build("1", "1999-02-03", ["pilot2"])
    sch, rec, pk = f["flight-watcher-schedule-card-pilot2.js"], f["flight-watcher-recall-card-pilot2.js"], f["flight-watcher-pickers-card-pilot2.js"]
    assert "input_number.flight_watcher_pilot2_month_offset" in sch and "input_number.flight_watcher_month_offset" not in sch
    assert 'localStorage.getItem("flight_watcher_pilot2_' in sch and "flight_watcher_pilot2_pilot2" not in sch
    assert "/local/flight-watcher/pilot2/finds_" in f["flight-watcher-finds-card-pilot2.js"]
    assert "/local/flight-watcher/pairings_" in sch  # pairings stay shared
    assert '"/flight-watcher-pilot2/recall"' in rec and "flight_watcher_pilot2/" in rec
    assert '"flight-watcher-pilot-pilot2"' in pk and '"flight-watcher-pilot"' not in pk
    for name, text in f.items():  # no pre-rename name survives in any card, original or copy
        for old in ("flica_watcher", "flica-", "flica_rule", ".flica_", "/flica/", 'Item("flica_', "FLICA Watcher"):
            assert old not in text, (name, old)


def test_bad_pilot_name_skipped():
    f = cards.build("1", None, ["../x"])
    assert not any("../" in n for n in f)


def test_deploy_migrates_doh_and_writes_only_changes(tmp_path):
    dst, settings = tmp_path / "www", tmp_path / "cards.json"
    dst.mkdir()
    (dst / "flight-watcher-schedule-card.js").write_text('const DOH = "1990-01-01";\n')
    w1 = cards.deploy("1.0", [], dst=str(dst), settings=str(settings))
    assert json.loads(settings.read_text()) == {"doh": "1990-01-01"}
    assert 'DOH = "1990-01-01"' in (dst / "flight-watcher-schedule-card.js").read_text()
    assert cards.LOADER in w1 and "flight-watcher-clock-card.js" in w1
    assert cards.deploy("1.0", [], dst=str(dst), settings=str(settings)) == []
    assert cards.deploy("1.1", [], dst=str(dst), settings=str(settings)) == [cards.MANIFEST]
    assert not any(n.endswith(".tmp") for n in os.listdir(dst))


def test_deploy_without_www_or_doh(tmp_path):
    assert cards.deploy("1", [], dst=str(tmp_path / "missing"), settings=str(tmp_path / "s.json")) == []
    dst = tmp_path / "www"
    dst.mkdir()
    cards.deploy("1", [], dst=str(dst), settings=str(tmp_path / "s.json"))
    assert f'DOH = "{cards.PLACEHOLDER_DOH}"' in (dst / "flight-watcher-schedule-card.js").read_text()
    assert not (tmp_path / "s.json").exists()


def test_app_version_read_without_import():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v = run.app_version(os.path.join(here, "watcher.py"))
    assert v == open(os.path.join(here, "config.yaml")).read().split('version: "')[1].split('"')[0]


def test_every_entity_a_card_reads_is_one_discovery_creates(tmp_path, monkeypatch):
    """1.0.0 review: the cards' entity literals must equal discovery's default_entity_ids (both instances)."""
    import json as _json
    import re as _re
    import sys
    from test_instance import FakeClient, _load
    opts = {"username": "u", "password": "p", "log_level": "info", "category_check": "HNL 332 FO"}
    made = set()
    for inst in ("", "pilot2"):
        (tmp_path / (inst or "ryan")).mkdir()
        W = _load(tmp_path / (inst or "ryan"), monkeypatch, inst, opts)
        c = FakeClient()
        W.discovery(c)
        made |= {_json.loads(p)["default_entity_id"] for t, p, _ in c.msgs if t.endswith("/config") and p}
        sys.modules.pop("watcher", None)
    f = cards.build("1", None, ["pilot2"])
    used = set()
    for text in f.values():
        used |= set(_re.findall(r"\b(?:sensor|switch|button|number|select|binary_sensor)\.flight_watcher_[a-z0-9_]+", text))
    missing = {e for e in used if e not in made and not e.startswith("switch.flight_watcher_rule")}
    assert not missing, sorted(missing)

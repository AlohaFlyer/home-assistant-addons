"""1.6.0 (FW-0061): the portal folders and their modes (PORTAL_CONTRACT.md section 1), made by run.py before any
child starts and only for a pilot with portal: true. A tmp root stands in for /share; owners are checked through a
recording chown as if the launcher ran as root. Made-up pilot names."""
import os
import stat

import portal as PT
import run


def _mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


def test_modes_and_owners(tmp_path):
    root, share_fw = tmp_path / "fw_portal", tmp_path / "flight_watcher"
    share_fw.mkdir(mode=0o755)
    owners = {}
    ready = PT.prepare(str(root), ["james", "demo"], str(share_fw), euid=0,
                       chown=lambda p, u, g: owners.__setitem__(os.path.relpath(p, tmp_path), (u, g)), log=print)
    assert ready == ["james", "demo"]
    assert _mode(root) == 0o755 and owners["fw_portal"] == (0, 0)
    for n in ready:
        d = root / n
        assert _mode(d) == 0o750 and owners[f"fw_portal/{n}"] == (0, 2061)
        for sub in ("out", "out/blobs", "out/files"):
            assert _mode(d / sub) == 0o750 and owners[f"fw_portal/{n}/{sub}"] == (0, 2061), sub
        assert _mode(d / "in") == 0o700 and owners[f"fw_portal/{n}/in"] == (2061, 2061)
    assert _mode(share_fw) == 0o700 and owners["flight_watcher"] == (0, 0)  # root only from 1.6.0 with a portal


def test_modes_reapplied_and_no_chown_unless_root(tmp_path):
    root = tmp_path / "fw_portal"
    called = []
    PT.prepare(str(root), ["james"], euid=1000, chown=lambda *a: called.append(a), log=print)
    os.chmod(root / "james" / "in", 0o777)
    os.chmod(root / "james" / "out", 0o777)
    assert PT.prepare(str(root), ["james"], euid=1000, chown=lambda *a: called.append(a), log=print) == ["james"]
    assert _mode(root / "james" / "in") == 0o700 and _mode(root / "james" / "out") == 0o750 and called == []


def test_symlinked_in_folder_refused(tmp_path):
    root, elsewhere = tmp_path / "fw_portal", tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "james").mkdir(parents=True)
    os.symlink(elsewhere, root / "james" / "in")
    said = []
    assert PT.prepare(str(root), ["james", "demo"], log=said.append) == ["demo"]
    assert len(said) == 1 and "pilot 'james' refused" in said[0] and "symlink" in said[0]
    assert os.listdir(elsewhere) == []  # nothing made through the link


def test_symlinked_pilot_folder_or_root_refused(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root = tmp_path / "fw_portal"
    root.mkdir()
    os.symlink(elsewhere, root / "james")
    said = []
    assert PT.prepare(str(root), ["james"], log=said.append) == [] and "refused" in said[0]
    link_root = tmp_path / "link_root"
    os.symlink(elsewhere, link_root)
    said = []
    assert PT.prepare(str(link_root), ["demo"], log=said.append) == []
    assert "no pilot portal this start" in said[0] and os.listdir(elsewhere) == []
    (tmp_path / "afile").write_text("x")
    assert PT.prepare(str(tmp_path / "afile"), ["demo"], log=said.append) == []


def test_bad_names_never_make_a_folder(tmp_path):
    root = tmp_path / "fw_portal"
    assert PT.prepare(str(root), ["../x", "", "James", "demo"], log=print) == ["demo"]
    assert sorted(os.listdir(root)) == ["demo"] and not (tmp_path / "x").exists()


def test_setup_portal_makes_the_key_before_children_and_logs_its_public_half(tmp_path, capsys):
    data, root = tmp_path / "data", tmp_path / "fw_portal"
    data.mkdir()
    ready, pub = run.setup_portal(["james"], data=str(data), root=str(root), share_fw=str(tmp_path / "fw"),
                                  euid=1000)
    key = data / "portal_ed25519.pem"
    assert ready == ["james"] and _mode(key) == 0o600 and PT.public_id(PT.load_key(str(key))) == pub
    out = capsys.readouterr().out
    assert f"portal signing key {pub}" in out and "PRIVATE" not in out
    assert not any(str(p).startswith(str(root)) for p in [key])  # the key is in /data, never under the portal root
    assert [p for p in root.rglob("*") if p.suffix == ".pem"] == []
    # nothing at all when no pilot has a portal: no key, no folder, no line
    other = tmp_path / "data2"
    other.mkdir()
    assert run.setup_portal([], data=str(other), root=str(tmp_path / "none")) == ([], "")
    assert os.listdir(other) == [] and not (tmp_path / "none").exists() and capsys.readouterr().out == ""


# ---------------------------------------------------------------- portal off is fail-closed (contract 1)
def _leftovers(root, name):
    d = root / name
    for sub in ("out/blobs", "out/files", "in"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "out" / "state.json").write_text('{"fwp": 1}')
    (d / "out" / "manifest.json").write_text('{"fwp": 1}')
    (d / "out" / ".state.json.0123456789abcdef.tmp").write_text("x")
    (d / "out" / "files" / "finds_2026-11.json").write_text('{"fwp": 1}')
    (d / "out" / "blobs" / ("ab" * 32 + ".js")).write_text("//")
    (d / "in" / "1763600000123-0123456789abcdef.json").write_text("{}")
    (d / "in" / ".1763600000124-0123456789abcdee.json.tmp").write_text("{}")
    (d / "in" / "stray").mkdir()


def _files(p):
    return sorted(str(x.relative_to(p)) for x in p.rglob("*") if not x.is_dir() or x.is_symlink())


def test_portal_off_clears_out_and_in(tmp_path, capsys):
    """A pilot set back to portal: false (or removed) keeps no signed state, files or manifest for the portal to go
    on serving, and no command waits in in/: run.py empties both at the next start. The folders and <data> stay."""
    data, root = tmp_path / "data", tmp_path / "fw_portal"
    data.mkdir()
    _leftovers(root, "demo")
    (data / "portal_seq.json").write_text('{"seq": 5}')
    assert run.setup_portal([], data=str(data), root=str(root)) == ([], "")
    out = capsys.readouterr().out
    assert out.count("portal for pilot 'demo' off: out/ and in/ cleared") == 1 and "signing key" not in out
    assert _files(root) == [] and sorted(os.listdir(root / "demo")) == ["in", "out"]
    assert sorted(os.listdir(root / "demo" / "out")) == ["blobs", "files"]
    assert (data / "portal_seq.json").read_text() == '{"seq": 5}' and os.listdir(data) == ["portal_seq.json"]
    assert run.setup_portal([], data=str(data), root=str(root)) == ([], "")
    assert capsys.readouterr().out == ""  # already empty: no line on later starts


def test_portal_off_never_touches_a_pilot_still_on(tmp_path, capsys):
    data, root = tmp_path / "data", tmp_path / "fw_portal"
    data.mkdir()
    _leftovers(root, "demo")
    _leftovers(root, "other")
    before = _files(root / "other")
    ready, pub = run.setup_portal(["other"], data=str(data), root=str(root), euid=1000)
    assert ready == ["other"] and pub
    assert _files(root / "demo") == [] and _files(root / "other") == before
    assert "pilot 'other'" not in capsys.readouterr().out


def test_portal_off_never_follows_a_link(tmp_path):
    root, outside = tmp_path / "fw_portal", tmp_path / "outside"
    for sub in ("out", "files", "in", "pilot"):
        (outside / sub).mkdir(parents=True)
        (outside / sub / "keep.json").write_text("{}")
    (root / "demo").mkdir(parents=True)
    os.symlink(outside / "out", root / "demo" / "out")  # out/ itself a link: the link goes, never its files
    (root / "demo" / "in").mkdir()
    os.symlink(outside / "in" / "keep.json", root / "demo" / "in" / "1763600000123-0123456789abcdef.json")
    (root / "james" / "out").mkdir(parents=True)
    os.symlink(outside / "files", root / "james" / "out" / "files")
    os.symlink(outside / "pilot", root / "linked")  # a pilot folder that is a link: skipped
    assert sorted(PT.retire(str(root), [], log=lambda m: None)) == ["demo", "james"]
    assert sorted(_files(outside)) == ["files/keep.json", "in/keep.json", "out/keep.json", "pilot/keep.json"]
    assert sorted(os.listdir(root / "demo")) == ["in"] and os.listdir(root / "demo" / "in") == []
    assert os.listdir(root / "james" / "out") == [] and os.path.islink(root / "linked")


def test_portal_off_on_a_key_failure_and_never_without_a_root(tmp_path, monkeypatch, capsys):
    data, root = tmp_path / "data", tmp_path / "fw_portal"
    data.mkdir()
    _leftovers(root, "demo")
    monkeypatch.setattr(run.portal, "load_key", lambda *a, **k: (_ for _ in ()).throw(OSError("no key")))
    assert run.setup_portal(["demo"], data=str(data), root=str(root)) == ([], "")
    out = capsys.readouterr().out
    assert "no pilot portal this start" in out and "pilot 'demo' off" in out and _files(root) == []
    # an install that never had a portal: no root, nothing made, nothing said
    assert PT.retire(str(tmp_path / "none"), [], log=print) == [] and not (tmp_path / "none").exists()
    os.symlink(root, tmp_path / "linkroot")
    _leftovers(root, "demo")
    assert PT.retire(str(tmp_path / "linkroot"), [], log=print) == [] and _files(root) != []
    assert capsys.readouterr().out == ""

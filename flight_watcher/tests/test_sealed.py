"""1.1.0: sealed settings from the dashboard card. Synthetic values only."""
import json
import os
import re
import shutil
import stat
import subprocess
import time

import pytest

import sealed as SEAL

HERE = os.path.dirname(os.path.abspath(__file__))


def test_key_created_private_and_reused(tmp_path):
    p = tmp_path / "k.pem"
    k1 = SEAL.load_key(str(p))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert SEAL.public_info(SEAL.load_key(str(p))) == SEAL.public_info(k1)


def test_round_trip_and_refusals(tmp_path):
    k = SEAL.load_key(str(tmp_path / "k.pem"))
    pub = SEAL.public_info(k)["pubkey"]
    body = SEAL.seal(pub, {"username": "doej", "password": "pw-1"})
    assert "pw-1" not in json.dumps(body)
    assert SEAL.open_sealed(k, body["enc"]) == {"username": "doej", "password": "pw-1"}
    with pytest.raises(SEAL.SealError, match="too old"):
        SEAL.open_sealed(k, SEAL.seal(pub, {"password": "x"}, ts=time.time() - 7200)["enc"])
    bad = json.loads(json.dumps(body))
    bad["enc"]["data"] = bad["enc"]["data"][:-4] + "AAAA"
    with pytest.raises(SEAL.SealError, match="cannot open"):
        SEAL.open_sealed(k, bad["enc"])
    other = SEAL.load_key(str(tmp_path / "other.pem"))
    with pytest.raises(SEAL.SealError, match="another key"):
        SEAL.open_sealed(other, body["enc"])
    with pytest.raises(SEAL.SealError):
        SEAL.open_sealed(k, {"v": 2})


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_card_seal_opens_in_python(tmp_path):
    """The card's own sealing code (run under Node's WebCrypto) produces what open_sealed() accepts."""
    k = SEAL.load_key(str(tmp_path / "k.pem"))
    info = SEAL.public_info(k)
    src = open(os.path.join(HERE, "..", "www", "flight-watcher-settings-card.js"), encoding="utf-8").read()
    body = re.search(r"try \{\n(.*?)\n      this\._sentAt = a\.at", src, re.S).group(1)
    js = ("const a = %s; const fields = {password: 'pw-node', my_name: 'Doe'};\n"
          "(async () => {\n%s\n console.log(JSON.stringify(body)); })();" % (json.dumps(info), body))
    f = tmp_path / "seal.mjs"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    sealed = json.loads(out.stdout)
    assert "pw-node" not in out.stdout
    assert SEAL.open_sealed(k, sealed["enc"]) == {"password": "pw-node", "my_name": "Doe"}

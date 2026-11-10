"""Sealed settings (1.1.0): credentials typed on the dashboard reach the Watcher encrypted end to end.

Each Watcher instance keeps its own RSA-2048 key pair in <data>/settings_key.pem (created mode 600 on first use,
never leaves the app) and publishes the public half on <prefix>/settings/state (`pubkey`, base64 SPKI DER, and
`kid`, a short fingerprint). The dashboard Settings card encrypts the form in the browser (WebCrypto): a random
AES-256-GCM key encrypts the JSON {fields..., "ts": unix seconds}, and RSA-OAEP (SHA-256) wraps that key. It sends

    {"enc": {"v": 1, "kid": "...", "key": b64, "iv": b64, "data": b64}}

with mqtt.publish to <prefix>/settings/set, so Home Assistant's history database, logs and the MQTT broker only
ever hold ciphertext. open_sealed() returns the fields, or raises SealError (wrong key, tampered, too old).
"""
import base64
import hashlib
import json
import os
import tempfile
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_AGE_S = 3600  # a sealed message older than this (or this far in the future) is refused: no replays later on


class SealError(ValueError):
    pass


_LOCK = threading.Lock()


def load_key(path):
    """The instance's private key, created (mode 600) when missing. A file that does not parse (empty, cut short)
    is moved aside to <path>.bad and replaced by a new key; the card picks the new public key up from the state."""
    with _LOCK:
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return serialization.load_pem_private_key(f.read(), password=None)
            except ValueError:
                os.replace(path, path + ".bad")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        fd, tmp = tempfile.mkstemp(prefix=".settings_key.", dir=os.path.dirname(path) or ".")  # mode 600
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return key


def public_info(key):
    """{pubkey: base64 SPKI DER, kid: 16 hex chars of its SHA-256} for settings/state."""
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"pubkey": base64.b64encode(der).decode(), "kid": hashlib.sha256(der).hexdigest()[:16]}


def open_sealed(key, enc, now=None):
    """Decrypt an {"enc": ...} body; returns the dict of fields (without "ts")."""
    if not isinstance(enc, dict) or enc.get("v") != 1:
        raise SealError("unknown sealed format")
    if enc.get("kid") and enc["kid"] != public_info(key)["kid"]:
        raise SealError("sealed for another key (reload this page and save again)")
    try:
        aes = key.decrypt(base64.b64decode(enc["key"]), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        plain = AESGCM(aes).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["data"]), None)
        d = json.loads(plain)
    except Exception as e:  # noqa: BLE001 (any decode/auth failure is the same answer)
        raise SealError(f"cannot open ({type(e).__name__})") from None
    if not isinstance(d, dict):
        raise SealError("not an object")
    ts = d.pop("ts", None)
    now = time.time() if now is None else now
    if not isinstance(ts, (int, float)) or abs(now - ts) > MAX_AGE_S:
        raise SealError("too old or clock off")
    return d


def seal(pub_b64, fields, ts=None):
    """What the browser card does, in Python (tests, and a CLI for Ryan if ever needed)."""
    pub = serialization.load_der_public_key(base64.b64decode(pub_b64))
    aes = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    data = AESGCM(aes).encrypt(iv, json.dumps({**fields, "ts": time.time() if ts is None else ts}).encode(), None)
    wrapped = pub.encrypt(aes, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                            algorithm=hashes.SHA256(), label=None))
    der = base64.b64decode(pub_b64)
    return {"enc": {"v": 1, "kid": hashlib.sha256(der).hexdigest()[:16], "key": base64.b64encode(wrapped).decode(),
                    "iv": base64.b64encode(iv).decode(), "data": base64.b64encode(data).decode()}}

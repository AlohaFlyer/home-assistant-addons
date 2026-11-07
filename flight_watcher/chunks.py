"""FW-0066 (Ryan, Nov 7: "any user can see and upload"): uploads in chunks over MQTT, for a Home Assistant user who
is not an admin. Home Assistant gives an app ingress session (the uploads card's fast path, web.py api/upload) only to
an admin; any signed-in user may call the mqtt.publish service. So the uploads card sends the file in chunks to
<prefix>/upload/chunk (qos 1, never retained), each one JSON:

    {"v": 1, "id": 16 to 64 letters and digits, "i": index, "n": chunks, "size": file bytes, "sha": sha256 hex of the
     file, "kind": award | pairings | seniority | contacts, "month": "YYYY-MM" (award, pairings) or "",
     "list_date": "YYYY-MM-DD" (seniority, optional) or "", "enc": {...} or absent, "data": base64 of the chunk}

Sealed (whenever the browser has WebCrypto): the file is encrypted once with a random AES-256-GCM key, the key wrapped
with this Watcher's RSA-OAEP public key (sealed.py, the Settings card's), and the ciphertext is what is cut into
chunks; enc = {"v": 1, "kid", "key", "iv", "ts"} rides on every chunk, and the GCM additional data binds the upload's
fields (aad()), so a changed kind, month or size fails to open. Home Assistant records every call_service event with
its data (the recorder keeps one under 32 KB), so a sealed upload leaves only ciphertext there and in the broker.
A plain http page has no WebCrypto: the card then sends the file as it is, except a contact list, which is refused
unsealed (here and in the card).

The Watcher keeps each upload's chunks in a private staging folder (mode 700, files 600) under
/share/flight_watcher/uploads/.staging/<prefix>/<id>/; a repeated chunk is ignored; chunks may come in any order. An
upload that stops arriving for TIMEOUT_S is dropped (sweep()). When all n are in: joined in order, opened when sealed,
checked (size, sha256, the file type for its kind, the size cap) and handed to web.save_upload, the ingress upload's
own save path. The status goes back on <prefix>/upload/status (not retained; sensor.<prefix>_upload_status)."""
import base64
import hashlib
import os
import re
import shutil
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import contacts as CT
import sealed as SEAL

CHUNK_MAX = 192 * 1024  # raw bytes in one chunk (about 256 KiB of base64): the card's FW_UP_CHUNK
MAX_CHUNKS = 4096
MAX_ACTIVE = 4  # uploads in progress at once, per Watcher instance
TIMEOUT_S = 120  # an upload with no chunk for this long is dropped
TAG = 16  # the AES-GCM tag after the ciphertext
KINDS = ("award", "pairings", "seniority", "contacts")
ID_RE = re.compile(r"[A-Za-z0-9]{16,64}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
B64_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}")
META = ("v", "id", "n", "size", "sha", "kind", "month", "list_date", "enc")
WHAT = {"award": "the award", "pairings": "the pairings package", "seniority": "the seniority list",
        "contacts": "the pilot contact list"}


class Bad(ValueError):
    """An upload refused (the message is plain text for the card: no file content in it)."""


def aad(meta):
    """The AES-GCM additional data: the upload's fields, in the card's order (fwUpAad)."""
    enc = meta.get("enc") or {}
    return "|".join(str(x) for x in ("fw-upload", 1, meta["id"], meta["n"], meta["size"], meta["sha"], meta["kind"],
                                     meta["month"], meta["list_date"], enc.get("ts", ""))).encode()


def check_meta(msg, max_bytes):
    """The fields every chunk of one upload carries, validated; raises Bad."""
    if not isinstance(msg, dict) or msg.get("v") != 1:
        raise Bad("Not an upload chunk this version reads.")
    m = {k: msg.get(k) for k in META}
    m["month"], m["list_date"] = m["month"] or "", m["list_date"] or ""
    if not isinstance(m["id"], str) or not ID_RE.fullmatch(m["id"]):
        raise Bad("Bad upload id.")
    if m["kind"] not in KINDS:
        raise Bad("Pick what the file is.")
    if not isinstance(m["size"], int) or isinstance(m["size"], bool) or m["size"] < 1:
        raise Bad("Bad file size.")
    if m["size"] > max_bytes:
        raise Bad(f"Too large: {m['size'] / 1e6:.1f} MB (the Watcher takes up to {max_bytes // 1_000_000} MB).")
    if not isinstance(m["sha"], str) or not SHA_RE.fullmatch(m["sha"]):
        raise Bad("Bad checksum.")
    if m["kind"] in ("award", "pairings"):
        if not isinstance(m["month"], str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m["month"]):
            raise Bad("Pick the bid period (month).")
    elif m["month"]:
        raise Bad("Only an award or a pairings package has a bid period.")
    if m["list_date"] and (m["kind"] != "seniority" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m["list_date"]))):
        raise Bad("Bad list date.")
    enc = m["enc"]
    if enc is not None:
        if not (isinstance(enc, dict) and enc.get("v") == 1 and all(isinstance(enc.get(k), str) for k in ("key", "iv"))
                and isinstance(enc.get("ts"), int) and isinstance(enc.get("kid", ""), str)):
            raise Bad("Bad seal on the upload.")
        m["enc"] = {k: enc.get(k) for k in ("v", "kid", "key", "iv", "ts")}
    elif m["kind"] == "contacts":
        raise Bad("A pilot contact list is only taken encrypted: open Home Assistant at its https address (the "
                  "Nabu Casa one) and upload it again.")
    n = m["n"]
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_CHUNKS or n * CHUNK_MAX < expected(m):
        raise Bad("Bad chunk count.")
    return m


def expected(meta):
    return meta["size"] + (TAG if meta.get("enc") else 0)


class Assembler:
    """Chunks in, whole files out. Thread-safe: chunks arrive on the MQTT thread, sweep() runs on a timer and
    finish() on a worker thread."""

    def __init__(self, root, max_bytes, key=None, now=time.time, timeout_s=TIMEOUT_S):
        self.root, self.max_bytes, self.key, self.now, self.timeout_s = root, max_bytes, key, now, timeout_s
        self.ups, self.lock = {}, threading.Lock()
        self.done = {}  # id -> time an upload was finished or dropped: a late repeated chunk of it is ignored

    def _status(self, up, state, message, ok=None, meta=None):
        m = meta or up["meta"]
        st = {"id": m["id"], "kind": m["kind"], "state": state, "got": len(up["got"]) if up else 0, "total": m["n"],
              "message": message}
        if ok is not None:
            st["ok"] = ok
        return st

    def _mkroot(self):
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _drop(self, uid):
        self.ups.pop(uid, None)
        self.done[uid] = self.now()
        shutil.rmtree(os.path.join(self.root, uid), ignore_errors=True)

    def _fail(self, uid, up, message, meta):
        """End an upload with an error: its chunks go, and later chunks with its id are ignored."""
        self._drop(uid)
        return self._status(up, "error", message, False, meta), None

    def add(self, msg):
        """One chunk. Returns (status or None, ready or None): ready ({meta, dir}) once every chunk is in; status
        None for a chunk the Watcher cannot tie to an upload (no valid id, or an upload already ended)."""
        with self.lock:
            uid = msg.get("id") if isinstance(msg, dict) else None
            if not isinstance(uid, str) or not ID_RE.fullmatch(uid) or uid in self.done:
                return None, None
            up = self.ups.get(uid)
            try:
                meta = check_meta(msg, self.max_bytes)
            except Bad as e:
                n = msg.get("n")
                return self._fail(uid, up, str(e), {"id": uid, "kind": msg.get("kind") if msg.get("kind") in KINDS else "",
                                                   "n": n if isinstance(n, int) and not isinstance(n, bool) else 0})
            i, data = msg.get("i"), msg.get("data")
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < meta["n"]:
                return self._fail(uid, up, "Bad chunk index.", meta)
            raw = None
            if isinstance(data, str) and data and len(data) <= (CHUNK_MAX * 4) // 3 + 4 and B64_RE.fullmatch(data):
                try:
                    raw = base64.b64decode(data, validate=True)
                except ValueError:
                    raw = None
            if not raw or len(raw) > CHUNK_MAX:
                return self._fail(uid, up, "Bad chunk data.", meta)
            if up is None:
                if len(self.ups) >= MAX_ACTIVE:
                    return self._fail(uid, None, "The Watcher is busy with other uploads; try again in a minute.", meta)
                self._mkroot()
                d = os.path.join(self.root, uid)
                shutil.rmtree(d, ignore_errors=True)  # a folder left from before a restart
                os.makedirs(d, mode=0o700)
                up = self.ups[uid] = {"meta": meta, "dir": d, "got": {}, "bytes": 0, "first": self.now(),
                                      "last": self.now()}
            elif up["meta"] != meta:
                return self._fail(uid, up, "The upload's parts do not match; nothing was saved.", meta)
            up["last"] = self.now()
            if i in up["got"]:  # a repeated chunk (the card or the broker sent it twice): the first copy stands
                return self._status(up, "receiving", f"Received {len(up['got'])} of {meta['n']} parts."), None
            if up["bytes"] + len(raw) > expected(meta):
                return self._fail(uid, up, "More data came than the file's size; nothing was saved.", meta)
            fd = os.open(os.path.join(up["dir"], f"{i:05d}.part"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            up["got"][i] = len(raw)
            up["bytes"] += len(raw)
            if len(up["got"]) < meta["n"]:
                return self._status(up, "receiving", f"Received {len(up['got'])} of {meta['n']} parts."), None
            if up["bytes"] != expected(meta):
                return self._fail(uid, up, "The parts do not add up to the file's size; nothing was saved.", meta)
            self.ups.pop(uid, None)
            self.done[uid] = self.now()
            return self._status(up, "checking", f"All {meta['n']} parts in; checking the file."), up

    def finish(self, up):
        """Join, open and check a complete upload: (fields for web.save_upload, file bytes). Raises Bad; the staging
        folder goes either way."""
        meta = up["meta"]
        try:
            blob = b"".join(open(os.path.join(up["dir"], f"{i:05d}.part"), "rb").read() for i in range(meta["n"]))
        except OSError as e:
            raise Bad(f"The upload's parts were lost ({type(e).__name__}); nothing was saved.") from None
        finally:
            shutil.rmtree(up["dir"], ignore_errors=True)
        if meta.get("enc"):
            blob = self._open(meta, blob)
        if len(blob) != meta["size"]:
            raise Bad("The file's size does not match; nothing was saved.")
        if hashlib.sha256(blob).hexdigest() != meta["sha"]:
            raise Bad("The file's checksum does not match (it changed on the way); nothing was saved. Try again.")
        if meta["kind"] == "contacts":
            if CT.sniff(blob) is None:
                raise Bad("That file is not a PDF, CSV or XLSX contact list.")
        elif not blob.startswith(b"%PDF"):
            raise Bad("That file is not a PDF.")
        return {"kind": meta["kind"], "month": meta["month"], "list_date": meta["list_date"]}, blob

    def _open(self, meta, blob):
        enc = meta["enc"]
        key = self.key() if callable(self.key) else self.key
        if key is None:
            raise Bad("The Watcher has no key to open a sealed upload.")
        if enc.get("kid") and enc["kid"] != SEAL.public_info(key)["kid"]:
            raise Bad("Sealed for another key: reload the dashboard and upload again.")
        if abs(self.now() - enc["ts"]) > SEAL.MAX_AGE_S:
            raise Bad("The sealed upload is too old (or this device's clock is off); upload again.")
        try:
            aes = key.decrypt(base64.b64decode(enc["key"]), padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            return AESGCM(aes).decrypt(base64.b64decode(enc["iv"]), blob, aad(meta))
        except Exception as e:  # noqa: BLE001 (any unwrap or tag failure is the same answer)
            raise Bad(f"The sealed upload does not open ({type(e).__name__}); nothing was saved. Reload the "
                      "dashboard and upload again.") from None

    def sweep(self):
        """Drop uploads that stopped arriving (TIMEOUT_S with no chunk) and staging folders left from before a
        restart. Returns the error statuses for the dropped uploads."""
        out, now = [], self.now()
        with self.lock:
            for uid, t in list(self.done.items()):
                if now - t > 10 * self.timeout_s:
                    self.done.pop(uid, None)
            for uid, up in list(self.ups.items()):
                if now - up["last"] > self.timeout_s:
                    self._drop(uid)
                    out.append(self._status(up, "error", f"Timed out: {len(up['got'])} of {up['meta']['n']} parts "
                                            "arrived; nothing was saved. Upload again.", False))
            try:
                left = os.listdir(self.root)
            except OSError:
                left = []
            for name in left:
                p = os.path.join(self.root, name)
                if name in self.ups:
                    continue
                try:
                    if now - os.path.getmtime(p) > self.timeout_s:
                        shutil.rmtree(p, ignore_errors=True)
                except OSError:
                    pass
        return out

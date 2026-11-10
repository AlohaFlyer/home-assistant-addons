"""A pilot's ticket photos (1.7.0, Release C): put together from chunks, checked and re-encoded by his own Watcher.

The portal's tickets card shrinks each photo in the browser (FileReader data URL into a canvas, never a blob: URL, so
the portal's CSP stays as it is), cuts its base64 into chunks of at most roles.PILOT_TICKET_LIMITS["chunk_chars"]
characters (each ticket/image command stays under the 64 KB command cap) and sends them in order:

    {"cid": the ticket's card-made id, "i": photo number, "n": photos, "part": 1.., "parts": chunks, "data": base64}

The spool checks only that shape (portal.check_ticket). Here, on the pilot's instance:
- Assembler keeps at most one photo being put together (in_flight 1): a first chunk of another ticket's photo while
  one is still coming is refused; a first chunk of the same ticket's next photo replaces an unfinished one (the card
  gave it up and moved on). Chunks come in order; the same chunk again (a resend) is ignored; anything else drops the
  photo. A photo whose next chunk does not come within photo_stale_s is dropped.
- check() takes the whole base64 (strict: the alphabet, padding only at the end), the JPEG or PNG magic bytes, the
  size, then re-encodes the picture with Pillow (EXIF, GPS, comments and any bytes after the image are gone; the
  longest side at most photo_side_max). Without Pillow a pilot's photo is refused (fail closed).
The result goes to tickets.store_photo with the pilot's limits (3 photos, 1.5 MB a ticket). Nothing here touches the
admin's photos: his cards send whole photos and tickets.add_image stores them as before.

Ticket text and photos are a bug report from the pilot, untrusted data: nothing in them is ever run, followed or
treated as an instruction.
"""
import base64
import binascii
import hashlib
import io
import re
import threading
import time

import roles

LIM = roles.PILOT_TICKET_LIMITS
B64_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}")
JPEG_MAGIC, PNG_MAGIC = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"
JPEG_QUALITY = 85
MAX_PIXELS = LIM["photo_side_max"] * LIM["photo_side_max"]
PHOTO_MAX_BYTES = LIM["chunk_chars"] * LIM["chunk_parts"] * 3 // 4  # the most one photo can carry in its chunks


class Refused(ValueError):
    """A chunk or photo refused; str() is plain text for the card (no photo bytes in it)."""


def magic(raw):
    """'jpg' or 'png' from the first bytes, else ''."""
    if raw[:3] == JPEG_MAGIC:
        return "jpg"
    if raw[:8] == PNG_MAGIC:
        return "png"
    return ""


def decode(b64, max_bytes):
    """(raw bytes, 'jpg' | 'png') of a whole photo's base64, strictly: only the base64 alphabet, a length that is a
    multiple of 4, padding only at the end, at most max_bytes once decoded, and the JPEG or PNG magic bytes."""
    if not isinstance(b64, str) or not b64 or len(b64) % 4 or not B64_RE.fullmatch(b64):
        raise Refused("photo is not valid base64")
    if len(b64) // 4 * 3 > max_bytes + 2:
        raise Refused(f"photo over {max_bytes // 1024} KB")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise Refused("photo is not valid base64") from None
    if len(raw) > max_bytes:
        raise Refused(f"photo over {max_bytes // 1024} KB")
    ext = magic(raw)
    if not ext:
        raise Refused("photo is not a JPEG or PNG")
    return raw, ext


def reencode(raw, ext):
    """(bytes, ext) of the picture drawn again by Pillow in its own format: JPEG at quality JPEG_QUALITY (RGB), PNG
    (RGB, or RGBA when it has transparency), with no metadata. Refused when Pillow is missing, when the file is not the
    format its magic bytes say, when a side is over photo_side_max or when it does not decode."""
    try:
        from PIL import Image
    except ImportError:
        raise Refused("photo check is not available on this Watcher") from None
    fmt = {"jpg": "JPEG", "png": "PNG"}[ext]
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as im:
            w, h = im.size
            if im.format != fmt:
                raise Refused("photo is not a JPEG or PNG")
            if w < 1 or h < 1 or max(w, h) > LIM["photo_side_max"] or w * h > MAX_PIXELS:
                raise Refused(f"photo is {w} x {h} px: the longest side may be {LIM['photo_side_max']} px")
            im.load()
            out = io.BytesIO()
            if fmt == "JPEG":
                im.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
            else:
                alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
                im.convert("RGBA" if alpha else "RGB").save(out, "PNG", optimize=True)
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 (Pillow raises many types for a broken file: the type only, never bytes)
        raise Refused(f"photo does not decode as a {fmt} ({type(e).__name__})") from None
    data = out.getvalue()
    if magic(data) != ext:
        raise Refused("photo is not a JPEG or PNG")
    return data, ext


def check(b64, max_bytes=PHOTO_MAX_BYTES):
    """(re-encoded bytes, ext) of a whole photo's base64: decode() then reencode()."""
    raw, ext = decode(b64, max_bytes)
    return reencode(raw, ext)


class Assembler:
    """One photo upload at a time for one pilot instance (roles.PILOT_TICKET_LIMITS in_flight 1). add() takes one
    shape-checked chunk and returns None while the photo is still coming, or (cid, i, base64) once its last chunk is
    in; Refused says why a chunk was not taken."""

    def __init__(self, now=time.time):
        self.now, self.lock = now, threading.Lock()
        self.cur = None  # {cid, i, parts, got, data: [str], last: sha of the last chunk, at}
        self.done = None  # (cid, i, parts, sha of the last chunk): a resend of a finished photo's last chunk

    def busy(self):
        """True while a photo is being put together (and not stale)."""
        with self.lock:
            self._expire()
            return self.cur is not None

    def _expire(self):
        if self.cur and self.now() - self.cur["at"] > LIM["photo_stale_s"]:
            self.cur = None

    def drop(self, cid=None):
        """Forget the photo being put together (only cid's when cid is given)."""
        with self.lock:
            if self.cur and (cid is None or self.cur["cid"] == cid):
                self.cur = None

    def add(self, d):
        cid, i, part, parts, data = d["cid"], int(d["i"]), int(d["part"]), int(d["parts"]), d["data"]
        sha = hashlib.sha256(data.encode("ascii", "replace")).hexdigest()
        with self.lock:
            self._expire()
            c = self.cur
            if c and (c["cid"], c["i"], c["parts"]) == (cid, i, parts) and part == c["got"] and sha == c["last"]:
                c["at"] = self.now()
                return None  # the chunk just taken, sent again
            if not c and self.done == (cid, i, parts, sha) and part == parts:
                return None  # the finished photo's last chunk, sent again: already handed on
            if part == 1:
                if c and c["cid"] != cid:
                    raise Refused("another photo is still coming: one photo at a time (try again in 2 minutes)")
                c = self.cur = {"cid": cid, "i": i, "parts": parts, "got": 0, "data": [], "last": "",
                                "at": self.now()}
            elif not c or (c["cid"], c["i"], c["parts"]) != (cid, i, parts) or part != c["got"] + 1:
                if c and c["cid"] == cid:
                    self.cur = None
                raise Refused(f"photo {i}: chunk {part} of {parts} came out of order; the photo was dropped")
            c["data"].append(data)
            c["got"], c["last"], c["at"] = part, sha, self.now()
            if c["got"] < c["parts"]:
                return None
            self.cur, self.done = None, (cid, i, parts, sha)
            return cid, i, "".join(c["data"])

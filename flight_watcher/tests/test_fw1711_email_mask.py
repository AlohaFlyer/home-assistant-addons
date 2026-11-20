"""captures.mask (a pilot's capture mask, also run on each of his log lines by PilotLogMask) masks e-mail addresses in
linear time: a long run of address characters with no '@' cost it minutes (the pattern was tried from each of the
run's characters). It masks the very same spans as before. Synthetic data only."""
import random
import re
import time

import pytest

import captures as CAPS

OLD_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")  # the 1.6.2 pattern, as mask() ran it until now


def old_emails(t):
    return OLD_EMAIL_RE.sub(lambda m: CAPS._x(m.group(0)), t)


@pytest.mark.parametrize("tok", ["x" * 200000, "9" * 100000, "1.2.3.4." * 20000])
def test_a_long_token_costs_the_mask_no_seconds(tok):
    t0 = time.perf_counter()
    CAPS.mask(tok, ())
    assert time.perf_counter() - t0 < 2.0, tok[:8]


@pytest.mark.parametrize("make", [lambda n: "x" * n + "@", lambda n: "x" * n + " jane.doe@example.com",
                                  lambda n: "a@" * (n // 2), lambda n: "x@" + "a" * n, lambda n: "x@" + "a." * (n // 2),
                                  lambda n: "1.2.3.4.@" * (n // 9), lambda n: "9" * n + "@example.com"])
def test_a_long_token_with_an_at_sign_costs_no_seconds_either(make):
    t0 = time.perf_counter()
    CAPS._emails(make(200000))
    assert time.perf_counter() - t0 < 2.0, make(8)
    assert CAPS._emails(make(300)) == old_emails(make(300))  # the old pattern is quadratic: compared on a short copy


@pytest.mark.parametrize("text,leaks,kept", [
    ("mail doe.j@example.com today", ("doe.j", "example"), "mail xxx.x@xxxxxxx.xxx today"),
    ("x@y.com 808-555-0100", ("x@y.com",), "x@x.xxx"),
    ("<jane+fw@mail.example.co.uk>", ("jane", "example"), "<xxxx+xx@xxxx.xxxxxxx.xx.xx>"),
    ("a@b.c+d@e.f", ("b.c", "d@e.f"), "x@x.x+x@x.x"),  # right after an address: the next one is masked too
    ("j_d-1@mail.example.com, pat.poe@example.org", ("j_d", "pat", "poe", "example"), "x_x-#@xxxx.xxxxxxx.xxx, "),
    ("x" * 70 + "@example.com", ("example",), "x" * 70 + "@xxxxxxx.xxx"),  # a local part over 64 characters
    ("jane@" + "b" * 70 + ".com", ("jane", "bbb"), "xxxx@" + "x" * 70 + ".xxx"),  # a label over 63
])
def test_every_address_is_masked_as_before(text, leaks, kept):
    out = CAPS.mask(text, ())
    for leak in leaks:
        assert leak not in out, (text, out, leak)
    assert kept in out, (text, out)
    assert CAPS._emails(text) == old_emails(text)


def test_the_same_spans_as_the_old_pattern_on_random_text():
    rnd = random.Random(1711)
    alphabet = "ab9_.+-@ x!<>é"
    for n in range(20000):
        t = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))
        assert CAPS._emails(t) == old_emails(t), repr(t)


def test_no_at_sign_no_change():
    for t in ("", "Doe, Jane H3601 17Nov", "x" * 1000, "1.2.3.4." * 100):
        assert CAPS._emails(t) == t

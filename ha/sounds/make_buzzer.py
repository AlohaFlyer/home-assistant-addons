"""FW-0054 (Ryan): the buzzer for a new pairing he can take. Writes flight-watcher-buzzer.wav (16-bit PCM, 48 kHz,
mono, about 1.4 s: three harsh buzzes). Pure Python so it runs on the HA host:
    python3 make_buzzer.py /homeassistant/www/flight-watcher-buzzer.wav
iOS plays a push's named sound only after it is imported into the Home Assistant app (Settings > Companion App >
Notifications > Sounds > Import); until then it plays the default sound."""
import math
import struct
import sys
import wave

RATE = 48000


def buzz(sec, f1=196.0, f2=294.0, amp=0.9):
    """A square-ish buzz (two detuned square waves, soft clipped) with 8 ms ramps so it never clicks."""
    n, ramp = int(sec * RATE), int(0.008 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        s = 0.55 * (1 if math.sin(2 * math.pi * f1 * t) >= 0 else -1) + 0.45 * (1 if math.sin(2 * math.pi * f2 * t) >= 0 else -1)
        s = math.tanh(1.6 * s) / math.tanh(1.6)
        env = min(1.0, i / ramp, (n - 1 - i) / ramp)
        out.append(amp * env * s)
    return out


def main(path):
    gap = [0.0] * int(0.12 * RATE)
    samples = buzz(0.38) + gap + buzz(0.38) + gap + buzz(0.38)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767)) for x in samples))
    print(path, len(samples) / RATE, "s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "flight-watcher-buzzer.wav")

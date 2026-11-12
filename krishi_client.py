"""Smart Krishi - the PC side of the voice kiosk.

Adapted from Campus Mithra's pc_client.py. The ESP32 link (USB serial, the
button-mode loop, credit-based audio streaming to the MAX98357A) is unchanged;
only the server endpoints changed, and the campus-only features (Firestore
campus lookup, walking-route QR codes, RFID attendance) are gone.

By default the kiosk's own INMP441 microphone and talk button are the input:
hold the button, speak, let go. The recording streams over USB, then Sarvam
(speech to text) -> Gemma + agricultural RAG -> edge-tts, and the answer is
shown on the TFT and spoken on the MAX98357A.

    python krishi_client.py                       kiosk button + mic (COM port auto-detected)
    python krishi_client.py --esp32 COM9          same, explicit port
    python krishi_client.py --pc-mic              fallback: PC earphone mic + Ctrl+Alt+4
    python krishi_client.py --devices             list PC input devices and exit
    python krishi_client.py --ask "tomato fertilizer"   one text question, no microphone

Endpoints used (server/app.py):
    POST /api/krishi/transcribe       recording -> text (Sarvam)
    POST /api/krishi/chat             text -> answer + sources + audio_id (Gemma + RAG)
    GET  /api/krishi/audio/{id}.s16   the spoken answer, 16-bit 16 kHz for the I2S amp
"""

from __future__ import annotations

import argparse
import ctypes
import io
import math
import os
import re
import sys
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    # The file wins over values a VS Code terminal copied in before it was edited.
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass
DEFAULT_SERVER = os.getenv("KRISHI_SERVER", f"http://127.0.0.1:{os.getenv('PORT', '8001')}")
TARGET_RATE = 16000          # what the server and Sarvam prefer
CHANNELS = 1
CHUNK = 1024

# Judged on RMS and clipping, never on peak alone: one stray spike pushes the
# peak to full scale without meaning anything, while a genuinely railed input
# both carries a large RMS and spends much of its time pinned at the limit.
RAILED_RMS = 8000
CLIPPED_FRACTION = 0.01
ALIVE_RMS = 2.0


# --------------------------------------------------------------------------- #
# Global hotkey (Windows, via RegisterHotKey)
# --------------------------------------------------------------------------- #

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY, PM_REMOVE = 0x0312, 0x0001

MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
             "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}


class HotkeyError(RuntimeError):
    pass


def parse_hotkey(combo: str):
    mods, vk, label = 0, None, []
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
            label.append(part)
        elif len(part) == 1 and (part.isalnum()):
            vk = ord(part.upper())
            label.append(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x70 + int(part[1:]) - 1
            label.append(part.upper())
        elif part == "space":
            vk, _ = 0x20, label.append("Space")
        else:
            raise HotkeyError(f"Cannot parse hotkey part {part!r} in {combo!r}")
    if vk is None:
        raise HotkeyError(f"No key found in {combo!r} (e.g. ctrl+alt+4)")
    return mods, vk, "+".join(label)


class HotkeyListener:
    """A system-wide hotkey that sets an Event each time it is pressed.

    RegisterHotKey binds the hotkey to the *calling thread* and posts WM_HOTKEY
    to that thread's message queue, so registration and the message pump must
    both live on the one thread -- hence everything inside _run().
    """

    def __init__(self, combo="ctrl+alt+4"):
        if sys.platform != "win32":
            raise HotkeyError("global hotkeys are implemented for Windows only")
        self.mods, self.vk, self.name = parse_hotkey(combo)
        self.pressed = threading.Event()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None

    def _run(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not user32.RegisterHotKey(None, 1, self.mods | MOD_NOREPEAT, self.vk):
            err = ctypes.get_last_error()
            extra = " - another application already owns it" if err == 1409 else ""
            self._error = f"Windows refused to register {self.name} (error {err}{extra})."
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    if msg.message == WM_HOTKEY:
                        self.pressed.set()
                else:
                    time.sleep(0.02)
        finally:
            user32.UnregisterHotKey(None, 1)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        if self._error:
            raise HotkeyError(self._error)
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def clear(self):
        self.pressed.clear()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


# --------------------------------------------------------------------------- #
# Microphone
# --------------------------------------------------------------------------- #

def list_input_devices(pa):
    devices = []
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
        except OSError:
            continue
        if int(info.get("maxInputChannels", 0)) < 1:
            continue
        try:
            host = pa.get_host_api_info_by_index(info["hostApi"])["name"]
        except OSError:
            host = "?"
        devices.append({"index": i, "name": str(info["name"]), "host_api": str(host),
                        "channels": int(info["maxInputChannels"]),
                        "rate": int(info["defaultSampleRate"])})
    return devices


def default_input_index(pa):
    try:
        return int(pa.get_default_input_device_info()["index"])
    except (OSError, KeyError):
        return None


def open_input_stream(pa, device_index, device_rate):
    import pyaudio
    last = None
    for rate in dict.fromkeys((TARGET_RATE, device_rate)):
        try:
            return pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=rate,
                           input=True, input_device_index=device_index,
                           frames_per_buffer=CHUNK), rate
        except OSError as exc:
            last = exc
    raise RuntimeError(
        f"Could not open device {device_index} at {TARGET_RATE} Hz or {device_rate} Hz.\n"
        f"  PortAudio said: {last}\n"
        "  Check the mic is plugged in, not in use elsewhere, and that\n"
        "  Settings > Privacy & security > Microphone allows desktop apps.")


def probe_level(pa, device, seconds=0.6, settle=0.25):
    """Record briefly and return (peak, rms, clipped_fraction), or None.

    The first buffers after opening a stream routinely carry a DC step or a
    one-sample spike, enough to make a good microphone look pinned at full
    scale, so `settle` worth of audio is discarded first.
    """
    try:
        stream, rate = open_input_stream(pa, device["index"], device["rate"])
    except (RuntimeError, OSError):
        return None
    try:
        frames = [stream.read(CHUNK, exception_on_overflow=False)
                  for _ in range(max(1, int(rate * (seconds + settle) / CHUNK)))]
        audio = np.frombuffer(b"".join(frames), dtype=np.int16)
        drop = int(rate * settle)
        if audio.size > drop + CHUNK:
            audio = audio[drop:]
        if audio.size == 0:
            return 0, 0.0, 0.0
        mag = np.abs(audio.astype(np.int32))
        return (int(mag.max()),
                float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))),
                float(np.count_nonzero(mag >= 32000) / mag.size))
    except OSError:
        return None
    finally:
        stream.stop_stream()
        stream.close()


# Names that mean "a mic you wear" versus "a mic built into the laptop". On a
# typical Realtek laptop, "Microphone (Realtek...)" is the 3.5 mm jack the wired
# earphones plug into and "Microphone Array (Realtek...)" is the built-in pair.
EARPHONE_HINTS = ("headset", "headphone", "earphone", "earbud", "hands-free", "handsfree",
                  "airpods", "buds", "bluetooth", "bt ", "usb audio", "jack")
BUILTIN_HINTS = ("array", "internal", "built-in", "builtin", "webcam", "camera")


def mic_kind(name):
    n = name.lower()
    if any(h in n for h in EARPHONE_HINTS):
        return "earphone"
    if any(h in n for h in BUILTIN_HINTS):
        return "built-in"
    return "jack"      # unlabelled Realtek "Microphone" = the headset jack


def pick_input_device(pa, devices, default_index):
    """Choose the earphone microphone, and make sure it is actually delivering audio.

    Preference: anything named like a headset/earphone, then the plain
    "Microphone" jack, and only then the laptop's built-in mic array. Each
    candidate is probed, because the Windows default cannot be trusted: a jack
    with nothing plugged in opens happily and records perfect silence.
    """
    skip = ("droidcam", "midi", "pc speaker", "sound mapper", "primary sound", "stereo mix")
    candidates = [d for d in devices if not any(s in d["name"].lower() for s in skip)] or devices
    # Windows lists every mic once per audio API (MME, DirectSound, WASAPI,
    # WDM-KS). MME is the most forgiving about sample rates, so probe only those
    # when there are any - it is the same microphone, and startup is 4x faster.
    mme = [d for d in candidates if d["host_api"] == "MME"]
    if mme:
        candidates = mme

    print("\nFinding a working microphone ...")
    scored = []
    for d in candidates:
        level = probe_level(pa, d)
        if level is None:
            continue
        peak, rms, clipped = level
        note = ("silent" if rms < ALIVE_RMS
                else "saturated" if rms > RAILED_RMS or clipped > CLIPPED_FRACTION
                else "ok")
        d["noise_rms"] = rms
        scored.append((d, rms, note))
        print(f"    [{d['index']:>2}] {d['name'][:32]:<32} {mic_kind(d['name']):<9} "
              f"rms {rms:>7.1f}  clip {clipped * 100:>4.0f}%  {note}")

    usable = [(d, r) for d, r, n in scored if n == "ok"]
    rank = {"earphone": 0, "jack": 1, "built-in": 2}
    if usable:
        best_kind = min(rank[mic_kind(d["name"])] for d, _ in usable)
        worn = [(d, r) for d, r in usable if rank[mic_kind(d["name"])] == best_kind]
        if best_kind < 2:
            chosen = max(worn, key=lambda dr: dr[1])[0]
            print(f"  Using the earphone mic: [{chosen['index']}] {chosen['name']}")
            return chosen
        print("  No earphone mic is producing sound - is the earphone plugged in, and is it")
        print("  enabled under Settings > System > Sound > Input?  Using the built-in mic for now.")
    if not usable:
        fallback = next(((d, r) for d, r, n in scored if n == "saturated"), None)
        if fallback is None:
            idx = default_index if default_index is not None else devices[0]["index"]
            chosen = next(d for d in devices if d["index"] == idx)
            print(f"  No device produced any audio. Falling back to [{chosen['index']}] {chosen['name']}.")
            print("  Check Windows mic privacy settings and the input volume.")
            return chosen
        chosen, rms = fallback
        print(f"  Only saturated inputs found; using [{chosen['index']}] {chosen['name']} (rms {rms:.0f}).")
        print("  Expect empty transcripts - turn that input's level down or pass --device.")
        return chosen

    # Honour the Windows default when it actually works, so a deliberately
    # configured mic beats whichever other device happens to be noisier now.
    for d, rms in usable:
        if d["index"] == default_index:
            print(f"  Using the Windows default: [{d['index']}] {d['name']}")
            return d
    chosen, rms = max(usable, key=lambda dr: dr[1])
    print(f"  Using [{chosen['index']}] {chosen['name']} (rms {rms:.0f})")
    return chosen


class SpeechEndpointer:
    """Decides when the visitor has finished speaking, from audio level alone.

    Speech starts when the level stays clearly above the mic's idle noise floor
    for ~0.2 s, and ends after `silence_s` of quiet - long enough to ride over
    the natural pauses inside a sentence, short enough not to feel laggy. If
    nobody speaks within `no_speech_s`, it gives up rather than recording a
    silent room until the time limit.

    The noise floor comes from the startup mic probe, so there is no
    calibration delay after the wake chime, when visitors start talking at once.
    """

    def __init__(self, rate, frame, noise_rms, silence_s=1.2, no_speech_s=6.0,
                 ratio=3.0, min_rms=150.0, max_rms=3000.0, threshold=None):
        fs = frame / rate
        self.silence_frames = max(1, round(silence_s / fs))
        self.no_speech_frames = max(1, round(no_speech_s / fs))
        self.start_frames = max(1, round(0.2 / fs))
        floor = max(noise_rms or 0.0, 1.0)
        self.threshold = threshold or min(max_rms, max(min_rms, floor * ratio))
        self.floor = floor
        self.n = self.loud_run = self.quiet_run = 0
        self.started = False

    def push(self, rms):
        """Feed one frame's RMS. Returns 'waiting', 'speech', 'done' or 'no_speech'."""
        self.n += 1
        if not self.started:
            self.loud_run = self.loud_run + 1 if rms >= self.threshold else 0
            if self.loud_run >= self.start_frames:
                self.started = True
                return "speech"
            return "no_speech" if self.n >= self.no_speech_frames else "waiting"
        # Hysteresis: only clearly-quiet frames count towards the end, so a soft
        # word near the threshold doesn't cut the sentence off.
        self.quiet_run = self.quiet_run + 1 if rms < self.threshold * 0.7 else 0
        return "done" if self.quiet_run >= self.silence_frames else "speech"

    def level(self, rms):
        """0-100 for a level meter: the noise floor at 0, ~40 dB above it at 100."""
        return int(max(0, min(100, 50 * math.log10(max(rms, 1.0) / self.floor))))


def record(pa, device, max_seconds, hotkey, esp=None, auto_stop=True, threshold=None):
    """Record from the wake press until the visitor stops talking.

    Ends on whichever comes first: silence after speech (auto_stop), the hotkey
    pressed again, or max_seconds. Returns (samples, rate, reason) where reason
    is 'silence', 'key', 'max' or 'no_speech'.
    """
    stream, rate = open_input_stream(pa, device["index"], device["rate"])
    if hotkey:
        hotkey.clear()          # a press while opening belongs to the start
    ep = SpeechEndpointer(rate, CHUNK, device.get("noise_rms"), threshold=threshold)
    frames, reason, heard, last_meter = [], "max", False, 0.0
    how = "stops when you finish talking" if auto_stop else "press again to stop"
    print(f"\n>>> LISTENING - speak now ({how}; max {max_seconds}s)")
    try:
        for _ in range(math.ceil(rate * max_seconds / CHUNK)):
            if hotkey and hotkey.pressed.is_set():
                reason = "key"
                break
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
            state = ep.push(rms)

            now = time.time()
            if now - last_meter > 0.15:
                pct = ep.level(rms)
                bar = "#" * (pct // 5)
                print(f"    mic [{bar:<20}] {'hearing you' if ep.started else 'waiting...'}  ",
                      end="\r", flush=True)
                if esp:
                    esp.level(pct)
                last_meter = now

            if state == "speech" and not heard:
                heard = True
                if esp:
                    esp.status("hearing you")
            if auto_stop and state == "done":
                reason = "silence"
                break
            if auto_stop and state == "no_speech":
                reason = "no_speech"
                break
    except OSError as exc:
        raise RuntimeError(f"Microphone read failed mid-recording: {exc}") from exc
    finally:
        stream.stop_stream()
        stream.close()
        if esp:
            esp.level(0)
    audio = np.frombuffer(b"".join(frames), dtype=np.int16)
    print(f">>> STOPPED ({reason}) - captured {audio.size / rate:.1f}s" + " " * 30)
    return audio, rate, reason


def resample(audio, rate):
    if rate == TARGET_RATE or audio.size == 0:
        return audio, rate
    try:
        from scipy.signal import resample_poly
    except ImportError:
        print(f"  note: sending at native {rate} Hz (scipy not installed)")
        return audio, rate
    g = math.gcd(TARGET_RATE, rate)
    out = resample_poly(audio.astype(np.float32), TARGET_RATE // g, rate // g)
    return np.clip(out, -32768, 32767).astype(np.int16), TARGET_RATE


def wav_bytes(audio, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# ESP32 display + speaker (USB serial)
# --------------------------------------------------------------------------- #

BAUD = 921600    # must match SERIAL_BAUD in firmware/include/config.h

# USB-serial bridges used on ESP32 DevKit boards, by (vid, pid).
KNOWN_BRIDGES = {
    (0x10C4, 0xEA60): "Silicon Labs CP2102",
    (0x1A86, 0x7523): "WCH CH340",
    (0x1A86, 0x55D4): "WCH CH9102",
    (0x0403, 0x6001): "FTDI FT232",
    (0x303A, 0x1001): "Espressif native USB",
}


def autodetect_esp32_port():
    from serial.tools import list_ports
    found = [p.device for p in list_ports.comports() if (p.vid, p.pid) in KNOWN_BRIDGES]
    return found[0] if len(found) == 1 else None


class Esp32Link:
    """Link to firmware/src/main.cpp over USB serial.

    One byte stream carries text lines (status, credits, logs) and binary
    packets announced by a header line ("MIC:<n>" / "RAW:<n>" followed by n raw
    bytes). Everything is read through one buffer, so a packet can never be
    half-consumed as text.

    Opening a COM port normally pulses DTR/RTS, which resets an ESP32; both are
    held low before opening so a running board keeps running.
    """

    def __init__(self, port, baud=BAUD, verbose=False):
        import serial
        self.port, self.verbose = port, verbose
        self._rx = bytearray()
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, baud, 0.05
        self.ser.dtr = False
        self.ser.rts = False
        try:
            self.ser.open()
        except serial.SerialException as exc:
            hint = ""
            if "Access is denied" in str(exc) or "PermissionError" in str(exc):
                hint = ("\n  Another program has the port. Close `pio device monitor`, "
                        "the VS Code serial monitor, or any other script using it.")
            raise RuntimeError(f"Could not open {port}: {exc}{hint}") from exc

    # --- low level -------------------------------------------------------------

    def _send(self, line):
        payload = line.replace("\r", " ").replace("\n", " ")
        self.ser.write((payload + "\n").encode("utf-8", errors="replace"))
        self.ser.flush()

    def _fill(self):
        chunk = self.ser.read(max(1, self.ser.in_waiting))
        if chunk:
            self._rx += chunk
        return bool(chunk)

    def _read_line(self, timeout):
        deadline = time.time() + timeout
        while True:
            i = self._rx.find(b"\n")
            if i >= 0:
                line = bytes(self._rx[:i])
                del self._rx[:i + 1]
                return line.decode("ascii", errors="replace").strip()
            if time.time() >= deadline:
                return None
            self._fill()

    def _read_exact(self, n, timeout=3.0):
        deadline = time.time() + timeout
        while len(self._rx) < n and time.time() < deadline:
            self._fill()
        data = bytes(self._rx[:n])
        del self._rx[:n]
        return data

    def _readline(self):
        return self._read_line(0.2) or ""

    def discard_input(self):
        self.ser.reset_input_buffer()
        self._rx.clear()

    def next_event(self, timeout=0.2):
        """('line', text) | ('mic', pcm_bytes) | ('raw', bytes) | None on timeout."""
        line = self._read_line(timeout)
        if line is None:
            return None
        if line.startswith(("MIC:", "RAW:")):
            try:
                n = int(line[4:])
            except ValueError:
                return ("line", line)
            return (line[:3].lower(), self._read_exact(n))
        return ("line", line)

    # --- commands --------------------------------------------------------------

    def ping(self):
        for _ in range(2):
            self.discard_input()
            self._send("PING")
            deadline = time.time() + 2.5
            while time.time() < deadline:
                if self._readline() == "PONG":
                    # the kiosk follows PONG with its screen language (LANG:en|kn|hi)
                    line = self._read_line(0.5) or ""
                    if line.startswith("LANG:"):
                        set_screen_lang(line[5:])
                    return True
            time.sleep(2.0)         # maybe it was booting
        return False

    def question(self, text): self._send(f"Q:{text}")
    def answer(self, text): self._send(f"A:{text}")
    def source(self, files): self._send(f"R:{files}")
    def qr(self, url, label=""):
        # QR:<url>|<label>; the label is display text, so it cannot carry a "|" or a newline
        label = re.sub(r"[|\r\n]+", " ", label).strip()[:120]
        self._send(f"QR:{url}|{label}" if label else f"QR:{url}")
    def listening(self, prompt=""): self._send(f"L:{prompt}")
    def status(self, text): self._send(f"S:{text[:30]}")
    def clear(self): self._send("CLR")
    def beep(self): self._send("BEEP")
    def heartbeat(self): self._send("HB")
    def idle(self): self._send("IDLE")      # the kiosk may accept a new button press
    def dashboard(self, line): self._send(line[:400])   # "D:k=v;..." - DashboardPoller.take_line()

    def glyphs(self, header, rows):
        """Kannada/Hindi text as 1-bit rows (kiosk_text.py): "GQ:w,h" or
        "GA:w,h,pages", then one "GR:<hex>" line per row with trailing zero
        bytes dropped. Paced in ~1 KB bursts so the kiosk's 4 KB receive
        buffer is never overrun while it is busy drawing."""
        out = [header]
        for r in rows:
            out.append("GR:" + r.rstrip(b"\x00").hex())
        data = ("\n".join(out) + "\n").encode("ascii")
        for i in range(0, len(data), 1024):
            self.ser.write(data[i:i + 1024])
            self.ser.flush()
            time.sleep(0.012)
    def volume(self, pct): self._send(f"VOL:{max(0, min(100, int(pct)))}")
    def test_record(self, ms): self._send(f"MICREC:{int(ms)}")

    def level(self, pct):
        # No flush: these go out ~7 times a second and must never stall the mic loop.
        self.ser.write(f"M:{max(0, min(100, int(pct)))}\n".encode())

    def play(self, pcm: bytes, bytes_per_second=32000):
        """Stream the spoken answer (16-bit 16 kHz by default) to the speaker.
        Blocks until it has finished playing. Returns (ok, message).

        The ESP32 grants credit ("C:<n>") as room frees up in its buffer, and
        audio is only ever sent against credit, so nothing can overflow.
        """
        if not pcm:
            return True, "no audio"
        # Drop replies to earlier commands, so a stale line can't be mistaken
        # for this transfer's DONE or ERR.
        time.sleep(0.05)
        self.discard_input()
        self._send(f"AUD:{len(pcm)}")
        sent, credit = 0, 0
        deadline = time.time() + len(pcm) / bytes_per_second + 20
        while time.time() < deadline:
            if credit > 0 and sent < len(pcm):
                n = min(credit, len(pcm) - sent, 4096)
                self.ser.write(pcm[sent:sent + n])
                sent += n
                credit -= n
                continue
            line = self._read_line(0.2)
            if not line:
                continue
            if line.startswith("C:"):
                credit += int(line[2:] or 0)
            elif line.startswith("DONE:"):
                played, gaps = (line[5:].split(",") + ["0"])[:2]
                note = f"{int(played) / bytes_per_second:.1f}s"
                if int(gaps):
                    note += f", {gaps} gap(s)"
                if line.endswith(",stopped"):          # the farmer pressed the button
                    note += " - stopped by the button"
                return True, note
            elif line.startswith("ERR:"):
                return False, line[4:]
            elif self.verbose:
                print(f"    {line}")
        return False, f"timed out ({sent}/{len(pcm)} bytes sent)"

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def kiosk_volume(arg):
    """--volume, else KIOSK_VOLUME in .env (0-100), else the firmware's own level."""
    if arg is not None:
        return arg
    v = os.getenv("KIOSK_VOLUME", "").strip()
    return int(v) if v.isdigit() else None


def connect_esp32(port, volume=None):
    """Open the ESP32 link, or return None (the client keeps working without it)."""
    if port and port.lower() == "none":
        return None
    try:
        import serial  # noqa: F401
    except ImportError:
        print("  ESP32: pyserial is not installed (pip install pyserial) - continuing without it.")
        return None
    if not port:
        port = autodetect_esp32_port()
        if not port:
            print("  ESP32: none detected - continuing with PC audio. Use --esp32 COM9 to force.")
            return None
    try:
        link = Esp32Link(port)
    except RuntimeError as exc:
        print(f"  ESP32: {exc}\n  Continuing with PC audio.")
        return None
    if not link.ping():
        print(f"  ESP32: {port} opened but the board did not answer PING.\n"
              "    Is the Smart Krishi firmware flashed?  (cd firmware && pio run -t upload)")
        link.close()
        return None
    if volume is not None:
        link.volume(volume)
    link.clear()
    print(f"  ESP32: connected on {port}")
    return link


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #

def send_indic_text(esp, question, answer=None):
    """Kannada/Hindi question (and answer) to the kiosk TFT in their own script.
    Returns True when sent; on any problem the kiosk shows the Latin text."""
    try:
        import kiosk_text
        if not (kiosk_text.has_indic(answer if answer is not None else question) and kiosk_text.available()):
            return False
        q_rows = kiosk_text.render_question(question or "")
        esp.glyphs(f"GQ:{kiosk_text.TEXT_W},{len(q_rows)}", q_rows)
        if answer is not None:
            pages, page_h = kiosk_text.render_answer(answer, len(q_rows))
            esp.glyphs(f"GA:{kiosk_text.TEXT_W},{page_h},{len(pages)}", [r for p in pages for r in p])
        return True
    except Exception as exc:
        print(f"           (Kannada/Hindi script for the TFT failed: {exc}; showing Latin letters)")
        return False


def deliver(result, server, esp=None, play=True, pc_audio=False, question_text=None):
    """Print the answer, put it on the TFT, and speak it.

    With an ESP32 connected the answer is spoken on the kiosk speaker; the PC
    speakers are used only when there is no ESP32, or with --pc-audio.
    """
    answer = result.get("answer", "")
    sources = result.get("sources") or []
    print(f"  krishi > {answer}")
    if result.get("language", "en") != "en":
        print(f"           (en) {result.get('answer_en', '')}")
    if sources:
        how = " (read directly from the knowledge base - Gemma was unavailable)" \
            if result.get("via") == "kb-direct" else ""
        print(f"           referred: {', '.join(sources)}{how}")
    elif not result.get("in_scope"):
        print("           referred: (nothing in the knowledge base)")
    if esp:
        esp.source("")     # no "from <file>" line under the answer (sources stay in this console log)
        if result.get("language", "en") != "en":
            # in Kannada/Hindi script; A: below still carries the Latin copy as a fallback
            send_indic_text(esp, question_text or result.get("question", ""), answer)
        esp.answer(result.get("answer_display") or answer)
    if not (play and result.get("audio_id")):
        if esp:
            esp.status("ready")
        return
    if esp:
        # 16-bit 16 kHz for the MAX98357A (the server's .s16 format)
        pcm = fetch_audio(server, result["audio_id"], "s16")
        if pcm:
            ok, note = esp.play(pcm, bytes_per_second=32000)
            print(f"           (spoken on the kiosk speaker: {note})" if ok
                  else f"           (kiosk speaker failed: {note})")
    if pc_audio or not esp:
        play_answer(server, result["audio_id"])


def fetch_audio(server, audio_id, ext):
    import httpx
    try:
        r = httpx.get(f"{server}/api/krishi/audio/{audio_id}.{ext}", timeout=120)
    except httpx.RequestError as exc:
        print(f"           (no audio: {exc})")
        return None
    if r.status_code != 200:
        # 503 here means text-to-speech failed; the server needs internet for edge-tts.
        print(f"           (no audio: HTTP {r.status_code} - is the server online for edge-tts?)")
        return None
    return r.content


def play_answer(server, audio_id):
    data = fetch_audio(server, audio_id, "mp3")
    if not data:
        return
    path = ROOT / "server" / "debug" / "last_answer.mp3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if sys.platform != "win32":
        print(f"           (saved to {path})")
        return
    # winsound only plays WAV, so play the mp3 through WPF's MediaPlayer, and
    # wait exactly as long as the clip lasts rather than a fixed delay.
    import subprocess
    script = (
        "Add-Type -AssemblyName presentationCore; "
        "$p = New-Object System.Windows.Media.MediaPlayer; "
        f"$p.Open([uri]'{path}'); "
        "$n = 0; while (-not $p.NaturalDuration.HasTimeSpan -and $n -lt 100) "
        "{ Start-Sleep -Milliseconds 50; $n++ }; "
        "$p.Play(); "
        "if ($p.NaturalDuration.HasTimeSpan) "
        "{ Start-Sleep -Milliseconds ([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds + 300) } "
        "else { Start-Sleep -Seconds 10 }; "
        "$p.Close()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       timeout=90, capture_output=True)
    except Exception:
        print(f"           (could not play; saved to {path})")


def ask_text(server, question, session, language="en", style="mixed"):
    import httpx
    body = {"question": question, "session": session}
    if language != "en":
        body.update(language=language, style=style)   # answered the way it was asked
    r = httpx.post(f"{server}/api/krishi/chat", json=body, timeout=180)
    r.raise_for_status()
    return r.json()


def understand(server, text):
    """A typed question in any kiosk language (Kannada, Hindi, English, or a
    Kanglish mix): its language, English for the RAG search and
    Gemma, and a Latin-script copy for the TFT. English as-is if that fails."""
    import httpx
    try:
        r = httpx.post(f"{server}/api/krishi/understand", json={"text": text}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"language": "en", "english": text, "display": text}


def transcribe(server, audio, rate):
    """Speech to text on the server. Returns the /api/transcribe JSON."""
    import httpx
    files = {"file": ("q.wav", wav_bytes(audio, rate), "audio/wav")}
    r = httpx.post(f"{server}/api/krishi/transcribe", files=files, timeout=120)
    r.raise_for_status()
    return r.json()


def handle_question(server, question, session, esp, play, pc_audio, heard=None):
    """Question text in -> answer on screen and speaker out.

    heard is the /api/transcribe reply for a spoken question; it already says
    which language it was in. Retrieval and Gemma work in English; the
    answer comes back in the farmer's language.
    """
    q = heard if heard and "english" in heard else understand(server, question)
    lang, english = q.get("language", "en"), q.get("english") or question
    style = q.get("style", "mixed")      # Kanglish/Hinglish, or plain Kannada/Hindi
    asked_in = lang
    # The answer comes back in the language the question was asked in (and in
    # the same style: Kanglish/Hinglish stays mixed), whatever language the
    # screen was set to. Only the screen's own labels follow SCREEN_LANG.
    print(f"\n  you    > {question}")
    if lang != "en" or english != question:
        print(f"           ({lang}) {english}")
    if esp:
        if asked_in != "en":
            send_indic_text(esp, question)            # the question in its own script
        esp.question(q.get("display") or question)   # shown now, while Gemma works
    t0 = time.time()
    result = ask_text(server, english, session) if lang == "en" else ask_text(server, english, session, lang, style)
    print(f"           ({time.time() - t0:.1f}s)")
    sensor = result.get("sensor")
    if sensor:
        print(f"           live sensor reading used: {sensor.get('device_id')} ({sensor.get('status')})")
    deliver(result, server, esp, play, pc_audio, question_text=question)


# --------------------------------------------------------------------------- #
# Kiosk push-to-talk: the INMP441 on the ESP32 is the microphone
# --------------------------------------------------------------------------- #

KIOSK_MIC_RATE = 16000     # MIC_RATE in firmware/include/config.h


def condition_kiosk_audio(pcm):
    """Prepare a kiosk recording for speech-to-text.

    The firmware already removes DC, so this only levels it: the loudness of a
    push-to-talk clip depends on how far the visitor stands from the mic, and
    Sarvam does better on a consistently loud signal. Gain is capped at 20x so
    that a near-silent clip is not blown up into pure noise.
    Returns (int16 samples, stats dict).
    """
    x = pcm.astype(np.float32)
    x -= x.mean()
    peak = float(np.percentile(np.abs(x), 99.9)) if x.size else 0.0
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    gain = min(20.0, (0.7 * 32767) / peak) if peak > 0 else 1.0
    y = np.clip(x * gain, -32768, 32767).astype(np.int16)
    return y, {"rms": rms, "peak": peak, "gain": gain}


def save_wav(path, samples, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def answer_kiosk_recording(server, esp, raw, kiosk_bytes, kiosk_ms, args):
    """One finished button press: recording -> Sarvam -> Gemma -> TFT + speaker."""
    pcm = np.frombuffer(bytes(raw[: len(raw) // 2 * 2]), dtype="<i2")
    secs = pcm.size / KIOSK_MIC_RATE
    lost = kiosk_bytes - len(raw)
    print(f"  recorded {secs:.1f}s ({len(raw):,} bytes"
          + (f", {lost:,} lost on the link!" if lost else "") + f"; button held {kiosk_ms} ms)")

    audio, st = condition_kiosk_audio(pcm)
    save_wav(ROOT / "server" / "debug" / "last_kiosk_mic.wav", audio, KIOSK_MIC_RATE)
    print(f"  mic level: rms {st['rms']:.0f}, peak {st['peak']:.0f}, levelled x{st['gain']:.1f}"
          "  (server/debug/last_kiosk_mic.wav)")

    if st["peak"] < 60:
        print("  That recording is silent - is the INMP441 wired and powered?")
        esp.status("no sound")
        esp.answer("I couldn't hear anything. Hold the button and speak close to the microphone.")
        return

    esp.status("PROCESSING")
    t0 = time.time()
    heard = transcribe(server, audio, KIOSK_MIC_RATE)
    print(f"  [sarvam {time.time() - t0:.1f}s]", end=" ")
    if not heard.get("ok"):
        print(f"speech-to-text failed: {heard.get('error')}")
        esp.status("speech error")
        esp.answer(heard.get("reply", "My speech service is not working right now."))
        return
    if not heard.get("text"):
        print("heard nothing intelligible")
        esp.status("didn't catch that")
        esp.answer("I didn't catch that. Hold the button and try again.")
        return
    print(f"heard: {heard['text']!r}")
    handle_question(server, heard["text"], args.session, esp, not args.no_audio, args.pc_audio, heard)


SCREEN_LANG = {"lang": "en"}          # chosen on the kiosk's language screen (LANG: lines)


def set_screen_lang(code):
    code = (code or "").strip()
    if code in ("en", "kn", "hi") and code != SCREEN_LANG["lang"]:
        SCREEN_LANG["lang"] = code
        print(f"  kiosk screen language: {code}")


class LabelWorker:
    """Screen text in Kannada / Hindi for the kiosk.

    The kiosk sends TRQ:<key>|<lang>|<font>|<maxW>|<lines>|<English text> for
    each text it needs. This thread batches them, has the server translate them
    (POST /api/krishi/translate), renders each in its script (kiosk_text) to fit
    maxW x lines, and queues "LB:<key>|<w>,<h>" + "LR:<hex>" lines. The serial
    loop sends the queue with take() only between recordings and answers."""

    def __init__(self, server):
        self.server = server
        self._q = []
        self._out = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._rendered = {}                   # (lang, font, maxw, lines, text) -> (w, h, rows)
        threading.Thread(target=self._run, daemon=True).start()

    def request(self, line):
        parts = line[4:].split("|", 5)
        if len(parts) != 6:
            return
        key, lang, font, maxw, lines, text = parts
        try:
            req = (key, lang, int(font), int(maxw), int(lines), text)
        except ValueError:
            return
        with self._lock:
            self._q.append(req)
        self._wake.set()

    def take(self, max_bytes=6000):
        """Queued lines, up to about max_bytes per call so the loop stays responsive."""
        out, size = [], 0
        with self._lock:
            while self._out and size < max_bytes:
                block = self._out.pop(0)
                out += block
                size += sum(len(x) + 1 for x in block)
        return out

    def _run(self):
        import httpx
        import kiosk_text
        while True:
            self._wake.wait()
            time.sleep(0.12)                  # gather a screenful of requests
            self._wake.clear()
            with self._lock:
                batch, self._q = self._q, []
            by_lang = {}
            for req in batch:
                by_lang.setdefault(req[1], []).append(req)
            for lang, reqs in by_lang.items():
                todo = [r for r in reqs if (lang, r[2], r[3], r[4], r[5]) not in self._rendered]
                texts = list(dict.fromkeys(r[5] for r in todo))
                translated = {}
                for i in range(0, len(texts), 50):
                    chunk = texts[i:i + 50]
                    try:
                        resp = httpx.post(f"{self.server}/api/krishi/translate",
                                          json={"lang": lang, "texts": chunk}, timeout=60)
                        resp.raise_for_status()
                        translated.update(zip(chunk, resp.json()["translations"]))
                    except Exception as exc:
                        print(f"  screen text: translation failed ({exc}); the kiosk keeps English")
                for key, _, font, maxw, lines, text in reqs:
                    ck = (lang, font, maxw, lines, text)
                    if ck not in self._rendered:
                        native = translated.get(text)
                        if not native:
                            continue
                        try:
                            rows, w, h = kiosk_text.render_label(native, font, maxw or 300, lines)
                        except Exception as exc:
                            print(f"  screen text: render failed for {text!r}: {exc}")
                            continue
                        self._rendered[ck] = (w, h, rows)
                    w, h, rows = self._rendered[ck]
                    block = [f"LB:{key}|{w},{h}"] + ["LR:" + r.rstrip(b"\x00").hex() for r in rows]
                    with self._lock:
                        self._out.append(block)


class DashboardPoller:
    """Fetches /api/krishi/sensors/latest every `every` seconds on its own
    thread, so a slow or dead server never stalls the serial loop (which must
    keep reading mic audio). The main loop asks for the newest D: line with
    take_line() and sends it only between recordings and answers.

    D: line fields (empty value = not available):
        st   online | stale | offline | no_data | unknown (server unreachable)
        age  seconds since the reading reached the server, at send time
        t h  temperature degC, humidity %
        sr sv sp   soil raw ADC, soil valid 0/1, soil percent (calibrated only)
        mq mv      MQ-135 raw ADC, valid 0/1 (0 while warming up / faulty)
        srv  ok | down       dev  device id       td  1 = test data
    """

    def __init__(self, server, every=5.0):
        self.server, self.every = server, every
        self._lock = threading.Lock()
        self._data, self._fetched, self._ok, self._new = None, 0.0, None, False
        self._weather, self._weather_at = None, 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import httpx
        while True:
            if time.time() - self._weather_at > 60:       # the server caches it for 10 min
                try:
                    w = httpx.get(f"{self.server}/api/krishi/weather", timeout=15).json()
                    with self._lock:
                        if w.get("alert", 0) >= 2 and (self._weather or {}).get("alert", 0) < 2:
                            print(f"  RAIN ALERT on the dashboard: {w.get('message')}")
                        self._weather = w if w.get("ok") else (self._weather if self._weather else w)
                except Exception:
                    pass
                self._weather_at = time.time()
            try:
                r = httpx.get(f"{self.server}/api/krishi/sensors/latest", timeout=3.0)
                r.raise_for_status()
                data, ok = r.json(), True
            except Exception:
                data, ok = None, False
            with self._lock:
                if ok:
                    self._data, self._fetched = data, time.time()
                if ok != self._ok:
                    print(f"  dashboard: server {'reachable' if ok else 'UNREACHABLE - showing last known reading'}")
                self._ok, self._new = ok, True
            time.sleep(self.every)

    @staticmethod
    def _num(v, nd=1):
        return "" if v is None else (f"{v:.{nd}f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))

    def take_line(self):
        """The newest D: line, once per poll; None when nothing new."""
        with self._lock:
            if not self._new:
                return None
            self._new = False
            data, fetched, ok, w = self._data, self._fetched, self._ok, self._weather
        f = {"srv": "ok" if ok else "down", "st": "unknown" if not ok else "no_data"}
        if w and w.get("ok"):
            # weather: temp, condition, alert 0-3, message (no ';' or '=' - D: line syntax)
            f.update(wt=self._num(w.get("temp_c")), wc=re.sub(r"[^A-Za-z]", "", w.get("condition", ""))[:12],
                     wa=str(int(w.get("alert", 0))), wm=re.sub(r"[;=|]", " ", w.get("message", ""))[:60])
        if data:
            if ok:
                f["st"] = data.get("status", "no_data")
            rd = data.get("reading") or {}
            if rd:
                age = (data.get("age_seconds") or 0) + (time.time() - fetched)
                f.update(age=str(int(age)), t=self._num(rd.get("temperature_c")),
                         h=self._num(rd.get("humidity_percent"), 0), sr=self._num(rd.get("soil_moisture_raw")),
                         sv="1" if rd.get("soil_sensor_valid") else "0",
                         sp=self._num(rd.get("soil_moisture_percent"), 0), mq=self._num(rd.get("mq135_raw")),
                         mv="1" if rd.get("mq135_valid", True) else "0",
                         dev=re.sub(r"[^A-Za-z0-9_\-]", "", str(rd.get("device_id", "")))[:24],
                         td="1" if rd.get("is_test_data") else "0")
        return "D:" + ";".join(f"{k}={v}" for k, v in f.items())


def kiosk_crops(server, esp):
    """CROPS? from the touch screen -> the server's crop list."""
    import httpx
    try:
        data = httpx.get(f"{server}/api/krishi/fertilizer/crops", timeout=10).json()
        crops, regions = data["crops"], data.get("regions", [])
        esp._send("CROPS:" + ";".join(f"{c['id']}={c['name']}" for c in crops))
        if regions:
            esp._send(f"REGIONS:{data.get('default_region', 'other')}|" +
                      ";".join(f"{r['id']}={r['name']}" for r in regions))
        print(f"  touch screen: {len(crops)} crops, {len(regions)} districts sent")
    except Exception as exc:
        print(f"  touch screen: crop list failed: {exc}")


LAST_FERT = {}          # the recommendation the farmer is looking at (for star feedback)


def kiosk_feedback(server, line):
    """FB:<1-5> from the stars after a fertilizer recommendation."""
    import httpx
    try:
        stars = int(line[3:].strip())
        body = {"stars": stars, "kind": "fertilizer", "language": SCREEN_LANG["lang"], **LAST_FERT}
        httpx.post(f"{server}/api/krishi/feedback", json=body, timeout=10).raise_for_status()
        print(f"  feedback: {stars} star{'s' if stars != 1 else ''} for {LAST_FERT.get('crop', '?')}")
    except Exception as exc:
        print(f"  feedback not saved: {exc}")


def kiosk_fertilizer(server, esp, line):
    """FERT:crop=tomato;area=1;n=low;p=unknown;k=high -> recommendation pages
    (FRB/FRT/FRL.../FRE), or FRX:<message> on failure."""
    import httpx
    f = dict(kv.split("=", 1) for kv in line[5:].split(";") if "=" in kv)
    try:
        body = {"crop": f.get("crop", ""), "area_acres": float(f.get("area", "1")),
                "n": f.get("n", "unknown"), "p": f.get("p", "unknown"), "k": f.get("k", "unknown"),
                "region": f.get("region") or None}
        r = httpx.post(f"{server}/api/krishi/fertilizer", json=body, timeout=20)
        r.raise_for_status()
        rec = r.json()
    except Exception as exc:
        print(f"  fertilizer request failed: {exc}")
        esp._send("FRX:Could not work out the recommendation. Check the PC app and server, then try again.")
        return
    pages = rec["screen"]["pages"]
    clean = lambda t: re.sub(r"[|\r\n]+", " ", t)[:95]
    lines = [f"FRB:{len(pages)}", f"FRT:{clean(rec['screen']['title'])}"]
    lines += [f"FRL:{i}|{ln['style']}|{clean(ln['text'])}" for i, pg in enumerate(pages) for ln in pg]
    for ln in lines + ["FRE"]:
        esp._send(ln)
    LAST_FERT.clear()
    LAST_FERT.update(crop=rec["crop"], area_acres=rec["area_acres"], region=rec["region"]["id"],
                     ratings=rec["ratings"], totals=rec["totals"])
    t = rec["totals"]
    print(f"  fertilizer: {rec['name']} {rec['area_acres']} acre, {rec['region']['name']}, soil {rec['ratings']} from {rec['rating_from']} -> "
          f"urea {t['urea_kg']} kg, DAP {t['dap_kg']} kg, MOP {t['mop_kg']} kg  ({rec['source']['crop']})")


def run_button_mode(server, esp, args):
    """Wait for the kiosk's talk button and answer each recording.

    The ESP32 streams its INMP441 audio while the button is held ("REC:START",
    then "MIC:" packets, then "REC:END" on release). Each finished recording is
    answered, then "IDLE" tells the kiosk it may accept the next press. A short
    tap only switches the kiosk between its dashboard and chat screens: the
    ESP32 reports it as "REC:CANCEL tap" and the audio is dropped.
    """
    print("\nReady. Kiosk button: TAP to switch dashboard/chat, HOLD to ask a question.  Ctrl+C to quit.")
    esp.status("ready")
    esp.heartbeat()
    dash = DashboardPoller(server)
    labels = LabelWorker(server)
    rec, rec_last, last_hb = None, 0.0, time.time()
    try:
        while True:
            # Heartbeats tell the kiosk the PC app is there; it refuses presses
            # (and says so on screen) when they stop.
            if rec is None and time.time() - last_hb > 2.0:
                esp.heartbeat()
                last_hb = time.time()
            # Dashboard data: only while no recording is streaming in, and never
            # during an answer (this loop is busy then, and the link is audio).
            if rec is None:
                line = dash.take_line()
                if line:
                    esp.dashboard(line)
                # Kannada / Hindi screen text, paced like the answer bitmaps.
                out = labels.take()
                if out:
                    data = ("\n".join(out) + "\n").encode("ascii")
                    for i in range(0, len(data), 1024):
                        esp.ser.write(data[i:i + 1024])
                        esp.ser.flush()
                        time.sleep(0.012)

            ev = esp.next_event(0.2)
            if ev is None:
                if rec is not None and time.time() - rec_last > 3.0:
                    print("\n  The recording stopped arriving mid-way - USB link problem?")
                    rec = None
                    esp.status("link error")
                    esp.idle()
                continue
            kind, payload = ev

            if kind == "mic":
                if rec is not None:
                    rec += payload
                    rec_last = time.time()
                continue
            if kind != "line":
                continue
            line = payload

            if line == "REC:START":
                rec, rec_last = bytearray(), time.time()
                print("\n>>> LISTENING (button held)")
            elif line.startswith("REC:END"):
                parts = line.split()
                kiosk_bytes = int(parts[1]) if len(parts) > 1 else 0
                kiosk_ms = int(parts[2]) if len(parts) > 2 else 0
                print(">>> released")
                try:
                    answer_kiosk_recording(server, esp, rec or bytearray(), kiosk_bytes, kiosk_ms, args)
                except Exception as exc:
                    print(f"  Failed: {exc}")
                    esp.status("server error")
                    esp.answer("Sorry, something went wrong. Please try again.")
                finally:
                    rec = None
                    esp.idle()
                    last_hb = time.time()
            elif line.startswith("REC:CANCEL"):
                reason = line[11:].strip()
                if reason == "tap":
                    print("  (button tap: screen switched)")
                else:
                    print(f"  (recording discarded: {reason or 'too short'})")
                rec = None
            elif line.startswith("[esp] screen"):
                print(f"  kiosk: {line[6:]}")
            elif line.startswith("TRQ:"):
                labels.request(line)
            elif line.startswith("LANG:"):
                set_screen_lang(line[5:])
            elif line == "CROPS?":
                kiosk_crops(server, esp)
            elif line.startswith("FB:"):
                kiosk_feedback(server, line)
            elif line.startswith("FERT:"):
                kiosk_fertilizer(server, esp, line)
            elif line.startswith(("[esp]", "ERR")):
                print(f"  kiosk: {line}")
    except KeyboardInterrupt:
        print("\nBye.")


def check_server(server):
    import httpx
    try:
        r = httpx.get(f"{server}/api/krishi/health", timeout=15)
        r.raise_for_status()
        h = r.json()
    except Exception as exc:
        print(f"Cannot reach the Smart Krishi server at {server}\n  {exc}\n"
              "  Start it with:  cd server && python app.py")
        return None
    print(f"Server: {server}  |  {h.get('app')}  |  {h.get('chunks')} chunks  |  "
          f"backend {h.get('backend')}  |  embeddings {h.get('embeddings')}")
    return h


# --------------------------------------------------------------------------- #

def main(argv=None):
    # Kannada and Hindi questions and answers are printed: a legacy Windows
    # console code page would otherwise raise UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Smart Krishi push-to-talk client")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--hotkey", default="ctrl+alt+4")
    ap.add_argument("--device", type=int, help="input device index (see --devices)")
    ap.add_argument("--mic", help="pick the mic whose name contains this text, e.g. --mic Headset")
    ap.add_argument("--manual-stop", action="store_true",
                    help="don't stop on silence; press the hotkey again to stop")
    ap.add_argument("--vad-threshold", type=float,
                    help="mic level (RMS) that counts as speech, if auto-detection misjudges your mic")
    ap.add_argument("--no-chime", action="store_true", help="no wake chime on the kiosk speaker")
    ap.add_argument("--devices", action="store_true", help="list input devices and exit")
    ap.add_argument("--seconds", type=int, default=15, help="maximum recording length")
    ap.add_argument("--ask", help="ask one text question and exit (no microphone)")
    ap.add_argument("--no-audio", action="store_true", help="do not speak the answer")
    ap.add_argument("--esp32", default="",
                    help="ESP32 COM port, e.g. COM9 (auto-detected if omitted; 'none' to disable)")
    ap.add_argument("--volume", type=int, help="kiosk speaker volume 0-100")
    ap.add_argument("--pc-audio", action="store_true",
                    help="also play the answer on the PC speakers when an ESP32 is connected")
    ap.add_argument("--pc-mic", action="store_true",
                    help="use the PC (earphone) microphone and the hotkey instead of the "
                         "kiosk's INMP441 and talk button")
    ap.add_argument("--session", default="pc")
    args = ap.parse_args(argv)

    if args.ask:
        if check_server(args.server) is None:
            return 1
        esp = connect_esp32(args.esp32, kiosk_volume(args.volume))
        try:
            handle_question(args.server, args.ask, args.session, esp,
                            not args.no_audio, args.pc_audio)
            if esp:
                esp.idle()
        finally:
            if esp:
                esp.close()
        return 0

    # Default: the kiosk's own microphone and talk button. The PC microphone and
    # hotkey below remain as a fallback (--pc-mic, or when no kiosk is attached).
    if not args.pc_mic and not args.devices:
        if check_server(args.server) is None:
            return 1
        esp = connect_esp32(args.esp32, kiosk_volume(args.volume))
        if esp:
            try:
                run_button_mode(args.server, esp, args)
            finally:
                esp.clear()
                esp.close()
            return 0
        print("  No kiosk connected - falling back to the PC microphone and hotkey.")

    try:
        import pyaudio
    except ImportError:
        print("PyAudio is not installed.\n  pip install PyAudio")
        return 1

    pa = pyaudio.PyAudio()
    try:
        devices = list_input_devices(pa)
        if not devices:
            print("No input devices found.")
            return 1
        default_index = default_input_index(pa)

        if args.devices:
            print("\nInput devices ('*' = Windows default)")
            for d in devices:
                star = "*" if d["index"] == default_index else " "
                print(f" {star} [{d['index']:>2}] {d['name'][:40]:<40} "
                      f"{d['host_api'][:12]:<12} {d['channels']}ch {d['rate']}Hz")
            return 0

        if check_server(args.server) is None:
            return 1

        if args.device is not None or args.mic:
            if args.device is not None:
                device = next((d for d in devices if d["index"] == args.device), None)
            else:
                named = [d for d in devices if args.mic.lower() in d["name"].lower()]
                device = next((d for d in named if d["host_api"] == "MME"), named[0] if named else None)
            if device is None:
                print(f"No matching input device ({args.device or args.mic}). Try --devices.")
                return 1
            level = probe_level(pa, device)          # noise floor for end-of-speech detection
            device["noise_rms"] = level[1] if level else None
            print(f"Using [{device['index']}] {device['name']}  (idle rms {device['noise_rms'] or 0:.0f})")
        else:
            device = pick_input_device(pa, devices, default_index)

        esp = connect_esp32(args.esp32, kiosk_volume(args.volume))

        try:
            hotkey = HotkeyListener(args.hotkey).start()
        except HotkeyError as exc:
            print(f"\n{exc}\n  Falling back to pressing Enter in this window.")
            hotkey = None

        key = hotkey.name if hotkey else "Enter"
        stop = (f"press {key} again" if args.manual_stop
                else f"it stops by itself when you finish (or press {key} again)")
        print(f"\nReady. Press {key} to wake Smart Krishi and speak - {stop}.  Ctrl+C to quit.")
        if esp:
            esp.status(f"press {key.lower()}")
        try:
            while True:
                if hotkey:
                    hotkey.clear()
                    while not hotkey.pressed.is_set():
                        time.sleep(0.05)
                    hotkey.clear()
                else:
                    input()

                # Wake: chime, then the listening screen. The chime is finished
                # before recording starts, so it is never captured by the mic.
                if esp:
                    if not args.no_chime:
                        esp.beep()
                        time.sleep(0.35)
                    esp.listening()
                audio, rate, reason = record(pa, device, args.seconds, hotkey, esp,
                                             auto_stop=not args.manual_stop,
                                             threshold=args.vad_threshold)
                if reason == "no_speech":
                    print("  I didn't hear anything. Speak a little louder or closer to the mic.\n"
                          "  (If your voice never lights up the meter, try --vad-threshold 80.)")
                    if esp:
                        esp.status("didn't hear you")
                        esp.answer("I didn't hear anything. Press the talk key and try again.")
                    continue
                if audio.size < rate // 2:
                    print("  Too short - speak a little longer.")
                    if esp:
                        esp.status("too short")
                    continue
                audio, rate = resample(audio, rate)
                if esp:
                    esp.status("recognising")
                try:
                    heard = transcribe(args.server, audio, rate)
                    if not heard.get("ok"):
                        # Speech service failed - not the same as silence.
                        print(f"  Speech-to-text failed: {heard.get('error')}")
                        if esp:
                            esp.status("speech error")
                            esp.answer(heard.get("reply", ""))
                        continue
                    if not heard.get("text"):
                        print("  Heard nothing - speak closer to the mic.")
                        if esp:
                            esp.status("didn't catch that")
                        continue
                    handle_question(args.server, heard["text"], args.session, esp,
                                    not args.no_audio, args.pc_audio, heard)
                except Exception as exc:
                    print(f"  Request failed: {exc}")
                    if esp:
                        esp.status("server error")
        except KeyboardInterrupt:
            print("\nBye.")
        finally:
            if hotkey:
                hotkey.stop()
            if esp:
                esp.clear()
                esp.close()
    finally:
        pa.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Speech-to-text (Sarvam AI or faster-whisper), text-to-speech (edge-tts) and
audio helpers.

STT_PROVIDER picks the engine:
    sarvam   - api.sarvam.ai, better on Indian English and Indian languages
    whisper  - faster-whisper, runs offline on the CPU (the default)

Only the speech-to-text half varies. The text-to-speech path below (edge-tts ->
mp3 -> 8-bit PCM for the ESP32 DAC) is shared by both.
"""
import io, json, os, re, threading, wave
import numpy as np

_model, _lock = None, threading.Lock()

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# What each failure actually means for someone standing at the kiosk.
SARVAM_ERROR_HINTS = {
    400: "Bad request - usually an unsupported audio format or a bad parameter.",
    401: "Invalid or missing API key. Check SARVAM_API_KEY.",
    403: "API key rejected (invalid, disabled, or no access to this model).",
    404: "Endpoint not found - the Sarvam API path may have changed.",
    413: "Audio too large. Keep clips under about 30 seconds.",
    422: "Unprocessable audio or parameters - check SARVAM_LANGUAGE and the audio.",
    429: "Rate limit or quota exceeded. Wait and retry, or check your Sarvam plan.",
    500: "Sarvam server error. Retry in a moment.",
    503: "Sarvam service unavailable. Retry in a moment.",
}


class SttError(RuntimeError):
    """Speech-to-text failed. Deliberately distinct from an empty transcript:
    an empty transcript means silence was heard, this means nothing was."""


def provider() -> str:
    return os.getenv("STT_PROVIDER", "whisper").strip().lower()


# --- faster-whisper (offline) -------------------------------------------------

def _whisper():
    global _model
    with _lock:
        if _model is None:
            # Imported here, not at module load, so a Sarvam-only install does
            # not need faster-whisper (or its ~200 MB of dependencies) at all.
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SttError(
                    "STT_PROVIDER=whisper but faster-whisper is not installed.\n"
                    "  pip install faster-whisper      (or set STT_PROVIDER=sarvam)"
                ) from exc
            _model = WhisperModel(os.getenv("WHISPER_MODEL", "base.en"), device="cpu", compute_type="int8")
    return _model


def warmup():
    """Load the local model ahead of the first question. A no-op for Sarvam,
    which has nothing to load."""
    if provider() != "sarvam":
        _whisper()


def _run(audio, hint):
    lang = os.getenv("STT_LANGUAGE", "en") or None
    segs, _ = _whisper().transcribe(audio, language=lang, beam_size=5, vad_filter=True,
                                    condition_on_previous_text=False, initial_prompt=hint or None)
    return " ".join(s.text.strip() for s in segs).strip()


# --- Sarvam AI ----------------------------------------------------------------

def _keyterms(hint: str) -> list[str]:
    """Sarvam's equivalent of Whisper's initial_prompt.

    kb/meta.json carries the vocabulary as one comma-separated string, which is
    what Whisper wants. Sarvam wants a JSON list instead, at most 50 entries of
    at most 64 characters, and it is what makes Oxford, KCET and COMEDK come back
    spelled correctly.
    """
    terms = []
    for raw in (hint or "").replace("\n", ",").split(","):
        term = raw.strip().strip(".")
        if term and term not in terms:
            terms.append(term[:64])
    return terms[:50]


def _describe_sarvam_error(status: int, body: str) -> str:
    detail = ""
    try:
        data = json.loads(body)
        err = data.get("error", data) if isinstance(data, dict) else {}
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("detail") or "").strip()
    except ValueError:
        pass
    if not detail:
        detail = body[:300].strip()
    hint = SARVAM_ERROR_HINTS.get(status, "Unexpected response from Sarvam.")
    return f"Sarvam STT error - HTTP {status}: {hint}" + (f"\n  API message: {detail}" if detail else "")


def _sarvam_transcribe(filename: str, data: bytes, mime: str, hint: str = "") -> tuple[str, str | None]:
    """(transcript, detected language code). With SARVAM_LANGUAGE=unknown Sarvam
    detects the language (Kannada, Hindi, English, and mixes of them)."""
    import httpx

    key = os.getenv("SARVAM_API_KEY", "").strip()
    if not key:
        raise SttError(
            "STT_PROVIDER=sarvam but SARVAM_API_KEY is not set.\n"
            "  Add SARVAM_API_KEY=your_key to .env (https://dashboard.sarvam.ai)."
        )

    model = os.getenv("SARVAM_MODEL", "saaras:v4").strip()
    form = {"model": model, "language_code": os.getenv("SARVAM_LANGUAGE", "en-IN").strip()}

    # keyterms is a saaras:v4-only feature; older models reject it.
    terms = _keyterms(hint)
    if terms and model.startswith("saaras:v4"):
        form["keyterms"] = json.dumps(terms)

    try:
        r = httpx.post(SARVAM_STT_URL, headers={"api-subscription-key": key},
                       files={"file": (filename, data, mime)}, data=form, timeout=90)
    except httpx.TimeoutException as exc:
        raise SttError("Sarvam API timed out. Check the network and retry.") from exc
    except httpx.RequestError as exc:
        raise SttError(f"Could not reach api.sarvam.ai: {exc}") from exc

    if r.status_code != 200:
        raise SttError(_describe_sarvam_error(r.status_code, r.text))
    try:
        # An empty transcript here is a real result (silence), not an error.
        j = r.json()
        return (j.get("transcript") or "").strip(), j.get("language_code") or form["language_code"]
    except ValueError as exc:
        raise SttError(f"Sarvam returned HTTP 200 with a non-JSON body: {r.text[:300]}") from exc


# --- entry points -------------------------------------------------------------

def transcribe_file(data: bytes, hint: str = "", filename: str = "audio.wav") -> str:
    """Transcribe an uploaded recording (browser kiosk or the PC client)."""
    return transcribe_file_detect(data, hint, filename)[0]


def transcribe_file_detect(data: bytes, hint: str = "", filename: str = "audio.wav") -> tuple[str, str | None]:
    """transcribe_file, plus the language heard ("kn-IN"...; "en" for Whisper)."""
    if provider() == "sarvam":
        ext = (filename.rsplit(".", 1)[-1] if "." in filename else "wav").lower()
        mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
                "flac": "audio/flac", "ogg": "audio/ogg", "webm": "audio/webm"}.get(ext, "audio/wav")
        return _sarvam_transcribe(filename, data, mime, hint)
    return _run(io.BytesIO(data), hint), "en"


def prepare_pcm(pcm: bytes, rate: int) -> np.ndarray:
    """ESP32 ADC samples (int16 LE) -> clean 16 kHz float32 for Whisper."""
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    x -= x.mean()
    x = np.append(x[0], x[1:] - 0.95 * x[:-1])                    # pre-emphasis / DC & rumble removal
    peak = np.percentile(np.abs(x), 99.5) or 1.0
    x = np.clip(x / (peak * 1.2), -1, 1)                           # normalise (ADC mic is very quiet)
    if rate != 16000:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 16000 / rate)), np.arange(len(x)), x)
    return x.astype(np.float32)


def pcm_to_wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    """Wrap float32 [-1, 1] mono samples as a 16-bit WAV in memory."""
    pcm16 = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


def transcribe_pcm(pcm: bytes, rate: int, hint: str = "") -> str:
    """Transcribe raw int16 mono PCM straight off the ESP32 ADC.

    prepare_pcm() runs either way: its DC removal, pre-emphasis and
    normalisation are what make that very quiet ADC microphone intelligible,
    and Sarvam gets the cleaned audio, not the raw buffer. Sarvam takes a file
    rather than a bare PCM buffer, so the cleaned result is wrapped as a WAV
    (prepare_pcm has already resampled it to 16 kHz).
    """
    audio = prepare_pcm(pcm, rate)
    if provider() == "sarvam":
        return _sarvam_transcribe("esp32.wav", pcm_to_wav_bytes(audio, 16000), "audio/wav", hint)[0]
    return _run(audio, hint)


def save_wav(path, pcm: bytes, rate: int):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)


async def synth_mp3(text: str, voice: str) -> bytes:
    import edge_tts
    buf = bytearray()
    async for ch in edge_tts.Communicate(text, voice).stream():
        if ch["type"] == "audio":
            buf += ch["data"]
    if not buf:
        raise RuntimeError("TTS returned no audio")
    return bytes(buf)


def mp3_to_u8(mp3: bytes, rate: int = 8000) -> bytes:
    """MP3 -> unsigned 8-bit mono PCM (what the ESP32 DAC plays). Uses PyAV (installed with faster-whisper)."""
    import av
    rs = av.AudioResampler(format="s16", layout="mono", rate=rate)
    parts = []
    with av.open(io.BytesIO(mp3)) as c:
        for fr in c.decode(audio=0):
            parts += [f.to_ndarray().reshape(-1) for f in rs.resample(fr)]
    parts += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
    x = np.concatenate(parts).astype(np.float32)
    x = x / (np.abs(x).max() or 1) * 0.9
    return np.clip(x * 127 + 128, 0, 255).astype(np.uint8).tobytes()


def mp3_to_pcm16(mp3: bytes, rate: int = 16000) -> bytes:
    """MP3 -> signed 16-bit little-endian mono PCM, for an I2S amplifier such as
    the MAX98357A. Twice the sample rate and 256x the resolution of the 8-bit
    DAC format above, which stays as it is for the DAC kiosk."""
    import av
    rs = av.AudioResampler(format="s16", layout="mono", rate=rate)
    parts = []
    with av.open(io.BytesIO(mp3)) as c:
        for fr in c.decode(audio=0):
            parts += [f.to_ndarray().reshape(-1) for f in rs.resample(fr)]
    parts += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
    x = np.concatenate(parts).astype(np.float32)
    x = x / (np.abs(x).max() or 1)                          # peak at full scale
    # Loudness. Peak-normalised speech is still quiet on average (its RMS sits
    # near -18 dBFS), and on a small speaker it is average level that sounds
    # loud. A soft-knee tanh compressor lifts the quiet parts by up to ~12 dB
    # while the peaks stay rounded under full scale instead of clipping.
    rms = float(np.sqrt(np.mean(x * x))) or 1e-6
    drive = float(np.clip(0.25 / rms, 1.0, 4.0))
    x = np.tanh(drive * x) / np.tanh(drive)
    return np.clip(x * 0.97 * 32767, -32768, 32767).astype("<i2").tobytes()


def for_speech(t: str) -> str:
    t = re.sub(r"Rs\.?\s*", "rupees ", t)
    t = re.sub(r"\bLPA\b", "lakhs per annum", t)
    return t.replace("&", " and ").replace("%", " percent")


def ascii_clean(t: str) -> str:
    for a, b in {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u20b9": "Rs. "}.items():
        t = t.replace(a, b)
    return t.encode("ascii", "ignore").decode()

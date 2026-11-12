"""Smart Krishi server: agricultural RAG + Gemma Q&A for the ESP32 voice kiosk.

Same pipeline as Campus Mithra's server/app.py, with an agricultural knowledge
base, prompt and fallbacks, and live readings from the UNO Q farm sensor device.

Reused unchanged from Campus Mithra: rag.py (hybrid embeddings + TF-IDF
retrieval), llm.py (Gemma via Gemini API or Ollama), grounding.py (every answer
sentence and every number must be backed by the retrieved text), speech.py
(Sarvam / Whisper STT, edge-tts, PCM for the MAX98357A) and language.py
(Kannada <-> English via Sarvam).

Endpoints (all under /api/krishi):
    GET  /health                 status, chunks, model
    POST /chat                   {"question", "session", "language", "style"} -> answer
    POST /transcribe             recording -> text (used by krishi_client.py)
    POST /voice                  recording -> answer, in one call
    POST /understand             typed Kannada/English -> English + display text
    GET  /audio/{id}.{mp3|s16|u8}  the spoken answer
    POST /sensors                reading from the UNO Q sensor device (device token)
    GET  /sensors/latest         newest reading, validity, online/stale/offline
"""
import asyncio, json, logging, os, re, uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

from fastapi import APIRouter, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from typing import Annotated
from pydantic import BaseModel, Field, model_validator

import hmac
import fertilizer, language, llm, sensors, speech
from grounding import grounded_sources
from prompts import PROMPT
from rag import Retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
log = logging.getLogger("krishi")

KB_DIR = Path(os.getenv("KRISHI_KB_DIR", ROOT / "kb"))
META = json.loads((KB_DIR / "meta.json").read_text(encoding="utf-8"))
VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
TTS_ON = os.getenv("TTS_ENABLED", "1") == "1"
PLAY_RATE = int(os.getenv("ESP_PLAY_RATE", "8000"))
I2S_RATE = int(os.getenv("ESP_I2S_RATE", "16000"))       # must equal PLAY_RATE in firmware config.h

DONT_KNOW = ("I don't have enough verified information to answer that. "
             "Please check with your local agriculture officer or Krishi Vigyan Kendra.")
BROKEN = "Sorry, I couldn't put that answer together just now. Please ask me again."
UNHEARD = "Sorry, I couldn't hear that clearly. Please try again and speak close to the microphone."
DEAF = "Sorry, my speech service is not working right now. Please try again in a little while."
NO_SENSOR_DATA = "I have not received any readings from the farm sensor device yet, so I cannot tell you the farm conditions."
SENSOR_SOURCE = "live_sensors"     # how the sensor section is named in the prompt and in sources
GREET = re.compile(r"^\W*(hi|hello|hey|namaste|namaskara|namaskar|good (morning|afternoon|evening))\b[\s\W]*(krishi|there)?\W*$", re.I)
THANKS = re.compile(r"^\W*(thanks|thank you|thank you very much|ok thanks|dhanyavada|bye|goodbye)\W*$", re.I)

RET: Retriever | None = None
AUDIO: "OrderedDict[str, dict]" = OrderedDict()
LAST_Q: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global RET
    RET = await asyncio.to_thread(
        Retriever, KB_DIR, os.getenv("OLLAMA_URL", "http://localhost:11434"), os.getenv("EMBED_MODEL", ""),
        ROOT / "server" / ".cache", float(os.getenv("EMB_MIN_SCORE", "0.40")), float(os.getenv("TFIDF_MIN_SCORE", "0.08")))
    log.info("Agricultural knowledge base: %d chunks from %s", len(RET.chunks), KB_DIR)
    log.info("Speech-to-text provider: %s | sensor ingestion %s", speech.provider(),
             "on" if os.getenv("KRISHI_SENSOR_TOKEN", "").strip() else "OFF (set KRISHI_SENSOR_TOKEN)")
    warm = asyncio.create_task(asyncio.to_thread(speech.warmup))
    try:
        yield
    finally:
        warm.cancel()


app = FastAPI(title="Smart Krishi", lifespan=lifespan)
api = APIRouter(prefix="/api/krishi")


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*#_`>]", "", t)).strip()


def spoken_source(name: str) -> str:
    """'03_tomato_cultivation.md' -> 'tomato cultivation'."""
    return re.sub(r"^\d+[_\-\s]*", "", name.rsplit(".", 1)[0]).replace("_", " ").replace("-", " ").strip()


def for_speech(t: str) -> str:
    t = re.sub(r"\bkg\s*/\s*ha\b", "kilograms per hectare", t, flags=re.I)
    t = re.sub(r"\bt\s*/\s*ha\b", "tonnes per hectare", t, flags=re.I)
    t = re.sub(r"\bNPK\b", "N P K", t)
    return speech.for_speech(t)


def kiosk_loud(pcm: bytes) -> bytes:
    """Louder speech for the kiosk speaker without harsh clipping.

    The firmware multiplies every sample by SPEAKER_GAIN (2) and hard-clips, so
    full-scale audio from the server is clipped on its loudest half. Here a soft
    (tanh) limiter with KIOSK_LOUDNESS drive raises the average level and lands
    the peaks at half scale, which the firmware's 2x brings to full scale.
    Measured on edge-tts speech: drive 6 is about +3 dB louder than before with
    fewer clipped samples. 0 sends the audio unchanged (Campus Mithra's level).
    """
    import numpy as np
    drive = float(os.getenv("KIOSK_LOUDNESS", "6"))
    if drive <= 0 or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    y = np.tanh(drive * x) / np.tanh(drive) * 0.5
    return np.clip(y * 32767, -32768, 32767).astype("<i2").tobytes()


def remember_audio(text: str, voice: str | None = None) -> str:
    aid = uuid.uuid4().hex[:12]
    AUDIO[aid] = {"text": text, **({"voice": voice} if voice else {})}
    while len(AUDIO) > 60:
        AUDIO.popitem(last=False)
    return aid


def pack(q, a, in_scope, sources=(), via="gemma", sensor=None):
    """Bundle a reply; the spoken version names its source at the end."""
    sources = list(sources)
    speak = a
    if sources and os.getenv("SPEAK_SOURCES", "1") == "1":
        speak += " This is from the " + " and ".join(spoken_source(s) for s in sources[:2]) + " information."
    aid = remember_audio(speak)
    return {"question": q, "answer": a, "in_scope": in_scope, "sources": sources, "via": via,
            "sensor": sensor, "audio_id": aid if TTS_ON else None}


_STOP = set("""a an the is are was were be of to in on at for from by with and or what which who
whom how when where why do does did can could will would i me my we our you your it its this that
there here about tell please much many any some have has had get give should my crop crops plant plants""".split())


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def extractive_answer(question: str, hits: list[dict]) -> tuple[str, str] | None:
    """Verbatim lines from the knowledge base, used only when Gemma is unreachable
    (same fallback as Campus Mithra)."""
    want = _words(question)
    if not want:
        return None
    best = []
    for rank, h in enumerate(hits[:2]):
        for line in h["text"].splitlines():
            line = re.sub(r"^[-*\d.)\s]+", "", line.strip()).replace("**", "")
            if not line or line.startswith("|"):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                score = len(want & _words(sentence))
                if score:
                    best.append((score, -rank, sentence.strip(), h["source"]))
    if not best:
        return None
    best.sort(reverse=True)
    top = best[0][0]
    picked = [b for b in best if b[0] >= max(1, top - 1)][:2]
    text = " ".join(p[2].rstrip(".") + "." for p in picked)
    if len(text) > 320:
        text = text[:317].rsplit(" ", 1)[0] + "..."
    return "Here is what I found. " + text, picked[0][3]


async def answer_question(q: str, sid: str = "web") -> dict:
    q = (q or "").strip()
    if not q:
        return pack(q, UNHEARD, False)
    if GREET.match(q):
        return pack(q, META["greeting"], True)
    if THANKS.match(q):
        return pack(q, "You're welcome! Ask me anything else about your crops.", True)

    prev = LAST_Q.get(sid)
    rq = f"{prev} {q}" if prev and len(q.split()) <= 5 else q          # short follow-ups reuse the last topic
    hits, relevant = await asyncio.to_thread(RET.search, rq)
    hits = list(hits)

    # Farm-condition questions also see the latest sensor reading, in its own
    # prompt section, kept apart from the knowledge documents.
    sensor, sensor_hit = None, None
    if sensors.SENSOR_WORDS.search(q):
        rec = sensors.latest()
        if rec:
            sensor = {"device_id": rec["device_id"], "status": sensors.status(rec),
                      "received_at": rec["received_at"], "is_test_data": bool(rec.get("is_test_data"))}
            sensor_hit = {"source": SENSOR_SOURCE, "title": "Live farm sensor readings", "text": sensors.as_context(rec)}
            relevant = True
        elif not relevant or sensors.LIVE_INTENT.search(q):
            return pack(q, NO_SENSOR_DATA, False, via="no-sensor-data")
    if not relevant:
        return pack(q, DONT_KNOW, False, via="unknown", sensor=sensor)

    ctx = "\n\n".join(f"[{h['source']}] {h['title']}\n{h['text']}" for h in hits)
    live = sensor_hit["text"] if sensor_hit else "No live sensor reading is available for this question."
    try:
        raw = await llm.generate(PROMPT.format(sensors=live, context=ctx, question=q))
    except Exception as e:
        log.error("LLM error: %s", e)
        found = extractive_answer(q, hits)
        if found:
            log.info("answered from the knowledge base directly (Gemma unavailable)")
            return pack(q, found[0], True, [found[1]], via="kb-direct", sensor=sensor)
        return pack(q, BROKEN, False, via="error", sensor=sensor)
    if "NOT_IN_KB" in raw.upper():
        return pack(q, DONT_KNOW, False, via="unknown", sensor=sensor)

    answer, cited = llm.split_sources(raw)
    if sensor_hit and SENSOR_SOURCE in raw.rsplit("\n", 1)[-1]:
        cited.insert(0, SENSOR_SOURCE)
    sources = grounded_sources(answer, hits + ([sensor_hit] if sensor_hit else []))
    if sources is None:
        # Catches invented quantities and readings: any number that is not in
        # the documents or the sensor section fails.
        log.info("rejected ungrounded answer: %r", answer[:200])
        return pack(q, DONT_KNOW, False, via="ungrounded", sensor=sensor)
    sources = [s for s in cited if s in sources] or sources
    LAST_Q[sid] = q
    log.info("answered from %s", ", ".join(sources))
    return pack(q, clean(answer), True, sources, sensor=sensor)


async def localize(r: dict, lang: str, style: str = "mixed") -> dict:
    """The English reply in the farmer's language (Kannada), with a Latin-script
    copy for the TFT. A failed translation leaves the reply in English."""
    r = {**r, "language": "en", "answer_en": r["answer"], "answer_display": r["answer"]}
    if lang == "en" or lang not in language.enabled():
        return r
    try:
        native, roman = await language.from_english(r["answer"], lang, style)
    except Exception as e:
        log.warning("could not translate the answer to %s (%s); replying in English", lang, e)
        return r
    r.update(language=lang, answer=native, answer_display=roman)
    if r.get("audio_id") in AUDIO:
        suffix = language.spoken_suffix(lang, r["sources"]) if os.getenv("SPEAK_SOURCES", "1") == "1" else ""
        AUDIO[r["audio_id"]] = {"text": native + suffix, "voice": language.voice(lang)}
    return r


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class Chat(BaseModel):
    question: str = Field(max_length=1000)
    session: str = "web"
    language: Literal["en", "kn", "hi"] = "en"
    style: Literal["mixed", "native"] = "mixed"


class Understand(BaseModel):
    text: str = Field(max_length=1000)


class SensorReading(BaseModel):
    """One reading from the UNO Q sensor device. null = not measured / invalid."""
    model_config = {"extra": "forbid"}
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    temperature_c: float | None = Field(default=None, ge=-40, le=85)
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    soil_moisture_raw: int | None = Field(default=None, ge=0, le=65535)
    soil_moisture_percent: float | None = Field(default=None, ge=0, le=100)
    soil_sensor_valid: bool = False
    mq135_raw: int | None = Field(default=None, ge=0, le=65535)
    mq135_valid: bool = True
    faults: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=12)
    crop: str | None = Field(default=None, max_length=40)
    seq: int | None = Field(default=None, ge=0)
    uptime_s: int | None = Field(default=None, ge=0)
    is_test_data: bool = False

    @model_validator(mode="after")
    def _no_percent_without_calibration(self):
        # A percentage only means something from a calibrated, valid sensor.
        if not self.soil_sensor_valid:
            self.soil_moisture_percent = None
        return self


@api.post("/chat")
async def chat(body: Chat):
    return await localize(await answer_question(body.question, body.session), body.language, body.style)


@api.post("/understand")
async def understand(body: Understand):
    return await language.understand(body.text)


async def _transcribe(file: UploadFile):
    return await asyncio.to_thread(speech.transcribe_file_detect, await file.read(), META["stt_hint"],
                                   file.filename or "audio.wav")


@api.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Speech to text only, so the kiosk can show the question while Gemma works."""
    try:
        text, heard_lang = await _transcribe(file)
    except speech.SttError as e:
        log.error("STT error: %s", e)
        return {"ok": False, "text": "", "error": str(e).splitlines()[0], "reply": DEAF}
    log.info("Heard (%s): %r", heard_lang, text)
    q = await language.understand(text, heard_lang) if text else {}
    return {"ok": True, "text": text, "reply": "" if text else UNHEARD,
            "language": q.get("language", "en"), "english": q.get("english", text),
            "display": q.get("display", text), "style": q.get("style", "mixed")}


@api.post("/voice")
async def voice(file: UploadFile = File(...), session: str = "voice"):
    """Recording in, answer out (transcript, answer, sources, audio_id)."""
    try:
        text, heard_lang = await _transcribe(file)
    except speech.SttError as e:
        log.error("STT error: %s", e)
        return {**pack("", DEAF, False, via="stt-error"), "transcript": ""}
    log.info("Heard (%s): %r", heard_lang, text)
    if not text:
        return {**pack("", UNHEARD, False), "transcript": ""}
    q = await language.understand(text, heard_lang)
    r = await localize(await answer_question(q["english"], session), q["language"], q["style"])
    return {**r, "transcript": text, "question_display": q.get("display", text)}


@api.get("/audio/{aid}.{ext}")
async def audio(aid: str, ext: str):
    item = AUDIO.get(aid)
    if not item or ext not in ("mp3", "u8", "s16"):
        return Response(status_code=404)
    try:
        if "mp3" not in item:
            item["mp3"] = await speech.synth_mp3(for_speech(item["text"]), item.get("voice", VOICE))
        if ext == "mp3":
            return Response(item["mp3"], media_type="audio/mpeg")
        if ext == "s16":                     # 16-bit for the MAX98357A kiosk
            if "s16" not in item:
                pcm = await asyncio.to_thread(speech.mp3_to_pcm16, item["mp3"], I2S_RATE)
                item["s16"] = kiosk_loud(pcm)
            return Response(item["s16"], media_type="application/octet-stream")
        if "u8" not in item:
            item["u8"] = await asyncio.to_thread(speech.mp3_to_u8, item["mp3"], PLAY_RATE)
        return Response(item["u8"], media_type="application/octet-stream")
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return Response(status_code=503)


def _sensor_token_ok(authorization: str | None, x_device_token: str | None) -> bool:
    expected = os.getenv("KRISHI_SENSOR_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Sensor ingestion is off: set KRISHI_SENSOR_TOKEN in .env.")
    given = x_device_token or ""
    if not given and authorization and authorization.lower().startswith("bearer "):
        given = authorization[7:]
    return hmac.compare_digest(given.strip().encode(), expected.encode())


@api.post("/sensors")
async def sensors_ingest(body: SensorReading, authorization: str | None = Header(default=None),
                         x_device_token: str | None = Header(default=None)):
    """A reading from the Arduino UNO Q sensor device (Authorization: Bearer <KRISHI_SENSOR_TOKEN>)."""
    if not _sensor_token_ok(authorization, x_device_token):
        raise HTTPException(status_code=401, detail="Missing or wrong device token.")
    rec = sensors.save(body.model_dump())
    log.info("sensor %s seq=%s: T=%s RH=%s soil_raw=%s valid=%s mq135_raw=%s faults=%s", rec["device_id"],
             rec["seq"], rec["temperature_c"], rec["humidity_percent"], rec["soil_moisture_raw"],
             rec["soil_sensor_valid"], rec["mq135_raw"], ",".join(rec["faults"]) or "-")
    return {"ok": True, "received_at": rec["received_at"]}


@api.get("/sensors/latest")
async def sensors_latest(device_id: str | None = None):
    """Latest reading, server time, per-measurement validity and online/stale/offline status."""
    return sensors.summary(device_id)


class FertilizerRequest(BaseModel):
    model_config = {"extra": "forbid"}
    crop: str = Field(max_length=20)
    area_acres: float = Field(gt=0, le=100)
    n: Literal["low", "medium", "high", "unknown"] = "unknown"
    p: Literal["low", "medium", "high", "unknown"] = "unknown"
    k: Literal["low", "medium", "high", "unknown"] = "unknown"


@api.get("/fertilizer/crops")
async def fertilizer_crops():
    """Crops the kiosk's crop screen offers (one source of truth: fertilizer.CROPS)."""
    return {"crops": [{"id": cid, "name": c.name, "note": c.note} for cid, c in fertilizer.CROPS.items()],
            "areas_acres": fertilizer.AREAS, "ratings": list(fertilizer.RATING_FACTOR)}


@api.post("/fertilizer")
async def fertilizer_recommend(body: FertilizerRequest):
    """Official crop dose x Soil Health Card rating -> urea/DAP/MOP per stage,
    with the live sensor conditions; plus the pages the kiosk TFT shows."""
    if body.crop not in fertilizer.CROPS:
        raise HTTPException(status_code=404, detail=f"Unknown crop '{body.crop}'.")
    rec = sensors.latest()
    out = fertilizer.recommend(body.crop, body.area_acres, body.n, body.p, body.k, rec, sensors.status(rec))
    title, pages = fertilizer.screen_pages(out)
    log.info("fertilizer: %s %.2f acre N=%s P=%s K=%s -> %s", body.crop, body.area_acres, body.n, body.p, body.k, out["totals"])
    return {**out, "screen": {"title": title, "pages": [[{"style": s, "text": t} for s, t in pg] for pg in pages]}}


@api.get("/health")
async def health():
    backend = os.getenv("LLM_BACKEND", "ollama")
    model = (os.getenv("GEMINI_MODEL", "gemma-3-27b-it") if backend == "gemini"
             else os.getenv("GEMMA_MODEL", "gemma3:4b"))
    return {"ok": True, "app": "Smart Krishi", "college": META["name"], "kb": str(KB_DIR.name),
            "chunks": len(RET.chunks), "embeddings": RET.E is not None, "backend": backend, "model": model,
            "stt": speech.provider(), "embed_model": RET.model or None,
            "languages": language.enabled(), "sensor_ingestion": bool(os.getenv("KRISHI_SENSOR_TOKEN", "").strip()),
            "sensor_status": sensors.status(sensors.latest())}


app.include_router(api)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8001")))

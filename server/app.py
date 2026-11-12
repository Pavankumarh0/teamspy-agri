"""Smart Krishi server: agricultural RAG + Gemma Q&A for the ESP32 voice kiosk.

Same pipeline as Campus Mithra's server/app.py, with an agricultural knowledge
base, prompt and fallbacks, and a soil-sensor endpoint for the second ESP32.

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
    POST /soil-data              reading from the soil sensor ESP32
    GET  /soil-data/latest       newest reading (real, else mock if SOIL_MOCK=1)
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
from pydantic import BaseModel, Field

import language, llm, soil, speech
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
    log.info("Speech-to-text provider: %s | soil mock readings: %s", speech.provider(), soil.mock_enabled())
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

    # Soil questions also see the latest sensor reading (real, else a labelled mock).
    sensor = None
    if soil.SOIL_WORDS.search(q):
        rec = soil.latest()
        if rec:
            sensor = {k: rec.get(k) for k in ("device_id", "source", "received_at", "soil_moisture",
                                               "crop", "temperature", "humidity")}
            hits.insert(0, soil.as_context(rec))
            relevant = True
    if not relevant:
        return pack(q, DONT_KNOW, False, via="unknown", sensor=sensor)

    ctx = "\n\n".join(f"[{h['source']}] {h['title']}\n{h['text']}" for h in hits)
    try:
        raw = await llm.generate(PROMPT.format(context=ctx, question=q))
    except Exception as e:
        log.error("LLM error: %s", e)
        found = extractive_answer(q, [h for h in hits if h["source"] != "soil_sensor.md"])
        if found:
            log.info("answered from the knowledge base directly (Gemma unavailable)")
            return pack(q, found[0], True, [found[1]], via="kb-direct", sensor=sensor)
        return pack(q, BROKEN, False, via="error", sensor=sensor)
    if "NOT_IN_KB" in raw.upper():
        return pack(q, DONT_KNOW, False, via="unknown", sensor=sensor)

    answer, cited = llm.split_sources(raw)
    sources = grounded_sources(answer, hits)
    if sources is None:
        # Catches invented quantities: any number not in the retrieved text fails.
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


class SoilReading(BaseModel):
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    soil_moisture: float = Field(ge=0, le=100)
    crop: str | None = Field(default=None, max_length=40)
    temperature: float | None = Field(default=None, ge=-20, le=70)
    humidity: float | None = Field(default=None, ge=0, le=100)


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
                item["s16"] = await asyncio.to_thread(speech.mp3_to_pcm16, item["mp3"], I2S_RATE)
            return Response(item["s16"], media_type="application/octet-stream")
        if "u8" not in item:
            item["u8"] = await asyncio.to_thread(speech.mp3_to_u8, item["mp3"], PLAY_RATE)
        return Response(item["u8"], media_type="application/octet-stream")
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return Response(status_code=503)


@api.post("/soil-data")
async def soil_data(body: SoilReading, x_device_key: str | None = Header(default=None)):
    """A real reading from the soil sensor ESP32. If KRISHI_SENSOR_KEY is set,
    the node must send it in the X-Device-Key header."""
    key = os.getenv("KRISHI_SENSOR_KEY", "").strip()
    if key and x_device_key != key:
        raise HTTPException(status_code=401, detail="Missing or wrong X-Device-Key.")
    rec = soil.save(body.model_dump())
    log.info("soil reading from %s: moisture %s", rec["device_id"], rec["soil_moisture"])
    return {"ok": True, "reading": rec}


@api.get("/soil-data/latest")
async def soil_latest(device_id: str | None = None):
    rec = soil.latest(device_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No soil reading yet (SOIL_MOCK=0).")
    return {"reading": rec, "is_mock": rec.get("source") == "mock",
            "age_minutes": round(soil.age_minutes(rec), 1)}


@api.get("/health")
async def health():
    backend = os.getenv("LLM_BACKEND", "ollama")
    model = (os.getenv("GEMINI_MODEL", "gemma-3-27b-it") if backend == "gemini"
             else os.getenv("GEMMA_MODEL", "gemma3:4b"))
    return {"ok": True, "app": "Smart Krishi", "college": META["name"], "kb": str(KB_DIR.name),
            "chunks": len(RET.chunks), "embeddings": RET.E is not None, "backend": backend, "model": model,
            "stt": speech.provider(), "embed_model": RET.model or None,
            "languages": language.enabled(), "soil_mock": soil.mock_enabled()}


app.include_router(api)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8001")))

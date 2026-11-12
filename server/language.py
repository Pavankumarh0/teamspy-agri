"""Kannada, Hindi and English at the kiosk, including Kanglish and Hinglish.

The answering pipeline (retrieval, Gemma, the grounding check, sources) stays
English: the knowledge base and the campus records are English, and grounding
compares the answer with them word for word. This module wraps it:

    question (any of the three, mixed or not)
        -> understand(): detected language, English for the pipeline, and a
           Latin-script copy for the kiosk TFT (its fonts are ASCII only)
    English answer
        -> localize(): the answer in the visitor's language, code-mixed the way
           people on campus speak (English place names and words stay English),
           plus its Latin-script copy for the TFT

Translation is Sarvam's (api.sarvam.ai, the same key as speech-to-text). When
it fails, the visitor gets the English answer rather than no answer.
"""
import asyncio
import logging
import os
import re
from collections import OrderedDict

import httpx

log = logging.getLogger("language")

SARVAM = "https://api.sarvam.ai"

# Reply languages: code -> Sarvam language code and edge-tts voice.
LANGUAGES = {
    "en": {"code": "en-IN", "voice": lambda: os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")},
    "kn": {"code": "kn-IN", "voice": lambda: os.getenv("TTS_VOICE_KN", "kn-IN-SapnaNeural")},
    "hi": {"code": "hi-IN", "voice": lambda: os.getenv("TTS_VOICE_HI", "hi-IN-SwaraNeural")},
}

# Spoken after an answer: "This is from the hostel information." The source
# name (hostel, canteen and food...) stays English, as people say it.
SOURCE_SUFFIX = {
    "en": " This is from the {src} information.",
    "kn": " ಈ ಮಾಹಿತಿ {src} ವಿಭಾಗದಿಂದ ಬಂದಿದೆ.",
    "hi": " यह जानकारी {src} से ली गई है।",
}


def enabled() -> list[str]:
    """KIOSK_LANGUAGES=en,kn,hi (the default); English is always on."""
    raw = os.getenv("KIOSK_LANGUAGES", "en,kn,hi")
    langs = [x.strip() for x in raw.split(",") if x.strip() in LANGUAGES]
    return ["en"] + [x for x in langs if x != "en"]


def reply_language(sarvam_code: str | None) -> str:
    """'kn-IN' -> 'kn'. Anything not enabled (Tamil, an unknown result...) is
    answered in English, though the question is still translated."""
    short = (sarvam_code or "").split("-")[0].lower()
    return short if short in enabled() else "en"


def voice(lang: str) -> str:
    return LANGUAGES.get(lang, LANGUAGES["en"])["voice"]()


def _key() -> str:
    return os.getenv("SARVAM_API_KEY", "").strip()


async def _post(c: httpx.AsyncClient, path: str, body: dict) -> dict:
    r = await c.post(f"{SARVAM}/{path}", headers={"api-subscription-key": _key()}, json=body)
    r.raise_for_status()
    return r.json()


# How a reply is phrased, matching how the visitor asked: "mixed" keeps English
# words (Kanglish, Hinglish; mayura:v1 code-mixed), "native" is proper Kannada
# or Hindi (sarvam-translate:v1; mayura's colloquial modes keep most English
# words, and its formal mode mistranslated "step-free" as "footprints").
NATIVE_MODEL = "sarvam-translate:v1"


async def _translate(c, text: str, source: str, target: str, roman: bool = False,
                     model: str = "mayura:v1") -> tuple[str, str]:
    """(translated text, detected source code). mayura:v1 is the model with
    source auto-detection, code-mixed mode and Roman output."""
    body = {"input": text[:1000], "source_language_code": source, "target_language_code": target,
            "model": model, "numerals_format": "international"}
    if model == "mayura:v1" and target != "en-IN":
        body["mode"] = "code-mixed"
    if roman:
        body["output_script"] = "roman"
    j = await _post(c, "translate", body)
    return (j.get("translated_text") or "").strip(), j.get("source_language_code") or source


async def _roman(c, text: str, source: str) -> str:
    """Native script -> Latin letters, for the TFT."""
    j = await _post(c, "transliterate", {"input": text[:1000], "source_language_code": source,
                                         "target_language_code": "en-IN", "numerals_format": "international"})
    return (j.get("transliterated_text") or "").strip()


# Kannada (U+0C80) and Devanagari (U+0900) share the ISCII layout, so one table,
# by offset within the block, covers both. Plain ASCII spellings, as people
# type them, long vowels single: "Granthalayavu", "paidal duri".
_VOWELS = {0x05: "a", 0x06: "a", 0x07: "i", 0x08: "i", 0x09: "u", 0x0A: "u", 0x0B: "ru", 0x0E: "e",
           0x0F: "e", 0x10: "ai", 0x12: "o", 0x13: "o", 0x14: "au"}
_SIGNS = {0x3E: "a", 0x3F: "i", 0x40: "i", 0x41: "u", 0x42: "u", 0x43: "ru", 0x46: "e", 0x47: "e",
          0x48: "ai", 0x4A: "o", 0x4B: "o", 0x4C: "au"}
_CONSONANTS = dict(zip(range(0x15, 0x3A), (
    "k kh g gh ng ch chh j jh ny t th d dh n t th d dh n n p ph b bh m y r r l l l v sh sh s h").split()))
_VIRAMA, _NUKTA = 0x4D, 0x3C


def romanize(text: str) -> str:
    """Kannada or Hindi script -> ASCII letters, letter by letter, for the TFT.
    (Sarvam's transliterate rewrote whole Kannada words into Hindi.)"""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in "।॥":                 # danda -> full stop
            out.append(".")
            i += 1
            continue
        block = 0x0900 if 0x0900 <= ord(ch) <= 0x097F else 0x0C80 if 0x0C80 <= ord(ch) <= 0x0CFF else None
        if block is None:
            out.append(ch)
            i += 1
            continue
        off = ord(ch) - block
        if off in _CONSONANTS:
            out.append(_CONSONANTS[off])
            j = i + 1
            if j < len(text) and ord(text[j]) - block == _NUKTA:
                j += 1
            nxt = ord(text[j]) - block if j < len(text) and block <= ord(text[j]) <= block + 0x7F else None
            if nxt in _SIGNS:
                out.append(_SIGNS[nxt]); j += 1
            elif nxt == _VIRAMA:
                j += 1
            elif not (block == 0x0900 and nxt is None):
                out.append("a")              # inherent vowel; Hindi drops it at the end of a word
            i = j
            continue
        if off in _VOWELS:
            out.append(_VOWELS[off])
        elif off in (0x01, 0x02):            # chandrabindu, anusvara: the nasal of what follows
            nxt = _CONSONANTS.get(ord(text[i + 1]) - block, "") if i + 1 < len(text) else ""
            out.append("m" if nxt[:1] in ("p", "b", "m") or (not nxt and block == 0x0C80) else "n")
        elif off == 0x03:
            out.append("h")
        elif 0x66 <= off <= 0x6F:
            out.append(str(off - 0x66))
        i += 1
    s = "".join(out)
    # sentences start with a capital, as on the rest of the screen
    return re.sub(r"(^|[.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)


def _ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


_FUNCTION_WORDS = set("a an the is are am to of in on at for and or me my i you it this that what where when how which give".split())


def question_style(display: str, english: str) -> str:
    """'mixed' when the visitor used English words (the Latin-script question
    shares a content word with its English translation: "Boys hostel-ge hoguva
    map kodu" / "Give me the map to the boys' hostel"), else 'native'
    ("Granthalaya ellide?" / "Where is the library?")."""
    words = lambda t: {w.rstrip("s") for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 2} - _FUNCTION_WORDS
    return "mixed" if words(display) & words(english) else "native"


async def understand(text: str, detected: str | None = None) -> dict:
    """What the visitor asked, in the forms the kiosk needs.

    detected is speech-to-text's language code; None for typed text, where
    the translator detects it (it understands romanised Hindi and Kannada too).
    Returns {"language", "english", "display", "original", "style"}; style
    says whether to answer code-mixed or in plain Kannada/Hindi (question_style).
    """
    text = (text or "").strip()
    out = {"language": "en", "english": text, "display": text, "original": text, "style": "mixed"}
    if not text or not _key():
        return out
    lang_code = detected if detected and detected != "unknown" else None
    if lang_code and lang_code.startswith("en"):
        return out                                    # English: no extra round trip
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if lang_code:
                english_job = _translate(c, text, lang_code, "en-IN")
                roman_job = _roman(c, text, lang_code) if not _ascii(text) else asyncio.sleep(0, text)
                (english, _), display = await asyncio.gather(english_job, roman_job)
            else:
                english, lang_code = await _translate(c, text, "auto", "en-IN")
                display = text if _ascii(text) or lang_code.startswith("en") else await _roman(c, text, lang_code)
    except Exception as e:
        log.warning("could not translate the question (%s); answering it as English", e)
        return out
    out.update(language=reply_language(lang_code), english=english or text, display=display or text)
    out["style"] = question_style(out["display"], out["english"])
    return out


_cache: "OrderedDict[tuple[str, str, str], tuple[str, str]]" = OrderedDict()


async def from_english(text: str, lang: str, style: str = "mixed") -> tuple[str, str]:
    """(native, roman) translation of an English answer, in the style the
    question was asked in. Fixed replies such as "I don't know about that."
    repeat, so results are cached."""
    if lang == "en" or not text or not _key():
        return text, text
    key = (lang, style, text)
    if key in _cache:
        return _cache[key]
    target = LANGUAGES[lang]["code"]
    async with httpx.AsyncClient(timeout=15) as c:
        if style == "native":
            native, _ = await _translate(c, text, "en-IN", target, model=NATIVE_MODEL)
            roman = romanize(native)       # letter for letter what is spoken
        else:
            (native, _), (roman, _) = await asyncio.gather(
                _translate(c, text, "en-IN", target), _translate(c, text, "en-IN", target, roman=True))
    result = (native or text, roman or text)
    _cache[key] = result
    while len(_cache) > 200:
        _cache.popitem(last=False)
    return result


def spoken_suffix(lang: str, sources: list[str]) -> str:
    if not sources:
        return ""
    names = " and ".join(re.sub(r"^\d+[_\-\s]*", "", s.rsplit(".", 1)[0]).replace("_", " ").replace("-", " ").strip()
                         for s in sources[:2])
    return SOURCE_SUFFIX.get(lang, SOURCE_SUFFIX["en"]).format(src=names)

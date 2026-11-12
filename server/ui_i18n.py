"""Screen text in Kannada / Hindi for the kiosk TFT.

The kiosk asks for every piece of screen text it draws (labels, buttons,
statuses, fertilizer results) in the farmer's chosen language. Translation:

  1. numbers are lifted out first ("Urea 98 kg" -> "Urea {0} kg"), so one
     translation serves every value, and the numbers are put back unchanged;
  2. ui_overrides.json (hand-checked wording for the main screen phrases) wins;
  3. otherwise Sarvam translation (language.from_english, plain "native" style),
     cached in data/ui_translations.json so each phrase is translated once.

If translation fails the English text is returned, and the kiosk shows English.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from pathlib import Path

import language

log = logging.getLogger("ui_i18n")
HERE = Path(__file__).resolve().parent
OVERRIDES = HERE / "ui_overrides.json"
NUM = re.compile(r"\d+(?:[.,]\d+)?")
LANGS = ("kn", "hi")

_lock = threading.Lock()
_cache: dict[str, dict[str, str]] | None = None


def _cache_path() -> Path:
    return Path(os.getenv("UI_TRANSLATION_CACHE", HERE / "data" / "ui_translations.json"))


def _load() -> dict[str, dict[str, str]]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
        for lang in LANGS:
            _cache.setdefault(lang, {})
    return _cache


def _save():
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def overrides() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}


def template(text: str) -> tuple[str, list[str]]:
    """'Urea 98 kg, DAP 44.5 kg' -> ('Urea {0} kg, DAP {1} kg', ['98', '44.5'])."""
    nums: list[str] = []

    def keep(m):
        nums.append(m.group(0))
        return "{%d}" % (len(nums) - 1)
    return NUM.sub(keep, text), nums


def fill(tpl: str, nums: list[str]) -> str | None:
    """Numbers back into a translated template; None if the translation lost one."""
    out = tpl
    for i, n in enumerate(nums):
        if "{%d}" % i not in out:
            return None
        out = out.replace("{%d}" % i, n)
    return out


async def translate(texts: list[str], lang: str) -> list[str]:
    if lang not in LANGS:
        return list(texts)
    over = overrides().get(lang, {})
    with _lock:
        cache = _load()[lang]
    todo, tpls = {}, []
    for t in texts:
        tpl, nums = template(t.strip())
        tpls.append((tpl, nums))
        if tpl and tpl not in over and tpl not in cache and re.search(r"[A-Za-z]", tpl):
            todo[tpl] = None

    async def one(tpl):
        try:
            native, _ = await language.from_english(tpl, lang, "native")
            return tpl, native
        except Exception as e:                       # network, quota: fall back to English
            log.warning("translate %r to %s failed: %s", tpl, lang, e)
            return tpl, None
    if todo:
        done = await asyncio.gather(*(one(t) for t in todo))
        with _lock:
            for tpl, native in done:
                if native:
                    cache[tpl] = native
            _save()
    out = []
    for (tpl, nums), original in zip(tpls, texts):
        native = over.get(tpl) or cache.get(tpl)
        out.append((fill(native, nums) if native else None) or original)
    return out

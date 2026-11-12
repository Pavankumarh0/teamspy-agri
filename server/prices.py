"""Today's mandi (market) prices of crops from AGMARKNET, through the data.gov.in
"Current Daily Price of Various Commodities from Various Markets (Mandi)" API.

Needs DATA_GOV_IN_API_KEY in .env (free: register at https://data.gov.in ->
My Account -> Generate API key). Prices are rupees per quintal (100 kg), as
AGMARKNET reports them. Results are cached for PRICE_CACHE_S seconds.
"""
from __future__ import annotations

import os
import re
import time

import httpx

RESOURCE = os.getenv("AGMARKNET_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070")
URL = "https://api.data.gov.in/resource/{rid}"

# spoken word -> AGMARKNET commodity names to try (first match wins)
COMMODITIES: dict[str, list[str]] = {
    "tomato": ["Tomato"],
    "onion": ["Onion"],
    "potato": ["Potato"],
    "paddy": ["Paddy(Dhan)(Common)", "Paddy(Common)", "Paddy"],
    "rice": ["Rice"],
    "ragi": ["Ragi (Finger Millet)", "Ragi"],
    "maize": ["Maize"],
    "jowar": ["Jowar(Sorghum)", "Jowar"],
    "wheat": ["Wheat"],
    "green chilli": ["Green Chilli"],
    "chilli": ["Dry Chillies", "Green Chilli"],
    "groundnut": ["Groundnut"],
    "banana": ["Banana", "Banana - Green"],
    "coconut": ["Coconut"],
    "arecanut": ["Arecanut(Betelnut/Supari)", "Arecanut"],
    "coffee": ["Coffee"],
    "cotton": ["Cotton"],
    "turmeric": ["Turmeric"],
    "brinjal": ["Brinjal"],
    "cabbage": ["Cabbage"],
    "cauliflower": ["Cauliflower"],
    "carrot": ["Carrot"],
    "beans": ["Beans"],
    "beetroot": ["Beetroot"],
    "garlic": ["Garlic"],
    "ginger": ["Ginger(Green)", "Ginger(Dry)"],
    "tur": ["Arhar (Tur/Red Gram)(Whole)", "Arhar(Tur/Red Gram)(Whole)"],
    "green gram": ["Green Gram (Moong)(Whole)", "Green Gram(Moong)(Whole)"],
    "bengal gram": ["Bengal Gram(Gram)(Whole)"],
    "sunflower": ["Sunflower"],
    "soyabean": ["Soyabean"],
    "mango": ["Mango"],
    "grapes": ["Grapes"],
    "pomegranate": ["Pomegranate"],
}
ALIASES = {"chili": "chilli", "chillies": "chilli", "mirchi": "chilli", "capsicum": "chilli", "corn": "maize",
           "finger millet": "ragi", "sorghum": "jowar", "peanut": "groundnut", "areca": "arecanut",
           "supari": "arecanut", "red gram": "tur", "toor": "tur", "moong": "green gram", "chana": "bengal gram",
           "eggplant": "brinjal", "aubergine": "brinjal", "paddy rice": "paddy", "tomatoes": "tomato",
           "onions": "onion", "potatoes": "potato", "bananas": "banana", "coconuts": "coconut"}

PRICE_WORDS = re.compile(r"\b(price|prices|rate|rates|cost|mandi|market|apmc|selling|sell|quintal|bhav|bhaav)\b", re.I)

_CACHE: dict[str, tuple[float, dict]] = {}


def find_crop(text: str) -> str | None:
    """The crop a price question is about, or None."""
    t = " " + re.sub(r"[^a-z ]+", " ", text.lower()) + " "
    names = sorted(list(COMMODITIES) + list(ALIASES), key=len, reverse=True)   # 'green chilli' before 'chilli'
    for n in names:
        if f" {n} " in t:
            return ALIASES.get(n, n)
    return None


def is_price_question(text: str) -> bool:
    return bool(PRICE_WORDS.search(text)) and find_crop(text) is not None


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _field(rec: dict, name: str):
    for k, v in rec.items():
        if k.lower().replace(" ", "_") == name:
            return v
    return None


def _query(key: str, commodity: str, state: str | None) -> list[dict]:
    params = {"api-key": key, "format": "json", "limit": 100, "offset": 0, "filters[commodity]": commodity}
    if state:
        params["filters[state.keyword]"] = state
    r = httpx.get(URL.format(rid=RESOURCE), params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("records") or []


def get(crop: str, state: str = "Karnataka", district: str | None = None) -> dict:
    """{'ok': True, 'crop', 'commodity', 'scope', 'date', 'markets': [...]} or {'ok': False, 'reason'}."""
    key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
    if not key:
        return {"ok": False, "reason": "no_key"}
    ck = f"{crop}|{state}|{district}"
    ttl = float(os.getenv("PRICE_CACHE_S", "1800"))
    if ck in _CACHE and time.time() - _CACHE[ck][0] < ttl:
        return _CACHE[ck][1]
    out = {"ok": False, "reason": "no_data", "crop": crop}
    try:
        for commodity in COMMODITIES.get(crop, []):
            for scope in (state, None):                    # this state first, then all India
                recs = _query(key, commodity, scope)
                if recs:
                    out = _summarize(crop, commodity, recs, "state" if scope else "india", state, district)
                    break
            if out["ok"]:
                break
    except Exception as e:                                  # network / quota / bad key
        out = {"ok": False, "reason": "error", "crop": crop, "error": str(e)[:200]}
    _CACHE[ck] = (time.time(), out)
    return out


def _summarize(crop, commodity, recs, scope, state, district) -> dict:
    rows = []
    for r in recs:
        modal = _num(_field(r, "modal_price"))
        if modal is None or modal <= 0:
            continue
        rows.append({"market": str(_field(r, "market") or "").strip(),
                     "district": str(_field(r, "district") or "").strip(),
                     "state": str(_field(r, "state") or "").strip(),
                     "variety": str(_field(r, "variety") or "").strip(),
                     "date": str(_field(r, "arrival_date") or "").strip(),
                     "min": _num(_field(r, "min_price")), "max": _num(_field(r, "max_price")), "modal": modal})
    if not rows:
        return {"ok": False, "reason": "no_data", "crop": crop}
    d = (district or "").lower()
    rows.sort(key=lambda x: (0 if d and d in x["district"].lower() else 1, -x["modal"]))
    return {"ok": True, "crop": crop, "commodity": commodity, "scope": scope, "state": state,
            "date": rows[0]["date"], "markets": rows[:4]}


def _rs(v: float | None) -> str:
    return "unknown" if v is None else f"{v:.0f}"


def as_context(p: dict) -> str:
    """The prices as plain text for the LIVE DATA section of the prompt."""
    where = f"in {p['state']}" if p["scope"] == "state" else f"in India (no {p['state']} market reported it today)"
    lines = [f"Today's market (mandi) prices of {p['commodity']} {where}, from AGMARKNET (Government of India), "
             f"reported on {p['date']}. Prices are in rupees per quintal; one quintal is 100 kilograms."]
    for m in p["markets"]:
        place = ", ".join(x for x in (m["market"], m["district"]) if x)
        lines.append(f"- {place} market{' (' + m['variety'] + ')' if m['variety'] else ''}: usual (modal) price "
                     f"{_rs(m['modal'])} rupees, lowest {_rs(m['min'])}, highest {_rs(m['max'])} rupees per quintal.")
    lines.append("Prices change every day and differ between markets; check with the nearest APMC before selling.")
    return "\n".join(lines)


def unavailable_message(p: dict) -> str:
    crop = p.get("crop", "this crop")
    if p.get("reason") == "no_key":
        return ("Live market prices are not set up on this kiosk yet. You can check today's prices "
                "on the Agmarknet website or at your nearest APMC market.")
    if p.get("reason") == "error":
        return (f"I could not reach the market price service right now. Please try again later, "
                f"or check the {crop} price on Agmarknet or at your nearest APMC market.")
    return (f"No market has reported a {crop} price today. Please check on Agmarknet "
            f"or at your nearest APMC market.")

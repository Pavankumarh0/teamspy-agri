"""Weather for the farm's district from OpenWeatherMap (WEATHER_API_KEY), with a
rain alert. Cached for 10 minutes, so the kiosk's 5-second dashboard polling
costs at most ~150 API calls a day.

Alert levels (next 12 h = the next four 3-hour forecast slots):
    3 raining   it is raining / drizzling / storming now
    2 likely    probability of precipitation >= 50 %
    1 possible  probability >= 30 %
    0 none
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx

from campus_time import IST

log = logging.getLogger("weather")
OWM = "https://api.openweathermap.org/data/2.5"
CACHE_S = 600

# District headquarters (approximate) for the districts on the crop screen.
COORDS = {
    "bengaluru": (12.97, 77.59), "tumakuru": (13.34, 77.10), "kolar": (13.14, 78.13),
    "hassan": (13.00, 76.10), "belagavi": (15.85, 74.50), "chikkaballapura": (13.43, 77.73),
}
RAIN_MAIN = {"Rain", "Drizzle", "Thunderstorm"}
_cache: dict[str, tuple[float, dict]] = {}


def location(region: str | None) -> tuple[float, float, str]:
    lat, lon = os.getenv("KRISHI_LAT", "").strip(), os.getenv("KRISHI_LON", "").strip()
    if lat and lon:
        return float(lat), float(lon), "farm"
    region = (region or os.getenv("KRISHI_REGION", "bengaluru")).lower()
    lat_, lon_ = COORDS.get(region, COORDS["bengaluru"])
    return lat_, lon_, region if region in COORDS else "bengaluru"


def summarize(current: dict, forecast: list[dict], now: float | None = None) -> dict:
    """OpenWeatherMap current + forecast JSON -> what the kiosk shows."""
    main = (current.get("weather") or [{}])[0].get("main", "")
    desc = (current.get("weather") or [{}])[0].get("description", main)
    temp = current.get("main", {}).get("temp")
    raining = main in RAIN_MAIN or bool(current.get("rain"))
    slots = forecast[:4]
    pop = max((s.get("pop", 0) for s in slots), default=0)
    first_wet = next((s for s in slots if s.get("pop", 0) >= 0.5 or (s.get("weather") or [{}])[0].get("main") in RAIN_MAIN), None)
    hours = None
    if first_wet:
        hours = max(0, round((first_wet["dt"] - (now or time.time())) / 3600))
    if raining:
        alert, msg = 3, "Raining now"
    elif pop >= 0.5:
        alert = 2
        msg = f"Rain likely in about {hours} h ({round(pop * 100)}%)" if hours else f"Rain likely soon ({round(pop * 100)}%)"
    elif pop >= 0.3:
        alert, msg = 1, f"Rain possible in the next 12 h ({round(pop * 100)}%)"
    else:
        alert, msg = 0, "No rain expected in the next 12 h"
    return {"temp_c": None if temp is None else round(temp, 1), "condition": main, "description": desc,
            "rain_chance_12h": round(pop * 100), "raining": raining, "alert": alert, "message": msg}


def get(region: str | None = None) -> dict:
    """Current weather + rain alert for the farm, or {"ok": False, ...}."""
    key = os.getenv("WEATHER_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "WEATHER_API_KEY not set"}
    lat, lon, place = location(region)
    hit = _cache.get(place)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        params = {"lat": lat, "lon": lon, "appid": key, "units": "metric"}
        cur = httpx.get(f"{OWM}/weather", params=params, timeout=10)
        fc = httpx.get(f"{OWM}/forecast", params={**params, "cnt": 4}, timeout=10)
        cur.raise_for_status()
        fc.raise_for_status()
        out = {"ok": True, "place": place, "source": "OpenWeatherMap",
               "fetched_at": datetime.now(timezone.utc).astimezone(IST).strftime("%H:%M"),
               **summarize(cur.json(), fc.json().get("list", []))}
    except Exception as e:
        log.warning("weather unavailable: %s", e)
        if hit:                                   # keep showing the last known weather
            return {**hit[1], "stale": True}
        return {"ok": False, "error": "weather service unreachable"}
    _cache[place] = (time.time(), out)
    return out


def advice(w: dict | None) -> list[str]:
    """What the weather means for applying fertilizer (KB: nitrogen is easily
    lost by washing away)."""
    if not w or not w.get("ok"):
        return []
    if w["alert"] >= 2:
        return [f"Weather: {w['message']}. Wait to apply urea until the rain has passed, "
                "because rain can wash nitrogen away."]
    if w["alert"] == 1:
        return [f"Weather: {w['message']}. Avoid applying urea just before rain."]
    return [f"Weather: {w['message']}."]

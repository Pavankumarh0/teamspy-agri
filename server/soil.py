"""Soil sensor readings: the hook for the second ESP32 (soil moisture node).

The sensor node will POST /api/krishi/soil-data with
    {"device_id": "krishi_sensor_01", "soil_moisture": 42, "crop": "tomato",
     "temperature": 28, "humidity": 65}

Readings are kept per device (latest only) in memory and in data/soil_latest.json,
so a restart does not lose the last reading.

Until that node exists, SOIL_MOCK=1 supplies a fixed reading for development.
A mock reading is ALWAYS labelled: "source": "mock" in the API, and
"MOCK READING (simulated, not a real measurement)" in the text Gemma sees, so
it can never be passed off as a field measurement. A real reading always wins
over the mock one.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from campus_time import IST

_lock = threading.Lock()
_latest: dict[str, dict] = {}
_loaded = False

SOIL_WORDS = re.compile(
    r"\b(soil|moisture|water(?:ing)?|irrigat\w*|dry|wet|sensor|reading|humidity|temperature)\b", re.I)

MOCK_READING = {"device_id": "mock_sensor", "soil_moisture": 42, "crop": "tomato",
                "temperature": 28, "humidity": 65}


def _store() -> Path:
    return Path(os.getenv("SOIL_STORE", Path(__file__).resolve().parent / "data" / "soil_latest.json"))


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _latest.update({k: v for k, v in data.items() if isinstance(v, dict)})
    except (OSError, ValueError):
        pass


def save(reading: dict) -> dict:
    """Record a real reading from a sensor node. Returns the stored record."""
    rec = {**reading, "source": "sensor", "received_at": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _load()
        _latest[rec["device_id"]] = rec
        try:
            _store().parent.mkdir(parents=True, exist_ok=True)
            _store().write_text(json.dumps(_latest, indent=2), encoding="utf-8")
        except OSError:
            pass
    return rec


def mock_enabled() -> bool:
    return os.getenv("SOIL_MOCK", "1") == "1"


def latest(device_id: str | None = None) -> dict | None:
    """The newest real reading (of one device, or of any), else the mock one if
    SOIL_MOCK=1, else None."""
    with _lock:
        _load()
        rows = [_latest[device_id]] if device_id and device_id in _latest else (
            [] if device_id else list(_latest.values()))
    if rows:
        return max(rows, key=lambda r: r.get("received_at", ""))
    if mock_enabled():
        return {**MOCK_READING, "source": "mock", "received_at": datetime.now(timezone.utc).isoformat()}
    return None


def age_minutes(rec: dict, now: datetime | None = None) -> float:
    try:
        at = datetime.fromisoformat(rec["received_at"])
    except (KeyError, ValueError):
        return float("inf")
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() / 60


def as_context(rec: dict, now: datetime | None = None) -> dict:
    """The reading as a CONTEXT section for Gemma (source soil_sensor.md)."""
    at = datetime.fromisoformat(rec["received_at"]).astimezone(IST)
    label = "MOCK READING (simulated, not a real measurement)" if rec.get("source") == "mock" \
        else "REAL SENSOR READING"
    if age_minutes(rec, now) > float(os.getenv("SOIL_MAX_AGE_MIN", "60")):
        label += ". STALE: this reading may be out of date"
    parts = [f"{label}. Device {rec['device_id']}, taken at {at:%H:%M} on {at:%d %B %Y} India time."]
    if rec.get("crop"):
        parts.append(f"Crop: {rec['crop']}.")
    if rec.get("soil_moisture") is not None:
        parts.append(f"Soil moisture: {rec['soil_moisture']:g} percent.")
    if rec.get("temperature") is not None:
        parts.append(f"Air temperature: {rec['temperature']:g} degrees Celsius.")
    if rec.get("humidity") is not None:
        parts.append(f"Air humidity: {rec['humidity']:g} percent.")
    return {"source": "soil_sensor.md", "title": "Latest soil sensor reading", "text": " ".join(parts)}

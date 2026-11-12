"""Smart Krishi - UNO Q Linux side: sensor readings from the STM32 -> HTTP POST.

The sketch calls Bridge.notify("krishi_reading", ...) every 5 s. The handler
below only stores the reading (Bridge handlers run on one dedicated thread and
must stay quick); the App loop posts the newest one to the Smart Krishi server:

    POST {backend_url}/api/krishi/sensors
    Authorization: Bearer {device_token}

Only the newest unsent reading is kept: after an outage the server gets the
current conditions, not a backlog. Failed posts back off from 2 s to 30 s.

Configuration: python/config.json (copy config.example.json; it is not committed
because it holds the device token). Environment variables of the same name in
upper case (KRISHI_BACKEND_URL, KRISHI_DEVICE_TOKEN, ...) override it.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from arduino.app_utils import App, Bridge

HERE = Path(__file__).resolve().parent
FAULTS = {0: "dht_read_failed", 1: "dht_out_of_range", 2: "soil_saturated_high", 3: "soil_near_zero",
          4: "soil_noisy", 5: "mq135_saturated_high", 6: "mq135_near_zero", 7: "mq135_warming_up",
          8: "mq135_noisy"}


def load_config() -> dict:
    cfg = {"backend_url": "", "device_token": "", "device_id": "unoq_soil_01", "crop": None,
           "soil_dry_raw": None, "soil_wet_raw": None, "timeout_s": 4}
    for name in ("config.json", "config.example.json"):
        f = HERE / name
        if f.exists():
            try:
                cfg.update({k: v for k, v in json.loads(f.read_text()).items() if not k.startswith("_")})
                print(f"[krishi] config from {name}")
                break
            except ValueError as e:
                print(f"[krishi] {name} is not valid JSON: {e}")
    for key in list(cfg):
        env = os.getenv("KRISHI_" + key.upper())
        if env is not None and env != "":
            cfg[key] = env
    cfg["backend_url"] = str(cfg["backend_url"] or "").rstrip("/")
    return cfg


CFG = load_config()
_lock = threading.Lock()
_pending = None              # newest reading not yet accepted by the server
_next_try = 0.0
_backoff = 2.0
_sent = 0


def soil_percent(raw: int, faults: list[str]):
    """Moisture % = (DRY - RAW) / (DRY - WET) x 100, clamped to 0-100.
    Only with both calibration readings set (soil_dry_raw, soil_wet_raw). A
    reading at the top of the ADC range is just "as dry as the DRY point" once
    calibrated, so it gives ~0 % (the fault still travels with it); a reading
    near zero or a noisy one gives no percentage."""
    dry, wet = CFG.get("soil_dry_raw"), CFG.get("soil_wet_raw")
    if dry in (None, "") or wet in (None, ""):
        return None
    if any(f in faults for f in ("soil_near_zero", "soil_noisy")):
        return None
    dry, wet = float(dry), float(wet)
    if dry == wet:
        return None
    pct = (dry - raw) / (dry - wet) * 100.0
    return round(min(100.0, max(0.0, pct)), 1)


def krishi_reading(dht_ok, temp_c, hum, soil_raw, soil_valid, mq_raw, mq_valid, faults, seq, uptime_s):
    """Bridge handler: build the payload and leave it for the loop."""
    global _pending
    names = [n for bit, n in FAULTS.items() if int(faults) & (1 << bit)]
    pct = soil_percent(int(soil_raw), names)
    payload = {
        "device_id": CFG["device_id"],
        "temperature_c": round(float(temp_c), 1) if dht_ok else None,
        "humidity_percent": round(float(hum), 1) if dht_ok else None,
        "soil_moisture_raw": int(soil_raw),
        "soil_moisture_percent": pct,
        "soil_sensor_valid": pct is not None,
        "mq135_raw": int(mq_raw),
        "mq135_valid": bool(mq_valid),
        "faults": names,
        "seq": int(seq),
        "uptime_s": int(uptime_s),
    }
    if CFG.get("crop"):
        payload["crop"] = str(CFG["crop"])[:40]
    print(f"[krishi] #{seq} T={payload['temperature_c']} RH={payload['humidity_percent']} "
          f"soil_raw={soil_raw} soil_pct={pct if pct is not None else '-'} soil_valid={payload['soil_sensor_valid']} mq135_raw={mq_raw} "
          f"faults={','.join(names) or '-'}")
    with _lock:
        _pending = payload


def post(payload: dict) -> tuple[bool, str]:
    req = urllib.request.Request(
        CFG["backend_url"] + "/api/krishi/sensors", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {CFG['device_token']}"})
    try:
        with urllib.request.urlopen(req, timeout=float(CFG["timeout_s"])) as r:
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode(errors="replace")
        return False, f"HTTP {e.code} {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"unreachable: {getattr(e, 'reason', e)}"


def loop():
    global _pending, _next_try, _backoff, _sent
    time.sleep(0.2)
    with _lock:
        payload = _pending
    if payload is None or time.monotonic() < _next_try:
        return
    if not CFG["backend_url"] or not CFG["device_token"]:
        print("[krishi] backend_url / device_token not configured (python/config.json) - not sending")
        _next_try = time.monotonic() + 60
        return
    ok, info = post(payload)
    if ok:
        with _lock:
            if _pending is payload:
                _pending = None
        _backoff = 2.0
        _sent += 1
        if _sent == 1 or _sent % 12 == 0:          # once a minute is enough in the log
            print(f"[krishi] sent #{payload['seq']} to {CFG['backend_url']} ({info}); {_sent} sent")
    else:
        print(f"[krishi] send failed ({info}); retry in {_backoff:.0f} s")
        _next_try = time.monotonic() + _backoff
        if info.startswith("HTTP 4"):               # 401/422: retrying the same payload will not help
            with _lock:
                if _pending is payload:
                    _pending = None
        _backoff = min(30.0, _backoff * 2)


print(f"[krishi] Smart Krishi sensors: device {CFG['device_id']} -> {CFG['backend_url'] or '(no backend_url)'}")
Bridge.provide("krishi_reading", krishi_reading)
App.run(user_loop=loop)

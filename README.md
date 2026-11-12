# Smart Krishi Assistant

An AI farm assistant built on the **Campus Mithra** kiosk, with two devices:

- **Device 1, ESP32 voice kiosk:** a farm **dashboard** on the TFT (temperature,
  humidity, soil moisture, MQ-135) and a **voice chatbot**. Tap the button to switch
  screens; hold it to ask a question in English, Kannada or Hindi.
- **Device 2, Arduino UNO Q sensor collector:** reads a DHT11, an HW-080 soil probe
  and an MQ-135 every 5 s and posts them to the Smart Krishi server.

```
 UNO Q  STM32 sketch ──Bridge.notify──► Linux: python/main.py ──Wi-Fi HTTP POST──┐
        DHT11 D2, soil A0, MQ-135 A1     (App Lab app smart-krishi-sensors)      │
                                                                                  ▼
                                              PC: server/app.py (FastAPI :8001)
                                              /api/krishi/sensors  ← readings + device token
                                              /api/krishi/chat     ← RAG over kb/ + live readings → Gemma
                                                         ▲   │
                                   GET /sensors/latest   │   │  answer, speech
                                   every 5 s (thread)    │   ▼
 ESP32 kiosk ◄────────USB serial 921600──────────── PC: krishi_client.py
   TFT: dashboard ⇄ chat   button: tap = switch, hold = talk
   INMP441 mic ──► (question audio) ──► Sarvam STT
   MAX98357A ◄── 16 kHz speech ◄── edge-tts
```

**The ESP32 has no Wi-Fi in this design.** It already depends on the PC for
speech and Gemma over USB, and the backend runs on that same PC, so the PC client
fetches the readings and sends them to the ESP32 as a `D:` line. That means no
Wi-Fi credentials on the ESP32 and no blocking HTTP next to the audio code. The
dashboard shows the link status instead: *PC*, *Server* and *Sensor
online/stale/offline*. The UNO Q is the device that uses Wi-Fi, through its Linux side.

## What is reused from Campus Mithra

Campus Mithra (`Documents/PlatformIO/Projects/Campus-Mithra`) is **not modified**.

| Piece | Here | From Campus Mithra | Changes |
|---|---|---|---|
| RAG retrieval (Gemini embeddings + TF-IDF) | `server/rag.py` | `server/rag.py` | none |
| Gemma (Gemini API or Ollama) | `server/llm.py` | same | none |
| Grounding check (every sentence and **number** must be in the evidence) | `server/grounding.py` | same | none |
| Speech (Sarvam/Whisper STT, edge-tts), Kannada/Hindi | `server/speech.py`, `language.py` | same | none |
| ESP32 firmware: pins, I2S mic/amp, USB protocol, chat screen | `firmware/` | `firmware/` | branding; dashboard and tap/hold added |
| PC ⇄ ESP32 bridge | `krishi_client.py` | `pc_client.py` | `/api/krishi/*`; dashboard poller; campus/QR/RFID removed |
| UNO Q sensor sketch | `unoq/smart-krishi-sensors/sketch` | your App Lab app `test-moisture` | same pins and DHT11; filtering, validity, Bridge |

## Wiring

### ESP32 kiosk (unchanged)
ILI9341 TFT 240×320, used in landscape (CS 5, DC 2, RST 4, MOSI 23, SCK 18,
MISO 19), INMP441 (SCK 14, WS 15, SD 32), MAX98357A (BCLK 26, LRC 25, DIN 22),
push button **GPIO27 → GND** (INPUT_PULLUP). Details: [docs/HARDWARE.md](docs/HARDWARE.md).

### UNO Q sensors (as in `test-moisture`)

| Sensor | UNO Q | Supply | Notes |
|---|---|---|---|
| DHT11 DATA | D2 | 3.3 V or 5 V per module | the sketch uses `DHT11` (from `test-moisture`); change `DHTTYPE` for a DHT22 |
| HW-080 soil AO | A0 | **3.3 V** | read as 14-bit raw (0–16383) |
| MQ-135 AO | A1 **through a divider** | **5 V** heater supply, common GND | AO swings up to ~5 V: **never connect it straight to A1** |

**MQ-135 divider:** AO → **10 kΩ** → A1 → **20 kΩ** → GND. That gives
5 V × 20/(10+20) = **3.33 V at most** at A1. With standard values, 10 kΩ + 22 kΩ
gives 3.44 V; 12 kΩ + 22 kΩ gives 3.24 V (the safest). Check the maximum with a
multimeter before connecting A1. All grounds must be joined.

## Button and screens

| Gesture | From the dashboard | From the chat screen |
|---|---|---|
| **Tap** (released before 0.4 s) | → chat screen | → dashboard |
| **Hold** (0.4 s or more) | records → switches to chat → answer | records → answer |
| Press while an answer is being prepared or spoken | ignored | ignored |

- Debounce is 50 ms, and each press needs a release before the next.
- Recording starts the moment the button goes down, so a hold loses no speech; a tap's audio is discarded (`REC:CANCEL tap`).
- LISTENING appears only once the press is long enough to count as a hold, so a tap never flashes the chat screen.
- The ESP32 boots into the dashboard.
- Switching screens never resets the board. The chat screen keeps the last answer, so you can tap back to it.

**Dashboard:** title, four cards (temperature, humidity, soil moisture, MQ-135
raw), sensor online/stale/offline, PC and server link, and "Updated N s ago".
- Missing values show `--`.
- The soil card shows `Not calibrated` plus the raw value until the UNO Q sends a calibrated percentage. A raw value of 16319 or more adds "check probe".
- MQ-135 is always labelled *raw, uncalibrated, not ppm*.
- When the sensor is stale or offline, the server is unreachable or the PC app stops, values stay on screen dimmed and marked *last known*.
- Only changed fields are repainted, so there is no flicker.

**Chat screen:** "SMART KRISHI AI" heading, LISTENING with a level meter,
PROCESSING with thinking dots, SPEAKING with lip-sync, the recognised question and
the answer, wrapped and paged. Same as Campus Mithra.

## Setup

```powershell
cd C:\Users\"Pavan Kumar H"\Documents\projects\amc-agri
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

In `.env`: `GEMINI_API_KEY` and `SARVAM_API_KEY` (as for Campus Mithra), and
`KRISHI_SENSOR_TOKEN` — generate one with
`python -c "import secrets; print(secrets.token_urlsafe(24))"`. Without a token, sensor
ingestion is switched off (HTTP 503).

### Flash the ESP32
```powershell
cd firmware
C:\Users\"Pavan Kumar H"\.platformio\penv\Scripts\pio.exe run -t upload    # COM9
```
Expect `[esp] screen: dashboard` and `button GPIO27: tap ... hold = talk` in the monitor.

### Install the UNO Q app (Arduino App Lab)
1. In App Lab, create an app `smart-krishi-sensors`, or copy the folder
   `unoq/smart-krishi-sensors` to the board's `~/ArduinoApps/`.
2. On the board, copy `python/config.example.json` to `python/config.json` and fill in:
   - `backend_url`: the PC's address, e.g. `http://10.185.75.17:8001` (`ipconfig` on the PC; both devices on the same Wi-Fi).
   - `device_token`: the same value as `KRISHI_SENSOR_TOKEN`.
   - `device_id`: `unoq_soil_01`, and optionally `crop`.
3. Run the app: the App Lab **Run** button, or on the board `arduino-app-cli app start user:smart-krishi-sensors`. It replaces whichever app was running; `test-moisture` stays installed.
4. The App Lab console shows `--- SMART KRISHI SENSOR DATA #n ---` from the sketch and `[krishi] sent #n` from Python.
5. **Make it the board's default app**, or a UNO Q reboot starts the previous default and the dashboard shows *Sensor offline*. Use App Lab's default-app option, or on the board:
   `printf %s /home/arduino/ArduinoApps/smart-krishi-sensors > /var/lib/arduino-app-cli/default.app`
   (`app list` then marks it with `*`). This board's previous default (WiFi Robot Remote) is saved as `/var/lib/arduino-app-cli/default.app.bak-wifi-robot-remote`.

`config.json` is gitignored: the token is never in the code or the repo.

**Soil calibration** (until it is done, the soil sensor is reported as not calibrated):
1. Read the raw value with the probe in **dry** soil, then in **thoroughly wet** soil. Use the App Lab console or `GET /api/krishi/sensors/latest`.
2. Put both in `config.json` as `soil_dry_raw` and `soil_wet_raw`, then restart the app.

Investigate a reading pinned near 16383 first: a dry probe in air, a loose wire or the wrong pin all read like that.

## Run

```powershell
.\start.ps1                # server + kiosk client on COM9
```

## API (`server/app.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/krishi/sensors` | sensor reading; header `Authorization: Bearer <KRISHI_SENSOR_TOKEN>` (or `X-Device-Token`) |
| GET | `/api/krishi/sensors/latest` | `reading`, `server_time`, `received_at`, `age_seconds`, `status` (`online`/`stale`/`offline`/`no_data`), per-value `valid`, `is_test_data`; `?device_id=` optional |
| POST | `/api/krishi/chat` | question → answer, `sources`, `via`, `sensor` |
| POST | `/api/krishi/voice`, `/transcribe`, `/understand` | voice and language helpers |
| GET | `/api/krishi/audio/{id}.s16` | spoken answer for the MAX98357A |
| GET | `/api/krishi/health` | status, model, `sensor_ingestion`, `sensor_status` |

Sensor payload (every field except `device_id` may be `null` or left out):

```json
{"device_id": "unoq_soil_01", "temperature_c": 28.5, "humidity_percent": 31,
 "soil_moisture_raw": 16363, "soil_moisture_percent": null, "soil_sensor_valid": false,
 "mq135_raw": 1748, "mq135_valid": true, "faults": ["soil_saturated_high"],
 "crop": "tomato", "seq": 12, "uptime_s": 60, "is_test_data": false}
```

Validation rules:
- Ranges: temperature −40 to 85, humidity and percent 0–100, raw values 0–65535.
- Unknown fields are rejected with HTTP 422.
- A `soil_moisture_percent` sent with `soil_sensor_valid: false` is dropped.
- Readings are kept per device in `server/data/sensors_latest.json`, written atomically, so they survive a restart.
- `online` means a reading in the last `SENSOR_STALE_S` (30 s); `stale` until `SENSOR_OFFLINE_S` (120 s); then `offline`.

**Fault names:** `dht_read_failed`, `dht_out_of_range`, `soil_saturated_high`,
`soil_near_zero`, `soil_noisy`, `mq135_saturated_high`, `mq135_near_zero`,
`mq135_warming_up` (first 3 min), `mq135_noisy`.

### Sensor readings in answers
A farm-condition question ("How is my farm today?", "Is the soil dry?") gets the latest reading as a **separate** `LIVE SENSOR READINGS` block in the prompt, apart from the `KNOWLEDGE DOCUMENTS`:
- It carries the reading's time, and labels STALE / OFFLINE / TEST DATA where they apply.
- An uncalibrated soil sensor appears as "not calibrated" and an MQ-135 as "raw only, not ppm". The raw numbers are never offered as measurements.
- The grounding check also covers sensor values, so an invented reading ("soil moisture is 42 percent") is rejected.
- With no reading at all, the kiosk says it has not received any sensor data yet.
- There is no weather source; nothing about weather is assumed.

## Languages, loudness, knowledge base

- **Languages:** English, Kannada and Hindi (`KIOSK_LANGUAGES=en,kn,hi`). Kanglish and Hinglish questions get Kanglish/Hinglish answers, and pure Kannada/Hindi get pure answers, as in Campus Mithra. The TFT shows Latin script.
- **Speaker loudness:** `KIOSK_LOUDNESS` (default 6, 0 = Campus Mithra's level). It is a soft limiter applied before the firmware's 2x gain.
- **Knowledge base (`kb/`)** is **starter content, not yet verified**, and has no fertilizer doses. Check it against the official package of practices (UAS Bangalore / KVK) before farmers rely on it.
- **Back to Campus Mithra:** flash Campus Mithra's `firmware/` again.

## Tests

```powershell
cd server; ..\.venv\Scripts\python -m unittest discover -s tests
```

| Check (12 Nov 2026) | How | Result |
|---|---|---|
| Server + client unit tests (39): sensor auth, validation, nulls, persistence, online/stale/offline, separate prompt block, invented-reading rejection, no-data reply, test-data label, `D:` line builder, grounding, languages | `unittest` | pass |
| ESP32 firmware build | `pio run` | pass (RAM 19.3%, flash 26.5%, no warnings) |
| ESP32 on the real board, over serial | flashed; script sends boot/`D:`/`Q:`/`A:`/`CLR`/`PING` | boots into the dashboard; 9 `D:` variants (spec payload, nulls, calibrated, stale, offline, server down, no data, test data, oversized garbage) parsed with no error; `Q:` switches to chat; still answers `PING` |
| UNO Q app on the real board | App Lab built the sketch, flashed the STM32 and started Python | readings every 5 s: DHT11 28–30 °C / 24 % RH, MQ-135 raw ~1500–1700 (warm-up flag for the first 3 min), soil raw 16362–16372 → `soil_saturated_high`, **invalid, no percentage** |
| UNO Q → server over Wi-Fi with device token | `POST /api/krishi/sensors` | HTTP 200; `/sensors/latest` shows `online` |
| Server outage | server restarted during the run | status went `offline`; UNO Q backed off (2 → 30 s), then sent only the newest reading; back to `online` |
| Live Gemma with real readings ("How is my farm today?", soil, air quality, irrigation amount, a normal KB question) | `/api/krishi/chat` | real temperature/humidity with time; soil "not calibrated"; MQ-135 "raw only"; probe warning; no irrigation amount invented; KB answers unchanged |
| Campus Mithra | git status, its 21 server tests + 5 kiosk test files | unchanged, pass |

**Not verified — needs someone at the kiosk:**
- The look of the dashboard on the TFT: layout, colours, no flicker, the "Updated N s ago" counter.
- A **tap** switching screens and a **hold** recording from the dashboard, with the 50 ms debounce on the real button.
- The full spoken flow from the dashboard: hold, speak, LISTENING, answer, speech.
- The MQ-135 divider voltage at A1 (measure it), and the soil probe in real soil. Its pegged 16 3xx reading needs investigating before calibration.

# Smart Krishi Assistant

An AI voice assistant for farmers, built on the **Campus Mithra** kiosk. A farmer
holds the button, asks a question in English or Kannada, and hears a grounded
answer from an agricultural knowledge base. The answer also appears on the screen.

```
 talk button ─► INMP441 ─► ESP32 ──USB serial 921600──► PC: krishi_client.py
                            │ ▲                              │
                            │ │                    server/app.py (FastAPI, :8001)
                            │ │                    Sarvam STT → Kannada↔English
                            │ │                    RAG over kb/ → Gemma → grounding check
                            │ └── 16 kHz speech ◄── edge-tts
                            ├──► TFT  "SMART KRISHI": question, answer, source
                            └──► MAX98357A ─► speaker
```

## What is reused from Campus Mithra

Campus Mithra (`Documents/PlatformIO/Projects/Campus-Mithra`) is **not modified**.
This is a separate project; the working pieces were copied in:

| Piece | Here | From Campus Mithra | Changes |
|---|---|---|---|
| RAG retrieval (Gemini embeddings + TF-IDF, cached) | `server/rag.py` | `server/rag.py` | none |
| Gemma (Gemini API or Ollama, retries, fallback model) | `server/llm.py` | `server/llm.py` | none (its campus `PROMPT` is unused) |
| Grounding check (every sentence and **every number** must appear in the retrieved text) | `server/grounding.py` | same | none |
| Speech: Sarvam/Whisper STT, edge-tts, 16-bit PCM for the MAX98357A | `server/speech.py` | same | none |
| Kannada ↔ English (Sarvam), Latin script for the TFT | `server/language.py` | same | none |
| IST date helper | `server/campus_time.py` | same | none |
| ESP32 firmware (pins, I2S mic/amp, USB protocol, screens) | `firmware/` | `firmware/` | branding text only, separate build dir |
| PC ⇄ ESP32 bridge | `krishi_client.py` | `pc_client.py` | `/api/krishi/*` endpoints; Firestore campus lookup, QR maps and RFID removed |
| Launcher, hardware self-test | `start.ps1`, `scripts/esp32_selftest.py` | same | names, port, sample text |

New for Smart Krishi: `server/app.py` (agricultural API), `server/prompts.py`
(farming rules: no invented doses, explain the reason, label mock sensor data),
`server/soil.py` (soil sensor store), `kb/` (agricultural documents) and tests.

The two projects have **separate knowledge bases, `.env` files, ports
(Campus 8000, Krishi 8001), virtual environments and firmware build folders**.

## Hardware

Identical to Campus Mithra: ESP32 DevKit, INMP441 (SCK 14, WS 15, SD 32),
MAX98357A (BCLK 26, LRC 25, DIN 22), TFT ILI9341 (CS 5, DC 2, RST 4, MOSI 23,
SCK 18, MISO 19), talk button GPIO27 to GND. No new parts and no rewiring. The
link to the PC is the existing **USB serial** connection at 921600 baud, as on the
working Campus Mithra kiosk. Full pin map and troubleshooting: [docs/HARDWARE.md](docs/HARDWARE.md).

The screen shows `SMART KRISHI` in the title bar and these statuses on the right:
`PC offline` (no connection), `ready`, `LISTENING` with a level bar, `PROCESSING`,
`SPEAKING`, and errors (`mic error`, `speech error`, `server error`, `no answer`, `link error`).
The face drawing is unchanged from Campus Mithra, graduation cap included.

## Setup (once)

```powershell
cd C:\Users\"Pavan Kumar H"\Documents\projects\amc-agri
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then add GEMINI_API_KEY and SARVAM_API_KEY
```

The keys are the same as for Campus Mithra (Google AI Studio for Gemma and
embeddings, Sarvam for speech-to-text and Kannada translation). edge-tts needs
internet access.

## Flash the ESP32

Close anything holding the COM port (serial monitor, a running client), then:

```powershell
cd firmware
C:\Users\"Pavan Kumar H"\.platformio\penv\Scripts\pio.exe run -t upload     # COM9, as in platformio.ini
C:\Users\"Pavan Kumar H"\.platformio\penv\Scripts\pio.exe device monitor     # 921600 baud; expect "[esp] Smart Krishi kiosk - push-to-talk"
```

Or use the PlatformIO "Upload" button in VS Code with this `firmware/` folder open.
If the board is not on COM9, change `upload_port`/`monitor_port` in
`firmware/platformio.ini`. If the screen is blank or the colours are wrong, flash
`-e mithra_st7789`. The build needs the `C:\pio` junction that Campus Mithra
already uses (see the top of `platformio.ini`).

To switch the kiosk back to Campus Mithra, flash Campus Mithra's `firmware/`
again. The two firmwares use the same protocol and differ only in branding.

## Run

```powershell
.\start.ps1                 # server window + kiosk client on COM9
.\start.ps1 -Port COM5      # another port
.\start.ps1 -NoEsp32        # no kiosk: PC mic (Ctrl+Alt+4) and PC speakers
```

Then, on the kiosk, **hold the button, ask, let go**. Manual start:

```powershell
cd server; ..\.venv\Scripts\python app.py                     # http://127.0.0.1:8001
..\.venv\Scripts\python krishi_client.py --esp32 COM9          # from the project root
..\.venv\Scripts\python krishi_client.py --ask "When should I water my crops?" --esp32 none
python scripts\esp32_selftest.py --port COM9                    # screen + speaker test, no server
```

## API (`server/app.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/krishi/health` | status, chunks, model, languages, mock flag |
| POST | `/api/krishi/chat` | `{"question", "session", "language": "en"/"kn", "style"}` → `answer`, `sources`, `via`, `sensor`, `audio_id` |
| POST | `/api/krishi/voice` | multipart `file` (WAV) → transcript + answer in one call |
| POST | `/api/krishi/transcribe` | multipart `file` → text and language (the kiosk client uses this to show the question early) |
| POST | `/api/krishi/understand` | typed Kannada/English → English + display text |
| GET | `/api/krishi/audio/{id}.s16` | spoken answer, 16-bit 16 kHz (MAX98357A); also `.mp3`, `.u8` |
| POST | `/api/krishi/soil-data` | soil sensor reading (below) |
| GET | `/api/krishi/soil-data/latest` | newest reading, with `is_mock` and `age_minutes` |

`via` says how an answer was made: `gemma` (grounded), `unknown` (not enough
verified information), `ungrounded` (Gemma's answer was rejected, for example
because it contained a number not found in the knowledge base), `kb-direct`
(Gemma was unreachable, so sentences were read verbatim from the knowledge base) or `error`.

## Soil sensor (future second ESP32)

The sensor node should POST JSON to `http://<PC IP>:8001/api/krishi/soil-data`:

```json
{"device_id": "krishi_sensor_01", "soil_moisture": 42, "crop": "tomato", "temperature": 28, "humidity": 65}
```

`soil_moisture` and `humidity` must be 0-100, and `device_id` may contain letters,
digits, `_` and `-`. If `KRISHI_SENSOR_KEY` is set, the node must send it in an
`X-Device-Key` header. The latest reading per device is kept in
`server/data/soil_latest.json`.

When a question mentions soil, moisture, watering or the sensor, the newest
reading goes to Gemma as a `soil_sensor.md` section that carries its time and one
of these labels:
- `REAL SENSOR READING`: posted by a sensor.
- `MOCK READING (simulated, not a real measurement)`: used only when `SOIL_MOCK=1` and no real reading exists. Gemma is told to say it is simulated, and the API marks it `"source": "mock"`.
- `STALE`: added when a reading is older than `SOIL_MAX_AGE_MIN`.

Set `SOIL_MOCK=0` once the real sensor is running.

## Knowledge base (`kb/`)

Eight Markdown files: soil health, moisture and irrigation, fertilizers,
sustainable alternatives, tomato cultivation, tomato leaf problems, the sensor
guide and where to get help. Each `##` section is one retrieval chunk. To add a
document, drop a `.md` file with `##` sections into `kb/` and restart the server.
Embeddings are rebuilt and cached automatically.

**Status: starter content, not yet verified.** It was written for development
from general agronomy guidance and must be checked against the official
package of practices (UAS Bangalore / KVK / Department of Agriculture) before
farmers rely on it. It deliberately contains **no fertilizer doses**: dose
questions are answered with "depends on your soil test / Soil Health Card". If
you add verified dose tables, Gemma may quote them, and the grounding check
still rejects any number that is not in the documents.

## Tests

```powershell
cd server; ..\.venv\Scripts\python -m unittest discover -s tests
```

| Check | Result (12 Nov 2026) |
|---|---|
| Server unit tests (27): grounding, language, Krishi API, invented-dose rejection, soil mock/real/stale labels, sensor key, KB separation | pass |
| Firmware compile (`pio run -e mithra_ili9341`) | pass (RAM 19%, flash 26%) |
| Live RAG + Gemma (gemma-4-26b-a4b-it) on the six example questions | grounded answers with sources |
| Dose trap ("how many kg of urea per acre") | no number invented; refers to soil test |
| Off-topic, campus and market-price questions | "not enough verified information" |
| Voice pipeline from synthesized WAV (English and Kannada): Sarvam STT → RAG → Gemma → Kannada reply → 16 kHz audio | pass |
| `krishi_client.py --ask` against the server (no board) | pass |
| Campus Mithra after the change: 21 server tests, kiosk tests, live `/api/ask` on :8000 | pass, repo unchanged |
| **Microphone, speaker, button, display, USB link on the real ESP32** | **not tested: no board was connected** |
| **Full button-to-speaker flow on the kiosk** | **not tested: needs the board** |

### Hardware checklist (to do with the board connected)
1. Flash and watch the monitor for `mic ... ok`, `speaker ... ok` and `mic slots: ... -> slot 0`.
2. `python scripts\esp32_selftest.py --port COM9`: PING, screen pages, chime and speech.
3. `.\start.ps1`: the title bar changes from `PC offline` to `ready`.
4. Hold the button and ask "What causes yellow leaves in tomato plants?": you should see `LISTENING` → `PROCESSING` → the answer, and hear it spoken.
5. Ask the same question in Kannada.
6. If recognition is poor, listen to `server/debug/last_kiosk_mic.wav`.

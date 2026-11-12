<div align="center">

<img src="public/favicon.svg" width="72" alt="Chiguru logo" />

# Chiguru · Smart Krishi

**A voice-first farm assistant that speaks the farmer's language.**

Hold a button, ask about your crop in Kannada, Hindi or English, and hear a grounded answer
in the same language, using live soil readings from your own field.

![React](https://img.shields.io/badge/React_19-20232A?logo=react&logoColor=61DAFB)
![Three.js](https://img.shields.io/badge/Three.js-000000?logo=threedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Gemma](https://img.shields.io/badge/Gemma_4-4285F4?logo=google&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-E7352C?logo=espressif&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino_UNO_Q-00878F?logo=arduino&logoColor=white)
![Sarvam AI](https://img.shields.io/badge/Sarvam_AI-STT_%2B_translation-6C47FF)

</div>

![Chiguru landing page, hero section](docs/images/screenshots/01-hero.jpg)

> **Chiguru** (ಚಿಗುರು) means *a new sprout* in Kannada. **Smart Krishi** (ಕೃಷಿ, *farming*) is the
> voice kiosk inside it. This repository holds the whole project: the 3D landing page, the
> ESP32 kiosk firmware, the PC bridge and the AI server.

## Contents

- [Problem statement](#problem-statement)
- [Our solution](#our-solution)
- [The hardware](#the-hardware)
- [Screenshots](#screenshots)
- [Features](#features)
- [Architecture](#architecture)
- [Why the answers can be trusted](#why-the-answers-can-be-trusted)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [API reference](#api-reference)
- [Hardware wiring](#hardware-wiring)
- [Knowledge base](#knowledge-base)
- [Testing](#testing)
- [Status and roadmap](#status-and-roadmap)
- [Team](#team)
- [Credits and licences](#credits-and-licences)

## Problem statement

Farmers need answers at the moment a problem appears: the tomato leaves are yellowing, the soil
looks dry, the fertilizer bag is open. The tools they have today fall short in four ways:

1. **Language and literacy.** Most farm apps and advisories are text-heavy and written in English
   or a formal register of the state language. Many farmers would rather *speak* their question,
   in their own words, often mixing Kannada and English the way people actually talk.
2. **Generic advice.** A leaflet or a video cannot tell whether *this* field is dry *right now*.
   Advice that ignores the farmer's own soil and weather is hard to act on.
3. **Wrong answers are expensive.** A guessed fertilizer dose or a made-up pesticide name wastes
   money, damages the soil and can harm health. General-purpose AI chatbots will happily invent
   such numbers.
4. **Experts are far away.** Agriculture officers and Krishi Vigyan Kendras (KVKs) give reliable
   advice, but are rarely reachable at the moment the question comes up.

## Our solution

**Chiguru** is an IoT farm assistant that a farmer simply talks to.

| | What it does |
|---|---|
| 🎙️ **Push-to-talk kiosk** | An ESP32 with a microphone, speaker and screen. Hold the button, ask, let go. No typing, no menus, no reading needed. |
| 🗣️ **Your language in, your language out** | Speech is recognised in Kannada, Hindi or English (and code-mixed speech). The answer is translated back and spoken in the same language. |
| 📚 **Grounded answers only** | Answers come from a curated agricultural knowledge base through retrieval-augmented generation (RAG) with Gemma 4. A grounding check rejects any sentence or number that is not in the source text. |
| 🌱 **Knows your field** | A sensor node (Arduino UNO Q + DHT11 + soil-moisture probe) reports readings. Soil and watering questions are answered with the latest reading, clearly labelled real, mock or stale. |
| 🤝 **Honest when unsure** | If the knowledge base has no answer, the kiosk says so and points the farmer to the local agriculture officer or KVK. |
| 🌐 **A public face** | A scroll-driven 3D landing page explains Chiguru to farmers, FPOs and partners, with copy in five Indian languages. |

## The hardware

<table>
  <tr>
    <td width="50%"><img src="docs/images/hardware/sensor-node.jpg" alt="Sensor node: Arduino UNO Q with a DHT11 and a soil moisture probe in a tray of soil" /></td>
    <td width="50%"><img src="docs/images/hardware/voice-kiosk.jpg" alt="Voice kiosk: ESP32 on breadboards with a TFT screen showing sensor readings in Kannada, and a speaker" /></td>
  </tr>
  <tr>
    <td><b>Sensor node.</b> Arduino UNO Q with a DHT11 (air temperature and humidity) on the mini
    breadboard and a soil-moisture probe (LM393 module) in a tray of soil.</td>
    <td><b>Voice kiosk.</b> ESP32 DevKit, MAX98357A amplifier and speaker, INMP441 microphone and an
    ILI9341 TFT. Here the screen shows the field readings in Kannada: ತಾಪಮಾನ (temperature) 28.2 °C,
    ಆರ್ದ್ರತೆ (humidity) and ಮಣ್ಣಿನ ತೇವಾಂಶ (soil moisture), with "sensor online, updated 10 s ago".</td>
  </tr>
</table>

## Screenshots

The landing page is one continuous camera flight through a 3D farm. Each section of the page
moves the camera to a new part of the farm.

| | |
|---|---|
| ![Your land section](docs/images/screenshots/02-your-land.jpg) | ![Ask Chiguru section](docs/images/screenshots/03-ask-chiguru.jpg) |
| **01 · Your Land.** Crop cards in Hindi, Kannada and Telugu over the wheat field. | **02 · Ask Chiguru.** Voice features beside the pasture and grazing cows. |
| ![Device section](docs/images/screenshots/04-device.jpg) | ![Impact section](docs/images/screenshots/05-impact.jpg) |
| **03 · The Device.** Sensor beacons and a holographic field scan over the crop rows, with labels in Tamil, Telugu and Bengali. | **04 · Impact.** Key numbers over the valley and the windmill. |
| ![Contact section](docs/images/screenshots/06-contact.jpg) | <img src="docs/images/screenshots/07-mobile.jpg" alt="Mobile view of the hero" width="260" /> |
| **05 · Contact.** The camera rises toward the mountains and the sun. | **Mobile.** The same scene adapts to a phone, with quality tuned to the device. |

## Features

**Voice kiosk (`firmware/`, `krishi_client.py`)**
- Push-to-talk on GPIO27: presses under 0.4 s are ignored, and recording stops by itself at 15 s.
- Mic audio streams to the PC while the button is held, so nothing piles up in the ESP32's RAM.
- Spoken answers stream back as 16 kHz 16-bit PCM, sent only against credit from the ESP32, so its 32 KB buffer cannot overflow.
- Screen states: `PC offline`, `ready`, `LISTENING` with a level bar, `PROCESSING`, `SPEAKING`, plus clear error states.
- Kannada and Hindi answers are spoken in that language. The TFT shows them in Latin script, because its built-in fonts are ASCII only.
- Fallbacks: a PC earphone mic (Ctrl+Alt+4), a text-only `--ask` mode, and a hardware self-test script.

**AI server (`server/`)**
- Hybrid retrieval: Gemini embeddings plus TF-IDF over Markdown chunks, cached on disk, with relevance gates.
- Gemma 4 through Google AI Studio, with a fallback model, or Gemma 3 running locally on Ollama.
- Grounding check on every answer, plus a verbatim knowledge-base fallback if Gemma is unreachable.
- Soil-sensor endpoint with an optional device key, persisted per device.
- Short follow-up questions reuse the topic of the previous question.

**Landing page (`src/`)**
- Procedural terrain, sky and fog shaders. Instanced grass, wheat, flowers and crop rows that sway in the wind and part under the pointer.
- Animated farmer (waves on click, follows the cursor), grazing cows, a tractor with exhaust and dust, a windmill, birds, butterflies and pollen.
- GSAP + Lenis scroll choreography, with floating glass cards tied to each section.
- Automatic quality tiers (GPU, memory, touch, screen size), adaptive resolution, `prefers-reduced-motion` support, and a painted fallback when WebGL is unavailable.

## Architecture

![Chiguru · Smart Krishi system architecture](docs/images/architecture.svg)

The ESP32 listens, shows and speaks. The PC does the recognition and the thinking. They talk over
the USB cable the board is flashed through, so there are no Wi-Fi credentials, IP addresses or
firewall rules on the critical path.

### One question, end to end

```mermaid
sequenceDiagram
    autonumber
    actor F as Farmer
    participant K as ESP32 kiosk
    participant C as krishi_client.py
    participant S as FastAPI server
    participant X as Cloud APIs

    F->>K: Holds the button and asks (Kannada)
    K->>C: REC:START, then MIC audio chunks over USB
    F->>K: Releases the button
    K->>C: REC:END
    C->>S: POST /api/krishi/transcribe (WAV)
    S->>X: Sarvam speech-to-text, language detection, translation to English
    S-->>C: text, language, English version
    C->>K: Q: the question (shown on the TFT)
    C->>S: POST /api/krishi/chat
    S->>S: Retrieve kb chunks (+ latest soil reading)
    S->>X: Gemma 4 with the retrieved context
    S->>S: Grounding check on every sentence and number
    S->>X: Sarvam translation back to Kannada
    S-->>C: answer, sources, audio_id
    C->>K: R: sources and A: answer (shown on the TFT)
    C->>S: GET /api/krishi/audio/ID.s16
    S->>X: edge-tts Kannada voice
    S-->>C: 16 kHz 16-bit PCM
    C->>K: AUD: speech, sent as the ESP32 grants credit
    K->>F: Speaks the answer
```

## Why the answers can be trusted

Farmers act on what they hear, so the server is built to refuse rather than guess:

- **Context only.** The prompt (`server/prompts.py`) lets Gemma answer only from the retrieved
  knowledge-base sections. Anything else returns `NOT_IN_KB`.
- **No invented doses.** Gemma may not state a fertilizer, manure, pesticide or water quantity
  unless that exact figure is in the context, and may not name a chemical product the context
  does not name. Dose questions are answered with the principle and "depends on your soil test /
  Soil Health Card".
- **Grounding check.** `server/grounding.py` verifies that every answer sentence, and every
  number, appears in the retrieved text. An answer that fails is replaced with "I don't have
  enough verified information".
- **Labelled sensor data.** A soil reading reaches Gemma as `REAL SENSOR READING`,
  `MOCK READING (simulated, not a real measurement)` or `STALE`, and Gemma must say so.
- **Prompt-injection safe.** The question and context are treated as untrusted data, never as instructions.
- **Traceable.** Every reply carries its source files and a `via` field:

| `via` | Meaning |
|---|---|
| `gemma` | Grounded answer from Gemma |
| `unknown` | Not enough verified information |
| `ungrounded` | Gemma's answer was rejected, for example for a number not in the knowledge base |
| `kb-direct` | Gemma was unreachable, so sentences were read verbatim from the knowledge base |
| `error` | Something failed. The farmer is asked to try again |

## Tech stack

| Layer | Technologies |
|---|---|
| **Landing page** | React 19, TypeScript, Vite 8, Three.js r187, React Three Fiber 9, drei 10, postprocessing, three-custom-shader-material, GSAP 3, Lenis, Fontsource (Fraunces, Manrope), oxlint |
| **Kiosk firmware** | ESP32 DevKit (`esp32dev`), Arduino framework on `espressif32` 6.9, PlatformIO, TFT_eSPI, ESP-IDF I2S driver, QRCode |
| **Kiosk hardware** | INMP441 I2S microphone, MAX98357A I2S amplifier + speaker, ILI9341 (or ST7789) SPI TFT, push button |
| **Sensor node** | Arduino UNO Q, DHT11, soil-moisture probe (LM393 module) |
| **Server** | Python 3, FastAPI, Uvicorn, Pydantic, httpx, NumPy, scikit-learn (TF-IDF), PyAV, python-dotenv |
| **Language model** | Gemma 4 (`gemma-4-26b-a4b-it`, fallback `gemma-4-31b-it`) via Google AI Studio, or `gemma3:4b` on Ollama |
| **Embeddings** | `gemini-embedding-001` + TF-IDF hybrid |
| **Speech** | Sarvam AI `saaras:v4` speech-to-text and translation, faster-whisper (offline option), Microsoft edge-tts (`en-IN-NeerjaNeural`, `kn-IN-SapnaNeural`, `hi-IN-SwaraNeural`) |
| **PC bridge** | pyserial, PyAudio, SciPy, Win32 global hotkey |
| **Tooling** | PowerShell launcher (`start.ps1`), `unittest`, ESP32 self-test script |

## Repository layout

```
.
├── src/                    Chiguru landing page (React + React Three Fiber)
│   ├── config/world.ts     farm layout and the camera shot for every section
│   ├── lib/                noise, terrain height, quality tiers, shared store
│   ├── three/              canvas, camera rig, sun, post-processing, shaders
│   │   └── world/          one file per scene element (grass, cows, tractor...)
│   └── ui/                 navigation, page sections, scroll + GSAP animations
├── public/                 optimised GLB models (meshopt + WebP) and ground textures
├── firmware/               ESP32 kiosk firmware (PlatformIO)
│   ├── include/config.h    pins, sample rates, timeouts, volume
│   └── src/main.cpp        push-to-talk, I2S mic + amp, TFT screens, USB protocol
├── server/                 FastAPI server
│   ├── app.py              /api/krishi/* endpoints and the answer pipeline
│   ├── rag.py              hybrid embeddings + TF-IDF retrieval
│   ├── llm.py              Gemma via Google AI Studio or Ollama
│   ├── prompts.py          farming rules (no invented doses, explain the reason)
│   ├── grounding.py        every sentence and number must be in the sources
│   ├── speech.py           Sarvam / Whisper STT, edge-tts, PCM conversion
│   ├── language.py         Kannada / Hindi <-> English via Sarvam
│   ├── soil.py             soil-sensor store (real / mock / stale)
│   └── tests/              unit tests
├── kb/                     agricultural knowledge base (Markdown)
├── krishi_client.py        PC <-> ESP32 bridge over USB serial
├── scripts/                ESP32 self-test, list available Gemini models
├── docs/HARDWARE.md        full pin map, protocol and troubleshooting
├── start.ps1               one-command launcher (server + kiosk link)
└── .env.example            every setting, documented
```

## Getting started

### 1. Landing page

Needs Node.js 20 or newer.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dist/
npm run preview    # serve the production build
```

- Force a quality tier with `?quality=high|medium|low`.
- Profile by switching subsystems off: `?off=grass,wheat,trees,post,shadows`.
- Where to edit: copy in `src/ui/Sections.tsx`, camera journey in `SHOTS_LANDSCAPE` / `SHOTS_PORTRAIT`
  (`src/config/world.ts`), sky colours in `PALETTE` (`src/three/shaders/chunks.ts`), and brand
  colours and fonts in the CSS variables at the top of `src/index.css`.

### 2. AI server and kiosk link (Windows)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # add GEMINI_API_KEY (Google AI Studio) and SARVAM_API_KEY
```

Then start everything with one command:

```powershell
.\start.ps1                 # server window + kiosk client on COM9
.\start.ps1 -Port COM5      # the ESP32 is on another port
.\start.ps1 -NoEsp32        # no kiosk: PC earphone mic (Ctrl+Alt+4) and PC speakers
```

On the kiosk: **hold the button, ask, let go.** To run the pieces by hand:

```powershell
cd server; ..\.venv\Scripts\python app.py                         # http://127.0.0.1:8001
..\.venv\Scripts\python krishi_client.py --esp32 COM9              # from the project root
..\.venv\Scripts\python krishi_client.py --ask "When should I water my crops?" --esp32 none
python scripts\esp32_selftest.py --port COM9                       # screen + speaker test, no server
```

The most useful `.env` settings:

| Setting | Default | Purpose |
|---|---|---|
| `LLM_BACKEND` | `gemini` | `gemini` (Google AI Studio) or `ollama` (local, offline) |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | `gemma-4-26b-a4b-it` / `gemma-4-31b-it` | Gemma models to call |
| `EMBED_MODEL` | `gemini-embedding-001` | Empty = TF-IDF keyword matching only |
| `STT_PROVIDER` | `sarvam` | `sarvam` (best for Kannada) or `whisper` (offline) |
| `KIOSK_LANGUAGES` | `en,kn,hi` | Languages the kiosk replies in |
| `KIOSK_LOUDNESS` | `6` | Soft-limiter drive for the speaker. `0` = unchanged |
| `SOIL_MOCK` | `1` | Use a clearly labelled mock reading until a real sensor posts |
| `SOIL_MAX_AGE_MIN` | `60` | Readings older than this are flagged `STALE` |
| `KRISHI_SENSOR_KEY` | empty | If set, the sensor must send it as `X-Device-Key` |
| `PORT` | `8001` | Server port |

### 3. Flash the ESP32 kiosk

Close anything holding the COM port first (a serial monitor or a running client).

```powershell
cd firmware
pio run -t upload           # COM9, as set in platformio.ini
pio device monitor          # 921600 baud; expect "[esp] Smart Krishi kiosk - push-to-talk"
```

If the screen is blank or the colours are wrong, flash the ST7789 build instead:
`pio run -e mithra_st7789 -t upload`.

### 4. Connect the sensor node

The sensor node posts a JSON reading to the server:

```bash
curl -X POST http://<PC-IP>:8001/api/krishi/soil-data \
  -H "Content-Type: application/json" \
  -H "X-Device-Key: <KRISHI_SENSOR_KEY, if set>" \
  -d '{"device_id": "krishi_sensor_01", "soil_moisture": 42, "crop": "tomato", "temperature": 28, "humidity": 65}'
```

`soil_moisture` and `humidity` must be 0 to 100, and `device_id` may contain letters, digits, `_`
and `-`. The latest reading per device is kept in `server/data/soil_latest.json`. Set
`SOIL_MOCK=0` once the real sensor is reporting.

## API reference

All endpoints live under `/api/krishi` on port 8001.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Status, chunk count, model, languages, mock flag |
| `POST` | `/chat` | `{"question", "session", "language": "en"/"kn"/"hi", "style"}` → `answer`, `sources`, `via`, `sensor`, `audio_id` |
| `POST` | `/voice` | Multipart `file` (WAV) → transcript and answer in one call |
| `POST` | `/transcribe` | Multipart `file` → text and language (used to show the question early) |
| `POST` | `/understand` | Typed Kannada / Hindi / English → English + display text |
| `GET` | `/audio/{id}.s16` | Spoken answer as 16-bit 16 kHz PCM for the MAX98357A. Also `.mp3` and `.u8` |
| `POST` | `/soil-data` | A reading from the sensor node |
| `GET` | `/soil-data/latest` | Newest reading, with `is_mock` and `age_minutes` |

Example:

```bash
curl -s http://127.0.0.1:8001/api/krishi/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What causes yellow leaves in tomato plants?", "language": "kn"}'
```

## Hardware wiring

**Power the ESP32 from USB only, and never put 5 V on a GPIO pin.** All grounds are joined.

| ESP32 | Connects to | Notes |
|---|---|---|
| 3V3 | TFT VCC + LED, INMP441 VDD and L/R, MAX98357A SD | 3.3 V |
| 5V (VIN) | MAX98357A VIN | The amplifier runs from USB 5 V |
| GPIO5 / 2 / 4 | TFT CS / DC / RESET | |
| GPIO23 / 18 / 19 | TFT MOSI / SCK / MISO | SPI |
| GPIO14 / 15 / 32 | INMP441 SCK / WS / SD | I2S0, microphone in |
| GPIO26 / 25 / 22 | MAX98357A BCLK / LRC / DIN | I2S1, speaker out |
| GPIO27 | Talk button → GND | `INPUT_PULLUP`, active low |

The kiosk and the PC talk over USB serial at 921600 baud with a line protocol (`Q:`, `A:`, `R:`,
`AUD:`, `HB`, `REC:START`, `MIC:`, `REC:END`, `C:` credit...). The full pin map, the protocol and a
troubleshooting table are in **[docs/HARDWARE.md](docs/HARDWARE.md)**.

## Knowledge base

Eight Markdown files in `kb/`:

| File | Topic |
|---|---|
| `01_soil_health.md` | Healthy soil, organic matter, soil testing, pH |
| `02_soil_moisture_and_irrigation.md` | When and how to water, drip irrigation, mulching |
| `03_fertilizers_and_nutrients.md` | N, P, K and micronutrients, and why doses depend on a soil test |
| `04_sustainable_alternatives.md` | Compost, vermicompost, green manure, biofertilizers, neem cake |
| `05_tomato_cultivation.md` | Growing tomatoes |
| `06_tomato_leaf_problems.md` | Yellow leaves, early blight, leaf curl, blossom end rot |
| `07_soil_sensor_guide.md` | Reading the soil sensor |
| `08_where_to_get_help.md` | Soil Health Card, KVK, Raitha Samparka Kendra |

Each `##` section is one retrieval chunk. To add a topic, drop a `.md` file with `##` sections into
`kb/` and restart the server. Embeddings are rebuilt and cached automatically.

> [!IMPORTANT]
> The knowledge base is **starter content** written from general agronomy guidance. It must be
> checked against the official package of practices (UAS Bangalore, KVK or the Department of
> Agriculture) before farmers rely on it. It deliberately contains **no fertilizer doses**.

## Testing

```powershell
cd server; ..\.venv\Scripts\python -m unittest discover -s tests
```

**28 server tests pass** (run on 12 Nov 2026). They cover the grounding check, language handling,
the Krishi API, rejection of invented doses, soil mock / real / stale labels, the sensor key and
the kiosk loudness limiter.

| Check | How |
|---|---|
| Server logic | `python -m unittest discover -s tests` |
| Firmware build | `pio run -e mithra_ili9341` |
| Kiosk hardware (link, screen, speaker) | `python scripts\esp32_selftest.py --port COM9` |
| Full pipeline without the board | `python krishi_client.py --ask "..." --esp32 none` |
| Poor recognition | Listen to `server/debug/last_kiosk_mic.wav` |

## Status and roadmap

**Working today:** the landing page, the AI server and its API, the PC bridge, the kiosk firmware
(push-to-talk, screen, speaker), and the prototype hardware in the photos above.

**Not in this repository yet:** the UNO Q sensor-node sketch, and the Kannada sensor dashboard
visible on the kiosk screen in the photo. The committed firmware draws ASCII text only.

**Next:**
- [ ] Commit the sensor-node sketch and the Kannada dashboard firmware
- [ ] Have an agronomist review the knowledge base, then add verified dose tables
- [ ] More crops beyond tomato, and more languages (Tamil, Telugu)
- [ ] Wi-Fi link so the kiosk can run without a PC next to it
- [ ] Connect the landing page contact form to a backend

## Team

- **Yadava H C**: Chiguru landing page and 3D scene
- **[Pavan Kumar H](https://github.com/Pavankumarh0)**: Smart Krishi kiosk, firmware and AI server

The kiosk is built on the team's earlier **Campus Mithra** voice kiosk: the same board, wiring,
USB protocol and server pipeline, pointed at agriculture.

## Credits and licences

- Farmer, cows, windmill, barn, silo, fence, hay bales and trees: **Quaternius**, CC0 (via poly.pizza)
- Tractor: **Poly by Google**, CC-BY 3.0 (attribution kept in the page footer)
- Soil and grass textures: **Poly Haven** (`brown_mud_02`, `grass_ground`), CC0
- Fonts: Fraunces and Manrope (SIL Open Font License), self-hosted via Fontsource
- Speech and language: Sarvam AI, Microsoft edge-tts. Language model: Google Gemma

The footer contact details (`hello@chiguru.example`, `+91 80 0000 0000`) are placeholders, and the
contact form only shows a confirmation.

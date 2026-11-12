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

**Dashboard:** title, temperature and humidity cards, a full-width **soil moisture %** card with a dry–wet bar, sensor online/stale/offline, PC and server link, and "Updated N s ago". The MQ-135 air-quality card was removed. MQ-135 is still read and stored, just not shown.
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

**Soil moisture %** = (DRY − RAW) / (DRY − WET) × 100, clamped to 0–100, computed on the UNO Q.

**Calibrated 12 Nov 2026 on this probe:**
- **DRY = 16370**: probe in air, steady at 16359–16379.
- **WET = 7950**: probe settled in water, 7942–7977.

These are in the board's `python/config.json` as `soil_dry_raw` and `soil_wet_raw`. The HW-080 is a resistive probe: in water its reading drifts upward over minutes (polarisation and corrosion of the prongs), so readings can creep. Recalibrate if values look off, and expect the prongs to corrode if the probe is powered continuously.

To recalibrate (until both values are set, the soil sensor reads "Not calibrated"):
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

## Touch screen and fertilizer recommendation

### Touch wiring (XPT2046 on the TFT module)

| Touch pin | ESP32 | Notes |
|---|---|---|
| T_CLK | GPIO18 | shared with TFT SCK |
| T_DIN | GPIO23 | shared with TFT MOSI |
| T_DO | GPIO19 | shared with TFT MISO |
| T_CS | GPIO21 | `TOUCH_CS=21` in `platformio.ini` |
| **T_IRQ** | **not connected** | GPIO22 is the MAX98357A **DIN** (speaker data). Wiring T_IRQ there would fight the audio line. The firmware polls touch pressure instead, so IRQ isn't needed |

**Calibrate once** (stored in the ESP32's flash). Touch does nothing until this is done:
1. **Press the screen firmly** anywhere for about ⅓ s. The calibration arrows appear.
2. Touch **exactly on the tip** of each corner arrow as it appears.
3. If the four touches don't span the screen, e.g. all in one spot, the calibration is rejected and repeated, up to 3 times. It is never saved. This calibration on 12 Nov: raw x 498–3827, y 400–3702.

Other ways to start it: hold the push button for 1.5 s while the board starts, or send `TCAL` over serial.
- Until calibrated, the dashboard footer says *Press screen firmly to set up touch*, and the boot log says `NOT calibrated`.
- `TRAW:20` over serial prints raw touch readings: z stays near 0 with no touch (this panel: 5–40). x/y stuck at 0 or 4095 even when pressed means T_CS or the shared SPI wiring is wrong.

### Using it
1. On the dashboard, tap **Fertilizer >**.
2. On the crop screen, pick a crop: Tomato, Paddy, Ragi, Maize or Onion.
3. Tap **Land: …** in the top bar to set the district where the land is (remembered).
4. Optionally tap **N / P / K** to enter the *Soil Health Card* rating. Each tap cycles **Auto** → Low → Med → High. Auto means the district's typical value (see below).
5. Set the **area** with − / + (0.25 to 10 acres), then tap **Recommend fertilizer**.
6. The result has four pages:
   - **Total** urea / DAP / MOP for the area.
   - **When to apply**: each stage with its products.
   - **Field now**: live sensor conditions.
   - **Why**: reasons and extras such as FYM, borax and zinc sulphate.

The physical button still works everywhere: tap returns to the dashboard, hold asks a question.

### How the recommendation is made (`server/fertilizer.py`)
- **Dose:** the official recommended dose and split schedule for the crop, from the TNAU Agritech portal (Tamil Nadu Agricultural University), retrieved 12 Nov 2026. Ragi uses its **Karnataka** irrigated recommendation. Every figure has its source URL and quote in the code and in `kb/09_recommended_fertilizer_doses.md`.

| Crop | N:P₂O₅:K₂O kg/ha | Schedule |
|---|---|---|
| Tomato (varieties) | 150:100:50 | ½ N + all P, K at planting; ½ N at 30 days / earthing up |
| Paddy (medium/long) | 150:50:50 | N and K in 4 equal splits: basal, tillering, panicle initiation, heading; P basal |
| Ragi (irrigated, Karnataka) | 100:50:50 | ½ N + all P, K at sowing; ¼ N at 30 and ¼ at 50 days |
| Maize (hybrid) | 150:75:75 | ¼ N + all P, K at sowing; ½ N at 25 days, ¼ at 45 days |
| Onion (Bellary) | 100:150:75 | ½ N + all P, K at planting; ½ N at 30 days |

- **Soil nutrient status**, for each of N, P and K:
  1. The farmer's **Soil Health Card** value, if entered.
  2. Otherwise the **district's typical status** from published soil surveys, marked `*` on screen with the source named on the *Why* page.
  3. Otherwise the general dose.
- **ICAR rule:** low = dose +25 %, high = −25 %, medium = the general dose.

| District | N | P | K | Source |
|---|---|---|---|---|
| Bengaluru | medium | high | medium | Avinash et al. 2026, *Mysore J. Agric. Sci.* 60(2): farm-land means N 384, P₂O₅ 109, K₂O 258 kg/ha (read in the paper) |
| Tumakuru | low | medium | medium | Bhattacharya & Chikkaramappa 2023, *Mysore J. Agric. Sci.* 57(2): means N 228, P₂O₅ 33.8, K₂O 211 kg/ha (read in the paper) |
| Kolar | low | high | high | nutrient-index study of tomato soils (search excerpt) |
| Hassan | medium | medium | low | geo-referenced fertility study (search excerpt) |
| Belagavi | low | medium | high | GIS fertility mapping, 160 samples (search excerpt) |
| Chikkaballapura | – | low | low | nutrient-index study; N not settled → general dose (search excerpt) |
| Other | – | – | – | general dose |

  District values are averages from soil surveys, not a test of the farmer's field. Kolar, Hassan, Belagavi and Chikkaballapura come from search excerpts of the papers, so verify them before relying on them. The default district is `KRISHI_REGION` in `.env` (`bengaluru`). Sources and URLs are in `server/fertilizer.py` (`REGIONS`).
- **Products:** P comes from DAP (18-46-0), whose N counts towards that stage; the rest of the N is urea (46 %); K comes from MOP (60 %). Doses are converted per stage, for the selected area.
- **Live sensors** don't measure N, P, K or pH, so they **never change the dose**. They give the field conditions (temperature, humidity, soil moisture if calibrated) and when to apply ("feel the soil, apply to moist soil, water lightly after").
- **Not included:**
  - **An ML model:** no trustworthy soil-crop training data or nutrient sensor. A model trained on made-up data gives made-up doses.
  - **Weather forecasts:** a Tomorrow.io-type API key would be needed.
  - **Hybrid-specific doses.**
- **Check before field use:** the figures come from TNAU, a university recommendation. Before field use, check them against UAS Bangalore's package of practices or the local agriculture officer.
- The same doses are in the knowledge base, so a spoken "how much fertilizer for ragi?" gives the same figures. A test checks the two match.

API: `GET /api/krishi/fertilizer/crops`; `POST /api/krishi/fertilizer {"crop","area_acres","n","p","k"}` returns the doses, products, stages, field conditions, sources and the screen pages.

## Screen language (English / Kannada / Hindi)

**At power-on the kiosk asks for the language.**
- Touch **English**, **ಕನ್ನಡ** or **हिंदी**. The push button moves the highlight, and after 20 s the highlighted one (the last choice, remembered) is taken.
- Change it later with **Language** at the bottom right of the dashboard.

**Everything on the screen then appears in that language:** dashboard, crop and fertilizer screens, chat statuses and bubbles. Voice answers also come in the screen language (Kanglish/Hinglish style if the question was asked that way).

**How it works:** the TFT fonts are ASCII only, so:
1. **Asking.** In Kannada or Hindi, the firmware's `uiDraw()` / `uiWrap()` asks the PC for each text the first time it is needed (`TRQ:`).
2. **Translating.** `krishi_client.py` (LabelWorker) has the server translate it (`POST /api/krishi/translate`, `server/ui_i18n.py`):
   - Numbers become placeholders, so "Urea {0} kg" is translated once for every value.
   - Hand-checked wording in **`server/ui_overrides.json`** wins.
   - Everything else is Sarvam machine translation, cached in `server/data/ui_translations.json`.
3. **Drawing.** The PC renders the text with HarfBuzz and the Nirmala UI font (`kiosk_text.render_label`) and sends a bitmap (`LB:`/`LR:`).
4. **Showing.** The kiosk keeps up to 64 KB of these. English shows until a label arrives. Fixed text triggers one redraw; a changing dashboard value repaints only its field.

The language screen's own words are built into the firmware (`firmware/include/lang_names.h`, from `scripts/make_lang_header.py`), so they show before the PC app is connected.

**Correcting a translation:** add or edit the English → Kannada/Hindi pair in `server/ui_overrides.json` (use `{0}` for numbers), then restart the server. Alternatively, delete the entry in `server/data/ui_translations.json` to have it re-translated. Machine translation gets short phrases mostly right, but not always: "When to apply" first came back as "when to submit an application" and is now overridden. **Have a Kannada and a Hindi speaker read through the screens.**

## Knowledge base additions (women farmers, schemes, pests, potato, coffee)

| File | Contents |
|---|---|
| `kb/10_women_farmers.md` | women decide on their farm, same advice for all; the 30 % rule for women farmers in agriculture schemes; MKSP; equal property rights (2005 amendment); KVK training |
| `kb/11_government_schemes.md` | PM-KISAN (₹6000/yr in 3 instalments, PIB); crop insurance PMFBY, Soil Health Card, drip/sprinkler support (no unverified amounts); where to ask; for today's crop prices see *Market prices* below |
| `kb/12_pest_management.md` | integrated pest management, traps; pink bollworm, fall armyworm, aphids, potato late blight, rice stem borer. Practices only: no pesticide names or doses |
| `kb/13_crop_diseases.md` | symptoms, conditions and non-chemical management of common diseases: paddy, ragi, maize, tomato, onion, potato, chilli, groundnut, banana, coffee; fungus / bacteria / virus signs. No fungicide names or doses |
| `kb/14_soil_types.md` | red, black, laterite, alluvial, sandy, forest, saline/alkaline soils (where in Karnataka, properties, crops, care); texture, pH, soil testing |
| `kb/09_recommended_fertilizer_doses.md` | + potato (UAS Bangalore, Hassan: 25 t FYM + 75:75:100 kg NPK/ha), + coffee split timing and the 40:30:40 per-split limit |

- **Potato** is the 6th crop on the fertilizer screen.
- **Coffee is not a fertilizer-screen crop.** The Coffee Board / CCRI dose table could not be retrieved and verified, so no coffee doses are given.
- **Real farmer questions:** put a free data.gov.in key in `.env` (`DATA_GOV_IN_API_KEY`), then run:
  1. `python eval\fetch_kcc.py <KCC resource id>`
  2. `python eval\run_eval.py --queries eval\queries_kcc.json --fresh`

## Any farming question (general AI)

When the knowledge base cannot answer a farming question, or Gemma fails, a Gemini model answers it from its general agricultural knowledge. It uses the same `GEMINI_API_KEY`; the model is set by `GENERAL_MODEL` (default `gemini-3-flash-preview`) and `GENERAL_FALLBACK_MODEL` (`gemini-flash-lite-latest`), each try limited to `GENERAL_TIMEOUT` seconds (15).
- **What it covers:** crops, livestock, dairy, poultry, fisheries, beekeeping, machinery, irrigation, schemes, marketing and more (`via: "general"`, source `general_knowledge`).
- **Off-topic questions** get "I can only help with farming and agriculture questions."
- **Safety rules:**
  - Answers with any amount and unit (kg, ml, litre...) are dropped, because only the documents and the fertilizer screen give verified doses.
  - It never guesses prices, weather or sensor readings.
  - Fertilizer answers get the safety warning.
- Verified documents are always tried first. `GENERAL_AI=0` turns this off.

## Market prices (today's crop rates)

**Source:** AGMARKNET daily mandi prices, through the data.gov.in API ("Current Daily Price of Various Commodities from Various Markets"). Put a free data.gov.in key in `.env` as `DATA_GOV_IN_API_KEY`.
- A question with a price word (price, rate, cost, mandi, market, bhav...) **and** a crop name (tomato, onion, ragi, paddy, maize, chilli, coconut, arecanut... see `server/prices.py`) gets today's prices as live data: up to 4 markets in `KRISHI_STATE` (default Karnataka, the farm's district first), or all India if no market in the state reported it.
- Prices are rupees per quintal (100 kg); the answer names the market and the date. The numbers are checked against the API data like sensor readings.
- **Backup: web search.** Without the key, or if no market reported the crop today, a Gemini model with Google Search looks up the latest reported mandi price (`via: "price-web"`). It is used only if it is backed by a web page and states a rupee figure. This needs Google Search grounding quota on the `GEMINI_API_KEY` project (the free tier may refuse it with HTTP 429). `PRICE_WEB_SEARCH=0` turns it off.
- **If neither works,** the kiosk says so and points to Agmarknet or the nearest APMC.
- **Spelling:** "prize", "bhav", "daam", "keemat" and local crop names (tamatar, pyaz, eerulli, aloo...) are recognised. Fertilizer prices (urea etc.) are not covered.

## Fertilizer safety warning

Every fertilizer answer from the AI, and every page of the fertilizer screen (as a footer above the buttons), ends with one sentence: *"Pregnant women, children and the elderly should not handle fertilizers; wash hands after use."* (`fertilizer.SAFETY_WARNING`).

## Weather and rain alert

**Source:** OpenWeatherMap, using `WEATHER_API_KEY` in `.env`.
- Weather is fetched for the farm's district (`KRISHI_REGION`, or `KRISHI_LAT` / `KRISHI_LON`) and cached for 10 minutes. Endpoint: `GET /api/krishi/weather`.

**The dashboard's weather strip** shows an icon, the temperature and a rain message:
- **red** when it is raining now, or rain is likely (≥ 50 % in the next 12 h);
- **amber** when rain is possible (≥ 30 %).

When a rain alert starts, the kiosk **chimes twice**. Rain also reaches:
- the fertilizer result: "wait to apply urea until the rain has passed, because rain can wash nitrogen away";
- the chatbot: questions about weather or rain get the forecast as live data.

## Farmer feedback (stars)

After the result pages, **Rate >** opens **5 stars**. The farmer touches one, the rating is saved with the crop, area, district and doses (`POST /api/krishi/feedback` → `server/data/feedback.jsonl`), a thank-you shows, and the kiosk returns to the dashboard. `GET /api/krishi/feedback/summary` gives the count and average stars, per crop.

## Why a fertilizer is recommended

The result has 5 pages: totals → **Why these fertilizers** → when to apply → why this amount → field now.

**Why these fertilizers:**
- **Urea** gives nitrogen (46 % N), for leaf and stem growth. It is split because nitrogen is easily lost.
- **DAP** gives phosphorus (46 % P₂O₅) and some N (18 %), for roots and flowering, so all of it goes in at the start.
- **MOP** gives potassium (60 % K₂O), for fruit size and quality, water use and stress resistance.

These are the nutrient roles in `kb/03_fertilizers_and_nutrients.md`, and a test checks the wording matches.

**Why this amount:** names whether each nutrient's rating came from the soil card or the district survey, and the resulting ±25 %.

## Languages, loudness, knowledge base

- **Languages:** English, Kannada and Hindi (`KIOSK_LANGUAGES=en,kn,hi`). Kanglish and Hinglish questions get Kanglish/Hinglish answers, and pure Kannada/Hindi get pure answers, as in Campus Mithra. The TFT shows Latin script.
- **Kannada / Hindi on the screen:** the TFT fonts are ASCII only, and Kannada/Devanagari need shaping (vowel signs, conjuncts).
  - The PC renders those questions and answers itself (`kiosk_text.py`: HarfBuzz + the Windows *Nirmala UI* font, 18 px) and sends them as 1-bit bitmaps (`GQ:`/`GA:`/`GR:` lines).
  - Kanglish answers keep their English words. Up to 12 pages, turned while the answer is spoken.
  - If the libraries or font are missing, the screen falls back to Latin letters. Needs `uharfbuzz` and `freetype-py` (in `requirements.txt`).
- **Soil sensor monitor**: `.\.venv\Scripts\python scripts\soil_monitor.py` streams one line per reading (raw value, change, what it means); `--last 30` shows recent readings. It works while the kiosk is running. The raw log, from the PC:
  `& "$env:LOCALAPPDATA\Arduino15\packages\arduino\tools\adb\32.0.0\adb.exe" shell arduino-app-cli app logs /home/arduino/ArduinoApps/smart-krishi-sensors --follow`
  (one line per reading: `soil_raw=…`, faults). Or open the app in App Lab: the sketch's own Serial Monitor lines also show the sample spread.
- **Speaker loudness:** `KIOSK_LOUDNESS` (default 6, 0 = Campus Mithra's level). It is a soft limiter applied before the firmware's 2x gain.
- **Knowledge base (`kb/`)** is **starter content, not yet verified**. Its only fertilizer doses are the sourced ones in `09_recommended_fertilizer_doses.md`. Check it against the official package of practices (UAS Bangalore / KVK) before farmers rely on it.
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

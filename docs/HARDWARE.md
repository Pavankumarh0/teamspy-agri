# Smart Krishi - Hardware setup

**Identical to the Campus Mithra kiosk: same board, same wiring, same pins.** Only the firmware's branding text differs. RFID (GPIO16) stays switched off (`RFID_ENABLED 0`) and is not used by Smart Krishi.

The ESP32 is the kiosk: a farmer **holds the talk button and speaks** into the
INMP441 microphone, lets go, and hears the answer from the MAX98357A speaker
while it is shown on the TFT. The PC does the recognition and the thinking.

```
 talk button (GPIO27)
        │ hold
        ▼
 INMP441 ──I2S0──► ESP32 ──USB serial 921600──► PC: krishi_client.py
                    │  ▲                            │
                    │  │                       server: Sarvam STT
                    │  │                            │
                    │  │                       Gemma + RAG over kb/*.md (agriculture)
                    │  │                            │
                    │  └── speech, 16 kHz 16-bit ◄─ edge-tts
                    ├──► TFT          question, answer, source file
                    └──I2S1──► MAX98357A ──► speaker
```

**Power the ESP32 from USB only. Never put 5 V on a GPIO pin.**

## Pin map

| ESP32 | Goes to | Notes |
|---|---|---|
| 3V3 | TFT VCC + LED, INMP441 VDD, INMP441 L/R, MAX98357A SD | 3.3 V |
| 5V (VIN) | MAX98357A VIN | the amp runs from USB 5 V |
| GND | TFT, INMP441, MAX98357A, button | **all grounds joined** |
| GPIO5 | TFT CS | |
| GPIO2 | TFT DC | |
| GPIO4 | TFT RESET | |
| GPIO23 | TFT SDI (MOSI) | |
| GPIO18 | TFT SCK | |
| GPIO19 | TFT SDO (MISO) | optional |
| GPIO14 | INMP441 SCK | I2S0 bit clock |
| GPIO15 | INMP441 WS | I2S0 word select (a strapping pin, safe here: the ESP32 drives it) |
| GPIO32 | INMP441 SD | I2S0 data in; the firmware enables its pull-down |
| GPIO26 | MAX98357A BCLK | I2S1 bit clock |
| GPIO25 | MAX98357A LRC | I2S1 word select |
| GPIO22 | MAX98357A DIN | I2S1 data out |
| GPIO27 | talk button → GND | INPUT_PULLUP, active low |

No pin is shared with the TFT, and the mic and the amplifier are on separate I2S
peripherals. MAX98357A GAIN is left unconnected (9 dB).

**GPIO25 used to drive the PAM8403 from the DAC.** Make sure nothing from the old
amplifier is still attached to it: it now carries the MAX98357A's 16 kHz word
clock, which an analog amplifier would play as a loud whine.

**About L/R = 3V3:** that puts the INMP441 in the right I2S slot. On the ESP32,
which buffer slot that lands in has varied between IDF versions, so the firmware
reads both and picks the live one at boot. On this board, measured: **slot 0**.

## Stage 1 - Flash

Close anything holding COM9 (serial monitor, `krishi_client.py`), then:

```powershell
cd firmware
pio run -t upload
pio device monitor        # 921600 baud
```

Expected:

```
[esp] Smart Krishi kiosk - push-to-talk
[esp] TFT driver 0x9341 240x320  CS=5 DC=2 RST=4
[esp] speaker MAX98357A  BCLK=26 LRC=25 DIN=22  16000 Hz 16-bit  volume 60  ok
[esp] mic INMP441  SCK=14 WS=15 SD=32  16000 Hz  ok
[esp] mic slots: [0] sd=... flat=0%  [1] sd=0 flat=100%  -> slot 0
[esp] talk button GPIO27 (hold to talk)
[esp] ready
```

The TFT shows **PC offline** until the PC app is running - that is correct.

| Problem | Fix |
|---|---|
| `mic slots: ... both slots flat` | INMP441 not delivering data: check VDD=3V3, GND, SCK=14, WS=15, SD=32 |
| `ERR:mic I2S ...` / `ERR:speaker I2S ...` | Driver failed to start - the pin numbers in `include/config.h` |
| Blank or garbled screen | As before: try `pio run -e mithra_st7789 -t upload` |
| Build fails with `CreateProcess: No such file or directory` | The `C:\pio` junction is missing - see the top of `platformio.ini` |

## Stage 2 - The whole kiosk

```powershell
.\start.ps1
```

The kiosk boots into the **farm dashboard**. **Tap** the button (under 0.4 s) to switch between the dashboard and the chat screen; **hold the button → speak → let go** to ask a question from either screen.

| On the TFT | Meaning |
|---|---|
| PC offline | `krishi_client.py` is not running; presses are ignored |
| ready | waiting for a press |
| LISTENING + level bar | recording while the button is held |
| PROCESSING | recognising and answering |
| SPEAKING | the answer is playing |

Presses are ignored while an answer is being prepared or spoken, and each
recording needs a fresh press. A press shorter than 0.4 s is a tap (screen
switch, its audio is discarded); recording stops by itself at 15 s.

The PC keeps the last recording at `server/debug/last_kiosk_mic.wav` - listen
to it if recognition is poor.

| Problem | Fix |
|---|---|
| "No sound from the microphone" | The INMP441 sent no data - Stage 1 table |
| Recognition is poor | Listen to `last_kiosk_mic.wav`. Speak within ~30 cm. If it clips, lower `MIC_GAIN_BITS` in `config.h`; if faint, raise it |
| Speaker silent but text appears | The PC needs internet for edge-tts; check the server window for `TTS failed`. Check VIN=5V and SD=3V3 on the amp |
| Speaker distorted | Lower the volume: `python krishi_client.py --volume 40`; the default firmware applies 2x digital gain with peak saturation |
| ESP32 resets when the answer plays | The USB port cannot supply the amp's peaks: a better cable/port, or power the MAX98357A from a separate 5 V supply with grounds joined |

## Protocol

PC → ESP32 (one line each): `HB`, `IDLE`, `Q:`, `R:`, `A:`, `S:`, `AUD:<bytes>`,
`VOL:<0-100>`, `CLR`, `BEEP`, `PING`; for testing `MICREC:<ms>` (record as if the
button were held), `MICRAW:<ms>` (raw I2S words of both slots), `MICSLOT:<0|1>`.

ESP32 → PC: `REC:START`, then `MIC:<n>` + n bytes of 16-bit 16 kHz PCM while the
button is held, then `REC:END <bytes> <ms>` on release (or `REC:CANCEL`). During
answer playback: `C:<bytes>` credits and `DONE:<bytes>,<gaps>`.

Speech to the speaker is sent only against credit, so the 32 KB buffer cannot
overflow; mic audio is streamed as it is captured, so nothing accumulates in RAM.
The full description is at the top of `firmware/src/main.cpp`.

## Fallbacks

- **PC earphone mic:** `python krishi_client.py --pc-mic` - Ctrl+Alt+4 to talk, as
  before. The kiosk still shows and speaks the answer.
- **Wi-Fi:** the working kiosk uses USB serial, not Wi-Fi. Campus Mithra keeps an older Wi-Fi variant in `archive/firmware-wifi-kiosk/` (ADC mic, DAC speaker); it is not part of Smart Krishi.

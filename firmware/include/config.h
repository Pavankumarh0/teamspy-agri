#pragma once
// Smart Krishi kiosk (forked from Campus Mithra, same wiring) - tunables. TFT pins are build flags in platformio.ini.
//
// Pin map (no conflicts with the TFT on 2, 4, 5, 18, 19, 23):
//   INMP441 mic  (I2S0, RX)   SCK 14   WS 15   SD 32   L/R -> 3V3 (right slot)
//   MAX98357A    (I2S1, TX)   BCLK 26  LRC 25  DIN 22  SD -> 3V3 (always on)
//   Talk button               GPIO27 -> button -> GND  (INPUT_PULLUP)

// ---------- LINK TO THE PC ----------
// Must match monitor_speed in platformio.ini and BAUD in krishi_client.py.
// 16 kHz 16-bit mic audio is 32 KB/s; 921600 baud carries ~92 KB/s.
#define SERIAL_BAUD       921600

// ---------- TALK BUTTON ----------
#define BTN_TALK          27
#define BTN_DEBOUNCE_MS   25
#define REC_MIN_MS        400      // shorter presses are ignored (an accidental tap)
#define REC_MAX_MS        15000    // recording stops here even if still held

// ---------- INMP441 MICROPHONE ----------
#define MIC_PORT          I2S_NUM_0
#define MIC_SCK           14
#define MIC_WS            15
#define MIC_SD            32
#define MIC_RATE          16000    // what Sarvam prefers
// The INMP441 sends 24-bit samples left-aligned in 32-bit slots. Converting to
// 16-bit keeps the top 16 bits; each extra bit here doubles the level (+6 dB).
// Speech at arm's length sits around -40 dBFS, so +12 dB uses the 16-bit range
// better without clipping a normal voice. The PC normalises again afterwards.
#define MIC_GAIN_BITS     2

// ---------- MAX98357A SPEAKER ----------
#define AMP_PORT          I2S_NUM_1
#define AMP_BCLK          26
#define AMP_LRC           25
#define AMP_DIN           22
#define PLAY_RATE         16000    // must equal ESP_I2S_RATE in the server .env
#define PLAY_VOLUME       100      // 0-100 at boot (full scale); the PC can lower it with VOL:<n>
#define SPEAKER_GAIN      2        // 2x digital gain (+6 dB), saturating peaks to prevent integer wrap
// The MAX98357A's own gain is set by its GAIN pin, not by software:
//   GAIN to GND through 100k = 15 dB (loudest)   GAIN to GND = 12 dB
//   GAIN unconnected         =  9 dB (as wired)   GAIN to VIN =  6 dB
// For more volume than full-scale samples give, rewire GAIN, not this number.

// ---------- AUDIO BUFFERING ----------
// Speech arrives faster than it plays; the PC only sends what fits here (credit
// flow control), so this can never overflow however long the answer is.
#define AUDIO_RING_BYTES  32768    // 1 s of 16 kHz 16-bit
#define AUDIO_PREBUFFER   6144     // ~0.2 s before playback starts
#define AUDIO_CREDIT_STEP 2048
#define AUDIO_TIMEOUT_MS  3000     // give up if the PC goes quiet mid-answer

// ---------- PC LINK HEALTH ----------
#define PC_ALIVE_MS       7000     // the PC sends HB every 2 s; silence longer = offline
#define BUSY_TIMEOUT_MS   90000    // longest wait for an answer after releasing

// ---------- RFID CARD READER LINK (UNO Q -> ESP32, receive only) ----------
// Frames "RFID:<UID>\n" from the UNO Q's Serial1 (D1/TX). docs/RFID_PROTOCOL.md
//   UNO Q D1/TX -> GPIO16 (UART2 RX), UNO Q GND -> GND. GPIO16 is not used by
//   anything above. UART2's TX is NOT attached, so GPIO17 stays free.
//   ESP32-WROVER modules use GPIO16/17 for PSRAM: this pin choice assumes the
//   DevKit V1's ESP32-WROOM-32 (check the can's marking). docs/RFID_WIRING.md
// RFID attendance is switched OFF for now: 0 builds the kiosk without the
// card reader link (GPIO16 unused). Set 1 (or -D RFID_ENABLED=1 in
// platformio.ini) to bring it back; the UNO Q sketch is in archive/rfid/.
#ifndef RFID_ENABLED
#define RFID_ENABLED        0
#endif
#define RFID_UART_NUM       2
#define RFID_RX_PIN         16
#define RFID_BAUD           115200   // must equal LINK_BAUD in the UNO Q sketch
#define RFID_RX_BUFFER      1024     // the UNO Q's boot banner fits while the loop draws
#define RFID_MAX_BYTES_POLL 64       // bytes parsed per loop pass, so a burst can't stall audio
#define RFID_SAME_CARD_MS   2000     // the same UID again within this = one tap
#define RFID_QUEUE_LEN      8        // taps waiting for the PC while an answer is playing
#define RFID_MAX_AGE_MS     120000   // taps older than this are dropped, not forwarded

/*
 * Smart Krishi - ESP32 voice kiosk: push-to-talk mic, TFT, I2S speaker
 *
 * Forked from the Campus Mithra kiosk firmware. Pins, audio, protocol and
 * screen layout are unchanged; only the branding text differs.
 *
 *   hold button -> INMP441 (I2S) -> USB serial -> PC: Sarvam STT -> Gemma + RAG
 *                                                         |
 *   TFT  <------ question, answer, source <---------------+
 *   MAX98357A (I2S) <--- spoken answer (edge-tts, 16 kHz 16-bit) <---+
 *
 * The ESP32 listens, shows and speaks; the PC does the recognition and the
 * thinking. They talk over the USB cable the board is already flashed through:
 * no Wi-Fi credentials, no IP address, no firewall rule in the failure path.
 *
 * ---------------------------------------------------------------------------
 * Talk button (GPIO27 to GND, INPUT_PULLUP)
 * ---------------------------------------------------------------------------
 *   press and hold -> recording starts, streamed to the PC as it is captured
 *   release        -> recording ends; the kiosk waits for the answer (PROCESSING)
 *   Presses while an answer is being prepared or spoken are ignored, and a new
 *   recording needs a fresh press, so one press can never submit twice.
 *
 * ---------------------------------------------------------------------------
 * Protocol, PC -> ESP32: one command per line, '\n' terminated
 * ---------------------------------------------------------------------------
 *   HB            heartbeat; the kiosk shows "PC offline" if these stop
 *   IDLE          the PC has finished with the last recording; accept a new press
 *   Q:<text>      the visitor's question, shown in the top panel
 *   QR:<url>      render a route deep link as a QR code on the TFT
 *   R:<files>     knowledge-base file(s) the answer came from; send before A:
 *   A:<text>      the answer, shown in the bottom panel (paged if long)
 *   S:<text>      one-line status in the title bar
 *   L:[prompt]    PC-mic fallback: show "Listening... speak now"
 *   M:<0-100>     PC-mic fallback: live microphone level
 *   AUD:<bytes>   spoken answer follows: <bytes> of signed 16-bit little-endian
 *                 mono PCM at PLAY_RATE, sent ONLY as the ESP32 grants credit
 *   VOL:<0-100>   speaker volume
 *   CLR           back to the idle screen
 *   BEEP          short chime
 *   PING          replies PONG
 *   MICREC:<ms>   test: record for <ms> exactly as if the button were held
 *   MICRAW:<ms>   test: stream raw 32-bit stereo I2S words, to check the mic slot
 *   MICSLOT:<0|1> force which I2S slot holds the mic (normally detected at boot)
 *
 * ESP32 -> PC
 *   PONG                   reply to PING
 *   REC:START              the talk button was pressed; mic audio follows
 *   MIC:<n>\n<n bytes>     n bytes of signed 16-bit little-endian mono PCM, 16 kHz
 *   REC:END <bytes> <ms>   button released: the recording is complete
 *   REC:CANCEL <reason>    recording discarded (too short); nothing to answer
 *   RAW:<n>\n<n bytes>     MICRAW data
 *   C:<bytes>              credit: the PC may send this many more audio bytes
 *   DONE:<bytes>,<gaps>    playback finished; gaps = times the buffer ran dry
 *   RFID:<uid> age=<ms>    an RFID card was tapped <ms> ago (UNO Q reader on
 *                          GPIO16, docs/RFID_PROTOCOL.md); sent only while idle
 *   ERR:<message>          something went wrong
 *   [esp] <text>           log line, for humans
 *
 * ---------------------------------------------------------------------------
 * Hardware - no pin is shared with the TFT (MOSI 23, SCLK 18, CS 5, DC 2,
 * RST 4, MISO 19). The mic and the amplifier use separate I2S peripherals.
 *   INMP441    I2S0 RX   SCK 14  WS 15  SD 32   (L/R -> 3V3)
 *   MAX98357A  I2S1 TX   BCLK 26 LRC 25 DIN 22  (SD -> 3V3)
 *   Button     GPIO27 -> GND
 *   RFID link  UART2 RX GPIO16 <- UNO Q D1/TX (receive only; rfid_receiver.cpp)
 *
 * Only one program can hold the COM port: close `pio device monitor` before
 * starting krishi_client.py.
 */

#include <Arduino.h>
#include <TFT_eSPI.h>
#include <qrcode.h>
#include <driver/i2s.h>
#include <driver/gpio.h>
#include <math.h>
#include <Preferences.h>
#include "config.h"
#include "rfid_receiver.h"

TFT_eSPI tft = TFT_eSPI();

static const int16_t SCREEN_W = 320;     // landscape (rotation 1)
static const int16_t SCREEN_H = 240;

// ---------------------------------------------------------------------------
// Campus Mithra UI palette shared with the web and Flutter apps:
// cream canvas, ink headers/outlines, paper cards, orange, sun and mint.
// ---------------------------------------------------------------------------
static const uint16_t COL_BG     = 0xF4F8;   // cream #e9dcc5
static const uint16_t COL_CARD   = 0x18C2;   // ink #1d1a16
static const uint16_t COL_SAFF   = 0xEBC4;   // tangerine #ee7a22
static const uint16_t COL_SUN    = 0xF5E7;   // sun #f1bd3b
static const uint16_t COL_SAFF_D = 0x18C2;   // ink outline
static const uint16_t COL_TEAL   = 0x55B3;   // mint #56b49c
static const uint16_t COL_MINT_D = 0x2BAC;   // dark mint for readable text
static const uint16_t COL_FACE   = 0x18C2;   // ink face plate
static const uint16_t COL_CAP    = 0x18C2;   // ink graduation cap
static const uint16_t COL_EYE    = 0xFF9C;   // paper
static const uint16_t COL_PUPIL  = 0x18C2;   // ink
static const uint16_t COL_CHEEK  = 0xFB2C;   // soft pink
static const uint16_t COL_BUBBLE = 0xFF9C;   // paper card #f7f0e3
static const uint16_t COL_INK    = 0x18C2;   // ink text
static const uint16_t COL_MUTE   = 0x5AA8;   // muted brown #5f5446
static const uint16_t COL_TEXT   = 0xFF9C;   // paper on ink
static const uint16_t COL_DIM    = 0x9CCF;   // secondary ink

static const size_t MAX_LINE = 600;          // longest text line accepted
static uint32_t messageCount = 0;

// While a route QR fills the screen nothing else may draw on it: the face
// would blink and glance over the code and make it unscannable. Moods still
// change; the next bubble screen (button press, answer...) redraws the face,
// and the QR goes back to the idle screen after QR_SHOW_MS.
static bool qrShown = false;
static uint32_t qrSinceMs = 0;
static const uint32_t QR_SHOW_MS = 120000;



// ---------------------------------------------------------------------------
// Text sanitising
// ---------------------------------------------------------------------------

/*
 * The built-in TFT_eSPI fonts hold ASCII 32..126 only. Kannada and Hindi need a
 * generated custom font, which is a separate job; until then each UTF-8
 * sequence becomes a single '?' rather than mojibake.
 */
static void sanitiseAscii(const char *in, char *out, size_t outSize, bool *dropped) {
  size_t o = 0;
  *dropped = false;
  for (size_t i = 0; in[i] != '\0' && o + 1 < outSize; i++) {
    uint8_t c = (uint8_t)in[i];
    if (c >= 0x20 && c <= 0x7E) { out[o++] = (char)c; continue; }
    if (c == '\t') { out[o++] = ' '; continue; }
    if (c < 0x80) continue;
    *dropped = true;
    out[o++] = '?';
    while (((uint8_t)in[i + 1] & 0xC0) == 0x80) i++;
  }
  out[o] = '\0';
}


// ---------------------------------------------------------------------------
// Word wrap with paging
// ---------------------------------------------------------------------------

/*
 * Lays out `text` from `start`, word-wrapped into at most maxLines lines of
 * maxW pixels, drawing them only when `draw` is set. Returns the offset of the
 * first character it could not place - the start of the next page.
 *
 * One function does both measuring and drawing, so the page breaks computed
 * up front are exactly the ones drawn later.
 */
static size_t wrapPass(const char *text, size_t start, uint8_t font,
                       int16_t maxW, int maxLines, bool draw,
                       int16_t x, int16_t y, uint16_t colour, uint16_t bg) {
  if (maxLines <= 0) return start;
  const int16_t lineH = tft.fontHeight(font) + 2;
  if (draw) { tft.setTextColor(colour, bg); tft.setTextDatum(TL_DATUM); }

  static char line[MAX_LINE + 1];
  static char cand[MAX_LINE + 1];
  size_t lineLen = 0;
  int lines = 0;
  size_t i = start;
  while (text[i] == ' ') i++;

  while (text[i] != '\0') {
    const size_t ws = i;
    while (text[i] != '\0' && text[i] != ' ') i++;
    const size_t wl = i - ws;

    size_t c = 0;
    if (lineLen) { memcpy(cand, line, lineLen); c = lineLen; cand[c++] = ' '; }
    size_t copy = wl;
    if (c + copy > MAX_LINE) copy = MAX_LINE - c;
    memcpy(cand + c, text + ws, copy);
    c += copy;
    cand[c] = '\0';

    // A word that is first on its line is placed even if too wide, so an
    // over-long token (a URL) cannot stall the layout forever.
    if (lineLen == 0 || tft.textWidth(cand, font) <= maxW) {
      memcpy(line, cand, c + 1);
      lineLen = c;
      while (text[i] == ' ') i++;
      continue;
    }

    if (draw) tft.drawString(line, x, y + lines * lineH, font);
    lines++;
    lineLen = 0;
    if (lines >= maxLines) return ws;   // page full - next page starts here
    i = ws;                             // place this word on the new line
  }

  if (lineLen) {
    if (draw) tft.drawString(line, x, y + lines * lineH, font);
  }
  return i;
}

static int linesFor(uint8_t font, int16_t h) {
  return h / (tft.fontHeight(font) + 2);
}


// ---------------------------------------------------------------------------
// Route QR code
// ---------------------------------------------------------------------------

/*
 * The visitor scans this to continue on a phone with live GPS guidance. The
 * URL only names the destination: no credentials or API key reach the ESP32.
 *
 * Phone cameras need dark modules on light with a 4-module quiet zone (an
 * inverted code fails on many phones), and read bigger modules from further
 * away, so the smallest QR version that holds the URL is used at the largest
 * scale that fits the screen. The library does not check capacity itself.
 */
static const uint8_t QR_MAX_VERSION = 10;
static const uint8_t QR_QUIET = 4;
// Byte-mode capacity of versions 1..10 (ISO 18004, table 7).
static const uint16_t QR_CAP_L[QR_MAX_VERSION] = {17, 32, 53, 78, 106, 134, 154, 192, 230, 271};
static const uint16_t QR_CAP_M[QR_MAX_VERSION] = {14, 26, 42, 62, 84, 106, 122, 152, 180, 213};

static void drawQr(const char *url, const char *label) {
  const size_t len = strlen(url);
  uint8_t version = 0, ecc = ECC_LOW;
  for (uint8_t v = 1; v <= QR_MAX_VERSION && !version; v++) {
    if (len <= QR_CAP_M[v - 1]) { version = v; ecc = ECC_MEDIUM; }   // same size, more robust
    else if (len <= QR_CAP_L[v - 1]) { version = v; ecc = ECC_LOW; }
  }
  if (!version) return;   // the caller limits the URL length

  QRCode qr;
  uint8_t data[qrcode_getBufferSize(QR_MAX_VERSION)];
  qrcode_initText(&qr, data, version, ecc, url);

  const int16_t modules = qr.size + 2 * QR_QUIET;
  const int16_t scale = (SCREEN_H - 8) / modules;
  const int16_t side = modules * scale;
  const int16_t left = 4, top = (SCREEN_H - side) / 2;
  const int16_t qx = left + QR_QUIET * scale, qy = top + QR_QUIET * scale;

  qrShown = true;
  qrSinceMs = millis();
  tft.fillScreen(COL_BG);
  tft.fillRect(left, top, side, side, TFT_WHITE);   // the white box is the quiet zone
  for (uint8_t y = 0; y < qr.size; y++)
    for (uint8_t x = 0; x < qr.size; x++)
      if (qrcode_getModule(&qr, x, y))
        tft.fillRect(qx + x * scale, qy + y * scale, scale, scale, TFT_BLACK);

  // Right-hand panel: what this code is for and where it leads.
  const int16_t px = left + side + 8, pw = SCREEN_W - px - 4;
  int16_t y = top + 2;
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COL_INK, COL_BG);
  // Next to a large QR the panel is narrow (~80 px): "Scan me" in the big font
  // would run off the screen, so it becomes "Scan" + "this for live...".
  const bool wide = tft.textWidth("Scan me", 4) <= pw;
  tft.drawString(wide ? "Scan me" : "Scan", px, y, 4);
  y += tft.fontHeight(4) + 2;
  wrapPass(wide ? "for live walking directions" : "this for live walking directions", 0, 2, pw, 3, true,
           px, y, COL_MUTE, COL_BG);
  y += 3 * (tft.fontHeight(2) + 2) + 6;
  const int hintLines = 4;
  const int16_t hintY = SCREEN_H - 4 - hintLines * (tft.fontHeight(1) + 2);
  if (label && *label) {
    tft.drawFastHLine(px, y - 4, pw, COL_DIM);
    wrapPass(label, 0, 2, pw, linesFor(2, hintY - y - 4), true, px, y, COL_INK, COL_BG);
  }
  wrapPass("Opens the map on your phone and follows you.", 0, 1, pw, hintLines, true,
           px, hintY, COL_MUTE, COL_BG);
}


// ---------------------------------------------------------------------------
// Title bar
// ---------------------------------------------------------------------------

static const int16_t BAR_H = 20;

// ---------------------------------------------------------------------------
// Screen mode: the farm dashboard (default at boot) or the voice chat screen.
// A short button tap switches between them; holding the button records (see
// loop()). While the dashboard is up, the chat screen's drawing functions do
// nothing (their state still updates), and the chat screen is redrawn whole
// when it comes back - the same approach as the route QR above.
// ---------------------------------------------------------------------------
enum UiMode { UI_DASH, UI_CHAT, UI_CROP, UI_FERT };   // + crop selection, fertilizer result
static UiMode ui = UI_DASH;
static bool pcAlive();
static void chatPump();                         // keeps the mic flowing during long redraws

static void drawTitleBar(const char *status) {
  if (qrShown || ui != UI_CHAT) return;         // the QR / dashboard use the whole screen
  tft.fillRect(0, 0, SCREEN_W, BAR_H, COL_CARD);
  tft.fillCircle(10, BAR_H / 2, 4, COL_SUN);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(COL_TEXT, COL_CARD);
  tft.drawString("SMART KRISHI AI", 20, BAR_H / 2 + 1, 2);
  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(COL_DIM, COL_CARD);
  tft.drawString(status, SCREEN_W - 6, BAR_H / 2 + 1, 2);
}


// ---------------------------------------------------------------------------
// The buddy - Mithra, a little robot in a graduation cap
// ---------------------------------------------------------------------------
//
// Only the parts that move (eyes, mouth, the "z z" / "..." above the head) are
// redrawn, each inside its own small rectangle, so the animation costs well
// under a millisecond per frame and never disturbs the audio streams.

enum Mood { MOOD_SLEEPY, MOOD_IDLE, MOOD_LISTEN, MOOD_THINK, MOOD_TALK, MOOD_HAPPY, MOOD_CONFUSED };
static Mood mood = MOOD_SLEEPY;
static uint32_t moodSinceMs = 0;

// Geometry (left third of the screen).
static const int16_t FACE_CX = 64;
static const int16_t HEAD_X = 10, HEAD_Y = 66, HEAD_W = 108, HEAD_H = 96, HEAD_R = 26;
static const int16_t PLATE_X = 19, PLATE_Y = 77, PLATE_W = 90, PLATE_H = 74, PLATE_R = 20;
static const int16_t EYE_L = 44, EYE_R = 84, EYE_Y = 104, EYE_RAD = 12;
static const int16_t MOUTH_Y = 132;

static int8_t gazeX = 0, gazeY = 0;
static bool eyesClosed = false;
static uint32_t nextBlinkMs = 0, blinkEndMs = 0, nextGazeMs = 0, lastFxMs = 0, lastMouthMs = 0;
static uint8_t fxFrame = 0;
// Where the animated "thinking" dots go inside the bubble (0 = none shown).
static int16_t thinkX = 0, thinkY = 0;
static float talkLevel = 0.0f;          // 0..1, from the audio being played
static int16_t mouthShown = -1;

static void drawEyes() {
  // clear the whole eye band on the face plate
  tft.fillRect(EYE_L - EYE_RAD - 3, EYE_Y - EYE_RAD - 3, (EYE_R - EYE_L) + 2 * EYE_RAD + 7,
               2 * EYE_RAD + 7, COL_FACE);
  const int16_t xs[2] = {EYE_L, EYE_R};
  for (int e = 0; e < 2; e++) {
    const int16_t x = xs[e];
    if (mood == MOOD_SLEEPY || eyesClosed) {
      // closed: a soft downward curve
      tft.fillRoundRect(x - 10, EYE_Y - 1, 20, 4, 2, COL_EYE);
      tft.fillRect(x - 10, EYE_Y - 1, 3, 2, COL_FACE);
      tft.fillRect(x + 7, EYE_Y - 1, 3, 2, COL_FACE);
      continue;
    }
    if (mood == MOOD_HAPPY) {
      // ^ ^ eyes
      tft.drawWideLine(x - 9, EYE_Y + 4, x, EYE_Y - 5, 4, COL_EYE, COL_FACE);
      tft.drawWideLine(x, EYE_Y - 5, x + 9, EYE_Y + 4, 4, COL_EYE, COL_FACE);
      continue;
    }
    int16_t r = EYE_RAD, pr = 5;
    if (mood == MOOD_LISTEN) { r = EYE_RAD + 1; pr = 6; }          // wide, attentive
    if (mood == MOOD_CONFUSED && e == 1) { r = EYE_RAD - 3; pr = 4; }
    tft.fillCircle(x, EYE_Y, r, COL_EYE);
    int16_t gx = gazeX, gy = gazeY;
    if (mood == MOOD_THINK) { gx = 4; gy = -5; }                   // looking up, thinking
    tft.fillCircle(x + gx, EYE_Y + gy, pr, COL_PUPIL);
    tft.fillCircle(x + gx + 2, EYE_Y + gy - 2, 2, COL_EYE);       // a glint
  }
}

/* level: 0..1 mouth opening while talking; ignored for the other moods. */
static void drawMouth(float level) {
  tft.fillRect(FACE_CX - 22, MOUTH_Y - 10, 44, 22, COL_FACE);
  switch (mood) {
    case MOOD_TALK: {
      const int16_t h = 2 + (int16_t)(level * 10.0f);
      tft.fillRoundRect(FACE_CX - 11, MOUTH_Y - h / 2, 22, h + 2, (h + 2) / 2, COL_EYE);
      if (h > 5) tft.fillRect(FACE_CX - 6, MOUTH_Y + h / 2 - 2, 12, 2, COL_CHEEK);   // tongue
      break;
    }
    case MOOD_LISTEN:
      tft.fillCircle(FACE_CX, MOUTH_Y, 5, COL_EYE);                  // a little "o"
      tft.fillCircle(FACE_CX, MOUTH_Y, 2, COL_FACE);
      break;
    case MOOD_THINK:
      tft.fillRoundRect(FACE_CX - 6, MOUTH_Y - 1, 14, 3, 1, COL_EYE); // hmm
      break;
    case MOOD_SLEEPY:
      tft.fillRoundRect(FACE_CX - 5, MOUTH_Y - 1, 10, 3, 1, COL_EYE);
      break;
    case MOOD_CONFUSED:
      tft.drawWideLine(FACE_CX - 10, MOUTH_Y + 2, FACE_CX - 3, MOUTH_Y - 2, 3, COL_EYE, COL_FACE);
      tft.drawWideLine(FACE_CX - 3, MOUTH_Y - 2, FACE_CX + 4, MOUTH_Y + 2, 3, COL_EYE, COL_FACE);
      tft.drawWideLine(FACE_CX + 4, MOUTH_Y + 2, FACE_CX + 10, MOUTH_Y - 2, 3, COL_EYE, COL_FACE);
      break;
    case MOOD_HAPPY:
    case MOOD_IDLE:
    default: {
      // A smile: the bottom crescent of a ring. Kept low enough that the parts
      // painted out in face colour never reach the eyes above it.
      const int16_t r = mood == MOOD_HAPPY ? 11 : 9;
      const int16_t cy = MOUTH_Y - 3;
      tft.fillCircle(FACE_CX, cy, r, COL_EYE);
      tft.fillCircle(FACE_CX, cy - 3, r, COL_FACE);
      tft.fillRect(FACE_CX - r - 1, cy - r - 1, 2 * r + 3, r + 1, COL_FACE);
      break;
    }
  }
}

static void drawCheeks(bool on) {
  const uint16_t c = on ? COL_CHEEK : COL_FACE;
  tft.fillCircle(PLATE_X + 11, MOUTH_Y - 6, 5, c);
  tft.fillCircle(PLATE_X + PLATE_W - 12, MOUTH_Y - 6, 5, c);
}

/* Three dots that pulse one after another, after "Let me check" in the bubble. */
static void drawThinkDots() {
  if (!thinkX) return;
  for (int i = 0; i < 3; i++) {
    const bool lit = (fxFrame % 3) == i;
    tft.fillCircle(thinkX + i * 11, thinkY, 4, COL_BUBBLE);
    tft.fillCircle(thinkX + i * 11, thinkY, lit ? 4 : 2, lit ? COL_SAFF : COL_MUTE);
  }
}

static void drawBuddy() {
  // body
  tft.fillRect(0, BAR_H, 128, SCREEN_H - BAR_H, COL_BG);
  tft.fillRoundRect(FACE_CX - 30, HEAD_Y + HEAD_H + 6, 60, 52, 16, COL_TEAL);
  tft.fillRect(FACE_CX - 8, HEAD_Y + HEAD_H - 2, 16, 10, COL_SAFF_D);              // neck
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_TEXT, COL_TEAL);
  tft.drawString("K", FACE_CX, HEAD_Y + HEAD_H + 28, 4);
  // arms
  tft.fillRoundRect(FACE_CX - 42, HEAD_Y + HEAD_H + 12, 12, 34, 6, COL_TEAL);
  tft.fillRoundRect(FACE_CX + 30, HEAD_Y + HEAD_H + 12, 12, 34, 6, COL_TEAL);
  // head
  tft.fillRoundRect(HEAD_X - 2, HEAD_Y - 2, HEAD_W + 4, HEAD_H + 4, HEAD_R + 2, COL_SAFF_D);
  tft.fillRoundRect(HEAD_X, HEAD_Y, HEAD_W, HEAD_H, HEAD_R, COL_SAFF);
  tft.fillCircle(HEAD_X - 2, HEAD_Y + HEAD_H / 2, 7, COL_SAFF_D);                  // ears
  tft.fillCircle(HEAD_X + HEAD_W + 2, HEAD_Y + HEAD_H / 2, 7, COL_SAFF_D);
  tft.fillRoundRect(PLATE_X, PLATE_Y, PLATE_W, PLATE_H, PLATE_R, COL_FACE);
  // graduation cap: a diamond board on a band, with a tassel
  tft.fillRoundRect(FACE_CX - 26, HEAD_Y - 12, 52, 16, 4, COL_CAP);
  tft.fillTriangle(FACE_CX, HEAD_Y - 36, FACE_CX + 54, HEAD_Y - 22, FACE_CX, HEAD_Y - 8, COL_CAP);
  tft.fillTriangle(FACE_CX, HEAD_Y - 36, FACE_CX - 54, HEAD_Y - 22, FACE_CX, HEAD_Y - 8, COL_CAP);
  tft.fillCircle(FACE_CX, HEAD_Y - 22, 3, COL_TEAL);
  tft.drawWideLine(FACE_CX, HEAD_Y - 22, FACE_CX + 46, HEAD_Y - 18, 2, COL_TEAL, COL_CAP);
  tft.drawWideLine(FACE_CX + 46, HEAD_Y - 18, FACE_CX + 46, HEAD_Y + 2, 2, COL_TEAL, COL_BG);
  tft.fillRoundRect(FACE_CX + 43, HEAD_Y + 1, 7, 10, 2, COL_TEAL);
  mouthShown = -1;
  drawEyes();
  drawMouth(0);
  drawCheeks(mood == MOOD_HAPPY || mood == MOOD_TALK);
}

static void setMood(Mood m) {
  if (m == mood) return;
  mood = m;
  moodSinceMs = millis();
  eyesClosed = false;
  gazeX = gazeY = 0;
  fxFrame = 0;
  mouthShown = -1;
  if (qrShown || ui != UI_CHAT) return;         // drawn when the chat screen comes back
  drawEyes();
  drawMouth(0);
  drawCheeks(m == MOOD_HAPPY || m == MOOD_TALK);
}

/* Called every loop: blinking, glancing around, the "z z" and "..." and the
   mouth moving with the speech. Everything is time-based and non-blocking. */
static void buddyTick() {
  if (qrShown || ui != UI_CHAT) return;         // no blinking over the QR code / dashboard
  const uint32_t now = millis();

  // a happy or confused face relaxes back to idle after a few seconds
  if ((mood == MOOD_HAPPY || mood == MOOD_CONFUSED) && now - moodSinceMs > 3500) setMood(MOOD_IDLE);

  // blinking
  if (mood == MOOD_IDLE || mood == MOOD_LISTEN || mood == MOOD_TALK) {
    if (!eyesClosed && now >= nextBlinkMs) {
      eyesClosed = true;
      blinkEndMs = now + 130;
      drawEyes();
    } else if (eyesClosed && now >= blinkEndMs) {
      eyesClosed = false;
      nextBlinkMs = now + 2200 + (esp_random() % 3000);
      drawEyes();
    }
  }

  // glancing around while idle
  if (mood == MOOD_IDLE && !eyesClosed && now >= nextGazeMs) {
    static const int8_t GX[] = {0, 4, -4, 3, 0, -3};
    static const int8_t GY[] = {0, 1, 1, -3, 3, -2};
    const int k = esp_random() % 6;
    gazeX = GX[k];
    gazeY = GY[k];
    nextGazeMs = now + 1500 + (esp_random() % 2500);
    drawEyes();
  }

  // the thinking dots in the bubble
  if (mood == MOOD_THINK && thinkX && now - lastFxMs > 300) {
    fxFrame++;
    lastFxMs = now;
    drawThinkDots();
  }

  // lip-sync
  if (mood == MOOD_TALK && now - lastMouthMs > 60) {
    lastMouthMs = now;
    const int16_t q = (int16_t)(talkLevel * 5.0f);           // 6 mouth shapes
    if (q != mouthShown) {
      mouthShown = q;
      drawMouth(q / 5.0f);
    }
  }
}


// ---------------------------------------------------------------------------
// Speech bubble (right two thirds)
// ---------------------------------------------------------------------------

static const int16_t BUB_X = 136, BUB_Y = BAR_H + 6, BUB_W = SCREEN_W - 136 - 4;
static const int16_t BUB_H = SCREEN_H - BUB_Y - 4, BUB_R = 12;
static const int16_t IN_X = BUB_X + 9, IN_W = BUB_W - 18, IN_TOP = BUB_Y + 8;
static const int16_t IN_BOTTOM = BUB_Y + BUB_H - 8;
static const int16_t FOOT_Y = IN_BOTTOM - 14;                 // source + page counter

static void drawBubble() {
  if (qrShown) {                                // a new screen takes the QR down:
    qrShown = false;                            // bring back the title bar and face
    tft.fillScreen(COL_BG);
    drawTitleBar("ready");
    drawBuddy();
  }
  thinkX = 0;                                   // whatever was in the bubble is gone
  tft.fillRect(128, BAR_H, SCREEN_W - 128, SCREEN_H - BAR_H, COL_BG);
  tft.fillRoundRect(BUB_X, BUB_Y, BUB_W, BUB_H, BUB_R, COL_BUBBLE);
  tft.drawRoundRect(BUB_X, BUB_Y, BUB_W, BUB_H, BUB_R, COL_INK);
  // tail pointing at Mithra's mouth
  tft.fillTriangle(BUB_X + 1, MOUTH_Y - 16, BUB_X + 1, MOUTH_Y + 2, BUB_X - 12, MOUTH_Y - 2, COL_BUBBLE);
  tft.drawTriangle(BUB_X + 1, MOUTH_Y - 16, BUB_X + 1, MOUTH_Y + 2, BUB_X - 12, MOUTH_Y - 2, COL_INK);
}

/* A short headline (large font if it fits) and a body text. */
static void bubbleMessage(const char *headline, const char *body, uint16_t headColour = COL_MINT_D) {
  if (ui != UI_CHAT) return;
  drawBubble();
  int16_t y = IN_TOP + 4;
  if (headline && headline[0]) {
    const uint8_t f = tft.textWidth(headline, 4) <= IN_W ? 4 : 2;
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(headColour, COL_BUBBLE);
    tft.drawString(headline, IN_X, y, f);
    y += tft.fontHeight(f) + 8;
  }
  if (body && body[0]) {
    wrapPass(body, 0, 2, IN_W, linesFor(2, IN_BOTTOM - y), true, IN_X, y, COL_INK, COL_BUBBLE);
  }
}

// --- the visitor's question + Mithra's answer, paged -------------------------

static const int MAX_PAGES = 12;
static char   questionText[MAX_LINE + 1] = "";
static char   answerText[MAX_LINE + 1];
static char   answerSource[80] = "";     // knowledge-base file(s) the answer came from
static size_t pageStart[MAX_PAGES + 1];
static int    pageCount = 0;
static int    pageShown = -1;
static int16_t answerTop = IN_TOP;

// --- Kannada / Hindi: text drawn on the PC --------------------------------------
//
// The TFT fonts are ASCII only, and Kannada / Devanagari need shaping (vowel
// signs, conjuncts), so the PC renders such questions and answers itself
// (kiosk_text.py: HarfBuzz + the Nirmala UI font) and sends 1-bit bitmaps,
// IN_W pixels wide, before the Q: / A: line they belong to:
//   GQ:<w>,<h>          question strip, then h  "GR:<hex>" rows
//   GA:<w>,<h>,<pages>  answer pages,   then h*pages "GR:<hex>" rows
// A row is (w+7)/8 bytes in hex, MSB = leftmost pixel; trailing zero bytes may
// be left out (an empty row is blank). Q: / A: then show the bitmaps; without
// them (English, or the PC could not render) the Latin text is shown as before.
static const int GFX_BPR = (IN_W + 7) / 8;
static const int GFX_Q_MAX_H = 60;
static const int GFX_A_MAX_H = 170;
static uint8_t gfxQ[GFX_Q_MAX_H * GFX_BPR];
static uint8_t gfxA[MAX_PAGES * GFX_A_MAX_H * GFX_BPR];
static int  gfxQH = 0, gfxAH = 0, gfxAPages = 0;
static int  gfxTarget = 0;                      // receiving: 0 nothing, 1 question, 2 answer
static int  gfxRowsWant = 0, gfxRowsGot = 0;
static bool gfxQReady = false, gfxAReady = false;   // complete, waiting for its Q: / A:
static bool gfxQShown = false, gfxAShown = false;   // the current screen uses them

static void gfxForget() {
  gfxQShown = gfxAShown = gfxQReady = gfxAReady = false;
  gfxTarget = 0;
}

/* Blits a 1-bit bitmap as runs of one colour (one SPI burst per run), clipped
   at maxY. A page turn mid-speech costs a few ms, so the audio never starves. */
static void drawGfx(const uint8_t *rows, int h, int16_t x, int16_t y, int16_t maxY, uint16_t fg, uint16_t bg) {
  if (y + h > maxY) h = maxY - y;
  if (h <= 0) return;
  tft.startWrite();
  tft.setAddrWindow(x, y, IN_W, h);
  for (int r = 0; r < h; r++) {
    const uint8_t *row = rows + r * GFX_BPR;
    bool on = false;
    uint32_t run = 0;
    for (int c = 0; c < IN_W; c++) {
      const bool px = row[c >> 3] & (0x80 >> (c & 7));
      if (px != on && run) { tft.pushColor(on ? fg : bg, run); run = 0; }
      on = px;
      run++;
    }
    tft.pushColor(on ? fg : bg, run);
  }
  tft.endWrite();
}

/* GQ: / GA: header -> start receiving rows. */
static void gfxBegin(int target, const char *args) {
  int w = 0, h = 0, pages = 1;
  const int n = sscanf(args, "%d,%d,%d", &w, &h, &pages);
  const int maxH = target == 1 ? GFX_Q_MAX_H : GFX_A_MAX_H;
  if (n < 2 || w != IN_W || h < 0 || h > maxH || pages < 1 || pages > (target == 1 ? 1 : MAX_PAGES)) {
    Serial.printf("ERR:gfx header rejected (w=%d h=%d pages=%d)\n", w, h, pages);
    gfxTarget = 0;
    return;
  }
  gfxTarget = target;
  gfxRowsWant = h * pages;
  gfxRowsGot = 0;
  if (target == 1) { gfxQH = h; gfxQReady = false; memset(gfxQ, 0, sizeof gfxQ); }
  else { gfxAH = h; gfxAPages = pages; gfxAReady = false; memset(gfxA, 0, (size_t)h * pages * GFX_BPR); }
  if (gfxRowsWant == 0) {                       // nothing to receive
    if (target == 1) gfxQReady = true; else gfxAReady = true;
    gfxTarget = 0;
  }
}

static inline int hexNibble(char c) {
  return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* GR: one row. */
static void gfxRow(const char *hex) {
  if (!gfxTarget || gfxRowsGot >= gfxRowsWant) return;
  uint8_t *dst = (gfxTarget == 1 ? gfxQ : gfxA) + (size_t)gfxRowsGot * GFX_BPR;
  for (int i = 0; i < GFX_BPR && hex[2 * i] && hex[2 * i + 1]; i++) {
    const int hi = hexNibble(hex[2 * i]), lo = hexNibble(hex[2 * i + 1]);
    if (hi < 0 || lo < 0) break;
    dst[i] = (uint8_t)(hi << 4 | lo);
  }
  if (++gfxRowsGot == gfxRowsWant) {
    if (gfxTarget == 1) gfxQReady = true; else gfxAReady = true;
    Serial.printf("[esp] %s text received (%d rows)\n", gfxTarget == 1 ? "question" : "answer", gfxRowsGot);
    gfxTarget = 0;
  }
}

/* Draws the question strip at the top of the bubble; returns the y below it. */
static int16_t drawQuestionStrip() {
  if (gfxQShown) {
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(COL_MUTE, COL_BUBBLE);
    tft.drawString("You asked", IN_X, IN_TOP, 1);
    const int16_t qTop = IN_TOP + 10;
    drawGfx(gfxQ, gfxQH, IN_X, qTop, FOOT_Y, COL_MINT_D, COL_BUBBLE);
    const int16_t bottom = qTop + gfxQH + 3;   // kiosk_text.ANSWER_GAP = 3 + 5
    tft.drawFastHLine(IN_X, bottom, IN_W, 0xD6BA);
    return bottom + 5;
  }
  if (!questionText[0]) return IN_TOP + 2;
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COL_MUTE, COL_BUBBLE);
  tft.drawString("You asked", IN_X, IN_TOP, 1);
  const int16_t qTop = IN_TOP + 10;
  wrapPass(questionText, 0, 2, IN_W, 2, true, IN_X, qTop, COL_MINT_D, COL_BUBBLE);
  // how many lines did it take (1 or 2)?
  const size_t one = wrapPass(questionText, 0, 2, IN_W, 1, false, 0, 0, 0, 0);
  const int lines = questionText[one] ? 2 : 1;
  const int16_t bottom = qTop + lines * (tft.fontHeight(2) + 2) + 3;
  tft.drawFastHLine(IN_X, bottom, IN_W, 0xD6BA);
  return bottom + 5;
}

static void drawAnswerPage(int page) {
  if (ui != UI_CHAT) return;
  if (page < 0 || page >= pageCount) return;
  drawBubble();
  answerTop = drawQuestionStrip();
  if (gfxAShown) {
    drawGfx(gfxA + (size_t)page * gfxAH * GFX_BPR, gfxAH, IN_X, answerTop, FOOT_Y - 2, COL_INK, COL_BUBBLE);
  } else {
    wrapPass(answerText, pageStart[page], 2, IN_W, linesFor(2, FOOT_Y - answerTop - 2),
             true, IN_X, answerTop, COL_INK, COL_BUBBLE);
  }
  // footer: where it came from, and which page
  tft.setTextDatum(BL_DATUM);
  tft.setTextColor(COL_MUTE, COL_BUBBLE);
  if (answerSource[0]) {
    char src[sizeof(answerSource) + 6];
    snprintf(src, sizeof(src), "from %s", answerSource);
    size_t len = strlen(src);
    while (len > 6 && tft.textWidth(src, 1) > IN_W - 26) {
      src[--len] = '\0';
      src[len - 1] = '.';
      src[len - 2] = '.';
    }
    tft.drawString(src, IN_X, IN_BOTTOM, 1);
  }
  if (pageCount > 1) {
    char counter[12];
    snprintf(counter, sizeof(counter), "%d/%d", page + 1, pageCount);
    tft.setTextDatum(BR_DATUM);
    tft.drawString(counter, IN_X + IN_W, IN_BOTTOM, 1);
  }
  pageShown = page;
}

/* "Let me check" with pulsing dots, under the question if there is one yet. */
static void drawThinkingBubble() {
  if (ui != UI_CHAT) return;
  drawBubble();
  const int16_t y = drawQuestionStrip() + 6;
  const char *msg = questionText[0] ? "Let me check" : "Hmm, one moment";
  const uint8_t f = tft.textWidth(msg, 4) + 36 <= IN_W ? 4 : 2;
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COL_INK, COL_BUBBLE);
  tft.drawString(msg, IN_X, y, f);
  thinkX = IN_X + tft.textWidth(msg, f) + 8;
  thinkY = y + tft.fontHeight(f) - 7;
  drawThinkDots();
}

static void showQuestion(const char *text) {
  bool dropped = false;
  sanitiseAscii(text, questionText, sizeof(questionText), &dropped);
  gfxQShown = gfxQReady;                       // the PC sent this question in Kannada/Hindi script
  gfxQReady = false;
  gfxAShown = false;
  drawThinkingBubble();
  if (dropped) Serial.println(F("[esp] non-ASCII characters shown as '?'"));
}

/*
 * Splits the answer into pages that fit under the question strip. Long answers
 * turn their pages automatically while they are spoken.
 */
static void showAnswer(const char *text) {
  bool dropped = false;
  sanitiseAscii(text, answerText, sizeof(answerText), &dropped);
  const size_t len = strlen(answerText);

  if (gfxQReady) { gfxQShown = true; gfxQReady = false; }   // re-sent with the answer
  if (gfxAReady) {                             // pages already laid out by the PC
    gfxAReady = false;
    gfxAShown = true;
    pageCount = gfxAPages;
    drawAnswerPage(0);
    return;
  }
  gfxAShown = false;

  // the strip's height decides how much room each page has
  drawBubble();
  answerTop = drawQuestionStrip();
  const int lines = linesFor(2, FOOT_Y - answerTop - 2);

  pageCount = 0;
  size_t at = 0;
  while (pageCount < MAX_PAGES) {
    pageStart[pageCount++] = at;
    const size_t next = wrapPass(answerText, at, 2, IN_W, lines, false, 0, 0, 0, 0);
    if (next >= len || next == at) break;
    at = next;
  }
  pageStart[pageCount] = len;
  drawAnswerPage(0);
  if (dropped) Serial.println(F("[esp] non-ASCII characters shown as '?'"));
}

// --- screens -------------------------------------------------------------------

static void drawIdleBubble() {
  bubbleMessage("Namaskara!", "Hold the button and ask me about crops, soil, watering, "
                              "fertilizers or your farm. Tap it for the dashboard.");
}

static void drawOfflineBubble() {
  bubbleMessage("Zzz...", "I'm asleep. Start the PC app (start.ps1) to wake me up.", COL_MUTE);
}

static void drawIdleScreen() {
  qrShown = false;
  tft.fillScreen(COL_BG);
  drawTitleBar("ready");
  questionText[0] = '\0';
  answerSource[0] = '\0';
  pageCount = 0;
  gfxForget();
  mood = MOOD_IDLE;
  drawBuddy();
  drawIdleBubble();
}


// ---------------------------------------------------------------------------
// Listening: Mithra's attentive face and a live voice meter in the bubble
// ---------------------------------------------------------------------------

static const int METER_BARS = 15;
static uint8_t meterHist[METER_BARS];

static void drawListening(const char *prompt) {
  questionText[0] = '\0';
  answerSource[0] = '\0';
  pageCount = 0;
  gfxQShown = gfxAShown = false;
  setMood(MOOD_LISTEN);
  bubbleMessage(prompt, "I'm all ears - let go of the button when you're done.");
  memset(meterHist, 0, sizeof(meterHist));
  drawTitleBar("LISTENING");
}

/* The voice meter: a row of bars along the bottom of the bubble that scrolls
   as the visitor speaks. lvl is 0-100. */
static void drawLevel(int lvl) {
  if (ui != UI_CHAT) return;
  lvl = lvl < 0 ? 0 : lvl > 100 ? 100 : lvl;
  memmove(meterHist, meterHist + 1, METER_BARS - 1);
  meterHist[METER_BARS - 1] = (uint8_t)lvl;
  const int16_t h = 44, bottom = IN_BOTTOM - 4;
  const int16_t barW = (IN_W - (METER_BARS - 1) * 3) / METER_BARS;
  tft.fillRect(IN_X, bottom - h, IN_W, h + 1, COL_BUBBLE);
  for (int i = 0; i < METER_BARS; i++) {
    const int16_t bh = 3 + (int16_t)((h - 3) * meterHist[i] / 100);
    const int16_t x = IN_X + i * (barW + 3);
    tft.fillRoundRect(x, bottom - bh, barW, bh, 2, meterHist[i] > 15 ? COL_SAFF : COL_TEAL);
  }
}
// ---------------------------------------------------------------------------
// Farm dashboard (Mode A)
// ---------------------------------------------------------------------------
//
// The readings come from the UNO Q sensor device via the server; the PC app
// fetches them and sends one line every 5 s over this same USB link:
//   D:st=online;age=4;t=28.5;h=31;sr=16363;sv=0;sp=;mq=1748;mv=1;srv=ok;dev=unoq_soil_01;td=0
// An empty value means "not available" and is shown as "--". Nothing here is
// ever made up: the soil card says "Not calibrated" until the device sends a
// calibrated percentage, and MQ-135 is shown as the raw number it is.
//
// The frame (header, cards, labels) is drawn once; after that only a field
// whose text or colour changed is repainted, so the screen never flickers.

static const uint16_t D_BG   = 0x09E5;   // #0f3d2e deep field green
static const uint16_t D_BAR  = 0x0123;   // #062619
static const uint16_t D_CARD = 0x1AE8;   // #1a5c43
static const uint16_t D_LEAF = 0x8E8F;   // #8bd17c
static const uint16_t D_TEXT = 0xFFFF;
static const uint16_t D_MUTE = 0xB698;   // #b7d3c2
static const uint16_t D_DIM  = 0x7C70;   // #7a8f80 old / unavailable values
static const uint16_t D_WARN = 0xF5E7;   // #f1bd3b
static const uint16_t D_BAD  = 0xE289;   // #e5534b

// Touch buttons (XPT2046, see "Touch screen" further down). Rectangles in
// screen pixels, landscape 320x240.
struct Btn { int16_t x, y, w, h; };
static bool touchReady = false;           // calibrated; until then taps are ignored
static const Btn BTN_FERT = {204, 4, 110, 22};

static bool hit(const Btn &b, uint16_t x, uint16_t y) {
  return x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h;
}

static void drawBtn(const Btn &b, const char *label, uint16_t fill, uint16_t fg, uint8_t font = 2) {
  tft.fillRoundRect(b.x, b.y, b.w, b.h, 6, fill);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fg, fill);
  tft.drawString(label, b.x + b.w / 2, b.y + b.h / 2 + 1, font);
}

static struct {
  bool have;                 // any D: line received since boot
  bool srvOk, sv, mv, td;
  long age;                  // seconds since the server got the reading, when sent (-1 none)
  uint32_t rxMs;             // when the D: line arrived
  char st[10], t[10], h[10], sr[10], sp[10], mq[10], dev[26];
} dd;

struct DField { char txt[40]; uint16_t fg; bool drawn; };
enum { F_V0, F_V1, F_V2, F_V3, F_S0, F_S1, F_S2, F_S3, F_SENSOR, F_LINK, F_AGE, F_COUNT };
static DField dfields[F_COUNT];
static uint16_t dotColour = 0;
static uint32_t lastDashTickMs = 0;

static const int16_t CARD_W = 148, CARD_H = 74;
static const int16_t CARD_X[4] = {8, 164, 8, 164};
static const int16_t CARD_Y[4] = {38, 38, 118, 118};
static const char *const CARD_LABEL[4] = {"Temperature", "Humidity", "Soil moisture", "Air - MQ-135"};

static void dashCopy(char *dst, size_t n, const char *src) {
  size_t i = 0;
  for (; src[i] && i < n - 1; i++) dst[i] = (src[i] >= 32 && src[i] < 127) ? src[i] : '?';
  dst[i] = '\0';
}

static void parseDash(char *body) {
  memset(&dd, 0, sizeof dd);
  dd.have = true;
  dd.age = -1;
  dd.rxMs = millis();
  strcpy(dd.st, "unknown");
  char *save = nullptr;
  for (char *kv = strtok_r(body, ";", &save); kv; kv = strtok_r(nullptr, ";", &save)) {
    char *eq = strchr(kv, '=');
    if (!eq) continue;
    *eq = '\0';
    const char *k = kv, *v = eq + 1;
    if (!strcmp(k, "st")) dashCopy(dd.st, sizeof dd.st, v);
    else if (!strcmp(k, "age")) dd.age = v[0] ? atol(v) : -1;
    else if (!strcmp(k, "t")) dashCopy(dd.t, sizeof dd.t, v);
    else if (!strcmp(k, "h")) dashCopy(dd.h, sizeof dd.h, v);
    else if (!strcmp(k, "sr")) dashCopy(dd.sr, sizeof dd.sr, v);
    else if (!strcmp(k, "sp")) dashCopy(dd.sp, sizeof dd.sp, v);
    else if (!strcmp(k, "mq")) dashCopy(dd.mq, sizeof dd.mq, v);
    else if (!strcmp(k, "dev")) dashCopy(dd.dev, sizeof dd.dev, v);
    else if (!strcmp(k, "sv")) dd.sv = v[0] == '1';
    else if (!strcmp(k, "mv")) dd.mv = v[0] == '1';
    else if (!strcmp(k, "td")) dd.td = v[0] == '1';
    else if (!strcmp(k, "srv")) dd.srvOk = !strcmp(v, "ok");
  }
}

/* Repaints one field's rectangle only if its text or colour changed. */
static void dashField(int id, int16_t rx, int16_t ry, int16_t rw, int16_t rh, int16_t ax, int16_t ay,
                      uint8_t datum, uint8_t font, const char *txt, uint16_t fg, uint16_t bg) {
  DField &f = dfields[id];
  if (f.drawn && f.fg == fg && strncmp(f.txt, txt, sizeof f.txt - 1) == 0) return;
  dashCopy(f.txt, sizeof f.txt, txt);
  f.fg = fg;
  f.drawn = true;
  tft.fillRect(rx, ry, rw, rh, bg);
  tft.setTextDatum(datum);
  tft.setTextColor(fg, bg);
  tft.drawString(txt, ax, ay, font);
}

/* A card's big value with its unit ("deg" = a degree sign + C). The cache key
   is value + unit, so the pair is repainted together. */
static void dashValue(int i, const char *value, const char *unit, uint16_t fg) {
  char key[40];
  snprintf(key, sizeof key, "%s|%s", value, unit);
  DField &f = dfields[F_V0 + i];
  if (f.drawn && f.fg == fg && strcmp(f.txt, key) == 0) return;
  dashCopy(f.txt, sizeof f.txt, key);
  f.fg = fg;
  f.drawn = true;
  const int16_t x = CARD_X[i] + 10, y = CARD_Y[i] + 26, w = CARD_W - 20;
  tft.fillRect(x, y, w, 28, D_CARD);
  const uint8_t font = tft.textWidth(value, 4) + 30 <= w ? 4 : 2;     // "Not calibrated" uses font 2
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(fg, D_CARD);
  tft.drawString(value, x, font == 4 ? y + 1 : y + 6, font);
  int16_t ux = x + tft.textWidth(value, font) + 4;
  if (!strcmp(unit, "deg")) {
    tft.drawCircle(ux + 2, y + 5, 2, fg);
    tft.drawString("C", ux + 6, y + 4, 2);
  } else if (unit[0]) {
    tft.drawString(unit, ux, y + 4, 2);
  }
}

static void dashSub(int i, const char *txt, uint16_t fg) {
  dashField(F_S0 + i, CARD_X[i] + 10, CARD_Y[i] + 56, CARD_W - 20, 12, CARD_X[i] + 10, CARD_Y[i] + 57,
            TL_DATUM, 1, txt, fg, D_CARD);
}

static void dashUpdate() {
  if (ui != UI_DASH) return;
  const bool pc = pcAlive();
  const bool fresh = dd.have && millis() - dd.rxMs < DASH_DATA_TIMEOUT_MS;
  const bool online = !strcmp(dd.st, "online");
  const bool live = pc && fresh && dd.srvOk && online;          // values are current measurements

  // --- the four cards ---
  const uint16_t vfg = live ? D_TEXT : D_DIM;
  const char *old = (dd.have && !live) ? "last known" : "";
  char buf[40];
  if (dd.t[0]) { dashValue(0, dd.t, "deg", vfg); dashSub(0, old[0] ? old : "air, DHT11", old[0] ? D_WARN : D_MUTE); }
  else { dashValue(0, "--", "", D_DIM); dashSub(0, dd.have ? "no valid reading" : "waiting for data", D_MUTE); }
  if (dd.h[0]) { dashValue(1, dd.h, "%", vfg); dashSub(1, old[0] ? old : "relative, DHT11", old[0] ? D_WARN : D_MUTE); }
  else { dashValue(1, "--", "", D_DIM); dashSub(1, dd.have ? "no valid reading" : "waiting for data", D_MUTE); }
  if (dd.sv && dd.sp[0]) {
    dashValue(2, dd.sp, "%", vfg);
    snprintf(buf, sizeof buf, "raw %s%s", dd.sr, old[0] ? ", last known" : "");
    dashSub(2, buf, old[0] ? D_WARN : D_MUTE);
  } else if (dd.sr[0]) {
    dashValue(2, "Not calibrated", "", D_WARN);
    snprintf(buf, sizeof buf, "raw %s%s", dd.sr, atol(dd.sr) >= 16319 ? " - check probe" : "");
    dashSub(2, buf, D_MUTE);
  } else { dashValue(2, "--", "", D_DIM); dashSub(2, dd.have ? "no valid reading" : "waiting for data", D_MUTE); }
  if (dd.mq[0]) {
    dashValue(3, dd.mq, "raw", dd.mv ? vfg : D_DIM);
    dashSub(3, !dd.mv ? "warming up / check" : old[0] ? "last known" : "uncalibrated, not ppm",
            (!dd.mv || old[0]) ? D_WARN : D_MUTE);
  } else { dashValue(3, "--", "", D_DIM); dashSub(3, dd.have ? "no valid reading" : "waiting for data", D_MUTE); }

  // --- status line 1: the sensor device, and the PC / server link ---
  const char *sensorTxt;
  uint16_t dot;
  if (!pc)                       { sensorTxt = "PC app offline";     dot = D_BAD; }
  else if (!dd.have || !fresh)   { sensorTxt = "Waiting for data";   dot = D_DIM; }
  else if (!dd.srvOk)            { sensorTxt = "Server unreachable"; dot = D_BAD; }
  else if (dd.td)                { sensorTxt = "TEST DATA, not real"; dot = D_WARN; }
  else if (online)               { sensorTxt = "Sensor online";      dot = D_LEAF; }
  else if (!strcmp(dd.st, "stale"))   { sensorTxt = "Sensor stale";   dot = D_WARN; }
  else if (!strcmp(dd.st, "offline")) { sensorTxt = "Sensor offline"; dot = D_BAD; }
  else                           { sensorTxt = "No sensor data yet"; dot = D_DIM; }
  if (dot != dotColour) { tft.fillCircle(14, 206, 5, dot); dotColour = dot; }
  dashField(F_SENSOR, 24, 198, 170, 16, 24, 206, ML_DATUM, 2, sensorTxt, dot == D_DIM ? D_MUTE : D_TEXT, D_BG);
  snprintf(buf, sizeof buf, "PC %s  Server %s", pc ? "ok" : "off",
           !pc || !dd.have ? "?" : dd.srvOk ? "ok" : "down");
  dashField(F_LINK, 196, 198, 120, 16, 312, 206, MR_DATUM, 2, buf, (pc && dd.srvOk) ? D_MUTE : D_BAD, D_BG);

  // --- status line 2: how old the reading is ---
  if (dd.have && dd.age >= 0) {
    const unsigned long a = (unsigned long)dd.age + (millis() - dd.rxMs) / 1000;
    char ago[16];
    if (a < 120) snprintf(ago, sizeof ago, "%lus", a);
    else if (a < 7200) snprintf(ago, sizeof ago, "%lu min", a / 60);
    else snprintf(ago, sizeof ago, "%lu h", a / 3600);
    snprintf(buf, sizeof buf, "%s %s ago", live ? "Updated" : "Last reading", ago);
  } else {
    snprintf(buf, sizeof buf, "No reading yet");
  }
  dashField(F_AGE, 4, 218, 196, 16, 10, 226, ML_DATUM, 2, buf, live ? D_MUTE : D_WARN, D_BG);
}

static void dashDrawFrame() {
  tft.fillScreen(D_BG);
  tft.fillRect(0, 0, SCREEN_W, 30, D_BAR);
  tft.fillCircle(14, 15, 5, D_LEAF);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(D_LEAF, D_BAR);
  tft.drawString("SMART KRISHI", 26, 16, 4);
  drawBtn(BTN_FERT, "Fertilizer >", touchReady ? D_LEAF : D_CARD, touchReady ? D_BAR : D_MUTE);
  for (int i = 0; i < 4; i++) {
    tft.fillRoundRect(CARD_X[i], CARD_Y[i], CARD_W, CARD_H, 8, D_CARD);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(D_MUTE, D_CARD);
    tft.drawString(CARD_LABEL[i], CARD_X[i] + 10, CARD_Y[i] + 7, 2);
  }
  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(D_DIM, D_BG);
  tft.drawString(touchReady ? "Button tap: chat  hold: ask" : "Press screen firmly to set up touch", 312, 226, 1);
  for (int i = 0; i < F_COUNT; i++) dfields[i].drawn = false;
  dotColour = 0;
  dashUpdate();
}

/* Once a second: the "updated N s ago" counter and the link state. */
static void dashTick() {
  if (millis() - lastDashTickMs < DASH_REFRESH_MS) return;
  lastDashTickMs = millis();
  dashUpdate();
}

// --- switching screens -------------------------------------------------------

static void enterChat() {
  if (ui == UI_CHAT) return;
  ui = UI_CHAT;
  qrShown = false;
  Serial.println(F("[esp] screen: chat"));
  // the face to come back with: asleep without the PC app, else awake
  if (!pcAlive()) mood = MOOD_SLEEPY;
  else if (mood == MOOD_SLEEPY) mood = MOOD_IDLE;
  chatPump();
  tft.fillScreen(COL_BG);
  chatPump();
  drawBuddy();
  chatPump();
  if (!pcAlive()) {
    drawOfflineBubble();
    drawTitleBar("PC offline");
  } else if (pageCount > 0) {                  // the last answer is still there
    drawAnswerPage(pageShown >= 0 && pageShown < pageCount ? pageShown : 0);
    drawTitleBar("answer");
  } else {
    drawIdleBubble();
    drawTitleBar("ready");
  }
  chatPump();
}

static void enterDash() {
  ui = UI_DASH;
  Serial.println(F("[esp] screen: dashboard"));
  dashDrawFrame();
}

static void toggleScreen() {
  if (ui == UI_DASH) enterChat();
  else enterDash();
}


// ---------------------------------------------------------------------------
// Speaker - MAX98357A on I2S1
// ---------------------------------------------------------------------------

static uint8_t volumePct = PLAY_VOLUME;
static const int AMP_DMA_COUNT = 8;
static const int AMP_DMA_FRAMES = 256;     // 8 x 256 frames = 128 ms queued in DMA

static bool ampBegin() {
  i2s_config_t c = {};
  c.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  c.sample_rate = PLAY_RATE;
  c.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  // Stereo frames with the same sample in both slots. With SD tied to 3V3 the
  // MAX98357A plays the left slot; filling both makes it right however SD is
  // wired, and side-steps the ESP32's slot-order quirk entirely.
  c.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  c.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  c.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  c.dma_buf_count = AMP_DMA_COUNT;
  c.dma_buf_len = AMP_DMA_FRAMES;
  c.use_apll = false;
  // On an underrun, send silence instead of replaying the last buffer - which
  // would otherwise come out of the speaker as a loud buzz.
  c.tx_desc_auto_clear = true;

  esp_err_t e = i2s_driver_install(AMP_PORT, &c, 0, nullptr);
  if (e != ESP_OK) { Serial.printf("ERR:speaker I2S install failed (%d)\n", (int)e); return false; }
  i2s_pin_config_t p = {};
  p.mck_io_num = I2S_PIN_NO_CHANGE;
  p.bck_io_num = AMP_BCLK;
  p.ws_io_num = AMP_LRC;
  p.data_out_num = AMP_DIN;
  p.data_in_num = I2S_PIN_NO_CHANGE;
  e = i2s_set_pin(AMP_PORT, &p);
  if (e != ESP_OK) { Serial.printf("ERR:speaker I2S pins failed (%d)\n", (int)e); return false; }
  i2s_zero_dma_buffer(AMP_PORT);
  return true;
}

// --- chime ------------------------------------------------------------------

static void playTone(uint16_t freq, uint16_t ms) {
  static int16_t buf[2 * 128];
  const uint32_t total = (uint32_t)PLAY_RATE * ms / 1000;
  const uint32_t fade = PLAY_RATE / 200;                 // 5 ms in and out: no click
  const float amp = 12000.0f * SPEAKER_GAIN * volumePct / 100.0f;
  const float step = 2.0f * (float)M_PI * freq / PLAY_RATE;
  float ph = 0.0f;
  uint32_t done = 0;
  while (done < total) {
    uint32_t n = total - done;
    if (n > 128) n = 128;
    for (uint32_t i = 0; i < n; i++) {
      const uint32_t k = done + i;
      float env = 1.0f;
      if (k < fade) env = (float)k / fade;
      else if (total - k < fade) env = (float)(total - k) / fade;
      const int16_t s = (int16_t)(sinf(ph) * amp * env);
      ph += step;
      if (ph > 2.0f * (float)M_PI) ph -= 2.0f * (float)M_PI;
      buf[2 * i] = buf[2 * i + 1] = s;
    }
    size_t w = 0;
    i2s_write(AMP_PORT, buf, n * 4, &w, portMAX_DELAY);
    done += n;
  }
}

static void playChime() {
  playTone(880, 90);
  playTone(1320, 120);
}

// --- streamed speech ----------------------------------------------------------

static uint8_t ring[AUDIO_RING_BYTES];
static size_t ringHead = 0, ringTail = 0, ringCount = 0;
static int16_t stage[2 * AMP_DMA_FRAMES];      // stereo frames waiting for the DMA
static size_t stageLen = 0, stageOff = 0;      // bytes

static struct {
  bool active;
  bool playing;          // prebuffer reached
  bool starved;          // currently in an underrun
  bool draining;         // all data handed to the DMA; waiting for it to play out
  uint32_t total, received, granted, played, gaps;
  uint32_t lastRxMs, drainUntilMs;
} aud;

static void grantCredit() {
  const uint32_t outstanding = aud.granted - aud.received;
  const int32_t room = (int32_t)AUDIO_RING_BYTES - (int32_t)ringCount - (int32_t)outstanding;
  const uint32_t left = aud.total - aud.granted;
  if (left == 0 || room <= 0) return;
  uint32_t g = (uint32_t)room;
  if (g > left) g = left;
  if (g < AUDIO_CREDIT_STEP && g < left) return;    // wait for a worthwhile chunk
  aud.granted += g;
  Serial.printf("C:%lu\n", (unsigned long)g);
}

static inline int16_t ringPop16() {
  const uint8_t lo = ring[ringTail];
  ringTail = (ringTail + 1) % AUDIO_RING_BYTES;
  const uint8_t hi = ring[ringTail];
  ringTail = (ringTail + 1) % AUDIO_RING_BYTES;
  ringCount -= 2;
  return (int16_t)(lo | (hi << 8));
}

enum KioskState { ST_IDLE, ST_RECORDING, ST_BUSY };
static KioskState state = ST_IDLE;

static void startAudio(uint32_t bytes) {
  if (bytes == 0) { Serial.println(F("DONE:0,0")); return; }
  ringHead = ringTail = ringCount = 0;
  stageLen = stageOff = 0;
  memset(&aud, 0, sizeof(aud));
  aud.total = bytes;
  aud.active = true;
  drawTitleBar("SPEAKING");            // all drawing happens before audio starts
  talkLevel = 0.0f;
  setMood(MOOD_TALK);
  aud.lastRxMs = millis();
  grantCredit();
}

static void finishAudio(bool ok) {
  aud.active = false;
  i2s_zero_dma_buffer(AMP_PORT);
  if (ok) {
    Serial.printf("DONE:%lu,%lu\n", (unsigned long)aud.played, (unsigned long)aud.gaps);
  } else {
    Serial.printf("ERR:audio timed out after %lu of %lu bytes\n",
                  (unsigned long)aud.received, (unsigned long)aud.total);
    delay(50);
    while (Serial.available()) Serial.read();   // drop any late stragglers
  }
  talkLevel = 0.0f;
  setMood(ok ? MOOD_HAPPY : MOOD_CONFUSED);      // a smile once the answer is out
  if (state != ST_BUSY) drawTitleBar("ready");   // in BUSY, the PC's IDLE says when
}

/* Called continuously while a clip is active. Never blocks: the I2S writes use
   a zero timeout, so the button and the serial link stay responsive. */
static void serviceAudio() {
  // 1. Move whatever has arrived into the ring, in contiguous runs.
  while (aud.received < aud.total && ringCount < AUDIO_RING_BYTES) {
    size_t avail = Serial.available();
    if (avail == 0) break;
    size_t run = AUDIO_RING_BYTES - ringHead;
    size_t space = AUDIO_RING_BYTES - ringCount;
    size_t want = aud.total - aud.received;
    size_t n = avail;
    if (n > run) n = run;
    if (n > space) n = space;
    if (n > want) n = want;
    n = Serial.read(ring + ringHead, n);
    if (n == 0) break;
    ringHead = (ringHead + n) % AUDIO_RING_BYTES;
    ringCount += n;
    aud.received += n;
    aud.lastRxMs = millis();
  }

  // 2. Start once a little is buffered, so a USB hiccup at the start doesn't stutter.
  if (!aud.playing && (ringCount >= AUDIO_PREBUFFER || aud.received == aud.total)) {
    aud.playing = true;
  }

  // 3. Keep the I2S DMA fed. Its own clock paces playback exactly.
  if (aud.playing && !aud.draining) {
    for (int k = 0; k < 8; k++) {
      if (stageOff >= stageLen) {
        size_t n = ringCount / 2;
        if (n > (size_t)AMP_DMA_FRAMES) n = AMP_DMA_FRAMES;
        if (n == 0) {
          if (aud.received < aud.total && !aud.starved) { aud.starved = true; aud.gaps++; }
          break;
        }
        aud.starved = false;
        uint32_t loud = 0;
        for (size_t i = 0; i < n; i++) {
      int32_t s = ((int32_t)ringPop16() * volumePct * SPEAKER_GAIN) / 100;
          if (s > 32767) s = 32767;
          else if (s < -32768) s = -32768;
          stage[2 * i] = stage[2 * i + 1] = (int16_t)s;
          loud += (uint32_t)(s < 0 ? -s : s);
        }
        // How wide Mithra's mouth opens: the average loudness of this chunk.
        const float lvl = (float)loud / (float)n / 5000.0f;
        talkLevel = lvl > 1.0f ? 1.0f : lvl;
        stageLen = n * 4;
        stageOff = 0;
        aud.played += n * 2;
      }
      size_t w = 0;
      i2s_write(AMP_PORT, (const uint8_t *)stage + stageOff, stageLen - stageOff, &w, 0);
      if (w == 0) break;                 // DMA full - come back next loop
      stageOff += w;
    }
  }

  // 4. Turn the answer's pages in step with the speech.
  if (pageCount > 1 && aud.total) {
    int page = (int)((uint64_t)aud.played * pageCount / aud.total);
    if (page >= pageCount) page = pageCount - 1;
    if (page != pageShown) drawAnswerPage(page);
  }

  // 5. Let the PC send more.
  grantCredit();

  // 6. Done (after the DMA has played its last buffers), or abandoned.
  if (aud.received == aud.total && ringCount < 2 && stageOff >= stageLen) {
    if (!aud.draining) {
      aud.draining = true;
      aud.drainUntilMs = millis() + (AMP_DMA_COUNT * AMP_DMA_FRAMES * 1000UL) / PLAY_RATE + 30;
    } else if ((int32_t)(millis() - aud.drainUntilMs) >= 0) {
      finishAudio(true);
    }
  } else if (aud.received < aud.total && millis() - aud.lastRxMs > AUDIO_TIMEOUT_MS) {
    finishAudio(false);
  }
}


// ---------------------------------------------------------------------------
// Microphone - INMP441 on I2S0
// ---------------------------------------------------------------------------

static const int MIC_FRAMES = 256;             // 16 ms per read at 16 kHz
static int32_t micRaw[2 * MIC_FRAMES];         // stereo 32-bit words from the DMA
static int16_t micPcm[MIC_FRAMES];
static int micSlot = 1;                        // which slot carries the mic; detected at boot
static float dcX = 0.0f, dcY = 0.0f;

static bool micBegin() {
  i2s_config_t c = {};
  c.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  c.sample_rate = MIC_RATE;
  // The INMP441 sends 24-bit samples MSB-first in 32-bit slots, so read 32-bit
  // words; the top 24 bits are the sample (Philips I2S, one-bit delay).
  c.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  // Read both slots and pick the live one in software: with L/R on 3V3 the mic
  // talks in the right slot, but where that lands in the buffer has varied
  // between ESP-IDF versions, so it is measured rather than assumed.
  c.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  c.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  c.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  c.dma_buf_count = 8;                         // 8 x 16 ms = 128 ms of slack
  c.dma_buf_len = MIC_FRAMES;
  c.use_apll = false;

  esp_err_t e = i2s_driver_install(MIC_PORT, &c, 0, nullptr);
  if (e != ESP_OK) { Serial.printf("ERR:mic I2S install failed (%d)\n", (int)e); return false; }
  i2s_pin_config_t p = {};
  p.mck_io_num = I2S_PIN_NO_CHANGE;
  p.bck_io_num = MIC_SCK;
  p.ws_io_num = MIC_WS;
  p.data_out_num = I2S_PIN_NO_CHANGE;
  p.data_in_num = MIC_SD;
  e = i2s_set_pin(MIC_PORT, &p);
  if (e != ESP_OK) { Serial.printf("ERR:mic I2S pins failed (%d)\n", (int)e); return false; }
  // The INMP441 lets SD float during the other slot; its datasheet asks for a
  // pull-down so that slot reads as clean zeros rather than noise.
  gpio_pulldown_en((gpio_num_t)MIC_SD);
  return true;
}

static void micFlush() {
  size_t got = 0;
  do { i2s_read(MIC_PORT, micRaw, sizeof(micRaw), &got, 0); } while (got > 0);
}

/* Finds which of the two I2S slots the INMP441 is talking in. The silent slot
   reads 0 (thanks to the pull-down) or -1; the live one carries the mic's noise
   floor even in a quiet room, so it never sits at exactly 0. */
static int detectMicSlot() {
  // The INMP441 needs ~85 ms after the clock starts, and its output then settles
  // for a while longer: measured here, the first 150 ms still carried a power-on
  // swing of -15 dBFS. Wait it out, so the boot log shows the real noise floor.
  delay(400);
  micFlush();
  uint32_t degenerate[2] = {0, 0}, n = 0;
  double sum[2] = {0, 0}, sq[2] = {0, 0};
  while (n < 4096) {
    size_t got = 0;
    i2s_read(MIC_PORT, micRaw, sizeof(micRaw), &got, pdMS_TO_TICKS(100));
    const size_t frames = got / 8;
    if (!frames) break;
    for (size_t i = 0; i < frames; i++) {
      for (int s = 0; s < 2; s++) {
        const int32_t v = micRaw[2 * i + s] >> 8;
        if (v == 0 || v == -1) degenerate[s]++;
        sum[s] += v;
        sq[s] += (double)v * v;
      }
    }
    n += frames;
  }
  if (n == 0) {
    Serial.println(F("ERR:mic sent no I2S data - check SCK=14, WS=15, SD=32 and 3V3"));
    return 1;
  }
  double sd[2];
  for (int s = 0; s < 2; s++) {
    const double mean = sum[s] / n;
    const double var = sq[s] / n - mean * mean;
    sd[s] = var > 0 ? sqrt(var) : 0;
  }
  const bool live0 = degenerate[0] < n / 2, live1 = degenerate[1] < n / 2;
  int slot = (live0 && !live1) ? 0 : (live1 && !live0) ? 1 : (sd[0] > sd[1] ? 0 : 1);
  Serial.printf("[esp] mic slots: [0] sd=%.0f flat=%lu%%  [1] sd=%.0f flat=%lu%%  -> slot %d%s\n",
                sd[0], (unsigned long)(degenerate[0] * 100 / n),
                sd[1], (unsigned long)(degenerate[1] * 100 / n), slot,
                (!live0 && !live1) ? "  (both slots flat: check the mic wiring)" : "");
  return slot;
}

// --- push-to-talk recording -------------------------------------------------

static uint32_t recStartMs = 0, recBytes = 0, recLimitMs = REC_MAX_MS;
static uint32_t busySinceMs = 0, lastLevelMs = 0;
static bool recFromButton = false;
// A button recording streams from the moment of the press (so no first word is
// lost), but LISTENING is only drawn once the press has lasted REC_MIN_MS: a
// shorter press is a tap that switches screens, and must not flash the chat.
static bool recShown = true;
static double levelSq = 0;
static uint32_t levelN = 0;

static void startRecording(bool fromButton, uint32_t limitMs) {
  state = ST_RECORDING;
  recFromButton = fromButton;
  recLimitMs = limitMs;
  recShown = !fromButton;
  if (!fromButton) {               // MICREC test: show it at once
    enterChat();
    drawListening("Test recording...");
  }
  micFlush();                      // drop audio captured before the press
  dcX = dcY = 0.0f;
  recBytes = 0;
  levelSq = 0;
  levelN = 0;
  lastLevelMs = millis();
  Serial.println(F("REC:START"));
  recStartMs = millis();
}

/* Reads whatever the mic DMA has, converts it to 16-bit and streams it to the
   PC at once - nothing accumulates in RAM, however long the visitor talks. */
static void pumpMic() {
  size_t got = 0;
  i2s_read(MIC_PORT, micRaw, sizeof(micRaw), &got, 0);
  const size_t frames = got / 8;
  if (!frames) return;
  for (size_t i = 0; i < frames; i++) {
    const int32_t v = micRaw[2 * i + micSlot] >> 8;        // signed 24-bit sample
    // DC blocker (one-pole high-pass, ~13 Hz): the INMP441 output carries a DC
    // offset that would otherwise eat headroom and skew the level meter.
    const float x = (float)v;
    const float y = x - dcX + 0.995f * dcY;
    dcX = x;
    dcY = y;
    int32_t s = (int32_t)y >> (8 - MIC_GAIN_BITS);
    if (s > 32767) s = 32767;
    else if (s < -32768) s = -32768;
    micPcm[i] = (int16_t)s;
    levelSq += (double)s * s;
    levelN++;
  }
  Serial.printf("MIC:%u\n", (unsigned)(frames * 2));
  Serial.write((const uint8_t *)micPcm, frames * 2);
  recBytes += frames * 2;

  if (millis() - lastLevelMs >= 100 && levelN) {
    const double rms = sqrt(levelSq / levelN);
    // Reference ~ an ordinary room: measured idle level on this mic is ~120 (int16,
    // after MIC_GAIN_BITS), which reads ~25%; normal speech fills most of the bar.
    if (recShown) drawLevel((int)(50.0 * log10((rms > 1 ? rms : 1) / 40.0)));
    levelSq = 0;
    levelN = 0;
    lastLevelMs = millis();
  }
}

static void chatPump() {
  if (state == ST_RECORDING) pumpMic();
}

static void stopRecording() {
  const uint32_t ms = millis() - recStartMs;
  if (recShown) drawLevel(0);
  if (recFromButton && ms < REC_MIN_MS) {
    // A tap, not a question: drop the audio and switch screens.
    Serial.println(F("REC:CANCEL tap"));
    state = ST_IDLE;
    toggleScreen();
    return;
  }
  if (ms < REC_MIN_MS || recBytes == 0) {
    Serial.printf("REC:CANCEL %s\n", recBytes ? "too-short" : "no-audio");
    state = ST_IDLE;
    enterChat();
    setMood(MOOD_CONFUSED);
    if (recBytes) bubbleMessage("Oops!", "Keep holding the button the whole time you speak, then let go.");
    else bubbleMessage("I can't hear!", "No sound is coming from my microphone. Check the INMP441 wiring.");
    drawTitleBar(recBytes ? "hold longer" : "mic error");
    return;
  }
  Serial.printf("REC:END %lu %lu\n", (unsigned long)recBytes, (unsigned long)ms);
  if (!recShown) {                 // released right at the threshold, before LISTENING was drawn
    recShown = true;
    enterChat();
  }
  state = ST_BUSY;
  busySinceMs = millis();
  questionText[0] = '\0';
  setMood(MOOD_THINK);
  drawThinkingBubble();
  drawTitleBar("PROCESSING");
}

/* Test only: stream the raw I2S words of both slots, so the PC can confirm
   which slot carries the mic and that the 24-bit data is aligned as expected. */
static void streamRaw(uint32_t ms) {
  micFlush();
  const uint32_t start = millis();
  while (millis() - start < ms) {
    size_t got = 0;
    i2s_read(MIC_PORT, micRaw, sizeof(micRaw), &got, pdMS_TO_TICKS(50));
    if (got) {
      Serial.printf("RAW:%u\n", (unsigned)got);
      Serial.write((const uint8_t *)micRaw, got);
    }
  }
  Serial.println(F("[esp] raw done"));
}


// ---------------------------------------------------------------------------
// Push button
// ---------------------------------------------------------------------------

static bool btnDown = false, btnRaw = false, btnArmed = true;
static uint32_t btnChangeMs = 0;

/* Debounced: +1 on a press, -1 on a release, 0 otherwise. */
static int pollButton() {
  const bool raw = digitalRead(BTN_TALK) == LOW;
  const uint32_t now = millis();
  if (raw != btnRaw) { btnRaw = raw; btnChangeMs = now; }
  if (btnDown != btnRaw && now - btnChangeMs >= BTN_DEBOUNCE_MS) {
    btnDown = btnRaw;
    return btnDown ? 1 : -1;
  }
  return 0;
}


// ---------------------------------------------------------------------------
// Touch screen (XPT2046) + crop selection + fertilizer recommendation
// ---------------------------------------------------------------------------
//
// Touch shares the TFT's SPI bus; T_CS = GPIO21 (TOUCH_CS in platformio.ini).
// T_IRQ is not used (GPIO22 is the speaker's data line): the library polls the
// touch pressure instead. Taps only count once the screen has been calibrated
// (stored in flash) - an unconnected controller would otherwise read as a press.
//
// Flow: dashboard "Fertilizer >" -> crop screen (crop, Soil Health Card N/P/K
// rating, area) -> "Recommend" sends FERT:... to the PC, whose server answers
// with the pages shown on the result screen. Doses come from the server
// (official crop recommendations); this file only displays them.

static Preferences prefs;
static uint16_t touchCal[5];

static void touchBegin() {
  prefs.begin("krishi", false);
  touchReady = prefs.getBytes("tcal", touchCal, sizeof touchCal) == sizeof touchCal;
  if (touchReady) tft.setTouch(touchCal);
}

static void touchCalibrate() {
  tft.fillScreen(D_BG);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(D_TEXT, D_BG);
  tft.drawString("Touch calibration", 160, 100, 4);
  tft.drawString("Touch each corner arrow as it appears", 160, 136, 2);
  delay(1500);
  tft.calibrateTouch(touchCal, D_LEAF, D_BG, 15);      // blocks until the 4 corners are touched
  prefs.putBytes("tcal", touchCal, sizeof touchCal);
  tft.setTouch(touchCal);
  touchReady = true;
  Serial.printf("[esp] touch calibrated: %u %u %u %u %u\n", touchCal[0], touchCal[1], touchCal[2], touchCal[3], touchCal[4]);
}

// --- crop screen -------------------------------------------------------------------

static const int MAX_CROPS = 6;
static char cropId[MAX_CROPS][12], cropName[MAX_CROPS][14];
static int  cropCount = 0, cropSel = -1;
static uint8_t soilRating[3] = {0, 0, 0};             // N, P, K: 0 not known, 1 low, 2 medium, 3 high
static const char *const RATING_TXT[4] = {"Auto", "Low", "Med", "High"};   // Auto = district / general
static const char *const RATING_ID[4] = {"unknown", "low", "medium", "high"};
static const float AREAS[] = {0.25f, 0.5f, 1, 1.5f, 2, 2.5f, 3, 4, 5, 10};
static const int AREA_N = sizeof AREAS / sizeof AREAS[0];
static int  areaIdx = 2;                              // 1 acre
static uint32_t cropsAskedMs = 0;

// District of the land (REGIONS: from the PC). Nutrients without a Soil Health
// Card value are assumed from that district's soil surveys on the server.
static const int MAX_REGIONS = 8;
static char regionId[MAX_REGIONS][16], regionName[MAX_REGIONS][18];
static int  regionCount = 0, regionSel = -1;
static const Btn BTN_REGION = {150, 3, 166, 22};

static const Btn BTN_BACK  = {4, 3, 70, 22};
static const Btn BTN_RATE[3] = {{96, 138, 68, 28}, {170, 138, 68, 28}, {244, 138, 68, 28}};
static const Btn BTN_MINUS = {96, 176, 44, 28};
static const Btn BTN_PLUS  = {268, 176, 44, 28};
static const Btn BTN_GO    = {8, 210, 304, 26};

static Btn cropBtn(int i) { return {(int16_t)(8 + (i % 3) * 104), (int16_t)(34 + (i / 3) * 50), 96, 44}; }

static void drawTopBar(const char *title, const char *right = "") {
  tft.fillRect(0, 0, SCREEN_W, 29, D_BAR);
  drawBtn(BTN_BACK, "< Back", D_CARD, D_TEXT);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(D_LEAF, D_BAR);
  tft.drawString(title, 84, 15, 2);
  if (right[0]) {
    tft.setTextDatum(MR_DATUM);
    tft.setTextColor(D_MUTE, D_BAR);
    tft.drawString(right, 314, 15, 2);
  }
}

static void drawCropButtons() {
  tft.fillRect(0, 30, SCREEN_W, 102, D_BG);
  if (cropCount == 0) {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(D_MUTE, D_BG);
    tft.drawString(pcAlive() ? "Getting the crop list from the PC..." : "PC app offline - start start.ps1", 160, 80, 2);
    return;
  }
  for (int i = 0; i < cropCount; i++) {
    const bool sel = i == cropSel;
    drawBtn(cropBtn(i), cropName[i], sel ? D_LEAF : D_CARD, sel ? D_BAR : D_TEXT, 2);
  }
}

static void drawRatings() {
  tft.fillRect(0, 134, SCREEN_W, 36, D_BG);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(D_MUTE, D_BG);
  tft.drawString("Soil card", 8, 152, 2);
  static const char *const NUT[3] = {"N", "P", "K"};
  for (int i = 0; i < 3; i++) {
    char label[12];
    snprintf(label, sizeof label, "%s: %s", NUT[i], RATING_TXT[soilRating[i]]);
    const uint16_t fill = soilRating[i] == 0 ? D_CARD : soilRating[i] == 1 ? D_WARN : soilRating[i] == 2 ? D_LEAF : D_MUTE;
    drawBtn(BTN_RATE[i], label, fill, soilRating[i] == 0 ? D_TEXT : D_BAR);
  }
}

static void drawArea() {
  tft.fillRect(0, 172, SCREEN_W, 36, D_BG);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(D_MUTE, D_BG);
  tft.drawString("Area", 8, 190, 2);
  drawBtn(BTN_MINUS, "-", D_CARD, D_TEXT, 4);
  drawBtn(BTN_PLUS, "+", D_CARD, D_TEXT, 4);
  char a[16];
  snprintf(a, sizeof a, "%g acre%s", AREAS[areaIdx], AREAS[areaIdx] == 1 ? "" : "s");
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(D_TEXT, D_BG);
  tft.drawString(a, 204, 191, 2);
}

static void drawRegionBtn() {
  char label[28];
  if (regionSel >= 0) snprintf(label, sizeof label, "Land: %s", regionName[regionSel]);
  else snprintf(label, sizeof label, "Land: ...");
  const uint8_t font = tft.textWidth(label, 2) <= BTN_REGION.w - 8 ? 2 : 1;
  drawBtn(BTN_REGION, label, D_CARD, D_TEXT, font);
}

static void drawGo() {
  const bool ok = cropSel >= 0;
  drawBtn(BTN_GO, ok ? "Recommend fertilizer >" : "Choose a crop first", ok ? D_LEAF : D_CARD, ok ? D_BAR : D_MUTE);
}

static void drawCropScreen() {
  tft.fillScreen(D_BG);
  drawTopBar("Fertilizer");
  drawRegionBtn();
  drawCropButtons();
  drawRatings();
  drawArea();
  drawGo();
}

static void enterCrop() {
  ui = UI_CROP;
  Serial.println(F("[esp] screen: crops"));
  drawCropScreen();
  if (cropCount == 0 && pcAlive()) { Serial.println(F("CROPS?")); cropsAskedMs = millis(); }
}

/* CROPS:tomato=Tomato;paddy=Paddy;... from the PC (the server's crop list). */
static void parseCrops(char *body) {
  cropCount = 0;
  char *save = nullptr;
  for (char *kv = strtok_r(body, ";", &save); kv && cropCount < MAX_CROPS; kv = strtok_r(nullptr, ";", &save)) {
    char *eq = strchr(kv, '=');
    if (!eq) continue;
    *eq = '\0';
    dashCopy(cropId[cropCount], sizeof cropId[0], kv);
    dashCopy(cropName[cropCount], sizeof cropName[0], eq + 1);
    cropCount++;
  }
  if (cropSel >= cropCount) cropSel = -1;
  Serial.printf("[esp] %d crops\n", cropCount);
  if (ui == UI_CROP) { drawCropButtons(); drawGo(); }
}

/* REGIONS:<default id>|id=Name;id=Name;... - the saved choice wins over the default. */
static void parseRegions(char *body) {
  char *bar = strchr(body, '|');
  if (!bar) return;
  *bar = '\0';
  char def[16];
  dashCopy(def, sizeof def, body);
  regionCount = 0;
  char *save = nullptr;
  for (char *kv = strtok_r(bar + 1, ";", &save); kv && regionCount < MAX_REGIONS; kv = strtok_r(nullptr, ";", &save)) {
    char *eq = strchr(kv, '=');
    if (!eq) continue;
    *eq = '\0';
    dashCopy(regionId[regionCount], sizeof regionId[0], kv);
    dashCopy(regionName[regionCount], sizeof regionName[0], eq + 1);
    regionCount++;
  }
  const String saved = prefs.getString("region", "");
  regionSel = -1;
  for (int i = 0; i < regionCount; i++) if (saved.length() && saved == regionId[i]) regionSel = i;
  for (int i = 0; i < regionCount && regionSel < 0; i++) if (!strcmp(def, regionId[i])) regionSel = i;
  if (regionSel < 0 && regionCount) regionSel = 0;
  Serial.printf("[esp] %d regions, land in %s\n", regionCount, regionSel >= 0 ? regionId[regionSel] : "-");
  if (ui == UI_CROP) drawRegionBtn();
}

// --- fertilizer result screen ----------------------------------------------------

static const int FR_MAX_LINES = 48;
struct FLine { uint8_t page; char style; char text[96]; };
static FLine frLines[FR_MAX_LINES];
static int  frCount = 0, frPages = 0, frPage = 0;
static char frTitle[48] = "";
static uint8_t frState = 0;                           // 0 nothing, 1 waiting, 2 ready, 3 error
static char frError[96] = "";
static uint32_t frAskedMs = 0;
static const Btn BTN_PREV = {8, 210, 100, 26};
static const Btn BTN_NEXT = {212, 210, 100, 26};

/* Draws `text` word-wrapped from y; returns the y below it (stops at maxY). */
static int16_t drawWrapped(const char *text, uint8_t font, uint16_t fg, int16_t y, int16_t maxY) {
  const int16_t lineH = tft.fontHeight(font) + 2;
  size_t pos = 0;
  while (text[pos] && y + lineH <= maxY) {
    const size_t next = wrapPass(text, pos, font, 304, 1, true, 8, y, fg, D_BG);
    y += lineH;
    if (next == pos) break;
    pos = next;
  }
  return y;
}

static void drawFertScreen() {
  tft.fillScreen(D_BG);
  char right[8] = "";
  if (frState == 2 && frPages > 1) snprintf(right, sizeof right, "%d/%d", frPage + 1, frPages);
  drawTopBar(frState == 2 ? frTitle : "Fertilizer", right);
  tft.setTextDatum(MC_DATUM);
  if (frState == 1) {
    tft.setTextColor(D_MUTE, D_BG);
    tft.drawString("Working it out...", 160, 110, 4);
    return;
  }
  if (frState != 2) {
    tft.setTextColor(D_WARN, D_BG);
    drawWrapped(frError[0] ? frError : "No recommendation yet.", 2, D_WARN, 60, 200);
    return;
  }
  int16_t y = 36;
  const int16_t maxY = frPages > 1 ? 206 : 236;
  for (int i = 0; i < frCount && y < maxY; i++) {
    const FLine &l = frLines[i];
    if (l.page != frPage) continue;
    switch (l.style) {
      case 'H': y = drawWrapped(l.text, 2, D_LEAF, y, maxY) + 2; break;
      case 'V': y = drawWrapped(l.text, 4, D_TEXT, y, maxY); break;
      case 'W': y = drawWrapped(l.text, 2, D_WARN, y, maxY); break;
      case 'S': y = drawWrapped(l.text, 1, D_MUTE, y + 2, maxY); break;
      default:  y = drawWrapped(l.text, 2, D_TEXT, y, maxY); break;
    }
  }
  if (frPages > 1) {
    drawBtn(BTN_PREV, "< Prev", frPage > 0 ? D_CARD : D_BG, frPage > 0 ? D_TEXT : D_DIM);
    drawBtn(BTN_NEXT, "Next >", frPage < frPages - 1 ? D_LEAF : D_BG, frPage < frPages - 1 ? D_BAR : D_DIM);
  }
}

static void enterFert() {
  ui = UI_FERT;
  Serial.println(F("[esp] screen: fertilizer"));
  drawFertScreen();
}

static void requestFertilizer() {
  frPage = 0;
  if (!pcAlive()) {
    frState = 3;
    strcpy(frError, "The PC app is not connected, so the recommendation cannot be worked out. Start start.ps1.");
  } else {
    frState = 1;
    frAskedMs = millis();
    Serial.printf("FERT:crop=%s;area=%g;n=%s;p=%s;k=%s;region=%s\n", cropId[cropSel], AREAS[areaIdx],
                  RATING_ID[soilRating[0]], RATING_ID[soilRating[1]], RATING_ID[soilRating[2]],
                  regionSel >= 0 ? regionId[regionSel] : "");
  }
  enterFert();
}

/* FRB:<pages>, FRT:<title>, FRL:<page>|<style>|<text>, FRE (done), FRX:<error>. */
static bool handleFertLine(char *line) {
  if (strncmp(line, "FRB:", 4) == 0) { frCount = 0; frPages = atoi(line + 4); frTitle[0] = '\0'; return true; }
  if (strncmp(line, "FRT:", 4) == 0) { dashCopy(frTitle, sizeof frTitle, line + 4); return true; }
  if (strncmp(line, "FRL:", 4) == 0) {
    char *a = line + 4, *b = strchr(a, '|');
    if (!b || frCount >= FR_MAX_LINES) return true;
    char *c = strchr(b + 1, '|');
    if (!c) return true;
    FLine &l = frLines[frCount++];
    l.page = (uint8_t)atoi(a);
    l.style = b[1];
    dashCopy(l.text, sizeof l.text, c + 1);
    return true;
  }
  if (strcmp(line, "FRE") == 0) {
    frState = 2;
    frPage = 0;
    if (frPages < 1) frPages = 1;
    Serial.printf("[esp] fertilizer: %d lines, %d pages\n", frCount, frPages);
    if (ui == UI_FERT) drawFertScreen();
    return true;
  }
  if (strncmp(line, "FRX:", 4) == 0) {
    frState = 3;
    dashCopy(frError, sizeof frError, line + 4);
    if (ui == UI_FERT) drawFertScreen();
    return true;
  }
  return false;
}

// --- taps --------------------------------------------------------------------------

static void onTap(uint16_t x, uint16_t y) {
  Serial.printf("[esp] touch %u,%u\n", x, y);
  switch (ui) {
    case UI_DASH:
      if (hit(BTN_FERT, x, y)) enterCrop();
      break;
    case UI_CHAT:
      if (y < BAR_H) enterDash();                       // the title bar goes back to the dashboard
      break;
    case UI_CROP:
      if (hit(BTN_BACK, x, y)) { enterDash(); break; }
      if (hit(BTN_REGION, x, y) && regionCount) {
        regionSel = (regionSel + 1) % regionCount;
        prefs.putString("region", regionId[regionSel]);
        drawRegionBtn();
        break;
      }
      for (int i = 0; i < cropCount; i++)
        if (hit(cropBtn(i), x, y)) { cropSel = i; drawCropButtons(); drawGo(); return; }
      for (int i = 0; i < 3; i++)
        if (hit(BTN_RATE[i], x, y)) { soilRating[i] = (soilRating[i] + 1) % 4; drawRatings(); return; }
      if (hit(BTN_MINUS, x, y) && areaIdx > 0) { areaIdx--; drawArea(); break; }
      if (hit(BTN_PLUS, x, y) && areaIdx < AREA_N - 1) { areaIdx++; drawArea(); break; }
      if (hit(BTN_GO, x, y) && cropSel >= 0) requestFertilizer();
      break;
    case UI_FERT:
      if (hit(BTN_BACK, x, y)) { enterCrop(); break; }
      if (frState == 2 && frPages > 1) {
        if (hit(BTN_PREV, x, y) && frPage > 0) { frPage--; drawFertScreen(); }
        else if (hit(BTN_NEXT, x, y) && frPage < frPages - 1) { frPage++; drawFertScreen(); }
      }
      break;
  }
}

static bool touchHeld = false;
static uint32_t lastTouchPollMs = 0, lastTapMs = 0;
static uint8_t uncalPresses = 0;
// Pressure that counts as a touch. Measured on this panel: 5-30 with nothing
// touching it; the library default (600) needs a hard press on some panels.
static const uint16_t TOUCH_Z_MIN = 350;

/* TRAW:<n> - print n raw touch readings, to see whether the controller answers:
   no touch -> z near 0; a finger -> z in the hundreds+ and x, y between ~200 and
   ~3900; x or y stuck at 0 or 4095 -> nothing is answering (wiring, T_CS). */
static void touchDiag(int n) {
  for (int i = 0; i < n; i++) {
    uint16_t x = 0, y = 0;
    tft.getTouchRaw(&x, &y);
    const uint16_t z = tft.getTouchRawZ();
    Serial.printf("[esp] touch raw x=%u y=%u z=%u\n", x, y, z);
    delay(100);
  }
}

/* A real finger press on an uncalibrated screen: firm, and x, y inside the
   panel's raw range (an absent controller reads 0 or 4095 there). */
static bool rawPressLooksReal() {
  uint16_t x = 0, y = 0;
  tft.getTouchRaw(&x, &y);
  const uint16_t z = tft.getTouchRawZ();
  return z > TOUCH_Z_MIN && z < 4000 && x > 150 && x < 3950 && y > 150 && y < 3950;
}

/* Every 25 ms while idle: one tap per press (released between taps). Before
   calibration, a firm press held for ~0.3 s starts the calibration. */
static void pollTouch() {
  if (millis() - lastTouchPollMs < 25) return;
  lastTouchPollMs = millis();
  if (!touchReady) {
    uncalPresses = rawPressLooksReal() ? uncalPresses + 1 : 0;
    if (uncalPresses >= 12) {
      uncalPresses = 0;
      Serial.println(F("[esp] touch pressed on an uncalibrated screen - calibrating"));
      touchCalibrate();
      enterDash();
    }
    return;
  }
  uint16_t x = 0, y = 0;
  const bool down = tft.getTouch(&x, &y, TOUCH_Z_MIN);
  if (down && !touchHeld) {
    touchHeld = true;
    if (millis() - lastTapMs > 150) { lastTapMs = millis(); onTap(x, y); }
  } else if (!down) {
    touchHeld = false;
  }
}

/* Crop list retry, result timeout. */
static void fertTick() {
  if (ui == UI_CROP && cropCount == 0 && pcAlive() && millis() - cropsAskedMs > 3000) {
    Serial.println(F("CROPS?"));
    cropsAskedMs = millis();
  }
  if (ui == UI_FERT && frState == 1 && millis() - frAskedMs > 20000) {
    frState = 3;
    strcpy(frError, "No answer from the PC app. Check that start.ps1 is running, then try again.");
    drawFertScreen();
  }
}


// ---------------------------------------------------------------------------
// Protocol
// ---------------------------------------------------------------------------

static uint32_t lastPcMs = 0;
static uint32_t lastHbMs = 0;                  // HB comes only from pc_client's main loop
static bool pcShownAlive = false;

static bool pcAlive() {
  return lastPcMs != 0 && millis() - lastPcMs < PC_ALIVE_MS;
}

static void handleLine(char *line) {
  size_t len = strlen(line);
  while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == ' ' || line[len - 1] == '\t')) {
    line[--len] = '\0';
  }
  if (len == 0) return;
  lastPcMs = millis();                         // any line proves the PC app is there

  if (strcmp(line, "HB") == 0) { lastHbMs = millis(); return; }
  if (strcmp(line, "PING") == 0) { Serial.println(F("PONG")); return; }
  if (handleFertLine(line)) return;                                       // FRB/FRT/FRL/FRE/FRX
  if (strncmp(line, "CROPS:", 6) == 0) { parseCrops(line + 6); return; }
  if (strncmp(line, "REGIONS:", 8) == 0) { parseRegions(line + 8); return; }
  if (strcmp(line, "TCAL") == 0) { touchCalibrate(); enterDash(); return; }
  if (strncmp(line, "TRAW:", 5) == 0) { touchDiag(constrain(atoi(line + 5), 1, 100)); return; }
  if (strncmp(line, "TOUCH:", 6) == 0) {                                 // test: a tap at x,y
    unsigned x = 0, y = 0;
    if (sscanf(line + 6, "%u,%u", &x, &y) == 2) onTap((uint16_t)x, (uint16_t)y);
    return;
  }
  if (strncmp(line, "GR:", 3) == 0) { gfxRow(line + 3); return; }       // Kannada/Hindi text rows
  if (strncmp(line, "GQ:", 3) == 0) { gfxBegin(1, line + 3); return; }
  if (strncmp(line, "GA:", 3) == 0) { gfxBegin(2, line + 3); return; }
  if (strncmp(line, "D:", 2) == 0) {           // dashboard readings from the PC app
    parseDash(line + 2);
    if (ui == UI_DASH && state == ST_IDLE && !aud.active) dashUpdate();
    return;
  }
  if (strcmp(line, "CLR") == 0) {
    if (ui != UI_CHAT) {                       // forget the chat, keep the current screen
      questionText[0] = '\0';
      answerSource[0] = '\0';
      pageCount = 0;
      gfxForget();
      mood = MOOD_IDLE;
      dashUpdate();
    } else {
      drawIdleScreen();
    }
    pcShownAlive = true;
    Serial.println(F("[esp] cleared"));
    return;
  }
  if (strcmp(line, "BEEP") == 0) { playChime(); Serial.println(F("[esp] beep")); return; }
  if (strncmp(line, "QR:", 3) == 0) {
    // QR:<url>  or  QR:<url>|<label>   (a deep link never contains a raw '|')
    char *url = line + 3;
    char *bar = strchr(url, '|');
    static char label[121];
    label[0] = '\0';
    if (bar) {
      *bar = '\0';
      bool dropped;
      sanitiseAscii(bar + 1, label, sizeof label, &dropped);
    }
    if (strlen(url) < 8 || strlen(url) > 200) {
      Serial.println(F("ERR:QR URL must be 8-200 characters"));
      return;
    }
    enterChat();
    drawQr(url, label);
    Serial.println(F("[esp] route QR shown"));
    return;
  }
  if (strcmp(line, "IDLE") == 0) {
    if (state == ST_BUSY) state = ST_IDLE;
    if (mood == MOOD_THINK || mood == MOOD_TALK) setMood(MOOD_IDLE);
    drawTitleBar("ready");
    return;
  }

  if (strncmp(line, "AUD:", 4) == 0) {
    startAudio((uint32_t)strtoul(line + 4, nullptr, 10));
    return;
  }
  if (strncmp(line, "VOL:", 4) == 0) {
    long v = strtol(line + 4, nullptr, 10);
    volumePct = (uint8_t)(v < 0 ? 0 : v > 100 ? 100 : v);
    Serial.printf("[esp] volume %u\n", volumePct);
    return;
  }
  if (strncmp(line, "MICREC:", 7) == 0) {
    if (state == ST_IDLE && !aud.active) startRecording(false, (uint32_t)strtoul(line + 7, nullptr, 10));
    else Serial.println(F("ERR:busy"));
    return;
  }
  if (strncmp(line, "MICRAW:", 7) == 0) {
    if (state == ST_IDLE && !aud.active) streamRaw((uint32_t)strtoul(line + 7, nullptr, 10));
    else Serial.println(F("ERR:busy"));
    return;
  }
  if (strncmp(line, "MICSLOT:", 8) == 0) {
    micSlot = line[8] == '0' ? 0 : 1;
    Serial.printf("[esp] mic slot forced to %d\n", micSlot);
    return;
  }

  if (len >= 2 && line[1] == ':') {
    const char *body = line + 2;
    switch (line[0]) {
      case 'L':
        enterChat();
        drawListening(body[0] ? body : "Listening... speak now");
        return;
      case 'M':
        drawLevel((int)strtol(body, nullptr, 10));
        return;
      case 'R': {
        bool dropped = false;
        sanitiseAscii(body, answerSource, sizeof(answerSource), &dropped);
        Serial.printf("[esp] source: %s\n", answerSource);
        return;
      }
      case 'Q':
        messageCount++;
        answerSource[0] = '\0';        // a new question has no source yet
        enterChat();
        setMood(MOOD_THINK);
        showQuestion(body);
        drawTitleBar("PROCESSING");
        Serial.printf("[esp] Q #%lu (%u chars)\n", (unsigned long)messageCount, (unsigned)strlen(body));
        return;
      case 'A':
        enterChat();
        showAnswer(body);
        drawTitleBar("answer");
        Serial.printf("[esp] A (%u chars, %d page%s)\n", (unsigned)strlen(body),
                      pageCount, pageCount == 1 ? "" : "s");
        return;
      case 'S':
        drawTitleBar(body);
        // the PC reports problems in the status line - look puzzled about them
        if (strstr(body, "error") || strstr(body, "didn't") || strstr(body, "no sound")) {
          setMood(MOOD_CONFUSED);
        }
        return;
      default:
        break;
    }
  }
  Serial.printf("ERR:unknown command: %.40s\n", line);
}

/* Non-blocking line reader. Over-long lines are truncated, never overflowed. */
static void pollSerial() {
  static char buf[MAX_LINE + 1];
  static size_t n = 0;
  static bool overflowed = false;

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      buf[n] = '\0';
      if (overflowed) Serial.println(F("[esp] warning: line was truncated"));
      handleLine(buf);
      n = 0;
      overflowed = false;
      // AUD: switches the link to binary audio, and MICREC starts streaming -
      // stop parsing lines at once.
      if (aud.active || state == ST_RECORDING) return;
      continue;
    }
    if (n < MAX_LINE) buf[n++] = c;
    else overflowed = true;
  }
}


// ---------------------------------------------------------------------------
// RFID card taps (UNO Q reader -> GPIO16 -> here -> PC -> attendance backend)
// ---------------------------------------------------------------------------
//
// The kiosk only passes taps on: the PC (pc_client.py) sends them to the
// backend, which decides who the card belongs to. Taps wait in a small queue
// while the kiosk is busy, because the PC reads no lines while it fetches an
// answer and discards its input before playing one.

static struct { char uid[30]; uint32_t atMs; } rfidQueue[RFID_QUEUE_LEN];
static int rfidHead = 0, rfidCount = 0;

/* One call per tap, from rfid_receiver.cpp: `uid` is validated and
   de-duplicated. The extension point for anything else a tap should do. */
static void onRfidCardDetected(const char *uid) {
  if (rfidCount == RFID_QUEUE_LEN) {               // full: the oldest tap gives way
    Serial.printf("[esp] rfid: queue full, dropped %s\n", rfidQueue[rfidHead].uid);
    rfidHead = (rfidHead + 1) % RFID_QUEUE_LEN;
    rfidCount--;
  }
  const int slot = (rfidHead + rfidCount) % RFID_QUEUE_LEN;
  strncpy(rfidQueue[slot].uid, uid, sizeof(rfidQueue[slot].uid) - 1);
  rfidQueue[slot].uid[sizeof(rfidQueue[slot].uid) - 1] = '\0';
  rfidQueue[slot].atMs = millis();
  rfidCount++;
}

/* Hands queued taps to the PC, but only while the kiosk is idle and the PC's
   main loop is running (it sends HB every 2 s), so no tap is sent into a
   moment where the PC would throw it away. */
static void forwardRfidEvents() {
  if (!rfidCount || state != ST_IDLE || aud.active) return;
  if (lastHbMs == 0 || millis() - lastHbMs > PC_ALIVE_MS) return;
  while (rfidCount) {
    const uint32_t age = millis() - rfidQueue[rfidHead].atMs;
    if (age > RFID_MAX_AGE_MS) Serial.printf("[esp] rfid: %s waited too long, dropped\n", rfidQueue[rfidHead].uid);
    else Serial.printf("RFID:%s age=%lu\n", rfidQueue[rfidHead].uid, (unsigned long)age);
    rfidHead = (rfidHead + 1) % RFID_QUEUE_LEN;
    rfidCount--;
  }
}


// ---------------------------------------------------------------------------

void setup() {
  // Larger than the defaults: received speech waits in the driver while the
  // loop draws, and outgoing mic audio queues while the USB bridge catches up.
  Serial.setRxBufferSize(4096);
  Serial.setTxBufferSize(8192);
  Serial.begin(SERIAL_BAUD);
  delay(200);

  pinMode(BTN_TALK, INPUT_PULLUP);

  tft.init();
  tft.setRotation(1);
  mood = MOOD_SLEEPY;                          // the chat face, for when chat is opened
  touchBegin();
  // Holding the button while the board starts (1.5 s) calibrates the touch screen.
  if (digitalRead(BTN_TALK) == LOW) {
    const uint32_t t0 = millis();
    while (digitalRead(BTN_TALK) == LOW && millis() - t0 < 1500) delay(10);
    if (millis() - t0 >= 1500) {
      touchCalibrate();
      while (digitalRead(BTN_TALK) == LOW) delay(10);   // let go before normal use
      btnArmed = true;
    }
  }
  ui = UI_DASH;                                // boot into the farm dashboard
  dashDrawFrame();

  const bool ampOk = ampBegin();
  const bool micOk = micBegin();

  setup_t cfg;
  tft.getSetup(cfg);
  Serial.println();
  Serial.println(F("[esp] Smart Krishi kiosk - push-to-talk"));
  Serial.printf("[esp] TFT driver 0x%04X %dx%d  CS=%d DC=%d RST=%d\n",
                cfg.tft_driver, cfg.tft_width, cfg.tft_height,
                cfg.pin_tft_cs, cfg.pin_tft_dc, cfg.pin_tft_rst);
  Serial.printf("[esp] speaker MAX98357A  BCLK=%d LRC=%d DIN=%d  %d Hz 16-bit  volume %u  %s\n",
                AMP_BCLK, AMP_LRC, AMP_DIN, PLAY_RATE, volumePct, ampOk ? "ok" : "FAILED");
  Serial.printf("[esp] mic INMP441  SCK=%d WS=%d SD=%d  %d Hz  %s\n",
                MIC_SCK, MIC_WS, MIC_SD, MIC_RATE, micOk ? "ok" : "FAILED");
  if (micOk) micSlot = detectMicSlot();
  Serial.printf("[esp] button GPIO%d: tap (<%d ms) = dashboard/chat, hold = talk; debounce %d ms\n",
                BTN_TALK, REC_MIN_MS, BTN_DEBOUNCE_MS);
  Serial.printf("[esp] touch XPT2046 CS=%d (IRQ unused): %s\n", TOUCH_CS,
                touchReady ? "calibrated" : "NOT calibrated - press the screen firmly to start calibration");
  Serial.println(F("[esp] screen: dashboard"));
  rfidBegin(onRfidCardDetected);
  Serial.println(F("[esp] ready"));
}

void loop() {
  // --- talk button -----------------------------------------------------------
  // One button, two gestures:
  //   tap  (released before REC_MIN_MS) -> switch dashboard <-> chat
  //   hold (REC_MIN_MS or longer)       -> push-to-talk, from either screen
  // Recording starts at the press, so a hold loses no speech; a tap's audio is
  // discarded (REC:CANCEL tap). Presses while an answer is being prepared or
  // spoken are ignored, as before.
  static bool pressNoRec = false;              // pressed while the PC app was offline
  static uint32_t pressMs = 0;
  const int edge = pollButton();
  if (edge == 1) {
    if (state == ST_IDLE && !aud.active && btnArmed) {
      btnArmed = false;                        // needs a release before the next press
      pressMs = millis();
      if (!pcAlive()) {
        pressNoRec = true;                     // a tap still switches screens
        Serial.println(F("[esp] button pressed - PC app not connected, not recording"));
      } else {
        Serial.println(F("[esp] button pressed - recording"));
        startRecording(true, REC_MAX_MS);
      }
    } else if (state != ST_RECORDING) {
      Serial.println(F("[esp] button pressed - ignored: still answering"));
    }
  } else if (edge == -1) {
    btnArmed = true;
    if (state == ST_RECORDING && recFromButton) {
      Serial.printf("[esp] button released after %lu ms\n", (unsigned long)(millis() - recStartMs));
      stopRecording();
    } else if (pressNoRec) {
      pressNoRec = false;
      if (millis() - pressMs < REC_MIN_MS) {
        toggleScreen();
      } else {
        enterChat();
        setMood(MOOD_SLEEPY);
        bubbleMessage("Zzz...", "I need the PC app to answer. Start it with start.ps1, then ask again.", COL_MUTE);
        drawTitleBar("PC offline");
      }
    }
  }

  // --- recording: keep the mic stream flowing, nothing else ------------------
  buddyTick();
  rfidPoll();                                  // never blocks; card taps are queued

  if (state == ST_RECORDING) {
    pumpMic();
    if (recFromButton && !recShown && millis() - recStartMs >= REC_MIN_MS) {
      recShown = true;                         // a hold: this is a question
      enterChat();                             // pumps the mic between its drawing steps
      pumpMic();
      drawListening("Listening... speak now");
      pumpMic();
    }
    if (millis() - recStartMs >= recLimitMs) {
      if (recFromButton) Serial.println(F("[esp] recording hit the time limit"));
      stopRecording();
    }
    return;
  }

  // --- playback or commands ----------------------------------------------------
  if (aud.active) {
    serviceAudio();
  } else {
    pollSerial();
  }

  if (state == ST_BUSY && millis() - busySinceMs > BUSY_TIMEOUT_MS) {
    state = ST_IDLE;
    Serial.println(F("[esp] no answer from the PC - ready again"));
    setMood(MOOD_CONFUSED);
    bubbleMessage("Sorry!", "I didn't get an answer from the PC. Please ask me again.");
    drawTitleBar("no answer");
  }

  // --- route QR: back to the idle screen when nobody is using it -------------
  if (qrShown && state == ST_IDLE && !aud.active && millis() - qrSinceMs > QR_SHOW_MS) {
    drawIdleScreen();
    if (!pcShownAlive) { setMood(MOOD_SLEEPY); drawOfflineBubble(); }
  }

  // --- PC link indicator -----------------------------------------------------
  if (state == ST_IDLE && !aud.active && pcAlive() != pcShownAlive) {
    pcShownAlive = pcAlive();
    if (ui == UI_CHAT) {
      drawTitleBar(pcShownAlive ? "ready" : "PC offline");
      if (!pcShownAlive) {
        setMood(MOOD_SLEEPY);
        drawOfflineBubble();
      } else if (mood == MOOD_SLEEPY) {
        setMood(MOOD_IDLE);
        drawIdleBubble();
      }
    } else {
      mood = pcShownAlive ? (mood == MOOD_SLEEPY ? MOOD_IDLE : mood) : MOOD_SLEEPY;
      dashUpdate();
    }
  }

  // --- dashboard: age counter and link state, once a second -----------------
  if (ui == UI_DASH && state == ST_IDLE && !aud.active) dashTick();

  // --- touch screen and the fertilizer screens (never during audio) ----------
  if (state == ST_IDLE && !aud.active && !qrShown) {
    pollTouch();
    fertTick();
  }

  forwardRfidEvents();

  if (!aud.active) delay(1);
}

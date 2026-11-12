// UART2 receiver for the UNO Q RFID sender. The parsing itself lives in
// rfid_frame.h (host-tested in rfid/tests/); this file only moves bytes and
// writes "[esp]" log lines, which pc_client.py shows as "kiosk: ...".
#include <Arduino.h>
#include "config.h"
#include "rfid_frame.h"
#include "rfid_receiver.h"

#if RFID_ENABLED

static HardwareSerial rfidSerial(RFID_UART_NUM);
static rfidlink::LineParser parser;
static RfidCardCallback cardCallback = nullptr;

static char lastUid[rfidlink::MAX_UID_TEXT + 1] = "";
static uint32_t lastUidMs = 0;

// Rejected lines are counted and reported at most once a second, so a burst of
// boot noise from the UNO Q cannot flood the PC link.
static uint32_t rejectedSinceLog = 0, lastRejectLogMs = 0;
static rfidlink::Reject lastReject = rfidlink::REJ_NONE;

void rfidBegin(RfidCardCallback onCard) {
  cardCallback = onCard;
  rfidSerial.setRxBufferSize(RFID_RX_BUFFER);           // must precede begin()
  // TX pin -1: only RX is routed, GPIO17 is left untouched.
  rfidSerial.begin(RFID_BAUD, SERIAL_8N1, RFID_RX_PIN, -1);
  Serial.printf("[esp] rfid: UART%d RX=GPIO%d %d baud (receive only)\n",
                RFID_UART_NUM, RFID_RX_PIN, RFID_BAUD);
}

static void handle(const rfidlink::Event &ev, uint32_t now) {
  switch (ev.kind) {
    case rfidlink::KIND_CARD:
      if (strcmp(ev.uid, lastUid) == 0 && now - lastUidMs < RFID_SAME_CARD_MS) {
        Serial.printf("[esp] rfid: repeat of %s ignored\n", ev.uid);
        lastUidMs = now;
        return;
      }
      strcpy(lastUid, ev.uid);
      lastUidMs = now;
      Serial.printf("[esp] rfid: card %s\n", ev.uid);
      if (cardCallback) cardCallback(ev.uid);
      return;
    case rfidlink::KIND_HELLO:
      Serial.printf("[esp] rfid: sender says %s\n", ev.text);
      return;
    default:
      rejectedSinceLog++;
      lastReject = ev.reason;
      return;
  }
}

void rfidPoll() {
  const uint32_t now = millis();
  rfidlink::Event ev;
  for (int i = 0; i < RFID_MAX_BYTES_POLL && rfidSerial.available() > 0; i++) {
    const int c = rfidSerial.read();
    if (c < 0) break;
    if (parser.feed((uint8_t)c, now, ev)) handle(ev, now);
  }
  if (rejectedSinceLog && now - lastRejectLogMs >= 1000) {
    Serial.printf("[esp] rfid: ignored %lu line(s), last: %s\n",
                  (unsigned long)rejectedSinceLog, rfidlink::rejectName(lastReject));
    rejectedSinceLog = 0;
    lastRejectLogMs = now;
  }
}

#else

void rfidBegin(RfidCardCallback) {}
void rfidPoll() {}

#endif

#pragma once
// RFID link parser for frames from the UNO Q card reader (docs/RFID_PROTOCOL.md).
//
//   RFID:A3:2F:91:0C\n        a card was tapped (4, 7 or 10 UID bytes)
//   HELLO:RFID/1 ...\n        optional sender status line
//
// Board-independent (no Arduino calls), so rfid/tests/ compiles and tests this
// exact file on a PC. Fed one byte at a time; never blocks, never allocates,
// and never writes past its buffers whatever arrives on the wire - including
// the Zephyr boot messages the UNO Q prints on the same pin at power-up.

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace rfidlink {

static const size_t MAX_LINE = 64;          // longer lines are discarded whole
static const size_t MAX_UID_TEXT = 29;      // 10 bytes "XX:" x 10 - 1

enum Kind : uint8_t { KIND_CARD, KIND_HELLO, KIND_REJECTED };
enum Reject : uint8_t {
  REJ_NONE,
  REJ_NOT_A_FRAME,    // a line that is not ours (boot banner, noise)
  REJ_BAD_UID,        // "RFID:" but the UID is not 4/7/10 uppercase hex pairs
  REJ_OVERLONG,       // more than MAX_LINE characters before the newline
  REJ_BAD_CHAR,       // a byte outside printable ASCII
  REJ_STALE,          // a partial line that stopped arriving (cut off mid-frame)
};

struct Event {
  Kind kind;
  Reject reason;
  char uid[MAX_UID_TEXT + 1];    // KIND_CARD
  char text[MAX_LINE + 1];       // KIND_HELLO: the text after "HELLO:"
};

inline bool isUpperHex(char c) { return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'); }

/* "A3:2F:91:0C" with 4, 7 or 10 bytes, uppercase only. */
inline bool validUid(const char *s) {
  const size_t len = strlen(s);
  if (len != 11 && len != 20 && len != 29) return false;
  for (size_t i = 0; i < len; i++) {
    const bool sep = (i % 3) == 2;
    if (sep ? s[i] != ':' : !isUpperHex(s[i])) return false;
  }
  return true;
}

class LineParser {
 public:
  explicit LineParser(uint32_t partialTimeoutMs = 1000) : timeoutMs_(partialTimeoutMs) {}

  /* Feed one received byte. Returns true when `ev` holds a finished line's
     result (a card, a hello, or a rejection). Empty lines produce nothing. */
  bool feed(uint8_t c, uint32_t nowMs, Event &ev) {
    // A frame is sent in one burst (35 bytes take 3 ms at 115200 baud), so a
    // line left unfinished for a whole second was cut off. Drop it so it cannot
    // glue onto the next line. The timeout is measured between reads, so it is
    // kept longer than any blocking step of the kiosk loop (the chime, a page
    // redraw): a frame that waited in the UART buffer is never mistaken for one.
    const bool stale = (len_ || overlong_ || badChar_) && nowMs - lastByteMs_ > timeoutMs_;
    lastByteMs_ = nowMs;
    if (stale) {
      reset();
      // This byte starts the next line. On an empty buffer one byte can never
      // complete a line, so it produces no event of its own.
      Event ignored;
      consume(c, ignored);
      return reject(ev, REJ_STALE);
    }
    return consume(c, ev);
  }

  struct Stats {
    uint32_t cards = 0, hellos = 0, notFrames = 0, badUids = 0, overlong = 0, badChars = 0, stale = 0;
  } stats;

 private:
  bool consume(uint8_t c, Event &ev) {
    if (c == '\r') return false;
    if (c == '\n') {
      const bool over = overlong_, bad = badChar_;
      const size_t n = len_;
      buf_[len_] = '\0';
      reset();
      if (over) return reject(ev, REJ_OVERLONG);
      if (bad) return reject(ev, REJ_BAD_CHAR);
      if (n == 0) return false;
      return classify(ev);
    }
    if (overlong_) return false;
    if (c < 0x20 || c > 0x7E) badChar_ = true;
    if (len_ >= MAX_LINE) { overlong_ = true; return false; }
    buf_[len_++] = (char)c;
    return false;
  }

  bool classify(Event &ev) {
    if (strncmp(buf_, "RFID:", 5) == 0) {
      if (!validUid(buf_ + 5)) return reject(ev, REJ_BAD_UID);
      ev.kind = KIND_CARD;
      ev.reason = REJ_NONE;
      strcpy(ev.uid, buf_ + 5);           // length checked by validUid
      ev.text[0] = '\0';
      stats.cards++;
      return true;
    }
    if (strncmp(buf_, "HELLO:", 6) == 0) {
      ev.kind = KIND_HELLO;
      ev.reason = REJ_NONE;
      ev.uid[0] = '\0';
      strcpy(ev.text, buf_ + 6);          // shorter than buf_
      stats.hellos++;
      return true;
    }
    return reject(ev, REJ_NOT_A_FRAME);
  }

  bool reject(Event &ev, Reject why) {
    ev.kind = KIND_REJECTED;
    ev.reason = why;
    ev.uid[0] = ev.text[0] = '\0';
    switch (why) {
      case REJ_NOT_A_FRAME: stats.notFrames++; break;
      case REJ_BAD_UID: stats.badUids++; break;
      case REJ_OVERLONG: stats.overlong++; break;
      case REJ_BAD_CHAR: stats.badChars++; break;
      case REJ_STALE: stats.stale++; break;
      default: break;
    }
    return true;
  }

  void reset() { len_ = 0; overlong_ = badChar_ = false; }

  char buf_[MAX_LINE + 1] = "";
  size_t len_ = 0;
  bool overlong_ = false, badChar_ = false;
  uint32_t timeoutMs_, lastByteMs_ = 0;
};

inline const char *rejectName(Reject r) {
  switch (r) {
    case REJ_NOT_A_FRAME: return "not a frame";
    case REJ_BAD_UID: return "bad UID";
    case REJ_OVERLONG: return "too long";
    case REJ_BAD_CHAR: return "bad characters";
    case REJ_STALE: return "cut off";
    default: return "ok";
  }
}

}  // namespace rfidlink

#pragma once
// Receives card taps from the UNO Q RFID sender on UART2 (RX only, GPIO16).
// Non-blocking: call rfidPoll() every loop pass. docs/RFID_PROTOCOL.md

typedef void (*RfidCardCallback)(const char *uid);

/* Starts UART2 on RFID_RX_PIN. `onCard` is called once per tap, with the UID
   as "A3:2F:91:0C" (already validated and de-duplicated). */
void rfidBegin(RfidCardCallback onCard);

/* Parses whatever has arrived (at most RFID_MAX_BYTES_POLL bytes per call). */
void rfidPoll();

"""Hardware self-test for the Smart Krishi kiosk (same as Campus Mithra's). No server, no Gemma needed.

    python scripts/esp32_selftest.py              auto-detect the board
    python scripts/esp32_selftest.py --port COM9
    python scripts/esp32_selftest.py --volume 30  start quieter

Checks, in order, so a fault points at one thing (runs without the server):
  1. the USB link        (PING -> PONG)
  2. the screen          (a question and a long, multi-page answer)
  3. the speaker         (a chime, then real speech streamed from the PC)

Speech is made with the same edge-tts voice and 16-bit conversion the server
uses for the MAX98357A, so if this sounds right, answers will too. Needs internet for edge-tts.
Close `pio device monitor` first - only one program can hold the COM port.
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from krishi_client import connect_esp32  # noqa: E402

QUESTION = "What causes yellow leaves in tomato plants?"
ANSWER = ("Yellow leaves on tomato have several possible causes. Nitrogen deficiency makes the "
          "older, lower leaves turn evenly pale yellow first. Magnesium deficiency makes older "
          "leaves yellow between the veins. Overwatering damages the roots, so leaves turn yellow "
          "and plants wilt even though the soil is wet. Early blight starts as brown spots with "
          "rings like a target on lower leaves, and leaf curl virus is spread by whiteflies.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="", help="COM port (auto-detected if omitted)")
    ap.add_argument("--volume", type=int, default=None, help="speaker volume 0-100")
    args = ap.parse_args()

    print("1. USB link")
    esp = connect_esp32(args.port, args.volume)
    if esp is None:
        return 1

    try:
        print("\n2. Screen - a question, then an answer long enough to need pages")
        esp.status("self test")
        esp.question(QUESTION)
        time.sleep(0.8)
        esp.answer(ANSWER)
        print("   Look at the TFT: question on top, answer below with a page counter.")

        print("\n3. Speaker - chime")
        esp.beep()
        time.sleep(0.6)

        print("   Speaker - speech (edge-tts -> 16-bit 16 kHz -> USB -> I2S -> MAX98357A)")
        import speech
        voice = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
        rate = int(os.getenv("ESP_I2S_RATE", "16000"))
        t0 = time.time()
        mp3 = asyncio.run(speech.synth_mp3(speech.for_speech(ANSWER), voice))
        pcm = speech.mp3_to_pcm16(mp3, rate)
        print(f"   synthesised {len(pcm) / 2 / rate:.1f}s of audio in {time.time() - t0:.1f}s, streaming ...")
        t0 = time.time()
        ok, note = esp.play(pcm, bytes_per_second=2 * rate)
        took = time.time() - t0
        print(f"   {'OK' if ok else 'FAILED'}: {note}  (wall time {took:.1f}s)")
        if ok and "gap" in note:
            print("   Gaps mean the buffer ran dry: check the USB cable or try a lower volume of\n"
                  "   other USB traffic. A gap or two at the start is harmless.")
        esp.status("self test done")
        print("\nIf the screen showed both panels and you heard a chime and the full answer,")
        print("the kiosk hardware is working. Next:  .\\start.ps1  (or python krishi_client.py)")
        return 0 if ok else 1
    finally:
        esp.close()


if __name__ == "__main__":
    sys.exit(main())

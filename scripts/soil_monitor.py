"""Live soil-moisture monitor for the UNO Q sensor device (Ctrl+C to stop).

    .\\.venv\\Scripts\\python scripts\\soil_monitor.py            follow live, one line per reading (5 s)
    .\\.venv\\Scripts\\python scripts\\soil_monitor.py --last 30  the last 30 readings, then exit

Reads the Smart Krishi sensors app's log on the UNO Q over USB (adb, installed
with the Arduino UNO Q board package), so it works while the kiosk is running.
The raw value is the 14-bit ADC reading (0-16383): on this HW-080 probe, higher
means drier. Moisture % = (DRY - RAW) / (DRY - WET) x 100 is computed on the
UNO Q from soil_dry_raw / soil_wet_raw in its python/config.json (calibrated
12 Nov 2026: DRY 16370 = in air, WET 7950 = in water).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP = "/home/arduino/ArduinoApps/smart-krishi-sensors"
LINE = re.compile(r"#(\d+) T=(\S+) RH=(\S+) soil_raw=(\d+)(?: soil_pct=(\S+))? soil_valid=(\w+) mq135_raw=(\d+) faults=(\S+)")


def find_adb() -> str:
    for cand in (shutil.which("adb"),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Arduino15/packages/arduino/tools/adb/32.0.0/adb.exe"):
        if cand and Path(cand).exists():
            return str(cand)
    sys.exit("adb not found: install the Arduino UNO Q board package (Arduino IDE / App Lab).")


def meaning(raw: int, faults: str) -> str:
    if "soil_saturated_high" in faults:
        return "TOP OF RANGE: probe in air, very dry, or a wire loose"
    if "soil_near_zero" in faults:
        return "NEAR ZERO: probe shorted or disconnected?"
    if "soil_noisy" in faults:
        return "NOISY: readings jumping - check the wiring"
    if raw >= 15500:
        return "very dry, or the probe is barely touching soil"
    return "in soil (higher = drier; ~14000 was seen in soil here)"


def main():
    ap = argparse.ArgumentParser(description="UNO Q soil moisture monitor")
    ap.add_argument("--last", type=int, help="show the last N readings and exit")
    args = ap.parse_args()
    adb = find_adb()
    cmd = [adb, "shell", "arduino-app-cli", "app", "logs", APP] + (["--tail", str(args.last)] if args.last else ["--follow", "--tail", "1"])
    print("reading   moisture   soil_raw   change   status")
    prev = None
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace") as p:
        try:
            for line in p.stdout:
                m = LINE.search(line)
                if not m:
                    if "error" in line.lower() or "failed" in line.lower():
                        print("  " + line.strip())
                    continue
                seq, raw, pct, faults = int(m[1]), int(m[4]), m[5], m[8]
                change = "" if prev is None else f"{raw - prev:+d}"
                moist = f"{float(pct):5.1f} %" if pct and pct != "-" else "  --   "
                print(f"#{seq:<7} {moist:>8}   {raw:>8}   {change:>6}   {meaning(raw, faults)}")
                prev = raw
        except KeyboardInterrupt:
            p.terminate()


if __name__ == "__main__":
    main()

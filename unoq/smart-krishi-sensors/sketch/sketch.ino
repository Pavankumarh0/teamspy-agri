/*
 * Smart Krishi - sensor collector for the Arduino UNO Q (STM32U585, Zephyr core)
 *
 * Built on the working "test-moisture" App Lab sketch: same pins, same DHT11,
 * same 14-bit ADC. What is new: median-filtered analog readings, validity
 * checks and fault flags, a non-blocking 5 s schedule, and the hand-off to the
 * UNO Q's Linux side through the App Lab Bridge (the STM32 has no network of
 * its own; python/main.py on the Linux side does the HTTP POST).
 *
 *   DHT11 DATA        -> D2   (temperature degC, relative humidity %)
 *   HW-080 soil AO    -> A0   (3.3 V supply)
 *   MQ-135 AO         -> A1   through a voltage divider: 5 V sensor output
 *                             must never exceed 3.3 V at A1 (see README)
 *   all grounds common
 *
 * Every 5 s:  Bridge.notify("krishi_reading", ...)  -> python/main.py
 * Debug:      Monitor (App Lab console / Arduino IDE serial monitor)
 *
 * Nothing is converted into units the hardware cannot measure: soil and
 * MQ-135 are sent as raw ADC counts. The soil percentage is only computed on
 * the Linux side, and only once calibration values are configured.
 */

#include <Arduino_RouterBridge.h>
#include <DHT.h>

// ---------- pins and sensor type (from the working test-moisture sketch) ----------
#define DHTPIN     2
#define DHTTYPE    DHT11
#define SOIL_PIN   A0
#define MQ135_PIN  A1

// ---------- ADC ----------
#define ADC_BITS        14
#define ADC_MAX         ((1 << ADC_BITS) - 1)      // 16383
#define ANALOG_SAMPLES  15                          // median of 15 reads per channel
// Readings this close to the rails are treated as invalid until investigated:
// a pegged soil probe (16363 was seen on this board) means dry air, a broken
// wire or wrong wiring, not "very dry soil".
#define RAIL_HIGH       (ADC_MAX - 64)              // >= 16319
#define RAIL_LOW        16                          // <= 16: shorted / not connected

// ---------- timing ----------
#define SAMPLE_MS        5000UL     // one reading every 5 s
#define MQ135_WARMUP_MS  180000UL   // first 3 min after power-up: heater still warming

// ---------- DHT11 plausible range (datasheet: 0-50 degC, 20-90 %RH) ----------
#define T_MIN  -10.0f
#define T_MAX   60.0f

// Fault bits, decoded into names on the Linux side.
enum : uint32_t {
  F_DHT_READ      = 1u << 0,   // DHT returned NaN (wiring, timing, sensor)
  F_DHT_RANGE     = 1u << 1,   // value outside the plausible range
  F_SOIL_HIGH     = 1u << 2,   // soil ADC pegged near 16383
  F_SOIL_LOW      = 1u << 3,   // soil ADC near 0
  F_SOIL_NOISY    = 1u << 4,   // samples spread too widely to trust
  F_MQ_HIGH       = 1u << 5,   // MQ-135 ADC pegged: divider missing or wrong?
  F_MQ_LOW        = 1u << 6,   // MQ-135 ADC near 0: not connected / no heater supply
  F_MQ_WARMUP     = 1u << 7,   // heater warm-up period after power-up
  F_MQ_NOISY      = 1u << 8,
};
#define NOISE_SPREAD  2000          // max-min of the middle samples above this = noisy

DHT dht(DHTPIN, DHTTYPE);
static uint32_t lastSampleMs = 0;
static uint32_t seq = 0;

static void sortInts(int *a, int n) {
  for (int i = 1; i < n; i++) {               // insertion sort: 15 values
    int v = a[i], j = i - 1;
    while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; }
    a[j + 1] = v;
  }
}

/* Median of ANALOG_SAMPLES reads; spread = range of the middle two thirds. */
static int readMedian(uint8_t pin, int *spread) {
  int s[ANALOG_SAMPLES];
  for (int i = 0; i < ANALOG_SAMPLES; i++) {
    s[i] = analogRead(pin);
    delayMicroseconds(200);                   // ~3 ms per channel in total
  }
  sortInts(s, ANALOG_SAMPLES);
  const int lo = ANALOG_SAMPLES / 6, hi = ANALOG_SAMPLES - 1 - ANALOG_SAMPLES / 6;
  *spread = s[hi] - s[lo];
  return s[ANALOG_SAMPLES / 2];
}

static void sample() {
  uint32_t faults = 0;

  // --- DHT11 (the library itself enforces the 2 s minimum between reads) ---
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  bool dhtOk = !(isnan(t) || isnan(h));
  if (!dhtOk) {
    faults |= F_DHT_READ;
  } else if (t < T_MIN || t > T_MAX || h < 0.0f || h > 100.0f) {
    faults |= F_DHT_RANGE;
    dhtOk = false;
  }

  // --- soil (HW-080) ---
  int soilSpread = 0;
  const int soilRaw = readMedian(SOIL_PIN, &soilSpread);
  bool soilValid = true;
  if (soilRaw >= RAIL_HIGH) { faults |= F_SOIL_HIGH; soilValid = false; }
  if (soilRaw <= RAIL_LOW)  { faults |= F_SOIL_LOW;  soilValid = false; }
  if (soilSpread > NOISE_SPREAD) { faults |= F_SOIL_NOISY; soilValid = false; }

  // --- MQ-135 ---
  int mqSpread = 0;
  const int mqRaw = readMedian(MQ135_PIN, &mqSpread);
  bool mqValid = true;
  if (mqRaw >= RAIL_HIGH) { faults |= F_MQ_HIGH; mqValid = false; }
  if (mqRaw <= RAIL_LOW)  { faults |= F_MQ_LOW;  mqValid = false; }
  if (mqSpread > NOISE_SPREAD) { faults |= F_MQ_NOISY; mqValid = false; }
  if (millis() < MQ135_WARMUP_MS) { faults |= F_MQ_WARMUP; mqValid = false; }

  seq++;
  // To the Linux side. Floats are sent even when invalid (0), with dhtOk saying
  // whether to use them: NaN does not survive the trip into JSON.
  Bridge.notify("krishi_reading", dhtOk, dhtOk ? t : 0.0f, dhtOk ? h : 0.0f,
                soilRaw, soilValid, mqRaw, mqValid, (int)faults, (int)seq, (int)(millis() / 1000));

  // --- debug output, as in the original sketch ---
  Monitor.println("\n--- SMART KRISHI SENSOR DATA #" + String(seq) + " ---");
  if (dhtOk) {
    Monitor.println("Temperature: " + String(t, 1) + " C");
    Monitor.println("Humidity: " + String(h, 0) + " %");
  } else {
    Monitor.println(String("DHT11: ") + ((faults & F_DHT_READ) ? "reading failed" : "out of range"));
  }
  Monitor.println("Soil Moisture Raw: " + String(soilRaw) + " (spread " + String(soilSpread) + ")" +
                  (soilValid ? "" : "  INVALID"));
  Monitor.println("MQ135 Raw: " + String(mqRaw) + " (spread " + String(mqSpread) + ")" +
                  (mqValid ? "" : ((faults & F_MQ_WARMUP) ? "  warming up" : "  INVALID")));
  Monitor.println("faults: 0x" + String(faults, HEX));
}

void setup() {
  Bridge.begin();
  Monitor.begin(115200);
  analogReadResolution(ADC_BITS);
  dht.begin();
  Monitor.println("SMART KRISHI SENSOR COLLECTOR");
  Monitor.println("DHT11 D2, soil A0, MQ-135 A1, 14-bit ADC, every 5 s");
  lastSampleMs = millis() - SAMPLE_MS + 2500;   // first reading after 2.5 s (DHT settle)
}

void loop() {
  const uint32_t now = millis();
  if (now - lastSampleMs >= SAMPLE_MS) {
    lastSampleMs = now;
    sample();
  }
  delay(10);    // yield; the schedule above is what times the samples
}

// ============================================================
// Sharp GP2Y0A02YK0F + ESP32
// Read ONLY analog output voltage
//
// Sensor:
//   VCC -> ESP32 VIN
//   GND -> ESP32 GND
//   VO  -> ESP32 GPIO34
//
// Serial output:
//   Time(ms), ADC, Voltage(V)
// ============================================================

#include <Arduino.h>

const int SENSOR_PIN = 34;

// Sampling period
const unsigned long SAMPLE_INTERVAL_MS = 50;

unsigned long lastSampleTime = 0;


void setup() {

  // ----------------------------------------------------------
  // Serial communication
  // ----------------------------------------------------------
  Serial.begin(115200);

  delay(1000);

  // ----------------------------------------------------------
  // ESP32 ADC configuration
  // ----------------------------------------------------------

  // 12-bit ADC:
  // ADC value = 0 ... 4095
  analogReadResolution(12);

  // 11 dB attenuation gives a wider measurable voltage range.
  // GPIO34 belongs to ADC1, so it is suitable for analog input.
  analogSetPinAttenuation(SENSOR_PIN, ADC_11db);

  // ----------------------------------------------------------
  // Startup message
  // ----------------------------------------------------------

  Serial.println();
  Serial.println("========================================");
  Serial.println(" GP2Y0A02YK0F + ESP32 Voltage Logger");
  Serial.println("========================================");

  Serial.println();
  Serial.println("Wiring:");
  Serial.println("Sensor VCC -> ESP32 VIN");
  Serial.println("Sensor GND -> ESP32 GND");
  Serial.println("Sensor VO  -> ESP32 GPIO34");

  Serial.println();
  Serial.println("Serial format:");
  Serial.println("Time(ms),ADC,Voltage(V)");

  Serial.println();
  Serial.println("Starting measurement...");
  Serial.println();

  // CSV header
  Serial.println("Time(ms),ADC,Voltage(V)");

  delay(500);
}


void loop() {

  unsigned long currentTime = millis();

  // ----------------------------------------------------------
  // Sample every 50 ms
  // ----------------------------------------------------------

  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL_MS) {

    lastSampleTime = currentTime;

    // --------------------------------------------------------
    // Read ADC
    // --------------------------------------------------------

    int adcValue = analogRead(SENSOR_PIN);

    // --------------------------------------------------------
    // Convert ADC to calibrated millivolts
    // --------------------------------------------------------

    uint32_t voltage_mV = analogReadMilliVolts(SENSOR_PIN);

    float voltage_V = voltage_mV / 1000.0;


    // --------------------------------------------------------
    // Print data
    // --------------------------------------------------------

    Serial.print(currentTime);
    Serial.print(",");

    Serial.print(adcValue);
    Serial.print(",");

    Serial.println(voltage_V, 3);
  }
}

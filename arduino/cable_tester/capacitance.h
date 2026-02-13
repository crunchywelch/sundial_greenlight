// Capacitance measurement for cable tester
// Uses RC time constant method
//
// Circuit:
//   D7 (CAP_CHARGE)    --[2.2MΩ]--+-- to cable TIP (via test jack)
//                                 |
//   D8 (CAP_DISCHARGE) --[1kΩ]----+
//                                 |
//   A1 (CAP_SENSE) ---------------+
//
// Cable far end must be OPEN (K1+K2 HIGH, cont pins set to INPUT)
// K4 LOW = capacitance mode (TIP to cap circuit, SLEEVE to GND)

#ifndef CAPACITANCE_H
#define CAPACITANCE_H

// Pin definitions for capacitance measurement
#define CAP_CHARGE_PIN    7    // Digital out - charges cable through 2.2MΩ
#define CAP_DISCHARGE_PIN 8    // Digital out - discharges cable through 1kΩ
#define CAP_SENSE_PIN     A1   // Analog in - dedicated to capacitance (A0 is resistance)

// Circuit constants
#define CAP_CHARGE_RESISTOR 2200000.0  // 2.2MΩ charging resistor
#define CAP_DISCHARGE_RESISTOR 1000.0  // 1kΩ discharge resistor

// Measurement parameters
#define CAP_THRESHOLD_PERCENT 50       // Measure time to reach 50% of Vcc
#define CAP_ADC_THRESHOLD 512          // 50% of 1024 (10-bit ADC)
#define CAP_TIMEOUT_US 100000          // 100ms timeout
#define CAP_DISCHARGE_TIME_MS 10       // Time to fully discharge
#define CAP_NUM_SAMPLES 5              // Number of measurements to average

// Calibration - account for stray capacitance in test fixture
#define CAP_STRAY_PF 20.0              // Subtract this from measurements

// Result structure
struct CapacitanceResult {
  bool valid;
  float capacitance_pf;    // Measured capacitance in picofarads
  unsigned long charge_time_us;  // Time to reach threshold
  int num_samples;         // Number of valid samples averaged
};

// Note: Call this in main setup() after relay pins are configured
void setupCapacitancePins() {
  pinMode(CAP_CHARGE_PIN, OUTPUT);
  pinMode(CAP_DISCHARGE_PIN, OUTPUT);
  // CAP_SENSE_PIN (A1) is analog, no pinMode needed

  // Start in discharged state
  digitalWrite(CAP_CHARGE_PIN, LOW);
  digitalWrite(CAP_DISCHARGE_PIN, LOW);
}

// External relay control function (defined in main .ino)
extern void resetCircuit();  // Resets all relays

// Relay pins (needed for test mode switching)
extern const int K1_K2_RELAY_PIN;
extern const int K4_RELAY_PIN;

// Continuity output pins (need to set high-Z during cap test)
extern const int TS_CONT_OUT_SLEEVE_PIN;
extern const int TS_CONT_OUT_TIP_PIN;

// Discharge the cable completely
void dischargeCable() {
  digitalWrite(CAP_CHARGE_PIN, LOW);      // Stop charging
  digitalWrite(CAP_DISCHARGE_PIN, LOW);   // Pull to ground through 1kΩ
  delay(CAP_DISCHARGE_TIME_MS);           // Wait for full discharge
}

// Measure time to charge to threshold
// Returns time in microseconds, or 0 if timeout
unsigned long measureChargeTime() {
  // Make sure we're discharged
  dischargeCable();

  // Set discharge pin to high-impedance (input mode)
  pinMode(CAP_DISCHARGE_PIN, INPUT);

  // Record start time and begin charging
  unsigned long startTime = micros();
  digitalWrite(CAP_CHARGE_PIN, HIGH);

  // Wait for voltage to reach threshold
  unsigned long timeout = startTime + CAP_TIMEOUT_US;
  while (micros() < timeout) {
    int adcValue = analogRead(CAP_SENSE_PIN);
    if (adcValue >= CAP_ADC_THRESHOLD) {
      unsigned long chargeTime = micros() - startTime;

      // Stop charging and restore discharge pin
      digitalWrite(CAP_CHARGE_PIN, LOW);
      pinMode(CAP_DISCHARGE_PIN, OUTPUT);
      digitalWrite(CAP_DISCHARGE_PIN, LOW);

      return chargeTime;
    }
  }

  // Timeout - capacitance too high or open circuit
  digitalWrite(CAP_CHARGE_PIN, LOW);
  pinMode(CAP_DISCHARGE_PIN, OUTPUT);
  digitalWrite(CAP_DISCHARGE_PIN, LOW);

  return 0;
}

// Calculate capacitance from charge time
// For RC circuit charging to 50% of Vcc:
// V(t) = Vcc * (1 - e^(-t/RC))
// 0.5 = 1 - e^(-t/RC)
// e^(-t/RC) = 0.5
// -t/RC = ln(0.5) = -0.693
// C = t / (R * 0.693)
float calculateCapacitance(unsigned long chargeTimeUs) {
  if (chargeTimeUs == 0) return 0.0;

  // Convert time to seconds
  float timeSeconds = chargeTimeUs / 1000000.0;

  // Calculate capacitance in Farads
  // Using ln(2) = 0.693 for 50% threshold
  float capacitanceFarads = timeSeconds / (CAP_CHARGE_RESISTOR * 0.693);

  // Convert to picofarads
  float capacitancePf = capacitanceFarads * 1e12;

  // Subtract stray capacitance from test fixture
  capacitancePf -= CAP_STRAY_PF;
  if (capacitancePf < 0) capacitancePf = 0;

  return capacitancePf;
}

// Run capacitance measurement with averaging
CapacitanceResult measureCapacitance() {
  CapacitanceResult result;
  result.valid = false;
  result.capacitance_pf = 0;
  result.charge_time_us = 0;
  result.num_samples = 0;

  unsigned long totalTime = 0;
  int validSamples = 0;

  for (int i = 0; i < CAP_NUM_SAMPLES; i++) {
    unsigned long chargeTime = measureChargeTime();

    if (chargeTime > 0) {
      totalTime += chargeTime;
      validSamples++;
    }

    // Small delay between measurements
    delay(10);
  }

  if (validSamples > 0) {
    result.valid = true;
    result.charge_time_us = totalTime / validSamples;
    result.capacitance_pf = calculateCapacitance(result.charge_time_us);
    result.num_samples = validSamples;
  }

  return result;
}

// Run capacitance test and report via serial
// Returns true if capacitance is within expected range for audio cables
bool runCapacitanceTest() {
  // Configure for capacitance test mode
  // Far end must be OPEN (floating) - no DC path through cable
  // K1+K2 HIGH connects far end to continuity pins, set those to high-Z
  digitalWrite(K1_K2_RELAY_PIN, HIGH);  // Far end to continuity pins (not shorted)
  digitalWrite(K4_RELAY_PIN, LOW);       // Cap mode: TIP to cap circuit, SLEEVE to GND
  // Set continuity output pins to high-Z so far end floats
  pinMode(TS_CONT_OUT_SLEEVE_PIN, INPUT);
  pinMode(TS_CONT_OUT_TIP_PIN, INPUT);
  delay(20);  // Let relays settle

  CapacitanceResult result = measureCapacitance();

  // Restore continuity pins to OUTPUT mode and reset circuit
  pinMode(TS_CONT_OUT_SLEEVE_PIN, OUTPUT);
  digitalWrite(TS_CONT_OUT_SLEEVE_PIN, LOW);
  pinMode(TS_CONT_OUT_TIP_PIN, OUTPUT);
  digitalWrite(TS_CONT_OUT_TIP_PIN, LOW);
  resetCircuit();

  if (!result.valid) {
    Serial.println("CAP:FAIL:TIMEOUT:No charge detected");
    return false;
  }

  // Expected range for audio cables: 50-2000 pF
  // Adjust these based on your cable types
  bool inRange = (result.capacitance_pf >= 50 && result.capacitance_pf <= 2000);

  Serial.print("CAP:");
  Serial.print(inRange ? "PASS" : "WARN");
  Serial.print(":PF:");
  Serial.print(result.capacitance_pf, 1);
  Serial.print(":TIME_US:");
  Serial.print(result.charge_time_us);
  Serial.print(":SAMPLES:");
  Serial.println(result.num_samples);

  return inRange;
}

// Calibration routine - measure with test jacks shorted
// This measures the stray capacitance of your test fixture
void calibrateStrayCapacitance() {
  Serial.println("CAP_CAL:Starting stray capacitance calibration");
  Serial.println("CAP_CAL:Ensure NO cable is connected");
  delay(2000);

  // Same relay config as cap test
  digitalWrite(K1_K2_RELAY_PIN, HIGH);
  digitalWrite(K4_RELAY_PIN, LOW);
  pinMode(TS_CONT_OUT_SLEEVE_PIN, INPUT);
  pinMode(TS_CONT_OUT_TIP_PIN, INPUT);
  delay(20);

  CapacitanceResult result = measureCapacitance();

  // Restore
  pinMode(TS_CONT_OUT_SLEEVE_PIN, OUTPUT);
  digitalWrite(TS_CONT_OUT_SLEEVE_PIN, LOW);
  pinMode(TS_CONT_OUT_TIP_PIN, OUTPUT);
  digitalWrite(TS_CONT_OUT_TIP_PIN, LOW);
  resetCircuit();

  if (result.valid) {
    // Add back the stray we subtracted to get raw measurement
    float rawPf = result.capacitance_pf + CAP_STRAY_PF;
    Serial.print("CAP_CAL:Measured stray capacitance: ");
    Serial.print(rawPf, 1);
    Serial.println(" pF");
    Serial.print("CAP_CAL:Update CAP_STRAY_PF to ");
    Serial.print(rawPf, 0);
    Serial.println(" in capacitance.h");
  } else {
    Serial.println("CAP_CAL:FAILED - Could not measure");
  }
}

#endif // CAPACITANCE_H

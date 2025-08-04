/*
 * Greenlight Cable Tester - ATmega32 Arduino Sketch
 * 
 * Comprehensive audio cable testing system supporting:
 * - Continuity testing (tip, ring, sleeve)
 * - Polarity checking 
 * - DC resistance measurement
 * - Cable capacitance measurement
 * - USB serial communication with Raspberry Pi
 * 
 * Author: Greenlight Terminal System
 * Version: 1.0
 * 
 * Pin Configuration:
 * - A0-A5: Analog measurement inputs
 * - D2-D13: Digital I/O for relays and test signals
 * - Serial: USB communication (pins 0,1)
 */

#include <Arduino.h>

// ===== PIN DEFINITIONS =====
// Analog pins for measurements
#define CONTINUITY_SENSE_A0    A0    // Tip continuity measurement
#define CONTINUITY_SENSE_A1    A1    // Ring continuity measurement  
#define CONTINUITY_SENSE_A2    A2    // Sleeve continuity measurement
#define RESISTANCE_MEASURE     A3    // Precision resistance measurement
#define CAPACITANCE_MEASURE    A4    // Capacitance measurement input
#define VOLTAGE_MONITOR        A5    // Supply voltage monitoring

// Digital pins for test circuit control
#define TEST_RELAY_TIP         2     // Relay control for tip connection
#define TEST_RELAY_RING        3     // Relay control for ring connection
#define TEST_RELAY_SLEEVE      4     // Relay control for sleeve connection
#define POLARITY_TEST_PIN      5     // Polarity test signal output
#define RESISTANCE_CURRENT     6     // Precision current source control
#define CAPACITANCE_CHARGE     7     // Capacitance charging control
#define CALIBRATION_RELAY      8     // Calibration reference relay

// Status and indicator pins
#define STATUS_LED            13     // Built-in LED for status
#define ERROR_LED             12     // External error indicator
#define PASS_LED              11     // Test pass indicator
#define FAIL_LED              10     // Test fail indicator

// Test fixture pins
#define FIXTURE_DETECT         9     // Cable insertion detection

// ===== CONFIGURATION =====
const int UNIT_ID = 1;                    // Arduino unit identifier
const int BAUD_RATE = 9600;               // Serial communication speed
const float VOLTAGE_REF = 5.0;            // ADC reference voltage
const int ADC_RESOLUTION = 1024;          // 10-bit ADC resolution
const int MEASUREMENT_SAMPLES = 50;       // Samples for averaging

// Test thresholds
const float CONTINUITY_THRESHOLD_OHMS = 5.0;      // Max resistance for continuity
const float OPEN_CIRCUIT_THRESHOLD = 10000.0;     // Min resistance for open circuit
const float POLARITY_VOLTAGE_THRESHOLD = 2.5;     // Voltage threshold for polarity
const unsigned long CAPACITANCE_TIMEOUT_US = 100000; // 100ms timeout for cap test

// Calibration values (set during calibration)
float resistance_offset = 0.0;
float capacitance_offset = 0.0;
float voltage_calibration_factor = 1.0;

// ===== GLOBAL VARIABLES =====
bool system_ready = false;
unsigned long last_status_blink = 0;
bool status_led_state = false;

// Test results structure
struct TestResults {
  bool tip_continuity;
  bool ring_continuity;
  bool sleeve_continuity;
  bool polarity_correct;
  float resistance_ohms;
  float capacitance_pf;
  bool overall_pass;
  String error_message;
};

// ===== SETUP FUNCTION =====
void setup() {
  // Initialize serial communication
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ; // Wait for serial port to connect (needed for native USB)
  }
  
  // Initialize digital pins
  pinMode(TEST_RELAY_TIP, OUTPUT);
  pinMode(TEST_RELAY_RING, OUTPUT);
  pinMode(TEST_RELAY_SLEEVE, OUTPUT);
  pinMode(POLARITY_TEST_PIN, OUTPUT);
  pinMode(RESISTANCE_CURRENT, OUTPUT);
  pinMode(CAPACITANCE_CHARGE, OUTPUT);
  pinMode(CALIBRATION_RELAY, OUTPUT);
  
  pinMode(STATUS_LED, OUTPUT);
  pinMode(ERROR_LED, OUTPUT);
  pinMode(PASS_LED, OUTPUT);
  pinMode(FAIL_LED, OUTPUT);
  
  pinMode(FIXTURE_DETECT, INPUT_PULLUP);
  
  // Set initial states - all relays off, LEDs off
  digitalWrite(TEST_RELAY_TIP, LOW);
  digitalWrite(TEST_RELAY_RING, LOW);
  digitalWrite(TEST_RELAY_SLEEVE, LOW);
  digitalWrite(POLARITY_TEST_PIN, LOW);
  digitalWrite(RESISTANCE_CURRENT, LOW);
  digitalWrite(CAPACITANCE_CHARGE, LOW);
  digitalWrite(CALIBRATION_RELAY, LOW);
  
  digitalWrite(ERROR_LED, LOW);
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  
  // Power-on self test
  powerOnSelfTest();
  
  // Set system ready
  system_ready = true;
  digitalWrite(STATUS_LED, HIGH);
  
  // Send startup message
  Serial.println("ARDUINO_READY:UNIT_" + String(UNIT_ID));
  delay(100);
}

// ===== MAIN LOOP =====
void loop() {
  // Handle serial commands
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    handleSerialCommand(command);
  }
  
  // Status LED heartbeat
  statusHeartbeat();
  
  // Small delay to prevent overwhelming the system
  delay(10);
}

// ===== COMMAND HANDLING =====
void handleSerialCommand(String command) {
  if (command == "GET_UNIT_ID") {
    Serial.println("UNIT_ID:" + String(UNIT_ID));
    
  } else if (command == "GET_STATUS") {
    sendStatusResponse();
    
  } else if (command == "TEST_CABLE") {
    runFullCableTest();
    
  } else if (command == "CALIBRATE") {
    runCalibrationSequence();
    
  } else if (command == "RESET") {
    resetTestCircuit();
    Serial.println("RESET:COMPLETE");
    
  } else if (command == "SELF_TEST") {
    powerOnSelfTest();
    
  } else {
    Serial.println("ERROR:UNKNOWN_COMMAND:" + command);
  }
}

void sendStatusResponse() {
  String status = "STATUS:";
  status += system_ready ? "READY" : "NOT_READY";
  status += ":FIXTURE_";
  status += digitalRead(FIXTURE_DETECT) == LOW ? "INSERTED" : "EMPTY";
  status += ":VOLTAGE_" + String(measureSupplyVoltage(), 2);
  Serial.println(status);
}

// ===== CABLE TESTING FUNCTIONS =====
void runFullCableTest() {
  if (!system_ready) {
    Serial.println("ERROR:SYSTEM_NOT_READY");
    return;
  }
  
  // Check if cable is inserted
  if (digitalRead(FIXTURE_DETECT) == HIGH) {
    Serial.println("ERROR:NO_CABLE_IN_FIXTURE");
    return;
  }
  
  // Initialize test results
  TestResults results;
  results.overall_pass = true;
  results.error_message = "";
  
  // Turn on testing indicator
  digitalWrite(STATUS_LED, LOW);
  blinkLED(PASS_LED, 2, 100); // Brief "testing" indication
  
  // Step 1: Continuity Tests
  results.tip_continuity = testContinuity(TEST_RELAY_TIP, CONTINUITY_SENSE_A0, "TIP");
  delay(50);
  results.ring_continuity = testContinuity(TEST_RELAY_RING, CONTINUITY_SENSE_A1, "RING");
  delay(50);
  results.sleeve_continuity = testContinuity(TEST_RELAY_SLEEVE, CONTINUITY_SENSE_A2, "SLEEVE");
  delay(50);
  
  // Step 2: Polarity Test
  results.polarity_correct = testPolarity();
  delay(100);
  
  // Step 3: Resistance Measurement
  results.resistance_ohms = measureResistance();
  delay(100);
  
  // Step 4: Capacitance Measurement
  results.capacitance_pf = measureCapacitance();
  delay(100);
  
  // Determine overall pass/fail
  results.overall_pass = results.tip_continuity && 
                        results.ring_continuity && 
                        results.sleeve_continuity && 
                        results.polarity_correct &&
                        (results.resistance_ohms > 0.0) &&
                        (results.capacitance_pf > 0.0);
  
  // Send results
  sendTestResults(results);
  
  // Visual indication
  if (results.overall_pass) {
    digitalWrite(PASS_LED, HIGH);
    digitalWrite(FAIL_LED, LOW);
  } else {
    digitalWrite(PASS_LED, LOW);
    digitalWrite(FAIL_LED, HIGH);
  }
  
  // Reset test circuit
  resetTestCircuit();
  digitalWrite(STATUS_LED, HIGH);
}

bool testContinuity(int relay_pin, int sense_pin, String connection_name) {
  // Activate test relay
  digitalWrite(relay_pin, HIGH);
  delay(10); // Allow relay to settle
  
  // Apply small test voltage
  digitalWrite(POLARITY_TEST_PIN, HIGH);
  delay(5);
  
  // Measure voltage across test points
  float voltage = readAverageVoltage(sense_pin, 10);
  
  // Calculate resistance using voltage divider
  // Assumes 1K test resistor in series
  const float TEST_RESISTOR = 1000.0;
  float resistance = (voltage * TEST_RESISTOR) / (VOLTAGE_REF - voltage);
  
  // Clean up
  digitalWrite(POLARITY_TEST_PIN, LOW);
  digitalWrite(relay_pin, LOW);
  
  bool continuity_good = (resistance < CONTINUITY_THRESHOLD_OHMS);
  
  // Debug output
  Serial.println("DEBUG:" + connection_name + "_CONTINUITY:" + 
                String(continuity_good ? "PASS" : "FAIL") + 
                ":RESISTANCE:" + String(resistance, 3));
  
  return continuity_good;
}

bool testPolarity() {
  // Test polarity by applying known signal and measuring response
  digitalWrite(TEST_RELAY_TIP, HIGH);
  digitalWrite(TEST_RELAY_SLEEVE, HIGH);
  delay(10);
  
  // Apply positive test signal to tip
  digitalWrite(POLARITY_TEST_PIN, HIGH);
  delay(10);
  
  // Measure voltage at expected positive end
  float tip_voltage = readAverageVoltage(CONTINUITY_SENSE_A0, 5);
  
  // Apply negative (ground) to sleeve  
  digitalWrite(POLARITY_TEST_PIN, LOW);
  delay(10);
  
  float sleeve_voltage = readAverageVoltage(CONTINUITY_SENSE_A2, 5);
  
  // Clean up
  digitalWrite(TEST_RELAY_TIP, LOW);
  digitalWrite(TEST_RELAY_SLEEVE, LOW);
  
  // Check polarity - tip should be higher voltage than sleeve
  bool polarity_correct = (tip_voltage > sleeve_voltage + 0.5);
  
  Serial.println("DEBUG:POLARITY:" + 
                String(polarity_correct ? "CORRECT" : "REVERSED") +
                ":TIP_V:" + String(tip_voltage, 2) +
                ":SLEEVE_V:" + String(sleeve_voltage, 2));
  
  return polarity_correct;
}

float measureResistance() {
  // Precision resistance measurement using constant current method
  digitalWrite(TEST_RELAY_TIP, HIGH);
  digitalWrite(TEST_RELAY_SLEEVE, HIGH);
  digitalWrite(RESISTANCE_CURRENT, HIGH);
  delay(50); // Allow circuit to stabilize
  
  // Measure voltage drop across cable
  float voltage_drop = readAverageVoltage(RESISTANCE_MEASURE, MEASUREMENT_SAMPLES);
  
  // Calculate resistance using Ohm's law
  // Assumes known current source (e.g., 1mA)
  const float TEST_CURRENT_MA = 1.0;
  float resistance = (voltage_drop * 1000.0) / TEST_CURRENT_MA; // Convert to ohms
  
  // Apply calibration offset
  resistance += resistance_offset;
  
  // Clean up
  digitalWrite(RESISTANCE_CURRENT, LOW);
  digitalWrite(TEST_RELAY_TIP, LOW);
  digitalWrite(TEST_RELAY_SLEEVE, LOW);
  
  Serial.println("DEBUG:RESISTANCE:" + String(resistance, 3) + "_OHMS");
  
  return resistance;
}

float measureCapacitance() {
  // Capacitance measurement using RC time constant method
  
  // First, discharge any existing charge
  pinMode(CAPACITANCE_MEASURE, OUTPUT);
  digitalWrite(CAPACITANCE_MEASURE, LOW);
  digitalWrite(TEST_RELAY_TIP, HIGH);
  digitalWrite(TEST_RELAY_SLEEVE, HIGH);
  delay(100); // Ensure full discharge
  
  // Switch to input and start charging through known resistor
  pinMode(CAPACITANCE_MEASURE, INPUT);
  digitalWrite(CAPACITANCE_CHARGE, HIGH); // Start charging
  
  unsigned long start_time = micros();
  unsigned long charge_time = 0;
  
  // Measure time to reach 63.2% of supply voltage (1 time constant)
  float threshold_voltage = VOLTAGE_REF * 0.632;
  int threshold_adc = (int)(threshold_voltage * ADC_RESOLUTION / VOLTAGE_REF);
  
  while (analogRead(CAPACITANCE_MEASURE) < threshold_adc) {
    charge_time = micros() - start_time;
    if (charge_time > CAPACITANCE_TIMEOUT_US) {
      break; // Timeout - probably open circuit
    }
  }
  
  // Calculate capacitance using RC formula: C = t / (R * ln(Vcc/(Vcc-Vt)))
  // For 63.2% threshold: C = t / R (simplified)
  const float CHARGING_RESISTOR = 10000.0; // 10K ohm charging resistor
  float capacitance_f = (float)charge_time / (CHARGING_RESISTOR * 1000000.0);
  float capacitance_pf = capacitance_f * 1000000000000.0; // Convert to picofarads
  
  // Apply calibration offset
  capacitance_pf += capacitance_offset;
  
  // Clean up
  digitalWrite(CAPACITANCE_CHARGE, LOW);
  digitalWrite(TEST_RELAY_TIP, LOW);
  digitalWrite(TEST_RELAY_SLEEVE, LOW);
  
  Serial.println("DEBUG:CAPACITANCE:" + String(capacitance_pf, 1) + "_PF:TIME:" + String(charge_time) + "_US");
  
  return capacitance_pf;
}

// ===== UTILITY FUNCTIONS =====
float readAverageVoltage(int pin, int samples) {
  long total = 0;
  for (int i = 0; i < samples; i++) {
    total += analogRead(pin);
    delay(1);
  }
  float average_reading = total / (float)samples;
  return (average_reading * VOLTAGE_REF * voltage_calibration_factor) / ADC_RESOLUTION;
}

float measureSupplyVoltage() {
  // Measure actual supply voltage for calibration
  return readAverageVoltage(VOLTAGE_MONITOR, 10);
}

void resetTestCircuit() {
  // Turn off all relays and test signals
  digitalWrite(TEST_RELAY_TIP, LOW);
  digitalWrite(TEST_RELAY_RING, LOW);
  digitalWrite(TEST_RELAY_SLEEVE, LOW);
  digitalWrite(POLARITY_TEST_PIN, LOW);
  digitalWrite(RESISTANCE_CURRENT, LOW);
  digitalWrite(CAPACITANCE_CHARGE, LOW);
  digitalWrite(CALIBRATION_RELAY, LOW);
  
  // Reset indicator LEDs
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  digitalWrite(ERROR_LED, LOW);
}

void sendTestResults(TestResults results) {
  // Send structured response to Raspberry Pi
  String response = "TEST_RESULT:";
  response += "CONTINUITY:" + String(results.tip_continuity && results.ring_continuity && results.sleeve_continuity ? 1 : 0);
  response += ":RESISTANCE:" + String(results.resistance_ohms, 3);
  response += ":CAPACITANCE:" + String(results.capacitance_pf, 1);
  response += ":POLARITY:" + String(results.polarity_correct ? 1 : 0);
  response += ":OVERALL:" + String(results.overall_pass ? 1 : 0);
  
  Serial.println(response);
  
  // Send detailed breakdown if needed
  Serial.println("DETAIL:TIP:" + String(results.tip_continuity ? 1 : 0) +
                ":RING:" + String(results.ring_continuity ? 1 : 0) +
                ":SLEEVE:" + String(results.sleeve_continuity ? 1 : 0));
}

// ===== CALIBRATION FUNCTIONS =====
void runCalibrationSequence() {
  Serial.println("CALIBRATION:STARTING");
  
  // Visual indication
  blinkLED(STATUS_LED, 5, 200);
  
  // Step 1: Voltage reference calibration
  digitalWrite(CALIBRATION_RELAY, HIGH);
  delay(100);
  float measured_ref = readAverageVoltage(VOLTAGE_MONITOR, 100);
  voltage_calibration_factor = VOLTAGE_REF / measured_ref;
  digitalWrite(CALIBRATION_RELAY, LOW);
  
  // Step 2: Resistance offset calibration (short circuit)
  Serial.println("CALIBRATION:CONNECT_SHORT_CIRCUIT");
  delay(5000); // Wait for user to connect short
  
  float short_resistance = measureResistance();
  resistance_offset = 0.0 - short_resistance; // Offset to make short read 0.0
  
  // Step 3: Capacitance offset calibration (open circuit)
  Serial.println("CALIBRATION:REMOVE_ALL_CONNECTIONS");
  delay(5000); // Wait for user to disconnect everything
  
  float open_capacitance = measureCapacitance();
  capacitance_offset = 0.0 - open_capacitance; // Offset to make open read 0.0
  
  // Save calibration values (in EEPROM in production)
  Serial.println("CALIBRATION:COMPLETE:VOLTAGE_CAL:" + String(voltage_calibration_factor, 4) +
                ":RESISTANCE_OFFSET:" + String(resistance_offset, 3) +
                ":CAPACITANCE_OFFSET:" + String(capacitance_offset, 1));
  
  // Success indication
  blinkLED(PASS_LED, 3, 500);
}

void powerOnSelfTest() {
  Serial.println("SELF_TEST:STARTING");
  
  // Test all LEDs
  digitalWrite(STATUS_LED, HIGH);
  digitalWrite(ERROR_LED, HIGH);
  digitalWrite(PASS_LED, HIGH);
  digitalWrite(FAIL_LED, HIGH);
  delay(500);
  
  digitalWrite(ERROR_LED, LOW);
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  delay(500);
  
  // Test relay operation
  for (int i = 0; i < 3; i++) {
    digitalWrite(TEST_RELAY_TIP, HIGH);
    delay(100);
    digitalWrite(TEST_RELAY_TIP, LOW);
    digitalWrite(TEST_RELAY_RING, HIGH);
    delay(100);
    digitalWrite(TEST_RELAY_RING, LOW);
    digitalWrite(TEST_RELAY_SLEEVE, HIGH);
    delay(100);
    digitalWrite(TEST_RELAY_SLEEVE, LOW);
  }
  
  // Test ADC readings
  float voltage_test = measureSupplyVoltage();
  bool adc_ok = (voltage_test > 4.0 && voltage_test < 6.0);
  
  if (adc_ok) {
    Serial.println("SELF_TEST:PASS:VOLTAGE:" + String(voltage_test, 2));
    blinkLED(PASS_LED, 2, 200);
  } else {
    Serial.println("SELF_TEST:FAIL:VOLTAGE:" + String(voltage_test, 2));
    blinkLED(ERROR_LED, 5, 100);
    system_ready = false;
  }
}

// ===== LED CONTROL =====
void blinkLED(int pin, int count, int delay_ms) {
  for (int i = 0; i < count; i++) {
    digitalWrite(pin, HIGH);
    delay(delay_ms);
    digitalWrite(pin, LOW);
    delay(delay_ms);
  }
}

void statusHeartbeat() {
  // Heartbeat blink every 2 seconds when system is ready
  unsigned long current_time = millis();
  if (current_time - last_status_blink > 2000) {
    if (system_ready) {
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    }
    last_status_blink = current_time;
  }
}
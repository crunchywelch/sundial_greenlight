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
 * Arudino board: Arduino Pro Mini
 * Pin Configuration:
 * - A0: Analog measurement inputs
 * - D2-D13: Digital I/O for relays and test signals
 * - Serial: USB communication (pins 0,1)
 */

#include <Arduino.h>

// ===== PIN DEFINITIONS =====
// Analog pins
#define RESISTANCE_SENSE_A0    A0    // Resistance measurement input

// Digital pins
#define CABLE_RELAYS               2     // Relay control for cable relays, NC=cap/res tests, Open=continuity tests
#define CONTINUITY_RELAY           3     // Relay control for continuity test, NC=Sleeve, Open=Tip
#define RES_CAP_TEST_RELAY         4     // Relay control for resistance and capacitance tests, NC=capacitance, Open=resistance
#define CONTINUITY_OUTPUT          5     // Continuity test output
#define CAPACITANCE_AIN0           7     // Capacitance comparitor input
#define CONTINUITY_INPUT_TIP       8     // Continuity tip test input
#define CONTINUITY_INPUT_SLEEVE    9     // Continuity sleeve test input

// Status and indicator pinssleeve
#define STATUS_LED            13     // Built-in LED for status
#define ERROR_LED             12     // External error indicator
#define PASS_LED              11     // Test pass indicator
#define FAIL_LED              10     // Test fail indicator

// Test fixture pins
//#define FIXTURE_DETECT         8     // Cable insertion detection

// Resistance measurement pins
#define CURRENT_SOURCE_PWM     6     // PWM output for constant current source

// ===== CONFIGURATION =====
const int UNIT_ID = 1;                    // Arduino unit identifier
const int BAUD_RATE = 9600;               // Serial communication speed
const float VOLTAGE_REF = 5.0;            // ADC reference voltage
const int ADC_RESOLUTION = 1024;          // 10-bit ADC resolution
const int MEASUREMENT_SAMPLES = 50;       // Samples for averaging

// Debug mode
const bool DEBUG_MODE = true;             // Enable verbose setup and operation

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

// Capacitance measurement variables
volatile boolean capacitance_triggered;
volatile boolean capacitance_active;
volatile unsigned long capacitance_start_time;
volatile unsigned long capacitance_duration;
const unsigned long CHARGING_RESISTOR = 10000;  // 10k ohm

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
  
  if (DEBUG_MODE) {
    Serial.println("===============================================");
    Serial.println("    Greenlight Cable Tester Starting Up");
    Serial.println("===============================================");
    Serial.println("Board: Arduino Pro Mini");
    Serial.println("Unit ID: " + String(UNIT_ID));
    Serial.println("Baud Rate: " + String(BAUD_RATE));
    Serial.println("Debug Mode: ENABLED");
    Serial.println("");
  }
  
  if (DEBUG_MODE) Serial.println("Configuring digital pins...");
  // Initialize digital pins
  pinMode(CABLE_RELAYS, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(CABLE_RELAYS) + " (CABLE_RELAYS) -> OUTPUT");
  
  pinMode(CONTINUITY_RELAY, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(CONTINUITY_RELAY) + " (CONTINUITY_RELAY) -> OUTPUT");
  
  pinMode(RES_CAP_TEST_RELAY, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(RES_CAP_TEST_RELAY) + " (RES_CAP_TEST_RELAY) -> OUTPUT");
  
  pinMode(CONTINUITY_OUTPUT, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(CONTINUITY_OUTPUT) + " (CONTINUITY_OUTPUT) -> OUTPUT");
  
  pinMode(CONTINUITY_INPUT_TIP, INPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(CONTINUITY_INPUT_TIP) + " (CONTINUITY_INPUT_TIP) -> INPUT");
  
  pinMode(CONTINUITY_INPUT_SLEEVE, INPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(CONTINUITY_INPUT_SLEEVE) + " (CONTINUITY_INPUT_SLEEVE) -> INPUT");
  
  if (DEBUG_MODE) Serial.println("Configuring LED pins...");
  pinMode(STATUS_LED, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(STATUS_LED) + " (STATUS_LED) -> OUTPUT");
  
  pinMode(ERROR_LED, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(ERROR_LED) + " (ERROR_LED) -> OUTPUT");
  
  pinMode(PASS_LED, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(PASS_LED) + " (PASS_LED) -> OUTPUT");
  
  pinMode(FAIL_LED, OUTPUT);
  if (DEBUG_MODE) Serial.println("  Pin " + String(FAIL_LED) + " (FAIL_LED) -> OUTPUT");
  
  // pinMode(FIXTURE_DETECT, INPUT_PULLUP);  // Not used yet
  
  if (DEBUG_MODE) Serial.println("Setting initial pin states...");
  // Set initial states - all relays off, LEDs off
  digitalWrite(CABLE_RELAYS, LOW);
  if (DEBUG_MODE) Serial.println("  CABLE_RELAYS -> LOW (NC = cap/res tests)");
  
  digitalWrite(CONTINUITY_RELAY, LOW);
  if (DEBUG_MODE) Serial.println("  CONTINUITY_RELAY -> LOW (NC = Sleeve)");
  
  digitalWrite(RES_CAP_TEST_RELAY, LOW);
  if (DEBUG_MODE) Serial.println("  RES_CAP_TEST_RELAY -> LOW (NC = capacitance)");
  
  digitalWrite(CONTINUITY_OUTPUT, LOW);
  if (DEBUG_MODE) Serial.println("  CONTINUITY_OUTPUT -> LOW");
  
  // Configure analog comparator for capacitance measurement
  if (DEBUG_MODE) Serial.println("Setting up analog comparator...");
  setupAnalogComparator();
  if (DEBUG_MODE) Serial.println("  Analog comparator configured for capacitance measurement");
  
  digitalWrite(ERROR_LED, LOW);
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  if (DEBUG_MODE) Serial.println("  All LEDs -> OFF");
  
  // Power-on self test
  if (DEBUG_MODE) Serial.println("Running power-on self test...");
  powerOnSelfTest();
  
  // Set system ready
  system_ready = true;
  digitalWrite(STATUS_LED, HIGH);
  if (DEBUG_MODE) {
    Serial.println("System ready!");
    Serial.println("STATUS_LED -> ON (system ready indicator)");
    Serial.println("");
    Serial.println("=== CONTINUOUS TESTING MODE ACTIVE ===");
    Serial.println("Testing continuity and polarity every 2 seconds");
    Serial.println("LED Indicators:");
    Serial.println("  GREEN (Pass): All tests pass");
    Serial.println("  RED (Fail): Continuity failure");
    Serial.println("  YELLOW (Error): Good continuity but wrong polarity");
    Serial.println("");
  }
  
  // Send startup message
  Serial.println("ARDUINO_READY:UNIT_" + String(UNIT_ID));
  delay(100);
}

// ===== MAIN LOOP =====
void loop() {
  // Turn off all LEDs before starting test
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  digitalWrite(ERROR_LED, LOW);
  
  // Continuous testing for breadboard validation
  TestResults results;
  testContinuityAndPolarity(results);
  
  // Add resistance measurement
  results.resistance_ohms = measureResistance();
  
  if (DEBUG_MODE) {
    Serial.println("=== OVERALL TEST RESULTS ===");
    Serial.println("TIP: " + String(results.tip_continuity ? "PASS" : "FAIL"));
    Serial.println("SLEEVE: " + String(results.sleeve_continuity ? "PASS" : "FAIL"));  
    Serial.println("POLARITY: " + String(results.polarity_correct ? "CORRECT" : "INCORRECT"));
    Serial.println("RESISTANCE: " + String(results.resistance_ohms, 3) + " ohms");
  }
  
  // LED indication  
  bool resistance_ok = (results.resistance_ohms > 0.1) && (results.resistance_ohms < 100.0);  // Reasonable range
  bool overall_pass = results.tip_continuity && results.sleeve_continuity && results.polarity_correct && resistance_ok;
  
  if (overall_pass) {
    digitalWrite(PASS_LED, HIGH);
    digitalWrite(FAIL_LED, LOW);
    digitalWrite(ERROR_LED, LOW);
  } else if (results.tip_continuity && results.sleeve_continuity && !results.polarity_correct) {
    // Continuity good but polarity wrong
    digitalWrite(PASS_LED, LOW);
    digitalWrite(FAIL_LED, LOW);
    digitalWrite(ERROR_LED, HIGH);
  } else {
    // Continuity failure
    digitalWrite(PASS_LED, LOW);
    digitalWrite(FAIL_LED, HIGH);
    digitalWrite(ERROR_LED, LOW);
  }
  
  delay(2000);  // Wait 2 seconds before next test
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
    //runCalibrationSequence();
    
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
  status += ":FIXTURE_UNKNOWN";  // Cable detection not implemented yet
  status += ":VOLTAGE_" + String(measureSupplyVoltage(), 2);
  Serial.println(status);
}

// ===== CABLE TESTING FUNCTIONS =====
void runFullCableTest() {
  if (!system_ready) {
    Serial.println("ERROR:SYSTEM_NOT_READY");
    return;
  }
  
  // Note: Cable insertion detection removed for now
  // Future: Add cable detection logic if needed
  
  // Initialize test results
  TestResults results;
  results.overall_pass = true;
  results.error_message = "";
  
  // Turn on testing indicator
  digitalWrite(STATUS_LED, LOW);
  blinkLED(PASS_LED, 2, 100); // Brief "testing" indication
  
  // Step 1: Continuity and Polarity Tests
  testContinuityAndPolarity(results);
  
  // Step 2: Resistance Measurement
  results.resistance_ohms = measureResistance();
  delay(100);
  
  // Step 3: Capacitance Measurement
  results.capacitance_pf = measureCapacitance();
  delay(100);
  
  // Determine overall pass/fail
  results.overall_pass = results.tip_continuity && 
                        results.sleeve_continuity && 
                        results.polarity_correct &&
                        (results.resistance_ohms > 0.0) &&
                        (results.capacitance_pf > 0.0);
                        
  // Note: Ring continuity removed for TS cable testing
  
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

void testContinuityAndPolarity(TestResults &results) {
  // Setup for continuity testing
  digitalWrite(CABLE_RELAYS, HIGH);  // Open = continuity tests
  digitalWrite(CONTINUITY_OUTPUT, LOW);
  delay(10);
  
  if (DEBUG_MODE) {
    Serial.println("\n=== CONTINUITY AND POLARITY TEST ===");
  }

  // Test 1: TIP continuity test
  if (DEBUG_MODE) Serial.println("Testing TIP continuity...");
  digitalWrite(CONTINUITY_RELAY, HIGH);  // Open = Tip
  delay(10);
  digitalWrite(CONTINUITY_OUTPUT, HIGH);
  delay(50);

  bool tip_reads_high = digitalRead(CONTINUITY_INPUT_TIP) == HIGH;
  bool sleeve_reads_low_during_tip = digitalRead(CONTINUITY_INPUT_SLEEVE) == LOW;
  
  results.tip_continuity = tip_reads_high;
  
  if (DEBUG_MODE) {
    Serial.print("  TIP: ");
    Serial.print(tip_reads_high ? "CONNECTED" : "BROKEN");
    Serial.print(" | SLEEVE: ");
    Serial.println(sleeve_reads_low_during_tip ? "ISOLATED" : "LEAKAGE");
  }

  digitalWrite(CONTINUITY_OUTPUT, LOW);
  delay(50);

  // Test 2: SLEEVE continuity test  
  if (DEBUG_MODE) Serial.println("Testing SLEEVE continuity...");
  digitalWrite(CONTINUITY_RELAY, LOW);   // NC = Sleeve
  delay(10);
  digitalWrite(CONTINUITY_OUTPUT, HIGH);
  delay(50);

  bool sleeve_reads_high = digitalRead(CONTINUITY_INPUT_SLEEVE) == HIGH;
  bool tip_reads_low_during_sleeve = digitalRead(CONTINUITY_INPUT_TIP) == LOW;
  
  results.sleeve_continuity = sleeve_reads_high;
  
  if (DEBUG_MODE) {
    Serial.print("  SLEEVE: ");
    Serial.print(sleeve_reads_high ? "CONNECTED" : "BROKEN");
    Serial.print(" | TIP: ");
    Serial.println(tip_reads_low_during_sleeve ? "ISOLATED" : "LEAKAGE");
  }

  // Polarity check: Both tests should be isolated
  results.polarity_correct = (tip_reads_high && sleeve_reads_low_during_tip) && 
                            (sleeve_reads_high && tip_reads_low_during_sleeve);
  
  // Clean up
  digitalWrite(CONTINUITY_OUTPUT, LOW);
  digitalWrite(CABLE_RELAYS, LOW);
  
  // Debug output
  if (DEBUG_MODE) {
    Serial.println("\n--- Test Results ---");
    Serial.println("TIP Continuity: " + String(results.tip_continuity ? "PASS" : "FAIL"));
    Serial.println("SLEEVE Continuity: " + String(results.sleeve_continuity ? "PASS" : "FAIL"));
    Serial.println("Polarity: " + String(results.polarity_correct ? "CORRECT" : "INCORRECT"));
    Serial.println("========================\n");
  }
}

void setupAnalogComparator() {
  // Configure analog comparator for capacitance measurement
  ADCSRB = 0;  // No ACME (multiplexer off)
  ACSR = _BV(ACI) | _BV(ACIE) | _BV(ACIS0) | _BV(ACIS1);  
  // Clear interrupt flag, enable comparator interrupt, trigger on rising edge
}

// Analog comparator interrupt service routine
ISR (ANALOG_COMP_vect) {
  unsigned long now = micros();
  if (capacitance_active) {
    capacitance_duration = now - capacitance_start_time;
    capacitance_triggered = true;
  }
}

float measureResistance() {
  // Setup for resistance measurement
  digitalWrite(CABLE_RELAYS, LOW);   // NC = cap/res tests
  digitalWrite(RES_CAP_TEST_RELAY, HIGH);  // Open = resistance
  
  // Set constant current via PWM (pin 6)
  // PWM value 128 = ~2.5V reference = ~250mA current (with 10Ω sense resistor)
  const int PWM_CURRENT_LEVEL = 128;  // Adjust this value to set current
  const float SENSE_RESISTOR = 10.0;  // 10Ω current sense resistor
  const float EXPECTED_CURRENT_MA = (PWM_CURRENT_LEVEL / 255.0) * (VOLTAGE_REF * 1000.0) / SENSE_RESISTOR;
  
  analogWrite(CURRENT_SOURCE_PWM, PWM_CURRENT_LEVEL);
  delay(100); // Allow current source to stabilize
  
  // Measure voltage drop across cable at A0
  // Current flows: Current Source → Cable → A0 → GND
  float voltage_drop = readAverageVoltage(RESISTANCE_SENSE_A0, MEASUREMENT_SAMPLES);
  
  // Calculate cable resistance using Ohm's law: R = V / I
  float cable_resistance;
  if (EXPECTED_CURRENT_MA > 0.1) {  // Avoid division by zero
    cable_resistance = (voltage_drop * 1000.0) / EXPECTED_CURRENT_MA;  // Convert mA to A
  } else {
    cable_resistance = OPEN_CIRCUIT_THRESHOLD;  // No current flow
  }
  
  // Apply calibration offset
  cable_resistance += resistance_offset;
  
  // Clean up
  analogWrite(CURRENT_SOURCE_PWM, 0);  // Turn off current source
  digitalWrite(RES_CAP_TEST_RELAY, LOW);
  digitalWrite(CABLE_RELAYS, LOW);
  
  if (DEBUG_MODE) {
    Serial.println("DEBUG:RESISTANCE:I=" + String(EXPECTED_CURRENT_MA, 1) + "mA:V=" + String(voltage_drop, 3) + "V:R=" + String(cable_resistance, 3) + "_OHMS");
  }
  
  return cable_resistance;
}

float measureCapacitance() {
  // Setup for capacitance measurement using analog comparator
  digitalWrite(CABLE_RELAYS, LOW);   // NC = cap/res tests
  digitalWrite(RES_CAP_TEST_RELAY, LOW);  // NC = capacitance
  delay(10);
  
  // Discharge capacitor first by pulling AIN0 low briefly
  pinMode(6, OUTPUT);  // AIN0 pin 6
  digitalWrite(6, LOW);
  delay(100);  // Ensure full discharge
  pinMode(6, INPUT);   // Return to comparator input
  
  // Reset capacitance measurement variables
  capacitance_triggered = false;
  capacitance_active = false;
  
  // Start charging - this will begin the RC charge cycle
  capacitance_active = true;
  capacitance_start_time = micros();
  
  // The charging happens through the voltage divider circuit
  // Analog comparator will trigger interrupt when threshold is reached
  
  // Wait for comparator interrupt or timeout
  unsigned long timeout_start = millis();
  while (!capacitance_triggered && (millis() - timeout_start < 100)) {
    // Wait for interrupt
    delayMicroseconds(10);
  }
  
  capacitance_active = false;
  
  float capacitance_pf = 0.0;
  
  if (capacitance_triggered) {
    // Calculate capacitance: C = t / R (for comparator threshold)
    float capacitance_f = (float)capacitance_duration / (CHARGING_RESISTOR * 1000000.0);
    capacitance_pf = capacitance_f * 1000000000000.0; // Convert to picofarads
    
    // Apply calibration offset
    capacitance_pf += capacitance_offset;
  } else {
    // Timeout - probably open circuit or very low capacitance
    capacitance_pf = 0.0;
  }
  
  // Clean up
  digitalWrite(RES_CAP_TEST_RELAY, LOW);
  digitalWrite(CABLE_RELAYS, LOW);
  
  Serial.println("DEBUG:CAPACITANCE:" + String(capacitance_pf, 1) + "_PF:TIME:" + String(capacitance_duration) + "_US");
  
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
  // Measure actual supply voltage using internal reference
  // For now, return nominal voltage - could be improved with voltage divider
  return VOLTAGE_REF;
}

void resetTestCircuit() {
  // Turn off all relays and test signals
  digitalWrite(CABLE_RELAYS, LOW);
  digitalWrite(CONTINUITY_RELAY, LOW);
  digitalWrite(RES_CAP_TEST_RELAY, LOW);
  digitalWrite(CONTINUITY_OUTPUT, LOW);
  
  // Reset indicator LEDs
  digitalWrite(PASS_LED, LOW);
  digitalWrite(FAIL_LED, LOW);
  digitalWrite(ERROR_LED, LOW);
  
  // Reset capacitance measurement variables
  capacitance_triggered = false;
  capacitance_active = false;
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
                ":SLEEVE:" + String(results.sleeve_continuity ? 1 : 0));
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
  
  // Test ADC readings
  float voltage_test = measureSupplyVoltage();
  bool adc_ok = (voltage_test > 4.0 && voltage_test < 6.0);
  
  if (adc_ok) {
    Serial.println("SELF_TEST:PASS:VOLTAGE:" + String(voltage_test, 2));
    // Blink all indicator LEDs to show they work
    blinkLED(PASS_LED, 3, 200);    // Green - 3 blinks
    delay(200);
    blinkLED(ERROR_LED, 3, 200);   // Yellow - 3 blinks  
    delay(200);
    blinkLED(FAIL_LED, 3, 200);    // Red - 3 blinks
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

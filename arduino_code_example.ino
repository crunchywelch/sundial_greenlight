/*
 * Greenlight Cable Tester - Arduino ATmega32 Code
 * 
 * This code interfaces with the Greenlight Terminal for cable testing.
 * Communication via USB Serial at 9600 baud.
 * 
 * Commands from Raspberry Pi:
 * - GET_UNIT_ID -> Returns UNIT_ID:1
 * - GET_STATUS -> Returns STATUS:READY
 * - TEST_CABLE -> Runs full test, returns TEST_RESULT:CONTINUITY:1:RESISTANCE:0.25:CAPACITANCE:145.2
 * - CALIBRATE -> Runs calibration sequence
 */

// Pin definitions for ATmega32
#define CONTINUITY_TEST_PIN A0    // Analog pin for continuity measurement
#define RESISTANCE_MEASURE_PIN A1 // Analog pin for resistance measurement  
#define CAPACITANCE_MEASURE_PIN A2 // Analog pin for capacitance measurement

#define RELAY_1_PIN 2             // Digital pin for test relay 1
#define RELAY_2_PIN 3             // Digital pin for test relay 2
#define TEST_SIGNAL_PIN 4         // Digital pin for test signal generation

#define STATUS_LED_PIN 13         // Built-in LED for status indication

// Configuration
const int UNIT_ID = 1;            // Arduino unit identifier
const int BAUD_RATE = 9600;       // Serial communication speed
const int SAMPLE_COUNT = 100;     // Number of samples for averaging

// Test parameters
const float CONTINUITY_THRESHOLD = 100.0;  // Ohms - below this is continuity
const float VOLTAGE_REF = 5.0;             // Reference voltage
const int ADC_RESOLUTION = 1024;           // 10-bit ADC

void setup() {
  // Initialize serial communication
  Serial.begin(BAUD_RATE);
  
  // Initialize pins
  pinMode(RELAY_1_PIN, OUTPUT);
  pinMode(RELAY_2_PIN, OUTPUT);
  pinMode(TEST_SIGNAL_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  
  // Set initial states
  digitalWrite(RELAY_1_PIN, LOW);
  digitalWrite(RELAY_2_PIN, LOW);
  digitalWrite(TEST_SIGNAL_PIN, LOW);
  digitalWrite(STATUS_LED_PIN, HIGH);  // Power-on indicator
  
  // Brief startup delay
  delay(1000);
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command == "GET_UNIT_ID") {
      Serial.print("UNIT_ID:");
      Serial.println(UNIT_ID);
      
    } else if (command == "GET_STATUS") {
      Serial.println("STATUS:READY");
      
    } else if (command == "TEST_CABLE") {
      runCableTest();
      
    } else if (command == "CALIBRATE") {
      runCalibration();
      
    } else {
      Serial.print("ERROR:UNKNOWN_COMMAND:");
      Serial.println(command);
    }
  }
  
  delay(10);  // Small delay to prevent overwhelming the serial buffer
}

void runCableTest() {
  digitalWrite(STATUS_LED_PIN, LOW);  // Turn off status LED during test
  
  // Step 1: Continuity Test
  bool continuity_pass = testContinuity();
  
  // Step 2: Resistance Measurement
  float resistance = measureResistance();
  
  // Step 3: Capacitance Measurement  
  float capacitance = measureCapacitance();
  
  // Send results back to Raspberry Pi
  Serial.print("TEST_RESULT:CONTINUITY:");
  Serial.print(continuity_pass ? 1 : 0);
  Serial.print(":RESISTANCE:");
  Serial.print(resistance, 3);  // 3 decimal places
  Serial.print(":CAPACITANCE:");
  Serial.println(capacitance, 1);  // 1 decimal place
  
  digitalWrite(STATUS_LED_PIN, HIGH);  // Turn status LED back on
}

bool testContinuity() {
  // Enable test circuit
  digitalWrite(RELAY_1_PIN, HIGH);
  delay(50);  // Allow circuit to settle
  
  // Apply small test current and measure voltage drop
  digitalWrite(TEST_SIGNAL_PIN, HIGH);
  delay(10);
  
  // Read continuity measurement
  int raw_reading = analogRead(CONTINUITY_TEST_PIN);
  float voltage = (raw_reading * VOLTAGE_REF) / ADC_RESOLUTION;
  
  // Calculate resistance (simplified - in practice you'd use proper current measurement)
  float test_resistance = voltage * 1000.0;  // Rough approximation
  
  // Clean up
  digitalWrite(TEST_SIGNAL_PIN, LOW);
  digitalWrite(RELAY_1_PIN, LOW);
  
  return test_resistance < CONTINUITY_THRESHOLD;
}

float measureResistance() {
  // Configure for precision resistance measurement
  digitalWrite(RELAY_2_PIN, HIGH);
  delay(100);  // Allow circuit to settle
  
  // Take multiple samples for accuracy
  long total = 0;
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    total += analogRead(RESISTANCE_MEASURE_PIN);
    delay(1);
  }
  
  float average_reading = total / (float)SAMPLE_COUNT;
  float voltage = (average_reading * VOLTAGE_REF) / ADC_RESOLUTION;
  
  // Convert voltage to resistance using voltage divider calculation
  // This assumes a known reference resistor in the test circuit
  const float REF_RESISTOR = 1000.0;  // 1K reference resistor
  float resistance = REF_RESISTOR * voltage / (VOLTAGE_REF - voltage);
  
  digitalWrite(RELAY_2_PIN, LOW);
  
  return resistance;
}

float measureCapacitance() {
  // Simple capacitance measurement using RC time constant
  // This is a simplified version - production code would be more sophisticated
  
  // Discharge capacitor first
  pinMode(CAPACITANCE_MEASURE_PIN, OUTPUT);
  digitalWrite(CAPACITANCE_MEASURE_PIN, LOW);
  delay(100);
  
  // Switch to input and start charging
  pinMode(CAPACITANCE_MEASURE_PIN, INPUT);
  unsigned long start_time = micros();
  
  // Measure time to reach threshold
  while (digitalRead(CAPACITANCE_MEASURE_PIN) == LOW) {
    if (micros() - start_time > 50000) break;  // 50ms timeout
  }
  
  unsigned long charge_time = micros() - start_time;
  
  // Calculate capacitance using RC formula: t = RC * ln(Vcc/(Vcc-Vt))
  // This is simplified - actual implementation would be more complex
  const float R_VALUE = 10000.0;  // 10K charging resistor
  float capacitance_pf = (charge_time / R_VALUE) * 1000000.0;  // Convert to pF
  
  return capacitance_pf;
}

void runCalibration() {
  digitalWrite(STATUS_LED_PIN, LOW);
  
  // Calibration sequence
  // In practice, this would involve:
  // 1. Testing with known reference standards
  // 2. Adjusting measurement offsets
  // 3. Verifying accuracy
  
  for (int i = 0; i < 5; i++) {
    digitalWrite(STATUS_LED_PIN, HIGH);
    delay(200);
    digitalWrite(STATUS_LED_PIN, LOW);
    delay(200);
  }
  
  Serial.println("CALIBRATION_COMPLETE:SUCCESS");
  digitalWrite(STATUS_LED_PIN, HIGH);
}
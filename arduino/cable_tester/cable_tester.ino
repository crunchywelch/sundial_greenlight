/*
 * Greenlight TS Cable Tester - Arduino Mega 2560
 *
 * Continuity, polarity, and resistance testing for TS (Tip-Sleeve) cables.
 * Communicates with Raspberry Pi via USB serial.
 *
 * Commands:
 *   CONT     - Run continuity/polarity test, returns RESULT:...
 *   RES      - Run resistance test, returns RES:...
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *
 * Relay Configuration:
 *   K1+K2 (D2) - Tied together. LOW = short far end + res/cap path, HIGH = continuity mode
 *   K3 (D3)    - Tip/Sleeve selector: LOW = sleeve, HIGH = tip
 *   K4 (D4)    - LOW = capacitance mode, HIGH = resistance mode
 *
 * Pin Configuration:
 *   D2  - K1+K2 relay control (tied together)
 *   D3  - K3 relay control (tip/sleeve selector)
 *   D4  - K4 relay control (res/cap mode)
 *   D5  - CONT_TEST_OUT (continuity signal, input to K3)
 *   D6  - RES_TEST_OUT (PN2222A base drive)
 *   D8  - TIP_SENSE (input - continuity test)
 *   D9  - SLEEVE_SENSE (input - continuity test)
 *   A0  - RES_SENSE (analog input - resistance measurement)
 *   D10 - FAIL_LED (red)
 *   D11 - PASS_LED (green)
 *   D12 - ERROR_LED (yellow)
 *   D13 - STATUS_LED (built-in)
 */

// ===== PIN DEFINITIONS =====
// Relays
#define K1_K2_RELAY         2    // K1+K2 tied together: LOW = short/res path, HIGH = continuity
#define K3_RELAY            3    // Tip/sleeve selector: LOW = sleeve, HIGH = tip
#define K4_RELAY            4    // LOW = capacitance, HIGH = resistance

// Test signals
#define CONT_TEST_OUT       5    // Continuity test signal (input to K3)
#define RES_TEST_OUT     6    // PN2222A base drive for resistance test
#define TIP_SENSE           8    // Input: tip on far end (continuity)
#define SLEEVE_SENSE        9    // Input: sleeve on far end (continuity)
#define RES_SENSE           A0   // Analog input: resistance measurement

// LEDs
#define FAIL_LED           10
#define PASS_LED           11
#define ERROR_LED          12
#define STATUS_LED         13

// ===== CONFIGURATION =====
const char* TESTER_ID = "TS_TESTER_1";
const int BAUD_RATE = 9600;
const int RELAY_SETTLE_MS = 10;
const int SIGNAL_SETTLE_MS = 50;

// Resistance test thresholds
const int RES_PASS_THRESHOLD = 700;  // ADC value above this = PASS (low resistance)
const float RES_REFERENCE_OHM = 47.0; // Reference resistor value
const float SUPPLY_VOLTAGE = 5.0;    // Supply voltage
const float VCE_SAT = 0.3;           // Transistor saturation voltage estimate

// Calibration (stored in RAM, lost on reset - could use EEPROM)
int calibrationADC = 0;              // ADC reading with zero-ohm reference
bool isCalibrated = false;

// Forward declaration for default argument
void setResultLED(int pin = -1);

// ===== GLOBAL STATE =====
bool systemReady = false;
String inputBuffer = "";

// ===== TEST RESULTS =====
struct TestResults {
  // Raw readings
  bool tipToTip;       // Signal sent to TIP, read on TIP_SENSE
  bool tipToSleeve;    // Signal sent to TIP, read on SLEEVE_SENSE
  bool sleeveToSleeve; // Signal sent to SLEEVE, read on SLEEVE_SENSE
  bool sleeveToTip;    // Signal sent to SLEEVE, read on TIP_SENSE
  // Interpreted results
  bool overallPass;
  bool reversed;
  bool crossed;
  bool openTip;
  bool openSleeve;
};

// ===== SETUP =====
void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) { ; }  // Wait for USB serial

  // Configure relay outputs
  pinMode(K1_K2_RELAY, OUTPUT);
  pinMode(K3_RELAY, OUTPUT);
  pinMode(K4_RELAY, OUTPUT);
  pinMode(RES_TEST_OUT, OUTPUT);
  pinMode(CONT_TEST_OUT, OUTPUT);

  // Configure sense inputs
  pinMode(TIP_SENSE, INPUT);
  pinMode(SLEEVE_SENSE, INPUT);
  // A0 is analog input by default

  // Configure LEDs
  pinMode(FAIL_LED, OUTPUT);
  pinMode(PASS_LED, OUTPUT);
  pinMode(ERROR_LED, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  // Initialize all relays OFF, test circuit OFF
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(CONT_TEST_OUT, LOW);

  // All LEDs off
  setResultLED();
  digitalWrite(STATUS_LED, LOW);

  // Run self-test
  if (selfTest()) {
    systemReady = true;
    digitalWrite(STATUS_LED, HIGH);
    Serial.println("READY:" + String(TESTER_ID));
  } else {
    systemReady = false;
    setResultLED(ERROR_LED);
    Serial.println("ERROR:SELF_TEST_FAILED");
  }
}

// ===== MAIN LOOP =====
void loop() {
  // Blink status LED when idle
  static unsigned long lastBlink = 0;
  if (systemReady && millis() - lastBlink > 1000) {
    digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    lastBlink = millis();
  }

  // Handle serial commands
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        handleCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
    }
  }
}

// ===== COMMAND HANDLER =====
void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  if (cmd == "CONT") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runContinuityTest();

  } else if (cmd == "RES") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runResistanceTest();

  } else if (cmd == "CAL") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runCalibration();

  } else if (cmd == "STATUS") {
    sendStatus();

  } else if (cmd == "ID") {
    Serial.println("ID:" + String(TESTER_ID));

  } else if (cmd == "RESET") {
    resetCircuit();
    Serial.println("OK:RESET");

  // ===== DEBUG COMMANDS FOR HARDWARE TESTING =====
  } else if (cmd == "LED") {
    // Cycle through all LEDs (result LEDs are active-low)
    Serial.println("DEBUG:LED_TEST_START");
    setResultLED();
    digitalWrite(STATUS_LED, LOW);
    Serial.println("PASS_LED ON (D11) - GREEN");
    setResultLED(PASS_LED);
    delay(500);
    setResultLED();
    Serial.println("FAIL_LED ON (D10) - RED");
    setResultLED(FAIL_LED);
    delay(500);
    setResultLED();
    Serial.println("ERROR_LED ON (D12) - YELLOW");
    setResultLED(ERROR_LED);
    delay(500);
    setResultLED();
    Serial.println("STATUS_LED ON (D13)");
    digitalWrite(STATUS_LED, HIGH);
    delay(500);
    digitalWrite(STATUS_LED, LOW);
    Serial.println("DEBUG:LED_TEST_DONE");

  } else if (cmd == "K12") {
    bool state = !digitalRead(K1_K2_RELAY);
    digitalWrite(K1_K2_RELAY, state);
    Serial.println("DEBUG:K1+K2(D2):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K3") {
    bool state = !digitalRead(K3_RELAY);
    digitalWrite(K3_RELAY, state);
    Serial.println("DEBUG:K3(D3):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K4") {
    bool state = !digitalRead(K4_RELAY);
    digitalWrite(K4_RELAY, state);
    Serial.println("DEBUG:K4(D4):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "SIG") {
    bool state = !digitalRead(CONT_TEST_OUT);
    digitalWrite(CONT_TEST_OUT, state);
    Serial.println("DEBUG:CONT_TEST_OUT(D5):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "RESON") {
    digitalWrite(RES_TEST_OUT, HIGH);
    Serial.println("DEBUG:RES_TEST_OUT(D6):HIGH");

  } else if (cmd == "RESOFF") {
    digitalWrite(RES_TEST_OUT, LOW);
    Serial.println("DEBUG:RES_TEST_OUT(D6):LOW");

  } else if (cmd == "READ") {
    int tip = digitalRead(TIP_SENSE);
    int sleeve = digitalRead(SLEEVE_SENSE);
    int resAdc = analogRead(RES_SENSE);
    Serial.println("DEBUG:TIP(D8):" + String(tip) + ":SLEEVE(D9):" + String(sleeve) + ":RES(A0):" + String(resAdc));

  } else if (cmd == "PINS") {
    Serial.println("=== PIN STATUS ===");
    Serial.println("RELAYS:");
    Serial.println("  D2  K1+K2: " + String(digitalRead(K1_K2_RELAY) ? "HIGH" : "LOW") + " (HIGH=cont, LOW=res)");
    Serial.println("  D3  K3:    " + String(digitalRead(K3_RELAY) ? "HIGH" : "LOW") + " (HIGH=tip, LOW=sleeve)");
    Serial.println("  D4  K4:    " + String(digitalRead(K4_RELAY) ? "HIGH" : "LOW") + " (HIGH=res, LOW=cap)");
    Serial.println("TEST SIGNALS:");
    Serial.println("  D5  CONT:    " + String(digitalRead(CONT_TEST_OUT) ? "HIGH" : "LOW"));
    Serial.println("  D6  RES_EN:  " + String(digitalRead(RES_TEST_OUT) ? "HIGH" : "LOW"));
    Serial.println("SENSE INPUTS:");
    Serial.println("  D8  TIP:     " + String(digitalRead(TIP_SENSE) ? "HIGH" : "LOW"));
    Serial.println("  D9  SLEEVE:  " + String(digitalRead(SLEEVE_SENSE) ? "HIGH" : "LOW"));
    Serial.println("  A0  RES:     " + String(analogRead(RES_SENSE)));
    Serial.println("LEDS:");
    Serial.println("  D10 FAIL:    " + String(digitalRead(FAIL_LED) ? "OFF" : "ON"));
    Serial.println("  D11 PASS:    " + String(digitalRead(PASS_LED) ? "OFF" : "ON"));
    Serial.println("  D12 ERROR:   " + String(digitalRead(ERROR_LED) ? "OFF" : "ON"));
    Serial.println("  D13 STATUS:  " + String(digitalRead(STATUS_LED) ? "ON" : "OFF"));

  } else if (cmd == "HELP") {
    Serial.println("=== COMMANDS ===");
    Serial.println("CONT    - Run continuity test");
    Serial.println("RES     - Run resistance test");
    Serial.println("CAL     - Calibrate with 0-ohm reference");
    Serial.println("STATUS  - Get tester status");
    Serial.println("ID      - Get tester ID");
    Serial.println("RESET   - Reset circuit");
    Serial.println("--- DEBUG ---");
    Serial.println("LED     - Cycle all LEDs");
    Serial.println("K12     - Toggle K1+K2 relay (D2)");
    Serial.println("K3      - Toggle K3 relay (D3)");
    Serial.println("K4      - Toggle K4 relay (D4)");
    Serial.println("SIG     - Toggle continuity signal (D5)");
    Serial.println("RESON   - Enable resistance test current");
    Serial.println("RESOFF  - Disable resistance test current");
    Serial.println("READ    - Read all sense pins");
    Serial.println("PINS    - Show all pin states");

  } else {
    Serial.println("ERROR:UNKNOWN_CMD:" + cmd);
  }
}

// ===== TEST FUNCTIONS =====
void runContinuityTest() {
  TestResults results;

  // Turn off result LEDs, turn on status
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  // Enter continuity test mode
  digitalWrite(K1_K2_RELAY, HIGH);   // K1+K2: feed signal, route to sense inputs
  delay(RELAY_SETTLE_MS);

  // === TEST 1: SEND SIGNAL TO TIP ===
  digitalWrite(K3_RELAY, HIGH);   // Route to TIP
  delay(RELAY_SETTLE_MS);

  digitalWrite(CONT_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.tipToTip = digitalRead(TIP_SENSE) == HIGH;
  results.tipToSleeve = digitalRead(SLEEVE_SENSE) == HIGH;

  digitalWrite(CONT_TEST_OUT, LOW);
  delay(RELAY_SETTLE_MS);

  // === TEST 2: SEND SIGNAL TO SLEEVE ===
  digitalWrite(K3_RELAY, LOW);    // Route to SLEEVE
  delay(RELAY_SETTLE_MS);

  digitalWrite(CONT_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.sleeveToSleeve = digitalRead(SLEEVE_SENSE) == HIGH;
  results.sleeveToTip = digitalRead(TIP_SENSE) == HIGH;

  digitalWrite(CONT_TEST_OUT, LOW);

  // === EVALUATE RESULTS ===
  // PASS: signal goes tip->tip and sleeve->sleeve, no cross-connection
  results.overallPass = results.tipToTip && !results.tipToSleeve &&
                        results.sleeveToSleeve && !results.sleeveToTip;

  // REVERSED: signal goes tip->sleeve and sleeve->tip
  results.reversed = !results.tipToTip && results.tipToSleeve &&
                     !results.sleeveToSleeve && results.sleeveToTip;

  // CROSSED: signal bleeds to both pins (short between tip and sleeve)
  results.crossed = results.tipToTip && results.tipToSleeve;

  // OPEN: no signal detected
  results.openTip = !results.tipToTip && !results.tipToSleeve;
  results.openSleeve = !results.sleeveToSleeve && !results.sleeveToTip;

  // Reset circuit
  resetCircuit();

  // Update LEDs
  if (results.overallPass) {
    setResultLED(PASS_LED);
  } else if (results.reversed || results.crossed) {
    // Wiring error (reversed polarity or short)
    setResultLED(ERROR_LED);
  } else {
    // Open connection
    setResultLED(FAIL_LED);
  }

  // Send results
  sendResults(results);
}

void sendResults(TestResults &r) {
  String response = "RESULT:";
  response += r.overallPass ? "PASS" : "FAIL";

  // Raw readings: TT=tipToTip, TS=tipToSleeve, SS=sleeveToSleeve, ST=sleeveToTip
  response += ":TT:" + String(r.tipToTip ? 1 : 0);
  response += ":TS:" + String(r.tipToSleeve ? 1 : 0);
  response += ":SS:" + String(r.sleeveToSleeve ? 1 : 0);
  response += ":ST:" + String(r.sleeveToTip ? 1 : 0);

  // Add failure reason if failed
  if (!r.overallPass) {
    response += ":REASON:";
    if (r.reversed) {
      response += "REVERSED";
    } else if (r.crossed) {
      response += "CROSSED";
    } else if (r.openTip && r.openSleeve) {
      response += "NO_CABLE";
    } else if (r.openTip) {
      response += "TIP_OPEN";
    } else if (r.openSleeve) {
      response += "SLEEVE_OPEN";
    } else {
      response += "UNKNOWN";
    }
  }

  Serial.println(response);
}

void sendStatus() {
  String status = "STATUS:";
  status += systemReady ? "READY" : "NOT_READY";
  Serial.println(status);
}

void resetCircuit() {
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(CONT_TEST_OUT, LOW);
}

// ===== CALIBRATION =====
void runCalibration() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  Serial.println("CAL:MEASURING...");

  // Configure for resistance test mode
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K4_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);

  // Enable current through PN2222A
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  // Take multiple samples for stable calibration
  long adcSum = 0;
  const int NUM_SAMPLES = 50;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(10);
  }
  calibrationADC = adcSum / NUM_SAMPLES;
  isCalibrated = true;

  // Disable test current
  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  setResultLED(PASS_LED);
  Serial.println("CAL:OK:ADC:" + String(calibrationADC));
}

// ===== RESISTANCE TEST =====
void runResistanceTest() {
  // Turn off result LEDs, turn on status
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  // Configure for resistance test mode
  // K1+K2 LOW = short far end, connect to K4 path
  // K4 HIGH = resistance mode
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K4_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);

  // Enable current through PN2222A
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  // Read voltage across 47Ω reference resistor (average multiple samples)
  // Higher voltage = more current = lower cable resistance
  long adcSum = 0;
  const int NUM_SAMPLES = 20;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(5);
  }
  int adcValue = adcSum / NUM_SAMPLES;

  // Disable test current
  digitalWrite(RES_TEST_OUT, LOW);

  // Reset circuit
  resetCircuit();

  // Evaluate result
  bool pass = adcValue >= RES_PASS_THRESHOLD;

  // Calculate current from ADC
  float voltage = (adcValue / 1023.0) * SUPPLY_VOLTAGE;
  float current = voltage / RES_REFERENCE_OHM;

  // Calculate cable resistance relative to calibration
  float cableResistance = 0.0;
  if (isCalibrated && current > 0.001) {
    float calVoltage = (calibrationADC / 1023.0) * SUPPLY_VOLTAGE;
    float calCurrent = calVoltage / RES_REFERENCE_OHM;
    // Lower ADC = less current = more resistance
    // R_cable = (V_cal - V_meas) / I  (approximately)
    float voltageDiff = calVoltage - voltage;
    cableResistance = voltageDiff / current;
    if (cableResistance < 0) cableResistance = 0;
  }

  // Update LED
  if (pass) {
    setResultLED(PASS_LED);
  } else {
    setResultLED(FAIL_LED);
  }

  // Send result
  String response = "RES:";
  response += pass ? "PASS" : "FAIL";
  response += ":ADC:" + String(adcValue);
  if (isCalibrated) {
    response += ":CAL:" + String(calibrationADC);
    // Show in milliohms for better resolution
    int milliohms = (int)(cableResistance * 1000);
    response += ":MOHM:" + String(milliohms);
    response += ":OHM:" + String(cableResistance, 3);
  } else {
    response += ":OHM:UNCAL";
  }
  Serial.println(response);
}

// ===== UTILITY FUNCTIONS =====
// Result LEDs are active-low (common anode RGB LED)
// setResultLED(pin) - turn on that LED, others off
// setResultLED()    - all result LEDs off
void setResultLED(int pin) {
  digitalWrite(FAIL_LED, HIGH);
  digitalWrite(PASS_LED, HIGH);
  digitalWrite(ERROR_LED, HIGH);
  if (pin >= 0) {
    digitalWrite(pin, LOW);
  }
}

bool selfTest() {
  // Blink each result LED in sequence
  int leds[] = {PASS_LED, ERROR_LED, FAIL_LED};
  for (int i = 0; i < 3; i++) {
    setResultLED(leds[i]);
    delay(150);
    setResultLED();
  }

  // Could add more hardware checks here
  return true;
}

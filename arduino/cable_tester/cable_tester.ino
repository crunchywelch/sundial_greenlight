/*
 * Greenlight TS/XLR Cable Tester - Arduino Mega 2560
 *
 * Continuity, polarity, and resistance testing for TS/XLR cables.
 * Communicates with Raspberry Pi via USB serial.
 *
 * Commands:
 *   CONT     - Run continuity/polarity test, returns RESULT:...
 *   RES      - Run resistance test, returns RES:...
 *   CAL      - Calibrate resistance (use short cable)
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *
 * Relay Configuration:
 *   K1+K2 (D16)    - Tied together. TS test mode switching. LOW = short far end + res/cap path, HIGH = continuity mode
 *   K3 (D15)       - XLR/TS test mode. LOW = TS, HIGH = XLR
 *   K4 (D14)       - Resistance test mode. HIGH = resistance mode (for TS only)
 *   K5+K6+K7 (D69) - Tied together. XLR test mode switching. LOW = short far end, HIGH = continuity/resistance test mode on all pins
 *   K8+K9 (D68)    - Tied together. XLR continuity/resistance test mode switching. LOW = continuity mode, HIGH = resistance mode
 *
 * Pin Configuration:
 *   D2  - TS continuity signal, SLEEVE
 *   D3  - TS continuity signal, TIP
 *   D4  - TS continuity sense, SLEEVE
 *   D5  - TS continuity sense, TIP
 *   D6  - TS_RES_TEST_OUT (PN2222A base drive via 330Ω)
 *   D13 - STATUS_LED (built-in)
 *   D14 - K4_DRIVE, RES test mode
 *   D15 - K3_DRIVE, XLR/TS test mode
 *   D16 - K1_K2_DRIVE, TS test mode
 *   D19 - FAIL_LED (red)
 *   D20 - PASS_LED (green)
 *   D21 - ERROR_LED (blue)
 *   D60 - XLR_RES_TEST_OUT_PIN3 
 *   D61 - XLR_RES_TEST_OUT_PIN2
 *   D62 - XLR_CONT_TEST_OUT_PIN1
 *   D63 - XLR_CONT_TEST_OUT_PIN2, K8+K9 must be LOW
 *   D64 - XLR_CONT_TEST_OUT_PIN3, K8+K9 must be LOW
 *   D65 - XLR_CONT_TEST_IN_PIN1 
 *   D66 - XLR_CONT_TEST_IN_PIN2, K8+K9 must be LOW, K5+K6+K7 must be HIGH
 *   D67 - XLR_CONT_TEST_IN_PIN3, K8+K9 must be LOW, K5+K6+K7 must be HIGH
 *   D68 - K8_K9_DRIVE
 *   D69 - K5_K6_K7_DRIVE
 *   A0  - TS_RES_SENSE (analog input - high-side sense resistor junction)
 *   A2  - XLR_RES_SENSE_PIN2 (analog input - resistance measure XLR pin 2)
 *   A3  - XLR_RES_SENSE_PIN3 (analog input - resistance measure XLR pin 3)
 */

// ===== PIN DEFINITIONS =====

// --- TS Cable Testing ---
// Continuity signals
#define TS_CONT_OUT_SLEEVE   2    // Continuity signal output to SLEEVE
#define TS_CONT_OUT_TIP      3    // Continuity signal output to TIP
#define TS_CONT_IN_SLEEVE    4    // Continuity sense input from SLEEVE
#define TS_CONT_IN_TIP       5    // Continuity sense input from TIP
// Resistance
#define TS_RES_TEST_OUT      6    // PN2222A base drive for resistance test
#define TS_RES_SENSE         A0   // Analog input: resistance measurement

// --- Relay Drives ---
#define K1_K2_RELAY         16   // TS test mode: LOW = short far end + res path, HIGH = continuity
#define K3_RELAY            15   // XLR/TS mode: LOW = TS, HIGH = XLR
#define K4_RELAY            14   // RES mode (TS only): HIGH = resistance
#define K5_K6_K7_RELAY      69   // XLR test mode: LOW = short far end, HIGH = cont/res mode
#define K8_K9_RELAY         68   // XLR cont/res mode: LOW = continuity, HIGH = resistance

// --- XLR Cable Testing ---
// Continuity signals
#define XLR_CONT_OUT_PIN1   62   // Continuity signal output to XLR Pin 1
#define XLR_CONT_OUT_PIN2   63   // Continuity signal output to XLR Pin 2
#define XLR_CONT_OUT_PIN3   64   // Continuity signal output to XLR Pin 3
#define XLR_CONT_IN_PIN1    65   // Continuity sense input from XLR Pin 1
#define XLR_CONT_IN_PIN2    66   // Continuity sense input from XLR Pin 2
#define XLR_CONT_IN_PIN3    67   // Continuity sense input from XLR Pin 3
// Resistance
#define XLR_RES_OUT_PIN2    61   // PN2222A base drive for XLR Pin 2 resistance
#define XLR_RES_OUT_PIN3    60   // PN2222A base drive for XLR Pin 3 resistance
#define XLR_RES_SENSE_PIN2  A2   // Analog input: XLR Pin 2 resistance
#define XLR_RES_SENSE_PIN3  A3   // Analog input: XLR Pin 3 resistance

// --- LEDs ---
#define STATUS_LED          13   // Built-in LED
#define ERROR_LED           21   // Blue
#define PASS_LED            20   // Green
#define FAIL_LED            19   // Red

// ===== CONFIGURATION =====
const char* TESTER_ID = "TS_TESTER_1";
const int BAUD_RATE = 9600;
const int RELAY_SETTLE_MS = 10;
const int SIGNAL_SETTLE_MS = 50;

// Resistance test config
// High-side sense topology: 5V → R_sense(20Ω) → cable → relay → collector, emitter → GND
// A0 reads junction of R_sense and cable. Lower ADC = more current = lower cable resistance.
const int RES_PASS_THRESHOLD = 500;  // ADC value below this = PASS (low cable resistance)
const float RES_SENSE_OHM = 20.0;   // High-side sense resistor (20Ω)
const float SUPPLY_VOLTAGE = 5.0;    // Arduino USB supply voltage
const float VCE_SAT = 0.3;           // PN2222A saturation voltage estimate
// Base: D6 → 330Ω → base. Emitter grounded, so Ib ≈ 12mA — solid drive, no degeneration.

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

  // --- Relay outputs ---
  pinMode(K1_K2_RELAY, OUTPUT);
  pinMode(K3_RELAY, OUTPUT);
  pinMode(K4_RELAY, OUTPUT);
  pinMode(K5_K6_K7_RELAY, OUTPUT);
  pinMode(K8_K9_RELAY, OUTPUT);

  // --- TS continuity outputs ---
  pinMode(TS_CONT_OUT_SLEEVE, OUTPUT);
  pinMode(TS_CONT_OUT_TIP, OUTPUT);

  // --- TS continuity inputs ---
  pinMode(TS_CONT_IN_SLEEVE, INPUT);
  pinMode(TS_CONT_IN_TIP, INPUT);

  // --- TS resistance ---
  pinMode(TS_RES_TEST_OUT, OUTPUT);
  // A0 (TS_RES_SENSE) is analog input by default

  // --- XLR continuity outputs ---
  pinMode(XLR_CONT_OUT_PIN1, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN2, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN3, OUTPUT);

  // --- XLR continuity inputs ---
  pinMode(XLR_CONT_IN_PIN1, INPUT);
  pinMode(XLR_CONT_IN_PIN2, INPUT);
  pinMode(XLR_CONT_IN_PIN3, INPUT);

  // --- XLR resistance ---
  pinMode(XLR_RES_OUT_PIN2, OUTPUT);
  pinMode(XLR_RES_OUT_PIN3, OUTPUT);
  // A2, A3 (XLR_RES_SENSE) are analog inputs by default

  // --- LEDs ---
  pinMode(FAIL_LED, OUTPUT);
  pinMode(PASS_LED, OUTPUT);
  pinMode(ERROR_LED, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  // Initialize all relays OFF
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(K5_K6_K7_RELAY, LOW);
  digitalWrite(K8_K9_RELAY, LOW);

  // Initialize all test outputs OFF
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(TS_RES_TEST_OUT, LOW);
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);
  digitalWrite(XLR_RES_OUT_PIN2, LOW);
  digitalWrite(XLR_RES_OUT_PIN3, LOW);

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
    Serial.println("FAIL_LED ON (D19) - RED");
    setResultLED(FAIL_LED);
    delay(500);
    setResultLED();
    Serial.println("PASS_LED ON (D20) - GREEN");
    setResultLED(PASS_LED);
    delay(500);
    setResultLED();
    Serial.println("ERROR_LED ON (D21) - BLUE");
    setResultLED(ERROR_LED);
    delay(500);
    setResultLED();
    Serial.println("STATUS_LED ON (D13)");
    digitalWrite(STATUS_LED, HIGH);
    delay(500);
    digitalWrite(STATUS_LED, LOW);
    Serial.println("DEBUG:LED_TEST_DONE");

  // --- TS Relay Toggles ---
  } else if (cmd == "K12") {
    bool state = !digitalRead(K1_K2_RELAY);
    digitalWrite(K1_K2_RELAY, state);
    Serial.println("DEBUG:K1+K2(D16):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K3") {
    bool state = !digitalRead(K3_RELAY);
    digitalWrite(K3_RELAY, state);
    Serial.println("DEBUG:K3(D15):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K4") {
    bool state = !digitalRead(K4_RELAY);
    digitalWrite(K4_RELAY, state);
    Serial.println("DEBUG:K4(D14):" + String(state ? "HIGH" : "LOW"));

  // --- XLR Relay Toggles ---
  } else if (cmd == "K567") {
    bool state = !digitalRead(K5_K6_K7_RELAY);
    digitalWrite(K5_K6_K7_RELAY, state);
    Serial.println("DEBUG:K5+K6+K7(D69):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K89") {
    bool state = !digitalRead(K8_K9_RELAY);
    digitalWrite(K8_K9_RELAY, state);
    Serial.println("DEBUG:K8+K9(D68):" + String(state ? "HIGH" : "LOW"));

  // --- TS Test Signals ---
  } else if (cmd == "TSTIP") {
    bool state = !digitalRead(TS_CONT_OUT_TIP);
    digitalWrite(TS_CONT_OUT_TIP, state);
    Serial.println("DEBUG:TS_CONT_OUT_TIP(D3):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "TSSLV") {
    bool state = !digitalRead(TS_CONT_OUT_SLEEVE);
    digitalWrite(TS_CONT_OUT_SLEEVE, state);
    Serial.println("DEBUG:TS_CONT_OUT_SLEEVE(D2):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "TSRES") {
    bool state = !digitalRead(TS_RES_TEST_OUT);
    digitalWrite(TS_RES_TEST_OUT, state);
    Serial.println("DEBUG:TS_RES_TEST_OUT(D6):" + String(state ? "HIGH" : "LOW"));

  // --- XLR Test Signals ---
  } else if (cmd == "XLR1") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN1);
    digitalWrite(XLR_CONT_OUT_PIN1, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN1(D62):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR2") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN2);
    digitalWrite(XLR_CONT_OUT_PIN2, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN2(D63):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR3") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN3);
    digitalWrite(XLR_CONT_OUT_PIN3, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN3(D64):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLRR2") {
    bool state = !digitalRead(XLR_RES_OUT_PIN2);
    digitalWrite(XLR_RES_OUT_PIN2, state);
    Serial.println("DEBUG:XLR_RES_OUT_PIN2(D61):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLRR3") {
    bool state = !digitalRead(XLR_RES_OUT_PIN3);
    digitalWrite(XLR_RES_OUT_PIN3, state);
    Serial.println("DEBUG:XLR_RES_OUT_PIN3(D60):" + String(state ? "HIGH" : "LOW"));

  // --- Read Sensors ---
  } else if (cmd == "READ") {
    Serial.println("=== TS SENSE ===");
    Serial.println("  TIP(D5):    " + String(digitalRead(TS_CONT_IN_TIP)));
    Serial.println("  SLEEVE(D4): " + String(digitalRead(TS_CONT_IN_SLEEVE)));
    Serial.println("  RES(A0):    " + String(analogRead(TS_RES_SENSE)));
    Serial.println("=== XLR SENSE ===");
    Serial.println("  PIN1(D65):  " + String(digitalRead(XLR_CONT_IN_PIN1)));
    Serial.println("  PIN2(D66):  " + String(digitalRead(XLR_CONT_IN_PIN2)));
    Serial.println("  PIN3(D67):  " + String(digitalRead(XLR_CONT_IN_PIN3)));
    Serial.println("  RES2(A2):   " + String(analogRead(XLR_RES_SENSE_PIN2)));
    Serial.println("  RES3(A3):   " + String(analogRead(XLR_RES_SENSE_PIN3)));
  } else if (cmd == "PINS") {
    Serial.println("=== RELAYS ===");
    Serial.println("  D16 K1+K2:     " + String(digitalRead(K1_K2_RELAY) ? "HIGH" : "LOW") + " (TS mode)");
    Serial.println("  D15 K3:        " + String(digitalRead(K3_RELAY) ? "HIGH" : "LOW") + " (XLR/TS cap)");
    Serial.println("  D14 K4:        " + String(digitalRead(K4_RELAY) ? "HIGH" : "LOW") + " (CAP/RES)");
    Serial.println("  D69 K5+K6+K7:  " + String(digitalRead(K5_K6_K7_RELAY) ? "HIGH" : "LOW") + " (XLR mode)");
    Serial.println("  D68 K8+K9:     " + String(digitalRead(K8_K9_RELAY) ? "HIGH" : "LOW") + " (XLR cont/res)");
    Serial.println("=== TS OUTPUTS ===");
    Serial.println("  D2  SLEEVE:  " + String(digitalRead(TS_CONT_OUT_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D3  TIP:     " + String(digitalRead(TS_CONT_OUT_TIP) ? "HIGH" : "LOW"));
    Serial.println("  D6  RES:     " + String(digitalRead(TS_RES_TEST_OUT) ? "HIGH" : "LOW"));
    Serial.println("=== TS INPUTS ===");
    Serial.println("  D4  SLEEVE:  " + String(digitalRead(TS_CONT_IN_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D5  TIP:     " + String(digitalRead(TS_CONT_IN_TIP) ? "HIGH" : "LOW"));
    Serial.println("  A0  RES:     " + String(analogRead(TS_RES_SENSE)));
    Serial.println("=== XLR OUTPUTS ===");
    Serial.println("  D62 PIN1:    " + String(digitalRead(XLR_CONT_OUT_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D63 PIN2:    " + String(digitalRead(XLR_CONT_OUT_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D64 PIN3:    " + String(digitalRead(XLR_CONT_OUT_PIN3) ? "HIGH" : "LOW"));
    Serial.println("  D61 RES2:    " + String(digitalRead(XLR_RES_OUT_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D60 RES3:    " + String(digitalRead(XLR_RES_OUT_PIN3) ? "HIGH" : "LOW"));
    Serial.println("=== XLR INPUTS ===");
    Serial.println("  D65 PIN1:    " + String(digitalRead(XLR_CONT_IN_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D66 PIN2:    " + String(digitalRead(XLR_CONT_IN_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D67 PIN3:    " + String(digitalRead(XLR_CONT_IN_PIN3) ? "HIGH" : "LOW"));
    Serial.println("  A2  RES2:    " + String(analogRead(XLR_RES_SENSE_PIN2)));
    Serial.println("  A3  RES3:    " + String(analogRead(XLR_RES_SENSE_PIN3)));
    Serial.println("=== LEDS ===");
    Serial.println("  D13 STATUS:  " + String(digitalRead(STATUS_LED) ? "ON" : "OFF"));
    Serial.println("  D19 FAIL:    " + String(digitalRead(FAIL_LED) ? "OFF" : "ON"));
    Serial.println("  D20 PASS:    " + String(digitalRead(PASS_LED) ? "OFF" : "ON"));
    Serial.println("  D21 ERROR:   " + String(digitalRead(ERROR_LED) ? "OFF" : "ON"));

  } else if (cmd == "HELP") {
    Serial.println("=== COMMANDS ===");
    Serial.println("CONT    - Run TS continuity test");
    Serial.println("RES     - Run TS resistance test");
    Serial.println("CAL     - Calibrate resistance (short cable)");
    Serial.println("STATUS  - Get tester status");
    Serial.println("ID      - Get tester ID");
    Serial.println("RESET   - Reset circuit");
    Serial.println("--- DEBUG: RELAYS ---");
    Serial.println("K12     - Toggle K1+K2 (D16)");
    Serial.println("K3      - Toggle K3 (D15)");
    Serial.println("K4      - Toggle K4 (D14)");
    Serial.println("K567    - Toggle K5+K6+K7 (D69)");
    Serial.println("K89     - Toggle K8+K9 (D68)");
    Serial.println("--- DEBUG: TS ---");
    Serial.println("TSTIP   - Toggle TS tip out (D3)");
    Serial.println("TSSLV   - Toggle TS sleeve out (D2)");
    Serial.println("TSRES   - Toggle TS resistance (D6)");
    Serial.println("--- DEBUG: XLR ---");
    Serial.println("XLR1    - Toggle XLR pin1 out (D62)");
    Serial.println("XLR2    - Toggle XLR pin2 out (D63)");
    Serial.println("XLR3    - Toggle XLR pin3 out (D64)");
    Serial.println("XLRR2   - Toggle XLR res pin2 (D61)");
    Serial.println("XLRR3   - Toggle XLR res pin3 (D60)");
    Serial.println("--- DEBUG: READ ---");
    Serial.println("READ    - Read all sense pins");
    Serial.println("PINS    - Show all pin states");
    Serial.println("LED     - Cycle all LEDs");

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
  digitalWrite(K1_K2_RELAY, HIGH);   // K1+K2: continuity mode
  delay(RELAY_SETTLE_MS);

  // === TEST 1: SEND SIGNAL TO TIP ===
  digitalWrite(TS_CONT_OUT_TIP, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.tipToTip = digitalRead(TS_CONT_IN_TIP) == HIGH;
  results.tipToSleeve = digitalRead(TS_CONT_IN_SLEEVE) == HIGH;

  digitalWrite(TS_CONT_OUT_TIP, LOW);
  delay(RELAY_SETTLE_MS);

  // === TEST 2: SEND SIGNAL TO SLEEVE ===
  digitalWrite(TS_CONT_OUT_SLEEVE, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.sleeveToSleeve = digitalRead(TS_CONT_IN_SLEEVE) == HIGH;
  results.sleeveToTip = digitalRead(TS_CONT_IN_TIP) == HIGH;

  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);

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
  // All relays off
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(K5_K6_K7_RELAY, LOW);
  digitalWrite(K8_K9_RELAY, LOW);

  // All TS test outputs off
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(TS_RES_TEST_OUT, LOW);

  // All XLR test outputs off
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);
  digitalWrite(XLR_RES_OUT_PIN2, LOW);
  digitalWrite(XLR_RES_OUT_PIN3, LOW);

}

// ===== CALIBRATION =====
// Calibrate with a known-good short cable (or direct short).
// Establishes baseline ADC that includes Vce_sat + parasitic resistance.
// Cable resistance is then measured relative to this baseline.
void runCalibration() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  Serial.println("CAL:MEASURING...");

  // Configure for resistance test mode
  digitalWrite(K1_K2_RELAY, LOW);    // Short far end + res/cap path
  digitalWrite(K4_RELAY, HIGH);      // Resistance mode (HIGH = resistance)
  delay(RELAY_SETTLE_MS);

  // Enable current through PN2222A
  digitalWrite(TS_RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  // Take multiple samples for stable calibration
  long adcSum = 0;
  const int NUM_SAMPLES = 50;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(TS_RES_SENSE);
    delay(10);
  }
  int measuredADC = adcSum / NUM_SAMPLES;

  // Disable test current
  digitalWrite(TS_RES_TEST_OUT, LOW);
  resetCircuit();

  // Reject if reading is too high (no cable or bad connection)
  if (measuredADC > 600) {
    setResultLED(FAIL_LED);
    Serial.println("CAL:FAIL:ADC:" + String(measuredADC) + ":NO_CABLE");
    return;
  }

  calibrationADC = measuredADC;
  isCalibrated = true;

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
  digitalWrite(TS_RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  // Read voltage at high-side sense resistor junction (average multiple samples)
  // Lower voltage = more current flowing = lower cable resistance
  long adcSum = 0;
  const int NUM_SAMPLES = 20;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(TS_RES_SENSE);
    delay(5);
  }
  int adcValue = adcSum / NUM_SAMPLES;

  // Disable test current
  digitalWrite(TS_RES_TEST_OUT, LOW);

  // Reset circuit
  resetCircuit();

  // Evaluate result (lower ADC = more current = better cable)
  bool pass = adcValue <= RES_PASS_THRESHOLD;

  // Calculate current: I = (VCC - V_sense) / R_sense
  float senseVoltage = (adcValue / 1023.0) * SUPPLY_VOLTAGE;
  float current = (SUPPLY_VOLTAGE - senseVoltage) / RES_SENSE_OHM;

  // Calculate cable resistance relative to calibration
  // Calibration captures baseline (Vce_sat + parasitic resistance)
  // R_cable ≈ (V_test - V_cal) / I_cal
  float cableResistance = 0.0;
  if (isCalibrated) {
    float calVoltage = (calibrationADC / 1023.0) * SUPPLY_VOLTAGE;
    float calCurrent = (SUPPLY_VOLTAGE - calVoltage) / RES_SENSE_OHM;
    if (calCurrent > 0.001) {
      float voltageDiff = senseVoltage - calVoltage;
      cableResistance = voltageDiff / calCurrent;
      if (cableResistance < 0) cableResistance = 0;
    }
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
  int leds[] = {FAIL_LED, PASS_LED, ERROR_LED};
  for (int i = 0; i < 3; i++) {
    setResultLED(leds[i]);
    delay(150);
    setResultLED();
  }

  // Could add more hardware checks here
  return true;
}

/*
 * Greenlight TS/XLR Cable Tester - Arduino Mega 2560
 *
 * Continuity, polarity, and resistance testing for TS/XLR cables.
 * Communicates with Raspberry Pi via USB serial.
 *
 * Commands:
 *   CONT     - Run TS continuity/polarity test, returns RESULT:...
 *   RES      - Run TS resistance test, returns RES:...
 *   XLRRES   - Run XLR resistance test (pin 2 + pin 3), returns XLRRES:...
 *   CAL      - Calibrate TS resistance (use short cable)
 *   XLRCAL   - Calibrate XLR resistance (use short cable)
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *
 * Relay Configuration:
 *   K1+K2 (D14)    - Tied together. TS test mode switching. LOW = short far end + res path, HIGH = continuity mode
 *   K3 (D15)       - Resistance circuit switching. LOW = TS, HIGH = XLR
 *   K4 (D16)       - XLR resistance pin select. LOW = Pin 2, HIGH = Pin 3
 *   K5 (D62)       - XLR Pin 2 mode. LOW = continuity, HIGH = resistance (into K4)
 *   K6 (D63)       - XLR Pin 3 mode. LOW = continuity, HIGH = resistance (into K4)
 *
 * Pin Configuration:
 *   D2  - TS continuity signal, SLEEVE
 *   D3  - TS continuity signal, TIP
 *   D4  - TS continuity sense, SLEEVE
 *   D5  - TS continuity sense, TIP
 *   D6  - RES_TEST_OUT (PN2222A base drive via 330Ω, shared TS/XLR)
 *   D13 - STATUS_LED (built-in)
 *   D14 - K1_K2_DRIVE, TS test mode
 *   D15 - K3_DRIVE, resistance TS/XLR switch
 *   D16 - K4_DRIVE, XLR pin 2/3 select
 *   D19 - FAIL_LED (red)
 *   D20 - PASS_LED (green)
 *   D21 - ERROR_LED (blue)
 *   D62 - K5_DRIVE, XLR Pin 2 cont/res switch
 *   D63 - K6_DRIVE, XLR Pin 3 cont/res switch
 *   D64 - XLR_CONT_OUT_PIN1 (drive)
 *   D65 - XLR_CONT_IN_PIN1 (read)
 *   D66 - XLR_CONT_OUT_PIN2 (drive), K5 must be LOW
 *   D67 - XLR_CONT_IN_PIN2 (read), K5 must be LOW
 *   D68 - XLR_CONT_OUT_PIN3 (drive), K6 must be LOW
 *   D69 - XLR_CONT_IN_PIN3 (read), K6 must be LOW
 *   A0  - RES_SENSE (analog input - high-side sense resistor junction, shared TS/XLR)
 */

// ===== PIN DEFINITIONS =====

// --- TS Cable Testing ---
// Continuity signals
#define TS_CONT_OUT_SLEEVE   2    // Continuity signal output to SLEEVE
#define TS_CONT_OUT_TIP      3    // Continuity signal output to TIP
#define TS_CONT_IN_SLEEVE    4    // Continuity sense input from SLEEVE
#define TS_CONT_IN_TIP       5    // Continuity sense input from TIP

// --- Resistance (shared TS/XLR via K3/K4 relay switching) ---
#define RES_TEST_OUT         6    // PN2222A base drive for resistance test
#define RES_SENSE            A0   // Analog input: resistance measurement

// --- Relay Drives ---
#define K1_K2_RELAY         14   // TS test mode: LOW = short far end + res path, HIGH = continuity
#define K3_RELAY            15   // Resistance circuit: LOW = TS, HIGH = XLR
#define K4_RELAY            16   // XLR resistance pin select: LOW = Pin 2, HIGH = Pin 3
#define K5_RELAY            62   // XLR Pin 2: LOW = continuity, HIGH = resistance (into K4)
#define K6_RELAY            63   // XLR Pin 3: LOW = continuity, HIGH = resistance (into K4)

// --- XLR Cable Testing ---
// Continuity signals (paired drive/read with pulldown resistors)
#define XLR_CONT_OUT_PIN1   64   // Continuity signal output to XLR Pin 1
#define XLR_CONT_IN_PIN1    65   // Continuity sense input from XLR Pin 1
#define XLR_CONT_OUT_PIN2   66   // Continuity signal output to XLR Pin 2
#define XLR_CONT_IN_PIN2    67   // Continuity sense input from XLR Pin 2
#define XLR_CONT_OUT_PIN3   68   // Continuity signal output to XLR Pin 3
#define XLR_CONT_IN_PIN3    69   // Continuity sense input from XLR Pin 3

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
int calibrationADC = 0;              // TS ADC reading with zero-ohm reference
bool isCalibrated = false;
int xlrCalibrationADC = 0;           // XLR ADC reading with zero-ohm reference
bool isXlrCalibrated = false;

// Forward declaration for default argument
void setResultLED(int pin = -1);

// ===== GLOBAL STATE =====
bool systemReady = false;
String inputBuffer = "";

// ===== TS TEST RESULTS =====
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

// ===== XLR TEST RESULTS =====
struct XlrContResults {
  // 3x3 continuity matrix: [drive][read]
  bool p[3][3];  // p[0]=drive pin1, p[1]=drive pin2, p[2]=drive pin3
  bool overallPass;
};

// ===== SETUP =====
void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) { ; }  // Wait for USB serial

  // --- Relay outputs ---
  pinMode(K1_K2_RELAY, OUTPUT);
  pinMode(K3_RELAY, OUTPUT);
  pinMode(K4_RELAY, OUTPUT);
  pinMode(K5_RELAY, OUTPUT);
  pinMode(K6_RELAY, OUTPUT);

  // --- TS continuity outputs ---
  pinMode(TS_CONT_OUT_SLEEVE, OUTPUT);
  pinMode(TS_CONT_OUT_TIP, OUTPUT);

  // --- TS continuity inputs ---
  pinMode(TS_CONT_IN_SLEEVE, INPUT);
  pinMode(TS_CONT_IN_TIP, INPUT);

  // --- Resistance (shared TS/XLR) ---
  pinMode(RES_TEST_OUT, OUTPUT);
  // A0 (RES_SENSE) is analog input by default

  // --- XLR continuity outputs ---
  pinMode(XLR_CONT_OUT_PIN1, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN2, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN3, OUTPUT);

  // --- XLR continuity inputs ---
  pinMode(XLR_CONT_IN_PIN1, INPUT);
  pinMode(XLR_CONT_IN_PIN2, INPUT);
  pinMode(XLR_CONT_IN_PIN3, INPUT);

  // --- LEDs ---
  pinMode(FAIL_LED, OUTPUT);
  pinMode(PASS_LED, OUTPUT);
  pinMode(ERROR_LED, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  // Initialize all relays OFF
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(K5_RELAY, LOW);
  digitalWrite(K6_RELAY, LOW);

  // Initialize all test outputs OFF
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);

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

  } else if (cmd == "XLRCONT") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runXlrContinuityTest();

  } else if (cmd == "RES") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runResistanceTest();

  } else if (cmd == "XLRRES") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runXlrResistanceTest();

  } else if (cmd == "CAL") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runCalibration();

  } else if (cmd == "XLRCAL") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runXlrCalibration();

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
    Serial.println("DEBUG:K1+K2(D14):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K3") {
    bool state = !digitalRead(K3_RELAY);
    digitalWrite(K3_RELAY, state);
    Serial.println("DEBUG:K3(D15):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K4") {
    bool state = !digitalRead(K4_RELAY);
    digitalWrite(K4_RELAY, state);
    Serial.println("DEBUG:K4(D16):" + String(state ? "HIGH" : "LOW"));

  // --- XLR Relay Toggles ---
  } else if (cmd == "K5") {
    bool state = !digitalRead(K5_RELAY);
    digitalWrite(K5_RELAY, state);
    Serial.println("DEBUG:K5(D62):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K6") {
    bool state = !digitalRead(K6_RELAY);
    digitalWrite(K6_RELAY, state);
    Serial.println("DEBUG:K6(D63):" + String(state ? "HIGH" : "LOW"));

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
    bool state = !digitalRead(RES_TEST_OUT);
    digitalWrite(RES_TEST_OUT, state);
    Serial.println("DEBUG:RES_TEST_OUT(D6):" + String(state ? "HIGH" : "LOW"));

  // --- XLR Test Signals ---
  } else if (cmd == "XLR1") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN1);
    digitalWrite(XLR_CONT_OUT_PIN1, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN1(D64):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR2") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN2);
    digitalWrite(XLR_CONT_OUT_PIN2, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN2(D66):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR3") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN3);
    digitalWrite(XLR_CONT_OUT_PIN3, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN3(D68):" + String(state ? "HIGH" : "LOW"));

  // --- Read Sensors ---
  } else if (cmd == "READ") {
    Serial.println("=== TS SENSE ===");
    Serial.println("  TIP(D5):    " + String(digitalRead(TS_CONT_IN_TIP)));
    Serial.println("  SLEEVE(D4): " + String(digitalRead(TS_CONT_IN_SLEEVE)));
    Serial.println("=== RES SENSE (shared) ===");
    Serial.println("  RES(A0):    " + String(analogRead(RES_SENSE)));
    Serial.println("=== XLR SENSE ===");
    Serial.println("  PIN1(D65):  " + String(digitalRead(XLR_CONT_IN_PIN1)));
    Serial.println("  PIN2(D67):  " + String(digitalRead(XLR_CONT_IN_PIN2)));
    Serial.println("  PIN3(D69):  " + String(digitalRead(XLR_CONT_IN_PIN3)));
  } else if (cmd == "PINS") {
    Serial.println("=== RELAYS ===");
    Serial.println("  D14 K1+K2:     " + String(digitalRead(K1_K2_RELAY) ? "HIGH" : "LOW") + " (TS far end)");
    Serial.println("  D15 K3:        " + String(digitalRead(K3_RELAY) ? "HIGH" : "LOW") + " (res: L=TS H=XLR)");
    Serial.println("  D16 K4:        " + String(digitalRead(K4_RELAY) ? "HIGH" : "LOW") + " (XLR: L=P2 H=P3)");
    Serial.println("  D62 K5:        " + String(digitalRead(K5_RELAY) ? "HIGH" : "LOW") + " (XLR P2: L=cont H=res)");
    Serial.println("  D63 K6:        " + String(digitalRead(K6_RELAY) ? "HIGH" : "LOW") + " (XLR P3: L=cont H=res)");
    Serial.println("=== TS OUTPUTS ===");
    Serial.println("  D2  SLEEVE:  " + String(digitalRead(TS_CONT_OUT_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D3  TIP:     " + String(digitalRead(TS_CONT_OUT_TIP) ? "HIGH" : "LOW"));
    Serial.println("=== TS INPUTS ===");
    Serial.println("  D4  SLEEVE:  " + String(digitalRead(TS_CONT_IN_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D5  TIP:     " + String(digitalRead(TS_CONT_IN_TIP) ? "HIGH" : "LOW"));
    Serial.println("=== RESISTANCE (shared) ===");
    Serial.println("  D6  DRIVE:   " + String(digitalRead(RES_TEST_OUT) ? "HIGH" : "LOW"));
    Serial.println("  A0  SENSE:   " + String(analogRead(RES_SENSE)));
    Serial.println("=== XLR CONTINUITY ===");
    Serial.println("  D64 PIN1 OUT: " + String(digitalRead(XLR_CONT_OUT_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D65 PIN1 IN:  " + String(digitalRead(XLR_CONT_IN_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D66 PIN2 OUT: " + String(digitalRead(XLR_CONT_OUT_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D67 PIN2 IN:  " + String(digitalRead(XLR_CONT_IN_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D68 PIN3 OUT: " + String(digitalRead(XLR_CONT_OUT_PIN3) ? "HIGH" : "LOW"));
    Serial.println("  D69 PIN3 IN:  " + String(digitalRead(XLR_CONT_IN_PIN3) ? "HIGH" : "LOW"));
    Serial.println("=== LEDS ===");
    Serial.println("  D13 STATUS:  " + String(digitalRead(STATUS_LED) ? "ON" : "OFF"));
    Serial.println("  D19 FAIL:    " + String(digitalRead(FAIL_LED) ? "OFF" : "ON"));
    Serial.println("  D20 PASS:    " + String(digitalRead(PASS_LED) ? "OFF" : "ON"));
    Serial.println("  D21 ERROR:   " + String(digitalRead(ERROR_LED) ? "OFF" : "ON"));

  } else if (cmd == "HELP") {
    Serial.println("=== COMMANDS ===");
    Serial.println("CONT    - Run TS continuity test");
    Serial.println("XLRCONT - Run XLR continuity test");
    Serial.println("RES     - Run TS resistance test");
    Serial.println("XLRRES  - Run XLR resistance test (pin 2+3)");
    Serial.println("CAL     - Calibrate TS resistance (short cable)");
    Serial.println("XLRCAL  - Calibrate XLR resistance (short cable)");
    Serial.println("STATUS  - Get tester status");
    Serial.println("ID      - Get tester ID");
    Serial.println("RESET   - Reset circuit");
    Serial.println("--- DEBUG: RELAYS ---");
    Serial.println("K12     - Toggle K1+K2 (D14)");
    Serial.println("K3      - Toggle K3 (D15)");
    Serial.println("K4      - Toggle K4 (D16)");
    Serial.println("K5      - Toggle K5 (D62) XLR P2 cont/res");
    Serial.println("K6      - Toggle K6 (D63) XLR P3 cont/res");
    Serial.println("--- DEBUG: TS ---");
    Serial.println("TSTIP   - Toggle TS tip out (D3)");
    Serial.println("TSSLV   - Toggle TS sleeve out (D2)");
    Serial.println("TSRES   - Toggle resistance drive (D6)");
    Serial.println("--- DEBUG: XLR ---");
    Serial.println("XLR1    - Toggle XLR pin1 out (D64)");
    Serial.println("XLR2    - Toggle XLR pin2 out (D66)");
    Serial.println("XLR3    - Toggle XLR pin3 out (D68)");
    Serial.println("--- DEBUG: XLR TESTS ---");
    Serial.println("XC      - Test XLR continuity (all pins)");
    Serial.println("XR      - Test XLR resistance (pin 2+3)");
    Serial.println("--- DEBUG: READ ---");
    Serial.println("READ    - Read all sense pins");
    Serial.println("PINS    - Show all pin states");
    Serial.println("LED     - Cycle all LEDs");

  // ===== XLR DEBUG TESTS =====
  } else if (cmd == "XC") {
    runXlrContinuityTest();

  } else if (cmd == "XR") {
    runXlrResistanceTest();

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

// ===== XLR CONTINUITY TEST =====
void runXlrContinuityTest() {
  XlrContResults r;

  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  // Ensure K5/K6 LOW = continuity mode
  resetCircuit();
  delay(RELAY_SETTLE_MS);

  // Pin mapping arrays for compact loop
  const int outPins[] = {XLR_CONT_OUT_PIN1, XLR_CONT_OUT_PIN2, XLR_CONT_OUT_PIN3};
  const int inPins[]  = {XLR_CONT_IN_PIN1,  XLR_CONT_IN_PIN2,  XLR_CONT_IN_PIN3};

  // Drive each pin and read all three
  for (int d = 0; d < 3; d++) {
    digitalWrite(outPins[d], HIGH);
    delay(SIGNAL_SETTLE_MS);
    for (int s = 0; s < 3; s++) {
      r.p[d][s] = digitalRead(inPins[s]) == HIGH;
    }
    digitalWrite(outPins[d], LOW);
    delay(RELAY_SETTLE_MS);
  }

  resetCircuit();

  // PASS: each pin connects only to itself (identity matrix)
  r.overallPass = true;
  for (int d = 0; d < 3; d++) {
    for (int s = 0; s < 3; s++) {
      if (d == s && !r.p[d][s]) r.overallPass = false;  // should be connected
      if (d != s && r.p[d][s])  r.overallPass = false;  // should NOT be connected
    }
  }

  // LED
  if (r.overallPass) {
    setResultLED(PASS_LED);
  } else {
    // Check if it's a wiring error vs open
    bool anyConnection = false;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) anyConnection = true;
    setResultLED(anyConnection ? ERROR_LED : FAIL_LED);
  }

  // Send result
  // Format: XLRCONT:PASS:P11:1:P12:0:P13:0:P21:0:P22:1:P23:0:P31:0:P32:0:P33:1[:REASON:xxx]
  String response = "XLRCONT:";
  response += r.overallPass ? "PASS" : "FAIL";
  for (int d = 0; d < 3; d++) {
    for (int s = 0; s < 3; s++) {
      response += ":P" + String(d + 1) + String(s + 1) + ":" + String(r.p[d][s] ? 1 : 0);
    }
  }

  // Failure reason
  if (!r.overallPass) {
    response += ":REASON:";
    // Check for no cable (nothing connected)
    bool allOpen = true;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) allOpen = false;
    if (allOpen) {
      response += "NO_CABLE";
    } else {
      // Build list of issues
      String issues = "";
      for (int i = 0; i < 3; i++) {
        if (!r.p[i][i]) {
          if (issues.length() > 0) issues += ",";
          issues += "P" + String(i + 1) + "_OPEN";
        }
      }
      for (int d = 0; d < 3; d++) {
        for (int s = 0; s < 3; s++) {
          if (d != s && r.p[d][s]) {
            if (issues.length() > 0) issues += ",";
            issues += "P" + String(d + 1) + "_P" + String(s + 1) + "_SHORT";
          }
        }
      }
      response += issues.length() > 0 ? issues : "UNKNOWN";
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
  digitalWrite(K5_RELAY, LOW);
  digitalWrite(K6_RELAY, LOW);

  // All test outputs off
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);

}

// ===== CALIBRATION =====
// Calibrate with a known-good short cable (or direct short).
// Establishes baseline ADC that includes Vce_sat + parasitic resistance.
// Cable resistance is then measured relative to this baseline.
void runCalibration() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  Serial.println("CAL:MEASURING...");

  // Configure for TS resistance test mode (calibrate with TS cable)
  digitalWrite(K1_K2_RELAY, LOW);    // Short far end + res path
  digitalWrite(K3_RELAY, LOW);       // Route resistance circuit to TS
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
  int measuredADC = adcSum / NUM_SAMPLES;

  // Disable test current
  digitalWrite(RES_TEST_OUT, LOW);
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

// ===== XLR CALIBRATION =====
void runXlrCalibration() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  Serial.println("XLRCAL:MEASURING...");

  // Configure for XLR resistance path (use pin 2)
  digitalWrite(K5_RELAY, HIGH);      // Pin 2 to resistance mode
  digitalWrite(K6_RELAY, HIGH);      // Pin 3 to resistance mode (return path)
  digitalWrite(K3_RELAY, HIGH);      // Route resistance circuit to XLR
  digitalWrite(K4_RELAY, LOW);       // Select Pin 2
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
  int measuredADC = adcSum / NUM_SAMPLES;

  // Disable test current
  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  // Reject if reading is too high (no cable or bad connection)
  if (measuredADC > 600) {
    setResultLED(FAIL_LED);
    Serial.println("XLRCAL:FAIL:ADC:" + String(measuredADC) + ":NO_CABLE");
    return;
  }

  xlrCalibrationADC = measuredADC;
  isXlrCalibrated = true;

  setResultLED(PASS_LED);
  Serial.println("XLRCAL:OK:ADC:" + String(xlrCalibrationADC));
}

// ===== RESISTANCE MEASUREMENT HELPER =====
// Takes a resistance reading on the shared circuit (A0).
// Returns averaged ADC value from NUM_SAMPLES readings.
int readResistanceADC() {
  long adcSum = 0;
  const int NUM_SAMPLES = 20;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(5);
  }
  return adcSum / NUM_SAMPLES;
}

// Calculate cable resistance from ADC reading relative to calibration
float calcCableResistance(int adcValue) {
  if (!isCalibrated) return 0.0;

  float senseVoltage = (adcValue / 1023.0) * SUPPLY_VOLTAGE;
  float calVoltage = (calibrationADC / 1023.0) * SUPPLY_VOLTAGE;
  float calCurrent = (SUPPLY_VOLTAGE - calVoltage) / RES_SENSE_OHM;
  if (calCurrent <= 0.001) return 0.0;

  float cableResistance = (senseVoltage - calVoltage) / calCurrent;
  if (cableResistance < 0) cableResistance = 0;
  return cableResistance;
}

// Format and send resistance result for a single reading
void sendResResult(const char* prefix, int adcValue) {
  bool pass = adcValue <= RES_PASS_THRESHOLD;
  float cableResistance = calcCableResistance(adcValue);

  String response = String(prefix);
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

// ===== TS RESISTANCE TEST =====
void runResistanceTest() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  // Configure for TS resistance test
  // K1+K2 LOW = short far end + res path
  // K3 LOW = route resistance circuit to TS
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  delay(RELAY_SETTLE_MS);

  // Enable current through PN2222A
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  int adcValue = readResistanceADC();

  // Disable test current
  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  // Update LED
  bool pass = adcValue <= RES_PASS_THRESHOLD;
  setResultLED(pass ? PASS_LED : FAIL_LED);

  sendResResult("RES:", adcValue);
}

// ===== XLR RESISTANCE TEST =====
// Tests pin 2 and pin 3 sequentially through the shared resistance circuit.
// K3 HIGH = route to XLR, K4 selects pin (LOW = pin 2, HIGH = pin 3)
void runXlrResistanceTest() {
  setResultLED();
  digitalWrite(STATUS_LED, HIGH);

  // Configure for XLR resistance test
  // K5 HIGH, K6 HIGH = switch pin 2 and pin 3 to resistance mode (into K4)
  // K3 HIGH = route resistance circuit to XLR
  digitalWrite(K5_RELAY, HIGH);
  digitalWrite(K6_RELAY, HIGH);
  digitalWrite(K3_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);

  // --- Test Pin 2 ---
  digitalWrite(K4_RELAY, LOW);       // K4 LOW = Pin 2
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  int adcPin2 = readResistanceADC();

  digitalWrite(RES_TEST_OUT, LOW);
  delay(RELAY_SETTLE_MS);

  // --- Test Pin 3 ---
  digitalWrite(K4_RELAY, HIGH);      // K4 HIGH = Pin 3
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  int adcPin3 = readResistanceADC();

  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  // Evaluate: both pins must pass
  bool pin2Pass = adcPin2 <= RES_PASS_THRESHOLD;
  bool pin3Pass = adcPin3 <= RES_PASS_THRESHOLD;
  bool overallPass = pin2Pass && pin3Pass;

  setResultLED(overallPass ? PASS_LED : FAIL_LED);

  // Send combined result using XLR calibration
  String response = "XLRRES:";
  response += overallPass ? "PASS" : "FAIL";
  response += ":P2ADC:" + String(adcPin2);
  response += ":P3ADC:" + String(adcPin3);
  if (isXlrCalibrated) {
    float calVoltage = (xlrCalibrationADC / 1023.0) * SUPPLY_VOLTAGE;
    float calCurrent = (SUPPLY_VOLTAGE - calVoltage) / RES_SENSE_OHM;
    float res2 = 0.0, res3 = 0.0;
    if (calCurrent > 0.001) {
      float v2 = (adcPin2 / 1023.0) * SUPPLY_VOLTAGE;
      float v3 = (adcPin3 / 1023.0) * SUPPLY_VOLTAGE;
      res2 = (v2 - calVoltage) / calCurrent;
      res3 = (v3 - calVoltage) / calCurrent;
      if (res2 < 0) res2 = 0;
      if (res3 < 0) res3 = 0;
    }
    response += ":CAL:" + String(xlrCalibrationADC);
    response += ":P2MOHM:" + String((int)(res2 * 1000));
    response += ":P2OHM:" + String(res2, 3);
    response += ":P3MOHM:" + String((int)(res3 * 1000));
    response += ":P3OHM:" + String(res3, 3);
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

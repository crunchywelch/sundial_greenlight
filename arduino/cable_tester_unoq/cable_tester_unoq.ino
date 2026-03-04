/*
 * Greenlight TS/XLR Cable Tester - Arduino UNO Q (Renesas RA4M1)
 *
 * Forked from Mega 2560 version. Key differences:
 *   - 3.3V GPIO logic (5V tolerant inputs except A0/A1)
 *   - 14-bit ADC (0-16383) vs Mega's 10-bit (0-1023)
 *   - 20 usable I/O pins (vs Mega's 70)
 *   - Relay coils driven via PN2222A transistors from 5V rail
 *     (3.3V GPIO -> 1k base resistor -> PN2222A -> relay coil -> +5V)
 *   - Resistance sense circuit powered from 3.3V (A0 not 5V tolerant)
 *   - Display: onboard 8x13 LED matrix (PE0-7 rows, PG0-12 cols)
 *     Uses Arduino_LED_Matrix library — zero GPIO cost
 *
 * Commands:
 *   CONT     - Run TS continuity/polarity test, returns RESULT:...
 *   RES      - Run TS resistance test, returns RES:...
 *   XRES     - Run XLR resistance test (pin 2 + pin 3), returns XRES:...
 *   CAL      - Calibrate TS resistance (use short cable)
 *   XSHELL   - Run XLR shell bond test, returns XSHELL:...
 *   XCAL     - Calibrate XLR resistance (use short cable)
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *
 * Relay Configuration (all via PN2222A drivers, coils on 5V rail):
 *   K1+K2 (D7)     - Tied together. TS test mode. LOW = short far end + res path, HIGH = continuity
 *   K3 (D8)        - Resistance circuit. LOW = TS, HIGH = XLR
 *   K4 (D9)        - XLR resistance pin select. LOW = Pin 2, HIGH = Pin 3
 *   K5 (D10)       - XLR Pin 2 mode. LOW = continuity, HIGH = resistance (into K4)
 *   K6 (D11)       - XLR Pin 3 mode. LOW = continuity, HIGH = resistance (into K4)
 *
 * Pin Configuration:
 *   D2     - TS continuity signal, SLEEVE
 *   D3     - TS continuity signal, TIP
 *   D4     - TS continuity sense, SLEEVE
 *   D5     - TS continuity sense, TIP
 *   D6     - RES_TEST_OUT (PN2222A base drive via 330R, shared TS/XLR)
 *   D7     - K1_K2_DRIVE (via PN2222A)
 *   D8     - K3_DRIVE (via PN2222A)
 *   D9     - K4_DRIVE (via PN2222A)
 *   D10    - K5_DRIVE (via PN2222A)
 *   D11    - K6_DRIVE (via PN2222A)
 *   D12    - XLR_CONT_OUT_PIN1 (drive)
 *   D13    - XLR_CONT_OUT_PIN2 (drive)
 *   A1/D15 - XLR_CONT_OUT_PIN3 (drive)
 *   A2/D16 - XLR_CONT_OUT_SHELL (drive, near side)
 *   A3/D17 - XLR_CONT_IN_PIN1 (read)
 *   A4/D18 - XLR_CONT_IN_PIN2 (read)
 *   A5/D19 - XLR_CONT_IN_PIN3 (read)
 *   D20    - XLR_CONT_IN_SHELL (read, far side)
 *   D21    - (spare)
 *   A0/D14 - RES_SENSE (analog input, 3.3V circuit only!)
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
#define RES_SENSE            A0   // Analog input: resistance measurement (3.3V max!)

// --- Relay Drives (all via PN2222A, GPIO -> 1k -> base) ---
#define K1_K2_RELAY          7   // TS test mode: LOW = short far end + res path, HIGH = continuity
#define K3_RELAY             8   // Resistance circuit: LOW = TS, HIGH = XLR
#define K4_RELAY             9   // XLR resistance pin select: LOW = Pin 2, HIGH = Pin 3
#define K5_RELAY            10   // XLR Pin 2: LOW = continuity, HIGH = resistance (into K4)
#define K6_RELAY            11   // XLR Pin 3: LOW = continuity, HIGH = resistance (into K4)

// --- XLR Cable Testing ---
// Continuity signals (paired drive/read with pulldown resistors)
#define XLR_CONT_OUT_PIN1   12   // Continuity signal output to XLR Pin 1
#define XLR_CONT_IN_PIN1    17   // Continuity sense input from XLR Pin 1 (A3)
#define XLR_CONT_OUT_PIN2   13   // Continuity signal output to XLR Pin 2 (K5)
#define XLR_CONT_IN_PIN2    18   // Continuity sense input from XLR Pin 2 (K5) (A4)
#define XLR_CONT_OUT_PIN3   15   // Continuity signal output to XLR Pin 3 (K6) (A1)
#define XLR_CONT_IN_PIN3    19   // Continuity sense input from XLR Pin 3 (K6) (A5)
#define XLR_CONT_OUT_SHELL  16   // Continuity signal output to XLR shell (near side) (A2)
#define XLR_CONT_IN_SHELL   20   // Continuity sense input from XLR shell (far side) (SDA)

// --- Display: 8x13 LED Matrix ---
// Uses Arduino_LED_Matrix library (same as UNO R4 WiFi).
// Driven by internal MCU pins (PE0-7 rows, PG0-12 cols) — no GPIO cost.
// Frames are 8 rows x 12 cols packed into 3x uint32_t.
#include <Arduino_LED_Matrix.h>
ArduinoLEDMatrix matrix;

// ===== CONFIGURATION =====
const char* TESTER_ID = "UNOQ_TESTER_1";
const int BAUD_RATE = 9600;
const int RELAY_SETTLE_MS = 10;
const int SIGNAL_SETTLE_MS = 50;

// Resistance test config
// High-side sense topology: 3.3V -> R_sense(20R) -> cable -> relay -> collector, emitter -> GND
// A0 reads junction of R_sense and cable. Lower ADC = more current = lower cable resistance.
// NOTE: UNO Q RA4M1 has 14-bit ADC (0-16383). All thresholds scaled accordingly.
const int ADC_MAX = 16383;                       // 14-bit ADC max
const int RES_PASS_THRESHOLD = 1966;             // ~120/1023 * 16383 (uncalibrated fallback)
const float MAX_CABLE_RESISTANCE = 1.0;          // Max cable resistance in ohms to pass
const float RES_SENSE_OHM = 20.0;               // High-side sense resistor (20R)
const float SUPPLY_VOLTAGE = 3.3;               // 3.3V supply for resistance circuit
const float VCE_SAT = 0.3;                      // PN2222A saturation voltage estimate
// Base: D6 -> 330R -> base. Emitter grounded.
// At 3.3V: Ib = (3.3 - 0.7) / 330 = ~7.9mA — sufficient for relay current loads.

// Calibration rejection threshold (scaled for 14-bit ADC, 3.3V supply)
const int CAL_REJECT_THRESHOLD = 9830;           // ~600/1023 * 16383

// Calibration (stored in RAM, lost on reset - could use EEPROM)
int calibrationADC = 0;              // TS ADC reading with zero-ohm reference
bool isCalibrated = false;
int xlrCalibrationADC_P2 = 0;        // XLR Pin 2 ADC reading with zero-ohm reference
int xlrCalibrationADC_P3 = 0;        // XLR Pin 3 ADC reading with zero-ohm reference
bool isXlrCalibrated = false;

// Forward declarations
void showResult(int result = 0);

// Display result constants
#define SHOW_OFF    0
#define SHOW_PASS   1   // Checkmark
#define SHOW_FAIL   2   // X
#define SHOW_ERROR  3   // ! (wiring fault)
#define SHOW_READY  4   // Heartbeat dot

// LED matrix frames (8 rows x 12 cols, packed as 3x uint32_t)
// Each uint32_t holds ~32 bits of the 96-bit frame (8*12=96)
const uint32_t FRAME_OFF[] = {0, 0, 0};

const uint32_t FRAME_PASS[] = {  // Checkmark
  0x00100180,
  0x30060030,
  0x00C00000
};

const uint32_t FRAME_FAIL[] = {  // X
  0x81042108,
  0x40081042,
  0x10810000
};

const uint32_t FRAME_ERROR[] = { // !
  0x0C030030,
  0x00C00000,
  0x0C000000
};

const uint32_t FRAME_READY[] = { // Center dot
  0x00000000,
  0x30060000,
  0x00000000
};

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
  bool shorted;
  bool openTip;
  bool openSleeve;
};

// ===== XLR TEST RESULTS =====
struct XlrContResults {
  // 3x3 continuity matrix: [drive][sense]
  // Index 0=pin1, 1=pin2, 2=pin3
  bool p[3][3];
  bool overallPass;
};

struct XlrShellResults {
  bool nearShellBond;   // drive shell, sense pin1
  bool farShellBond;    // drive pin1, sense shell
  bool shellToShell;    // drive shell, sense shell
  bool shellToP2;       // shell shorted to pin2
  bool shellToP3;       // shell shorted to pin3
  bool overallPass;
};

// ===== SETUP =====
void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) { ; }  // Wait for USB serial

  // Set ADC resolution to 14-bit (UNO R4 / UNO Q default is 10-bit for compatibility)
  analogReadResolution(14);

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
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);

  // --- XLR continuity inputs ---
  pinMode(XLR_CONT_IN_PIN1, INPUT);
  pinMode(XLR_CONT_IN_PIN2, INPUT);
  pinMode(XLR_CONT_IN_PIN3, INPUT);
  pinMode(XLR_CONT_IN_SHELL, INPUT);

  // --- LED Matrix ---
  matrix.begin();

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
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);

  // Display off
  showResult(SHOW_OFF);

  // Run self-test
  if (selfTest()) {
    systemReady = true;
    Serial.println("READY:" + String(TESTER_ID));
  } else {
    systemReady = false;
    showResult(SHOW_ERROR);
    Serial.println("ERROR:SELF_TEST_FAILED");
  }
}

// ===== MAIN LOOP =====
void loop() {
  // Blink center dot when idle (status heartbeat)
  static unsigned long lastBlink = 0;
  static bool blinkState = false;
  if (systemReady && millis() - lastBlink > 1000) {
    blinkState = !blinkState;
    matrix.loadFrame(blinkState ? FRAME_READY : FRAME_OFF);
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

  } else if (cmd == "XCONT") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runXlrContinuityTest();

  } else if (cmd == "XSHELL") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runXlrShellTest();

  } else if (cmd == "RES") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runResistanceTest();

  } else if (cmd == "XRES") {
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

  } else if (cmd == "XCAL") {
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
    Serial.println("DEBUG:LED_TEST_START");
    showResult(SHOW_OFF);
    Serial.println("RED (fail)");
    showResult(SHOW_FAIL);
    delay(500);
    showResult(SHOW_OFF);
    Serial.println("GREEN (pass)");
    showResult(SHOW_PASS);
    delay(500);
    showResult(SHOW_OFF);
    Serial.println("BLUE (error)");
    showResult(SHOW_ERROR);
    delay(500);
    showResult(SHOW_OFF);
    Serial.println("DEBUG:LED_TEST_DONE");

  // --- TS Relay Toggles ---
  } else if (cmd == "K12") {
    bool state = !digitalRead(K1_K2_RELAY);
    digitalWrite(K1_K2_RELAY, state);
    Serial.println("DEBUG:K1+K2(D7):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K3") {
    bool state = !digitalRead(K3_RELAY);
    digitalWrite(K3_RELAY, state);
    Serial.println("DEBUG:K3(D8):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K4") {
    bool state = !digitalRead(K4_RELAY);
    digitalWrite(K4_RELAY, state);
    Serial.println("DEBUG:K4(D9):" + String(state ? "HIGH" : "LOW"));

  // --- XLR Relay Toggles ---
  } else if (cmd == "K5") {
    bool state = !digitalRead(K5_RELAY);
    digitalWrite(K5_RELAY, state);
    Serial.println("DEBUG:K5(D10):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "K6") {
    bool state = !digitalRead(K6_RELAY);
    digitalWrite(K6_RELAY, state);
    Serial.println("DEBUG:K6(D11):" + String(state ? "HIGH" : "LOW"));

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
    Serial.println("DEBUG:XLR_CONT_OUT_PIN1(D12):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR2") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN2);
    digitalWrite(XLR_CONT_OUT_PIN2, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN2(D13):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLR3") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN3);
    digitalWrite(XLR_CONT_OUT_PIN3, state);
    Serial.println("DEBUG:XLR_CONT_OUT_PIN3(D15/A1):" + String(state ? "HIGH" : "LOW"));

  } else if (cmd == "XLRS") {
    bool state = !digitalRead(XLR_CONT_OUT_SHELL);
    digitalWrite(XLR_CONT_OUT_SHELL, state);
    Serial.println("DEBUG:XLR_CONT_OUT_SHELL(D16/A2):" + String(state ? "HIGH" : "LOW"));

  // --- Read Sensors ---
  } else if (cmd == "READ") {
    Serial.println("=== TS SENSE ===");
    Serial.println("  TIP(D5):    " + String(digitalRead(TS_CONT_IN_TIP)));
    Serial.println("  SLEEVE(D4): " + String(digitalRead(TS_CONT_IN_SLEEVE)));
    Serial.println("=== RES SENSE (shared, 14-bit) ===");
    Serial.println("  RES(A0):    " + String(analogRead(RES_SENSE)));
    Serial.println("=== XLR SENSE ===");
    Serial.println("  PIN1(D17/A3):  " + String(digitalRead(XLR_CONT_IN_PIN1)));
    Serial.println("  PIN2(D18/A4):  " + String(digitalRead(XLR_CONT_IN_PIN2)));
    Serial.println("  PIN3(D19/A5):  " + String(digitalRead(XLR_CONT_IN_PIN3)));
    Serial.println("  SHELL(D20):    " + String(digitalRead(XLR_CONT_IN_SHELL)));
  } else if (cmd == "PINS") {
    Serial.println("=== RELAYS (via PN2222A) ===");
    Serial.println("  D7  K1+K2:     " + String(digitalRead(K1_K2_RELAY) ? "HIGH" : "LOW") + " (TS far end)");
    Serial.println("  D8  K3:        " + String(digitalRead(K3_RELAY) ? "HIGH" : "LOW") + " (res: L=TS H=XLR)");
    Serial.println("  D9  K4:        " + String(digitalRead(K4_RELAY) ? "HIGH" : "LOW") + " (XLR: L=P2 H=P3)");
    Serial.println("  D10 K5:        " + String(digitalRead(K5_RELAY) ? "HIGH" : "LOW") + " (XLR P2: L=cont H=res)");
    Serial.println("  D11 K6:        " + String(digitalRead(K6_RELAY) ? "HIGH" : "LOW") + " (XLR P3: L=cont H=res)");
    Serial.println("=== TS OUTPUTS ===");
    Serial.println("  D2  SLEEVE:  " + String(digitalRead(TS_CONT_OUT_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D3  TIP:     " + String(digitalRead(TS_CONT_OUT_TIP) ? "HIGH" : "LOW"));
    Serial.println("=== TS INPUTS ===");
    Serial.println("  D4  SLEEVE:  " + String(digitalRead(TS_CONT_IN_SLEEVE) ? "HIGH" : "LOW"));
    Serial.println("  D5  TIP:     " + String(digitalRead(TS_CONT_IN_TIP) ? "HIGH" : "LOW"));
    Serial.println("=== RESISTANCE (shared) ===");
    Serial.println("  D6  DRIVE:   " + String(digitalRead(RES_TEST_OUT) ? "HIGH" : "LOW"));
    Serial.println("  A0  SENSE:   " + String(analogRead(RES_SENSE)) + " (14-bit, 3.3V ref)");
    Serial.println("=== XLR CONTINUITY ===");
    Serial.println("  D12    PIN1 OUT:  " + String(digitalRead(XLR_CONT_OUT_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D17/A3 PIN1 IN:   " + String(digitalRead(XLR_CONT_IN_PIN1) ? "HIGH" : "LOW"));
    Serial.println("  D13    PIN2 OUT:  " + String(digitalRead(XLR_CONT_OUT_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D18/A4 PIN2 IN:   " + String(digitalRead(XLR_CONT_IN_PIN2) ? "HIGH" : "LOW"));
    Serial.println("  D15/A1 PIN3 OUT:  " + String(digitalRead(XLR_CONT_OUT_PIN3) ? "HIGH" : "LOW"));
    Serial.println("  D19/A5 PIN3 IN:   " + String(digitalRead(XLR_CONT_IN_PIN3) ? "HIGH" : "LOW"));
    Serial.println("  D16/A2 SHELL OUT: " + String(digitalRead(XLR_CONT_OUT_SHELL) ? "HIGH" : "LOW"));
    Serial.println("  D20    SHELL IN:  " + String(digitalRead(XLR_CONT_IN_SHELL) ? "HIGH" : "LOW"));
    Serial.println("=== DISPLAY ===");
    Serial.println("  LED Matrix (8x13) active");

  } else if (cmd == "HELP") {
    Serial.println("=== COMMANDS ===");
    Serial.println("CONT    - Run TS continuity test");
    Serial.println("XCONT   - Run XLR continuity test (pins 1-3)");
    Serial.println("XSHELL  - Run XLR shell bond test");
    Serial.println("RES     - Run TS resistance test");
    Serial.println("XRES    - Run XLR resistance test (pin 2+3)");
    Serial.println("CAL     - Calibrate TS resistance (short cable)");
    Serial.println("XCAL    - Calibrate XLR resistance (short cable)");
    Serial.println("STATUS  - Get tester status");
    Serial.println("ID      - Get tester ID");
    Serial.println("RESET   - Reset circuit");
    Serial.println("--- DEBUG: RELAYS ---");
    Serial.println("K12     - Toggle K1+K2 (D7)");
    Serial.println("K3      - Toggle K3 (D8)");
    Serial.println("K4      - Toggle K4 (D9)");
    Serial.println("K5      - Toggle K5 (D10) XLR P2 cont/res");
    Serial.println("K6      - Toggle K6 (D11) XLR P3 cont/res");
    Serial.println("--- DEBUG: TS ---");
    Serial.println("TSTIP   - Toggle TS tip out (D3)");
    Serial.println("TSSLV   - Toggle TS sleeve out (D2)");
    Serial.println("TSRES   - Toggle resistance drive (D6)");
    Serial.println("--- DEBUG: XLR ---");
    Serial.println("XLR1    - Toggle XLR pin1 out (D12)");
    Serial.println("XLR2    - Toggle XLR pin2 out (D13)");
    Serial.println("XLR3    - Toggle XLR pin3 out (D15/A1)");
    Serial.println("XLRS    - Toggle XLR shell out (D16/A2)");
    Serial.println("--- DEBUG: XLR TESTS ---");
    Serial.println("XC      - Test XLR continuity (pins 1-3)");
    Serial.println("XS      - Test XLR shell bond");
    Serial.println("XR      - Test XLR resistance (pin 2+3)");
    Serial.println("--- DEBUG: READ ---");
    Serial.println("READ    - Read all sense pins");
    Serial.println("PINS    - Show all pin states");
    Serial.println("LED     - Cycle all LEDs");

  // ===== XLR DEBUG TESTS =====
  } else if (cmd == "XC") {
    runXlrContinuityTest();

  } else if (cmd == "XS") {
    runXlrShellTest();

  } else if (cmd == "XR") {
    runXlrResistanceTest();

  } else {
    Serial.println("ERROR:UNKNOWN_CMD:" + cmd);
  }
}

// ===== TEST FUNCTIONS =====
void runContinuityTest() {
  TestResults results;

  // Turn off result LEDs
  showResult(SHOW_OFF);

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

  // SHORT: tip and sleeve are shorted together
  results.shorted = results.tipToSleeve || results.sleeveToTip;

  // OPEN: no signal detected
  results.openTip = !results.tipToTip && !results.tipToSleeve;
  results.openSleeve = !results.sleeveToSleeve && !results.sleeveToTip;

  // Reset circuit
  resetCircuit();

  // Update LEDs
  if (results.overallPass) {
    showResult(SHOW_PASS);
  } else if (results.reversed || results.shorted) {
    // Wiring error (reversed polarity or short)
    showResult(SHOW_ERROR);
  } else {
    // Open connection
    showResult(SHOW_FAIL);
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
    } else if (r.shorted) {
      response += "SHORT";
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
// 3x3 matrix: pin1, pin2, pin3 only (no shell)
// Shell bond is tested separately via XSHELL command since some
// connectors have non-conductive coated shells.
void runXlrContinuityTest() {
  XlrContResults r;

  showResult(SHOW_OFF);

  // Ensure K5/K6 LOW = continuity mode
  resetCircuit();
  delay(RELAY_SETTLE_MS);

  // Pin mapping arrays: index 0=pin1, 1=pin2, 2=pin3
  const int outPins[] = {XLR_CONT_OUT_PIN1, XLR_CONT_OUT_PIN2, XLR_CONT_OUT_PIN3};
  const int inPins[]  = {XLR_CONT_IN_PIN1,  XLR_CONT_IN_PIN2,  XLR_CONT_IN_PIN3};

  // Shell drive must be high-Z during pin tests — if a cable has shell
  // bonded to pin1, shell output held LOW would fight the pin1 drive signal
  pinMode(XLR_CONT_OUT_SHELL, INPUT);

  // Drive each of 3 channels and read all three
  for (int d = 0; d < 3; d++) {
    // Set all drive pins to high-Z first to avoid fighting through cable bonds
    for (int i = 0; i < 3; i++) {
      pinMode(outPins[i], INPUT);
    }
    // Drive only the selected channel
    pinMode(outPins[d], OUTPUT);
    digitalWrite(outPins[d], HIGH);
    delay(SIGNAL_SETTLE_MS);
    for (int s = 0; s < 3; s++) {
      r.p[d][s] = digitalRead(inPins[s]) == HIGH;
    }
    digitalWrite(outPins[d], LOW);
    delay(RELAY_SETTLE_MS);
  }

  // Restore all drive pins to OUTPUT for resetCircuit()
  for (int i = 0; i < 3; i++) {
    pinMode(outPins[i], OUTPUT);
  }
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);

  resetCircuit();

  // === EVALUATE RESULTS ===
  r.overallPass = true;
  for (int d = 0; d < 3; d++) {
    for (int s = 0; s < 3; s++) {
      if (d == s && !r.p[d][s]) r.overallPass = false;  // should be connected
      if (d != s && r.p[d][s])  r.overallPass = false;  // should NOT be connected
    }
  }

  // LED
  if (r.overallPass) {
    showResult(SHOW_PASS);
  } else {
    bool anyConnection = false;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) anyConnection = true;
    showResult(anyConnection ? SHOW_ERROR : SHOW_FAIL);
  }

  // Send result
  String response = "XCONT:";
  response += r.overallPass ? "PASS" : "FAIL";
  for (int d = 0; d < 3; d++) {
    for (int s = 0; s < 3; s++) {
      response += ":P" + String(d + 1) + String(s + 1) + ":" + String(r.p[d][s] ? 1 : 0);
    }
  }

  // Failure reason
  if (!r.overallPass) {
    response += ":REASON:";
    bool allOpen = true;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) allOpen = false;
    if (allOpen) {
      response += "NO_CABLE";
    } else {
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

// ===== XLR SHELL BOND TEST =====
// Tests shell-to-pin1 bond at both cable ends.
// Only usable with uncoated/conductive connector shells.
// Test jacks must have shell UNBONDED from pin 1.
//
// Drives pin1 and shell separately, reads cross-connections:
//   drive pin1 -> sense shell = far end shell bond
//   drive shell -> sense pin1 = near end shell bond
void runXlrShellTest() {
  XlrShellResults r;

  showResult(SHOW_OFF);

  resetCircuit();
  delay(RELAY_SETTLE_MS);

  // All 4 drive/sense pins involved
  const int outPins[] = {XLR_CONT_OUT_PIN1, XLR_CONT_OUT_PIN2, XLR_CONT_OUT_PIN3, XLR_CONT_OUT_SHELL};
  const int inPins[]  = {XLR_CONT_IN_PIN1,  XLR_CONT_IN_PIN2,  XLR_CONT_IN_PIN3,  XLR_CONT_IN_SHELL};

  // --- Drive pin1, read shell (far end bond) ---
  for (int i = 0; i < 4; i++) pinMode(outPins[i], INPUT);
  pinMode(XLR_CONT_OUT_PIN1, OUTPUT);
  digitalWrite(XLR_CONT_OUT_PIN1, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.farShellBond = digitalRead(XLR_CONT_IN_SHELL) == HIGH;
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  delay(RELAY_SETTLE_MS);

  // --- Drive shell, read pin1/pin2/pin3/shell (near end bond + shorts) ---
  for (int i = 0; i < 4; i++) pinMode(outPins[i], INPUT);
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);
  digitalWrite(XLR_CONT_OUT_SHELL, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.nearShellBond = digitalRead(XLR_CONT_IN_PIN1) == HIGH;
  r.shellToP2 = digitalRead(XLR_CONT_IN_PIN2) == HIGH;
  r.shellToP3 = digitalRead(XLR_CONT_IN_PIN3) == HIGH;
  r.shellToShell = digitalRead(XLR_CONT_IN_SHELL) == HIGH;
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);

  // Restore drive pins to OUTPUT
  for (int i = 0; i < 4; i++) {
    pinMode(outPins[i], OUTPUT);
    digitalWrite(outPins[i], LOW);
  }
  resetCircuit();

  // === EVALUATE ===
  r.overallPass = r.nearShellBond && r.farShellBond && !r.shellToP2 && !r.shellToP3;

  showResult(r.overallPass ? SHOW_PASS : (r.nearShellBond || r.farShellBond ? SHOW_ERROR : SHOW_FAIL));

  // Send result
  String response = "XSHELL:";
  response += r.overallPass ? "PASS" : "FAIL";
  response += ":NEAR:" + String(r.nearShellBond ? 1 : 0);
  response += ":FAR:" + String(r.farShellBond ? 1 : 0);
  response += ":SS:" + String(r.shellToShell ? 1 : 0);

  if (!r.overallPass) {
    response += ":REASON:";
    String issues = "";
    if (!r.nearShellBond) issues += "NEAR_SHELL_OPEN";
    if (!r.farShellBond) {
      if (issues.length() > 0) issues += ",";
      issues += "FAR_SHELL_OPEN";
    }
    if (r.shellToP2) {
      if (issues.length() > 0) issues += ",";
      issues += "SHELL_P2_SHORT";
    }
    if (r.shellToP3) {
      if (issues.length() > 0) issues += ",";
      issues += "SHELL_P3_SHORT";
    }
    response += issues.length() > 0 ? issues : "UNKNOWN";
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
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);
}

// ===== CALIBRATION =====
// Calibrate with a known-good short cable (or direct short).
// Establishes baseline ADC that includes Vce_sat + parasitic resistance.
// Cable resistance is then measured relative to this baseline.
void runCalibration() {
  showResult(SHOW_OFF);

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
  if (measuredADC > CAL_REJECT_THRESHOLD) {
    showResult(SHOW_FAIL);
    Serial.println("CAL:FAIL:ADC:" + String(measuredADC) + ":NO_CABLE");
    return;
  }

  calibrationADC = measuredADC;
  isCalibrated = true;

  showResult(SHOW_PASS);
  Serial.println("CAL:OK:ADC:" + String(calibrationADC));
}

// ===== XLR CALIBRATION =====
// Calibrates both pin 2 and pin 3 paths separately since relay contact
// resistance can differ between K4 LOW (pin 2) and K4 HIGH (pin 3).
void runXlrCalibration() {
  showResult(SHOW_OFF);

  Serial.println("XCAL:MEASURING...");

  const int NUM_SAMPLES = 50;

  // Common setup: both pins to resistance mode, route to XLR
  digitalWrite(K5_RELAY, HIGH);      // Pin 2 to resistance mode
  digitalWrite(K6_RELAY, HIGH);      // Pin 3 to resistance mode
  digitalWrite(K3_RELAY, HIGH);      // Route resistance circuit to XLR

  // --- Calibrate Pin 2 ---
  digitalWrite(K4_RELAY, LOW);       // Select Pin 2
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  long adcSum = 0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(10);
  }
  int measuredP2 = adcSum / NUM_SAMPLES;

  digitalWrite(RES_TEST_OUT, LOW);
  delay(RELAY_SETTLE_MS);

  // --- Calibrate Pin 3 ---
  digitalWrite(K4_RELAY, HIGH);      // Select Pin 3
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  adcSum = 0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(10);
  }
  int measuredP3 = adcSum / NUM_SAMPLES;

  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  // Reject if either reading is too high (no cable or bad connection)
  if (measuredP2 > CAL_REJECT_THRESHOLD || measuredP3 > CAL_REJECT_THRESHOLD) {
    showResult(SHOW_FAIL);
    Serial.println("XCAL:FAIL:P2ADC:" + String(measuredP2) + ":P3ADC:" + String(measuredP3) + ":NO_CABLE");
    return;
  }

  xlrCalibrationADC_P2 = measuredP2;
  xlrCalibrationADC_P3 = measuredP3;
  isXlrCalibrated = true;

  showResult(SHOW_PASS);
  Serial.println("XCAL:OK:P2ADC:" + String(xlrCalibrationADC_P2) + ":P3ADC:" + String(xlrCalibrationADC_P3));
}

// ===== RESISTANCE MEASUREMENT HELPER =====
// Takes a resistance reading on the shared circuit (A0).
// Returns averaged ADC value from NUM_SAMPLES readings (14-bit).
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
// Uses 14-bit ADC (0-16383) and 3.3V reference
float calcCableResistance(int adcValue, int calADC) {
  float senseVoltage = (adcValue / (float)ADC_MAX) * SUPPLY_VOLTAGE;
  float calVoltage = (calADC / (float)ADC_MAX) * SUPPLY_VOLTAGE;
  float calCurrent = (SUPPLY_VOLTAGE - calVoltage) / RES_SENSE_OHM;
  if (calCurrent <= 0.001) return 0.0;

  float cableResistance = (senseVoltage - calVoltage) / calCurrent;
  if (cableResistance < 0) cableResistance = 0;
  return cableResistance;
}

// Check pass/fail: use calibrated resistance if available, else absolute ADC
bool resPassCheck(int adcValue, bool calibrated, int calADC) {
  if (calibrated) {
    return calcCableResistance(adcValue, calADC) <= MAX_CABLE_RESISTANCE;
  }
  return adcValue <= RES_PASS_THRESHOLD;
}

// Format and send resistance result for a single reading
void sendResResult(const char* prefix, int adcValue) {
  bool pass = resPassCheck(adcValue, isCalibrated, calibrationADC);
  float cableResistance = isCalibrated ? calcCableResistance(adcValue, calibrationADC) : 0.0;

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
  showResult(SHOW_OFF);

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
  bool pass = resPassCheck(adcValue, isCalibrated, calibrationADC);
  showResult(pass ? SHOW_PASS : SHOW_FAIL);

  sendResResult("RES:", adcValue);
}

// ===== XLR RESISTANCE TEST =====
// Tests pin 2 and pin 3 sequentially through the shared resistance circuit.
// K3 HIGH = route to XLR, K4 selects pin (LOW = pin 2, HIGH = pin 3)
void runXlrResistanceTest() {
  showResult(SHOW_OFF);

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

  // Evaluate: both pins must pass (each against its own calibration)
  bool pin2Pass = resPassCheck(adcPin2, isXlrCalibrated, xlrCalibrationADC_P2);
  bool pin3Pass = resPassCheck(adcPin3, isXlrCalibrated, xlrCalibrationADC_P3);
  bool overallPass = pin2Pass && pin3Pass;

  showResult(overallPass ? SHOW_PASS : SHOW_FAIL);

  // Send combined result using per-pin XLR calibration
  float res2 = 0.0, res3 = 0.0;
  if (isXlrCalibrated) {
    res2 = calcCableResistance(adcPin2, xlrCalibrationADC_P2);
    res3 = calcCableResistance(adcPin3, xlrCalibrationADC_P3);
  }

  String response = "XRES:";
  response += overallPass ? "PASS" : "FAIL";
  response += ":P2ADC:" + String(adcPin2);
  response += ":P3ADC:" + String(adcPin3);
  if (isXlrCalibrated) {
    response += ":P2CAL:" + String(xlrCalibrationADC_P2);
    response += ":P3CAL:" + String(xlrCalibrationADC_P3);
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

// Display result on LED matrix
void showResult(int result) {
  switch (result) {
    case SHOW_PASS:  matrix.loadFrame(FRAME_PASS);  break;
    case SHOW_FAIL:  matrix.loadFrame(FRAME_FAIL);  break;
    case SHOW_ERROR: matrix.loadFrame(FRAME_ERROR); break;
    case SHOW_READY: matrix.loadFrame(FRAME_READY); break;
    default:         matrix.loadFrame(FRAME_OFF);   break;
  }
}

bool selfTest() {
  // Cycle through display patterns
  int patterns[] = {SHOW_FAIL, SHOW_PASS, SHOW_ERROR};
  for (int i = 0; i < 3; i++) {
    showResult(patterns[i]);
    delay(300);
    showResult(SHOW_OFF);
    delay(100);
  }

  // Could add more hardware checks here
  return true;
}

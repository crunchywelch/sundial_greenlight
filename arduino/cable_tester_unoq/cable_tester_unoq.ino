/*
 * Greenlight TS/XLR Cable Tester - Arduino UNO Q
 *
 * Communicates with MPU via Router Bridge (msgpack-rpc).
 * Exposes a single run_command(cmd) function that accepts text commands
 * and returns text responses — same protocol as the Mega 2560 serial version.
 *
 * Key differences from Mega 2560:
 *   - 3.3V GPIO logic (5V tolerant inputs except A0/A1)
 *   - 14-bit ADC (0-16383) vs Mega's 10-bit (0-1023)
 *   - 20 usable I/O pins (vs Mega's 70)
 *   - Relay coils driven via PN2222A transistors from 5V rail
 *   - Resistance sense circuit powered from 3.3V (A0 not 5V tolerant)
 *   - Display: onboard 8x13 LED matrix (zero GPIO cost)
 *   - Communication: Router Bridge RPC (not USB serial)
 *
 * Commands (via run_command):
 *   CONT     - Run TS continuity/polarity test, returns RESULT:...
 *   RES      - Run TS resistance test, returns RES:...
 *   XRES     - Run XLR resistance test (pin 2 + pin 3), returns XRES:...
 *   CAL      - Calibrate TS resistance (use short cable)
 *   XSHELL   - Run XLR shell bond test, returns XSHELL:...
 *   XCAL     - Calibrate XLR resistance (use short cable)
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *   RESET    - Reset circuit, returns OK:RESET
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

#include "Arduino_RouterBridge.h"
#include <Arduino_LED_Matrix.h>

// ===== PIN DEFINITIONS =====

// --- TS Cable Testing ---
#define TS_CONT_OUT_SLEEVE   2
#define TS_CONT_OUT_TIP      3
#define TS_CONT_IN_SLEEVE    4
#define TS_CONT_IN_TIP       5

// --- Resistance (shared TS/XLR via K3/K4 relay switching) ---
#define RES_TEST_OUT         6
#define RES_SENSE            A0

// --- Relay Drives (all via PN2222A, GPIO -> 1k -> base) ---
#define K1_K2_RELAY          7
#define K3_RELAY             8
#define K4_RELAY             9
#define K5_RELAY            10
#define K6_RELAY            11

// --- XLR Cable Testing ---
#define XLR_CONT_OUT_PIN1   12
#define XLR_CONT_IN_PIN1    17   // A3
#define XLR_CONT_OUT_PIN2   13
#define XLR_CONT_IN_PIN2    18   // A4
#define XLR_CONT_OUT_PIN3   15   // A1
#define XLR_CONT_IN_PIN3    19   // A5
#define XLR_CONT_OUT_SHELL  16   // A2
#define XLR_CONT_IN_SHELL   20   // SDA

// ===== LED MATRIX =====
ArduinoLEDMatrix matrix;

#define SHOW_OFF    0
#define SHOW_PASS   1
#define SHOW_FAIL   2
#define SHOW_ERROR  3
#define SHOW_READY  4

const uint32_t FRAME_OFF[]   = {0, 0, 0};
const uint32_t FRAME_PASS[]  = {0x00100180, 0x30060030, 0x00C00000};  // Checkmark
const uint32_t FRAME_FAIL[]  = {0x81042108, 0x40081042, 0x10810000};  // X
const uint32_t FRAME_ERROR[] = {0x0C030030, 0x00C00000, 0x0C000000};  // !
const uint32_t FRAME_READY[] = {0x00000000, 0x30060000, 0x00000000};  // Center dot

// ===== CONFIGURATION =====
const char* TESTER_ID = "UNOQ_TESTER_1";
const int RELAY_SETTLE_MS = 10;
const int SIGNAL_SETTLE_MS = 50;

// Resistance test config (3.3V supply, 14-bit ADC)
const int ADC_MAX = 16383;
const int RES_PASS_THRESHOLD = 1966;        // ~120/1023 * 16383
const float MAX_CABLE_RESISTANCE = 1.0;
const float RES_SENSE_OHM = 20.0;
const float SUPPLY_VOLTAGE = 3.3;
const float VCE_SAT = 0.3;
const int CAL_REJECT_THRESHOLD = 9830;      // ~600/1023 * 16383

// Calibration state
int calibrationADC = 0;
bool isCalibrated = false;
int xlrCalibrationADC_P2 = 0;
int xlrCalibrationADC_P3 = 0;
bool isXlrCalibrated = false;

// ===== GLOBAL STATE =====
bool systemReady = false;

// ===== TEST RESULT STRUCTS =====
struct TestResults {
  bool tipToTip;
  bool tipToSleeve;
  bool sleeveToSleeve;
  bool sleeveToTip;
  bool overallPass;
  bool reversed;
  bool shorted;
  bool openTip;
  bool openSleeve;
};

struct XlrContResults {
  bool p[3][3];
  bool overallPass;
};

struct XlrShellResults {
  bool nearShellBond;
  bool farShellBond;
  bool shellToShell;
  bool shellToP2;
  bool shellToP3;
  bool overallPass;
};

// ===== FORWARD DECLARATIONS =====
void showResult(int result = 0);
void resetCircuit();
String handleCommand(String cmd);
String runContinuityTest();
String runXlrContinuityTest();
String runXlrShellTest();
String runResistanceTest();
String runXlrResistanceTest();
String runCalibration();
String runXlrCalibration();

// ===== BRIDGE COMMAND HANDLER =====
// Single entry point for all commands from the MPU.
// Accepts command string, returns response string.
String run_command(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  return handleCommand(cmd);
}

// ===== SETUP =====
void setup() {
  // Set ADC resolution to 14-bit
  analogReadResolution(14);

  // --- Relay outputs ---
  pinMode(K1_K2_RELAY, OUTPUT);
  pinMode(K3_RELAY, OUTPUT);
  pinMode(K4_RELAY, OUTPUT);
  pinMode(K5_RELAY, OUTPUT);
  pinMode(K6_RELAY, OUTPUT);

  // --- TS continuity ---
  pinMode(TS_CONT_OUT_SLEEVE, OUTPUT);
  pinMode(TS_CONT_OUT_TIP, OUTPUT);
  pinMode(TS_CONT_IN_SLEEVE, INPUT);
  pinMode(TS_CONT_IN_TIP, INPUT);

  // --- Resistance ---
  pinMode(RES_TEST_OUT, OUTPUT);

  // --- XLR continuity ---
  pinMode(XLR_CONT_OUT_PIN1, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN2, OUTPUT);
  pinMode(XLR_CONT_OUT_PIN3, OUTPUT);
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);
  pinMode(XLR_CONT_IN_PIN1, INPUT);
  pinMode(XLR_CONT_IN_PIN2, INPUT);
  pinMode(XLR_CONT_IN_PIN3, INPUT);
  pinMode(XLR_CONT_IN_SHELL, INPUT);

  // --- LED Matrix ---
  matrix.begin();

  // Initialize all outputs LOW
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(K5_RELAY, LOW);
  digitalWrite(K6_RELAY, LOW);
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);

  showResult(SHOW_OFF);

  // Self-test (LED cycle)
  if (selfTest()) {
    systemReady = true;
  } else {
    systemReady = false;
    showResult(SHOW_ERROR);
  }

  // Register Bridge RPC handler
  Bridge.begin();
  Bridge.provide("run_command", run_command);
}

// ===== MAIN LOOP =====
void loop() {
  // Heartbeat blink when idle
  static unsigned long lastBlink = 0;
  static bool blinkState = false;
  if (systemReady && millis() - lastBlink > 1000) {
    blinkState = !blinkState;
    matrix.loadFrame(blinkState ? FRAME_READY : FRAME_OFF);
    lastBlink = millis();
  }
}

// ===== COMMAND DISPATCHER =====
String handleCommand(String cmd) {
  if (cmd == "CONT") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runContinuityTest();

  } else if (cmd == "XCONT" || cmd == "XC") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runXlrContinuityTest();

  } else if (cmd == "XSHELL" || cmd == "XS") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runXlrShellTest();

  } else if (cmd == "RES") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runResistanceTest();

  } else if (cmd == "XRES" || cmd == "XR") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runXlrResistanceTest();

  } else if (cmd == "CAL") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runCalibration();

  } else if (cmd == "XCAL") {
    if (!systemReady) return "ERROR:NOT_READY";
    return runXlrCalibration();

  } else if (cmd == "STATUS") {
    return String("STATUS:") + (systemReady ? "READY" : "NOT_READY");

  } else if (cmd == "ID") {
    return String("ID:") + TESTER_ID;

  } else if (cmd == "RESET") {
    resetCircuit();
    return "OK:RESET";

  } else if (cmd == "READ") {
    return readSensors();

  } else if (cmd == "PINS") {
    return readPinStates();

  // --- Relay toggles ---
  } else if (cmd == "K12") {
    bool state = !digitalRead(K1_K2_RELAY);
    digitalWrite(K1_K2_RELAY, state);
    return String("DEBUG:K1+K2(D7):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "K3") {
    bool state = !digitalRead(K3_RELAY);
    digitalWrite(K3_RELAY, state);
    return String("DEBUG:K3(D8):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "K4") {
    bool state = !digitalRead(K4_RELAY);
    digitalWrite(K4_RELAY, state);
    return String("DEBUG:K4(D9):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "K5") {
    bool state = !digitalRead(K5_RELAY);
    digitalWrite(K5_RELAY, state);
    return String("DEBUG:K5(D10):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "K6") {
    bool state = !digitalRead(K6_RELAY);
    digitalWrite(K6_RELAY, state);
    return String("DEBUG:K6(D11):") + (state ? "HIGH" : "LOW");

  // --- Signal toggles ---
  } else if (cmd == "TSTIP") {
    bool state = !digitalRead(TS_CONT_OUT_TIP);
    digitalWrite(TS_CONT_OUT_TIP, state);
    return String("DEBUG:TS_CONT_OUT_TIP(D3):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "TSSLV") {
    bool state = !digitalRead(TS_CONT_OUT_SLEEVE);
    digitalWrite(TS_CONT_OUT_SLEEVE, state);
    return String("DEBUG:TS_CONT_OUT_SLEEVE(D2):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "TSRES") {
    bool state = !digitalRead(RES_TEST_OUT);
    digitalWrite(RES_TEST_OUT, state);
    return String("DEBUG:RES_TEST_OUT(D6):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "XLR1") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN1);
    digitalWrite(XLR_CONT_OUT_PIN1, state);
    return String("DEBUG:XLR_CONT_OUT_PIN1(D12):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "XLR2") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN2);
    digitalWrite(XLR_CONT_OUT_PIN2, state);
    return String("DEBUG:XLR_CONT_OUT_PIN2(D13):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "XLR3") {
    bool state = !digitalRead(XLR_CONT_OUT_PIN3);
    digitalWrite(XLR_CONT_OUT_PIN3, state);
    return String("DEBUG:XLR_CONT_OUT_PIN3(D15/A1):") + (state ? "HIGH" : "LOW");

  } else if (cmd == "XLRS") {
    bool state = !digitalRead(XLR_CONT_OUT_SHELL);
    digitalWrite(XLR_CONT_OUT_SHELL, state);
    return String("DEBUG:XLR_CONT_OUT_SHELL(D16/A2):") + (state ? "HIGH" : "LOW");

  } else {
    return "ERROR:UNKNOWN_CMD:" + cmd;
  }
}

// ===== TS CONTINUITY TEST =====
String runContinuityTest() {
  TestResults r;

  showResult(SHOW_OFF);

  digitalWrite(K1_K2_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);

  // Test TIP
  digitalWrite(TS_CONT_OUT_TIP, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.tipToTip = digitalRead(TS_CONT_IN_TIP) == HIGH;
  r.tipToSleeve = digitalRead(TS_CONT_IN_SLEEVE) == HIGH;
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  delay(RELAY_SETTLE_MS);

  // Test SLEEVE
  digitalWrite(TS_CONT_OUT_SLEEVE, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.sleeveToSleeve = digitalRead(TS_CONT_IN_SLEEVE) == HIGH;
  r.sleeveToTip = digitalRead(TS_CONT_IN_TIP) == HIGH;
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);

  // Evaluate
  r.overallPass = r.tipToTip && !r.tipToSleeve && r.sleeveToSleeve && !r.sleeveToTip;
  r.reversed = !r.tipToTip && r.tipToSleeve && !r.sleeveToSleeve && r.sleeveToTip;
  r.shorted = r.tipToSleeve || r.sleeveToTip;
  r.openTip = !r.tipToTip && !r.tipToSleeve;
  r.openSleeve = !r.sleeveToSleeve && !r.sleeveToTip;

  resetCircuit();

  if (r.overallPass) showResult(SHOW_PASS);
  else if (r.reversed || r.shorted) showResult(SHOW_ERROR);
  else showResult(SHOW_FAIL);

  // Build response
  String resp = "RESULT:";
  resp += r.overallPass ? "PASS" : "FAIL";
  resp += ":TT:" + String(r.tipToTip ? 1 : 0);
  resp += ":TS:" + String(r.tipToSleeve ? 1 : 0);
  resp += ":SS:" + String(r.sleeveToSleeve ? 1 : 0);
  resp += ":ST:" + String(r.sleeveToTip ? 1 : 0);

  if (!r.overallPass) {
    resp += ":REASON:";
    if (r.reversed) resp += "REVERSED";
    else if (r.shorted) resp += "SHORT";
    else if (r.openTip && r.openSleeve) resp += "NO_CABLE";
    else if (r.openTip) resp += "TIP_OPEN";
    else if (r.openSleeve) resp += "SLEEVE_OPEN";
    else resp += "UNKNOWN";
  }

  return resp;
}

// ===== XLR CONTINUITY TEST =====
String runXlrContinuityTest() {
  XlrContResults r;

  showResult(SHOW_OFF);
  resetCircuit();
  delay(RELAY_SETTLE_MS);

  const int outPins[] = {XLR_CONT_OUT_PIN1, XLR_CONT_OUT_PIN2, XLR_CONT_OUT_PIN3};
  const int inPins[]  = {XLR_CONT_IN_PIN1,  XLR_CONT_IN_PIN2,  XLR_CONT_IN_PIN3};

  pinMode(XLR_CONT_OUT_SHELL, INPUT);

  for (int d = 0; d < 3; d++) {
    for (int i = 0; i < 3; i++) pinMode(outPins[i], INPUT);
    pinMode(outPins[d], OUTPUT);
    digitalWrite(outPins[d], HIGH);
    delay(SIGNAL_SETTLE_MS);
    for (int s = 0; s < 3; s++) {
      r.p[d][s] = digitalRead(inPins[s]) == HIGH;
    }
    digitalWrite(outPins[d], LOW);
    delay(RELAY_SETTLE_MS);
  }

  for (int i = 0; i < 3; i++) pinMode(outPins[i], OUTPUT);
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);
  resetCircuit();

  // Evaluate
  r.overallPass = true;
  for (int d = 0; d < 3; d++) {
    for (int s = 0; s < 3; s++) {
      if (d == s && !r.p[d][s]) r.overallPass = false;
      if (d != s && r.p[d][s])  r.overallPass = false;
    }
  }

  if (r.overallPass) {
    showResult(SHOW_PASS);
  } else {
    bool anyConnection = false;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) anyConnection = true;
    showResult(anyConnection ? SHOW_ERROR : SHOW_FAIL);
  }

  // Build response
  String resp = "XCONT:";
  resp += r.overallPass ? "PASS" : "FAIL";
  for (int d = 0; d < 3; d++)
    for (int s = 0; s < 3; s++)
      resp += ":P" + String(d + 1) + String(s + 1) + ":" + String(r.p[d][s] ? 1 : 0);

  if (!r.overallPass) {
    resp += ":REASON:";
    bool allOpen = true;
    for (int d = 0; d < 3; d++)
      for (int s = 0; s < 3; s++)
        if (r.p[d][s]) allOpen = false;
    if (allOpen) {
      resp += "NO_CABLE";
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
      resp += issues.length() > 0 ? issues : "UNKNOWN";
    }
  }

  return resp;
}

// ===== XLR SHELL BOND TEST =====
String runXlrShellTest() {
  XlrShellResults r;

  showResult(SHOW_OFF);
  resetCircuit();
  delay(RELAY_SETTLE_MS);

  const int outPins[] = {XLR_CONT_OUT_PIN1, XLR_CONT_OUT_PIN2, XLR_CONT_OUT_PIN3, XLR_CONT_OUT_SHELL};
  const int inPins[]  = {XLR_CONT_IN_PIN1,  XLR_CONT_IN_PIN2,  XLR_CONT_IN_PIN3,  XLR_CONT_IN_SHELL};

  // Drive pin1, read shell (far end bond)
  for (int i = 0; i < 4; i++) pinMode(outPins[i], INPUT);
  pinMode(XLR_CONT_OUT_PIN1, OUTPUT);
  digitalWrite(XLR_CONT_OUT_PIN1, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.farShellBond = digitalRead(XLR_CONT_IN_SHELL) == HIGH;
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  delay(RELAY_SETTLE_MS);

  // Drive shell, read pin1/pin2/pin3/shell
  for (int i = 0; i < 4; i++) pinMode(outPins[i], INPUT);
  pinMode(XLR_CONT_OUT_SHELL, OUTPUT);
  digitalWrite(XLR_CONT_OUT_SHELL, HIGH);
  delay(SIGNAL_SETTLE_MS);
  r.nearShellBond = digitalRead(XLR_CONT_IN_PIN1) == HIGH;
  r.shellToP2 = digitalRead(XLR_CONT_IN_PIN2) == HIGH;
  r.shellToP3 = digitalRead(XLR_CONT_IN_PIN3) == HIGH;
  r.shellToShell = digitalRead(XLR_CONT_IN_SHELL) == HIGH;
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);

  for (int i = 0; i < 4; i++) {
    pinMode(outPins[i], OUTPUT);
    digitalWrite(outPins[i], LOW);
  }
  resetCircuit();

  r.overallPass = r.nearShellBond && r.farShellBond && !r.shellToP2 && !r.shellToP3;
  showResult(r.overallPass ? SHOW_PASS : (r.nearShellBond || r.farShellBond ? SHOW_ERROR : SHOW_FAIL));

  String resp = "XSHELL:";
  resp += r.overallPass ? "PASS" : "FAIL";
  resp += ":NEAR:" + String(r.nearShellBond ? 1 : 0);
  resp += ":FAR:" + String(r.farShellBond ? 1 : 0);
  resp += ":SS:" + String(r.shellToShell ? 1 : 0);

  if (!r.overallPass) {
    resp += ":REASON:";
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
    resp += issues.length() > 0 ? issues : "UNKNOWN";
  }

  return resp;
}

// ===== RESISTANCE HELPERS =====
int readResistanceADC() {
  long adcSum = 0;
  const int NUM_SAMPLES = 20;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(5);
  }
  return adcSum / NUM_SAMPLES;
}

float calcCableResistance(int adcValue, int calADC) {
  float senseVoltage = (adcValue / (float)ADC_MAX) * SUPPLY_VOLTAGE;
  float calVoltage = (calADC / (float)ADC_MAX) * SUPPLY_VOLTAGE;
  float calCurrent = (SUPPLY_VOLTAGE - calVoltage) / RES_SENSE_OHM;
  if (calCurrent <= 0.001) return 0.0;
  float cableResistance = (senseVoltage - calVoltage) / calCurrent;
  if (cableResistance < 0) cableResistance = 0;
  return cableResistance;
}

bool resPassCheck(int adcValue, bool calibrated, int calADC) {
  if (calibrated) return calcCableResistance(adcValue, calADC) <= MAX_CABLE_RESISTANCE;
  return adcValue <= RES_PASS_THRESHOLD;
}

String formatResResult(const char* prefix, int adcValue) {
  bool pass = resPassCheck(adcValue, isCalibrated, calibrationADC);
  float cableResistance = isCalibrated ? calcCableResistance(adcValue, calibrationADC) : 0.0;

  String resp = String(prefix);
  resp += pass ? "PASS" : "FAIL";
  resp += ":ADC:" + String(adcValue);
  if (isCalibrated) {
    resp += ":CAL:" + String(calibrationADC);
    resp += ":MOHM:" + String((int)(cableResistance * 1000));
    resp += ":OHM:" + String(cableResistance, 3);
  } else {
    resp += ":OHM:UNCAL";
  }
  return resp;
}

// ===== TS RESISTANCE TEST =====
String runResistanceTest() {
  showResult(SHOW_OFF);

  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  delay(RELAY_SETTLE_MS);

  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  int adcValue = readResistanceADC();

  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  bool pass = resPassCheck(adcValue, isCalibrated, calibrationADC);
  showResult(pass ? SHOW_PASS : SHOW_FAIL);

  return formatResResult("RES:", adcValue);
}

// ===== XLR RESISTANCE TEST =====
String runXlrResistanceTest() {
  showResult(SHOW_OFF);

  digitalWrite(K5_RELAY, HIGH);
  digitalWrite(K6_RELAY, HIGH);
  digitalWrite(K3_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);

  // Pin 2
  digitalWrite(K4_RELAY, LOW);
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);
  int adcPin2 = readResistanceADC();
  digitalWrite(RES_TEST_OUT, LOW);
  delay(RELAY_SETTLE_MS);

  // Pin 3
  digitalWrite(K4_RELAY, HIGH);
  delay(RELAY_SETTLE_MS);
  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);
  int adcPin3 = readResistanceADC();
  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  bool pin2Pass = resPassCheck(adcPin2, isXlrCalibrated, xlrCalibrationADC_P2);
  bool pin3Pass = resPassCheck(adcPin3, isXlrCalibrated, xlrCalibrationADC_P3);
  bool overallPass = pin2Pass && pin3Pass;

  showResult(overallPass ? SHOW_PASS : SHOW_FAIL);

  float res2 = 0.0, res3 = 0.0;
  if (isXlrCalibrated) {
    res2 = calcCableResistance(adcPin2, xlrCalibrationADC_P2);
    res3 = calcCableResistance(adcPin3, xlrCalibrationADC_P3);
  }

  String resp = "XRES:";
  resp += overallPass ? "PASS" : "FAIL";
  resp += ":P2ADC:" + String(adcPin2);
  resp += ":P3ADC:" + String(adcPin3);
  if (isXlrCalibrated) {
    resp += ":P2CAL:" + String(xlrCalibrationADC_P2);
    resp += ":P3CAL:" + String(xlrCalibrationADC_P3);
    resp += ":P2MOHM:" + String((int)(res2 * 1000));
    resp += ":P2OHM:" + String(res2, 3);
    resp += ":P3MOHM:" + String((int)(res3 * 1000));
    resp += ":P3OHM:" + String(res3, 3);
  } else {
    resp += ":OHM:UNCAL";
  }
  return resp;
}

// ===== TS CALIBRATION =====
String runCalibration() {
  showResult(SHOW_OFF);

  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  delay(RELAY_SETTLE_MS);

  digitalWrite(RES_TEST_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  long adcSum = 0;
  const int NUM_SAMPLES = 50;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    adcSum += analogRead(RES_SENSE);
    delay(10);
  }
  int measuredADC = adcSum / NUM_SAMPLES;

  digitalWrite(RES_TEST_OUT, LOW);
  resetCircuit();

  if (measuredADC > CAL_REJECT_THRESHOLD) {
    showResult(SHOW_FAIL);
    return "CAL:FAIL:ADC:" + String(measuredADC) + ":NO_CABLE";
  }

  calibrationADC = measuredADC;
  isCalibrated = true;

  showResult(SHOW_PASS);
  return "CAL:OK:ADC:" + String(calibrationADC);
}

// ===== XLR CALIBRATION =====
String runXlrCalibration() {
  showResult(SHOW_OFF);

  const int NUM_SAMPLES = 50;

  digitalWrite(K5_RELAY, HIGH);
  digitalWrite(K6_RELAY, HIGH);
  digitalWrite(K3_RELAY, HIGH);

  // Pin 2
  digitalWrite(K4_RELAY, LOW);
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

  // Pin 3
  digitalWrite(K4_RELAY, HIGH);
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

  if (measuredP2 > CAL_REJECT_THRESHOLD || measuredP3 > CAL_REJECT_THRESHOLD) {
    showResult(SHOW_FAIL);
    return "XCAL:FAIL:P2ADC:" + String(measuredP2) + ":P3ADC:" + String(measuredP3) + ":NO_CABLE";
  }

  xlrCalibrationADC_P2 = measuredP2;
  xlrCalibrationADC_P3 = measuredP3;
  isXlrCalibrated = true;

  showResult(SHOW_PASS);
  return "XCAL:OK:P2ADC:" + String(xlrCalibrationADC_P2) + ":P3ADC:" + String(xlrCalibrationADC_P3);
}

// ===== UTILITY =====
void resetCircuit() {
  digitalWrite(K1_K2_RELAY, LOW);
  digitalWrite(K3_RELAY, LOW);
  digitalWrite(K4_RELAY, LOW);
  digitalWrite(K5_RELAY, LOW);
  digitalWrite(K6_RELAY, LOW);
  digitalWrite(TS_CONT_OUT_SLEEVE, LOW);
  digitalWrite(TS_CONT_OUT_TIP, LOW);
  digitalWrite(RES_TEST_OUT, LOW);
  digitalWrite(XLR_CONT_OUT_PIN1, LOW);
  digitalWrite(XLR_CONT_OUT_PIN2, LOW);
  digitalWrite(XLR_CONT_OUT_PIN3, LOW);
  digitalWrite(XLR_CONT_OUT_SHELL, LOW);
}

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
  int patterns[] = {SHOW_FAIL, SHOW_PASS, SHOW_ERROR};
  for (int i = 0; i < 3; i++) {
    showResult(patterns[i]);
    delay(300);
    showResult(SHOW_OFF);
    delay(100);
  }
  return true;
}

String readSensors() {
  String r = "TS_TIP:" + String(digitalRead(TS_CONT_IN_TIP));
  r += ",TS_SLV:" + String(digitalRead(TS_CONT_IN_SLEEVE));
  r += ",RES_ADC:" + String(analogRead(RES_SENSE));
  r += ",XLR_P1:" + String(digitalRead(XLR_CONT_IN_PIN1));
  r += ",XLR_P2:" + String(digitalRead(XLR_CONT_IN_PIN2));
  r += ",XLR_P3:" + String(digitalRead(XLR_CONT_IN_PIN3));
  r += ",XLR_SH:" + String(digitalRead(XLR_CONT_IN_SHELL));
  return r;
}

String readPinStates() {
  String r = "K12:" + String(digitalRead(K1_K2_RELAY) ? "H" : "L");
  r += ",K3:" + String(digitalRead(K3_RELAY) ? "H" : "L");
  r += ",K4:" + String(digitalRead(K4_RELAY) ? "H" : "L");
  r += ",K5:" + String(digitalRead(K5_RELAY) ? "H" : "L");
  r += ",K6:" + String(digitalRead(K6_RELAY) ? "H" : "L");
  r += ",RES_DRV:" + String(digitalRead(RES_TEST_OUT) ? "H" : "L");
  r += ",RES_ADC:" + String(analogRead(RES_SENSE));
  return r;
}

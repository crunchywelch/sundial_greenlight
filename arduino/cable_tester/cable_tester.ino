/*
 * Greenlight TS Cable Tester - Arduino Mega 2560
 *
 * Simple continuity and polarity testing for TS (Tip-Sleeve) cables.
 * Communicates with Raspberry Pi via USB serial.
 *
 * Commands:
 *   TEST     - Run continuity/polarity test, returns RESULT:...
 *   STATUS   - Get tester status, returns STATUS:...
 *   ID       - Get tester ID, returns ID:...
 *
 * Pin Configuration:
 *   D2  - CABLE_RELAYS      (HIGH = continuity mode)
 *   D3  - CONTINUITY_RELAY  (LOW = sleeve, HIGH = tip)
 *   D5  - TEST_SIGNAL_OUT   (test signal output)
 *   D8  - TIP_SENSE         (input - reads tip on far end)
 *   D9  - SLEEVE_SENSE      (input - reads sleeve on far end)
 *   D10 - FAIL_LED          (red)
 *   D11 - PASS_LED          (green)
 *   D12 - ERROR_LED         (yellow)
 *   D13 - STATUS_LED        (built-in)
 */

// ===== PIN DEFINITIONS =====
#define CABLE_RELAYS        2    // HIGH = continuity test mode
#define CONTINUITY_RELAY    3    // LOW = sleeve, HIGH = tip
#define TEST_SIGNAL_OUT     5    // Test signal output
#define TIP_SENSE           8    // Input: tip on far end
#define SLEEVE_SENSE        9    // Input: sleeve on far end

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

// ===== GLOBAL STATE =====
bool systemReady = false;
String inputBuffer = "";

// ===== TEST RESULTS =====
struct TestResults {
  bool tipContinuity;
  bool sleeveContinuity;
  bool tipIsolated;      // Tip isolated when testing sleeve
  bool sleeveIsolated;   // Sleeve isolated when testing tip
  bool polarityCorrect;
  bool overallPass;
};

// ===== SETUP =====
void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) { ; }  // Wait for USB serial

  // Configure relay outputs
  pinMode(CABLE_RELAYS, OUTPUT);
  pinMode(CONTINUITY_RELAY, OUTPUT);
  pinMode(TEST_SIGNAL_OUT, OUTPUT);

  // Configure sense inputs
  pinMode(TIP_SENSE, INPUT);
  pinMode(SLEEVE_SENSE, INPUT);

  // Configure LEDs
  pinMode(FAIL_LED, OUTPUT);
  pinMode(PASS_LED, OUTPUT);
  pinMode(ERROR_LED, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  // Initialize outputs
  digitalWrite(CABLE_RELAYS, LOW);
  digitalWrite(CONTINUITY_RELAY, LOW);
  digitalWrite(TEST_SIGNAL_OUT, LOW);

  // All LEDs off
  setAllLEDs(false);

  // Run self-test
  if (selfTest()) {
    systemReady = true;
    digitalWrite(STATUS_LED, HIGH);
    Serial.println("READY:" + String(TESTER_ID));
  } else {
    systemReady = false;
    digitalWrite(ERROR_LED, HIGH);
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

  if (cmd == "TEST") {
    if (!systemReady) {
      Serial.println("ERROR:NOT_READY");
      return;
    }
    runTest();

  } else if (cmd == "STATUS") {
    sendStatus();

  } else if (cmd == "ID") {
    Serial.println("ID:" + String(TESTER_ID));

  } else if (cmd == "RESET") {
    resetCircuit();
    Serial.println("OK:RESET");

  } else {
    Serial.println("ERROR:UNKNOWN_CMD:" + cmd);
  }
}

// ===== TEST FUNCTIONS =====
void runTest() {
  TestResults results;

  // Turn off result LEDs, turn on status
  setAllLEDs(false);
  digitalWrite(STATUS_LED, HIGH);

  // Enter continuity test mode
  digitalWrite(CABLE_RELAYS, HIGH);
  delay(RELAY_SETTLE_MS);

  // === TEST 1: TIP CONTINUITY ===
  digitalWrite(CONTINUITY_RELAY, HIGH);  // Route to TIP
  delay(RELAY_SETTLE_MS);

  digitalWrite(TEST_SIGNAL_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.tipContinuity = digitalRead(TIP_SENSE) == HIGH;
  results.sleeveIsolated = digitalRead(SLEEVE_SENSE) == LOW;

  digitalWrite(TEST_SIGNAL_OUT, LOW);
  delay(RELAY_SETTLE_MS);

  // === TEST 2: SLEEVE CONTINUITY ===
  digitalWrite(CONTINUITY_RELAY, LOW);   // Route to SLEEVE
  delay(RELAY_SETTLE_MS);

  digitalWrite(TEST_SIGNAL_OUT, HIGH);
  delay(SIGNAL_SETTLE_MS);

  results.sleeveContinuity = digitalRead(SLEEVE_SENSE) == HIGH;
  results.tipIsolated = digitalRead(TIP_SENSE) == LOW;

  digitalWrite(TEST_SIGNAL_OUT, LOW);

  // === EVALUATE RESULTS ===
  results.polarityCorrect = results.sleeveIsolated && results.tipIsolated;
  results.overallPass = results.tipContinuity &&
                        results.sleeveContinuity &&
                        results.polarityCorrect;

  // Reset circuit
  resetCircuit();

  // Update LEDs
  if (results.overallPass) {
    digitalWrite(PASS_LED, HIGH);
  } else if (results.tipContinuity && results.sleeveContinuity && !results.polarityCorrect) {
    // Continuity OK but polarity wrong (wires crossed)
    digitalWrite(ERROR_LED, HIGH);
  } else {
    // Continuity failure
    digitalWrite(FAIL_LED, HIGH);
  }

  // Send results
  sendResults(results);
}

void sendResults(TestResults &r) {
  String response = "RESULT:";
  response += r.overallPass ? "PASS" : "FAIL";
  response += ":TIP:" + String(r.tipContinuity ? 1 : 0);
  response += ":SLEEVE:" + String(r.sleeveContinuity ? 1 : 0);
  response += ":POLARITY:" + String(r.polarityCorrect ? 1 : 0);

  // Add failure reason if failed
  if (!r.overallPass) {
    response += ":REASON:";
    if (!r.tipContinuity) {
      response += "TIP_OPEN";
    } else if (!r.sleeveContinuity) {
      response += "SLEEVE_OPEN";
    } else if (!r.polarityCorrect) {
      response += "CROSSED_WIRES";
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
  digitalWrite(CABLE_RELAYS, LOW);
  digitalWrite(CONTINUITY_RELAY, LOW);
  digitalWrite(TEST_SIGNAL_OUT, LOW);
}

// ===== UTILITY FUNCTIONS =====
void setAllLEDs(bool state) {
  digitalWrite(FAIL_LED, state);
  digitalWrite(PASS_LED, state);
  digitalWrite(ERROR_LED, state);
  digitalWrite(STATUS_LED, state);
}

bool selfTest() {
  // Quick LED test
  setAllLEDs(true);
  delay(200);
  setAllLEDs(false);
  delay(200);

  // Blink each LED
  int leds[] = {PASS_LED, ERROR_LED, FAIL_LED};
  for (int i = 0; i < 3; i++) {
    digitalWrite(leds[i], HIGH);
    delay(150);
    digitalWrite(leds[i], LOW);
  }

  // Could add more hardware checks here
  return true;
}

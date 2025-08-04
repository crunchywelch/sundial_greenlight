/*
 * CableTester.h - Arduino library for Greenlight Cable Testing
 * 
 * This library provides a clean interface for audio cable testing
 * with the ATmega32 Arduino board.
 * 
 * Author: Greenlight Terminal System
 * Version: 1.0
 */

#ifndef CABLE_TESTER_H
#define CABLE_TESTER_H

#include <Arduino.h>

// Test result structure
struct CableTestResult {
  bool tip_continuity;
  bool ring_continuity; 
  bool sleeve_continuity;
  bool polarity_correct;
  float resistance_ohms;
  float capacitance_pf;
  bool overall_pass;
  String error_message;
  unsigned long test_duration_ms;
};

// Calibration data structure
struct CalibrationData {
  float voltage_calibration_factor;
  float resistance_offset;
  float capacitance_offset;
  bool is_calibrated;
};

class CableTester {
public:
  // Constructor
  CableTester(int unit_id = 1);
  
  // Initialization
  bool begin();
  void setUnitId(int id);
  
  // Testing functions
  CableTestResult testCable();
  bool testContinuity(int connection); // 0=tip, 1=ring, 2=sleeve
  bool testPolarity();
  float measureResistance();
  float measureCapacitance();
  
  // System functions
  bool isReady();
  bool isCableInserted();
  float getSupplyVoltage();
  String getStatus();
  
  // Calibration functions
  bool calibrate();
  bool loadCalibration();
  bool saveCalibration();
  CalibrationData getCalibrationData();
  
  // Communication functions
  void handleSerialCommand();
  void sendTestResult(CableTestResult result);
  void sendStatus();
  
  // LED control
  void setStatusLED(bool state);
  void setPassLED(bool state);
  void setFailLED(bool state);
  void setErrorLED(bool state);
  void blinkLED(int pin, int count, int delay_ms);
  
  // Utility functions
  void resetTestCircuit();
  bool selfTest();
  void heartbeat();

private:
  int _unit_id;
  bool _system_ready;
  CalibrationData _calibration;
  unsigned long _last_heartbeat;
  
  // Internal measurement functions
  float _readAverageVoltage(int pin, int samples = 10);
  bool _testSingleContinuity(int relay_pin, int sense_pin);
  void _activateRelay(int pin, bool state);
  void _initializePins();
  bool _runPowerOnSelfTest();
  
  // Constants
  static const float VOLTAGE_REF;
  static const int ADC_RESOLUTION;
  static const float CONTINUITY_THRESHOLD_OHMS;
  static const unsigned long CAPACITANCE_TIMEOUT_US;
};

// Pin definitions (can be customized)
extern const int PIN_TEST_RELAY_TIP;
extern const int PIN_TEST_RELAY_RING;
extern const int PIN_TEST_RELAY_SLEEVE;
extern const int PIN_POLARITY_TEST;
extern const int PIN_RESISTANCE_CURRENT;
extern const int PIN_CAPACITANCE_CHARGE;
extern const int PIN_CALIBRATION_RELAY;
extern const int PIN_STATUS_LED;
extern const int PIN_ERROR_LED;
extern const int PIN_PASS_LED;
extern const int PIN_FAIL_LED;
extern const int PIN_FIXTURE_DETECT;
extern const int PIN_CONTINUITY_SENSE_A0;
extern const int PIN_CONTINUITY_SENSE_A1;
extern const int PIN_CONTINUITY_SENSE_A2;
extern const int PIN_RESISTANCE_MEASURE;
extern const int PIN_CAPACITANCE_MEASURE;
extern const int PIN_VOLTAGE_MONITOR;

#endif // CABLE_TESTER_H
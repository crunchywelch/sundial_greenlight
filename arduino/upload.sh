#!/bin/bash
arduino-cli compile --fqbn arduino:avr:mega cable_tester
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester

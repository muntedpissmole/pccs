#include <HardwareSerial.h>  // For Mega's Serial

#define NUM_PWM_CHANNELS 12
const uint8_t ANALOG_PINS[] = {A0, A1};
#define NUM_ANALOG_PINS (sizeof(ANALOG_PINS) / sizeof(ANALOG_PINS[0]))

int pwmPins[NUM_PWM_CHANNELS] = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13};
int pwmValues[NUM_PWM_CHANNELS] = {0};

struct RampState {
  bool active;
  int start_pwm;
  int target_pwm;
  unsigned long start_time;
  unsigned long duration_ms;
};

RampState ramp_states[NUM_PWM_CHANNELS];

void setup() {
  Serial.begin(500000);  // Updated baud
  while (!Serial);  // Wait for connection

  for (int i = 0; i < NUM_PWM_CHANNELS; i++) {
    pinMode(pwmPins[i], OUTPUT);
    analogWrite(pwmPins[i], pwmValues[i]);
    ramp_states[i] = {false, 0, 0, 0, 0};  // Initialize ramps inactive
  }

  for (uint8_t pin : ANALOG_PINS) {
    pinMode(pin, INPUT);
  }
  analogReference(DEFAULT);

  pinMode(13, OUTPUT);
  digitalWrite(13, HIGH);
}

void loop() {
  // Update all active ramps (non-blocking)
  for (int i = 0; i < NUM_PWM_CHANNELS; i++) {
    if (ramp_states[i].active) {
      unsigned long elapsed = millis() - ramp_states[i].start_time;
      if (elapsed >= ramp_states[i].duration_ms) {
        pwmValues[i] = ramp_states[i].target_pwm;
        analogWrite(pwmPins[i], pwmValues[i]);
        ramp_states[i].active = false;
      } else {
        float progress = (float)elapsed / ramp_states[i].duration_ms;
        int new_val = ramp_states[i].start_pwm + (int)((ramp_states[i].target_pwm - ramp_states[i].start_pwm) * progress);
        pwmValues[i] = constrain(new_val, 0, 255);
        analogWrite(pwmPins[i], pwmValues[i]);
      }
    }
  }

  // Handle incoming serial commands
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == 'P') {  // Ping
      Serial.println("AA");  // Echo 'AA' for 0xAA equivalent
    } else if (cmd == 'A') {  // Analog read
      int pin = Serial.parseInt();
      if (pin >= 0 && pin < NUM_ANALOG_PINS) {
        Serial.println(readAnalogFresh(pin));
      } else {
        Serial.println("ERR");
      }
    } else if (cmd == 'S') {  // Set PWM (instant)
      int channel = Serial.parseInt();
      int value = Serial.parseInt();
      if (channel >= 1 && channel <= NUM_PWM_CHANNELS) {
        int idx = channel - 1;
        pwmValues[idx] = constrain(value, 0, 255);
        analogWrite(pwmPins[idx], pwmValues[idx]);
        ramp_states[idx].active = false;  // Cancel any ramp
        Serial.println(pwmValues[idx]);  // Echo value
      } else {
        Serial.println("ERR");
      }
    } else if (cmd == 'G') {  // Get PWM
      int channel = Serial.parseInt();
      if (channel >= 1 && channel <= NUM_PWM_CHANNELS) {
        Serial.println(pwmValues[channel - 1]);
      } else {
        Serial.println("ERR");
      }
    } else if (cmd == 'R') {  // Ramp PWM (non-blocking)
      int channel = Serial.parseInt();
      int target = Serial.parseInt();
      unsigned long duration = Serial.parseInt();
      if (channel >= 1 && channel <= NUM_PWM_CHANNELS && duration >= 0) {
        int idx = channel - 1;
        ramp_states[idx].active = true;
        ramp_states[idx].start_pwm = pwmValues[idx];
        ramp_states[idx].target_pwm = constrain(target, 0, 255);
        ramp_states[idx].start_time = millis();
        ramp_states[idx].duration_ms = duration;
        if (duration == 0) {
          pwmValues[idx] = ramp_states[idx].target_pwm;
          analogWrite(pwmPins[idx], pwmValues[idx]);
          ramp_states[idx].active = false;
        }
        Serial.println(ramp_states[idx].target_pwm);  // Echo target immediately
      } else {
        Serial.println("ERR");
      }
    } else if (cmd == 'B') {  // Batch get all PWM
      for (int i = 0; i < NUM_PWM_CHANNELS; i++) {
        if (i > 0) Serial.print(" ");
        Serial.print(pwmValues[i]);
      }
      Serial.println();
    }
    // Flush any remaining input
    while (Serial.available()) Serial.read();
  }
}

uint16_t readAnalogFresh(int pinIndex) {
  uint8_t pin = ANALOG_PINS[pinIndex];
  analogRead(pin);  // Dummy read to settle
  delay(1);
  long sum = 0;
  for (int j = 0; j < 5; j++) {
    sum += analogRead(pin);
    delayMicroseconds(100);
  }
  return sum / 5;
}
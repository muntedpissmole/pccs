struct PWMState {
  int current_value;
  int start_value;
  int target;
  unsigned long start_time;
  unsigned long duration;
};
PWMState pwm_states[14]; // Indices 1-13 for pins 1-13 (but skipping pin 1 to avoid TX conflict)
long readVcc() {
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delay(2); // Wait for Vref to settle

  // Discard first conversion
  ADCSRA |= _BV(ADSC); // Start conversion
  while (bit_is_set(ADCSRA, ADSC)); // Wait
  uint8_t low = ADCL; // Discard
  uint8_t high = ADCH; // Discard

  long sum = 0;
  int num = 16;
  for (int i = 0; i < num; i++) {
    ADCSRA |= _BV(ADSC); // Start conversion
    while (bit_is_set(ADCSRA, ADSC)); // Wait
    low = ADCL;
    high = ADCH;
    sum += (high << 8) | low;
  }

  long result = sum / num;
  if (result == 0) result = 1; // Avoid division by zero
  result = 1125300L / result; // Calculate Vcc (in mV); adjust 1125300 if calibrated differently
  return result;
}
void setup() {
  Serial.begin(500000);
  for (int i = 2; i <= 13; i++) { // Skip pin 1 to avoid conflict with TX
    pinMode(i, OUTPUT);
    pwm_states[i].current_value = 0;
    pwm_states[i].target = 0;
    pwm_states[i].duration = 0;
    analogWrite(i, 0);
  }
}
void loop() {
  unsigned long current_time = millis();
  for (int i = 2; i <= 13; i++) { // Skip pin 1
    if (pwm_states[i].duration > 0) {
      unsigned long elapsed = current_time - pwm_states[i].start_time;
      if (elapsed >= pwm_states[i].duration) {
        pwm_states[i].current_value = pwm_states[i].target;
        analogWrite(i, pwm_states[i].current_value);
        pwm_states[i].duration = 0;
      } else {
        float progress = static_cast<float>(elapsed) / pwm_states[i].duration;
        pwm_states[i].current_value = pwm_states[i].start_value + static_cast<int>((pwm_states[i].target - pwm_states[i].start_value) * progress);
        analogWrite(i, pwm_states[i].current_value);
      }
    }
  }
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.startsWith("SET ")) {
      processSet(command.substring(4));
    } else if (command.startsWith("RAMP ")) {
      processRamp(command.substring(5));
    } else if (command.startsWith("GET ")) {
      processGet(command.substring(4));
    } else if (command.startsWith("ANALOG ")) {
      processAnalog(command.substring(7));
    } else if (command.startsWith("GETVCC")) {
      processGetVcc();
    }
  }
}
void processSet(String args) {
  int space_pos = args.indexOf(' ');
  if (space_pos != -1) {
    int pin = args.substring(0, space_pos).toInt();
    int value = args.substring(space_pos + 1).toInt();
    if (pin >= 2 && pin <= 13 && value >= 0 && value <= 255) { // Skip pin 1
      pwm_states[pin].current_value = value;
      pwm_states[pin].target = value;
      pwm_states[pin].duration = 0;
      analogWrite(pin, value);
    }
  }
}
void processRamp(String args) {
  int first_space = args.indexOf(' ');
  int second_space = args.indexOf(' ', first_space + 1);
  if (first_space != -1 && second_space != -1) {
    int pin = args.substring(0, first_space).toInt();
    int target = args.substring(first_space + 1, second_space).toInt();
    unsigned long duration = args.substring(second_space + 1).toInt();
    if (pin >= 2 && pin <= 13 && target >= 0 && target <= 255 && duration > 0) { // Skip pin 1
      pwm_states[pin].start_value = pwm_states[pin].current_value;
      pwm_states[pin].target = target;
      pwm_states[pin].start_time = millis();
      pwm_states[pin].duration = duration;
    }
  }
}
void processGet(String args) {
  int pin = args.toInt();
  if (pin >= 2 && pin <= 13) { // Skip pin 1
    Serial.print("VALUE ");
    Serial.print(pin);
    Serial.print(" ");
    Serial.println(pwm_states[pin].current_value);
  }
}
void processAnalog(String args) {
  int pin = args.toInt();
  if (pin >= 0 && pin <= 5) { // A0 to A5
    long sum = 0;
    int num_reads = 64;
    for (int i = 0; i < num_reads; i++) {
      sum += analogRead(A0 + pin);
      delayMicroseconds(50);
    }
    float value = static_cast<float>(sum) / num_reads;
    Serial.print("ANALOG ");
    Serial.print(pin);
    Serial.print(" ");
    Serial.println(value, 3);
  }
}
void processGetVcc() {
  long vcc = readVcc();
  Serial.print("VCC ");
  Serial.println(vcc);
}
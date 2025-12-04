// arduino.cpp

#include <avr/io.h>
#include <avr/sleep.h>

struct PWMState {
  int current_value;
  int start_value;
  int target;
  unsigned long start_time;
  unsigned long duration;
};
PWMState pwm_states[14]; // Indices 1-13 for pins 1-13 (but skipping pin 1 to avoid TX conflict)

ISR(ADC_vect) {
  // Empty ISR just to wake from sleep
}

long readVcc() {
  ADMUX = (0 << REFS1) | (1 << REFS0) | (0 << ADLAR) | (1 << MUX4) | (1 << MUX3) | (1 << MUX2) | (1 << MUX1) | (0 << MUX0);
  ADCSRB &= ~(1 << MUX5);
  delay(2);
  for (int i = 0; i < 10; i++) {
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    (void)ADCL;
    (void)ADCH;
  }
  long sum = 0;
  int num = 64;
  for (int i = 0; i < num; i++) {
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    uint8_t low = ADCL;
    uint8_t high = ADCH;
    sum += (high << 8) | low;
  }
  long result = sum / num;
  if (result == 0) result = 1;
  result = 1125300L / result;
  return result;
}

void setup() {
  Serial.begin(500000);
  ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);
  for (int i = 2; i <= 13; i++) {
    pinMode(i, OUTPUT);
    pwm_states[i].current_value = 0;
    pwm_states[i].target = 0;
    pwm_states[i].duration = 0;
    analogWrite(i, 0);
  }
}

void loop() {
  static unsigned long last_update = 0;
  unsigned long now = millis();

  if (now - last_update >= 4) {
    last_update = now;

    for (int i = 2; i <= 13; i++) {
      if (pwm_states[i].duration > 0) {
        unsigned long elapsed = now - pwm_states[i].start_time;
        if (elapsed >= pwm_states[i].duration) {
          pwm_states[i].current_value = pwm_states[i].target;
          pwm_states[i].duration = 0;
        } else {
          float progress = static_cast<float>(elapsed) / pwm_states[i].duration;
          pwm_states[i].current_value = pwm_states[i].start_value +
            static_cast<int>((pwm_states[i].target - pwm_states[i].start_value) * progress);
        }
        analogWrite(i, pwm_states[i].current_value);
      }
    }
  }

    while (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.length() == 0) continue;

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
    } else if (command == "GETALL") {
      processGetAll();
    }
  }
}

void processSet(String args) {
  int space_pos = args.indexOf(' ');
  if (space_pos != -1) {
    int pin = args.substring(0, space_pos).toInt();
    int value = args.substring(space_pos + 1).toInt();
    if (pin >= 2 && pin <= 13 && value >= 0 && value <= 255) {
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
    if (pin >= 2 && pin <= 13 && target >= 0 && target <= 255 && duration > 0) {
      pwm_states[pin].start_value = pwm_states[pin].current_value;
      pwm_states[pin].target = target;
      pwm_states[pin].start_time = millis();
      pwm_states[pin].duration = duration;
    }
  }
}

void processGet(String args) {
  int pin = args.toInt();
  if (pin >= 2 && pin <= 13) {
    Serial.print("VALUE ");
    Serial.print(pin);
    Serial.print(" ");
    Serial.println(pwm_states[pin].current_value);
  }
}

void processAnalog(String args) {
  int pin = args.toInt();
  if (pin >= 0 && pin <= 5) {
    float value = getAnalogAvg(pin);
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

void processGetAll() {
  long vcc = readVcc();
  float a0 = getAnalogAvg(0);
  float a1 = getAnalogAvg(1);
  float a2 = getAnalogAvg(2);
  Serial.print("ALL ");
  Serial.print(vcc);
  Serial.print(" ");
  Serial.print(a0, 3);
  Serial.print(" ");
  Serial.print(a1, 3);
  Serial.print(" ");
  Serial.println(a2, 3);
}

float getAnalogAvg(int pin) {
  long sum = 0;
  int num_reads = 64;
  for (int i = 0; i < num_reads; i++) {
    sum += analogRead(A0 + pin);
    delayMicroseconds(50);
  }
  return static_cast<float>(sum) / num_reads;
}
import time
import logging
from modules.arduino import ArduinoController  # Adjust import

logging.basicConfig(level=logging.DEBUG)
ard = ArduinoController()
failures = 0
total = 10000  # Bump to 10k for better detection
for i in range(total):
    vcc = ard.get_vcc()
    if vcc is None:
        failures += 1
    if i % 100 == 0:
        print(f"Progress: {i}/{total}")
    time.sleep(0.05)  # Mimic app call rate
print(f"Failures: {failures}/{total}")
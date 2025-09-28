import serial
import time

SERIAL_PORT = '/dev/ttyACM0'  # Update if needed
BAUD_RATE = 500000

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print(f"Connected to {SERIAL_PORT} at {BAUD_RATE} baud")
    time.sleep(2)  # Wait for Arduino to stabilize
    ser.write(b'GETVCC\n')
    response = ser.readline().decode().strip()
    print(f"Sent: GETVCC, Received: {response}")
    ser.close()
except serial.SerialException as e:
    print(f"Serial error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
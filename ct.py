import serial
import time
from datetime import datetime
import statistics

# Configuration
CT_SOLAR_ZERO_OFFSET = 2.5326  # Adjusted for zero solar current
CT_SOLAR_SENSITIVITY = 0.0125
CT_BATTERY_ZERO_OFFSET = 0.00751  # From disconnected delta
CT_BATTERY_SENSITIVITY_CHARGING = 0.0191  # Calibrated for clamp meter ~0.208 A (charging)
CT_BATTERY_SENSITIVITY_DISCHARGING = 0.004727  # Fine-tuned for clamp meter ~-1.1 A (discharging)

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 500000

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
    print(f"Connected to {SERIAL_PORT} at {BAUD_RATE} baud")
    time.sleep(2)
    ser.flushInput()
    ser.flushOutput()
except serial.SerialException as e:
    print(f"Failed to connect to {SERIAL_PORT}: {e}")
    exit(1)

def send_command(cmd):
    ser.write((cmd + '\n').encode())
    response = ser.readline().decode().strip()
    print(f"Sent: {cmd}, Received: {response}")
    return response

def get_analog(pin, samples=30):  # Increased samples for stability
    values = []
    for _ in range(samples):
        response = send_command(f'ANALOG {pin}')
        if response.startswith(f'ANALOG {pin} '):
            try:
                values.append(float(response.split(' ')[2]))
            except ValueError:
                continue
        time.sleep(0.01)
    return statistics.median(values) if values else None

def get_vcc():
    for _ in range(3):
        response = send_command('GETVCC')
        if response.startswith('VCC '):
            try:
                return int(response.split(' ')[1])
            except ValueError:
                continue
        time.sleep(0.1)
    return None

print("Starting CT polling. Press Ctrl+C to stop.")
try:
    delta_buffer = []
    BUFFER_SIZE = 5
    while True:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        vcc_mv = get_vcc()
        if vcc_mv is None:
            print(f"{now} - WARNING: Failed to get VCC, using fallback 5.0V")
            vcc_mv = 5000
        vref = vcc_mv / 1000.0
        
        battery_voltage_raw = get_analog(0)
        solar_raw = get_analog(2)
        battery_ct_raw = get_analog(3)
        battery_ct_ref_raw = get_analog(4)
        
        if None in (battery_voltage_raw, solar_raw, battery_ct_raw, battery_ct_ref_raw):
            print(f"{now} - ERROR: Failed to read one or more analogs")
            time.sleep(0.5)
            continue
        
        v_a0 = battery_voltage_raw * vref / 1023.0
        v_a2 = solar_raw * vref / 1023.0
        v_a3 = battery_ct_raw * vref / 1023.0
        v_a4 = battery_ct_ref_raw * vref / 1023.0
        
        battery_voltage = round(v_a0 * 5, 1)
        solar_current = (v_a2 - CT_SOLAR_ZERO_OFFSET) / CT_SOLAR_SENSITIVITY
        solar_current = max(0, round(solar_current, 2))
        
        delta = v_a3 - v_a4
        delta_buffer.append(delta)
        if len(delta_buffer) > BUFFER_SIZE:
            delta_buffer.pop(0)
        avg_delta = statistics.median(delta_buffer)
        
        battery_delta = avg_delta - CT_BATTERY_ZERO_OFFSET
        if battery_delta >= 0:
            battery_current = battery_delta / CT_BATTERY_SENSITIVITY_CHARGING  # Charging
        else:
            battery_current = battery_delta / CT_BATTERY_SENSITIVITY_DISCHARGING  # Discharging
        battery_current = round(battery_current, 2)
        
        load_current = round(solar_current - battery_current, 2)
        load_current = max(0, load_current)  # Prevent negative load current
        
        print(f"{now} - Raw: A0={battery_voltage_raw:.2f}, A2={solar_raw:.2f}, A3={battery_ct_raw:.2f}, A4={battery_ct_ref_raw:.2f}, delta={delta:.5f}, avg_delta={avg_delta:.5f}, vref={vref:.2f}")
        print(f"{now} - Calculated: battery_voltage={battery_voltage}V, solar_current={solar_current}A, battery_current={battery_current}A (positive=charging, negative=discharging), load_current={load_current}A")
        
        time.sleep(1)
except KeyboardInterrupt:
    print("Polling stopped.")
except Exception as e:
    print(f"Unexpected error: {e}")
finally:
    ser.close()
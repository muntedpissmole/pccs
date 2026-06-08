# modules/arduino.py
import serial
import threading
import time
import os
import logging

logger = logging.getLogger("pccs")


def brightness_to_pwm(brightness: int) -> int:
    """Convert 0-100 brightness percent to 0-255 PWM value for Arduino."""
    return int(max(0, min(100, brightness)) * 2.55)


def pwm_to_brightness(pwm: int) -> int:
    """Convert 0-255 PWM to nearest 0-100 brightness percent (for state reads)."""
    return round(max(0, min(255, pwm)) / 2.55)


class ArduinoManager:
    def __init__(self, config):
        self.config = config
        self.ser = None
        self.serial_lock = threading.Lock()
        self.state = {}

        self.OPTIMISTIC_LOCK: dict[str, float] = {}
        self.OPTIMISTIC_LOCK_DURATION = config.getfloat('arduino', 'optimistic_lock_duration', 2.5)

        self.LIGHT_MAP = {}
        self.RGB_BUG_LIGHTS = {}
        self.LIGHT_ICONS = {}

        self._frontend_controls = []   # Unified ordered list for frontend

        self._load_all_controls()

        self.COMMAND_DELAY = config.getfloat('arduino', 'command_delay', 0.08)
        self.RESPONSE_DELAY = config.getfloat('arduino', 'response_delay', 0.04)
        self.RGB_RED_SWITCH_RAMP = config.getint('arduino', 'rgb_red_switch_ramp_ms', 180)
        self.RGB_MODE_SWITCH_RAMP = config.getint('arduino', 'rgb_mode_switch_ramp_ms', 250)

    def _load_all_controls(self):
        """Load PWM, RGB, and Relay controls with custom ordering"""
        # Safely clear all collections
        self.LIGHT_MAP.clear()
        self.RGB_BUG_LIGHTS.clear()
        
        if not hasattr(self, 'RGB_LIGHTS'):
            self.RGB_LIGHTS = set()
        else:
            self.RGB_LIGHTS.clear()
        
        self.LIGHT_ICONS.clear()
        self._frontend_controls.clear()

        logger.debug("=== LOADING ALL CONTROLS WITH ORDER ===")

        # ====================== LIGHTS (PWM + RGB) ======================
        if self.config.has_section('lights'):
            for name, line in self.config.items('lights'):
                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 4:
                    logger.warning(f"Invalid light: {name}")
                    continue

                friendly = parts[0]
                light_type = parts[1].lower()
                icon = parts[-2] if len(parts) > 2 and parts[-2].startswith('fa-') else "fa-lightbulb"
                try:
                    order = int(parts[-1])
                except:
                    order = 999

                self.LIGHT_ICONS[name] = icon

                if light_type == "pwm":
                    try:
                        pin = int(parts[2])
                        self.LIGHT_MAP[name] = pin
                        self._frontend_controls.append({
                            "name": name,
                            "label": friendly,
                            "type": "dimmer",
                            "icon": icon,
                            "has_mode": False,
                            "order": order
                        })
                        logger.debug(f"✓ PWM: {name} | order {order}")
                    except:
                        logger.error(f"Bad PWM pin for {name}")

                elif light_type == "rgb_bug":
                    try:
                        if len(parts) < 5:
                            continue
                        self.RGB_BUG_LIGHTS[name] = {
                            "white": int(parts[2]),
                            "red":   int(parts[3]),
                            "green": int(parts[4])
                        }
                        self.RGB_LIGHTS.add(name)
                        self._frontend_controls.append({
                            "name": name,
                            "label": friendly,
                            "type": "dimmer",
                            "icon": icon,
                            "has_mode": True,
                            "order": order
                        })
                        logger.debug(f"✓ RGB: {name} | order {order}")
                    except Exception as e:
                        logger.error(f"RGB parse error {name}: {e}")

        # ====================== RELAYS ======================
        if self.config.has_section('gpio'):
            for name, line in self.config.items('gpio'):
                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 5 or line.strip().startswith('#'):
                    continue

                friendly = parts[0]
                icon = parts[4] if len(parts) > 4 and parts[4].startswith('fa-') else "fa-lightbulb"
                try:
                    order = int(parts[5])
                except:
                    order = 999

                self._frontend_controls.append({
                    "name": name,
                    "label": friendly,
                    "type": "relay",
                    "icon": icon,
                    "has_mode": False,
                    "order": order
                })
                logger.debug(f"✓ Relay: {name} | order {order}")

        self._frontend_controls.sort(key=lambda x: x['order'])

    # ====================== FRONTEND ======================
    def get_frontend_config(self):
        """Return single unified list in user-defined order"""
        return self._frontend_controls

    # ====================== REST OF THE CLASS (unchanged) ======================
    def init_serial(self) -> bool:
        ports = [p.strip() for p in self.config.get('arduino', 'serial_ports').split(',')]
        baud_rate = self.config.getint('arduino', 'baud_rate')
        init_delay = self.config.getfloat('arduino', 'init_delay')

        for port in ports:
            if os.path.exists(port):
                try:
                    self.ser = serial.Serial(port, baud_rate, timeout=self.config.getfloat('arduino', 'timeout'))
                    time.sleep(init_delay)
                    self.ser.reset_input_buffer()
                    logger.info(f"📟 Arduino initialized on {port}")
                    return True
                except Exception as e:
                    logger.error(f"❌ Failed to open {port}: {e}")
        
        logger.warning("⚠️ No Arduino hardware found")
        return False

    def send_command(self, cmd: str, expect: str = None) -> str | None:
        """Send cmd, optionally wait for a response line starting with `expect`."""
        if not self.ser or not self.ser.is_open:
            return None

        with self.serial_lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write((cmd + '\n').encode('utf-8'))
                self.ser.flush()
                time.sleep(self.COMMAND_DELAY)

                if expect is None:
                    # RAMP/SET etc. do not produce responses from the Arduino.
                    # Avoid blocking on readline (which would timeout after 0.5s per attempt).
                    return None

                # Read lines (respecting port timeout) until we get one that
                # matches the expected prefix (if given) or any non-empty.
                # Tolerate occasional glued/stale responses from high baud serial
                # by searching inside the blob for the expected token.
                for _ in range(5):
                    blob = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if not blob:
                        continue
                    if blob.startswith(expect):
                        return blob
                    # search inside (e.g. "....VCC 5023" or previous reply glued)
                    idx = blob.find(expect)
                    if idx != -1:
                        return blob[idx:]
                    # otherwise discard and try next read
                    logger.debug("Discarded unexpected serial response while waiting for %s: %s", expect, blob)

            except serial.SerialException as se:
                msg = str(se)
                if "readiness to read but returned no data" in msg or "multiple access" in msg:
                    # Transient (device reset, contention, or USB serial glitch after open).
                    # Return None so callers (VCC/ANALOG) can retry or fallback; avoid log spam.
                    return None
                logger.error(f"Serial error sending '{cmd}': {se}")
                try:
                    self.ser.reset_input_buffer()
                except:
                    pass
            except Exception as e:
                msg = str(e)
                # Transient during shutdown, port close races, or USB serial glitches — don't spam ERROR
                if any(x in msg for x in ("NoneType", "closed", "not open", "EBADF", "Bad file descriptor")):
                    return None
                logger.error(f"Serial error sending '{cmd}': {e}")
                try:
                    self.ser.reset_input_buffer()
                except:
                    pass
        return None

    def should_ignore_for_optimistic(self, name: str) -> bool:
        if name in self.OPTIMISTIC_LOCK:
            if time.time() < self.OPTIMISTIC_LOCK[name]:
                return True
            else:
                self.OPTIMISTIC_LOCK.pop(name, None)
        return False

    def read_all_states(self):
        if not self.ser or not self.ser.is_open:
            return

        for name, pin in self.LIGHT_MAP.items():
            if self.should_ignore_for_optimistic(name):
                continue
            resp = self.send_command(f"GET {pin}", expect="VALUE")
            if resp and resp.startswith("VALUE"):
                try:
                    pwm = int(resp.split()[2])
                    self.state[name] = pwm_to_brightness(pwm)
                except:
                    pass

        for name, pins in self.RGB_BUG_LIGHTS.items():
            if self.should_ignore_for_optimistic(name):
                continue
            try:
                red_resp = self.send_command(f"GET {pins['red']}", expect="VALUE")
                white_resp = self.send_command(f"GET {pins['white']}", expect="VALUE")
                red_pwm = int(red_resp.split()[2]) if red_resp and red_resp.startswith("VALUE") else 0
                white_pwm = int(white_resp.split()[2]) if white_resp and white_resp.startswith("VALUE") else 0

                if red_pwm > white_pwm:
                    self.state[name] = pwm_to_brightness(red_pwm)
                    self.state[f"{name}_mode"] = "red"
                else:
                    self.state[name] = pwm_to_brightness(white_pwm)
                    self.state[f"{name}_mode"] = "white"
            except:
                pass

    def set_rgb_bug_light(self, name: str, brightness: int, mode: str = 'white', ramp_ms: int | None = None) -> bool:
        config = self.RGB_BUG_LIGHTS.get(name)
        if not config:
            return False

        pwm = brightness_to_pwm(brightness)
        if ramp_ms is not None:
            red_ramp = ramp_ms
            mode_ramp = ramp_ms
        else:
            red_ramp = self.RGB_RED_SWITCH_RAMP
            mode_ramp = self.RGB_MODE_SWITCH_RAMP

        # Use a consistent ramp time for crossfading the channels during mode switch.
        # This ensures white/red (or bug color) fade in/out overlap properly instead of
        # one completing before the other starts, and avoids different rates causing
        # both channels to be partially on for a noticeable time.
        # We unify on mode_ramp for the transition (when ramp_ms provided they are equal anyway).
        xfade_ramp = mode_ramp

        if mode == 'red':
            # Send "in" channels first so the bug color starts appearing while white is still up,
            # then kill the white. With same duration this gives crossfade.
            self.send_command(f"RAMP {config['red']} {pwm} {xfade_ramp}")
            self.send_command(f"RAMP {config['green']} {int(pwm * 0.05)} {xfade_ramp}")
            self.send_command(f"RAMP {config['white']} 0 {xfade_ramp}")
        else:
            # Kill the bug color first, then bring white up. Same duration → clean crossfade.
            self.send_command(f"RAMP {config['red']} 0 {xfade_ramp}")
            self.send_command(f"RAMP {config['green']} 0 {xfade_ramp}")
            self.send_command(f"RAMP {config['white']} {pwm} {xfade_ramp}")

        self.OPTIMISTIC_LOCK[name] = time.time() + self.OPTIMISTIC_LOCK_DURATION
        return True

    def cleanup(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                logger.error(f"Error closing serial: {e}")

    def is_connected(self) -> bool:
        """Return True if serial port is open and ready."""
        return bool(self.ser and getattr(self.ser, "is_open", False))

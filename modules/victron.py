# modules/victron.py
"""
Victron SmartShunt + MPPT SmartSolar manager (BLE Instant Readout).

Uses the `victron_ble` library for passive advertisement scanning.
All values shown in the UI are taken directly from the devices — no local
calculations, no Arduino fallbacks.

The tile stays compact (target ~150 px) and only displays fields the user
explicitly asked for:
  - SoC gauge + %
  - Battery voltage
  - Time-to-go (∞ when charging sentinel)
  - Consumed Ah (from shunt)
  - Solar current A ("current generated" from MPPT)
  - Yield today kWh ("total generated for the day" from MPPT)

Emits: 'victron_update' (same event name used by the old fallback shim).
"""

import logging
import time
import threading
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger("pccs")


class VictronManager:
    def __init__(self, socketio, config, phase_manager=None):
        self.socketio = socketio
        self.config = config
        self.phase_manager = phase_manager

        # ====================== CONFIG ======================
        self.shunt_address = (config.get('victron', 'shunt_address', fallback='') or '').strip().lower()
        self.shunt_key     = (config.get('victron', 'shunt_key',     fallback='') or '').strip()

        self.mppt_address  = (config.get('victron', 'mppt_address',  fallback='') or '').strip().lower()
        self.mppt_key      = (config.get('victron', 'mppt_key',      fallback='') or '').strip()

        self.scan_interval = config.getfloat('victron', 'scan_interval', fallback=2.0)
        self.stale_timeout = config.getfloat('victron', 'stale_timeout', fallback=45.0)

        # Internal
        self._running = False
        self._ble_thread = None
        self._stop_event = threading.Event()
        self._last_emit_ts = 0.0
        self._last_data_ts = 0.0

        self.state = {
            "stale": True,
            "soc": None,
            "voltage": None,
            "current_a": None,
            "consumed_ah": None,
            "time_to_go_mins": None,
            "solar_power_w": None,
            "solar_current_a": None,
            "yield_today_kwh": None,
            "charge_state": None,
            "last_update": None,
        }

        self.device_keys = {}
        if self.shunt_address and self.shunt_key:
            self.device_keys[self.shunt_address] = self.shunt_key
        if self.mppt_address and self.mppt_key:
            self.device_keys[self.mppt_address] = self.mppt_key

        if not self.device_keys:
            logger.warning("🔋 Victron: no shunt or mppt keys configured — tile will stay stale until devices are added")
        else:
            logger.info(
                "🔋 VictronManager initialized (shunt=%s, mppt=%s, scan=%.1fs, stale=%.0fs)",
                "yes" if self.shunt_address else "no",
                "yes" if self.mppt_address else "no",
                self.scan_interval,
                self.stale_timeout,
            )

    # ====================== PUBLIC API ======================

    def start(self):
        if self._running:
            return
        if not self.device_keys:
            return

        self._running = True
        self._stop_event.clear()

        self._ble_thread = threading.Thread(target=self._ble_thread_target, daemon=True, name="victron-ble")
        self._ble_thread.start()

        logger.info("🔋 Victron BLE scanner thread started")

    def stop(self):
        if not self._running:
            return

        logger.info("🔋 VictronManager stopping...")
        self._running = False
        self._stop_event.set()

        if self._ble_thread and self._ble_thread.is_alive():
            self._ble_thread.join(timeout=3.0)

        logger.info("🔋 VictronManager stopped")

    def get_state(self):
        """Return a copy of current state for socket / API consumers."""
        s = self.state.copy()
        s["stale"] = self._is_stale()
        if s.get("last_update") is None and self.state.get("last_update"):
            s["last_update"] = self.state["last_update"]
        return s

    def reset_daily_generation(self):
        """Called by PhaseManager when entering Night phase.
        With real Victron MPPT we just rely on its native yield_today — no-op here.
        """
        logger.debug("🔋 Victron daily reset requested (ignored — using device yield_today)")

    # ====================== INTERNAL ======================

    def _is_stale(self):
        if not self._last_data_ts:
            return True
        return (time.time() - self._last_data_ts) > self.stale_timeout

    def _ble_thread_target(self):
        """Dedicated thread with its own asyncio loop (required for BLE + Flask)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ble_loop(loop))
        except Exception as e:
            logger.error("🔋 Victron BLE thread crashed: %s", e, exc_info=True)
        finally:
            try:
                loop.close()
            except:
                pass

    async def _ble_loop(self, loop):
        """Main scanning loop using victron_ble.Scanner."""
        try:
            from victron_ble.scanner import Scanner
        except ImportError as e:
            logger.error("🔋 victron_ble (or bleak) not importable: %s — BLE scanning unavailable", e)
            return

        scanner = Scanner()

        # Supply keys for the devices we care about
        for addr, key in self.device_keys.items():
            try:
                scanner.add_device_key(addr, key)
            except Exception as ex:
                logger.warning("🔋 Failed to add key for %s: %s", addr, ex)

        def _on_advertisement(ble_device, advertisement):
            # This callback runs in the BLE thread / event loop
            try:
                self._handle_advertisement(ble_device, advertisement)
            except Exception as ex:
                logger.debug("🔋 Victron parse error for %s: %s", getattr(ble_device, 'address', '?'), ex)

        try:
            await scanner.start(callback=_on_advertisement)
            logger.info("🔋 Victron BLE scanner active — listening for %s device(s)", len(self.device_keys))

            # Keep the scanner alive until stop is requested
            while self._running and not self._stop_event.is_set():
                await asyncio.sleep(0.5)
                # Opportunistic staleness + emit check (cheap)
                self._emit_if_needed()

            await scanner.stop()
            logger.debug("🔋 Victron scanner stopped cleanly")

        except Exception as e:
            logger.error("🔋 Victron scanner error: %s", e, exc_info=True)

    def _handle_advertisement(self, ble_device, advertisement):
        """Parse one Victron advertisement and fold it into self.state."""
        addr = (ble_device.address or "").lower()
        if addr not in self.device_keys:
            return

        try:
            from victron_ble.devices import detect_device_type
            device_type = detect_device_type(advertisement)
            if device_type is None:
                return

            # Instantiate parser with the correct key
            key = self.device_keys[addr]
            parser = device_type(key)
            parsed = parser.parse(advertisement)

        except Exception as e:
            logger.debug("🔋 Victron advertisement handling failed for %s: %s", addr, e)
            return

        now = time.time()
        self._last_data_ts = now
        changed = False

        # --- SmartShunt / BMV (battery monitor) ---
        if hasattr(parsed, "get_soc"):
            soc = parsed.get_soc()
            if soc is not None and soc != self.state.get("soc"):
                self.state["soc"] = round(float(soc), 1)
                changed = True

            v = parsed.get_voltage()
            if v is not None and v != self.state.get("voltage"):
                self.state["voltage"] = round(float(v), 2)
                changed = True

            c = parsed.get_current()
            if c is not None and c != self.state.get("current_a"):
                self.state["current_a"] = round(float(c), 2)
                changed = True

            # consumed_ah is present on many battery monitor parsers
            if hasattr(parsed, "consumed_ah"):
                ca = getattr(parsed, "consumed_ah", None)
                if ca is not None and ca != self.state.get("consumed_ah"):
                    self.state["consumed_ah"] = round(float(ca), 1)
                    changed = True

            ttg = parsed.get_remaining_mins()
            if ttg is not None and ttg != self.state.get("time_to_go_mins"):
                # 65535 is the classic "infinite" sentinel
                self.state["time_to_go_mins"] = int(ttg) if ttg < 65000 else None
                changed = True

        # --- MPPT SmartSolar / BlueSolar ---
        if hasattr(parsed, "get_battery_voltage") or hasattr(parsed, "get_pv_power"):
            # Prefer battery side values when available
            bv = getattr(parsed, "get_battery_voltage", lambda: None)()
            if bv is not None:
                # Only overwrite if we don't already have a fresher shunt voltage
                if self.state.get("voltage") is None:
                    self.state["voltage"] = round(float(bv), 2)
                    changed = True

            # Solar current (this is the "current generated" the user wants)
            # Many MPPT parsers expose get_battery_current() for the charge current
            sc = None
            for meth in ("get_battery_current", "get_pv_current", "get_current"):
                if hasattr(parsed, meth):
                    try:
                        val = getattr(parsed, meth)()
                        if val is not None:
                            sc = float(val)
                            break
                    except:
                        pass
            if sc is not None and sc != self.state.get("solar_current_a"):
                self.state["solar_current_a"] = round(sc, 2)
                changed = True

            # Yield today — authoritative "total generated for the day"
            y = None
            for meth in ("get_yield_today", "get_yield_today_kwh"):
                if hasattr(parsed, meth):
                    try:
                        y = getattr(parsed, meth)()
                        if y is not None:
                            break
                    except:
                        pass
            if y is not None:
                kwh = float(y) / 1000.0 if y > 10 else float(y)  # library sometimes returns Wh
                if kwh != self.state.get("yield_today_kwh"):
                    self.state["yield_today_kwh"] = round(kwh, 2)
                    changed = True

            # Charge state (0-9 or enum in newer parsers)
            cs = None
            if hasattr(parsed, "get_charge_state"):
                try:
                    cs = parsed.get_charge_state()
                except:
                    pass
            if cs is not None:
                mapped = self._map_charge_state(cs)
                if mapped != self.state.get("charge_state"):
                    self.state["charge_state"] = mapped
                    changed = True

            # Also capture raw solar power if present (nice for future)
            sp = None
            if hasattr(parsed, "get_solar_power"):
                try:
                    sp = parsed.get_solar_power()
                except:
                    pass
            if sp is not None and sp != self.state.get("solar_power_w"):
                self.state["solar_power_w"] = round(float(sp), 0)
                changed = True

        self.state["last_update"] = datetime.now(timezone.utc).isoformat()

        if changed or (now - self._last_emit_ts) > (self.scan_interval * 3):
            self._emit_if_needed(force=True)

    def _map_charge_state(self, raw):
        """Map Victron charge state numbers / enums to friendly strings."""
        mapping = {
            0: "Off",
            1: "Bulk",
            2: "Absorption",
            3: "Float",
            4: "Storage",
            5: "Equalize",
            6: "Inverting",
            7: "Power supply",
            8: "Starting",
            9: "Repeated absorption",
            10: "Auto equalize",
            11: "BatterySafe",
            252: "External control",
        }
        if isinstance(raw, int):
            return mapping.get(raw, f"State {raw}")
        if hasattr(raw, "name"):
            return raw.name.replace("_", " ").title()
        return str(raw)

    def _emit_if_needed(self, force=False):
        if not self.socketio:
            return

        now = time.time()
        stale = self._is_stale()

        # Always emit when staleness changes so the UI can react
        staleness_changed = stale != self.state.get("_last_stale", None)
        self.state["_last_stale"] = stale

        interval = 0.8 if force else self.scan_interval
        if (now - self._last_emit_ts) < interval and not staleness_changed and not force:
            return

        payload = self.get_state()
        try:
            self.socketio.emit("victron_update", payload)
            self._last_emit_ts = now
        except Exception as e:
            logger.debug("🔋 Failed to emit victron_update: %s", e)


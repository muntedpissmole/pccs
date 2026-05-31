# modules/system.py
import os
import psutil
import platform
import subprocess
import threading
import time
import logging
import json
from datetime import datetime
import importlib.metadata

logger = logging.getLogger(__name__)


class SystemInfoManager:
    def __init__(self, config, socketio, app_version):
        self.config = config
        self.socketio = socketio
        self.app_version = app_version
        self.dhcp_clients_cache = []
        self.DHCP_REFRESH_INTERVAL = 60  # seconds

        self._start_background_tasks()

    def _start_background_tasks(self):
        """Start background refresh threads"""
        threading.Thread(target=self._dhcp_refresh_loop, daemon=True).start()

    def _dhcp_refresh_loop(self):
        """Background task to refresh DHCP clients"""
        while True:
            time.sleep(self.DHCP_REFRESH_INTERVAL)
            try:
                self.get_dhcp_clients()
                self.socketio.emit('dhcp_update', {'dhcp_clients': self.dhcp_clients_cache})
            except Exception as e:
                logger.debug(f"DHCP refresh failed: {e}")

    # ====================== DHCP ======================

    def get_dhcp_clients(self):
        """Parse dnsmasq leases"""
        try:
            lease_file = '/var/lib/misc/dnsmasq.leases'
            clients = []

            if os.path.exists(lease_file):
                with open(lease_file, 'r') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            clients.append({
                                'mac': parts[1],
                                'ip': parts[2],
                                'name': parts[3] if parts[3] != '*' else 'Unknown',
                                'lease_expiry': datetime.fromtimestamp(int(parts[0])).strftime('%H:%M')
                            })

            self.dhcp_clients_cache = sorted(clients, key=lambda x: x['name'].lower())
            return self.dhcp_clients_cache
        except Exception as e:
            logger.error(f"Failed to read DHCP leases: {e}")
            return []

    # ====================== SYSTEM INFO ======================

    def get_system_info(self):
        """Return comprehensive system information for diagnostics page"""
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "hostname": platform.node(),
                "model": self._get_model(),
                "os": f"{platform.system()} {platform.release()}",
                "kernel": platform.release(),
                "python_version": platform.python_version(),
                "flask_version": self._get_flask_version(),
                "app_version": self.app_version,                    # Fixed
                "uptime": self._get_uptime(),
                "boot_time": datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S"),

                "cpu_model": self._get_cpu_model(),
                "cpu_cores": psutil.cpu_count(logical=False),
                "cpu_threads": psutil.cpu_count(logical=True),
                "cpu_temp": self._get_cpu_temp(),
                "cpu_percent": round(psutil.cpu_percent(interval=0.4), 1),
                "load_avg": self._get_load_avg(),

                "memory_total": round(psutil.virtual_memory().total / (1024**2)),
                "memory_used": round(psutil.virtual_memory().used / (1024**2)),
                "memory_percent": psutil.virtual_memory().percent,

                "disk_total": round(psutil.disk_usage('/').total / (1024**3), 1),
                "disk_used": round(psutil.disk_usage('/').used / (1024**3), 1),
                "disk_percent": psutil.disk_usage('/').percent,

                "throttling_status": self._get_throttling_status(),
                "throttling_raw": self._get_throttling_raw(),
                "throttling_color": self._get_throttling_color(),

                "network_details": self._get_network_details(),
                "dhcp_clients": self.dhcp_clients_cache,
                "dhcp_range": self._get_dhcp_range(),               # Added

                "connected_clients": self._get_connected_clients(),
                "process_count": len(psutil.pids()),
                "top_processes": self._get_top_processes(),
            }

            return data

        except Exception as e:
            logger.error(f"Error gathering system info: {e}")
            return {"error": str(e)}

    # ====================== HELPER METHODS ======================

    def _get_model(self):
        try:
            with open('/proc/device-tree/model') as f:
                return f.read().strip()
        except:
            return "Unknown"

    def _get_cpu_model(self):
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if 'CPU part' in line:
                        cpu_part = line.split(':', 1)[1].strip()
                        if cpu_part == '0xd0b':
                            return "Broadcom BCM2712 (4× Cortex-A76)"
                        return f"ARM CPU (part 0x{cpu_part})"
            return "Unknown"
        except:
            return "Unknown"

    def _get_cpu_temp(self):
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                return round(int(f.read()) / 1000, 1)
        except:
            return None

    def _get_load_avg(self):
        try:
            return " ".join([f"{x:.2f}" for x in os.getloadavg()])
        except:
            return None

    def _get_uptime(self):
        try:
            return str(datetime.now() - datetime.fromtimestamp(psutil.boot_time()))
        except:
            return "Unknown"

    def _get_flask_version(self):
        try:
            return importlib.metadata.version("flask")
        except:
            return "Unknown"

    def _get_throttling_status(self):
        try:
            result = subprocess.check_output(['vcgencmd', 'get_throttled'], 
                                           stderr=subprocess.STDOUT, timeout=3).decode().strip()
            if '=' in result:
                raw = result.split('=')[1].strip()
                return "Normal ✓" if raw == '0x0' else "Throttled ⚠️"
            return "Unknown"
        except:
            return "vcgencmd unavailable"

    def _get_throttling_raw(self):
        try:
            result = subprocess.check_output(['vcgencmd', 'get_throttled'], 
                                           stderr=subprocess.STDOUT, timeout=3).decode().strip()
            return result.split('=')[1].strip() if '=' in result else "N/A"
        except:
            return "N/A"

    def _get_throttling_color(self):
        try:
            result = subprocess.check_output(['vcgencmd', 'get_throttled'], 
                                           stderr=subprocess.STDOUT, timeout=3).decode().strip()
            return "#4ade80" if '=' in result and result.split('=')[1].strip() == '0x0' else "#fbbf24"
        except:
            return "#94a3b8"

    def _get_network_details(self):
        details = []

        # Show all active interfaces
        for iface in ['eth0', 'wlan0', 'usb0', 'rndis0', 'enp0s3']:
            try:
                output = subprocess.check_output(
                    f"ip addr show {iface} 2>/dev/null", shell=True, timeout=2
                ).decode()
                for line in output.splitlines():
                    if 'inet ' in line and '127.' not in line:
                        ip = line.split()[1].split('/')[0]
                        status = "UP" if "state UP" in output else "DOWN"
                        details.append(f"{iface}: {ip} ({status})")
            except:
                pass

        # ==================== UPSTREAM GATEWAY ====================
        gateway = "Not detected"
        try:
            # Much more reliable: use 'ip route get' to an external IP
            output = subprocess.check_output(
                "ip route get 8.8.8.8", shell=True, timeout=3
            ).decode().strip()

            for line in output.splitlines():
                if 'via' in line:
                    parts = line.split()
                    try:
                        # Find gateway IP and dev
                        gw_ip = None
                        via_iface = None
                        
                        for i, p in enumerate(parts):
                            if p == 'via' and i + 1 < len(parts):
                                gw_ip = parts[i + 1]
                            elif p == 'dev' and i + 1 < len(parts):
                                via_iface = parts[i + 1]
                        
                        if gw_ip and via_iface:
                            gateway = f"{gw_ip} (via {via_iface})"
                            break
                    except:
                        continue

        except Exception as e:
            logger.debug(f"Gateway detection failed: {e}")
            # Fallback to original method
            try:
                output = subprocess.check_output("ip route show default", shell=True, timeout=3).decode()
                for line in output.splitlines():
                    if 'default via' in line:
                        parts = line.split()
                        gw_ip = parts[2]
                        via_iface = parts[-1] if len(parts) > 3 else "unknown"
                        
                        # Improved index-to-name mapping
                        if via_iface.isdigit():
                            via_iface = self._get_interface_name_from_index(via_iface)
                        
                        gateway = f"{gw_ip} (via {via_iface})"
                        break
            except:
                pass

        details.append(f"Gateway: {gateway}")

        # ==================== DNS SERVERS ====================
        dns_servers = []
        try:
            for conf_path in ['/etc/dnsmasq.conf', '/etc/dnsmasq/dnsmasq.conf']:
                if os.path.exists(conf_path):
                    with open(conf_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('server=') and not line.startswith('server=/'):
                                dns = line.split('=')[1].strip()
                                if dns not in dns_servers and dns != '127.0.0.1':
                                    dns_servers.append(dns)
                    if dns_servers:
                        break
        except:
            pass

        if dns_servers:
            for i, dns in enumerate(dns_servers, 1):
                label = f"DNS {i} (Primary)" if i == 1 else f"DNS {i}"
                details.append(f"{label}: {dns}")
        else:
            details.append("DNS: Not detected")

        # WAN IP
        try:
            public_ip = subprocess.check_output(
                "curl -s --max-time 6 https://api.ipify.org || echo 'N/A'",
                shell=True, timeout=8
            ).decode().strip()
            details.append(f"WAN IP: {public_ip}" if public_ip != 'N/A' else "WAN IP: unavailable")
        except:
            details.append("WAN IP: unavailable")

        # Traffic
        try:
            stats = psutil.net_io_counters()
            details.append(f"Total Sent: {stats.bytes_sent / (1024*1024):.1f} MB")
            details.append(f"Total Received: {stats.bytes_recv / (1024*1024):.1f} MB")
        except:
            pass

        return details

    def _get_dhcp_range(self):
        """Try to parse dhcp-range from dnsmasq config"""
        try:
            for conf_path in ['/etc/dnsmasq.conf', '/etc/dnsmasq/dnsmasq.conf']:
                if os.path.exists(conf_path):
                    with open(conf_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('dhcp-range='):
                                parts = line.split('=')[1].split(',')
                                if len(parts) >= 2:
                                    start = parts[0].strip()
                                    end = parts[1].strip()
                                    return f"{start} — {end}"
            return "Unknown (not found in config)"
        except Exception as e:
            logger.debug(f"Could not read DHCP range: {e}")
            return "Unable to read DHCP range"

    def _get_top_processes(self, limit=6):
        try:
            processes = []
            for proc in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']), 
                             key=lambda p: (p.info['cpu_percent'] or 0), reverse=True)[:limit]:
                processes.append({
                    'name': proc.info['name'][:28],
                    'cpu': round(proc.info['cpu_percent'] or 0, 1),
                    'mem': round(proc.info['memory_percent'] or 0, 1)
                })
            return processes
        except:
            return []

    def _get_connected_clients(self):
        try:
            if hasattr(self.socketio, 'server') and hasattr(self.socketio.server, 'manager'):
                return len(self.socketio.server.manager.rooms.get('/', {}))
            return 0
        except:
            return 0
            
    def _get_interface_name_from_index(self, ifindex: str) -> str:
        """Convert interface index (e.g. '600') to name (wlan0, usb0, etc.)"""
        try:
            output = subprocess.check_output("ip link show", shell=True, timeout=2).decode()
            for line in output.splitlines():
                if ifindex + ':' in line:
                    name = line.split(':', 2)[1].strip()
                    return name
        except:
            pass
        return ifindex

    # ====================== ITERATION 2 HELPERS (Network tile) ======================

    def _get_unifi_primary_ssid(self):
        """Best-effort attempt to read the primary WiFi SSID from Unifi OS.
        Returns None on failure / if not running Unifi OS.
        """
        candidates = [
            "/data/unifi/data/sites/default/config.gateway.json",
            "/etc/unifi/config.gateway.json",
            "/data/unifi/data/setting/network.json",
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    with open(path) as f:
                        data = json.load(f)
                    # Common patterns in Unifi configs
                    if isinstance(data, dict):
                        for key in ("wlan", "wireless", "networks"):
                            if key in data:
                                net = data[key]
                                if isinstance(net, list) and net:
                                    for n in net:
                                        if n.get("enabled") and n.get("name"):
                                            return n["name"]
                                elif isinstance(net, dict):
                                    for v in net.values():
                                        if isinstance(v, dict) and v.get("name"):
                                            return v["name"]
                    # Fallback: look for any "ssid" or "name" field that looks like a WiFi name
                    def _find_ssid(obj):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k.lower() in ("ssid", "name") and isinstance(v, str) and len(v) > 1:
                                    return v
                                res = _find_ssid(v)
                                if res:
                                    return res
                        elif isinstance(obj, list):
                            for item in obj:
                                res = _find_ssid(item)
                                if res:
                                    return res
                        return None
                    found = _find_ssid(data)
                    if found:
                        return found
            except Exception:
                continue
        return None

    # Note: Cached ping logic currently lives in app.py (_get_cached_ping) for simplicity.
    # If more sophisticated ping handling is needed later it can be moved here.

    # ====================== Signal Quality Helpers ======================

    def _get_current_signal_quality(self, iface: str | None) -> str | None:
        """Return a human string like '92% (Good)' for the WAN quality where possible."""
        if not iface:
            return None

        # WiFi client interfaces (house WiFi, campsite WiFi tether, future Starlink Go WiFi)
        if self._looks_like_wireless(iface):
            return self._get_wifi_signal_quality(iface)

        # USB / RNDIS tethering from a phone — try to read the phone's cellular signal
        if iface.startswith(("usb", "rndis")):
            return self._get_usb_cellular_signal_quality()

        # Direct Ethernet to Starlink Go (future) — we can add dedicated logic later
        # For now fall back to None (will show as "-")
        return None

    def _looks_like_wireless(self, iface: str) -> bool:
        try:
            out = subprocess.check_output(
                ["iw", "dev", iface, "info"],
                stderr=subprocess.DEVNULL,
                timeout=1
            )
            return True
        except Exception:
            return False

    def _get_wifi_signal_quality(self, iface: str) -> str | None:
        """Try to get RSSI from a WiFi client interface and turn it into percent + state."""
        try:
            # Works well for station/client mode
            out = subprocess.check_output(
                ["iw", "dev", iface, "station", "dump"],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode(errors="ignore")

            for line in out.splitlines():
                line = line.strip()
                if line.startswith("signal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            rssi = int(parts[1])
                            return self._rssi_to_quality_string(rssi)
                        except ValueError:
                            continue
        except Exception:
            pass
        return None

    def _rssi_to_quality_string(self, rssi: int) -> str:
        """Map RSSI (dBm, negative) to a nice '92% (Good)' string."""
        if rssi >= -50:
            pct, label = 100, "Excellent"
        elif rssi >= -60:
            pct, label = 90, "Excellent"
        elif rssi >= -70:
            pct, label = 75, "Good"
        elif rssi >= -80:
            pct, label = 50, "Fair"
        elif rssi >= -85:
            pct, label = 30, "Poor"
        else:
            pct, label = 10, "Very Poor"
        return f"{pct}% ({label})"

    def _get_usb_cellular_signal_quality(self) -> str | None:
        """Best-effort attempt to read cellular signal strength from a USB-tethered phone.

        Many Android phones in USB tether mode expose a serial port we can send AT
        commands to. We try common ports and common Telstra/Android commands.
        """
        import serial
        import glob

        # Common ports seen with Android USB tethering / modem mode
        candidates = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")

        # Sort so we try lower numbers first (often the diagnostic port)
        candidates.sort()

        for port in candidates:
            try:
                with serial.Serial(port, 115200, timeout=1) as ser:
                    # Wake up the modem
                    ser.write(b"AT\r")
                    resp = ser.read(100).decode(errors="ignore")
                    if "OK" not in resp:
                        continue

                    # Try AT+CSQ first (most universal)
                    ser.write(b"AT+CSQ\r")
                    resp = ser.read(200).decode(errors="ignore")
                    if "+CSQ:" in resp:
                        # Format is usually +CSQ: <rssi>,<ber>
                        try:
                            rssi = int(resp.split("+CSQ:")[1].split(",")[0].strip())
                            # Convert CSQ (0-31) to dBm approx: dBm = -113 + (rssi * 2)
                            dbm = -113 + (rssi * 2)
                            return self._rssi_to_quality_string(dbm)
                        except Exception:
                            pass

                    # Try Telstra / newer Android: AT+CPSI?
                    ser.write(b"AT+CPSI?\r")
                    resp = ser.read(300).decode(errors="ignore")
                    if "+CPSI:" in resp:
                        # Example: +CPSI: 0,1,"46001",...
                        # We can look for signal related fields in some responses
                        # For many modems this gives more detailed info; fall back to CSQ if possible
                        pass

            except (serial.SerialException, OSError):
                continue

        return None

    def _get_starlink_signal_quality(self) -> str | None:
        """Try to fetch signal quality from a local Starlink dish/router."""
        candidates = [
            "http://192.168.100.1/api/status",
            "http://192.168.100.1/api/v1/status",
            "http://192.168.100.1/api/device/status",
        ]
        for url in candidates:
            try:
                import urllib.request
                with urllib.request.urlopen(url, timeout=2) as resp:
                    data = json.loads(resp.read().decode())
                # Starlink v3/v4 style
                if "signalQuality" in data:
                    sq = data["signalQuality"]
                    if isinstance(sq, (int, float)):
                        pct = int(sq * 100)
                        label = "Excellent" if pct > 85 else "Good" if pct > 65 else "Fair" if pct > 40 else "Poor"
                        return f"{pct}% ({label})"
                # Older / other shapes
                if "snr" in data or "signal" in data:
                    # rough mapping if we have dB values
                    pass
            except Exception:
                continue
        return None

    # ====================== NEW: COMPACT NETWORK STATUS FOR DASHBOARD TILE ======================

    _FRIENDLY_IFACE: dict = {
        "wlan0": "WiFi",
        "wlan1": "WiFi 2",
        "eth0": "Ethernet",
        "eth1": "Ethernet 2",
        "usb0": "USB",
        "rndis0": "USB",
        "enp0s3": "Ethernet",
        "ppp0": "Cellular",
        "wwan0": "Cellular",
    }

    def _get_friendly_interface_name(self, iface: str) -> str:
        if not iface:
            return "Network"
        for key, friendly in self._FRIENDLY_IFACE.items():
            if iface == key or (key[:-1] and iface.startswith(key[:-1])):
                return friendly
        if iface.startswith("wlan"):
            return "WiFi"
        if iface.startswith("eth") or iface.startswith("en"):
            return "Ethernet"
        if iface.startswith("usb") or iface.startswith("rndis"):
            return "USB"
        if iface.startswith("ppp") or iface.startswith("wwan"):
            return "Cellular"
        return iface.upper()[:12]

    def _get_link_speed(self, iface: str) -> int | None:
        """Best-effort link speed in Mbps (sysfs for wired, iw for wireless)."""
        if not iface:
            return None
        try:
            speed_path = f"/sys/class/net/{iface}/speed"
            if os.path.exists(speed_path):
                with open(speed_path) as f:
                    val = int(f.read().strip())
                    if val > 0:
                        return val
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                f'iw dev {iface} link 2>/dev/null | grep -i "tx bitrate" || true',
                shell=True, timeout=2
            ).decode().strip().lower()
            if "bitrate" in out:
                for part in out.split():
                    if part.replace(".", "", 1).isdigit():
                        return int(round(float(part)))
        except Exception:
            pass
        return None

    def _sample_throughput(self):
        """Compute KB/s deltas. Targets the last known upstream iface when possible."""
        now = time.time()
        try:
            curr = psutil.net_io_counters(pernic=True)
        except Exception:
            return 0.0, 0.0

        prev = getattr(self, "_prev_net_io", None)
        prev_ts = getattr(self, "_prev_net_io_ts", 0.0)
        upstream = getattr(self, "_last_upstream_iface", None)
        dt = now - prev_ts if prev_ts else 0.0

        def _kbps(delta: int, dt: float) -> float:
            return max(0.0, round((delta / 1024.0) / dt, 1)) if dt > 0.05 else 0.0

        rx_k = tx_k = 0.0
        if upstream and prev and upstream in curr and upstream in prev:
            rx_k = _kbps(curr[upstream].bytes_recv - prev[upstream].bytes_recv, dt)
            tx_k = _kbps(curr[upstream].bytes_sent - prev[upstream].bytes_sent, dt)
        elif prev:
            try:
                tot = psutil.net_io_counters()
                tot_prev = getattr(self, "_prev_tot_io", None)
                if tot_prev:
                    rx_k = _kbps(tot.bytes_recv - tot_prev.bytes_recv, dt)
                    tx_k = _kbps(tot.bytes_sent - tot_prev.bytes_sent, dt)
            except Exception:
                pass

        self._prev_net_io = curr
        self._prev_net_io_ts = now
        try:
            self._prev_tot_io = psutil.net_io_counters()
        except Exception:
            pass
        return rx_k, tx_k

    def get_network_status(self):
        """Compact payload for the main UI Network tile (internet half + basics)."""
        status = {
            "internet": {
                "connected": False,
                "upstream_iface": None,
                "friendly_name": "No Internet",
                "gateway": None,
                "link_speed_mbps": None,
                "rx_kbps": 0.0,
                "tx_kbps": 0.0,
            },
            "last_updated": datetime.now().isoformat(),
        }
        via_iface = None
        gw_ip = None
        try:
            output = subprocess.check_output(
                "ip route get 8.8.8.8", shell=True, timeout=2.5
            ).decode().strip()
            for line in output.splitlines():
                if "via" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "via" and i + 1 < len(parts):
                            gw_ip = parts[i + 1]
                        elif p == "dev" and i + 1 < len(parts):
                            via_iface = parts[i + 1]
                    if gw_ip and via_iface:
                        break
        except Exception as e:
            logger.debug(f"get_network_status gateway probe: {e}")

        if via_iface:
            status["internet"]["connected"] = True
            status["internet"]["upstream_iface"] = via_iface
            status["internet"]["friendly_name"] = self._get_friendly_interface_name(via_iface)
            status["internet"]["gateway"] = gw_ip
            self._last_upstream_iface = via_iface
            spd = self._get_link_speed(via_iface)
            if spd:
                status["internet"]["link_speed_mbps"] = spd

            # Signal quality (new)
            sig = self._get_current_signal_quality(via_iface)
            if sig:
                status["internet"]["signal_quality"] = sig

        rx, tx = self._sample_throughput()
        status["internet"]["rx_kbps"] = rx
        status["internet"]["tx_kbps"] = tx
        return status

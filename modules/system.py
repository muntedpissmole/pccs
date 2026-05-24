# modules/system.py
import os
import psutil
import platform
import subprocess
import threading
import time
import logging
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
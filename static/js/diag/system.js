/**
 * PCCS Diagnostics — System info & WiFi
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() { return PCCS.getSocket(); }

  // ====================== PCCS CORE INFORMATION ======================
  	function renderCoreInfo(data) {
  		S.lastSystemInfo = data;

  		// System Overview
  		document.getElementById('system-overview').innerHTML = `
  			<div class="status-row"><span>Hostname</span><span>${data.hostname || '—'}</span></div>
  			<div class="status-row"><span>Model</span><span>${data.model || '—'}</span></div>
  			<div class="status-row"><span>OS</span><span>${data.os || '—'}</span></div>
  			<div class="status-row"><span>Kernel</span><span>${data.kernel || '—'}</span></div>
  			<div class="status-row"><span>Uptime</span><span>${data.uptime || '—'}</span></div>
  		`;

  		// Hardware
  		document.getElementById('hardware-info').innerHTML = `
  			<div class="status-row"><span>CPU Model</span><span>${data.cpu_model || '—'}</span></div>
  			<div class="status-row"><span>Cores / Threads</span><span>${data.cpu_cores} / ${data.cpu_threads}</span></div>
  			<div class="status-row"><span>CPU Temp</span><span>${data.cpu_temp ? data.cpu_temp + '°C' : '—'}</span></div>
  		`;

  		// CPU & Performance
  		document.getElementById('cpu-info').innerHTML = `
  			<div class="status-row"><span>CPU Usage</span><span>${data.cpu_percent || 0}%</span></div>
  			<div class="status-row"><span>Load Average</span><span>${data.load_avg || '—'}</span></div>
  			<div class="status-row"><span>Processes</span><span>${data.process_count || '—'}</span></div>
  		`;

  		// Thermal & Throttling
  		document.getElementById('throttling-info').innerHTML = `
  			<div class="status-row"><span>Status</span><span style="color:${data.throttling_color || '#94a3b8'}">
  				${data.throttling_status || 'Unknown'}
  			</span></div>
  			<div class="status-row"><span>Raw Value</span><span style="font-family:monospace; opacity:0.85;">
  				${data.throttling_raw || 'N/A'}
  			</span></div>
  		`;

  		// PCCS Application
  		document.getElementById('pccs-info').innerHTML = `
  			<div class="status-row"><span>Version</span><span>v${data.app_version || '—'}</span></div>
  			<div class="status-row"><span>Python</span><span>${data.python_version || '—'}</span></div>
  			<div class="status-row"><span>Flask</span><span>${data.flask_version || '—'}</span></div>
  			<div class="status-row"><span>Running Since</span><span>${data.running_since || '—'}</span></div>
  			<div class="status-row"><span>Clients</span><span>${data.connected_clients || '—'}</span></div>
  		`;

  		// Resource Usage
  		document.getElementById('resource-usage').innerHTML = `
  			<div class="status-row"><span>Memory</span><span>${data.memory_used} / ${data.memory_total} MB (${data.memory_percent}%)</span></div>
  			<div class="status-row"><span>Disk</span><span>${data.disk_used} / ${data.disk_total} GB (${data.disk_percent}%)</span></div>
  		`;

  		// ==================== NETWORK DETAILS ====================
  		let netDetailHTML = '';
  		if (data.network_details && data.network_details.length) {
  			data.network_details.forEach(item => {
  				const colonIndex = item.indexOf(':');
  				if (colonIndex > 0) {
  					const label = item.substring(0, colonIndex);
  					const value = item.substring(colonIndex + 1).trim();
  					netDetailHTML += `
  						<div class="status-row">
  							<span>${label}</span>
  							<span>${value}</span>
  						</div>`;
  				} else {
  					netDetailHTML += `<div class="status-row"><span>${item}</span><span></span></div>`;
  				}
  			});
  		} else {
  			netDetailHTML = '<div class="status-row"><span>No network data</span><span>—</span></div>';
  		}
  		document.getElementById('network-details').innerHTML = netDetailHTML;

  		// WiFi current status (populated by the new WiFi tile + system_info.current_wifi)
  		try {
  			const cur = data.current_wifi || {};
  			const el = document.getElementById('wifi-current');
  			if (el) {
  				if (cur && cur.connected && cur.ssid) {
  					let txt = cur.ssid;
  					if (cur.iface) txt += ` (${cur.iface})`;
  					if (cur.ip) txt += ` — ${cur.ip}`;
  					el.textContent = txt;
  				} else {
  					el.textContent = 'Not connected';
  				}
  			}
  		} catch (e) { /* non-fatal */ }

  	// ==================== DHCP CLIENTS ====================
  	let dhcpHTML = `
  		<div style="margin-bottom:12px; opacity:0.85; font-size:0.95rem;">
  			Range: <strong>${data.dhcp_range || 'Unknown'}</strong>
  		</div>`;

  	if (data.dhcp_clients && data.dhcp_clients.length) {
  		data.dhcp_clients.forEach(client => {
  			let expiryText = '';

  			if (client.lease_expiry) {
  				const now = new Date();
  				const [hours, minutes] = client.lease_expiry.split(':').map(Number);

  				let expiryDate = new Date(now);
  				expiryDate.setHours(hours, minutes, 0, 0);

  				if (expiryDate < now) {
  					expiryDate.setDate(expiryDate.getDate() + 1);
  				}

  				const diffMs = expiryDate - now;
  				const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  				const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

  				if (diffHours > 0) {
  					expiryText = ` <span style="opacity:0.7">(${diffHours}h ${diffMinutes}m left)</span>`;
  				} else if (diffMinutes > 0) {
  					expiryText = ` <span style="opacity:0.7">(${diffMinutes}m left)</span>`;
  				} else {
  					expiryText = ` <span style="opacity:0.7">(expiring soon)</span>`;
  				}
  			}

  			dhcpHTML += `
  				<div class="status-row">
  					<span>${client.name}</span>
  					<span style="text-align:right;">
  						${client.ip}${expiryText}<br>
  						<small style="opacity:0.5">${client.mac}</small>
  					</span>
  				</div>`;
  		});
  	} else {
  		dhcpHTML += '<div class="status-row"><span>No clients connected</span><span>—</span></div>';
  	}

  	document.getElementById('dhcp-clients').innerHTML = dhcpHTML;

  		// Top Processes
  		let procHTML = '';
  		if (data.top_processes && data.top_processes.length) {
  			data.top_processes.forEach(p => {
  				procHTML += `
  					<div class="status-row">
  						<span>${p.name}</span>
  						<span>${p.cpu}% CPU • ${p.mem}% MEM</span>
  					</div>`;
  			});
  		} else {
  			procHTML = '<div class="status-row"><span>No data</span></div>';
  		}
  		document.getElementById('top-processes').innerHTML = procHTML;
  	}

  	// ====================== WIFI CLIENT TILE (diag) ======================
  	async function scanWifi() {
  		const select = document.getElementById('wifi-network-select');
  		const statusEl = document.getElementById('wifi-status');
  		if (statusEl) {
  			statusEl.textContent = 'Scanning…';
  			statusEl.style.color = '#facc15';
  		}
  		if (select) select.disabled = true;

  		try {
  			const res = await fetch('/api/wifi/scan');
  			if (!res.ok) throw new Error('Scan request failed');
  			const data = await res.json();

  			S.wifiNetworks = data.networks || [];

  			if (select) {
  				select.innerHTML = '';
  				const placeholder = document.createElement('option');
  				placeholder.value = '';
  				placeholder.textContent = S.wifiNetworks.length ? '— Select a network —' : 'No networks found';
  				select.appendChild(placeholder);

  				S.wifiNetworks.forEach(n => {
  					const opt = document.createElement('option');
  					opt.value = n.ssid;
  					const sig = (typeof n.signal === 'number') ? ` ${n.signal}%` : '';
  					const sec = n.security ? ` [${n.security}]` : '';
  					const inUse = n.in_use ? ' ✓' : '';
  					opt.textContent = `${n.ssid}${sig}${sec}${inUse}`;
  					opt.dataset.security = n.security || 'open';
  					opt.dataset.signal = (n.signal != null) ? String(n.signal) : '';
  					if (n.in_use) opt.dataset.inUse = 'true';
  					select.appendChild(opt);
  				});
  			}

  			// Also update the current display if the backend gave us one
  			const curEl = document.getElementById('wifi-current');
  			if (curEl && data.current) {
  				const c = data.current;
  				if (c.connected && c.ssid) {
  					let t = c.ssid;
  					if (c.iface) t += ` (${c.iface})`;
  					if (c.ip) t += ` — ${c.ip}`;
  					curEl.textContent = t;
  				} else {
  					curEl.textContent = 'Not connected';
  				}
  			}

  			if (statusEl) {
  				statusEl.textContent = S.wifiNetworks.length ? `${S.wifiNetworks.length} network(s) found` : 'No networks found';
  				statusEl.style.color = '';
  			}
  		} catch (err) {
  			console.error('WiFi scan failed', err);
  			if (statusEl) {
  				statusEl.textContent = 'Scan failed (see console/logs)';
  				statusEl.style.color = '#f87171';
  			}
  		} finally {
  			if (select) select.disabled = false;
  		}
  	}

  	function onWifiChanged() {
  		const select = document.getElementById('wifi-network-select');
  		const pwContainer = document.getElementById('wifi-password-container');
  		const pwInput = document.getElementById('wifi-password');
  		if (!select || !pwContainer) return;

  		const opt = select.options[select.selectedIndex];
  		const sec = (opt && opt.dataset.security) ? opt.dataset.security.toLowerCase() : '';
  		const needsPw = sec && !['open', '--', ''].includes(sec) && !sec.includes('open');

  		if (needsPw) {
  			pwContainer.style.display = '';
  			if (pwInput) pwInput.placeholder = 'Password required';
  		} else {
  			pwContainer.style.display = 'none';
  			if (pwInput) pwInput.value = '';
  		}
  	}

  	async function connectWifi() {
  		const select = document.getElementById('wifi-network-select');
  		const pwInput = document.getElementById('wifi-password');
  		const statusEl = document.getElementById('wifi-status');
  		const btns = document.querySelectorAll('#wifi-tile button');

  		if (!select || !select.value) {
  			if (statusEl) {
  				statusEl.textContent = 'Please scan and select a network first';
  				statusEl.style.color = '#f87171';
  			}
  			return;
  		}

  		const ssid = select.value;
  		const password = (pwInput && pwInput.offsetParent !== null) ? (pwInput.value || null) : null;

  		// Disable controls during the (potentially slow) connect
  		btns.forEach(b => { b.disabled = true; b.style.opacity = '0.6'; });
  		if (statusEl) {
  			statusEl.textContent = `Connecting to ${ssid}…`;
  			statusEl.style.color = '#facc15';
  		}

  		try {
  			const res = await fetch('/api/wifi/connect', {
  				method: 'POST',
  				headers: { 'Content-Type': 'application/json' },
  				body: JSON.stringify({ ssid, password })
  			});
  			const data = await res.json();

  			if (data && data.success) {
  				if (statusEl) {
  					statusEl.textContent = data.message || `Connected to ${ssid}`;
  					statusEl.style.color = '#4ade80';
  				}
  				// Refresh core info (Network Details + current_wifi) soon
  				setTimeout(() => {
  					try { D.system.loadCoreInfo(); } catch (_) {}
  				}, 1200);
  				// Optional: re-scan so the ✓ in-use flag updates
  				setTimeout(() => { try { D.system.scanWifi(); } catch (_) {} }, 2500);
  			} else {
  				if (statusEl) {
  					statusEl.textContent = data && data.message ? data.message : 'Connection failed';
  					statusEl.style.color = '#f87171';
  				}
  			}
  		} catch (err) {
  			console.error('WiFi connect failed', err);
  			if (statusEl) {
  				statusEl.textContent = 'Connect request failed';
  				statusEl.style.color = '#f87171';
  			}
  		} finally {
  			setTimeout(() => {
  				btns.forEach(b => { b.disabled = false; b.style.opacity = ''; });
  			}, 600);
  		}
  	}

  	// Fetch core info
  	async function loadCoreInfo() {
  		try {
  			const res = await fetch('/api/system_info');
  			if (!res.ok) throw new Error('Failed to fetch');
  			const data = await res.json();
  			renderCoreInfo(data);
  		} catch (err) {
  			console.error("Failed to load core info:", err);
  			document.getElementById('raw-system-info').innerHTML = 
  				`<span style="color:#f87171;">⚠️ Could not load system information</span>`;
  		}
  	}

  D.system = { renderCoreInfo, loadCoreInfo, scanWifi, onWifiChanged, connectWifi };
})();

/**
 * PCCS Environmental Tile Updaters
 * Extracted from templates/index.html
 */
import { PCCS, getSocket } from './namespace.js';

const S = PCCS.state;

// ==================== GPS, SENSORS, WEATHER ====================

	function updateGPS(data) { 
		if (!data) return;

		S.gpsStatusReceived = true;
		const fixQuality = parseInt(data.fix_quality || 0);
		S.hasValidGPSFix = fixQuality >= 1;

		// Keep these unchanged
		if (data.satellites !== undefined) {
			document.getElementById('satellites').textContent = `${data.satellites || 0} / ${fixQuality}`;
		}

		const locationEl = document.getElementById('location');
		if (locationEl) {
			const suburb = (data.suburb || "").trim();
			locationEl.textContent = suburb || (S.hasValidGPSFix ? "Acquiring position..." : "No GPS Fix");
		}

		// NEW: Use combined function
		updateTimeAndSun(data);

		// Curve module manages its own readiness
		if (window.PCCS && window.PCCS.sunCurve) {
			window.PCCS.sunCurve.updateCurveGeometry();
		}

		// Keep weather logic
		if (S.hasValidGPSFix && data.latitude && data.longitude) {
			const now = Date.now();
			if (now - S.lastWeatherUpdate > S.WEATHER_INTERVAL_MS) {
				S.lastWeatherUpdate = now;
				fetchWeatherForecast(data.latitude, data.longitude);
			}
		}

		// Keep styling
		document.getElementById('tile-date').classList.toggle('text-amber-400', !S.hasValidGPSFix);
		document.getElementById('tile-time').classList.toggle('text-amber-400', !S.hasValidGPSFix);
	}

    function stripLeadingZero(timeStr) {
        return timeStr ? timeStr.replace(/^0(\d):/, '$1:') : "";
    }

	function updateClock() {
		// Only show local browser time + * when the backend has explicitly confirmed no GPS fix.
		// Before we hear from the backend, or when it reports a valid fix, do not show the warning asterisk.
		if (S.gpsStatusReceived && S.hasValidGPSFix) return;

		const now = new Date();
		const dayName = now.toLocaleDateString('en-AU', { weekday: 'short' });
		const day = now.getDate();
		const month = now.toLocaleDateString('en-AU', { month: 'short' });
		
		const showWarning = S.gpsStatusReceived && !S.hasValidGPSFix;
		const dateSuffix = showWarning ? ' *' : '';
		const timeSuffix = showWarning ? ' *' : '';
		
		document.getElementById('tile-date').textContent = `${dayName} ${day} ${month}${dateSuffix}`;
		
		let hours = now.getHours();
		let minutes = now.getMinutes().toString().padStart(2, '0');
		const ampm = hours >= 12 ? 'PM' : 'AM';
		hours = hours % 12 || 12;
		
		document.getElementById('tile-time').textContent = `${hours}:${minutes} ${ampm}${timeSuffix}`;
	}

	function updateSensors(data) {
		if (!data) return;

		// ==================== WATER GAUGE ====================
		if (data.water_percent !== undefined) {
			const percent = Math.max(0, Math.min(100, Math.round(data.water_percent)));
			
			const levelEl = document.getElementById('water-level');
			if (levelEl) levelEl.textContent = `${percent}%`;

			const fill = document.getElementById('water-fill');
			if (fill) {
				const currentWidth = parseFloat(fill.style.width) || 0;

				// Only reset + animate if value actually changed significantly
				if (Math.abs(currentWidth - percent) > 1) {
					fill.style.transition = 'none';
					fill.style.width = `${currentWidth}%`;   // keep current visual
					void fill.offsetWidth;                   // force reflow

					fill.style.transition = 'width 700ms cubic-bezier(0.34, 1.56, 0.64, 1)';
				} else {
					// Small changes → smooth transition only
					fill.style.transition = 'width 400ms ease-out';
				}

				fill.style.width = `${percent}%`;

				if (percent < 25) {
					fill.classList.add('low');
				} else {
					fill.classList.remove('low');
				}
			}

			const extraEl = document.getElementById('water-extra');
			if (extraEl && data.water_litres !== undefined) {
				extraEl.textContent = `Fresh: ${Math.round(data.water_litres)} L`;
			}
		}

		// ==================== TEMPERATURE ====================
		if (data.temp_c !== undefined && data.temp_c !== null) {
			const tempEl = document.getElementById('outside-temp');
			if (tempEl) {
				tempEl.textContent = `${Math.round(data.temp_c)}°C`;
			}
		}

		if (data.fridge_temp_c !== undefined && data.fridge_temp_c !== null) {
			const fridgeEl = document.getElementById('fridge-temp');
			if (fridgeEl) {
				fridgeEl.textContent = `${Math.round(data.fridge_temp_c)}°C`;
			}
		} else {
			const fridgeEl = document.getElementById('fridge-temp');
			if (fridgeEl) {
				fridgeEl.textContent = '—°C';
			}
		}
	}
	
	// ====================== COMBINED TIME & SUN ======================
	function updateTimeAndSun(data) {
		if (!data) return;

		// Date
		if (data.date) {
			let dayName = '', day = '', month = '';
			const dateStr = data.date.trim();

			// Try robust manual parse for known backend formats first
			// Format 1: "Monday, 12 May 2025"
			let m = dateStr.match(/^([A-Za-z]+),\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/);
			if (m) {
				dayName = m[1].slice(0, 3);
				day = m[2];
				month = m[3].slice(0, 3);
			} else {
				// Format 2: "2025-05-12" or let Date try
				const dateObj = new Date(dateStr);
				if (!isNaN(dateObj.getTime())) {
					dayName = dateObj.toLocaleDateString('en-AU', { weekday: 'short' });
					day = dateObj.getDate();
					month = dateObj.toLocaleDateString('en-AU', { month: 'short' });
				}
			}
			if (dayName && day && month) {
				document.getElementById('tile-date').textContent = `${dayName} ${day} ${month}`;
			}
		}

		// Time
		if (data.local_time) {
			const mins = parseTimeToMinutes(data.local_time);
			if (mins != null) {
				let hours = Math.floor(mins / 60);
				const minutes = (mins % 60).toString().padStart(2, '0');
				const ampm = hours >= 12 ? 'PM' : 'AM';
				hours = hours % 12 || 12;
				document.getElementById('tile-time').textContent = `${hours}:${minutes} ${ampm}`;
			}
		}

		// Sunrise / Sunset (raw astronomical times - bottom labels)
		if (data.sunrise) {
			const sunriseTime = stripLeadingZero(data.sunrise);
			const sunriseEl = document.getElementById('sunrise');
			if (sunriseEl) sunriseEl.textContent = sunriseTime;
		}
		if (data.sunset) {
			const sunsetTime = stripLeadingZero(data.sunset);
			const sunsetEl = document.getElementById('sunset');
			if (sunsetEl) sunsetEl.textContent = sunsetTime;
		}

		// Curve logic now lives in sun-curve.js
		if (window.PCCS && window.PCCS.sunCurve) {
			window.PCCS.sunCurve.updateCurveGeometry();
			window.PCCS.sunCurve.animateSunPosition(data.sunrise, data.sunset, data.local_time);
		}
	}

	// Phase + curve logic now lives in static/js/sun-curve.js
	function updatePhaseInfo(data) {
		if (window.PCCS && window.PCCS.sunCurve) {
			window.PCCS.sunCurve.updatePhaseInfo(data);
		}
	}

async function fetchWeatherForecast(lat, lon) {
        try {
            const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&daily=temperature_2m_max,temperature_2m_min,weathercode&current_weather=true&timezone=auto`;
            const res = await fetch(url, { cache: 'no-store' });
            const data = await res.json();

            if (data.daily) {
                const max = Math.round(data.daily.temperature_2m_max[0]);
                const min = Math.round(data.daily.temperature_2m_min[0]);
                document.getElementById('temp-range').textContent = `${min}° / ${max}°`;
            }

            const weatherIcon = document.getElementById('weather-icon');
            if (data.current_weather && weatherIcon) {
                const code = data.current_weather.weathercode;
                const isDay = data.current_weather.is_day === 1;
                weatherIcon.className = `fa-solid ${getWeatherIcon(code, isDay)} text-2xl accent-sky`;
            }
        } catch (e) {
            console.warn('Weather fetch failed:', e);
        }
    }

    function getWeatherIcon(code, isDay) {
        const icons = {
            0: isDay ? 'fa-sun' : 'fa-moon',
            1: isDay ? 'fa-sun' : 'fa-moon',
            2: 'fa-cloud', 3: 'fa-cloud',
            45: 'fa-smog', 48: 'fa-smog',
            51: 'fa-cloud-rain', 53: 'fa-cloud-rain', 55: 'fa-cloud-rain',
            61: 'fa-cloud-showers-heavy', 63: 'fa-cloud-showers-heavy', 65: 'fa-cloud-showers-heavy',
            71: 'fa-snowflake', 73: 'fa-snowflake', 75: 'fa-snowflake',
            80: 'fa-cloud-showers-heavy', 81: 'fa-cloud-showers-heavy', 82: 'fa-cloud-showers-heavy',
            95: 'fa-bolt', 96: 'fa-bolt', 99: 'fa-bolt'
        };
        return icons[code] || 'fa-cloud';
    }

// ==================== NETWORK TILE (Iteration 2) ====================
	function updateNetworkTile(data) {
		if (!data) return;
		const inet = (data.internet || {});
		const right = (data.right || {});

		// LEFT half (internet)
		const statusEl = document.getElementById('net-inet-status');
		const iconEl = document.getElementById('net-inet-icon');
		const ifaceEl = document.getElementById('net-iface');
		const rxEl = document.getElementById('net-rx');
		const txEl = document.getElementById('net-tx');
		const linkEl = document.getElementById('net-link-speed');
		const pingEl = document.getElementById('net-ping');
		const signalEl = document.getElementById('net-signal');

		const connected = !!inet.connected;
		const statusText = connected ? 'Online' : 'Offline';
		const statusColor = connected ? 'text-emerald-400' : 'text-red-400';
		const icon = connected ? 'fa-globe' : 'fa-exclamation-triangle';

		if (statusEl) {
			statusEl.textContent = statusText;
			statusEl.className = `tile-value font-medium leading-none ${statusColor}`;
		}
		if (iconEl) {
			iconEl.className = `fa-solid ${icon} fa-fw w-4 ${statusColor}`;
		}
		if (ifaceEl) {
			ifaceEl.textContent = inet.friendly_name || '—';
		}
		if (signalEl) {
			// Show whatever quality info the backend provides (e.g. "87%" or "Excellent" or "—")
			signalEl.textContent = inet.signal_quality || '—';
		}
		if (rxEl) rxEl.textContent = (inet.rx_kbps != null) ? `${inet.rx_kbps}` : '—';
		if (txEl) txEl.textContent = (inet.tx_kbps != null) ? `${inet.tx_kbps}` : '—';
		if (linkEl) {
			linkEl.textContent = inet.link_speed_mbps ? `${inet.link_speed_mbps}M` : '';
		}

		// Ping (left side, right-aligned in the speed row)
		if (pingEl) {
			const ms = inet.ping_ms;
			const pstatus = inet.ping_status || 'unknown';

			let colorClass = 'opacity-60';
			if (pstatus === 'good') colorClass = 'text-emerald-400';
			else if (pstatus === 'slow') colorClass = 'text-amber-400';
			else if (pstatus === 'fail') colorClass = 'text-red-400';

			if (ms != null && ms !== undefined) {
				pingEl.innerHTML = `<span class="${colorClass}">${ms}ms</span>`;
			} else {
				pingEl.innerHTML = `<span class="opacity-50">—</span>`;
			}
		}

		// RIGHT half (new Iteration 2 layout)
		const tempEl = document.getElementById('net-core-temp');
		const uptimeEl = document.getElementById('net-uptime');
		const clientsEl = document.getElementById('net-dhcp-clients');

		if (tempEl) {
			const t = right.core_temp_c;
			tempEl.textContent = (t != null) ? `${t}°C` : '—°C';
		}
		if (uptimeEl) {
			uptimeEl.textContent = right.uptime || '—';
		}
		if (clientsEl) {
			const c = right.dhcp_clients;
			clientsEl.textContent = (c != null) ? c : '—';
		}
	}

	// parseTimeToMinutes moved to format-utils.js (with fallback inside sun-curve.js)

	// updatePhaseCurveLabels now lives inside sun-curve.js

	// All sun/moon curve logic (geometry, animation, phase labels) has been extracted
	// to static/js/sun-curve.js as part of the professional refactor.
	// Old monolithic implementation removed. See PCCS.sunCurve.* for the current code.

  PCCS.tiles = {
    updateGPS,
    updateSensors,
    updateNetworkTile,
    updatePhaseInfo,
    updateClock,
    updateTimeAndSun,
    fetchWeatherForecast,
    getWeatherIcon,
  };

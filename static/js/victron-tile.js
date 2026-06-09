/**
 * PCCS Victron Power Tile
 * Extracted from templates/index.html
 */
import { PCCS } from './namespace.js';

// ==================== VICTRON / POWER TILE (Battery + Solar) ====================
function formatTTG(mins) {
  if (mins === null || mins === undefined || mins <= 0) return '—';
  if (mins >= 65000) return '∞';           // Victron "infinite / charging" sentinel
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h > 0) return `${h}h ${m.toString().padStart(2, '0')}m`;
  return `${m}m`;
}

function updatePowerTile(data) {
  if (!data) return;
  const tile = document.getElementById('power-tile');
  if (!tile) return;

  // SoC gauge + big percentage (with % unit)
  const soc = (data.soc != null) ? Math.max(0, Math.min(100, Math.round(data.soc))) : null;
  const socEl = document.getElementById('soc-percent');
  const progress = document.getElementById('soc-progress');
  if (socEl) socEl.textContent = (soc != null) ? soc + '%' : '—';
  if (progress) {
    const circ = 245.0; // 2 * PI * 39 (for 92px gauge, r=39)
    const offset = (soc != null) ? circ * (1 - (soc / 100)) : circ;
    progress.setAttribute('stroke-dashoffset', offset.toFixed(1));
    progress.setAttribute('stroke', 'var(--accent-color)');
  }

  // Voltage
  const vEl = document.getElementById('bat-voltage');
  if (vEl) {
    if (data.voltage != null) {
      vEl.textContent = `${parseFloat(data.voltage).toFixed(1)}V`;
    } else {
      vEl.textContent = '—';
    }
  }

  // Time-to-go
  const ttgEl = document.getElementById('bat-ttg');
  if (ttgEl) ttgEl.textContent = formatTTG(data.time_to_go_mins);

  // Consumed Ah (show sign, 1 decimal)
  const consEl = document.getElementById('bat-consumed');
  if (consEl) {
    if (data.consumed_ah != null) {
      const sign = data.consumed_ah > 0 ? '+' : '';
      consEl.textContent = `${sign}${parseFloat(data.consumed_ah).toFixed(1)}Ah`;
    } else {
      consEl.textContent = '—';
    }
  }

  // Solar current (the "current generated" value) — prefer solar_current_a, fall back gracefully
  const solEl = document.getElementById('sol-current');
  if (solEl) {
    const a = (data.solar_current_a != null) ? data.solar_current_a : data.current_a;
    if (a != null) {
      solEl.textContent = `${parseFloat(a).toFixed(1)}A`;
    } else {
      solEl.textContent = '—';
    }
  }

  // Total generated today (kWh from MPPT yield_today)
  const todayEl = document.getElementById('sol-today');
  if (todayEl) {
    if (data.yield_today_kwh != null) {
      todayEl.textContent = `${parseFloat(data.yield_today_kwh).toFixed(2)} kWh`;
    } else {
      todayEl.textContent = '—';
    }
  }

  // Charge state (small, bottom right)
  const csEl = document.getElementById('charge-state');
  if (csEl) {
    csEl.textContent = data.charge_state || '';
  }
}

PCCS.victron = { updatePowerTile };
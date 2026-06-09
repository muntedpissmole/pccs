/**
 * PCCS Diagnostics namespace root.
 */
import { PCCS } from '../namespace.js';

PCCS.diag = PCCS.diag || {};
PCCS.diag.state = {
  reedsCache: {},
  screenData: {},
  lastSystemInfo: {},
  sonosSpeakers: [],
  activeSonos: null,
  sonosStates: {},
  wifiNetworks: [],
};
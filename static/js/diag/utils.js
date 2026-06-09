/**
 * PCCS Diagnostics — utilities
 */
import { PCCS } from '../namespace.js';

const D = PCCS.diag;
function toTitleCase(str) {
  return str.replace(/\w\S*/g, txt =>
    txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
  );
}
D.utils = { toTitleCase };
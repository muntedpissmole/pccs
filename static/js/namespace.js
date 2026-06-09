/**
 * PCCS global namespace root.
 * All frontend modules attach to PCCS.*
 */
export const PCCS = globalThis.PCCS ?? {};
globalThis.PCCS = PCCS;

export function getSocket() {
  return PCCS.app?.socket ?? globalThis.socket ?? null;
}

PCCS.getSocket = getSocket;
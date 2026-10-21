import type { Radio } from '@/api/types'

/** The lamps answer every minute and the motion sensor reports at least every 5 min, so a
 * radio that hears nothing for this long has stopped receiving (even if it still answers). */
export const QUIET_MINUTES = 10

/** "SONOFF Dongle Plus MG24", or the radio type when it didn't say. */
export function radioName(radio: Radio): string {
  return [radio.manufacturer, radio.model].filter(Boolean).join(' ') || radio.type
}

/** Whole minutes since the radio last heard any device; null before the first frame. */
export function heardMinutes(radio: Radio, nowMs: number): number | null {
  return radio.heard === null ? null : Math.max(0, Math.round((nowMs / 1000 - radio.heard) / 60))
}

/** No frame from any paired device for QUIET_MINUTES (counted from the start until the first). */
export function radioQuiet(radio: Radio, nowMs: number, paired: boolean): boolean {
  const since = radio.heard ?? radio.started
  return !radio.fake && paired && since !== null && nowMs / 1000 - since >= QUIET_MINUTES * 60
}

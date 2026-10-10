import type { Snapshot } from '@/api/types'

import { localDateParts } from './format'

const toMinutes = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

/**
 * Is it night? The window runs from night.start to night.end in the home's
 * timezone, and ends early once a sunrise has started (the server's rule).
 */
export function isNight(now: Date, snapshot: Pick<Snapshot, 'night' | 'timezone' | 'sunrise'>): boolean {
  if (snapshot.sunrise) return false // a sunrise ends the night
  const { hhmm } = localDateParts(now, snapshot.timezone)
  const minute = toMinutes(hhmm)
  const start = toMinutes(snapshot.night.start)
  const end = toMinutes(snapshot.night.end)
  return start <= end ? minute >= start && minute < end : minute >= start || minute < end
}

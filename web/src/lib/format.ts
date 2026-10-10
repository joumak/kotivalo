// Times are shown in the service's timezone (the home's), whatever the device's.

export function formatTime(iso: string | Date, locale: string, timeZone: string): string {
  return new Date(iso).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit', timeZone })
}

/** "07:00" (stored alarm time) in the locale's style: "7.00" in Finnish. */
export function formatClockTime(hhmm: string, locale: string): string {
  const [hour, minute] = hhmm.split(':').map(Number)
  const date = new Date(Date.UTC(2026, 0, 5, hour, minute))
  return date.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' })
}

export function weekdayName(iso: string, locale: string, timeZone: string, long = true): string {
  return new Date(iso).toLocaleDateString(locale, {
    weekday: long ? 'long' : 'short',
    timeZone,
  })
}

/** Monday-first weekday names; 5 Jan 2026 was a Monday. */
export function weekdayNames(locale: string, style: 'short' | 'long' = 'short'): string[] {
  return Array.from({ length: 7 }, (_, i) =>
    new Date(Date.UTC(2026, 0, 5 + i, 12)).toLocaleDateString(locale, {
      weekday: style,
      timeZone: 'UTC',
    }),
  )
}

export function minutesBetween(fromMs: number, toIso: string): number {
  return Math.max(0, Math.round((Date.parse(toIso) - fromMs) / 60000))
}

/** Lamp level 2..254 as a percentage people expect: 1..100. */
export function levelPercent(level: number | null): number {
  if (level === null) return 0
  return Math.max(1, Math.round((level / 254) * 100))
}

export function percentToLevel(percent: number): number {
  return Math.min(254, Math.max(2, Math.round((percent / 100) * 254)))
}

export function localDateParts(now: Date, timeZone: string): { hhmm: string; weekday: number } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    weekday: 'short',
    hourCycle: 'h23',
    timeZone,
  }).formatToParts(now)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  return { hhmm: `${get('hour')}:${get('minute')}`, weekday: weekdays.indexOf(get('weekday')) }
}

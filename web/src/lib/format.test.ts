import { describe, expect, it } from 'vitest'

import { formatClockTime, formatTime, levelPercent, localDateParts, percentToLevel, weekdayNames } from './format'

describe('format', () => {
  it('writes times the Finnish way and the English way', () => {
    expect(formatClockTime('07:00', 'fi-FI')).toBe('7.00')
    expect(formatClockTime('06:30', 'en-GB')).toBe('6:30')
    expect(formatTime('2026-10-12T03:30:00Z', 'fi-FI', 'Europe/Helsinki')).toBe('6.30')
  })

  it('lists weekdays from Monday', () => {
    expect(weekdayNames('fi-FI')).toEqual(['ma', 'ti', 'ke', 'to', 'pe', 'la', 'su'])
    expect(weekdayNames('en-GB', 'long')[0]).toBe('Monday')
  })

  it('maps lamp levels to percentages and back', () => {
    expect(levelPercent(254)).toBe(100)
    expect(levelPercent(2)).toBe(1) // the dimmest level still reads as on
    expect(percentToLevel(1)).toBe(3)
    expect(percentToLevel(0)).toBe(2) // never level 1: that switches a FLOALT off
    expect(levelPercent(percentToLevel(67))).toBe(67)
  })

  it('finds the local time in the home timezone', () => {
    const parts = localDateParts(new Date('2026-10-12T20:30:00Z'), 'Europe/Helsinki')
    expect(parts).toEqual({ hhmm: '23:30', weekday: 0 })
  })
})

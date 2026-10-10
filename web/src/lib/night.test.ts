import { describe, expect, it } from 'vitest'

import type { SunriseRun } from '@/api/types'

import { isNight } from './night'

const home = (start: string, end: string, sunrise: SunriseRun | null = null) => ({
  night: { start, end },
  timezone: 'Europe/Helsinki',
  sunrise,
})
// 12 Oct 2026, Helsinki is UTC+3
const at = (hhmm: string) => new Date(`2026-10-12T${hhmm}:00+03:00`)

describe('night window', () => {
  it('crosses midnight', () => {
    expect(isNight(at('23:30'), home('23:00', '07:00'))).toBe(true)
    expect(isNight(at('03:00'), home('23:00', '07:00'))).toBe(true)
    expect(isNight(at('07:00'), home('23:00', '07:00'))).toBe(false)
    expect(isNight(at('22:59'), home('23:00', '07:00'))).toBe(false)
  })

  it('works within one day too', () => {
    expect(isNight(at('14:00'), home('13:00', '15:00'))).toBe(true)
    expect(isNight(at('16:00'), home('13:00', '15:00'))).toBe(false)
  })

  it('ends when a sunrise starts', () => {
    const run = { kind: 'alarm', phase: 'ramp' } as SunriseRun
    expect(isNight(at('06:10'), home('23:00', '07:00', run))).toBe(false)
  })
})

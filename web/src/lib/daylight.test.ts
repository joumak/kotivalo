import { describe, expect, it } from 'vitest'

import type { DaylightCurve } from '@/api/types'

import { coolness, dayPoints, formatOffset, kelvinAt, movePoint } from './daylight'

const CURVE: DaylightCurve = {
  warm_kelvin: 2700,
  cool_kelvin: 4000,
  morning_start: 0,
  morning_end: 120,
  evening_start: -120,
  evening_end: 0,
}
const SUNRISE = '2026-10-23T05:19:00Z'
const SUNSET = '2026-10-23T14:50:00Z'
const at = (iso: string) => Date.parse(iso)

describe('daylight curve', () => {
  const points = dayPoints(CURVE, SUNRISE, SUNSET)

  it('is warm at sunrise, cool by day and warm again at sunset', () => {
    expect(kelvinAt(at('2026-10-23T04:00:00Z'), CURVE, points)).toBe(2700)
    expect(kelvinAt(at(SUNRISE), CURVE, points)).toBe(2700)
    expect(kelvinAt(at('2026-10-23T06:19:00Z'), CURVE, points)).toBe(3224) // halfway in mireds
    expect(kelvinAt(at('2026-10-23T10:00:00Z'), CURVE, points)).toBe(4000)
    expect(kelvinAt(at(SUNSET), CURVE, points)).toBe(2700)
  })

  it('never reaches full cool when a short day makes the slopes overlap', () => {
    const winter = dayPoints({ ...CURVE, morning_end: 240, evening_start: -240 }, '2026-12-21T07:24:00Z', '2026-12-21T13:13:00Z')
    expect(coolness(at('2026-12-21T10:18:30Z'), winter)).toBeLessThan(0.8)
  })

  it('treats an equal start and end as a step', () => {
    const step = dayPoints({ ...CURVE, morning_end: 0 }, SUNRISE, SUNSET)
    expect(coolness(at(SUNRISE) - 1, step)).toBe(0)
    expect(coolness(at(SUNRISE), step)).toBe(1)
  })
})

describe('offsets', () => {
  it('reads as hours and minutes from the sun', () => {
    expect(formatOffset(0)).toBe('')
    expect(formatOffset(90)).toBe('+ 1 h 30 min')
    expect(formatOffset(-45)).toBe('− 45 min')
    expect(formatOffset(120)).toBe('+ 2 h')
  })

  it('keeps each slope in order when one end passes the other', () => {
    expect(movePoint(CURVE, 'morning_start', 180)).toMatchObject({ morning_start: 180, morning_end: 180 })
    expect(movePoint(CURVE, 'morning_end', -30)).toMatchObject({ morning_start: -30, morning_end: -30 })
    expect(movePoint(CURVE, 'evening_end', -150)).toMatchObject({ evening_start: -150, evening_end: -150 })
    expect(movePoint(CURVE, 'evening_start', 60)).toMatchObject({ evening_start: 60, evening_end: 60 })
  })
})

import { describe, expect, it } from 'vitest'

import type { WeatherPoint } from '@/api/types'

import { describePlace, formatTemp, hourLabel, nextMarks, weatherIcon } from './weather'

// Every symbol MET's Locationforecast can send (without the _day/_night suffix),
// including its own typos ("lightssleet...").
const MET_SYMBOLS = [
  'clearsky', 'cloudy', 'fair', 'fog', 'heavyrain', 'heavyrainandthunder', 'heavyrainshowers',
  'heavyrainshowersandthunder', 'heavysleet', 'heavysleetandthunder', 'heavysleetshowers',
  'heavysleetshowersandthunder', 'heavysnow', 'heavysnowandthunder', 'heavysnowshowers',
  'heavysnowshowersandthunder', 'lightrain', 'lightrainandthunder', 'lightrainshowers',
  'lightrainshowersandthunder', 'lightsleet', 'lightsleetandthunder', 'lightsleetshowers',
  'lightsnow', 'lightsnowandthunder', 'lightsnowshowers', 'lightssleetshowersandthunder',
  'lightssnowshowersandthunder', 'partlycloudy', 'rain', 'rainandthunder', 'rainshowers',
  'rainshowersandthunder', 'sleet', 'sleetandthunder', 'sleetshowers', 'sleetshowersandthunder',
  'snow', 'snowandthunder', 'snowshowers', 'snowshowersandthunder',
]

const point = (time: string, temperature = 5): WeatherPoint => ({
  time,
  temperature,
  symbol: 'cloudy',
  wind: 3,
  precipitation: 0,
})

/** Hourly points from `start` (UTC). */
const hourly = (start: string, count: number) =>
  Array.from({ length: count }, (_, i) => point(new Date(Date.parse(start) + i * 3600_000).toISOString()))

describe('weather icons', () => {
  it('know every MET symbol', () => {
    for (const symbol of MET_SYMBOLS) expect(weatherIcon(symbol).condition, symbol).not.toBe('unknown')
  })

  it('pick the right condition, and the night variant', () => {
    expect(weatherIcon('clearsky_day').Icon).not.toBe(weatherIcon('clearsky_night').Icon)
    expect(weatherIcon('partlycloudy_night').condition).toBe('partlyCloudy')
    expect(weatherIcon('rainshowers_day').condition).toBe('showers')
    expect(weatherIcon('lightrain').condition).toBe('lightRain')
    expect(weatherIcon('heavysnowshowersandthunder_day').condition).toBe('thunder')
    expect(weatherIcon('lightsleet').condition).toBe('sleet')
    expect(weatherIcon(null).condition).toBe('unknown')
  })
})

describe('next marks', () => {
  it('are the next local hours divisible by three, across midnight', () => {
    // 19:30Z is 22:30 in Helsinki (EEST, +3)
    const marks = nextMarks(hourly('2026-10-10T20:00:00Z', 24), new Date('2026-10-10T19:30:00Z'), 'Europe/Helsinki')
    expect(marks.map((p) => hourLabel(p.time, 'Europe/Helsinki'))).toEqual(['00', '03', '06'])
  })

  it('skip points that are already past', () => {
    const marks = nextMarks(hourly('2026-10-10T12:00:00Z', 24), new Date('2026-10-10T15:10:00Z'), 'Europe/Helsinki')
    expect(marks[0].time).toBe('2026-10-10T18:00:00.000Z') // 21 local
  })

  it('show 03:00 once on the night the clocks go back', () => {
    // 25 Oct 2026: 04:00 EEST becomes 03:00 EET (01:00Z)
    const marks = nextMarks(hourly('2026-10-24T22:00:00Z', 12), new Date('2026-10-24T21:30:00Z'), 'Europe/Helsinki')
    expect(marks.map((p) => hourLabel(p.time, 'Europe/Helsinki'))).toEqual(['03', '06', '09'])
  })
})

describe('temperatures and places', () => {
  it('format temperatures without a minus zero', () => {
    expect(formatTemp(6.6, 'fi-FI')).toBe('7°')
    expect(formatTemp(-3.2, 'fi-FI')).toBe('−3°')
    expect(formatTemp(-0.4, 'en-GB')).toBe('0°')
  })

  it('describe a place, or its coordinates', () => {
    expect(describePlace({ name: 'Espoo', region: 'Uusimaa', country: 'Suomi', lat: 60.21, lon: 24.66 })).toBe(
      'Espoo, Uusimaa, Suomi',
    )
    expect(describePlace({ name: '', lat: 60.2, lon: 24.7 })).toBe('60.20, 24.70')
  })
})

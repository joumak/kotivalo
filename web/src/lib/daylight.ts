import type { DaylightCurve } from '@/api/types'

// How far the points may lie from sunrise and sunset, in minutes (settings.py).
export const MORNING_RANGE: [number, number] = [-180, 360]
export const EVENING_RANGE: [number, number] = [-360, 180]
export const OFFSET_STEP = 15

const MINUTE = 60_000

/** One day's curve as instants (ms): starts cooling, fully cool, starts warming, fully warm. */
export interface DayPoints {
  morningStart: number
  morningEnd: number
  eveningStart: number
  eveningEnd: number
}

export function dayPoints(curve: DaylightCurve, sunrise: string, sunset: string): DayPoints {
  const rise = Date.parse(sunrise)
  const set = Date.parse(sunset)
  return {
    morningStart: rise + curve.morning_start * MINUTE,
    morningEnd: rise + curve.morning_end * MINUTE,
    eveningStart: set + curve.evening_start * MINUTE,
    eveningEnd: set + curve.evening_end * MINUTE,
  }
}

function rising(t: number, start: number, end: number): number {
  if (t >= end) return 1
  if (t <= start) return 0
  return (t - start) / (end - start)
}

/** 0 = warm, 1 = fully cool, as daylight.py: where the slopes overlap the warmer wins. */
export function coolness(t: number, points: DayPoints): number {
  const morning = rising(t, points.morningStart, points.morningEnd)
  const evening = 1 - rising(t, points.eveningStart, points.eveningEnd)
  return Math.min(morning, evening)
}

/** The warmth at t, moving evenly in mireds as the lamps do. */
export function kelvinAt(t: number, curve: DaylightCurve, points: DayPoints): number {
  const warm = 1e6 / curve.warm_kelvin
  const cool = 1e6 / curve.cool_kelvin
  return Math.round(1e6 / (warm + (cool - warm) * coolness(t, points)))
}

/** "+ 1 h 30 min", "− 45 min"; "" at the sun's own time. */
export function formatOffset(minutes: number): string {
  if (minutes === 0) return ''
  const abs = Math.abs(minutes)
  const parts = [Math.floor(abs / 60) ? `${Math.floor(abs / 60)} h` : '', abs % 60 ? `${abs % 60} min` : '']
  return `${minutes > 0 ? '+' : '−'} ${parts.filter(Boolean).join(' ')}`
}

export type DaylightPoint = 'morning_start' | 'morning_end' | 'evening_start' | 'evening_end'

/** Sets one point; moving a slope's start past its end (or back) takes the other along. */
export function movePoint(curve: DaylightCurve, point: DaylightPoint, minutes: number): DaylightCurve {
  const next = { ...curve, [point]: minutes }
  if (point === 'morning_start') next.morning_end = Math.max(next.morning_end, minutes)
  if (point === 'morning_end') next.morning_start = Math.min(next.morning_start, minutes)
  if (point === 'evening_start') next.evening_end = Math.max(next.evening_end, minutes)
  if (point === 'evening_end') next.evening_start = Math.min(next.evening_start, minutes)
  return next
}

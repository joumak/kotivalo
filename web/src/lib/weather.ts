import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudHail,
  CloudLightning,
  CloudMoon,
  CloudMoonRain,
  CloudRain,
  CloudSnow,
  CloudSun,
  CloudSunRain,
  Moon,
  Sun,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type { Place, WeatherPlace, WeatherPoint } from '@/api/types'

export type Condition =
  | 'clear'
  | 'partlyCloudy'
  | 'cloudy'
  | 'fog'
  | 'lightRain'
  | 'rain'
  | 'showers'
  | 'sleet'
  | 'snow'
  | 'thunder'
  | 'unknown'

/** A MET symbol code ("rainshowers_night", "heavysnowandthunder") as an icon and a condition. */
export function weatherIcon(symbol: string | null): { Icon: LucideIcon; condition: Condition } {
  const [base, variant] = (symbol ?? '').split('_')
  const night = variant === 'night'
  if (base.includes('thunder')) return { Icon: CloudLightning, condition: 'thunder' }
  if (base.includes('sleet')) return { Icon: CloudHail, condition: 'sleet' }
  if (base.includes('snow')) return { Icon: CloudSnow, condition: 'snow' }
  if (base.includes('rainshowers')) return { Icon: night ? CloudMoonRain : CloudSunRain, condition: 'showers' }
  if (base === 'lightrain') return { Icon: CloudDrizzle, condition: 'lightRain' }
  if (base.includes('rain')) return { Icon: CloudRain, condition: 'rain' }
  if (base === 'fog') return { Icon: CloudFog, condition: 'fog' }
  if (base === 'cloudy') return { Icon: Cloud, condition: 'cloudy' }
  if (base === 'fair' || base === 'partlycloudy') return { Icon: night ? CloudMoon : CloudSun, condition: 'partlyCloudy' }
  if (base === 'clearsky') return { Icon: night ? Moon : Sun, condition: 'clear' }
  return { Icon: Cloud, condition: 'unknown' }
}

function localHour(iso: string, timeZone: string): number {
  const hour = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone }).format(new Date(iso))
  return Number(hour)
}

/** The forecast at the next local hours divisible by `step` (e.g. 18, 21, 00). */
export function nextMarks(hours: WeatherPoint[], now: Date, timeZone: string, count = 3, step = 3): WeatherPoint[] {
  const marks: WeatherPoint[] = []
  let previous: number | null = null
  for (const point of hours) {
    const hour = localHour(point.time, timeZone)
    // The night the clocks go back has 03:00 twice: show it once.
    if (Date.parse(point.time) <= now.getTime() || hour % step !== 0 || hour === previous) continue
    marks.push(point)
    previous = hour
    if (marks.length === count) break
  }
  return marks
}

/** "18", "00": the hour of a forecast point in the home's timezone. */
export function hourLabel(iso: string, timeZone: string): string {
  return String(localHour(iso, timeZone)).padStart(2, '0')
}

/** "7°", "−3°" (the locale's minus sign); never "−0°". */
export function formatTemp(celsius: number, locale: string): string {
  const rounded = Math.round(celsius) || 0
  return `${new Intl.NumberFormat(locale).format(rounded)}°`
}

export function formatCoordinates(place: WeatherPlace): string {
  return `${place.lat.toFixed(2)}, ${place.lon.toFixed(2)}`
}

/** "Espoo, Uusimaa, Suomi", or the coordinates of a place without a name. */
export function describePlace(place: WeatherPlace | Place): string {
  const parts = 'region' in place ? [place.name, place.region, place.country] : [place.name]
  return parts.filter(Boolean).join(', ') || formatCoordinates(place)
}

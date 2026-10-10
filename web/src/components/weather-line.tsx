import { Wind } from 'lucide-react'

import type { Snapshot } from '@/api/types'
import { useT } from '@/i18n'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'
import { formatTemp, hourLabel, nextMarks, weatherIcon } from '@/lib/weather'

interface WeatherLineProps {
  snapshot: Snapshot
  /** compact: the Lights page; panel: the wall panel by day; night: the panel's dark night
   * screen, where everything takes the surrounding dim colour (no brighter accents). */
  variant?: 'compact' | 'panel' | 'night'
  className?: string
}

/** Now (icon, temperature, wind), then the next three 3-hour marks. Nothing without a fresh forecast. */
export function WeatherLine({ snapshot, variant = 'compact', className }: WeatherLineProps) {
  const t = useT()
  const now = useNow(60_000)
  const muted = variant === 'night' ? undefined : 'text-muted-foreground'
  const forecast = snapshot.weather?.forecast
  if (!forecast || snapshot.weather.stale) return null

  const tz = snapshot.timezone
  const current = forecast.now
  const { Icon, condition } = weatherIcon(current.symbol)
  const wind = current.wind === null ? null : t.weather.wind(Math.round(current.wind))
  const marks = nextMarks(forecast.hours, now, tz).map((point) => ({
    point,
    hour: hourLabel(point.time, tz),
    ...weatherIcon(point.symbol),
  }))
  const spoken = [
    t.weather.now(t.weather.conditions[condition], formatTemp(current.temperature, t.locale)),
    wind && t.weather.windNow(wind),
    ...marks.map((m) => t.weather.at(m.hour, t.weather.conditions[m.condition], formatTemp(m.point.temperature, t.locale))),
  ]
    .filter(Boolean)
    .join('; ')

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-6 gap-y-1.5 tabular-nums',
        { compact: 'text-base', panel: 'text-[clamp(1.1rem,2.2vw,1.75rem)]', night: 'justify-center text-xl' }[variant],
        className,
      )}
    >
      <span className="sr-only">{spoken}</span>
      <span aria-hidden className="flex items-center gap-2">
        <Icon className={cn('size-[1.3em]', muted)} strokeWidth={1.75} />
        <span className={cn(variant !== 'night' && 'font-medium')}>{formatTemp(current.temperature, t.locale)}</span>
        {wind && (
          <span className={cn('ml-2 flex items-center gap-1', muted)}>
            <Wind className="size-[1em]" strokeWidth={1.75} />
            {wind}
          </span>
        )}
      </span>
      {marks.length > 0 && (
        <span aria-hidden className={cn('flex items-center gap-5', muted)}>
          {marks.map(({ point, hour, Icon: MarkIcon }) => (
            <span key={point.time} className="flex items-center gap-1.5">
              <span className="text-[0.8em]">{hour}</span>
              <MarkIcon className="size-[1.15em]" strokeWidth={1.75} />
              {formatTemp(point.temperature, t.locale)}
            </span>
          ))}
        </span>
      )}
    </div>
  )
}

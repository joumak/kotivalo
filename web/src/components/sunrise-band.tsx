import { useT } from '@/i18n'
import { formatTime } from '@/lib/format'
import { kelvinToRgb, rgb } from '@/lib/light-color'

interface SunriseBandProps {
  start: string // ISO: light starts
  full: string // ISO: full brightness (the alarm)
  off: string | null // ISO: switches off; null = stays on
  warmKelvin: number
  coolKelvin: number
  timezone: string
  /** 0..1 position of "now" along the band, when a sunrise is running. */
  now?: number
}

/**
 * The sunrise drawn as what it is: night turning into warm light, then daylight,
 * with the times when the light starts, is full, and switches off.
 */
export function SunriseBand({ start, full, off, warmKelvin, coolKelvin, timezone, now }: SunriseBandProps) {
  const t = useT()
  const fadeMs = Date.parse(full) - Date.parse(start)
  const holdMs = off ? Date.parse(off) - Date.parse(full) : fadeMs * 0.25
  const fadeShare = fadeMs / (fadeMs + holdMs)
  const warm = kelvinToRgb(warmKelvin)
  const cool = kelvinToRgb(coolKelvin)
  const time = (iso: string) => formatTime(iso, t.locale, timezone)
  const band = [
    `linear-gradient(to right,`,
    `rgb(15 22 34) 0%,`,
    `${rgb(warm, 0.55)} ${fadeShare * 35}%,`,
    `${rgb(warm)} ${fadeShare * 70}%,`,
    `${rgb(cool)} ${fadeShare * 100}%,`,
    off ? `${rgb(cool)} 96%, rgb(15 22 34) 100%)` : `${rgb(cool, 0.6)} 100%)`,
  ].join(' ')

  return (
    <div>
      <div className="relative h-5 overflow-hidden rounded-full ring-1 ring-border ring-inset" style={{ background: band }}>
        <div
          className="absolute inset-y-0 w-px bg-black/40"
          style={{ left: `${fadeShare * 100}%` }}
          aria-hidden
        />
        {now !== undefined && (
          <div
            className="absolute inset-y-0 w-1 rounded-full bg-white shadow-[0_0_8px_white]"
            style={{ left: `calc(${Math.min(1, Math.max(0, now)) * 100}% - 2px)` }}
            aria-hidden
          />
        )}
      </div>
      <div className="relative mt-2 h-10 text-sm text-muted-foreground">
        <span className="absolute left-0">
          {t.wakeup.lightStarts(time(start))}
        </span>
        <span
          className="absolute -translate-x-1/2 text-right font-medium text-foreground"
          style={{ left: `${fadeShare * 100}%`, top: '1.25rem' }}
        >
          {time(full)}
        </span>
        <span className="absolute right-0">{off ? t.wakeup.offAt(time(off)) : t.wakeup.staysOn}</span>
      </div>
    </div>
  )
}

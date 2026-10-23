import { Sunrise, Sunset } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'

import { useActions } from '@/api/actions'
import type { Daylight, DaylightCurve, Snapshot } from '@/api/types'
import { Field, NumberSelect } from '@/components/fields'
import { Button } from '@/components/ui/button'
import { useT } from '@/i18n'
import { EVENING_RANGE, MORNING_RANGE, OFFSET_STEP, dayPoints, formatOffset, kelvinAt, movePoint } from '@/lib/daylight'
import type { DayPoints, DaylightPoint } from '@/lib/daylight'
import { formatTime } from '@/lib/format'
import { kelvinToRgb, rgb } from '@/lib/light-color'
import { useNow } from '@/lib/screen'

const HOUR = 3_600_000
const BAND_STOPS = 48

function curveOf(daylight: Daylight): DaylightCurve {
  const { warm_kelvin, cool_kelvin, morning_start, morning_end, evening_start, evening_end } = daylight
  return { warm_kelvin, cool_kelvin, morning_start, morning_end, evening_start, evening_end }
}

function kelvins(from: number, to: number): number[] {
  const list: number[] = []
  for (let k = Math.ceil(from / 100) * 100; k <= to; k += 100) list.push(k)
  return list
}

/** The daylight curve: warmths, and when the light cools after sunrise and warms before sunset. */
export function DaylightSettings({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const now = useNow(60_000).getTime()
  const daylight = snapshot.daylight
  // Shows the saved curve until you edit; then your draft until it is saved.
  const [draft, setDraft] = useState<DaylightCurve | null>(null)
  const curve = draft ?? curveOf(daylight)
  const time = (ms: number) => formatTime(new Date(ms), t.locale, snapshot.timezone)
  const points = daylight.sunrise && daylight.sunset ? dayPoints(curve, daylight.sunrise, daylight.sunset) : null
  const move = (point: DaylightPoint, minutes: number) => setDraft(movePoint(curve, point, minutes))

  const save = async () => {
    if (await actions.daylight(curve)) {
      setDraft(null)
      toast.success(t.daylight.saved)
    }
  }

  const lamps = snapshot.lights.filter((l) => daylight.lights.includes(l.ieee) && l.caps.supports_ct)
  const kMin = lamps.length ? Math.min(...lamps.map((l) => l.kelvin_range[0])) : 2200
  const kMax = lamps.length ? Math.max(...lamps.map((l) => l.kelvin_range[1])) : 4000
  const kelvinNow = points
    ? kelvinAt(now, curve, points)
    : daylight.polar === 'day'
      ? curve.cool_kelvin
      : daylight.polar === 'night'
        ? curve.warm_kelvin
        : null
  const status =
    daylight.polar === 'day'
      ? t.daylight.polarDay
      : daylight.polar === 'night'
        ? t.daylight.polarNight
        : daylight.sunrise && daylight.sunset
          ? t.daylight.today(time(Date.parse(daylight.sunrise)), time(Date.parse(daylight.sunset)))
          : t.daylight.noPlace

  const slider = (point: DaylightPoint, label: string, range: [number, number], sunrise: boolean) => {
    const at = points
      ? { morning_start: points.morningStart, morning_end: points.morningEnd, evening_start: points.eveningStart, evening_end: points.eveningEnd }[point]
      : null
    const offset = formatOffset(curve[point])
    return (
      <OffsetSlider
        label={label}
        value={curve[point]}
        range={range}
        at={at === null ? null : time(at)}
        anchor={sunrise ? t.daylight.sunrise(offset) : t.daylight.sunset(offset)}
        onChange={(minutes) => move(point, minutes)}
      />
    )
  }

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-medium">{t.daylight.title}</h2>
        <p className="mt-1 text-muted-foreground">{t.daylight.help}</p>
      </div>
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">{status}</p>
        {points && daylight.sunrise && daylight.sunset && (
          <DayBand curve={curve} points={points} sunrise={Date.parse(daylight.sunrise)} sunset={Date.parse(daylight.sunset)} now={now} time={time} />
        )}
        {kelvinNow !== null && <p className="text-base tabular-nums">{t.daylight.now(kelvinNow)}</p>}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t.daylight.warm}>
          <NumberSelect
            value={curve.warm_kelvin}
            options={kelvins(Math.max(1500, kMin), curve.cool_kelvin - 100)}
            label={(k) => `${k} K`}
            onChange={(v) => setDraft({ ...curve, warm_kelvin: v })}
          />
        </Field>
        <Field label={t.daylight.cool}>
          <NumberSelect
            value={curve.cool_kelvin}
            options={kelvins(curve.warm_kelvin + 100, Math.min(6500, kMax))}
            label={(k) => `${k} K`}
            onChange={(v) => setDraft({ ...curve, cool_kelvin: v })}
          />
        </Field>
      </div>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-medium">{t.daylight.morning}</legend>
        {slider('morning_start', t.daylight.startsCooling, MORNING_RANGE, true)}
        {slider('morning_end', t.daylight.fullyCool, MORNING_RANGE, true)}
      </fieldset>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-medium">{t.daylight.evening}</legend>
        {slider('evening_start', t.daylight.startsWarming, EVENING_RANGE, false)}
        {slider('evening_end', t.daylight.fullyWarm, EVENING_RANGE, false)}
      </fieldset>
      <Button className="self-start" disabled={!draft} onClick={save}>
        {t.daylight.save}
      </Button>
    </section>
  )
}

interface OffsetSliderProps {
  label: string
  value: number // minutes from the sun
  range: [number, number]
  at: string | null // the clock time today
  anchor: string // "sunrise + 30 min"
  onChange: (minutes: number) => void
}

function OffsetSlider({ label, value, range, at, anchor, onChange }: OffsetSliderProps) {
  const id = useId()
  const text = at ? `${at}, ${anchor}` : anchor
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <label htmlFor={id} className="text-sm text-muted-foreground">
          {label}
        </label>
        <span className="text-sm tabular-nums">
          {at && <span className="mr-2 text-base font-medium">{at}</span>}
          <span className="text-muted-foreground">{anchor}</span>
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={range[0]}
        max={range[1]}
        step={OFFSET_STEP}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={text}
        className="h-10 w-full accent-[var(--ember)]"
      />
    </div>
  )
}

interface DayBandProps {
  curve: DaylightCurve
  points: DayPoints
  sunrise: number
  sunset: number
  now: number
  time: (ms: number) => string
}

/** Today's light from three hours before sunrise to three after sunset, in its own colours. */
function DayBand({ curve, points, sunrise, sunset, now, time }: DayBandProps) {
  const from = sunrise + (MORNING_RANGE[0] / 60) * HOUR
  const to = sunset + (EVENING_RANGE[1] / 60) * HOUR
  const share = (ms: number) => Math.min(100, Math.max(0, ((ms - from) / (to - from)) * 100))
  const stops = Array.from({ length: BAND_STOPS + 1 }, (_, i) => {
    const ms = from + ((to - from) * i) / BAND_STOPS
    return `${rgb(kelvinToRgb(kelvinAt(ms, curve, points)))} ${((i / BAND_STOPS) * 100).toFixed(1)}%`
  })
  const marks = [
    { ms: sunrise, Icon: Sunrise },
    { ms: sunset, Icon: Sunset },
  ]
  return (
    <div aria-hidden className="pb-6">
      <div className="relative h-10 rounded-xl" style={{ background: `linear-gradient(to right, ${stops.join(', ')})` }}>
        {now > from && now < to && (
          <span className="absolute inset-y-[-4px] w-0.5 rounded bg-foreground" style={{ left: `${share(now)}%` }} />
        )}
        {marks.map(({ ms, Icon }) => (
          <span
            key={ms}
            className="absolute top-full mt-1 flex -translate-x-1/2 items-center gap-1 text-xs whitespace-nowrap text-muted-foreground tabular-nums"
            style={{ left: `${share(ms)}%` }}
          >
            <Icon className="size-3.5" />
            {time(ms)}
          </span>
        ))}
      </div>
    </div>
  )
}

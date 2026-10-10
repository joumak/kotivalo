import { Activity, Menu, Sunrise } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'

import { useActions } from '@/api/actions'
import { useLive } from '@/api/live'
import type { Lamp, Snapshot } from '@/api/types'
import { SunriseBand } from '@/components/sunrise-band'
import { Button } from '@/components/ui/button'
import { MasterSwitch } from '@/components/master-switch'
import { WeatherLine } from '@/components/weather-line'
import { useT } from '@/i18n'
import { formatTime, levelPercent, percentToLevel, weekdayName } from '@/lib/format'
import { glowStrength, rgb } from '@/lib/light-color'
import { isLit, lampColor, lampStatus, sensorFor } from '@/lib/lamp-state'
import { isNight } from '@/lib/night'
import { byRoom } from '@/lib/rooms'
import { useNow } from '@/lib/screen'
import { useLiveValue } from '@/lib/use-live-value'
import { cn } from '@/lib/utils'

const NIGHT_AWAKE_MS = 60_000 // after a touch at night, show the lamps this long

/** Moves fixed content a few pixels each minute so a screen left on doesn't burn in. */
function burnInShift(now: Date, range: number): { x: number; y: number } {
  const minute = Math.floor(now.getTime() / 60000)
  const x = ((minute * 37) % (2 * range + 1)) - range
  const y = ((minute * 23) % (2 * range + 1)) - range
  return { x, y }
}

export function PanelDashboard({ onMenu }: { onMenu: () => void }) {
  const { snapshot } = useLive()
  const now = useNow(1000)
  const [awakeUntil, setAwakeUntil] = useState(0)
  if (!snapshot) return <div className="h-dvh bg-black" />

  const night = isNight(now, snapshot)
  if (night && now.getTime() >= awakeUntil) {
    return <NightScreen snapshot={snapshot} now={now} onWake={() => setAwakeUntil(Date.now() + NIGHT_AWAKE_MS)} />
  }
  const shift = burnInShift(now, 3)
  return (
    <div
      className={cn('h-dvh overflow-hidden bg-background', night && 'opacity-75')}
      onPointerDown={() => night && setAwakeUntil(Date.now() + NIGHT_AWAKE_MS)}
    >
      <div
        className="grid h-full gap-8 p-[max(1.5rem,env(safe-area-inset-top))] landscape:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] portrait:grid-rows-[auto_1fr]"
        style={{ transform: `translate(${shift.x}px, ${shift.y}px)` }}
      >
        <ClockColumn snapshot={snapshot} now={now} onMenu={onMenu} night={night} />
        <div className="flex min-h-0 flex-col gap-4">
          <MasterSwitch snapshot={snapshot} size="lg" className="self-end" />
          <div className="min-h-0 grow overflow-y-auto">
            <LampGrid snapshot={snapshot} />
          </div>
        </div>
      </div>
    </div>
  )
}

function ClockColumn({ snapshot, now, onMenu, night }: { snapshot: Snapshot; now: Date; onMenu: () => void; night: boolean }) {
  const t = useT()
  const actions = useActions()
  const tz = snapshot.timezone
  const [next] = snapshot.upcoming
  const run = snapshot.sunrise
  const { ramp } = snapshot.wakeup
  const clock = now.toLocaleTimeString(t.locale, { hour: 'numeric', minute: '2-digit', timeZone: tz })
  const date = now.toLocaleDateString(t.locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: tz })
  return (
    <div className="flex min-w-0 flex-col justify-between gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p
            className={cn(
              'leading-[0.85] font-medium tracking-tighter tabular-nums',
              'text-[clamp(5.5rem,17vw,14rem)] portrait:text-[clamp(5.5rem,24vw,13rem)]',
              night && 'text-ember',
            )}
          >
            {clock}
          </p>
          <p className="mt-3 text-[clamp(1.25rem,2.6vw,2rem)] text-muted-foreground first-letter:uppercase">{date}</p>
          <WeatherLine snapshot={snapshot} size="panel" className="mt-4" />
        </div>
        <Button size="icon-lg" variant="ghost" aria-label={t.panel.menu} onClick={onMenu}>
          <Menu className="size-6" />
        </Button>
      </div>
      <div className="flex flex-col gap-4">
        {run ? (
          <>
            <p className="flex items-center gap-3 text-2xl">
              <Sunrise className="size-7 text-ember" />
              {t.wakeup.fullAt(formatTime(run.end, t.locale, tz))}
            </p>
            <SunriseBand
              start={run.start}
              full={run.end}
              off={run.off}
              warmKelvin={ramp.warm_kelvin}
              coolKelvin={ramp.cool_kelvin}
              timezone={tz}
              now={(now.getTime() - Date.parse(run.start)) / (Date.parse(run.off ?? run.end) - Date.parse(run.start))}
            />
          </>
        ) : next ? (
          <div className="flex flex-wrap items-center gap-4">
            <p className={cn('flex items-center gap-3 text-2xl', next.skipped && 'text-muted-foreground line-through')}>
              <Sunrise className="size-7 text-ember" />
              {t.panel.alarm(weekdayName(next.alarm, t.locale, tz, false), formatTime(next.alarm, t.locale, tz))}
            </p>
            <Button variant="outline" size="lg" onClick={() => actions.skip(next.key, !next.skipped)}>
              {next.skipped ? t.wakeup.unskip : t.wakeup.skip}
            </Button>
          </div>
        ) : (
          <p className="text-2xl text-muted-foreground">{t.panel.noAlarm}</p>
        )}
      </div>
    </div>
  )
}

/** Every lamp visible at once (no scrolling on a wall): one grid that fills the column. */
function LampGrid({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const lamps = byRoom(snapshot.lights, t.lamp.noRoom).flatMap(([room, list]) =>
    list.map((lamp) => ({ room, lamp })),
  )
  return (
    <div className="grid h-full auto-rows-[minmax(8.5rem,1fr)] grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-4">
      {lamps.map(({ room, lamp }) => (
        <PanelTile key={lamp.ieee} lamp={lamp} room={room} snapshot={snapshot} />
      ))}
    </div>
  )
}

/**
 * A large lamp tile: tap to switch, press and drag up or down to set brightness.
 * The tile fills from the bottom with the lamp's own light.
 */
function PanelTile({ lamp, room, snapshot }: { lamp: Lamp; room: string; snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const ieee = lamp.ieee
  const lit = isLit(lamp)
  const send = useCallback((percent: number) => void actions.lamp(ieee, 'level', percentToLevel(percent)), [actions, ieee])
  const level = useLiveValue(lit ? levelPercent(lamp.state.level) : 0, send)
  const drag = useRef<{ y: number; start: number; height: number; moved: boolean } | null>(null)
  const color = lampColor(lamp)
  const sensor = sensorFor(lamp, snapshot)
  const strength = glowStrength(lit ? percentToLevel(level.value) : 0)

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    const height = event.currentTarget.getBoundingClientRect().height
    drag.current = { y: event.clientY, start: level.value, height, moved: false }
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dy = d.y - event.clientY
    if (!d.moved && Math.abs(dy) < 10) return
    d.moved = true
    level.change(Math.round(Math.min(100, Math.max(1, d.start + (dy / d.height) * 100))))
  }
  const onPointerUp = () => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.moved) level.commit(Math.max(1, level.value))
    else void actions.lamp(ieee, 'toggle')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      void actions.lamp(ieee, 'toggle')
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      level.commit(Math.min(100, Math.max(1, level.value + (event.key === 'ArrowUp' ? 10 : -10))))
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={lit}
      aria-label={`${lamp.name}, ${lampStatus(lamp, snapshot, t)}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => (drag.current = null)}
      onKeyDown={onKeyDown}
      className={cn(
        'relative flex touch-none flex-col justify-between overflow-hidden rounded-3xl border bg-card p-5 select-none',
        'focus-visible:ring-4 focus-visible:ring-ring/60 focus-visible:outline-none',
        lamp.error && 'border-dashed',
      )}
      style={lit ? { boxShadow: `0 0 ${Math.round(48 * strength)}px ${rgb(color, 0.2 * strength)}` } : undefined}
    >
      {lit && (
        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 transition-[height] duration-150"
          style={{
            height: `${level.value}%`,
            background: `linear-gradient(to top, ${rgb(color, 0.75 * strength + 0.15)}, ${rgb(color, 0.25 * strength)})`,
          }}
        />
      )}
      <span className="relative flex flex-col gap-0.5">
        <span className={cn('flex items-center gap-2 text-sm', lit && level.value > 80 ? 'text-black/60' : 'text-muted-foreground')}>
          {room}
          {sensor && (
            <Activity
              className={cn('size-4', sensor.occupied && 'text-ember')}
              aria-label={sensor.occupied ? t.sensor.occupied : t.sensor.empty}
            />
          )}
        </span>
        <span className="text-xl leading-tight font-medium text-balance">{lamp.name}</span>
      </span>
      <span className={cn('relative text-lg tabular-nums', lit && level.value > 45 ? 'text-black/75' : 'text-muted-foreground')}>
        {lampStatus(lamp, snapshot, t)}
      </span>
    </div>
  )
}

/** Night: almost black, a dim warm clock that drifts to avoid burn-in. The first touch only wakes. */
function NightScreen({ snapshot, now, onWake }: { snapshot: Snapshot; now: Date; onWake: () => void }) {
  const t = useT()
  const shift = burnInShift(now, 40)
  const clock = now.toLocaleTimeString(t.locale, { hour: 'numeric', minute: '2-digit', timeZone: snapshot.timezone })
  const [next] = snapshot.upcoming
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <button
      ref={ref}
      type="button"
      onPointerDown={(event) => {
        event.preventDefault()
        onWake()
      }}
      onKeyDown={onWake}
      aria-label={t.panel.tapToWake}
      className="grid h-dvh w-full place-items-center bg-black outline-none"
    >
      <div style={{ transform: `translate(${shift.x}px, ${shift.y}px)` }} className="text-center">
        <p
          className="text-[clamp(4rem,13vw,10rem)] leading-none font-medium tracking-tighter tabular-nums"
          style={{ color: 'rgb(255 147 44 / 0.42)' }}
        >
          {clock}
        </p>
        {next && !next.skipped && (
          <p className="mt-4 flex items-center justify-center gap-2 text-xl" style={{ color: 'rgb(255 147 44 / 0.28)' }}>
            <Sunrise className="size-5" />
            {formatTime(next.alarm, t.locale, snapshot.timezone)}
          </p>
        )}
      </div>
    </button>
  )
}

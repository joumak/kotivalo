import { Menu, Sunrise } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useActions } from '@/api/actions'
import { useLive } from '@/api/live'
import type { Snapshot } from '@/api/types'
import { LampCard } from '@/components/lamp-card'
import { LampSheet, useLampSheet } from '@/components/lamp-sheet'
import { SunriseBand } from '@/components/sunrise-band'
import { Button } from '@/components/ui/button'
import { MasterSwitch } from '@/components/master-switch'
import { WeatherLine } from '@/components/weather-line'
import { useT } from '@/i18n'
import { formatTime, weekdayName } from '@/lib/format'
import { isNight } from '@/lib/night'
import { byRoom } from '@/lib/rooms'
import { useIdle, useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'

const NIGHT_AWAKE_MS = 60_000 // after a touch at night, show the lamps this long
const SHEET_IDLE_MS = 60_000 // a lamp's controls left open close by themselves

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
  const sheet = useLampSheet()
  useIdle(sheet.open, SHEET_IDLE_MS, sheet.close)
  if (!snapshot) return <div className="h-dvh bg-black" />

  const night = isNight(now, snapshot)
  const asleep = night && now.getTime() >= awakeUntil
  const shift = burnInShift(now, 3)
  return (
    <>
      {asleep ? (
        <NightScreen snapshot={snapshot} now={now} onWake={() => setAwakeUntil(Date.now() + NIGHT_AWAKE_MS)} />
      ) : (
        <div
          className={cn('flex h-dvh items-center justify-center overflow-hidden overscroll-none bg-background', night && 'opacity-75')}
          onPointerDown={() => night && setAwakeUntil(Date.now() + NIGHT_AWAKE_MS)} // at night, touches keep it showing
        >
          <div
            className="grid h-full max-h-[64rem] w-full max-w-[100rem] gap-8 p-[max(1.5rem,env(safe-area-inset-top))] landscape:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] portrait:grid-rows-[auto_1fr]"
            style={{ transform: `translate(${shift.x}px, ${shift.y}px)` }}
          >
            <ClockColumn snapshot={snapshot} now={now} onMenu={onMenu} night={night} />
            <div className="flex min-h-0 flex-col gap-4">
              <MasterSwitch snapshot={snapshot} size="lg" className="self-end" />
              <div className="min-h-0 grow overflow-y-auto overscroll-contain">
                <LampGrid snapshot={snapshot} onControls={sheet.show} />
              </div>
            </div>
          </div>
        </div>
      )}
      {/* A React parent of the sheet's portal: touches inside the sheet count too. */}
      <div onPointerDown={() => night && setAwakeUntil(Date.now() + NIGHT_AWAKE_MS)}>
        <LampSheet snapshot={snapshot} sheet={{ ...sheet, open: sheet.open && !asleep }} />
      </div>
    </>
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
              'text-[clamp(5.5rem,min(17vw,30vh),14rem)] portrait:text-[clamp(5.5rem,24vw,13rem)]',
              night && 'text-ember',
            )}
          >
            {clock}
          </p>
          <p className="mt-3 text-[clamp(1.25rem,2.6vw,2rem)] text-muted-foreground first-letter:uppercase">{date}</p>
          <WeatherLine snapshot={snapshot} variant="panel" className="mt-4" />
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
function LampGrid({ snapshot, onControls }: { snapshot: Snapshot; onControls: (ieee: string, opener: HTMLElement) => void }) {
  const t = useT()
  const lamps = byRoom(snapshot.lights, t.lamp.noRoom).flatMap(([room, list]) =>
    list.map((lamp) => ({ room, lamp })),
  )
  return (
    <div className="grid h-full auto-rows-[minmax(8.5rem,1fr)] grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-4">
      {lamps.map(({ room, lamp }) => (
        <LampCard
          key={lamp.ieee}
          lamp={lamp}
          snapshot={snapshot}
          room={room}
          size="panel"
          onControls={(opener) => onControls(lamp.ieee, opener)}
        />
      ))}
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
        <div className="mt-3" style={{ color: 'rgb(255 147 44 / 0.28)' }}>
          <WeatherLine snapshot={snapshot} variant="night" />
        </div>
      </div>
    </button>
  )
}

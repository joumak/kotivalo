import { useState } from 'react'
import { toast } from 'sonner'

import { useActions } from '@/api/actions'
import { useLive } from '@/api/live'
import type { Alarm, Ramp, Snapshot } from '@/api/types'
import { Field, NumberSelect } from '@/components/fields'
import { PageTitle } from '@/components/shell'
import { SunriseBand } from '@/components/sunrise-band'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useT } from '@/i18n'
import { formatClockTime, formatTime, minutesBetween, weekdayName, weekdayNames } from '@/lib/format'
import { useLayout } from '@/lib/layout'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'

const DURATIONS = [10, 15, 20, 30, 45, 60]
const HOLDS = [0, 15, 30, 60, 90, 120]
const NONE = 'none'

export function WakeupPage() {
  const t = useT()
  const { snapshot } = useLive()
  const layout = useLayout()
  if (!snapshot) return null
  const columns = layout === 'short' || layout === 'wide'
  return (
    <>
      <PageTitle>{t.nav.wakeup}</PageTitle>
      <div className={cn('grid gap-8', columns && 'grid-cols-2 items-start gap-10')}>
        <div className="flex flex-col gap-8">
          {snapshot.sunrise ? <RunningSunrise snapshot={snapshot} /> : <NextAlarm snapshot={snapshot} />}
          <WeekStrip snapshot={snapshot} />
        </div>
        <SunriseSettings snapshot={snapshot} />
      </div>
    </>
  )
}

function NextAlarm({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const now = useNow(30000)
  const [next, ...later] = snapshot.upcoming
  const { ramp } = snapshot.wakeup
  if (!next) return <p className="text-lg text-muted-foreground">{t.wakeup.noAlarm}</p>

  const tz = snapshot.timezone
  const off = ramp.hold_min ? new Date(Date.parse(next.alarm) + ramp.hold_min * 60000).toISOString() : null
  return (
    <section className="flex flex-col gap-5">
      <div className={cn(next.skipped && 'opacity-50')}>
        <p className="text-7xl leading-none font-semibold tracking-tight tabular-nums">
          {formatTime(next.alarm, t.locale, tz)}
        </p>
        <p className="mt-2 text-lg">
          {next.skipped
            ? t.wakeup.skipped
            : minutesBetween(now.getTime(), next.alarm) < 24 * 60
              ? t.wakeup.when(
                  weekdayName(next.alarm, t.locale, tz),
                  t.time.inTime(minutesBetween(now.getTime(), next.alarm)),
                )
              : weekdayName(next.alarm, t.locale, tz)}
        </p>
      </div>
      <SunriseBand
        start={next.start}
        full={next.alarm}
        off={off}
        warmKelvin={ramp.warm_kelvin}
        coolKelvin={ramp.cool_kelvin}
        timezone={tz}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => actions.skip(next.key, !next.skipped)}>
          {next.skipped ? t.wakeup.unskip : t.wakeup.skip}
        </Button>
      </div>
      {later.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm text-muted-foreground">{t.wakeup.later}</h2>
          <ul className="divide-y rounded-2xl border">
            {later.slice(0, 3).map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <span className={cn('tabular-nums', item.skipped && 'text-muted-foreground line-through')}>
                  {weekdayName(item.alarm, t.locale, tz)} {formatTime(item.alarm, t.locale, tz)}
                </span>
                <Button size="sm" variant="ghost" onClick={() => actions.skip(item.key, !item.skipped)}>
                  {item.skipped ? t.wakeup.unskip : t.wakeup.skip}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function RunningSunrise({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const now = useNow(5000)
  const run = snapshot.sunrise!
  const { ramp } = snapshot.wakeup
  const endMs = Date.parse(run.off ?? run.end)
  const position = (now.getTime() - Date.parse(run.start)) / (endMs - Date.parse(run.start))
  return (
    <section className="flex flex-col gap-5 rounded-3xl border border-ember/40 bg-ember/5 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">{run.kind === 'test' ? t.wakeup.testRunning : t.wakeup.running}</h2>
          <p className="mt-1 text-muted-foreground">{t.wakeup.fullAt(formatTime(run.end, t.locale, snapshot.timezone))}</p>
        </div>
        <Button variant="destructive" onClick={() => actions.stopSunrise()}>
          {t.wakeup.stop}
        </Button>
      </div>
      <SunriseBand
        start={run.start}
        full={run.end}
        off={run.off}
        warmKelvin={ramp.warm_kelvin}
        coolKelvin={ramp.cool_kelvin}
        timezone={snapshot.timezone}
        now={position}
      />
    </section>
  )
}

function WeekStrip({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const [editing, setEditing] = useState<number | null>(null)
  const alarms = snapshot.wakeup.alarms
  const short = weekdayNames(t.locale, 'short')
  const long = weekdayNames(t.locale, 'long')

  const save = async (day: number, alarm: Alarm) => {
    const next = alarms.map((a, i) => (i === day ? alarm : a))
    if (await actions.wakeup({ alarms: next })) setEditing(null)
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-medium">{t.wakeup.days}</h2>
      <div className="grid grid-cols-7 gap-1.5">
        {alarms.map((alarm, day) => (
          <button
            key={day}
            type="button"
            onClick={() => setEditing(day)}
            aria-label={`${long[day]}: ${alarm.enabled ? formatClockTime(alarm.time, t.locale) : t.wakeup.dayOff}`}
            className={cn(
              'flex min-h-16 flex-col items-center justify-center gap-1 rounded-2xl border px-1 py-2 transition-colors',
              'focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none',
              alarm.enabled ? 'border-ember/50 bg-ember/15' : 'bg-card text-muted-foreground',
            )}
          >
            <span className="text-sm capitalize">{short[day]}</span>
            <span className={cn('text-sm tabular-nums', alarm.enabled && 'font-medium')}>
              {alarm.enabled ? formatClockTime(alarm.time, t.locale) : t.wakeup.dayOff}
            </span>
          </button>
        ))}
      </div>
      {editing !== null && (
        <AlarmDialog
          weekday={long[editing]}
          alarm={alarms[editing]}
          onCancel={() => setEditing(null)}
          onSave={(alarm) => save(editing, alarm)}
        />
      )}
    </section>
  )
}

interface AlarmDialogProps {
  weekday: string
  alarm: Alarm
  onCancel: () => void
  onSave: (alarm: Alarm) => void
}

function AlarmDialog({ weekday, alarm, onCancel, onSave }: AlarmDialogProps) {
  const t = useT()
  const [enabled, setEnabled] = useState(alarm.enabled)
  const [time, setTime] = useState(alarm.time)
  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t.wakeup.editTitle(weekday)}</DialogTitle>
          <DialogDescription className="sr-only">{t.wakeup.enabled}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-5 py-2">
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="alarm-enabled" className="text-base">
              {t.wakeup.enabled}
            </Label>
            <Switch id="alarm-enabled" checked={enabled} onCheckedChange={setEnabled} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="alarm-time" className="text-base">
              {t.wakeup.time}
            </Label>
            <Input
              id="alarm-time"
              type="time"
              value={time}
              required
              disabled={!enabled}
              onChange={(event) => setTime(event.target.value)}
              className="h-12 w-36 text-center text-xl tabular-nums"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            {t.wakeup.cancel}
          </Button>
          <Button disabled={enabled && !time} onClick={() => onSave({ enabled, time: time || alarm.time })}>
            {t.wakeup.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SunriseSettings({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  // Shows the saved ramp until you edit; then your draft until it is saved.
  const [draft, setDraft] = useState<Ramp | null>(null)
  const ramp = draft ?? snapshot.wakeup.ramp
  const dirty = draft !== null

  const change = (patch: Partial<Ramp>) => setDraft({ ...ramp, ...patch })
  const save = async () => {
    if (await actions.wakeup({ ramp })) {
      setDraft(null)
      toast.success(t.wakeup.saved)
    }
  }

  const lamp = snapshot.lights.find((l) => l.ieee === snapshot.wakeup.light)
  const [kMin, kMax] = lamp?.kelvin_range ?? [2200, 4000]
  const kelvins = (from: number, to: number) => {
    const list: number[] = []
    for (let k = Math.ceil(from / 100) * 100; k <= to; k += 100) list.push(k)
    return list
  }

  return (
    <section className="flex flex-col gap-5">
      <h2 className="text-lg font-medium">{t.wakeup.sunrise}</h2>
      <Field label={t.wakeup.lamp}>
        <Select
          value={snapshot.wakeup.light ?? NONE}
          onValueChange={(value) => actions.wakeup({ light: value === NONE ? null : value })}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder={t.wakeup.noLamp} />
          </SelectTrigger>
          <SelectContent>
            {snapshot.lights
              .filter((l) => l.caps.dimmable) // a sunrise has to dim
              .map((l) => (
              <SelectItem key={l.ieee} value={l.ieee}>
                {l.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t.wakeup.duration}>
          <NumberSelect
            value={ramp.duration_min}
            options={DURATIONS}
            label={t.wakeup.minutes}
            onChange={(v) => change({ duration_min: v })}
          />
        </Field>
        <Field label={t.wakeup.switchOff}>
          <NumberSelect
            value={ramp.hold_min}
            options={HOLDS}
            label={(n) => (n === 0 ? t.wakeup.never : t.wakeup.after(n))}
            onChange={(v) => change({ hold_min: v })}
          />
        </Field>
        <Field label={t.wakeup.startWarmth}>
          <NumberSelect
            value={ramp.warm_kelvin}
            options={kelvins(Math.max(1500, kMin), ramp.cool_kelvin)}
            label={(k) => `${k} K`}
            onChange={(v) => change({ warm_kelvin: v })}
          />
        </Field>
        <Field label={t.wakeup.endWarmth}>
          <NumberSelect
            value={ramp.cool_kelvin}
            options={kelvins(ramp.warm_kelvin, Math.min(6500, kMax))}
            label={(k) => `${k} K`}
            onChange={(v) => change({ cool_kelvin: v })}
          />
        </Field>
      </div>
      <Field label={t.wakeup.curve}>
        <input
          type="range"
          min={1}
          max={4}
          step={0.1}
          value={ramp.gamma}
          onChange={(event) => change({ gamma: Number(event.target.value) })}
          className="h-10 w-full accent-[var(--ember)]"
          aria-label={t.wakeup.curve}
        />
        <div className="flex justify-between text-sm text-muted-foreground">
          <span>{t.wakeup.curveEven}</span>
          <span>{t.wakeup.curveSlow}</span>
        </div>
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!dirty} onClick={save}>
          {t.wakeup.saveSunrise}
        </Button>
        <span className="ml-auto text-sm text-muted-foreground">{t.wakeup.tryIt}</span>
        {[2, 5].map((minutes) => (
          <Button
            key={minutes}
            variant="outline"
            disabled={!snapshot.wakeup.light}
            onClick={() => actions.testSunrise(minutes)}
          >
            {t.wakeup.minutes(minutes)}
          </Button>
        ))}
      </div>
      <LastAlarm snapshot={snapshot} />
    </section>
  )
}

function LastAlarm({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const last = snapshot.last_run
  if (!last) return null
  const kind = last.result.split(':')[0]
  const result = t.wakeup.result[kind] ?? last.result
  return (
    <p className="text-sm text-muted-foreground">
      {t.wakeup.lastAlarm(result, formatTime(last.finished, t.locale, snapshot.timezone))}
    </p>
  )
}




import {
  Activity,
  CircleHelp,
  Gamepad2,
  LampCeiling,
  Lightbulb,
  Plug,
  Pencil,
  SlidersHorizontal,
  Sunrise,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import { useActions } from '@/api/actions'
import { useLive } from '@/api/live'
import type { DeviceInfo, DeviceKind, MotionRule, Profile, Remote, Sensor, Snapshot } from '@/api/types'
import { PageTitle } from '@/components/shell'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
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
import type { Messages } from '@/i18n/en'
import { formatClockTime, levelPercent, percentToLevel } from '@/lib/format'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'

const KINDS: DeviceKind[] = ['light', 'motion', 'remote', 'other']
const ICONS = { light: Lightbulb, motion: Activity, remote: Gamepad2, other: CircleHelp, fixture: LampCeiling }
const PAIR_SECONDS = 254

export function DevicesPage() {
  const t = useT()
  const { snapshot } = useLive()
  const [renaming, setRenaming] = useState<DeviceInfo | null>(null)
  const [removing, setRemoving] = useState<DeviceInfo | null>(null)
  const [motion, setMotion] = useState<Sensor | null>(null)
  const [remote, setRemote] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [fixture, setFixture] = useState<DeviceInfo | 'new' | null>(null)
  if (!snapshot) return null

  const rooms = [...new Set(snapshot.devices.map((d) => d.room).filter(Boolean))].sort()
  const editing = motion && snapshot.sensors.find((s) => s.ieee === motion.ieee)
  const editingRemote = remote && snapshot.remotes.find((r) => r.ieee === remote)
  return (
    <>
      <PageTitle action={<Button onClick={() => setAdding(true)}>{t.devices.add}</Button>}>{t.nav.devices}</PageTitle>
      <PairingStatus snapshot={snapshot} />
      {snapshot.devices.length === 0 && <p className="text-muted-foreground">{t.devices.empty}</p>}
      <div className="flex max-w-3xl flex-col gap-7">
        {KINDS.map((kind) => {
          // Fixtures come first among the lamps, each followed by its bulbs.
          const list =
            kind === 'light' ? lampsWithFixtures(snapshot.devices) : snapshot.devices.filter((d) => d.kind === kind)
          if (list.length === 0) return null
          const bulbs = snapshot.devices.filter((d) => d.kind === 'light')
          return (
            <section key={kind}>
              <div className="mb-3 flex items-center justify-between gap-4">
                <h2 className="text-lg font-medium text-muted-foreground">{t.devices.kinds[kind]}</h2>
                {kind === 'light' && bulbs.length > 1 && (
                  <Button variant="outline" size="sm" onClick={() => setFixture('new')}>
                    <LampCeiling data-icon="inline-start" />
                    {t.fixture.create}
                  </Button>
                )}
              </div>
              <ul className="divide-y rounded-2xl border bg-card">
                {list.map((device) => (
                    <DeviceRow
                      key={device.ieee}
                      device={device}
                      sensor={snapshot.sensors.find((s) => s.ieee === device.ieee)}
                      remote={snapshot.remotes.find((r) => r.ieee === device.ieee)}
                      onRename={() => setRenaming(device)}
                      onRemove={() => setRemoving(device)}
                      onMotion={(sensor) => setMotion(sensor)}
                      onRemote={(r) => setRemote(r.ieee)}
                      onFixture={() => setFixture(device)}
                      fixtureName={snapshot.devices.find((d) => d.ieee === device.fixture)?.name}
                    />
                  ))}
              </ul>
            </section>
          )
        })}
      </div>
      {adding && <AddDeviceDialog snapshot={snapshot} onClose={() => setAdding(false)} />}
      {renaming && <RenameDialog device={renaming} rooms={rooms} onClose={() => setRenaming(null)} />}
      {removing && <RemoveDialog device={removing} onClose={() => setRemoving(null)} />}
      {editing && <MotionDialog sensor={editing} snapshot={snapshot} onClose={() => setMotion(null)} />}
      {editingRemote && <RemoteDialog remote={editingRemote} snapshot={snapshot} onClose={() => setRemote(null)} />}
      {fixture && (
        <FixtureDialog
          fixture={fixture === 'new' ? null : (snapshot.devices.find((d) => d.ieee === fixture.ieee) ?? null)}
          devices={snapshot.devices}
          rooms={rooms}
          onClose={() => setFixture(null)}
        />
      )}
    </>
  )
}

/** Lamps for the device list: each fixture followed by its bulbs, then the other lamps,
 * a multi-channel device's channels together. */
function lampsWithFixtures(devices: DeviceInfo[]): DeviceInfo[] {
  const byName = (a: DeviceInfo, b: DeviceInfo) => a.name.localeCompare(b.name)
  const fixtures = devices.filter((d) => d.kind === 'fixture').sort(byName)
  const single = devices.filter((d) => d.kind === 'light' && !d.fixture && !d.parent).sort(byName)
  const channels = (device: DeviceInfo) =>
    devices.filter((d) => d.parent === device.ieee && !d.fixture).sort((a, b) => (a.channel ?? 0) - (b.channel ?? 0))
  return [
    ...fixtures.flatMap((f) => [f, ...devices.filter((d) => d.fixture === f.ieee).sort(byName)]),
    ...single.flatMap((d) => [d, ...channels(d)]),
  ]
}

function pairingLeft(snapshot: Snapshot, now: Date): number {
  return snapshot.pairing_until
    ? Math.max(0, Math.round((Date.parse(snapshot.pairing_until) - now.getTime()) / 1000))
    : 0
}

/** While pairing is open: the countdown and what joined, visible on the page itself. */
function PairingStatus({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const left = pairingLeft(snapshot, useNow(1000))
  if (left === 0) return null
  return (
    <div role="status" className="mb-6 max-w-3xl rounded-3xl border border-ember/40 bg-ember/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <p className="text-lg font-medium tabular-nums">{t.devices.pairing(left)}</p>
        <Button variant="outline" onClick={() => actions.permit(0)}>
          {t.devices.stopPairing}
        </Button>
      </div>
      {snapshot.last_event && <p className="mt-3 text-sm">{snapshot.last_event}</p>}
    </div>
  )
}

/** Choose what you are adding, read how to put it into pairing mode, then pair. */
function AddDeviceDialog({ snapshot, onClose }: { snapshot: Snapshot; onClose: () => void }) {
  const t = useT()
  const actions = useActions()
  const left = pairingLeft(snapshot, useNow(1000))
  const [kind, setKind] = useState<'light' | 'motion' | 'remote' | null>(null)
  const choices = { light: t.devices.addLamp, motion: t.devices.addSensor, remote: t.devices.addRemote }
  const help = { light: t.devices.pairHelp, motion: t.devices.sensorHelp, remote: t.devices.remoteHelp }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.devices.addTitle}</DialogTitle>
          <DialogDescription>{kind === null ? t.devices.addWhat : null}</DialogDescription>
        </DialogHeader>
        {kind === null ? (
          <div className="grid gap-3 sm:grid-cols-3">
            {(['light', 'motion', 'remote'] as const).map((choice) => {
              const Icon = ICONS[choice]
              return (
                <button
                  key={choice}
                  type="button"
                  onClick={() => setKind(choice)}
                  className="flex min-h-28 flex-col items-start justify-between gap-3 rounded-2xl border bg-card p-4 text-left text-base transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none"
                >
                  <Icon className="size-6 text-ember" />
                  {choices[choice]}
                </button>
              )
            })}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="max-w-prose">{help[kind]}</p>
            {kind === 'motion' && <p className="max-w-prose text-sm text-muted-foreground">{t.devices.sensorBatteries}</p>}
            {left > 0 && (
              <div role="status" className="rounded-2xl border border-ember/40 bg-ember/10 px-4 py-3">
                <p className="font-medium tabular-nums">{t.devices.pairing(left)}</p>
                {snapshot.last_event && <p className="mt-1 text-sm">{snapshot.last_event}</p>}
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t.devices.close}
          </Button>
          {kind !== null &&
            (left > 0 ? (
              <Button variant="outline" onClick={() => actions.permit(0)}>
                {t.devices.stopPairing}
              </Button>
            ) : (
              <Button onClick={() => actions.permit(PAIR_SECONDS)}>{t.devices.startPairing}</Button>
            ))}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface DeviceRowProps {
  device: DeviceInfo
  sensor?: Sensor
  remote?: Remote
  onRename: () => void
  onRemove: () => void
  onMotion: (sensor: Sensor) => void
  onRemote: (remote: Remote) => void
  onFixture: () => void
  fixtureName?: string
}

function DeviceRow({ device, sensor, remote, onRename, onRemove, onMotion, onRemote, onFixture, fixtureName }: DeviceRowProps) {
  const t = useT()
  const actions = useActions()
  const now = useNow(60000)
  const Icon = device.kind === 'light' && !device.dimmable ? Plug : ICONS[device.kind]
  const seen = !device.paired
    ? t.devices.notSeen
    : device.last_seen
      ? t.devices.seen(t.time.ago(Math.round((now.getTime() / 1000 - device.last_seen) / 60)))
      : null
  const minutesSince = (iso: string) => Math.max(0, Math.round((now.getTime() - Date.parse(iso)) / 60000))
  const details = sensor
    ? [
        sensor.occupied ? t.sensor.occupied : t.sensor.empty,
        sensor.lux !== null ? t.sensor.lux(sensor.lux) : null,
        sensor.bright !== null ? (sensor.bright ? t.sensor.bright : t.sensor.dim) : null,
        sensor.battery !== null ? t.sensor.battery(sensor.battery) : null,
      ]
    : remote
      ? [
          remote.last_action && remote.last_press
            ? t.remote.lastPress(t.remote.actions[remote.last_action], t.time.ago(minutesSince(remote.last_press)))
            : seen,
          remote.battery !== null ? t.sensor.battery(remote.battery) : null,
        ]
      : device.kind === 'fixture'
        ? [t.fixture.count(device.members.length), device.wakeup ? t.lamp.wakeupLamp : null]
        : [
            device.channel ? t.devices.channel(device.channel) : null,
            fixtureName ? t.fixture.partOf(fixtureName) : null,
            device.wakeup ? t.lamp.wakeupLamp : null,
            device.parent ? null : seen,
          ]
  // What to do next, on a line of its own.
  const firmware = remote?.firmware
  const hint = firmware
    ? firmware.state === 'updating'
      ? t.remote.firmware.updating(Math.floor(firmware.progress))
      : t.remote.firmware[firmware.state]
    : sensor && !sensor.configured
      ? t.sensor.notConfigured
      : remote && !remote.configured
        ? t.remote.notConfigured
        : remote && remote.lights.length === 0
          ? t.remote.noLamps
          : null
  return (
    <li className={cn('flex items-center gap-4 px-4 py-3', (device.fixture || device.parent) && 'pl-10')}>
      <Icon
        className={cn(
          'size-5 shrink-0',
          device.wakeup || sensor?.occupied ? 'text-ember' : 'text-muted-foreground',
        )}
      />
      <div className="min-w-0 grow">
        <p className="truncate font-medium">{device.name}</p>
        <p className="text-sm text-muted-foreground">{[device.room, ...details].filter(Boolean).join(', ')}</p>
        {hint && <p className="mt-1 text-sm text-ember">{hint}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {sensor && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.sensor.settings(device.name)}
            title={t.sensor.settings(device.name)}
            onClick={() => onMotion(sensor)}
          >
            <SlidersHorizontal />
          </Button>
        )}
        {remote && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.remote.settings(device.name)}
            title={t.remote.settings(device.name)}
            onClick={() => onRemote(remote)}
          >
            <SlidersHorizontal />
          </Button>
        )}
        {device.kind === 'fixture' && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.fixture.settings(device.name)}
            title={t.fixture.settings(device.name)}
            onClick={onFixture}
          >
            <SlidersHorizontal />
          </Button>
        )}
        {((device.kind === 'light' && !device.fixture) || device.kind === 'fixture') && device.dimmable && !device.wakeup && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.devices.useForWakeup}
            title={t.devices.useForWakeup}
            onClick={() => actions.wakeup({ light: device.ieee })}
          >
            <Sunrise />
          </Button>
        )}
        <Button size="icon" variant="ghost" aria-label={t.devices.rename} title={t.devices.rename} onClick={onRename}>
          <Pencil />
        </Button>
        {!device.parent && ( // a channel goes with its device
          <Button size="icon" variant="ghost" aria-label={t.devices.remove} title={t.devices.remove} onClick={onRemove}>
            <Trash2 />
          </Button>
        )}
      </div>
    </li>
  )
}

/** Which lamps a remote's buttons control. */
function RemoteDialog({ remote, snapshot, onClose }: { remote: Remote; snapshot: Snapshot; onClose: () => void }) {
  const t = useT()
  const actions = useActions()
  const [lights, setLights] = useState<string[]>(remote.lights)
  const save = async () => {
    if (await actions.remote(remote.ieee, lights)) onClose()
  }
  const updating = remote.firmware?.state === 'waiting' || remote.firmware?.state === 'updating'
  const updateFirmware = async () => {
    if (await actions.updateFirmware(remote.ieee)) onClose()
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.remote.settings(remote.name)}</DialogTitle>
          <DialogDescription>{t.remote.legend}</DialogDescription>
        </DialogHeader>
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-2 text-sm text-muted-foreground">{t.remote.lamps}</legend>
          {snapshot.lights.map((lamp) => {
            const id = `remote-lamp-${lamp.ieee}`
            return (
              <div key={lamp.ieee} className="flex items-center justify-between gap-4 py-1.5">
                <Label htmlFor={id} className="text-base">
                  {lamp.name}
                </Label>
                <Switch
                  id={id}
                  checked={lights.includes(lamp.ieee)}
                  onCheckedChange={(on) => setLights(on ? [...lights, lamp.ieee] : lights.filter((x) => x !== lamp.ieee))}
                />
              </div>
            )
          })}
        </fieldset>
        <div className="flex flex-col items-start gap-2 border-t pt-4">
          <p className="max-w-prose text-sm text-muted-foreground">{t.remote.updateHelp}</p>
          <Button variant="outline" disabled={updating} onClick={updateFirmware}>
            {t.remote.updateFirmware}
          </Button>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t.wakeup.cancel}
          </Button>
          <Button onClick={save}>{t.remote.save}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const DARK_LUX = [5, 10, 30, 50, 100, 200]
const OFF_AFTER = [1, 2, 5, 10, 15, 30]
const PERCENTS = [5, 10, 20, 30, 50, 75, 100]
const KELVINS = [2200, 2500, 2700, 3000, 3500, 4000]
const ALWAYS = 'always'
const DIM = 'dim'

function defaultRule(sensor: string): MotionRule {
  return {
    sensor,
    lights: [],
    enabled: true,
    dark_lux: 30,
    off_after_min: 5,
    day: { level: 254, kelvin: 2700 },
    night: { level: 13, kelvin: 2200 },
  }
}

/** Which lamps a motion sensor switches on, when, and how bright. */
function MotionDialog({ sensor, snapshot, onClose }: { sensor: Sensor; snapshot: Snapshot; onClose: () => void }) {
  const t = useT()
  const actions = useActions()
  const [rule, setRule] = useState<MotionRule>(() => sensor.rule ?? defaultRule(sensor.ieee))
  const change = (patch: Partial<MotionRule>) => setRule((r) => ({ ...r, ...patch }))
  const takenBy = (lamp: string) =>
    snapshot.sensors.find((s) => s.ieee !== sensor.ieee && s.rule?.lights.includes(lamp))

  const save = async () => {
    const { sensor: _, ...body } = rule
    if (await actions.motion(sensor.ieee, body)) onClose()
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.sensor.settings(sensor.name)}</DialogTitle>
          <DialogDescription>
            {[
              sensor.occupied ? t.sensor.occupied : t.sensor.empty,
              sensor.lux !== null ? t.sensor.lux(sensor.lux) : null,
              sensor.bright !== null ? (sensor.bright ? t.sensor.bright : t.sensor.dim) : null,
            ]
              .filter(Boolean)
              .join(', ')}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-6">
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="motion-enabled" className="text-base">
              {t.sensor.enabled}
            </Label>
            <Switch id="motion-enabled" checked={rule.enabled} onCheckedChange={(enabled) => change({ enabled })} />
          </div>

          <fieldset className="flex flex-col gap-1" disabled={!rule.enabled}>
            <legend className="mb-2 text-sm text-muted-foreground">{t.sensor.lamps}</legend>
            {snapshot.lights.map((lamp) => {
              const other = takenBy(lamp.ieee)
              const id = `motion-lamp-${lamp.ieee}`
              return (
                <div key={lamp.ieee} className="flex items-center justify-between gap-4 py-1.5">
                  <Label htmlFor={id} className={cn('flex flex-col items-start gap-0.5 text-base', other && 'opacity-50')}>
                    {lamp.name}
                    {other && <span className="text-sm text-muted-foreground">{t.sensor.takenBy(other.name)}</span>}
                  </Label>
                  <Switch
                    id={id}
                    disabled={!!other}
                    checked={rule.lights.includes(lamp.ieee)}
                    onCheckedChange={(on) =>
                      change({ lights: on ? [...rule.lights, lamp.ieee] : rule.lights.filter((x) => x !== lamp.ieee) })
                    }
                  />
                </div>
              )
            })}
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2">
            {sensor.bright !== null ? (
              // It only tells bright from dim: any threshold means "only when it is dim".
              <Field label={t.sensor.when} hint={t.sensor.luxNow(sensor.bright ? t.sensor.bright : t.sensor.dim)}>
                <Select
                  value={rule.dark_lux === null ? ALWAYS : DIM}
                  onValueChange={(v) => change({ dark_lux: v === ALWAYS ? null : 30 })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DIM}>{t.sensor.onlyDim}</SelectItem>
                    <SelectItem value={ALWAYS}>{t.sensor.always}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            ) : (
              <Field label={t.sensor.darkerThan} hint={sensor.lux !== null ? t.sensor.luxNow(t.sensor.lux(sensor.lux)) : undefined}>
                <Select
                  value={rule.dark_lux === null ? ALWAYS : String(rule.dark_lux)}
                  onValueChange={(v) => change({ dark_lux: v === ALWAYS ? null : Number(v) })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DARK_LUX.map((lux) => (
                      <SelectItem key={lux} value={String(lux)}>
                        {t.sensor.lux(lux)}
                      </SelectItem>
                    ))}
                    <SelectItem value={ALWAYS}>{t.sensor.always}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            )}
            <Field label={t.sensor.offAfter}>
              <NumberSelect value={rule.off_after_min} options={OFF_AFTER} label={t.sensor.minutes} onChange={(v) => change({ off_after_min: v })} />
            </Field>
          </div>

          <ProfileFields title={t.sensor.day} profile={rule.day} onChange={(day) => change({ day })} t={t} />
          <ProfileFields
            title={t.sensor.night}
            hint={t.sensor.nightHint(formatClockTime(snapshot.night.start, t.locale), formatClockTime(snapshot.night.end, t.locale))}
            profile={rule.night}
            onChange={(night) => change({ night })}
            t={t}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t.wakeup.cancel}
          </Button>
          <Button onClick={save}>{t.sensor.save}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProfileFields({
  title,
  hint,
  profile,
  onChange,
  t,
}: {
  title: string
  hint?: string
  profile: Profile
  onChange: (profile: Profile) => void
  t: Messages
}) {
  return (
    <fieldset>
      <legend className="text-base font-medium">{title}</legend>
      {hint && <p className="mb-2 text-sm text-muted-foreground">{hint}</p>}
      <div className="mt-2 grid grid-cols-2 gap-4">
        <Field label={t.sensor.brightness}>
          <NumberSelect
            value={levelPercent(profile.level)}
            options={PERCENTS}
            label={(p) => `${p} %`}
            onChange={(p) => onChange({ ...profile, level: percentToLevel(p) })}
          />
        </Field>
        <Field label={t.sensor.warmth}>
          <NumberSelect value={profile.kelvin} options={KELVINS} label={(k) => `${k} K`} onChange={(kelvin) => onChange({ ...profile, kelvin })} />
        </Field>
      </div>
    </fieldset>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
    </div>
  )
}

function NumberSelect({
  value,
  options,
  label,
  onChange,
}: {
  value: number
  options: number[]
  label: (value: number) => string
  onChange: (value: number) => void
}) {
  const all = options.includes(value) ? options : [...options, value].sort((a, b) => a - b)
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {all.map((option) => (
          <SelectItem key={option} value={String(option)}>
            {label(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function RenameDialog({ device, rooms, onClose }: { device: DeviceInfo; rooms: string[]; onClose: () => void }) {
  const t = useT()
  const actions = useActions()
  const [name, setName] = useState(device.name)
  const [room, setRoom] = useState(device.room)
  const save = async () => {
    if (await actions.device(device.ieee, { name, room })) onClose()
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.devices.rename}</DialogTitle>
          <DialogDescription>{device.model ?? device.ieee}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="device-name">{t.devices.name}</Label>
            <Input id="device-name" value={name} maxLength={40} required onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="device-room">{t.devices.room}</Label>
            <Input
              id="device-room"
              value={room}
              maxLength={40}
              list="known-rooms"
              placeholder={t.devices.roomHint}
              onChange={(e) => setRoom(e.target.value)}
            />
            <datalist id="known-rooms">
              {rooms.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t.wakeup.cancel}
            </Button>
            <Button type="submit" disabled={!name.trim()}>
              {t.wakeup.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RemoveDialog({ device, onClose }: { device: DeviceInfo; onClose: () => void }) {
  const t = useT()
  const actions = useActions()
  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t.devices.removeTitle(device.name)}</AlertDialogTitle>
          <AlertDialogDescription>
            {device.kind === 'fixture' ? t.devices.removeFixtureBody : t.devices.removeBody}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t.wakeup.cancel}</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-white hover:bg-destructive/90"
            onClick={() => void actions.removeDevice(device.ieee).then(onClose)}
          >
            {t.devices.remove}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** Group bulbs (a lamp's spots) into a fixture, or change a fixture's bulbs. */
function FixtureDialog({
  fixture,
  devices,
  rooms,
  onClose,
}: {
  fixture: DeviceInfo | null
  devices: DeviceInfo[]
  rooms: string[]
  onClose: () => void
}) {
  const t = useT()
  const actions = useActions()
  const [name, setName] = useState('')
  const [room, setRoom] = useState('')
  const [members, setMembers] = useState<string[]>(fixture?.members ?? [])
  const bulbs = devices.filter((d) => d.kind === 'light').sort((a, b) => a.name.localeCompare(b.name))
  const save = async () => {
    const done = fixture
      ? await actions.updateFixture(fixture.ieee, members)
      : await actions.createFixture({ name: name.trim(), room: room.trim(), members })
    if (done) onClose()
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{fixture ? t.fixture.settings(fixture.name) : t.fixture.title}</DialogTitle>
          <DialogDescription>{t.fixture.help}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          {!fixture && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="fixture-name">{t.devices.name}</Label>
                <Input id="fixture-name" value={name} maxLength={40} required onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="fixture-room">{t.devices.room}</Label>
                <Input
                  id="fixture-room"
                  value={room}
                  maxLength={40}
                  list="fixture-rooms"
                  placeholder={t.devices.roomHint}
                  onChange={(e) => setRoom(e.target.value)}
                />
                <datalist id="fixture-rooms">
                  {rooms.map((r) => (
                    <option key={r} value={r} />
                  ))}
                </datalist>
              </div>
            </div>
          )}
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-2 text-sm text-muted-foreground">{t.fixture.bulbs}</legend>
            {bulbs.map((bulb) => {
              const other = bulb.fixture && bulb.fixture !== fixture?.ieee ? devices.find((d) => d.ieee === bulb.fixture) : undefined
              const id = `fixture-bulb-${bulb.ieee}`
              return (
                <div key={bulb.ieee} className="flex items-center justify-between gap-4 py-1.5">
                  <Label htmlFor={id} className={cn('flex flex-col items-start gap-0.5 text-base', other && 'opacity-50')}>
                    {bulb.name}
                    {other && <span className="text-sm text-muted-foreground">{t.fixture.inOther(other.name)}</span>}
                  </Label>
                  <Switch
                    id={id}
                    disabled={!!other}
                    checked={members.includes(bulb.ieee)}
                    onCheckedChange={(on) =>
                      setMembers(on ? [...members, bulb.ieee] : members.filter((m) => m !== bulb.ieee))
                    }
                  />
                </div>
              )
            })}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t.wakeup.cancel}
            </Button>
            <Button type="submit" disabled={members.length === 0 || (!fixture && !name.trim())}>
              {t.fixture.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

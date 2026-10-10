import { Activity, CircleHelp, Gamepad2, Lightbulb, Pencil, Sunrise, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useActions } from '@/api/actions'
import { useLive } from '@/api/live'
import type { DeviceInfo, DeviceKind, Snapshot } from '@/api/types'
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
import { useT } from '@/i18n'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'

const KINDS: DeviceKind[] = ['light', 'motion', 'remote', 'other']
const ICONS = { light: Lightbulb, motion: Activity, remote: Gamepad2, other: CircleHelp }
const PAIR_SECONDS = 254

export function DevicesPage() {
  const t = useT()
  const { snapshot } = useLive()
  const [renaming, setRenaming] = useState<DeviceInfo | null>(null)
  const [removing, setRemoving] = useState<DeviceInfo | null>(null)
  if (!snapshot) return null

  const rooms = [...new Set(snapshot.devices.map((d) => d.room).filter(Boolean))].sort()
  return (
    <>
      <PageTitle>{t.nav.devices}</PageTitle>
      <Pairing snapshot={snapshot} />
      {snapshot.devices.length === 0 && <p className="text-muted-foreground">{t.devices.empty}</p>}
      <div className="flex max-w-3xl flex-col gap-7">
        {KINDS.map((kind) => {
          const list = snapshot.devices.filter((d) => d.kind === kind)
          if (list.length === 0) return null
          return (
            <section key={kind}>
              <h2 className="mb-3 text-lg font-medium text-muted-foreground">{t.devices.kinds[kind]}</h2>
              <ul className="divide-y rounded-2xl border bg-card">
                {list
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((device) => (
                    <DeviceRow
                      key={device.ieee}
                      device={device}
                      onRename={() => setRenaming(device)}
                      onRemove={() => setRemoving(device)}
                    />
                  ))}
              </ul>
            </section>
          )
        })}
      </div>
      {renaming && <RenameDialog device={renaming} rooms={rooms} onClose={() => setRenaming(null)} />}
      {removing && <RemoveDialog device={removing} onClose={() => setRemoving(null)} />}
    </>
  )
}

function Pairing({ snapshot }: { snapshot: Snapshot }) {
  const t = useT()
  const actions = useActions()
  const now = useNow(1000)
  const left = snapshot.pairing_until
    ? Math.max(0, Math.round((Date.parse(snapshot.pairing_until) - now.getTime()) / 1000))
    : 0
  if (left === 0) {
    return (
      <Button className="mb-6" onClick={() => actions.permit(PAIR_SECONDS)}>
        {t.devices.add}
      </Button>
    )
  }
  return (
    <div role="status" className="mb-6 max-w-3xl rounded-3xl border border-ember/40 bg-ember/10 p-5">
      <div className="mb-2 flex items-center justify-between gap-4">
        <p className="text-lg font-medium tabular-nums">{t.devices.pairing(left)}</p>
        <Button variant="outline" onClick={() => actions.permit(0)}>
          {t.devices.stopPairing}
        </Button>
      </div>
      <p className="max-w-prose text-muted-foreground">{t.devices.pairHelp}</p>
      {snapshot.last_event && <p className="mt-3 text-sm">{snapshot.last_event}</p>}
    </div>
  )
}

interface DeviceRowProps {
  device: DeviceInfo
  onRename: () => void
  onRemove: () => void
}

function DeviceRow({ device, onRename, onRemove }: DeviceRowProps) {
  const t = useT()
  const actions = useActions()
  const now = useNow(60000)
  const Icon = ICONS[device.kind]
  const seen = !device.paired
    ? t.devices.notSeen
    : device.last_seen
      ? t.devices.seen(t.time.ago(Math.round((now.getTime() / 1000 - device.last_seen) / 60)))
      : null
  return (
    <li className="flex items-center gap-4 px-4 py-3">
      <Icon className={cn('size-5 shrink-0', device.wakeup ? 'text-ember' : 'text-muted-foreground')} />
      <div className="min-w-0 grow">
        <p className="truncate font-medium">{device.name}</p>
        <p className="truncate text-sm text-muted-foreground">
          {[device.room, device.wakeup ? t.lamp.wakeupLamp : null, seen].filter(Boolean).join(', ')}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {device.kind === 'light' && !device.wakeup && (
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
        <Button size="icon" variant="ghost" aria-label={t.devices.remove} title={t.devices.remove} onClick={onRemove}>
          <Trash2 />
        </Button>
      </div>
    </li>
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
          <AlertDialogDescription>{t.devices.removeBody}</AlertDialogDescription>
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

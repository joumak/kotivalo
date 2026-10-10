import { Activity } from 'lucide-react'
import { useState } from 'react'

import { useLive } from '@/api/live'
import type { Lamp, Snapshot } from '@/api/types'
import { useActions } from '@/api/actions'
import { LampControls, LampTile } from '@/components/lamp'
import { PageTitle } from '@/components/shell'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/components/ui/drawer'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { MasterSwitch } from '@/components/master-switch'
import { WeatherLine } from '@/components/weather-line'
import { useT } from '@/i18n'
import { glowStyle, isLit, lampStatus, motionMode } from '@/lib/lamp-state'
import { useLayout } from '@/lib/layout'
import { byRoom } from '@/lib/rooms'
import { cn } from '@/lib/utils'

export function LightsPage() {
  const t = useT()
  const { snapshot } = useLive()
  const layout = useLayout()
  const [selected, setSelected] = useState<string | null>(null)
  if (!snapshot) return null

  const lamps = snapshot.lights
  const wide = layout === 'wide'
  const current = lamps.find((l) => l.ieee === selected) ?? (wide ? lamps[0] : undefined)
  const rooms = byRoom(lamps, t.lamp.noRoom)

  // Rooms sit side by side where there is room; a room with many lamps spans both columns.
  const twoColumns = layout !== 'phone'
  const grid = (
    <div className={cn('grid gap-x-6 gap-y-7', twoColumns && 'grid-cols-2')}>
      {lamps.length === 0 && <p className="text-muted-foreground">{t.lamp.noLamps}</p>}
      {rooms.map(([room, list]) => (
        <section key={room} aria-label={room} className={cn(twoColumns && list.length > 2 && 'col-span-2')}>
          <h2 className="mb-3 text-lg font-medium text-muted-foreground">{room}</h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
            {list.map((lamp) => (
              <LampTile
                key={lamp.ieee}
                lamp={lamp}
                snapshot={snapshot}
                selected={wide && current?.ieee === lamp.ieee}
                onSelect={() => setSelected(lamp.ieee)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )

  if (wide) {
    return (
      <>
        <PageTitle action={<MasterSwitch snapshot={snapshot} />}>{t.nav.lights}</PageTitle>
        <WeatherLine snapshot={snapshot} className="-mt-2 mb-6" />
        <div className="grid grid-cols-[1fr_minmax(18rem,24rem)] items-start gap-8">
          {grid}
          <aside className="sticky top-4 rounded-3xl border bg-card p-6" style={current ? glowStyle(current, 0.5) : {}}>
            {current ? (
              <ControlPanel lamp={current} snapshot={snapshot} vertical />
            ) : (
              <p className="text-muted-foreground">{t.lamp.pickOne}</p>
            )}
          </aside>
        </div>
      </>
    )
  }

  const close = () => setSelected(null)
  return (
    <>
      <PageTitle action={<MasterSwitch snapshot={snapshot} />}>{t.nav.lights}</PageTitle>
      <WeatherLine snapshot={snapshot} className="-mt-2 mb-6" />
      {grid}
      {layout === 'short' ? (
        <Sheet open={!!current} onOpenChange={(open) => !open && close()}>
          <SheetContent side="right" className="overflow-y-auto">
            {current && <ControlPanel lamp={current} snapshot={snapshot} sheet />}
          </SheetContent>
        </Sheet>
      ) : (
        <Drawer open={!!current} onOpenChange={(open) => !open && close()}>
          <DrawerContent className="px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
            {current && <ControlPanel lamp={current} snapshot={snapshot} drawer />}
          </DrawerContent>
        </Drawer>
      )}
    </>
  )
}

interface ControlPanelProps {
  lamp: Lamp
  snapshot: Snapshot
  vertical?: boolean
  drawer?: boolean
  sheet?: boolean
}

function ControlPanel({ lamp, snapshot, vertical, drawer, sheet }: ControlPanelProps) {
  const t = useT()
  const actions = useActions()
  const status = lampStatus(lamp, snapshot, t)
  const power = (
    <Switch
      checked={isLit(lamp)}
      onCheckedChange={(on) => actions.lamp(lamp.ieee, on ? 'on' : 'off')}
      aria-label={isLit(lamp) ? t.lamp.turnOff(lamp.name) : t.lamp.turnOn(lamp.name)}
      className="scale-125"
    />
  )
  const heading = drawer ? (
    <DrawerHeader className="flex-row items-center justify-between gap-4 px-0 text-left">
      <div className="text-left">
        <DrawerTitle className="text-xl">{lamp.name}</DrawerTitle>
        <DrawerDescription>{status}</DrawerDescription>
      </div>
      {power}
    </DrawerHeader>
  ) : sheet ? (
    <SheetHeader className="flex-row items-center justify-between gap-4 px-0">
      <div>
        <SheetTitle className="text-xl">{lamp.name}</SheetTitle>
        <SheetDescription>{status}</SheetDescription>
      </div>
      {power}
    </SheetHeader>
  ) : (
    <div className="mb-6 flex items-center justify-between gap-4">
      <div>
        <h2 className="text-xl font-medium">{lamp.name}</h2>
        <p className="text-sm text-muted-foreground">{status}</p>
      </div>
      {power}
    </div>
  )
  return (
    <div className={cn(sheet && 'px-4', vertical && 'flex h-[min(34rem,70dvh)] flex-col')}>
      {heading}
      <div className={cn(vertical && 'min-h-0 grow')}>
        <LampControls lamp={lamp} orientation={vertical ? 'vertical' : 'horizontal'} />
      </div>
      <MotionMode lamp={lamp} />
    </div>
  )
}

/** Says whether the motion sensor switches the lamp, and hands it back after a manual switch. */
function MotionMode({ lamp }: { lamp: Lamp }) {
  const t = useT()
  const actions = useActions()
  const mode = motionMode(lamp)
  if (!mode) return null
  const text = { motion: t.lamp.motionControls, byHand: t.lamp.motionByHand, waits: t.lamp.motionWaits }[mode]
  return (
    <div className="mt-6 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2">
      <p className="flex grow basis-48 items-start gap-2 text-sm text-muted-foreground">
        <Activity aria-hidden className="mt-0.5 size-4 shrink-0" />
        {text}
      </p>
      {mode !== 'motion' && (
        <Button variant="outline" onClick={() => void actions.lamp(lamp.ieee, 'auto')}>
          {t.lamp.letMotionControl}
        </Button>
      )}
    </div>
  )
}

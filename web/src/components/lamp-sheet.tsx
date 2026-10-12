import { Activity, Hand, X } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import type { RefObject } from 'react'

import { useActions } from '@/api/actions'
import type { Lamp, Snapshot } from '@/api/types'
import { LampControls } from '@/components/lamp'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/components/ui/drawer'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { useT } from '@/i18n'
import { isLit, lampStatus, motionMode } from '@/lib/lamp-state'
import { hasRail, useLayout } from '@/lib/layout'

export interface LampSheetState {
  ieee: string | null
  open: boolean
  opener: RefObject<HTMLElement | null>
  show: (ieee: string, opener: HTMLElement) => void
  close: () => void
}

/** Which lamp's controls are open. The lamp stays set while the panel closes, so its
 * content doesn't vanish mid-animation. */
export function useLampSheet(): LampSheetState {
  const [ieee, setIeee] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const opener = useRef<HTMLElement | null>(null)
  const show = useCallback((lamp: string, element: HTMLElement) => {
    opener.current = element
    setIeee(lamp)
    setOpen(true)
  }, [])
  const close = useCallback(() => setOpen(false), [])
  return { ieee, open, opener, show, close }
}

/**
 * A lamp's controls: a side sheet where there is a side rail (landscape), a bottom drawer
 * otherwise. Render one per page, outside the cards (React events bubble through portals).
 */
export function LampSheet({ snapshot, sheet }: { snapshot: Snapshot; sheet: LampSheetState }) {
  const layout = useLayout()
  const lamp = snapshot.lights.find((l) => l.ieee === sheet.ieee)
  const open = sheet.open && !!lamp
  const onOpenChange = (next: boolean) => {
    if (!next) sheet.close()
  }
  // No Radix trigger here, so focus goes back to the ⚙ that opened it.
  const returnFocus = (event: Event) => {
    event.preventDefault()
    sheet.opener.current?.focus()
  }
  if (hasRail(layout)) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" showCloseButton={false} onCloseAutoFocus={returnFocus} className="overflow-y-auto sm:max-w-md">
          {lamp && <ControlPanel lamp={lamp} snapshot={snapshot} container="sheet" onClose={sheet.close} />}
        </SheetContent>
      </Sheet>
    )
  }
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent onCloseAutoFocus={returnFocus} className="px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        {lamp && <ControlPanel lamp={lamp} snapshot={snapshot} container="drawer" onClose={sheet.close} />}
      </DrawerContent>
    </Drawer>
  )
}

interface ControlPanelProps {
  lamp: Lamp
  snapshot: Snapshot
  container: 'sheet' | 'drawer'
  onClose: () => void
}

function ControlPanel({ lamp, snapshot, container, onClose }: ControlPanelProps) {
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
  const heading =
    container === 'drawer' ? (
      <DrawerHeader className="flex-row items-center justify-between gap-4 px-0 text-left">
        <div className="text-left">
          <DrawerTitle className="text-xl">{lamp.name}</DrawerTitle>
          <DrawerDescription>{status}</DrawerDescription>
        </div>
        {power}
      </DrawerHeader>
    ) : (
      <SheetHeader className="flex-row items-center gap-4 px-0">
        <div className="grow">
          <SheetTitle className="text-xl">{lamp.name}</SheetTitle>
          <SheetDescription>{status}</SheetDescription>
        </div>
        {power}
        <Button variant="ghost" size="icon" aria-label={t.lamp.close} onClick={onClose} className="-mr-2">
          <X className="size-5" />
        </Button>
      </SheetHeader>
    )
  return (
    <div className={container === 'sheet' ? 'px-4 pb-6' : undefined}>
      {heading}
      <LampControls lamp={lamp} />
      <MotionMode lamp={lamp} />
    </div>
  )
}

/** For lamps something automatic can switch: "hand only", and who switches it now. */
function MotionMode({ lamp }: { lamp: Lamp }) {
  if (!lamp.has_motion && !lamp.wakeup) return null
  return (
    <div className="mt-6 flex shrink-0 flex-col gap-4">
      <HandOnly lamp={lamp} />
      <MotionStatus lamp={lamp} />
    </div>
  )
}

function HandOnly({ lamp }: { lamp: Lamp }) {
  const t = useT()
  const actions = useActions()
  const id = `hand-only-${lamp.ieee}`
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-2">
        <Hand aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div>
          <Label htmlFor={id} className="text-base">
            {t.lamp.handOnly}
          </Label>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {lamp.wakeup ? `${t.lamp.handOnlyHelp} ${t.lamp.handOnlyAlarm}` : t.lamp.handOnlyHelp}
          </p>
        </div>
      </div>
      <Switch
        id={id}
        checked={lamp.hand_only}
        onCheckedChange={(on) => actions.lamp(lamp.ieee, 'hand_only', on ? 1 : 0)}
      />
    </div>
  )
}

/** Says whether the motion sensor switches the lamp, and hands it back after a manual switch. */
function MotionStatus({ lamp }: { lamp: Lamp }) {
  const t = useT()
  const actions = useActions()
  const mode = motionMode(lamp)
  if (!mode) return null
  const text = { motion: t.lamp.motionControls, byHand: t.lamp.motionByHand, waits: t.lamp.motionWaits }[mode]
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
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

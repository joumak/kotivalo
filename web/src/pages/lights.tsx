import { useLive } from '@/api/live'
import { LampCard } from '@/components/lamp-card'
import { LampSheet, useLampSheet } from '@/components/lamp-sheet'
import { MasterSwitch } from '@/components/master-switch'
import { PageTitle } from '@/components/shell'
import { WeatherLine } from '@/components/weather-line'
import { useT } from '@/i18n'
import { useLayout } from '@/lib/layout'
import { byRoom } from '@/lib/rooms'
import { cn } from '@/lib/utils'

export function LightsPage() {
  const t = useT()
  const { snapshot } = useLive()
  const layout = useLayout()
  const sheet = useLampSheet()
  if (!snapshot) return null

  const lamps = snapshot.lights
  const rooms = byRoom(lamps, t.lamp.noRoom)
  // Rooms sit side by side where there is room; a room with many lamps spans both columns.
  const twoColumns = layout !== 'phone'
  return (
    <>
      <PageTitle action={<MasterSwitch snapshot={snapshot} />}>{t.nav.lights}</PageTitle>
      <WeatherLine snapshot={snapshot} className="-mt-2 mb-6" />
      <div className={cn('grid gap-x-6 gap-y-7', twoColumns && 'grid-cols-2')}>
        {lamps.length === 0 && <p className="text-muted-foreground">{t.lamp.noLamps}</p>}
        {rooms.map(([room, list]) => (
          <section key={room} aria-label={room} className={cn(twoColumns && list.length > 2 && 'col-span-2')}>
            <h2 className="mb-3 text-lg font-medium text-muted-foreground">{room}</h2>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
              {list.map((lamp) => (
                <LampCard
                  key={lamp.ieee}
                  lamp={lamp}
                  snapshot={snapshot}
                  onControls={(opener) => sheet.show(lamp.ieee, opener)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      <LampSheet snapshot={snapshot} sheet={sheet} />
    </>
  )
}

import { Activity, Power, Sunrise } from 'lucide-react'
import { useCallback } from 'react'

import { useActions } from '@/api/actions'
import type { Lamp, Snapshot } from '@/api/types'
import { LightSlider } from '@/components/light-slider'
import { useT } from '@/i18n'
import { levelPercent, percentToLevel } from '@/lib/format'
import { glowStyle, isLit, lampColor, lampStatus, sensorFor } from '@/lib/lamp-state'
import { DEFAULT_KELVIN, kelvinToRgb, rgb } from '@/lib/light-color'
import { useLiveValue } from '@/lib/use-live-value'
import { cn } from '@/lib/utils'

interface LampTileProps {
  lamp: Lamp
  snapshot: Snapshot
  selected?: boolean
  onSelect?: () => void
}

/** A lamp as a swatch of its own light. Tap the tile to adjust it, the button to switch it. */
export function LampTile({ lamp, snapshot, selected, onSelect }: LampTileProps) {
  const t = useT()
  const actions = useActions()
  const lit = isLit(lamp)
  const color = lampColor(lamp)
  const sensor = sensorFor(lamp, snapshot)
  return (
    <div
      className={cn(
        'relative flex min-h-32 flex-col justify-between rounded-3xl border bg-card p-4 transition-shadow',
        lamp.error && 'border-dashed',
        selected && 'ring-2 ring-primary',
      )}
      style={glowStyle(lamp)}
    >
      <button
        type="button"
        onClick={onSelect}
        className="absolute inset-0 rounded-3xl focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none"
        aria-label={lamp.name}
      />
      <div className="pointer-events-none relative flex items-start justify-between gap-2">
        <span className="text-base leading-snug font-medium text-balance">{lamp.name}</span>
        <span className="mt-0.5 flex shrink-0 gap-1.5">
          {sensor && (
            <Activity
              className={cn('size-4', sensor.occupied ? 'text-ember' : 'text-muted-foreground/60')}
              aria-label={sensor.occupied ? t.sensor.occupied : t.sensor.empty}
            />
          )}
          {lamp.wakeup && <Sunrise className="size-4 text-ember" aria-label={t.lamp.wakeupLamp} />}
        </span>
      </div>
      <div className="relative flex items-end justify-between gap-2">
        <span className="pointer-events-none text-sm text-muted-foreground">{lampStatus(lamp, snapshot, t)}</span>
        <button
          type="button"
          aria-pressed={lit}
          aria-label={lit ? t.lamp.turnOff(lamp.name) : t.lamp.turnOn(lamp.name)}
          onClick={() => actions.lamp(lamp.ieee, 'toggle')}
          className={cn(
            'grid size-11 shrink-0 place-items-center rounded-full border transition-colors',
            'focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none',
            lit ? 'border-transparent text-black' : 'bg-secondary text-muted-foreground',
          )}
          style={lit ? { backgroundColor: rgb(color) } : undefined}
        >
          <Power className="size-5" />
        </button>
      </div>
    </div>
  )
}

interface LampControlsProps {
  lamp: Lamp
  orientation?: 'horizontal' | 'vertical'
}

/** Brightness and warmth, taking effect while dragging. */
export function LampControls({ lamp, orientation = 'horizontal' }: LampControlsProps) {
  const t = useT()
  const actions = useActions()
  const ieee = lamp.ieee
  const lit = isLit(lamp)

  const sendLevel = useCallback(
    (percent: number) => void actions.lamp(ieee, 'level', percentToLevel(percent)),
    [actions, ieee],
  )
  const sendKelvin = useCallback((kelvin: number) => void actions.lamp(ieee, 'kelvin', kelvin), [actions, ieee])

  const brightness = useLiveValue(lit ? levelPercent(lamp.state.level) : 0, sendLevel)
  const [kMin, kMax] = lamp.kelvin_range
  const warmth = useLiveValue(lamp.state.kelvin ?? DEFAULT_KELVIN, sendKelvin)

  const color = lit ? lampColor(lamp) : kelvinToRgb(warmth.value)
  const vertical = orientation === 'vertical'
  const direction = vertical ? 'to top' : 'to right'
  return (
    <div className={cn('flex gap-6', vertical ? 'h-full justify-center' : 'flex-col')}>
      <LightSlider
        label={t.lamp.brightness}
        valueText={brightness.value === 0 ? t.lamp.off : t.lamp.level(brightness.value)}
        value={brightness.value}
        min={1}
        max={100}
        orientation={orientation}
        track="var(--muted)"
        fill={`linear-gradient(${direction}, ${rgb(color, 0.35)}, ${rgb(color)})`}
        onChange={(v) => brightness.change(Math.max(1, v))}
        onCommit={(v) => brightness.commit(Math.max(1, v))}
      />
      {lamp.caps.supports_ct && (
        <LightSlider
          label={t.lamp.warmth}
          valueText={t.lamp.kelvin(warmth.value)}
          value={warmth.value}
          min={kMin}
          max={kMax}
          step={lamp.kelvin_step}
          orientation={orientation}
          disabled={!lit} // IKEA lamps ignore colour changes while off
          track={`linear-gradient(${direction}, ${rgb(kelvinToRgb(kMin))}, ${rgb(kelvinToRgb(kMax))})`}
          onChange={warmth.change}
          onCommit={warmth.commit}
        />
      )}
    </div>
  )
}

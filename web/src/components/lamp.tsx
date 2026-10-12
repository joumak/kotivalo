import { useCallback } from 'react'

import { useActions } from '@/api/actions'
import type { Lamp } from '@/api/types'
import { LightSlider } from '@/components/light-slider'
import { useT } from '@/i18n'
import { levelPercent, percentToLevel } from '@/lib/format'
import { isLit, lampColor } from '@/lib/lamp-state'
import { DEFAULT_KELVIN, kelvinToRgb, rgb } from '@/lib/light-color'
import { useLiveValue } from '@/lib/use-live-value'

/** Brightness and warmth, taking effect while dragging (neither for a plug). */
export function LampControls({ lamp }: { lamp: Lamp }) {
  const t = useT()
  const actions = useActions()
  const ieee = lamp.ieee
  const lit = isLit(lamp)

  const sendLevel = useCallback(
    (percent: number) => void actions.lamp(ieee, 'level', percentToLevel(percent)),
    [actions, ieee],
  )
  const sendKelvin = useCallback((kelvin: number) => void actions.lamp(ieee, 'kelvin', kelvin), [actions, ieee])

  // Off shows as 0; a lamp in an unknown state (not answering) keeps its last known level.
  const brightness = useLiveValue(lamp.state.on === false ? 0 : levelPercent(lamp.state.level), sendLevel)
  const [kMin, kMax] = lamp.kelvin_range
  const warmth = useLiveValue(lamp.state.kelvin ?? DEFAULT_KELVIN, sendKelvin)

  const color = lit ? lampColor(lamp) : kelvinToRgb(warmth.value)
  return (
    <div className="flex flex-col gap-6">
      {lamp.caps.dimmable && (
        <LightSlider
          label={t.lamp.brightness}
          valueText={brightness.value === 0 ? t.lamp.off : t.lamp.level(brightness.value)}
          value={brightness.value}
          min={1}
          max={100}
          track="var(--muted)"
          fill={`linear-gradient(to right, ${rgb(color, 0.35)}, ${rgb(color)})`}
          onChange={(v) => brightness.change(Math.max(1, v))}
          onCommit={(v) => brightness.commit(Math.max(1, v))}
        />
      )}
      {lamp.caps.supports_ct && (
        <LightSlider
          label={t.lamp.warmth}
          valueText={t.lamp.kelvin(warmth.value)}
          value={warmth.value}
          min={kMin}
          max={kMax}
          step={lamp.kelvin_step}
          disabled={!lit} // IKEA lamps ignore colour changes while off
          track={`linear-gradient(to right, ${rgb(kelvinToRgb(kMin))}, ${rgb(kelvinToRgb(kMax))})`}
          onChange={warmth.change}
          onCommit={warmth.commit}
        />
      )}
    </div>
  )
}

import { Activity, Hand, Settings, Sunrise } from 'lucide-react'
import { useCallback, useId } from 'react'
import type { CSSProperties } from 'react'

import { useActions } from '@/api/actions'
import type { Lamp, Snapshot } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useT } from '@/i18n'
import { levelPercent, percentToLevel } from '@/lib/format'
import { isLit, lampColor, lampStatus, sensorFor } from '@/lib/lamp-state'
import { glowStrength, rgb } from '@/lib/light-color'
import { useDragLevel } from '@/lib/use-drag-level'
import { useLiveValue } from '@/lib/use-live-value'
import { cn } from '@/lib/utils'

const DARK_TEXT_FROM = 45 // brightness (%) from which text over the light turns dark

interface LampCardProps {
  lamp: Lamp
  snapshot: Snapshot
  /** ⚙ was pressed: open the lamp's controls (focus returns to `opener` afterwards). */
  onControls: (opener: HTMLElement) => void
  /** Shown where rooms are not headings (the wall panel). */
  room?: string
  size?: 'page' | 'panel'
}

/**
 * A lamp as a swatch of its own light, the same on every screen: tap to switch, drag
 * sideways to set the brightness (the light fills the card from the left), and ⚙ for
 * warmth, "hand only" and motion.
 */
export function LampCard({ lamp, snapshot, onControls, room, size = 'page' }: LampCardProps) {
  const t = useT()
  const actions = useActions()
  const ieee = lamp.ieee
  const lit = isLit(lamp)
  const send = useCallback((percent: number) => void actions.lamp(ieee, 'level', percentToLevel(percent)), [actions, ieee])
  const level = useLiveValue(lit ? levelPercent(lamp.state.level) : 0, send)
  const { dragging, handlers } = useDragLevel(level, () => {
    level.reset()
    void actions.lamp(ieee, 'toggle')
  })
  const statusId = useId()
  const hintId = useId()

  const value = level.value // 0 while off; while an off lamp is dragged on, what it will get
  const shown = value > 0
  const dark = shown && value >= DARK_TEXT_FROM
  const color = lampColor(lamp)
  const strength = glowStrength(shown ? percentToLevel(value) : 0)
  const status = dragging ? t.lamp.level(value) : lampStatus(lamp, snapshot, t)
  const motion = !dragging && 'duration-150'
  const text = { lamp, snapshot, room, status, panel: size === 'panel' }

  return (
    <div
      className={cn(
        'relative grid overflow-hidden rounded-3xl border bg-card transition-shadow',
        size === 'panel' ? 'h-full' : 'min-h-32',
        lamp.error && 'border-dashed',
        'has-[[data-surface]:focus-visible]:outline-3 has-[[data-surface]:focus-visible]:outline-offset-2 has-[[data-surface]:focus-visible]:outline-ring/60',
      )}
      style={shown ? { boxShadow: `0 0 ${Math.round(48 * strength)}px ${rgb(color, 0.2 * strength)}` } : undefined}
    >
      <button
        type="button"
        data-surface
        aria-pressed={lit}
        aria-label={lamp.name}
        aria-describedby={`${statusId} ${hintId}`}
        {...handlers}
        className="relative touch-pan-y text-left outline-none select-none [-webkit-touch-callout:none]"
      >
        {shown && (
          <span
            aria-hidden
            className={cn('absolute inset-y-0 left-0 transition-[width]', motion)}
            style={{
              width: `${value}%`,
              background: `linear-gradient(to right, ${rgb(color, 0.8 * strength + 0.1)}, ${rgb(color, 0.6 * strength + 0.1)})`,
            }}
          />
        )}
        <CardText
          {...text}
          statusId={statusId}
          className={cn('relative transition-[clip-path]', motion)}
          style={dark ? { clipPath: `inset(0 0 0 ${value}%)` } : undefined}
        />
        {dark && (
          <CardText
            {...text}
            dark
            className={cn('absolute inset-0 transition-[clip-path]', motion)}
            style={{ clipPath: `inset(0 ${100 - value}% 0 0)` }}
          />
        )}
        <span id={hintId} className="sr-only">
          {t.lamp.cardHint}
        </span>
      </button>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t.lamp.controls(lamp.name)}
        onClick={(event) => onControls(event.currentTarget)}
        className={cn('absolute top-1.5 right-1.5', dark && value > 85 ? 'text-black/60 hover:bg-black/10' : 'text-muted-foreground')}
      >
        <Settings className="size-5" />
      </Button>
    </div>
  )
}

interface CardTextProps {
  lamp: Lamp
  snapshot: Snapshot
  room?: string
  status: string
  panel: boolean
  /** The copy drawn over the light: dark, hidden from assistive technology. */
  dark?: boolean
  statusId?: string
  className?: string
  style?: CSSProperties
}

function CardText({ lamp, snapshot, room, status, panel, dark, statusId, className, style }: CardTextProps) {
  const sensor = sensorFor(lamp, snapshot)
  const quiet = dark ? 'text-black/60' : 'text-muted-foreground'
  const icons = lamp.hand_only || sensor || lamp.wakeup
  return (
    <span
      aria-hidden={dark || undefined}
      className={cn('flex size-full flex-col justify-between gap-2', panel ? 'p-5' : 'p-4', className)}
      style={style}
    >
      <span className="flex flex-col gap-0.5 pr-9">
        {(room || icons) && (
          <span className={cn('flex min-h-5 items-center gap-1.5 text-sm', quiet)}>
            {room}
            {lamp.hand_only ? (
              <Hand aria-hidden className="size-4" />
            ) : (
              sensor && <Activity aria-hidden className={cn('size-4', sensor.occupied && !dark && 'text-ember')} />
            )}
            {lamp.wakeup && <Sunrise aria-hidden className={cn('size-4', !dark && 'text-ember')} />}
          </span>
        )}
        <span
          className={cn(
            'font-medium text-balance',
            panel ? 'text-xl leading-tight' : 'text-base leading-snug',
            dark && 'text-black/85',
          )}
        >
          {lamp.name}
        </span>
      </span>
      <span id={statusId} className={cn(panel ? 'text-lg tabular-nums' : 'text-sm', dark ? 'text-black/75' : 'text-muted-foreground')}>
        {status}
      </span>
    </span>
  )
}

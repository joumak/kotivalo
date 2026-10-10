import { Slider as SliderPrimitive } from 'radix-ui'
import type { CSSProperties } from 'react'

import { cn } from '@/lib/utils'

interface LightSliderProps {
  label: string
  valueText: string
  value: number
  min: number
  max: number
  step?: number
  /** CSS background for the track (e.g. a warm-to-cool gradient). */
  track: string
  /** Fill colour for the part below the thumb; omit for a track without fill. */
  fill?: string
  orientation?: 'horizontal' | 'vertical'
  disabled?: boolean
  onChange: (value: number) => void
  onCommit: (value: number) => void
  className?: string
}

/**
 * A thick, touch-friendly slider whose track shows the light itself. Horizontal in
 * phone drawers, a tall pillar in the tablet's control panel.
 */
export function LightSlider({
  label,
  valueText,
  value,
  min,
  max,
  step = 1,
  track,
  fill,
  orientation = 'horizontal',
  disabled,
  onChange,
  onCommit,
  className,
}: LightSliderProps) {
  const vertical = orientation === 'vertical'
  return (
    <div className={cn('flex gap-3', vertical ? 'h-full flex-col items-center' : 'flex-col', className)}>
      <div className={cn('flex items-baseline gap-2', vertical ? 'flex-col items-center gap-0' : 'justify-between')}>
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-base font-medium tabular-nums">{valueText}</span>
      </div>
      <SliderPrimitive.Root
        value={[value]}
        min={min}
        max={max}
        step={step}
        orientation={orientation}
        disabled={disabled}
        onValueChange={([v]) => onChange(v)}
        onValueCommit={([v]) => onCommit(v)}
        className={cn(
          'relative flex touch-none select-none data-disabled:opacity-40',
          vertical ? 'min-h-56 w-20 grow flex-col' : 'h-14 w-full items-center',
        )}
      >
        <SliderPrimitive.Track
          className={cn(
            'relative grow overflow-hidden rounded-2xl ring-1 ring-border ring-inset',
            vertical ? 'w-full' : 'h-full',
          )}
          style={{ background: track } as CSSProperties}
        >
          {fill && (
            <SliderPrimitive.Range
              className={cn('absolute', vertical ? 'w-full' : 'h-full')}
              style={{ background: fill }}
            />
          )}
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          aria-label={label} // the thumb carries role="slider"
          aria-valuetext={valueText}
          className={cn(
            'block rounded-full bg-white shadow-[0_0_0_2px_rgb(0_0_0/0.35)] outline-none',
            'focus-visible:ring-4 focus-visible:ring-ring/60',
            vertical ? 'h-2 w-14' : 'h-10 w-2',
          )}
        />
      </SliderPrimitive.Root>
    </div>
  )
}

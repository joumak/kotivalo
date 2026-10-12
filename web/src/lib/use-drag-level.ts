import { useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'

import type { LiveValue } from './use-live-value'

export const DRAG_SLOP_PX = 10 // a pointer that moves less is a tap
const KEY_STEP = 10
const KEY_STEPS: Record<string, number> = { ArrowRight: KEY_STEP, ArrowUp: KEY_STEP, ArrowLeft: -KEY_STEP, ArrowDown: -KEY_STEP }

export type Gesture = 'pending' | 'horizontal' | 'vertical'

/** Which way a pointer is going. A tie counts as vertical, like the browser's own scroll lock. */
export function gestureKind(dx: number, dy: number, slop = DRAG_SLOP_PX): Gesture {
  const x = Math.abs(dx)
  const y = Math.abs(dy)
  if (Math.max(x, y) < slop) return 'pending'
  return x > y ? 'horizontal' : 'vertical'
}

/** Brightness (0..100, 0 = off) after moving `delta` points from `start`. A lit lamp never
 * goes below 1; an off lamp stays off until it is moved up. */
export function shiftLevel(start: number, delta: number): number {
  const next = Math.round(Math.min(100, start + delta))
  if (next >= 1) return next
  return start > 0 ? 1 : 0
}

/** Points moved for `dx` pixels: the card's whole width is the whole range. */
export function dragDelta(dx: number, width: number): number {
  return (dx / Math.max(width, 1)) * 100
}

interface Drag {
  id: number
  x: number
  y: number
  start: number
  width: number
  kind: Gesture
  last: number | null
}

/**
 * Tap to switch, drag sideways to set the brightness: for a native button in a page that
 * scrolls (`touch-action: pan-y`), so a vertical move is left to the browser.
 *
 * The tap is the button's own click (keyboard and screen readers get it for free); the
 * click that follows a drag or a scroll is swallowed. Arrow keys step 10 %.
 */
export function useDragLevel(level: LiveValue, onTap: () => void) {
  const drag = useRef<Drag | null>(null)
  const noClick = useRef(false)
  const [dragging, setDragging] = useState(false)

  const finish = () => {
    const d = drag.current
    drag.current = null
    setDragging(false)
    if (d?.last != null) level.commit(d.last)
  }

  const handlers = {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      if (!e.isPrimary || e.button !== 0) return
      noClick.current = false
      const { width } = e.currentTarget.getBoundingClientRect()
      drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, start: level.value, width, kind: 'pending', last: null }
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const d = drag.current
      if (!d || e.pointerId !== d.id) return
      if (d.kind === 'pending') {
        const kind = gestureKind(e.clientX - d.x, e.clientY - d.y)
        if (kind === 'pending') return
        noClick.current = true
        if (kind === 'vertical') {
          drag.current = null // the page scrolls
          return
        }
        d.kind = kind
        d.x = e.clientX // count from here, so the level doesn't jump by the slop
        try {
          e.currentTarget.setPointerCapture(e.pointerId) // a mouse may leave the card
        } catch {
          // not supported: the drag still works while the pointer stays on the card
        }
        setDragging(true)
        return
      }
      const next = shiftLevel(d.start, dragDelta(e.clientX - d.x, d.width))
      if (next === 0 && d.last === null) return // an off lamp moved left stays off
      d.last = Math.max(1, next)
      level.change(d.last)
    },
    onPointerUp: (e: PointerEvent<HTMLElement>) => {
      if (drag.current && e.pointerId === drag.current.id) finish()
    },
    onLostPointerCapture: (e: PointerEvent<HTMLElement>) => {
      // A finger is captured by the element it lands on (the card's text), and moving the
      // capture to the card makes that element lose it: an event that bubbles up to here.
      if (e.target === e.currentTarget) finish()
    },
    onPointerCancel: () => {
      // The browser took the gesture (a scroll): no tap. A drag already under way keeps
      // the value the lamp has been sent.
      noClick.current = true
      finish()
    },
    onClick: () => {
      if (noClick.current) {
        noClick.current = false
        return
      }
      onTap()
    },
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      noClick.current = false
      const step = KEY_STEPS[e.key]
      if (step === undefined) return
      e.preventDefault()
      const next = shiftLevel(level.value, step)
      if (next === 0) return
      level.change(next) // shown at once
      level.commit(next)
    },
  }
  return { dragging, handlers }
}

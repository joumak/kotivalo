import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { percentToLevel } from './format'
import { dragDelta, gestureKind, shiftLevel, useDragLevel } from './use-drag-level'
import { useLiveValue } from './use-live-value'

describe('gesture helpers', () => {
  it('waits for a clear direction; a tie is a scroll', () => {
    expect(gestureKind(3, 4)).toBe('pending')
    expect(gestureKind(12, 3)).toBe('horizontal')
    expect(gestureKind(-12, 3)).toBe('horizontal')
    expect(gestureKind(5, 11)).toBe('vertical')
    expect(gestureKind(10, 10)).toBe('vertical')
  })

  it('keeps a lit lamp lit and an off lamp off until moved up', () => {
    expect(shiftLevel(40, 25)).toBe(65)
    expect(shiftLevel(95, 20)).toBe(100)
    expect(shiftLevel(40, -60)).toBe(1)
    expect(shiftLevel(0, -20)).toBe(0)
    expect(shiftLevel(0, 0.4)).toBe(0)
    expect(shiftLevel(0, 12)).toBe(12)
  })

  it('never asks for level 1, which switches an IKEA lamp off', () => {
    for (let start = 0; start <= 100; start += 7) {
      for (let delta = -120; delta <= 120; delta += 3) {
        const next = shiftLevel(start, delta)
        if (next > 0) expect(percentToLevel(next)).toBeGreaterThanOrEqual(2)
      }
    }
  })

  it('maps the card width to the whole range', () => {
    expect(dragDelta(100, 200)).toBe(50)
    expect(Number.isFinite(dragDelta(30, 0))).toBe(true)
  })
})

function Card({ remote, send, onTap }: { remote: number; send: (v: number) => void; onTap: () => void }) {
  const level = useLiveValue(remote, send)
  const { handlers } = useDragLevel(level, onTap)
  return (
    <button type="button" {...handlers}>
      <span>{level.value}</span>
    </button>
  )
}

function setup(remote = 40) {
  const send = vi.fn()
  const onTap = vi.fn()
  render(<Card remote={remote} send={send} onTap={onTap} />)
  const card = screen.getByRole('button')
  vi.spyOn(card, 'getBoundingClientRect').mockReturnValue({ width: 200, height: 120 } as DOMRect)
  const pointer = { pointerId: 1, isPrimary: true, button: 0 }
  const down = (x: number, y = 50) => fireEvent.pointerDown(card, { ...pointer, clientX: x, clientY: y })
  const move = (x: number, y = 50) => fireEvent.pointerMove(card, { ...pointer, clientX: x, clientY: y })
  const up = () => fireEvent.pointerUp(card, pointer)
  return { card, send, onTap, down, move, up }
}

describe('useDragLevel', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('taps to switch', () => {
    const { card, onTap, down, up } = setup()
    down(20)
    up()
    fireEvent.click(card)
    expect(onTap).toHaveBeenCalledTimes(1)
  })

  it('drags sideways to set the brightness, without a tap', () => {
    const { card, send, onTap, down, move, up } = setup(40)
    down(20)
    move(32) // past the slop: from here on, 100 px is 50 points
    move(132)
    expect(card.textContent).toBe('90')
    up()
    fireEvent.click(card)
    expect(send).toHaveBeenLastCalledWith(90)
    expect(onTap).not.toHaveBeenCalled()
  })

  it('leaves a vertical move to the page', () => {
    const { card, send, onTap, down, move, up } = setup()
    down(20, 50)
    move(22, 80)
    move(120, 90)
    up()
    fireEvent.click(card)
    expect(send).not.toHaveBeenCalled()
    expect(onTap).not.toHaveBeenCalled()
  })

  it('keeps an off lamp off when it is dragged left', () => {
    const { send, down, move, up } = setup(0)
    down(150)
    move(130)
    move(40)
    up()
    expect(send).not.toHaveBeenCalled()
  })

  it('sends nothing when the browser takes the gesture before a drag', () => {
    const { card, send, onTap, down, move } = setup()
    down(20)
    move(21, 52)
    fireEvent.pointerCancel(card, { pointerId: 1 })
    fireEvent.click(card)
    expect(send).not.toHaveBeenCalled()
    expect(onTap).not.toHaveBeenCalled()
  })

  it('keeps dragging when the text under a finger hands its capture to the card', () => {
    const { card, send, down, move, up } = setup(40)
    down(20)
    move(32)
    fireEvent.lostPointerCapture(card.firstElementChild!, { pointerId: 1 }) // bubbles up
    move(132)
    up()
    expect(send).toHaveBeenLastCalledWith(90)
  })

  it('keeps what a cancelled drag had reached', () => {
    const { card, send, down, move } = setup(40)
    down(20)
    move(32)
    move(72)
    fireEvent.pointerCancel(card, { pointerId: 1 })
    expect(send).toHaveBeenLastCalledWith(60)
  })

  it('steps with the arrow keys', () => {
    const { card, send } = setup(40)
    fireEvent.keyDown(card, { key: 'ArrowRight' })
    expect(send).toHaveBeenLastCalledWith(50)
    expect(card.textContent).toBe('50')
    fireEvent.keyDown(card, { key: 'ArrowLeft' })
    fireEvent.keyDown(card, { key: 'ArrowLeft' })
    expect(send).toHaveBeenLastCalledWith(30)
  })
})

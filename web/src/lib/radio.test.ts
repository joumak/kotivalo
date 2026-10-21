import { describe, expect, it } from 'vitest'

import type { Radio } from '@/api/types'

import { QUIET_MINUTES, heardMinutes, radioName, radioQuiet } from './radio'

const START = 1_800_000_000
const radio = (change: Partial<Radio> = {}): Radio => ({
  type: 'ezsp',
  fake: false,
  manufacturer: 'SONOFF',
  model: 'Dongle Plus MG24',
  firmware: '7.4.5.0 build 0',
  channel: 25,
  pan_id: '0xAE6B',
  started: START,
  heard: START + 5,
  ...change,
})
const at = (minutes: number) => (START + 5 + minutes * 60) * 1000

describe('radioName', () => {
  it('joins the maker and the model', () => {
    expect(radioName(radio())).toBe('SONOFF Dongle Plus MG24')
  })
  it('falls back to the radio type', () => {
    expect(radioName(radio({ manufacturer: null, model: null }))).toBe('ezsp')
  })
})

describe('heardMinutes', () => {
  it('counts whole minutes', () => {
    expect(heardMinutes(radio(), at(0.4))).toBe(0)
    expect(heardMinutes(radio(), at(3))).toBe(3)
  })
  it('is null before the first frame', () => {
    expect(heardMinutes(radio({ heard: null }), at(3))).toBeNull()
  })
  it('never goes negative (a clock ahead of the browser)', () => {
    expect(heardMinutes(radio(), at(-2))).toBe(0)
  })
})

describe('radioQuiet', () => {
  it('is quiet after QUIET_MINUTES without a frame', () => {
    expect(radioQuiet(radio(), at(QUIET_MINUTES - 1), true)).toBe(false)
    expect(radioQuiet(radio(), at(QUIET_MINUTES), true)).toBe(true)
  })
  it('counts from the start until the first frame', () => {
    const silent = radio({ heard: null })
    expect(radioQuiet(silent, (START + (QUIET_MINUTES - 1) * 60) * 1000, true)).toBe(false)
    expect(radioQuiet(silent, (START + QUIET_MINUTES * 60) * 1000, true)).toBe(true)
  })
  it('is never quiet with nothing paired, in test mode, or before the radio starts', () => {
    expect(radioQuiet(radio(), at(60), false)).toBe(false)
    expect(radioQuiet(radio({ fake: true }), at(60), true)).toBe(false)
    expect(radioQuiet(radio({ started: null, heard: null }), at(60), true)).toBe(false)
  })
})

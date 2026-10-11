import { describe, expect, it } from 'vitest'

import type { Lamp, Snapshot } from '@/api/types'
import { en } from '@/i18n/en'
import { fi } from '@/i18n/fi'

import { lampStatus, motionMode } from '@/lib/lamp-state'

const lamp = (state: Partial<Lamp['state']>, extra: Partial<Lamp> = {}): Lamp => ({
  ieee: 'aa',
  name: 'Paneeli',
  room: '',
  model: null,
  paired: true,
  available: true,
  caps: { model: null, manufacturer: null, supports_ct: true, min_mireds: 250, max_mireds: 454 },
  kelvin_range: [2200, 4000],
  kelvin_step: 50,
  state: { on: true, level: 170, mireds: 370, kelvin: 2703, ...state },
  error: null,
  reachable: true,
  last_report: null,
  wakeup: false,
  power_on: 'on',
  owner: 'manual',
  owner_until: null,
  profile: null,
  has_motion: false,
  motion_paused: false,
  hand_only: false,
  members: [],
  ...extra,
})
const snapshot = (sunrise: Snapshot['sunrise'] = null) =>
  ({ timezone: 'Europe/Helsinki', sunrise, sensors: [] }) as unknown as Snapshot

describe('lamp status', () => {
  it('says how bright and how warm', () => {
    expect(lampStatus(lamp({}), snapshot(), fi)).toBe('67 %, 2700 K')
    expect(lampStatus(lamp({ on: false }), snapshot(), fi)).toBe('Pois')
  })

  it('names a running sunrise on its lamp', () => {
    const run = {
      kind: 'alarm', key: 'k', light: 'aa', phase: 'ramp', progress: 0.5, failures: 0,
      start: '2026-10-12T03:00:00Z', end: '2026-10-12T03:30:00Z', off: '2026-10-12T04:30:00Z',
    } as const
    expect(lampStatus(lamp({}), snapshot(run), fi)).toBe('Auringonnousu, täysi klo 6.30')
    expect(lampStatus(lamp({}), snapshot({ ...run, phase: 'hold' }), en)).toBe('Sunrise done, off at 7:30')
  })

  it('says when a lamp does not respond', () => {
    expect(lampStatus(lamp({}, { error: 'timeout' }), snapshot(), en)).toBe(
      'Not responding: is the wall switch off? Last 67 %, 2700 K',
    )
  })
})

describe('motion status', () => {
  it('says the lamp is on by motion, and when it will go off', () => {
    const motion = lamp({}, { owner: 'motion', profile: 'day', owner_until: '2026-10-12T15:32:00Z' })
    expect(lampStatus(motion, snapshot(), fi)).toBe('Liikkeestä päällä, sammuu klo 18.32')
    const night = lamp({ level: 13 }, { owner: 'motion', profile: 'night', owner_until: null })
    expect(lampStatus(night, snapshot(), en)).toBe('Night light')
  })
})

describe('lamps with a motion sensor', () => {
  it('say when they are on by hand, or when motion is paused', () => {
    const manual = lamp({ level: 254 }, { owner: 'manual', has_motion: true })
    expect(lampStatus(manual, snapshot(), fi)).toBe('Käsin päällä, 100 %')
    const paused = lamp({ on: false }, { owner: 'off', has_motion: true, motion_paused: true })
    expect(lampStatus(paused, snapshot(), en)).toBe('Off, motion paused')
  })

  it('say whether motion switches them, so a hand can give them back', () => {
    expect(motionMode(lamp({}, { owner: 'manual', has_motion: false }))).toBeNull()
    expect(motionMode(lamp({}, { owner: 'manual', has_motion: true }))).toBe('byHand')
    expect(motionMode(lamp({ on: false }, { owner: 'off', has_motion: true, motion_paused: true }))).toBe('waits')
    expect(motionMode(lamp({ on: false }, { owner: 'off', has_motion: true }))).toBe('motion')
    expect(motionMode(lamp({}, { owner: 'motion', has_motion: true }))).toBe('motion')
    expect(motionMode(lamp({}, { owner: 'sunrise', has_motion: true }))).toBeNull()
  })

  it('say when they are on hand only, and offer no motion hand-back then', () => {
    const held = lamp({ level: 127 }, { owner: 'manual', has_motion: true, hand_only: true })
    expect(lampStatus(held, snapshot(), fi)).toBe('Vain käsin, 50 %')
    expect(lampStatus(lamp({ on: false }, { owner: 'off', hand_only: true }), snapshot(), en)).toBe('Hand only, off')
    expect(motionMode(held)).toBeNull()
  })
})

describe('lamps that do not answer', () => {
  it('suggest the wall switch and show their last known state', () => {
    const silent = lamp({ on: null, level: 150, kelvin: 2500 }, { error: 'read state failed' })
    expect(lampStatus(silent, snapshot(), fi)).toBe('Ei vastaa: onko seinäkatkaisija pois? Viimeksi 59 %, 2500 K')
    const never = lamp({ on: null, level: null, kelvin: null }, { error: 'read state failed' })
    expect(lampStatus(never, snapshot(), en)).toBe('Not responding: is the wall switch off?')
  })
})

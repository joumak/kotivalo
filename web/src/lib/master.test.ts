import { describe, expect, it } from 'vitest'

import { en } from '@/i18n/en'
import { fi } from '@/i18n/fi'

import { masterAction, secondsLeft } from './master'

describe('master switch', () => {
  it('switches everything off while anything is lit', () => {
    expect(masterAction({ any_on: true, remembered: ['a'], off_at: null })).toEqual({ action: 'off', label: 'allOff' })
  })

  it('brings the remembered lamps back, or all of them', () => {
    expect(masterAction({ any_on: false, remembered: ['a'], off_at: null })).toEqual({ action: 'on', label: 'restore' })
    expect(masterAction({ any_on: false, remembered: [], off_at: null })).toEqual({ action: 'on', label: 'allOn' })
  })

  it('counts down a delayed off in whole seconds', () => {
    const offAt = '2026-10-12T15:05:00+00:00'
    expect(secondsLeft(offAt, new Date('2026-10-12T15:00:00Z'))).toBe(300)
    expect(secondsLeft(offAt, new Date('2026-10-12T15:04:59.500Z'))).toBe(1)
    expect(secondsLeft(offAt, new Date('2026-10-12T15:06:00Z'))).toBe(0)
  })

  it('shows whole minutes, then seconds for the last minute', () => {
    expect(fi.master.offIn(301)).toBe('Pois 5 min päästä') // a second-old clock tick
    expect(fi.master.offIn(269)).toBe('Pois 4 min päästä')
    expect(fi.master.offIn(60)).toBe('Pois 1 min päästä')
    expect(en.master.offIn(42)).toBe('All off in 42 s')
  })
})

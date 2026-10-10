import { describe, expect, it } from 'vitest'

import { masterAction } from './master'

describe('master switch', () => {
  it('switches everything off while anything is lit', () => {
    expect(masterAction({ any_on: true, remembered: ['a'] })).toEqual({ action: 'off', label: 'allOff' })
  })

  it('brings the remembered lamps back, or all of them', () => {
    expect(masterAction({ any_on: false, remembered: ['a'] })).toEqual({ action: 'on', label: 'restore' })
    expect(masterAction({ any_on: false, remembered: [] })).toEqual({ action: 'on', label: 'allOn' })
  })
})

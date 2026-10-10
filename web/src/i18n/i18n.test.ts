import { describe, expect, it } from 'vitest'

import { en } from './en'
import { fi } from './fi'

/** Every key path, with the kind of value (string, function, ...) at the leaf. */
function shape(value: unknown, path = ''): string[] {
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, child]) => shape(child, `${path}.${key}`))
  }
  return [`${path}:${typeof value}`]
}

describe('translations', () => {
  it('Finnish and English have exactly the same keys and kinds', () => {
    expect(shape(fi).sort()).toEqual(shape(en).sort())
  })

  it('formats relative times in both languages', () => {
    expect(en.time.inTime(80)).toBe('in 1 h 20 min')
    expect(fi.time.inTime(80)).toBe('1 h 20 min päästä')
    expect(fi.time.ago(5)).toBe('5 min sitten')
    expect(en.time.inTime(0)).toBe('now')
  })

  it('rounds colour temperature as people read it', () => {
    expect(fi.lamp.kelvin(2703)).toBe('2700 K')
    expect(en.lamp.kelvin(4000)).toBe('4000 K')
  })
})

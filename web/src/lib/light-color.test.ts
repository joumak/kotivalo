import { describe, expect, it } from 'vitest'

import { glowStrength, kelvinToRgb, rgb } from './light-color'

describe('light colour', () => {
  it('turns colour temperature into the colour of the light', () => {
    expect(kelvinToRgb(2200)).toEqual([255, 146, 39]) // warm ember
    const [r, g, b] = kelvinToRgb(4000)
    expect(r).toBe(255)
    expect(g).toBeGreaterThan(200)
    expect(b).toBeGreaterThan(150)
    expect(Math.min(...kelvinToRgb(6600))).toBeGreaterThan(250) // about white
  })

  it('glows more for brighter lamps, with low levels still visible', () => {
    expect(glowStrength(null)).toBe(0)
    expect(glowStrength(254)).toBe(1)
    expect(glowStrength(25)).toBeGreaterThan(0.3)
  })

  it('writes CSS colours', () => {
    expect(rgb([255, 146, 39])).toBe('rgb(255 146 39)')
    expect(rgb([255, 146, 39], 0.5)).toBe('rgb(255 146 39 / 0.5)')
  })
})

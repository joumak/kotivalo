// The colour a lamp actually gives: its colour temperature as RGB, dimmed by its level.
// This is the UI's only accent colour: every lamp tile glows with its own light.

/** Blackbody colour for a colour temperature (Tanner Helland's approximation). */
export function kelvinToRgb(kelvin: number): [number, number, number] {
  const t = kelvin / 100
  let r: number
  let g: number
  let b: number
  if (t <= 66) {
    r = 255
    g = 99.4708025861 * Math.log(t) - 161.1195681661
    b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592)
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492)
    b = 255
  }
  const clamp = (v: number) => Math.round(Math.min(255, Math.max(0, v)))
  return [clamp(r), clamp(g), clamp(b)]
}

export function rgb([r, g, b]: [number, number, number], alpha = 1): string {
  return alpha >= 1 ? `rgb(${r} ${g} ${b})` : `rgb(${r} ${g} ${b} / ${alpha})`
}

/** Perceived brightness 0..1 from a lamp level 2..254 (lamps look brighter at low levels). */
export function glowStrength(level: number | null): number {
  if (!level) return 0
  return Math.sqrt(Math.min(254, Math.max(0, level)) / 254)
}

export const DEFAULT_KELVIN = 2700 // lamps that cannot tune their colour

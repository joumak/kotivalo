import type { CSSProperties } from 'react'

import type { Lamp, Snapshot } from '@/api/types'
import type { Messages } from '@/i18n/en'

import { formatTime, levelPercent } from './format'
import { DEFAULT_KELVIN, glowStrength, kelvinToRgb, rgb } from './light-color'

export function lampColor(lamp: Lamp): [number, number, number] {
  const kelvin = lamp.caps.supports_ct ? (lamp.state.kelvin ?? DEFAULT_KELVIN) : DEFAULT_KELVIN
  return kelvinToRgb(kelvin)
}

export function isLit(lamp: Lamp): boolean {
  return lamp.state.on === true
}

/** One short line saying what the lamp is doing, and why. */
export function lampStatus(lamp: Lamp, snapshot: Snapshot, t: Messages): string {
  const run = snapshot.sunrise
  const time = (iso: string) => formatTime(iso, t.locale, snapshot.timezone)
  if (lamp.error) return t.lamp.notResponding
  if (run && run.light === lamp.ieee) {
    if (run.phase === 'hold') return run.off ? t.lamp.sunriseHold(time(run.off)) : t.lamp.sunriseDone
    return t.lamp.sunrise(time(run.end))
  }
  if (!isLit(lamp)) return lamp.has_motion && lamp.motion_paused ? t.lamp.offMotionPaused : t.lamp.off
  if (lamp.owner === 'motion') {
    const status = lamp.profile === 'night' ? t.lamp.nightLight : t.lamp.motionOn
    return lamp.owner_until ? t.lamp.offAt(status, time(lamp.owner_until)) : status
  }
  const level = t.lamp.level(levelPercent(lamp.state.level))
  if (lamp.has_motion && lamp.owner === 'manual') return `${t.lamp.byHand}, ${level}`
  return lamp.caps.supports_ct && lamp.state.kelvin
    ? `${level}, ${t.lamp.kelvin(lamp.state.kelvin)}`
    : level
}

/** The lamp's own light as a glow: hue from its colour temperature, strength from its level. */
export function glowStyle(lamp: Lamp, scale = 1): CSSProperties {
  if (!isLit(lamp)) return {}
  const color = lampColor(lamp)
  const strength = glowStrength(lamp.state.level) * scale
  return {
    backgroundImage: `radial-gradient(120% 100% at 15% 0%, ${rgb(color, 0.55 * strength)} 0%, ${rgb(color, 0.12 * strength)} 55%, transparent 80%)`,
    boxShadow: `0 0 ${Math.round(40 * strength)}px ${rgb(color, 0.18 * strength)}`,
  }
}

/** The motion sensor whose rule switches this lamp, if any. */
export function sensorFor(lamp: Lamp, snapshot: Snapshot) {
  return snapshot.sensors.find((s) => s.rule?.enabled && s.rule.lights.includes(lamp.ieee))
}

import type { Lamp, Snapshot } from '@/api/types'
import type { Messages } from '@/i18n/en'

import { formatTime, levelPercent } from './format'
import { DEFAULT_KELVIN, kelvinToRgb } from './light-color'

export function lampColor(lamp: Lamp): [number, number, number] {
  const kelvin = lamp.caps.supports_ct ? (lamp.state.kelvin ?? DEFAULT_KELVIN) : DEFAULT_KELVIN
  return kelvinToRgb(kelvin)
}

export function isLit(lamp: Lamp): boolean {
  return lamp.state.on === true
}

/** The brightness and warmth the lamp last had: "59 %, 2500 K". Null if never read. */
export function lastKnown(lamp: Lamp, t: Messages): string | null {
  if (lamp.state.level === null) return null
  const level = t.lamp.level(levelPercent(lamp.state.level))
  return lamp.caps.supports_ct && lamp.state.kelvin ? `${level}, ${t.lamp.kelvin(lamp.state.kelvin)}` : level
}

/** One short line saying what the lamp is doing, and why. */
export function lampStatus(lamp: Lamp, snapshot: Snapshot, t: Messages): string {
  const run = snapshot.sunrise
  const time = (iso: string) => formatTime(iso, t.locale, snapshot.timezone)
  if (lamp.error) {
    const last = lastKnown(lamp, t)
    return last ? `${t.lamp.notResponding} ${t.lamp.lastKnown(last)}` : t.lamp.notResponding
  }
  if (run && run.light === lamp.ieee) {
    if (run.phase === 'hold') return run.off ? t.lamp.sunriseHold(time(run.off)) : t.lamp.sunriseDone
    return t.lamp.sunrise(time(run.end))
  }
  // A plug (on/off only) says "on" where a dimmable lamp gives its brightness.
  const dimmable = lamp.caps.dimmable
  if (lamp.hand_only) {
    const on = dimmable ? t.lamp.level(levelPercent(lamp.state.level)) : t.lamp.onLower
    return t.lamp.handOnlyState(isLit(lamp) ? on : t.lamp.offLower)
  }
  if (!isLit(lamp)) return lamp.has_motion && lamp.motion_paused ? t.lamp.offMotionPaused : t.lamp.off
  if (lamp.owner === 'motion') {
    const status = lamp.profile === 'night' ? t.lamp.nightLight : t.lamp.motionOn
    return lamp.owner_until ? t.lamp.offAt(status, time(lamp.owner_until)) : status
  }
  if (!dimmable) return lamp.has_motion && lamp.owner === 'manual' ? t.lamp.byHand : t.lamp.on
  const level = t.lamp.level(levelPercent(lamp.state.level))
  if (lamp.has_motion && lamp.owner === 'manual') return `${t.lamp.byHand}, ${level}`
  return lamp.caps.supports_ct && lamp.state.kelvin
    ? `${level}, ${t.lamp.kelvin(lamp.state.kelvin)}`
    : level
}

/**
 * For a lamp with a motion sensor: whether motion switches it now ('motion'), or a hand
 * did and motion leaves it alone ('byHand': on by hand, 'waits': off by hand, motion
 * waits for an empty room). Null when there is no sensor or a sunrise runs the lamp.
 */
export function motionMode(lamp: Lamp): 'motion' | 'byHand' | 'waits' | 'bright' | null {
  if (!lamp.has_motion || lamp.owner === 'sunrise' || lamp.hand_only) return null
  if (lamp.owner === 'manual') return 'byHand'
  if (lamp.owner === 'off' && lamp.motion_paused) return 'waits'
  return lamp.owner === 'off' && lamp.motion_bright ? 'bright' : 'motion'
}

/** The motion sensor whose rule switches this lamp, if any. */
export function sensorFor(lamp: Lamp, snapshot: Snapshot) {
  return snapshot.sensors.find((s) => s.rule?.enabled && s.rule.lights.includes(lamp.ieee))
}

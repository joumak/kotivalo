import type { MasterStatus } from '@/api/types'

/** The delays offered for "all off later", in seconds. */
export const MASTER_DELAYS_S = [60, 300]

/** What the master switch does now: everything off if anything is lit; otherwise bring
 * back the remembered lamps, or (nothing ever remembered) switch every lamp on. */
export function masterAction(master: MasterStatus): { action: 'on' | 'off'; label: 'allOff' | 'restore' | 'allOn' } {
  if (master.any_on) return { action: 'off', label: 'allOff' }
  return { action: 'on', label: master.remembered.length > 0 ? 'restore' : 'allOn' }
}

/** Whole seconds until a delayed master-off, never below zero. */
export function secondsLeft(offAt: string, now: Date): number {
  return Math.max(0, Math.ceil((Date.parse(offAt) - now.getTime()) / 1000))
}

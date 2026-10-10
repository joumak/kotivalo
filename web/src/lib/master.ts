import type { MasterStatus } from '@/api/types'

/** What the master switch does now: everything off if anything is lit; otherwise bring
 * back the remembered lamps, or (nothing ever remembered) switch every lamp on. */
export function masterAction(master: MasterStatus): { action: 'on' | 'off'; label: 'allOff' | 'restore' | 'allOn' } {
  if (master.any_on) return { action: 'off', label: 'allOff' }
  return { action: 'on', label: master.remembered.length > 0 ? 'restore' : 'allOn' }
}

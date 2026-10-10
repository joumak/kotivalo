import { describe, expect, it } from 'vitest'

import { LiveState } from './live'
import type { Snapshot } from './types'

const snapshot = (boot: string, seq: number) => ({ boot, seq }) as unknown as Snapshot

describe('live state', () => {
  it('ignores a snapshot older than the one shown', () => {
    const live = new LiveState()
    live.apply(snapshot('a', 5))
    live.apply(snapshot('a', 3)) // an action's response, after the stream pushed what followed
    expect(live.get().snapshot?.seq).toBe(5)
    live.apply(snapshot('a', 6))
    expect(live.get().snapshot?.seq).toBe(6)
  })

  it('takes any snapshot after the service restarted', () => {
    const live = new LiveState()
    live.apply(snapshot('a', 500))
    live.apply(snapshot('b', 1))
    expect(live.get().snapshot?.boot).toBe('b')
  })
})

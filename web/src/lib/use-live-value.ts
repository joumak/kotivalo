import { useCallback, useEffect, useRef, useState } from 'react'

const SEND_EVERY_MS = 200
const HOLD_AFTER_COMMIT_MS = 1500

/**
 * A control value that takes effect while it is being dragged.
 *
 * - Sends at most every 200 ms while dragging, plus the final value on release.
 *   (The server keeps only the newest value per lamp, so nothing queues up.)
 * - While dragging, and briefly after, it ignores pushed state from the server,
 *   so the slider never jumps back to an older value.
 */
export interface LiveValue {
  value: number
  change: (value: number) => void
  commit: (value: number) => void
  reset: () => void
}

export function useLiveValue(remote: number, send: (value: number) => void): LiveValue {
  const [local, setLocal] = useState<number | null>(null)
  const lastSent = useRef(0)
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null)
  const release = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (pending.current) clearTimeout(pending.current)
      if (release.current) clearTimeout(release.current)
    },
    [],
  )

  const change = useCallback(
    (value: number) => {
      setLocal(value)
      if (release.current) clearTimeout(release.current)
      if (pending.current) clearTimeout(pending.current)
      const wait = Math.max(0, lastSent.current + SEND_EVERY_MS - Date.now())
      pending.current = setTimeout(() => {
        lastSent.current = Date.now()
        send(value)
      }, wait)
    },
    [send],
  )

  const commit = useCallback(
    (value: number) => {
      if (pending.current) clearTimeout(pending.current)
      lastSent.current = Date.now()
      send(value)
      release.current = setTimeout(() => setLocal(null), HOLD_AFTER_COMMIT_MS)
    },
    [send],
  )

  /** Back to the server's value now, dropping anything not yet sent (e.g. after a tap). */
  const reset = useCallback(() => {
    if (pending.current) clearTimeout(pending.current)
    if (release.current) clearTimeout(release.current)
    setLocal(null)
  }, [])

  return { value: local ?? remote, change, commit, reset }
}

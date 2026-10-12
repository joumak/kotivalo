import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

// Per-screen preferences, kept in this browser only.
const PANEL_KEY = 'kotivalo-panel'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* storage blocked */
  }
}

/** "This screen is a wall panel." */
export function usePanelMode(): [boolean, (on: boolean) => void] {
  const [panel, setPanelState] = useState(() => read(PANEL_KEY) === '1')
  const setPanel = useCallback((on: boolean) => {
    write(PANEL_KEY, on ? '1' : null)
    setPanelState(on)
  }, [])
  return [panel, setPanel]
}

const darkQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

function subscribeScheme(callback: () => void) {
  const query = darkQuery()
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

/** Follows the device's light/dark setting; the wall panel is always dark. */
export function useTheme(forceDark: boolean): 'dark' | 'light' {
  const systemDark = useSyncExternalStore(subscribeScheme, () => darkQuery().matches)
  const theme = forceDark || systemDark ? 'dark' : 'light'
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])
  return theme
}

/** The current time, updated every `everyMs`. */
export function useNow(everyMs = 1000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), everyMs)
    return () => clearInterval(timer)
  }, [everyMs])
  return now
}

/** Calls `onIdle` after `ms` without a touch, click or key press (while `active`). */
export function useIdle(active: boolean, ms: number, onIdle: () => void) {
  // In a ref: a new callback on every render (every live update) must not restart the timer.
  const callback = useRef(onIdle)
  useEffect(() => {
    callback.current = onIdle
  })
  useEffect(() => {
    if (!active) return
    const fire = () => callback.current()
    let timer = setTimeout(fire, ms)
    const reset = () => {
      clearTimeout(timer)
      timer = setTimeout(fire, ms)
    }
    window.addEventListener('pointerdown', reset)
    window.addEventListener('keydown', reset)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointerdown', reset)
      window.removeEventListener('keydown', reset)
    }
  }, [active, ms])
}

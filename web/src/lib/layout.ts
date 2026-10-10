import { useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (callback) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', callback)
      return () => list.removeEventListener('change', callback)
    },
    () => window.matchMedia(query).matches,
  )
}

/**
 * The four layouts:
 * - phone: portrait phone; bottom tabs, lamp controls in a bottom drawer
 * - short: phone held sideways; side rail, controls in a side sheet
 * - tablet: portrait tablet; like the phone with more columns
 * - wide: landscape tablet; side rail, lamp grid with a control panel beside it
 */
export type Layout = 'phone' | 'short' | 'tablet' | 'wide'

export function useLayout(): Layout {
  const short = useMediaQuery('(max-height: 500px)')
  const wide = useMediaQuery('(min-width: 1024px) and (orientation: landscape)')
  const tablet = useMediaQuery('(min-width: 640px)')
  if (short) return 'short'
  if (wide) return 'wide'
  if (tablet) return 'tablet'
  return 'phone'
}

export const hasRail = (layout: Layout) => layout === 'short' || layout === 'wide'

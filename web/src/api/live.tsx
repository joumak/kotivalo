import { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'

import { ApiError, api, eventsUrl } from './client'
import type { Snapshot } from './types'

export type Connection = 'connecting' | 'live' | 'offline' | 'unauthorized'

export interface LiveView {
  snapshot: Snapshot | null
  connection: Connection
}

/** The service state, pushed over Server-Sent Events. One instance per page. */
export class LiveState {
  private view: LiveView = { snapshot: null, connection: 'connecting' }
  private readonly listeners = new Set<() => void>()
  private source: EventSource | null = null

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  get = () => this.view

  private update(change: Partial<LiveView>) {
    this.view = { ...this.view, ...change }
    this.listeners.forEach((listener) => listener())
  }

  /** A fresher snapshot, e.g. the response to an action. */
  apply = (snapshot: Snapshot) => this.update({ snapshot })

  connect = () => {
    this.source?.close()
    const source = new EventSource(eventsUrl())
    this.source = source
    source.onopen = () => this.update({ connection: 'live' })
    source.onmessage = (event) => this.update({ snapshot: JSON.parse(event.data), connection: 'live' })
    source.onerror = () => {
      // EventSource retries by itself; find out whether it is an access-code problem.
      this.update({ connection: 'offline' })
      api.state().then(this.apply, (error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          source.close()
          this.update({ connection: 'unauthorized' })
        }
      })
    }
  }

  close = () => this.source?.close()
}

const LiveContext = createContext<LiveState | null>(null)

export function LiveProvider({ children, state }: { children: ReactNode; state?: LiveState }) {
  const live = useMemo(() => state ?? new LiveState(), [state])
  useEffect(() => {
    live.connect()
    return live.close
  }, [live])
  return <LiveContext.Provider value={live}>{children}</LiveContext.Provider>
}

export function useLiveState(): LiveState {
  const live = useContext(LiveContext)
  if (!live) throw new Error('useLiveState outside LiveProvider')
  return live
}

export function useLive(): LiveView {
  const live = useLiveState()
  return useSyncExternalStore(live.subscribe, live.get)
}

import { Lightbulb, MonitorSmartphone, Settings2, Sunrise, Waypoints } from 'lucide-react'
import type { ReactNode } from 'react'

import { useLive } from '@/api/live'
import { useT } from '@/i18n'
import { hasRail, useLayout } from '@/lib/layout'
import { cn } from '@/lib/utils'

export type Tab = 'lights' | 'wakeup' | 'devices' | 'settings'
export const TABS: Tab[] = ['lights', 'wakeup', 'devices', 'settings']
const ICONS = { lights: Lightbulb, wakeup: Sunrise, devices: Waypoints, settings: Settings2 }

interface ShellProps {
  tab: Tab
  onTab: (tab: Tab) => void
  onBackToPanel?: () => void
  children: ReactNode
}

/** Navigation (bottom tabs, or a side rail when height is short or the screen is wide) and banners. */
export function Shell({ tab, onTab, onBackToPanel, children }: ShellProps) {
  const t = useT()
  const layout = useLayout()
  const rail = hasRail(layout)

  const items = TABS.map((key) => {
    const Icon = ICONS[key]
    const active = key === tab
    return (
      <button
        key={key}
        type="button"
        onClick={() => onTab(key)}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex flex-1 flex-col items-center justify-center gap-1 rounded-xl px-2 py-1.5 text-xs transition-colors',
          'focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none',
          rail && 'w-full flex-none py-3',
          active ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
        )}
      >
        <Icon className="size-5" strokeWidth={active ? 2.25 : 1.75} />
        {t.nav[key]}
      </button>
    )
  })

  return (
    <div className={cn('min-h-dvh', rail && 'flex')}>
      {rail ? (
        <nav className="sticky top-0 flex h-dvh w-24 shrink-0 flex-col gap-1 border-r bg-card/60 px-2 py-4">
          {items}
          {onBackToPanel && (
            <button
              type="button"
              onClick={onBackToPanel}
              className="mt-auto flex flex-col items-center gap-1 py-3 text-xs text-muted-foreground"
            >
              <MonitorSmartphone className="size-5" />
              {t.panel.back}
            </button>
          )}
        </nav>
      ) : (
        <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-background/90 px-2 pt-1 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur">
          {items}
        </nav>
      )}
      <main className={cn('min-w-0 flex-1 px-4 pt-[max(1rem,env(safe-area-inset-top))] sm:px-6', rail ? 'pb-8' : 'pb-28')}>
        <Banners />
        {onBackToPanel && !rail && (
          <button
            type="button"
            onClick={onBackToPanel}
            className="mb-3 inline-flex items-center gap-2 text-sm text-muted-foreground"
          >
            <MonitorSmartphone className="size-4" />
            {t.panel.back}
          </button>
        )}
        {children}
      </main>
    </div>
  )
}

function Banners() {
  const t = useT()
  const { snapshot, connection } = useLive()
  const messages: string[] = []
  if (connection === 'offline') messages.push(t.banner.offline)
  if (connection === 'unauthorized') messages.push(t.banner.unauthorized)
  if (snapshot?.clock_synced === false) messages.push(t.banner.clock)
  if (messages.length === 0) return null
  return (
    <div role="status" className="mb-4 flex flex-col gap-2">
      {messages.map((message) => (
        <p key={message} className="rounded-xl border border-ember/40 bg-ember/10 px-4 py-3 text-sm">
          {message}
        </p>
      ))}
    </div>
  )
}

export function PageTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">{children}</h1>
      {action}
    </div>
  )
}

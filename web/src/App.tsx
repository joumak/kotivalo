import { Suspense, lazy, useEffect, useState } from 'react'

import { LiveProvider, useLive } from '@/api/live'
import { Shell, TABS } from '@/components/shell'
import type { Tab } from '@/components/shell'
import { Toaster } from '@/components/ui/sonner'
import { LangProvider, useT } from '@/i18n'
import { useLayout } from '@/lib/layout'
import { useIdle, usePanelMode, useTheme } from '@/lib/screen'
import { LightsPage } from '@/pages/lights'
import { PanelDashboard } from '@/pages/panel'

// The lights and the panel load first; the other pages when first opened.
const WakeupPage = lazy(() => import('@/pages/wakeup').then((m) => ({ default: m.WakeupPage })))
const DevicesPage = lazy(() => import('@/pages/devices').then((m) => ({ default: m.DevicesPage })))
const SettingsPage = lazy(() => import('@/pages/settings').then((m) => ({ default: m.SettingsPage })))

const PANEL_IDLE_MS = 3 * 60_000 // a wall panel returns to its dashboard after this

function tabFromHash(): Tab {
  const name = window.location.hash.replace(/^#\/?/, '')
  return (TABS as string[]).includes(name) ? (name as Tab) : 'lights'
}

function useHashTab(): [Tab, (tab: Tab) => void] {
  const [tab, setTabState] = useState(tabFromHash)
  useEffect(() => {
    const onHash = () => setTabState(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [tab, (next) => (window.location.hash = `/${next}`)]
}

function Root() {
  const { snapshot, connection } = useLive()
  const [panel, setPanel] = usePanelMode()
  const [inApp, setInApp] = useState(false)
  const [tab, setTab] = useHashTab()
  const theme = useTheme(panel)
  const layout = useLayout()
  useIdle(panel && inApp, PANEL_IDLE_MS, () => setInApp(false))

  const onPanel = (on: boolean) => {
    setPanel(on)
    setInApp(false)
  }
  const needsCode = connection === 'unauthorized' && !snapshot

  let content
  if (!snapshot && !needsCode) {
    content = <Loading offline={connection === 'offline'} />
  } else if (panel && !inApp && snapshot) {
    content = <PanelDashboard onMenu={() => setInApp(true)} />
  } else {
    const page = needsCode ? 'settings' : tab
    content = (
      <Shell tab={page} onTab={setTab} onBackToPanel={panel ? () => setInApp(false) : undefined}>
        <Suspense fallback={null}>
          {page === 'lights' && <LightsPage />}
          {page === 'wakeup' && <WakeupPage />}
          {page === 'devices' && <DevicesPage />}
          {page === 'settings' && <SettingsPage panel={panel} onPanel={onPanel} />}
        </Suspense>
      </Shell>
    )
  }
  return (
    <>
      {content}
      <Toaster theme={theme} position={layout === 'phone' ? 'top-center' : 'bottom-right'} />
    </>
  )
}

function Loading({ offline }: { offline: boolean }) {
  const t = useT()
  return (
    <div className="grid h-dvh place-items-center px-6 text-center text-muted-foreground">
      {offline ? t.banner.offline : null}
    </div>
  )
}

export default function App() {
  return (
    <LangProvider>
      <LiveProvider>
        <Root />
      </LiveProvider>
    </LangProvider>
  )
}

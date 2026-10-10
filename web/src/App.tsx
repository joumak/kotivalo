import { useEffect, useState } from 'react'

import { LiveProvider, useLive } from '@/api/live'
import { Shell, TABS } from '@/components/shell'
import type { Tab } from '@/components/shell'
import { Toaster } from '@/components/ui/sonner'
import { LangProvider, useT } from '@/i18n'
import { useLayout } from '@/lib/layout'
import { usePanelMode, useTheme } from '@/lib/screen'
import { DevicesPage } from '@/pages/devices'
import { LightsPage } from '@/pages/lights'
import { PanelDashboard } from '@/pages/panel'
import { SettingsPage } from '@/pages/settings'
import { WakeupPage } from '@/pages/wakeup'

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

/** Calls `onIdle` after `ms` without a touch, click or key press (while `active`). */
function useIdle(active: boolean, ms: number, onIdle: () => void) {
  useEffect(() => {
    if (!active) return
    let timer = setTimeout(onIdle, ms)
    const reset = () => {
      clearTimeout(timer)
      timer = setTimeout(onIdle, ms)
    }
    window.addEventListener('pointerdown', reset)
    window.addEventListener('keydown', reset)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointerdown', reset)
      window.removeEventListener('keydown', reset)
    }
  }, [active, ms, onIdle])
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
        {page === 'lights' && <LightsPage />}
        {page === 'wakeup' && <WakeupPage />}
        {page === 'devices' && <DevicesPage />}
        {page === 'settings' && <SettingsPage panel={panel} onPanel={onPanel} />}
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

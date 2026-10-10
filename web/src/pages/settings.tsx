import { useState } from 'react'
import { toast } from 'sonner'

import { useActions } from '@/api/actions'
import { getToken, setToken } from '@/api/client'
import { useLive, useLiveState } from '@/api/live'
import { PageTitle } from '@/components/shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { LANGS, useLang } from '@/i18n'
import type { Lang } from '@/i18n'
import { cn } from '@/lib/utils'

interface SettingsPageProps {
  panel: boolean
  onPanel: (on: boolean) => void
}

export function SettingsPage({ panel, onPanel }: SettingsPageProps) {
  const { t, lang, setLang } = useLang()
  return (
    <>
      <PageTitle>{t.nav.settings}</PageTitle>
      <div className="flex max-w-xl flex-col gap-9">
        <section>
          <h2 className="mb-3 text-lg font-medium">{t.settings.language}</h2>
          <div className="inline-flex rounded-2xl border bg-card p-1" role="radiogroup" aria-label={t.settings.language}>
            {(Object.keys(LANGS) as Lang[]).map((key) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={lang === key}
                onClick={() => setLang(key)}
                className={cn(
                  'min-w-28 rounded-xl px-4 py-2.5 text-base transition-colors',
                  'focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none',
                  lang === key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground',
                )}
              >
                {LANGS[key].label}
              </button>
            ))}
          </div>
        </section>

        <section className="flex items-start justify-between gap-6">
          <div>
            <Label htmlFor="panel-mode" className="text-lg font-medium">
              {t.settings.panel}
            </Label>
            <p className="mt-1 text-muted-foreground">{t.settings.panelHelp}</p>
          </div>
          <Switch id="panel-mode" checked={panel} onCheckedChange={onPanel} className="mt-1" />
        </section>

        <NightWindow />
        <AccessCode />
      </div>
    </>
  )
}

function NightWindow() {
  const { t } = useLang()
  const { snapshot } = useLive()
  const actions = useActions()
  // Shows the saved window until you edit; then your draft until it is saved.
  const [draft, setDraft] = useState<{ start: string; end: string } | null>(null)
  if (!snapshot) return null
  const { start, end } = draft ?? snapshot.night
  const edit = (change: Partial<{ start: string; end: string }>) => setDraft({ start, end, ...change })
  return (
    <section>
      <h2 className="text-lg font-medium">{t.settings.night}</h2>
      <p className="mt-1 mb-4 text-muted-foreground">{t.settings.nightHelp}</p>
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="night-start">{t.settings.from}</Label>
          <Input id="night-start" type="time" value={start} onChange={(e) => edit({ start: e.target.value })} className="h-11 w-32 tabular-nums" />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="night-end">{t.settings.to}</Label>
          <Input id="night-end" type="time" value={end} onChange={(e) => edit({ end: e.target.value })} className="h-11 w-32 tabular-nums" />
        </div>
        <Button
          disabled={!draft || !start || !end}
          onClick={async () => {
            if (await actions.night(start, end)) {
              setDraft(null)
              toast.success(t.settings.saved)
            }
          }}
        >
          {t.settings.saveNight}
        </Button>
      </div>
    </section>
  )
}

function AccessCode() {
  const { t } = useLang()
  const live = useLiveState()
  const [code, setCode] = useState(getToken)
  return (
    <section>
      <Label htmlFor="access-code" className="text-lg font-medium">
        {t.settings.token}
      </Label>
      <p className="mt-1 mb-4 text-muted-foreground">{t.settings.tokenHelp}</p>
      <form
        className="flex flex-wrap gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          setToken(code.trim())
          live.connect()
          toast.success(t.settings.saved)
        }}
      >
        <Input
          id="access-code"
          type="password"
          autoComplete="off"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="h-11 max-w-64"
        />
        <Button type="submit" variant="outline">
          {t.settings.saveToken}
        </Button>
      </form>
    </section>
  )
}

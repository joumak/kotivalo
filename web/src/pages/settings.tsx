import { useState } from 'react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'

import { useActions } from '@/api/actions'
import { api, getToken, setToken } from '@/api/client'
import { useLive, useLiveState } from '@/api/live'
import type { Place } from '@/api/types'
import { DaylightSettings } from '@/components/daylight-settings'
import { PageTitle } from '@/components/shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { LANGS, useLang } from '@/i18n'
import type { Lang } from '@/i18n'
import { heardMinutes, radioName, radioQuiet } from '@/lib/radio'
import { useNow } from '@/lib/screen'
import { cn } from '@/lib/utils'
import { describePlace } from '@/lib/weather'

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
        <WeatherSettings />
        <Daylight />
        <AccessCode />
        <RadioInfo />
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

function Daylight() {
  const { snapshot } = useLive()
  return snapshot ? <DaylightSettings snapshot={snapshot} /> : null
}

/** Where the weather is for: search a town (or type coordinates), tap a result. */
function WeatherSettings() {
  const { t, lang } = useLang()
  const { snapshot } = useLive()
  const actions = useActions()
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<Place[] | null>(null)
  const [busy, setBusy] = useState(false)
  if (!snapshot) return null
  const location = snapshot.weather.location

  const search = async () => {
    setBusy(true)
    try {
      setPlaces(await api.searchPlaces(query, lang))
    } catch {
      setPlaces(null)
      toast.error(t.weather.searchFailed)
    } finally {
      setBusy(false)
    }
  }
  const choose = async (place: Place) => {
    if (await actions.weather({ name: place.name, lat: place.lat, lon: place.lon })) {
      setPlaces(null)
      setQuery('')
      toast.success(t.settings.saved)
    }
  }

  return (
    <section>
      <h2 className="text-lg font-medium">{t.weather.title}</h2>
      <p className="mt-1 mb-4 text-muted-foreground">{t.weather.help}</p>
      {location ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card py-2 pr-2 pl-4">
          <p>{t.weather.showing(describePlace(location))}</p>
          <Button variant="ghost" onClick={() => actions.weather(null)}>
            {t.weather.remove}
          </Button>
        </div>
      ) : (
        <p className="mb-4 text-sm text-muted-foreground">{t.weather.none}</p>
      )}
      <form
        className="flex flex-wrap gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void search()
        }}
      >
        <Label htmlFor="weather-place" className="sr-only">
          {t.weather.placeholder}
        </Label>
        <Input
          id="weather-place"
          value={query}
          placeholder={t.weather.placeholder}
          onChange={(e) => setQuery(e.target.value)}
          className="h-11 max-w-72"
        />
        <Button type="submit" variant="outline" disabled={busy || query.trim().length < 2}>
          {t.weather.search}
        </Button>
      </form>
      {places &&
        (places.length === 0 ? (
          <p className="mt-3 text-muted-foreground">{t.weather.noResults}</p>
        ) : (
          <ul className="mt-3 divide-y rounded-2xl border bg-card">
            {places.map((place) => (
              <li key={`${place.lat},${place.lon}`}>
                <button
                  type="button"
                  onClick={() => choose(place)}
                  className="min-h-11 w-full rounded-2xl px-4 py-2.5 text-left transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/60 focus-visible:outline-none"
                >
                  {describePlace(place)}
                </button>
              </li>
            ))}
          </ul>
        ))}
      <p className="mt-4 text-sm text-muted-foreground">{t.weather.attribution}</p>
    </section>
  )
}

/** The radio and its network, and whether it still hears the devices (read-only). */
function RadioInfo() {
  const { t } = useLang()
  const { snapshot } = useLive()
  const now = useNow(30_000).getTime()
  if (!snapshot) return null
  const radio = snapshot.radio
  const minutes = heardMinutes(radio, now)
  const quiet = radioQuiet(radio, now, snapshot.devices.some((d) => d.paired))
  return (
    <section>
      <h2 className="text-lg font-medium">{t.radio.title}</h2>
      <p className="mt-1 mb-4 text-muted-foreground">{t.radio.help}</p>
      {radio.fake ? (
        <p className="text-sm text-muted-foreground">{t.radio.fake}</p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 rounded-2xl border bg-card px-4 py-3">
          <RadioRow label={t.radio.stick}>{radioName(radio)}</RadioRow>
          {radio.firmware && <RadioRow label={t.radio.firmware}>{radio.firmware}</RadioRow>}
          {radio.channel !== null && radio.pan_id && (
            <RadioRow label={t.radio.network}>{t.radio.channel(radio.channel, radio.pan_id)}</RadioRow>
          )}
          <RadioRow label={t.radio.heard} warn={quiet}>
            {minutes === null ? t.radio.notYet : t.time.ago(minutes)}
          </RadioRow>
        </dl>
      )}
    </section>
  )
}

function RadioRow({ label, warn = false, children }: { label: string; warn?: boolean; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('min-w-0 break-words tabular-nums', warn && 'font-medium text-ember')}>{children}</dd>
    </>
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

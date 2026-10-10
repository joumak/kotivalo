import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { en } from './en'
import type { Messages } from './en'
import { fi } from './fi'

export type Lang = 'fi' | 'en'
export const LANGS: Record<Lang, { messages: Messages; label: string }> = {
  fi: { messages: fi, label: 'Suomi' },
  en: { messages: en, label: 'English' },
}
const KEY = 'kotivalo-lang'

/** The screen's language: saved per device, defaulting to the browser's. */
export function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'fi' || saved === 'en') return saved
  } catch {
    /* storage blocked */
  }
  return navigator.language.toLowerCase().startsWith('fi') ? 'fi' : 'en'
}

interface LangContext {
  lang: Lang
  t: Messages
  setLang: (lang: Lang) => void
}

const Context = createContext<LangContext | null>(null)

export function LangProvider({ children, lang: fixed }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(() => fixed ?? initialLang())
  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* storage blocked */
    }
  }, [])
  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])
  const value = useMemo(() => ({ lang, t: LANGS[lang].messages, setLang }), [lang, setLang])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useLang(): LangContext {
  const value = useContext(Context)
  if (!value) throw new Error('useLang outside LangProvider')
  return value
}

export function useT(): Messages {
  return useLang().t
}

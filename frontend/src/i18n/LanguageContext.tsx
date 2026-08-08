/* eslint-disable react-refresh/only-export-components -- provider and hook form one small, inseparable API. */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Language = 'es' | 'en'

interface LanguageContextValue {
  language: Language
  locale: 'es-CL' | 'en-US'
  setLanguage: (language: Language) => void
  tr: (spanish: string, english: string) => string
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function initialLanguage(): Language {
  const stored = window.localStorage.getItem('aleph-language')
  if (stored === 'es' || stored === 'en') return stored
  return window.navigator.language.toLocaleLowerCase().startsWith('es') ? 'es' : 'en'
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(initialLanguage)

  useEffect(() => {
    window.localStorage.setItem('aleph-language', language)
    document.documentElement.lang = language
  }, [language])

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      locale: language === 'es' ? 'es-CL' : 'en-US',
      setLanguage,
      tr: (spanish, english) => (language === 'es' ? spanish : english),
    }),
    [language],
  )

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const context = useContext(LanguageContext)
  if (!context) throw new Error('useLanguage must be used inside LanguageProvider')
  return context
}

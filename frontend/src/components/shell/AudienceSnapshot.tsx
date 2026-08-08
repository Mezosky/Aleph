import { useEffect, useState } from 'react'
import AnimatedNumber from '@/components/ui/AnimatedNumber'
import { useLanguage } from '@/i18n/LanguageContext'
import { dataUrl } from '@/lib/data'

interface SiteAnalytics {
  status: 'awaiting_configuration' | 'active' | 'stale'
  period_start: string | null
  generated_at: string | null
  visits: number | null
  privacy_note_es: string
  privacy_note_en: string
}

export default function AudienceSnapshot() {
  const { language, locale, tr } = useLanguage()
  const [snapshot, setSnapshot] = useState<SiteAnalytics | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch(dataUrl('site-analytics.json'), { signal: controller.signal, headers: { Accept: 'application/json' } })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((value: SiteAnalytics) => setSnapshot(value))
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  const configured = snapshot?.visits !== null && snapshot?.visits !== undefined
  const periodStart = snapshot?.period_start
    ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(snapshot.period_start))
    : null

  return (
    <section aria-labelledby="audience-title" className="mt-10 border-y border-line-hairline py-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-baseline gap-3">
          <p id="audience-title" className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
            {tr('Visitas', 'Visits')}
          </p>
          <p className="font-serif text-title tabular text-ink-primary">
            {configured && snapshot?.visits !== null ? <AnimatedNumber value={snapshot.visits} locale={locale} /> : '—'}
          </p>
          <p className="text-micro text-ink-muted">
            {tr('desde la activación', 'since activation')}
            {periodStart ? ` · ${periodStart}` : ''}
          </p>
        </div>
        {!configured && (
          <p className="text-micro text-ink-muted">
            {tr('Contador listo; falta conectar el origen analítico.', 'Counter ready; analytics source not connected yet.')}
          </p>
        )}
      </div>
      <p className="mt-3 text-micro text-ink-muted">
        {snapshot ? (language === 'es' ? snapshot.privacy_note_es : snapshot.privacy_note_en) : tr('Cargando métricas agregadas…', 'Loading aggregate metrics…')}
      </p>
    </section>
  )
}

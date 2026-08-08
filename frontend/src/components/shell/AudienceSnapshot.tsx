import { useEffect, useState } from 'react'
import AnimatedNumber from '@/components/ui/AnimatedNumber'
import { useLanguage } from '@/i18n/LanguageContext'
import { dataUrl } from '@/lib/data'

interface CountryVisit {
  code: string
  label_es: string
  label_en: string
  visits: number
}

interface ReferrerVisit {
  host: string
  visits: number
}

interface SiteAnalytics {
  status: 'awaiting_configuration' | 'active' | 'stale'
  period_start: string | null
  generated_at: string | null
  visits: number | null
  page_views: number | null
  countries: CountryVisit[]
  referrers: ReferrerVisit[]
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
  const topCountries = snapshot?.countries.slice(0, 4) ?? []
  const topReferrers = snapshot?.referrers.slice(0, 4) ?? []
  const periodStart = snapshot?.period_start
    ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(snapshot.period_start))
    : null

  return (
    <section aria-labelledby="audience-title" className="mt-10 border-y border-line-hairline py-7">
      <div className="grid gap-7 md:grid-cols-[0.8fr_1.15fr_1.15fr] md:divide-x md:divide-line-hairline">
        <div>
          <p id="audience-title" className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
            {tr('Audiencia del dossier', 'Dossier audience')}
          </p>
          <p className="mt-2 font-serif text-lede tabular text-ink-primary">
            {configured && snapshot?.visits !== null ? <AnimatedNumber value={snapshot.visits} locale={locale} /> : '—'}
          </p>
          <p className="mt-1 text-caption text-ink-secondary">
            {tr('visitas desde la activación', 'visits since activation')}
            {periodStart ? ` · ${periodStart}` : ''}
          </p>
          {!configured && (
            <p className="mt-3 text-micro text-ink-muted">
              {tr('Contador listo; falta conectar el origen analítico.', 'Counter ready; analytics source not connected yet.')}
            </p>
          )}
        </div>

        <div className="md:pl-7">
          <p className="text-micro font-semibold uppercase tracking-[0.14em] text-ink-muted">
            {tr('Desde dónde', 'From where')}
          </p>
          {topCountries.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2 text-caption text-ink-secondary">
              {topCountries.map((country) => (
                <li key={country.code} className="border border-line-hairline px-2.5 py-1.5">
                  {language === 'es' ? country.label_es : country.label_en}{' '}
                  <span className="tabular text-ink-primary">{country.visits.toLocaleString(locale)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-caption text-ink-muted">
              {tr('Países agregados cuando exista una muestra.', 'Aggregate countries once a sample exists.')}
            </p>
          )}
        </div>

        <div className="md:pl-7">
          <p className="text-micro font-semibold uppercase tracking-[0.14em] text-ink-muted">
            {tr('Cómo llegaron', 'How they arrived')}
          </p>
          {topReferrers.length > 0 ? (
            <ul className="mt-3 space-y-1.5 text-caption text-ink-secondary">
              {topReferrers.map((referrer) => (
                <li key={referrer.host} className="flex justify-between gap-4">
                  <span className="truncate">{referrer.host}</span>
                  <span className="tabular text-ink-primary">{referrer.visits.toLocaleString(locale)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-caption text-ink-muted">
              {tr('Referentes agregados, incluido acceso directo.', 'Aggregate referrers, including direct access.')}
            </p>
          )}
        </div>
      </div>
      <p className="mt-6 text-micro text-ink-muted">
        {snapshot ? (language === 'es' ? snapshot.privacy_note_es : snapshot.privacy_note_en) : tr('Cargando métricas agregadas…', 'Loading aggregate metrics…')}
      </p>
    </section>
  )
}

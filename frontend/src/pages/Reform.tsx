import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { describeDataError, loadMegareformaDossier, loadMegareformaEnglish, loadMegareformaSources } from '@/lib/data'
import type { MegareformaDossier, MegareformaSources } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'
import { translateData, type TranslationCatalog } from '@/i18n/translateData'

export default function Reform() {
  const { language, tr } = useLanguage()
  const { slug = '' } = useParams()
  const [rawDossier, setDossier] = useState<MegareformaDossier | null>(null)
  const [rawSources, setSources] = useState<MegareformaSources | null>(null)
  const [translations, setTranslations] = useState<TranslationCatalog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      loadMegareformaDossier(controller.signal),
      loadMegareformaSources(controller.signal),
      loadMegareformaEnglish(controller.signal),
    ]).then(
      ([nextDossier, nextSources, nextTranslations]) => {
        setDossier(nextDossier)
        setSources(nextSources)
        setTranslations(nextTranslations)
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(describeDataError(reason))
      },
    )
    return () => controller.abort()
  }, [])

  const dossier = useMemo(
    () => translateData(rawDossier, translations, language === 'en'),
    [language, rawDossier, translations],
  )
  const sources = useMemo(
    () => translateData(rawSources, translations, language === 'en'),
    [language, rawSources, translations],
  )

  if (slug !== '18216-05')
    return (
      <section>
        <h1 className="text-title font-semibold">
          {tr('Este despliegue contiene un solo dossier', 'This deployment contains one dossier')}
        </h1>
        <p className="mt-4 text-body text-ink-secondary">
          {tr(
            'La demo congelada analiza exclusivamente el boletín 18216-05.',
            'The frozen demo analyzes bulletin 18216-05 exclusively.',
          )}
        </p>
        <Link to="/" className="mt-5 inline-block text-caption font-semibold underline">
          {tr('Volver a la Megarreforma', 'Back to the Megareform')}
        </Link>
      </section>
    )
  if (error)
    return (
      <p role="alert" className="border border-status-critical p-5">
        {error}
      </p>
    )
  if (!dossier || !sources || !translations)
    return (
      <p role="status" className="text-body text-ink-secondary">
        {tr('Cargando evidencia…', 'Loading evidence…')}
      </p>
    )

  return (
    <article>
      <header className="max-w-4xl">
        <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
          {tr('Expediente auditable', 'Auditable record')} · {dossier.document.id}
        </p>
        <h1 className="mt-4 text-display font-semibold">{tr('Evidencia del dossier', 'Dossier evidence')}</h1>
        <p className="mt-5 max-w-3xl text-lede text-ink-secondary">
          {tr(
            'Pasajes literales del PDF, fuentes originales capturadas y límites declarados. Ningún perfil de actor entra en la evaluación factual.',
            'Verbatim PDF passages, captured original sources and disclosed limitations. No actor profile enters the factual evaluation.',
          )}
        </p>
      </header>

      <section className="mt-12 border-y border-line-hairline py-6">
        <dl className="grid gap-6 text-caption sm:grid-cols-3">
          <div>
            <dt className="text-ink-muted">{tr('Documento', 'Document')}</dt>
            <dd className="mt-1 font-semibold">Informe DIPRES N°84</dd>
          </div>
          <div>
            <dt className="text-ink-muted">{tr('Huella SHA-256', 'SHA-256 fingerprint')}</dt>
            <dd className="mt-1 break-all font-mono text-micro">{dossier.document.sha256}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">{tr('Modelo', 'Model')}</dt>
            <dd className="mt-1 font-semibold">{dossier.model.name} · local</dd>
          </div>
        </dl>
      </section>

      <section className="mt-16">
        <h2 className="text-title font-semibold">
          {tr('Pasajes que sostienen el resumen', 'Passages supporting the summary')}
        </h2>
        <div className="mt-7 space-y-4">
          {dossier.objectives.map((objective) => (
            <article key={objective.id} className="border border-line-hairline bg-surface-card p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="text-lede font-semibold">{objective.title}</h3>
                <span className="text-micro font-semibold uppercase text-ink-muted">
                  PDF · {tr('página', 'page')} {objective.page} ·{' '}
                  {tr('cita original verificada', 'verified original quotation')}
                </span>
              </div>
              <blockquote className="mt-4 border-l-2 border-line-strong pl-4 text-body text-ink-primary">
                “{objective.source_quote}”
              </blockquote>
              <p className="mt-4 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">{tr('Límite', 'Limitation')}:</span> {objective.caveat}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-20 border-t border-line-hairline pt-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-micro uppercase text-ink-muted">{tr('Registro de adquisición', 'Acquisition log')}</p>
            <h2 className="mt-2 text-title font-semibold">
              {sources.capture_count} {tr('fuentes capturadas', 'captured sources')}
            </h2>
          </div>
          <a
            href={dossier.document.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-caption font-semibold underline underline-offset-4"
          >
            {tr('Abrir PDF canónico', 'Open canonical PDF')} ↗
          </a>
        </div>
        <ol className="mt-7 divide-y divide-line-hairline border-y border-line-hairline">
          {sources.items.map((source, index) => (
            <li key={source.id} className="grid gap-2 py-4 text-caption sm:grid-cols-[3rem_10rem_1fr_auto]">
              <span className="tabular text-ink-muted">{String(index + 1).padStart(2, '0')}</span>
              <span className="font-semibold">{source.publisher}</span>
              <span className="text-ink-secondary">{source.title}</span>
              <a
                href={source.original_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold underline"
              >
                Original ↗
              </a>
            </li>
          ))}
        </ol>
      </section>
    </article>
  )
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { describeDataError, loadMegareformaDossier, loadMegareformaSources } from '@/lib/data'
import type { MegareformaDossier, MegareformaSources } from '@/types/megareforma'

export default function Reform() {
  const { slug = '' } = useParams()
  const [dossier, setDossier] = useState<MegareformaDossier | null>(null)
  const [sources, setSources] = useState<MegareformaSources | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([loadMegareformaDossier(controller.signal), loadMegareformaSources(controller.signal)]).then(
      ([nextDossier, nextSources]) => {
        setDossier(nextDossier)
        setSources(nextSources)
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(describeDataError(reason))
      },
    )
    return () => controller.abort()
  }, [])

  if (slug !== '18216-05')
    return (
      <section>
        <h1 className="text-title font-semibold">Este despliegue contiene un solo dossier</h1>
        <p className="mt-4 text-body text-ink-secondary">
          La demo congelada analiza exclusivamente el boletín 18216-05.
        </p>
        <Link to="/" className="mt-5 inline-block text-caption font-semibold underline">
          Volver a la Megarreforma
        </Link>
      </section>
    )
  if (error)
    return (
      <p role="alert" className="border border-status-critical p-5">
        {error}
      </p>
    )
  if (!dossier || !sources)
    return (
      <p role="status" className="text-body text-ink-secondary">
        Cargando evidencia…
      </p>
    )

  return (
    <article>
      <header className="max-w-4xl">
        <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
          Expediente auditable · {dossier.document.id}
        </p>
        <h1 className="mt-4 text-display font-semibold">Evidencia del dossier</h1>
        <p className="mt-5 max-w-3xl text-lede text-ink-secondary">
          Pasajes literales del PDF, fuentes originales capturadas y límites declarados. Ningún perfil de actor entra en
          la evaluación factual.
        </p>
      </header>

      <section className="mt-12 border-y border-line-hairline py-6">
        <dl className="grid gap-6 text-caption sm:grid-cols-3">
          <div>
            <dt className="text-ink-muted">Documento</dt>
            <dd className="mt-1 font-semibold">Informe DIPRES N°84</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Huella SHA-256</dt>
            <dd className="mt-1 break-all font-mono text-micro">{dossier.document.sha256}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Modelo</dt>
            <dd className="mt-1 font-semibold">{dossier.model.name} · local</dd>
          </div>
        </dl>
      </section>

      <section className="mt-16">
        <h2 className="text-title font-semibold">Pasajes que sostienen el resumen</h2>
        <div className="mt-7 space-y-4">
          {dossier.objectives.map((objective) => (
            <article key={objective.id} className="border border-line-hairline bg-surface-card p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="text-lede font-semibold">{objective.title}</h3>
                <span className="text-micro font-semibold uppercase text-ink-muted">
                  PDF · página {objective.page} · cita verificada
                </span>
              </div>
              <blockquote className="mt-4 border-l-2 border-line-strong pl-4 text-body text-ink-primary">
                “{objective.source_quote}”
              </blockquote>
              <p className="mt-4 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">Límite:</span> {objective.caveat}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-20 border-t border-line-hairline pt-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-micro uppercase text-ink-muted">Registro de adquisición</p>
            <h2 className="mt-2 text-title font-semibold">{sources.capture_count} fuentes capturadas</h2>
          </div>
          <a
            href={dossier.document.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-caption font-semibold underline underline-offset-4"
          >
            Abrir PDF canónico ↗
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

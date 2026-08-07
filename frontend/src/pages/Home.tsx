import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ActorPopover from '@/components/dossier/ActorPopover'
import DossierMeter from '@/components/dossier/DossierMeter'
import SourceCard from '@/components/dossier/SourceCard'
import { describeDataError, loadMegareformaDossier, loadMegareformaSources } from '@/lib/data'
import type { MegareformaDossier, MegareformaSources } from '@/types/megareforma'

const VERDICT_STYLE = {
  supported: 'border-status-good',
  contradicted: 'border-status-critical',
  mixed: 'border-status-warning',
  conditional: 'border-status-warning',
  unresolved: 'border-status-neutral',
} as const

function Loading() {
  return (
    <p role="status" className="py-20 text-body text-ink-secondary">
      Cargando la instantánea auditada…
    </p>
  )
}

export default function Home() {
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

  const actors = useMemo(() => new Map(dossier?.actors.map((actor) => [actor.id, actor]) ?? []), [dossier])
  const sourceById = useMemo(() => new Map(sources?.items.map((source) => [source.id, source]) ?? []), [sources])

  if (error)
    return (
      <p role="alert" className="border border-status-critical p-5 text-body">
        {error}
      </p>
    )
  if (!dossier || !sources) return <Loading />

  return (
    <>
      <section className="relative border-b border-line-hairline pb-12 pt-4 sm:pb-16 lg:grid lg:grid-cols-[1fr_18rem] lg:gap-14">
        <div>
          <p className="text-micro font-semibold uppercase tracking-[0.2em] text-ink-muted">
            Dossier único · Boletín 18216-05
          </p>
          <h1 className="mt-5 max-w-4xl text-display font-semibold text-ink-primary">
            La Megarreforma, pieza por pieza.
          </h1>
          <p className="mt-6 max-w-3xl text-lede text-ink-secondary">{dossier.summary}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href={dossier.document.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-data bg-ink-primary px-5 py-3 text-caption font-semibold text-ink-inverse"
            >
              Abrir PDF original ↗
            </a>
            <Link
              to="/documento/18216-05"
              className="rounded-data border border-line-strong px-5 py-3 text-caption font-semibold text-ink-primary"
            >
              Revisar evidencia
            </Link>
          </div>
        </div>
        <aside className="mt-10 border-l-2 border-line-strong pl-5 lg:mt-1">
          <p className="text-micro uppercase tracking-wide text-ink-muted">Qué está analizado</p>
          <p className="mt-3 text-caption text-ink-secondary">{dossier.document.scope_note}</p>
          <p className="mt-4 text-micro text-ink-muted">
            Corte: {new Date(dossier.retrieval_cutoff).toLocaleDateString('es-CL')} ·{' '}
            {dossier.model.execution === 'local_gpu_offline' ? 'Qwen local en GPU' : dossier.model.name} · 0 llamadas de
            IA en esta web
          </p>
        </aside>
      </section>

      <dl className="grid grid-cols-2 gap-px bg-line-hairline lg:grid-cols-5">
        {[
          ['Páginas del informe', dossier.document.page_count],
          ['Proposiciones extraídas', dossier.counts.propositions],
          ['Fuentes revisadas', dossier.counts.sources_curated],
          ['Capturas verificadas', sources.capture_count],
          ['Brechas declaradas', sources.gap_count],
        ].map(([label, value]) => (
          <div key={label} className="bg-surface-card p-4 sm:p-5">
            <dt className="text-micro uppercase text-ink-muted">{label}</dt>
            <dd className="mt-2 text-title tabular font-semibold text-ink-primary">{value}</dd>
          </div>
        ))}
      </dl>

      <section id="objetivos" className="mt-20">
        <div className="max-w-3xl">
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">En simple</p>
          <h2 className="mt-3 text-title font-semibold text-ink-primary">¿Qué quiere lograr la reforma?</h2>
          <p className="mt-4 text-body text-ink-secondary">
            Objetivos sintetizados por el modelo local y aceptados sólo cuando su cita aparece en la página indicada del
            PDF.
          </p>
        </div>
        <div className="mt-8 grid gap-px bg-line-hairline lg:grid-cols-2">
          {dossier.objectives.map((objective, index) => (
            <article key={objective.id} className="bg-surface-card p-6 sm:p-8">
              <p className="text-micro font-semibold text-ink-muted">
                {String(index + 1).padStart(2, '0')} · PÁGINA {objective.page}
              </p>
              <h3 className="mt-3 text-lede font-semibold text-ink-primary">{objective.title}</h3>
              <p className="mt-3 text-body text-ink-primary">{objective.plain_language}</p>
              <p className="mt-3 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">Cómo:</span> {objective.mechanism}
              </p>
              <p className="mt-2 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">A quién toca:</span>{' '}
                {objective.affected_groups.join(', ')}.
              </p>
              <details className="mt-4 border-t border-line-hairline pt-3">
                <summary className="cursor-pointer text-caption font-semibold">Cita verificada y límite</summary>
                <blockquote className="mt-3 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                  “{objective.source_quote}”
                </blockquote>
                <p className="mt-3 text-caption text-ink-secondary">{objective.caveat}</p>
              </details>
            </article>
          ))}
        </div>
      </section>

      <section id="medidores" className="mt-24 border-t border-line-hairline pt-12">
        <div className="max-w-3xl">
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">Medidores desarmables</p>
          <h2 className="mt-3 text-title font-semibold text-ink-primary">Dónde cae el debate</h2>
          <p className="mt-4 text-body text-ink-secondary">
            No son notas de bondad ni un detector mágico de sesgo. Cada aguja resume componentes nombrados; abre “Ver
            cálculo” para auditar qué la mueve. Las fotografías son neutrales y simétricas.
          </p>
        </div>
        <div className="mt-8 grid gap-5 lg:grid-cols-2">
          {dossier.meters.map((meter) => (
            <DossierMeter key={meter.id} meter={meter} actors={dossier.actors} />
          ))}
        </div>
      </section>

      <section id="debate" className="mt-24 border-t border-line-hairline pt-12">
        <div className="max-w-3xl">
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
            Gobierno, oposición y evidencia
          </p>
          <h2 className="mt-3 text-title font-semibold text-ink-primary">¿Quién tiene razón?</h2>
          <p className="mt-4 text-body text-ink-secondary">
            Aleph responde por afirmación. Una proyección puede ser plausible y seguir sin estar demostrada; una
            etiqueta política puede contener un núcleo factual y una carga retórica.
          </p>
        </div>
        <div className="mt-8 space-y-6">
          {dossier.debate.map((question) => (
            <article
              key={question.id}
              className={`border-l-4 bg-surface-card p-6 sm:p-8 ${VERDICT_STYLE[question.verdict]}`}
            >
              <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">{question.subtitle}</p>
              <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
                <h3 className="max-w-3xl text-lede font-semibold text-ink-primary">{question.title}</h3>
                <span className="border border-line-strong px-2 py-1 text-micro font-semibold uppercase text-ink-primary">
                  {question.verdict_label}
                </span>
              </div>
              <div className="mt-6 grid gap-px bg-line-hairline md:grid-cols-2">
                {question.positions.map((position, index) => (
                  <div key={`${position.side}-${index}`} className="bg-surface-raised p-4">
                    <p className="text-micro uppercase text-ink-muted">
                      {position.side === 'government'
                        ? 'Gobierno'
                        : position.side === 'opposition'
                          ? 'Oposición'
                          : 'Análisis técnico'}
                    </p>
                    <p className="mt-2 text-caption text-ink-primary">{position.claim}</p>
                    {position.actor_ids.length > 0 && (
                      <p className="mt-3 text-caption text-ink-secondary">
                        {position.actor_ids.map((id, actorIndex) => {
                          const actor = actors.get(id)
                          return actor ? (
                            <span key={id}>
                              {actorIndex > 0 && ', '}
                              <ActorPopover actor={actor} />
                            </span>
                          ) : null
                        })}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-6 text-body text-ink-primary">{question.assessment}</p>
              <p className="mt-3 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">Qué falta para cerrarlo:</span>{' '}
                {question.what_would_resolve_it}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {question.source_ids.map((id) => {
                  const source = sourceById.get(id)
                  return source ? (
                    <a
                      key={id}
                      href={source.original_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="border border-line-hairline px-2 py-1 text-micro text-ink-secondary underline-offset-2 hover:underline"
                    >
                      {source.publisher} ↗
                    </a>
                  ) : null
                })}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section id="actores" className="mt-24 border-t border-line-hairline pt-12">
        <div className="max-w-3xl">
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">Quién es quién</p>
          <h2 className="mt-3 text-title font-semibold">Actores citados</h2>
          <p className="mt-4 text-body text-ink-secondary">
            Pasa el cursor o enfoca un nombre en el debate para ver su ficha. Los antecedentes se muestran aparte: nunca
            cambian un veredicto factual.
          </p>
        </div>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {dossier.actors.map((actor) => (
            <article key={actor.id} className="border border-line-hairline bg-surface-card p-4">
              <img
                src={loadActorImage(actor.image)}
                alt={actor.image_alt}
                className="aspect-[4/5] w-full object-cover object-top grayscale"
                loading="lazy"
              />
              <h3 className="mt-4 text-body font-semibold">{actor.name}</h3>
              <p className="mt-1 text-caption text-ink-secondary">
                {actor.role} · {actor.affiliation}
              </p>
              <p className="mt-3 text-micro text-ink-muted">
                Foto: {actor.image_credit} · {actor.image_license}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section id="fuentes" className="mt-24 border-t border-line-hairline pt-12">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="max-w-3xl">
            <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">Barrido documental</p>
            <h2 className="mt-3 text-title font-semibold">Publicaciones originales</h2>
            <p className="mt-4 text-body text-ink-secondary">
              Cada tarjeta abre la publicación original y usa una captura local tomada durante la recolección. Las
              fuentes no capturadas permanecen como brechas explícitas.
            </p>
          </div>
          <p className="text-caption text-ink-secondary">
            {sources.capture_count} capturas · {sources.gap_count} brechas
          </p>
        </div>
        <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {sources.items.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
        </div>
        {sources.gaps.length > 0 && (
          <details className="mt-8 border border-line-hairline bg-surface-sunken p-5">
            <summary className="cursor-pointer text-caption font-semibold">
              Ver {sources.gaps.length} fuentes no capturadas
            </summary>
            <ul className="mt-4 space-y-2 text-caption text-ink-secondary">
              {sources.gaps.map((gap) => (
                <li key={gap.id}>
                  <a
                    href={gap.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold underline underline-offset-2"
                  >
                    {gap.id}
                  </a>
                  : {gap.error}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </>
  )
}

function loadActorImage(path: string): string {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.endsWith('/') ? base : `${base}/`}data/${path}`
}

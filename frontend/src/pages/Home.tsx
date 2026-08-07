import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ActorPopover from '@/components/dossier/ActorPopover'
import CensusActorPopover from '@/components/dossier/CensusActorPopover'
import DossierMeter from '@/components/dossier/DossierMeter'
import SourceCard from '@/components/dossier/SourceCard'
import {
  describeDataError,
  loadMegareformaActorCensus,
  loadMegareformaDeepAnalysis,
  loadMegareformaDossier,
  loadMegareformaMunicipalActors,
  loadMegareformaSources,
  loadMegareformaTheory,
} from '@/lib/data'
import type {
  ActorCensus,
  CensusActor,
  DeepTopic,
  MegareformaDeepAnalysis,
  MegareformaDossier,
  MegareformaSources,
  MegareformaTheory,
  MunicipalActorIndex,
  MunicipalPositionGroup,
} from '@/types/megareforma'

const VERDICT_STYLE = {
  supported: 'border-status-good',
  contradicted: 'border-status-critical',
  mixed: 'border-status-warning',
  conditional: 'border-status-warning',
  unresolved: 'border-status-neutral',
} as const

const MUNICIPAL_GROUP: Record<MunicipalPositionGroup, { label: string; className: string }> = {
  government_formula: { label: 'Respalda fórmula acordada', className: 'border-status-good' },
  targeted_exemption: { label: 'Pide focalización y redistribución', className: 'border-status-warning' },
  revenue_protection: { label: 'Prioriza resguardo de ingresos', className: 'border-status-neutral' },
  dialogue_participant: { label: 'Participa en negociación', className: 'border-line-strong' },
}

const TOPIC_GROUP: Record<DeepTopic['group'], string> = {
  gasto_y_reconstruccion: 'Reconstrucción y gasto',
  educacion: 'Educación superior',
  empleo_publico: 'Empleo público',
  regulacion: 'Regulación y permisos',
  tributos_permanentes: 'Tributos permanentes',
  tributos_transitorios: 'Tributos transitorios',
  efecto_fiscal: 'Efecto fiscal y supuestos',
}

const ACTOR_TYPE: Record<CensusActor['actor_type'], string> = {
  government: 'Gobierno',
  legislator: 'Congreso',
  mayor: 'Municipios',
  political_party: 'Partidos',
  municipal_association: 'Asociaciones municipales',
  technical_body: 'Órganos técnicos',
  judiciary: 'Justicia',
  business: 'Gremios y empresas',
  union: 'Sindicatos',
  civil_society: 'Sociedad civil',
  academic: 'Academia',
  international_organization: 'Organismos internacionales',
  other: 'Otros actores',
}

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
  const [theory, setTheory] = useState<MegareformaTheory | null>(null)
  const [municipal, setMunicipal] = useState<MunicipalActorIndex | null>(null)
  const [deep, setDeep] = useState<MegareformaDeepAnalysis | null>(null)
  const [census, setCensus] = useState<ActorCensus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      loadMegareformaDossier(controller.signal),
      loadMegareformaSources(controller.signal),
      loadMegareformaTheory(controller.signal),
      loadMegareformaMunicipalActors(controller.signal),
      loadMegareformaDeepAnalysis(controller.signal),
      loadMegareformaActorCensus(controller.signal),
    ]).then(
      ([nextDossier, nextSources, nextTheory, nextMunicipal, nextDeep, nextCensus]) => {
        setDossier(nextDossier)
        setSources(nextSources)
        setTheory(nextTheory)
        setMunicipal(nextMunicipal)
        setDeep(nextDeep)
        setCensus(nextCensus)
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(describeDataError(reason))
      },
    )
    return () => controller.abort()
  }, [])

  const actors = useMemo(() => new Map(dossier?.actors.map((actor) => [actor.id, actor]) ?? []), [dossier])
  const sourceById = useMemo(() => new Map(sources?.items.map((source) => [source.id, source]) ?? []), [sources])
  const gapById = useMemo(() => new Map(sources?.gaps.map((gap) => [gap.id, gap]) ?? []), [sources])

  if (error)
    return (
      <p role="alert" className="border border-status-critical p-5 text-body">
        {error}
      </p>
    )
  if (!dossier || !sources || !theory || !municipal || !deep || !census) return <Loading />

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

      <dl className="grid grid-cols-2 gap-px bg-line-hairline lg:grid-cols-7">
        {[
          ['Páginas del informe', dossier.document.page_count],
          ['Proposiciones extraídas', deep.document.propositions],
          ['Materias explicadas', deep.coverage.topics_grounded],
          ['Fuentes revisadas', dossier.counts.sources_curated],
          ['Capturas verificadas', sources.capture_count],
          ['Actores documentados', census.coverage.actors_indexed],
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

      <section id="lectura-completa" className="mt-24 border-t border-line-hairline pt-12">
        <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
          <div className="max-w-3xl">
            <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
              Auditoría de cobertura del PDF
            </p>
            <h2 className="mt-3 text-title font-semibold text-ink-primary">Las 46 páginas, sin el recorte de seis temas</h2>
            <p className="mt-4 text-body text-ink-secondary">{deep.coverage.methodology}</p>
          </div>
          <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
            <p className="font-semibold text-ink-primary">
              {deep.coverage.pages_structured}/46 páginas · {deep.document.paragraphs} párrafos ·{' '}
              {deep.document.propositions} proposiciones
            </p>
            <p className="mt-3">
              {deep.coverage.blank_pages.length === 1
                ? `La página ${deep.coverage.blank_pages[0]} está vacía en el original; no contiene una materia omitida.`
                : `${deep.coverage.blank_pages.length} páginas están vacías en el original.`}
            </p>
            <p className="mt-3">{deep.coverage.limitation}</p>
            <p className="mt-3">
              {deep.coverage.reviewed_model_fields} campos corregidos en revisión: {deep.coverage.review_method}
            </p>
          </aside>
        </div>
        <div className="mt-8 space-y-4">
          {(Object.entries(TOPIC_GROUP) as [DeepTopic['group'], string][]).map(([group, label]) => {
            const topics = deep.topics.filter((topic) => topic.group === group)
            return (
              <details key={group} className="border border-line-hairline bg-surface-card" open={group === 'gasto_y_reconstruccion'}>
                <summary className="cursor-pointer px-5 py-4 text-body font-semibold text-ink-primary">
                  {label} · {topics.length} {topics.length === 1 ? 'materia' : 'materias'}
                </summary>
                <div className="grid gap-px border-t border-line-hairline bg-line-hairline lg:grid-cols-2">
                  {topics.map((topic) => (
                    <article key={topic.id} className="bg-surface-raised p-5 sm:p-6">
                      <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">
                        Páginas {topic.pages.join(', ')}
                      </p>
                      <p className={`mt-2 text-micro font-semibold uppercase ${topic.coverage_status === 'captured_news' ? 'text-status-good' : 'text-status-warning'}`}>
                        {topic.coverage_status === 'captured_news'
                          ? `${topic.news_source_ids.length} publicaciones capturadas sobre esta materia`
                          : 'Sin noticias capturadas sobre esta materia'}
                      </p>
                      <h3 className="mt-2 text-lede font-semibold text-ink-primary">{topic.title}</h3>
                      <p className="mt-4 text-caption text-ink-primary">{topic.what_changes}</p>
                      <p className="mt-3 text-caption text-ink-secondary">
                        <span className="font-semibold text-ink-primary">Mecanismo:</span> {topic.mechanism}
                      </p>
                      <p className="mt-3 text-caption text-ink-secondary">
                        <span className="font-semibold text-ink-primary">Objetivo declarado:</span>{' '}
                        {topic.government_goal}
                      </p>
                      <p className="mt-3 text-caption text-ink-secondary">
                        <span className="font-semibold text-ink-primary">Efecto fiscal:</span> {topic.fiscal_effect}
                      </p>
                      <details className="mt-4 border-t border-line-hairline pt-3">
                        <summary className="cursor-pointer text-caption font-semibold">Supuestos, riesgos y cita</summary>
                        <p className="mt-3 text-caption text-ink-secondary">
                          <span className="font-semibold text-ink-primary">Afecta a:</span>{' '}
                          {topic.affected_groups.join(', ')}.
                        </p>
                        {topic.assumptions.length > 0 && (
                          <ul className="mt-3 space-y-1 pl-5 text-caption text-ink-secondary">
                            {topic.assumptions.map((assumption) => <li key={assumption} className="list-disc">{assumption}</li>)}
                          </ul>
                        )}
                        <ul className="mt-3 space-y-1 pl-5 text-caption text-ink-secondary">
                          {topic.risks_and_open_questions.map((risk) => <li key={risk} className="list-disc">{risk}</li>)}
                        </ul>
                        <blockquote className="mt-4 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                          “{topic.source_quote}” — p. {topic.source_page}
                        </blockquote>
                        {topic.news_source_ids.length > 0 && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {topic.news_source_ids.map((id) => {
                              const source = sourceById.get(id)
                              return source ? (
                                <a key={id} href={source.original_url} target="_blank" rel="noopener noreferrer" className="border border-line-hairline px-2 py-1 text-micro underline-offset-2 hover:underline">
                                  {source.publisher} ↗
                                </a>
                              ) : null
                            })}
                          </div>
                        )}
                      </details>
                    </article>
                  ))}
                </div>
              </details>
            )
          })}
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

      <section id="evidencia-comparada" className="mt-24 border-t border-line-hairline pt-12">
        <div className="max-w-3xl">
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">Teoría y evidencia global</p>
          <h2 className="mt-3 text-title font-semibold text-ink-primary">¿Qué sabemos fuera de este debate?</h2>
          <p className="mt-4 text-body text-ink-secondary">
            El modelo local contrastó cada mecanismo con evidencia empírica e institucional internacional. No traslada
            automáticamente un resultado extranjero a Chile: separa lo respaldado, lo condicional y lo que aún debe medirse.
          </p>
        </div>
        <div className="mt-8 grid gap-5 lg:grid-cols-2">
          {theory.topics.map((topic) => (
            <article key={topic.id} className="border border-line-hairline bg-surface-card p-6 sm:p-8">
              <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">Pregunta comparada</p>
              <h3 className="mt-2 text-lede font-semibold text-ink-primary">{topic.question}</h3>
              <p className="mt-4 border-l-2 border-line-strong pl-4 text-body text-ink-primary">{topic.bottom_line}</p>
              <ul className="mt-5 space-y-2 pl-5 text-caption text-ink-secondary">
                {topic.findings.map((finding) => <li key={finding} className="list-disc">{finding}</li>)}
              </ul>
              <p className="mt-5 text-caption text-ink-secondary">
                <span className="font-semibold text-ink-primary">Aplicado a la reforma:</span> {topic.application_to_reform}
              </p>
              <details className="mt-4 border-t border-line-hairline pt-3">
                <summary className="cursor-pointer text-caption font-semibold">Límites y referencias</summary>
                <p className="mt-3 text-caption text-ink-secondary">{topic.limits}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {topic.source_ids.map((id) => {
                    const source = sourceById.get(id)
                    const gap = gapById.get(id)
                    const href = source?.original_url ?? gap?.url
                    return href ? (
                      <a key={id} href={href} target="_blank" rel="noopener noreferrer" className="border border-line-hairline px-2 py-1 text-micro underline-offset-2 hover:underline">
                        {source?.publisher ?? id} {gap ? '(no archivada)' : ''} ↗
                      </a>
                    ) : null
                  })}
                </div>
              </details>
            </article>
          ))}
        </div>
        <p className="mt-5 text-micro text-ink-muted">
          Qwen local · {theory.model.usage.total_tokens.toLocaleString('es-CL')} tokens · salida JSON validada · 0 llamadas de IA desde esta página.
        </p>
      </section>

      <section id="censo-actores" className="mt-24 border-t border-line-hairline pt-12">
        <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
          <div className="max-w-3xl">
            <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
              Censo del corpus completo
            </p>
            <h2 className="mt-3 text-title font-semibold text-ink-primary">Todos los actores sustantivos encontrados</h2>
            <p className="mt-4 text-body text-ink-secondary">
              {census.coverage.universe} Cada mención conserva una cita literal y la publicación donde aparece;
              nombres en firmas, menús o notas relacionadas fueron excluidos.
            </p>
          </div>
          <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
            <p className="font-semibold text-ink-primary">
              {census.coverage.actors_indexed} actores · {census.coverage.people} personas ·{' '}
              {census.coverage.institutions} instituciones
            </p>
            <p className="mt-3">
              {census.coverage.captured_sources_audited}/{census.coverage.captured_sources_total} capturas auditadas ·{' '}
              {census.coverage.accepted_mentions} menciones verificadas
            </p>
            <p className="mt-3">
              {census.coverage.detailed_profiles} fichas con trayectoria verificada · {census.coverage.indexed_only}{' '}
              actores conservados como índice documental
            </p>
          </aside>
        </div>
        <div className="mt-8 grid gap-4 lg:grid-cols-2">
          {(Object.entries(ACTOR_TYPE) as [CensusActor['actor_type'], string][]).map(([type, label]) => {
            const group = census.actors.filter((actor) => actor.actor_type === type)
            if (group.length === 0) return null
            return (
              <details key={type} className="border border-line-hairline bg-surface-card">
                <summary className="cursor-pointer px-5 py-4 text-body font-semibold text-ink-primary">
                  {label} · {group.length}
                </summary>
                <div className="divide-y divide-line-hairline border-t border-line-hairline">
                  {group.map((actor) => (
                    <article key={`${actor.entity_kind}-${actor.id}`} className="p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="text-body font-semibold text-ink-primary">
                            <CensusActorPopover actor={actor} />
                          </h3>
                          <p className="mt-1 text-caption text-ink-secondary">
                            {actor.role}
                            {actor.institution ? ` · ${actor.institution}` : ''}
                            {actor.affiliation ? ` · ${actor.affiliation}` : ''}
                          </p>
                        </div>
                        <span className="border border-line-hairline px-2 py-1 text-micro uppercase text-ink-muted">
                          {actor.profile_depth === 'detailed' ? 'ficha ampliada' : 'índice verificado'}
                        </span>
                      </div>
                      <p className="mt-3 text-caption text-ink-primary">{actor.participation_summary}</p>
                      <details className="mt-3">
                        <summary className="cursor-pointer text-caption font-semibold">
                          {actor.source_ids.length} {actor.source_ids.length === 1 ? 'fuente' : 'fuentes'} · ver evidencia
                        </summary>
                        <div className="mt-3 space-y-3">
                          {actor.mentions.map((mention, index) => {
                            const source = sourceById.get(mention.source_id)
                            return (
                              <div key={`${mention.source_id}-${index}`} className="border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                                <p>{mention.action_or_position}</p>
                                <blockquote className="mt-2">“{mention.evidence_quote}”</blockquote>
                                {source && (
                                  <a href={source.original_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-micro font-semibold underline underline-offset-2">
                                    {source.publisher} ↗
                                  </a>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </details>
                    </article>
                  ))}
                </div>
              </details>
            )
          })}
        </div>
        <p className="mt-5 text-micro text-ink-muted">{census.coverage.limitation}</p>
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
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
              <details className="mt-4 border-t border-line-hairline pt-3">
                <summary className="cursor-pointer text-caption font-semibold">Trayectoria y acciones verificadas</summary>
                <ul className="mt-3 space-y-1 text-caption text-ink-secondary">
                  {actor.roles.map((role) => <li key={role}>· {role}</li>)}
                </ul>
                {actor.public_record.map((record) => (
                  <div key={`${record.date}-${record.action}`} className="mt-4 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                    <p className="font-semibold text-ink-primary">{record.date} · {record.status === 'pending' ? 'resultado pendiente' : record.status === 'observed' ? 'resultado observado' : 'no medible'}</p>
                    <p className="mt-1">{record.action}</p>
                    <p className="mt-2"><span className="font-semibold text-ink-primary">Resultado:</span> {record.outcome}</p>
                    <p className="mt-2">{record.assessment}</p>
                  </div>
                ))}
                <p className="mt-4 text-micro text-ink-muted">{actor.record_caveat}</p>
              </details>
            </article>
          ))}
        </div>
      </section>

      <section id="municipios" className="mt-24 border-t border-line-hairline pt-12">
        <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
          <div className="max-w-3xl">
            <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
              Impacto territorial
            </p>
            <h2 className="mt-3 text-title font-semibold">Las voces municipales, sin recortes</h2>
            <p className="mt-4 text-body text-ink-secondary">
              {municipal.coverage.universe} {municipal.coverage.method}
            </p>
          </div>
          <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
            <p className="font-semibold text-ink-primary">
              {municipal.coverage.actors_indexed} alcaldes/as · {municipal.coverage.municipal_sources_curated} fuentes
            </p>
            <p className="mt-3">{municipal.coverage.blind_path_rule}</p>
          </aside>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {municipal.actors.map((actor) => {
            const group = MUNICIPAL_GROUP[actor.position_group]
            const record = actor.public_record[0]!
            return (
              <article key={actor.id} className={`border-l-4 bg-surface-card p-5 ${group.className}`}>
                <div className="flex items-start gap-4">
                  {actor.image ? (
                    <img
                      src={loadActorImage(actor.image)}
                      alt={actor.image_alt || `Retrato de ${actor.name}`}
                      className="h-16 w-14 shrink-0 object-cover object-top grayscale"
                      loading="lazy"
                    />
                  ) : (
                    <span
                      aria-hidden="true"
                      className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-caption font-semibold text-ink-primary"
                    >
                      {actor.name.split(' ').map((part) => part[0]).slice(0, 2).join('')}
                    </span>
                  )}
                  <div>
                    <h3 className="text-body font-semibold text-ink-primary">{actor.name}</h3>
                    <p className="mt-1 text-caption text-ink-secondary">
                      {actor.role} · {actor.municipality} · {actor.affiliation}
                    </p>
                  </div>
                </div>
                <p className="mt-4 text-micro font-semibold uppercase tracking-wide text-ink-muted">{group.label}</p>
                <p className="mt-2 text-caption text-ink-primary">{actor.position_summary}</p>
                <details className="mt-4 border-t border-line-hairline pt-3">
                  <summary className="cursor-pointer text-caption font-semibold">Acción, resultado y fuentes</summary>
                  <p className="mt-3 text-caption text-ink-secondary">{record.action}</p>
                  <p className="mt-3 text-caption text-ink-secondary">
                    <span className="font-semibold text-ink-primary">Resultado:</span> {record.outcome}
                  </p>
                  <p className="mt-3 text-caption text-ink-secondary">{record.assessment}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {actor.source_ids.map((id) => {
                      const source = sourceById.get(id)
                      const gap = gapById.get(id)
                      const href = source?.original_url ?? gap?.url
                      return href ? (
                        <a
                          key={id}
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="border border-line-hairline px-2 py-1 text-micro underline-offset-2 hover:underline"
                        >
                          {source?.publisher ?? id} {gap ? '(brecha)' : ''} ↗
                        </a>
                      ) : null
                    })}
                  </div>
                  <p className="mt-4 text-micro text-ink-muted">{actor.record_caveat}</p>
                  {actor.image && (
                    <p className="mt-2 text-micro text-ink-muted">
                      Foto: {actor.image_credit} · {actor.image_license}
                    </p>
                  )}
                </details>
              </article>
            )
          })}
        </div>
        <p className="mt-5 text-micro text-ink-muted">{municipal.coverage.limitation}</p>
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
              {sources.capture_count} capturas · {sources.items.filter((source) => source.format === 'video' || source.format === 'audio').length} videos/audio · {sources.gap_count} brechas
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

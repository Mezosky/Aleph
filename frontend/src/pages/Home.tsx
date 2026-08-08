import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ActorPopover from '@/components/dossier/ActorPopover'
import CensusActorPopover from '@/components/dossier/CensusActorPopover'
import DossierMeter from '@/components/dossier/DossierMeter'
import DossierSectionNav from '@/components/dossier/DossierSectionNav'
import SourceCard from '@/components/dossier/SourceCard'
import AnimatedNumber from '@/components/ui/AnimatedNumber'
import {
  describeDataError,
  loadMegareformaActorCensus,
  loadMegareformaDeepAnalysis,
  loadMegareformaDossier,
  loadMegareformaEnglish,
  loadMegareformaMunicipalActors,
  loadMegareformaSources,
  loadMegareformaTheory,
} from '@/lib/data'
import { useLanguage } from '@/i18n/LanguageContext'
import { translateData, type TranslationCatalog } from '@/i18n/translateData'
import type {
  ActorCensus,
  CapturedSource,
  CensusActor,
  DebateQuestion,
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

const ActorMap = lazy(() => import('@/components/dossier/ActorMap'))

const MUNICIPAL_GROUP: Record<MunicipalPositionGroup, { label: string; className: string }> = {
  government_formula: {
    label: 'Respalda fórmula acordada',
    className: 'border-status-good',
  },
  targeted_exemption: {
    label: 'Pide focalización y redistribución',
    className: 'border-status-warning',
  },
  revenue_protection: {
    label: 'Prioriza resguardo de ingresos',
    className: 'border-status-neutral',
  },
  dialogue_participant: {
    label: 'Participa en negociación',
    className: 'border-line-strong',
  },
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
const TOPIC_GROUP_EN: Record<DeepTopic['group'], string> = {
  gasto_y_reconstruccion: 'Reconstruction and spending',
  educacion: 'Higher education',
  empleo_publico: 'Public employment',
  regulacion: 'Regulation and permits',
  tributos_permanentes: 'Permanent taxes',
  tributos_transitorios: 'Temporary taxes',
  efecto_fiscal: 'Fiscal effect and assumptions',
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
const ACTOR_TYPE_EN: Record<CensusActor['actor_type'], string> = {
  government: 'Government',
  legislator: 'Congress',
  mayor: 'Municipalities',
  political_party: 'Political parties',
  municipal_association: 'Municipal associations',
  technical_body: 'Technical bodies',
  judiciary: 'Judiciary',
  business: 'Business associations and companies',
  union: 'Trade unions',
  civil_society: 'Civil society',
  academic: 'Academia',
  international_organization: 'International organizations',
  other: 'Other actors',
}

const DEBATE_NEWS_TERMS: Record<string, readonly string[]> = {
  'growth-pays': ['crecimiento', 'empleo', 'inversión', 'recaudación', 'riesgo fiscal', 'consejo fiscal autónomo'],
  'hidden-tax-reform': [
    'reforma tributaria',
    'impuesto corporativo',
    'primera categoría',
    'reintegración',
    'sence',
    'dfl2',
    'repatriación',
    'invariabilidad tributaria',
  ],
  'permits-environment': [
    'permiso ambiental',
    'permisos ambientales',
    'evaluación ambiental',
    'rca',
    'acuicultura',
    'tribunal constitucional',
  ],
  'municipal-compensation': [
    'compensación municipal',
    'fondo común municipal',
    'exención de contribuciones',
    'alcaldes',
    'municipios',
  ],
}

function Loading() {
  const { tr } = useLanguage()
  return (
    <p role="status" className="py-20 text-body text-ink-secondary">
      {tr('Cargando la instantánea auditada…', 'Loading the audited snapshot…')}
    </p>
  )
}

function debateNews(
  question: DebateQuestion,
  searchSourceById: Map<string, CapturedSource>,
  displaySourceById = searchSourceById,
): CapturedSource[] {
  const ids = new Set(question.source_ids)
  question.positions.forEach((position) => position.source_ids.forEach((id) => ids.add(id)))
  const terms = DEBATE_NEWS_TERMS[question.id] ?? []
  searchSourceById.forEach((source) => {
    const searchable = `${source.title} ${source.summary}`.toLocaleLowerCase('es')
    if (source.kind === 'news' && terms.some((term) => searchable.includes(term))) ids.add(source.id)
  })
  return [...ids]
    .map((id) => displaySourceById.get(id))
    .filter((source): source is CapturedSource => source?.kind === 'news')
    .sort((left, right) => right.published_at.localeCompare(left.published_at))
}

interface HomeProps {
  view?: 'main' | 'actors'
}

export default function Home({ view = 'main' }: HomeProps) {
  const { language, locale, tr } = useLanguage()
  const [rawDossier, setDossier] = useState<MegareformaDossier | null>(null)
  const [rawSources, setSources] = useState<MegareformaSources | null>(null)
  const [rawTheory, setTheory] = useState<MegareformaTheory | null>(null)
  const [rawMunicipal, setMunicipal] = useState<MunicipalActorIndex | null>(null)
  const [rawDeep, setDeep] = useState<MegareformaDeepAnalysis | null>(null)
  const [rawCensus, setCensus] = useState<ActorCensus | null>(null)
  const [translations, setTranslations] = useState<TranslationCatalog | null>(null)
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
      loadMegareformaEnglish(controller.signal),
    ]).then(
      ([nextDossier, nextSources, nextTheory, nextMunicipal, nextDeep, nextCensus, nextTranslations]) => {
        setDossier(nextDossier)
        setSources(nextSources)
        setTheory(nextTheory)
        setMunicipal(nextMunicipal)
        setDeep(nextDeep)
        setCensus(nextCensus)
        setTranslations(nextTranslations)
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(describeDataError(reason))
      },
    )
    return () => controller.abort()
  }, [])

  const english = language === 'en'
  const dossier = useMemo(() => translateData(rawDossier, translations, english), [english, rawDossier, translations])
  const sources = useMemo(() => translateData(rawSources, translations, english), [english, rawSources, translations])
  const theory = useMemo(() => translateData(rawTheory, translations, english), [english, rawTheory, translations])
  const municipal = useMemo(
    () => translateData(rawMunicipal, translations, english),
    [english, rawMunicipal, translations],
  )
  const deep = useMemo(() => translateData(rawDeep, translations, english), [english, rawDeep, translations])
  const census = useMemo(() => translateData(rawCensus, translations, english), [english, rawCensus, translations])

  const actors = useMemo(() => new Map(dossier?.actors.map((actor) => [actor.id, actor]) ?? []), [dossier])
  const sourceById = useMemo(() => new Map(sources?.items.map((source) => [source.id, source]) ?? []), [sources])
  const rawSourceById = useMemo(
    () => new Map(rawSources?.items.map((source) => [source.id, source]) ?? []),
    [rawSources],
  )
  const gapById = useMemo(() => new Map(sources?.gaps.map((gap) => [gap.id, gap]) ?? []), [sources])

  if (error)
    return (
      <p role="alert" className="border border-status-critical p-5 text-body">
        {error}
      </p>
    )
  if (!dossier || !sources || !theory || !municipal || !deep || !census || !translations) return <Loading />

  const allNews = sources.items
    .filter((source) => source.kind === 'news')
    .sort((left, right) => right.published_at.localeCompare(left.published_at))
  const evaluatedNewsIds = new Set(
    dossier.debate.flatMap((question) => debateNews(question, rawSourceById, sourceById).map((source) => source.id)),
  )
  const otherDebateNews = allNews.filter((source) => !evaluatedNewsIds.has(source.id))
  const newestNews = allNews[0]

  return (
    <>
      {view === 'main' && (
        <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-8 xl:grid-cols-[13rem_minmax(0,1fr)] xl:gap-10">
          <DossierSectionNav />
          <div className="min-w-0">
          <section id="resumen" className="relative isolate scroll-mt-36 overflow-hidden border-b border-line-hairline px-5 pb-12 pt-8 sm:px-8 sm:pb-16 lg:grid lg:scroll-mt-24 lg:grid-cols-[1fr_18rem] lg:gap-14">
            <div
              aria-hidden="true"
              className="absolute inset-0 -z-20 scale-105 bg-cover bg-center opacity-[0.18] grayscale blur-[2px]"
              style={{
                backgroundImage: `url(${import.meta.env.BASE_URL}la-moneda.jpg)`,
              }}
            />
            <div
              aria-hidden="true"
              className="absolute inset-0 -z-10"
              style={{
                background:
                  'linear-gradient(90deg, var(--surface-page) 8%, color-mix(in srgb, var(--surface-page) 88%, transparent) 62%, color-mix(in srgb, var(--surface-page) 72%, transparent))',
              }}
            />
            <div className="relative">
              <p className="text-micro font-semibold uppercase tracking-[0.2em] text-ink-muted">
                {tr('Dossier único', 'Single-document dossier')} · Chile · Boletín 18216-05
              </p>
              <h1 className="mt-5 max-w-4xl text-display font-semibold text-ink-primary">
                {tr('La Megarreforma, pieza por pieza.', 'Chile’s Megareform, piece by piece.')}
              </h1>
              <p className="mt-6 max-w-3xl text-lede text-ink-secondary">{dossier.summary}</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <a
                  href={dossier.document.pdf_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-data bg-ink-primary px-5 py-3 text-caption font-semibold text-ink-inverse"
                >
                  {tr('Abrir PDF original', 'Open original PDF')} ↗
                </a>
                <Link
                  to="/documento/18216-05"
                  className="rounded-data border border-line-strong px-5 py-3 text-caption font-semibold text-ink-primary"
                >
                  {tr('Revisar evidencia', 'Review evidence')}
                </Link>
              </div>
            </div>
            <aside className="mt-10 border-l-2 border-line-strong pl-5 lg:mt-1">
              <p className="text-micro uppercase tracking-wide text-ink-muted">
                {tr('Qué está analizado', 'What was analyzed')}
              </p>
              <p className="mt-3 text-caption text-ink-secondary">{dossier.document.scope_note}</p>
              <p className="mt-4 text-micro text-ink-muted">
                {tr('Corte', 'Cutoff')}: {new Date(dossier.retrieval_cutoff).toLocaleDateString(locale)} ·{' '}
                {dossier.model.execution === 'local_gpu_offline'
                  ? tr('Qwen local en GPU', 'Local Qwen on GPU')
                  : dossier.model.name}{' '}
                · 0 {tr('llamadas de IA en esta web', 'AI calls from this website')}
              </p>
              <p className="mt-4 text-micro text-ink-muted">
                {tr('Fondo', 'Background')}: Palacio de La Moneda · Martin St-Amant ·{' '}
                <a
                  href="https://commons.wikimedia.org/wiki/File:128_-_Santiago_-_Panorama_de_La_Moneda_-_Janvier_2010.jpg"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2"
                >
                  CC BY-SA 3.0 ↗
                </a>
              </p>
            </aside>
          </section>

          <dl className="grid grid-cols-2 gap-px bg-line-hairline lg:grid-cols-7">
            {[
              [tr('Páginas del informe', 'Report pages'), dossier.document.page_count],
              [tr('Proposiciones extraídas', 'Extracted propositions'), deep.document.propositions],
              [tr('Materias explicadas', 'Topics explained'), deep.coverage.topics_grounded],
              [tr('Fuentes revisadas', 'Sources reviewed'), dossier.counts.sources_curated],
              [tr('Capturas verificadas', 'Verified captures'), sources.capture_count],
              [tr('Actores documentados', 'Documented actors'), census.coverage.actors_indexed],
              [tr('Brechas declaradas', 'Disclosed gaps'), sources.gap_count],
            ].map(([label, value]) => (
              <div key={label} className="bg-surface-card p-4 sm:p-5">
                <dt className="text-micro uppercase text-ink-muted">{label}</dt>
                <dd className="mt-2 text-title tabular font-semibold text-ink-primary">
                  <AnimatedNumber value={Number(value)} locale={locale} />
                </dd>
              </div>
            ))}
          </dl>

          <section id="objetivos" className="mt-20 scroll-mt-36 lg:scroll-mt-24">
            <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
              <div className="max-w-3xl">
                <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                  {tr('En simple', 'In plain language')}
                </p>
                <h2 className="mt-3 text-title font-semibold text-ink-primary">
                  {tr('La reforma: seis ejes y treinta materias', 'The reform: six pillars and thirty topics')}
                </h2>
                <p className="mt-4 text-body text-ink-secondary">
                  {tr(
                    'Empieza por los seis ejes principales y continúa, en esta misma sección, con el desglose completo del PDF. Cada explicación fue aceptada sólo cuando su cita aparece en la página indicada.',
                    'Start with the six main pillars, then continue in the same section with the complete PDF breakdown. Each explanation was accepted only when its quotation appears on the cited page.',
                  )}
                </p>
              </div>
              <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
                <p className="font-semibold text-ink-primary">
                  {deep.coverage.pages_structured}/46 {tr('páginas', 'pages')} · {deep.document.paragraphs}{' '}
                  {tr('párrafos', 'paragraphs')} · {deep.document.propositions} {tr('proposiciones', 'propositions')}
                </p>
                <p className="mt-3">
                  {deep.coverage.blank_pages.length === 1
                    ? tr(
                        `La página ${deep.coverage.blank_pages[0]} está vacía en el original.`,
                        `Page ${deep.coverage.blank_pages[0]} is blank in the original.`,
                      )
                    : tr(
                        `${deep.coverage.blank_pages.length} páginas están vacías en el original.`,
                        `${deep.coverage.blank_pages.length} pages are blank in the original.`,
                      )}
                </p>
              </aside>
            </div>
            <h3 className="mt-10 text-lede font-semibold text-ink-primary">
              {tr('Vista rápida', 'Quick view')} · 6 {tr('ejes', 'pillars')}
            </h3>
            <div className="mt-8 grid gap-px bg-line-hairline lg:grid-cols-2">
              {dossier.objectives.map((objective, index) => (
                <article key={objective.id} className="bg-surface-card p-6 sm:p-8">
                  <p className="text-micro font-semibold text-ink-muted">
                    {String(index + 1).padStart(2, '0')} · {tr('PÁGINA', 'PAGE')} {objective.page}
                  </p>
                  <h3 className="mt-3 text-lede font-semibold text-ink-primary">{objective.title}</h3>
                  <p className="mt-3 text-body text-ink-primary">{objective.plain_language}</p>
                  <p className="mt-3 text-caption text-ink-secondary">
                    <span className="font-semibold text-ink-primary">{tr('Cómo', 'How')}:</span> {objective.mechanism}
                  </p>
                  <p className="mt-2 text-caption text-ink-secondary">
                    <span className="font-semibold text-ink-primary">{tr('A quién toca', 'Who is affected')}:</span>{' '}
                    {objective.affected_groups.join(', ')}.
                  </p>
                  <details className="mt-4 border-t border-line-hairline pt-3">
                    <summary className="cursor-pointer text-caption font-semibold">
                      {tr('Cita original verificada y límite', 'Verified original quotation and limitation')}
                    </summary>
                    <blockquote className="mt-3 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                      “{objective.source_quote}”
                    </blockquote>
                    <p className="mt-3 text-caption text-ink-secondary">{objective.caveat}</p>
                  </details>
                </article>
              ))}
            </div>

            <div id="lectura-completa" className="mt-14 border-t border-line-hairline pt-10">
              <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
                <div className="max-w-3xl">
                  <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                    {tr('Auditoría de cobertura del PDF', 'PDF coverage audit')}
                  </p>
                  <h3 className="mt-3 text-lede font-semibold text-ink-primary">
                    {tr('Lectura completa', 'Complete reading')} · 30 {tr('materias', 'topics')}
                  </h3>
                  <p className="mt-4 text-body text-ink-secondary">{deep.coverage.methodology}</p>
                </div>
                <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
                  <p className="mt-3">{deep.coverage.limitation}</p>
                  <p className="mt-3">
                    {deep.coverage.reviewed_model_fields}{' '}
                    {tr('campos corregidos en revisión', 'fields corrected in review')}: {deep.coverage.review_method}
                  </p>
                </aside>
              </div>
              <div className="mt-8 space-y-4">
                {(Object.entries(TOPIC_GROUP) as [DeepTopic['group'], string][]).map(([group, label]) => {
                  const topics = deep.topics.filter((topic) => topic.group === group)
                  return (
                    <details
                      key={group}
                      className="border border-line-hairline bg-surface-card"
                      open={group === 'gasto_y_reconstruccion'}
                    >
                      <summary className="cursor-pointer px-5 py-4 text-body font-semibold text-ink-primary">
                        {language === 'es' ? label : TOPIC_GROUP_EN[group]} · {topics.length}{' '}
                        {topics.length === 1 ? tr('materia', 'topic') : tr('materias', 'topics')}
                      </summary>
                      <div className="grid gap-px border-t border-line-hairline bg-line-hairline lg:grid-cols-2">
                        {topics.map((topic) => (
                          <article key={topic.id} className="bg-surface-raised p-5 sm:p-6">
                            <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">
                              {tr('Páginas', 'Pages')} {topic.pages.join(', ')}
                            </p>
                            <p
                              className={`mt-2 text-micro font-semibold uppercase ${topic.coverage_status === 'captured_news' ? 'text-status-good' : 'text-status-warning'}`}
                            >
                              {topic.coverage_status === 'captured_news'
                                ? `${topic.news_source_ids.length} ${tr('publicaciones capturadas sobre esta materia', 'captured publications on this topic')}`
                                : tr('Sin noticias capturadas sobre esta materia', 'No captured news on this topic')}
                            </p>
                            <h3 className="mt-2 text-lede font-semibold text-ink-primary">{topic.title}</h3>
                            <p className="mt-4 text-caption text-ink-primary">{topic.what_changes}</p>
                            <p className="mt-3 text-caption text-ink-secondary">
                              <span className="font-semibold text-ink-primary">{tr('Mecanismo', 'Mechanism')}:</span>{' '}
                              {topic.mechanism}
                            </p>
                            <p className="mt-3 text-caption text-ink-secondary">
                              <span className="font-semibold text-ink-primary">
                                {tr('Objetivo declarado', 'Stated objective')}:
                              </span>{' '}
                              {topic.government_goal}
                            </p>
                            <p className="mt-3 text-caption text-ink-secondary">
                              <span className="font-semibold text-ink-primary">
                                {tr('Efecto fiscal', 'Fiscal effect')}:
                              </span>{' '}
                              {topic.fiscal_effect}
                            </p>
                            <details className="mt-4 border-t border-line-hairline pt-3">
                              <summary className="cursor-pointer text-caption font-semibold">
                                {tr('Supuestos, riesgos y cita', 'Assumptions, risks and quotation')}
                              </summary>
                              <p className="mt-3 text-caption text-ink-secondary">
                                <span className="font-semibold text-ink-primary">Afecta a:</span>{' '}
                                {topic.affected_groups.join(', ')}.
                              </p>
                              {topic.assumptions.length > 0 && (
                                <ul className="mt-3 space-y-1 pl-5 text-caption text-ink-secondary">
                                  {topic.assumptions.map((assumption) => (
                                    <li key={assumption} className="list-disc">
                                      {assumption}
                                    </li>
                                  ))}
                                </ul>
                              )}
                              <ul className="mt-3 space-y-1 pl-5 text-caption text-ink-secondary">
                                {topic.risks_and_open_questions.map((risk) => (
                                  <li key={risk} className="list-disc">
                                    {risk}
                                  </li>
                                ))}
                              </ul>
                              <blockquote className="mt-4 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
                                “{topic.source_quote}” — p. {topic.source_page}
                              </blockquote>
                              {topic.news_source_ids.length > 0 && (
                                <div className="mt-4 flex flex-wrap gap-2">
                                  {topic.news_source_ids.map((id) => {
                                    const source = sourceById.get(id)
                                    return source ? (
                                      <a
                                        key={id}
                                        href={source.original_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="border border-line-hairline px-2 py-1 text-micro underline-offset-2 hover:underline"
                                      >
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
            </div>
          </section>

          <section id="medidores" className="mt-24 scroll-mt-36 border-t border-line-hairline pt-12 lg:scroll-mt-24">
            <div className="max-w-3xl">
              <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                {tr('Medidores desarmables', 'Inspectable meters')}
              </p>
              <h2 className="mt-3 text-title font-semibold text-ink-primary">
                {tr('Dónde cae el debate', 'Where the debate falls')}
              </h2>
              <p className="mt-4 text-body text-ink-secondary">
                {tr(
                  'No son notas de bondad ni un detector mágico de sesgo. Cada aguja resume componentes nombrados; abre “Ver cálculo” para auditar qué la mueve. Las fotografías son neutrales y simétricas.',
                  'These are not goodness scores or a magic bias detector. Each needle summarizes named components; open “View calculation” to audit what moves it. The photographs are neutral and symmetric.',
                )}
              </p>
            </div>
            <div className="mt-8 grid gap-5 lg:grid-cols-2">
              {dossier.meters.map((meter) => (
                <DossierMeter key={meter.id} meter={meter} actors={dossier.actors} />
              ))}
            </div>
          </section>

          <section id="debate" className="mt-24 scroll-mt-36 border-t border-line-hairline pt-12 lg:scroll-mt-24">
            <div className="max-w-3xl">
              <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                {tr('Gobierno, oposición y evidencia', 'Government, opposition and evidence')}
              </p>
              <h2 className="mt-3 text-title font-semibold text-ink-primary">
                {tr('¿Quién tiene razón?', 'Who has the stronger case?')}
              </h2>
              <p className="mt-4 text-body text-ink-secondary">
                {tr(
                  'Aleph responde por afirmación y reúne automáticamente las noticias citadas por cada posición. La página sigue siendo offline: una actualización del corpus recalcula esta lista antes del próximo deploy.',
                  'Aleph answers claim by claim and automatically gathers the news cited by each position. The page remains offline: updating the corpus recalculates this list before the next deployment.',
                )}
              </p>
              <div className="mt-6 grid grid-cols-2 gap-px bg-line-hairline sm:grid-cols-4">
                {[
                  [tr('Prensa visible', 'Visible press'), `${allNews.length}/${allNews.length}`],
                  [tr('En preguntas evaluadas', 'In evaluated questions'), evaluatedNewsIds.size],
                  [tr('Otras aristas', 'Other angles'), otherDebateNews.length],
                  [
                    tr('Última publicación', 'Latest publication'),
                    newestNews ? new Date(newestNews.published_at).toLocaleDateString(locale) : '—',
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="bg-surface-card p-3">
                    <p className="text-micro uppercase text-ink-muted">{label}</p>
                    <p className="mt-1 text-caption font-semibold text-ink-primary">{value}</p>
                  </div>
                ))}
              </div>
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
                  {debateNews(question, rawSourceById, sourceById)[0] && (
                    <p className="mt-3 text-micro font-semibold uppercase tracking-wide text-ink-muted">
                      {tr('Debate público', 'Public debate')} · {debateNews(question, rawSourceById, sourceById).length}{' '}
                      {tr('publicaciones incorporadas', 'publications included')} · {tr('última', 'latest')}{' '}
                      {new Date(debateNews(question, rawSourceById, sourceById)[0]!.published_at).toLocaleDateString(
                        locale,
                      )}
                    </p>
                  )}
                  <div className="mt-6 grid gap-px bg-line-hairline md:grid-cols-2">
                    {question.positions.map((position, index) => (
                      <div key={`${position.side}-${index}`} className="bg-surface-raised p-4">
                        <p className="text-micro uppercase text-ink-muted">
                          {position.side === 'government'
                            ? tr('Gobierno', 'Government')
                            : position.side === 'opposition'
                              ? tr('Oposición', 'Opposition')
                              : tr('Análisis técnico', 'Technical analysis')}
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
                    <span className="font-semibold text-ink-primary">
                      {tr('Qué falta para cerrarlo', 'What would settle it')}:
                    </span>{' '}
                    {question.what_would_resolve_it}
                  </p>
                  {debateNews(question, rawSourceById, sourceById).length > 0 && (
                    <details className="mt-5 border-t border-line-hairline pt-4">
                      <summary className="cursor-pointer text-caption font-semibold text-ink-primary">
                        {tr('Noticias que actualizan este debate', 'News updating this debate')}
                      </summary>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {debateNews(question, rawSourceById, sourceById).map((source) => (
                          <a
                            key={source.id}
                            href={source.original_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="border border-line-hairline bg-surface-raised p-3 text-caption text-ink-secondary hover:border-line-strong"
                          >
                            <span className="block text-micro font-semibold uppercase text-ink-muted">
                              {source.publisher} · {new Date(source.published_at).toLocaleDateString(locale)}
                            </span>
                            <span className="mt-1 block text-ink-primary">{source.title} ↗</span>
                          </a>
                        ))}
                      </div>
                    </details>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    {question.source_ids.map((id) => {
                      const source = sourceById.get(id)
                      return source ? (
                        <a
                          key={id}
                          href={source.original_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-micro text-ink-muted underline underline-offset-2"
                        >
                          Fuente central: {source.publisher} ↗
                        </a>
                      ) : null
                    })}
                  </div>
                </article>
              ))}
            </div>
            {otherDebateNews.length > 0 && (
              <details className="mt-8 border border-line-hairline bg-surface-card p-5">
                <summary className="cursor-pointer text-body font-semibold text-ink-primary">
                  {tr('Otras aristas y tramitación', 'Other angles and legislative process')} · {otherDebateNews.length}{' '}
                  {tr('publicaciones', 'publications')}
                </summary>
                <p className="mt-3 max-w-3xl text-caption text-ink-secondary">
                  {tr(
                    'Estas piezas forman parte del debate público —votaciones, negociación, procedimiento y materias que aún no tienen una pregunta factual propia—. Se muestran para que ninguna captura desaparezca por no encajar en las cuatro evaluaciones actuales.',
                    'These pieces are part of the public debate—votes, negotiation, procedure and topics that do not yet have their own factual question. They are shown so no capture disappears merely because it does not fit the four current evaluations.',
                  )}
                </p>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {otherDebateNews.map((source) => (
                    <a
                      key={source.id}
                      href={source.original_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="border border-line-hairline bg-surface-raised p-3 text-caption text-ink-secondary hover:border-line-strong"
                    >
                      <span className="block text-micro font-semibold uppercase text-ink-muted">
                        {source.publisher} · {new Date(source.published_at).toLocaleDateString(locale)}
                      </span>
                      <span className="mt-1 block text-ink-primary">{source.title} ↗</span>
                    </a>
                  ))}
                </div>
              </details>
            )}
          </section>

          <section id="evidencia-comparada" className="mt-24 scroll-mt-36 border-t border-line-hairline pt-12 lg:scroll-mt-24">
            <div className="max-w-3xl">
              <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                {tr('Teoría y evidencia global', 'Theory and global evidence')}
              </p>
              <h2 className="mt-3 text-title font-semibold text-ink-primary">
                {tr('¿Qué sabemos fuera de este debate?', 'What do we know beyond this debate?')}
              </h2>
              <p className="mt-4 text-body text-ink-secondary">
                {tr(
                  'El modelo local contrastó cada mecanismo con evidencia empírica e institucional internacional. No traslada automáticamente un resultado extranjero a Chile: separa lo respaldado, lo condicional y lo que aún debe medirse.',
                  'The local model contrasted each mechanism with international empirical and institutional evidence. It does not automatically transfer a foreign result to Chile: it separates what is supported, what is conditional and what still needs to be measured.',
                )}
              </p>
            </div>
            <div className="mt-8 grid gap-5 lg:grid-cols-2">
              {theory.topics.map((topic) => (
                <article key={topic.id} className="border border-line-hairline bg-surface-card p-6 sm:p-8">
                  <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">
                    {tr('Pregunta comparada', 'Comparative question')}
                  </p>
                  <h3 className="mt-2 text-lede font-semibold text-ink-primary">{topic.question}</h3>
                  <p className="mt-4 border-l-2 border-line-strong pl-4 text-body text-ink-primary">
                    {topic.bottom_line}
                  </p>
                  <ul className="mt-5 space-y-2 pl-5 text-caption text-ink-secondary">
                    {topic.findings.map((finding) => (
                      <li key={finding} className="list-disc">
                        {finding}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-5 text-caption text-ink-secondary">
                    <span className="font-semibold text-ink-primary">
                      {tr('Aplicado a la reforma', 'Applied to the reform')}:
                    </span>{' '}
                    {topic.application_to_reform}
                  </p>
                  <details className="mt-4 border-t border-line-hairline pt-3">
                    <summary className="cursor-pointer text-caption font-semibold">
                      {tr('Límites y referencias', 'Limitations and references')}
                    </summary>
                    <p className="mt-3 text-caption text-ink-secondary">{topic.limits}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {topic.source_ids.map((id) => {
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
                            {source?.publisher ?? id} {gap ? tr('(no archivada)', '(not archived)') : ''} ↗
                          </a>
                        ) : null
                      })}
                    </div>
                  </details>
                </article>
              ))}
            </div>
            <p className="mt-5 text-micro text-ink-muted">
              Qwen local · {theory.model.usage.total_tokens.toLocaleString(locale)} tokens ·{' '}
              {tr('salida JSON validada', 'validated JSON output')} · 0{' '}
              {tr('llamadas de IA desde esta página.', 'AI calls from this page.')}
            </p>
          </section>
          </div>
        </div>
      )}

      {view === 'actors' && (
        <>
          <section className="border-b border-line-hairline pb-12 pt-4 sm:pb-16">
            <p className="text-micro font-semibold uppercase tracking-[0.2em] text-ink-muted">
              {tr('Registro público y archivo', 'Public records and archive')}
            </p>
            <h1 className="mt-5 max-w-4xl text-display font-semibold text-ink-primary">
              {tr('Actores, municipios y fuentes.', 'Actors, municipalities and sources.')}
            </h1>
            <p className="mt-6 max-w-3xl text-lede text-ink-secondary">
              {tr(
                'Quién intervino en el debate, qué sostuvo, qué trayectoria pública está verificada y dónde consultar cada publicación original. Esta información está separada del análisis factual de la reforma.',
                'Who entered the debate, what they argued, which parts of their public record were verified, and where to consult every original publication. This information is kept separate from the factual analysis of the reform.',
              )}
            </p>
            <dl className="mt-8 grid max-w-4xl grid-cols-2 gap-px bg-line-hairline sm:grid-cols-4">
              {[
                [tr('Actores', 'Actors'), census.coverage.actors_indexed],
                [tr('Menciones verificadas', 'Verified mentions'), census.coverage.accepted_mentions],
                [tr('Capturas', 'Captures'), sources.capture_count],
                [tr('Brechas', 'Gaps'), sources.gap_count],
              ].map(([label, value]) => (
                <div key={label} className="bg-surface-card p-4">
                  <dt className="text-micro uppercase text-ink-muted">{label}</dt>
                  <dd className="mt-2 text-title font-semibold tabular text-ink-primary">
                    <AnimatedNumber value={Number(value)} locale={locale} />
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <Suspense
            fallback={
              <p className="mt-16 border border-line-hairline bg-surface-card p-6 text-caption text-ink-secondary">
                {tr('Preparando mapa interactivo de actores…', 'Preparing the interactive actor map…')}
              </p>
            }
          >
            <ActorMap actors={census.actors} />
          </Suspense>

          <section id="censo-actores" className="mt-24 border-t border-line-hairline pt-12">
            <div className="grid gap-8 lg:grid-cols-[1fr_20rem] lg:items-start">
              <div className="max-w-3xl">
                <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                  {tr('Censo del corpus completo', 'Complete corpus census')}
                </p>
                <h2 className="mt-3 text-title font-semibold text-ink-primary">
                  {tr('Todos los actores sustantivos encontrados', 'Every substantive actor found')}
                </h2>
                <p className="mt-4 text-body text-ink-secondary">
                  {census.coverage.universe}{' '}
                  {tr(
                    'Cada mención conserva una cita literal y la publicación donde aparece; nombres en firmas, menús o notas relacionadas fueron excluidos.',
                    'Each mention preserves a verbatim quotation and the publication where it appears; names in bylines, menus or related stories were excluded.',
                  )}
                </p>
              </div>
              <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
                <p className="font-semibold text-ink-primary">
                  {census.coverage.actors_indexed} {tr('actores', 'actors')} · {census.coverage.people}{' '}
                  {tr('personas', 'people')} · {census.coverage.institutions} {tr('instituciones', 'institutions')}
                </p>
                <p className="mt-3">
                  {census.coverage.captured_sources_audited}/{census.coverage.captured_sources_total}{' '}
                  {tr('capturas auditadas', 'captures audited')} · {census.coverage.accepted_mentions}{' '}
                  {tr('menciones verificadas', 'verified mentions')}
                </p>
                <p className="mt-3">
                  {census.coverage.detailed_profiles}{' '}
                  {tr('fichas con trayectoria verificada', 'profiles with verified records')} ·{' '}
                  {census.coverage.indexed_only}{' '}
                  {tr('actores conservados como índice documental', 'actors retained as a document index')}
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
                      {language === 'es' ? label : ACTOR_TYPE_EN[type]} · {group.length}
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
                              {actor.profile_depth === 'detailed'
                                ? tr('ficha ampliada', 'expanded profile')
                                : tr('índice verificado', 'verified index')}
                            </span>
                          </div>
                          <p className="mt-3 text-caption text-ink-primary">{actor.participation_summary}</p>
                          <details className="mt-3">
                            <summary className="cursor-pointer text-caption font-semibold">
                              {actor.source_ids.length}{' '}
                              {actor.source_ids.length === 1 ? tr('fuente', 'source') : tr('fuentes', 'sources')} ·{' '}
                              {tr('ver evidencia', 'view evidence')}
                            </summary>
                            <div className="mt-3 space-y-3">
                              {actor.mentions.map((mention, index) => {
                                const source = sourceById.get(mention.source_id)
                                return (
                                  <div
                                    key={`${mention.source_id}-${index}`}
                                    className="border-l-2 border-line-strong pl-3 text-caption text-ink-secondary"
                                  >
                                    <p>{mention.action_or_position}</p>
                                    <blockquote className="mt-2">“{mention.evidence_quote}”</blockquote>
                                    {source && (
                                      <a
                                        href={source.original_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="mt-2 inline-block text-micro font-semibold underline underline-offset-2"
                                      >
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
              <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                {tr('Quién es quién', 'Who is who')}
              </p>
              <h2 className="mt-3 text-title font-semibold">{tr('Actores citados', 'Cited actors')}</h2>
              <p className="mt-4 text-body text-ink-secondary">
                {tr(
                  'Pasa el cursor o enfoca un nombre en el debate para ver su ficha. Los antecedentes se muestran aparte: nunca cambian un veredicto factual.',
                  'Hover over or focus a name in the debate to see its profile. Background records are shown separately and never change a factual verdict.',
                )}
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
                    {tr('Foto', 'Photo')}: {actor.image_credit} · {actor.image_license}
                  </p>
                  <details className="mt-4 border-t border-line-hairline pt-3">
                    <summary className="cursor-pointer text-caption font-semibold">
                      {tr('Trayectoria y acciones verificadas', 'Verified record and actions')}
                    </summary>
                    <ul className="mt-3 space-y-1 text-caption text-ink-secondary">
                      {actor.roles.map((role) => (
                        <li key={role}>· {role}</li>
                      ))}
                    </ul>
                    {actor.public_record.map((record) => (
                      <div
                        key={`${record.date}-${record.action}`}
                        className="mt-4 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary"
                      >
                        <p className="font-semibold text-ink-primary">
                          {record.date} ·{' '}
                          {record.status === 'pending'
                            ? tr('resultado pendiente', 'outcome pending')
                            : record.status === 'observed'
                              ? tr('resultado observado', 'outcome observed')
                              : tr('no medible', 'not measurable')}
                        </p>
                        <p className="mt-1">{record.action}</p>
                        <p className="mt-2">
                          <span className="font-semibold text-ink-primary">{tr('Resultado', 'Outcome')}:</span>{' '}
                          {record.outcome}
                        </p>
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
                  {tr('Impacto territorial', 'Territorial impact')}
                </p>
                <h2 className="mt-3 text-title font-semibold">
                  {tr('Las voces municipales, sin recortes', 'Municipal voices, without omissions')}
                </h2>
                <p className="mt-4 text-body text-ink-secondary">
                  {municipal.coverage.universe} {municipal.coverage.method}
                </p>
              </div>
              <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
                <p className="font-semibold text-ink-primary">
                  {municipal.coverage.actors_indexed} {tr('alcaldes/as', 'mayors')} ·{' '}
                  {municipal.coverage.municipal_sources_curated} {tr('fuentes', 'sources')}
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
                          alt={actor.image_alt || `${tr('Retrato de', 'Portrait of')} ${actor.name}`}
                          className="h-16 w-14 shrink-0 object-cover object-top grayscale"
                          loading="lazy"
                        />
                      ) : (
                        <span
                          aria-hidden="true"
                          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-caption font-semibold text-ink-primary"
                        >
                          {actor.name
                            .split(' ')
                            .map((part) => part[0])
                            .slice(0, 2)
                            .join('')}
                        </span>
                      )}
                      <div>
                        <h3 className="text-body font-semibold text-ink-primary">{actor.name}</h3>
                        <p className="mt-1 text-caption text-ink-secondary">
                          {actor.role} · {actor.municipality} · {actor.affiliation}
                        </p>
                      </div>
                    </div>
                    <p className="mt-4 text-micro font-semibold uppercase tracking-wide text-ink-muted">
                      {language === 'es'
                        ? group.label
                        : {
                            government_formula: 'Supports the agreed formula',
                            targeted_exemption: 'Calls for targeting and redistribution',
                            revenue_protection: 'Prioritizes revenue protection',
                            dialogue_participant: 'Participates in negotiation',
                          }[actor.position_group]}
                    </p>
                    <p className="mt-2 text-caption text-ink-primary">{actor.position_summary}</p>
                    <details className="mt-4 border-t border-line-hairline pt-3">
                      <summary className="cursor-pointer text-caption font-semibold">
                        {tr('Acción, resultado y fuentes', 'Action, outcome and sources')}
                      </summary>
                      <p className="mt-3 text-caption text-ink-secondary">{record.action}</p>
                      <p className="mt-3 text-caption text-ink-secondary">
                        <span className="font-semibold text-ink-primary">{tr('Resultado', 'Outcome')}:</span>{' '}
                        {record.outcome}
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
                              {source?.publisher ?? id} {gap ? tr('(brecha)', '(gap)') : ''} ↗
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
                <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
                  {tr('Barrido documental', 'Document sweep')}
                </p>
                <h2 className="mt-3 text-title font-semibold">
                  {tr('Publicaciones originales', 'Original publications')}
                </h2>
                <p className="mt-4 text-body text-ink-secondary">
                  {tr(
                    'Cada tarjeta abre la publicación original y usa una captura local tomada durante la recolección. Las fuentes no capturadas permanecen como brechas explícitas.',
                    'Each card opens the original publication and uses a local capture taken during collection. Sources that could not be captured remain visible as explicit gaps.',
                  )}
                </p>
              </div>
              <p className="text-caption text-ink-secondary">
                {sources.capture_count} {tr('capturas', 'captures')} ·{' '}
                {sources.items.filter((source) => source.format === 'video' || source.format === 'audio').length}{' '}
                video/audio · {sources.gap_count} {tr('brechas', 'gaps')}
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
                  {tr('Ver', 'View')} {sources.gaps.length} {tr('fuentes no capturadas', 'uncaptured sources')}
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
      )}
    </>
  )
}

function loadActorImage(path: string): string {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.endsWith('/') ? base : `${base}/`}data/${path}`
}

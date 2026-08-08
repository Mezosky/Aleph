import { useEffect, useMemo, useRef, useState } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { UMAP } from 'umap-js'
import type { CensusActor } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

type Sector =
  'left' | 'centre_left' | 'centre' | 'centre_right' | 'right' | 'independent' | 'institutional' | 'undocumented'

const SECTORS: Record<Sector, { label: string; color: string; glyph: string; score: number }> = {
  left: { label: 'Izquierda declarada', color: 'var(--cat-4)', glyph: '◀', score: -2 },
  centre_left: { label: 'Centroizquierda declarada', color: 'var(--cat-3)', glyph: '◆', score: -1 },
  centre: { label: 'Centro / transversal', color: 'var(--cat-5)', glyph: '●', score: 0 },
  centre_right: { label: 'Centroderecha declarada', color: 'var(--cat-1)', glyph: '■', score: 1 },
  right: { label: 'Derecha declarada', color: 'var(--cat-2)', glyph: '▶', score: 2 },
  independent: {
    label: 'Independiente',
    color: 'var(--ink-muted)',
    glyph: '×',
    score: 0,
  },
  institutional: {
    label: 'Institución · no aplica',
    color: 'var(--line-strong)',
    glyph: '◇',
    score: 0,
  },
  undocumented: {
    label: 'Afiliación no documentada',
    color: 'var(--ink-secondary)',
    glyph: '?',
    score: 0,
  },
}
const SECTOR_EN: Record<Sector, string> = {
  left: 'Declared left',
  centre_left: 'Declared centre-left',
  centre: 'Centre / cross-party',
  centre_right: 'Declared centre-right',
  right: 'Declared right',
  independent: 'Independent',
  institutional: 'Institution · not applicable',
  undocumented: 'Affiliation not documented',
}

const ACTOR_VISUAL: Record<CensusActor['actor_type'], { symbol: string; glyph: string; es: string; en: string }> = {
  government: { symbol: 'diamond', glyph: '◆', es: 'Gobierno', en: 'Government' },
  legislator: { symbol: 'circle', glyph: '●', es: 'Congreso', en: 'Congress' },
  mayor: { symbol: 'square', glyph: '■', es: 'Municipios', en: 'Municipalities' },
  political_party: { symbol: 'star', glyph: '★', es: 'Partidos', en: 'Political parties' },
  municipal_association: {
    symbol: 'hexagon',
    glyph: '⬢',
    es: 'Asociaciones municipales',
    en: 'Municipal associations',
  },
  technical_body: { symbol: 'triangle-up', glyph: '▲', es: 'Órganos técnicos', en: 'Technical bodies' },
  judiciary: { symbol: 'pentagon', glyph: '⬟', es: 'Justicia', en: 'Judiciary' },
  business: { symbol: 'triangle-down', glyph: '▼', es: 'Gremios y empresas', en: 'Business' },
  union: { symbol: 'triangle-up', glyph: '△', es: 'Sindicatos', en: 'Trade unions' },
  civil_society: { symbol: 'cross', glyph: '✚', es: 'Sociedad civil', en: 'Civil society' },
  academic: { symbol: 'cross', glyph: '＋', es: 'Academia', en: 'Academia' },
  international_organization: {
    symbol: 'hexagram',
    glyph: '✦',
    es: 'Organismos internacionales',
    en: 'International organizations',
  },
  other: { symbol: 'x', glyph: '×', es: 'Otros', en: 'Other' },
}

function sectorFor(actor: CensusActor): Sector {
  if (actor.affiliation_status === 'institutional_not_applicable') return 'institutional'
  if (actor.affiliation_status === 'not_documented') return 'undocumented'
  if (actor.affiliation_status === 'independent_public_record') return 'independent'
  const value = `${actor.affiliation} ${actor.institution}`.toLocaleLowerCase('es')
  if (/partido comunista|\bpc\b|frente amplio/.test(value)) return 'left'
  if (
    /partido socialista|\bps\b|partido por la democracia|\bppd\b|partido liberal|federación regionalista|\bfrevs\b/.test(
      value,
    )
  )
    return 'centre_left'
  if (/partido de la gente|\bpdg\b|demócrata cristiano|\bpdc\b|demócratas/.test(value)) return 'centre'
  if (/renovación nacional|\brn\b|evolución política|evópoli/.test(value)) return 'centre_right'
  if (/partido republicano|unión demócrata independiente|\budi\b|\bpnl\b/.test(value)) return 'right'
  if (/independiente/.test(value)) return 'independent'
  return 'undocumented'
}

function affiliationDescription(actor: CensusActor, tr: (es: string, en: string) => string) {
  if (actor.affiliation_status === 'institutional_not_applicable') {
    return tr('Afiliación partidaria no aplica', 'Party affiliation does not apply')
  }
  if (actor.affiliation_status === 'not_documented') {
    return tr('Afiliación no documentada', 'Affiliation not documented')
  }
  return actor.affiliation
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state += 0x6d2b79f5
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function actorVectors(actors: CensusActor[]): number[][] {
  const actorTypes = [...new Set(actors.map((actor) => actor.actor_type))].sort()
  const sources = [...new Set(actors.flatMap((actor) => actor.source_ids))].sort()
  return actors.map((actor) => {
    const sector = sectorFor(actor)
    return [
      SECTORS[sector].score / 2,
      actor.profile_depth === 'detailed' ? 1 : 0,
      ...actorTypes.map((type) => (actor.actor_type === type ? 1 : 0)),
      ...sources.map((source) => (actor.source_ids.includes(source) ? 0.7 : 0)),
    ]
  })
}

export default function ActorMap({ actors }: { actors: CensusActor[] }) {
  const { language, tr } = useLanguage()
  const chartRef = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<CensusActor | null>(null)
  const embedding = useMemo(() => {
    if (actors.length < 3) return actors.map((_, index) => [index, 0])
    const umap = new UMAP({
      nComponents: 2,
      nNeighbors: Math.min(12, actors.length - 1),
      minDist: 0.18,
      spread: 1,
      random: seededRandom(1821605),
    })
    return umap.fit(actorVectors(actors))
  }, [actors])
  const sectorSummary = useMemo(
    () =>
      (Object.keys(SECTORS) as Sector[])
        .map((sector) => {
          const members = actors.filter((actor) => sectorFor(actor) === sector)
          return {
            sector,
            actors: members.length,
            mentions: members.reduce((total, actor) => total + actor.mentions.length, 0),
          }
        })
        .filter((item) => item.actors > 0)
        .sort((left, right) => right.mentions - left.mentions),
    [actors],
  )
  const actorTypeSummary = useMemo(
    () =>
      [...new Set(actors.map((actor) => actor.actor_type))].sort(
        (left, right) =>
          actors.filter((actor) => actor.actor_type === right).length -
          actors.filter((actor) => actor.actor_type === left).length,
      ),
    [actors],
  )
  const affiliationCoverage = useMemo(() => {
    const people = actors.filter((actor) => actor.entity_kind === 'person')
    return {
      documented: people.filter((actor) => actor.affiliation_status !== 'not_documented').length,
      people: people.length,
    }
  }, [actors])

  useEffect(() => {
    const chart = chartRef.current as Plotly.PlotlyHTMLElement | null
    if (!chart || embedding.length !== actors.length) return
    const rootStyle = window.getComputedStyle(document.documentElement)
    const resolveColor = (token: string) => {
      const property = token.match(/^var\((--[^)]+)\)$/)?.[1]
      return property ? rootStyle.getPropertyValue(property).trim() : token
    }

    const groups = (Object.keys(SECTORS) as Sector[]).map((sector) => ({
      sector,
      points: actors
        .map((actor, index) => ({
          actor,
          coordinates: [embedding[index]?.[0] ?? 0, embedding[index]?.[1] ?? 0] as [number, number],
          index,
        }))
        .filter(({ actor }) => sectorFor(actor) === sector),
    }))
    const traces = groups.flatMap(({ sector, points }) => {
      const color = resolveColor(SECTORS[sector].color)
      const halo = {
        type: 'scattergl' as const,
        mode: 'markers' as const,
        x: points.map(({ coordinates }) => coordinates[0]),
        y: points.map(({ coordinates }) => coordinates[1]),
        hoverinfo: 'skip' as const,
        marker: {
          color,
          symbol: 'circle',
          size: points.map(({ actor }) => Math.min(76, 44 + Math.sqrt(actor.mentions.length) * 7)),
          opacity: sector === 'institutional' || sector === 'undocumented' ? 0.06 : 0.105,
          line: { width: 0 },
        },
        showlegend: false,
      }
      const markers = {
        type: 'scattergl' as const,
        mode: 'markers' as const,
        name: language === 'es' ? SECTORS[sector].label : SECTOR_EN[sector],
        x: points.map(({ coordinates }) => coordinates[0]),
        y: points.map(({ coordinates }) => coordinates[1]),
        text: points.map(({ actor }) => actor.name),
        customdata: points.map(({ actor, index }) => [
          index,
          actor.role || tr('Rol no especificado', 'Role not specified'),
          affiliationDescription(actor, tr),
          ACTOR_VISUAL[actor.actor_type][language],
          actor.mentions.length,
          actor.source_ids.length,
        ]),
        hovertemplate: `<b>%{text}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>%{customdata[3]}<br><b>%{customdata[4]} ${tr('intervenciones verificadas', 'verified interventions')}</b><br>%{customdata[5]} ${tr('fuentes', 'sources')}<extra></extra>`,
        marker: {
          color,
          symbol: points.map(({ actor }) => ACTOR_VISUAL[actor.actor_type].symbol),
          size: points.map(({ actor }) => Math.min(25, 8 + Math.sqrt(actor.mentions.length) * 3.2)),
          opacity: 0.8,
          line: { color: resolveColor('var(--surface-page)'), width: 0.7 },
        },
        showlegend: false,
      }
      return [halo, markers]
    })

    void Plotly.newPlot(
      chart,
      traces,
      {
        autosize: true,
        height: 560,
        margin: { l: 24, r: 24, t: 20, b: 30 },
        paper_bgcolor: resolveColor('var(--surface-sunken)'),
        plot_bgcolor: resolveColor('var(--surface-sunken)'),
        hovermode: 'closest',
        dragmode: 'pan',
        xaxis: { visible: false, fixedrange: false },
        yaxis: { visible: false, fixedrange: false },
      },
      {
        responsive: true,
        displaylogo: false,
        scrollZoom: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d'],
      },
    )

    const onClick = (event: Plotly.PlotMouseEvent) => {
      const index = Number((event.points[0]?.customdata as Array<unknown> | undefined)?.[0])
      if (Number.isInteger(index) && actors[index]) setSelected(actors[index])
    }
    chart.on('plotly_click', onClick)
    return () => {
      chart.removeAllListeners('plotly_click')
      Plotly.purge(chart)
    }
  }, [actors, embedding, language, tr])

  return (
    <section aria-labelledby="actor-map-title" className="mt-16 border-t border-line-hairline pt-12">
      <div className="grid gap-6 lg:grid-cols-[1fr_21rem]">
        <div>
          <p className="text-micro font-semibold uppercase tracking-[0.18em] text-ink-muted">
            {tr('Mapa interactivo de actores', 'Interactive actor map')}
          </p>
          <h2 id="actor-map-title" className="mt-3 text-title font-semibold text-ink-primary">
            {tr('Así se agrupan las voces del debate', 'How the voices in the debate cluster')}
          </h2>
          <p className="mt-4 max-w-3xl text-body text-ink-secondary">
            {tr(
              'Acerca actores que comparten tipo, afiliación registrada y fuentes dentro del corpus. El tamaño muestra cuántas intervenciones verificadas acumula cada actor. Pasa el cursor o toca un punto; arrastra y pellizca para explorar.',
              'Actors are placed closer when they share type, recorded affiliation and sources in the corpus. Size shows how many verified interventions each actor accumulates. Hover or tap a point; drag and pinch to explore.',
            )}
          </p>
          <p className="mt-3 text-caption font-semibold text-ink-primary">
            {affiliationCoverage.documented}/{affiliationCoverage.people}{' '}
            {tr(
              'personas tienen afiliación o independencia documentada; las instituciones figuran aparte como “no aplica”.',
              'people have a documented affiliation or independent status; institutions are separated as “not applicable”.',
            )}
          </p>
        </div>
        <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
          <p className="font-semibold text-ink-primary">
            {tr('No es un puntaje ideológico.', 'This is not an ideology score.')}
          </p>
          <p className="mt-2">
            {tr(
              'Color y halo = sector declarado y su acumulación; icono = tipo de actor; tamaño = intervenciones verificadas en este corpus. La cercanía expresa similitud documental y la disposición puede rotar. Ninguna señal mide extremismo, honestidad ni quién tiene razón.',
              'Color and halo = declared sector and its accumulation; icon = actor type; size = verified interventions in this corpus. Proximity represents documentary similarity and the layout may rotate. No signal measures extremism, honesty or who is right.',
            )}
          </p>
        </aside>
      </div>
      <div
        className="mt-8 grid gap-px bg-line-hairline sm:grid-cols-2 xl:grid-cols-3"
        aria-label={tr('Acumulación por sector declarado', 'Accumulation by declared sector')}
      >
        {sectorSummary.map(({ sector, actors: actorCount, mentions }) => (
          <div key={sector} className="bg-surface-card p-4">
            <p className="flex items-center gap-2 text-caption font-semibold text-ink-primary">
              <span aria-hidden="true" className="text-lede" style={{ color: SECTORS[sector].color }}>
                {SECTORS[sector].glyph}
              </span>
              {language === 'es' ? SECTORS[sector].label : SECTOR_EN[sector]}
            </p>
            <p className="mt-2 text-micro text-ink-muted">
              {actorCount} {actorCount === 1 ? tr('actor', 'actor') : tr('actores', 'actors')} · {mentions}{' '}
              {tr('intervenciones verificadas', 'verified interventions')}
            </p>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-micro text-ink-muted">
        <span className="font-semibold uppercase tracking-wide">{tr('Iconos', 'Icons')}:</span>
        {actorTypeSummary.map((type) => (
          <span key={type} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="text-ink-primary">
              {ACTOR_VISUAL[type].glyph}
            </span>
            {ACTOR_VISUAL[type][language]}
          </span>
        ))}
        <span>· {tr('círculo mayor = más intervenciones', 'larger marker = more interventions')}</span>
      </div>
      <div className="mt-8 border border-line-hairline bg-surface-sunken p-2 sm:p-4">
        <div
          ref={chartRef}
          aria-label={tr('Mapa interactivo de actores', 'Interactive actor map')}
          className="min-h-[35rem] w-full"
        />
      </div>
      {selected && (
        <article className="mt-4 border-l-4 border-line-strong bg-surface-card p-5" aria-live="polite">
          <p className="text-micro font-semibold uppercase text-ink-muted">
            {tr('Actor seleccionado', 'Selected actor')}
          </p>
          <h3 className="mt-2 text-lede font-semibold text-ink-primary">{selected.name}</h3>
          <p className="mt-1 text-caption text-ink-secondary">
            {[selected.role, selected.institution, affiliationDescription(selected, tr)].filter(Boolean).join(' · ')}
          </p>
          {selected.affiliation_source_url && (
            <p className="mt-2 text-micro text-ink-muted">
              <a
                href={selected.affiliation_source_url}
                target="_blank"
                rel="noreferrer"
                className="underline decoration-line-strong underline-offset-4"
              >
                {tr('Afiliación en registro público', 'Affiliation in public record')}
              </a>{' '}
              · {tr('verificada al', 'verified as of')} {selected.affiliation_verified_at}
            </p>
          )}
          <p className="mt-3 text-caption text-ink-primary">{selected.participation_summary}</p>
          <p className="mt-3 text-micro text-ink-muted">
            {language === 'es' ? SECTORS[sectorFor(selected)].label : SECTOR_EN[sectorFor(selected)]} ·{' '}
            {ACTOR_VISUAL[selected.actor_type].glyph} {ACTOR_VISUAL[selected.actor_type][language]} ·{' '}
            {selected.mentions.length} {tr('intervenciones', 'interventions')} · {selected.source_ids.length}{' '}
            {tr('fuentes', 'sources')} ·{' '}
            {selected.profile_depth === 'detailed'
              ? tr('ficha ampliada', 'expanded profile')
              : tr('índice documental', 'document index')}
          </p>
        </article>
      )}
    </section>
  )
}

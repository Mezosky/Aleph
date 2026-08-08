import { useEffect, useMemo, useRef, useState } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { UMAP } from 'umap-js'
import type { CensusActor } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

type Sector = 'left' | 'centre_left' | 'centre' | 'centre_right' | 'right' | 'unaffiliated'

const SECTORS: Record<Sector, { label: string; symbol: string; score: number }> = {
  left: { label: 'Izquierda declarada', symbol: 'triangle-left', score: -2 },
  centre_left: { label: 'Centroizquierda declarada', symbol: 'diamond', score: -1 },
  centre: { label: 'Centro / transversal', symbol: 'circle', score: 0 },
  centre_right: { label: 'Centroderecha declarada', symbol: 'square', score: 1 },
  right: { label: 'Derecha declarada', symbol: 'triangle-right', score: 2 },
  unaffiliated: {
    label: 'Independiente o no informado',
    symbol: 'x',
    score: 0,
  },
}
const SECTOR_EN: Record<Sector, string> = {
  left: 'Declared left',
  centre_left: 'Declared centre-left',
  centre: 'Centre / cross-party',
  centre_right: 'Declared centre-right',
  right: 'Declared right',
  unaffiliated: 'Independent or undisclosed',
}

function sectorFor(actor: CensusActor): Sector {
  const value = `${actor.affiliation} ${actor.institution}`.toLocaleLowerCase('es')
  if (/partido comunista|\bpc\b|frente amplio/.test(value)) return 'left'
  if (/partido socialista|\bps\b|partido por la democracia|\bppd\b/.test(value)) return 'centre_left'
  if (/partido de la gente|\bpdg\b/.test(value)) return 'centre'
  if (/renovación nacional|\brn\b/.test(value)) return 'centre_right'
  if (/partido republicano|unión demócrata independiente|\budi\b|\bpnl\b/.test(value)) return 'right'
  return actor.affiliation ? 'centre' : 'unaffiliated'
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

  useEffect(() => {
    const chart = chartRef.current as Plotly.PlotlyHTMLElement | null
    if (!chart || embedding.length !== actors.length) return
    const rootStyle = window.getComputedStyle(document.documentElement)
    const resolveColor = (token: string) => {
      const property = token.match(/^var\((--[^)]+)\)$/)?.[1]
      return property ? rootStyle.getPropertyValue(property).trim() : token
    }

    const traces = (Object.keys(SECTORS) as Sector[]).map((sector) => {
      const points = actors
        .map((actor, index) => ({
          actor,
          coordinates: [embedding[index]?.[0] ?? 0, embedding[index]?.[1] ?? 0] as [number, number],
          index,
        }))
        .filter(({ actor }) => sectorFor(actor) === sector)
      return {
        type: 'scattergl' as const,
        mode: 'markers' as const,
        name:
          language === 'es' ? SECTORS[sector].label : SECTOR_EN[sector],
        x: points.map(({ coordinates }) => coordinates[0]),
        y: points.map(({ coordinates }) => coordinates[1]),
        text: points.map(({ actor }) => actor.name),
        customdata: points.map(({ actor, index }) => [
          index,
          actor.role || tr('Rol no especificado', 'Role not specified'),
          actor.affiliation || tr('Sin afiliación informada', 'No affiliation reported'),
          actor.source_ids.length,
        ]),
        hovertemplate: `<b>%{text}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>%{customdata[3]} ${tr('fuentes', 'sources')}<extra></extra>`,
        marker: {
          color: resolveColor('var(--ink-secondary)'),
          symbol: SECTORS[sector].symbol,
          size: points.map(({ actor }) => (actor.profile_depth === 'detailed' ? 13 : 9)),
          opacity: 0.82,
          line: { color: resolveColor('var(--surface-page)'), width: 0.7 },
        },
      }
    })

    void Plotly.newPlot(
      chart,
      traces,
      {
        autosize: true,
        height: 560,
        margin: { l: 24, r: 24, t: 20, b: 30 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        hovermode: 'closest',
        dragmode: 'pan',
        legend: { orientation: 'h', y: -0.08, x: 0, font: { size: 11 } },
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
            {tr('Explorador interactivo', 'Interactive explorer')}
          </p>
          <h2 id="actor-map-title" className="mt-3 text-title font-semibold text-ink-primary">
            {tr('Mapa UMAP de actores y afiliaciones declaradas', 'UMAP of actors and declared affiliations')}
          </h2>
          <p className="mt-4 max-w-3xl text-body text-ink-secondary">
            {tr(
              'Acerca actores que comparten tipo, afiliación registrada y fuentes dentro del corpus. Pasa el cursor o toca un punto para identificarlo; arrastra y pellizca para explorar.',
              'Actors are placed closer when they share type, recorded affiliation and sources in the corpus. Hover or tap a point to identify it; drag and pinch to explore.',
            )}
          </p>
        </div>
        <aside className="border-l-2 border-line-strong pl-5 text-caption text-ink-secondary">
          <p className="font-semibold text-ink-primary">
            {tr('No es un puntaje ideológico.', 'This is not an ideology score.')}
          </p>
          <p className="mt-2">
            {tr(
              'La forma de cada punto traduce afiliaciones públicas a sectores descriptivos; el color permanece neutral. La posición UMAP expresa similitud documental y puede rotar; no mide extremismo, honestidad ni quién tiene razón.',
              'Point shape maps public affiliations to descriptive sectors while color remains neutral. UMAP position represents documentary similarity and may rotate; it does not measure extremism, honesty or who is right.',
            )}
          </p>
        </aside>
      </div>
      <div className="mt-8 border border-line-hairline bg-surface-card p-2 sm:p-4">
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
            {[selected.role, selected.institution, selected.affiliation].filter(Boolean).join(' · ')}
          </p>
          <p className="mt-3 text-caption text-ink-primary">{selected.participation_summary}</p>
          <p className="mt-3 text-micro text-ink-muted">
            {language === 'es' ? SECTORS[sectorFor(selected)].label : SECTOR_EN[sectorFor(selected)]} ·{' '}
            {selected.source_ids.length} {tr('fuentes', 'sources')} ·{' '}
            {selected.profile_depth === 'detailed'
              ? tr('ficha ampliada', 'expanded profile')
              : tr('índice documental', 'document index')}
          </p>
        </article>
      )}
    </section>
  )
}

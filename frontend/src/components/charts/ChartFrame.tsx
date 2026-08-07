/**
 * The frame every Aleph chart is drawn inside.
 *
 * Four things are non-optional here, because each one is a product rule rather
 * than a decoration:
 *
 *  1. A "ver datos" toggle that swaps the graphic for a real `<table>` of the
 *     same numbers. Colour and length are one channel; the table is the other,
 *     and it is the one that survives colour-vision deficiency, a screen reader
 *     and a printer.
 *  2. Evidence confidence printed prominently, model confidence printed beneath
 *     it and marked as a diagnostic. A high model confidence over thin evidence
 *     is not reassurance and must never look like it.
 *  3. A permanent `data_status` marker. Synthetic data says so where the data
 *     is, not only in a page header a reader may have scrolled past.
 *  4. An opt-in `overflow-x` container, so a wide chart scrolls inside itself
 *     and never gives the page a horizontal scrollbar.
 *
 * The helpers exported alongside it — `ComponentBreakdown`, `InspectorPanel`,
 * `ConfidenceReadout`, `StatusLabel`, `ChartLegend`, `ChartTooltip` — exist so
 * that every chart opens its numbers the same way. A score with no route to its
 * components is a bug in this product, not a simplification.
 */

import { useId, useState, type ReactNode } from 'react'
import clsx from 'clsx'
import type { AlephId, Component, Confidence, DataStatus } from '@/types/aleph'
import { formatConfidence, formatNumber, formatScore } from '@/lib/format'
import { divergingColor, type StatusToken } from '@/lib/viz'

/* ------------------------------------------------------------------ *
 * The table view — the required non-visual channel
 * ------------------------------------------------------------------ */

export interface ChartTableColumn {
  key: string
  label: string
  /** Right-aligned and tabular-figured. */
  numeric?: boolean
}

export interface ChartTableRow {
  key: string
  /** Positionally aligned with `columns`. The first cell becomes the row header. */
  cells: ReactNode[]
}

export interface ChartTableSpec {
  /** Read out before the table. Say what the rows are, not "tabla de datos". */
  caption: string
  columns: ChartTableColumn[]
  rows: ChartTableRow[]
}

/* ------------------------------------------------------------------ *
 * Data-status marker
 * ------------------------------------------------------------------ */

const DATA_STATUS_NOTE: Record<DataStatus, { label: string; detail: string }> = {
  synthetic: {
    label: 'Datos sintéticos',
    detail:
      'Estas cifras son un ejemplo construido para mostrar el procedimiento. No describen ninguna reforma, medio ni declaración real.',
  },
  derived: {
    label: 'Datos derivados',
    detail: 'Calculados a partir de otras fuentes de este mismo análisis.',
  },
  partial: {
    label: 'Datos parciales',
    detail: 'Falta parte del material que este gráfico debería cubrir.',
  },
  stale: {
    label: 'Datos desactualizados',
    detail: 'La recolección de evidencia es anterior a los hechos más recientes.',
  },
}

/* ------------------------------------------------------------------ *
 * ChartFrame
 * ------------------------------------------------------------------ */

export interface ChartFrameProps {
  title: string
  subtitle?: ReactNode
  /**
   * Rendered between the header and the chart. Use it for anything that changes
   * how the chart must be READ — e.g. that the impact axes are not party labels.
   */
  notice?: ReactNode
  legend?: ReactNode
  /** Extra controls in the header, to the left of the "ver datos" toggle. */
  actions?: ReactNode
  /** Method / source line under the chart. */
  footnote?: ReactNode
  confidence?: Confidence | null
  dataStatus?: DataStatus | null
  table: ChartTableSpec
  /** True when the graphic is wider than a phone. Adds the overflow-x container. */
  scroll?: boolean
  /** Rem-based minimum width for the scrolling area. */
  minWidthClass?: string
  headingLevel?: 2 | 3 | 4
  className?: string
  children: ReactNode
}

export function ChartFrame({
  title,
  subtitle,
  notice,
  legend,
  actions,
  footnote,
  confidence,
  dataStatus,
  table,
  scroll = false,
  minWidthClass = 'min-w-[34rem]',
  headingLevel = 3,
  className,
  children,
}: ChartFrameProps) {
  const baseId = useId()
  const [showTable, setShowTable] = useState(false)
  const panelId = `${baseId}-panel`
  const titleId = `${baseId}-title`
  const HeadingTag = `h${headingLevel}` as 'h2' | 'h3' | 'h4'
  const status = dataStatus ? DATA_STATUS_NOTE[dataStatus] : null

  return (
    <figure
      aria-labelledby={titleId}
      className={clsx(
        'rounded-data border border-line-hairline bg-surface-card',
        'px-4 py-5 sm:px-6 sm:py-7',
        className,
      )}
    >
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <HeadingTag
            id={titleId}
            className="text-body font-semibold tracking-tight text-ink-primary"
          >
            {title}
          </HeadingTag>
          {subtitle ? (
            <p className="mt-1 max-w-prose text-caption text-ink-secondary">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-pressed={showTable}
            aria-controls={panelId}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-data border px-2.5 py-1.5',
              'text-micro uppercase tracking-wide transition-colors duration-200 ease-subtle',
              showTable
                ? 'border-line-strong bg-surface-sunken text-ink-primary'
                : 'border-line-hairline bg-surface-card text-ink-secondary hover:border-line-strong hover:text-ink-primary',
            )}
          >
            <span aria-hidden="true">{showTable ? '▤' : '▦'}</span>
            {showTable ? 'Ver gráfico' : 'Ver datos'}
          </button>
        </div>
      </header>

      {status ? (
        <p className="mt-4 flex flex-wrap items-baseline gap-x-2 gap-y-1 border-l-2 border-line-strong pl-3 text-caption text-ink-secondary">
          <span className="text-micro font-semibold uppercase tracking-wide text-ink-primary">
            {status.label}
          </span>
          <span>{status.detail}</span>
        </p>
      ) : null}

      {notice ? <div className="mt-4">{notice}</div> : null}
      {legend ? <div className="mt-4">{legend}</div> : null}

      <div id={panelId} className="mt-5">
        {showTable ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-caption">
              <caption className="sr-only">{table.caption}</caption>
              <thead>
                <tr className="border-b border-line-strong">
                  {table.columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      className={clsx(
                        'whitespace-nowrap px-2 py-2 text-micro font-semibold uppercase tracking-wide text-ink-secondary',
                        column.numeric ? 'text-right' : 'text-left',
                      )}
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row) => (
                  <tr key={row.key} className="border-b border-line-hairline align-top">
                    {row.cells.map((cell, index) => {
                      const column = table.columns[index]
                      const numeric = column?.numeric ?? false
                      const cellClass = clsx(
                        'px-2 py-2',
                        numeric ? 'text-right tabular' : 'text-left',
                      )
                      return index === 0 ? (
                        <th
                          key={column?.key ?? index}
                          scope="row"
                          className={clsx(cellClass, 'font-medium text-ink-primary')}
                        >
                          {cell}
                        </th>
                      ) : (
                        <td key={column?.key ?? index} className={clsx(cellClass, 'text-ink-secondary')}>
                          {cell}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : scroll ? (
          <div className="-mx-1 overflow-x-auto px-1">
            <div className={minWidthClass}>{children}</div>
          </div>
        ) : (
          children
        )}
      </div>

      {footnote || confidence ? (
        <figcaption className="mt-6 border-t border-line-hairline pt-4">
          {footnote ? (
            <p className="max-w-prose text-caption text-ink-secondary">{footnote}</p>
          ) : null}
          {confidence ? <ConfidenceReadout confidence={confidence} className="mt-3" /> : null}
        </figcaption>
      ) : null}
    </figure>
  )
}

/* ------------------------------------------------------------------ *
 * Confidence — evidence first, model second
 * ------------------------------------------------------------------ */

export interface ConfidenceReadoutProps {
  confidence?: Confidence | null
  className?: string
}

export function ConfidenceReadout({ confidence, className }: ConfidenceReadoutProps) {
  if (!confidence) return null
  const evidence = confidence.evidence_confidence
  const width = `${Math.max(0, Math.min(1, evidence)) * 100}%`

  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-micro uppercase tracking-wide text-ink-secondary">
          Confianza de la evidencia
        </span>
        <span className="tabular text-body font-semibold text-ink-primary">
          {formatConfidence(evidence)}
        </span>
        <span
          aria-hidden="true"
          className="h-1.5 w-24 shrink-0 overflow-hidden rounded-[2px] bg-surface-sunken"
        >
          <span
            className="block h-full rounded-[2px]"
            style={{ width, backgroundColor: 'var(--ink-primary)' }}
          />
        </span>
      </div>
      {typeof confidence.model_confidence === 'number' ? (
        <p className="text-micro text-ink-muted">
          Confianza del modelo {formatConfidence(confidence.model_confidence)} — diagnóstico
          secundario. No sustituye a la evidencia.
        </p>
      ) : null}
      {confidence.limiting_factor ? (
        <p className="max-w-prose text-caption text-ink-secondary">
          <span className="text-ink-muted">Principal límite: </span>
          {confidence.limiting_factor}
        </p>
      ) : null}
      {confidence.basis && confidence.basis.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {confidence.basis.map((entry, index) => (
            <li
              key={`${entry.factor}-${index}`}
              title={entry.note ?? undefined}
              className="rounded-[2px] border border-line-hairline px-1.5 py-0.5 text-micro text-ink-secondary"
            >
              <span aria-hidden="true" className="text-ink-muted">
                {entry.effect === 'raises' ? '↑' : entry.effect === 'lowers' ? '↓' : '·'}{' '}
              </span>
              {CONFIDENCE_FACTOR_LABELS[entry.factor] ?? entry.factor}
              <span className="sr-only">
                {entry.effect === 'raises'
                  ? ' (sube la confianza)'
                  : entry.effect === 'lowers'
                    ? ' (baja la confianza)'
                    : ' (neutral)'}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

const CONFIDENCE_FACTOR_LABELS: Record<string, string> = {
  primary_source_coverage: 'Cobertura de fuente primaria',
  evidence_agreement: 'Acuerdo entre evidencias',
  temporal_consistency: 'Consistencia temporal',
  quantitative_validation: 'Validación cuantitativa',
  source_independence: 'Independencia de fuentes',
  retrieval_completeness: 'Completitud de la recuperación',
  claim_ambiguity: 'Ambigüedad de la afirmación',
}

/* ------------------------------------------------------------------ *
 * Status chip — never colour alone
 * ------------------------------------------------------------------ */

export interface StatusLabelProps {
  token: StatusToken
  /** Overrides the token's own label when the caller has a better one. */
  label?: string
  bordered?: boolean
  className?: string
}

export function StatusLabel({ token, label, bordered = false, className }: StatusLabelProps) {
  return (
    <span
      title={token.description}
      className={clsx(
        'inline-flex items-center gap-1.5 whitespace-nowrap text-caption text-ink-primary',
        bordered && 'rounded-[2px] border border-line-hairline px-1.5 py-0.5',
        className,
      )}
    >
      <span aria-hidden="true" className="text-[0.7em] leading-none" style={{ color: token.color }}>
        {token.icon}
      </span>
      {label ?? token.label}
    </span>
  )
}

/* ------------------------------------------------------------------ *
 * Legend
 * ------------------------------------------------------------------ */

export interface ChartLegendItem {
  id: string
  label: string
  /** CSS custom-property reference from viz.ts. Never a literal colour. */
  color?: string
  icon?: string
  note?: string
  /** Rendered as an outline swatch — used for "adds no independent observation". */
  hollow?: boolean
}

export interface ChartLegendProps {
  items: readonly ChartLegendItem[]
  label?: string
  className?: string
}

export function ChartLegend({ items, label = 'Leyenda', className }: ChartLegendProps) {
  return (
    <ul aria-label={label} className={clsx('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
      {items.map((item) => (
        <li key={item.id} className="flex items-center gap-1.5 text-caption text-ink-secondary">
          {item.icon ? (
            <span aria-hidden="true" className="text-[0.7em] leading-none" style={{ color: item.color }}>
              {item.icon}
            </span>
          ) : (
            <span
              aria-hidden="true"
              className={clsx('h-2.5 w-2.5 shrink-0 rounded-[2px]', item.hollow && 'border')}
              style={
                item.hollow
                  ? { borderColor: item.color, backgroundColor: 'transparent' }
                  : { backgroundColor: item.color }
              }
            />
          )}
          <span className="text-ink-primary">{item.label}</span>
          {item.note ? <span className="text-ink-muted">· {item.note}</span> : null}
        </li>
      ))}
    </ul>
  )
}

/* ------------------------------------------------------------------ *
 * Notices
 * ------------------------------------------------------------------ */

export interface ChartNoticeProps {
  /** Short leading word, e.g. "Qué mide" or "Importante". */
  term?: string
  children: ReactNode
  className?: string
}

export function ChartNotice({ term, children, className }: ChartNoticeProps) {
  return (
    <p
      className={clsx(
        'max-w-prose border-l-2 border-line-strong pl-3 text-caption text-ink-secondary',
        className,
      )}
    >
      {term ? (
        <span className="mr-1.5 text-micro font-semibold uppercase tracking-wide text-ink-primary">
          {term}
        </span>
      ) : null}
      {children}
    </p>
  )
}

/* ------------------------------------------------------------------ *
 * Inspector — where an opened score lives
 * ------------------------------------------------------------------ */

export interface InspectorPanelProps {
  id: string
  title: string
  /** Plain-language justification the reader can argue with. */
  rationale?: ReactNode
  children: ReactNode
  className?: string
}

export function InspectorPanel({ id, title, rationale, children, className }: InspectorPanelProps) {
  return (
    <section
      id={id}
      aria-label={title}
      className={clsx(
        'animate-fade-up rounded-data border border-line-hairline bg-surface-sunken p-4',
        className,
      )}
    >
      <h4 className="text-micro font-semibold uppercase tracking-wide text-ink-secondary">
        {title}
      </h4>
      {rationale ? (
        <p className="mt-2 max-w-prose text-caption text-ink-secondary">{rationale}</p>
      ) : null}
      <div className="mt-4 flex flex-col gap-5">{children}</div>
    </section>
  )
}

/* ------------------------------------------------------------------ *
 * Evidence references
 * ------------------------------------------------------------------ */

export interface EvidenceRefsProps {
  refs?: readonly AlephId[]
  label?: string
  onSelect?: (id: AlephId) => void
  className?: string
}

export function EvidenceRefs({
  refs,
  label = 'Evidencia usada',
  onSelect,
  className,
}: EvidenceRefsProps) {
  if (!refs || refs.length === 0) {
    return (
      <p className={clsx('text-micro text-ink-muted', className)}>
        Sin referencias de evidencia asociadas — trátese como no verificado.
      </p>
    )
  }
  return (
    <div className={clsx('flex flex-wrap items-baseline gap-1.5', className)}>
      <span className="text-micro uppercase tracking-wide text-ink-muted">{label}</span>
      {refs.map((ref) =>
        onSelect ? (
          <button
            key={ref}
            type="button"
            onClick={() => onSelect(ref)}
            className="rounded-[2px] border border-line-hairline px-1.5 py-0.5 font-mono text-micro text-ink-secondary transition-colors duration-200 ease-subtle hover:border-line-strong hover:text-ink-primary"
          >
            {ref}
          </button>
        ) : (
          <span
            key={ref}
            className="rounded-[2px] border border-line-hairline px-1.5 py-0.5 font-mono text-micro text-ink-secondary"
          >
            {ref}
          </span>
        ),
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * Component breakdown — the calculation, opened
 * ------------------------------------------------------------------ */

export interface ComponentBreakdownProps {
  components: readonly Component[]
  /** The headline number these components add up to. Enables the arithmetic check. */
  score?: number
  /** Heading for components with a negative weight. */
  negativeHeading?: string
  /** Heading for components with a positive weight. */
  positiveHeading?: string
  /** Words for the arithmetic line, e.g. "puntaje del eje". */
  scoreLabel?: string
  onSelectEvidence?: (id: AlephId) => void
  className?: string
}

export function ComponentBreakdown({
  components,
  score,
  negativeHeading = 'Restan',
  positiveHeading = 'Suman',
  scoreLabel = 'puntaje',
  onSelectEvidence,
  className,
}: ComponentBreakdownProps) {
  const negative = components.filter((c) => c.weight < 0)
  const positive = components.filter((c) => c.weight >= 0)
  const sum = components.reduce((acc, c) => acc + c.weight, 0)
  // Which side of the net result argues the other way. This is the counter-evidence.
  const counterSign = typeof score === 'number' ? (score < 0 ? 1 : -1) : 0

  if (components.length === 0) {
    return (
      <p className={clsx('text-caption text-ink-secondary', className)}>
        Este puntaje no trae componentes. Sin ellos el número no es inspeccionable y no debería
        usarse.
      </p>
    )
  }

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      <div className="grid gap-4 md:grid-cols-2">
        {[
          { key: 'neg', heading: negativeHeading, list: negative, sign: -1 },
          { key: 'pos', heading: positiveHeading, list: positive, sign: 1 },
        ].map((group) => (
          <div key={group.key}>
            <h5 className="flex items-baseline gap-2 text-micro font-semibold uppercase tracking-wide text-ink-secondary">
              {group.heading}
              {counterSign === group.sign && group.list.length > 0 ? (
                <span className="rounded-[2px] border border-line-strong px-1 py-px text-micro font-normal normal-case tracking-normal text-ink-primary">
                  contra-evidencia
                </span>
              ) : null}
            </h5>
            {group.list.length === 0 ? (
              <p className="mt-2 text-caption text-ink-muted">Ninguno.</p>
            ) : (
              <ul className="mt-2 flex flex-col divide-y divide-line-hairline">
                {group.list.map((component, index) => (
                  <li key={`${component.label}-${index}`} className="py-2.5 first:pt-0 last:pb-0">
                    <div className="flex items-baseline gap-2">
                      <span
                        aria-hidden="true"
                        className="mt-1 h-2 w-2 shrink-0 rounded-[2px]"
                        style={{ backgroundColor: divergingColor(component.weight) }}
                      />
                      <span className="tabular shrink-0 text-caption font-semibold text-ink-primary">
                        {formatScore(component.weight, { digits: 1 })}
                      </span>
                      <span className="text-caption text-ink-primary">{component.label}</span>
                    </div>
                    {component.note ? (
                      <p className="mt-1 pl-4 text-caption text-ink-secondary">{component.note}</p>
                    ) : null}
                    <EvidenceRefs
                      refs={component.evidence_refs}
                      onSelect={onSelectEvidence}
                      className="mt-1.5 pl-4"
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      <div className="border-t border-line-hairline pt-3">
        <p className="text-micro uppercase tracking-wide text-ink-muted">Cálculo</p>
        <p className="tabular mt-1 break-words text-caption text-ink-primary">
          {components.map((c) => formatScore(c.weight, { digits: 1 })).join('  ')}
          {'  =  '}
          {formatNumber(sum, { digits: 1 })}
        </p>
        {typeof score === 'number' ? (
          <p className="mt-1 text-caption text-ink-secondary">
            {Math.abs(sum - score) <= 0.5 ? (
              <>
                La suma de los componentes reproduce el {scoreLabel}:{' '}
                <span className="tabular font-semibold text-ink-primary">
                  {formatNumber(score, { digits: 1 })}
                </span>
                .
              </>
            ) : (
              <>
                La suma de los componentes ({formatNumber(sum, { digits: 1 })}) no coincide con el{' '}
                {scoreLabel} publicado ({formatNumber(score, { digits: 1 })}): hay una normalización
                posterior que este desglose no muestra.
              </>
            )}
          </p>
        ) : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * Hover tooltip
 *
 * CSS-driven so it also opens on keyboard focus. Do NOT place inside a
 * container with `overflow-x-auto`: the browser clips the vertical axis too.
 * Wide charts use SVG <title> instead.
 * ------------------------------------------------------------------ */

export interface ChartTooltipProps {
  label: ReactNode
  children: ReactNode
  className?: string
}

export function ChartTooltip({ label, children, className }: ChartTooltipProps) {
  return (
    <span className={clsx('group/tip relative block', className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 hidden w-max max-w-[16rem] -translate-x-1/2 rounded-data border border-line-hairline bg-surface-raised px-2.5 py-1.5 text-left text-caption leading-snug text-ink-primary shadow-sm group-hover/tip:block group-focus-within/tip:block"
      >
        {label}
      </span>
    </span>
  )
}

/* ------------------------------------------------------------------ *
 * Uncertainty list
 * ------------------------------------------------------------------ */

export interface UncertaintyListProps {
  items?: readonly { statement: string; kind: string; resolvable_by?: string | null }[]
  title?: string
  className?: string
}

export function UncertaintyList({
  items,
  title = 'Qué queda sin resolver',
  className,
}: UncertaintyListProps) {
  if (!items || items.length === 0) return null
  return (
    <div className={className}>
      <h5 className="text-micro font-semibold uppercase tracking-wide text-ink-secondary">
        {title}
      </h5>
      <ul className="mt-2 flex flex-col gap-2">
        {items.map((item, index) => (
          <li key={`${item.kind}-${index}`} className="max-w-prose text-caption text-ink-secondary">
            <span aria-hidden="true" className="mr-1.5 text-ink-muted">
              ◇
            </span>
            {item.statement}
            {item.resolvable_by ? (
              <span className="text-ink-muted"> Se resolvería con: {item.resolvable_by}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

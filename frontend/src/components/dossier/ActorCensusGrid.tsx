import { useMemo, useState } from 'react'
import { useLanguage } from '@/i18n/LanguageContext'
import { dataUrl } from '@/lib/data'
import type { ActorProfile, CapturedSource, CensusActor } from '@/types/megareforma'

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '·'
  const first = words[0] ?? ''
  if (words.length === 1) return first.slice(0, 2).toUpperCase()
  return `${first[0] ?? ''}${words.at(-1)?.[0] ?? ''}`.toUpperCase()
}

function affiliationLabel(actor: CensusActor, tr: (es: string, en: string) => string): string {
  if (actor.affiliation_status === 'institutional_not_applicable') return ''
  if (actor.affiliation_status === 'not_documented') {
    return tr('Afiliación no documentada', 'Affiliation not documented')
  }
  return actor.affiliation
}

export default function ActorCensusGrid({
  actors,
  profiles,
  sourceById,
}: {
  actors: CensusActor[]
  profiles: Map<string, ActorProfile>
  sourceById: Map<string, CapturedSource>
}) {
  const { tr } = useLanguage()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = useMemo(
    () => actors.find((actor) => actor.id === selectedId) ?? null,
    [actors, selectedId],
  )
  const selectedProfile = selected ? profiles.get(selected.id) : undefined
  const legalRecords = selectedProfile?.legal_record ?? selected?.legal_record ?? []
  const audit = selectedProfile?.official_record_audit ?? selected?.official_record_audit

  return (
    <div className="border-t border-line-hairline p-4 sm:p-5">
      <div className="flex flex-wrap gap-x-3 gap-y-4" role="list">
        {actors.map((actor) => {
          const profile = profiles.get(actor.id)
          const hasPersonalRecord = (profile?.legal_record.length ?? actor.legal_record?.length ?? 0) > 0
          const image = actor.image || profile?.image
          const active = actor.id === selectedId
          return (
            <button
              key={`${actor.entity_kind}-${actor.id}`}
              type="button"
              role="listitem"
              aria-pressed={active}
              aria-label={`${actor.name}${hasPersonalRecord ? ` · ${tr('antecedente personal documentado', 'documented personal record')}` : ''}`}
              onClick={() => setSelectedId(active ? null : actor.id)}
              className="group flex w-[4.6rem] flex-col items-center gap-1.5 text-center"
            >
              <span
                className={`relative grid h-12 w-12 place-items-center overflow-visible rounded-full border text-micro font-semibold tracking-wide transition ${
                  active
                    ? 'border-ink-primary bg-ink-primary text-surface-page ring-2 ring-line-strong ring-offset-2 ring-offset-surface-card'
                    : 'border-line-strong bg-surface-raised text-ink-secondary group-hover:border-ink-primary group-hover:text-ink-primary'
                }`}
              >
                {image ? (
                  <img
                    src={dataUrl(image)}
                    alt=""
                    className="h-full w-full rounded-full object-cover object-top grayscale transition group-hover:grayscale-0"
                    loading="lazy"
                  />
                ) : (
                  initials(actor.name)
                )}
                {hasPersonalRecord && (
                  <span
                    className="absolute right-[-0.1rem] top-[-0.1rem] h-2.5 w-2.5 rounded-full border-2 border-surface-card bg-status-critical"
                    aria-hidden="true"
                  />
                )}
              </span>
              <span className="line-clamp-2 text-[0.65rem] leading-tight text-ink-secondary group-hover:text-ink-primary">
                {actor.name}
              </span>
            </button>
          )
        })}
      </div>

      {selected && (
        <article className="mt-5 border-t border-line-hairline pt-5" aria-live="polite">
          <div className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-body font-semibold text-ink-primary">{selected.name}</h3>
                {legalRecords.length > 0 && (
                  <span className="inline-flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wide text-status-critical">
                    <span className="h-2 w-2 rounded-full bg-status-critical" aria-hidden="true" />
                    {tr('registro personal', 'personal record')}
                  </span>
                )}
              </div>
              <p className="mt-1 text-caption text-ink-secondary">
                {[selected.role, selected.institution, affiliationLabel(selected, tr)].filter(Boolean).join(' · ') ||
                  tr('Institución citada en el corpus', 'Institution cited in the corpus')}
              </p>
              <p className="mt-3 max-w-3xl text-caption text-ink-primary">{selected.participation_summary}</p>
            </div>
            <button
              type="button"
              onClick={() => setSelectedId(null)}
              className="shrink-0 text-micro uppercase tracking-wide text-ink-muted hover:text-ink-primary"
              aria-label={tr('Cerrar ficha', 'Close profile')}
            >
              ×
            </button>
          </div>

          {legalRecords.map((record) => (
            <div
              key={record.source.id}
              className="mt-4 max-w-3xl border-l-2 border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] p-3 text-caption text-ink-secondary"
            >
              <p className="font-semibold uppercase tracking-wide text-status-critical">
                {tr('Antecedente judicial oficial', 'Official legal record')}
              </p>
              <p className="mt-2">{record.summary}</p>
              {record.presumption_note && <p className="mt-2 font-semibold text-ink-primary">{record.presumption_note}</p>}
              <a
                href={record.source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-block font-semibold underline underline-offset-2"
              >
                {tr('Abrir fuente oficial', 'Open official source')} ↗
              </a>
            </div>
          ))}

          <p className="mt-4 max-w-3xl text-micro text-ink-muted">
            {audit
              ? `${tr('Barrido nominal de registros oficiales', 'Name-based official-register sweep')} · ${audit.checked_at}. ${audit.caveat}`
              : tr(
                  'Revisión oficial pendiente. La ausencia de punto rojo no significa ausencia de antecedentes.',
                  'Official review pending. No red dot does not mean that no record exists.',
                )}
          </p>

          <details className="mt-4 max-w-3xl">
            <summary className="cursor-pointer text-caption font-semibold text-ink-primary">
              {selected.source_ids.length}{' '}
              {selected.source_ids.length === 1 ? tr('fuente', 'source') : tr('fuentes', 'sources')} ·{' '}
              {tr('ver evidencia', 'view evidence')}
            </summary>
            <div className="mt-3 space-y-3">
              {selected.mentions.map((mention, index) => {
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
      )}
    </div>
  )
}
